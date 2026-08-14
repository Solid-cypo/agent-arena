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
    CRISPIN,
    DARK_BASIC,
    DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FROSLASS,
    JUDGE,
    LILLIE,
    MEGA_FROSLASS,
    MEGA_STARMIE,
    MEOWTH_EX,
    MUNKIDORI,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    RISKY_RUINS,
    SNORUNT,
    STARYU,
    ULTRA_BALL,
    UNFAIR_STAMP,
    WATER_BASIC,
)
from opponent_roles import OPPONENT_ROLES, opponent_role, role_coverage
from turn_planner import build_turn_plan, discard_value, enumerate_midgame_open_gaps

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
    # Bad single-gap hand may force DRAW, but Staryu remains the acquire target.
    assert plan.objective in ("MAKE_ATTACKER", "DRAW")
    assert plan.gap.need_base
    assert plan.acquire.targets[0] == STARYU


def test_g2_tracks_evolution_energy_and_summoning_wait():
    staryu = _pkm(STARYU, turnPlayed=5)
    plan = _plan(_player(active=staryu, hand=(WATER_BASIC,)), turn=5)
    assert plan.gap.need_evolution and plan.gap.need_energy
    assert plan.two_turn_path == ("WAIT_EVOLVE", "EVOLUTION", "ENERGY")


def test_held_attacker_path_uses_free_search_window_for_dp():
    """Summoning-sick Staryu + held Mega: free DP dig (cannot evolve yet)."""
    staryu = _pkm(STARYU, turnPlayed=5)
    plan = _plan(
        _player(
            active=staryu,
            hand=(MEGA_STARMIE, WATER_BASIC, POFFIN, ULTRA_BALL),
        ),
        turn=5,
    )
    assert not plan.facts.staryu_can_evolve
    assert SNORUNT in plan.acquire.targets
    assert POFFIN in plan.acquire.sources
    assert not plan.acquire.ball_allowed


def test_held_mega_evolvable_skips_snorunt_acquire():
    """Evolvable Staryu + held Mega: evolve this turn — empty acquire targets."""
    staryu = _pkm(STARYU, turnPlayed=3)
    plan = _plan(
        _player(
            active=staryu,
            hand=(MEGA_STARMIE, WATER_BASIC, POFFIN, ULTRA_BALL),
        ),
        turn=5,
    )
    assert plan.facts.staryu_can_evolve
    assert plan.acquire.targets == ()


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

    # Watered base → Mega land gate open. No Lillie → Meowth first, Mega for free dig.
    missing_mega = _plan(
        _player(
            active=_pkm(STARYU, energies=(WATER_BASIC,)),
            hand=(POFFIN, ULTRA_BALL),
        )
    )
    assert missing_mega.acquire.targets[0] == MEOWTH_EX
    assert MEGA_STARMIE in missing_mega.acquire.targets
    assert missing_mega.acquire.ball_allowed

    # Dry base + no water-fetch tools → water then Meowth then Mega (G1: no FROSLASS mix).
    dry_mega = _plan(
        _player(active=_pkm(STARYU), hand=(POFFIN, ULTRA_BALL))
    )
    assert dry_mega.acquire.targets[0] == WATER_BASIC
    assert MEOWTH_EX in dry_mega.acquire.targets
    assert dry_mega.acquire.targets[-1] == MEGA_STARMIE
    assert FROSLASS not in dry_mega.acquire.targets
    assert dry_mega.acquire.ball_allowed


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


def test_held_munkidori_with_field_mega_targets_seat_first():
    """Mega on field + held Munk → seat Munk when Wave-D Meowth dig is closed."""
    # HandQual/OpsOrder Wave D: thin hand digs Meowth first; close that path.
    plan = _plan(
        _player(
            active=_pkm(MEGA_STARMIE),  # no water → not attack_required
            bench=(_pkm(MEOWTH_EX),),
            hand=(MUNKIDORI, WATER_BASIC, POFFIN),
        )
    )
    assert plan.acquire.targets == (MUNKIDORI,)
    assert STARYU not in plan.acquire.targets
    assert SNORUNT not in plan.acquire.targets


def test_field_munk_missing_dark_targets_dark():
    """Munk on field without Dark → fetch Dark once Meowth cycle is closed."""
    plan = _plan(
        _player(
            active=_pkm(MEGA_STARMIE),
            bench=(_pkm(MUNKIDORI), _pkm(MEOWTH_EX)),
            hand=(WATER_BASIC, POFFIN),
        )
    )
    assert plan.acquire.targets == (DARK_BASIC,)


