#!/usr/bin/env python3
"""End-to-end WebSocket voice check.

Streams a synthesized voice command over /ws/voice (live PCM -> Gnani STT
stream), asserts the transcript, session start and streamed TTS audio, answers
the interactive prompts, and checks the agent reaches review.

Server must be running (default profile):
    BASE_URL=http://127.0.0.1:8899 .venv/bin/uvicorn app.main:app --port 8899

Run:
    BASE_URL=http://127.0.0.1:8899 .venv/bin/python scripts/voice_ws_check.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx
import websockets

from app import config
from app.voice import tts
from app.voice.streaming import FRAME_SAMPLES, STREAM_SAMPLE_RATE, read_wav_pcm

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def main() -> int:
    base = config.BASE_URL
    ws_url = base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"

    async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
        await client.post("/portal/__reset")

    command = await tts.speak("Scholarship application చేయండి.")
    pcm, rate = read_wav_pcm(command["path"])
    check("command audio ready", len(pcm) > 0 and rate == STREAM_SAMPLE_RATE, f"{len(pcm)} bytes @ {rate}")

    transcripts: list[str] = []
    audio_chunks = 0
    session_id: str | None = None
    answered = 0
    data: dict = {}

    async with websockets.connect(ws_url, max_size=2**22) as ws:
        connected = json.loads(await ws.recv())
        check("ws connected", connected.get("type") == "connected", str(connected.get("message", "")))

        await ws.send(json.dumps({"type": "start"}))
        frame_bytes = FRAME_SAMPLES * 2
        for offset in range(0, len(pcm), frame_bytes):
            frame = pcm[offset : offset + frame_bytes]
            if len(frame) < frame_bytes:
                frame = frame + bytes(frame_bytes - len(frame))
            await ws.send(frame)
            await asyncio.sleep(FRAME_SAMPLES / rate)
        await ws.send(json.dumps({"type": "stop"}))

        async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                # drain websocket messages
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.15)
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "transcript":
                        transcripts.append(message.get("text", ""))
                    elif kind == "session" and session_id is None:
                        session_id = message.get("session_id")
                    elif kind == "audio":
                        audio_chunks += 1
                    elif kind == "audio_fallback":
                        audio_chunks += 1
                except asyncio.TimeoutError:
                    pass

                if session_id is None:
                    continue
                response = await client.get(f"/api/voice/session/{session_id}")
                data = response.json()
                if data["status"] in ("done", "error"):
                    # give the last audio messages a moment to arrive
                    try:
                        while True:
                            raw = await asyncio.wait_for(ws.recv(), timeout=0.3)
                            kind = json.loads(raw).get("type")
                            if kind in ("audio", "audio_fallback"):
                                audio_chunks += 1
                    except asyncio.TimeoutError:
                        pass
                    break
                if data["awaiting_input"]:
                    await client.post("/api/voice/answer", data={"text": "అవును"})
                    answered += 1
                    await asyncio.sleep(0.4)

    heard = " | ".join(t for t in transcripts if t)
    check("ws transcript recognized", any("స్కాలర్షిప్" in t or "అప్లికేషన్" in t for t in transcripts), heard)
    check("ws session started", session_id is not None, str(session_id))
    check("tts streamed over ws", audio_chunks >= 3, f"{audio_chunks} audio messages")
    check("interactive prompts answered", answered >= 1, f"{answered}")
    check("run reached review", data.get("stop_reason") == "done", str(data.get("stop_reason")))

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} websocket checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
