"""Turn a spoken answer into a valid value for one form field.

Each field gets a spec from the page itself (select options, input type, pattern,
maxlength, min/max), so this works for any form, not just the mock portal.

Order: fast deterministic rules for clear answers (numerals, ISO dates, "x at y dot
com", exact option names, plain English text); otherwise the LLM extracts the value
from the utterance in any language and writes it in English letters. Every result
is validated against the field spec before it is used — the LLM proposes, the
validators decide.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from app import events
from app.agent import readback, values
from app.voice import intent_llm

LLM_TIMEOUT_S = 6.0
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


@dataclass
class FieldSpec:
    label: str
    kind: str                      # text | digits | number | date | email | option
    key: str | None = None         # profile key (full_name, phone, ...) when known
    options: list[str] = field(default_factory=list)
    min_len: int = 1
    max_len: int = 100
    min_val: float | None = None
    max_val: float | None = None


@dataclass
class Parsed:
    value: str | None
    confident: bool = False
    source: str = "none"           # rules | llm | none


# --------------------------------------------------------------------------- field spec


def _int(text: str) -> int | None:
    return int(text) if text and text.isdigit() else None


def _float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def field_spec(element: dict, options: list[str] | None = None) -> FieldSpec:
    """Describe a page element as a field to ask for."""
    label = element.get("label") or ""
    key = values.label_key(label)
    c = element.get("constraints") or {}
    etype = (element.get("type") or "").lower()
    spec = FieldSpec(label=label, kind="text", key=key)
    if options or element.get("tag") == "select":
        spec.kind, spec.options = "option", list(options or [])
        return spec
    if etype == "date":
        spec.kind = "date"
        return spec
    if etype == "email" or key == "email":
        spec.kind = "email"
        return spec
    if etype == "number":
        spec.kind = "number"
        spec.min_val, spec.max_val = _float(c.get("min", "")), _float(c.get("max", ""))
        return spec
    digit_pattern = re.fullmatch(r"(?:\[0-9\]|\\d)\{(\d+)(?:,(\d+))?\}", c.get("pattern", ""))
    if digit_pattern or c.get("inputmode") == "numeric" or etype == "tel":
        spec.kind = "digits"
        if digit_pattern:
            spec.min_len = int(digit_pattern.group(1))
            spec.max_len = int(digit_pattern.group(2) or digit_pattern.group(1))
        else:
            spec.min_len = _int(c.get("minlength", "")) or 1
            spec.max_len = _int(c.get("maxlength", "")) or 20
        return spec
    spec.min_len = _int(c.get("minlength", "")) or 1
    spec.max_len = _int(c.get("maxlength", "")) or 100
    return spec


# --------------------------------------------------------------------------- validation


def validate(spec: FieldSpec, value: object) -> str | None:
    """Return the canonical value if it fits the field, else None."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if spec.kind == "option":
        return next((o for o in spec.options if o.lower() == text.lower()), None)
    if spec.kind == "digits":
        digits = re.sub(r"[\s-]", "", text)
        return digits if digits.isdigit() and spec.min_len <= len(digits) <= spec.max_len else None
    if spec.kind == "number":
        number = _float(text)
        if number is None:
            return None
        if (spec.min_val is not None and number < spec.min_val) or (
            spec.max_val is not None and number > spec.max_val
        ):
            return None
        return str(int(number)) if number.is_integer() else str(number)
    if spec.kind == "date":
        try:
            day = dt.date.fromisoformat(text)
        except ValueError:
            return None
        return day.isoformat() if 1900 <= day.year and day <= dt.date.today() else None
    if spec.kind == "email":
        email = text.lower().replace(" ", "")
        return email if re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}", email) else None
    # free text
    if readback.parse_yes_no(text) is not None and len(text.split()) <= 2:
        return None  # "yes" / "no" is not a name or an address
    if not (spec.min_len <= len(text) <= spec.max_len):
        return None
    return text.title() if text.isascii() and text == text.lower() else text


# --------------------------------------------------------------------------- deterministic rules


def _rule_date(text: str) -> str | None:
    t = readback.normalize_text(text)
    ymd = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", t)
    if ymd:
        year, month, day = ymd.groups()
    else:
        dmy = re.search(r"\b(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})\b", t)
        named = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,})\.?,?\s+(\d{4})\b", t)
        named_us = re.search(r"\b([a-z]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", t)
        if dmy:
            day, month, year = dmy.groups()
        elif named or named_us:
            if named:
                day, name, year = named.groups()
            else:
                name, day, year = named_us.groups()
            month = next((str(i + 1) for i, m in enumerate(MONTHS) if m.startswith(name[:3])), None)
            if month is None:
                return None
        else:
            return None
    try:
        return dt.date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _rule_email(text: str) -> tuple[str | None, bool]:
    t = readback.normalize_text(text)
    t = re.sub(r"\s*\b(?:at the rate(?: of)?|at)\b\s*", "@", t)
    t = re.sub(r"\s*\b(?:dot)\b\s*", ".", t)
    t = re.sub(r"\s*\bunderscore\b\s*", "_", t)
    t = re.sub(r"\s*([@.])\s*", r"\1", t)
    match = re.search(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}", t)
    if not match:
        return None, False
    return match.group(0), match.group(0) == t  # confident only if the email was all they said


_LEAD_IN = re.compile(r"^(?:(?:my|our|the|his|her)\s+)?(?:[\w-]+\s+){0,3}?(?:is|are|it's|its|i am|i'm)\s+(.+)$")


def _rule_text(text: str) -> str | None:
    """Plain English answers: drop a short lead-in ("my name is ...") and keep the value's case."""
    stripped = " ".join(text.split()).strip(" .,!?")
    if not stripped or not stripped.isascii() or readback._mentions_negation(stripped):
        return None
    lead = _LEAD_IN.match(stripped.lower())
    if lead:
        stripped = stripped[len(stripped) - len(lead.group(1)):]
    stripped = re.sub(r"\s+(?:please|only)$", "", stripped, flags=re.I)
    return stripped or None


