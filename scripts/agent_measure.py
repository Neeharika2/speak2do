#!/usr/bin/env python3
"""M2 measurement: run the Jev-driven agent N times and report the success rate.

Gate (plan M2): reach the review page in >= 8/10 runs; document median step time.

Run:
    BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/agent_measure.py --runs 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx

from app import config, events
from app.agent.loop import run_agent_goal

GOAL = "Complete the scholarship application forms and reach the review page."


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--max-actions", type=int, default=50)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    results: list[dict] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for run in range(1, args.runs + 1):
            await client.post(f"{config.BASE_URL}/portal/__reset")
            trace_id = events.new_trace_id()
            result = await run_agent_goal(
                GOAL,
                trace_id=trace_id,
                start_url=f"{config.PORTAL_URL}/login",
                success_url="/review",
                max_actions=args.max_actions,
                max_seconds=args.max_seconds,
            )
            result.update({"run": run, "trace_id": trace_id})
            results.append(result)
            print(
                f"run {run:>2}/{args.runs}: {'PASS' if result['success'] else 'FAIL'}  "
                f"steps={result['steps']:>2}  wall={result['wall_s']:>6.1f}s  "
                f"stop={result['stop_reason']}  tokens={result['tokens']}"
            )

    passes = sum(1 for r in results if r["success"])
    all_steps = [d for r in results for d in r["step_durations_s"]]
    median_step = statistics.median(all_steps) if all_steps else 0.0
    walls = [r["wall_s"] for r in results]
    report = {
        "runs": args.runs,
        "passes": passes,
        "pass_rate": round(passes / args.runs, 3),
        "median_step_s": round(median_step, 2),
        "median_wall_s": round(statistics.median(walls), 2) if walls else 0.0,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": results,
    }
    out_path = Path(args.out) if args.out else REPO_ROOT / "data" / f"agent_measure_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\npass rate: {passes}/{args.runs} ({report['pass_rate'] * 100:.0f}%)")
    print(f"median step time: {median_step:.2f}s (target < 5s)")
    print(f"median wall time: {report['median_wall_s']:.1f}s")
    print(f"report: {out_path}")
    gate = report["pass_rate"] >= 0.8
    print(f"M2 gate (>= 8/10): {'PASS' if gate else 'FAIL'}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
