"""Jev-driven agent loop (M2): observe -> decide -> validate -> execute -> verify.

Budgets: max actions, wall time, retries per action, token cost cap.
Guards: no-progress detector (repeated page states / repeated actions), consecutive errors.
Secrets never enter the model state (values.py redacts; the executor supplies them).
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Callable

from app import events, policy
from app.agent import jev_client, values
from app.agent.observe import observe_page
from app.agent.voice_ux import HandoffError, StopRequested
from app.browser.controller import BrowserController

OPERATION_QUESTION = {
    "type": "choice",
    "instructions": (
        "Choose the next operation that advances the goal on this page. Fill empty required fields "
        "before clicking buttons; never repeat an action that is already reflected in element values."
    ),
    "criteria": {
        "click": "Click the selected element (link, button, or checkbox).",
        "type": "Type the required value into the selected text field.",
        "select": "Choose an option in the selected dropdown.",
        "wait": "The page is still changing; wait briefly and decide again.",
        "done": "The goal is already complete on this page.",
        "blocked": "No listed element action can safely advance the goal.",
    },
}

MAX_TARGETS = 18           # elements offered to Jev per step (choice criteria cap is 20)
STALL_LIMIT = 4            # identical page states before no_progress
ERROR_STREAK_LIMIT = 3     # consecutive action errors before stopping
REPEATED_ACTION_LIMIT = 3  # identical actions in a row before no_progress


def _element_summary(element: dict) -> str:
    base = f'{element["role"]} "{element["label"]}"'
    tag, etype, value = element["tag"], element["type"], element["value"]
    if tag in ("input", "textarea") and etype not in ("checkbox", "radio", "submit", "button"):
        return base + (f" (filled: {value})" if value else " (empty)")
    if tag == "select":
        if value in ("", "Select"):
            return base + " (no selection)"
        return base + f" (selected: {value})"
    if etype in ("checkbox", "radio"):
        return base + (" (checked)" if value == "checked" else " (unchecked)")
    return base


def _is_empty_field(element: dict) -> bool:
    tag, etype, value = element["tag"], element["type"], element["value"]
    if tag == "select":
        return value in ("", "Select")
    if tag in ("input", "textarea"):
        return etype not in ("checkbox", "radio", "submit", "button") and value == ""
    return False


def _target_candidates(candidates: list[dict]) -> list[dict]:
    """Bounded action set (plan §3): remove hidden/disabled/incompatible and premature targets.

    While empty fields exist, offer only those (fill before submit); afterwards offer
    clickable elements (links, buttons, checkboxes).
    """
    empty_fields = [e for e in candidates if _is_empty_field(e)]
    if empty_fields:
        return empty_fields
    return [
        e
        for e in candidates
        if e["tag"] in ("a", "button") or e["type"] in ("checkbox", "radio", "submit", "button")
    ]


def _normalize_operation(element: dict, operation: str) -> str:
    """Map a model-chosen operation to the primitive the element actually supports."""
    if operation in ("wait", "done", "blocked"):
        return operation
    tag, etype = element["tag"], element["type"]
    if tag == "select":
        return "select"
    if tag in ("a", "button") or etype in ("checkbox", "radio", "submit", "button"):
        return "click"
    if tag in ("input", "textarea"):
        return "type"
    return operation


def _signature(obs: dict) -> str:
    parts = [obs["path"]]
    for element in obs["elements"][:MAX_TARGETS]:
        parts.append(f"{element['label']}|{element['value']}")
    return hashlib.md5("||".join(parts).encode()).hexdigest()


async def _decide(goal: str, obs: dict, recent: list[str]) -> tuple[dict, int]:
    candidates = obs["elements"][:MAX_TARGETS]
    targets = _target_candidates(candidates)[:MAX_TARGETS]
    if not targets:
        return {"operation": "blocked", "target": None}, 0
    questions: dict = {"operation": OPERATION_QUESTION}
    if len(targets) >= 2:
        questions["target"] = {
            "type": "choice",
            "instructions": "If click/type/select was chosen, pick the target element id.",
            "criteria": {str(e["id"]): _element_summary(e) for e in targets},
        }
    state = {
        "goal": goal,
        "page": {"path": obs["path"], "heading": obs["heading"]},
        "elements": [
            {"id": e["id"], "role": e["role"], "label": e["label"], "value": e["value"]} for e in candidates
        ],
        "recent_actions": recent[-6:],
    }
    data = await jev_client.decide(state, questions)
    usage = data.get("usage", {}) or {}
    tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    answers = data.get("answers", {}) or {}
    operation = (answers.get("operation") or {}).get("choice")
    target = (answers.get("target") or {}).get("choice")
    if target is None and len(targets) == 1:
        target = str(targets[0]["id"])
    return {"operation": operation, "target": None if target is None else str(target)}, tokens


def _choose_option(options: list[dict], wanted: str) -> dict | None:
    wanted = (wanted or "").strip().lower()
    usable = [o for o in options if not o["disabled"] and o["text"] and o["text"].strip().lower() != "select"]
    if not usable or not wanted:
        return None
    for option in usable:
        if option["text"].lower() == wanted:
            return option
    for option in usable:
        text = option["text"].lower()
        if text.startswith(wanted) or wanted.startswith(text):
            return option
    return None  # never guess: a wrong option is worse than asking again


async def _perform(browser: BrowserController, element: dict, operation: str, value: str) -> None:
    assert browser.page is not None
    locator = browser.page.locator(f'[data-agent-id="{element["id"]}"]')
    await locator.wait_for(state="attached", timeout=5000)
    if operation == "click":
        await locator.click(timeout=5000)
    elif operation == "type":
        await locator.fill(value, timeout=5000)
    elif operation == "select":
        options = await locator.evaluate(
            "el => Array.from(el.options).map(o => ({text: o.text.trim(), value: o.value, disabled: o.disabled}))"
        )
        chosen = _choose_option(options, value)
        if chosen is None:
            raise RuntimeError(f"no option for {value!r} in {[o['text'] for o in options]}")
        await locator.select_option(value=chosen["value"] or chosen["text"], timeout=5000)
    else:
        raise ValueError(f"unsupported operation: {operation}")


async def _apply_overrides(browser: BrowserController, trace_id: str, obs: dict, overrides: dict) -> None:
    """Re-fill fields on the current page whose value was corrected by voice."""
    if not overrides:
        return
    for element in obs["elements"]:
        key = values.label_key(element["label"])
        if key is None or key not in overrides:
            continue
        wanted = str(overrides[key] or "").strip()
        if not wanted:
            continue
        if str(element.get("value") or "").strip() == wanted:
            continue
        operation = _normalize_operation(element, "type")
        if operation not in ("type", "select"):
            continue
        try:
            await _perform(browser, element, operation, wanted)
            events.log_event(trace_id, "agent.override_applied", field=key, label=element["label"])
        except Exception as exc:  # noqa: BLE001
            events.log_event(trace_id, "agent.override_error", field=key, error=str(exc))


async def run_agent_goal(
    goal: str,
    *,
    trace_id: str,
    start_url: str,
    success_url: str = "",
    max_actions: int = 50,
    max_seconds: float = 300.0,
    max_retries: int = 2,
    max_tokens: int = 60_000,
    stall_limit: int = STALL_LIMIT,
    error_limit: int = ERROR_STREAK_LIMIT,
    live_dir: Path | None = None,
    headless: bool = True,
    on_step: Callable[[str], None] | None = None,
    voice_io: object | None = None,
    stop_check: Callable[[], bool] | None = None,
    profile_overrides: Callable[[], dict] | None = None,
    profile: dict | None = None,
) -> dict:
    """Run the observe/decide/act loop until success or a budget/guard stops it."""
    started = time.monotonic()
    base_profile = profile if profile is not None else values.load_profile()

    def current_profile() -> dict:
        if profile_overrides is None:
            return base_profile
        try:
            overrides = profile_overrides() or {}
        except Exception:  # noqa: BLE001
            overrides = {}
        merged = dict(base_profile)
        merged.update(overrides)
        return merged
    browser = BrowserController(headless=headless)
    await browser.start()

    actions: list[str] = []
    step_durations: list[float] = []
    recent: list[str] = []
    tokens = 0
    stall = 0
    consecutive_errors = 0
    stop_reason = "action_budget"
    error: str | None = None
    last_signature = ""
    final_url = ""

    def goal_reached() -> bool:
        return bool(success_url) and browser.page is not None and success_url in browser.page.url

    try:
        await browser.goto(start_url)
        events.log_event(trace_id, "agent.start", goal=goal, start_url=start_url, success_url=success_url)

        while True:
            if stop_check and stop_check():
                stop_reason = "user_stop"
                break
            if goal_reached():
                stop_reason = "done"
                break
            if len(actions) >= max_actions:
                stop_reason = "action_budget"
                break
            if time.monotonic() - started > max_seconds:
                stop_reason = "time_budget"
                break
            if tokens > max_tokens:
                stop_reason = "cost_budget"
                break

            step_started = time.perf_counter()
            try:
                obs = await observe_page(browser.page)
            except Exception as exc:  # noqa: BLE001
                stop_reason, error = "observe_error", str(exc)
                break

            if goal_reached():
                stop_reason = "done"
                break

            if voice_io is not None:
                await voice_io.on_page(obs["path"])

            signature = _signature(obs)
            stall = stall + 1 if signature == last_signature else 0
            last_signature = signature
            if stall >= stall_limit:
                stop_reason = "no_progress"
                break

            try:
                decision, used = await _decide(goal, obs, recent)
            except Exception as exc:  # noqa: BLE001
                stop_reason, error = "decision_error", str(exc)
                break
            tokens += used

            operation = decision["operation"]
            target = decision["target"]

            if operation == "blocked":
                stop_reason = "blocked"
                break
            if operation == "done":
                # Jev may answer "done" while the page is still navigating; re-check after a beat.
                await asyncio.sleep(0.5)
                stop_reason = "done" if goal_reached() else "done_claimed"
                break
            if operation is None:
                stop_reason, error = "decision_error", "no operation returned"
                break
            if operation == "wait":
                actions.append(f"wait ({obs['path']})")
                step_durations.append(round(time.perf_counter() - step_started, 2))
                await asyncio.sleep(0.5)
                if stop_check and stop_check():
                    stop_reason = "user_stop"
                    break
                continue

            element = next((e for e in obs["elements"] if str(e["id"]) == str(target)), None)
            if element is None:
                actions.append(f"{operation} ? (stale target {target})")
                consecutive_errors += 1
                if consecutive_errors >= error_limit:
                    stop_reason = "action_errors"
                    break
                continue

            operation = _normalize_operation(element, operation)

            value = ""
            if operation in ("type", "select"):
                mapped = values.mapped_value(element["label"], current_profile())
                if mapped is not None and str(mapped).strip():
                    value = mapped
                elif voice_io is not None:
                    try:
                        options: list[str] = []
                        if element["tag"] == "select" and browser.page is not None:
                            options = await browser.page.locator(
                                f'[data-agent-id="{element["id"]}"]'
                            ).evaluate(
                                "el => Array.from(el.options).map(o => o.text.trim()).filter(t => t && t !== 'Select')"
                            )
                        value = await voice_io.ask_field(element, options)
                    except StopRequested:
                        stop_reason = "user_stop"
                        break
                    except HandoffError as exc:
                        stop_reason, error = "handoff", str(exc)
                        break

            policy_decision = policy.decide(
                {
                    "kind": operation,
                    "selector": element["label"],
                    "value": "[REDACTED]" if values.is_secret(element["label"]) else value,
                    "has_value": bool(value),
                }
            )
            if policy_decision.verdict != policy.ALLOW:
                stop_reason = f"policy_{policy_decision.verdict}"
                break

            if stop_check and stop_check():
                stop_reason = "user_stop"
                break
            if voice_io is not None:
                try:
                    await voice_io.before_action(element, obs, current_profile())
                except StopRequested:
                    stop_reason = "user_stop"
                    break
                except HandoffError as exc:
                    stop_reason, error = "handoff", str(exc)
                    break
            if profile_overrides is not None:
                try:
                    await _apply_overrides(browser, trace_id, obs, profile_overrides() or {})
                except Exception as exc:  # noqa: BLE001
                    events.log_event(trace_id, "agent.override_error", error=str(exc))

            label = f"{operation} {element['label']!r}"
            if value:
                label += f" = {values.display_value(element['label'], value)}"

            action_error: Exception | None = None
            for _attempt in range(max_retries + 1):
                try:
                    await _perform(browser, element, operation, value)
                    action_error = None
                    break
                except Exception as exc:  # noqa: BLE001
                    action_error = exc
                    await asyncio.sleep(0.3)
            if action_error is not None:
                consecutive_errors += 1
                actions.append(f"{label} [failed: {action_error}]")
                if voice_io is not None and voice_io.forget(values.label_key(element["label"])):
                    # the page rejected the user's answer: ask for it again instead of retrying it
                    events.log_event(trace_id, "agent.answer_rejected", label=element["label"], error=str(action_error))
                if consecutive_errors >= error_limit:
                    stop_reason = "action_errors"
                    break
                continue
            consecutive_errors = 0

            actions.append(label)
            recent.append(label)
            if len(recent) > 6:
                recent.pop(0)
            duration = round(time.perf_counter() - step_started, 2)
            step_durations.append(duration)
            events.log_event(
                trace_id,
                "agent.action",
                duration_ms=duration * 1000,
                action=label,
                operation=operation,
                target=target,
                tokens=tokens,
                policy=policy_decision.verdict,
            )
            if on_step:
                on_step(label)
            if live_dir is not None:
                try:
                    await browser.screenshot(live_dir / "view.png")
                except Exception:  # noqa: BLE001
                    pass
            if len(actions) >= REPEATED_ACTION_LIMIT and actions[-1] == actions[-2] == actions[-3]:
                stop_reason = "no_progress"
                break
            await asyncio.sleep(0.15)

        final_url = browser.page.url if browser.page else ""
    finally:
        await browser.stop()

    success = stop_reason == "done" or (bool(success_url) and success_url in final_url)
    result = {
        "success": success,
        "stop_reason": stop_reason,
        "steps": len(actions),
        "actions": actions,
        "wall_s": round(time.monotonic() - started, 2),
        "step_durations_s": step_durations,
        "tokens": tokens,
        "error": error,
        "final_url": final_url,
    }
    events.log_event(
        trace_id,
        "agent.done",
        success=success,
        stop_reason=stop_reason,
        steps=len(actions),
        wall_s=result["wall_s"],
        tokens=tokens,
    )
    return result
