# Phase 3 — M2: Agent Loop + Jev + Full Portal

**Window:** Fri 16 – Wed 21 Oct 2026 · **Implemented early: Fri 9 Oct** · **Status:** ✅ Complete — gate passed (10/10)
**Plan reference:** `voice_first_agent_plan_v4.md` §2.5, §3, §7 (M2)

## Goal (from the plan)

Mock portal application pages complete incl. hostile toggles. Agent (text goal) reaches the **review page** in **≥ 8 of 10 runs**; median step time documented (target < 5 s). Budgets enforced (max ~50 actions, ~5 min, 2 retries, cost cap). No-progress detector works.

---

## What was built

### Mock portal (now complete)

| Piece | File | Notes |
|---|---|---|
| Data layer | `app/portal/db.py` | draft merge, submit (normal vs trap), receipt IDs `SCH-2026-000123`, `submission_attempts` log, reset hook, M1→M2 schema migration |
| Routes | `app/portal/routes.py` | Form 1/2/3, Review, Submit, Receipt, Status, fake CAPTCHA, hostile controls, injected SVG, `__reset`, `loop-trap` |
| Hostile engine | `app/portal/hostile.py` | env `PORTAL_HOSTILE=a,b` + cookie endpoint `GET /portal/hostile?toggles=…` |
| Templates | `app/portal/templates/` | form2, form3 (dependent district dropdown), review (declaration + submit), receipt, captcha, trap; base has popup/injected content |

**Hostile toggles (8):** `slow`, `popup`, `inject_dom`, `inject_img`, `captcha`, `expiry`, `layout`, `dup_trap`.

### Jev-driven agent loop

| Piece | File | Notes |
|---|---|---|
| Observation | `app/agent/observe.py` | DOM/accessibility element list; secrets redacted before leaving the page; elements tagged `data-agent-id` |
| Value provider | `app/agent/values.py` | deterministic label→profile mapping; password/OTP supplied by executor, never to the model |
| LLM fallback | `app/agent/llm.py` | Gemini fills unknown field labels (cap: 15 calls/run) — not exercised in the gate run (all fields mapped) |
| Loop | `app/agent/loop.py` | observe → decide (Jev) → normalize → execute (Playwright) → verify; budgets + guards; `agent.action` events with timings/tokens |

**Loop design decisions:**
- Jev answers two typed questions per step: `operation` (click/type/select/wait/done/blocked) and `target` (bounded element list).
- The executor **normalizes** the primitive to the element type (select → `select`, button → `click`, text field → `type`), so a mislabeled operation cannot break execution.
- **Bounded action set:** while empty fields exist, only those are offered as targets; buttons/links appear only after fields are filled; filled fields are excluded entirely. (Prevents the observed failure modes: re-typing a filled field and premature submit.)
- **Budgets:** 50 actions, 300 s, 2 retries/action, 60k token cap, 15 LLM fallback calls.
- **No-progress detector:** page-state signature repeated 4×, or the same action 3× in a row → stop with `no_progress`.
- **Stop reasons:** done, action_budget, time_budget, cost_budget, no_progress, blocked, done_claimed, action_errors, observe/decision errors, policy.

## Verification (evidence)

| Test | Command | Result |
|---|---|---|
| Hostile toggles + submit dup handling | `scripts/hostile_check.py` | ✅ **14/14** (slow 2.0 s, popup, inject_dom, inject_img, layout, captcha, expiry, normal dedupe=1, trap dup=2) |
| Guards | `scripts/agent_guards.py` | ✅ **4/4**: trap page halts safely; action budget stops at 3; token cap stops with `cost_budget`; injected stall stops with `no_progress` at 4 steps |
| **M2 gate** | `scripts/agent_measure.py --runs 10` | ✅ **10/10** reach review; **median step 0.70 s**; median wall 21.1 s; ~19.4k tokens/run |
| M1 regression | `scripts/walking_skeleton.py` | ✅ PASS |
| M1 regression | `scripts/ui_smoke.py` | ✅ PASS (server must be started with matching `BASE_URL` on non-default ports) |

Full report: `data/agent_measure_<timestamp>.json`. Example run: 23 steps — login (3) → OTP (2) → dashboard (1) → form1 (6) → form2 (4) → form3 (5) → review.

## Plan M2 acceptance checklist

- [x] Mock portal application pages complete incl. hostile toggles
- [x] Agent (text goal) reaches the review page in ≥ 8/10 → **10/10**
- [x] Median step time documented → **0.70 s** (target < 5 s)
- [x] Budgets enforced: max actions / wall time / retries / cost cap
- [x] No-progress detector works (proven with a forced stall)
- [ ] Agent robustness *against* hostile modes — per plan this is M4 (injection suite, handoff, idempotency)
- [ ] Click-through handoff — carried into the M4 handoff work

## Post-review fixes (Fri 9 Oct, external review)

1. **Voice app wired to the real agent loop** — `/api/voice/command` and `/api/voice/text` now call `run_agent_goal` (was still the M1 `demo_flow`). Speaking runs the full flow to the review page; the spoken reply is success/failure-aware in Telugu.
2. **Stable element ids** — `data-agent-id` is assigned once per node (`window.__agentIdSeq`) instead of by observation order, so reactive re-renders / validation updates cannot shift targets.
3. **Secrets out of the policy path** — the policy action dict now receives `[REDACTED]` for password/OTP fields (plus `has_value`), so a future policy logger cannot leak them; event log re-verified at 0 occurrences.
4. **`done` claim race** — when Jev answers "done" mid-navigation the loop waits 0.5 s and re-checks the success URL; an unverified claim stops safely and stays distinct as `done_claimed`.

Verified after the fixes: agent 3/3 (median step 0.62 s), guards 4/4, `ui_smoke.py` end-to-end **23 steps** through the voice API, 0 secrets in the event log.

## How to run

```bash
.venv/bin/uvicorn app.main:app --port 8765          # in one terminal
.venv/bin/python scripts/hostile_check.py           # portal hostile checks
.venv/bin/python scripts/agent_guards.py            # budget/guard checks
.venv/bin/python scripts/agent_measure.py --runs 10 # gate measurement
```

Test-only hooks (mock portal): `POST /portal/__reset` clears applications; `GET /portal/loop-trap` is a deliberately stuck page.

## Known limitations

- The agent **reaches review only** — no declaration checkbox/submit path yet (M4/M5).
- Hostile modes are built and verified portal-side, but the agent is not yet hardened against them (that is exactly the M4 test suite).
- Wrong prefilled values are not corrected; only empty fields are filled.
- Cost cap is measured in tokens (Jev has no published per-token price at this stage) — treat as a proxy.
- Click-through handoff still pending (M4).
- Human-speech STT recordings still pending (Phase 1 carry-over).

## Open items

- [ ] Submit path + bound confirmation + idempotency (M4/M5)
- [ ] Hostile robustness: injection suite, captcha/expiry handoff (M4)
- [ ] Click-through handoff (M4)
- [ ] Human 5-phrase STT recordings (Phase 1)
- [ ] Jev mandatory question to organizers (Phase 1)

## Next phase

**Phase 4 — M3 (Thu 22 – Mon 26 Oct): voice UX in Telugu** — voice-to-voice to review, code-switched phrases, digit/name read-back, "Aagu" halts actions within 1 s, ≥ 90% entity accuracy after confirmation on a 30-phrase test set.
