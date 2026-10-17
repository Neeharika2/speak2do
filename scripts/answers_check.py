#!/usr/bin/env python3
"""Offline checks for the per-field answer pipeline (app/agent/answers.py + VoiceAgent.ask_field).

The LLM is replaced by a fake, so this runs without network or API keys:
    .venv/bin/python scripts/answers_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.agent import answers, readback
from app.agent.voice_ux import StopRequested, VoiceAgent

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


# Elements as observe_page reports them for the mock portal.
def el(label, tag="input", etype="text", **constraints):
    base = {"pattern": "", "maxlength": "", "minlength": "", "inputmode": "", "min": "", "max": ""}
    base.update(constraints)
    return {"label": label, "tag": tag, "type": etype, "constraints": base}


NAME = el("Full name", minlength="3")
PHONE = el("Mobile number", pattern="[0-9]{10}", maxlength="10", inputmode="numeric")
PIN = el("PIN code", pattern="[0-9]{6}", maxlength="6", inputmode="numeric")
DOB = el("Date of birth", etype="date")
EMAIL = el("Email", etype="email")
MARKS = el("Marks (%)", etype="number", min="0", max="100")
GENDER = el("Gender", tag="select", etype="select-one")
GENDERS = ["Female", "Male", "Other"]

# fake LLM: utterance -> response
FAKE_LLM: dict[str, dict | None] = {
    "నా పేరు సీత దేవి": {"value": "Sita Devi", "confident": True},
    "ఆడ": {"value": "Female", "confident": True},
    "పన్నెండు మార్చి రెండు వేల ఐదు": {"value": "2005-03-12", "confident": True},
    "ఎనభై ఒకటి": {"value": "81", "confident": True},
    "మగ కాదు": {"value": "Unknown", "confident": True},          # off-list option -> rejected
    "ముప్పై ఫిబ్రవరి": {"value": "2005-02-30", "confident": True},  # impossible date -> rejected
    "రాము": {"value": "రాము", "confident": True},                   # native script -> not confident
}


async def fake_llm(spec, utterance):
    return FAKE_LLM.get(utterance, {"value": None, "confident": False})


async def parse(element, utterance, options=None):
    return await answers.parse_answer(answers.field_spec(element, options), utterance)


class FakeVoice:
    """Scripted user: answers in order; records what the agent said and asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.asked: list[str] = []
        self.said: list[str] = []
        self.stored: dict[str, str] = {}
        self.agent = VoiceAgent(
            say=self.said.append,
            ask=self.ask,
            on_answer=lambda k, v: self.stored.__setitem__(k, v),
            on_forget=lambda k: self.stored.pop(k, None),
        )

    async def ask(self, prompt, _kind):
        self.asked.append(prompt)
        return self.replies.pop(0)


