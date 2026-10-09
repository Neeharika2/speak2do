#!/usr/bin/env python3
"""M1 walking-skeleton smoke test (headless CLI version of the voice app).

Path: TTS command -> STT -> hardcoded intent -> policy -> Playwright login on the
mock portal -> fill two profile fields -> TTS confirmation. `trace_id` on every event.

Prereqs:
    .venv/bin/uvicorn app.main:app --port 8765     # in another terminal
Run:
    .venv/bin/python scripts/walking_skeleton.py
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

from app import config, events
from app.agent.demo_flow import run_application_flow
from app.voice import stt, tts

COMMAND_TEXT = "Scholarship application login చేయండి."
CONFIRMATION_TEXT = "Login అయింది. మొదటి పేజీలో రెండు వివరాలు నింపాను."


async def wait_for_portal(timeout_s: float = 15.0) -> None:
    url = f"{config.BASE_URL}/health"
    deadline = time.monotonic() + timeout_s
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError(f"portal not reachable at {url} — start uvicorn first (see README)")


def print_step(label: str) -> None:
    print(f"  [action] {label}")


async def main() -> int:
    trace_id = events.new_trace_id()
    started = time.perf_counter()
    print(f"trace_id: {trace_id}")

    await wait_for_portal()
    events.log_event(trace_id, "portal.ready", url=config.BASE_URL)

    # Stage 1 — voice in/out (real Gnani calls)
    command_audio = await tts.speak(COMMAND_TEXT)
    events.log_event(trace_id, "tts.command", duration_ms=command_audio["latency_ms"], path=command_audio["path"])
    stt_result = await stt.transcribe(command_audio["path"])
    events.log_event(trace_id, "stt.command", duration_ms=stt_result["latency_ms"], transcript=stt_result["transcript"])
    print(f"  [voice] heard: {stt_result['transcript']}")

    # Stage 2 + 3 — hardcoded intent -> browser (executor), every action through policy
    summary = await run_application_flow(trace_id, live_dir=config.SCREENSHOT_DIR, on_step=print_step)
    print(f"  [verify] form-1 fields set — view: {config.SCREENSHOT_DIR / 'view.png'}  ({summary})")

    # Stage 4 — spoken confirmation
    confirmation_audio = await tts.speak(CONFIRMATION_TEXT)
    events.log_event(
        trace_id, "tts.confirmation", duration_ms=confirmation_audio["latency_ms"], path=confirmation_audio["path"]
    )
    print(f"  [voice] confirmation: {confirmation_audio['path']}")

    events.log_event(trace_id, "done", ok=True, wall_ms=round((time.perf_counter() - started) * 1000, 1))
    print(f"\nSMOKE PASSED — trace {trace_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
