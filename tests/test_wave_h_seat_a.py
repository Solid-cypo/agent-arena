"""Wave H: seat A / no_mega close — soft PATH overlays + Lillie source."""
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
    LILLIE,
    MEGA_STARMIE,
    MEOWTH_EX,
    POFFIN,
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


def test_h1_need_base_lillie_and_poffin_path():
    me = _player(active=_pkm(SNORUNT), hand=(MEGA_STARMIE, LILLIE, POFFIN))
    obs = _obs(me, turn=3, first_player=0)
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert plan.gap.need_base and LILLIE in plan.acquire.sources
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=1), sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=2), sit) >= sp._DOMINATE_OPEN_PATH


def test_h1_gs_t1_budew_still_path():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(sp._BUDEW_ID, POFFIN),
    )
    obs = _obs(me, turn=2, first_player=1)
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) >= sp._DOMINATE_OPEN


def test_h1_water_gun_banned_when_mega_can_evolve():
    me = _player(active=_pkm(STARYU, energies=(WATER_BASIC,)), hand=(MEGA_STARMIE,))
    obs = _obs(me, turn=5)
    assert is_basic_attack_forbidden(STARYU, build_turn_plan(obs, build_board_snapshot(obs)))


def test_h2_meowth_demoted_need_base_going_first():
    me = _player(active=_pkm(SNORUNT), hand=(MEOWTH_EX, POFFIN))
    obs = _obs(me, turn=3, first_player=0)
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) <= -sp._DOMINATE_OPEN_PATH


def test_h3_promote_bench_mega_path():
    me = _player(
        active=_pkm(sp._CARDS["dunsparce_b"]),
        bench=(_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),),
        hand=(SWITCH,),
    )
    obs = _obs(me, turn=5)
    sit = sp._compute_situation(obs)
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.PLAY, index=0), sit) >= sp._DOMINATE_OPEN_PATH


def test_h0_itchy_still_ok_with_unfueled_bench_mega():
    me = _player(
        active=_pkm(sp._BUDEW_ID, hp=30),
        bench=(_pkm(MEGA_STARMIE),),
    )
    obs = _obs(me, turn=2, first_player=1)
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert not is_basic_attack_forbidden(sp._BUDEW_ID, plan, attack_id=323)
