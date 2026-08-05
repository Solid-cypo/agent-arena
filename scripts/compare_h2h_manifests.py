#!/usr/bin/env python3
"""Compare two H2H audit manifests: game-level agreement + WR delta.

Wave I0 smoke: same seed/n should NOT be treated as bit-identical (libcg
random_device). This reports agreement rate for regression awareness.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "games" not in data:
        raise SystemExit(f"no games[] in {path}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("a", type=Path, help="manifest.json or audit dir")
    ap.add_argument("b", type=Path, help="manifest.json or audit dir")
    args = ap.parse_args()

    pa = args.a if args.a.name == "manifest.json" else args.a / "manifest.json"
    pb = args.b if args.b.name == "manifest.json" else args.b / "manifest.json"
    ma, mb = _load(pa), _load(pb)
    ga, gb = ma["games"], mb["games"]
    n = min(len(ga), len(gb))
    if n == 0:
        print("empty manifests")
        return 1

    same_win = 0
    for i in range(n):
        if bool(ga[i].get("cur_win")) == bool(gb[i].get("cur_win")):
            same_win += 1

    wa = ma.get("wins_current", sum(1 for g in ga if g.get("cur_win")))
    wb = mb.get("wins_current", sum(1 for g in gb if g.get("cur_win")))
    print(f"A: {pa}")
    print(f"B: {pb}")
    print(f"n_compared: {n} (len A={len(ga)} B={len(gb)})")
    print(f"seed0 A={ma.get('seed0')} B={mb.get('seed0')}")
    print(f"wins_current: A={wa} B={wb} delta={wb - wa}")
    print(f"game_level_cur_win_agreement: {same_win}/{n} ({same_win / n:.1%})")
    print(
        "NOTE: engine shuffle uses random_device — expect ~45–55% agreement "
        "even with identical code + seed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
