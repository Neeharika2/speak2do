#!/usr/bin/env python3
"""End-to-end WebSocket voice check.

Sends {"type": "begin"} (the Start button) over /ws/voice, answers the agent's
first question by voice (live PCM -> Gnani STT stream), answers the rest by text,
and checks the transcript, the stored answer, streamed TTS and that review is reached.

Server must be running (default = empty profile, so the agent asks every field):
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

from app import config, lang
from app.voice import tts
from app.voice.streaming import FRAME_SAMPLES, STREAM_SAMPLE_RATE, read_wav_pcm

RESULTS: list[tuple[str, bool, str]] = []

# Typed answers keyed by the spoken field name the agent uses (Telugu, the default language).
_TE = lang.get("te-IN")
TEXT_ANSWERS = [(_TE.label(key), value) for key, value in [
    ("dob", "2005-03-12"), ("gender", "Female"), ("phone", "9876543210"),
    ("email", "sita@example.com"), ("college", "Govt College Hyderabad"),
    ("course", "UG"), ("year", "2nd"), ("marks", "81"), ("address", "1-2 MG Road"),
    ("city", "Hyderabad"), ("state", "Telangana"), ("district", "Hyderabad"), ("pin", "500001"),
]]


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def main() -> int:
    base = config.BASE_URL
    ws_url = base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/voice"

    async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
        await client.post("/portal/__reset")

    spoken = await tts.speak("సీత దేవి")  # the user's spoken answer to the first question (name)
    pcm, rate = read_wav_pcm(spoken["path"])
    check("answer audio ready", len(pcm) > 0 and rate == STREAM_SAMPLE_RATE, f"{len(pcm)} bytes @ {rate}")

    transcripts: list[str] = []
    audio_chunks = 0
    session_id: str | None = None
    spoke = False
    voice_prompt = ""
    voice_deadline = 0.0
    answered = 0
    data: dict = {}

    async def stream_answer(ws) -> None:
        await ws.send(json.dumps({"type": "start"}))
        frame_bytes = FRAME_SAMPLES * 2
        for offset in range(0, len(pcm), frame_bytes):
            frame = pcm[offset : offset + frame_bytes]
            if len(frame) < frame_bytes:
                frame = frame + bytes(frame_bytes - len(frame))
            await ws.send(frame)
            await asyncio.sleep(FRAME_SAMPLES / rate)
        await ws.send(json.dumps({"type": "stop"}))

    async with websockets.connect(ws_url, max_size=2**22) as ws:
        connected = json.loads(await ws.recv())
        check("ws connected", connected.get("type") == "connected", str(connected.get("message", "")))
        await ws.send(json.dumps({"type": "begin"}))  # the page's Start button

        async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.15)
                    message = json.loads(raw)
                    kind = message.get("type")
                    if kind == "transcript":
                        transcripts.append(message.get("text", ""))
                    elif kind == "session" and session_id is None:
                        session_id = message.get("session_id")
                    elif kind in ("audio", "audio_fallback"):
                        audio_chunks += 1
                except asyncio.TimeoutError:
                    pass

                if session_id is None:
                    continue
                data = (await client.get(f"/api/voice/session/{session_id}")).json()
                if data["status"] in ("done", "error"):
                    break
                if not data["awaiting_input"]:
                    continue
                if not spoke:
                    # first question: answer by voice over the socket
                    spoke = True
                    voice_prompt = data["prompt_text"]
                    voice_deadline = time.monotonic() + 20  # STT + VAD + debounce take a few seconds
                    await stream_answer(ws)
                    continue
                if data["prompt_text"] == voice_prompt and time.monotonic() < voice_deadline:
                    continue  # still waiting for the spoken answer to land
                answer = next((v for k, v in TEXT_ANSWERS if k in data["prompt_text"]), "అవును")
                await client.post("/api/voice/answer", data={"text": answer})
                answered += 1
                await asyncio.sleep(0.6)

    heard = " | ".join(t for t in transcripts if t)
    stored_name = (data.get("updated_fields") or {}).get("full_name", "")
    check("ws session started by begin", session_id is not None, str(session_id))
    check("spoken answer recognized over ws", any("సీత" in t for t in transcripts), heard)
    check("spoken answer stored for the field", "సీత" in stored_name, stored_name)
    check("tts streamed over ws", audio_chunks >= 3, f"{audio_chunks} audio messages")
    check("remaining questions answered", answered >= 10, f"{answered}")
    check("run reached review", data.get("stop_reason") == "done", str(data.get("stop_reason")))

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} websocket checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
