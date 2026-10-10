#!/usr/bin/env python3
"""M3 measurement: 30-phrase synthetic TTS -> STT accuracy + read-back simulation.

- raw accuracy: STT + normalization vs the expected entity;
- after-confirmation accuracy: simulated cooperative user — on a mismatch the
  phrase is re-synthesized (speed 0.95 / 1.05) and treated as the user repeating
  it after the read-back prompt (up to 2 extra attempts). If any attempt matches,
  the read-back caught the raw error.

Gate (plan M3): after-confirmation entity accuracy >= 90% (provisional).

Run:
    .venv/bin/python scripts/voice_accuracy.py [--testset spikes/voice_testset.json]
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx

from app import config
from app.agent import readback

AUDIO_DIR = config.DATA_DIR / "voice_accuracy"
ATTEMPT_SPEEDS = [1.0, 0.95, 1.05]


def extract_digits(text: str) -> str:
    found: list[tuple[int, str]] = []
    for index, word in enumerate(readback.DIGIT_WORDS):
        start = 0
        while True:
            position = text.find(word, start)
            if position == -1:
                break
            found.append((position, str(index)))
            start = position + len(word)
    found.sort()
    return "".join(digit for _, digit in found)


def matches(entry: dict, transcript: str) -> bool:
    kind = entry["match"]
    expected = entry["expected"]
    if kind == "digits":
        return extract_digits(transcript) == expected
    if kind == "alias":
        return readback.match_option(transcript, [expected]) == expected
    if kind == "yes":
        return readback.parse_yes_no(transcript) is True
    if kind == "no":
        return readback.parse_yes_no(transcript) is False
    if kind == "stop":
        return readback.is_stop(transcript)
    if kind == "contains":
        lowered = transcript.lower()
        return any(item.lower() in lowered for item in expected)
    if kind == "fuzzy":
        compact_expected = expected.replace(" ", "")
        compact_transcript = transcript.replace(" ", "")
        return (
            expected in transcript
            or compact_expected in compact_transcript
            or difflib.SequenceMatcher(None, expected, transcript).ratio() >= 0.75
        )
    return False


async def synthesize(client: httpx.AsyncClient, text: str, speed: float, tag: str) -> Path:
    payload = {
        "text": text,
        "voice": config.DEFAULT_VOICE,
        "model": "timbre-v2.5",
        "language": config.DEFAULT_LANGUAGE,
        "speed": speed,
        "audio_config": {
            "sample_rate": 48000,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        },
    }
    response = await client.post(
        config.GNANI_TTS_URL,
        headers={"X-API-Key-ID": config.GNANI_API_KEY},
        json=payload,
        timeout=60.0,
    )
    response.raise_for_status()
    path = AUDIO_DIR / f"{tag}_{speed}.wav"
    path.write_bytes(response.content)
    return path


async def transcribe(client: httpx.AsyncClient, path: Path) -> str:
    with path.open("rb") as fh:
        response = await client.post(
            config.GNANI_STT_URL,
            headers={"X-API-Key-ID": config.GNANI_API_KEY},
            data={"language_code": config.DEFAULT_LANGUAGE},
            files={"audio_file": (path.name, fh, "audio/wav")},
            timeout=60.0,
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success", False):
        raise RuntimeError(f"STT error: {payload}")
    return payload.get("transcript", "")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testset", default=str(REPO_ROOT / "spikes" / "voice_testset.json"))
    args = parser.parse_args()

    testset = json.loads(Path(args.testset).read_text(encoding="utf-8"))
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    raw_correct = 0
    confirmed_correct = 0
    async with httpx.AsyncClient() as client:
        for entry in testset:
            attempts: list[dict] = []
            confirmed = False
            raw_ok = False
            for attempt_index, speed in enumerate(ATTEMPT_SPEEDS):
                audio = await synthesize(client, entry["text"], speed, f"{entry['id']:02d}")
                transcript = await transcribe(client, audio)
                ok = matches(entry, transcript)
                attempts.append({"speed": speed, "transcript": transcript, "match": ok})
                if attempt_index == 0:
                    raw_ok = ok
                if ok:
                    confirmed = True
                    break
            raw_correct += int(raw_ok)
            confirmed_correct += int(confirmed)
            results.append({**entry, "raw": raw_ok, "confirmed": confirmed, "attempts": attempts})
            mark = "OK " if confirmed else "MISS"
            print(f"{mark} #{entry['id']:>2} {entry['type']:<8} expected={entry['expected']!r} raw={raw_ok}")

    total = len(testset)
    raw_accuracy = raw_correct / total if total else 0.0
    confirmed_accuracy = confirmed_correct / total if total else 0.0
    by_type: dict[str, dict[str, int]] = {}
    for entry in results:
        bucket = by_type.setdefault(entry["type"], {"total": 0, "raw": 0, "confirmed": 0})
        bucket["total"] += 1
        bucket["raw"] += int(entry["raw"])
        bucket["confirmed"] += int(entry["confirmed"])

    report = {
        "total": total,
        "raw_correct": raw_correct,
        "raw_accuracy": round(raw_accuracy, 3),
        "confirmed_correct": confirmed_correct,
        "confirmed_accuracy": round(confirmed_accuracy, 3),
        "by_type": by_type,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": results,
    }
    out_path = config.DATA_DIR / f"voice_accuracy_{int(time.time())}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nraw accuracy:                 {raw_correct}/{total} ({raw_accuracy * 100:.0f}%)")
    print(f"after read-back confirmation: {confirmed_correct}/{total} ({confirmed_accuracy * 100:.0f}%)")
    for name, bucket in sorted(by_type.items()):
        print(f"  {name:<8} raw {bucket['raw']}/{bucket['total']}  confirmed {bucket['confirmed']}/{bucket['total']}")
    print(f"report: {out_path}")
    gate = confirmed_accuracy >= 0.9
    print(f"M3 gate (>= 90% after confirmation): {'PASS' if gate else 'FAIL'}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
