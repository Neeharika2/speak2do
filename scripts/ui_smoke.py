#!/usr/bin/env python3
"""Headless UI check for the voice app.

Opens /assistant in a real browser, uses the text fallback, and verifies the whole
loop: agent flow runs, live-view frame arrives, and the spoken reply is available.

Prereqs:
    .venv/bin/uvicorn app.main:app --port 8765     # in another terminal
Run:
    .venv/bin/python scripts/ui_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
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

        await page.fill("#text-fallback", "Scholarship application login cheyyi")
        await page.click("#text-send")

        await page.wait_for_function("document.getElementById('status').dataset.state === 'done'", timeout=90_000)
        await page.wait_for_function("document.getElementById('live').naturalWidth > 0", timeout=10_000)
        await page.wait_for_function("document.getElementById('reply-audio').getAttribute('src') !== null", timeout=10_000)

        transcript = (await page.inner_text("#transcript")).strip()
        reply = (await page.inner_text("#reply-text")).strip()
        live_ok = await page.evaluate("document.getElementById('live').naturalWidth > 0")
        audio_src = await page.get_attribute("#reply-audio", "src")
        steps = await page.eval_on_selector_all("#steps li", "els => els.map(e => e.textContent)")

        print("transcript:", transcript)
        print("reply:", reply)
        print("steps:", len(steps))
        print("live view frame loaded:", live_ok)
        print("reply audio:", audio_src)

        await browser.close()
        if live_ok and audio_src and steps:
            print("\nUI SMOKE PASSED")
            return 0
        print("\nUI SMOKE FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
