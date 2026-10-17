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
from app.agent import answers, fields, readback


class StopRequested(Exception):
    """The user said a stop word; the loop must halt."""


class HandoffError(Exception):
    """The user's answer could not be used; the loop should hand off."""


FORM_1 = "/portal/application/form-1"
CORRECTION_CYCLES = 3
FIELD_ATTEMPTS = 4                              # tries to get a usable answer for one field
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

    async def _ask_value(self, field: str) -> str | None:
        prompt = self.lang.say("new_value", label=self.lang.label(field))
        for _ in range(2):
            answer = await self._ask_and_parse(prompt, "value")
            value = readback.extract_field_value(field, answer, self.lang.code)
            if value:
                return value
        return None

    def _apply_correction(self, field: str, value: str) -> dict | None:
        if self._on_correction is None:
            return None
        return self._on_correction(field, value)

    async def _correction_from_answer(self, answer: str, profile: dict) -> tuple[dict | None, bool]:
        """If the answer is a correction, collect the value and apply it."""
        correction = readback.parse_correction(answer)
        if correction is None:
            return profile, False
        field, value = correction
        if value is None:
            value = await self._ask_value(field)
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
            value = await self._ask_value(field)
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
        label = self.lang.label(spec.key, spec.label)
        if options:
            base = self.lang.say("ask_options", label=label, options=", ".join(options))
        else:
            base = self.lang.say("ask_value", label=label)
        prompt = base
        answer: str | None = None
        for _ in range(FIELD_ATTEMPTS):
            if answer is None:
                answer = await self._ask_and_parse(prompt, spec.kind)
            parsed = await answers.parse_answer(spec, answer, trace_id=self._trace_id, language=self.lang.code)
            answer = None
            if parsed.value is None:
                prompt = self.lang.say("retry") + base + answers.hint(spec, self.lang)
                continue
            said = answers.spoken(spec, parsed.value, self.lang)
            if spec.key in CONFIRM_KEYS or not parsed.confident:
                reply = await self._ask_and_parse(self.lang.say("confirm", value=said), "yes_no")
                verdict = readback.parse_yes_no(reply, self.lang.code)
                if verdict is True:
                    return self._accept(spec, parsed.value, confirmed=True)
                if verdict is None:
                    answer = reply  # they may have just said the (corrected) value again
                prompt = self.lang.say("reask") + base
                continue
            self._say(self.lang.say("echo", value=said))  # echo, then move on
            return self._accept(spec, parsed.value, confirmed=False)
        raise HandoffError(f"no usable answer for {spec.label!r}")

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
