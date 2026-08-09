#!/usr/bin/env python3
"""Copy starmie pilot modules into submission_starmie/pilot/ for Kaggle bundle."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
PILOT_DST = ROOT / "submission_starmie" / "pilot"

PILOT_MODULES = (
    "starmie_pilot.py",
    "opening_bridge.py",
    "opening_planner.py",
    "opening_exec.py",
    "opening_state.py",
    "hand_snapshot.py",
    "phase_fsm.py",
    "opening_cards.py",
    "deck_resources.py",
    "draw_axis.py",
    "supporter_planner.py",
    "turn_planner.py",
    "epoch_scheduler.py",
    "opponent_roles.py",
    "matchup_alakazam.py",
    "opening_handoff.py",
)

COMBAT_SRC = ROOT / "data" / "restore_peaks" / "combat_loop_55014671"
COMBAT_DST = ROOT / "submission_starmie" / "combat_loop"


def main() -> None:
    PILOT_DST.mkdir(parents=True, exist_ok=True)
    for name in PILOT_MODULES:
        src = SKILL_SCRIPTS / name
        dst = PILOT_DST / name
        shutil.copy2(src, dst)
        print(f"  {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    print(f"Synced {len(PILOT_MODULES)} modules to {PILOT_DST.relative_to(ROOT)}/")

    # Keep vendored combat_loop (~580 Opening) in the Kaggle bundle.
    if COMBAT_SRC.is_dir():
        if COMBAT_DST.exists():
            shutil.rmtree(COMBAT_DST)
        shutil.copytree(COMBAT_SRC, COMBAT_DST)
        # Runtime uses HEAD deck/weights; only pilot behavior is frozen.
        for name in ("deck.csv", "weights.json"):
            src = ROOT / "submission_starmie" / name
            if src.exists():
                shutil.copy2(src, COMBAT_DST / name)
        print(f"Vendored combat_loop -> {COMBAT_DST.relative_to(ROOT)}/")
    else:
        print(f"WARNING: missing {COMBAT_SRC} — Opening handoff will not activate")


if __name__ == "__main__":
    main()
