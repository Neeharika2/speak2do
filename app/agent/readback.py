"""Telugu read-back and spoken-answer parsing (plan §6).

Rules implemented here:
- digits are read digit by digit, grouped;
- names/values get a confirmation prompt ("సరేనా?");
- yes/no only counts as an answer to an active prompt;
- stop words ("ఆగు" and friends) trigger a hard stop;
- a small glossary maps Telugu-script answers to English portal options.
"""

from __future__ import annotations

DIGIT_WORDS = ["సున్నా", "ఒకటి", "రెండు", "మూడు", "నాలుగు", "ఐదు", "ఆరు", "ఏడు", "ఎనిమిది", "తొమ్మిది"]

YES_WORDS = ["అవును", "అవు", "సరే", "ఓకే", "ఒప్పు", "yes", "ok", "okay", "avunu", "avnu", "sare"]
NO_WORDS = ["కాదు", "వద్దు", "లేదు", "తప్పు", "no", "kadu", "ledu", "vaddu"]
STOP_WORDS = ["ఆగు", "ఆగండి", "ఆపు", "ఆపండి", "ఆపేయి", "stop", "aagu", "agu", "aap"]
REPEAT_WORDS = ["మళ్ళీ", "మళ్లీ", "మరలా", "repeat", "again"]

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
