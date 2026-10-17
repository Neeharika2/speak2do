#!/usr/bin/env python3
"""UI check for the agent-led conversation: Start -> agent asks -> hands-free mic -> Stop.

The Start button sends {"type": "begin"} over /ws/voice; the server replies with
{"type": "session"} and the page must bind to it so status, prompts, steps and the
live view keep updating. The mic streams continuously (muted while the agent talks).

Uses Chromium's fake audio capture as the microphone, so no real mic is needed.

Prereqs:
    BASE_URL=http://127.0.0.1:8765 .venv/bin/uvicorn app.main:app --port 8765
Run:
    BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/voice_ws_ui_check.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from playwright.async_api import async_playwright

import httpx

from app import config
from app.voice import tts
from app.voice.streaming import pcm_to_wav, read_wav_pcm

PHRASE = "నమస్తే, ఇది ఒక వెబ్ సాకెట్ పరీక్ష."
MIC_WAV = config.DATA_DIR / "voice_ws_ui_check.wav"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def fake_mic_wav() -> Path:
    """Synthesize the test phrase and save it for Chromium's fake audio device."""
    if not MIC_WAV.exists():
        result = await tts.speak(PHRASE)
        pcm, rate = read_wav_pcm(result["path"])
        MIC_WAV.write_bytes(pcm_to_wav(pcm, rate))
    return MIC_WAV


async def main() -> int:
    mic = await fake_mic_wav()

    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(f"{config.BASE_URL}/portal/__reset")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                f"--use-file-for-fake-audio-capture={mic}",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = await browser.new_context(permissions=["microphone"])
        page = await context.new_page()
        await page.goto(f"{config.BASE_URL}/assistant", wait_until="domcontentloaded")
        check("page loaded", await page.is_visible("#start-button"))
        await page.wait_for_function("window.__wsReady === true", timeout=15_000)

        # ---- Start: the agent leads; the mic is hands-free (no tap per turn)
        await page.click("#start-button")
        try:  # the label flips once mic permission resolves
            await page.wait_for_function(
                "document.getElementById('start-button').textContent.includes('Stop')", timeout=10_000
            )
        except Exception:  # noqa: BLE001 — surfaced as a failed check below
            pass
        label = (await page.inner_text("#start-button")).strip()
        check("start button turns into stop", "Stop" in label, label)
        try:
            await page.wait_for_function(
                "document.getElementById('status').dataset.state === 'awaiting'", timeout=90_000
            )
            asked = True
        except Exception:  # noqa: BLE001 — surfaced as a failed check below
            asked = False
        prompt = (await page.inner_text("#reply-text")).strip()
        check("agent asks the first question by itself", asked, prompt[:60])
        ws_audio = await page.evaluate("window.__wsAudioCount || 0")
        check("agent speech streamed to the page", ws_audio > 0, str(ws_audio))

        # the fake mic loops PHRASE; once the agent stops talking it is heard as the answer
        try:
            await page.wait_for_function(
                "document.getElementById('transcript').textContent.includes('పరీక్ష')", timeout=45_000
            )
            heard = True
        except Exception:  # noqa: BLE001
            heard = False
        transcript = (await page.inner_text("#transcript")).strip()
        check("hands-free mic heard the user", heard, transcript[:60])

        # ---- Stop button halts the run
        await page.click("#start-button")
        state = ""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = await page.get_attribute("#status", "data-state") or ""
            if state in ("done", "error"):
                break
            await page.wait_for_timeout(300)
        label = (await page.inner_text("#start-button")).strip()
        check("stop button ends the run", state == "done" and "Start" in label, f"{state} / {label}")

        # ---- updated fields panel: a mid-run correction must show up
        await page.fill("#text-fallback", "Scholarship application cheyyi")
        await page.click("#text-send")
        await page.wait_for_function(
            "['running','awaiting','speaking'].includes(document.getElementById('status').dataset.state)",
            timeout=45_000,
        )
        await page.fill("#text-fallback", "నా పేరు నిహారిక")
        await page.click("#text-send")
        try:
            await page.wait_for_function(
                "document.getElementById('updated').textContent.includes('నిహారిక')", timeout=30_000
            )
            updated_text = (await page.inner_text("#updated")).strip()
        except Exception:  # noqa: BLE001 — surfaced as a failed check below
            updated_text = (await page.inner_text("#updated")).strip()
        check("updated fields panel shows the correction", "Name: నిహారిక" in updated_text, updated_text[:60])

        await page.fill("#text-fallback", "ఆగు")  # stop the run cleanly
        await page.click("#text-send")
        try:
            await page.wait_for_function(
                "document.getElementById('status').dataset.state === 'done'", timeout=60_000
            )
        except Exception:  # noqa: BLE001
            pass
        await browser.close()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} ws UI checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
