#!/usr/bin/env python3
"""Build submission.tar.gz for Kaggle upload."""

from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CG_DIR = PROJECT_ROOT / "cg"


def _clean_cg_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(tarinfo.name).name
    if name.startswith("._") or name == "__pycache__" or tarinfo.name.endswith(".pyc"):
        return None
    return tarinfo


def build_submission(
    *,
    weights: Path,
    deck: Path,
    main_py: Path,
    cg_dir: Path,
    output: Path,
) -> Path:
    if not cg_dir.is_dir():
        raise FileNotFoundError(f"cg runtime not found: {cg_dir}")

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
        archive.add(cg_dir, arcname="cg", filter=_clean_cg_filter)

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
    parser.add_argument("--cg-dir", type=Path, default=CG_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "submission/submission.tar.gz",
    )
    args = parser.parse_args()

    output = build_submission(
        weights=_resolve(args.weights),
        deck=_resolve(args.deck),
        main_py=_resolve(args.main),
        cg_dir=_resolve(args.cg_dir),
        output=_resolve(args.output),
    )
    print(f"submission -> {output}")
    with tarfile.open(output, "r:gz") as archive:
        names = archive.getnames()
        top_level = sorted({name.split("/")[0] for name in names})
        print("top-level:", top_level)
        print("cg files:", sum(1 for name in names if name.startswith("cg/")))


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


if __name__ == "__main__":
    main()
