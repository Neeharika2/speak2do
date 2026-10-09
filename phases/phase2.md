# Phase 2 — M1: Walking Skeleton + Voice App

**Window:** Mon 12 – Thu 15 Oct 2026 (started early: Fri 9 Oct) · **Status:** 🟡 In progress — click-through handoff remaining
**Plan reference:** `voice_first_agent_plan_v4.md` §3 (architecture), §5 (handoff)

## Goal (from the plan)

Push-to-talk → STT → hardcoded intent → Playwright login on the mock portal → navigate to the form → fill two fields → TTS confirms. Live view shows the browser. Policy skeleton (pass-through) in the path. `trace_id` in every event; per-stage timings logged.

**Extra built beyond the plan text:** a real browser push-to-talk page (`/assistant`) with hold/tap recording, live view, transcript, steps, and a text fallback.

---

## What was built

### Runtime pieces

| Piece | File | Notes |
|---|---|---|
| FastAPI app (single process) | `app/main.py` | `/` → assistant, `/portal/*` → mock portal, `/health` |
| Config + paths | `app/config.py` | loads `.env`; vendor endpoints; demo defaults |
| Event log (trace_id, timings) | `app/events.py` | appends to `data/task_events.jsonl` |
| Gnani STT adapter | `app/voice/stt.py` | `transcribe(path) -> {transcript, latency_ms}` |
| Gnani TTS adapter | `app/voice/tts.py` | `speak(text) -> wav path` |
| Policy skeleton | `app/policy/engine.py` | pass-through `Allow`; every action flows through it |
| Jev client | `app/agent/jev_client.py` | TypeSafe System One `decide(state, questions)` |
| Demo flow | `app/agent/demo_flow.py` | login → OTP → dashboard → form-1 fill (name + phone) |
| Playwright controller | `app/browser/controller.py` | only module touching the browser; atomic screenshots |
| Voice API | `app/api/voice.py` | PTT command, sessions, live-view frame, reply audio |
| Assistant page | `app/templates/assistant.html` | hold/tap-to-talk (WAV in-browser), live view, transcript, steps, text fallback |

### Mock portal (M1 slice)

- `app/portal/routes.py` + templates + SQLite (`app/portal/db.py`)
- Pages: `/portal/login` → `/portal/login/otp` → `/portal/dashboard` → `/portal/status` → `/portal/application/form-1`
- Test credentials: `demo_user` / `demo_pass_123`, OTP `246810` (from config)

### Tooling

- `scripts/walking_skeleton.py` — CLI end-to-end smoke (voice → agent → confirmation)
- `scripts/ui_smoke.py` — headless browser test of the assistant page (text fallback → live view + audio)
- `requirements.txt`, `README.md`, `.venv` (uv, Python 3.12), Playwright Chromium

## How it works

```
Browser page /assistant
  hold/tap button → record WAV (Web Audio) → POST /api/voice/command
        ▼
FastAPI: STT (Gnani) → hardcoded intent → policy check (pass-through)
        ▼
Playwright drives the mock portal (login → OTP → dashboard → form-1)
  after every action: screenshot to data/sessions/<id>/view.png
        ▼
Page polls session status (~1/s): transcript, steps, live frame
        ▼
On done: TTS reply (Gnani) saved as reply.wav → played on the page
```

## Verification (all on Fri 9 Oct, test port 8899)

| Test | What it proves | Result |
|---|---|---|
| CLI smoke `walking_skeleton.py` | TTS → STT → login → form fill → verify → TTS confirm | ✅ PASSED (trace `tr_02715ea0600b`; earlier run wall 5.1 s) |
| UI smoke `ui_smoke.py` | assistant page → text fallback → 12 agent steps → live frame → reply audio | ✅ PASSED |
| Fake-mic hold test | hold-to-talk → upload → STT → reply; empty transcript handled | ✅ PASSED, no JS errors |
| Quick-tap test | tap once = stays recording; tap again = send; 30 s auto-stop exists | ✅ PASSED, no JS errors |
| Secret check | password/OTP never in event log | ✅ 0 occurrences |
| Existing smoke re-run | portal login/form + full flow still green | ✅ PASSED |

## Plan M1 acceptance checklist

- [x] Push-to-talk → STT → hardcoded intent → Playwright login → form → fill two fields → TTS confirms
- [x] Live view shows the browser (screenshot polling ~1 Hz)
- [ ] **Click-through handoff** (user takes over the live view for OTP/CAPTCHA) — remaining
- [x] Policy skeleton (pass-through) in the action path
- [x] `trace_id` appears in every event (voice → intent → action → verify → TTS)
- [x] Per-stage timings logged (`data/task_events.jsonl`)

## Decisions & notes

1. **Live view = screenshot polling** (~1 Hz) for now; WebSocket streaming is a later optimization (plan §3 target).
2. **OTP is auto-entered** by the executor in this phase; the plan's OTP handoff (user speaks the digits) comes with the handoff work.
3. **Hardcoded intent** — any recognized command triggers the same flow. The agent loop (Jev-driven decisions) is M2.
4. **One task at a time**; overlapping requests get HTTP 409.
5. PTT UX: **hold to talk** or **quick-tap for hands-free** (tap again to send); 30 s auto-send cap; text fallback always available.
6. Secrets: password/OTP values are redacted in logs; missing live frames return HTTP 204 (quiet).
7. Headless Chromium for the agent; the user's Chrome page shows only the live view.

## How to run

```bash
.venv/bin/uvicorn app.main:app --port 8765
# open http://127.0.0.1:8765/  → hold or quick-tap the button, speak Telugu
# text fallback available; portal target: /portal/login
```

## Known limitations

- Agent stops after form-1 (no form 2/3, review, submit — that's M2/M5).
- Reply text is fixed; intent is fixed.
- Live view is one-way (no click-through yet).
- Human-speech STT accuracy still unverified (Phase 1 open item).

## Open items

- [ ] Click-through handoff spike (plan §5) — completes this phase
- [ ] Human 5-phrase STT recordings (inherited from Phase 1)
- [ ] Jev mandatory question to organizers (inherited)
- [ ] Test with a real microphone on the actual laptop (done by user; any issue to be debugged)

## Next phase

**Phase 3 — M2 (Fri 16 – Wed 21 Oct):** full portal (form 2/3, review, receipt, hostile toggles), agent loop driven by Jev decisions, step/time/cost budgets, no-progress detector, review page reached ≥ 8/10.
