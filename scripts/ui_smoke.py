#!/usr/bin/env python3
"""Headless UI check for the voice app (M3: interactive).

Opens /assistant, sends the command via the text fallback, answers read-back /
missing-field prompts, and verifies the whole loop: live-view frame, reply audio,
and a completed agent run.

Prereqs:
    BASE_URL=http://127.0.0.1:8765 .venv/bin/uvicorn app.main:app --port 8765
Run:
    BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/ui_smoke.py
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

from app import config


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"{config.BASE_URL}/assistant", wait_until="domcontentloaded")
        assert await page.is_visible("#talk-button"), "talk button missing"
        assert await page.is_visible("#text-fallback"), "text fallback missing"

        await page.fill("#text-fallback", "Scholarship application cheyyi")
        await page.click("#text-send")

        answered = 0
        state = "queued"
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            state = await page.get_attribute("#status", "data-state") or ""
            if state in ("done", "error"):
                break
            if state == "awaiting":
                prompt = (await page.inner_text("#reply-text")).strip()
                answer = "గుంటూరు" if "District" in prompt else "అవును"
                await page.fill("#text-fallback", answer)
                await page.click("#text-send")
                answered += 1
                await page.wait_for_function(
                    "document.getElementById('status').dataset.state !== 'awaiting'", timeout=30_000
                )
            await asyncio.sleep(0.4)

        await page.wait_for_function("document.getElementById('live').naturalWidth > 0", timeout=15_000)
        await page.wait_for_function(
            "document.getElementById('reply-audio').getAttribute('src') !== null", timeout=15_000
        )

        transcript = (await page.inner_text("#transcript")).strip()
        reply = (await page.inner_text("#reply-text")).strip()
        steps = await page.eval_on_selector_all("#steps li", "els => els.map(e => e.textContent)")
        live_ok = await page.evaluate("document.getElementById('live').naturalWidth > 0")
        audio_src = await page.get_attribute("#reply-audio", "src")

        print("transcript:", transcript)
        print("prompts answered:", answered)
        print("reply:", reply)
        print("steps:", len(steps))
        print("live view frame loaded:", live_ok)
        print("reply audio:", audio_src)

        await browser.close()
        ok = state == "done" and live_ok and bool(audio_src) and len(steps) >= 10 and answered >= 1
        print("\nUI SMOKE PASSED" if ok else "\nUI SMOKE FAILED")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
