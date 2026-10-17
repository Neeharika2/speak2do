#!/usr/bin/env python3
"""Show utterances the voice layer could not place (step-1 measurement).

Rules first, LLM fallback second; anything that matches neither is logged as
`voice.unmatched` with its context. Review this list to grow the rule
vocabulary or tune the fallback prompt.

Run:
    .venv/bin/python scripts/voice_unmatched.py            # last 50
    .venv/bin/python scripts/voice_unmatched.py --limit 0  # all
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="max rows to print (0 = all)")
    args = parser.parse_args()

    rows: list[dict] = []
    if config.EVENTS_FILE.exists():
        for line in config.EVENTS_FILE.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("stage") == "voice.unmatched":
                rows.append(entry)

    if not rows:
        print(f"no voice.unmatched events in {config.EVENTS_FILE}")
        return 0

    contexts = Counter(row.get("context", "?") for row in rows)
    print(f"{len(rows)} unmatched utterances  {dict(contexts)}\n")
    shown = rows if args.limit == 0 else rows[-args.limit :]
    for row in shown:
        print(f"{row.get('ts', '')}  [{row.get('context', '?'):16}] {row.get('transcript', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
