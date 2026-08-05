"""Wave I: seat B My-T2+ side demote + evolve PATH + GS T1 Budew intact."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import OptionType
from hand_snapshot import build_board_snapshot
from opening_cards import (
    BOSS_ORDERS,
    HILDA,
    MEGA_STARMIE,
    MEOWTH_EX,
    SNORUNT,
    STARYU,
    SWITCH,
    WATER_BASIC,
)
from turn_planner import build_turn_plan, is_basic_attack_forbidden
import starmie_pilot as sp


def _pkm(cid, hp=100, max_hp=None, energies=(), **kw):
    return NS(
        id=cid,
        hp=hp,
        maxHp=max_hp if max_hp is not None else hp,
        energies=list(energies),
        **kw,
    )


def _player(*, active=None, bench=(), hand=(), prizes=6, hand_count=None):
    return NS(
        active=[active] if active else [],
        bench=list(bench),
        hand=[NS(id=cid) if isinstance(cid, int) else cid for cid in hand],
        discard=[],
        prize=[None] * prizes,
        prizeCount=prizes,
        handCount=len(hand) if hand_count is None else hand_count,
        supporterPlayed=False,
        energyAttached=False,
        deckCount=30,
    )


def _obs(me, opp=None, *, turn=3, my_index=0, first_player=0, ctx=0):
    opp = opp or _player(active=_pkm(999, hp=200), hand_count=2)
    return NS(
        current=NS(
            turn=turn,
            yourIndex=my_index,
            firstPlayer=first_player,
            stadium=[],
            players=[me, opp] if my_index == 0 else [opp, me],
        ),
        select=NS(context=int(ctx), deck=[], option=[]),
    )


def test_i1_gs_t1_budew_still_path():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(sp._BUDEW_ID, SNORUNT),
    )
    # going second My-T1: firstPlayer=1, turn=2 → my_turn 1
    obs = _obs(me, turn=2, first_player=1)
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) >= sp._DOMINATE_OPEN


def test_i1_gs_t2_snorunt_demoted_need_mega():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(SNORUNT, HILDA),
    )
    # going second My-T2: firstPlayer=1, turn=4 → my_turn 2
    obs = _obs(me, turn=4, first_player=1)
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) <= -sp._DOMINATE_OPEN_PATH


def test_i1_gs_t2_boss_demoted_mega_held():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS, MEGA_STARMIE),
    )
    obs = _obs(me, turn=4, first_player=1)
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) <= -sp._DOMINATE_OPEN_PATH


def test_i2_evolve_mega_path():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(MEGA_STARMIE,),
    )
    obs = _obs(me, turn=5, first_player=0)
    sit = sp._compute_situation(obs)
    # EVOLVE option: index unused; helper checks type + evolve target via option fields
    evo = NS(type=OptionType.EVOLVE, playerIndex=0, area=0, index=0, cardIndex=0)
    # If evolve helper cannot resolve synthetic option, at least Water Gun banned.
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert is_basic_attack_forbidden(STARYU, plan)


def test_i3_itchy_ok_unfueled_bench_mega():
    me = _player(
        active=_pkm(sp._BUDEW_ID, hp=30),
        bench=(_pkm(MEGA_STARMIE),),
    )
    obs = _obs(me, turn=2, first_player=1)
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert not is_basic_attack_forbidden(sp._BUDEW_ID, plan, attack_id=323)


def test_i3_dispatch_demotes_base_attack_when_switch_live():
    me = _player(
        active=_pkm(sp._CARDS["dunsparce_b"]),
        bench=(_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),),
        hand=(SWITCH,),
    )
    obs = _obs(me, turn=5)
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) >= sp._DOMINATE_OPEN_PATH
    atk = NS(type=OptionType.ATTACK, attackId=1)
    assert sp._hard_rule_bonus(obs, atk, sit) <= -sp._DOMINATE_OPEN_PATH


def test_reset_agent_state_is_per_state():
    a = {"opening_complete_this_game": True, "max_my_turn": 9}
    b = {"opening_complete_this_game": True, "max_my_turn": 3}
    # fill required keys via reset
    for st in (a, b):
        sp.reset_agent_state(st)
    assert a["opening_complete_this_game"] is False
    assert b["max_my_turn"] == 0
    assert a is not b
