"""OPENING uses frozen combat_loop (~580); post-handoff uses HEAD pilot.

Load order: combat_loop first, then HEAD (same pattern as H2H dual-load).
Handoff when Active Mega Starmie has water (`phase_fsm.opening_complete`),
sticky for the rest of the game.

Kill switch: OPENING_HANDOFF=0
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

_PILOT_MODNAMES = (
    "starmie_pilot",
    "turn_planner",
    "epoch_scheduler",
    "opening_bridge",
    "supporter_planner",
    "deck_resources",
    "draw_axis",
    "hand_snapshot",
    "legal_mask",
    "matchup_alakazam",
    "opening_bench",
    "opening_cards",
    "opening_planner",
    "opening_state",
    "opponent_roles",
    "phase_fsm",
    "rl_opening_proposer",
    "target_rules",
    "opening_handoff",
    "opening_exec",
)

AgentFn = Callable[[dict[str, Any]], list[int]]


def handoff_enabled() -> bool:
    return os.environ.get("OPENING_HANDOFF", "1").strip() not in ("0", "false", "False")


def submission_root_from_pilot_file(pilot_file: str | Path) -> Path:
    """pilot/starmie_pilot.py → submission root (sibling combat_loop/)."""
    pilot_dir = Path(pilot_file).resolve().parent
    root = pilot_dir.parent
    return root


def combat_loop_dir(agent_root: Path) -> Path:
    return agent_root / "combat_loop"


def _purge_pilot_modules() -> None:
    for name in list(sys.modules):
        if name in _PILOT_MODNAMES or name.startswith("starmie_pilot."):
            del sys.modules[name]


def _read_weights(agent_dir: Path) -> dict:
    path = agent_dir / "weights.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as h:
        return json.load(h)


def _load_agent(
    agent_dir: Path,
    deck: list[int],
    weights: dict[str, float] | None,
) -> tuple[AgentFn, Callable[[], None], Any, dict[str, Any]]:
    """Load make_starmie_agent from agent_dir/pilot (OPENING_HANDOFF forced off)."""
    agent_dir = agent_dir.resolve()
    pilot_dir = agent_dir / "pilot"
    if not pilot_dir.is_dir():
        raise FileNotFoundError(f"no pilot/ under {agent_dir}")

    _purge_pilot_modules()
    for p in (str(pilot_dir), str(agent_dir)):
        while p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)

    # Prevent recursion into build_handoff_agent while constructing either side.
    prev = os.environ.get("OPENING_HANDOFF")
    os.environ["OPENING_HANDOFF"] = "0"
    try:
        sp = importlib.import_module("starmie_pilot")
        w = dict(weights or {})
        if not w:
            w = _read_weights(agent_dir)
        agent_fn = sp.make_starmie_agent(deck, w)
        agent_state = getattr(sp, "_LIVE_AGENT_STATE", None)
        if agent_state is None:
            # Fallback: empty state bag for reset no-op compatibility.
            agent_state = {}
        reset_state = getattr(sp, "reset_agent_state", None)

        def reset_fn() -> None:
            if callable(reset_state):
                reset_state(agent_state)
            else:
                getattr(sp, "reset_for_new_game", lambda: None)()

        return agent_fn, reset_fn, sp, agent_state
    finally:
        if prev is None:
            os.environ.pop("OPENING_HANDOFF", None)
        else:
            os.environ["OPENING_HANDOFF"] = prev


def _opening_incomplete(obs_dict: dict[str, Any]) -> bool:
    """True until Active Mega Starmie + water (HEAD phase_fsm definition)."""
    if obs_dict.get("select") is None:
        return True
    # Imports resolve to whichever pilot is last on sys.path (HEAD after handoff build).
    from cg.api import to_observation_class
    from hand_snapshot import build_board_snapshot
    from phase_fsm import opening_complete

    obs = to_observation_class(obs_dict)
    if getattr(obs, "select", None) is None:
        return True
    board = build_board_snapshot(obs)
    return not bool(opening_complete(board))


def build_handoff_agent(
    agent_root: Path,
    deck: list[int],
    weights: dict[str, float] | None = None,
) -> AgentFn:
    """combat_loop while opening incomplete; HEAD after sticky handoff."""
    agent_root = Path(agent_root).resolve()
    cdir = combat_loop_dir(agent_root)
    if not (cdir / "pilot").is_dir():
        raise FileNotFoundError(f"missing vendored combat_loop at {cdir}")

    combat_fn, combat_reset, _combat_mod, _combat_state = _load_agent(
        cdir, deck, weights,
    )
    head_fn, head_reset, head_mod, head_state = _load_agent(
        agent_root, deck, weights,
    )

    sticky = {"handoff_done": False}

    def reset_both() -> None:
        sticky["handoff_done"] = False
        combat_reset()
        head_reset()

    # Harness / load_starmie_agent reset hooks point at HEAD module.
    head_mod.reset_for_new_game = reset_both  # type: ignore[attr-defined]
    _orig_reset_state = getattr(head_mod, "reset_agent_state", None)

    def reset_agent_state(agent_state: dict[str, Any] | None) -> None:
        sticky["handoff_done"] = False
        combat_reset()
        if callable(_orig_reset_state):
            _orig_reset_state(agent_state if agent_state is not None else head_state)
        else:
            head_reset()

    head_mod.reset_agent_state = reset_agent_state  # type: ignore[attr-defined]
    head_mod._LIVE_AGENT_STATE = head_state  # type: ignore[attr-defined]
    head_mod._HANDOFF_STICKY = sticky  # type: ignore[attr-defined]

    def agent(obs_dict: dict[str, Any]) -> list[int]:
        if obs_dict.get("select") is None:
            reset_both()
            return list(deck)
        if not sticky["handoff_done"]:
            if _opening_incomplete(obs_dict):
                return combat_fn(obs_dict)
            sticky["handoff_done"] = True
        return head_fn(obs_dict)

    return agent
