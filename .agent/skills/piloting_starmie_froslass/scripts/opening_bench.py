"""OPENING / live bench slot budgeting (5 bench seats).

Preset (user):
  attacker base (Staryu / Snorunt) ×1 · Dunsparce ×2 · Munkidori ×1 · flex ×1

Active is separate from these five bench seats. Mega Starmie on bench counts
as the attacker seat (not a second base).
"""
from __future__ import annotations

from opening_cards import (
    BUDEW,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    MEGA_STARMIE,
    MEGA_FROSLASS,
    MEOWTH_EX,
    MUNKIDORI,
    FROSLASS,
    SNORUNT,
    STARYU,
)

# Bench-role budgets (active ignored for these caps — see role_counts).
ATTACKER_BASE = frozenset({STARYU, SNORUNT, MEGA_STARMIE, MEGA_FROSLASS, FROSLASS})
DUNSPARCE_LINE = frozenset({DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE})
MUNK_LINE = frozenset({MUNKIDORI})
FLEX_LINE = frozenset({MEOWTH_EX, BUDEW, FAN_ROTOM})

# Legacy aliases used by older call sites.
STARYU_LINE = frozenset({STARYU, MEGA_STARMIE})
SNORUNT_LINE = frozenset({SNORUNT})
UTILITY_LINE = FLEX_LINE

BENCH_ROLE_CAPS: dict[str, int] = {
    "attacker_base": 1,
    "dunsparce": 2,
    "munk": 1,
    "flex": 1,
}


def bench_role_for(card_id: int) -> str | None:
    cid = int(card_id)
    if cid in ATTACKER_BASE:
        return "attacker_base"
    if cid in DUNSPARCE_LINE:
        return "dunsparce"
    if cid in MUNK_LINE:
        return "munk"
    if cid in FLEX_LINE:
        return "flex"
    return None


def role_counts_from_ids(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> dict[str, int]:
    """Count roles on **bench only** (active is not a bench seat)."""
    counts = {role: 0 for role in BENCH_ROLE_CAPS}
    for pid in bench_ids:
        role = bench_role_for(int(pid))
        if role:
            counts[role] += 1
    return counts


def can_bench_card(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
    bench_open: int,
    card_id: int,
) -> bool:
    """True if playing card_id to bench respects role caps."""
    if bench_open <= 0:
        return False
    role = bench_role_for(int(card_id))
    if role is None:
        # Unknown basic: spend the flex seat.
        role = "flex"
    return role_counts_from_ids(active_id, bench_ids)[role] < BENCH_ROLE_CAPS[role]


def dunsparce_quota_open(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> bool:
    """True while dunsparce-line count on bench+active is under 2.

    Active Dunsparce counts toward the engine line (max 2 total on field).
    """
    n = role_counts_from_ids(active_id, bench_ids)["dunsparce"]
    if active_id and int(active_id) in DUNSPARCE_LINE:
        n += 1
    return n < BENCH_ROLE_CAPS["dunsparce"]


def bench_role_counts(st) -> dict[str, int]:
    counts = {role: 0 for role in BENCH_ROLE_CAPS}
    for p in st.bench:
        role = bench_role_for(p.card_id)
        if role:
            counts[role] += 1
    return counts


def can_play_to_bench(st, card_id: int) -> bool:
    if st.bench_open() <= 0:
        return False
    role = bench_role_for(card_id)
    if role is None:
        role = "flex"
    return bench_role_counts(st)[role] < BENCH_ROLE_CAPS[role]
