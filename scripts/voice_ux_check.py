#!/usr/bin/env python3
"""Offline checks for the M3 voice UX layer (no network needed)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import lang
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

    prompt = lang.get("te-IN").say("readback_name_phone", name="Ravi Kumar", phone=readback.spoken_digits("9876543210"))
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

    # English speech as te-IN STT actually returns it (verified with TTS->STT)
    check(
        "english digits in Telugu script parsed",
        readback.parse_digits("మై ఫోన్ నంబర్ ఈజ్ నైన్ ఎయిట్ సెవెన్ సిక్స్ ఫైవ్ జీరో జీరో జీరో జీరో జీరో")
        == "9876500000",
    )
    check(
        "english name correction in Telugu script",
        readback.parse_correction("మై నేమ్ హాస్ చేంజ్డ్ టు సీతాదేవి") == ("full_name", "సీతాదేవి"),
    )
    check("english 'name is changed' asks for a value", readback.parse_correction("my name is changed") == ("full_name", None))
    check(
        "english name correction with value",
        readback.parse_correction("my name has changed to sita devi") == ("full_name", "Sita Devi"),
    )
    check("'my name is wrong' asks for a value", readback.parse_correction("my name is wrong") == ("full_name", None))
    check("'my number is wrong' asks for a value", readback.parse_correction("my number is wrong") == ("phone", None))
    check("'change my name to sita' has a value", readback.parse_correction("change my name to sita") == ("full_name", "Sita"))

    # "remove X and set Y" in one sentence: the instruction words must never end up
    # inside the stored name; the agent asks for the new value instead.
    check(
        "replacement phrasing asks for the new name",
        readback.parse_correction("నా పేరు నిహారిక రవికుమార్ అని తీసేసి నిహారిక అనిపెట్టు") == ("full_name", None),
    )
    check(
        "old + new name without 'remove' still asks",
        readback.parse_correction("నా పేరు నిహారిక రవికుమార్ అని, నిహారిక") == ("full_name", None),
    )
    check("plain new name still parses", readback.parse_correction("నా పేరు నిహారిక") == ("full_name", "నిహారిక"))
    check("name set phrasing strips instruction words", readback.extract_field_value("full_name", "నిహారిక అనిపెట్టు") == "నిహారిక")
    check("'name changed' in Telugu asks for a value", readback.parse_correction("నా పేరు మార్చాలి") == ("full_name", None))
    check("field + 'కూడా' is a change request", readback.parse_correction("నా ఫోన్ నెంబర్ కూడా") == ("phone", None))
    check("agreement with 'కూడా' is not a correction", readback.parse_correction("అవును, నా పేరు కూడా సరే") is None)
    check("repeated 'సరే' is agreement, not a correction", readback.parse_correction("ఫోన్ నంబర్ సరే సరే") is None)
    check("rejected name is not taken as the value", readback.extract_field_value("full_name", "నా పేరు సీత కాదు") is None)
    check("name containing 'no' survives", readback.extract_field_value("full_name", "Nora Nandini") == "Nora Nandini")
    check("'not' phrasing asks for a value", readback.parse_correction("my name is not ravi") == ("full_name", None))

    check("district alias matched", readback.match_option("మా జిల్లా గుంటూరు", ["Guntur", "Krishna"]) == "Guntur")
    check("english option matched", readback.match_option("Krishna", ["Guntur", "Krishna"]) == "Krishna")
    check("unknown option -> None (re-ask)", readback.match_option("something else", ["Guntur", "Krishna"]) is None)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} voice UX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
