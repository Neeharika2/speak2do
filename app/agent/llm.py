"""Gemini fallback for writing a field value the deterministic mapper cannot supply.

Used only when a field label is unknown; Jev still chooses the action/target.
"""

from __future__ import annotations

import json

import httpx

from app import config


async def suggest_value(label: str, page_path: str, profile: dict) -> str:
    if not config.GEMINI_API_KEY:
        return ""
    prompt = (
        "You are filling a scholarship application form.\n"
        f"Field label: {label}\nPage: {page_path}\n"
        f"Known profile: {json.dumps(profile, ensure_ascii=False)}\n"
        "Reply with ONLY the value to type, no quotes, no explanation."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            url,
            headers={"x-goog-api-key": config.GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
    response.raise_for_status()
    data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"')
    except (KeyError, IndexError, TypeError):
        return ""
