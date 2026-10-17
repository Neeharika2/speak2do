"""Deterministic field values for the agent (profile mapping first, executor secrets).

Jev chooses *which* field to fill; this module supplies *what* to put in it.
Secrets (password, OTP) are supplied here and never sent to the model.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import config
from app.agent import fields

DEMO_PROFILE = config.REPO_ROOT / "profile" / "demo_profile.json"


def load_profile(path: str | Path | None = None) -> dict:
    """Known user values. No path (the default) = empty: the agent asks for everything."""
    path = path if path is not None else config.AGENT_PROFILE
    if not path:
        return {}
    path = Path(path)
    if not path.is_absolute():
        path = config.REPO_ROOT / path
    return json.loads(path.read_text(encoding="utf-8"))

LOGIN_VALUES = {
    "user_id": lambda: config.PORTAL_TEST_USER,
    "password": lambda: config.PORTAL_TEST_PASSWORD,
    "otp": lambda: config.PORTAL_TEST_OTP,
}


def mapped_value(label: str, profile: dict) -> str | None:
    """Return the value for a field label, or None if unknown."""
    field = fields.for_label(label)
    if field is None:
        return None
    if field.login:
        return LOGIN_VALUES[field.key]()
    value = profile.get(field.key)
    return str(value) if value is not None else None


def label_key(label: str) -> str | None:
    """Which profile key does this field label correspond to?"""
    return fields.key_for(label)


def is_secret(label: str) -> bool:
    field = fields.for_label(label)
    return bool(field and field.secret)


def display_value(label: str, value: str) -> str:
    """Redact secrets for logs and agent-visible step labels."""
    return "[REDACTED]" if is_secret(label) else value
