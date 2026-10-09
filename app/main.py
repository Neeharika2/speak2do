"""FastAPI entry point: agent API + mock portal in one process (plan section 3)."""

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse

from app.api import voice
from app.portal import db, routes

db.init_db()

app = FastAPI(title="Voice-First Computer-Use Agent")
app.include_router(routes.router, prefix="/portal")
app.include_router(voice.router)


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Front door: the voice assistant (the portal is the agent's target)."""
    return RedirectResponse(url="/assistant")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Keep the console tidy: no favicon yet."""
    return Response(status_code=204)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
