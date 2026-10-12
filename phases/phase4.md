# Phase 4 — M3: Voice UX in Telugu

**Window:** Thu 22 – Mon 26 Oct 2026 · **Implemented early: Sat 10 Oct** · **Status:** ✅ Complete — gate passed (97%)
**Plan reference:** `voice_first_agent_plan_v4.md` §5, §6, §7 (M3)

## Goal (from the plan)

Full flow to the review page works voice-to-voice. A code-switched phrase works. Digit/name read-back works. On a 30-phrase test set, entity accuracy after read-back confirmation is **≥ 90%** (provisional; measure raw STT accuracy too). "Aagu" halts actions within **1 s** of transcript. Spoken progress at each major step.

---

## What was built

| Piece | File | Notes |
|---|---|---|
| Read-back rules | `app/agent/readback.py` | digits digit-by-digit grouped; name+phone confirmation prompt; yes/no/stop/repeat parsing (Telugu + transliteration); glossary aliases (districts/states in Telugu script) |
| Voice interpreter | `app/agent/voice_ux.py` | `VoiceAgent`: spoken progress on page transitions, read-back before leaving form 1, missing-field questions with options read aloud, stop/repeat/handoff handling |
| Loop hooks | `app/agent/loop.py` | `voice_io` + `stop_check` parameters; progress on page change; voice ask when a value is missing; read-back before the form-1 save click; stop check before every executor call; profile path via `AGENT_PROFILE` |
| Interactive sessions | `app/api/voice.py` | `awaiting` state; `/api/voice/answer` (read-back / field answers), `/api/voice/interrupt` ("Aagu" while running, or answer while awaiting), `/api/voice/session/{id}/speech`; speech is synthesized in background tasks so it never delays the stop path |
| Assistant page | `app/templates/assistant.html` | routes recordings to command/answer/interrupt, shows prompts, plays speech/answers; final reply shown on completion |
| Voice demo profile | `profile/demo_profile_voice.json` | district blank → the agent asks for it by voice (demo beat) |
| Checks | `scripts/voice_ux_check.py`, `scripts/voice_session_check.py`, `scripts/voice_accuracy.py` | offline, interactive, and measurement suites |

## Verification (evidence)

| Test | Result |
|---|---|
| `scripts/voice_ux_check.py` (offline) | ✅ **14/14** — digit grouping, read-back prompt, yes/no/unclear, stop + repeat detection, glossary matching |
| `scripts/voice_session_check.py` (interactive) | ✅ **9/9** — district asked by voice → answered "గుంటూరు" → filled; name/phone read-back asked; review reached; **"Aagu" halt 0.11 s** (target < 1 s); stop reason + spoken stop reply |
| `scripts/voice_accuracy.py` (30 phrases, TTS→STT) | ✅ **raw 29/30 (97%)**, **after read-back 29/30 (97%)** → M3 gate PASS. Per type: digits 8/8, districts 6/6, answers 4/4, stop 2/2, commands 2/2, names 7/8 |
| `scripts/ui_smoke.py` (interactive, browser) | ✅ PASS — 23 agent steps, **2 prompts answered**, live view + reply audio |
| Regression: guards / agent runs | ✅ 4/4 guards; 2/2 non-interactive runs (median step 0.61 s) |
| Secret check | ✅ 0 password/OTP occurrences in the event log |

The one accuracy miss (`లక్ష్మి ప్రసన్న`) failed all three synthesis attempts — exactly the case the read-back prompt exists to catch live (agent reads the name back, user says "కాదు", agent stops safely with the handoff reply).

## Plan M3 acceptance checklist

- [x] Full flow to the review page works voice-to-voice
- [x] Code-switched phrase works ("Scholarship application చేయండి", commands 2/2)
- [x] Digit/name read-back works (with confirm / re-ask / reject paths)
- [x] 30-phrase set: raw 97% and after read-back confirmation 97% (≥ 90%)
- [x] "Aagu" halts actions within 1 s of transcript (measured 0.11 s)
- [x] Spoken progress at each major step (login, each form, review)
- [x] "Repeat" support: "మళ్ళీ" re-speaks the active prompt

