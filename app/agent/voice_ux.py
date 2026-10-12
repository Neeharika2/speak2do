"""Interactive voice layer for the agent loop (M3 + corrections).

- spoken progress at major page transitions;
- read-back + confirmation before leaving form 1, with a correction dialogue
  ("కాదు" / "నా నంబర్ మారింది" → which field → new value → re-read);
- asking the user for a missing field, reading options aloud;
- stop ("ఆగు") and repeat ("మళ్ళీ") handling.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from app.agent import readback


class StopRequested(Exception):
    """The user said a stop word; the loop must halt."""


class HandoffError(Exception):
    """The user's answer could not be used; the loop should hand off."""


FORM_1 = "/portal/application/form-1"
CORRECTION_CYCLES = 3

PROGRESS = {
    "/portal/dashboard": "లాగిన్ అయింది.",
    "/portal/application/form-1": "మొదటి ఫారం నింపుతున్నాను.",
    "/portal/application/form-2": "విద్య వివరాలు నింపుతున్నాను.",
    "/portal/application/form-3": "చిరునామా వివరాలు నింపుతున్నాను.",
    "/portal/application/review": "రివ్యూ పేజీకి చేరుకున్నాను.",
}


class VoiceAgent:
    def __init__(
        self,
        say: Callable[[str], None],
        ask: Callable[[str, str], Awaitable[str]],
        stop_requested: Callable[[], bool] = lambda: False,
        on_correction: Callable[[str, str], dict] | None = None,
    ) -> None:
        self._say = say
        self._ask = ask
        self._stop = stop_requested
        self._on_correction = on_correction
        self._last_path: str | None = None
        self._readbacks: set[str] = set()

    async def on_page(self, path: str) -> None:
        if path == self._last_path:
            return
        self._last_path = path
        message = PROGRESS.get(path)
        if message:
            self._say(message)

    async def _ask_and_parse(self, prompt: str, kind: str) -> str:
        for _ in range(3):
            answer = await self._ask(prompt, kind)
            if readback.is_stop(answer):
                raise StopRequested(answer)
            if readback.is_repeat(answer):
                self._say(prompt)
                continue
            return answer
        raise HandoffError("no usable answer after repeats")

    async def _ask_value(self, field: str) -> str | None:
        label_te = readback.FIELD_LABELS_TE.get(field, field)
        for _ in range(2):
            answer = await self._ask_and_parse(f"కొత్త {label_te} చెప్పండి.", "value")
            value = readback.extract_field_value(field, answer)
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
            prompt = readback.name_phone_prompt(profile.get("full_name", ""), profile.get("phone", ""))
            answer = await self._ask_and_parse(prompt, "yes_no")

            profile, was_correction = await self._correction_from_answer(answer, profile)
            if was_correction:
                if profile is None:
                    return None
                continue

            verdict = readback.parse_yes_no(answer)
            if verdict is True:
                return profile
            if verdict is None:
                answer = await self._ask_and_parse("మళ్ళీ చెప్పండి. " + prompt, "yes_no")
                profile, was_correction = await self._correction_from_answer(answer, profile)
                if was_correction:
                    if profile is None:
                        return None
                    continue
                if readback.parse_yes_no(answer) is True:
                    return profile

            # explicit "no" (or unclear twice): ask which field, then collect the new value
            field = readback.parse_field_choice(
                await self._ask_and_parse("ఏది మార్చాలి? పేరు లేదా ఫోన్ నంబర్?", "field")
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

    async def ask_field(self, label: str, options: list[str]) -> str:
        """Ask the user for a field value; read options aloud for selects."""
        if options:
            prompt = readback.options_prompt(label, options)
            answer = await self._ask_and_parse(prompt, "option")
            match = readback.match_option(answer, options)
            if match is None:
                answer = await self._ask_and_parse("క్షమించండి. " + prompt, "option")
                match = readback.match_option(answer, options)
            if match is None:
                raise HandoffError(f"no option matched for {label!r}")
            return match
        return (await self._ask_and_parse(readback.value_prompt(label), "value")).strip()

    async def before_action(self, element: dict, obs: dict, profile: dict) -> None:
        """Read back name + phone once, before leaving the first form."""
        if obs.get("path") != FORM_1 or "form-1" in self._readbacks:
            return
        label = (element.get("label") or "").lower()
        if element.get("tag") != "button" or not ("save" in label or "continue" in label):
            return
        self._readbacks.add("form-1")
        confirmed = await self._readback_cycle(profile)
        if confirmed is None:
            self._say(readback.READBACK_REJECTED)
            raise HandoffError("read-back not confirmed")
