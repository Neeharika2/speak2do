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
  voice/             Gnani STT (transcribe) + TTS (speak) adapters
  policy/            deterministic policy engine (M1: pass-through)
  agent/             Jev (TypeSafe System One) client + demo_flow (login/form fill)
  browser/           Playwright controller (only module touching the browser)
  api/               voice app API (push-to-talk, session state, live view)
  templates/         assistant.html (the voice app page)
  portal/            mock scholarship portal (M1 slice: login/OTP/dashboard/form-1)
scripts/
  walking_skeleton.py   M1 smoke test: voice -> login -> form fill -> confirmation
  ui_smoke.py           UI smoke: text fallback -> agent flow -> live view + audio
spikes/
  stt_spike.py          M0 STT spike runner (5 recorded phrases)
  phrases.md            what to record + expected entities
  RECORDING_GUIDE.md    how to record and run
profile/demo_profile.json   synthetic profile used by the agent
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

- **Voice assistant (front door):** http://127.0.0.1:8765/ → **hold** the "Hold to talk"
  button and speak in Telugu (e.g. "Scholarship application login cheyyi"), or **quick-tap**
  it for hands-free mode (tap again to send). There is also a text fallback. You'll see the
  transcript, the live browser view, the agent's steps, and hear a spoken reply.
- **Mock portal (the agent's practice target):** http://127.0.0.1:8765/portal/login
  (demo_user / demo_pass_123, OTP 246810). You normally don't need to open this — the
  agent drives it while you watch the live view.

The browser asks for microphone permission on first use; allow it. Both pages are local
(`127.0.0.1`), which counts as a secure context, so the mic works without HTTPS.

## Smoke tests

With the server running:

```bash
.venv/bin/python scripts/walking_skeleton.py   # CLI: voice -> login -> form fill -> reply
.venv/bin/python scripts/ui_smoke.py           # UI: text fallback -> live view + audio
```

`walking_skeleton.py` synthesizes a Telugu command, transcribes it, drives the login +
OTP + dashboard + form-1 (fills name and phone), verifies the fields, saves a screenshot,
and speaks a confirmation. All stages share one `trace_id` in `data/task_events.jsonl`.

## STT spike (M0)

See [`spikes/RECORDING_GUIDE.md`](spikes/RECORDING_GUIDE.md). Quick pipeline check
with the synthetic sample:

```bash
.venv/bin/python spikes/stt_spike.py /tmp/opencode/gnani_tts_test.wav
```

## Notes

- `.env` holds real keys and is gitignored. `.env.example` documents the variables.
- All portal data is synthetic; passwords/OTPs are redacted in event logs.
- Jev is a decision model (not a browser driver): the loop observes/executes,
  Jev picks actions. See `docs/m0_vendor_status.md`.
