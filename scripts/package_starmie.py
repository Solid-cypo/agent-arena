"""Package the starmie_froslass agent into submission_starmie.tar.gz."""
from __future__ import annotations

import json
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "submission_starmie"
OUT = ROOT / "submission_starmie.tar.gz"
CG_DIR = ROOT / "cg"


def _clean_cg_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(tarinfo.name).name
    if name.startswith("._") or name == "__pycache__" or tarinfo.name.endswith(".pyc"):
        return None
    return tarinfo


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Package starmie_froslass submission.tar.gz")
    parser.add_argument(
        "--weights",
        type=Path,
        default=ROOT / "data/training/best_weights_starmie_v1.json",
    )
    args = parser.parse_args()

    deck_src = ROOT / "data/decks/starmie_froslass.csv"
    deck_dst = SRC / "deck.csv"
    shutil.copy(deck_src, deck_dst)
    print(f"Copied deck: {deck_src} -> {deck_dst}")

    weights_src = args.weights if args.weights.is_absolute() else ROOT / args.weights
    weights_dst = SRC / "weights.json"
    if weights_src.exists():
        shutil.copy(weights_src, weights_dst)
        print(f"Copied weights: {weights_src}")
    else:
        default = {
            "froslass_harvest": 1.5,
            "jetting_blow_pref": 1.2,
            "nebula_finish": 2.0,
            "boss_gust_path": 1.8,
        }
        weights_dst.write_text(json.dumps(default, indent=2))
        print("Used default weights (no trained file found)")

    staging = SRC / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    shutil.copy2(SRC / "main.py", staging / "main.py")
    shutil.copy2(deck_dst, staging / "deck.csv")
    shutil.copy2(weights_dst, staging / "weights.json")

    pilot_src = SRC / "pilot"
    pilot_staging = staging / "pilot"
    if pilot_src.is_dir():
        shutil.copytree(pilot_src, pilot_staging)
        print(f"Bundled pilot modules: {len(list(pilot_staging.glob('*.py')))} files")
    else:
        raise SystemExit(
            "Missing submission_starmie/pilot/ — run: python3 scripts/sync_starmie_submission.py"
        )

    with tarfile.open(OUT, "w:gz") as archive:
        for name in ("main.py", "deck.csv", "weights.json"):
            archive.add(staging / name, arcname=name)
        archive.add(pilot_staging, arcname="pilot", filter=_clean_cg_filter)
        archive.add(CG_DIR, arcname="cg", filter=_clean_cg_filter)

    shutil.rmtree(staging)

    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"Created {OUT} ({size_mb:.1f} MB)")
    with tarfile.open(OUT, "r:gz") as archive:
        top_level = sorted({name.split("/")[0] for name in archive.getnames()})
        print("top-level:", top_level)


if __name__ == "__main__":
    main()
