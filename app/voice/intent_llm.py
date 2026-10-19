"""LLM fallback for voice intents the rule layer cannot place.

Rules stay first (fast, deterministic, and safety-critical for stop/yes-no).
This module is consulted only for utterances that match nothing, and it is a
*proposal* engine: the LLM returns a strict JSON command, then deterministic
code validates it — fields must be known editable keys, values go through the
same sanitizers the rule layer uses, and callers gate on confidence.
LLM proposes, deterministic code disposes.

Model: Gnani Evon v3.3 over an OpenAI-compatible /v1/chat/completions endpoint
(Gnani API beta, a FriendliAI dedicated endpoint, or self-hosted vLLM/SGLang),
thinking mode disabled. Configure EVON_BASE_URL, EVON_API_KEY, EVON_MODEL.
Until Evon access is granted, Gemini (GEMINI_API_KEY) stands in automatically;
with neither configured the LLM layer is off and the rules work alone.

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
from app.agent import fields

INTENT_TIMEOUT_S = 4.0  # bounded: a slow LLM must never stall a voice turn
INTENT_MAX_TOKENS = 300  # a verdict is a short JSON object

# Editable profile keys: secrets and credentials are never voice-editable.
EDITABLE_FIELDS = fields.PROFILE_KEYS

ACTIONS = ("edit", "start_task", "cancel", "unclear")

FAKE_ENV = "VOICE_INTENT_FAKE_JSON"
DISABLED_ENV = "VOICE_INTENT_DISABLED"

@dataclass
class Edit:
    field: str
    value: str | None = None


@dataclass
class Intent:
    action: str
    edits: list[Edit] = field(default_factory=list)
    confidence: float = 0.0


def _instructions() -> str:
    return (
        "You are the intent parser for a voice assistant that fills a scholarship application. "
        "The user speaks any Indian language, English, or a mix. Classify the utterance as one action:\n"
        '- "edit": the user wants to change one or more form values. Put each change in edits with '
        'the field name and the NEW value if spoken (if no new value is given, omit "value").\n'
        '- "start_task": the user asks to start or continue the application.\n'
        '- "cancel": the user asks to stop the current work.\n'
        '- "unclear": anything else (questions, small talk, noise).\n'
        "Rules: values must be short form values, never sentences. Write names, places and other "
        "text in English (Latin) letters, transliterating from any script. If old and new values are both "
        "spoken, return only the new value. Never invent fields outside the list.\n"
        'Reply with a single JSON object only: {"action": "edit|start_task|cancel|unclear", '
        '"edits": [{"field": "...", "value": "..."}], "confidence": 0.0}'
    )


def _context(transcript: str, current_values: dict) -> str:
    known = {key: current_values.get(key, "") for key in EDITABLE_FIELDS if current_values.get(key)}
    return f"Utterance: \"{transcript}\"\nCurrent values: {json.dumps(known, ensure_ascii=False)}"


def _prompt(transcript: str, current_values: dict) -> str:
    return f"{_instructions()}\n\n{_context(transcript, current_values)}"


def _provider() -> str | None:
    """Evon when configured; Gemini as the stand-in until Evon access; None = rules only."""
    if config.EVON_BASE_URL and config.EVON_API_KEY:
        return "evon"
    if config.GEMINI_API_KEY:
        return "gemini"
    return None


def _configured() -> bool:
    return _provider() is not None


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


_PREFERRED_PAYLOAD_REJECTED = False  # host said 400 to the first variant once: go straight to the retry


async def _request_openai_compat(payloads: list[dict], timeout_s: float) -> str:
    """Evon v3.3 (or any OpenAI-compatible server) over /v1/chat/completions."""
    global _PREFERRED_PAYLOAD_REJECTED
    url = f"{config.EVON_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {config.EVON_API_KEY}"}
    if _PREFERRED_PAYLOAD_REJECTED and len(payloads) > 1:
        payloads = payloads[1:]
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(url, headers=headers, json=payloads[0])
        if response.status_code == 400 and len(payloads) > 1:
            _PREFERRED_PAYLOAD_REJECTED = True
            response = await client.post(url, headers=headers, json=payloads[1])
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


async def _request_gemini(prompt: str, timeout_s: float) -> str:
    """Gemini generateContent in JSON mode (the stand-in provider)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(url, headers={"x-goog-api-key": config.GEMINI_API_KEY}, json=body)
    response.raise_for_status()
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _request(transcript: str, current_values: dict, timeout_s: float) -> str:
    """Intent call (tests monkeypatch this). Returns the raw model text."""
    if _provider() == "gemini":
        return await _request_gemini(_prompt(transcript, current_values), timeout_s)
    return await _request_openai_compat(_openai_payloads(transcript, current_values), timeout_s)


async def complete_json(prompt: str, timeout_s: float = INTENT_TIMEOUT_S) -> dict | None:
    """One-shot JSON completion (Evon, or the Gemini stand-in); None when off or invalid.

    Shared by other voice parsers (e.g. app/agent/answers.py) so there is one model seam.
    """
    if os.environ.get(DISABLED_ENV) or not _configured():
        return None
    if _provider() == "gemini":
        return _loads_jsonish(await _request_gemini(prompt, timeout_s))
    base = {
        "model": config.EVON_MODEL,
        "temperature": 0.0,
        "max_tokens": INTENT_MAX_TOKENS,
        "stream": False,
        "messages": [{"role": "user", "content": prompt}],
    }
    payloads = [{**base, "chat_template_kwargs": {"enable_thinking": False}}, base]
    return _loads_jsonish(await _request_openai_compat(payloads, timeout_s))


def _loads_jsonish(raw: object) -> dict | None:
    """Parse JSON, tolerating markdown fences or surrounding prose."""
    if not isinstance(raw, str):
        return None
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()  # reasoning models may think aloud
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
        value = str(item.get("value") or "").strip() or None
        edits.append(Edit(field_name, value))  # the caller checks it against the field's rules
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
    """Ask the LLM to place an utterance the rules could not; None means "no verdict"."""
    if os.environ.get(DISABLED_ENV):
        return None
    if not transcript.strip():
        return None

    fake = os.environ.get(FAKE_ENV)
    started = time.perf_counter()
    source = "fake" if fake else _provider()
    if fake:
        raw = fake
    else:
        if not _configured():
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