def test_staryu_line_held_munk_targets_munk():
    """Staryu online + Mega held (sick) + water in hand + Munk → seat Munk."""
    staryu = _pkm(STARYU, energies=(WATER_BASIC,), turnPlayed=5)
    plan = _plan(
        _player(
            active=staryu,
            hand=(MUNKIDORI, MEGA_STARMIE, WATER_BASIC, POFFIN),
        ),
        turn=5,
    )
    assert not plan.facts.staryu_can_evolve
    # Mega held → evolution gap not a search target; seat Munk next.
    assert MEGA_STARMIE not in plan.acquire.targets
    assert plan.acquire.targets == (MUNKIDORI,)


def test_staryu_line_held_munk_waits_without_mega():
    """Staryu online + Munk held but Mega not secured → do not seat-target Munk."""
    plan = _plan(
        _player(
            active=_pkm(STARYU, energies=(WATER_BASIC,)),
            hand=(MUNKIDORI, WATER_BASIC, POFFIN),
        )
    )
    assert MUNKIDORI not in plan.acquire.targets


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
    # Wave L: Boss gust prep outranks Adrena-Brain when both are live.
    assert plan.combat.required_before_attack == ("BOSS", "ADRENA")
    assert plan.combat.rider_target.card_id == 901
    assert plan.combat.boss_target.card_id == 902


def test_froslass_two_prize_gate_and_exceptions():
    me = _player(active=_pkm(MEGA_STARMIE))
    two_prize = _player(active=_pkm(900, hp=200, ex=True), hand_count=4)
    one_prize = _player(active=_pkm(900, hp=200), hand_count=4)
    # 2-prize attacker decks build a second Starmie, not 861.
    assert not _plan(me, two_prize).combat.froslass_build_allowed
    assert not _plan(me, one_prize).combat.froslass_build_allowed

    terminal_me = _player(active=_pkm(MEGA_STARMIE), prizes=1)
    assert _plan(terminal_me, one_prize).combat.froslass_build_allowed

    # Wave F: Snorunt alone no longer unlocks BUILD_861 when expected_f < 2.
    unique_line = _player(active=_pkm(104), bench=(_pkm(860),))
    assert not _plan(unique_line, one_prize).combat.froslass_build_allowed

    # Sole attackable Mega is fueled 861 → exception allows build/attack path.
    only_861 = _player(
        active=_pkm(MEGA_FROSLASS, energies=(WATER_BASIC,)),
        prizes=6,
    )
    assert _plan(only_861, one_prize).combat.froslass_build_allowed


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


def test_ub_surplus_dunsparce_discardable_when_line_ge_3():
    plan = _plan(
        _player(
            active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
            bench=(_pkm(DUNSPARCE_A), _pkm(DUNSPARCE_B)),
            hand=(ULTRA_BALL, DUNSPARCE_A, WATER_BASIC),
        )
    )
    assert discard_value(DUNSPARCE_A, plan) <= 30


def test_ub_keeps_scarce_dunsparce_protected():
    plan = _plan(
        _player(
            active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
            hand=(ULTRA_BALL, DUNSPARCE_A, WATER_BASIC),
        )
    )
    assert discard_value(DUNSPARCE_A, plan) >= 100


def test_runaway_v1_cancelled_keeps_f4_hold_on_open_path():
    # RunAway-V1 NO-GO (WR); keep HandQual F4.
    # Dry Mega + only energy gap → structured bad hand may draw.
    dry_mega = _plan(
        _player(
            active=_pkm(MEGA_STARMIE),
            bench=(_pkm(DUDUNSPARCE),),
            hand=(WATER_BASIC,),
        )
    )
    assert dry_mega.draw.allow_run_away_draw

    # Pre-Mega multi-gap open path → HOLD.
    pre_mega = _plan(
        _player(
            active=_pkm(STARYU),
            bench=(_pkm(DUDUNSPARCE),),
            hand=(WATER_BASIC,),
        )
    )
    assert not pre_mega.draw.allow_run_away_draw


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


