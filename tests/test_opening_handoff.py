"""Opening handoff: combat_loop until Mega+water, then HEAD."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "submission_starmie" / "pilot"))
sys.path.insert(0, str(ROOT / "submission_starmie"))

from cg.api import AreaType, OptionType  # noqa: E402

COMBAT = ROOT / "submission_starmie" / "combat_loop"
HEAD = ROOT / "submission_starmie"


def _read_deck(agent_dir: Path) -> list[int]:
    ids = []
    with open(agent_dir / "deck.csv", encoding="utf-8") as h:
        for line in h:
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(int(line))
    return ids[:60]


@pytest.fixture(scope="module")
def handoff_agent():
    if not (COMBAT / "pilot").is_dir():
        pytest.skip("combat_loop not vendored")
    os.environ["OPENING_HANDOFF"] = "1"
    os.environ["RL_ENABLED"] = "0"
    # Import after env so make sees handoff on.
    import importlib
    import opening_handoff as oh

    importlib.reload(oh)
    from h2h_starmie_vs_baseline import load_starmie_agent

    fn, reset, sp, deck, state = load_starmie_agent(HEAD)
    assert getattr(sp, "_HANDOFF_STICKY", None) is not None or oh.handoff_enabled()
    return fn, reset, sp, deck, state


def test_combat_loop_vendored():
    assert (COMBAT / "pilot" / "starmie_pilot.py").is_file()
    assert (HEAD / "pilot" / "opening_handoff.py").is_file() or (
        ROOT / ".agent/skills/piloting_starmie_froslass/scripts/opening_handoff.py"
    ).is_file()


def test_handoff_sticky_and_reset(handoff_agent):
    fn, reset, sp, deck, state = handoff_agent
    sticky = getattr(sp, "_HANDOFF_STICKY", None)
    assert sticky is not None
    sticky["handoff_done"] = True
    reset()
    assert sticky["handoff_done"] is False
    # Deck setup call clears sticky via agent path.
    sticky["handoff_done"] = True
    out = fn({"select": None})
    assert out == deck
    assert sticky["handoff_done"] is False


def test_opening_incomplete_helper():
    os.environ["OPENING_HANDOFF"] = "0"
    from h2h_starmie_vs_baseline import load_starmie_agent
    from opening_handoff import _opening_incomplete

    _fn, _reset, sp, _deck, _ = load_starmie_agent(HEAD)
    # Minimal: no select → incomplete
    assert _opening_incomplete({"select": None}) is True
