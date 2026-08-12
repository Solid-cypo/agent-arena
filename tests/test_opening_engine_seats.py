"""Field seat preset: Staryu×2 · Snorunt×1 · Munk×1 · Dunsparce×1 · flex×1.

Field6Narrow: pre-Mega Staryu/Snorunt dual-line mutex.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, OptionType
from opening_bench import (
    BENCH_ROLE_CAPS,
    can_bench_card,
    flex_occupants,
    missing_core_seats,
    role_counts_from_ids,
)
from opening_cards import (
    BUDEW,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FAN_ROTOM,
    HILDA,
    MEGA_STARMIE,
    MUNKIDORI,
    SNORUNT,
    STARYU,
    WATER_BASIC,
)
import starmie_pilot as sp


def _pkm(cid, hp=70, energies=None, **kw):
    return NS(id=cid, hp=hp, maxHp=hp, energies=list(energies or []), **kw)


def _player(*, active=None, bench=(), hand=()):
    return NS(
        active=[active] if active else [],
        bench=list(bench),
        hand=[NS(id=c) for c in hand],
        discard=[],
        prize=[None] * 6,
        prizeCount=6,
        handCount=len(hand),
        supporterPlayed=False,
        energyAttached=False,
        deckCount=30,
    )


def _obs(*, me, opp, turn=2, first_player=0):
    return NS(
        current=NS(
            turn=turn,
            yourIndex=0,
            firstPlayer=first_player,
            stadium=[],
            players=[me, opp],
        ),
        select=NS(context=0, deck=[], option=[]),
    )


def test_bench_role_caps_match_preset():
    assert BENCH_ROLE_CAPS == {
        "staryu": 2,
        "snorunt": 1,
        "dunsparce": 1,
        "munk": 1,
        "flex": 1,
    }
    # Active counts toward caps (6-seat field).
    assert role_counts_from_ids(STARYU, [STARYU, SNORUNT])["staryu"] == 2
    assert can_bench_card(STARYU, [], 5, STARYU)  # second 海星星
    # Pre-Mega: Staryu on field → no Snorunt bench.
    assert not can_bench_card(STARYU, [], 5, SNORUNT)
    assert can_bench_card(STARYU, [], 5, DUNSPARCE_A)
    assert not can_bench_card(STARYU, [DUNSPARCE_A], 4, DUNSPARCE_B)  # 土龙×1
    assert can_bench_card(STARYU, [DUNSPARCE_A], 4, MUNKIDORI)
    assert not can_bench_card(STARYU, [MUNKIDORI], 4, MUNKIDORI)
    # Mega on active uses a Staryu seat — third 海星需吃灵活位且要给核心留座.
    assert not can_bench_card(MEGA_STARMIE, [STARYU], 4, STARYU)
    # Post-Mega: dual-line OK under caps.
    assert can_bench_card(MEGA_STARMIE, [], 5, SNORUNT)


def test_pre_mega_dual_line_mutex():
    """Active-only Snorunt may still bench Staryu; dual bench lines blocked."""
    assert can_bench_card(SNORUNT, [], 5, STARYU)
    assert not can_bench_card(SNORUNT, [STARYU], 4, SNORUNT)  # field has Staryu
    assert not can_bench_card(BUDEW, [SNORUNT], 4, STARYU)  # bench frost blocks Staryu
    assert can_bench_card(BUDEW, [], 5, STARYU)
    assert can_bench_card(BUDEW, [], 5, SNORUNT)


def test_flex_is_unreserved_seat_not_tool_caste():
    """Tools may use flex, but must leave open seats for missing cores."""
    # Pre-Mega + Active Staryu: missing = 2nd star + munk + duns (no snorunt) = 3.
    assert missing_core_seats(STARYU, []) == 3
    assert can_bench_card(STARYU, [], 5, FAN_ROTOM)
    # open=3, missing=3 → tool would leave 2 < 3 → block.
    assert not can_bench_card(STARYU, [], 3, BUDEW)
    # open=4 > 3 → tool OK under narrowed reserve.
    assert can_bench_card(STARYU, [], 4, BUDEW)
    # Core already parked on flex tool: second tool blocked.
    assert flex_occupants(STARYU, [FAN_ROTOM]) == 1
    assert not can_bench_card(STARYU, [FAN_ROTOM], 4, BUDEW)
    # After cores filled (post-Mega dual-line board), last open may take a tool.
    full_cores = [STARYU, SNORUNT, MUNKIDORI, DUNSPARCE_A]  # + active STARYU = 2 star
    # Pre-Mega this board is illegal to build via can_bench; counts still 0 missing.
    assert missing_core_seats(STARYU, full_cores) == 0
    assert can_bench_card(MEGA_STARMIE, [STARYU, SNORUNT, MUNKIDORI, DUNSPARCE_A], 1, FAN_ROTOM)
    # 66 occupies the dunsparce core seat (not flex) until it leaves.
    assert flex_occupants(STARYU, [DUDUNSPARCE, SNORUNT]) == 0
    # Pre-Mega: bench Snorunt zeros Staryu reserve → missing munk only.
    assert missing_core_seats(STARYU, [DUDUNSPARCE, SNORUNT]) == 1


def test_hand_dunsparce_paths_over_end():
    hand = (DUNSPARCE_A, HILDA, WATER_BASIC)
    me = _player(active=_pkm(STARYU), hand=hand)
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=2)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_MID
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL


def test_second_dunsparce_blocked_under_cap():
    """Field preset allows only one Dunsparce seat."""
    hand = (DUNSPARCE_B, HILDA)
    me = _player(
        active=_pkm(STARYU),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=3)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    assert not sp._obs_can_bench_card(obs, 0, DUNSPARCE_B)
    # Must not get engine-seat PATH for over-cap Dunsparce.
    assert sp._hard_rule_bonus(obs, play, sit) < sp._DOMINATE_OPEN - 1.0


def test_bench_duns_hand_66_evolves():
    hand = (DUDUNSPARCE, HILDA)
    me = _player(
        active=_pkm(STARYU),
        bench=[_pkm(DUNSPARCE_A)],
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    evo66 = NS(
        type=OptionType.EVOLVE, playerIndex=0, area=AreaType.HAND, index=0,
    )
    end = NS(type=OptionType.END)
    obs = _obs(me=me, opp=opp, turn=3)
    sit = sp._compute_situation(obs)
    sit["select_options"] = [
        NS(type=OptionType.PLAY, index=0),
        NS(type=OptionType.PLAY, index=1),
        evo66,
        end,
    ]
    assert sp._hard_rule_bonus(obs, evo66, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, end, sit) < 0


def test_hand_munk_benches_after_staryu():
    hand = (MUNKIDORI, HILDA, WATER_BASIC)
    me = _player(active=_pkm(STARYU), hand=hand)
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=2)
    sit = sp._compute_situation(obs)
    play = NS(type=OptionType.PLAY, index=0)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_MID
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL


def test_wait_evolve_fills_dunsparce_over_end():
    """Sick window: hand Dunsparce must beat blank END."""
    hand = (MEGA_STARMIE, DUNSPARCE_A, HILDA)
    me = _player(
        active=_pkm(STARYU, canEvolve=False),
        hand=hand,
    )
    opp = _player(active=_pkm(SNORUNT))
    obs = _obs(me=me, opp=opp, turn=1, first_player=0)
    sit = sp._compute_situation(obs)
    assert sp._plan_primary_step(sit["turn_plan"]) == "WAIT_EVOLVE"
    play = NS(type=OptionType.PLAY, index=1)
    end = NS(type=OptionType.END)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE_OPEN - 30.0
    assert sp._hard_rule_bonus(obs, end, sit) <= sp._ATTACH_ILLEGAL