def test_midgame_open_gaps_parallel_dark_and_placer():
    """Munk dry + no placer → DIG_DARK and PLAY_PLACER both open (parallel set)."""
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        bench=(_pkm(MUNKIDORI),),
        hand=(RISKY_RUINS,),  # placer held — still open until played
    )
    plan = _plan(me)
    assert "DIG_DARK" in plan.midgame_open_gaps
    assert "PLAY_PLACER" in plan.midgame_open_gaps
    # Priority: dark dig before placer.
    assert plan.midgame_open_gaps.index("DIG_DARK") < plan.midgame_open_gaps.index(
        "PLAY_PLACER"
    )


def test_midgame_open_gaps_dig_munk_when_missing():
    """Post-Mega no Munk in hand/field → DIG_MUNK (not PLAY_MUNK)."""
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(POKE_PAD,),
    )
    plan = _plan(me)
    assert "DIG_MUNK" in plan.midgame_open_gaps
    assert "PLAY_MUNK" not in plan.midgame_open_gaps
    assert plan.midgame_open_gaps.index("DIG_MUNK") < plan.midgame_open_gaps.index(
        "PLAY_PLACER"
    ) if "PLAY_PLACER" in plan.midgame_open_gaps else True


def test_midgame_open_gaps_play_munk_when_held():
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(MUNKIDORI,),
    )
    plan = _plan(me)
    assert "PLAY_MUNK" in plan.midgame_open_gaps
    assert "DIG_MUNK" not in plan.midgame_open_gaps


def test_acquire_pad_source_for_munk_target():
    """Pad is a legal free search when acquire targets Munk."""
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        bench=(_pkm(MEOWTH_EX),),  # Meowth online so acquire can chase Munk
        hand=(POKE_PAD, LILLIE),
    )
    plan = _plan(me)
    if MUNKIDORI in plan.acquire.targets:
        assert POKE_PAD in plan.acquire.sources


def test_midgame_open_gaps_empty_pre_mega():
    me = _player(active=_pkm(STARYU), hand=(MUNKIDORI, RISKY_RUINS))
    plan = _plan(me, turn=2)
    assert plan.midgame_open_gaps == ()


def test_sick_staryu_never_ball_digs_mega():
    """Autopsy 92356962: appearThisTurn bases → dig Meowth, never Mega."""
    me = _player(
        active=_pkm(STARYU, appearThisTurn=True),
        bench=(_pkm(STARYU, appearThisTurn=True),),
        hand=(CRISPIN, ULTRA_BALL, UNFAIR_STAMP, DUNSPARCE_A),
    )
    plan = _plan(me, turn=3)
    assert not plan.facts.staryu_can_evolve
    assert MEGA_STARMIE not in plan.acquire.targets
    assert MEOWTH_EX in plan.acquire.targets
    assert plan.acquire.ball_allowed
    assert discard_value(CRISPIN, plan) >= 9_500


def test_sick_staryu_ub_blocked_when_would_burn_crispin():
    """Episode hand shape: Crispin+UB+Stamp — Ball would force-burn Crispin."""
    me = _player(
        active=_pkm(STARYU, appearThisTurn=True),
        bench=(_pkm(STARYU, appearThisTurn=True),),
        hand=(CRISPIN, ULTRA_BALL, UNFAIR_STAMP),
    )
    plan = _plan(me, turn=3)
    assert MEGA_STARMIE not in plan.acquire.targets
    assert not plan.acquire.ball_allowed
    assert "Crispin" in plan.acquire.ball_reason or "forced-burn" in plan.acquire.ball_reason


def test_ub_mega_when_lillie_supporter_free_and_landable():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(LILLIE, ULTRA_BALL, UNFAIR_STAMP, DUNSPARCE_A),
    )
    plan = _plan(me, turn=5)
    assert plan.facts.staryu_can_evolve
    assert plan.acquire.targets == (MEGA_STARMIE,)
    assert plan.acquire.ball_allowed
    assert "Lillie+landable" in plan.acquire.ball_reason
    assert discard_value(LILLIE, plan) >= 10_000


def test_ub_never_discards_lillie_value():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(LILLIE, ULTRA_BALL, JUDGE),
    )
    plan = _plan(me)
    assert discard_value(LILLIE, plan) >= 10_000


def test_three_prize_opens_861_at_full_starmie_hp():
    """Fueled Mega Starmie vs Mega attacker → build Froslass immediately."""
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=330, max_hp=330, energies=(WATER_BASIC,)),
        hand=(SNORUNT, MEGA_FROSLASS),
    )
    opp = _player(active=_pkm(MEGA_STARMIE, hp=330, max_hp=330, megaEx=True), hand_count=3)
    plan = _plan(me, opp)
    assert plan.facts.opp_attacker_prizes >= 3
    assert plan.facts.starmie_attacker_ready
    assert plan.gap.need_second_attacker
    assert not plan.gap.need_second_starmie
    assert plan.combat.froslass_build_allowed


