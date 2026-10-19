#!/usr/bin/env python3
"""Offline checks for the LLM intent fallback (no network needed).

Covers the strict-schema validation: hallucinated fields are dropped, proposed
values run through the rule-layer sanitizers, confidence is clamped, bad output
degrades to None, and the test knobs (fake JSON / disabled) work.

Run:
    .venv/bin/python scripts/voice_intent_check.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import config, events
from app.agent import answers
from app.agent.voice_ux import VoiceAgent
from app.voice import intent_llm

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def main() -> int:
    # keep test events out of the real task log
    events.EVENTS_FILE = Path(tempfile.mkdtemp()) / "events.jsonl"
    # a dummy endpoint so the (faked) model counts as configured; nothing goes over the network
    config.EVON_BASE_URL, config.EVON_API_KEY = "http://evon.test/v1", "test-key"
    saved_request = intent_llm._request  # the real provider dispatcher

    async def parse(payload: object) -> intent_llm.Intent | None:
        async def fake_request(_transcript: str, _values: dict, _timeout: float) -> str:
            return payload if isinstance(payload, str) else json.dumps(payload)

        intent_llm._request = fake_request
        return await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)

    intent = await parse(
        {"action": "edit", "edits": [{"field": "full_name", "value": "నిహారిక"}], "confidence": 0.93}
    )
    check(
        "valid edit parsed",
        intent is not None and intent.action == "edit" and intent.edits[0].field == "full_name" and intent.edits[0].value == "నిహారిక",
        repr(intent),
    )

    intent = await parse({"action": "edit", "edits": [{"field": "password", "value": "hunter2"}], "confidence": 0.99})
    check("hallucinated/secret field dropped", intent is not None and intent.action == "unclear", repr(intent))

    # Proposed values are checked against the field's rules by the session's VoiceAgent
    # (rules only here: the model call inside value_for is stubbed out).
    async def no_llm(_spec, _utterance):
        return None

    answers._llm_extract = no_llm
    voice = VoiceAgent(say=lambda _m: None, ask=None, language="te-IN")
    voice.note_field({"label": "District", "tag": "select", "type": "", "constraints": {}},
                     ["Guntur", "Krishna", "Kurnool", "Hyderabad"])

    intent = await parse({"action": "edit", "edits": [{"field": "full_name", "value": "x"}], "confidence": 1.5})
    check("confidence clamped", intent is not None and intent.confidence == 1.0, repr(intent))
    check("short junk value rejected by the field", await voice.value_for("full_name", "x") is None)
    check("instruction sentence value rejected",
          await voice.value_for("full_name", "నిహారిక రవికుమార్ అని తీసేసి నిహారిక") is None)
    check("district value matched to the page option", await voice.value_for("district", "గుంటూరు") == "Guntur")
    check("phone digits normalized",
          await voice.value_for("phone", "నైన్ ఎయిట్ ఏడు ఆరు ఐదు నాలుగు మూడు రెండు ఒకటి సున్నా") == "9876543210")

    intent = await parse({"action": "nonsense", "confidence": 0.9})
    check("unknown action rejected", intent is None, repr(intent))

    intent = await parse("this is not json")
    check("invalid JSON degrades to None", intent is None, repr(intent))

    async def broken_request(_prompt: str, _schema: dict, _timeout: float) -> str:
        raise RuntimeError("network down")

    intent_llm._request = broken_request
    intent = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
    check("transport failure degrades to None", intent is None, repr(intent))

    os.environ[intent_llm.FAKE_ENV] = json.dumps(
        {"action": "cancel", "confidence": 0.95}
    )
    intent = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
    check("fake mode works without the API", intent is not None and intent.action == "cancel", repr(intent))
    del os.environ[intent_llm.FAKE_ENV]

    os.environ[intent_llm.DISABLED_ENV] = "1"
    intent = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
    check("disabled mode returns None", intent is None, repr(intent))
    del os.environ[intent_llm.DISABLED_ENV]

    check("editable fields exclude secrets", "password" not in intent_llm.EDITABLE_FIELDS and "otp" not in intent_llm.EDITABLE_FIELDS)

    # ---- model seam: Gnani Evon (OpenAI-compatible)

    payloads = intent_llm._openai_payloads("నా పేరు నిహారిక", {"full_name": "Ravi Kumar"})
    primary, retry = payloads[0], payloads[1]
    check(
        "evon payload: thinking off, token cap, near-greedy",
        primary.get("chat_template_kwargs") == {"enable_thinking": False}
        and primary.get("max_tokens") == intent_llm.INTENT_MAX_TOKENS
        and float(primary.get("temperature", 1)) <= 0.2
        and primary.get("model") == config.EVON_MODEL,
        json.dumps({k: v for k, v in primary.items() if k != "messages"}, ensure_ascii=False),
    )
    check(
        "evon payload: system + user roles",
        [m["role"] for m in primary["messages"]] == ["system", "user"]
        and "Utterance" in primary["messages"][1]["content"],
        str([m["role"] for m in primary["messages"]]),
    )
    check(
        "evon retry: merged user turn, no thinking kwarg",
        [m["role"] for m in retry["messages"]] == ["user"]
        and "chat_template_kwargs" not in retry
        and "Utterance" in retry["messages"][0]["content"],
        str([m["role"] for m in retry["messages"]]),
    )

    calls: list[list] = []

    async def fake_evon(payloads: list, _timeout: float) -> str:
        calls.append(payloads)
        return '<think>{"maybe": 1}</think>{"action": "cancel", "confidence": 0.9}'

    real_evon = intent_llm._request_openai_compat
    intent_llm._request_openai_compat = fake_evon
    intent_llm._request = saved_request  # undo the parse() helper's monkeypatch
    gemini_calls: list[str] = []

    async def fake_gemini(prompt: str, _timeout: float) -> str:
        gemini_calls.append(prompt)
        return '{"action": "cancel", "confidence": 0.9}'

    real_gemini = intent_llm._request_gemini
    intent_llm._request_gemini = fake_gemini
    saved = (config.EVON_BASE_URL, config.EVON_API_KEY, config.GEMINI_API_KEY)
    try:
        config.EVON_BASE_URL, config.EVON_API_KEY, config.GEMINI_API_KEY = "", "", ""
        off = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
        off_json = await intent_llm.complete_json("x", 0.1)
        check("nothing configured -> LLM layer off", off is None and off_json is None and not calls, str(len(calls)))
        config.GEMINI_API_KEY = "gemini-test-key"
        stand_in = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
        stand_in_json = await intent_llm.complete_json("x", 0.1)
        check("no Evon -> Gemini stands in", stand_in is not None and stand_in_json is not None
              and len(gemini_calls) == 2 and not calls, f"{len(gemini_calls)} gemini, {len(calls)} evon")
        config.EVON_BASE_URL, config.EVON_API_KEY = "http://evon.test/v1", "test-key"
        intent = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
        check("Evon configured -> Evon preferred over Gemini, <think> text ignored",
              intent is not None and intent.action == "cancel" and len(gemini_calls) == 2, repr(intent))
        data = await intent_llm.complete_json("prompt", 0.1)
        last = calls[-1]
        check(
            "complete_json: thinking off first, plain retry second",
            data == {"action": "cancel", "confidence": 0.9}
            and last[0].get("chat_template_kwargs") == {"enable_thinking": False}
            and "chat_template_kwargs" not in last[1],
            json.dumps(data),
        )
    finally:
        intent_llm._request_openai_compat = real_evon
        intent_llm._request_gemini = real_gemini
        config.EVON_BASE_URL, config.EVON_API_KEY, config.GEMINI_API_KEY = saved

    fenced = ('```json\n{"action": "edit", "edits": [{"field": "full_name", "value": "నిహారిక"}], '
              '"confidence": 0.8}\n```')
    intent = await parse(fenced)
    check("markdown-fenced JSON salvaged", intent is not None and intent.action == "edit", repr(intent))
    intent = await parse('Sure! Here is the JSON:\n{"action": "unclear", "confidence": 0.5}\nHope that helps.')
    check("prose-wrapped JSON salvaged", intent is not None and intent.action == "unclear", repr(intent))
    check("non-JSON text still rejected", intent_llm._loads_jsonish("not json at all") is None)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} intent checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
