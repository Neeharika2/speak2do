"""Per-language speech: every phrase the agent says and the words it listens for.

One JSON file per language (app/lang/<code>.json, e.g. te-IN.json), so native speakers
can review or fix wording without touching code. Codes match Gnani STT/TTS codes.

- phrases: templates the agent speaks ({label}, {value}, ... placeholders);
  a missing phrase falls back to English.
- labels: field names to say in prompts (keyed by profile key: full_name, phone, ...).
- words: yes / no / stop / repeat lists, digit words (index = digit), digit aliases,
  and field_words used to tell "name" from "phone". English words are always added,
  because people mix English into every Indian language.

Matching rule for word entries: Latin words match whole words; native-script words
match anywhere (Telugu "సరేనా" contains "సరే"), unless the entry starts with "=" —
then it must be a whole word (Hindi "=ना" must not match inside "नाम").
"""

from __future__ import annotations

import functools
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app import config

LANG_DIR = Path(__file__).parent
FALLBACK = "en-IN"


def _nfc(value):
    """Normalise Unicode so STT output and table words compare equal (e.g. Bengali য়)."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc(item) for item in value]
    if isinstance(value, dict):
        return {_nfc(key): _nfc(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class Lang:
    code: str
    name: str            # native name, shown in the picker
    english_name: str
    voice: str
    phrases: dict
    labels: dict
    words: dict

    def say(self, key: str, **values: object) -> str:
        template = self.phrases.get(key) or _load(FALLBACK).phrases[key]
        return template.format(**values)

    def label(self, key: str | None, fallback: str = "") -> str:
        """Spoken name for a field; the page's own label when the key is unknown."""
        if key and key in self.labels:
            return self.labels[key]
        return fallback or key or ""

    def word_list(self, kind: str) -> list[str]:
        words = list(self.words.get(kind, []))
        if self.code != FALLBACK:
            words += [w for w in _load(FALLBACK).words.get(kind, []) if w not in words]
        return words

    def digit_words(self) -> dict[str, str]:
        """Spoken word -> digit, for this language plus English."""
        mapping: dict[str, str] = {}
        sources = [self] if self.code == FALLBACK else [self, _load(FALLBACK)]
        for lang in sources:
            for digit, word in enumerate(lang.words.get("digits", [])):
                mapping.setdefault(word, str(digit))
            for word, digit in lang.words.get("digit_aliases", {}).items():
                mapping.setdefault(word, digit)
        return mapping

    def spoken_digit(self, digit: int) -> str:
        return self.words["digits"][digit].lstrip("=")

    def field_words(self) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}
        sources = [self] if self.code == FALLBACK else [self, _load(FALLBACK)]
        for lang in sources:
            for field, words in lang.words.get("field_words", {}).items():
                merged.setdefault(field, [])
                merged[field] += [w for w in words if w not in merged[field]]
        return merged


@functools.lru_cache(maxsize=None)
def _load(code: str) -> Lang:
    data = _nfc(json.loads((LANG_DIR / f"{code}.json").read_text(encoding="utf-8")))
    return Lang(
        code=code,
        name=data["name"],
        english_name=data["english_name"],
        voice=data.get("voice") or config.DEFAULT_VOICE,
        phrases=data.get("phrases", {}),
        labels=data.get("labels", {}),
        words=data.get("words", {}),
    )


def codes() -> list[str]:
    return sorted(path.stem for path in LANG_DIR.glob("*.json"))


def get(code: str | None = None) -> Lang:
    """The language for a session; unknown or empty codes fall back to the default."""
    code = code or config.DEFAULT_LANGUAGE
    if code not in codes():
        code = config.DEFAULT_LANGUAGE if config.DEFAULT_LANGUAGE in codes() else FALLBACK
    return _load(code)


def available() -> list[Lang]:
    """All languages, default first (for the picker)."""
    langs = [_load(code) for code in codes()]
    return sorted(langs, key=lambda lang: (lang.code != config.DEFAULT_LANGUAGE, lang.english_name))
