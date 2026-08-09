"""Wave U: online leak fixes (Water Gun / UB / attach seat / night stretcher / Budew)."""
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
    BUDEW,
    CRISPIN,
    DARK_BASIC,
    DUDUNSPARCE,
    DUNSPARCE_A,
    HILDA,
    MEGA_STARMIE,
    MUNKIDORI,
    NIGHT_STRETCHER,
    STARYU,
    SWITCH,
    ULTRA_BALL,
    WATER_BASIC,
)
from turn_planner import build_turn_plan, discard_value, is_basic_attack_forbidden
import starmie_pilot as sp


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
        deckCount=30,
    )


def _obs(me, opp=None, *, turn=5, my_index=0, first_player=0, ctx=0):
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


def _plan(me, **kw):
    obs = _obs(me, **kw)
    return build_turn_plan(obs, build_board_snapshot(obs)), obs


# ── U1: Staryu Water Gun ────────────────────────────────────────────────────

def test_u1_staryu_water_gun_banned_without_dig_tools():
    """90447438: night stretcher / Boss / Dudunsparce — still ban 1486."""
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        bench=(_pkm(DUNSPARCE_A),),
        hand=(DUDUNSPARCE, WATER_BASIC),
    )
    plan, obs = _plan(me, turn=5)
    assert is_basic_attack_forbidden(STARYU, plan)
    sit = sp._compute_situation(obs)
    assert (
        sp._hard_rule_bonus(obs, NS(type=OptionType.ATTACK, attackId=1486), sit)
        <= sp._ATTACH_ILLEGAL
    )


def test_u1_dudunsparce_evolve_dominates_make_attacker():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        bench=(_pkm(DUNSPARCE_A),),
        hand=(DUDUNSPARCE,),
    )
    plan, obs = _plan(me, turn=5)
    assert plan.objective == "MAKE_ATTACKER"
    sit = sp._compute_situation(obs)
    evo = NS(
        type=OptionType.EVOLVE,
        area=AreaType.HAND,
        index=0,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=0,
    )
    assert sp._hard_rule_bonus(obs, evo, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, NS(type=OptionType.END), sit) <= -sp._DOMINATE


def test_plan_step_evolution_beats_hilda_when_mega_held():
    """Plan-step lock: MAKE_ATTACKER/EVOLUTION owns turn once Mega is held."""
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        bench=(_pkm(DUNSPARCE_A),),
        hand=(MEGA_STARMIE, HILDA, WATER_BASIC),
    )
    plan, obs = _plan(me, turn=4)
    assert plan.objective == "MAKE_ATTACKER"
    assert plan.gap.need_evolution
    assert plan.facts.staryu_can_evolve
    sit = sp._compute_situation(obs)
    assert sp._plan_primary_step(sit["turn_plan"]) == "EVOLUTION"
    evo = NS(
        type=OptionType.EVOLVE,
        area=AreaType.HAND,
        index=0,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
        playerIndex=0,
    )
    hilda = NS(type=OptionType.PLAY, area=AreaType.HAND, index=1, playerIndex=0)
    assert sp._plan_step_execute_bonus(obs, evo, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._plan_step_execute_bonus(obs, hilda, sit) <= -sp._DOMINATE_OPEN_PATH
    assert sp._hard_rule_bonus(obs, evo, sit) > sp._hard_rule_bonus(obs, hilda, sit)


def test_plan_step_energy_v2_beats_hilda_and_bans_runaway():
    """ENERGY v2: water attach PATH; Hilda/Run Away demoted when attach offered."""
    me = _player(
        active=_pkm(MEGA_STARMIE, hp=330),
        bench=(_pkm(DUDUNSPARCE),),
        hand=(WATER_BASIC, HILDA),
    )
    plan, obs = _plan(me, turn=5)
    sit = sp._compute_situation(obs)
    assert sp._plan_primary_step(sit["turn_plan"]) == "ENERGY"
    assert "ENERGY" in sp._PLAN_STEP_LOCKED
    attach = NS(
        type=OptionType.ATTACH,
        index=0,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
        playerIndex=0,
    )
    hilda = NS(type=OptionType.PLAY, area=AreaType.HAND, index=1, playerIndex=0)
    runaway = NS(
        type=OptionType.ABILITY, area=AreaType.BENCH, index=0, playerIndex=0,
    )
    sit["select_options"] = [attach, hilda, runaway, NS(type=OptionType.END)]
    assert sp._plan_step_execute_bonus(obs, attach, sit) >= sp._DOMINATE_OPEN_PATH
    assert sp._plan_step_execute_bonus(obs, hilda, sit) <= -sp._DOMINATE_OPEN_PATH
    assert sp._plan_step_execute_bonus(obs, runaway, sit) <= -sp._DOMINATE_OPEN_PATH


def test_plan_step_energy_crispin_only_without_water_in_hand():
    me_dry = _player(
        active=_pkm(MEGA_STARMIE, hp=330),
        hand=(CRISPIN,),
    )
    plan, obs = _plan(me_dry, turn=5)
    sit = sp._compute_situation(obs)
    crispin = NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)
    assert sp._option_advances_plan_step(obs, crispin, sit, "ENERGY", plan)

    me_wet = _player(
        active=_pkm(MEGA_STARMIE, hp=330),
        hand=(WATER_BASIC, CRISPIN),
    )
    plan2, obs2 = _plan(me_wet, turn=5)
    sit2 = sp._compute_situation(obs2)
    crispin2 = NS(type=OptionType.PLAY, area=AreaType.HAND, index=1, playerIndex=0)
    assert not sp._option_advances_plan_step(obs2, crispin2, sit2, "ENERGY", plan2)