async def main() -> int:
    answers._llm_extract = fake_llm

    # ---- field specs come from the page
    spec = answers.field_spec(PHONE)
    check("phone spec: exactly 10 digits", (spec.kind, spec.min_len, spec.max_len) == ("digits", 10, 10))
    check("dob spec: date", answers.field_spec(DOB).kind == "date")
    check("marks spec: number 0-100", (answers.field_spec(MARKS).min_val, answers.field_spec(MARKS).max_val) == (0, 100))
    check("gender spec: option", answers.field_spec(GENDER, GENDERS).kind == "option")
    check("name spec: text, key full_name", (answers.field_spec(NAME).kind, answers.field_spec(NAME).key) == ("text", "full_name"))

    # ---- text
    r = await parse(NAME, "my name is Sita Devi")
    check("lead-in stripped, case kept", r.value == "Sita Devi" and r.source == "rules", str(r))
    r = await parse(NAME, "sita devi")
    check("lowercase STT name title-cased", r.value == "Sita Devi", str(r))
    r = await parse(NAME, "నా పేరు సీత దేవి")
    check("Telugu sentence -> English name (LLM)", r.value == "Sita Devi" and r.source == "llm", str(r))
    r = await parse(NAME, "అవును")
    check("'yes' is not a name", r.value is None, str(r))
    r = await parse(NAME, "yes")
    check("English 'yes' is not a name", r.value is None, str(r))
    r = await parse(NAME, "రాము")
    check("native-script LLM value needs confirmation", r.value == "రాము" and not r.confident, str(r))
    r = await parse(el("Address line"), "1-2 MG Road")
    check("address keeps case and house number", r.value == "1-2 MG Road", str(r))

    # ---- digits
    r = await parse(PHONE, "98765 43210")
    check("phone numerals", r.value == "9876543210", str(r))
    r = await parse(PHONE, "తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు నాలుగు మూడు రెండు ఒకటి సున్నా")
    check("phone in Telugu digit words", r.value == "9876543210", str(r))
    r = await parse(PHONE, "9876543")
    check("7-digit phone rejected", r.value is None, str(r))
    r = await parse(PIN, "5220")
    check("4-digit PIN rejected", r.value is None, str(r))
    r = await parse(PIN, "my pin is 522002")
    check("PIN with lead-in", r.value == "522002", str(r))

    # ---- number
    r = await parse(MARKS, "81")
    check("marks numeral", r.value == "81", str(r))
    r = await parse(MARKS, "150")
    check("marks above max rejected", r.value is None, str(r))
    r = await parse(MARKS, "ఎనభై ఒకటి")
    check("marks in Telugu words (LLM)", r.value == "81", str(r))

    # ---- date
    for text in ("12/03/2005", "12 March 2005", "2005-03-12", "March 12, 2005", "12th of march 2005"):
        r = await parse(DOB, text)
        check(f"date '{text}'", r.value == "2005-03-12", str(r))
    r = await parse(DOB, "31/02/2005")
    check("impossible date rejected", r.value is None, str(r))
    r = await parse(DOB, "12/03/2099")
    check("future date rejected", r.value is None, str(r))
    r = await parse(DOB, "పన్నెండు మార్చి రెండు వేల ఐదు")
    check("Telugu spoken date (LLM)", r.value == "2005-03-12", str(r))
    r = await parse(DOB, "ముప్పై ఫిబ్రవరి")
    check("impossible LLM date rejected", r.value is None, str(r))

    # ---- email
    r = await parse(EMAIL, "sita at gmail dot com")
    check("spoken email", r.value == "sita@gmail.com" and r.confident, str(r))
    r = await parse(EMAIL, "my email is sita.devi at gmail dot com")
    check("email inside a sentence -> confirm", r.value == "sita.devi@gmail.com" and not r.confident, str(r))

    # ---- options
    r = await parse(GENDER, "Female", GENDERS)
    check("exact option", r.value == "Female" and r.source == "rules", str(r))
    r = await parse(GENDER, "ఆడ", GENDERS)
    check("Telugu option meaning (LLM)", r.value == "Female", str(r))
    r = await parse(GENDER, "మగ కాదు", GENDERS)
    check("off-list LLM option rejected", r.value is None, str(r))
    r = await parse(GENDER, "a", GENDERS)
    check("'a' does not pick Male", r.value is None, str(r))

    # ---- word matching fixes
    check("'book it' is not yes", readback.parse_yes_no("book it") is None)
    check("'I know' is not no", readback.parse_yes_no("I know it") is None)
    check("Hindi 'chalu karo' is not stop", not readback.is_stop("chalu karo"))
    check("Hindi 'aap' is not stop", not readback.is_stop("aap ka naam"))
    check("'please stop' is stop", readback.is_stop("please stop"))

    # ---- conversation flow (VoiceAgent.ask_field)
    v = FakeVoice(["అవును", "Sita Devi", "అవును"])
    value = await v.agent.ask_field(NAME, [])
    check("name: 'yes' re-asked, then confirmed", value == "Sita Devi" and v.stored.get("full_name") == "Sita Devi", str(v.asked))
    check("name confirmation question asked", any("Sita Devi. సరేనా?" in a for a in v.asked))

    v = FakeVoice(["Female"])
    value = await v.agent.ask_field(GENDER, GENDERS)
    check("gender echoed, no yes/no", value == "Female" and len(v.asked) == 1 and v.said == ["Female, సరే."], str(v.said))

    v = FakeVoice(["9876543210", "కాదు", "9876500000", "అవును"])
    value = await v.agent.ask_field(PHONE, [])
    check("phone rejected at confirm, new number taken", value == "9876500000", str(v.asked))

    v = FakeVoice(["12 March 2005", "13 March 2005", "అవును"])
    value = await v.agent.ask_field(DOB, [])
    check("corrected value given instead of yes/no", value == "2005-03-13", str(v.asked))

    v = FakeVoice(["123", "456", "789", "000"])
    try:
        await v.agent.ask_field(PHONE, [])
        handed_off = False
    except Exception as exc:  # noqa: BLE001
        handed_off = type(exc).__name__ == "HandoffError"
    check("hand off after repeated unusable answers", handed_off and "10 అంకెలు" in v.asked[1], str(v.asked))

    v = FakeVoice(["ఆగు"])
    try:
        await v.agent.ask_field(NAME, [])
        stopped = False
    except StopRequested:
        stopped = True
    check("stop word halts the question", stopped)

    v = FakeVoice(["Sita Devi", "అవును", "9876543210", "అవును"])
    await v.agent.ask_field(NAME, [])
    await v.agent.ask_field(PHONE, [])
    check("forget drops a voice answer", v.agent.forget("phone") and "phone" not in v.stored)
    check("forget ignores profile values", not v.agent.forget("email"))
    v.replies += ["9876543210", "అవును"]
    await v.agent.ask_field(PHONE, [])
    before = len(v.asked)
    await v.agent.before_action(
        {"tag": "button", "label": "Save & Continue"}, {"path": "/portal/application/form-1"}, {}
    )
    check("no second name/phone read-back when both were confirmed", len(v.asked) == before)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} answer checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
