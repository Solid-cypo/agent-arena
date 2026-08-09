#!/usr/bin/env python3
"""Derive path-clock metrics from GameResult.engine_logs.

Logs must be collected during the live game (collect_engine_logs=True).
Do not treat same-seed re-runs as A/B — the engine has no seed API.
"""
from __future__ import annotations

from typing import Any

# Card / attack IDs — aligned with export_combat_review_pack / opening_cards.
STARYU = 1030
MEGA_STARMIE = 1031
MEGA_FROSLASS = 861
FROSLASS_104 = 104
MUNKIDORI = 112
BUDEW = 235
SNORUNT = 860
BOSS_ORDERS = 1182
HILDA = 1225
LILLIE = 1227
POFFIN = 1086
ULTRA_BALL = 1121
POKE_PAD = 1152
SALVATOR = 1189
CRISPIN = 1198
SWITCH = 1123
WATER_BASIC = 3
DARK_BASIC = 7
PRISM = 16
ST_ATKS = frozenset({1487, 1488})  # Jetting / Nebula
MF_ATKS = frozenset({1240, 1241})
ITCHY_POLLEN = 323
WATER_IDS = frozenset({WATER_BASIC, PRISM})
DARK_IDS = frozenset({DARK_BASIC, PRISM, 17})  # + Ignition legacy

SETUP_ITEMS = frozenset({POFFIN, POKE_PAD, ULTRA_BALL, SWITCH})
SETUP_SUPPORTERS = frozenset({HILDA, LILLIE, CRISPIN, SALVATOR})
SIDE_BASICS = frozenset({SNORUNT, MUNKIDORI, BUDEW})

# LogType ints (cg.api.LogType)
LT_TURN_START = 2
LT_TURN_END = 3
LT_PLAY = 10
LT_ATTACH = 11
LT_EVOLVE = 12
LT_MOVE_ATTACHED = 14
LT_ATTACK = 15


