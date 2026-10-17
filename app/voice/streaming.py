"""Gnani realtime WebSocket adapters (STT stream + TTS stream).

STT: wss://api.vachana.ai/stt/v3/stream — PCM16 mono, exactly 1024-byte frames
     (512 samples), VAD-segmented transcripts.
TTS: wss://api.vachana.ai/api/v1/tts — request/response, base64 audio chunks.

Both raise/return PCM16 at the negotiated sample rate (default 48 kHz).
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import io
import json
import wave
from pathlib import Path
from typing import Awaitable, Callable

import websockets
from websockets.protocol import State

from app import config, events

STT_WS_URL = "wss://api.vachana.ai/stt/v3/stream"
TTS_WS_URL = "wss://api.vachana.ai/api/v1/tts"

STREAM_SAMPLE_RATE = 48000
FRAME_SAMPLES = 512
FRAME_BYTES = FRAME_SAMPLES * 2  # Gnani requires exactly 1024-byte frames
STOP_SILENCE_MS = 650            # silence pushed after PTT release so VAD closes the segment
MIN_SILENCE_MS = 500             # balance: don't split mid-sentence, still snappy


async def _maybe_await(value):
    if inspect.isawaitable(value):
        await value


def pcm_to_wav(pcm: bytes, sample_rate: int = STREAM_SAMPLE_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


def read_wav_pcm(path: str | Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as reader:
        if reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise ValueError("only mono 16-bit WAV is supported")
        return reader.readframes(reader.getnframes()), reader.getframerate()


class SttStream:
    """One persistent Gnani STT WebSocket session (VAD segments become transcripts)."""

    def __init__(
        self,
        on_transcript: Callable[[dict], Awaitable | None] | None = None,
        on_processing: Callable[[dict], Awaitable | None] | None = None,
        *,
        language: str | None = None,
        sample_rate: int = STREAM_SAMPLE_RATE,
        min_silence_ms: int = MIN_SILENCE_MS,
    ) -> None:
        self._on_transcript = on_transcript
        self._on_processing = on_processing
        self.language = language or config.DEFAULT_LANGUAGE
        self.sample_rate = sample_rate
        self.min_silence_ms = min_silence_ms
        self._ws = None
        self._reader: asyncio.Task | None = None
        self.error: str | None = None
        self._closed = True
        self._closing = False

    @property
    def frame_delay(self) -> float:
        return FRAME_SAMPLES / self.sample_rate

    @property
    def alive(self) -> bool:
        """True while the socket is open and the reader has not seen a close."""
        if self._closed or self.error is not None or self._ws is None:
            return False
        return self._ws.state is State.OPEN

    async def ensure_connected(self) -> None:
        """(Re)connect when the previous socket died — idle timeouts, restarts."""
        if self.alive:
            return
        events.log_event("stt", "stt.reconnect", previous_error=self.error)
        await self.close()
        await self.connect()

    async def connect(self) -> None:
        if not config.GNANI_API_KEY:
            raise RuntimeError("GNANI_API_KEY is not set")
        headers = {
            "x-api-key-id": config.GNANI_API_KEY,
            "lang_code": self.language,
            "x-sample-rate": str(self.sample_rate),
            "x-min-silence-ms": str(self.min_silence_ms),
        }
        self._ws = await websockets.connect(STT_WS_URL, additional_headers=headers, max_size=2**20)
        self.error = None
        self._closed = False
        self._closing = False
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = message.get("type")
                if kind == "transcript":
                    if self._on_transcript:
                        await _maybe_await(self._on_transcript(message))
                elif kind == "processing":
                    if self._on_processing:
                        await _maybe_await(self._on_processing(message))
                elif kind == "error":
                    self.error = message.get("message")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — connection closed / cancelled
            self.error = str(exc)
        finally:
            self._closed = True
            if not self._closing:
                # the vendor side closed an idle/long stream: the next press reconnects
                events.log_event("stt", "stt.stream_ended", error=self.error or "closed by server")

    async def send_audio(self, frame: bytes) -> None:
        if self._ws is not None:
            await self._ws.send(frame)

    async def send_frames(self, pcm: bytes, *, pace: bool = True) -> None:
        """Split PCM16 into 1024-byte frames (last one zero-padded) and send."""
        for offset in range(0, len(pcm), FRAME_BYTES):
            frame = pcm[offset : offset + FRAME_BYTES]
            if len(frame) < FRAME_BYTES:
                frame = frame + bytes(FRAME_BYTES - len(frame))
            await self.send_audio(frame)
            if pace:
                await asyncio.sleep(self.frame_delay)

    async def send_silence(self, milliseconds: int = STOP_SILENCE_MS) -> None:
        frames = max(1, int((milliseconds / 1000) / self.frame_delay))
        zero = bytes(FRAME_BYTES)
        for _ in range(frames):
            await self.send_audio(zero)
            await asyncio.sleep(self.frame_delay)

    async def close(self) -> None:
        self._closing = True
        self._closed = True
        reader = self._reader
        self._reader = None
        if reader is not None:
            reader.cancel()
            try:
                await reader  # let its finally run before a possible reconnect
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


async def synthesize_stream(
    text: str,
    on_chunk: Callable[[bytes], Awaitable | None] | None = None,
    *,
    voice: str | None = None,
    language: str | None = None,
    speed: float = 1.0,
    sample_rate: int = STREAM_SAMPLE_RATE,
) -> bytes:
    """Synthesize via the Gnani TTS WebSocket; returns PCM16 and calls on_chunk per chunk."""
    if not config.GNANI_API_KEY:
        raise RuntimeError("GNANI_API_KEY is not set")
    request = {
        "text": text,
        "voice": voice or config.DEFAULT_VOICE,
        "model": "timbre-v2.5",
        "language": language or config.DEFAULT_LANGUAGE,
        "speed": speed,
        "audio_config": {
            "sample_rate": sample_rate,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "raw",
        },
    }
    chunks: list[bytes] = []
    async with websockets.connect(
        TTS_WS_URL, additional_headers={"X-API-Key-ID": config.GNANI_API_KEY}, max_size=2**22
    ) as ws:
        await ws.send(json.dumps(request))
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            message = json.loads(raw)
            kind = message.get("type")
            if kind == "audio":
                data = message.get("data") or {}
                payload = data.get("audio") or ""
                if payload:
                    chunk = base64.b64decode(payload)
                    chunks.append(chunk)
                    if on_chunk is not None:
                        await _maybe_await(on_chunk(chunk))
                if data.get("is_final"):
                    break
            elif kind == "complete":
                break
            elif kind == "error":
                raise RuntimeError(f"Gnani TTS error: {message.get('message')}")
    return b"".join(chunks)
