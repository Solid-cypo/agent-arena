#!/usr/bin/env python3
"""Build submission.tar.gz for Kaggle upload."""

from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_submission(
    *,
    weights: Path,
    deck: Path,
    main_py: Path,
    output: Path,
) -> Path:
    staging = PROJECT_ROOT / "submission" / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    shutil.copy2(main_py, staging / "main.py")
    shutil.copy2(deck, staging / "deck.csv")
    shutil.copy2(weights, staging / "weights.json")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        for name in ("main.py", "deck.csv", "weights.json"):
            archive.add(staging / name, arcname=name)

    shutil.rmtree(staging)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Kaggle submission.tar.gz")
    parser.add_argument(
        "--weights",
        type=Path,
        default=PROJECT_ROOT / "data/training/best_weights_tea_v2.json",
    )
    parser.add_argument("--deck", type=Path, default=PROJECT_ROOT / "deck.csv")
    parser.add_argument("--main", type=Path, default=PROJECT_ROOT / "submission/main.py")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "submission/submission.tar.gz",
    )
    args = parser.parse_args()

    output = build_submission(
        weights=args.weights,
        deck=args.deck,
        main_py=args.main,
        output=args.output,
    )
    print(f"submission -> {output}")
    with tarfile.open(output, "r:gz") as archive:
        print("contents:", archive.getnames())


if __name__ == "__main__":
    main()
