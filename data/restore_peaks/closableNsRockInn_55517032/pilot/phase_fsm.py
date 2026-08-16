"""Primary phase FSM: OPENING → AGGRESSION → HARVEST (+ CONTROL modifier)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hand_snapshot import BoardSnapshot

Phase = Literal["OPENING", "AGGRESSION", "HARVEST"]


@dataclass
class PhaseState:
    primary: Phase
    control_active: bool
    opening_complete: bool


def opening_complete(board: BoardSnapshot) -> bool:
    return board.active_is_mega_starmie and board.active_has_water


def compute_phase(
    board: BoardSnapshot,
    *,
    opening_ever_complete: bool = False,
) -> PhaseState:
    """Derive primary phase and CONTROL modifier from a board snapshot.

    ``opening_ever_complete`` must be True once this game has achieved a usable
    Active Mega Starmie. Without it, Mega Starmie KO makes ``opening_complete``
    false and the FSM used to regress to OPENING — blocking Mega Froslass (861).
    """
    control = board.prize_self < board.prize_opp
    opened_now = opening_complete(board)
    ever = bool(opening_ever_complete) or opened_now

    if board.active_is_mega_froslass:
        return PhaseState("HARVEST", control, True)

    # Usable Mega Starmie Active → AGGRESSION (main attacker window).
    if opened_now:
        return PhaseState("AGGRESSION", control, True)

    # Opening was achieved earlier but Mega Starmie left the field → HARVEST.
    # (Second attacker / Mega Froslass path. Do not regress to OPENING.)
    if ever and not board.mega_starmie_on_field:
        return PhaseState("HARVEST", control, True)

    # Still have Mega Starmie on bench after Active left — stay AGGRESSION-ish
    # via OPENING only if we never opened; if we opened, promote/rebuild.
    if ever and board.mega_starmie_on_field:
        # Active is not usable Starmie; treat as post-opening midgame.
        # Prefer HARVEST when Froslass line is the recovery plan.
        if board.froslass_104_on_field or board.snorunt_line_on_bench:
            return PhaseState("HARVEST", control, True)
        return PhaseState("AGGRESSION", control, True)

    # T3+ fallback: never opened, but Froslass line exists → HARVEST early.
    if not board.mega_starmie_on_field and board.my_turn_number >= 3:
        if board.froslass_104_on_field or board.snorunt_line_on_bench:
            return PhaseState("HARVEST", control, False)

    return PhaseState("OPENING", control, False)


def phase_label(state: PhaseState) -> str:
    tag = state.primary
    if state.control_active:
        tag = f"{tag}+CONTROL"
    return tag
