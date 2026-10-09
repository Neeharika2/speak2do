"""Jev (TypeSafe System One) client — bounded Choice/Noul/Score decisions.

Jev is a decision model, not a browser driver (see docs/m0_vendor_status.md):
our loop owns observation and execution; Jev selects from a bounded candidate set.
"""

from __future__ import annotations

import httpx

from app import config


async def decide(state: str | dict | list, questions: dict, *, model: str = "jev-latest") -> dict:
    """Ask one or more typed questions about a state; returns the answers payload."""
    if not config.JEV_API_KEY:
        raise RuntimeError("JEV_API_KEY is not set")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            config.TYPESAFE_URL,
            headers={"Authorization": f"Bearer {config.JEV_API_KEY}"},
            json={"model": model, "state": state, "questions": questions},
        )
    response.raise_for_status()
    return response.json()
