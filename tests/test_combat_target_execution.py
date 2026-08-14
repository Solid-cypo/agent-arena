"""Execution-layer tests: TurnPlan rider/boss targets beat legacy selectors."""
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

RIOLU, MAKUHITA, DREEPY = 677, 673, 119
WATER = int(EnergyType.WATER)
DARK = int(EnergyType.DARKNESS)


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


def _obs(me, opp, *, ctx, turn=5):
    return NS(
        current=NS(
            turn=turn,
            yourIndex=0,
            firstPlayer=0,
            stadium=[],
            players=[me, opp],
        ),
        select=NS(context=int(ctx), deck=[], option=[]),
    )


def test_rider_damage_select_matches_plan_not_lowest_hp():
    """Legacy DAMAGE scoring prefers HP<=50; 80HP Riolu must still win via plan."""
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], hp=300, max_hp=330, energies=(WATER,)),
        bench=(_pkm(sp._CARDS["munkidori"], energies=(DARK,)),),
        hand=(sp._CARDS["boss_orders"],),
    )
    opp = _player(
        active=_pkm(900, hp=200),
        bench=(
            _pkm(235, hp=30),     # Budew — legacy would prefer this
            _pkm(RIOLU, hp=80),   # plan rider
            _pkm(121, hp=110, ex=True),
        ),
        hand_count=4,
    )
    obs = _obs(me, opp, ctx=SelectContext.DAMAGE)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.mode == "DOUBLE_KO"
    assert sit["turn_plan"].combat.rider_target.card_id == RIOLU

    budew = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1)
    riolu = NS(type=OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1)
    assert sp._hard_rule_bonus(obs, riolu, sit) > sp._hard_rule_bonus(obs, budew, sit)
    assert sp._hard_rule_bonus(obs, riolu, sit) >= sp._DOMINATE
    assert sp._hard_rule_bonus(obs, budew, sit) <= -sp._DOMINATE


def test_boss_card_select_matches_plan_and_rejects_rider():
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], hp=300, max_hp=330, energies=(WATER,)),
        bench=(_pkm(sp._CARDS["munkidori"], energies=(DARK,)),),
        hand=(sp._CARDS["boss_orders"],),
    )
    opp = _player(
        active=_pkm(900, hp=200),
        bench=(
            _pkm(RIOLU, hp=80),
            _pkm(121, hp=110, ex=True),
        ),
        hand_count=4,
    )
    obs = _obs(me, opp, ctx=SelectContext.TO_ACTIVE)
    sit = sp._compute_situation(obs)
    plan = sit["turn_plan"]
    assert plan.combat.boss_target is not None
    assert plan.combat.boss_target.card_id == 121
    assert plan.combat.rider_target.card_id == RIOLU

    rider_opt = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1)
    boss_opt = NS(type=OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1)
    assert sp._hard_rule_bonus(obs, boss_opt, sit) >= sp._DOMINATE
    assert sp._hard_rule_bonus(obs, rider_opt, sit) <= -sp._DOMINATE


def test_boss_gust_after_play_keeps_110_not_10hp_rider():
    """92530813: after PLAY Boss, nested SWITCH must not grab the 10 HP rider."""
    me = _player(
        active=_pkm(
            sp._CARDS["mega_starmie_ex"], hp=60, max_hp=330, energies=(WATER,)
        ),
        prizes=5,
    )
    me.supporterPlayed = True
    lucario = _pkm(678, hp=420, max_hp=440)
    lucario.megaEx = True
    opp = _player(
        active=lucario,
        bench=(
            _pkm(675, hp=110),  # Lunatone
            _pkm(RIOLU, hp=10),  # rider — keep on bench
            _pkm(676, hp=110),  # Solrock — gust
        ),
        hand_count=5,
    )
    obs = _obs(me, opp, ctx=SelectContext.SWITCH)
    sit = sp._compute_situation(obs)
    combat = sit["turn_plan"].combat
    assert combat.mode == "DOUBLE_KO"
    assert combat.rider_target.card_id == RIOLU
    assert combat.boss_target is not None
    assert combat.boss_target.card_id == 676
    assert "BOSS" not in combat.required_before_attack

    lun0 = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1)
    rider = NS(type=OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1)
    sol = NS(type=OptionType.CARD, area=AreaType.BENCH, index=2, playerIndex=1)
    assert sp._hard_rule_bonus(obs, rider, sit) <= -sp._DOMINATE
    assert sp._hard_rule_bonus(obs, sol, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, sol, sit) > sp._hard_rule_bonus(obs, lun0, sit)


def test_adrena_select_also_uses_rider_target():
    me = _player(
        active=_pkm(
            sp._CARDS["mega_starmie_ex"],
            hp=300,
            max_hp=330,
            energies=(WATER,),
        ),
        bench=(_pkm(sp._CARDS["munkidori"], energies=(DARK,)),),
        hand=(sp._CARDS["boss_orders"],),
    )
    opp = _player(
        active=_pkm(900, hp=200),
        bench=(_pkm(DREEPY, hp=70), _pkm(121, hp=100, ex=True)),
        hand_count=3,
    )
    obs = _obs(me, opp, ctx=SelectContext.DAMAGE_COUNTER)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.rider_target.card_id == DREEPY
    rider = NS(type=OptionType.CARD, area=AreaType.BENCH, index=0, playerIndex=1)
    other = NS(type=OptionType.CARD, area=AreaType.BENCH, index=1, playerIndex=1)
    assert sp._hard_rule_bonus(obs, rider, sit) > sp._hard_rule_bonus(obs, other, sit)


def test_front_le120_skips_boss_play():
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], energies=(WATER,)),
        hand=(sp._CARDS["boss_orders"],),
    )
    opp = _player(
        active=_pkm(900, hp=100),
        bench=(_pkm(RIOLU, hp=50),),
        hand_count=2,
    )
    obs = _obs(me, opp, ctx=SelectContext.TO_ACTIVE)
    sit = sp._compute_situation(obs)
    assert sit["turn_plan"].combat.mode == "DOUBLE_KO"
    assert sit["turn_plan"].combat.boss_target is None
    assert "BOSS" not in sit["turn_plan"].combat.required_before_attack
    boss_play = NS(type=OptionType.PLAY, index=0)
    # TurnPlan does not force Boss; attack remains required.
    assert sit["turn_plan"].combat.attack_required
    # Playing Boss is not a required_before_attack step.
    bonus = sp._hard_rule_bonus(obs, boss_play, sit)
    assert bonus < sp._DOMINATE_OPEN_PATH


def test_ineffective_boss_play_not_forced_by_turn_plan():
    """Equal-prize KO-able Active: TurnPlan must not force an ineffective Boss."""
    me = _player(
        active=_pkm(sp._CARDS["mega_starmie_ex"], energies=(WATER,)),
        hand=(sp._CARDS["boss_orders"],),
    )
    opp = _player(
        active=_pkm(900, hp=100, ex=True),
        bench=(_pkm(901, hp=110, ex=True),),
        hand_count=3,
    )
    obs = _obs(me, opp, ctx=SelectContext.TO_ACTIVE)
    sit = sp._compute_situation(obs)
    plan = sit["turn_plan"]
    assert plan.combat.expected_prize_delta == 0
    assert "BOSS" not in plan.combat.required_before_attack
    boss_play = NS(type=OptionType.PLAY, index=0)
    assert sp._hard_rule_bonus(obs, boss_play, sit) < sp._DOMINATE_OPEN_PATH


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
