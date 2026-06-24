"""Guards the shared score ladder (review fix #5): the _DOMINATE_* constants and
the planner priorities live on one priority scale; an accidental inversion of the
DOMINATE band order would silently flip hard-rule priority, so assert it here."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for p in (str(ROOT), str(SKILL)):
    if p not in sys.path:
        sys.path.insert(0, p)

import starmie_pilot as sp


def test_dominate_band_order():
    ladder = [
        sp._DOMINATE_LOW,      # 880
        sp._DOMINATE_MID,      # 920
        sp._DOMINATE_SUPPORT,  # 960
        sp._DOMINATE_ATTACK,   # 975
        sp._DOMINATE,          # 1000
        sp._DOMINATE_PLUS,     # 1100
        sp._DOMINATE_RESCUE,   # 1120
        sp._DOMINATE_OPEN,     # 1130
        sp._DOMINATE_OPEN_PATH,  # 1150
    ]
    assert ladder == sorted(ladder), f"DOMINATE band order inverted: {ladder}"
    assert len(set(ladder)) == len(ladder), "DOMINATE constants collide (equal values)"


def test_opening_path_is_top():
    # The opening-planner route must outrank every other hard rule (Step A).
    assert sp._DOMINATE_OPEN_PATH == max(
        sp._DOMINATE_LOW, sp._DOMINATE_MID, sp._DOMINATE_SUPPORT, sp._DOMINATE_ATTACK,
        sp._DOMINATE, sp._DOMINATE_PLUS, sp._DOMINATE_RESCUE, sp._DOMINATE_OPEN,
        sp._DOMINATE_OPEN_PATH,
    )
