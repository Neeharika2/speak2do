#!/usr/bin/env python3
"""UI check for voice-started runs (M4): mic -> STT -> session binding in the page.

Regression guard: when a run is started by voice over /ws/voice, the server
sends {"type": "session"}; the page must bind to it so status, reply text,
steps and the live view keep updating (before the fix the page stayed at
"Transcribing…" forever and showed no reply).

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
        check("page loaded", await page.is_visible("#talk-button"))
        await page.wait_for_function("window.__wsReady === true", timeout=15_000)

        await page.click("#talk-button")  # tap to start listening
        await page.wait_for_timeout(300)
        recording_label = (await page.inner_text("#talk-button")).strip()
        await page.wait_for_timeout(4700)  # let the fake mic speak
        await page.click("#talk-button")  # tap again to send
        check("click toggles the talk button", "Tap to send" in recording_label, recording_label)

        state = ""
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = await page.get_attribute("#status", "data-state") or ""
            if state in ("done", "error"):
                break
            await page.wait_for_timeout(300)

        transcript = (await page.inner_text("#transcript")).strip()
        reply = (await page.inner_text("#reply-text")).strip()
        ws_audio = await page.evaluate("window.__wsAudioCount || 0")
        steps = await page.eval_on_selector_all("#steps li", "els => els.length")

        check("voice run finished (page kept polling)", state == "done", state)
        check("ws transcript shown", "పరీక్ష" in transcript, transcript[:60])
        check("reply shown in the page", "scholarship application" in reply, reply[:60])
        check("tts audio streamed to the page", ws_audio > 0, str(ws_audio))
        check("unrelated command ran no agent steps", steps == 0, str(steps))

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
