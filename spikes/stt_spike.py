#!/usr/bin/env python3
"""M0 spike: run test audio files through Gnani STT and record the results.

Usage (from the repo root, inside the venv):
    source .venv/bin/activate
    python spikes/stt_spike.py spikes/audio/
    python spikes/stt_spike.py spikes/audio/01_name.wav --lang te-IN

Results are appended to spikes/stt_results.json (one entry per audio file).
Requires httpx (installed via requirements.txt).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
STT_URL = "https://api.vachana.ai/stt/v3"
SUPPORTED = {".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a"}


def load_env(path: Path) -> None:
    """Load simple KEY=VALUE lines from .env without overwriting the environment."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def collect_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED))
        elif p.suffix.lower() in SUPPORTED:
            files.append(p)
        else:
            print(f"skip (unsupported): {p}", file=sys.stderr)
    return files


def transcribe(client: httpx.Client, api_key: str, path: Path, lang: str) -> dict:
    with path.open("rb") as fh:
        response = client.post(
            STT_URL,
            headers={"X-API-Key-ID": api_key},
            data={"language_code": lang},
            files={"audio_file": (path.name, fh, "audio/wav")},
            timeout=60.0,
        )
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="audio files or directories")
    parser.add_argument("--lang", default="te-IN", help="language code (default: te-IN)")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "spikes" / "stt_results.json"),
        help="results file (default: spikes/stt_results.json)",
    )
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    api_key = os.environ.get("GNANI_API_KEY", "")
    if not api_key:
        print("GNANI_API_KEY not found in environment or .env", file=sys.stderr)
        return 2

    files = collect_files(args.paths)
    if not files:
        print("No audio files found. See spikes/RECORDING_GUIDE.md", file=sys.stderr)
        return 2

    results = []
    failed = 0
    with httpx.Client() as client:
        for path in files:
            started = time.perf_counter()
            try:
                data = transcribe(client, api_key, path, args.lang)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL {path.name}: {exc}")
                results.append({"file": path.name, "ok": False, "error": str(exc)})
                continue
            elapsed = time.perf_counter() - started
            transcript = data.get("transcript", "")
            print(f"\n== {path.name} ==")
            print(f"transcript: {transcript}")
            print(f"latency: {data.get('end_to_end_latency', 'n/a')} s (wall {elapsed:.2f} s)")
            results.append(
                {
                    "file": path.name,
                    "ok": True,
                    "language": args.lang,
                    "transcript": transcript,
                    "end_to_end_latency_s": data.get("end_to_end_latency"),
                    "request_id": data.get("request_id"),
                    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
            )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if out_path.exists() and out_path.stat().st_size:
        existing = json.loads(out_path.read_text(encoding="utf-8"))
    out_path.write_text(json.dumps(existing + results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResults appended to {out_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