## Post-review quick wins (Mon 12 Oct, external review)

Applied the worthwhile items from the code review (and corrected one claim):

1. **Task definition externalized** — `AGENT_GOAL`, `AGENT_START_PATH`, `AGENT_SUCCESS_PATH`, `AGENT_DOMAIN` live in `app/config.py`; the voice API, measure/guards scripts, and the Gemini fallback prompt read from config instead of inline strings. *(The review's claim that credentials are "hardcoded" was wrong: `PORTAL_TEST_*` are env-configurable, and their separation from the profile is intentional — plan §4.4.)*
2. **Named guard limits** — `MAX_TARGETS`, `STALL_LIMIT`, `ERROR_STREAK_LIMIT`, `REPEATED_ACTION_LIMIT`, with `stall_limit`/`error_limit` exposed as `run_agent_goal` parameters.
3. **Session is a dataclass** — the 20-key session dict is now `Session` (files, status, interactive channels), ahead of M4's bound-confirmation state.

Verified after: compile ok · voice UX 14/14 · interactive session 9/9 · UI smoke PASS · guards 4/4 · agent runs 2/2 (median step 0.56 s) · 0 secret leaks.

Deferred (noted, not rejected): extracting helpers from the 250-line `run_agent_goal` (better done after M4 rules land), JSON glossary for the readback aliases, and `demo_flow` removal (kept as the M1 regression path).

## M3.5: voice corrections + intent gate (Sat 10 Oct, after user feedback)

Reported: any phrase ran the same fixed task, and "నా నంబర్ మారింది" was ignored.

- **Intent gate:** commands are checked for application/scholarship keywords (or a correction); unrelated speech gets a clarification reply and **no agent run**.
- **Corrections by voice:** "నా నంబర్ మారింది" / "నా నంబర్ <digits>" / "నా పేరు <name>" / "జిల్లా <district>" / pin / address / college / email are parsed. **English works too:** the te-IN STT returns English digits as Telugu script ("నైన్ ఎయిట్ సెవెన్…"), which the parser now understands alongside Telugu words, Latin words, and numerals. Missing values trigger "కొత్త ఫోన్ నంబర్ చెప్పండి."; the value goes into a session overlay and the affected field is re-filled in the form.
- **Mid-task text corrections:** a pending correction (e.g. "my name has changed") consumes the very next utterance as the new value; name values are token-cleaned and title-cased ("sita devi" → "Sita Devi").
- **Flaky-vendor resilience:** Gnani STT/TTS clients retry once on transport/TLS errors (a transient bad TLS node in the vendor pool was observed and verified to be vendor-side).
- **Read-back correction dialogue:** at the name/phone read-back, "కాదు" (or a direct correction) leads to "ఏది మార్చాలి?" → new value → re-read; up to 3 cycles, then safe handoff.
- **Mid-task:** a correction said while the agent works updates the overlay and acks ("సరే, ఫోన్ నంబర్ నవీకరించాను."); the loop syncs changed fields before saving (`agent.override_applied` event).
- **Loop:** `profile_overrides` callable merges session overrides per action; corrections are session-only and never written to the profile file (profile saving by voice remains a cut-list item).

Verified: offline **27/27** (parse/glossary/intent, incl. the real STT outputs for English speech); interactive **21/21** — read-back rejection → phone correction saved and re-read; command-time "నా నంబర్ మారింది" → asked → applied → reached review; mid-task "my name has changed" → "Sita Devi" saved and read back; unrelated command → clarify with zero steps; UI smoke PASS; guards 4/4; agent runs 2/2 (median step 0.53 s); "Aagu" halt 0.23 s; 0 secret leaks.

Known limits: correction fields are phone, name, district, pin, address, college, email (email extraction is best-effort; DOB not yet); corrections after a form is saved do not retroactively change that saved form (read-back is the natural moment); the intent gate is keyword-based, not full NLU.

## Realtime WebSocket transport (Mon 12 Oct, Gnani realtime APIs)

Voice input/output now runs over WebSockets end to end:

- **Adapters** (`app/voice/streaming.py`): `SttStream` (persistent Gnani `wss://…/stt/v3/stream`; PCM16 mono sent as exactly 1024-byte frames at real-time cadence, VAD min-silence 500 ms, 650 ms silence flush after PTT release) and `synthesize_stream` (Gnani `wss://…/api/v1/tts`; raw PCM chunks delivered progressively).
- **Server** (`/ws/voice` in `app/api/voice.py`): relays browser mic PCM to Gnani, routes final transcripts through the same command/answer/interrupt logic as REST (0.6 s debounce to merge VAD segments), and streams TTS audio back as base64 chunks. REST endpoints remain the fallback; REST-started sessions attach to the latest live socket for streamed speech.
- **Browser** (`assistant.html`): streams Int16 PCM frames while the button is held (quick-tap hands-free still works), shows live transcripts, and plays streamed TTS via Web Audio scheduling. Falls back to the WAV-upload path and file playback whenever the socket is unavailable; `audio_fallback` covers a server-side TTS stream failure.

Evidence: adapter checks **6/6** (progressive TTS chunks; STT transcript with 245 ms server latency) · WebSocket end-to-end **7/7** (live command transcript → session → 430 streamed audio messages → review reached) · UI smoke over WS: 23 steps, ~430 audio chunks · offline **30/30** · interactive session **25/25** · guards 4/4 · agent runs 2/2 · 0 secret leaks.

Notes: API keys never reach the browser (the server terminates the vendor sockets); each browser page owns one Gnani STT session (~15 min vendor cap → automatic reconnect on close); TTS still falls back to REST on socket failure.

## How to run

```bash
# normal voice app (profile complete; read-back still asks to confirm)
.venv/bin/uvicorn app.main:app --port 8765

# missing-field demo (district blank -> agent asks by voice)
AGENT_PROFILE=profile/demo_profile_voice.json .venv/bin/uvicorn app.main:app --port 8765

# checks
.venv/bin/python scripts/voice_ux_check.py
.venv/bin/python scripts/voice_accuracy.py
BASE_URL=http://127.0.0.1:8765 .venv/bin/python scripts/voice_session_check.py
```

## Decisions & notes

1. Interactions use the existing polling model + an `awaiting` session state (no WebSocket yet) — consistent with push-to-talk and simple to reason about.
2. Progress/prompt TTS runs as background tasks: the loop never blocks on speech, which keeps "Aagu" latency well under 1 s.
3. Read-back simulation assumes a cooperative user (re-synthesis on mismatch); live rejection paths (`కాదు` → safe stop/handoff) are implemented but not simulated for accuracy scoring.
4. Missing values are asked by voice when `voice_io` is present; scripted runs (`agent_measure`, guards) pass no `voice_io` and keep the deterministic M2 behavior.
5. On a rejected read-back the agent stops with the handoff reply; a value-correction dialogue ("say the correct value") is a candidate polish for M4.

## Known limitations

- Correction flow after "కాదు" is stop/handoff, not re-collection of the wrong value.
- Accuracy measurement is synthetic TTS audio; **human speech still unverified** (5-phrase mic recordings from Phase 1 remain open).
- No bound confirmation / submit yet (M4/M5).

## Open items

- [ ] Human 5-phrase STT recordings (Phase 1 carry-over)
- [ ] Jev mandatory question to organizers (Phase 1 carry-over)
- [ ] Bound submit confirmation + idempotency (M4)
- [ ] Hostile-mode robustness + handoff/click-through (M4)

## Next phase

**Phase 5 — M4 (Tue 27 – Fri 30 Oct): safety, handoff, idempotency** — policy rule table, 20-case confirm/deny corpus, bound submit confirmation, zero unsafe actions under the injection suite, OTP/CAPTCHA handoff, duplicate-submit guard, resume-mid-submit.
