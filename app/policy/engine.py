"""Deterministic policy engine (plan section 4.1).

M1 skeleton: every action flows through decision.py so rules can be added in M4
without touching callers. The model proposes, policy disposes, executor acts.
"""

from __future__ import annotations

from dataclasses import dataclass

ALLOW, CONFIRM, DENY, HANDOFF = "allow", "confirm", "deny", "handoff"


@dataclass
class Decision:
    verdict: str
    reason: str = ""


def decide(action: dict) -> Decision:
    """M1: pass-through. M4 replaces the body with the rule table."""
    return Decision(ALLOW, "M1 pass-through")
