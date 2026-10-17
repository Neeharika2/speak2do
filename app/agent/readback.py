"""Spoken-answer parsing and read-back helpers (plan §6).

Language-aware parts take a language code (app/lang tables; default = AGENT_LANGUAGE):
- yes / no / stop / repeat detection and digit words come from the language table
  (plus English, which people mix into every language);
- digits are read back digit by digit, grouped, in the session's language.

Correction parsing ("నా నంబర్ మారింది", "my number changed") is rule-based for Telugu and
English only; other languages reach the LLM fallback (app/voice/intent_llm.py).
"""

from __future__ import annotations

import re
import unicodedata

from app import lang as langs

_TE = langs.get("te-IN")

# Telugu + English word lists used by the correction heuristics below.
DIGIT_WORDS = [_TE.spoken_digit(i) for i in range(10)]
YES_WORDS = [w.lstrip("=") for w in _TE.word_list("yes")]
NO_WORDS = [w.lstrip("=") for w in _TE.word_list("no")]
STOP_WORDS = [w.lstrip("=") for w in _TE.word_list("stop")]

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
    # instruction verbs: "నిహారిక అనిపెట్టు" (set it as …), "పేరు మార్చు" (change the name)
    "అనిపెట్టు", "అనిపెట్టండి", "పెట్టు", "పెట్టండి", "పెట్టాలి", "మార్చు", "మార్చాలి",
    "చేయి", "చేయండి", "అన్నాను", "చెప్పాను", "కావాలి", "మాత్రమే", "ఒక్కటే", "కూడా",
    "తీసేసి", "తీసేయి", "తీసేయండి", "తీసివేయి", "తీసివేయండి", "బదులు", "బదులుగా",
    "set", "make", "call", "keep", "use", "please", "only",
]

# Replacement phrasings ("remove X and set Y") carry two values in one breath.
# Picking one out of messy STT is unreliable, so the agent asks for the new value.
REPLACEMENT_WORDS = [
    "తీసేసి", "తీసేయి", "తీసేయండి", "తీసివేయి", "తీసివేయండి", "తీసెయ్", "బదులు", "బదులుగా",
    "remove", "delete", "instead", "replace",
]
TEXT_STOPWORDS = {
    "is", "has", "was", "to", "it", "the", "a", "an", "now", "change", "changed", "new", "my", "me", "i",
    "not", "wrong", "incorrect",
}


_SEPARATORS = r"\s.,!?।;:\"'()\-"


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text or "").lower().split())


def _spans(normalized: str, word: str):
    """(start, end) of every match of a table word, honouring the matching rules in app/lang."""
    if word.startswith("="):
        word = word[1:]
        pattern = rf"(?<![^{_SEPARATORS}]){re.escape(word)}(?![^{_SEPARATORS}])"
    elif word.isascii():
        pattern = rf"(?<![a-z]){re.escape(word)}(?![a-z])"
    else:
        pattern = re.escape(word)
    return [(m.start(), m.end()) for m in re.finditer(pattern, normalized)]


def has_word(normalized: str, word: str) -> bool:
    """Latin words match whole words ("ok" is not in "book"); native-script words match as
    substrings unless the table marks them whole-word with "="."""
    return bool(_spans(normalized, word))


def _any(text: str, words: list[str]) -> bool:
    normalized = normalize_text(text)
    return bool(normalized) and any(has_word(normalized, word) for word in words)


def spoken_digits(value: str, language: str | None = None) -> str:
    """Read digits digit-by-digit, grouped in two halves (plan §6)."""
    lang = langs.get(language)
    words = [lang.spoken_digit(int(ch)) for ch in str(value) if ch.isdigit()]
    if not words:
        return str(value)
    if len(words) <= 2:
        return " ".join(words)
    mid = (len(words) + 1) // 2
    return f"{' '.join(words[:mid])}, {' '.join(words[mid:])}"


def parse_yes_no(text: str, language: str | None = None) -> bool | None:
    """True = yes, False = no, None = unclear (must re-ask). "No" wins over "yes"."""
    lang = langs.get(language)
    if _any(text, lang.word_list("no")):
        return False
    if _any(text, lang.word_list("yes")):
        return True
    return None


def is_stop(text: str, language: str | None = None) -> bool:
    return _any(text, langs.get(language).word_list("stop"))


