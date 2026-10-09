# Recording guide — 5 STT phrases (M0 spike)

Goal: capture 5 short Telugu phrases with the laptop mic and run them through Gnani STT.
Phrase list and expected entities: `spikes/phrases.md`.

## 1. Record (Linux, `arecord` is installed here)

```bash
cd /home/neeharika/Documents/computer-use-agent
mkdir -p spikes/audio

# Recording starts immediately after you press Enter — leave a short pause, then speak.
arecord -f S16_LE -r 16000 -c 1 -d 8 spikes/audio/01_name.wav
arecord -f S16_LE -r 16000 -c 1 -d 8 spikes/audio/02_phone_digits.wav
arecord -f S16_LE -r 16000 -c 1 -d 8 spikes/audio/03_place.wav
arecord -f S16_LE -r 16000 -c 1 -d 8 spikes/audio/04_english_mix.wav
arecord -f S16_LE -r 16000 -c 1 -d 8 spikes/audio/05_course_year.wav
```

Use the phrases from `spikes/phrases.md`, one per file, in order.

- If the recording is silent or noisy: check the mic with `arecord -f S16_LE -r 16000 -c 1 -d 3 /tmp/mictest.wav && aplay /tmp/mictest.wav` (or your system sound settings).
- External mic is preferred; keep the fan/AC noise low.

## 2. Check playback

```bash
aplay spikes/audio/01_name.wav
```

(Files also open in any audio player.)

## 3. Run the spike

```bash
source .venv/bin/activate
python spikes/stt_spike.py spikes/audio/
```

Results are appended to `spikes/stt_results.json` with transcripts and latency.

## 4. Score the transcripts

Against the "Expected entities" column in `spikes/phrases.md`, note per phrase:

- digits in the right order?
- names recognizable?
- English terms recognizable after script normalization?

Then update the summary in `docs/m0_vendor_status.md` (section 2 has the placeholders).

## Alternative: no mic right now

- **Phone recorder:** record the 5 phrases on a phone, transfer the files, then convert:
  `ffmpeg -i input.m4a -ar 16000 -ac 1 output.wav` (install ffmpeg if needed, or export WAV from Audacity).
- **Pipeline smoke:** run the spike on the existing synthetic sample:
  `python spikes/stt_spike.py /tmp/opencode/gnani_tts_test.wav`
