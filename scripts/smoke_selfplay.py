#!/usr/bin/env python3
"""Local self-play smoke test for the Kaggle submission agent.

Drives both sides with submission_starmie/main.py::agent against the real cabt
engine (root cg/). Verifies the agent returns legal selections and finishes a
game without crashing. Not a strength test — just submission integrity.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "submission_starmie"
sys.path.insert(0, str(SUB))
sys.path.insert(0, str(ROOT))

import main as sub_main  # noqa: E402
from cg.game import battle_start, battle_select, battle_finish  # noqa: E402


def read_deck():
    ids = []
    with open(SUB / "deck.csv", encoding="utf-8") as h:
        for line in h:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(int(line))
    return ids[:60]


def main():
    deck = read_deck()
    obs, start = battle_start(deck, deck)
    if obs is None:
        print(f"battle_start failed: errorPlayer={start.errorPlayer} errorType={start.errorType}")
        sys.exit(1)
    print(f"battle started; first select player = {obs.get('selectPlayer')}")

    steps = 0
    max_steps = 600
    errors = 0
    while steps < max_steps:
        sel = obs.get("select")
        if sel is None:
            break
        opts = sel.get("option", []) or []
        if len(opts) == 0:
            # terminal / no-op select — stop the loop
            break
        try:
            choice = sub_main.agent(obs)
        except Exception as e:
            errors += 1
            print(f"  step {steps}: agent raised {e!r}; using [0]")
            choice = [0]
        if not isinstance(choice, list) or not choice:
            choice = [0]
        try:
            obs = battle_select(choice)
        except IndexError:
            errors += 1
            print(f"  step {steps}: IndexError on choice={choice}")
            try:
                n = len(opts)
                mx = int(sel.get("maxCount", 1))
                mn = int(sel.get("minCount", 0))
                pick = max(mn, min(n, max(1, mx)))
                obs = battle_select(list(range(pick)))
            except Exception as e2:
                print(f"  step {steps}: recovery failed {e2!r}; aborting")
                break
        steps += 1
        if steps % 100 == 0:
            print(f"  ... {steps} steps, errors={errors}")

    winner = obs.get("winner") if isinstance(obs, dict) else None
    print(f"done: steps={steps} errors={errors} winner={winner}")
    battle_finish()
    ok = errors == 0 and steps > 0
    print("RESULT:", "OK" if ok else "CHECK")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
