"""Unit tests for dig-aware midgame stall path classification."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scan_midgame_dp_stall import (  # noqa: E402
    CRISPIN,
    DARK,
    HILDA,
    NIGHT_STRETCHER,
    RISKY_RUINS,
    WATER,
    _crispin_can_dig_dark,
    choice_kind,
    classify_paths,
    stall_bucket,
)

PLAY, ATTACH, END = 7, 8, 14


def _me(hand, discard=None):
    return {"hand": [{"id": c} for c in hand], "discard": [{"id": c} for c in (discard or [])]}


def test_crispin_dig_dark_requires_basic_in_discard():
    assert not _crispin_can_dig_dark([CRISPIN], [])  # empty discard — fake offer
    assert _crispin_can_dig_dark([CRISPIN], [DARK])
    assert _crispin_can_dig_dark([CRISPIN, DARK], [WATER])  # same-turn oil
    assert not _crispin_can_dig_dark([CRISPIN, DARK], [DARK])  # only same-type in disc


def test_crispin_opens_dark_path_and_ignored_end():
    hand = [CRISPIN, 1152]
    opts = [
        {"type": PLAY, "index": 0},
        {"type": END},
    ]
    goals = {"DARK": True, "PLACER": False}
    paths = classify_paths(opts, hand, goals, _me(hand, discard=[DARK, WATER]))
    assert "DARK" in paths and "DIG_DARK" in paths
    assert choice_kind([1], opts, paths, hand) == "END"
    assert stall_bucket(goals, paths, "END") == "PATH_IGNORED"


def test_crispin_empty_discard_not_dark_path():
    hand = [CRISPIN]
    opts = [{"type": PLAY, "index": 0}, {"type": END}]
    goals = {"DARK": True}
    paths = classify_paths(opts, hand, goals, _me(hand, discard=[1260, 861]))
    assert "DARK" not in paths
    assert stall_bucket(goals, paths, "END") == "NO_PATH"


def test_night_stretcher_dig_dark():
    hand = [NIGHT_STRETCHER]
    opts = [{"type": PLAY, "index": 0}, {"type": END}]
    goals = {"DARK": True}
    paths = classify_paths(opts, hand, goals, _me(hand, discard=[DARK]))
    assert "DIG_DARK" in paths
    assert choice_kind([0], opts, paths, hand) == "ADVANCE"
    assert stall_bucket(goals, paths, "ADVANCE") == "PROGRESS"


def test_hilda_dig_placer_when_ruins_not_in_hand():
    hand = [HILDA]
    opts = [{"type": PLAY, "index": 0}, {"type": END}]
    goals = {"PLACER": True, "DARK": False}
    paths = classify_paths(opts, hand, goals, _me(hand))
    assert "PLACER" in paths and "DIG_PLACER" in paths
    assert stall_bucket(goals, paths, "END") == "PATH_IGNORED"


def test_hilda_not_placer_path_if_ruins_already_in_hand():
    hand = [HILDA, RISKY_RUINS]
    opts = [
        {"type": PLAY, "index": 0},
        {"type": PLAY, "index": 1},
        {"type": END},
    ]
    goals = {"PLACER": True}
    paths = classify_paths(opts, hand, goals, _me(hand))
    assert "PLACER" in paths
    assert "DIG_PLACER" not in paths
    # Playing ruins advances; playing Hilda does not
    assert choice_kind([1], opts, paths, hand) == "ADVANCE"
    assert choice_kind([0], opts, paths, hand) == "OTHER"
