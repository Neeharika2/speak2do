# Voice-First Multilingual Computer-Use Agent
## Plan v4: solo, MVP, deadline Tuesday 10 Nov 2026

> **Product line:** "Speak. We'll do it."
> **Promise:** If you can tell us what you want done, you don't need to know how to use the computer.
> **Hero demo (core):** A local language-speaking user completes a scholarship application on a mock portal by voice — login, form fill, read-back, bound confirmation, submit, receipt. **Document capture/upload is an optional add-on if the stretch milestone lands.**

**Constraints:** 1 person, 32 days from today (Fri 9 Oct), MVP quality. Runs locally on a laptop. Not production-grade.

**Assumptions to adjust:** about 5 focused hours/day, 6 days/week, one lighter day per week as buffer. If your real capacity is lower, cut from the cut list (section 9) earlier, not later.

---

## 0. What changed in v4 (and why)

1. **Priority is explicit: application filling first (P0), documents second (P1).** P0 is the voice-to-voice application end to end — login/OTP → profile fill → missing-field questions → read-back → bound confirmation → submit → receipt. Documents are scheduled only after P0 passes its gate, and are cut first if it doesn't.
2. **The hero demo is complete without documents.** M5 is now a full end-to-end application run (≥ 8/10, 0 unsafe failures). Documents (M6) are an extended demo beat, not a dependency.
3. **Capture mechanism decided, for when documents are built:** in-page **laptop webcam** capture. Single device, offline, works on `http://localhost` (secure context for `getUserMedia`), no pairing. Phone-as-camera moves to post-MVP.
4. **Never a file picker.** The user's whole job is to show a document to a camera; the executor uploads via `set_input_files`. If the capture UI is cut, the capture step is cut with it — no OS file dialog fallback.
5. **Permissions bundled at onboarding:** mic + camera requested once, at consent. Never mid-task.
6. **Mock portal v1 has no documents page.** It is added in M6 only if documents are built; until then the Review page submits directly.

---

## 1. Scope

### P0 — must work (application filling)
- One language done well: **local language + English code-switching**
- Browser tasks only, via Playwright, with Jev as the computer-use engine (subject to the M0 go/no-go)
- One **mock scholarship portal** that you build (hero flow + hostile mode)
- Push-to-talk voice in, spoken progress and results out
- **Voice-to-voice application**: login (executor/OTP handoff) → profile fill → missing-field questions → read-back → review → bound confirmation → submit → receipt verification
- Simple profile (JSON) and task state (JSON), with sensitivity flags
- Deterministic policy engine; human handoff for login/OTP/CAPTCHA
- Error recovery for the core flow; idempotent submit

### P1 — next, only after P0 is proven (documents)
- Webcam capture → quality check → crop → image/PDF merge → upload → verify on the portal
- Synthetic documents only; upload allowlist; spoken re-capture guidance

### Non-goals (written down so they stay out)
- No real government portals, no real submissions, no payments
- No real Aadhaar/PAN/bank documents anywhere, ever. **Synthetic documents only.**
- No desktop/OS control, no arbitrary websites, no multi-tab or file-manager automation
- No user accounts or auth beyond the mock portal's login
- No Docker/Redis/Nginx/Kubernetes, no cloud deployment, no dashboards
- No second language unless everything else is done (Hindi is the first cut)
- No vector memory, reusable workflows, proactive features, or fine-tuning
- No on-device browser mode
- No phone-as-camera in the MVP (post-demo)

### MVP simplifications
SQLite (or plain JSON files), one FastAPI process with async tasks, local run, one user, a laptop as demo device (see 2.4).

---

## 2. Decisions to settle in M0 (by Sun 11 Oct)

