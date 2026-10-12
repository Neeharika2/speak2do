"""Voice app API: push-to-talk -> STT -> Jev agent -> TTS.

Transport:
- WebSocket `/ws/voice` (M4): live mic PCM -> Gnani STT WebSocket; transcripts
  are routed like commands/answers/interrupts; agent speech streams back as
  TTS audio chunks (progressive playback).
- REST endpoints below remain as fallback and for tests (WAV upload path).

Interactive sessions (M3): the agent speaks progress, pauses for read-back
confirmation or missing-field questions, and corrections are applied by voice.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app import config, events
from app.agent import readback
from app.agent.loop import run_agent_goal
from app.agent.voice_ux import VoiceAgent
from app.portal import db as portal_db
from app.voice import stt, streaming, tts

router = APIRouter()
templates = Jinja2Templates(directory=str(config.REPO_ROOT / "app" / "templates"))

SESSIONS_DIR = config.DATA_DIR / "sessions"
ACTIVE_STATES = {"queued", "transcribing", "running", "speaking", "awaiting"}
TRANSCRIPT_DEBOUNCE_S = 0.6  # aggregate VAD segments that belong to one utterance

REPLY_DONE = "అప్లికేషన్ వివరాలు నింపి, రివ్యూ పేజీకి చేరుకున్నాను."
REPLY_STOPPED = "ఆపేశాను."
REPLY_HANDOFF = "క్షమించండి, నాకు మీ సహాయం కావాలి."
REPLY_FAILED = "క్షమించండి, పనిని పూర్తి చేయలేకపోయాను. సహాయం అవసరం."
REPLY_EMPTY = "క్షమించండి, వినిపించలేదు. మళ్ళీ చెప్పండి."
REPLY_CLARIFY = (
    "నేను ఇప్పుడు scholarship application విషయంలో సహాయం చేయగలను. "
    "\"Scholarship application చేయండి\" అని చెప్పండి."
)


@dataclass
class Session:
    """One voice task: files, status, interactive channels, and the WS sink."""

    id: str
    trace_id: str
    dir: Path
    status: str = "queued"
    transcript: str = ""
    reply_text: str = ""
    error: str | None = None
    steps: list[str] = field(default_factory=list)
    created_at: str = ""
    finished_at: str | None = None
    task: asyncio.Task | None = None
    # interactive state
    awaiting: bool = False
    prompt_text: str = ""
    prompt_log: list[dict] = field(default_factory=list)
    speech_id: int = 0
    stream_id: int = 0
    speech_tasks: list[asyncio.Task] = field(default_factory=list)
    speech_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stop_flag: bool = False
    stop_reason: str | None = None
    answer_event: asyncio.Event | None = None
    answer_text: str | None = None
    # voice corrections (M3.5)
    overrides: dict = field(default_factory=dict)
    pending_correction: str | None = None
    base_profile: dict = field(default_factory=dict)
    # websocket sink for streamed speech (M4)
    ws_send: Callable[[dict], Awaitable[None]] | None = None


SESSIONS: dict[str, Session] = {}
_latest_ws_send: Callable[[dict], Awaitable[None]] | None = None


def _attach_ws(session: Session) -> None:
    """Let a REST-started session stream speech to the browser's live socket."""
    if session.ws_send is None and _latest_ws_send is not None:
        session.ws_send = _latest_ws_send


def _active_session() -> Session | None:
    for session in SESSIONS.values():
        if session.status in ACTIVE_STATES:
            return session
    return None


