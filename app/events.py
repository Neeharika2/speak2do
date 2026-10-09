"""Trace-id event log: every stage emits one JSON line to data/task_events.jsonl."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.config import EVENTS_FILE


def new_trace_id() -> str:
    return f"tr_{uuid.uuid4().hex[:12]}"


def log_event(trace_id: str, stage: str, *, duration_ms: float | None = None, **detail: Any) -> dict:
    """Append one event; returns the entry (useful for tests)."""
    entry: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "trace_id": trace_id,
        "stage": stage,
    }
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 1)
    entry.update(detail)
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
