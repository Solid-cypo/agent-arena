"""Phase 0 Setup Active/Bench selection."""
from __future__ import annotations

from opening_cards import (
    BUDEW,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    MEOWTH_EX,
    MUNKIDORI,
    SNORUNT,
    STARYU,
)


def pick_setup_active(hand_basics: list[int]) -> int:
    s = set(hand_basics)
    if STARYU in s:
        return STARYU
    if FAN_ROTOM in s:
        return FAN_ROTOM
    if DUNSPARCE_B in s:
        return DUNSPARCE_B
    if DUNSPARCE_A in s:
        return DUNSPARCE_A
    if SNORUNT in s:
        return SNORUNT
    if MUNKIDORI in s:
        return MUNKIDORI
    if BUDEW in s:
        return BUDEW
    if MEOWTH_EX in s:
        return MEOWTH_EX
    return hand_basics[0]


def pick_setup_bench(hand_basics: list[int], setup_active_id: int) -> int | None:
    s = set(hand_basics)
    if setup_active_id == STARYU and FAN_ROTOM in s:
        return FAN_ROTOM
    if setup_active_id == FAN_ROTOM:
        return None
    if FAN_ROTOM in s and setup_active_id != FAN_ROTOM:
        return FAN_ROTOM
    return None


def classify_archetype(setup_active_id: int, setup_bench_id: int | None) -> str:
    if setup_active_id == STARYU and setup_bench_id == FAN_ROTOM:
        return "A2"
    if setup_active_id == STARYU:
        return "S1"
    if setup_active_id == FAN_ROTOM:
        return "A1"
    if setup_active_id in (DUNSPARCE_A, DUNSPARCE_B):
        return "B1"
    if setup_active_id == SNORUNT:
        return "C1"
    if setup_active_id == BUDEW:
        return "E1"
    if setup_active_id == MEOWTH_EX:
        return "F1"
    return "X1"


def run_setup(state) -> str:
    """Apply setup choices to state; return archetype."""
    basics = state.hand_basics()
    if not basics:
        state._log("NOTE", "EDGE: no basic in opening hand — cannot setup")
        return "NONE"
    active_id = pick_setup_active(basics)
    state.setup_play_active(active_id)
    bench_id = pick_setup_bench(state.hand_basics(), active_id)
    if bench_id is not None and state.bench_open() > 0:
        state.setup_play_bench(bench_id)
    arch = classify_archetype(active_id, bench_id)
    state.setup_archetype = arch
    state._log("NOTE", f"Archetype={arch}")
    return arch
