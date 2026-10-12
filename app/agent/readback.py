"""Telugu read-back and spoken-answer parsing (plan §6).

Rules implemented here:
- digits are read digit by digit, grouped;
- names/values get a confirmation prompt ("సరేనా?");
- yes/no only counts as an answer to an active prompt;
- stop words ("ఆగు" and friends) trigger a hard stop;
- a small glossary maps Telugu-script answers to English portal options;
- corrections: English/Telugu/Tenglish phrasing, English digit words in both
  Latin and Telugu script ("నైన్ ఎయిట్ …").
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

# English digit words as they come back from te-IN STT (Telugu script), plus Telugu words.
PARSED_DIGIT_WORDS = {
    "సున్నా": "0", "జీరో": "0",
    "ఒకటి": "1", "వన్": "1",
    "రెండు": "2", "టూ": "2",
    "మూడు": "3", "త్రీ": "3",
    "నాలుగు": "4", "ఫోర్": "4",
    "ఐదు": "5", "ఫైవ్": "5", "ఫైవ": "5",
    "ఆరు": "6", "సిక్స్": "6", "సిక్స": "6",
    "ఏడు": "7", "సెవెన్": "7", "సెవెన": "7",
    "ఎనిమిది": "8", "ఎయిట్": "8", "ఎయిట": "8",
    "తొమ్మిది": "9", "నైన్": "9",
}

# Correction detection: which field is being changed, and change markers.
FIELD_KEYWORDS = {
    "phone": ["ఫోన్", "నంబర్", "నెంబర్", "mobile", "phone", "number"],
    "full_name": ["పేరు", "నేమ్", "name"],
    "district": ["జిల్లా", "district"],
    "pin": ["పిన్", "pin", "postal"],
    "address": ["చిరునామా", "address"],
    "college": ["కళాశాల", "college"],
    "email": ["ఈమెయిల్", "email"],
}
CHANGE_WORDS = [
    "మారింది", "మారిపోయింది", "మార్చ", "మార్చండి", "కొత్త", "సరిచేయ", "తప్పు", "సరికాదు",
    "చేంజ్", "చేంజ్డ్", "అప్డేట్",
    "change", "changed", "update", "new", "correct", "wrong", "incorrect",
]
FIELD_LABELS_TE = {
    "phone": "ఫోన్ నంబర్",
    "full_name": "పేరు",
    "district": "జిల్లా",
    "pin": "పిన్ కోడ్",
    "address": "చిరునామా",
    "college": "కళాశాల",
    "email": "ఈమెయిల్",
}

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

# Fillers stripped when a free-text value (name/address/college/email) is spoken.
TEXT_FILLERS = [
    "నా", "మా", "మీ", "అని", "మై", "నేమ్", "ఈజ్", "ఇస్", "హాస్", "చేంజ్డ్", "చేంజ్", "టు", "నౌ",
    "my", "is", "has", "was", "been", "the", "to", "now", "it", "it's", "i", "me", "a", "an",
    "not", "wrong", "incorrect", "isn't", "aren't",
]
TEXT_STOPWORDS = {
    "is", "has", "was", "to", "it", "the", "a", "an", "now", "change", "changed", "new", "my", "me", "i",
    "not", "wrong", "incorrect",
}

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
    """Extract digits from Telugu words, English words (Latin or Telugu script), or numerals."""
    candidates: list[tuple[int, int, str]] = []  # start, end, digit
    for word, digit in PARSED_DIGIT_WORDS.items():
        start = 0
        while True:
            position = text.find(word, start)
            if position == -1:
                break
            candidates.append((position, position + len(word), digit))
            start = position + 1
    for position, char in enumerate(text):
        if char.isdigit():
            candidates.append((position, position + 1, char))
    for match in re.finditer(r"[a-z]+", text.lower()):
        token = match.group(0)
        if token in ENGLISH_DIGITS:
            candidates.append((match.start(), match.end(), ENGLISH_DIGITS[token]))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    used_end = -1
    digits: list[str] = []
    for start, end, digit in candidates:
        if start >= used_end:
            digits.append(digit)
            used_end = end
    return "".join(digits)


def clean_text_value(text: str) -> str | None:
    """Strip filler words from a spoken free-text value (name, address, college, email).

    Token-based (not substring): single letters like "a"/"i" must never mangle a name.
    """
    token_fillers = {
        normalize_text(word)
        for group in (FIELD_KEYWORDS["full_name"], CHANGE_WORDS, YES_WORDS, NO_WORDS, STOP_WORDS, TEXT_FILLERS)
        for word in group
    }
    kept: list[str] = []
    for token in normalize_text(text).split():
        bare = token.strip(".,!?")
        if bare and bare not in token_fillers:
            kept.append(bare)
    cleaned = " ".join(kept).strip(" .,!?")
    if len(cleaned) < 2 or cleaned in TEXT_STOPWORDS:
        return None
    if re.fullmatch(r"[a-zA-Z .]+", cleaned):
        cleaned = cleaned.title()
    return cleaned


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
    if field == "pin":
        digits = parse_digits(normalized)
        return digits if len(digits) >= 4 else None
    if field == "district":
        return match_option(normalized, DISTRICT_OPTIONS)
    if field in ("full_name", "address", "college", "email"):
        return clean_text_value(normalized)
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
