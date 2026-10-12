#!/usr/bin/env python3
"""Checks for the Gnani WebSocket adapters (no server needed).

1. TTS stream: synthesize a Telugu sentence, assert progressive chunks, save WAV.
2. STT stream: stream that WAV through the STT WebSocket, assert transcript.

Run:
    .venv/bin/python scripts/streaming_check.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import config
from app.voice.streaming import SttStream, pcm_to_wav, read_wav_pcm, synthesize_stream

SENTENCE = "నమస్తే, ఇది ఒక వెబ్ సాకెట్ పరీక్ష."
OUT_WAV = config.DATA_DIR / "streaming_check.wav"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def tts_check() -> None:
    chunk_times: list[float] = []
    started = time.perf_counter()

    async def on_chunk(_chunk: bytes) -> None:
        chunk_times.append(time.perf_counter() - started)

    pcm = await synthesize_stream(SENTENCE, on_chunk)
    total = time.perf_counter() - started
    check("tts: audio returned", len(pcm) > 0, f"{len(pcm)} bytes")
    check("tts: chunks streamed progressively", len(chunk_times) >= 2, f"{len(chunk_times)} chunks")
    check(
        "tts: first chunk before completion",
        bool(chunk_times) and chunk_times[0] < total - 0.05,
        f"first {chunk_times[0]:.2f}s / total {total:.2f}s",
    )
    OUT_WAV.write_bytes(pcm_to_wav(pcm))
    print(f"      saved {OUT_WAV}")
    durations = [round(t, 2) for t in chunk_times[:5]]
    print(f"      chunk timestamps: {durations} …")


async def stt_check() -> None:
    pcm, rate = read_wav_pcm(OUT_WAV)
    transcripts: list[dict] = []

    async def on_transcript(message: dict) -> None:
        transcripts.append(message)

    stream = SttStream(on_transcript=on_transcript, sample_rate=rate)
    await stream.connect()
    try:
        started = time.perf_counter()
        await stream.send_frames(pcm, pace=True)
        await stream.send_silence()
        # collect segments until a quiet period (VAD may split at pauses)
        last_count = 0
        quiet_since: float | None = None
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.2)
            if len(transcripts) != last_count:
                last_count = len(transcripts)
                quiet_since = time.monotonic()
            elif quiet_since is not None and time.monotonic() - quiet_since > 1.2:
                break
        elapsed = time.perf_counter() - started
    finally:
        await stream.close()

    text = " ".join(t.get("text", "") for t in transcripts).strip()
    check("stt: transcript received", bool(text), text or f"error={stream.error}")
    check("stt: keyword recognized", "పరీక్ష" in text, text)
    check("stt: end-to-end under 10 s", bool(text) and elapsed < 10, f"{elapsed:.2f}s")
    if transcripts:
        print(f"      segments: {len(transcripts)}, server latency: {transcripts[0].get('latency')} ms")


async def main() -> int:
    await tts_check()
    await stt_check()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} streaming checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
