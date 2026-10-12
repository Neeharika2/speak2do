#!/usr/bin/env python3
"""M2 guard checks: forced-loop halt, action budget, token cost cap.

Run:
    BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/agent_guards.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx

from app import config, events
from app.agent import loop as loop_module
from app.agent.loop import run_agent_goal

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


async def main() -> int:
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. forced loop on the trap page — must halt safely, not run away
        trap = await run_agent_goal(
            "Reach the review page.",
            trace_id=events.new_trace_id(),
            start_url=f"{config.PORTAL_URL}/loop-trap",
            success_url="/review",
            max_actions=12,
            max_seconds=60,
        )
        check(
            "forced loop halts safely",
            (not trap["success"])
            and trap["stop_reason"] in ("no_progress", "blocked", "action_budget", "done_claimed")
            and trap["steps"] <= 12
            and trap["wall_s"] < 75,
            f"stop={trap['stop_reason']} steps={trap['steps']} wall={trap['wall_s']}s",
        )

        # 2. action budget — stops at the cap
        await client.post(f"{config.BASE_URL}/portal/__reset")
        budget = await run_agent_goal(
            config.AGENT_GOAL,
            trace_id=events.new_trace_id(),
            start_url=f"{config.PORTAL_URL}{config.AGENT_START_PATH}",
            success_url=config.AGENT_SUCCESS_PATH,
            max_actions=3,
            max_seconds=60,
        )
        check(
            "action budget enforced",
            (not budget["success"]) and budget["stop_reason"] == "action_budget" and budget["steps"] <= 3,
            f"stop={budget['stop_reason']} steps={budget['steps']}",
        )

        # 3. token cost cap — halts after the first costly decision
        await client.post(f"{config.BASE_URL}/portal/__reset")
        cost = await run_agent_goal(
            config.AGENT_GOAL,
            trace_id=events.new_trace_id(),
            start_url=f"{config.PORTAL_URL}{config.AGENT_START_PATH}",
            success_url=config.AGENT_SUCCESS_PATH,
            max_actions=50,
            max_seconds=60,
            max_tokens=1,
        )
        check(
            "token cost cap enforced",
            (not cost["success"]) and cost["stop_reason"] == "cost_budget",
            f"stop={cost['stop_reason']} tokens={cost['tokens']}",
        )

    # 4. no-progress detector — force a stalled agent that never changes state
    original_decide = loop_module._decide

    async def always_wait(goal, obs, recent):
        return {"operation": "wait", "target": None}, 0

    loop_module._decide = always_wait
    try:
        stalled = await run_agent_goal(
            "Reach the review page.",
            trace_id=events.new_trace_id(),
            start_url=f"{config.PORTAL_URL}{config.AGENT_START_PATH}",
            success_url=config.AGENT_SUCCESS_PATH,
            max_actions=20,
            max_seconds=60,
        )
    finally:
        loop_module._decide = original_decide
    check(
        "no-progress detector stops a stalled agent",
        (not stalled["success"]) and stalled["stop_reason"] == "no_progress",
        f"stop={stalled['stop_reason']} steps={stalled['steps']}",
    )

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} guard checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
