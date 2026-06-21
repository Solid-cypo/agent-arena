#!/usr/bin/env python3
"""Auto-submit after training completes.

Usage:
    python3 scripts/auto_submit.py \
        --log data/training/train_hops_v1.log \
        --weights data/training/best_weights_hops_v1.json \
        --deck data/decks/hops_control.csv \
        --message "Hops Control v1 auto-submit"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "pokemon-tcg-ai-battle"
POLL_INTERVAL = 30   # seconds between log checks
MAX_WAIT_H = 6       # give up after 6 hours


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def wait_for_completion(log_path: Path) -> bool:
    _log(f"Watching {log_path} ...")
    deadline = time.time() + MAX_WAIT_H * 3600
    while time.time() < deadline:
        if log_path.exists():
            text = log_path.read_text(encoding="utf-8")
            if "search complete" in text:
                _log("Training complete detected.")
                return True
        time.sleep(POLL_INTERVAL)
    _log("Timed out waiting for training.")
    return False


def package(weights: Path, deck: Path) -> Path:
    pkg_script = PROJECT_ROOT / "scripts" / "package_submission.py"
    out = PROJECT_ROOT / "submission" / "submission.tar.gz"
    _log(f"Packaging: weights={weights.name} deck={deck.name}")
    subprocess.run(
        [sys.executable, str(pkg_script),
         "--weights", str(weights),
         "--deck", str(deck),
         "--output", str(out)],
        check=True,
    )
    _log(f"Package ready: {out} ({out.stat().st_size // 1024} KB)")
    return out


def submit(tar: Path, message: str) -> None:
    _log(f"Submitting to Kaggle: {COMPETITION}")
    result = subprocess.run(
        ["kaggle", "competitions", "submit",
         COMPETITION,
         "-f", str(tar),
         "-m", message],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        _log("Submission accepted.")
        _log(result.stdout.strip())
    else:
        _log(f"Submission failed (code {result.returncode}):")
        _log(result.stderr.strip() or result.stdout.strip())

    # Show latest submission status
    status = subprocess.run(
        ["kaggle", "competitions", "submissions", COMPETITION],
        capture_output=True, text=True,
    )
    _log("Latest submissions:\n" + status.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log",     type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--deck",    type=Path, required=True)
    parser.add_argument("--message", type=str, default="auto-submit after training")
    args = parser.parse_args()

    weights = args.weights if args.weights.is_absolute() else PROJECT_ROOT / args.weights
    deck    = args.deck    if args.deck.is_absolute()    else PROJECT_ROOT / args.deck
    log     = args.log     if args.log.is_absolute()     else PROJECT_ROOT / args.log

    _log("Auto-submit watchdog started.")
    if not wait_for_completion(log):
        sys.exit(1)

    tar = package(weights, deck)
    submit(tar, args.message)
    _log("Done.")


if __name__ == "__main__":
    main()
