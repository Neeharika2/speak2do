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
from app.lang.script import sound_key

_TE = langs.get("te-IN")

# Telugu + English word lists used by the correction heuristics below.
DIGIT_WORDS = [_TE.spoken_digit(i) for i in range(10)]
YES_WORDS = [w.lstrip("=") for w in _TE.word_list("yes")]
NO_WORDS = [w.lstrip("=") for w in _TE.word_list("no")]
STOP_WORDS = [w.lstrip("=") for w in _TE.word_list("stop")]

# "Is this a request to (continue) the application task?"
INTENT_WORDS = [
    "application", "scholarship", "apply", "form", "fill", "submit", "start", "login",
    "అప్లికేషన్", "స్కాలర్షిప్", "దరఖాస్తు", "ఫారం", "నింప",
]

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


def _sound_match(normalized: str, options: list[str]) -> str | None:
    """The one option that sounds like the answer or a 1-3 word part of it (consonant keys)."""
    keys = {option: sound_key(option) for option in options}
    words = normalized.split()
    spans = {" ".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, min(len(words), i + 3) + 1)}
    found = {option for span in spans if len(key := sound_key(span)) >= 3 for option, k in keys.items() if k == key}
    return found.pop() if len(found) == 1 else None


def match_option(text: str, options: list[str]) -> str | None:
    """Match a spoken answer to one of the page's options, in any script ("గుంటూరు" -> Guntur)."""
    normalized = normalize_text(text)
    if not normalized:
        return None
    for option in options:
        if normalize_text(option) == normalized:
            return option
    sounded = _sound_match(normalized, options)
    if sounded:
        return sounded
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
        for group in (_TE.field_words()["full_name"], _TE.word_list("change"), YES_WORDS, NO_WORDS, STOP_WORDS, TEXT_FILLERS)
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
    """Which field does the utterance name? (The language's field words plus English.)"""
    normalized = normalize_text(text)
    keywords = langs.get(language).field_words()
    for field in sorted(keywords, key=lambda f: f == "full_name"):  # "college name" is college
        words = keywords[field]
        if any(has_word(normalized, word) for word in words):
            return field
    return None


def has_repeated_token(value: str) -> bool:
    """True when a value repeats a word ("… నిహారిక … నిహారిక") — old + new mixed."""
    seen: set[str] = set()
    for token in normalize_text(value).split():
        if len(token) >= 3 and token in seen:
            return True
        seen.add(token)
    return False


def mentions_negation(text: str) -> bool:
    """True when a value is being rejected ("పేరు సీత కాదు" = the name is not Sita).

    Latin "no"/"not" needs word boundaries ("Nora", "Nolan" are names).
    """
    normalized = normalize_text(text)
    if re.search(r"\b(no|not)\b", normalized):
        return True
    return any(word in normalized for word in ("కాదు", "వద్దు", "లేదు", "తప్పు", "kadu", "ledu", "vaddu"))


def change_requested(text: str, language: str | None = None) -> bool:
    """True when the utterance asks for a field to be changed ("…మారింది", "बदलना है", "is wrong")."""
    normalized = normalize_text(text)
    lang = langs.get(language)
    if _any(normalized, lang.word_list("change")) or _any(normalized, REPLACEMENT_WORDS):
        return True
    if mentions_negation(normalized) or _any(normalized, [w for w in lang.word_list("no") if not w.isascii()]):
        return True  # "… is not X" / "… తప్పు" rejects the current value
    # "నా ఫోన్ నంబర్ కూడా" ("my phone number too"): a field mention with "also"
    # and no yes/no word is a change request, not agreement.
    if "కూడా" in normalized and not any(word in normalized for word in YES_WORDS + NO_WORDS):
        return True
    return False


def mentions_replacement(text: str) -> bool:
    """"remove X and set Y" carries two values; picking one from messy STT is unreliable."""
    return _any(normalize_text(text), REPLACEMENT_WORDS)


def is_application_intent(text: str) -> bool:
    normalized = normalize_text(text)
    return any(has_word(normalized, word) for word in INTENT_WORDS)  # "information" is not "form"
