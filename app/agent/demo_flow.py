"""M1 application flow: login (password + OTP) and form-1 fill, no submit.

Shared by scripts/walking_skeleton.py (CLI smoke) and the voice app (app/api/voice.py).
Every action goes through policy and is logged with the same trace_id.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from app import config, events, policy
from app.browser.controller import BrowserController

PROFILE_PATH = config.REPO_ROOT / "profile" / "demo_profile.json"
SECRET_SELECTORS = {"#password", "#otp"}


async def _act(
    trace_id: str,
    browser: BrowserController,
    kind: str,
    *,
    selector: str = "",
    value: str = "",
    live_dir: Path | None = None,
    on_step: Callable[[str], None] | None = None,
) -> None:
    decision = policy.decide({"kind": kind, "selector": selector, "value": value})
    if decision.verdict != policy.ALLOW:
        raise RuntimeError(f"policy blocked {kind} {selector}: {decision}")

    started = time.perf_counter()
    if kind == "goto":
        await browser.goto(value)
    elif kind == "fill":
        await browser.fill(selector, value)
    elif kind == "click":
        await browser.click(selector)
    elif kind == "wait_for_url":
        await browser.wait_for_url(value)
    else:
        raise ValueError(f"unsupported action kind: {kind}")

    redacted = selector in SECRET_SELECTORS
    events.log_event(
        trace_id,
        f"action.{kind}",
        duration_ms=(time.perf_counter() - started) * 1000,
        selector=selector or None,
        policy=decision.verdict,
        value="[REDACTED]" if redacted else (value or None),
    )

    label = kind
    if selector:
        label += f" {selector}"
    if value:
        label += f" = {'[REDACTED]' if redacted else value}"
    if on_step:
        on_step(label)

    if live_dir is not None:
        await browser.screenshot(live_dir / "view.png")


async def run_application_flow(
    trace_id: str,
    *,
    live_dir: Path | None = None,
    on_step: Callable[[str], None] | None = None,
) -> dict:
    """Drive the mock portal: login -> OTP -> dashboard -> form-1 (name + phone)."""
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    events.log_event(trace_id, "intent", intent="login_and_fill_form", note="M1 hardcoded")

    browser = BrowserController(headless=True)
    await browser.start()
    try:

        async def act(kind: str, **kwargs) -> None:
            await _act(trace_id, browser, kind, live_dir=live_dir, on_step=on_step, **kwargs)

        await act("goto", value=f"{config.PORTAL_URL}/login")
        await act("fill", selector="#user_id", value=config.PORTAL_TEST_USER)
        await act("fill", selector="#password", value=config.PORTAL_TEST_PASSWORD)
        await act("click", selector="button[type=submit]")
        await act("wait_for_url", value="**/login/otp")
        await act("fill", selector="#otp", value=config.PORTAL_TEST_OTP)
        await act("click", selector="button[type=submit]")
        await act("wait_for_url", value="**/dashboard")
        await act("click", selector="text=Apply for Scholarship")
        await act("wait_for_url", value="**/form-1")
        await act("fill", selector="#full_name", value=profile["full_name"])
        await act("fill", selector="#phone", value=profile["phone"])

        name_value = await browser.input_value("#full_name")
        phone_value = await browser.input_value("#phone")
        if name_value != profile["full_name"] or phone_value != profile["phone"]:
            raise RuntimeError(f"form verification failed: {name_value!r}, {phone_value!r}")

        events.log_event(trace_id, "verify.form1", full_name=name_value, phone=phone_value)
        if live_dir is not None:
            await browser.screenshot(live_dir / "view.png")
        return {"full_name": name_value, "phone": phone_value}
    finally:
        await browser.stop()
