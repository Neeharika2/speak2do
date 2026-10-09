"""Gnani STT adapter (plan section 2.3): swap-friendly boundary — transcribe()."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from app import config


async def transcribe(audio_path: str | Path, language: str = config.DEFAULT_LANGUAGE) -> dict:
    """Transcribe one clip (WAV/MP3/OGG/FLAC/AAC/M4A, <= 60 s) to text."""
    if not config.GNANI_API_KEY:
        raise RuntimeError("GNANI_API_KEY is not set")
    path = Path(audio_path)
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=60.0) as client:
        with path.open("rb") as fh:
            response = await client.post(
                config.GNANI_STT_URL,
                headers={"X-API-Key-ID": config.GNANI_API_KEY},
                data={"language_code": language},
                files={"audio_file": (path.name, fh, "audio/wav")},
            )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success", False):
        raise RuntimeError(f"Gnani STT error: {payload}")
    return {
        "transcript": payload.get("transcript", ""),
        "language": language,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "request_id": payload.get("request_id"),
    }
