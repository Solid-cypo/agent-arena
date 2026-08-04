"""Unit tests for scripts/engine_log_metrics.py (synthetic engine_logs)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from engine_log_metrics import (  # noqa: E402
    BOSS_ORDERS,
    BUDEW,
    DARK_BASIC,
    ITCHY_POLLEN,
    LT_ATTACH,
    LT_ATTACK,
    LT_EVOLVE,
    LT_PLAY,
    LT_TURN_START,
    MEGA_STARMIE,
    MUNKIDORI,
    STARYU,
    WATER_BASIC,
    compare_sides,
    derive_path_metrics,
)


def _ts(pi: int) -> dict:
    return {"type": LT_TURN_START, "playerIndex": pi}


def _snap(
    pi: int,
    prize_self: int,
    prize_opp: int,
    *,
    active: int | None = None,
    bench: list[int] | None = None,
    hand: list[int] | None = None,
    energies: list[int] | None = None,
) -> dict:
    act = []
    if active is not None:
        act = [{"id": active, "hp": 70, "energies": list(energies or [])}]
    return {
        "type": "SNAPSHOT",
        "playerIndex": pi,
        "prize_self": prize_self,
        "prize_opp": prize_opp,
        "hand": list(hand or []),
        "active": act,
        "bench": [{"id": b, "hp": 70, "energies": []} for b in (bench or [])],
    }


def test_mega_path_bucket_and_gap():
    # pi=0: T1 setup, T2 water, T3 evolve+attack → fast_mega, gap=0
    logs = [
        _ts(0), _snap(0, 6, 6),
        _ts(1), _snap(1, 6, 6),
        _ts(0), _snap(0, 6, 6),
        {"type": LT_ATTACH, "playerIndex": 0, "cardId": WATER_BASIC, "cardIdTarget": STARYU},
        _ts(1), _snap(1, 6, 6),
        _ts(0), _snap(0, 6, 6),
        {
            "type": LT_EVOLVE,
            "playerIndex": 0,
            "cardId": MEGA_STARMIE,
            "cardIdTarget": STARYU,
        },
        {"type": LT_ATTACK, "playerIndex": 0, "cardId": MEGA_STARMIE, "attackId": 1487},
    ]
    m = derive_path_metrics(logs, 0)
    assert m["mega_evo_my_t"] == 3
    assert m["mega_atk_my_t"] == 3
    assert m["mega_gap"] == 0
    assert m["water_attach_pre_mega"] is True
    assert m["path_bucket"] == "fast_mega_t≤3"


def test_no_mega_bucket():
    logs = [_ts(0), _snap(0, 6, 6), _ts(1), _snap(1, 6, 6)]
    m = derive_path_metrics(logs, 0)
    assert m["path_bucket"] == "no_mega"
    assert m["mega_gap"] is None


def test_mega_late_and_evolved_no_attack():
    logs = []
    for t in range(1, 8):
        logs += [_ts(0), _snap(0, 6, 6), _ts(1), _snap(1, 6, 6)]
    logs += [
        _ts(0),
        _snap(0, 5, 6),
        {
            "type": LT_EVOLVE,
            "playerIndex": 0,
            "cardId": MEGA_STARMIE,
            "cardIdTarget": STARYU,
        },
        # no attack
    ]
    m = derive_path_metrics(logs, 0)
    assert m["mega_evo_my_t"] == 8
    assert m["path_bucket"] == "mega_late_>6"
    assert m["mega_evolved_no_attack"] is True
    assert m["mega_gap"] is None


def test_boss_munk_budew_itchy():
    logs = [
        _ts(0), _snap(0, 6, 6),
        {"type": LT_PLAY, "playerIndex": 0, "cardId": BUDEW},
        {"type": LT_ATTACK, "playerIndex": 0, "cardId": BUDEW, "attackId": ITCHY_POLLEN},
        _ts(1), _snap(1, 6, 6),
        _ts(0), _snap(0, 6, 6),
        {"type": LT_PLAY, "playerIndex": 0, "cardId": MUNKIDORI},
        {
            "type": LT_ATTACH,
            "playerIndex": 0,
            "cardId": DARK_BASIC,
            "cardIdTarget": MUNKIDORI,
        },
        _ts(1), _snap(1, 6, 6),
        _ts(0), _snap(0, 5, 6),
        {"type": LT_PLAY, "playerIndex": 0, "cardId": BOSS_ORDERS},
    ]
    m = derive_path_metrics(logs, 0)
    assert m["budew_play_my_t"] == 1
    assert m["budew_itchy_count"] == 1
    assert m["munk_play_my_t"] == 2
    assert m["munk_dark_attach"] is True
    assert m["boss_play_count"] == 1
    assert m["boss_first_my_t"] == 3
    assert m["prize_at_t4"] is None  # only reached T3


def test_compare_sides_mega_first():
    # Seat 0 evolves T2; seat 1 evolves T4 → cur_pi=0 mega first
    logs = [
        _ts(0), _snap(0, 6, 6),
        _ts(1), _snap(1, 6, 6),
        _ts(0), _snap(0, 6, 6),
        {
            "type": LT_EVOLVE,
            "playerIndex": 0,
            "cardId": MEGA_STARMIE,
            "cardIdTarget": STARYU,
        },
        _ts(1), _snap(1, 6, 6),
        _ts(0), _snap(0, 6, 6),
        _ts(1), _snap(1, 6, 6),
        _ts(0), _snap(0, 6, 6),
        _ts(1), _snap(1, 6, 6),
        {
            "type": LT_EVOLVE,
            "playerIndex": 1,
            "cardId": MEGA_STARMIE,
            "cardIdTarget": STARYU,
        },
    ]
    c = compare_sides(logs, cur_pi=0)
    assert c["cur_mega_first"] is True
    assert c["opp_mega_first"] is False
    assert c["mega_evo_delta"] == 2 - 4  # cur T2 - opp T4 = -2
    c2 = compare_sides(logs, cur_pi=1)
    assert c2["opp_mega_first"] is True  # from cur_pi=1 view, opp is seat 0


def test_staryu_solo_exposed_and_miss_poffin():
    from engine_log_metrics import POFFIN

    # T1: solo Staryu, hand has Poffin but never plays it (no bench piece needed —
    # still counts as miss when base already online? no — need_base false.
    # Use Active=Snorunt, no Staryu on field, hand has Poffin unused.
    logs = [
        _ts(0),
        _snap(0, 6, 6, active=860, bench=[], hand=[POFFIN, 1227]),
        # no PLAY
        _ts(1),
        _snap(1, 6, 6),
    ]
    m = derive_path_metrics(logs, 0)
    assert m["ever_wrong_active"] is False  # no staryu on bench / mega in hand
    assert m["setup_miss_counts"].get("miss_poffin", 0) == 1


def test_wrong_active_miss_switch_and_solo_exposed():
    from engine_log_metrics import SWITCH, MEGA_STARMIE as MEGA

    # Wrong active: Snorunt up, Staryu on bench, Switch in hand unused.
    logs = [
        _ts(0),
        _snap(0, 6, 6, active=860, bench=[STARYU], hand=[SWITCH, MEGA]),
        _ts(1),
        _snap(1, 6, 6),
        # Solo exposed Staryu next turn
        _ts(0),
        _snap(0, 6, 6, active=STARYU, bench=[], hand=[WATER_BASIC]),
    ]
    m = derive_path_metrics(logs, 0)
    assert m["ever_wrong_active"] is True
    assert m["wrong_active_first_id"] == 860
    assert m["setup_miss_counts"].get("miss_switch", 0) == 1
    assert m["ever_staryu_solo_exposed"] is True
    assert m["staryu_solo_exposed_turns"] >= 1
