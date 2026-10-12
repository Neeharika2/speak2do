"""Gnani TTS adapter (plan section 2.3): swap-friendly boundary — speak()."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import httpx

from app import config


async def speak(
    text: str,
    *,
    language: str = config.DEFAULT_LANGUAGE,
    voice: str = config.DEFAULT_VOICE,
    out_dir: str | Path = config.TTS_DIR,
) -> dict:
    """Synthesize text to a WAV file; returns path, size and latency."""
    if not config.GNANI_API_KEY:
        raise RuntimeError("GNANI_API_KEY is not set")
    payload = {
        "text": text,
        "voice": voice,
        "model": "timbre-v2.5",
        "language": language,
        "speed": 1.0,
        "audio_config": {
            "sample_rate": 48000,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        },
    }
    started = time.perf_counter()
    response = None
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(2):  # one retry: flaky TLS nodes have been observed
            try:
                response = await client.post(
                    config.GNANI_TTS_URL,
                    headers={"X-API-Key-ID": config.GNANI_API_KEY},
                    json=payload,
                )
                break
            except httpx.TransportError:
                if attempt == 1:
                    raise
                await asyncio.sleep(0.8)
    response.raise_for_status()
    out_path = Path(out_dir) / f"tts_{uuid.uuid4().hex[:8]}.wav"
    out_path.write_bytes(response.content)
    return {
        "path": str(out_path),
        "bytes": len(response.content),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "language": language,
        "voice": voice,
    }