def _si(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _path_bucket(mega_evo_my_t: int | None) -> str:
    if mega_evo_my_t is None:
        return "no_mega"
    if mega_evo_my_t <= 3:
        return "fast_mega_t≤3"
    if mega_evo_my_t <= 6:
        return "mega_t4-6"
    return "mega_late_>6"


def _active_id(snap: dict[str, Any]) -> int:
    active = snap.get("active") or []
    if not active:
        return 0
    row = active[0] or {}
    return _si(row.get("id") if isinstance(row, dict) else getattr(row, "id", 0))


def _active_has_water(snap: dict[str, Any]) -> bool:
    active = snap.get("active") or []
    if not active:
        return False
    row = active[0] or {}
    ens = row.get("energies") if isinstance(row, dict) else getattr(row, "energies", None)
    return any(_si(e) in WATER_IDS for e in (ens or []))


def _bench_ids(snap: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for row in snap.get("bench") or []:
        if not row:
            continue
        out.append(_si(row.get("id") if isinstance(row, dict) else getattr(row, "id", 0)))
    return out


def _hand_ids(snap: dict[str, Any]) -> list[int]:
    return [_si(x) for x in (snap.get("hand") or [])]


def _flush_turn_setup(
    *,
    snap: dict[str, Any] | None,
    plays: list[int],
    pre_mega: bool,
    counters: dict[str, int],
    events: list[dict[str, Any]],
    my_turn: int,
) -> None:
    """Score missed / wrong setup plays for one of our turns (pre-Mega window)."""
    if snap is None or not pre_mega or my_turn <= 0:
        return
    hand = set(_hand_ids(snap))
    active = _active_id(snap)
    bench = _bench_ids(snap)
    field = set([active] + bench) - {0}
    played = set(plays)
    staryu_on = STARYU in field or MEGA_STARMIE in field
    mega_in_hand = MEGA_STARMIE in hand
    need_base = not staryu_on
    wrong_active = (
        active not in (0, STARYU, MEGA_STARMIE)
        and (STARYU in bench or mega_in_hand)
    )
    dry_staryu = active == STARYU and not _active_has_water(snap)
    need_mega_fetch = staryu_on and not mega_in_hand and MEGA_STARMIE not in field

    def _miss(kind: str, card: int) -> None:
        counters[kind] = counters.get(kind, 0) + 1
        events.append({
            "my_turn": my_turn,
            "kind": kind,
            "card": card,
            "active": active,
            "bench": list(bench),
            "hand_had": sorted(hand & (SETUP_ITEMS | SETUP_SUPPORTERS | {STARYU, MEGA_STARMIE})),
        })

    # Missed seating Staryu from hand.
    if need_base and STARYU in hand and STARYU not in played:
        _miss("miss_play_staryu", STARYU)

    # Missed fetch tools when base missing.
    if need_base and STARYU not in hand:
        if POFFIN in hand and POFFIN not in played:
            _miss("miss_poffin", POFFIN)
        if POKE_PAD in hand and POKE_PAD not in played:
            _miss("miss_pad", POKE_PAD)
        if ULTRA_BALL in hand and ULTRA_BALL not in played:
            _miss("miss_ub", ULTRA_BALL)
        # Lillie dig only when no free basic-search item.
        if (
            LILLIE in hand
            and LILLIE not in played
            and not hand.intersection({POFFIN, POKE_PAD, ULTRA_BALL})
        ):
            _miss("miss_lillie", LILLIE)

    # Wrong active: had Switch but did not promote line.
    if wrong_active and SWITCH in hand and SWITCH not in played:
        _miss("miss_switch", SWITCH)

    # Mega fetch supporters while line online.
    if need_mega_fetch:
        if HILDA in hand and HILDA not in played:
            _miss("miss_hilda", HILDA)
        if SALVATOR in hand and SALVATOR not in played:
            _miss("miss_salvator", SALVATOR)
        if ULTRA_BALL in hand and ULTRA_BALL not in played and HILDA not in played:
            # Ball dig for Mega when Hilda also unused / absent.
            if HILDA not in hand:
                _miss("miss_ub_mega", ULTRA_BALL)

    # Dry Staryu: Crispin unused.
    if dry_staryu and CRISPIN in hand and CRISPIN not in played:
        _miss("miss_crispin", CRISPIN)

    # Wrong use: side basics / tools that steal the turn while base/mega gap open.
    if need_base or wrong_active or need_mega_fetch:
        for cid in plays:
            if cid in SIDE_BASICS:
                _miss("wrong_play_side_basic", cid)
            elif cid == BOSS_ORDERS:
                _miss("wrong_play_boss", cid)


def derive_path_metrics(
    engine_logs: list[dict[str, Any]],
    pi: int,
) -> dict[str, Any]:
    """Path clocks for one seat from a single game's engine_logs.

    ``pi`` is the playerIndex of the seat under analysis (0 or 1).
    """
    my_turn = 0  # increments on our logical TURN_START
    # Engine dual-renders many turns (two TURN_START per logical my-turn).
    # Only open a new my-turn after setup or after the opponent's TURN_START.
    saw_other_turn_start = True
    mega_evo_my_t: int | None = None
    mega_atk_my_t: int | None = None
    water_attach_pre_mega = False
    boss_play_count = 0
    boss_first_my_t: int | None = None
    munk_play_my_t: int | None = None
    munk_dark_attach = False
    budew_play_my_t: int | None = None
    budew_itchy_count = 0
    prize_curve: list[dict[str, int]] = []
    mega_seen = False

    # Exposure / stuck-active (pre-Mega Active window).
    staryu_active_turns = 0
    staryu_solo_exposed_turns = 0
    wrong_active_turns = 0
    wrong_active_first_id: int | None = None
    wrong_active_first_my_t: int | None = None
    ever_staryu_solo = False
    ever_wrong_active = False

    setup_miss_counts: dict[str, int] = {}
    setup_miss_events: list[dict[str, Any]] = []
    turn_snap: dict[str, Any] | None = None
    turn_plays: list[int] = []
    turn_pre_mega = True

    def _close_turn() -> None:
        nonlocal turn_snap, turn_plays
        _flush_turn_setup(
            snap=turn_snap,
            plays=turn_plays,
            pre_mega=turn_pre_mega,
            counters=setup_miss_counts,
            events=setup_miss_events,
            my_turn=my_turn,
        )
        turn_snap = None
        turn_plays = []

    for lg in engine_logs:
        if not isinstance(lg, dict):
            continue
        t = lg.get("type")

        # Synthetic SNAPSHOT after TURN_START (type is string).
        if t == "SNAPSHOT":
            snap_pi = _si(lg.get("playerIndex"), -1)
            if snap_pi == pi and my_turn > 0:
                prize_curve.append({
                    "my_turn": my_turn,
                    "prize_self": _si(lg.get("prize_self"), -1),
                    "prize_opp": _si(lg.get("prize_opp"), -1),
                })
                turn_snap = lg
                active = _active_id(lg)
                bench = _bench_ids(lg)
                hand = _hand_ids(lg)
                pre = not mega_seen
                if pre:
                    if active == STARYU:
                        staryu_active_turns += 1
                        if len(bench) == 0:
                            staryu_solo_exposed_turns += 1
                            ever_staryu_solo = True
                    elif active not in (0, MEGA_STARMIE) and (
                        STARYU in bench or MEGA_STARMIE in hand
                    ):
                        wrong_active_turns += 1
                        ever_wrong_active = True
                        if wrong_active_first_id is None:
                            wrong_active_first_id = active
                            wrong_active_first_my_t = my_turn
            continue

        t = _si(t, -1)
        lg_pi = _si(lg.get("playerIndex"), -1)

        if t == LT_TURN_START and lg_pi != pi:
            saw_other_turn_start = True
            continue

        if t == LT_TURN_START and lg_pi == pi:
            # Skip the duplicate TURN_START from combat dual-render.
            if my_turn > 0 and not saw_other_turn_start:
                continue
            # Closing previous our-turn before opening a new one.
            if my_turn > 0:
                _close_turn()
            my_turn += 1
            saw_other_turn_start = False
            turn_pre_mega = not mega_seen
            turn_plays = []
            continue

        if lg_pi != pi:
            continue

        if t == LT_EVOLVE:
            evo_id = _si(lg.get("cardId"))
            if evo_id == MEGA_STARMIE and mega_evo_my_t is None:
                mega_evo_my_t = my_turn
                mega_seen = True
            continue

        if t == LT_ATTACH:
            eid = _si(lg.get("cardId"))
            tid = _si(lg.get("cardIdTarget"))
            if (
                not mega_seen
                and eid in WATER_IDS
                and tid in (STARYU, MEGA_STARMIE)
            ):
                water_attach_pre_mega = True
            if tid == MUNKIDORI and eid in DARK_IDS:
                munk_dark_attach = True
            continue

        if t == LT_MOVE_ATTACHED:
            eid = _si(lg.get("cardId"))
            after = _si(lg.get("cardIdAfter"))
            if after == MUNKIDORI and eid in DARK_IDS:
                munk_dark_attach = True
            continue

        if t == LT_PLAY:
            cid = _si(lg.get("cardId"))
            turn_plays.append(cid)
            if cid == BOSS_ORDERS:
                boss_play_count += 1
                if boss_first_my_t is None:
                    boss_first_my_t = my_turn
            elif cid == MUNKIDORI and munk_play_my_t is None:
                munk_play_my_t = my_turn
            elif cid == BUDEW and budew_play_my_t is None:
                budew_play_my_t = my_turn
            continue

        if t == LT_ATTACK:
            aid = _si(lg.get("attackId"))
            cid = _si(lg.get("cardId"))
            if mega_atk_my_t is None and (
                aid in ST_ATKS or cid == MEGA_STARMIE
            ):
                mega_atk_my_t = my_turn
            if aid == ITCHY_POLLEN:
                budew_itchy_count += 1
            continue

    # Flush last open turn.
    if my_turn > 0:
        _close_turn()

    mega_gap: int | None
    if mega_evo_my_t is None:
        mega_gap = None
    elif mega_atk_my_t is None:
        mega_gap = None  # evolved but never attacked
    else:
        mega_gap = mega_atk_my_t - mega_evo_my_t

    prize_at_t4 = None
    for row in prize_curve:
        if row["my_turn"] == 4:
            prize_at_t4 = {
                "prize_self": row["prize_self"],
                "prize_opp": row["prize_opp"],
                "delta": row["prize_opp"] - row["prize_self"],  # >0 = we lead
            }
            break

    miss_total = sum(setup_miss_counts.values())
    return {
        "pi": pi,
        "max_my_turn": my_turn,
        "mega_evo_my_t": mega_evo_my_t,
        "mega_atk_my_t": mega_atk_my_t,
        "mega_gap": mega_gap,
        "mega_evolved_no_attack": bool(
            mega_evo_my_t is not None and mega_atk_my_t is None
        ),
        "water_attach_pre_mega": water_attach_pre_mega,
        "boss_play_count": boss_play_count,
        "boss_first_my_t": boss_first_my_t,
        "munk_play_my_t": munk_play_my_t,
        "munk_dark_attach": munk_dark_attach,
        "budew_play_my_t": budew_play_my_t,
        "budew_itchy_count": budew_itchy_count,
        "prize_curve": prize_curve,
        "prize_at_t4": prize_at_t4,
        "path_bucket": _path_bucket(mega_evo_my_t),
        # Exposure / stuck Active
        "staryu_active_turns": staryu_active_turns,
        "staryu_solo_exposed_turns": staryu_solo_exposed_turns,
        "ever_staryu_solo_exposed": ever_staryu_solo,
        "wrong_active_turns": wrong_active_turns,
        "ever_wrong_active": ever_wrong_active,
        "wrong_active_first_id": wrong_active_first_id,
        "wrong_active_first_my_t": wrong_active_first_my_t,
        # Setup tool / supporter misses (pre-Mega)
        "setup_miss_counts": setup_miss_counts,
        "setup_miss_total": miss_total,
        "setup_miss_events": setup_miss_events[:24],  # cap for manifest size
    }


def compare_sides(
    engine_logs: list[dict[str, Any]],
    *,
    cur_pi: int,
) -> dict[str, Any]:
    """Same-game dual-seat metrics for mirror H2H."""
    opp_pi = 1 - cur_pi
    cur = derive_path_metrics(engine_logs, cur_pi)
    opp = derive_path_metrics(engine_logs, opp_pi)

    def _delta(a: int | None, b: int | None) -> int | None:
        if a is None or b is None:
            return None
        return a - b

    return {
        "cur": cur,
        "opp": opp,
        "mega_evo_delta": _delta(cur["mega_evo_my_t"], opp["mega_evo_my_t"]),
        # Negative => current evolved earlier (good).
        "mega_atk_delta": _delta(cur["mega_atk_my_t"], opp["mega_atk_my_t"]),
        "cur_mega_first": (
            cur["mega_evo_my_t"] is not None
            and (
                opp["mega_evo_my_t"] is None
                or cur["mega_evo_my_t"] < opp["mega_evo_my_t"]
            )
        ),
        "opp_mega_first": (
            opp["mega_evo_my_t"] is not None
            and (
                cur["mega_evo_my_t"] is None
                or opp["mega_evo_my_t"] < cur["mega_evo_my_t"]
            )
        ),
        "cur_boss_first": (
            cur["boss_first_my_t"] is not None
            and (
                opp["boss_first_my_t"] is None
                or cur["boss_first_my_t"] < opp["boss_first_my_t"]
            )
        ),
        "cur_itchy": cur["budew_itchy_count"] > 0,
        "opp_itchy": opp["budew_itchy_count"] > 0,
    }
