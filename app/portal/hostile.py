"""Hostile-mode toggles for the mock portal (plan §2.5).

Enabled via env ``PORTAL_HOSTILE=a,b`` (server baseline) and/or the cookie set by
``GET /portal/hostile?toggles=a,b``. Toggles used in M2/M4/M5 tests:

slow, popup, inject_dom, inject_img, captcha, expiry, layout, dup_trap
"""

from __future__ import annotations

import os

from fastapi import Request

TOGGLES = {"slow", "popup", "inject_dom", "inject_img", "captcha", "expiry", "layout", "dup_trap"}
SLOW_DELAY_S = float(os.environ.get("PORTAL_SLOW_DELAY_S", "2.0"))


def active(request: Request) -> set[str]:
    toggles: set[str] = set()
    for source in (os.environ.get("PORTAL_HOSTILE", ""), request.cookies.get("portal_hostile", "")):
        toggles |= {item.strip() for item in source.split(",") if item.strip()}
    return toggles & TOGGLES


def has(request: Request, toggle: str) -> bool:
    return toggle in active(request)
