"""Voice app API: push-to-talk command -> STT -> agent flow -> TTS reply.

MVP shape: one task at a time. The page polls session state and the latest
live-view frame (~1 Hz), so no WebSocket yet (plan section 3 marks it as the target).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from app import config, events
from app.agent.demo_flow import run_application_flow
from app.voice import stt, tts

router = APIRouter()
templates = Jinja2Templates(directory=str(config.REPO_ROOT / "app" / "templates"))

SESSIONS_DIR = config.DATA_DIR / "sessions"
SESSIONS: dict[str, dict] = {}
ACTIVE_STATES = {"queued", "transcribing", "running", "speaking"}

REPLY_DONE = "Login అయింది. పేరు మరియు ఫోన్ నంబర్ ఫారమ్‌లో నింపాను."
REPLY_EMPTY = "క్షమించండి, వినిపించలేదు. మళ్ళీ చెప్పండి."


def _active_session() -> dict | None:
    for session in SESSIONS.values():
        if session["status"] in ACTIVE_STATES:
            return session
    return None


def _new_session() -> dict:
    sid = f"s_{uuid.uuid4().hex[:10]}"
    session_dir = SESSIONS_DIR / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    session = {
        "id": sid,
        "trace_id": events.new_trace_id(),
        "status": "queued",
        "transcript": "",
        "reply_text": "",
        "error": None,
        "steps": [],
        "dir": session_dir,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "finished_at": None,
        "task": None,
    }
    SESSIONS[sid] = session
    return session


async def _speak_reply(session: dict, text: str) -> None:
    session["status"] = "speaking"
    session["reply_text"] = text
    result = await tts.speak(text, out_dir=session["dir"])
    Path(result["path"]).replace(session["dir"] / "reply.wav")
    events.log_event(session["trace_id"], "tts.reply", duration_ms=result["latency_ms"])


async def _run_command(session: dict, audio_path: Path | None, text: str | None) -> None:
    trace_id = session["trace_id"]
    try:
        if text is not None:
            transcript = text.strip()
            events.log_event(trace_id, "text.command", transcript=transcript)
        else:
            session["status"] = "transcribing"
            result = await stt.transcribe(audio_path)
            transcript = result["transcript"].strip()
            events.log_event(trace_id, "stt.command", duration_ms=result["latency_ms"], transcript=transcript)
        session["transcript"] = transcript

        if not transcript:
            await _speak_reply(session, REPLY_EMPTY)
        else:
            session["status"] = "running"
            await run_application_flow(trace_id, live_dir=session["dir"], on_step=session["steps"].append)
            await _speak_reply(session, REPLY_DONE)

        session["status"] = "done"
        session["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        events.log_event(trace_id, "done", ok=True)
    except Exception as exc:  # noqa: BLE001 — surface to the page
        session["status"] = "error"
        session["error"] = f"{type(exc).__name__}: {exc}"
        events.log_event(trace_id, "error", error=session["error"])


@router.get("/assistant", response_class=HTMLResponse)
async def assistant_page(request: Request):
    return templates.TemplateResponse(request, "assistant.html", {"title": "Voice Assistant"})


@router.post("/api/voice/command")
async def voice_command(audio: UploadFile):
    if _active_session():
        raise HTTPException(status_code=409, detail="The agent is already busy with another task.")
    session = _new_session()
    audio_path = session["dir"] / "command.wav"
    audio_path.write_bytes(await audio.read())
    events.log_event(session["trace_id"], "audio.received", bytes=audio_path.stat().st_size)
    session["task"] = asyncio.create_task(_run_command(session, audio_path, None))
    return {"session_id": session["id"]}


@router.post("/api/voice/text")
async def voice_text(text: str = Form(...)):
    if _active_session():
        raise HTTPException(status_code=409, detail="The agent is already busy with another task.")
    session = _new_session()
    session["task"] = asyncio.create_task(_run_command(session, None, text))
    return {"session_id": session["id"]}


@router.get("/api/voice/session/{sid}")
async def session_status(sid: str):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    return {
        "id": session["id"],
        "trace_id": session["trace_id"],
        "status": session["status"],
        "transcript": session["transcript"],
        "reply_text": session["reply_text"],
        "error": session["error"],
        "steps": session["steps"],
        "created_at": session["created_at"],
        "finished_at": session["finished_at"],
    }


@router.get("/api/voice/session/{sid}/screenshot")
async def session_screenshot(sid: str):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    path = session["dir"] / "view.png"
    if not path.exists():
        return Response(status_code=204)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/api/voice/session/{sid}/audio")
async def session_audio(sid: str):
    session = SESSIONS.get(sid)
    if not session:
        raise HTTPException(status_code=404, detail="unknown session")
    path = session["dir"] / "reply.wav"
    if not path.exists():
        return Response(status_code=204)
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})
