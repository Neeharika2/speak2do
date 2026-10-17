"""The one list of form fields the agent knows.

Everything else derives from here: which profile key a page label means, which keys
are secrets, which answers are always confirmed, which keys voice may edit.
Spoken field names live in the language files (app/lang/<code>.json "labels" /
"field_words"); this file only knows the English words used in page labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label_words: tuple[str, ...]  # whole words in a page label that identify this field
    login: bool = False           # supplied from config by the executor, never asked
    secret: bool = False          # never logged, spoken, or sent to a model
    confirm: bool = False         # always read back for a yes/no (spelling matters)
    not_with: tuple[str, ...] = ()  # label words that mean some other field


# Order matters: the first match wins, so specific fields come before generic ones
# ("College name" is college, not full_name; "One time password" is otp, not password).
FIELDS: tuple[Field, ...] = (
    Field("user_id", ("user id", "userid", "username", "user name"), login=True),
    Field("otp", ("otp", "one time"), login=True, secret=True),
    Field("password", ("password",), login=True, secret=True),
    Field("email", ("email", "e mail"), confirm=True),
    Field("phone", ("mobile", "phone"), confirm=True),
    Field("dob", ("date of birth", "dob", "birth date"), confirm=True),
    Field("gender", ("gender",)),
    Field("college", ("college",)),
    Field("course", ("course",)),
    Field("year", ("year",)),
    Field("marks", ("marks", "percentage")),
    Field("address", ("address",)),
    Field("city", ("city", "village")),
    Field("district", ("district",)),
    Field("state", ("state",)),
    Field("pin", ("pin", "pincode", "postal")),
    Field("full_name", ("full name", "name"), confirm=True,
          not_with=("father", "mother", "guardian", "parent", "spouse", "husband", "wife", "nominee")),
)

BY_KEY = {field.key: field for field in FIELDS}
PROFILE_KEYS = [field.key for field in FIELDS if not field.login]  # what the user is asked for
CONFIRM_KEYS = {field.key for field in FIELDS if field.confirm}


def _words(label: str) -> str:
    """'One-time password (OTP)' -> 'one time password otp'."""
    return " ".join(re.findall(r"[a-z0-9]+", label.lower()))


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def for_label(label: str) -> Field | None:
    """The field a page label means, or None (unknown fields are asked by their label)."""
    text = _words(label)
    for field in FIELDS:
        if any(_has(text, word) for word in field.label_words):
            if any(_has(text, word) for word in field.not_with):
                return None  # "Father name" is not the applicant's name
            return field
    return None


def key_for(label: str) -> str | None:
    field = for_label(label)
    return field.key if field else None
