"""LLM fallback for voice intents the rule layer cannot place.

Rules stay first (fast, deterministic, and safety-critical for stop/yes-no).
This module is consulted only for utterances that match nothing, and it is a
*proposal* engine: the LLM returns a strict JSON command, then deterministic
code validates it — fields must be known editable keys, values go through the
same sanitizers the rule layer uses, and callers gate on confidence.
LLM proposes, deterministic code disposes.

Providers (VOICE_LLM_PROVIDER): "gemini" (default) or "evon" — Gnani Evon v3.3
served over an OpenAI-compatible /v1/chat/completions endpoint (vLLM, SGLang,
FriendliAI or the Gnani API beta), thinking mode disabled.

Test knobs:
    VOICE_INTENT_FAKE_JSON   — canned response text, skips the API (offline tests)
    VOICE_INTENT_DISABLED=1  — fallback always returns None (deterministic suites)
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

import httpx

from app import config, events
from app.agent import readback

INTENT_TIMEOUT_S = 4.0  # bounded: a slow LLM must never stall a voice turn
INTENT_MAX_TOKENS = 300  # a verdict is a short JSON object

# Editable profile keys: secrets and credentials are never voice-editable.
EDITABLE_FIELDS = [
    "full_name", "phone", "email", "dob", "gender", "college", "course",
    "year", "marks", "address", "city", "district", "state", "pin",
]

ACTIONS = ("edit", "start_task", "cancel", "unclear")

FAKE_ENV = "VOICE_INTENT_FAKE_JSON"
DISABLED_ENV = "VOICE_INTENT_DISABLED"

OPTION_FIELDS: dict[str, list[str]] = {
    "gender": ["Male", "Female", "Other"],
    "state": [name for name in readback.OPTION_ALIASES if name in ("Andhra Pradesh", "Telangana")],
    "district": readback.DISTRICT_OPTIONS,
}


@dataclass
class Edit:
    field: str
    value: str | None = None


@dataclass
class Intent:
    action: str
    edits: list[Edit] = field(default_factory=list)
    confidence: float = 0.0


def _schema() -> dict:
    return {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": list(ACTIONS)},
            "edits": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "field": {"type": "STRING", "enum": EDITABLE_FIELDS},
                        "value": {"type": "STRING"},
                    },
                    "required": ["field"],
                },
            },
            "confidence": {"type": "NUMBER"},
        },
        "required": ["action", "confidence"],
    }


def _instructions() -> str:
    return (
        "You are the intent parser for a voice assistant that fills a scholarship application. "
        "The user speaks Telugu, English, or a mix. Classify the utterance as one action:\n"
        '- "edit": the user wants to change one or more form values. Put each change in edits with '
        'the field name and the NEW value if spoken (if no new value is given, omit "value").\n'
        '- "start_task": the user asks to start or continue the application.\n'
        '- "cancel": the user asks to stop the current work.\n'
        '- "unclear": anything else (questions, small talk, noise).\n'
        "Rules: values must be short form values, never sentences. Keep the value in the script the "
        "user spoke (Telugu stays in Telugu script). If old and new values are both "
        "spoken, return only the new value. Never invent fields outside the list.\n"
        'Reply with a single JSON object only: {"action": "edit|start_task|cancel|unclear", '
        '"edits": [{"field": "...", "value": "..."}], "confidence": 0.0}'
    )


def _context(transcript: str, current_values: dict) -> str:
    known = {key: current_values.get(key, "") for key in EDITABLE_FIELDS if current_values.get(key)}
    return f"Utterance: \"{transcript}\"\nCurrent values: {json.dumps(known, ensure_ascii=False)}"


def _prompt(transcript: str, current_values: dict) -> str:
    return f"{_instructions()}\n\n{_context(transcript, current_values)}"


def _provider() -> str:
    """Resolve the configured provider ("gemini" when unknown)."""
    provider = (config.VOICE_LLM_PROVIDER or "gemini").strip().lower()
    return "evon" if provider in ("evon", "openai", "openai-compatible", "vllm") else "gemini"


def _api_key() -> str:
    return config.EVON_API_KEY if _provider() == "evon" else config.GEMINI_API_KEY


def _model() -> str:
    return config.EVON_MODEL if _provider() == "evon" else config.GEMINI_MODEL


def _openai_payloads(transcript: str, current_values: dict) -> list[dict]:
    """Payload variants for an OpenAI-compatible server; the second is the retry.

    Hosts differ: some reject `chat_template_kwargs` (Evon's thinking switch) or
    a `system` role, so we retry once with everything merged into one user turn.
    """
    base = {
        "model": config.EVON_MODEL,
        "temperature": 0.2,  # near-greedy: classification, not chat
        "top_p": 0.95,
        "max_tokens": INTENT_MAX_TOKENS,
        "stream": False,
    }
    full = {
        **base,
        "messages": [
            {"role": "system", "content": _instructions()},
            {"role": "user", "content": _context(transcript, current_values)},
        ],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    merged = {
        **base,
        "messages": [{"role": "user", "content": _prompt(transcript, current_values)}],
    }
    return [full, merged]


async def _request_gemini(prompt: str, schema: dict, timeout_s: float) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "responseSchema": schema,
        },
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(url, headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body)
        if response.status_code == 400:
            # some API versions reject responseSchema; retry with plain JSON mode
            body["generationConfig"].pop("responseSchema", None)
            response = await client.post(url, headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body)
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _request_openai_compat(payloads: list[dict], timeout_s: float) -> str:
    """Evon v3.3 (or any OpenAI-compatible server) over /v1/chat/completions."""
    url = f"{config.EVON_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {config.EVON_API_KEY}"}
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(url, headers=headers, json=payloads[0])
        if response.status_code == 400 and len(payloads) > 1:
            response = await client.post(url, headers=headers, json=payloads[1])
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


async def _request(transcript: str, current_values: dict, timeout_s: float) -> str:
    """Provider seam; tests monkeypatch this. Returns the raw JSON text."""
    if _provider() == "evon":
        return await _request_openai_compat(_openai_payloads(transcript, current_values), timeout_s)
    return await _request_gemini(_prompt(transcript, current_values), _schema(), timeout_s)


async def complete_json(prompt: str, schema: dict, timeout_s: float = INTENT_TIMEOUT_S) -> dict | None:
    """One-shot JSON completion on the configured provider; None when unavailable or invalid.

    Shared by other voice parsers (e.g. app/agent/answers.py) so there is one provider seam.
    """
    if os.environ.get(DISABLED_ENV) or not _api_key():
        return None
    if _provider() == "evon":
        base = {
            "model": config.EVON_MODEL,
            "temperature": 0.0,
            "max_tokens": INTENT_MAX_TOKENS,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }
        payloads = [{**base, "chat_template_kwargs": {"enable_thinking": False}}, base]
        raw = await _request_openai_compat(payloads, timeout_s)
    else:
        raw = await _request_gemini(prompt, schema, timeout_s)
    return _loads_jsonish(raw)


def _loads_jsonish(raw: object) -> dict | None:
    """Parse JSON, tolerating markdown fences or surrounding prose."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_value(field_name: str, value: str | None) -> str | None:
    """Run a proposed value through the same sanitizers the rule layer uses."""
    if not value or not str(value).strip():
        return None
    if field_name in OPTION_FIELDS:
        return readback.match_option(str(value), OPTION_FIELDS[field_name]) or readback.clean_text_value(str(value))
    if field_name in ("full_name", "phone", "pin", "address", "college", "email"):
        return readback.extract_field_value(field_name, str(value))
    return readback.clean_text_value(str(value))


def _validate(parsed: object) -> Intent | None:
    """Shape the model output into an Intent; drop anything off-schema."""
    if not isinstance(parsed, dict):
        return None
    action = parsed.get("action")
    if action not in ACTIONS:
        return None
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    edits: list[Edit] = []
    for item in parsed.get("edits") or []:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field") or "")
        if field_name not in EDITABLE_FIELDS:
            continue  # hallucinated field: never reaches the portal
        edits.append(Edit(field_name, _normalize_value(field_name, item.get("value"))))
    if action == "edit" and not edits:
        action = "unclear"
    return Intent(action=action, edits=edits, confidence=confidence)


async def parse_intent(
    transcript: str,
    *,
    trace_id: str,
    current_values: dict | None = None,
    timeout_s: float = INTENT_TIMEOUT_S,
) -> Intent | None:
    """Ask Gemini to place an utterance the rules could not; None means "no verdict"."""
    if os.environ.get(DISABLED_ENV):
        return None
    if not transcript.strip():
        return None

    fake = os.environ.get(FAKE_ENV)
    started = time.perf_counter()
    provider = _provider()
    source = "fake" if fake else provider
    if fake:
        raw = fake
    else:
        if not _api_key():
            return None
        try:
            raw = await _request(transcript, current_values or {}, timeout_s)
        except Exception as exc:  # noqa: BLE001 — fallback must never break the run
            events.log_event(
                trace_id, "voice.llm_error", transcript=transcript, error=f"{type(exc).__name__}: {exc}"
            )
            return None
    latency_ms = round((time.perf_counter() - started) * 1000, 1)

    parsed = _loads_jsonish(raw)
    if parsed is None:
        events.log_event(trace_id, "voice.llm_error", transcript=transcript, error="invalid JSON", raw=str(raw)[:200])
        return None
    intent = _validate(parsed)
    if intent is None:
        events.log_event(trace_id, "voice.llm_error", transcript=transcript, error="off-schema", raw=str(raw)[:200])
        return None
    events.log_event(
        trace_id,
        "voice.llm_intent",
        transcript=transcript,
        action=intent.action,
        edits=[[edit.field, edit.value] for edit in intent.edits],
        confidence=intent.confidence,
        latency_ms=latency_ms,
        source=source,
        model=_model(),
    )
    return intent
