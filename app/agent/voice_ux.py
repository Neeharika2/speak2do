"""Interactive voice layer for the agent loop (M3 + corrections).

- spoken progress at major page transitions;
- read-back + confirmation before leaving form 1, with a correction dialogue
  ("కాదు" / "నా నంబర్ మారింది" → which field → new value → re-read);
- asking the user for a missing field, reading options aloud;
- stop ("ఆగు") and repeat ("మళ్ళీ") handling.

Everything spoken comes from the session language's table (app/lang/<code>.json).
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from app import lang as langs
from app.agent import answers, fields, readback, spelling


class StopRequested(Exception):
    """The user said a stop word; the loop must halt."""


class HandoffError(Exception):
    """The user's answer could not be used; the loop should hand off."""


FORM_1 = "/portal/application/form-1"
CORRECTION_CYCLES = 3
FIELD_ATTEMPTS = 4                              # tries to get a usable answer for one field
SPELLABLE = {"text", "email"}                 # kinds the user may spell letter by letter
CONFIRM_KEYS = fields.CONFIRM_KEYS  # always confirmed: spelling matters

# page path -> phrase key spoken when the agent arrives there
PROGRESS = {
    "/portal/dashboard": "progress_dashboard",
    "/portal/application/form-1": "progress_form1",
    "/portal/application/form-2": "progress_form2",
    "/portal/application/form-3": "progress_form3",
    "/portal/application/review": "progress_review",
}


