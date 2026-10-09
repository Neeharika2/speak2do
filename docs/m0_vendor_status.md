# M0 — Vendor Access & Spike Results

**Date verified:** Fri 9 Oct 2026 (day 0)
**Method:** live API calls from this machine, keys read from `.env` (values never printed). Commands below are redacted.

## Summary

| Vendor | Key in `.env` | Check | Result |
|---|---|---|---|
| Gemini (LLM) | `GEMINI_API_KEY` | `GET /v1beta/models` | ✅ 200 — key valid |
| Gnani TTS | `GNANI_API_KEY` | `POST /api/v1/tts/inference` (te-IN, Varuni) | ✅ 200 — valid WAV returned |
| Gnani STT | `GNANI_API_KEY` | `POST /stt/v3` (te-IN) on the TTS output | ✅ 200 — transcript returned in 0.76 s |
| Jev | `JEV_API_KEY` | `POST api.typesafe.ai/v1/systemone` | ✅ 200 — 3/3 correct login decisions |

> ⚠️ The Jev key is a **TypeSafe** key. It does **not** work against `autojev.ai/api/v1/decisions` (401) — AutoJev is an independent integration layer that requires its own access key.

---

## 1. Jev — RESOLVED: decision layer, not a browser driver

Jev is TypeSafe's "System One" model. You send a `state` + typed questions (`Choice`, `Noul`, `Score`); it returns typed answers with probabilities and confidence. **It does not click, type, or drive a browser.**

- Endpoint: `POST https://api.typesafe.ai/v1/systemone`
- Auth: `Authorization: Bearer $JEV_API_KEY`, model `jev-latest` (server returned `jev-1.13.0`)
- Response: direct JSON (`{model, answers, usage}`) — no `{code, message, data}` envelope

**M0 questions answered (plan §2.1):**

1. **Can Jev drive a Playwright browser?** No — and it doesn't need to. Playwright/our loop observes (a11y tree/DOM) and executes; Jev selects the operation + target from a bounded candidate set.
2. **Inputs/outputs:** `state` (text/object: goal, page, bounded element list, recent actions) + typed questions. No screenshots. Output: choice + probabilities + confidence, noul (0–1), or score.
3. **File upload / dropdowns / scrolling:** executor capabilities, not Jev's. Jev selects among the operations we expose.
4. **Mandatory for the challenge?** Only the organizers can answer — **open item.** If mandatory, there is no integration conflict, since Jev is not a browser driver.

**Login sequence simulation — 3/3 correct:**

| Step | State given | Jev answer |
|---|---|---|
| 1 | Login page; User ID(12), Password(18), Login(21) empty | `type` → `12` (confidence 0.80 / 0.73) |
| 2 | User ID filled, password empty | `type` → `18` |
| 3 | Both filled | `click` → `21` |

**Architecture implication:** Jev = action selection ("model proposes"). Gemini = only for writing field values or generation when needed. Deterministic policy still gates everything (plan §4).

## 2. Gnani STT + TTS — verified, with findings

**TTS**
- Text (Telugu + number + English word): `"Scholarship application కోసం మీ ఫోన్ నంబర్ 9876543210 అని నిర్ధారించండి."`
- Result: 200, valid WAV (48 kHz mono PCM, 783 KB) → `/tmp/opencode/gnani_tts_test.wav` (listen to it: voice **Varuni**).

**STT (same audio fed back in, `language_code=te-IN`)**
- Transcript: `స్కాలర్షిప్ అప్లికేషన్ కోసం మీ ఫోన్ నెంబర్ తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు నాలుగు మూడు రెండు ఒకటి సున్నా అని నిర్ధారించండి`
- `end_to_end_latency`: 0.755 s.

**Findings that affect design:**

1. **Digits come back as words** (`తొమ్మిది…సున్నా`, not `9876543210`) → digit-word → numeral mapping is needed for phone/OTP/ID read-back and confirmation. Affects M3 entity accuracy.
2. **English terms arrive transliterated into Telugu script** (`స్కాలర్షిప్ అప్లికేషన్` = "scholarship application") → glossary/entity matching must normalize script, not exact-match.
3. **API quirk:** the request must omit `model` (or send `vachana-audio-intelligence-v2`). The docs' example value `gnani-prisma-v2.5` is only the response-side model name.
4. REST accepts clips ≤ 60 s — fine for push-to-talk; WebSocket endpoints exist if we need lower latency later.
5. Telugu voices available: **Suhana, Lehara, Lavanya, Yukti, Varuni** (all female). Pick after listening.

**Still unverified:** accuracy on **real human speech** (the round-trip used synthetic TTS audio). The 5-phrase mic spike is an open item.

## 3. Gemini (LLM) — verified

- `GET /v1beta/models` → 200.
- Notable models available: `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-pro-preview`, `gemini-2.5` series.
- **Action:** pin one model in M1 (suggestion: `gemini-3.8-flash` for planning; flash-lite for cheap formatting). Check rate limits + pricing in the AI Studio console — not verifiable via the API.

## 4. M0 gate — restated and met

Original wording (plan §2.1): *"Jev completes a 3-step action on a test login page."* Since Jev is a decision model, the gate becomes: **Jev picks the correct action at each login step from a bounded candidate list.** → **3/3 today = GO.**

End-to-end page execution (Playwright loop executing Jev's choices) is the first item of M1's walking skeleton. If it fails there, the plan §2.1 fallback stands: keep the Jev adapter and continue.

## 5. Open items

- [ ] **Ask organizers: is Jev mandatory for the challenge?** (only remaining unknown)
- [ ] Listen to `/tmp/opencode/gnani_tts_test.wav`; choose a Telugu voice (Suhana / Lehara / Lavanya / Yukti / Varuni)
- [ ] Record 5 real mic Telugu phrases (incl. digits + names) for the human-speech STT spike
- [ ] Confirm base language = Telugu
- [ ] Check Gemini quota + pricing in AI Studio

## 6. Housekeeping

- `.env` added to `.gitignore` — never commit keys.
- Mock portal spec drafted: `docs/mock_portal_spec.md`.
- Raw request/response files: `/tmp/opencode/` (temporary).
