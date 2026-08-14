"""Wave G: force Mega dig, demote side basics, ban base attack on dispatch."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, OptionType, SelectContext
from hand_snapshot import build_board_snapshot
from opening_cards import (
    HILDA,
    MEGA_STARMIE,
    MEOWTH_EX,
    MUNKIDORI,
    SALVATOR,
    SNORUNT,
    STARYU,
    ULTRA_BALL,
    WATER_BASIC,
)
from turn_planner import build_turn_plan
import starmie_pilot as sp

SWITCH = 1123
ITCHY = 323


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


def test_need_evolution_locks_mega_and_allows_ball():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(ULTRA_BALL, MUNKIDORI),
    )
    obs = _obs(me)
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert plan.gap.need_evolution
    # No Lillie → Meowth first; Mega still listed for free Hilda path.
    assert plan.acquire.targets[0] == MEOWTH_EX
    assert MEGA_STARMIE in plan.acquire.targets
    assert plan.acquire.ball_allowed
    sit = sp._compute_situation(obs)
    ub = NS(type=OptionType.PLAY, index=0)
    munk = NS(type=OptionType.PLAY, index=1)
    # Ball dig (Meowth/Mega) must outrank parking Munk while attacker line incomplete.
    assert sp._hard_rule_bonus(obs, ub, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, ub, sit) > sp._hard_rule_bonus(obs, munk, sit)


def test_salvator_dominates_when_need_mega():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(SALVATOR, SNORUNT),
    )
    obs = _obs(me)
    sit = sp._compute_situation(obs)
    salv = NS(type=OptionType.PLAY, index=0)
    snor = NS(type=OptionType.PLAY, index=1)
    assert sit["turn_plan"].gap.need_evolution
    assert sp._hard_rule_bonus(obs, salv, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, snor, sit) <= -sp._DOMINATE_OPEN_PATH


def test_dispatch_bans_itchy_when_bench_mega_ready():
    mega = _pkm(MEGA_STARMIE, energies=(WATER_BASIC,))
    me = _player(
        active=_pkm(sp._BUDEW_ID),
        bench=(mega,),
        hand=(SWITCH,),
    )
    obs = _obs(me, turn=5)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.attack_required
    itchy = NS(type=OptionType.ATTACK, attackId=ITCHY)
    sw = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, itchy, sit) <= -sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, sw, sit) >= sp._DOMINATE_OPEN_PATH


def test_gs_t1_budew_not_outranked_by_ub():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(ULTRA_BALL, sp._BUDEW_ID),
    )
    # Going second My-T1: first_player=1, engine turn=2.
    obs = _obs(me, turn=2, first_player=1)
    sit = sp._compute_situation(obs)
    assert sp._going_second(sit["board"])
    assert int(sit["board"].my_turn_number) == 1
    ub = NS(type=OptionType.PLAY, index=0)
    budew = NS(type=OptionType.PLAY, index=1)
    assert sp._hard_rule_bonus(obs, budew, sit) >= sp._hard_rule_bonus(obs, ub, sit)


def test_gs_after_t1_ub_outranks_new_budew():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(ULTRA_BALL, sp._BUDEW_ID),
    )
    # Going second My-T2: engine turn=4.
    obs = _obs(me, turn=4, first_player=1)
    sit = sp._compute_situation(obs)
    assert sp._going_second(sit["board"])
    assert int(sit["board"].my_turn_number) >= 2
    ub = NS(type=OptionType.PLAY, index=0)
    budew = NS(type=OptionType.PLAY, index=1)
    assert sp._hard_rule_bonus(obs, ub, sit) > sp._hard_rule_bonus(obs, budew, sit)


def test_hilda_in_sources_for_mega():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(HILDA,),
    )
    obs = _obs(me)
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert MEGA_STARMIE in plan.acquire.targets
    assert HILDA in plan.acquire.sources


def test_spent_supporter_does_not_block_ub_mega():
    """Dead Salvator/Hilda in hand must not UB-3-lock Ball dig for Mega."""
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(SALVATOR, ULTRA_BALL, MUNKIDORI),
    )
    me.supporterPlayed = True
    obs = _obs(me)
    plan = build_turn_plan(obs, build_board_snapshot(obs))
    assert MEGA_STARMIE in plan.acquire.targets
    assert SALVATOR not in plan.acquire.sources
    assert plan.acquire.ball_allowed
