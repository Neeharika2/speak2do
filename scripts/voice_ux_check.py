#!/usr/bin/env python3
"""Offline checks for the M3 voice UX layer (no network needed)."""

from __future__ import annotations

import asyncio

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import lang
from app.agent import answers, readback
from app.agent.voice_ux import VoiceAgent

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def main() -> int:
    # corrections go through the session's VoiceAgent; rules only (model stubbed out)
    async def no_llm(_spec, _utterance):
        return None

    answers._llm_extract = no_llm
    voice = VoiceAgent(say=lambda _m: None, ask=None, language="te-IN")
    voice.note_field({"label": "District", "tag": "select", "type": "", "constraints": {}}, ["Guntur", "Krishna"])
    fix = voice.correction_in

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
        await fix("నా నంబర్ తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు సున్నా సున్నా సున్నా సున్నా సున్నా")
        == ("phone", "9876500000"),
    )
    check("phone change without value -> asks for it", await fix("నా ఫోన్ నంబర్ మారింది") == ("phone", None))
    check("phone 'is fine' is not a correction", await fix("ఫోన్ నంబర్ సరే") is None)
    check("name correction parsed", await fix("నా పేరు సీతా దేవి") == ("full_name", "సీతా దేవి"))
    check("district correction parsed", await fix("జిల్లా గుంటూరు") == ("district", "Guntur"))
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
        await fix("మై నేమ్ హాస్ చేంజ్డ్ టు సీతాదేవి") == ("full_name", "సీతాదేవి"),
    )
    check("english 'name is changed' asks for a value", await fix("my name is changed") == ("full_name", None))
    check(
        "english name correction with value",
        await fix("my name has changed to sita devi") == ("full_name", "Sita Devi"),
    )
    check("'my name is wrong' asks for a value", await fix("my name is wrong") == ("full_name", None))
    check("'my number is wrong' asks for a value", await fix("my number is wrong") == ("phone", None))
    check("'change my name to sita' has a value", await fix("change my name to sita") == ("full_name", "Sita"))

    # "remove X and set Y" in one sentence: the instruction words must never end up
    # inside the stored name; the agent asks for the new value instead.
    check(
        "replacement phrasing asks for the new name",
        await fix("నా పేరు నిహారిక రవికుమార్ అని తీసేసి నిహారిక అనిపెట్టు") == ("full_name", None),
    )
    check(
        "old + new name without 'remove' still asks",
        await fix("నా పేరు నిహారిక రవికుమార్ అని, నిహారిక") == ("full_name", None),
    )
    check("plain new name still parses", await fix("నా పేరు నిహారిక") == ("full_name", "నిహారిక"))
    check("name set phrasing strips instruction words", await voice.value_for("full_name", "నిహారిక అనిపెట్టు") == "నిహారిక")
    check("'name changed' in Telugu asks for a value", await fix("నా పేరు మార్చాలి") == ("full_name", None))
    check("field + 'కూడా' is a change request", await fix("నా ఫోన్ నెంబర్ కూడా") == ("phone", None))
    check("agreement with 'కూడా' is not a correction", await fix("అవును, నా పేరు కూడా సరే") is None)
    check("repeated 'సరే' is agreement, not a correction", await fix("ఫోన్ నంబర్ సరే సరే") is None)
    check("rejected name is not taken as the value", await voice.value_for("full_name", "నా పేరు సీత కాదు") is None)
    check("name containing 'no' survives", await voice.value_for("full_name", "Nora Nandini") == "Nora Nandini")
    check("'not' phrasing asks for a value", await fix("my name is not ravi") == ("full_name", None))

    check("district matched by sound", readback.match_option("మా జిల్లా గుంటూరు", ["Guntur", "Krishna"]) == "Guntur")
    for spoken_place in ("गुंटूर", "குண்டூர்", "ಗುಂಟೂರು", "ഗുണ്ടൂർ", "গুন্টুর", "ગુંટુર", "ਗੁੰਟੂਰ"):
        check(f"place in any script: {spoken_place}", readback.match_option(spoken_place, ["Guntur", "Krishna", "Kurnool"]) == "Guntur")

    # corrections in other languages (rules only)
    hindi = VoiceAgent(say=lambda _m: None, ask=None, language="hi-IN")
    check("hi: 'phone number changed' asks for it", await hindi.correction_in("मेरा फ़ोन नंबर बदल गया है") == ("phone", None))
    check("hi: phone correction with Hindi digits",
          await hindi.correction_in("मेरा फ़ोन नंबर नौ आठ सात छह पाँच चार तीन दो एक शून्य है") == ("phone", "9876543210"))
    check("hi: 'name is wrong' asks for it", await hindi.correction_in("मेरा नाम गलत है") == ("full_name", None))
    hindi.note_field({"label": "District", "tag": "select", "type": "", "constraints": {}}, ["Guntur", "Krishna"])
    check("hi: district matched by sound", await hindi.correction_in("जिला गुंटूर") == ("district", "Guntur"))
    tamil = VoiceAgent(say=lambda _m: None, ask=None, language="ta-IN")
    check("ta: 'phone number changed' asks for it", await tamil.correction_in("என் தொலைபேசி எண் மாறிவிட்டது") == ("phone", None))
    bengali = VoiceAgent(say=lambda _m: None, ask=None, language="bn-IN")
    check("bn: email changed asks for it", await bengali.correction_in("আমার ইমেইল ভুল") == ("email", None))
    check("english option matched", readback.match_option("Krishna", ["Guntur", "Krishna"]) == "Krishna")
    check("unknown option -> None (re-ask)", readback.match_option("something else", ["Guntur", "Krishna"]) is None)

    # step 5: whole-word task intent, exact phone / PIN length on corrections
    check("'information' is not the task intent", not readback.is_application_intent("give me information"))
    check("'ఫోన్ చేయి' is not the task intent", not readback.is_application_intent("ఫోన్ చేయి"))
    check("'fill the form' is the task intent", readback.is_application_intent("please fill the form"))
    check("correction phone needs 10 digits", await voice.value_for("phone", "98765") is None
          and await voice.value_for("phone", "9876543210") == "9876543210")
    check("correction phone drops +91", await voice.value_for("phone", "+91 98765 43210") == "9876543210")
    check("correction PIN needs 6 digits", await voice.value_for("pin", "5220") is None
          and await voice.value_for("pin", "522001") == "522001")

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} voice UX checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