def test_two_prize_wants_second_starmie_not_861():
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=330, max_hp=330, energies=(WATER_BASIC,)),
        hand=(STARYU, SNORUNT, MEGA_FROSLASS),
    )
    opp = _player(active=_pkm(121, hp=300, ex=True), hand_count=4)
    plan = _plan(me, opp)
    assert plan.facts.opp_attacker_prizes == 2
    assert plan.gap.need_second_starmie
    assert not plan.gap.need_second_attacker
    assert not plan.combat.froslass_build_allowed
    assert "PLAY_STARYU" in plan.midgame_open_gaps


def test_adrena_prefers_bench_combo_when_jetting_already_kos_active():
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=300, max_hp=330, energies=(WATER_BASIC,)),
        bench=(_pkm(MUNKIDORI, energies=(DARK_BASIC,)),),
    )
    opp = _player(
        active=_pkm(900, hp=100),
        bench=(_pkm(119, hp=70),),  # Dreepy: 50+20 KO
        hand_count=3,
    )
    plan = _plan(me, opp)
    assert plan.combat.rider_target is not None
    assert plan.combat.rider_target.hp == 70
    assert plan.combat.adrena_target is not None
    assert plan.combat.adrena_target.area == "BENCH"
    assert plan.combat.adrena_target.hp == 70


def test_adrena_on_active_only_when_it_enables_attacker_ko():
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=300, max_hp=330, energies=(WATER_BASIC,)),
        bench=(_pkm(MUNKIDORI, energies=(DARK_BASIC,)),),
    )
    opp = _player(
        active=_pkm(900, hp=140),  # 120+20 KO, Jetting alone lives
        bench=(_pkm(119, hp=70),),
        hand_count=3,
    )
    plan = _plan(me, opp)
    assert plan.combat.adrena_target is not None
    assert plan.combat.adrena_target.area == "ACTIVE"
    assert plan.combat.rider_target is not None
    assert plan.combat.rider_target.area == "BENCH"


def test_froslass_boss_grabs_full_hp_second_attacker():
    """861 Active: Resentful 350 KOs bench Mega Lucario 340; front is a 1-prize wall."""
    me = _player(
        active=_pkm(MEGA_FROSLASS, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS,),
        prizes=5,
    )
    lucario = _pkm(678, hp=340, max_hp=340)  # Mega Lucario, 3 prizes
    opp = _player(
        active=_pkm(235, hp=60),  # Budew wall, 1 prize, also KO-able
        bench=(lucario,),
        hand_count=7,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "FROSLASS_ATTACK"
    assert plan.combat.boss_target is not None
    assert plan.combat.boss_target.card_id == 678
    assert plan.combat.expected_prize_delta >= 2
    assert "BOSS" in plan.combat.required_before_attack
    assert plan.combat.next_action == "BOSS"


def test_froslass_no_boss_when_front_already_best_prize():
    """Front Mega Lucario already Resentful-KO — do not spend Boss on equal/worse bench."""
    me = _player(
        active=_pkm(MEGA_FROSLASS, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS,),
        prizes=5,
    )
    opp = _player(
        active=_pkm(678, hp=340, max_hp=340),
        bench=(_pkm(1071, hp=190, ex=True),),  # Meowth ex, 2 prizes
        hand_count=7,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode == "FROSLASS_ATTACK"
    assert plan.combat.boss_target is None
    assert "BOSS" not in plan.combat.required_before_attack
    assert plan.combat.next_action == "ATTACK"


def test_starmie_still_ignores_fat_lucario_for_boss():
    """Boss→Jetting freeze: Starmie must not gust a 340 HP Mega Lucario."""
    me = _player(
        active=_pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        hand=(BOSS_ORDERS,),
        prizes=5,
    )
    opp = _player(
        active=_pkm(235, hp=60),
        bench=(_pkm(678, hp=340, max_hp=340),),
        hand_count=7,
    )
    plan = _plan(me, opp)
    assert plan.combat.mode != "FROSLASS_ATTACK"
    if plan.combat.boss_target is not None:
        assert plan.combat.boss_target.card_id != 678
        assert plan.combat.boss_target.hp <= 120


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
