"""Package the starmie_froslass agent into submission_starmie.tar.gz."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "submission_starmie"
OUT  = ROOT / "submission_starmie.tar.gz"

def main():
    # Copy deck
    deck_src = ROOT / "data/decks/starmie_froslass.csv"
    deck_dst = SRC / "deck.csv"
    shutil.copy(deck_src, deck_dst)
    print(f"Copied deck: {deck_src} -> {deck_dst}")

    # Copy latest trained weights (or default)
    weights_src = ROOT / "data/training/best_weights_starmie_v1.json"
    weights_dst = SRC / "weights.json"
    if weights_src.exists():
        shutil.copy(weights_src, weights_dst)
        print(f"Copied weights: {weights_src}")
    else:
        import json
        default = {"froslass_harvest": 1.5, "jetting_blow_pref": 1.2,
                   "nebula_finish": 2.0, "boss_gust_path": 1.8}
        weights_dst.write_text(json.dumps(default, indent=2))
        print("Used default weights (no trained file found)")

    # Copy cg/ runtime
    cg_src = ROOT / "cg"
    cg_dst = SRC / "cg"
    if cg_dst.exists():
        shutil.rmtree(cg_dst)
    shutil.copytree(cg_src, cg_dst)
    print(f"Copied cg/ runtime")

    # Build tar
    result = subprocess.run(
        ["tar", "-czf", str(OUT), "-C", str(SRC.parent), SRC.name],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("tar error:", result.stderr, file=sys.stderr)
        sys.exit(1)

    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"Created {OUT} ({size_mb:.1f} MB)")

if __name__ == "__main__":
    main()
