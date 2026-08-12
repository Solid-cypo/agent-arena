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
    "opening_bench.py",
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

    # Do NOT vendor combat_loop into submission_starmie/: OPENING_HANDOFF
    # defaults on and hijacks local h2h (~10pp WR) whenever the dir exists.
    # package_starmie.py never ships combat_loop; online = HEAD opening.
    # Frozen copies: data/restore_peaks/combat_loop_55014671,
    # .agent/Versions/combat_loop_vendored/ for explicit handoff experiments.
    if COMBAT_DST.exists():
        shutil.rmtree(COMBAT_DST)
        print(f"Removed landmine {COMBAT_DST.relative_to(ROOT)}/ (not shipped)")


if __name__ == "__main__":
    main()