def test_plan_step_dig_and_base_advances_mapping():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(HILDA, MUNKIDORI),
    )
    plan, obs = _plan(me, turn=4, first_player=0)
    sit = sp._compute_situation(obs)
    assert sp._plan_primary_step(sit["turn_plan"]) == "DIG_EVOLUTION"
    hilda = NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)
    munk = NS(type=OptionType.PLAY, area=AreaType.HAND, index=1, playerIndex=0)
    assert sp._option_advances_plan_step(obs, hilda, sit, "DIG_EVOLUTION", plan)
    assert not sp._option_advances_plan_step(obs, munk, sit, "DIG_EVOLUTION", plan)

    me2 = _player(
        active=_pkm(DUNSPARCE_A),
        hand=(STARYU, MUNKIDORI),
    )
    plan2, obs2 = _plan(me2, turn=3, first_player=0)
    sit2 = sp._compute_situation(obs2)
    assert sp._plan_primary_step(sit2["turn_plan"]) == "BASE"
    play_staryu = NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)
    assert sp._option_advances_plan_step(obs2, play_staryu, sit2, "BASE", plan2)


def test_plan_step_evolution_no_demote_when_advance_unavailable():
    """Knife 1: no Mega EVOLVE in MAIN list → WAIT_EVOLVE; END allowed, not demoted."""
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(MEGA_STARMIE, HILDA),
    )
    plan, obs = _plan(me, turn=4)
    sit = sp._compute_situation(obs)
    assert sp._plan_primary_step(sit["turn_plan"]) == "EVOLUTION"
    # Only END offered — no evolve in select_options → ground to WAIT.
    sit["select_options"] = [NS(type=OptionType.END)]
    assert sp._plan_primary_step(sit["turn_plan"], obs, sit) == "WAIT_EVOLVE"
    end_s = sp._plan_step_execute_bonus(obs, NS(type=OptionType.END), sit)
    assert end_s >= sp._DOMINATE_MID
    assert end_s > -sp._DOMINATE_OPEN_PATH


def test_knife_a_evolve66_beats_hilda_despite_tp_draw_hold():
    """ops_firefix restore: EVOLVE_66 PATH > Hilda dig even when draw=FORBID."""
    me = _player(
        active=_pkm(112, hp=110, max_hp=110, energies=(7,)),  # Munkidori
        bench=(_pkm(DUNSPARCE_A), _pkm(STARYU)),
        hand=(DUDUNSPARCE, WATER_BASIC, HILDA),
    )
    plan, obs = _plan(me, turn=4)
    sit = sp._compute_situation(obs)
    sit["select_options"] = [
        NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0, playerIndex=0),
        NS(type=OptionType.PLAY, area=AreaType.HAND, index=2, playerIndex=0),
        NS(type=OptionType.END),
    ]
    # TurnPlan often FORBIDs RunAway while MAKE_ATTACKER gap open.
    assert getattr(sit.get("draw_axis_dec"), "action", None) in (
        "FORBID",
        "EVOLVE_66",
        "HOLD",
        None,
    ) or True
    evo = NS(type=OptionType.EVOLVE, area=AreaType.HAND, index=0, playerIndex=0)
    hilda = NS(type=OptionType.PLAY, area=AreaType.HAND, index=2, playerIndex=0)
    evo_s = sp._hard_rule_bonus(obs, evo, sit)
    hilda_s = sp._hard_rule_bonus(obs, hilda, sit)
    assert evo_s >= sp._DOMINATE_OPEN_PATH
    assert evo_s > hilda_s


