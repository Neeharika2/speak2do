"""Script folding shared by spelling and option matching.

All Indian scripts in Unicode share one layout (Devanagari .. Malayalam, 0x80 code
points each), so any of them can be folded onto Devanagari. `sound_key` goes one step
further and keeps only consonant classes, so "గుంటూరు", "गुंटूर" and "Guntur" all
become the same key — good enough to match a spoken place name to an English option.
"""

from __future__ import annotations

import re
import unicodedata

_BRAHMIC = range(0x0900, 0x0D80)  # Devanagari .. Malayalam, 0x80 code points per script
_DROP = {"\u094d", "\u093c", "\u0901", "\u0971"}  # virama, nukta, candrabindu, Gurmukhi addak (after folding)
_FOLD = {
    "ऎ": "ए", "ॆ": "े", "ऒ": "ओ", "ॊ": "ो", "ऍ": "ए", "ॅ": "े", "ॉ": "ो", "ऑ": "ओ",
    "इ": "ई", "ि": "ी", "उ": "ऊ", "ु": "ू",
    "ऱ": "र", "ऩ": "न", "ऴ": "ल", "ळ": "ल", "ड़": "ड", "ढ़": "ढ", "य़": "य",
    "॰": "ं",  # Gurmukhi tippi (folded from U+0A70)
}
_CHILLU = {"ൺ": "ण", "ൻ": "न", "ർ": "र", "ൽ": "ल", "ൾ": "ल", "ൿ": "क"}  # Malayalam, outside the shared layout


def skeleton(text: str) -> str:
    """Fold any Indian script onto simplified Devanagari; Latin is lower-cased."""
    out: list[str] = []
    for char in unicodedata.normalize("NFC", text):
        if char in _CHILLU:
            char = _CHILLU[char]
        elif ord(char) in _BRAHMIC:
            char = chr(0x0900 + (ord(char) & 0x7F))
        if char in _DROP:
            continue
        out.append(_FOLD.get(char, char).lower())
    return "".join(out)


# Consonant classes: voicing and aspiration ignored (Tamil writes k/g, t/d, p/b alike),
# vowels / h / y dropped, all nasals one class.
_DEVA_CLASS = {
    "क": "K", "ख": "K", "ग": "K", "घ": "K", "ङ": "N", "च": "C", "छ": "C", "ज": "C", "झ": "C",
    "ञ": "N", "ट": "T", "ठ": "T", "ड": "T", "ढ": "T", "ण": "N", "त": "T", "थ": "T", "द": "T",
    "ध": "T", "न": "N", "प": "P", "फ": "P", "ब": "P", "भ": "P", "म": "N", "र": "R", "ल": "L",
    "व": "V", "श": "S", "ष": "S", "स": "S", "ं": "N", "ृ": "R", "ऋ": "R", "क़": "K", "ज़": "C", "फ़": "P",
}
_LATIN_CLASS = [
    ("ch", "C"), ("sh", "S"), ("ph", "P"), ("kh", "K"), ("gh", "K"), ("th", "T"), ("dh", "T"),
    ("bh", "P"), ("jh", "C"), ("ck", "K"),
    ("k", "K"), ("q", "K"), ("c", "K"), ("g", "K"), ("j", "C"), ("z", "C"), ("t", "T"), ("d", "T"),
    ("n", "N"), ("m", "N"), ("p", "P"), ("f", "P"), ("b", "P"), ("v", "V"), ("w", "V"), ("r", "R"),
    ("l", "L"), ("s", "S"), ("x", "KS"),
]


def sound_key(text: str) -> str:
    """Consonant skeleton of a word in any Indian script or English: 'Hyderabad' -> 'DRBD'."""
    out: list[str] = []
    for word in re.split(r"[\s.,;:!?।॥()\[\]'\"/-]+", text.lower()):
        if word.isascii():
            i = 0
            while i < len(word):
                for latin, cls in _LATIN_CLASS:
                    if word.startswith(latin, i):
                        out.append(cls)
                        i += len(latin)
                        break
                else:
                    i += 1  # vowels, h, y
        else:
            out.extend(_DEVA_CLASS.get(char, "") for char in skeleton(word))
    return "".join(out)
