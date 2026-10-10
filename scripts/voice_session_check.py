#!/usr/bin/env python3
"""M3 interactive session checks: missing-field Q&A and "Aagu" halt latency.

The server must be running with the voice profile for the missing-district test:
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


async def main() -> int:
    async with httpx.AsyncClient(base_url=config.BASE_URL, timeout=30.0) as client:
        # ---- Test 1: missing district answered by voice, read-back confirmed
        await client.post("/portal/__reset")
        sid = await start(client, "Scholarship application cheyyi")
        prompts: list[str] = []
        data: dict = {}
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            data = await status(client, sid)
            if data["status"] in ("done", "error"):
                break
            if data["awaiting_input"]:
                prompt = data["prompt_text"]
                prompts.append(prompt)
                answer = "గుంటూరు" if "District" in prompt else "అవును"
                response = await client.post("/api/voice/answer", data={"text": answer})
                response.raise_for_status()
            await asyncio.sleep(0.2)

        check("missing district asked by voice", any("District" in p for p in prompts), f"{len(prompts)} prompts")
        check("name/phone read-back asked", any("సరేనా" in p for p in prompts))
        check("session completed", data.get("status") == "done", str(data.get("status")))
        check("reached review (success)", data.get("stop_reason") == "done", str(data.get("stop_reason")))
        payload = portal_db.draft_payload(config.PORTAL_TEST_USER)
        check("district filled from voice answer", payload.get("district") == "Guntur", str(payload.get("district")))
        check("phone read-back shows digit words", any("తొమ్మిది" in p for p in prompts))

        # ---- Test 2: "Aagu" halts the run within 1 s of the transcript
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