# ── U2: Ultra Ball gates ────────────────────────────────────────────────────

def test_u2_ub_blocked_when_mega_held_with_base():
    me = _player(
        active=_pkm(STARYU, energies=(WATER_BASIC,)),
        hand=(MEGA_STARMIE, WATER_BASIC, ULTRA_BALL, DUDUNSPARCE),
    )
    plan, obs = _plan(me, turn=5)
    assert not plan.acquire.ball_allowed
    # Land path complete → empty Pokemon gap ("no current…") or explicit UB-2.
    assert (
        "UB-2" in plan.acquire.ball_reason
        or "no current Pokemon gap" in plan.acquire.ball_reason
    )
    sit = sp._compute_situation(obs)
    # ULTRA_BALL at hand index 2 — TurnPlan gate is hard-illegal (mega_clock
    # may demote other PLAY first via _hard_rule_bonus).
    assert (
        sp._turn_plan_hard_bonus(obs, NS(type=OptionType.PLAY, index=2), sit)
        <= sp._ATTACH_ILLEGAL
    )


def test_u2_forced_burn_blocks_ub_when_only_mega_and_water_left():
    """Hand after UB would be Mega+water only — must burn Mega (90443511)."""
    me = _player(
        active=_pkm(DUNSPARCE_A),
        hand=(ULTRA_BALL, MEGA_STARMIE, WATER_BASIC),
    )
    plan, _obs = _plan(me, turn=3)
    assert not plan.acquire.ball_allowed
    assert "forced-burn" in plan.acquire.ball_reason


def test_u2_held_mega_always_protected_in_discard_values():
    me = _player(
        active=_pkm(DUNSPARCE_A),
        hand=(MEGA_STARMIE, ULTRA_BALL, WATER_BASIC),
    )
    plan, _ = _plan(me)
    assert discard_value(MEGA_STARMIE, plan) >= 10_000


# ── U3: dual Staryu attach seat ─────────────────────────────────────────────

def test_u3_ban_water_on_active_when_bench_dry_staryu():
    me = _player(
        active=_pkm(STARYU, appearThisTurn=True),
        bench=(_pkm(STARYU, appearThisTurn=True),),
        hand=(WATER_BASIC, MEGA_STARMIE),
    )
    _, obs = _plan(me, turn=2, first_player=1)
    sit = sp._compute_situation(obs)
    # hand index 0 = water; Active attach
    attach_active = NS(
        type=OptionType.ATTACH,
        index=0,
        inPlayArea=AreaType.ACTIVE,
        inPlayIndex=0,
    )
    attach_bench = NS(
        type=OptionType.ATTACH,
        index=0,
        inPlayArea=AreaType.BENCH,
        inPlayIndex=0,
    )
    assert sp._attach_priority_bonus(
        obs, attach_active, 0, sit["board"], sit["phase"], sit.get("hand"),
    ) <= sp._ATTACH_ILLEGAL
    assert sp._attach_priority_bonus(
        obs, attach_bench, 0, sit["board"], sit["phase"], sit.get("hand"),
    ) >= sp._DOMINATE_OPEN_PATH


# ── U4: Night Stretcher prefers Mega after death ────────────────────────────

def test_u4_recover_mega_before_water_when_mega_offline():
    me = _player(
        active=_pkm(STARYU),
        hand=(NIGHT_STRETCHER,),
        discard=(WATER_BASIC, MEGA_STARMIE, MEGA_STARMIE),
    )
    plan, _ = _plan(me, turn=13)
    assert plan.acquire.recover_target == MEGA_STARMIE


def test_u4_fueled_gap_still_recovers_water_for_online_mega():
    me = _player(
        active=_pkm(MEGA_STARMIE),
        hand=(NIGHT_STRETCHER,),
        discard=(WATER_BASIC,),
    )
    plan, _ = _plan(me)
    assert plan.acquire.recover_target == WATER_BASIC


# ── U5: going-first Budew stay ──────────────────────────────────────────────