### 2.1 Jev integration mode: GO / NO-GO
Questions, in order of importance:
1. **Can Jev drive a Playwright-controlled browser**, or does it need its own browser/extension/session? If it needs its own, redesign around that browser (the executor then wraps Jev's environment instead of Playwright).
2. Inputs: screenshot, DOM/accessibility tree, or both? Output: action schema (coordinates, element refs, text)?
3. File upload, dropdowns, scrolling support? Latency per step, cost, rate limits, max steps?
4. Is Jev **mandatory** for the challenge? If yes and it can't integrate, ask the organizers on Sat 10 Oct, not later.

**Decision rule:** if Jev can complete a 3-step action on the mock login page by end of Sun 11 Oct, GO. Otherwise, build the harness on a DOM/LLM agent, keep the Jev adapter interface, and keep trying Jev in the background until the M2 gate.

### 2.2 Vendor access (day 0, today)
Confirm API keys, quotas, and rate limits for **Jev, Gnani STT, Gnani TTS, and your LLM**. Vendor access delays are the most common silent blocker. If anything is missing, escalate today.

### 2.3 Gnani spike
- STT: streaming vs batch, local language + code-switching, latency, accuracy on **digits and names**, audio format
- TTS: local language voice quality; how it handles English words, numbers, dates, currency (see section 6)
- Keep both behind thin adapters (`stt.transcribe()`, `tts.speak()`) so a swap is cheap if accuracy disappoints

### 2.4 Demo hardware and document capture (decided in v4)
- **Demo device: laptop browser (Chrome) + a good external mic.** The phone is not part of the hero demo.
- **Documents (when built): in-page webcam capture.** The PWA opens a camera widget (`getUserMedia`); the agent guides by voice — "Aadhaar card camera mundu pettandi", "konchem daggaraki", "glare undi, konchem tirugandi". Live preview + target frame on screen; auto-capture when the frame is steady, with a big manual "Capture" button as fallback. Works on `http://localhost` (secure context), offline, single device.
- **Permission bundling:** request mic + camera once at onboarding/consent. Never mid-task (permission popups are an elderly UX landmine).
- **Phone-as-camera is post-MVP.** If revisited: a phone page with `<input type=file capture>` (native camera app; no `getUserMedia`, no HTTPS requirement) reached via QR + LAN URL. Note: `getUserMedia` over `http://192.168.x.x` is blocked (not a secure context), so full in-page phone capture would need HTTPS/tunnel — avoid for the demo.
- **Never a file picker:** if the capture UI is cut, cut the whole capture step. Do not fall back to an OS file dialog — that is the exact failure mode the product exists to remove.

### 2.5 Mock portal spec (write in M0, build M1-M2; documents page M6 only)

| Page | Contents |
|---|---|
| Login | user ID, password, then OTP page (fixed test OTP) |
| Dashboard | "Scholarship Application" link, "Application status" link |
| Form 1 | name, DOB, gender, phone, email |
| Form 2 | college, course, year, marks |
| Form 3 | address; state → **district dropdown** (dependent) |
| Review | all fields shown, edit links, **Submit** button |
| Receipt | application ID; second visit shows "already submitted" |
| Documents (M6 only, if built) | Aadhaar (front+back as **one PDF ≤ 200 KB**), passport photo (JPG ≤ 50 KB) |

**Hostile mode toggles (used in M4/M5/M7 tests):** slow page loads; popup/overlay; injected text in the DOM ("ignore previous instructions..."); injected text inside an image; fake CAPTCHA step; session expiry mid-form; layout change (renamed/moved buttons); **duplicate-submit trap** (double-click or retry creates two applications unless the agent guards against it).

---

## 3. Architecture (single process)

```text
Browser PWA / page (laptop)
  push-to-talk, transcript pane, live view, confirm UI, camera (M6)
        │  WebSocket
        ▼
FastAPI app
  voice/      STT + TTS adapters
  task/       intent, plan, task state (JSON), trace_id
  policy/     rule table → Allow | Confirm | Deny | Handoff   (deterministic)
  agent/      loop: observe → decide → validate → execute → verify
    jev/      adapter (client, state_adapter, action_parser)
  browser/    Playwright controller + live view stream
  documents/  (M6) webcam capture, quality check, crop, image→PDF
  profile/    JSON profile with sensitivity flag
  events/     task_events table (with trace_id), redacted
        │
        ▼
SQLite            Playwright browser → mock portal
```

**Rule:** the model *proposes*, policy *disposes*, executor *acts*.

**Observation rule (cost/latency):** use the **accessibility tree/DOM first**; send a screenshot only when the tree is insufficient or the last action didn't change state as expected. Instrument per-stage timings from M1.

---

## 4. Safety design (skeleton in M1, full rules in M4)

### 4.1 Policy engine
Starts in M1 as a pass-through returning `Allow`, so every action already flows through it. Rules are added in M4.

| Rule | Decision |
|---|---|
| Navigate/read/scroll/search inside allowlisted domain | Allow |
| Fill ordinary field from profile or spoken value | Allow (read back digits/names first, see section 6) |
| Navigate outside allowlisted domains | Deny |
| Field is password / OTP (detected by executor) | **Handoff** (value never enters model context) |
| CAPTCHA detected | Handoff |
| Upload of a sensitive document | Confirm (announce doc type, ask yes/no) |
| File not in this task's prepared-files allowlist | Deny |
| Click matching Submit/Pay/Confirm/Delete patterns, or URL/state indicates final step | **Confirm (bound)** |
| Model-proposed action not in the action schema | Deny |
| Model risk hint | Can only escalate, never relax |

### 4.2 Bound confirmation
The agent reads a specific summary ("Scholarship application submit cheyyala? Name ___, college ___, 3 documents attached.") and the user's "yes" counts only if it answers **that prompt**, within a short timeout, from the current session. Pre-supplied or ambiguous yes → re-ask. Confirm via a tap as well as voice when available.

### 4.3 Idempotency (irreversible actions)
- Every irreversible action gets an **action ID** and is recorded as `pending → in_flight → done` before and after execution.
- Retries and re-plans check the record first; they never re-click Submit blindly.
- **Resume mid-submit:** if state is `in_flight`, do not retry. Navigate to the receipt/status page, verify whether the submission exists, then proceed or hand off.
- Test with the mock portal's duplicate-submit trap.

### 4.4 Secrets
Password, OTP, and any sensitive identifier are injected by the executor or entered by the user during handoff. The model sees `[REDACTED]`. Redact in logs and screenshots sent to models where feasible.

### 4.5 Prompt injection
Trusted: user instruction, system/policy. Untrusted: DOM text, screenshot content, search results, documents. Policy ignores instructions found in page content. Test with injected text in DOM, hidden elements, and images.

### 4.6 Live-view security (MVP-level)
Live view requires a session token, the browser runs in an isolated profile per task, and the profile/storage is wiped after each task.

---

## 5. Human handoff UX (spike in M1, finish in M4)

**Mechanism for MVP: live view with click-through.** The PWA shows the agent's browser as a stream of screenshots. During a handoff the user (or a helper beside them) can click on the stream to click, and type/speak into a focused field. The agent is paused and says why.

| Situation | Behavior |
|---|---|
| OTP | Agent says "OTP cheppandi." User speaks or types digits; executor enters them; digits are never sent to the model or logs |
| Login | Executor injects test credentials (mock portal). Real-portal login is out of scope |
| CAPTCHA | Agent says "CAPTCHA vachindi, please complete it." User clicks through the live view and says/taps "Done" |
| Ambiguous choice | Agent reads the options in local language, user answers by voice |
| Unexpected page / low confidence | "I reached a step where I need your help." Shows what it sees; user guides or cancels |

After handoff, the agent re-observes and continues from saved task state.

---

## 6. Voice and language rules

**Voice**
- Push-to-talk first; no VAD in the MVP.
- Always show the transcript on screen; always provide text/tap fallback.
- "Yes/No" are valid only as answers to an active prompt.
- Barge-in: "Aagu / Stop" sets a hard-stop flag checked before every executor call.
- Spoken progress at each major step; keep sentences short; support "Repeat".

**Read-back rules**

| Item | Rule |
|---|---|
| Digits (phone, ID, OTP not shown) | Read digit by digit, grouped; confirm before use |
| Names, districts | Read back; confirm if STT confidence is low or value is new |
| Dates | Say day, month name, year ("12 March 2005"); never numeric-only |
| Money | Say amount with unit; Indian numbering (lakh/crore) when the page uses it; state currency |
| English loanwords/terms | Keep English form for portal terms ("scholarship", "submit"); build a small glossary of form/scheme terms from the mock portal |
| Page text translated for the user | Say "summary" when summarizing; **never silently translate legal, consent, or declaration text**: read it faithfully or tell the user it's English-only and ask whether to proceed |

---

## 7. Milestones, dates, acceptance criteria

All owners: you. Acceptance criteria are **provisional**: re-baseline them after M0 and after the first M2 measurements. Keep each milestone's end-of-day state *working* (never leave the walking skeleton broken overnight); tag the repo at each milestone.

**Ordering rule:** P1 (documents) does not start until the P0 gate passes at the end of M5.

| # | Dates | Milestone | Done when |
|---|---|---|---|
| M0 | Fri 9 - Sun 11 Oct | Access, spikes, specs | Vendor keys/quota confirmed (day 0). **Jev go/no-go recorded.** Gnani STT returns local language transcripts for 5 test phrases; TTS speaks a local language sentence containing a number and an English word. Demo hardware and capture decision recorded (2.4). Mock portal spec written (application pages; documents page marked M6-only). |
| M1 | Mon 12 - Thu 15 Oct | Walking skeleton (application path) | Push-to-talk → STT → hardcoded intent → Playwright performs login on the mock portal → navigates to the application form → fills two fields → TTS confirms. Live view shows the browser and click-through works. Policy skeleton (pass-through) in the path. `trace_id` appears in every event (STT → plan → action → TTS). Per-stage timings logged. |
| M2 | Fri 16 - Wed 21 Oct | Agent loop + Jev + full application portal | Mock portal application pages complete incl. hostile toggles. Agent (text goal) reaches the **review page** in **≥ 8 of 10 runs** (provisional), median step time documented (target < 5 s). Budgets enforced: forced-loop test halts (max ~50 actions, ~5 min, 2 retries, cost cap). No-progress detector works. **Gate:** if < 50% success on Wed 21 Oct, cut scope (see section 9). |
| M3 | Thu 22 - Mon 26 Oct | Voice UX in local language | Full flow to the review page works voice-to-voice. A code-switched phrase works. Digit/name read-back works. On a 30-phrase test set, entity accuracy after read-back confirmation is **≥ 90%** (provisional; measure raw STT accuracy too). "Aagu" halts actions within **1 s** of transcript. Spoken progress at each major step. |
| M4 | Tue 27 - Fri 30 Oct | Safety, handoff, idempotency | Rule table implemented. **20-case should-confirm/should-deny corpus passes.** Submit is blocked without a bound confirmation (tests: pre-supplied yes, expired yes, ambiguous yes all rejected). Grep test: no OTP/password in any logged model prompt. Handoff works for OTP and CAPTCHA. Injection suite (≥ 6 cases: DOM, hidden, image) produces **zero unsafe actions**. Double-click and resume-after-submit create **one** application. **Gate Fri 30 Oct.** |
| M5 | Sat 31 Oct - Tue 3 Nov | **P0 complete: full application, no documents** | Full voice-to-voice application (login/OTP handoff → profile fill → missing-field question → read-back → bound confirm → submit → receipt) succeeds in **≥ 8 of 10 runs with 0 unsafe failures**. Error recovery verified: timeout, element missing, session expiry. Duplicate-submit trap handled. **Hero demo can now ship without documents.** **Gate:** if < 8/10 or any unsafe failure, documents are cancelled and M6 becomes hardening/rehearsal only. |
| M6 | Wed 4 - Fri 6 Nov | **P1 (conditional): documents + replay + freeze** | Only if the M5 gate passed. Documents: synthetic Aadhaar front+back captured via **webcam** → quality check → merged PDF ≤ 200 KB → uploaded and verified; a deliberately blurry photo triggers spoken re-capture guidance; upload allowlist test passes. Must be working by **end of Thu 5 Nov** or it is dropped for the demo. Replay mode (recorded model outputs) works as the demo fallback. **Feature freeze end of Fri 6 Nov.** If documents are dropped, use M6 for extra rehearsals and pitch prep. |
| M7 | Sat 7 - Mon 9 Nov | Demo and pitch | Demo script rehearsed **3 times** under realistic conditions (mic noise, venue-like network). Backup video recorded. Pitch ready. Submission package prepared. |
| Buffer | Tue 10 Nov | Deadline day | Submit. No new work. |

**Weekly rhythm:** Sunday review against the table; if a milestone slips by more than one day, cut from section 9 immediately instead of compressing later milestones.

---

## 8. Demo script (hero flow)

**Core (must work):**
1. User presses push-to-talk and says in local language, "Scholarship application complete cheyyi."
2. Agent understands and speaks a short plan.
3. Browser opens the mock portal (live view visible).
4. Login: executor injects credentials; OTP step triggers handoff, user speaks OTP digits.
5. Agent navigates to the scholarship application.
6. Agent fills known fields from the profile.
7. Agent reads back key values (phone number, DOB) for confirmation.
8. Agent asks for one missing field by voice (e.g., district) and reads the options in local language.
9. Agent reviews the form against the profile and reports it.
10. Agent asks the bound confirmation: "Submit cheyyala?" (summary read aloud).
11. User says "Avunu"; agent submits.
12. Agent verifies the receipt page and reads the application ID.
13. Agent summarizes the result in local language.
14. (Optional extras, only if built: show the injected-text test page being ignored; "Aagu" interrupting.)

**Optional documents segment (only if M6 landed) — insert between steps 8 and 9:**
- Portal asks for Aadhaar; agent asks the user to show the (synthetic) card to the laptop camera.
- Quality check fails on a deliberately bad first attempt; agent explains the fix in local language.
- Second attempt passes; agent builds the PDF, uploads it, and verifies the file shows on the page.

---

## 9. Cut list (cut in this order when behind)

1. **Documents (capture/upload entirely)** — demo the core flow without them
2. Second language (Hindi)
3. Real read-only site demo (use only the mock portal)
4. Camera guidance UI (voice-only guidance + manual capture button; **never a file picker**)
5. Profile saving by voice (keep a prefilled profile)
6. Live-view click-through (fall back to a helper doing the handoff in a second window)
7. Translation of page content beyond labels/options/errors
8. Jev as the driver, if the M2 gate fails and Jev can't recover (keep it as an adapter, demo with the DOM/LLM agent, and say so honestly), **only if Jev isn't mandatory**

**Never cut:** the P0 application flow (agent loop, profile fill, read-back, submit), policy engine, bound confirmation, secret handling, idempotency, demo rehearsals, backup video.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Vendor keys/quota delayed | Confirm today; escalate immediately; test with minimal quotas |
| Jev can't drive your browser | M0 go/no-go; adapter boundary; DOM/LLM fallback |
| Solo capacity / illness | Weekly review, cut list, buffer days, no new work after Fri 6 Nov |
| **Documents steal time from the core flow** | **P0 gate at M5; documents are conditional (M6), cut first, and the mock portal has no documents page until M6** |
| local language STT misses digits/names | Read-back, confidence gating, text fallback, adapter for swapping vendors |
| Latency feels broken | Narration, push-to-talk, tree-first observation, step budgets, timings from M1 |
| Mock portal takes longer than planned | Specified in M0; build minimum pages first, hostile toggles last |
| Unsafe autonomous action | Deterministic rules, bound confirmation, upload allowlist, zero-unsafe target |
| Demo-day failure | Replay mode, backup video, 3 rehearsals, laptop-based demo, text fallback |

---

## 11. Metrics (keep small)

Per task: success label (success / partial / safe failure / unsafe failure), actions used, wall-clock time, human interventions, wrong actions, confirmations, cost.
Per stage latency: STT, planning, each agent step, TTS.
Per document (only if M6 lands): capture attempts to a valid image.
Stored in `task_events` with `trace_id`; inspect with SQL or a notebook.

---

## 12. App accessibility requirements (the app should model the standard)

Large tap targets, high contrast, scalable fonts, visible transcript pane, minimal on-screen choices, semantic HTML with labels, every voice action has a tap/text equivalent.

---

## 13. Privacy minimums (MVP)

- Synthetic documents only (hard rule)
- Consent screen in the user's language before voice/camera use
- Delete captured documents and audio after the task by default
- No raw passwords, OTPs, or ID numbers in logs or prompts
- List which third parties see audio/screenshots (STT, TTS, LLM, Jev) and note their retention terms in the pitch
- Before any real-user pilot, get proper guidance on India's DPDP Act 2023 and Aadhaar-specific rules (this plan is not legal advice)

---

## 14. Final target

> "Scholarship application complete cheyyi."

becomes: voice → STT → intent/plan → policy check → Jev drives the portal → form fill from profile → missing-info questions → read-back and bound confirmation → submit (idempotent) → receipt verification → local language TTS summary, with safe handoff wherever the agent should not decide alone.

**When the documents milestone lands, insert before review:** webcam capture → quality check → PDF → upload verification → spoken confirmation of the uploaded file.
