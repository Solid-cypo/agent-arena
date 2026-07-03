#!/usr/bin/env python3
"""Package submission_starmie/ into a Kaggle-submittable tar.gz.

Includes: main.py, deck.csv, weights.json, pilot/, cg/ (with engine binaries).
Excludes __pycache__ and .pyc. Verifies the entry imports before packing.
"""
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "submission_starmie"
OUT = ROOT / "submission_starmie.tar.gz"


def _import_check() -> None:
    sys.path.insert(0, str(SUB))
    sys.path.insert(0, str(ROOT))
    import main  # noqa: F401
    assert main._read_deck()[:60], "deck empty"
    print(f"import check OK: deck={len(main._read_deck())} weights={len(main._read_weights())}")


def _filter(ti):
    name = ti.name
    if "__pycache__" in name or name.endswith(".pyc"):
        return None
    return ti


def main() -> None:
    _import_check()
    required = ["main.py", "deck.csv", "weights.json", "pilot/starmie_pilot.py",
                "cg/api.py", "cg/sim.py", "cg/game.py"]
    for rel in required:
        if not (SUB / rel).exists():
            raise SystemExit(f"missing required file: {rel}")
    # engine binary present?
    has_bin = (SUB / "cg/libcg.so").exists() or (SUB / "cg/cg.dll").exists()
    if not has_bin:
        raise SystemExit("missing cg engine binary (libcg.so / cg.dll)")
    with tarfile.open(OUT, "w:gz") as tar:
        tar.add(SUB, arcname="submission_starmie", filter=_filter)
    size_kb = OUT.stat().st_size / 1024
    print(f"packed -> {OUT}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
