#!/usr/bin/env python3
"""Offline checks for the language tables (app/lang/*.json) and language-aware parsing.

    .venv/bin/python scripts/lang_check.py
"""

from __future__ import annotations

import asyncio
import string
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import lang as langs
from app.agent import answers, fields, readback
from app.agent.voice_ux import VoiceAgent

RESULTS: list[tuple[str, bool, str]] = []
FIELDS = fields.PROFILE_KEYS

# What a user might say: (yes, no, stop) per language.
SAMPLES = {
    "en-IN": ("yes", "no", "stop"),
    "te-IN": ("అవును", "కాదు", "ఆగు"),
    "hi-IN": ("हाँ", "नहीं", "रुको"),
    "mr-IN": ("होय", "नाही", "थांबा"),
    "ta-IN": ("ஆமாம்", "இல்லை", "நிறுத்து"),
    "kn-IN": ("ಹೌದು", "ಇಲ್ಲ", "ನಿಲ್ಲಿಸು"),
    "ml-IN": ("അതെ", "ഇല്ല", "നിർത്തൂ"),
    "bn-IN": ("হ্যাঁ", "না", "থামো"),
    "gu-IN": ("હા", "ના", "રોકો"),
    "pa-IN": ("ਹਾਂ", "ਨਹੀਂ", "ਰੁਕੋ"),
}


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


async def main() -> int:
    english = langs.get("en-IN")
    codes = langs.codes()
    check("10 languages available", len(codes) == 10, ", ".join(codes))
    check("every language has samples here", set(codes) == set(SAMPLES), str(set(codes) ^ set(SAMPLES)))

    for code in codes:
        lang = langs.get(code)
        missing = [k for k in english.phrases if k not in lang.phrases]
        wrong = [k for k in english.phrases if k in lang.phrases and placeholders(lang.phrases[k]) != placeholders(english.phrases[k])]
        check(f"{code}: all phrases present", not missing, ", ".join(missing))
        check(f"{code}: placeholders match English", not wrong, ", ".join(wrong))
        check(f"{code}: all field labels", all(f in lang.labels for f in FIELDS), str([f for f in FIELDS if f not in lang.labels]))
        check(f"{code}: 10 digit words", len(lang.words.get("digits", [])) == 10)
        check(f"{code}: name/phone field words", {"full_name", "phone"} <= set(lang.words.get("field_words", {})))

        yes, no, stop = SAMPLES[code]
        check(f"{code}: yes / no / stop understood",
              readback.parse_yes_no(yes, code) is True and readback.parse_yes_no(no, code) is False
              and readback.is_stop(stop, code) and not readback.is_stop(yes, code),
              f"{readback.parse_yes_no(yes, code)}, {readback.parse_yes_no(no, code)}, {readback.is_stop(stop, code)}")
        spoken = readback.spoken_digits("9876543210", code)
        check(f"{code}: digit read-back parses back", readback.parse_digits(spoken, code) == "9876543210", spoken)
        check(f"{code}: English yes still works", readback.parse_yes_no("yes", code) is True)

    # whole-word ("=") rules: short words must not fire inside longer ones
    check("hi: 'नाम सही है' is yes (ना inside नाम ignored)", readback.parse_yes_no("नाम सही है", "hi-IN") is True)
    check("hi: 'यहां' is not yes (हां inside यहां ignored)", readback.parse_yes_no("यहां", "hi-IN") is None)
    check("bn: 'নাম ঠিক আছে' is yes", readback.parse_yes_no("নাম ঠিক আছে", "bn-IN") is True)
    check("gu: 'છે' adds no digit 6", readback.parse_digits("મારો નંબર છે 98", "gu-IN") == "98",
          readback.parse_digits("મારો નંબર છે 98", "gu-IN"))
    check("gu: 'નવો' adds no digit 9", readback.parse_digits("નવો નંબર", "gu-IN") == "")
    check("Devanagari numerals -> ASCII", readback.parse_digits("९८७६५४३२१०", "hi-IN") == "9876543210")
    check("Hindi digit words", readback.parse_digits("नौ आठ सात छह पाँच चार तीन दो एक शून्य", "hi-IN") == "9876543210")
    check("Hindi-script English digits", readback.parse_digits("नाइन एट सेवन", "hi-IN") == "987")
    check("hi: field choice 'नाम'", readback.parse_field_choice("नाम", "hi-IN") == "full_name")
    check("ta: field choice 'தொலைபேசி எண்'", readback.parse_field_choice("தொலைபேசி எண்", "ta-IN") == "phone")
    check("unknown code falls back to default", langs.get("xx-YY").code == langs.get().code)

    # a Hindi conversation turn, end to end through VoiceAgent
    asked: list[str] = []
    said: list[str] = []
    replies = ["Sita Devi", "हाँ"]

    async def ask(prompt, _kind):
        asked.append(prompt)
        return replies.pop(0)

    agent = VoiceAgent(say=said.append, ask=ask, language="hi-IN")
    name_field = {"label": "Full name", "tag": "input", "type": "text", "constraints": {"minlength": "3"}}
    value = await agent.ask_field(name_field, [])
    check("hi: asks in Hindi with the Hindi field name", asked[0] == "नाम बताइए।", asked[0])
    check("hi: confirms in Hindi, 'हाँ' accepted", value == "Sita Devi" and asked[1] == "Sita Devi। सही है?", str(asked))
    phone = {"label": "Mobile number", "tag": "input", "type": "text",
             "constraints": {"pattern": "[0-9]{10}", "inputmode": "numeric"}}
    replies[:] = ["नौ आठ सात छह पाँच चार तीन दो एक शून्य", "हाँ"]
    value = await agent.ask_field(phone, [])
    check("hi: phone in Hindi digit words", value == "9876543210", str(asked[-1]))
    check("hi: phone read back in Hindi digits", "नौ आठ" in asked[-1], asked[-1])
    spec = answers.field_spec(phone)
    check("hi: hint in Hindi", answers.hint(spec, langs.get("hi-IN")) == " 10 अंक बताइए।")

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} language checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
