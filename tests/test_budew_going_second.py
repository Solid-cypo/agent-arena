"""Going-second Budew dispatch: play / promote / Itchy when legal."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from cg.api import AreaType, EnergyType, OptionType, SelectContext
import starmie_pilot as sp

WATER = int(EnergyType.WATER)
SWITCH = 1123


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


def _obs_gs(me, opp, *, turn=2, my_index=0, first_player=1, ctx=0):
    """Default: we are seat 0 going second (first_player=1)."""
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


def test_going_second_plays_budew_when_bench_open():
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        hand=(sp._BUDEW_ID, sp._CARDS["mega_starmie_ex"], WATER),
    )
    opp = _player(active=_pkm(999, hp=200))
    obs = _obs_gs(me, opp, turn=2)
    sit = sp._compute_situation(obs)
    assert sp._going_second(sit["board"])
    play = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, play, sit) >= sp._DOMINATE


def test_going_second_defers_budew_when_last_seat_needed_for_staryu():
    me = _player(
        active=_pkm(sp._CARDS["dunsparce_a"]),
        hand=(sp._BUDEW_ID,),
    )
    # Fill bench to 4 → one seat left, and no Staryu on field.
    me.bench = [_pkm(112), _pkm(860), _pkm(65), _pkm(174)]
    opp = _player(active=_pkm(999, hp=200))
    obs = _obs_gs(me, opp, turn=2)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].gap.need_base
    play = NS(type=OptionType.PLAY, index=0)
    assert sp._going_second_budew_bonus(obs, play, sit) == 0.0


def test_going_second_promotes_benched_budew_with_switch():
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        bench=(_pkm(sp._BUDEW_ID),),
        hand=(SWITCH,),
    )
    opp = _player(active=_pkm(999, hp=200))
    obs = _obs_gs(me, opp, turn=2)
    sit = sp._compute_situation(obs)
    switch = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, switch, sit) >= sp._DOMINATE


def test_going_second_selects_budew_on_to_active():
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        bench=(_pkm(sp._BUDEW_ID), _pkm(sp._CARDS["munkidori"])),
    )
    opp = _player(active=_pkm(999, hp=200))
    obs = _obs_gs(me, opp, turn=2, ctx=SelectContext.TO_ACTIVE)
    sit = sp._compute_situation(obs)
    budew = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=0)
    munk = NS(type=OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=0)
    assert sp._hard_rule_bonus(obs, budew, sit) > sp._hard_rule_bonus(obs, munk, sit)


def test_going_second_itchy_on_active_budew():
    me = _player(active=_pkm(sp._BUDEW_ID, hp=30))
    opp = _player(active=_pkm(999, hp=200))
    obs = _obs_gs(me, opp, turn=2)
    sit = sp._compute_situation(obs)
    itchy = NS(type=OptionType.ATTACK, attackId=323)
    assert sp._hard_rule_bonus(obs, itchy, sit) > 0


def test_going_second_budew_yields_to_ready_mega_attack():
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], energies=(WATER,)),
        hand=(sp._BUDEW_ID,),
    )
    opp = _player(active=_pkm(999, hp=200))
    obs = _obs_gs(me, opp, turn=4)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.attack_required
    play = NS(type=OptionType.PLAY, index=0)
    assert sp._going_second_budew_bonus(obs, play, sit) == 0.0


def test_going_first_does_not_force_budew_play():
    me = _player(
        active=_pkm(sp._CARDS["staryu"]),
        hand=(sp._BUDEW_ID,),
    )
    opp = _player(active=_pkm(999, hp=200))
    # first_player == my_index → going first
    obs = _obs_gs(me, opp, turn=3, first_player=0)
    sit = sp._compute_situation(obs)
    assert not sp._going_second(sit["board"])
    play = NS(type=OptionType.PLAY, index=0)
    assert sp._going_second_budew_bonus(obs, play, sit) == 0.0


if __name__ == "__main__":
    tests = [v for n, v in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(failed)
