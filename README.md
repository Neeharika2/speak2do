# Voice-First Multilingual Computer-Use Agent

Plan: [`voice_first_agent_plan_v4.md`](voice_first_agent_plan_v4.md)
Phase build log: [`phases/README.md`](phases/README.md)
M0 evidence: [`docs/m0_vendor_status.md`](docs/m0_vendor_status.md)
Mock portal spec: [`docs/mock_portal_spec.md`](docs/mock_portal_spec.md)

## Layout

```
app/
  main.py            FastAPI app (agent + portal in one process)
  config.py          env loading, paths, vendor endpoints
  events.py          trace_id event log -> data/task_events.jsonl
  voice/             Gnani STT/TTS adapters + streaming.py (WebSocket STT/TTS)
  policy/            deterministic policy engine (M1: pass-through)
  agent/             Jev client, loop, observe/values/llm + readback/voice_ux (M3 voice UX)
  browser/           Playwright controller (only module touching the browser)
  api/               voice app API (push-to-talk, sessions, answers, stop, live view)
  templates/         assistant.html (the voice app page)
  portal/            mock scholarship portal (full app flow + hostile toggles)
scripts/
  walking_skeleton.py   M1 smoke test: voice -> login -> form fill -> confirmation
  ui_smoke.py           M1/M3 UI smoke: text fallback -> interactive agent -> live view + audio
  hostile_check.py      M2: hostile toggles + submit dup handling (14 checks)
  agent_guards.py       M2: forced-loop / budgets / cost cap / no-progress (4 checks)
  agent_measure.py      M2 gate: 10 runs to review + median step time report
  voice_ux_check.py     M3: read-back / parsing / corrections / intent checks (30, offline)
  voice_accuracy.py     M3 gate: 30-phrase TTS->STT accuracy + read-back simulation
  voice_session_check.py M3: Q&A, corrections, intent gate, "Aagu" halt (25 checks)
  streaming_check.py    M4: Gnani WS adapters — streamed TTS chunks + streamed STT (6 checks)
  voice_ws_check.py     M4: /ws/voice end-to-end — live transcript, streamed TTS (7 checks)
spikes/
  stt_spike.py          M0 STT spike runner (5 recorded phrases)
  phrases.md            what to record + expected entities
  RECORDING_GUIDE.md    how to record and run
profile/demo_profile.json   synthetic profile used by the agent
profile/demo_profile_voice.json  voice-demo profile (district blank -> agent asks by voice)
phases/               phase-by-phase build log (phase1.md = M0, phase2.md = M1, ...)
```

## Setup

```bash
uv venv .venv                                  # or: python3 -m venv .venv
uv pip install -r requirements.txt --python .venv/bin/python
.venv/bin/playwright install chromium
cp .env.example .env                           # then fill in the three API keys
```

## Run the app

```bash
.venv/bin/uvicorn app.main:app --port 8765
```

- **Voice assistant (front door):** http://127.0.0.1:8765/ → **tap** the "Tap to talk"
  button and speak in Telugu (e.g. "Scholarship application cheyyi"), **tap again to send**.
  The Jev-driven agent logs in, fills the
  whole application, **asks you to confirm name and phone, and asks for missing values
  by voice** (reading the options aloud). Correct it any time: "నా నంబర్ మారింది" makes
  it ask for the new number and **re-read it back**; unrelated commands get a
  clarification instead of running the task. Say **"ఆగు"** to stop at any time. The
  page's **Updated fields** panel lists every correction that was applied. There is
  also a text fallback.
- **Missing-field demo:** start the server with
  `AGENT_PROFILE=profile/demo_profile_voice.json` (district is blank → the agent asks).
- **Mock portal (the agent's practice target):** http://127.0.0.1:8765/portal/login
  (demo_user / demo_pass_123, OTP 246810). You normally don't need to open this — the
  agent drives it while you watch the live view.

The browser asks for microphone permission on first use; allow it. Both pages are local
(`127.0.0.1`), which counts as a secure context, so the mic works without HTTPS.

## Smoke tests and milestone checks

With the server running:

```bash
.venv/bin/python scripts/walking_skeleton.py       # M1: voice -> login -> form fill -> reply
.venv/bin/python scripts/ui_smoke.py               # M1/M3: interactive UI -> live view + audio
.venv/bin/python scripts/hostile_check.py          # M2: hostile toggles (14 checks)
.venv/bin/python scripts/agent_guards.py           # M2: budgets/no-progress guards (4 checks)
.venv/bin/python scripts/agent_measure.py --runs 10 # M2 gate: >= 8/10 reach review
.venv/bin/python scripts/voice_ux_check.py         # M3: read-back/parsing checks (offline)
.venv/bin/python scripts/voice_intent_check.py     # M5: LLM intent fallback checks (offline)
.venv/bin/python scripts/voice_unmatched.py        # M5: list utterances no layer could place
.venv/bin/python scripts/voice_accuracy.py         # M3 gate: 30-phrase accuracy (>= 90%)
BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/voice_session_check.py  # M3: Q&A + Aagu
.venv/bin/python scripts/streaming_check.py        # M4: Gnani WS adapters (TTS/STT)
BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/voice_ws_check.py       # M4: /ws/voice E2E
BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/voice_ws_ui_check.py    # M4: voice-started run shown in the UI
```

`walking_skeleton.py` synthesizes a Telugu command, transcribes it, drives the login +
OTP + dashboard + form-1 (fills name and phone), verifies the fields, saves a screenshot,
and speaks a confirmation. All stages share one `trace_id` in `data/task_events.jsonl`.

`agent_measure.py` runs the full Jev-driven agent (login → forms 1/2/3 → review) N times
and writes a report to `data/agent_measure_<ts>.json` (pass rate, median step time).

> Non-default ports: start the server with `BASE_URL=http://127.0.0.1:<port>` so the
> agent inside the server hits the same instance.

## STT spike (M0)

See [`spikes/RECORDING_GUIDE.md`](spikes/RECORDING_GUIDE.md). Quick pipeline check
with the synthetic sample:

```bash
.venv/bin/python spikes/stt_spike.py /tmp/opencode/gnani_tts_test.wav
```

## Notes

- `.env` holds real keys and is gitignored. `.env.example` documents the variables.
- Voice intent LLM is switchable: `VOICE_LLM_PROVIDER=gemini` (default) or `evon` —
  Gnani Evon v3.3 over an OpenAI-compatible endpoint (`EVON_BASE_URL`, `EVON_API_KEY`,
  `EVON_MODEL`; thinking mode disabled, 300-token cap). Rules stay first either way.
- All portal data is synthetic; passwords/OTPs are redacted in event logs.
- Jev is a decision model (not a browser driver): the loop observes/executes,
  Jev picks actions. See `docs/m0_vendor_status.md`.