def is_repeat(text: str, language: str | None = None) -> bool:
    return _any(text, langs.get(language).word_list("repeat"))


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
    if len(normalized) < 3:
        return None  # "a" must not pick "Male"
    for option in options:
        candidate = normalize_text(option)
        if candidate and (has_word(normalized, candidate) or normalized in candidate):
            return option
    return None


def parse_digits(text: str, language: str | None = None) -> str:
    """Extract digits from numerals (any script) and digit words of the language (+ English)."""
    normalized = normalize_text(text)
    candidates: list[tuple[int, int, str]] = []  # start, end, digit
    for word, digit in langs.get(language).digit_words().items():
        candidates += [(start, end, digit) for start, end in _spans(normalized, word)]
    for position, char in enumerate(normalized):
        if char.isdigit():
            candidates.append((position, position + 1, str(unicodedata.digit(char))))  # "५" -> "5"
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


def parse_field_choice(text: str, language: str | None = None) -> str | None:
    """Which field does the utterance name? (Telugu/English keywords + the language's own.)"""
    normalized = normalize_text(text)
    keywords = {field: list(words) for field, words in FIELD_KEYWORDS.items()}
    for field, words in langs.get(language).field_words().items():
        keywords.setdefault(field, []).extend(w for w in words if w not in keywords[field])
    for field, words in keywords.items():
        if any(has_word(normalized, word) for word in words):
            return field
    return None


def _has_repeated_token(value: str) -> bool:
    """True when a value repeats a word ("… నిహారిక … నిహారిక") — old + new mixed."""
    seen: set[str] = set()
    for token in normalize_text(value).split():
        if len(token) >= 3 and token in seen:
            return True
        seen.add(token)
    return False


def _mentions_negation(text: str) -> bool:
    """True when a value is being rejected ("పేరు సీత కాదు" = the name is not Sita).

    Latin "no"/"not" needs word boundaries ("Nora", "Nolan" are names).
    """
    normalized = normalize_text(text)
    if re.search(r"\b(no|not)\b", normalized):
        return True
    return any(word in normalized for word in ("కాదు", "వద్దు", "లేదు", "తప్పు", "kadu", "ledu", "vaddu"))


def extract_field_value(field: str, text: str, language: str | None = None) -> str | None:
    """Pull a usable value for a corrected field out of an utterance."""
    normalized = normalize_text(text)
    if field == "phone":
        digits = parse_digits(normalized, language)
        return digits if len(digits) >= 6 else None
    if field == "pin":
        digits = parse_digits(normalized, language)
        return digits if len(digits) >= 4 else None
    if field == "district":
        return match_option(normalized, DISTRICT_OPTIONS)
    if field in ("full_name", "address", "college", "email"):
        if any(word in normalized for word in REPLACEMENT_WORDS):
            return None  # "remove X, set Y": ask for the new value instead
        if _mentions_negation(normalized):
            return None  # "… is not X": X is the value being rejected
        value = clean_text_value(normalized)
        if field == "full_name" and value and _has_repeated_token(value):
            return None  # old and new name in one sentence: ask again
        return value
    return None


def _change_requested(normalized: str) -> bool:
    """True when the utterance asks for a field to be changed."""
    if any(word in normalized for word in CHANGE_WORDS + REPLACEMENT_WORDS):
        return True
    if _mentions_negation(normalized):
        return True  # "… is not X" rejects the current value
    # "నా ఫోన్ నంబర్ కూడా" ("my phone number too"): a field mention with "also"
    # and no yes/no word is a change request, not agreement.
    if "కూడా" in normalized and not any(word in normalized for word in YES_WORDS + NO_WORDS):
        return True
    return False


def parse_correction(text: str) -> tuple[str, str | None] | None:
    """Detect "field changed" intent. Returns (field, value|None), or None."""
    normalized = normalize_text(text)
    field = parse_field_choice(normalized)
    if field is None:
        return None
    value = extract_field_value(field, normalized)
    if value is None and not _change_requested(normalized):
        if field == "full_name" and _has_repeated_token(clean_text_value(normalized) or ""):
            return field, None  # old + new name in one sentence: ask again
        return None
    return field, value


def is_application_intent(text: str) -> bool:
    normalized = normalize_text(text)
    return any(word in normalized for word in INTENT_WORDS)
