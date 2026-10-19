"""Spelled answers: "N E E H A R I K A" said letter by letter, in any language.

Speech recognition writes English letter names in the user's script and often runs
them together: Telugu "ఎన్ఈఈ హెచ్ఏఆర్ఐ కే", Hindi "एन ई ई एच ए आर आई के".
All Indian scripts share one Unicode layout, so text is first folded onto Devanagari
(the "skeleton": no virama/nukta, short and long vowels merged), then split into letter
names; a word that does not split cleanly into letters is ignored ("spelling", "my").
"""

from __future__ import annotations

import functools
import re
import unicodedata

from app.lang.script import skeleton

DOUBLE, SPACE, AT, DOT = "<double>", " ", "@", "."

# Letter names as Indian speech recognisers write them (Devanagari form; other scripts fold onto it).
_NATIVE: dict[str, list[str]] = {
    "a": ["ए", "एय"], "b": ["बी"], "c": ["सी", "ची"], "d": ["डी"], "e": ["ई"],
    "f": ["एफ", "एफ्फ", "ऐफ"], "g": ["जी"], "h": ["एच", "हेच", "एच्च", "ऐच", "एइच"], "i": ["ऐ", "आई", "आय"],
    "j": ["जे", "जै", "जय"], "k": ["के", "केय"], "l": ["एल", "एल्ल", "ऐल"], "m": ["एम", "एं", "ऐम"],
    "n": ["एन", "ऐन"], "o": ["ओ"], "p": ["पी"], "q": ["क्यू", "क्यु"], "r": ["आर"], "s": ["एस", "एस्स", "ऐस"],
    "t": ["टी"], "u": ["यू"], "v": ["वी", "भी"], "w": ["डबल्यू", "डब्ल्यू", "डबल यू"],
    "x": ["एक्स", "ऐक्स"], "y": ["वाई", "वै", "वाय"], "z": ["जेड", "ज़ेड", "जेट"],
    DOUBLE: ["डबल"], SPACE: ["स्पेस"], AT: ["एट", "ऐट", "अट"], DOT: ["डॉट", "डाट", "डोट"],
}
# Whole words kept as written (email domains are said as words, not spelled).
_NATIVE_WORDS: dict[str, list[str]] = {
    "gmail": ["जीमेल", "जीमेयिल", "जीमेइल"], "yahoo": ["याहू"], "outlook": ["आउटलुक"],
    "hotmail": ["हॉटमेल"], "com": ["कॉम", "काम", "कोम"], "in": ["इन"],
}
_LATIN: dict[str, list[str]] = {
    "a": ["ay", "ae"], "b": ["bee", "be"], "c": ["see", "cee", "si"], "d": ["dee", "di"],
    "e": ["ee"], "f": ["ef", "eff"], "g": ["gee", "ji"], "h": ["aitch", "ech", "eich", "edge"],
    "i": ["eye"], "j": ["jay", "je"], "k": ["kay", "ke"], "l": ["el", "ell"], "m": ["em"],
    "n": ["en"], "o": ["oh"], "p": ["pee", "pe"], "q": ["queue", "cue", "kyu"], "r": ["are", "ar"],
    "s": ["es", "ess"], "t": ["tee", "te"], "u": ["you", "yu"], "v": ["vee", "ve"],
    "w": ["doubleyou"], "x": ["ex"], "y": ["why", "wai"], "z": ["zed", "zee"],
    DOUBLE: ["double"], SPACE: ["space"], AT: ["at", "@"], DOT: ["dot"],
}
_LATIN_WORDS = {"gmail", "yahoo", "outlook", "hotmail", "com", "in", "co", "org", "net", "edu"}
_RATE = {"the", "rate", "of"}  # "at the rate (of)" = @ (native forms simply do not split into letters)


@functools.lru_cache(maxsize=1)
def _native_table() -> dict[str, str]:
    table: dict[str, str] = {}
    for symbol, names in _NATIVE.items():
        for name in names:
            table[skeleton(name).replace(" ", "")] = symbol
    for word, names in _NATIVE_WORDS.items():
        for name in names:
            table[skeleton(name)] = word
    return table


@functools.lru_cache(maxsize=1)
def _latin_table() -> dict[str, str]:
    table = {chr(c): chr(c) for c in range(ord("a"), ord("z") + 1)}
    for symbol, names in _LATIN.items():
        for name in names:
            table[name] = symbol
    return table


def _split(token: str) -> list[str] | None:
    """Split one skeleton token into letter names (fewest pieces); None if it does not split."""
    table = _native_table()
    longest = max(len(key) for key in table)
    best: list[list[str] | None] = [None] * (len(token) + 1)
    best[len(token)] = []
    for start in range(len(token) - 1, -1, -1):
        for end in range(min(len(token), start + longest), start, -1):
            symbol = table.get(token[start:end])
            rest = best[end]
            if symbol is not None and rest is not None and (best[start] is None or len(rest) + 1 < len(best[start])):
                best[start] = [symbol, *rest]
    return best[0]


def mentions_spelling(text: str) -> bool:
    """'spelling thappu', 'స్పెల్లింగ్ చెప్తాను', 'letter by letter', Bengali 'বানান'."""
    folded = skeleton(text)
    return bool(re.search(r"\bspell|letter by letter", folded)) or "सपेल" in folded or "बानान" in folded


def decode(text: str) -> str:
    """Spelled letters -> text: 'ఎన్ఈఈ హెచ్ఏఆర్ఐ కే' -> 'neeharik'. Words that are not letters are dropped."""
    symbols: list[str] = []
    for raw in re.split(r"[\s,;:\-–—/|]+", unicodedata.normalize("NFC", text)):
        token = raw.strip(".!?।॥\"'()")
        if not token:
            continue
        lower = token.lower()
        if re.fullmatch(r"[a-z0-9@]+", lower):
            if lower.isdigit():
                symbols.extend(lower)
            elif lower in _latin_table():
                symbols.append(_latin_table()[lower])
            elif lower in _LATIN_WORDS or lower in _RATE:
                symbols.append(lower)
            continue  # other English words ("spelling", "my") are not part of the value
        pieces = _split(skeleton(token))
        if pieces:
            symbols.extend(pieces)
    return _assemble(symbols)


def _assemble(symbols: list[str]) -> str:
    out: list[str] = []
    double = False
    after_at = False
    for symbol in symbols:
        if symbol in _RATE:
            if after_at:
                continue
            symbol = ""  # stray "the"/"of" outside "at the rate"
        after_at = symbol == AT
        if len(symbol) > 1 and symbol.isalnum() and AT not in out:
            continue  # whole words ("gmail", "in") only belong to an email's domain
        if symbol == DOUBLE:
            double = True
            continue
        if double and len(symbol) == 1 and symbol.isalnum():
            out.append(symbol)
        double = False
        out.append(symbol)
    return re.sub(r" +", " ", "".join(out)).strip()


def letter_count(value: str) -> int:
    return sum(char.isalnum() for char in value)


def spell_out(value: str) -> str:
    """'Neeharika' -> 'N, E, E, H, A, R, I, K, A' (read back so each letter can be checked)."""
    words = []
    for word in value.split(" "):
        words.append(", ".join(char.upper() if char.isalpha() else char for char in word))
    return " — ".join(words)
