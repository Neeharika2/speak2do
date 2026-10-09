"""Deterministic field values for the agent (profile mapping first, executor secrets).

Jev chooses *which* field to fill; this module supplies *what* to put in it.
Secrets (password, OTP) are supplied here and never sent to the model.
"""

from __future__ import annotations

from app import config

# Specific labels first so generic keys ("name") cannot steal "college name".
MAPPINGS: list[tuple[tuple[str, ...], str]] = [
    (("user id", "userid", "username"), "user_id"),
    (("password",), "password"),
    (("one-time", "otp"), "otp"),
    (("email",), "email"),
    (("mobile", "phone"), "phone"),
    (("date of birth", "dob"), "dob"),
    (("gender",), "gender"),
    (("college",), "college"),
    (("course",), "course"),
    (("year",), "year"),
    (("marks",), "marks"),
    (("address",), "address"),
    (("city", "village"), "city"),
    (("district",), "district"),
    (("state",), "state"),
    (("pin", "postal"), "pin"),
    (("full name", "name"), "full_name"),
]

SECRET_KEYS = {"password", "otp"}


def mapped_value(label: str, profile: dict) -> str | None:
    """Return the value for a field label, or None if unknown."""
    text = label.lower()
    for keywords, key in MAPPINGS:
        if any(word in text for word in keywords):
            if key == "user_id":
                return config.PORTAL_TEST_USER
            if key == "password":
                return config.PORTAL_TEST_PASSWORD
            if key == "otp":
                return config.PORTAL_TEST_OTP
            if key in profile:
                return str(profile[key])
            return None
    return None


def is_secret(label: str) -> bool:
    text = label.lower()
    return any(word in text for word in ("password", "one-time", "otp"))


def display_value(label: str, value: str) -> str:
    """Redact secrets for logs and agent-visible step labels."""
    return "[REDACTED]" if is_secret(label) else value
