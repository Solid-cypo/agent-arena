"""Field seat budgeting (Active + 5 bench = 6 seats).

Preset (user):
  Staryu×2 · Snorunt×1 · Munkidori×1 · Dunsparce×1 · flex×1

Pre-Mega narrow (Field6Narrow): Staryu / Snorunt dual-line seating is gated
so Opening does not pack both lines onto the board before Mega lands:
  - If any Staryu-line is on the field → cannot bench Snorunt-line
  - If Snorunt-line is already on the **bench** → cannot bench Staryu-line
    (Active-only Snorunt still allows benching Staryu — common start)
After Mega Starmie is on the field, full preset caps apply (dual-line OK).

Flex is **not** a Fan/Budew/Meowth-only bucket. It is the one unreserved
seat: tools may sit there; after a seat opens (KO, or engine piece leaves
post 土龙→66 draw), that open seat is available for the next pokemon you
need to play. Core idea: when a new bench play is required, keep a seat.

Mega Starmie counts as Staryu; 104 / Mega Froslass as Snorunt; 66 as Dunsparce.
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

STARYU_LINE = frozenset({STARYU, MEGA_STARMIE})
SNORUNT_LINE = frozenset({SNORUNT, FROSLASS, MEGA_FROSLASS})
DUNSPARCE_LINE = frozenset({DUNSPARCE_A, DUNSPARCE_B, DUDUNSPARCE})
MUNK_LINE = frozenset({MUNKIDORI})
# Tools that may occupy the single flex seat (not an exclusive caste).
FLEX_TOOLS = frozenset({MEOWTH_EX, BUDEW, FAN_ROTOM})

# Legacy aliases.
FLEX_LINE = FLEX_TOOLS
ATTACKER_BASE = STARYU_LINE | SNORUNT_LINE
UTILITY_LINE = FLEX_TOOLS
STARYU_LINE_PUBLIC = STARYU_LINE  # noqa: alias clarity for importers

CORE_ROLE_CAPS: dict[str, int] = {
    "staryu": 2,
    "snorunt": 1,
    "dunsparce": 1,
    "munk": 1,
}

# Back-compat: callers/tests still import BENCH_ROLE_CAPS.
# "flex": 1 = at most one non-core / overflow occupant on the field.
BENCH_ROLE_CAPS: dict[str, int] = {**CORE_ROLE_CAPS, "flex": 1}
FIELD_ROLE_CAPS = BENCH_ROLE_CAPS


def bench_role_for(card_id: int) -> str | None:
    """Core/tool role key, or None if unmapped (treated as flex tool)."""
    cid = int(card_id)
    if cid in STARYU_LINE:
        return "staryu"
    if cid in SNORUNT_LINE:
        return "snorunt"
    if cid in DUNSPARCE_LINE:
        return "dunsparce"
    if cid in MUNK_LINE:
        return "munk"
    if cid in FLEX_TOOLS:
        return "flex"
    return None


def _field_ids(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> list[int]:
    out: list[int] = []
    if active_id is not None and int(active_id) > 0:
        out.append(int(active_id))
    out.extend(int(pid) for pid in bench_ids)
    return out


def role_counts_from_ids(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> dict[str, int]:
    """Count core roles + flex-tool tags on Active + bench.

    Over-cap cores are still counted in their role (for missing math use
    ``missing_core_seats`` / ``flex_occupants`` instead of raw counts alone).
    """
    counts = {role: 0 for role in BENCH_ROLE_CAPS}
    for pid in _field_ids(active_id, bench_ids):
        role = bench_role_for(pid)
        if role is None:
            counts["flex"] += 1
        else:
            counts[role] += 1
    return counts


def mega_starmie_on_field(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> bool:
    return any(int(pid) == MEGA_STARMIE for pid in _field_ids(active_id, bench_ids))


def pre_mega_dual_line_blocks(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
    card_id: int,
) -> bool:
    """True if pre-Mega Staryu/Snorunt seating mutex rejects this bench play."""
    if mega_starmie_on_field(active_id, bench_ids):
        return False
    role = bench_role_for(int(card_id))
    if role not in ("staryu", "snorunt"):
        return False
    field = _field_ids(active_id, bench_ids)
    has_staryu = any(pid in STARYU_LINE for pid in field)
    bench_snorunt = any(int(pid) in SNORUNT_LINE for pid in bench_ids)
    if role == "snorunt" and has_staryu:
        return True
    if role == "staryu" and bench_snorunt:
        return True
    return False


def missing_core_seats(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> int:
    """How many core seats are still unfilled (greedy per-role shortfall).

    Pre-Mega: do not reserve a Snorunt seat when Staryu-line is already on
    the field (mutex blocks that play). Still reserve Staryu when only
    Active Snorunt is up (bench Staryu remains legal).
    """
    caps_left = dict(CORE_ROLE_CAPS)
    for pid in _field_ids(active_id, bench_ids):
        role = bench_role_for(pid)
        if role in caps_left and caps_left[role] > 0:
            caps_left[role] -= 1
    if not mega_starmie_on_field(active_id, bench_ids):
        field = _field_ids(active_id, bench_ids)
        if any(pid in STARYU_LINE for pid in field):
            caps_left["snorunt"] = 0
        if any(int(pid) in SNORUNT_LINE for pid in bench_ids):
            # Bench already committed to frost line — Staryu benches blocked.
            caps_left["staryu"] = 0
    return sum(caps_left.values())


def flex_occupants(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> int:
    """Pokemon not filling a core quota (tools, unknowns, over-cap cores)."""
    caps_left = dict(CORE_ROLE_CAPS)
    flex = 0
    for pid in _field_ids(active_id, bench_ids):
        role = bench_role_for(pid)
        if role in caps_left and caps_left[role] > 0:
            caps_left[role] -= 1
        else:
            flex += 1
    return flex


def can_bench_card(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
    bench_open: int,
    card_id: int,
) -> bool:
    """True if playing card_id to bench respects core caps + flex reserve.

    - Core under quota: always OK when a bench seat is open (subject to
      pre-Mega Staryu/Snorunt dual-line mutex).
    - Tool / unknown / over-cap: uses the single flex seat; only if flex is
      free **and** remaining open seats after the play still cover missing
      cores (so we can still seat 猿/海星/雪童/土龙 when needed).
    """
    if bench_open <= 0:
        return False

    if pre_mega_dual_line_blocks(active_id, bench_ids, int(card_id)):
        return False

    role = bench_role_for(int(card_id))
    caps_left = dict(CORE_ROLE_CAPS)
    for pid in _field_ids(active_id, bench_ids):
        r = bench_role_for(pid)
        if r in caps_left and caps_left[r] > 0:
            caps_left[r] -= 1
    # Align flex-reserve math with mutex (same as missing_core_seats).
    if not mega_starmie_on_field(active_id, bench_ids):
        field = _field_ids(active_id, bench_ids)
        if any(pid in STARYU_LINE for pid in field):
            caps_left["snorunt"] = 0
        if any(int(pid) in SNORUNT_LINE for pid in bench_ids):
            caps_left["staryu"] = 0

    fills_core = role in caps_left and caps_left[role] > 0
    if fills_core:
        return True
    # Core over quota (2nd 土龙 / 3rd 海星 / …) must not eat the flex seat.
    if role in CORE_ROLE_CAPS:
        return False

    # Tool / unknown → single flex seat; keep opens for missing cores.
    if flex_occupants(active_id, bench_ids) >= 1:
        return False
    missing = sum(caps_left.values())
    return bench_open > missing


def dunsparce_quota_open(
    active_id: int | None,
    bench_ids: list[int] | tuple[int, ...],
) -> bool:
    """True while dunsparce-line core quota is open (≤1 on field)."""
    caps_left = dict(CORE_ROLE_CAPS)
    for pid in _field_ids(active_id, bench_ids):
        r = bench_role_for(pid)
        if r in caps_left and caps_left[r] > 0:
            caps_left[r] -= 1
    return caps_left["dunsparce"] > 0


def bench_role_counts(st) -> dict[str, int]:
    """Role counts for a simulator-style state with .active / .bench."""
    active_id = None
    if getattr(st, "active", None):
        ap = st.active[0] if isinstance(st.active, (list, tuple)) else st.active
        if ap is not None:
            active_id = int(getattr(ap, "card_id", getattr(ap, "id", 0)) or 0) or None
    bench_ids = [
        int(getattr(p, "card_id", getattr(p, "id", 0)) or 0)
        for p in (getattr(st, "bench", None) or [])
        if p is not None
    ]
    return role_counts_from_ids(active_id, bench_ids)


def can_play_to_bench(st, card_id: int) -> bool:
    if st.bench_open() <= 0:
        return False
    active_id = None
    if getattr(st, "active", None):
        ap = st.active[0] if isinstance(st.active, (list, tuple)) else st.active
        if ap is not None:
            active_id = int(getattr(ap, "card_id", getattr(ap, "id", 0)) or 0) or None
    bench_ids = [
        int(getattr(p, "card_id", getattr(p, "id", 0)) or 0)
        for p in (getattr(st, "bench", None) or [])
        if p is not None
    ]
    return can_bench_card(active_id, bench_ids, st.bench_open(), int(card_id))
