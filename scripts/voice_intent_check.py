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

from app import events
from app.voice import intent_llm

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def main() -> int:
    # keep test events out of the real task log
    events.EVENTS_FILE = Path(tempfile.mkdtemp()) / "events.jsonl"
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

    intent = await parse(
        {
            "action": "edit",
            "edits": [{"field": "full_name", "value": "నిహారిక రవికుమార్ అని తీసేసి నిహారిక"}],
            "confidence": 0.9,
        }
    )
    check(
        "instruction sentence value sanitized away",
        intent is not None and intent.edits and intent.edits[0].value is None,
        repr(intent),
    )

    intent = await parse(
        {"action": "edit", "edits": [{"field": "district", "value": "గుంటూరు"}], "confidence": 0.9}
    )
    check("district value matched to portal option", intent is not None and intent.edits[0].value == "Guntur", repr(intent))

    intent = await parse(
        {"action": "edit", "edits": [{"field": "phone", "value": "నైన్ ఎయిట్ ఏడు ఆరు ఐదు నాలుగు మూడు రెండు ఒకటి సున్నా"}], "confidence": 0.9}
    )
    check("phone digits normalized", intent is not None and intent.edits[0].value == "9876543210", repr(intent))

    intent = await parse({"action": "edit", "edits": [{"field": "full_name", "value": "x"}], "confidence": 1.5})
    check(
        "confidence clamped and short junk value dropped",
        intent is not None and intent.confidence == 1.0 and intent.edits[0].value is None,
        repr(intent),
    )

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

    # ---- provider seam: Evon (OpenAI-compatible) vs Gemini
    from app import config

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

    saved_provider = config.VOICE_LLM_PROVIDER
    try:
        config.VOICE_LLM_PROVIDER = "openai-compatible"
        check("provider alias 'openai-compatible' -> evon", intent_llm._provider() == "evon")
        config.VOICE_LLM_PROVIDER = "gemini"
        check("provider 'gemini' -> gemini", intent_llm._provider() == "gemini")

        calls: list[str] = []

        async def fake_gemini(_prompt: str, _schema: dict, _timeout: float) -> str:
            calls.append("gemini")
            return json.dumps({"action": "cancel", "confidence": 0.9})

        async def fake_evon(_transcript: str, _values: dict, _timeout: float) -> str:
            calls.append("evon")
            return json.dumps({"action": "cancel", "confidence": 0.9})

        real_gemini, real_evon = intent_llm._request_gemini, intent_llm._request_openai_compat
        intent_llm._request_gemini, intent_llm._request_openai_compat = fake_gemini, fake_evon
        intent_llm._request = saved_request  # undo the parse() helper's monkeypatch
        saved_key = config.EVON_API_KEY
        try:
            config.VOICE_LLM_PROVIDER = "evon"
            config.EVON_API_KEY = "test-key"
            intent = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
            config.VOICE_LLM_PROVIDER = "gemini"
            intent2 = await intent_llm.parse_intent("పరీక్ష", trace_id="tr_check", current_values={}, timeout_s=0.1)
        finally:
            intent_llm._request_gemini, intent_llm._request_openai_compat = real_gemini, real_evon
            config.EVON_API_KEY = saved_key
        check("dispatch routes to the configured transport", calls == ["evon", "gemini"], str(calls))
        check("both transports yield intents", intent is not None and intent2 is not None)
    finally:
        config.VOICE_LLM_PROVIDER = saved_provider

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
