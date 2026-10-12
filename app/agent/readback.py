"""Telugu read-back and spoken-answer parsing (plan §6).

Rules implemented here:
- digits are read digit by digit, grouped;
- names/values get a confirmation prompt ("సరేనా?");
- yes/no only counts as an answer to an active prompt;
- stop words ("ఆగు" and friends) trigger a hard stop;
- a small glossary maps Telugu-script answers to English portal options.
"""

from __future__ import annotations

import re

DIGIT_WORDS = ["సున్నా", "ఒకటి", "రెండు", "మూడు", "నాలుగు", "ఐదు", "ఆరు", "ఏడు", "ఎనిమిది", "తొమ్మిది"]

YES_WORDS = ["అవును", "అవు", "సరే", "ఓకే", "ఒప్పు", "yes", "ok", "okay", "avunu", "avnu", "sare"]
NO_WORDS = ["కాదు", "వద్దు", "లేదు", "తప్పు", "no", "kadu", "ledu", "vaddu"]
STOP_WORDS = ["ఆగు", "ఆగండి", "ఆపు", "ఆపండి", "ఆపేయి", "stop", "aagu", "agu", "aap"]
REPEAT_WORDS = ["మళ్ళీ", "మళ్లీ", "మరలా", "repeat", "again"]

ENGLISH_DIGITS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

# Correction detection (M3.5): which field is being changed, and change markers.
FIELD_KEYWORDS = {
    "phone": ["ఫోన్", "నంబర్", "నెంబర్", "mobile", "phone", "number"],
    "full_name": ["పేరు", "name"],
    "district": ["జిల్లా", "district"],
}
CHANGE_WORDS = [
    "మారింది", "మారిపోయింది", "మార్చ", "మార్చండి", "కొత్త", "సరిచేయ",
    "change", "changed", "update", "new", "correct",
]
FIELD_LABELS_TE = {"phone": "ఫోన్ నంబర్", "full_name": "పేరు", "district": "జిల్లా"}

# "Is this a request to (continue) the application task?"
INTENT_WORDS = [
    "application", "scholarship", "apply", "form", "fill", "submit", "start", "login",
    "అప్లికేషన్", "స్కాలర్షిప్", "దరఖాస్తు", "ఫారం", "చేయండి", "చేయి", "నింప",
]

# Telugu-script variants for English option values on the portal.
OPTION_ALIASES: dict[str, list[str]] = {
    "Guntur": ["గుంటూరు", "గుంటూర్", "గుంటురు", "guntur"],
    "Krishna": ["కృష్ణా", "కృష్ణ", "krishna"],
    "Kurnool": ["కూర్నూల్", "కర్నూలు", "kurnool"],
    "Visakhapatnam": ["విశాఖపట్నం", "విశాఖ", "visakhapatnam", "vizag"],
    "Hyderabad": ["హైదరాబాద్", "హైదరాబాదు", "hyderabad"],
    "Warangal": ["వరంగల్", "వరంగల్లు", "warangal"],
    "Karimnagar": ["కరీంనగర్", "karimnagar"],
    "Nizamabad": ["నిజామాబాద్", "nizamabad"],
    "Andhra Pradesh": ["ఆంధ్రప్రదేశ్", "ఆంధ్ర ప్రదేశ్", "ఆంధ్ర", "andhra pradesh", "andhra"],
    "Telangana": ["తెలంగాణ", "తెలంగాణా", "telangana"],
}

DISTRICT_OPTIONS = [name for name in OPTION_ALIASES if name not in ("Andhra Pradesh", "Telangana")]

READBACK_REJECTED = "సరే, ఆపుతున్నాను. వివరాలు సరిచేసి మళ్ళీ ప్రయత్నించండి."


def normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def spoken_digits(value: str) -> str:
    """Read digits digit-by-digit, grouped in two halves (plan §6)."""
    words = [DIGIT_WORDS[int(ch)] for ch in str(value) if ch.isdigit()]
    if not words:
        return str(value)
    if len(words) <= 2:
        return " ".join(words)
    mid = (len(words) + 1) // 2
    return f"{' '.join(words[:mid])}, {' '.join(words[mid:])}"


def name_phone_prompt(name: str, phone: str) -> str:
    return f"మీ పేరు {name}, ఫోన్ నంబర్ {spoken_digits(phone)}. సరేనా?"


def options_prompt(label: str, options: list[str]) -> str:
    return f"{label} చెప్పండి. ఎంపికలు: {', '.join(options)}."


def value_prompt(label: str) -> str:
    return f"{label} చెప్పండి."


def parse_yes_no(text: str) -> bool | None:
    """True = yes, False = no, None = unclear (must re-ask)."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    if any(word in normalized for word in NO_WORDS):
        return False
    if any(word in normalized for word in YES_WORDS):
        return True
    return None


def is_stop(text: str) -> bool:
    normalized = normalize_text(text)
    return any(word in normalized for word in STOP_WORDS)


def is_repeat(text: str) -> bool:
    normalized = normalize_text(text)
    return any(word in normalized for word in REPEAT_WORDS)


def match_option(text: str, options: list[str]) -> str | None:
    """Match a spoken answer to one of the portal's option labels (glossary-aware)."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    for option in options:
        if normalize_text(option) == normalized:
            return option
    for option in options:
        for alias in OPTION_ALIASES.get(option, []):
            if alias.lower() in normalized:
                return option
    for option in options:
        candidate = normalize_text(option)
        if candidate and (candidate in normalized or normalized in candidate):
            return option
    return None


def parse_digits(text: str) -> str:
    """Extract a digit string from Telugu digit words, English words, or numerals."""
    found: list[tuple[int, str]] = []
    for index, word in enumerate(DIGIT_WORDS):
        start = 0
        while True:
            position = text.find(word, start)
            if position == -1:
                break
            found.append((position, str(index)))
            start = position + len(word)
    for position, char in enumerate(text):
        if char.isdigit():
            found.append((position, char))
    for match in re.finditer(r"[a-z]+", text.lower()):
        token = match.group(0)
        if token in ENGLISH_DIGITS:
            found.append((match.start(), ENGLISH_DIGITS[token]))
    found.sort()
    return "".join(value for _, value in found)


def parse_field_choice(text: str) -> str | None:
    normalized = normalize_text(text)
    for field, words in FIELD_KEYWORDS.items():
        if any(word in normalized for word in words):
            return field
    return None


def extract_field_value(field: str, text: str) -> str | None:
    """Pull a usable value for a corrected field out of an utterance."""
    normalized = normalize_text(text)
    if field == "phone":
        digits = parse_digits(normalized)
        return digits if len(digits) >= 6 else None
    if field == "district":
        return match_option(normalized, DISTRICT_OPTIONS)
    if field == "full_name":
        cleaned = normalized
        removable = (
            FIELD_KEYWORDS["full_name"]
            + CHANGE_WORDS
            + YES_WORDS
            + NO_WORDS
            + STOP_WORDS
            + ["నా", "మా", "మీ", "అని", "my"]
        )
        for word in removable:
            cleaned = cleaned.replace(word, " ")
        cleaned = " ".join(cleaned.split()).strip(" .,!?")
        return cleaned if len(cleaned) >= 2 else None
    return None


def parse_correction(text: str) -> tuple[str, str | None] | None:
    """Detect "field changed" intent. Returns (field, value|None), or None."""
    normalized = normalize_text(text)
    field = parse_field_choice(normalized)
    if field is None:
        return None
    value = extract_field_value(field, normalized)
    changed = any(word in normalized for word in CHANGE_WORDS)
    if value is None and not changed:
        return None
    return field, value


def is_application_intent(text: str) -> bool:
    normalized = normalize_text(text)
    return any(word in normalized for word in INTENT_WORDS)