def _new_session() -> Session:
    sid = f"s_{uuid.uuid4().hex[:10]}"
    session_dir = SESSIONS_DIR / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    session = Session(
        id=sid,
        trace_id=events.new_trace_id(),
        dir=session_dir,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    SESSIONS[sid] = session
    return session


def _load_profile() -> dict:
    path = Path(config.AGENT_PROFILE)
    if not path.is_absolute():
        path = config.REPO_ROOT / path
    return json.loads(path.read_text(encoding="utf-8"))


def _apply_session_correction(session: Session, field: str, value: str) -> dict:
    """Apply a voice correction to the session and to the saved application record."""
    session.overrides[field] = value
    events.log_event(session.trace_id, "voice.correction", field=field, value=value)
    try:
        portal_db.save_section(config.PORTAL_TEST_USER, {field: value})
    except Exception as exc:  # noqa: BLE001 — the correction still applies to the session
        events.log_event(session.trace_id, "voice.correction_db_error", error=str(exc))
    merged = dict(session.base_profile)
    merged.update(session.overrides)
    return merged


async def _collect_field_value(session: Session, field: str) -> str | None:
    label_te = readback.FIELD_LABELS_TE.get(field, field)
    for _ in range(2):
        answer = await _ask(session, f"కొత్త {label_te} చెప్పండి.", "value")
        if readback.is_stop(answer):
            return None
        value = readback.extract_field_value(field, answer)
        if value:
            return value
    return None


# --------------------------------------------------------------------------- speech (streamed TTS)


async def _stream_speech(session: Session, text: str, kind: str, filename: str) -> None:
    """Synthesize via the TTS WebSocket, stream chunks to the browser, save the WAV.

    Falls back to the REST TTS API when the socket fails; the browser is told via
    an audio_fallback message so it can play the saved file instead.
    """
    async with session.speech_lock:
        session.stream_id += 1
        stream_id = session.stream_id
        events.log_event(session.trace_id, f"voice.{kind}", text=text)

        async def safe_send(payload: dict) -> None:
            if session.ws_send is None:
                return
            try:
                await session.ws_send(payload)
            except Exception:  # noqa: BLE001 — socket closed mid-speech; stop trying
                session.ws_send = None

        async def on_chunk(chunk: bytes) -> None:
            await safe_send(
                {
                    "type": "audio",
                    "kind": kind,
                    "id": stream_id,
                    "sample_rate": streaming.STREAM_SAMPLE_RATE,
                    "data": base64.b64encode(chunk).decode("ascii"),
                }
            )

        try:
            pcm = await streaming.synthesize_stream(text, on_chunk)
            (session.dir / filename).write_bytes(streaming.pcm_to_wav(pcm))
            await safe_send({"type": "audio_done", "kind": kind, "id": stream_id})
        except Exception as exc:  # noqa: BLE001 — fall back to REST
            events.log_event(session.trace_id, "voice.stream_error", error=str(exc))
            try:
                result = await tts.speak(text, out_dir=session.dir)
                Path(result["path"]).replace(session.dir / filename)
            except Exception as rest_exc:  # noqa: BLE001 — speech must never break the task
                events.log_event(session.trace_id, "voice.speech_error", error=str(rest_exc))
                return
            await safe_send({"type": "audio_fallback", "kind": kind, "id": stream_id})


async def _speak_worker(session: Session, text: str) -> None:
    await _stream_speech(session, text, "speech", "speech.wav")
    session.speech_id += 1  # polling fallback plays /speech once the file exists


def _publish_speech(session: Session, text: str) -> None:
    task = asyncio.create_task(_speak_worker(session, text))
    session.speech_tasks.append(task)


async def _ask(session: Session, prompt: str, kind: str) -> str:
    session.prompt_text = prompt
    session.prompt_log.append({"kind": kind, "prompt": prompt})
    session.awaiting = True
    session.status = "awaiting"
    events.log_event(session.trace_id, "voice.ask", kind=kind, prompt=prompt)
    _publish_speech(session, prompt)
    event = asyncio.Event()
    session.answer_event = event
    session.answer_text = None
    await event.wait()
    session.awaiting = False
    session.answer_event = None
    session.status = "running"
    answer = session.answer_text or ""
    events.log_event(session.trace_id, "voice.answer", kind=kind, transcript=answer)
    return answer


async def _speak_reply(session: Session, text: str) -> None:
    session.status = "speaking"
    session.reply_text = text
    await _stream_speech(session, text, "reply", "reply.wav")
    events.log_event(session.trace_id, "tts.reply", text=text)


# --------------------------------------------------------------------------- task runner


async def _run_command(session: Session, audio_path: Path | None, text: str | None) -> None:
    trace_id = session.trace_id
    try:
        if text is not None:
            transcript = text.strip()
            events.log_event(trace_id, "text.command", transcript=transcript)
        else:
            session.status = "transcribing"
            stt_result = await stt.transcribe(audio_path)
            transcript = stt_result["transcript"].strip()
            events.log_event(trace_id, "stt.command", duration_ms=stt_result["latency_ms"], transcript=transcript)
        session.transcript = transcript

        if not transcript:
            await _speak_reply(session, REPLY_EMPTY)
        else:
            session.base_profile = _load_profile()
            correction = readback.parse_correction(transcript)
            app_intent = readback.is_application_intent(transcript)
            run_task = False

            if correction is not None:
                field, value = correction
                if value is None:
                    value = await _collect_field_value(session, field)
                if value:
                    _apply_session_correction(session, field, value)
                    _publish_speech(session, f"సరే, {readback.FIELD_LABELS_TE.get(field, field)} నవీకరించాను.")
                    run_task = True
                else:
                    session.stop_reason = "clarify"
                    await _speak_reply(session, REPLY_FAILED)
            elif app_intent:
                run_task = True
            else:
                session.stop_reason = "clarify"
                await _speak_reply(session, REPLY_CLARIFY)

            if run_task:
                session.status = "running"
                voice = VoiceAgent(
                    say=lambda message: _publish_speech(session, message),
                    ask=lambda prompt, kind: _ask(session, prompt, kind),
                    stop_requested=lambda: session.stop_flag,
                    on_correction=lambda field, value: _apply_session_correction(session, field, value),
                )
                result = await run_agent_goal(
                    config.AGENT_GOAL,
                    trace_id=trace_id,
                    start_url=f"{config.PORTAL_URL}{config.AGENT_START_PATH}",
                    success_url=config.AGENT_SUCCESS_PATH,
                    live_dir=session.dir,
                    on_step=session.steps.append,
                    voice_io=voice,
                    stop_check=lambda: session.stop_flag,
                    profile_overrides=lambda: session.overrides,
                )
                session.stop_reason = result["stop_reason"]
                if result["stop_reason"] == "user_stop":
                    await _speak_reply(session, REPLY_STOPPED)
                elif result["success"]:
                    await _speak_reply(session, REPLY_DONE)
                elif result["stop_reason"] == "handoff":
                    await _speak_reply(session, REPLY_HANDOFF)
                else:
                    events.log_event(trace_id, "agent.not_done", stop_reason=result["stop_reason"])
                    await _speak_reply(session, REPLY_FAILED)

        session.status = "done"
        session.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        events.log_event(trace_id, "done", ok=True)
    except Exception as exc:  # noqa: BLE001 — surface to the page
        session.status = "error"
        session.error = f"{type(exc).__name__}: {exc}"
        events.log_event(trace_id, "error", error=session.error)


async def _transcribe_input(session: Session, audio: UploadFile | None, text: str | None) -> str:
    if text is not None and text.strip():
        return text.strip()
    if audio is None:
        return ""
    path = session.dir / f"input_{uuid.uuid4().hex[:6]}.wav"
    path.write_bytes(await audio.read())
    result = await stt.transcribe(path)
    return result["transcript"].strip()


# --------------------------------------------------------------------------- transcript routing (shared)


def _handle_answer(session: Session, transcript: str) -> dict:
    session.answer_text = transcript
    if session.answer_event is not None:
        session.answer_event.set()
    return {"ok": True, "answered": True, "transcript": transcript}


def _handle_interrupt(session: Session, transcript: str) -> dict:
    if readback.is_stop(transcript):
        session.stop_flag = True
        events.log_event(session.trace_id, "voice.stop_requested", transcript=transcript)
        return {"ok": True, "stopped": True, "transcript": transcript}
    correction = readback.parse_correction(transcript)
    if correction is None and session.pending_correction:
        value = readback.extract_field_value(session.pending_correction, transcript)
        if value:
            correction = (session.pending_correction, value)
    if correction is not None:
        field, value = correction
        if value is None:
            value = readback.extract_field_value(field, transcript)
        if value:
            _apply_session_correction(session, field, value)
            session.pending_correction = None
            _publish_speech(session, f"సరే, {readback.FIELD_LABELS_TE.get(field, field)} నవీకరించాను.")
            return {"ok": True, "updated": True, "field": field, "transcript": transcript}
        session.pending_correction = field
        _publish_speech(session, f"కొత్త {readback.FIELD_LABELS_TE.get(field, field)} చెప్పండి.")
        return {"ok": True, "pending": field, "transcript": transcript}
    return {"ok": True, "stopped": False, "transcript": transcript}


# --------------------------------------------------------------------------- HTTP endpoints


@router.get("/assistant", response_class=HTMLResponse)
async def assistant_page(request: Request):
    return templates.TemplateResponse(request, "assistant.html", {"title": "Voice Assistant"})


@router.post("/api/voice/command")
async def voice_command(audio: UploadFile | None = File(None), text: str | None = Form(None)):
    if _active_session():
        raise HTTPException(status_code=409, detail="The agent is already busy with another task.")
    session = _new_session()
    _attach_ws(session)
    audio_path: Path | None = None
    if text is None and audio is not None:
        audio_path = session.dir / "command.wav"
        audio_path.write_bytes(await audio.read())
        events.log_event(session.trace_id, "audio.received", bytes=audio_path.stat().st_size)
    session.task = asyncio.create_task(_run_command(session, audio_path, text))
    return {"session_id": session.id}


@router.post("/api/voice/answer")
async def voice_answer(audio: UploadFile | None = File(None), text: str | None = Form(None)):
    session = _active_session()
    if session is None or not session.awaiting:
        raise HTTPException(status_code=409, detail="The agent is not waiting for an answer.")
    _attach_ws(session)
    answer = await _transcribe_input(session, audio, text)
    return _handle_answer(session, answer)


@router.post("/api/voice/interrupt")
async def voice_interrupt(audio: UploadFile | None = File(None), text: str | None = Form(None)):
    session = _active_session()
    if session is None:
        raise HTTPException(status_code=409, detail="No active session.")
    _attach_ws(session)
    transcript = await _transcribe_input(session, audio, text)
    if session.awaiting:
        return _handle_answer(session, transcript)
    return _handle_interrupt(session, transcript)


# --------------------------------------------------------------------------- session read endpoints


@router.get("/api/voice/session/{sid}")
async def session_status(sid: str):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    return {
        "id": session.id,
        "trace_id": session.trace_id,
        "status": session.status,
        "transcript": session.transcript,
        "reply_text": session.reply_text,
        "error": session.error,
        "steps": session.steps,
        "created_at": session.created_at,
        "finished_at": session.finished_at,
        "awaiting_input": session.awaiting,
        "prompt_text": session.prompt_text,
        "speech_id": session.speech_id,
        "stop_reason": session.stop_reason,
    }


@router.get("/api/voice/session/{sid}/screenshot")
async def session_screenshot(sid: str):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    path = session.dir / "view.png"
    if not path.exists():
        return Response(status_code=204)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/api/voice/session/{sid}/speech")
async def session_speech(sid: str):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    path = session.dir / "speech.wav"
    if not path.exists():
        return Response(status_code=204)
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.get("/api/voice/session/{sid}/audio")
async def session_audio(sid: str):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    path = session.dir / "reply.wav"
    if not path.exists():
        return Response(status_code=204)
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- WebSocket transport


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """Live audio: browser PCM -> Gnani STT stream; transcripts routed; TTS streamed back."""
    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send_json(payload: dict) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    pending_texts: list[str] = []
    debounce_task: asyncio.Task | None = None

    async def _route_transcript(text: str) -> None:
        session = _active_session()
        if session is None:
            session = _new_session()
            session.ws_send = send_json
            session.task = asyncio.create_task(_run_command(session, None, text))
            await send_json({"type": "session", "session_id": session.id})
            return
        session.ws_send = send_json
        if session.awaiting:
            _handle_answer(session, text)
        else:
            _handle_interrupt(session, text)

    async def _flush_after_debounce() -> None:
        try:
            await asyncio.sleep(TRANSCRIPT_DEBOUNCE_S)
        except asyncio.CancelledError:
            return
        text = " ".join(part for part in pending_texts if part).strip()
        pending_texts.clear()
        if text:
            await _route_transcript(text)

    def _schedule_flush() -> None:
        nonlocal debounce_task
        if debounce_task is not None:
            debounce_task.cancel()
        debounce_task = asyncio.create_task(_flush_after_debounce())

    async def on_transcript(message: dict) -> None:
        text = (message.get("text") or "").strip()
        if not text:
            return
        await send_json({"type": "transcript", "text": text, "latency": message.get("latency")})
        pending_texts.append(text)
        _schedule_flush()

    async def on_processing(_message: dict) -> None:
        await send_json({"type": "processing"})

    stt_stream = streaming.SttStream(on_transcript=on_transcript, on_processing=on_processing)
    try:
        await stt_stream.connect()
    except Exception as exc:  # noqa: BLE001
        await send_json({"type": "error", "message": f"STT stream failed: {exc}"})
        await websocket.close()
        return

    global _latest_ws_send
    _latest_ws_send = send_json
    buffer = bytearray()
    recording = False
    try:
        await send_json({"type": "connected"})
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                if recording:
                    buffer.extend(data)
                    while len(buffer) >= streaming.FRAME_BYTES:
                        frame = bytes(buffer[: streaming.FRAME_BYTES])
                        del buffer[: streaming.FRAME_BYTES]
                        try:
                            await stt_stream.send_audio(frame)
                        except Exception:  # noqa: BLE001 — upstream died; let the browser reconnect
                            await send_json({"type": "error", "message": "STT stream lost; reconnect"})
                            return
                continue
            raw = message.get("text")
            if raw is None:
                continue
            try:
                command = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = command.get("type")
            if kind == "start":
                recording = True
                buffer.clear()
            elif kind == "stop":
                recording = False
                if buffer:
                    padded = bytes(buffer) + bytes(streaming.FRAME_BYTES - len(buffer))
                    await stt_stream.send_audio(padded)
                    buffer.clear()
                # real silence at cadence lets VAD close the segment
                await stt_stream.send_silence()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        events.log_event("ws", "ws.error", error=str(exc))
    finally:
        if debounce_task is not None:
            debounce_task.cancel()
        for session in SESSIONS.values():
            if session.ws_send is send_json:
                session.ws_send = None
        if _latest_ws_send is send_json:
            _latest_ws_send = None
        await stt_stream.close()
