"""Primary phase FSM: OPENING → AGGRESSION → HARVEST (+ CONTROL modifier)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hand_snapshot import BoardSnapshot
from opening_cards import MEGA_FROSLASS, MEGA_STARMIE

Phase = Literal["OPENING", "AGGRESSION", "HARVEST"]


@dataclass
class PhaseState:
    primary: Phase
    control_active: bool
    opening_complete: bool


def opening_complete(board: BoardSnapshot) -> bool:
    return board.active_is_mega_starmie and board.active_has_water


def compute_phase(board: BoardSnapshot) -> PhaseState:
    """Derive primary phase and CONTROL modifier from a board snapshot."""
    control = board.prize_self < board.prize_opp

    if board.active_is_mega_froslass:
        return PhaseState("HARVEST", control, True)

    if not opening_complete(board):
        if not board.mega_starmie_on_field and board.my_turn_number >= 3:
            if board.froslass_104_on_field or board.snorunt_line_on_bench:
                return PhaseState("HARVEST", control, False)
        return PhaseState("OPENING", control, False)

    if board.active_is_mega_starmie:
        return PhaseState("AGGRESSION", control, True)

    if not board.mega_starmie_on_field:
        return PhaseState("HARVEST", control, True)

    return PhaseState("AGGRESSION", control, True)


def phase_label(state: PhaseState) -> str:
    tag = state.primary
    if state.control_active:
        tag = f"{tag}+CONTROL"
    return tag