class VoiceAgent:
    def __init__(
        self,
        say: Callable[[str], None],
        ask: Callable[[str, str], Awaitable[str]],
        stop_requested: Callable[[], bool] = lambda: False,
        on_correction: Callable[[str, str], dict] | None = None,
        on_answer: Callable[[str, str], None] | None = None,
        on_forget: Callable[[str], None] | None = None,
        trace_id: str = "",
        language: str | None = None,
    ) -> None:
        self.lang = langs.get(language)
        self._say = say
        self._ask = ask
        self._stop = stop_requested
        self._on_correction = on_correction
        self._on_answer = on_answer
        self._on_forget = on_forget
        self._trace_id = trace_id
        self._last_path: str | None = None
        self._readbacks: set[str] = set()
        self._answered: set[str] = set()   # fields whose value came from the user's voice
        self._confirmed: set[str] = set()  # ... and that the user explicitly confirmed
        self._specs: dict[str, answers.FieldSpec] = {}  # field rules seen on the pages so far

    # ------------------------------------------------------------------ corrections (any language)

    def note_field(self, element: dict, options: list[str]) -> None:
        """Remember a page field's rules (length, options) so later corrections obey them."""
        spec = answers.field_spec(element, options)
        if spec.key:
            self._specs[spec.key] = spec

    def spec_for(self, key: str) -> answers.FieldSpec:
        return self._specs.get(key) or answers.default_spec(key, self.lang.label(key))

    async def value_for(self, key: str, text: str) -> str | None:
        """The new value for `key` in a correction utterance, or None."""
        return await answers.correction_value(
            self.spec_for(key), text, trace_id=self._trace_id, language=self.lang.code
        )

    async def correction_in(self, text: str) -> tuple[str, str | None] | None:
        """Is this a correction? (field, new value or None = ask for it). None = not a correction."""
        key = readback.parse_field_choice(text, self.lang.code)
        if key is None:
            return None
        value = await self.value_for(key, text)
        if value is None and not readback.change_requested(text, self.lang.code):
            if key == "full_name" and readback.has_repeated_token(readback.clean_text_value(text) or ""):
                return key, None  # old + new name in one sentence: ask again
            return None
        return key, value

    async def ask_new_value(self, key: str) -> str | None:
        """"New phone number?" — up to two tries."""
        prompt = self.lang.say("new_value", label=self.lang.label(key))
        for _ in range(2):
            value = await self.value_for(key, await self._ask_and_parse(prompt, "value"))
            if value:
                return value
        return None

    async def on_page(self, path: str) -> None:
        if path == self._last_path:
            return
        self._last_path = path
        key = PROGRESS.get(path)
        if key:
            self._say(self.lang.say(key))

    async def _ask_and_parse(self, prompt: str, kind: str) -> str:
        timeouts = 0
        for _ in range(3):
            try:
                answer = await self._ask(prompt, kind)
            except asyncio.TimeoutError as exc:
                # slow/quiet answer: re-ask once (the next _ask speaks again),
                # a second timeout means nobody is answering -> hand off
                timeouts += 1
                if timeouts >= 2:
                    raise HandoffError("no spoken answer within timeout") from exc
                continue
            if self._stop() or readback.is_stop(answer, self.lang.code):
                raise StopRequested(answer)
            if readback.is_repeat(answer, self.lang.code):
                self._say(prompt)
                continue
            return answer
        raise HandoffError("no usable answer after repeats")

    def _apply_correction(self, field: str, value: str) -> dict | None:
        if self._on_correction is None:
            return None
        return self._on_correction(field, value)

    async def _correction_from_answer(self, answer: str, profile: dict) -> tuple[dict | None, bool]:
        """If the answer is a correction, collect the value and apply it."""
        correction = await self.correction_in(answer)
        if correction is None:
            return profile, False
        field, value = correction
        if value is None:
            value = await self.ask_new_value(field)
        if not value:
            return None, True
        return self._apply_correction(field, value), True

    async def _readback_cycle(self, profile: dict) -> dict | None:
        """Read name + phone back; handle corrections; return the updated profile."""
        for _ in range(CORRECTION_CYCLES):
            prompt = self.lang.say(
                "readback_name_phone",
                name=profile.get("full_name", ""),
                phone=readback.spoken_digits(profile.get("phone", ""), self.lang.code),
            )
            answer = await self._ask_and_parse(prompt, "yes_no")

            profile, was_correction = await self._correction_from_answer(answer, profile)
            if was_correction:
                if profile is None:
                    return None
                continue

            verdict = readback.parse_yes_no(answer, self.lang.code)
            if verdict is True:
                return profile
            if verdict is None:
                answer = await self._ask_and_parse(self.lang.say("reask") + prompt, "yes_no")
                profile, was_correction = await self._correction_from_answer(answer, profile)
                if was_correction:
                    if profile is None:
                        return None
                    continue
                if readback.parse_yes_no(answer, self.lang.code) is True:
                    return profile

            # explicit "no" (or unclear twice): ask which field, then collect the new value
            field = readback.parse_field_choice(
                await self._ask_and_parse(self.lang.say("which_field"), "field"), self.lang.code
            )
            if field is None:
                return None
            value = await self.ask_new_value(field)
            if not value:
                return None
            updated = self._apply_correction(field, value)
            if updated is None:
                return None
            profile = updated
        return None

    async def ask_field(self, element: dict, options: list[str]) -> str:
        """Ask for one field, parse + validate the answer, confirm or echo it, and remember it."""
        spec = answers.field_spec(element, options)
        if spec.key:
            self._specs[spec.key] = spec
        label = self.lang.label(spec.key, spec.label)
        if options:
            base = self.lang.say("ask_options", label=label, options=", ".join(options))
        else:
            base = self.lang.say("ask_value", label=label)
        prompt = base
        answer: str | None = None
        can_spell = spec.kind in SPELLABLE
        spelling_mode = False  # the user chose to spell the value letter by letter
        last_value: str | None = None
        for _ in range(FIELD_ATTEMPTS):
            if answer is None:
                answer = await self._ask_and_parse(prompt, spec.kind)
            if can_spell and spelling.mentions_spelling(answer):
                spelling_mode = True
            if spelling_mode:
                value = self._spelled(spec, answer, last_value)
                answer = None
                if value is None:  # "I'll spell it" / "the spelling is wrong": ask for the letters
                    prompt = self.lang.say("ask_spelling")
                    continue
                reply = await self._ask_and_parse(self.lang.say("confirm", value=self._spell_back(value)), "yes_no")
                verdict = readback.parse_yes_no(reply, self.lang.code)
                if verdict is True:
                    return self._accept(spec, value, confirmed=True)
                if verdict is None:
                    answer = reply  # probably the letters again
                prompt = self.lang.say("reask") + self.lang.say("ask_spelling")
                continue
            parsed = await answers.parse_answer(spec, answer, trace_id=self._trace_id, language=self.lang.code)
            answer = None
            if parsed.value is None:
                prompt = self.lang.say("retry") + base + answers.hint(spec, self.lang)
                continue
            last_value = parsed.value
            said = answers.spoken(spec, parsed.value, self.lang)
            if spec.key in CONFIRM_KEYS or not parsed.confident:
                reply = await self._ask_and_parse(self.lang.say("confirm", value=said), "yes_no")
                verdict = readback.parse_yes_no(reply, self.lang.code)
                if verdict is True:
                    return self._accept(spec, parsed.value, confirmed=True)
                if verdict is None or (can_spell and spelling.mentions_spelling(reply)):
                    answer = reply  # a corrected value, or "the spelling is wrong"
                    continue
                prompt = self.lang.say("reask") + base
                continue
            self._say(self.lang.say("echo", value=said))  # echo, then move on
            return self._accept(spec, parsed.value, confirmed=False)
        raise HandoffError(f"no usable answer for {spec.label!r}")

    def _spelled(self, spec: answers.FieldSpec, text: str, last_value: str | None) -> str | None:
        """Letters the user spelled -> a valid value; None when no letters were heard yet."""
        letters = spelling.decode(text)
        if spelling.letter_count(letters) < 2:
            return None
        if spec.kind == "email":
            value = letters.replace(" ", "").lower()
            if "@" not in value and last_value and "@" in last_value:
                value += "@" + last_value.split("@", 1)[1]  # only the part before @ was spelled
        else:
            value = " ".join(word.capitalize() for word in letters.split())
        return answers.validate(spec, value, self.lang.code)

    @staticmethod
    def _spell_back(value: str) -> str:
        if "@" in value:
            local, domain = value.split("@", 1)
            return f"{spelling.spell_out(local)} @ {domain}"
        return spelling.spell_out(value)

    def _accept(self, spec: answers.FieldSpec, value: str, *, confirmed: bool) -> str:
        if spec.key:
            self._answered.add(spec.key)
            if confirmed:
                self._confirmed.add(spec.key)
            if self._on_answer is not None:
                self._on_answer(spec.key, value)  # stored once: retries and later pages never re-ask
        return value

    def forget(self, key: str | None) -> bool:
        """Drop a voice answer the page rejected so the field is asked again. False if not ours."""
        if not key or key not in self._answered:
            return False
        self._answered.discard(key)
        self._confirmed.discard(key)
        if self._on_forget is not None:
            self._on_forget(key)
        return True

    async def before_action(self, element: dict, obs: dict, profile: dict) -> None:
        """Read back name + phone once, before leaving the first form."""
        if obs.get("path") != FORM_1 or "form-1" in self._readbacks:
            return
        label = (element.get("label") or "").lower()
        if element.get("tag") != "button" or not ("save" in label or "continue" in label):
            return
        self._readbacks.add("form-1")
        if {"full_name", "phone"} <= self._confirmed:
            return  # both were already confirmed when the user gave them
        confirmed = await self._readback_cycle(profile)
        if confirmed is None:
            self._say(self.lang.say("readback_rejected"))
            raise HandoffError("read-back not confirmed")
