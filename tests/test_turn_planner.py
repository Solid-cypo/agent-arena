"""Focused behavior tests for the immutable per-decision TurnPlan."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agent/skills/piloting_starmie_froslass/scripts"
for path in (str(ROOT), str(SKILL)):
    if path not in sys.path:
        sys.path.insert(0, path)

from hand_snapshot import build_board_snapshot
from opening_cards import (
    BOSS_ORDERS,
    BUDEW,
    DARK_BASIC,
    DUDUNSPARCE,
    DUNSPARCE_A,
    FROSLASS,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    MUNKIDORI,
    NIGHT_STRETCHER,
    POFFIN,
    RISKY_RUINS,
    SNORUNT,
    STARYU,
    ULTRA_BALL,
    WATER_BASIC,
)
from opponent_roles import OPPONENT_ROLES, opponent_role, role_coverage
from turn_planner import build_turn_plan, discard_value

# Main attacker bases for the five combat-eval decks.
ABRA, DREEPY, RIOLU, IMPIDIMP, SPHEAL = 741, 119, 677, 646, 941
SHAYMIN, DUSKULL, MAKUHITA = 343, 131, 673


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
        hand=[NS(id=cid) if isinstance(cid, int) else cid for cid in hand],
        discard=[NS(id=cid) if isinstance(cid, int) else cid for cid in discard],
        prize=[None] * prizes,
        prizeCount=prizes,
        handCount=len(hand) if hand_count is None else hand_count,
        supporterPlayed=False,
        energyAttached=False,
    )


def _plan(me, opp=None, turn=5, stadium=(), matchup=None):
    opp = opp or _player(active=_pkm(999, hp=200), hand_count=4)
    obs = NS(
        current=NS(
            turn=turn,
            yourIndex=0,
            firstPlayer=0,
            stadium=[NS(id=cid) for cid in stadium],
            players=[me, opp],
        )
    )
    return build_turn_plan(obs, build_board_snapshot(obs), matchup=matchup)


def test_g1_missing_base_targets_staryu():
    plan = _plan(_player(active=_pkm(DUNSPARCE_A)))
    assert plan.objective == "MAKE_ATTACKER"
    assert plan.gap.need_base
    assert plan.acquire.targets[0] == STARYU


def test_g2_tracks_evolution_energy_and_summoning_wait():
    staryu = _pkm(STARYU, turnPlayed=5)
    plan = _plan(_player(active=staryu, hand=(WATER_BASIC,)), turn=5)
    assert plan.gap.need_evolution and plan.gap.need_energy
    assert plan.two_turn_path == ("WAIT_EVOLVE", "EVOLUTION", "ENERGY")


def test_held_attacker_path_uses_free_search_window_for_dp():
    staryu = _pkm(STARYU, turnPlayed=3)
    plan = _plan(
        _player(
            active=staryu,
            hand=(MEGA_STARMIE, WATER_BASIC, POFFIN, ULTRA_BALL),
        ),
        turn=5,
    )
    assert SNORUNT in plan.acquire.targets
    assert POFFIN in plan.acquire.sources
    assert not plan.acquire.ball_allowed


def test_dp_goal_accepts_risky_ruins_as_damage_placer():
    plan = _plan(
        _player(
            active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
            bench=(_pkm(MUNKIDORI, energies=(DARK_BASIC,)),),
        ),
        stadium=(RISKY_RUINS,),
    )
    assert plan.facts.damage_placer_online
    assert plan.gap.dp_gaps == ()


def test_damage_placer_gap_skips_held_risky_ruins():
    """Held Risky Ruins already covers the damage-placer gap — do not dig Snorunt."""
    plan = _plan(
        _player(
            active=_pkm(STARYU),
            bench=(_pkm(MUNKIDORI, energies=(DARK_BASIC,)),),
            hand=(MEGA_STARMIE, WATER_BASIC, RISKY_RUINS),
        )
    )
    assert SNORUNT not in plan.acquire.targets
    assert RISKY_RUINS not in plan.acquire.targets


def test_ready_active_mega_must_attack():
    plan = _plan(
        _player(
            active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
            hand=(ULTRA_BALL,),
        )
    )
    assert plan.objective == "ATTACK"
    assert plan.combat.attack_required
    assert "END" in plan.forbidden_actions
    assert plan.acquire.targets == ()
    assert not plan.acquire.ball_allowed


def test_ready_mega_allows_immediate_dp_prep_before_attack():
    plan = _plan(
        _player(
            active=_pkm(
                MEGA_STARMIE,
                hp=300,
                max_hp=330,
                energies=(WATER_BASIC,),
            ),
            bench=(
                _pkm(SNORUNT, turnPlayed=1),
                _pkm(MUNKIDORI),
            ),
            hand=(FROSLASS, DARK_BASIC),
        ),
        turn=5,
    )
    assert plan.combat.required_before_attack[:2] == (
        "EVOLVE_104",
        "ATTACH_DARK",
    )


def test_ready_bench_mega_requires_dispatch():
    me = _player(
        active=_pkm(DUNSPARCE_A),
        bench=(_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),),
    )
    plan = _plan(me)
    assert plan.objective == "MAKE_ATTACKER"
    assert plan.combat.required_before_attack[-1] == "DISPATCH"


def test_bench_mega_without_dispatch_out_is_not_false_mandatory_attack():
    me = _player(
        active=_pkm(MUNKIDORI),
        bench=(_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),),
    )
    plan = _plan(me)
    assert not plan.facts.can_dispatch_bench_mega
    assert not plan.combat.attack_required


def test_ub3_free_search_only_blocks_when_it_closes_gap():
    missing_base = _plan(
        _player(active=_pkm(DUNSPARCE_A), hand=(POFFIN, ULTRA_BALL))
    )
    assert not missing_base.acquire.ball_allowed
    assert "UB-3" in missing_base.acquire.ball_reason

    missing_mega = _plan(
        _player(active=_pkm(STARYU), hand=(POFFIN, ULTRA_BALL))
    )
    assert missing_mega.acquire.targets[0] == MEGA_STARMIE
    assert missing_mega.acquire.ball_allowed


def test_dynamic_discard_protects_path_and_releases_dead_poffin():
    me = _player(
        active=_pkm(STARYU),
        hand=(MEGA_STARMIE, POFFIN, ULTRA_BALL),
    )
    plan = _plan(me)
    assert discard_value(MEGA_STARMIE, plan) >= 10_000
    assert discard_value(POFFIN, plan) <= 30


def test_night_stretcher_recovers_unique_energy_gap():
    me = _player(
        active=_pkm(MEGA_STARMIE),
        hand=(NIGHT_STRETCHER,),
        discard=(WATER_BASIC,),
    )
    plan = _plan(me)
    assert plan.acquire.recover_target == WATER_BASIC
    assert NIGHT_STRETCHER in plan.acquire.sources


def test_double_ko_50_rider_without_boss():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(
        active=_pkm(900, hp=120),
        bench=(_pkm(901, hp=50),),
        hand_count=3,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "DOUBLE_KO"
    assert plan.combat.rider_target.card_id == 901
    assert plan.combat.boss_target is None


def test_ineffective_boss_not_forced_when_prize_delta_zero():
    """Active already KO-able for equal prizes — do not spend the supporter slot."""
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS,),
    )
    opp = _player(
        active=_pkm(900, hp=100, ex=True),  # 2 prizes, KO-able
        bench=(_pkm(901, hp=110, ex=True),),  # also 2 prizes
        hand_count=3,
    )
    plan = _plan(me, opp)
    assert plan.combat.expected_prize_delta == 0
    assert plan.combat.boss_target is None
    assert "BOSS" not in plan.combat.required_before_attack


def test_effective_boss_forced_when_prize_delta_positive():
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS,),
    )
    opp = _player(
        active=_pkm(900, hp=100),  # 1 prize
        bench=(_pkm(901, hp=110, ex=True),),  # 2 prizes
        hand_count=3,
    )
    plan = _plan(me, opp)
    assert plan.combat.expected_prize_delta > 0
    assert plan.combat.boss_target is not None
    assert plan.combat.boss_target.card_id == 901
    assert "BOSS" in plan.combat.required_before_attack


def test_held_dudunsparce_poffin_targets_staryu_and_dunsparce():
    plan = _plan(
        _player(
            active=_pkm(BUDEW),
            hand=(DUDUNSPARCE, POFFIN),
        )
    )
    assert plan.gap.need_base
    assert plan.acquire.targets[:2] == (STARYU, DUNSPARCE_A)


def test_held_munkidori_with_field_mega_targets_dark_not_basics():
    """Mega on field (attacker line online) + held Munk → fetch Dark, not basics."""
    plan = _plan(
        _player(
            active=_pkm(MEGA_STARMIE),  # no water → not attack_required
            hand=(MUNKIDORI, WATER_BASIC, POFFIN),
        )
    )
    assert plan.acquire.targets == (DARK_BASIC,)
    assert STARYU not in plan.acquire.targets
    assert SNORUNT not in plan.acquire.targets


def test_double_ko_80_orders_adrena_then_boss_and_preserves_rider():
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=300, max_hp=330, energies=(WATER_BASIC,)),
        bench=(_pkm(MUNKIDORI, energies=(DARK_BASIC,)),),
        hand=(BOSS_ORDERS,),
    )
    opp = _player(
        active=_pkm(900, hp=200),
        bench=(_pkm(901, hp=80), _pkm(902, hp=110, ex=True)),
        hand_count=4,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "DOUBLE_KO"
    assert plan.combat.required_before_attack == ("ADRENA", "BOSS")
    assert plan.combat.rider_target.card_id == 901
    assert plan.combat.boss_target.card_id == 902


def test_froslass_two_prize_gate_and_exceptions():
    me = _player(active=_pkm(MEGA_STARMIE))
    two_prize = _player(active=_pkm(900, hp=200, ex=True), hand_count=4)
    one_prize = _player(active=_pkm(900, hp=200), hand_count=4)
    assert _plan(me, two_prize).combat.froslass_build_allowed
    assert not _plan(me, one_prize).combat.froslass_build_allowed

    terminal_me = _player(active=_pkm(MEGA_STARMIE), prizes=1)
    assert _plan(terminal_me, one_prize).combat.froslass_build_allowed

    unique_line = _player(active=_pkm(104), bench=(_pkm(860),))
    assert _plan(unique_line, one_prize).combat.froslass_build_allowed


def test_dunsparce_budget_and_bad_hand_draw_gate():
    no_main = _plan(
        _player(active=_pkm(DUNSPARCE_A), bench=(_pkm(MUNKIDORI),))
    )
    assert not no_main.draw.allow_first_dunsparce

    good_hand = _plan(
        _player(
            active=_pkm(STARYU),
            bench=(_pkm(MUNKIDORI), _pkm(FROSLASS), _pkm(DUDUNSPARCE)),
            hand=(MEGA_STARMIE, WATER_BASIC),
        )
    )
    assert not good_hand.draw.allow_run_away_draw


def test_five_deck_main_bases_are_registered():
    for cid in (ABRA, DREEPY, RIOLU, IMPIDIMP, SPHEAL):
        profile = opponent_role(cid)
        assert profile.known
        assert profile.role == "MAIN_ATTACKER_BASE"
        assert profile.rider_priority == 100
    assert role_coverage((ABRA, DREEPY, RIOLU, IMPIDIMP, SPHEAL, 999)) == 5 / 6
    assert not opponent_role(999).known
    assert len(OPPONENT_ROLES) >= 20


def test_same_hp_rider_prefers_main_attacker_base():
    # 80HP window needs transferable damage + Munk dark; prefer Dreepy over
    # Duskull/Budew even when those are also knockable.
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=300, max_hp=330, energies=(WATER_BASIC,)),
        bench=(_pkm(MUNKIDORI, energies=(DARK_BASIC,)),),
    )
    opp = _player(
        active=_pkm(900, hp=120),
        bench=(
            _pkm(DUSKULL, hp=60),   # engine base
            _pkm(DREEPY, hp=70),    # main attacker base
            _pkm(235, hp=30),       # Budew utility
        ),
        hand_count=3,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "DOUBLE_KO"
    assert plan.combat.rider_target.card_id == DREEPY
    assert plan.combat.rider_target.role == "MAIN_ATTACKER_BASE"


def test_boss_must_not_equal_rider_and_prefers_high_prize():
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=300, max_hp=330, energies=(WATER_BASIC,)),
        bench=(_pkm(MUNKIDORI, energies=(DARK_BASIC,)),),
        hand=(BOSS_ORDERS,),
    )
    opp = _player(
        active=_pkm(900, hp=200),
        bench=(
            _pkm(RIOLU, hp=80),
            _pkm(MAKUHITA, hp=80),
            _pkm(121, hp=110, ex=True),  # Dragapult ex as KO-able prize
        ),
        hand_count=4,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "DOUBLE_KO"
    assert plan.combat.rider_target.card_id == RIOLU
    assert plan.combat.boss_target is not None
    assert plan.combat.boss_target.card_id != plan.combat.rider_target.card_id
    assert plan.combat.boss_target.card_id == 121


def test_shaymin_flower_curtain_blocks_non_rulebox_rider():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(
        active=_pkm(900, hp=120),
        bench=(
            _pkm(SHAYMIN, hp=80),
            _pkm(ABRA, hp=50),
            _pkm(140, hp=50, ex=True),  # Fezandipiti ex — Rule Box, not protected
        ),
        hand_count=3,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "DOUBLE_KO"
    assert plan.combat.rider_target.card_id == 140
    assert plan.combat.rider_target.attack_protected is False
    abra = next(t for t in plan.facts.opp_bench if t.card_id == ABRA)
    assert abra.attack_protected


def test_unknown_card_falls_back_without_crashing_double_ko():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(
        active=_pkm(900, hp=120),
        bench=(_pkm(9999, hp=40),),
        hand_count=2,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "DOUBLE_KO"
    assert plan.combat.rider_target.card_id == 9999
    assert plan.combat.rider_target.role == "UNKNOWN"
    assert not plan.combat.rider_target.known_role


def test_alakazam_matchup_boosts_abra_rider_priority():
    me = _player(active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)))
    opp = _player(
        active=_pkm(900, hp=120),
        bench=(_pkm(ABRA, hp=50), _pkm(DUSKULL, hp=50)),
        hand_count=3,
    )
    base = _plan(me, opp)
    boosted = _plan(me, opp, matchup="alakazam")
    assert base.combat.rider_target.card_id == ABRA
    assert boosted.combat.rider_target.card_id == ABRA
    assert (
        boosted.combat.rider_target.rider_priority
        > base.combat.rider_target.rider_priority
    )


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