def _rules(spec: FieldSpec, utterance: str) -> Parsed:
    if spec.kind == "option":
        match = readback.match_option(utterance, spec.options)
        return Parsed(match, True, "rules") if match else Parsed(None)
    if spec.kind == "digits":
        value = validate(spec, readback.parse_digits(readback.normalize_text(utterance)))
        return Parsed(value, True, "rules") if value else Parsed(None)
    if spec.kind == "number":
        numbers = re.findall(r"\d+(?:\.\d+)?", utterance)  # numerals only: "eighty one" goes to the LLM
        value = validate(spec, numbers[0]) if len(numbers) == 1 else None
        return Parsed(value, True, "rules") if value else Parsed(None)
    if spec.kind == "date":
        value = validate(spec, _rule_date(utterance))
        return Parsed(value, True, "rules") if value else Parsed(None)
    if spec.kind == "email":
        email, whole = _rule_email(utterance)
        value = validate(spec, email)
        return Parsed(value, whole, "rules") if value else Parsed(None)
    value = validate(spec, _rule_text(utterance))
    return Parsed(value, True, "rules") if value else Parsed(None)


# --------------------------------------------------------------------------- LLM extraction

_KIND_RULES = {
    "text": "the value in English (Latin) letters — transliterate names and places from any Indian "
            "script (e.g. 'సీత దేవి' -> 'Sita Devi'); normal capitalisation; keep house numbers",
    "digits": "digits only (convert number words in any language to digits, e.g. 'తొమ్మిది' -> 9)",
    "number": "a plain number (convert number words in any language, e.g. 'ఎనభై ఒకటి' -> 81)",
    "date": "the date as YYYY-MM-DD (month names and numbers may be spoken in any language)",
    "email": "the email address in lowercase with @ and dots, no spaces",
    "option": "exactly one of the allowed options (match meaning in any language, e.g. 'ఆడ' / "
              "'महिला' -> Female), or null",
}


def _llm_prompt(spec: FieldSpec, utterance: str) -> str:
    lines = [
        "You fill ONE field of an English web form from a user's spoken answer. The answer is "
        "speech-to-text output in any Indian language or English, possibly in native script.",
        f'Field label: "{spec.label}"',
        f"Return: {_KIND_RULES[spec.kind]}.",
    ]
    if spec.options:
        lines.append(f"Allowed options: {spec.options}")
    if spec.kind == "digits":
        lines.append(f"Length: {spec.min_len}-{spec.max_len} digits.")
    lines += [
        "Return only the value, never a sentence (drop lead-ins like 'my name is').",
        "If the answer does not contain a value for this field (e.g. only 'yes', a question, noise), "
        "value must be null.",
        'Set "confident" to false if you are unsure of the meaning or the spelling.',
        f'Spoken answer: "{utterance}"',
        'Reply with JSON only: {"value": "..." or null, "confident": true or false}',
    ]
    return "\n".join(lines)


async def _llm_extract(spec: FieldSpec, utterance: str) -> dict | None:
    """Provider call (tests replace this)."""
    return await intent_llm.complete_json(_llm_prompt(spec, utterance), LLM_TIMEOUT_S)


async def _llm(spec: FieldSpec, utterance: str, trace_id: str) -> Parsed:
    try:
        data = await _llm_extract(spec, utterance)
    except Exception as exc:  # noqa: BLE001 — extraction must never break the run
        events.log_event(trace_id, "voice.answer_llm_error", error=f"{type(exc).__name__}: {exc}")
        return Parsed(None)
    if not isinstance(data, dict):
        return Parsed(None)
    value = validate(spec, data.get("value"))
    if value is None:
        return Parsed(None)
    confident = data.get("confident") is True and (spec.kind != "text" or value.isascii())
    return Parsed(value, confident, "llm")


# --------------------------------------------------------------------------- entry points


async def parse_answer(spec: FieldSpec, utterance: str, *, trace_id: str = "") -> Parsed:
    """Best valid value for the field from one utterance (value None = ask again)."""
    utterance = (utterance or "").strip()
    parsed = Parsed(None)
    if utterance:
        parsed = _rules(spec, utterance)
        if parsed.value is None:
            parsed = await _llm(spec, utterance, trace_id)
        if parsed.value is None and spec.kind == "text":
            # no LLM available: keep the spoken words (native script), but confirm them
            value = validate(spec, readback.clean_text_value(utterance))
            parsed = Parsed(value, False, "rules") if value else Parsed(None)
    events.log_event(
        trace_id or "voice", "voice.answer_parsed", field=spec.key or spec.label, kind=spec.kind,
        utterance=utterance, value=parsed.value, confident=parsed.confident, source=parsed.source,
    )
    return parsed


def spoken(spec: FieldSpec, value: str) -> str:
    """How to say a value back to the user."""
    if spec.kind == "digits":
        return readback.spoken_digits(value)
    if spec.kind == "date":
        day = dt.date.fromisoformat(value)
        return f"{day.day} {MONTHS[day.month - 1].title()} {day.year}"
    return value


def hint(spec: FieldSpec) -> str:
    """Extra guidance when an answer could not be used (Telugu for now; languages in step 3)."""
    if spec.kind == "digits" and spec.min_len == spec.max_len:
        return f" {spec.min_len} అంకెలు చెప్పండి."
    if spec.kind == "date":
        return " రోజు, నెల, సంవత్సరం చెప్పండి."
    if spec.kind == "email":
        return " ఉదాహరణకు: sita at gmail dot com."
    return ""
