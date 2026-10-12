#!/usr/bin/env python3
"""M3 interactive session checks: Q&A, corrections, intent gate, "Aagu" halt.

The server must be running with the voice profile:
    AGENT_PROFILE=profile/demo_profile_voice.json .venv/bin/uvicorn app.main:app --port 8899

Run:
    BASE_URL=http://127.0.0.1:8899 .venv/bin/python scripts/voice_session_check.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx

from app import config
from app.portal import db as portal_db

NEW_PHONE = "9876500000"
DIGITS = "తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు సున్నా సున్నా సున్నా సున్నా సున్నా"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def start(client: httpx.AsyncClient, text: str) -> str:
    response = await client.post("/api/voice/command", data={"text": text})
    response.raise_for_status()
    return response.json()["session_id"]


async def status(client: httpx.AsyncClient, sid: str) -> dict:
    response = await client.get(f"/api/voice/session/{sid}")
    response.raise_for_status()
    return response.json()


async def run_until_done(client: httpx.AsyncClient, sid: str, answer_fn, timeout: float = 300.0) -> dict:
    data: dict = {}
    last_prompt: str | None = None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = await status(client, sid)
        if data["status"] in ("done", "error"):
            return data
        if data["awaiting_input"] and data["prompt_text"] != last_prompt:
            last_prompt = data["prompt_text"]
            answer = answer_fn(data["prompt_text"], data)
            if answer is not None:
                await client.post("/api/voice/answer", data={"text": answer})
        await asyncio.sleep(0.2)
    return data


async def main() -> int:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=30.0) as client:
        # ---- 1. baseline: missing district + read-back
        await client.post("/portal/__reset")
        sid = await start(client, "Scholarship application cheyyi")
        prompts: list[str] = []

        def answer_simple(prompt, _data):
            prompts.append(prompt)
            return "గుంటూరు" if "District" in prompt else "అవును"

        data = await run_until_done(client, sid, answer_simple)
        check("missing district asked by voice", any("District" in p for p in prompts), f"{len(prompts)} prompts")
        check("name/phone read-back asked", any("సరేనా" in p for p in prompts))
        check("reached review (success)", data.get("stop_reason") == "done", str(data.get("stop_reason")))
        check("phone read-back shows digit words", any("తొమ్మిది" in p for p in prompts))
        payload = portal_db.draft_payload(config.PORTAL_TEST_USER)
        check("district filled from voice answer", payload.get("district") == "Guntur", str(payload.get("district")))

        # ---- 2. read-back correction: "కాదు" -> phone -> new digits -> re-read -> yes
        await client.post("/portal/__reset")
        sid = await start(client, "Scholarship application cheyyi")
        prompts = []
        state = {"said_no": False}

        def answer_correction(prompt, _data):
            prompts.append(prompt)
            if "ఏది మార్చాలి" in prompt:
                return "ఫోన్ నంబర్"
            if "కొత్త ఫోన్" in prompt:
                return DIGITS
            if "సరేనా" in prompt and not state["said_no"]:
                state["said_no"] = True
                return "కాదు"
            if "District" in prompt:
                return "గుంటూరు"
            return "అవును"

        data = await run_until_done(client, sid, answer_correction)
        payload = portal_db.draft_payload(config.PORTAL_TEST_USER)
        check("read-back rejection starts correction", state["said_no"])
        check("corrected phone saved", payload.get("phone") == NEW_PHONE, str(payload.get("phone")))
        reread = False
        for index, p in enumerate(prompts):
            if "కొత్త ఫోన్" in p:
                reread = any("సరేనా" in q and "తొమ్మిది" in q for q in prompts[index + 1:])
                break
        check("corrected value read back", reread)
        check("run completed after correction", data.get("stop_reason") == "done", str(data.get("stop_reason")))

        # ---- 3. command-time correction: "నా నంబర్ మారింది" -> asks -> runs
        await client.post("/portal/__reset")
        sid = await start(client, "నా నంబర్ మారింది")
        state = {"asked_new": False}

        def answer_command_correction(prompt, _data):
            if "కొత్త ఫోన్" in prompt:
                state["asked_new"] = True
                return DIGITS
            if "District" in prompt:
                return "గుంటూరు"
            return "అవును"

        data = await run_until_done(client, sid, answer_command_correction)
        payload = portal_db.draft_payload(config.PORTAL_TEST_USER)
        check("agent asked for the new number", state["asked_new"])
        check("command-time correction applied", payload.get("phone") == NEW_PHONE, str(payload.get("phone")))
        check("ran to review after correction", data.get("stop_reason") == "done", str(data.get("stop_reason")))

        # ---- 4. unrelated command: clarify, no agent steps
        await client.post("/portal/__reset")
        sid = await start(client, "వాతావరణం ఎలా ఉంది")
        data = await run_until_done(client, sid, lambda p, d: None)
        check(
            "unrelated command clarified, no steps",
            not data.get("steps") and "scholarship application" in (data.get("reply_text") or ""),
            (data.get("reply_text") or "")[:50],
        )

        # ---- 5. "Aagu" halts the run within 1 s of the transcript
        await client.post("/portal/__reset")
        sid = await start(client, "Scholarship application cheyyi")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            data = await status(client, sid)
            if data["status"] in ("done", "error"):
                break
            if data["status"] == "running" and len(data["steps"]) >= 2:
                break
            await asyncio.sleep(0.15)

        started = time.monotonic()
        response = await client.post("/api/voice/interrupt", data={"text": "ఆగు"})
        response.raise_for_status()
        while time.monotonic() - started < 10:
            data = await status(client, sid)
            if data["status"] in ("speaking", "done", "error"):
                break
            await asyncio.sleep(0.05)
        halt_elapsed = time.monotonic() - started

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            data = await status(client, sid)
            if data["status"] == "done":
                break
            await asyncio.sleep(0.2)

        check("halt within 1 s of transcript", halt_elapsed <= 1.0, f"{halt_elapsed:.2f}s")
        check("stop reason recorded", data.get("stop_reason") == "user_stop", str(data.get("stop_reason")))
        check("spoken stop reply", "ఆపేశాను" in (data.get("reply_text") or ""), data.get("reply_text"))

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} session checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