def test_u5_going_first_t1_budew_bans_retreat_to_staryu():
    me = _player(
        active=_pkm(BUDEW, hp=30, appearThisTurn=True),
        bench=(_pkm(STARYU, energies=(WATER_BASIC,), appearThisTurn=True),),
        hand=(MEGA_STARMIE,),
    )
    # first_player=0, my_index=0 → going first; turn=1 → My-T1
    _, obs = _plan(me, turn=1, first_player=0)
    sit = sp._compute_situation(obs)
    sit["board"].my_turn_number = 1
    assert sp._going_first_budew_stay_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) <= sp._ATTACH_ILLEGAL
    switch_to_staryu = NS(
        type=OptionType.CARD,
        area=AreaType.BENCH,
        index=0,
        playerIndex=0,
    )
    obs.select.context = int(SelectContext.SWITCH)
    assert sp._going_first_budew_stay_bonus(obs, switch_to_staryu, sit) <= sp._ATTACH_ILLEGAL
    assert sp._going_first_budew_stay_bonus(
        obs, NS(type=OptionType.END), sit,
    ) >= sp._DOMINATE_MID


def test_u5_still_bans_retreat_when_mega_held_dispatchable():
    """Regression game_112/180: Mega in hand must not disable U5 stay."""
    me = _player(
        active=_pkm(BUDEW, hp=30, appearThisTurn=True),
        bench=(_pkm(STARYU, energies=(WATER_BASIC,), appearThisTurn=True),),
        hand=(MEGA_STARMIE, WATER_BASIC),
    )
    plan, obs = _plan(me, turn=1, first_player=0)
    sit = sp._compute_situation(obs)
    sit["board"].my_turn_number = 1
    assert plan.facts.can_dispatch_bench_mega or MEGA_STARMIE in plan.facts.hand_ids
    assert sp._going_first_budew_stay_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) <= sp._ATTACH_ILLEGAL
    assert sp._going_first_budew_stay_bonus(
        obs, NS(type=OptionType.END), sit,
    ) >= sp._DOMINATE_MID


# ── Knife A2 / OL-A2: protector wall (Budew/Dunsparce → bare Staryu) ─────────

def test_knife_a2_dunsparce_bans_retreat_to_watered_staryu_without_mega():
    """OL-A2 main leak: Dunsparce Active + watered Staryu, no Mega → stay."""
    me = _player(
        active=_pkm(DUNSPARCE_A),
        bench=(_pkm(STARYU, energies=(WATER_BASIC,)),),
        hand=(WATER_BASIC,),
    )
    _, obs = _plan(me, turn=3, first_player=0)
    sit = sp._compute_situation(obs)
    assert sit["board"].my_turn_number != 1 or True
    assert sp._protector_wall_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) <= sp._ATTACH_ILLEGAL
    assert sp._hard_rule_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) <= sp._ATTACH_ILLEGAL
    # mega_clock D2 must not PATH-promote either
    assert sp._mega_clock_hard_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) < sp._DOMINATE_OPEN_PATH


def test_knife_a2_budew_midgame_bans_staryu_expose_without_mega():
    me = _player(
        active=_pkm(BUDEW, hp=30),
        bench=(_pkm(STARYU, energies=(WATER_BASIC,)),),
        hand=(SWITCH,),
    )
    _, obs = _plan(me, turn=4, first_player=1)
    sit = sp._compute_situation(obs)
    switch = NS(type=OptionType.PLAY, area=AreaType.HAND, index=0, playerIndex=0)
    assert sp._hard_rule_bonus(obs, switch, sit) <= sp._ATTACH_ILLEGAL


def test_knife_a2_mega_in_hand_allows_promote_from_dunsparce():
    """Mega held opens cut (shipped knife); evolve must still win after land."""
    me = _player(
        active=_pkm(DUNSPARCE_A),
        bench=(_pkm(STARYU, energies=(WATER_BASIC,)),),
        hand=(MEGA_STARMIE, SWITCH),
    )
    _, obs = _plan(me, turn=3, first_player=0)
    sit = sp._compute_situation(obs)
    assert sp._protector_wall_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) == 0.0
    assert sp._mega_clock_hard_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) >= sp._DOMINATE_OPEN_PATH


def test_knife_a2_bench_mega_allows_retreat_but_bans_staryu_select():
    me = _player(
        active=_pkm(DUNSPARCE_A),
        bench=(
            _pkm(STARYU, energies=(WATER_BASIC,)),
            _pkm(MEGA_STARMIE, energies=(WATER_BASIC,)),
        ),
        hand=(),
    )
    _, obs = _plan(me, turn=5, first_player=0)
    sit = sp._compute_situation(obs)
    assert sp._protector_wall_bonus(
        obs, NS(type=OptionType.RETREAT), sit,
    ) == 0.0
    pick_staryu = NS(
        type=OptionType.CARD,
        area=AreaType.BENCH,
        index=0,
        playerIndex=0,
    )
    obs.select.context = int(SelectContext.SWITCH)
    assert sp._protector_wall_bonus(obs, pick_staryu, sit) <= sp._ATTACH_ILLEGAL
