# STT spike — 5 test phrases (Telugu)

Record each phrase **once, naturally** (not too slow), in a quiet room.
Save as WAV (16-bit PCM, mono, 16 kHz is plenty) in `spikes/audio/`.

| # | File name | Phrase to say (Telugu) | What it tests | Expected entities in transcript |
|---|---|---|---|---|
| 1 | `spikes/audio/01_name.wav` | నా పేరు రవి కుమార్. | personal name | రవి కుమార్ (Ravi Kumar) |
| 2 | `spikes/audio/02_phone_digits.wav` | నా ఫోన్ నంబర్ తొమ్మిది ఎనిమిది ఏడు ఆరు ఐదు నాలుగు మూడు రెండు ఒకటి సున్నా. | digits (say each digit) | 9876543210 (as Telugu digit words) |
| 3 | `spikes/audio/03_place.wav` | మా ఊరు గుంటూరు. | place name | గుంటూరు (Guntur) |
| 4 | `spikes/audio/04_english_mix.wav` | Scholarship application submit చేయండి. | English code-switching | scholarship / application / submit |
| 5 | `spikes/audio/05_course_year.wav` | నేను ఇంటర్మీడియట్ రెండవ సంవత్సరం చదువుతున్నాను. | course + year | ఇంటర్మీడియట్, రెండవ సంవత్సరం |

## Why these phrases

- The plan requires local language **including digits and names**.
- Expect two known behaviors from the first synthetic tests (see `docs/m0_vendor_status.md`):
  - digits come back as **words**, not numerals;
  - English loanwords arrive **transliterated into Telugu script**.
- Score each transcript yourself: are the digits right? Is the name right? Is the English term recognizable after script normalization?

## Scoring notes

- **Digit accuracy:** compare the digit words in order with the spoken number.
- **Name accuracy:** one spelling variant is acceptable; wrong name is a fail.
- **Code-switch:** the English term may appear in Telugu script — count it correct if it is recognizable.
- Record actual results in `spikes/stt_results.json` (the script appends) and summarize in `docs/m0_vendor_status.md` when done.
