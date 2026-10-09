# Phase 1 — M0: Access, Spikes, Specs

**Window:** Fri 9 – Sun 11 Oct 2026 · **Status:** ✅ Complete (2 human-dependent items carried forward)
**Plan reference:** `voice_first_agent_plan_v4.md` §2 (decisions to settle in M0)

## Goal

Confirm every vendor works, answer the Jev go/no-go, and write the mock portal spec — before any real building.

---

## 1. Vendor access — verified live (Fri 9 Oct)

Full evidence: `docs/m0_vendor_status.md`.

| Vendor | Check | Result |
|---|---|---|
| Gemini (LLM) | `GET /v1beta/models` | ✅ 200 — key valid; `gemini-3.8-flash`, `3.7-flash`, `3.6-flash`, `3.5-flash`, 3.1/2.5 series available |
| Gnani TTS | Telugu sentence with a number + an English word → WAV | ✅ 200 — valid 48 kHz WAV (voice: Varuni) |
| Gnani STT | TTS audio fed back in | ✅ 200 — correct Telugu transcript, ~0.76 s |
| Jev | `POST api.typesafe.ai/v1/systemone` | ✅ 200 — **3/3 correct login decisions** |

**Resolved blocker:** `JEV_API_KEY` is a **TypeSafe** key, not an AutoJev key. AutoJev returns 401 (it's an independent product with its own keys). Endpoint: `https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer`, model `jev-latest`.

## 2. Jev go/no-go — **GO** (recorded)

**Key finding:** Jev is a **decision model**, not a browser driver. It takes a state (goal + page + bounded element list) and typed questions (`Choice` / `Noul` / `Score`) and returns typed answers with probabilities.

Login simulation result: `type → User ID`, `type → Password`, `click → Login` (3/3, confidence 0.73–0.98).

**Architecture implication (confirmed in code):** our loop observes (Playwright/a11y tree) and executes; Jev selects. No conflict with Playwright — the plan's `agent/jev` adapter is the correct design.

## 3. Gnani spike

- ✅ TTS: Telugu sentence containing a number and an English word ("Scholarship application … 9876543210 …") → valid WAV.
- ✅ STT: synthetic round-trip returns Telugu transcript in native script.
- ⏳ **Human speech still unverified** — the 5-phrase mic kit is ready but recordings are pending.

**Findings that affect later design:**
1. Digits come back as **words** (`తొమ్మిది ఎనిమిది …`), not numerals → digit-word mapping needed for phone/OTP/ID read-back (M3).
2. English loanwords arrive **transliterated into Telugu script** → glossary matching must normalize script.
3. API quirk: the request `model` field must be omitted (`gnani-prisma-v2.5` is response-side only; docs example is wrong).
4. Telugu voices available: Suhana, Lehara, Lavanya, Yukti, **Varuni** (tested).

## 4. Decisions recorded

| Decision | Value | Where |
|---|---|---|
| Demo device | Laptop Chrome + external mic | plan §2.4 |
| Documents capture (M6) | In-page webcam; never a file picker | plan §2.4 |
| Permissions | Mic (+ camera later) requested once at consent | plan §2.4 |
| Base language (assumed) | **Telugu** (`te-IN`) — to confirm with user | this doc |
| LLM | Gemini (key verified); pin model in M1 | this doc |

## 5. Mock portal spec

Written: `docs/mock_portal_spec.md` — Login → Dashboard → Form 1/2/3 → Review → Receipt, hostile-mode matrix, duplicate-submit trap, accessibility contract. Documents page marked **M6-only**.

## Artifacts produced

| Artifact | Path |
|---|---|
| Vendor evidence | `docs/m0_vendor_status.md` |
| Portal spec | `docs/mock_portal_spec.md` |
| STT spike runner | `spikes/stt_spike.py` |
| Phrase list + expected entities | `spikes/phrases.md` |
| Recording guide | `spikes/RECORDING_GUIDE.md` |
| Secret hygiene | `.gitignore` (`.env` ignored), `.env.example` |
| Synthetic profile | `profile/demo_profile.json` |

## Open items (carried forward)

- [ ] **Ask organizers: is Jev mandatory for the challenge?** (only unknown left from the go/no-go)
- [ ] Record 5 real Telugu phrases and run `spikes/stt_spike.py` (human-speech accuracy)
- [ ] Pick the Telugu voice (default: Varuni)
- [ ] Check Gemini rate limits + pricing in AI Studio console
- [ ] Confirm base language is Telugu

## Plan M0 "done when" — mapping

| Criterion | Status |
|---|---|
| Vendor keys/quota confirmed (day 0) | ✅ (quota pages: manual check pending) |
| Jev go/no-go recorded | ✅ GO (decision layer) |
| Gnani STT local-language transcripts (5 test phrases) | 🟡 synthetic ✅ / human pending |
| TTS speaks sentence with number + English word | ✅ |
| Demo hardware + capture decision recorded | ✅ (plan §2.4) |
| Mock portal spec written (documents page M6-only) | ✅ |
