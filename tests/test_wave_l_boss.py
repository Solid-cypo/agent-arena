"""Wave L: effective Boss after fueled Mega — no OPENING demote changes."""
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
    DARK_BASIC,
    MEGA_STARMIE,
    NIGHT_STRETCHER,
    STARYU,
    WATER_BASIC,
)
from turn_planner import build_turn_plan
import starmie_pilot as sp

# Dragapult ex — high boss_priority MAIN_ATTACKER
DRAGAPULT_EX = 121
# Unknown wall (boss_priority 0)
WALL = 900


def _pkm(cid, hp=100, max_hp=None, energies=(), **kw):
    return NS(
        id=cid,
        hp=hp,
        maxHp=max_hp if max_hp is not None else hp,
        energies=list(energies),
        **kw,
    )


def _player(*, active=None, bench=(), hand=(), discard=(), prizes=6, hand_count=None):
    return NS(
        active=[active] if active else [],
        bench=list(bench),
        hand=[NS(id=cid) for cid in hand],
        discard=[NS(id=cid) for cid in discard],
        prize=[None] * prizes,
        prizeCount=prizes,
        handCount=len(hand) if hand_count is None else hand_count,
        supporterPlayed=False,
        energyAttached=False,
        deckCount=30,
    )


def _obs(me, opp, *, turn=7, first_player=0):
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


def test_wave_l_boss_before_dp_prep():
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=280, max_hp=330, energies=(WATER_BASIC,)),
        bench=(_pkm(sp._MUNKIDORI_ID, energies=(DARK_BASIC,)),),
        hand=(BOSS_ORDERS,),
        prizes=4,
    )
    opp = _player(
        active=_pkm(WALL, hp=200),
        bench=(_pkm(DRAGAPULT_EX, hp=110, ex=True),),
        hand_count=3,
        prizes=5,
    )
    plan = build_turn_plan(_obs(me, opp), build_board_snapshot(_obs(me, opp)))
    assert plan.combat.boss_target is not None
    assert plan.combat.required_before_attack[0] == "BOSS"
    assert "ADRENA" in plan.combat.required_before_attack


def test_wave_l_role_cut_when_closing():
    """Equal prizes, ≤3 own prizes, higher boss_priority → Boss forced."""
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS,),
        prizes=3,
    )
    opp = _player(
        active=_pkm(WALL, hp=100, ex=True),
        bench=(_pkm(DRAGAPULT_EX, hp=110, ex=True),),
        hand_count=3,
        prizes=4,
    )
    obs = _obs(me, opp)
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert plan.combat.boss_target is not None
    assert plan.combat.boss_target.card_id == DRAGAPULT_EX
    assert "BOSS" in plan.combat.required_before_attack
    sit = sp._compute_situation(obs)
    assert (
        sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit)
        >= sp._DOMINATE_OPEN_PATH
    )


def test_wave_l_opening_still_bans_boss():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS, MEGA_STARMIE),
        prizes=6,
    )
    opp = _player(
        active=_pkm(WALL, hp=200),
        bench=(_pkm(DRAGAPULT_EX, hp=100, ex=True),),
        hand_count=2,
    )
    obs = _obs(me, opp, turn=1, first_player=0)
    sit = sp._compute_situation(obs)
    assert sit["phase"].primary == "OPENING"
    bonus = sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit)
    assert bonus <= -sp._DOMINATE


def test_wave_l_recover_boss_from_discard():
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(NIGHT_STRETCHER,),
        discard=(BOSS_ORDERS,),
        prizes=4,
    )
    opp = _player(active=_pkm(WALL, hp=80), hand_count=2)
    plan = build_turn_plan(_obs(me, opp), build_board_snapshot(_obs(me, opp)))
    assert plan.acquire.recover_target == BOSS_ORDERS


def test_gs_t1_budew_untouched():
    """Regression: Wave L must not touch GS My-T1 Budew PATH."""
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(sp._BUDEW_ID, 860),
    )
    obs = _obs(
        me,
        _player(active=_pkm(999, hp=200), hand_count=2),
        turn=2,
        first_player=1,
    )
    sit = sp._compute_situation(obs)
    assert (
        sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit)
        >= sp._DOMINATE_OPEN
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
    print("ok")
