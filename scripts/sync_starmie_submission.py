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
    "opening_state.py",
    "hand_snapshot.py",
    "phase_fsm.py",
    "opening_cards.py",
    "deck_resources.py",
    "draw_axis.py",
    "supporter_planner.py",
    "turn_planner.py",
    "matchup_alakazam.py",
)


def main() -> None:
    PILOT_DST.mkdir(parents=True, exist_ok=True)
    for name in PILOT_MODULES:
        src = SKILL_SCRIPTS / name
        dst = PILOT_DST / name
        shutil.copy2(src, dst)
        print(f"  {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    print(f"Synced {len(PILOT_MODULES)} modules to {PILOT_DST.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
