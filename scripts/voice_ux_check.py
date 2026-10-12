#!/usr/bin/env python3
"""Offline checks for the M3 voice UX layer (no network needed)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent import readback

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def main() -> int:
    spoken = readback.spoken_digits("9876543210")
    check(
        "digits read digit-by-digit (grouped)",
        spoken.startswith("తొమ్మిది") and spoken.endswith("సున్నా") and "," in spoken,
        spoken,
    )

    prompt = readback.name_phone_prompt("Ravi Kumar", "9876543210")
    check("read-back prompt has name + digits + confirmation", "Ravi Kumar" in prompt and "తొమ్మిది" in prompt and "సరేనా" in prompt)

    check("yes parsed", readback.parse_yes_no("అవును") is True)
    check("transliterated yes parsed", readback.parse_yes_no("avunu") is True)
    check("no parsed", readback.parse_yes_no("కాదు") is False)
    check("unclear answer -> None (re-ask)", readback.parse_yes_no("hmm maybe") is None)

    check("stop word detected", readback.is_stop("ఆగు"))
    check("transliterated stop detected", readback.is_stop("aagu"))
    check("non-stop is not a stop", not readback.is_stop("scholarship application"))

    check("repeat request detected", readback.is_repeat("మళ్ళీ చెప్పు"))
    check("non-repeat is not a repeat", not readback.is_repeat("అవును"))

    check("digits parsed from Telugu words", readback.parse_digits("తొమ్మిది ఎనిమిది ఏడు") == "987")
    check("digits parsed from numerals", readback.parse_digits("నంబర్ 987 అని") == "987")
    check(
        "phone correction with spoken digits",
        readback.parse_correction("నా నంబర్ తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు సున్నా సున్నా సున్నా సున్నా సున్నా")
        == ("phone", "9876500000"),
    )
    check("phone change without value -> asks for it", readback.parse_correction("నా ఫోన్ నంబర్ మారింది") == ("phone", None))
    check("phone 'is fine' is not a correction", readback.parse_correction("ఫోన్ నంబర్ సరే") is None)
    check("name correction parsed", readback.parse_correction("నా పేరు సీతా దేవి") == ("full_name", "సీతా దేవి"))
    check("district correction parsed", readback.parse_correction("జిల్లా గుంటూరు") == ("district", "Guntur"))
    check("application intent detected", readback.is_application_intent("Scholarship application చేయండి"))
    check("unrelated speech is not application intent", not readback.is_application_intent("వాతావరణం ఎలా ఉంది"))

    check("district alias matched", readback.match_option("మా జిల్లా గుంటూరు", ["Guntur", "Krishna"]) == "Guntur")
    check("english option matched", readback.match_option("Krishna", ["Guntur", "Krishna"]) == "Krishna")
    check("unknown option -> None (re-ask)", readback.match_option("something else", ["Guntur", "Krishna"]) is None)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} voice UX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
