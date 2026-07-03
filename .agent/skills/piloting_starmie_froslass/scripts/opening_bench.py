"""OPENING bench slot budgeting (5 slots).

Targets: Staryu line <=2 . Dunsparce 1-2 . Snorunt 0-1 . utility 1-2.
Reconstructed from bytecode salvage (original .py was lost in a working-tree wipe).
"""
from __future__ import annotations

from opening_cards import (
    BUDEW,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    MEGA_STARMIE,
    MEOWTH_EX,
    SNORUNT,
    STARYU,
)

STARYU_LINE = frozenset({STARYU, MEGA_STARMIE})
DUNSPARCE_LINE = frozenset({DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE})
SNORUNT_LINE = frozenset({SNORUNT})
UTILITY_LINE = frozenset({MEOWTH_EX, BUDEW, FAN_ROTOM})

BENCH_ROLE_CAPS: dict[str, int] = {
    "staryu": 2,
    "dunsparce": 2,
    "snorunt": 1,
    "utility": 2,
}


def bench_role_for(card_id: int) -> str | None:
    if card_id in STARYU_LINE:
        return "staryu"
    if card_id in DUNSPARCE_LINE:
        return "dunsparce"
    if card_id in SNORUNT_LINE:
        return "snorunt"
    if card_id in UTILITY_LINE:
        return "utility"
    return None


def bench_role_counts(st) -> dict[str, int]:
    counts = {role: 0 for role in BENCH_ROLE_CAPS}
    for p in st.bench:
        role = bench_role_for(p.card_id)
        if role:
            counts[role] += 1
    if st.active:
        role = bench_role_for(st.active.card_id)
        if role:
            counts[role] += 1
    return counts


def can_play_to_bench(st, card_id: int) -> bool:
    if st.bench_open() <= 0:
        return False
    role = bench_role_for(card_id)
    if role is None:
        return True
    return bench_role_counts(st)[role] < BENCH_ROLE_CAPS[role]
