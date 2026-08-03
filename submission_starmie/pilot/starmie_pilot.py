"""Deck-specific pilot for the Starmie ex + Froslass ex dual-Mega deck.

Two-layer architecture:
  Layer 1 — deterministic hard rules (return DOMINATE score, always wins the sort)
  Layer 2 — soft trainable nudges (bounded ~0-5, nudges the generic baseline)

Public API:
  make_starmie_agent(deck, weights) -> AgentFn
  DEFAULT_WEIGHTS                   -> dict[str, float]   (soft dims only)
"""
from __future__ import annotations

import os
import random
from typing import Any, Callable

from cg.api import (
    AreaType,
    EnergyType,
    OptionType,
    SelectContext,
    all_card_data,
    to_observation_class,
)

AgentFn = Callable[[dict[str, Any]], list[int]]

# ── Deck card catalogue (all IDs live here, never in shared policy.py) ───────
_CARDS = {
    # Attackers
    "staryu":          1030,
    "mega_starmie_ex": 1031,
    "snorunt":          860,
    "mega_froslass_ex": 861,
    "froslass":         104,
    # Spread / transfer engine
    "munkidori":        112,
    # Disruption basics
    "budew":            235,
    "fan_rotom":        174,
    # Draw engine
    "dunsparce_a":       65,
    "dunsparce_b":      305,
    "dudunsparce":       66,
    "dudunsparce_ex":   306,
    "meowth_ex":       1071,
    # Key trainers / supporters
    "boss_orders":     1182,
    "hilda":           1225,
    "ignition_energy":   17,
    # Stadium
    "risky_ruins":     1260,
}

from deck_resources import build_deck_resources, build_hand_context_from_obs
from draw_axis import pick_draw_axis_action
from hand_snapshot import build_board_snapshot
from opening_cards import (
    BOSS_ORDERS as _OC_BOSS,
    CRISPIN,
    DARK_BASIC,
    DUDUNSPARCE as _OC_DUDUNSPARCE,
    DUNSPARCE_A,
    DUNSPARCE_B,
    FROSLASS as _OC_FROSLASS,
    HILDA,
    IGNITION,
    JUDGE,
    LILLIE,
    MEGA_STARMIE as _OC_MEGA_STARMIE,
    MEOWTH_EX as _OC_MEOWTH_EX,
    MUNKIDORI as _OC_MUNKIDORI,
    NIGHT_STRETCHER as _OC_NIGHT_STRETCHER,
    POKE_PAD as _OC_POKE_PAD,
    POFFIN as _OC_POFFIN,
    POFFIN_OPENING_PRIORITY,
    PRISM as _OC_PRISM,
    RISKY_RUINS as _RISKY_RUINS,
    SALVATOR,
    SNORUNT as _OC_SNORUNT,
    STARYU as _OC_STARYU,
    SWITCH as _OC_SWITCH,
    ULTRA_BALL as _OC_ULTRA_BALL,
    UNFAIR_STAMP,
    WALLYS_COMPASSION as _OC_WALLYS,
    WATER_BASIC,
    can_retreat_pokemon,
    ENERGY_IDS as _ENERGY_IDS,
    SUPPORTER_IDS as _SUPPORTER_IDS,
    WATER_ENERGY_IDS as _WATER_ENERGY_IDS,
    retreat_cost_for,
)
from opening_bridge import (
    compute_epoch_plan,
    compute_opening_route,
    score_opening_option,
    _active_can_retreat,
    _line_has_water,
)
from epoch_scheduler import (
    default_epoch_memory,
    refresh_epoch_memory,
    set_mega_froslass_window,
)
from matchup_alakazam import (
    alakazam_plan_b_hard_bonus,
    alak_lock_pick_order,
    doublekill_ready as alak_doublekill_ready,
    in_lock_window as alak_in_lock_window,
    protect_unfair_stamp_discard,
    refresh_alakazam_matchup,
)
from phase_fsm import compute_phase, opening_complete
from supporter_planner import lillie_forbidden, pick_supporter
from turn_planner import build_turn_plan, discard_value, is_basic_attack_forbidden

_MEGA_EX_IDS    = {_CARDS["mega_starmie_ex"], _CARDS["mega_froslass_ex"]}
_STARMIE_LINE   = {_CARDS["staryu"], _CARDS["mega_starmie_ex"]}
_FROSLASS_LINE  = {_CARDS["snorunt"], _CARDS["froslass"], _CARDS["mega_froslass_ex"]}
_MUNKIDORI_ID   = _CARDS["munkidori"]
_FAN_ROTOM_ID   = _CARDS["fan_rotom"]
_BUDEW_ID       = _CARDS["budew"]
_BOSS_ID        = _CARDS["boss_orders"]
# Attack lines that must never receive Dark via Crispin ATTACH_FROM.
_ATTACKER_LINE_IDS = frozenset({
    _OC_STARYU,
    _CARDS["mega_starmie_ex"],
    _OC_SNORUNT,
    _OC_FROSLASS,
    _CARDS["mega_froslass_ex"],
})
_JUNK_OIL_IDS = frozenset({
    _BUDEW_ID,
    _FAN_ROTOM_ID,
    DUNSPARCE_A,
    DUNSPARCE_B,
    _CARDS["dunsparce_a"],
    _CARDS["dunsparce_b"],
    _CARDS["dudunsparce"],
})

# Dominating score — hard-rule options always sort first
_DOMINATE = 1_000.0
_DOMINATE_PLUS = 1_100.0   # Nebula KO / Adrena-Brain (有伤可转) / retreat attach
_DOMINATE_RESCUE = 1_120.0 # Switch / Pad when stuck off Starmie (HR-9)
_DOMINATE_OPEN = 1_130.0   # HR-O5 OPENING Switch bench Mega → Active (G5)
_DOMINATE_OPEN_PATH = 1_150.0  # HR-O Main — opening_planner route (Step A)
_DOMINATE_ATTACK = 975.0   # Jetting Blow — below ability/attach, above supporters
_DOMINATE_SUPPORT = 960.0  # Boss / Lillie / Crispin / Stamp (Layer1 planners)
_DOMINATE_MID = 920.0      # Bench setup / attach / evolve 66
_DOMINATE_LOW = 880.0      # Risky Ruins / 306 ex
# Illegal ATTACH must lose to END/ATTACK even when those are also -DOMINATE.
_ATTACH_ILLEGAL = -50_000.0

# ── EX card set (cached) ──────────────────────────────────────────────────────
_EX_CACHE: set[int] | None = None

def _ex_card_set() -> set[int]:
    global _EX_CACHE
    if _EX_CACHE is None:
        _EX_CACHE = {
            c.cardId for c in all_card_data()
            if getattr(c, "ex", False) or getattr(c, "megaEx", False)
        }
    return _EX_CACHE


# ── Observation helpers ───────────────────────────────────────────────────────

def _si(v, d=0):
    try: return int(v)
    except: return d

def _board_pokemon(player_state) -> list:
    """Active + bench Pokemon objects for a player."""
    active = [p for p in (player_state.active or []) if p is not None]
    bench  = [p for p in (player_state.bench  or []) if p is not None]
    return active + bench

def _pokemon_in_area(obs, area, index, player_index):
    try:
        p = obs.current.players[player_index]
        if area == AreaType.ACTIVE: return (p.active or [])[index]
        if area == AreaType.BENCH:  return (p.bench  or [])[index]
    except Exception: pass
    return None

def _hand_card_id(obs, option, my_index: int) -> int:
    """Card ID of a PLAY option's hand card."""
    try:
        if option.type != OptionType.PLAY: return 0
        hand = obs.current.players[my_index].hand or []
        idx  = _si(getattr(option, "index", None), -1)
        if 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None))
    except Exception: pass
    return 0

def _ability_source_id(obs, option, my_index: int) -> int:
    """Card ID of the Pokemon whose ability is offered."""
    try:
        if option.type != OptionType.ABILITY: return 0
        return _si(getattr(
            _pokemon_in_area(obs, option.area, _si(option.index), my_index),
            "id", None
        ))
    except Exception: return 0

def _attack_id(option) -> int:
    """Attack ID from an ATTACK option (0 when not an attack)."""
    if option.type != OptionType.ATTACK: return 0
    return _si(getattr(option, "attackId", None))

def _has_darkness_energy(pokemon) -> bool:
    """True when the Pokemon has Darkness (or Prism) energy for Adrena-Brain."""
    try:
        energies = getattr(pokemon, "energies", None) or []
        dark_ids = {int(EnergyType.DARKNESS), _OC_PRISM}
        return any(_si(e) in dark_ids for e in energies)
    except Exception: return False


def _has_water_energy(pokemon) -> bool:
    """True when the Pokemon has Water (or Prism) energy for Jetting Blow."""
    try:
        energies = getattr(pokemon, "energies", None) or []
        water_ids = {int(EnergyType.WATER), WATER_BASIC, _OC_PRISM}
        return any(_si(e) in water_ids for e in energies)
    except Exception:
        return False


def _bench_mega_starmie_with_water(obs, my_index: int):
    """Return (bench_index, pokemon) for Mega Starmie ex with water, or (None, None)."""
    try:
        for i, p in enumerate(obs.current.players[my_index].bench or []):
            if (
                p
                and _si(getattr(p, "id", None)) == _CARDS["mega_starmie_ex"]
                and _has_water_energy(p)
            ):
                return i, p
    except Exception:
        pass
    return None, None


def _bench_has_non_staryu(obs, my_index: int) -> bool:
    """True if Bench has any Pokémon that is not unevolved Staryu."""
    try:
        for p in obs.current.players[my_index].bench or []:
            if p and _si(getattr(p, "id", None)) != _OC_STARYU:
                return True
    except Exception:
        pass
    return False


def _bench_has_id(obs, my_index: int, card_id: int) -> bool:
    try:
        for p in obs.current.players[my_index].bench or []:
            if p and _si(getattr(p, "id", None)) == card_id:
                return True
    except Exception:
        pass
    return False


def _hand_has_id(obs, my_index: int, card_id: int) -> bool:
    try:
        for c in obs.current.players[my_index].hand or []:
            if c and _si(getattr(c, "id", None)) == card_id:
                return True
    except Exception:
        pass
    return False


def _harvest_needs_froslass_attacker(board, phase) -> bool:
    """After Mega Starmie leaves: need Mega Froslass (861) as the new Active attacker."""
    if phase.primary != "HARVEST":
        return False
    if board.active_is_mega_froslass:
        return False
    # Opening never completed and no Starmie corpse → still may harvest via T3 fallback.
    return not board.mega_starmie_on_field


def _harvest_promote_switch_needed(obs, my_index: int, board, phase) -> bool:
    """Bench has 861 (or Snorunt+861 in hand) but Active is not the Froslass attacker."""
    if not _harvest_needs_froslass_attacker(board, phase):
        return False
    if _bench_has_id(obs, my_index, _CARDS["mega_froslass_ex"]):
        return True
    # Engine: Mega Froslass evolves from Snorunt — promote Snorunt to evolve in place.
    if (
        _hand_has_id(obs, my_index, _CARDS["mega_froslass_ex"])
        and _bench_has_id(obs, my_index, _OC_SNORUNT)
        and board.active_id != _OC_SNORUNT
    ):
        return True
    return False


def _synergy_core_ready(board) -> bool:
    """Dark Munkidori plus either supported damage-counter generator."""
    return (
        (board.froslass_104_on_field or board.risky_ruins_online)
        and board.munkidori_on_field
        and board.munkidori_has_dark
    )


_MAIN_PHASE_TYPES = (
    OptionType.PLAY,
    OptionType.ATTACH,
    OptionType.EVOLVE,
    OptionType.ABILITY,
    OptionType.RETREAT,
)


def _main_phase_open(sit: dict[str, Any]) -> bool:
    """True when the current select still offers a non-attack main-phase action."""
    opts = sit.get("select_options") or []
    return any(getattr(o, "type", None) in _MAIN_PHASE_TYPES for o in opts)


def _attack_last_score(sit: dict[str, Any], *, force_now: bool = False) -> float | None:
    """If attack must wait for main-phase work, return a soft trailing score.

    Returns None when the caller should use its normal dominate score
    (KO / prize closeout / no main-phase options left).
    """
    if force_now:
        return None
    if int(sit.get("prize_self", 99) or 99) <= 2:
        return None
    if _main_phase_open(sit):
        return 5.0  # below every hard-rule setup; above blank END (0 / -DOMINATE)
    return None


def _resentful_damage(opp_hand: int) -> int:
    return 50 * max(0, int(opp_hand))


def _resentful_worthless(opp_hand: int) -> bool:
    """Resentful Refrain is 50×opp hand — empty hand = 0 damage, dead attack."""
    return _resentful_damage(opp_hand) == 0


def _hand_has_water_energy(obs, my_index: int) -> bool:
    try:
        for c in obs.current.players[my_index].hand or []:
            if c and _si(getattr(c, "id", None)) in _WATER_ENERGY_IDS:
                return True
    except Exception:
        pass
    return False


def _can_fuel_mega_same_turn(obs, my_index: int, pokemon) -> bool:
    """True when pokemon lacks water but hand holds a water attach this turn."""
    if pokemon is None or _has_water_energy(pokemon):
        return False
    return _hand_has_water_energy(obs, my_index)


def _mega_active_fuel_ok(obs, my_index: int, pokemon) -> bool:
    """Mega may stand Active only if already watered or same-turn attach exists."""
    if pokemon is None:
        return False
    return _has_water_energy(pokemon) or _can_fuel_mega_same_turn(obs, my_index, pokemon)


def _froslass_line_worth(obs, my_index: int, board, sit: dict[str, Any]) -> bool:
    """861 line is worth keeping/promoting when it advances prizes.

    Absolute Snow (150) counts as advancing if it can KO the opp Active.
    Unfair Stamp is NOT a buff — it shrinks opp hand (draw 2).
    """
    opp_hand = int(sit.get("opp_hand_count") or 0)
    if _resentful_worthless(opp_hand):
        return False
    plan = sit.get("turn_plan")
    if plan is not None:
        try:
            from turn_planner import _expected_froslass_prizes

            if _expected_froslass_prizes(plan.facts) >= 2:
                return True
        except Exception:
            pass
    # Absolute Snow 150 can still advance a KO-able Active.
    try:
        opp = obs.current.players[1 - my_index]
        active = (opp.active or [None])[0]
        if active and 0 < _si(getattr(active, "hp", None)) <= 150:
            return True
    except Exception:
        pass
    # Fat hand Resentful (≥200) is the classic harvest window.
    return _resentful_damage(opp_hand) >= 200


def _starmie_promote_over_froslass(obs, my_index: int, board, sit: dict[str, Any]) -> bool:
    """Active 861 but Resentful is dead/weak — cut to a *fueled* bench Starmie.

    Never cut to an unfueled Mega (that gifts 2–3 prizes). Unfair Stamp shrinks
    opp hand and must not be treated as a Resentful buff.
    """
    if not board.active_is_mega_froslass:
        return False
    _, fueled = _bench_mega_starmie_with_water(obs, my_index)
    if fueled is None:
        return False
    opp_hand = int(sit.get("opp_hand_count") or 0)
    if _resentful_worthless(opp_hand):
        return True
    if _resentful_damage(opp_hand) < 150:
        return True
    if not _froslass_line_worth(obs, my_index, board, sit):
        return True
    return False


def _boss_engine_gate(board, phase, hand_ctx=None, turn_plan=None) -> bool:
    """Effective-Boss gate — mirrors supporter_planner._boss_ok.

    Prefer TurnPlan.boss_target / expected_prize_delta; ≤2 prizes still opens.
    Sole-supporter Boss is no longer a relaxation.
    """
    from supporter_planner import _boss_ok

    return _boss_ok(board, phase, hand_ctx, turn_plan=turn_plan)


def _defer_mega_promotion(board, phase) -> bool:
    """AGGRESSION/HARVEST only: defer bench→Active Mega until synergy core ready."""
    if phase.primary == "OPENING":
        return False
    return 2 <= board.my_turn_number <= 8 and not _synergy_core_ready(board)


def _opening_g5_switch_needed(phase, board, obs, my_index: int) -> bool:
    """Bench Mega Starmie + water ready but Active is not attacking Mega."""
    if phase.primary != "OPENING":
        return False
    if board.active_is_mega_starmie and board.active_has_water:
        return False
    _, mega = _bench_mega_starmie_with_water(obs, my_index)
    if mega is None:
        return False
    if _defer_mega_promotion(board, phase):
        return False
    return True


def _starmie_should_attack(board) -> bool:
    """Active Mega Starmie ex with water — must Jetting/Nebula this turn."""
    return board.active_is_mega_starmie and board.active_has_water


def _mega_froslass_should_attack(board) -> bool:
    """Active Mega Froslass ex with water — must Resentful/Absorbing this turn."""
    return board.active_is_mega_froslass and board.active_has_water


def _fueled_mega_must_attack(board, plan=None) -> bool:
    """Board-level must-attack: fueled Active Mega, independent of TurnPlan gaps.

    Online fade showed Boss/Poffin/66/Switch eating turns when attack_required
    failed to latch; board water on 1031/861 is the source of truth.
    """
    if _starmie_should_attack(board) or _mega_froslass_should_attack(board):
        return True
    if plan is not None and getattr(plan.combat, "attack_required", False):
        if getattr(plan.facts, "active_ready_mega", False):
            return True
    return False


def _mega_froslass_needs_water(board) -> bool:
    return board.active_is_mega_froslass and not board.active_has_water


def _hand_has_dark_energy(obs, my_index: int) -> bool:
    try:
        for c in obs.current.players[my_index].hand or []:
            if c and _si(getattr(c, "id", None)) == DARK_BASIC:
                return True
    except Exception:
        pass
    return False


def _refresh_harvest_ko(state: dict[str, Any], board) -> None:
    """Set harvest_ko_last_turn when Mega Starmie ex was KO'd before this My-T."""
    mt = board.my_turn_number
    if mt != state.get("last_my_turn", 0):
        if state.get("prev_active_was_mega_starmie") and not board.mega_starmie_on_field:
            state["harvest_ko_last_turn"] = True
        elif mt > state.get("last_my_turn", 0):
            state["harvest_ko_last_turn"] = False
        state["last_my_turn"] = mt
    state["prev_active_was_mega_starmie"] = board.active_is_mega_starmie


def _harvest_hard_rules(
    obs, option, sit, mi, board, phase, hand, prize_ids,
) -> float:
    """HR-H* — HARVEST-only Layer 1 rules (03_harvest.md)."""
    if phase.primary != "HARVEST":
        return 0.0

    opp_hand = sit["opp_hand_count"]
    hand_ctx = sit.get("hand")
    need_attacker = _harvest_needs_froslass_attacker(board, phase)

    # HR-H0  After Mega Starmie KO / absent — promote Froslass attacker to Active.
    # Fuel gate: never force unfueled 861 Active (gifts 2–3 prizes).
    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
            pi = _si(getattr(option, "playerIndex", None), mi)
            if pi == mi and need_attacker:
                pkm = _pokemon_in_area(
                    obs, option.area, _si(getattr(option, "index", None)), mi,
                )
                if pkm:
                    pid = _si(getattr(pkm, "id", None))
                    if pid == _CARDS["mega_froslass_ex"]:
                        if not _mega_active_fuel_ok(obs, mi, pkm):
                            return -_DOMINATE_OPEN_PATH
                        if not _froslass_line_worth(obs, mi, board, sit):
                            # Contested hand — prefer fueled Starmie if present.
                            _, fueled_st = _bench_mega_starmie_with_water(obs, mi)
                            if fueled_st is not None:
                                return -_DOMINATE
                        return _DOMINATE_OPEN_PATH
                    if pid == _CARDS["mega_starmie_ex"]:
                        if not _mega_active_fuel_ok(obs, mi, pkm):
                            return -_DOMINATE_OPEN_PATH
                        return _DOMINATE_OPEN_PATH
                    if pid == _OC_FROSLASS:
                        return _DOMINATE_OPEN - 10.0
                    if pid == _OC_SNORUNT and not board.froslass_104_on_field:
                        return _DOMINATE_MID
                    if pid == _OC_STARYU:
                        return -_DOMINATE_OPEN_PATH

    # HR-H0b  Do NOT leave Active Snorunt when 861 is in hand — evolve in place.
    # (Mega Froslass evolves from Snorunt; 104 is a parallel Stage-1, not the Mega pre-evo.)
    if (
        need_attacker
        and board.active_id == _OC_SNORUNT
        and _hand_has_id(obs, mi, _CARDS["mega_froslass_ex"])
    ):
        if option.type == OptionType.RETREAT:
            return -_DOMINATE_OPEN_PATH
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return -_DOMINATE_OPEN_PATH

    if need_attacker and _harvest_promote_switch_needed(obs, mi, board, phase):
        # Only rush Switch when a fueled (or same-turn-fuelable) 861 is on bench.
        try:
            bench_861 = next(
                (
                    p
                    for p in (obs.current.players[mi].bench or [])
                    if p and _si(getattr(p, "id", None)) == _CARDS["mega_froslass_ex"]
                ),
                None,
            )
        except Exception:
            bench_861 = None
        fueled_ok = bench_861 is not None and _mega_active_fuel_ok(obs, mi, bench_861)
        snorunt_evo = (
            _hand_has_id(obs, mi, _CARDS["mega_froslass_ex"])
            and _bench_has_id(obs, mi, _OC_SNORUNT)
        )
        if fueled_ok or snorunt_evo:
            if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
                return _DOMINATE_OPEN
            if option.type == OptionType.RETREAT:
                try:
                    _hand = obs.current.players[mi].hand or []
                except Exception:
                    _hand = []
                if not any(_si(getattr(c, "id", None)) == _OC_SWITCH for c in _hand if c):
                    return _DOMINATE_RESCUE

    # HR-H7  Unfair Stamp after our Active KO: refill us to 5 / opp to 2.
    # Shrinks opp hand — never treat as a Resentful buff.
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == UNFAIR_STAMP and sit.get("harvest_ko_last_turn"):
            return _DOMINATE_OPEN

    # HR-H8  Boss's Orders onto prize-path bench target (effective-Boss gate)
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if (
            cid == _BOSS_ID
            and hand_ctx
            and hand_ctx.gust_target_on_opp_bench
            and _boss_engine_gate(board, phase, hand_ctx, sit.get("turn_plan"))
        ):
            return _DOMINATE_SUPPORT

    # HR-H6  Judge: ban before first Resentful once 861 is online (or ready).
    # Fat-hand Judge only when Mega Froslass is not yet on the board.
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == JUDGE:
            opp_hand = int(sit.get("opp_hand_count") or 0)
            resentful_ready = bool(_mega_froslass_should_attack(board))
            mega_f_online = bool(
                getattr(board, "mega_froslass_on_field", False)
                or board.active_is_mega_froslass
            )
            if sit.get("harvest_resentful_fired"):
                if resentful_ready:
                    return 0.0  # attack first; CONTROL HR may still boost Judge later
                return _DOMINATE_SUPPORT if opp_hand >= 5 else _DOMINATE_MID
            if resentful_ready or mega_f_online:
                return -_DOMINATE
            # No 861 online yet — disrupt fat hands.
            if opp_hand >= 6:
                return _DOMINATE_SUPPORT
            return -_DOMINATE

    # HR-H1  Evolve Snorunt → Mega Froslass ex (861). Engine never offers 861 onto 104.
    if option.type == OptionType.EVOLVE:
        if _evolve_to_mega_froslass_ex(obs, option, mi):
            if need_attacker or sit.get("harvest_ko_last_turn"):
                return _DOMINATE_OPEN_PATH
            return _DOMINATE_OPEN
        # Parallel Stage-1: only when 861 is unavailable (don't spend Snorunt if 861 ready).
        if _evolve_to_froslass_104(obs, option, mi):
            if _hand_has_id(obs, mi, _CARDS["mega_froslass_ex"]):
                return -_DOMINATE_OPEN
            if not board.froslass_104_on_field:
                return _DOMINATE_OPEN if need_attacker else _DOMINATE_MID

    # HR-H2  Attach water to Active 861 before Resentful
    if option.type == OptionType.ATTACH and _mega_froslass_needs_water(board):
        target = _attach_target_pokemon(obs, option, mi)
        eid = _attach_energy_id(obs, option, mi)
        active = _active_pokemon(obs, mi)
        if target is active and eid in _WATER_ENERGY_IDS:
            return _DOMINATE_PLUS

    # HR-H2b  Attach water to bench 861 when Active is not yet the attacker
    if (
        option.type == OptionType.ATTACH
        and need_attacker
        and _bench_has_id(obs, mi, _CARDS["mega_froslass_ex"])
    ):
        target = _attach_target_pokemon(obs, option, mi)
        eid = _attach_energy_id(obs, option, mi)
        if (
            target is not None
            and _si(getattr(target, "id", None)) == _CARDS["mega_froslass_ex"]
            and eid in _WATER_ENERGY_IDS
            and not _has_water_energy(target)
        ):
            return _DOMINATE_OPEN

    # HR-H3 / HR-H4  Resentful only when it actually damages; else Absolute Snow.
    # Empty opp hand → Resentful = 0: never boost it (cut to Starmie instead).
    if option.type == OptionType.ATTACK and _mega_froslass_should_attack(board):
        atk_id = _attack_id(option)
        if _starmie_promote_over_froslass(obs, mi, board, sit):
            return -_DOMINATE  # must Switch/Retreat to bench Mega Starmie
        last = _attack_last_score(sit)
        if atk_id == _ATK_RESENTFUL:
            if _resentful_damage(opp_hand) >= 200:
                return last if last is not None else _DOMINATE_PLUS
            return -_DOMINATE  # worse than Absolute Snow (150)
        if atk_id == _ATK_ABS_SNOW:
            if _resentful_damage(opp_hand) < 200:
                return last if last is not None else _DOMINATE_ATTACK
            return -_DOMINATE

    # HR-H3b  When Resentful is LIVE, don't spend on supporters.
    # Stamp shrinks opp hand to 2 — ban before Resentful unless KO-refill window
    # where Resentful is already weak (<200).
    if (
        _mega_froslass_should_attack(board)
        and not sit.get("harvest_resentful_fired")
        and not _resentful_worthless(opp_hand)
        and not _starmie_promote_over_froslass(obs, mi, board, sit)
    ):
        if option.type == OptionType.PLAY:
            cid = _hand_card_id(obs, option, mi)
            if cid == UNFAIR_STAMP:
                if sit.get("harvest_ko_last_turn") and _resentful_damage(opp_hand) < 200:
                    pass  # refill us / deny opp resources
                else:
                    return -_DOMINATE
            elif cid == _OC_SWITCH:
                pass  # never ban the cut-back tool
            elif cid in _SUPPORTER_IDS or cid == _BOSS_ID:
                return -_DOMINATE  # beat Layer1 post-Mega supporter boost
        if option.type == OptionType.ABILITY:
            return -_DOMINATE

    # HR-H5  Penalize END when Mega Froslass should attack (unless cutting to Starmie)
    if option.type == OptionType.END and _mega_froslass_should_attack(board):
        if _starmie_promote_over_froslass(obs, mi, board, sit):
            return -_DOMINATE  # must promote, not pass
        return -_DOMINATE

    # HR-H5b  Penalize END when 861 can attach water this turn
    if (
        option.type == OptionType.END
        and _mega_froslass_needs_water(board)
        and _hand_has_water_energy(obs, mi)
    ):
        return -_DOMINATE

    # HR-H9  Search Mega Froslass when Snorunt is online but 861 missing.
    if (
        option.type == OptionType.CARD
        and getattr(board, "snorunt_on_field", False)
        and not getattr(board, "mega_froslass_on_field", False)
        and not board.active_is_mega_froslass
        and not _hand_has_id(obs, mi, _CARDS["mega_froslass_ex"])
    ):
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (int(SelectContext.TO_HAND), int(SelectContext.TO_FIELD)):
            cid = _card_option_id(obs, option, mi)
            if cid == _CARDS["mega_froslass_ex"]:
                return _DOMINATE_OPEN_PATH

    return 0.0


def _meowth_on_field(obs, my_index: int) -> bool:
    try:
        me = obs.current.players[my_index]
        for p in (me.active or []) + (me.bench or []):
            if p and _si(getattr(p, "id", None)) == _OC_MEOWTH_EX:
                return True
    except Exception:
        pass
    return False


def _control_blocks_setup(board, phase) -> bool:
    """CONTROL tools must not skip mandatory Mega ex attacks."""
    if phase.primary == "AGGRESSION" and _starmie_should_attack(board):
        return True
    if phase.primary == "HARVEST" and _mega_froslass_should_attack(board):
        return True
    return False


def _control_hard_rules(
    obs, option, sit, mi, board, phase, hand, prize_ids,
) -> float:
    """HR-C* — CONTROL modifier Layer 1 (04_control.md)."""
    if not phase.control_active or phase.primary == "OPENING":
        return 0.0

    hand_ctx = sit.get("hand")

    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == JUDGE:
            opp_hand = int(sit.get("opp_hand_count") or 0)
            if phase.primary == "HARVEST":
                if _mega_froslass_should_attack(board) and not sit.get(
                    "harvest_resentful_fired"
                ):
                    return 0.0  # let HR-H6 / attack win
                if sit.get("harvest_resentful_fired") or opp_hand >= 6:
                    return _DOMINATE_SUPPORT
                return 0.0
            elif _control_blocks_setup(board, phase):
                return 0.0
            if opp_hand >= 6:
                return _DOMINATE_SUPPORT
            return _DOMINATE_SUPPORT
        if cid == _OC_MEOWTH_EX:
            if board.bench_open <= 0 or _meowth_on_field(obs, mi):
                return 0.0
            if _control_blocks_setup(board, phase):
                return 0.0
            return _DOMINATE_MID
        if cid == _BOSS_ID and phase.primary == "AGGRESSION":
            if (
                hand_ctx
                and hand_ctx.gust_target_on_opp_bench
                and _boss_engine_gate(board, phase, hand_ctx, sit.get("turn_plan"))
            ):
                return _DOMINATE_SUPPORT

    if option.type == OptionType.ABILITY:
        if _ability_source_id(obs, option, mi) == _OC_MEOWTH_EX:
            if _control_blocks_setup(board, phase):
                return 0.0
            return _DOMINATE_PLUS

    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            return 0.0
        if ctx == int(SelectContext.TO_HAND):
            cid = _card_option_id(obs, option, mi)
            if cid == _BOSS_ID:
                return _DOMINATE
            if cid == JUDGE:
                if phase.primary == "HARVEST" and not sit.get("harvest_resentful_fired"):
                    return 0.0
                return _DOMINATE_MID
            if cid == CRISPIN:
                return _DOMINATE_LOW

    return 0.0


def _munkidori_on_bench(obs, my_index: int):
    """Return the first Munkidori on the bench that has Darkness energy."""
    try:
        for p in (obs.current.players[my_index].bench or []):
            if p and _si(getattr(p, "id", None)) == _MUNKIDORI_ID:
                if _has_darkness_energy(p):
                    return p
    except Exception: pass
    return None

def _mega_attacker_ready(obs, my_index: int) -> bool:
    """True when a Mega Starmie ex or Mega Froslass ex is in the active spot."""
    try:
        active = (obs.current.players[my_index].active or [None])[0]
        if active and _si(getattr(active, "id", None)) in _MEGA_EX_IDS:
            return True
    except Exception: pass
    return False


def _attach_target_pokemon(obs, option, my_index: int):
    try:
        area = option.inPlayArea
        p = obs.current.players[my_index]
        # ACTIVE: always the single Active Pokémon (do NOT fall back to hand index).
        if area == AreaType.ACTIVE or int(area) == int(AreaType.ACTIVE):
            return (p.active or [None])[0]
        if area == AreaType.BENCH or int(area) == int(AreaType.BENCH):
            idx = _si(getattr(option, "inPlayIndex", None), -1)
            bench = p.bench or []
            if 0 <= idx < len(bench):
                return bench[idx]
    except Exception:
        pass
    return None


def _attach_energy_id(obs, option, my_index: int) -> int:
    try:
        hand = obs.current.players[my_index].hand or []
        idx = _si(getattr(option, "handIndex", None), _si(getattr(option, "index", None), -1))
        if 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None))
    except Exception:
        pass
    return 0


def _nebula_ko_available(obs, my_index: int, prize_ids: set[int]) -> bool:
    try:
        opp_active = (obs.current.players[1 - my_index].active or [None])[0]
        if not opp_active:
            return False
        opp_cid = _si(getattr(opp_active, "id", None))
        opp_hp = _si(getattr(opp_active, "hp", None), 9999)
        return opp_cid in prize_ids and opp_hp <= 210
    except Exception:
        return False


def _gust_target_on_opp_bench(obs, my_index: int, prize_ids: set[int]) -> bool:
    try:
        oi = 1 - my_index
        bench_ids = {
            _si(getattr(p, "id", None))
            for p in (obs.current.players[oi].bench or []) if p
        }
        return bool(bench_ids & prize_ids)
    except Exception:
        return False


def _bench_has_id(obs, my_index: int, card_id: int) -> bool:
    try:
        for p in (obs.current.players[my_index].bench or []):
            if p and _si(getattr(p, "id", None)) == card_id:
                return True
    except Exception:
        pass
    return False


def _snorunt_on_bench(obs, my_index: int) -> bool:
    return _bench_has_id(obs, my_index, _CARDS["snorunt"])


def _pokemon_damage(pokemon) -> int:
    if pokemon is None:
        return 0
    max_hp = _si(getattr(pokemon, "maxHp", None), 0)
    hp = _si(getattr(pokemon, "hp", None), max_hp)
    return max(0, max_hp - hp)


def _own_transferable_damage(obs, my_index: int, min_damage: int = 10) -> bool:
    """True when any own Pokémon has damage counters to move via Adrena-Brain."""
    try:
        for p in _board_pokemon(obs.current.players[my_index]):
            if _pokemon_damage(p) >= min_damage:
                return True
    except Exception:
        pass
    return False


def _active_pokemon(obs, my_index: int):
    try:
        return (obs.current.players[my_index].active or [None])[0]
    except Exception:
        return None


def _munkidori_count_on_field(obs, my_index: int) -> int:
    try:
        return sum(
            1
            for p in _board_pokemon(obs.current.players[my_index])
            if p and _si(getattr(p, "id", None)) == _MUNKIDORI_ID
        )
    except Exception:
        return 0


def _count_froslass_104_on_field(obs, my_index: int) -> int:
    n = 0
    try:
        me = obs.current.players[my_index]
        active = (me.active or [None])[0]
        if active and _si(getattr(active, "id", None)) == _CARDS["froslass"]:
            n += 1
        for p in me.bench or []:
            if p and _si(getattr(p, "id", None)) == _CARDS["froslass"]:
                n += 1
    except Exception:
        pass
    return n


def _evolve_target_is_froslass_104(obs, option, my_index: int) -> bool:
    try:
        idx = _si(getattr(option, "index", None), -1)
        me = obs.current.players[my_index]
        if option.area == AreaType.BENCH:
            bench = me.bench or []
            if 0 <= idx < len(bench) and bench[idx]:
                return _si(getattr(bench[idx], "id", None)) == _CARDS["froslass"]
        if option.area == AreaType.ACTIVE:
            active = (me.active or [None])[0]
            if active:
                return _si(getattr(active, "id", None)) == _CARDS["froslass"]
    except Exception:
        pass
    return False


def _needs_retreat_rescue(obs, my_index: int, board, phase) -> bool:
    """Stuck on non-attacker Active without retreat energy — swap or attach out."""
    if phase.primary not in ("AGGRESSION", "OPENING", "HARVEST"):
        return False
    if board.active_is_mega_starmie:
        return False
    if phase.primary == "OPENING" and not board.mega_starmie_on_field:
        return False
    # C2b: HARVEST rescue only when an attacker is waiting on the bench.
    if phase.primary == "HARVEST" and not (
        getattr(board, "mega_froslass_on_field", False)
        or board.mega_starmie_on_field
    ):
        return False
    active = _active_pokemon(obs, my_index)
    if not active:
        return False
    aid = _si(getattr(active, "id", None))
    if aid in _MEGA_EX_IDS:
        return False
    # P4: Dunsparce line is the designated wall — only pull it out when a
    # READY attacker (Mega with water) waits on the bench.
    if aid in (DUNSPARCE_A, DUNSPARCE_B, _CARDS["dudunsparce"]):
        if not _bench_ready_attacker(obs, my_index):
            return False
    energies = [_si(e) for e in (getattr(active, "energies", None) or [])]
    return not can_retreat_pokemon(aid, energies)


def _bench_ready_attacker(obs, my_index: int) -> bool:
    """A Mega attacker with water sitting on our bench (worth promoting)."""
    try:
        for p in (obs.current.players[my_index].bench or []):
            if not p:
                continue
            if _si(getattr(p, "id", None)) in _MEGA_EX_IDS and _has_water_energy(p):
                return True
    except Exception:
        pass
    return False


def _field_id_count(obs, my_index: int, card_id: int) -> int:
    """Copies of card_id currently on our field (active + bench)."""
    n = 0
    try:
        me = obs.current.players[my_index]
        for p in list(me.active or []) + list(me.bench or []):
            if p and _si(getattr(p, "id", None)) == card_id:
                n += 1
    except Exception:
        pass
    return n


def _staryu_field_count(obs, my_index: int) -> int:
    return _field_id_count(obs, my_index, _OC_STARYU)


def _snorunt_field_count(obs, my_index: int) -> int:
    return _field_id_count(obs, my_index, _OC_SNORUNT)


def _staryu_overflow_ban(obs, option, mi: int) -> float:
    """P6/P8: at most 2 Staryu AND at most 2 Snorunt on field.
    Staryu: one Mega Starmie per game. Snorunt: one evolves to Mega Froslass
    (861), one to Froslass (104) — a third egg wastes bench and feeds prizes."""
    cid = 0
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
    elif option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (int(SelectContext.TO_BENCH), int(SelectContext.TO_FIELD)):
            cid = _card_option_id(obs, option, mi)
    if cid == _OC_STARYU and _staryu_field_count(obs, mi) >= 2:
        return -_DOMINATE
    if cid == _OC_SNORUNT:
        # Evolved copies occupy egg slots: 861 online → 1 left (for 104);
        # both online → 0 (a KO frees the slot again naturally).
        cap = 2
        if _field_id_count(obs, mi, _CARDS["mega_froslass_ex"]) > 0:
            cap -= 1
        if _field_id_count(obs, mi, _OC_FROSLASS) > 0:
            cap -= 1
        if _snorunt_field_count(obs, mi) >= cap:
            return -_DOMINATE
    return 0.0


def _discard_option_card_id(obs, option, mi: int) -> int:
    try:
        pi = _si(getattr(option, "playerIndex", None), mi)
        pile = obs.current.players[pi].discard or []
        idx = _si(getattr(option, "index", None), -1)
        if 0 <= idx < len(pile) and pile[idx]:
            return _si(getattr(pile[idx], "id", None))
    except Exception:
        pass
    return 0


def _own_promote_fallback_bonus(obs, option, mi: int) -> float:
    """P4: fallback ranking for OUR SWITCH / TO_ACTIVE bench selects when no
    earlier rule fired (i.e. no ready attacker preference applied) — wall with
    the Dunsparce line, keep attacker eggs (Staryu/Snorunt) and engine pieces
    (Munkidori) on the bench, never feed Meowth ex (2 prizes)."""
    if option.type != OptionType.CARD:
        return 0.0
    try:
        ctx = int(obs.select.context)
    except Exception:
        return 0.0
    if ctx not in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
        return 0.0
    if _si(getattr(option, "playerIndex", None), mi) != mi:
        return 0.0
    if option.area != AreaType.BENCH:
        return 0.0
    pkm = _pokemon_in_area(obs, option.area, _si(getattr(option, "index", None)), mi)
    if not pkm:
        return 0.0
    pid = _si(getattr(pkm, "id", None))
    if pid in _MEGA_EX_IDS:
        return 570.0 + (20.0 if _has_water_energy(pkm) else 0.0)
    if pid == _OC_FROSLASS:
        return 545.0
    if pid in (DUNSPARCE_A, DUNSPARCE_B, _CARDS["dunsparce_a"], _CARDS["dunsparce_b"]):
        return 540.0
    if pid == _CARDS["dudunsparce"]:
        return 535.0
    if pid == _BUDEW_ID:
        return 500.0
    if pid == _FAN_ROTOM_ID:
        return 495.0
    if pid == _OC_MEOWTH_EX:
        return 470.0
    if pid == _MUNKIDORI_ID:
        return 450.0
    if pid == _OC_SNORUNT:
        return 430.0
    if pid == _OC_STARYU:
        return 420.0
    return 0.0


def _attach_energy_to_active(obs, option, my_index: int) -> bool:
    if option.type != OptionType.ATTACH:
        return False
    target = _attach_target_pokemon(obs, option, my_index)
    active = _active_pokemon(obs, my_index)
    if not target or not active or target is not active:
        return False
    eid = _attach_energy_id(obs, option, my_index)
    return eid in _ENERGY_IDS


_OPP_MAX_DMG_TABLE: dict[int, int] | None = None


def _card_max_printed_damage(card_id: int) -> int:
    """Max printed attack damage for a card (lazy table from card data)."""
    global _OPP_MAX_DMG_TABLE
    if _OPP_MAX_DMG_TABLE is None:
        table: dict[int, int] = {}
        try:
            from cg.api import all_attack

            atk_dmg = {
                _si(getattr(a, "attackId", 0)): _si(getattr(a, "damage", 0))
                for a in all_attack()
            }
            for c in all_card_data():
                dmgs = [atk_dmg.get(_si(a), 0) for a in (c.attacks or [])]
                table[_si(c.cardId)] = max(dmgs) if dmgs else 0
        except Exception:
            pass
        _OPP_MAX_DMG_TABLE = table
    return _OPP_MAX_DMG_TABLE.get(_si(card_id), 0)


def _starmie_in_danger(obs, my_index: int) -> bool:
    """S1: Active Mega Starmie likely dies to the opponent's next attack.

    Estimate: remaining HP <= max printed damage of the opponent's Active
    (conservative — ignores energy readiness). Fallback threshold 130 when
    the opponent's damage cannot be estimated. A 1.2x margin was A/B tested
    and rejected: it reopened the 861 window too often (TC dp 31.7->25.7%,
    BC win 75->71.7%) for only -4 games of 861_no_fire."""
    try:
        active = (obs.current.players[my_index].active or [None])[0]
        if not active or _si(getattr(active, "id", None)) != _OC_MEGA_STARMIE:
            return False
        hp = _si(getattr(active, "hp", None), 10**6)
        opp_active = (obs.current.players[1 - my_index].active or [None])[0]
        dmg = _card_max_printed_damage(_si(getattr(opp_active, "id", None))) if opp_active else 0
        if dmg <= 0:
            dmg = 130
        return hp <= dmg
    except Exception:
        return False


def _mega_froslass_window_open(obs, my_index: int, board, phase) -> bool:
    """S2/S4 shared gate: is building/fetching 861 currently sanctioned?

    Insurance only — HARVEST / Starmie gone / Starmie dying. DP completion
    no longer opens the window (user tightened 2026-08-01). Online A/B
    (deck-fixed): insurance-only vs surplus (`or _synergy_core_ready(board)`
    appended below)."""
    if phase.primary == "HARVEST" or not board.mega_starmie_on_field:
        return True
    return _starmie_in_danger(obs, my_index)


def _evolve_mega_froslass_targets_snorunt(obs, option, my_index: int) -> bool:
    """True when EVOLVE option's in-play target is Snorunt."""
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        ipa = _si(getattr(option, "inPlayArea", None), -1)
        ipi = _si(getattr(option, "inPlayIndex", None), -1)
        tgt = None
        if ipa == int(AreaType.ACTIVE):
            tgt = (me.active or [None])[0]
        elif ipa == int(AreaType.BENCH):
            bench = me.bench or []
            if 0 <= ipi < len(bench):
                tgt = bench[ipi]
        if tgt is None:
            # Fallback: raw dict keys may only exist on select options.
            return board_snorunt_fallback(obs, my_index)
        return _si(getattr(tgt, "id", None)) == _OC_SNORUNT
    except Exception:
        return False


def board_snorunt_fallback(obs, my_index: int) -> bool:
    try:
        me = obs.current.players[my_index]
        act = (me.active or [None])[0]
        if act and _si(getattr(act, "id", None)) == _OC_SNORUNT:
            return True
        return any(
            p and _si(getattr(p, "id", None)) == _OC_SNORUNT for p in (me.bench or [])
        )
    except Exception:
        return False


def _dunsparce_on_bench_can_evolve(obs, my_index: int) -> bool:
    try:
        for p in (obs.current.players[my_index].bench or []):
            if p and _si(getattr(p, "id", None)) in (_CARDS["dunsparce_a"], _CARDS["dunsparce_b"]):
                return True
    except Exception:
        pass
    return False


def _mega_starmie_hp_low(obs, my_index: int, ratio: float = 0.55) -> bool:
    try:
        active = (obs.current.players[my_index].active or [None])[0]
        if not active or _si(getattr(active, "id", None)) != _CARDS["mega_starmie_ex"]:
            return False
        hp = _si(getattr(active, "hp", None), 9999)
        max_hp = _si(getattr(active, "maxHp", None), 330)
        return hp < max_hp * ratio
    except Exception:
        return False


def _synergy_window(board, phase) -> bool:
    """My-T2+ window for Froslass (104) + Munkidori bench synergy.

    P1 fix: the window no longer closes at T8 — the DP set (Munkidori +
    Froslass 104) must keep developing until it is actually online, otherwise
    post-Mega games stall with a lone attacker."""
    if board.my_turn_number < 2:
        return False
    return board.my_turn_number <= 8 or not _synergy_core_ready(board)


def _evolve_to_mega_starmie(obs, option, my_index: int) -> bool:
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        hand = me.hand or []
        idx = _si(getattr(option, "index", None), -1)
        if option.area == AreaType.HAND and 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None)) == _CARDS["mega_starmie_ex"]
        if option.area == AreaType.BENCH:
            bench = me.bench or []
            if 0 <= idx < len(bench) and bench[idx]:
                if _si(getattr(bench[idx], "id", None)) != _CARDS["staryu"]:
                    return False
                return any(
                    _si(getattr(c, "id", None)) == _CARDS["mega_starmie_ex"]
                    for c in hand if c
                )
        if option.area == AreaType.ACTIVE:
            active = (me.active or [None])[0]
            if active and _si(getattr(active, "id", None)) == _CARDS["staryu"]:
                return any(
                    _si(getattr(c, "id", None)) == _CARDS["mega_starmie_ex"]
                    for c in hand if c
                )
    except Exception:
        pass
    return False


def _card_option_id(obs, option, my_index: int) -> int:
    """Resolve card ID for CARD / deck-search options."""
    try:
        if option.type != OptionType.CARD:
            return 0
        deck = getattr(obs.select, "deck", None)
        idx = _si(getattr(option, "index", None), -1)
        if deck and 0 <= idx < len(deck) and deck[idx]:
            return _si(getattr(deck[idx], "id", None))
        area = getattr(option, "area", None)
        pi = _si(getattr(option, "playerIndex", None), my_index)
        p = obs.current.players[pi]
        if area == AreaType.HAND:
            hand = p.hand or []
            if 0 <= idx < len(hand) and hand[idx]:
                return _si(getattr(hand[idx], "id", None))
        if area == AreaType.BENCH:
            bench = p.bench or []
            if 0 <= idx < len(bench) and bench[idx]:
                return _si(getattr(bench[idx], "id", None))
        if area == AreaType.ACTIVE:
            active = (p.active or [None])[0]
            if active:
                return _si(getattr(active, "id", None))
    except Exception:
        pass
    return 0


def _select_pick_count(obs, n_options: int) -> int:
    """How many options to return. Prefer maxCount (fixes Poffin underselect).

    MAIN always returns 1 — prevents multi-ATTACH in one decision (ladder bug).
    """
    try:
        ctx = int(obs.select.context)
    except Exception:
        ctx = -1
    if ctx == int(SelectContext.MAIN):
        return 1 if n_options else 0
    try:
        min_c = max(0, int(obs.select.minCount))
        max_c = min(n_options, int(obs.select.maxCount))
    except Exception:
        return 1 if n_options else 0
    if max_c < min_c:
        return max(0, min_c) if n_options else 0
    # Greedy: take as many as the engine allows (Poffin maxCount=2 → pick 2).
    return max_c


def _field_pokemon_ids(obs, my_index: int) -> tuple[int | None, list[int], int]:
    """Return (active_id, bench_ids, bench_open) for live bench budgeting."""
    try:
        me = obs.current.players[my_index]
        active = (me.active or [None])[0]
        active_id = _si(getattr(active, "id", None)) if active else None
        bench_ids = []
        for p in me.bench or []:
            if p:
                pid = _si(getattr(p, "id", None))
                if pid:
                    bench_ids.append(pid)
        bench_open = max(0, 5 - len(bench_ids))
        return active_id, bench_ids, bench_open
    except Exception:
        return None, [], 0


def _obs_can_bench_card(obs, my_index: int, card_id: int) -> bool:
    try:
        from opening_bench import can_bench_card
        active_id, bench_ids, bench_open = _field_pokemon_ids(obs, my_index)
        return can_bench_card(active_id, bench_ids, bench_open, int(card_id))
    except Exception:
        return True


def _collapse_multi_attach(options: list, order: list[int], pick: int) -> list[int]:
    """Keep at most one ATTACH in the returned action list."""
    chosen: list[int] = []
    saw_attach = False
    for idx in order:
        if len(chosen) >= pick:
            break
        if idx < 0 or idx >= len(options):
            continue
        if options[idx].type == OptionType.ATTACH:
            if saw_attach:
                continue
            saw_attach = True
        chosen.append(idx)
    if not chosen and order:
        chosen = [order[0]]
    return chosen


def _sanitize_illegal_attaches(obs, options: list, order: list[int], chosen: list[int], sit: dict) -> list[int]:
    """Last-line filter: never return MAIN ATTACH options hard-banned as illegal."""
    mi = sit.get("my_index", 0)
    cleaned: list[int] = []
    for idx in chosen:
        if idx < 0 or idx >= len(options):
            continue
        opt = options[idx]
        if opt.type == OptionType.ATTACH:
            if _attach_hard_ban_bonus(obs, opt, mi) != 0.0:
                continue
        cleaned.append(idx)
    if cleaned:
        return cleaned
    # Replace with first legal non-illegal-attach from order (prefer END/ATTACK).
    for idx in order:
        if idx < 0 or idx >= len(options):
            continue
        opt = options[idx]
        if opt.type == OptionType.ATTACH and _attach_hard_ban_bonus(obs, opt, mi) != 0.0:
            continue
        return [idx]
    return chosen


def _reorder_poffin_bench(
    obs, options: list, order: list[int], my_index: int, sit: dict | None = None
) -> list[int]:
    """TO_BENCH Poffin: AcquirePlan targets first, then opening / matchup order.

    When ``plan.acquire.targets`` lists benchables (e.g. STARYU + DUNSPARCE
    with held Dudunsparce), those IDs win over the fixed opening table.
    """
    try:
        ctx = int(obs.select.context)
    except Exception:
        return order
    if ctx != int(SelectContext.TO_BENCH):
        return order
    try:
        effect = getattr(obs.select, "effect", None)
        eff_id = _si(getattr(effect, "id", None)) if effect is not None else 0
    except Exception:
        eff_id = 0
    if eff_id != _OC_POFFIN:
        return order
    pri = {cid: i for i, cid in enumerate(POFFIN_OPENING_PRIORITY)}
    plan = sit.get("turn_plan") if sit is not None else None
    acquire_targets = (
        tuple(getattr(getattr(plan, "acquire", None), "targets", ()) or ())
        if plan is not None
        else ()
    )
    if acquire_targets:
        # Strict AcquirePlan order, then residual opening priorities.
        rest = [c for c in POFFIN_OPENING_PRIORITY if c not in acquire_targets]
        pri = {cid: i for i, cid in enumerate(tuple(acquire_targets) + tuple(rest))}
    elif sit is not None and sit.get("matchup_alakazam_confirmed"):
        alak_board = sit.get("board")
        if alak_in_lock_window(alak_board):
            lock_first = alak_lock_pick_order(obs, alak_board, my_index)
            if lock_first:
                rest = [c for c in POFFIN_OPENING_PRIORITY if c not in lock_first]
                pri = {cid: i for i, cid in enumerate(tuple(lock_first) + tuple(rest))}
    elif sit is not None and _going_second(sit.get("board")):
        # Going second: prefer Budew in free Poffin fills once the Staryu seat
        # is safe (Staryu stays ahead in POFFIN_OPENING_PRIORITY when needed).
        board = sit.get("board")
        if board is not None and not bool(getattr(board, "staryu_on_field", False)):
            pass  # keep Staryu-first default
        elif not _field_has_budew(obs, my_index):
            rest = [c for c in POFFIN_OPENING_PRIORITY if c != _BUDEW_ID]
            pri = {cid: i for i, cid in enumerate((_BUDEW_ID,) + tuple(rest))}
    # Simulate filling slots in priority order under role caps.
    active_id, bench_ids, bench_open = _field_pokemon_ids(obs, my_index)
    try:
        from opening_bench import can_bench_card
    except Exception:
        can_bench_card = None  # type: ignore

    def _key(i: int) -> tuple:
        cid = _card_option_id(obs, options[i], my_index)
        under_cap = 0
        if can_bench_card is not None and cid:
            under_cap = 0 if can_bench_card(active_id, bench_ids, bench_open, cid) else 1
        return (under_cap, pri.get(cid, 1000), order.index(i) if i in order else i)

    return sorted(order, key=_key)


def _adrena_selection_bonus(obs, option, board, phase, my_index: int) -> float:
    """Adrena-Brain: pick own damaged Pokémon / opponent target."""
    if not _synergy_window(board, phase):
        return 0.0
    if option.type != OptionType.CARD:
        return 0.0
    try:
        ctx = int(obs.select.context)
    except Exception:
        return 0.0
    pi = _si(getattr(option, "playerIndex", None), my_index)
    if ctx in (int(SelectContext.DAMAGE_COUNTER), int(SelectContext.REMOVE_DAMAGE_COUNTER)):
        pkm = _pokemon_in_area(
            obs, option.area, _si(getattr(option, "index", None)), pi,
        )
        if pi == my_index and _pokemon_damage(pkm) >= 10:
            return _DOMINATE_PLUS
        if pi != my_index and ctx == int(SelectContext.DAMAGE_COUNTER):
            return _DOMINATE
    return 0.0


def _going_second(board) -> bool:
    """True once the engine has assigned firstPlayer and we are not that seat."""
    if board is None:
        return False
    fp = _si(getattr(board, "first_player", -1), -1)
    mi = _si(getattr(board, "my_index", 0), 0)
    return fp in (0, 1) and fp != mi


def _field_has_budew(obs, my_index: int) -> bool:
    try:
        me = obs.current.players[my_index]
        active = (me.active or [None])[0]
        if active and _si(getattr(active, "id", None)) == _BUDEW_ID:
            return True
        return any(
            p and _si(getattr(p, "id", None)) == _BUDEW_ID
            for p in (me.bench or [])
        )
    except Exception:
        return False


def _going_second_budew_bonus(obs, option, sit: dict[str, Any]) -> float:
    """GS policy: if Budew can be dispatched, dispatch it.

    Scope: all going-second games. Yields to TurnPlan mega-must-attack and to
    the last bench seat when the main attacker base is still missing.
    """
    plan = sit.get("turn_plan")
    if plan is not None and plan.combat.attack_required:
        return 0.0
    board = sit.get("board")
    if not _going_second(board):
        return 0.0
    # Ready Mega path owns the turn — do not stall with Budew.
    if plan is not None and (
        plan.facts.active_ready_mega or plan.facts.can_dispatch_bench_mega
    ):
        return 0.0
    if sit.get("mega_ready") and bool(getattr(board, "mega_starmie_on_field", False)):
        return 0.0

    mi = sit["my_index"]
    budew_active = bool(
        _active_pokemon(obs, mi)
        and _si(getattr(_active_pokemon(obs, mi), "id", None)) == _BUDEW_ID
    )
    budew_field = _field_has_budew(obs, mi)
    need_base = bool(plan.gap.need_base) if plan is not None else False
    bench_open = int(getattr(board, "bench_open", 0) or 0)

    # Wall: once Active, stay until the opponent breaks it (or Mega takes over).
    if budew_active and not sit.get("alak_finisher_window") and not sit.get(
        "alak_follow_window"
    ):
        if option.type == OptionType.RETREAT:
            return -_DOMINATE_MID
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return -_DOMINATE_MID
        if option.type == OptionType.ATTACK and _attack_id(option) == _ATK_ITCHY_POLLEN:
            return _DOMINATE

    # Play Budew from hand whenever a legal bench seat exists.
    if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _BUDEW_ID:
        if budew_field or bench_open <= 0:
            return 0.0
        if not _obs_can_bench_card(obs, mi, _BUDEW_ID):
            return 0.0
        # Keep the last open seat for Staryu when the attacker base is missing.
        if need_base and bench_open <= 1 and not bool(
            getattr(board, "staryu_on_field", False)
        ):
            return 0.0
        return _DOMINATE_OPEN

    # Promote benched Budew to Active (Switch preferred, retreat as backup).
    if budew_field and not budew_active:
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return _DOMINATE_OPEN
        if option.type == OptionType.RETREAT and _active_can_retreat(obs, mi):
            return _DOMINATE_OPEN - 10.0
        if option.type == OptionType.CARD:
            try:
                ctx = int(obs.select.context)
            except Exception:
                ctx = -1
            pi = _si(getattr(option, "playerIndex", None), mi)
            if (
                pi == mi
                and ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE))
            ):
                pkm = _pokemon_in_area(
                    obs, option.area, _si(getattr(option, "index", None)), mi,
                )
                if pkm and _si(getattr(pkm, "id", None)) == _BUDEW_ID:
                    return _DOMINATE_OPEN_PATH

    # Free search: take Budew when it is still missing from the field.
    if (
        option.type == OptionType.CARD
        and not budew_field
        and not (need_base and not _hand_has_id(obs, mi, _OC_STARYU))
    ):
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (
            int(SelectContext.TO_BENCH),
            int(SelectContext.TO_HAND),
            int(SelectContext.TO_FIELD),
        ):
            if _card_option_id(obs, option, mi) == _BUDEW_ID:
                return _DOMINATE_OPEN_PATH - 2.0

    # Poffin / Pad chase Budew when going second and it is not online yet.
    if (
        option.type == OptionType.PLAY
        and not budew_field
        and _hand_card_id(obs, option, mi) in (_OC_POFFIN, _OC_POKE_PAD)
    ):
        # Do not steal free search from an open Staryu gap.
        if need_base and not _hand_has_id(obs, mi, _OC_STARYU):
            return 0.0
        if plan is not None and plan.acquire.targets and _BUDEW_ID not in plan.acquire.targets:
            # Exact attacker-line gaps still own the free search window.
            if any(
                t in (_OC_STARYU, _CARDS["mega_starmie_ex"])
                for t in plan.acquire.targets
            ):
                return 0.0
        # Staryu already online → Budew is the free-search job this turn.
        if bool(getattr(board, "staryu_on_field", False)) or bool(
            getattr(board, "mega_starmie_on_field", False)
        ):
            return _DOMINATE_OPEN
        return _DOMINATE_MID + 40.0

    return 0.0


def _damage_select_bonus(obs, option, my_index: int) -> float:
    """SelectContext.DAMAGE — aim attack rider damage (Jetting bench 50) at a
    KO-able opponent target (remaining HP <= 50), else the lowest-HP one."""
    if option.type != OptionType.CARD:
        return 0.0
    try:
        ctx = int(obs.select.context)
    except Exception:
        return 0.0
    if ctx != int(SelectContext.DAMAGE):
        return 0.0
    pi = _si(getattr(option, "playerIndex", None), my_index)
    if pi == my_index:
        return -_DOMINATE  # never aim rider damage at our own board
    pkm = _pokemon_in_area(obs, option.area, _si(getattr(option, "index", None)), pi)
    if pkm is None:
        return 0.0
    hp = _si(getattr(pkm, "hp", None), 10**6)
    if 0 < hp <= 50:
        return _DOMINATE_PLUS  # secures the KO (DK-HIT line)
    return _DOMINATE - min(hp, 500) * 0.1


def _current_max_damage(obs, my_index: int, opp_hand_count: int = 0) -> int:
    """Best single-attack damage our Active can deal this turn (rough estimate
    used for gust planning / prize-path KO checks). 0 when no attack is live."""
    try:
        active = (obs.current.players[my_index].active or [None])[0]
        if not active:
            return 0
        cid = _si(getattr(active, "id", None))
        n_en = len(list(getattr(active, "energies", None) or []))
        has_water = _has_water_energy(active)
        if cid == _CARDS["mega_starmie_ex"]:
            dmg = 120 if has_water else 0          # Jetting Blow
            if n_en >= 3:
                dmg = max(dmg, 210)                # Nebula Beam
            return dmg
        if cid == _CARDS["mega_froslass_ex"]:
            dmg = 50 * max(0, opp_hand_count) if has_water else 0  # Resentful
            if has_water and n_en >= 3:
                dmg = max(dmg, 150)                # Absolute Snow
            return dmg
    except Exception:
        pass
    return 0


def _boss_gust_select_bonus(obs, option, sit: dict[str, Any]) -> float:
    """SP-BOSS-T — Layer1 deterministic gust target choice (was soft S-5b).

    A CARD select over the OPPONENT's bench in a switch-style context is a
    gust-style target pick (Boss's Orders). Rank: KO-able by current attack
    >> prize-path member >> higher prize value >> lower HP."""
    if option.type != OptionType.CARD:
        return 0.0
    mi = sit["my_index"]
    pi = _si(getattr(option, "playerIndex", None), mi)
    if pi == mi:
        return 0.0
    try:
        ctx = int(obs.select.context)
    except Exception:
        return 0.0
    if ctx not in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
        return 0.0
    try:
        if int(option.area) != int(AreaType.BENCH):
            return 0.0
    except Exception:
        return 0.0
    pkm = _pokemon_in_area(obs, option.area, _si(getattr(option, "index", None)), pi)
    if pkm is None:
        return 0.0
    hp = _si(getattr(pkm, "hp", None), 10**6)
    cid = _si(getattr(pkm, "id", None))
    maxdmg = _current_max_damage(obs, mi, int(sit.get("opp_hand_count") or 0))
    score = _DOMINATE_MID
    if maxdmg > 0 and 0 < hp <= maxdmg:
        score += 100.0                              # KO this turn
    if cid in (sit.get("prize_path_ids") or set()):
        score += 40.0
    if cid in _ex_card_set():
        score += 20.0                               # prize value weighting
    return score - min(max(hp, 0), 500) * 0.05      # low HP as tiebreak


def _evolve_to_froslass_104(obs, option, my_index: int) -> bool:
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        hand = me.hand or []
        idx = _si(getattr(option, "index", None), -1)
        if option.area == AreaType.HAND and 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None)) == _CARDS["froslass"]
        if option.area == AreaType.BENCH:
            bench = me.bench or []
            if 0 <= idx < len(bench) and bench[idx]:
                if _si(getattr(bench[idx], "id", None)) != _CARDS["snorunt"]:
                    return False
                return any(
                    _si(getattr(c, "id", None)) == _CARDS["froslass"]
                    for c in hand if c
                )
        if option.area == AreaType.ACTIVE:
            active = (me.active or [None])[0]
            if active and _si(getattr(active, "id", None)) == _CARDS["snorunt"]:
                return any(
                    _si(getattr(c, "id", None)) == _CARDS["froslass"]
                    for c in hand if c
                )
    except Exception:
        pass
    return False


def _evolve_to_mega_froslass_ex(obs, option, my_index: int) -> bool:
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        hand = me.hand or []
        idx = _si(getattr(option, "index", None), -1)
        if option.area == AreaType.HAND and 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None)) == _CARDS["mega_froslass_ex"]
        if option.area == AreaType.BENCH:
            bench = me.bench or []
            if 0 <= idx < len(bench) and bench[idx]:
                base = _si(getattr(bench[idx], "id", None))
                if base not in (_CARDS["snorunt"], _CARDS["froslass"]):
                    return False
                return any(
                    _si(getattr(c, "id", None)) == _CARDS["mega_froslass_ex"]
                    for c in hand if c
                )
        if option.area == AreaType.ACTIVE:
            active = (me.active or [None])[0]
            if active:
                base = _si(getattr(active, "id", None))
                if base in (_CARDS["snorunt"], _CARDS["froslass"]):
                    return any(
                        _si(getattr(c, "id", None)) == _CARDS["mega_froslass_ex"]
                        for c in hand if c
                    )
    except Exception:
        pass
    return False


def _evolve_to_dudunsparce(obs, option, my_index: int) -> bool:
    if option.type != OptionType.EVOLVE:
        return False
    try:
        me = obs.current.players[my_index]
        hand = me.hand or []
        idx = _si(getattr(option, "index", None), -1)
        if option.area == AreaType.HAND and 0 <= idx < len(hand):
            return _si(getattr(hand[idx], "id", None)) == _CARDS["dudunsparce"]
        if option.area == AreaType.BENCH:
            bidx = idx
            bench = me.bench or []
            if 0 <= bidx < len(bench) and bench[bidx]:
                bid = _si(getattr(bench[bidx], "id", None))
                if bid in (_CARDS["dunsparce_a"], _CARDS["dunsparce_b"]):
                    return any(
                        _si(getattr(c, "id", None)) == _CARDS["dudunsparce"]
                        for c in hand if c
                    )
    except Exception:
        pass
    return False


def _planner_score(priority: float) -> float:
    """Map supporter_planner / draw_axis priority into Layer1 band (850–950)."""
    if priority <= 0:
        return 0.0
    return priority


# ── Situation dict ────────────────────────────────────────────────────────────

def _compute_situation(
    obs,
    deck_template: list[int] | None = None,
    agent_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sit: dict[str, Any] = {
        "turn":              0,
        "my_index":          0,
        "prize_self":        6,
        "prize_opp":         6,
        "opp_hand_count":    5,
        "opp_just_took_prize": False,
        "bench_n_self":      0,
        "mega_ready":        False,
        "prize_path_ids":    set(),
        "deck_template":     deck_template,
    }
    try:
        mi = _si(obs.current.yourIndex)
        oi = 1 - mi
        me  = obs.current.players[mi]
        opp = obs.current.players[oi]

        sit["my_index"]       = mi
        sit["turn"]           = _si(obs.current.turn)
        sit["prize_self"]     = len(me.prize or []) or _si(getattr(me, "prizeCount", None), 6)
        sit["prize_opp"]      = len(opp.prize or []) or _si(getattr(opp, "prizeCount", None), 6)
        sit["opp_hand_count"] = _si(getattr(opp, "handCount", None), 5)
        sit["bench_n_self"]   = len([p for p in (me.bench or []) if p])
        sit["mega_ready"]     = _mega_attacker_ready(obs, mi)

        # Detect whether opponent just took a prize this turn (logs contain MOVE_CARD
        # from PRIZE area). Prize count dropped compared to baseline of 6 − turns_taken
        # — simpler heuristic: if opp has fewer prizes than expected and their hand
        # count is higher than expected (they drew a prize card), flag it.
        opp_prizes_taken = 6 - sit["prize_opp"]
        # Rough: if opponent took 1+ prizes and their hand count ≥ 5, they likely
        # just refilled from a prize draw this turn.
        sit["opp_just_took_prize"] = (opp_prizes_taken > 0 and sit["opp_hand_count"] >= 5)

        # Prize-path: opponent targets whose combined prize value covers self
        # prizes left. C2a refinement: KO-able by current firepower first, then
        # prize-value density (prizes per HP), then raw low HP.
        opp_board  = _board_pokemon(opp)
        path_ids: set[int] = set()
        needed = sit["prize_self"]
        maxdmg = _current_max_damage(obs, mi, sit["opp_hand_count"])
        ex_ids = _ex_card_set()

        def _path_key(p):
            hp = _si(getattr(p, "hp", None), 999)
            pv = 2 if _si(getattr(p, "id", None)) in ex_ids else 1
            koable = 1 if (maxdmg > 0 and 0 < hp <= maxdmg) else 0
            return (-koable, -pv / max(hp, 1), hp)

        for p in sorted(opp_board, key=_path_key):
            if needed <= 0: break
            cid = _si(getattr(p, "id", None))
            if cid > 0:
                path_ids.add(cid)
                needed -= (2 if cid in ex_ids else 1)
        sit["prize_path_ids"] = path_ids
        board = build_board_snapshot(obs)
        opened_now = opening_complete(board)
        opening_ever = opened_now or bool(
            agent_state and agent_state.get("opening_complete_this_game")
        )
        phase = compute_phase(board, opening_ever_complete=opening_ever)
        sit["board"] = board
        sit["phase"] = phase
        sit["opening_complete"] = opened_now
        sit["opening_ever_complete"] = opening_ever

        if agent_state is not None:
            _refresh_harvest_ko(agent_state, board)
            sit["harvest_ko_last_turn"] = agent_state.get("harvest_ko_last_turn", False)
            sit["harvest_resentful_fired"] = agent_state.get("harvest_resentful_fired", False)
            sit["agent_state"] = agent_state
            # C2a prize-stuck: my prizes <=2 and no prize taken for >=2 my turns
            my_tn = int(getattr(board, "my_turn_number", 0) or 0)
            pp = agent_state.setdefault(
                "prize_progress", {"last": 6, "turn": 0},
            )
            if sit["prize_self"] < pp["last"]:
                pp["last"] = sit["prize_self"]
                pp["turn"] = my_tn
            sit["prize_stuck"] = bool(
                sit["prize_self"] <= 2 and my_tn - pp["turn"] >= 2
            )
            alak_flags = refresh_alakazam_matchup(
                agent_state, obs, mi, int(getattr(board, "my_turn_number", 0) or 0),
            )
            sit.update(alak_flags)
            sit["alak_doublekill_ready"] = alak_doublekill_ready(obs, mi)
        else:
            sit["harvest_ko_last_turn"] = False
            sit["harvest_resentful_fired"] = False
            sit["agent_state"] = {}
            sit["matchup_alakazam_confirmed"] = False
            sit["alak_finisher_window"] = False
            sit["alak_follow_window"] = False
            sit["alak_budew_ko_last_opp_turn"] = False
            sit["prize_stuck"] = False
        sit["_pokemon_in_area_fn"] = _pokemon_in_area

        gust = _gust_target_on_opp_bench(obs, mi, path_ids)
        # C2a Boss trigger expansion (never during OPENING):
        # SP-BOSS-2 tempo gust — opp Active survives our best attack but a
        # bench target dies to it; SP-BOSS-3 — prize_stuck relaxes the target
        # bar to any KO-able / low-HP bench sitter.
        # P2: gust_koable — a bench target dies to our current firepower this
        # turn (an immediate prize), which exempts Boss from the engine gate.
        gust_koable = False
        if phase.primary != "OPENING":
            try:
                opp_active = (opp.active or [None])[0]
                oa_hp = (
                    _si(getattr(opp_active, "hp", None), 10**6)
                    if opp_active else 10**6
                )
                bench_hps = [
                    _si(getattr(p, "hp", None), 10**6)
                    for p in (opp.bench or []) if p
                ]
                gust_koable = maxdmg > 0 and any(
                    0 < h <= maxdmg for h in bench_hps
                )
                if not gust and oa_hp > maxdmg and gust_koable:
                    gust = True
                elif not gust and sit.get("prize_stuck") and any(
                    0 < h <= max(maxdmg, 70) for h in bench_hps
                ):
                    gust = True
            except Exception:
                pass
        hand = build_hand_context_from_obs(
            obs, gust_target_on_opp_bench=gust, gust_target_koable=gust_koable,
        )
        resources = build_deck_resources(obs, deck_template=deck_template)
        sit["hand"] = hand
        sit["resources"] = resources

        # Cross-turn epoch memory (G1→…→DONE sticky task).
        # Use ever-complete so Starmie KO does not roll epoch back to G1.
        # S-strategy: publish the 861 window so SF2 (insurance Mega) yields
        # to SF3 (DP set) while Starmie is healthy and DP incomplete.
        set_mega_froslass_window(
            _mega_froslass_window_open(obs, mi, board, phase)
        )
        if agent_state is not None:
            mem = agent_state.setdefault("epoch_memory", default_epoch_memory())
            refresh_epoch_memory(
                mem,
                board,
                hand,
                active_can_retreat=_active_can_retreat(obs, mi),
                line_has_water=_line_has_water(obs, mi),
                opening_complete_flag=opening_ever,
            )
            sit["epoch_memory"] = mem
        else:
            sit["epoch_memory"] = None

        # Build the immutable source of truth before migration aliases.  A
        # legacy planner exception must never leave a decision without TurnPlan.
        matchup_name = (
            "alakazam" if sit.get("matchup_alakazam_confirmed") else None
        )
        sit["turn_plan"] = build_turn_plan(
            obs,
            board,
            phase=phase,
            resources=resources,
            matchup=matchup_name,
        )
        sit["doublekill_ready"] = (
            sit["turn_plan"].combat.mode == "DOUBLE_KO"
        )

        d66_bench = _bench_has_id(obs, mi, _CARDS["dudunsparce"])
        dun_evolve = _dunsparce_on_bench_can_evolve(obs, mi)
        hp_low = _mega_starmie_hp_low(obs, mi)

        sit["supporter_dec"] = pick_supporter(
            board, phase, hand, resources, mega_starmie_damaged=hp_low,
            harvest_ko_last_turn=sit["harvest_ko_last_turn"],
            turn_plan=sit["turn_plan"],
        )
        sit["draw_axis_dec"] = pick_draw_axis_action(
            board, phase, hand, resources,
            dunsparce_on_bench_can_evolve=dun_evolve,
            dudunsparce_66_on_bench=d66_bench,
            mega_starmie_hp_low=hp_low,
        )
        if phase.primary == "OPENING":
            sit["opening_route"] = compute_opening_route(
                obs, board, hand, resources, mi,
            )
    except Exception as exc:
        sit["compute_error"] = repr(exc)
    return sit


# ── Soft-dim default weights (Layer 2 only, bounded 0-5) ─────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    # ── Layer 2: Starmie-specific soft dims (trainable) ──────────────────────
    "froslass_harvest":  1.5,   # Evolve Mega Froslass ex when opp hand ≥5 / just took prize
    "jetting_blow_pref": 1.5,   # Prefer Jetting Blow (atk 1487) for bench spread damage
    "nebula_finish":     2.5,   # Prefer Nebula Beam (atk 1488) for confirmed KO
    "boss_gust_path":    2.0,   # Boss's Orders onto prize-path bench target
    # ── Layer 1 baseline dims: tuned for Starmie aggro (NOT Tea Party control) ─
    # Higher evolve: Mega ex evolution is the win condition, always prioritise
    "evolve":        2.5,
    # Higher attach + no bench penalty: bench needs charging fast for Staryu/Snorunt
    "attach":        2.5,
    "bench_penalty": 0.2,    # positive: bench energy attachment is GOOD here
    "active_bonus":  0.1,    # reduced: active is not always the priority target
    # Higher attack: aggro deck, attack every turn possible
    "attack":        3.5,
    # Retreat is a core OPENING REC line (expert gold retreats frequently),
    # and Munkidori handles HP transfer mid-game. Neutral-positive weight.
    "retreat":      1.0,
    # Standard action dims
    "play":          1.2, "ability": 1.2,
    "yes":           0.1, "no":      0.0,
    # Card type scores: Pokemon and energy are premium in this deck
    "card_basic":    1.3, "card_pokemon":  0.8,
    "card_energy":   0.6, "card_trainer":  0.35,
    "damage_target": 1.5, "own_damaged":   0.5,
    "random_noise":  0.02,
}

# Attack IDs from card_db
_ATK_JETTING_BLOW  = 1487   # Mega Starmie ex: 120 + bench 50 (1 Water)
_ATK_NEBULA_BEAM   = 1488   # Mega Starmie ex: 210 ignore effects (3 Colorless)
_ATK_RESENTFUL     = 1240   # Mega Froslass ex: 50×opp_hand (1 Water)
_ATK_ABS_SNOW      = 1241   # Mega Froslass ex: 150 + Sleep (Water+CC)
_ATK_ITCHY_POLLEN  = 323    # Budew: 0 energy, blocks opp Items next turn


# ── Layer 1: hard-rule interceptor ───────────────────────────────────────────

def _layer1_supporter_draw_axis(
    obs, option, sit: dict[str, Any], mi: int, board, phase, hand, resources,
) -> float:
    """supporter_planner + draw_axis → DOMINATE scores (02_draw_axis.md)."""
    cid = _hand_card_id(obs, option, mi) if option.type == OptionType.PLAY else 0
    plan = sit.get("turn_plan")
    must_attack = _fueled_mega_must_attack(board, plan)

    if option.type == OptionType.PLAY and cid == LILLIE:
        forbidden, _rule = lillie_forbidden(
            board, phase, hand, resources, turn_plan=plan,
        )
        if forbidden:
            return -_DOMINATE

    # Salvator: never force when Mega already in hand (expert 35135/33672).
    if option.type == OptionType.PLAY and cid == SALVATOR:
        if hand and _OC_MEGA_STARMIE in hand.hand_ids:
            return -_DOMINATE

    # Fueled Mega owes an attack: only a still-needed Boss prep may claim the
    # supporter slot; dig/66/Poffin never outrank Jetting.
    if must_attack:
        actionable = (
            _actionable_pre_attack(obs, sit, plan.combat) if plan is not None else ()
        )
        if option.type == OptionType.PLAY and cid == _BOSS_ID and "BOSS" in actionable:
            return _DOMINATE_OPEN_PATH
        if option.type in (
            OptionType.PLAY, OptionType.EVOLVE, OptionType.ABILITY,
        ):
            return -_DOMINATE_OPEN_PATH
        if (
            option.type == OptionType.ABILITY
            and _ability_source_id(obs, option, mi) == _CARDS["dudunsparce"]
        ):
            return -_DOMINATE_OPEN_PATH

    sup = sit.get("supporter_dec")
    if sup and sup.action == "PLAY" and option.type == OptionType.PLAY:
        if cid == sup.card_id:
            # Never Layer1-boost supporters when Resentful is LIVE (≥200 dmg).
            # Empty-hand / cut-to-Starmie turns must keep Switch + engine free.
            if (
                _mega_froslass_should_attack(board)
                and not sit.get("harvest_resentful_fired")
                and not _resentful_worthless(int(sit.get("opp_hand_count") or 0))
                and not _starmie_promote_over_froslass(obs, mi, board, sit)
                and _resentful_damage(int(sit.get("opp_hand_count") or 0)) >= 200
            ):
                return -_DOMINATE
            # Gap-driven planner score only — do NOT force supporters above attack
            # just because the slot is still open this turn.
            return _planner_score(sup.priority)

    draw = sit.get("draw_axis_dec")
    if draw and draw.action == "ABILITY_DRAW" and option.type == OptionType.ABILITY:
        if _ability_source_id(obs, option, mi) == _CARDS["dudunsparce"]:
            return _planner_score(draw.priority)

    if draw and draw.action in ("EVOLVE_66",) and _evolve_to_dudunsparce(obs, option, mi):
        return _planner_score(draw.priority)

    if draw and draw.action == "PLAY_306" and option.type == OptionType.PLAY:
        # 306 cut from deck — never dominate playing Dudunsparce ex.
        return -_DOMINATE

    return 0.0


def _bench_has_free_retreat(obs, my_index: int) -> bool:
    try:
        for p in (obs.current.players[my_index].bench or []):
            if not p:
                continue
            pid = _si(getattr(p, "id", None))
            if retreat_cost_for(pid) == 0:
                return True
    except Exception:
        pass
    return False


def _active_has_ignition(obs, my_index: int) -> bool:
    active = _active_pokemon(obs, my_index)
    if not active:
        return False
    try:
        return any(_si(e) == IGNITION for e in (getattr(active, "energies", None) or []))
    except Exception:
        return False


def _staryu_needs_water(obs, my_index: int, board) -> bool:
    if not board.staryu_on_field:
        return False
    try:
        me = obs.current.players[my_index]
        for p in [*(me.active or []), *(me.bench or [])]:
            if p and _si(getattr(p, "id", None)) == _OC_STARYU and not _has_water_energy(p):
                return True
    except Exception:
        pass
    return False


def _pokemon_energy_count(pkm) -> int:
    try:
        return len([e for e in (getattr(pkm, "energies", None) or []) if e is not None])
    except Exception:
        return 0


def _attach_hard_ban_bonus(obs, option, mi: int) -> float:
    """Global ATTACH bans: ≤1 energy per Pokémon; attacker lines = Water Basic only."""
    if option.type != OptionType.ATTACH:
        return 0.0
    target = _attach_target_pokemon(obs, option, mi)
    eid = _attach_energy_id(obs, option, mi)
    if not target or eid not in _ENERGY_IDS:
        return 0.0
    tid = _si(getattr(target, "id", None))

    # HR-E1  At most one energy on any Pokémon.
    if _pokemon_energy_count(target) >= 1:
        return _ATTACH_ILLEGAL

    # HR-E2  Starmie line: Water Basic ONLY (never Dark/Prism/Ignition).
    if tid in (_OC_STARYU, _CARDS["mega_starmie_ex"]):
        if eid != WATER_BASIC and eid != int(EnergyType.WATER):
            return _ATTACH_ILLEGAL

    # HR-E2b  Froslass line (Snorunt / 104 / Mega 861): Water Basic ONLY.
    # Dark/Prism on Snorunt or Mega Froslass is a wasted attach (cannot attack / wrong type).
    if tid in (_OC_SNORUNT, _OC_FROSLASS, _CARDS["mega_froslass_ex"]):
        if eid != WATER_BASIC and eid != int(EnergyType.WATER):
            return _ATTACH_ILLEGAL

    # HR-E2c  With a dry attacker on field, never feed junk (Budew / Fan / Dun line).
    if _dry_attacker_needs_water(obs, mi) and tid in (
        _BUDEW_ID,
        _FAN_ROTOM_ID,
        DUNSPARCE_A,
        DUNSPARCE_B,
        _CARDS["dunsparce_a"],
        _CARDS["dunsparce_b"],
        _CARDS["dudunsparce"],
    ):
        return _ATTACH_ILLEGAL

    # P3 retreat-oil exception: non-attacker Active that cannot retreat may
    # take one energy of any color to enable the swap-out.
    is_retreat_oil = False
    try:
        active = (obs.current.players[mi].active or [None])[0]
        if target is active and tid not in _ATTACKER_LINE_IDS:
            ens = [_si(e) for e in (getattr(active, "energies", None) or [])]
            is_retreat_oil = not can_retreat_pokemon(tid, ens)
    except Exception:
        pass

    # HR-E3 (P3)  Dark/Prism/Ignition: Munkidori ONLY (retreat oil excepted).
    if eid in (DARK_BASIC, int(EnergyType.DARKNESS), _OC_PRISM, IGNITION):
        if tid != _MUNKIDORI_ID and not is_retreat_oil:
            return _ATTACH_ILLEGAL

    # HR-E4 (P3)  Water: attacker lines ONLY (retreat oil excepted).
    if eid in (WATER_BASIC, int(EnergyType.WATER)):
        if tid not in (
            _OC_STARYU,
            _CARDS["mega_starmie_ex"],
            _OC_SNORUNT,
            _OC_FROSLASS,
            _CARDS["mega_froslass_ex"],
        ) and not is_retreat_oil:
            return _ATTACH_ILLEGAL

    return 0.0


def _dry_attacker_needs_water(obs, my_index: int) -> bool:
    """True if any Starmie/Froslass attacker on field still lacks water."""
    try:
        me = obs.current.players[my_index]
        for p in list(me.active or []) + list(me.bench or []):
            if not p:
                continue
            tid = _si(getattr(p, "id", None))
            if tid in (
                _OC_STARYU,
                _CARDS["mega_starmie_ex"],
                _CARDS["mega_froslass_ex"],
            ) and not _has_water_energy(p):
                return True
    except Exception:
        pass
    return False


def _attach_priority_bonus(
    obs, option, mi: int, board, phase, hand, *, alak_matchup: bool = False,
) -> float:
    """Prefer productive ATTACH when it closes a real gap (not every-turn fill).

    Default (non-Alakazam): dry attacker water FIRST (Mega / Staryu that can
    come online this turn), then Munk dark. Alakazam matchup is the exception
    where DP (Munk dark) may outrank spare-Staryu water.
    """
    if option.type == OptionType.END:
        if hand and getattr(hand, "energy_attached", False):
            return 0.0
        # Only hard-block blank END when a dry attacker would otherwise fire unfueled.
        if _hand_has_water_energy(obs, mi) and _dry_attacker_needs_water(obs, mi):
            return _ATTACH_ILLEGAL  # deeper than -DOMINATE so END never ties illegal attaches
        # Munk dark / Run Away no longer force the turn open — holding is fine.
        return 0.0

    if option.type != OptionType.ATTACH:
        return 0.0
    if hand and getattr(hand, "energy_attached", False):
        return 0.0

    target = _attach_target_pokemon(obs, option, mi)
    eid = _attach_energy_id(obs, option, mi)
    if not target or eid not in _ENERGY_IDS:
        return 0.0
    tid = _si(getattr(target, "id", None))
    if _pokemon_energy_count(target) >= 1:
        return 0.0

    dry_atk = _dry_attacker_needs_water(obs, mi)
    water_in_hand = _hand_has_water_energy(obs, mi)

    # Soft-ban junk oil when dry attackers exist (hard ban also in _attach_hard_ban).
    if dry_atk and tid in (
        _BUDEW_ID, _FAN_ROTOM_ID, DUNSPARCE_A, DUNSPARCE_B, _CARDS["dudunsparce"],
    ):
        return _ATTACH_ILLEGAL

    # Water onto dry Mega attackers — 861 before Starmie when both dry (fire loop).
    if eid == WATER_BASIC or eid == int(EnergyType.WATER):
        if tid == _CARDS["mega_froslass_ex"] and not _has_water_energy(target):
            return _DOMINATE_OPEN_PATH
        if tid == _CARDS["mega_starmie_ex"] and not _has_water_energy(target):
            # Demote if a dry 861 still needs the water this turn.
            if _field_has_dry_mega_froslass(obs, mi):
                return _DOMINATE_MID
            return _DOMINATE_OPEN_PATH if board.active_is_mega_starmie else _DOMINATE_PLUS
        if tid == _OC_STARYU and not _has_water_energy(target):
            # Prefer Staryu water when no dry Mega still needs it.
            if not _field_has_dry_mega(obs, mi):
                # Alakazam-only: Munk dark may outrank spare-Staryu water.
                if (
                    alak_matchup
                    and _munk_needs_dark(obs, mi)
                    and _hand_has_dark_energy(obs, mi)
                ):
                    return _DOMINATE_MID - 40.0
                return _DOMINATE_PLUS  # normal: fuel the attacker egg first
            return _DOMINATE_MID
        # Water onto Snorunt is legal but low-value while dry Mega exists.
        if tid == _OC_SNORUNT and _field_has_dry_mega(obs, mi):
            return -_DOMINATE_MID

    # Dark/Prism onto Munk — never before a dry attacker that can take water
    # this turn, except Alakazam matchup (DP disruption is the plan).
    if (
        eid in (DARK_BASIC, _OC_PRISM, int(EnergyType.DARKNESS))
        and tid == _MUNKIDORI_ID
        and not _has_darkness_energy(target)
    ):
        if dry_atk and water_in_hand and not alak_matchup:
            return -_DOMINATE_MID  # water the attacker first
        return _DOMINATE_OPEN_PATH if phase.primary == "HARVEST" else _DOMINATE

    return 0.0


def _field_has_dry_mega(obs, my_index: int) -> bool:
    try:
        me = obs.current.players[my_index]
        for p in list(me.active or []) + list(me.bench or []):
            if not p:
                continue
            tid = _si(getattr(p, "id", None))
            if tid in (_CARDS["mega_starmie_ex"], _CARDS["mega_froslass_ex"]) and not _has_water_energy(p):
                return True
    except Exception:
        pass
    return False


def _field_has_dry_mega_froslass(obs, my_index: int) -> bool:
    try:
        me = obs.current.players[my_index]
        for p in list(me.active or []) + list(me.bench or []):
            if not p:
                continue
            if (
                _si(getattr(p, "id", None)) == _CARDS["mega_froslass_ex"]
                and not _has_water_energy(p)
            ):
                return True
    except Exception:
        pass
    return False


def _bench_mega_froslass_with_water(obs, my_index: int):
    """Return (bench_index, pokemon) for Mega Froslass with water, else (None, None)."""
    try:
        for i, p in enumerate(obs.current.players[my_index].bench or []):
            if (
                p
                and _si(getattr(p, "id", None)) == _CARDS["mega_froslass_ex"]
                and _has_water_energy(p)
            ):
                return i, p
    except Exception:
        pass
    return None, None


def _munk_needs_dark(obs, my_index: int) -> bool:
    try:
        for p in _board_pokemon(obs.current.players[my_index]):
            if _si(getattr(p, "id", None)) == _MUNKIDORI_ID and not _has_darkness_energy(p):
                return True
    except Exception:
        pass
    return False


def _froslass_promote_needed(obs, my_index: int, board, sit: dict[str, Any]) -> bool:
    """Bench 861+water should come Active only when the 861 line is worth it.

    Value gate: contested / tiny opp hands do not force a promote when a fueled
    Starmie is already attacking. Never cut for empty-hand Resentful.
    """
    if board.active_is_mega_froslass:
        return False
    if _resentful_worthless(int(sit.get("opp_hand_count") or 0)):
        return False
    _, bench_mf = _bench_mega_froslass_with_water(obs, my_index)
    if bench_mf is None:
        return False
    if not _froslass_line_worth(obs, my_index, board, sit):
        return False
    if not sit.get("harvest_resentful_fired"):
        # Do not yank a ready Starmie attacker for a mediocre 861 window.
        if board.active_is_mega_starmie and board.active_has_water:
            return _resentful_damage(int(sit.get("opp_hand_count") or 0)) >= 200
        return True
    return not (board.active_is_mega_starmie and board.active_has_water)


def _attach_retreat_fuel_bonus(obs, option, mi: int, board, phase) -> float:
    """Ban free-65 attach; Ignition only if same-turn retreat possible; prefer non-water fuel."""
    if option.type != OptionType.ATTACH:
        return 0.0
    target = _attach_target_pokemon(obs, option, mi)
    eid = _attach_energy_id(obs, option, mi)
    if not target or eid not in _ENERGY_IDS:
        return 0.0
    tid = _si(getattr(target, "id", None))

    # Ban attach onto free-retreat Dunsparce A (65).
    if tid == DUNSPARCE_A or tid == _CARDS["dunsparce_a"]:
        return -_DOMINATE

    active = _active_pokemon(obs, mi)
    on_active = bool(active and target is active)
    _, bench_mega_w = _bench_mega_starmie_with_water(obs, mi)
    need_promote = bool(
        phase.primary == "OPENING"
        and bench_mega_w is not None
        and not (board.active_is_mega_starmie and board.active_has_water)
    )

    # T2+: Fan Rotom is Call-dead — no oil, unless we must retreat it to promote Mega+W.
    if tid == _FAN_ROTOM_ID and board.my_turn_number >= 2:
        if not (on_active and need_promote):
            return -_DOMINATE

    if not on_active:
        return 0.0

    active_energies = [_si(e) for e in (getattr(active, "energies", None) or [])]
    # HR-E1 already bans 2nd energy; no retreat-oil second attach.
    if len(active_energies) >= 1:
        return -_DOMINATE

    already_can = can_retreat_pokemon(tid, active_energies)
    free_bench = _bench_has_free_retreat(obs, mi)
    cost = retreat_cost_for(tid)

    # Ignition: only as same-turn retreat fuel (else EOT discard).
    if eid == IGNITION:
        if already_can or cost == 0:
            return -_DOMINATE
        if need_promote or free_bench or cost >= 1:
            return _DOMINATE_OPEN_PATH if need_promote else _DOMINATE_PLUS
        return -_DOMINATE

    # Never spend Water Basic as Active retreat oil while Starmie line still needs it.
    # (Starmie line itself is hard-banned from non-water by HR-E2.)
    if eid == WATER_BASIC and _staryu_needs_water(obs, mi, board):
        if tid not in (_OC_STARYU, _CARDS["mega_starmie_ex"]) and cost > 0 and not already_can:
            return -_DOMINATE_MID
        return 0.0

    # Dark (not Prism) retreat fuel on non-Starmie Active: free-bench OR Mega promote.
    if (
        eid == DARK_BASIC
        and tid not in (_OC_STARYU, _CARDS["mega_starmie_ex"])
        and cost > 0
        and not already_can
    ):
        if need_promote:
            return _DOMINATE_OPEN_PATH
        if free_bench:
            return _DOMINATE

    return 0.0


def _crispin_attach_select_bonus(obs, option, sit: dict[str, Any]) -> float:
    """Hard bans for Crispin nested ATTACH_TO / ATTACH_FROM (not MAIN ATTACH)."""
    if option.type != OptionType.CARD:
        return 0.0
    try:
        ctx = int(obs.select.context)
    except Exception:
        return 0.0
    mi = sit["my_index"]

    if ctx == int(SelectContext.ATTACH_TO):
        eid = _card_option_id(obs, option, mi)
        if eid == DARK_BASIC:
            if _munk_needs_dark(obs, mi):
                return 0.0
            return _ATTACH_ILLEGAL
        if eid == WATER_BASIC and (
            _dry_attacker_needs_water(obs, mi) or _field_has_dry_mega(obs, mi)
        ):
            return _DOMINATE_OPEN_PATH
        return 0.0

    if ctx == int(SelectContext.ATTACH_FROM):
        agent_state = sit.get("agent_state") or {}
        eid = agent_state.get("pending_crispin_energy_id")
        if eid is None:
            # Fallback: if ATTACH_TO left a single energy visible in select.deck
            # matching prior choice — otherwise stay neutral.
            return 0.0
        tid = _card_option_id(obs, option, mi)
        if eid == DARK_BASIC:
            if tid in _ATTACKER_LINE_IDS:
                return _ATTACH_ILLEGAL
            if tid == _MUNKIDORI_ID:
                return _DOMINATE_OPEN_PATH
            return 0.0
        if eid == WATER_BASIC:
            if tid in _JUNK_OIL_IDS and _dry_attacker_needs_water(obs, mi):
                return _ATTACH_ILLEGAL
            if tid in (
                _OC_STARYU,
                _CARDS["mega_starmie_ex"],
                _CARDS["mega_froslass_ex"],
            ):
                return _DOMINATE_OPEN_PATH
        return 0.0

    return 0.0


def _turn_plan_required_option(obs, option, sit: dict[str, Any], requirement: str) -> bool:
    """Whether an option performs the planner's next pre-attack action."""
    mi = sit["my_index"]
    if requirement == "ADRENA":
        return (
            option.type == OptionType.ABILITY
            and _ability_source_id(obs, option, mi) == _MUNKIDORI_ID
        )
    if requirement == "BOSS":
        return (
            option.type == OptionType.PLAY
            and _hand_card_id(obs, option, mi) == _BOSS_ID
        )
    if requirement == "EVOLVE_104":
        return (
            option.type == OptionType.EVOLVE
            and _evolve_to_froslass_104(obs, option, mi)
        )
    if requirement == "ATTACH_DARK":
        target = _attach_target_pokemon(obs, option, mi)
        return (
            option.type == OptionType.ATTACH
            and _attach_energy_id(obs, option, mi) == DARK_BASIC
            and target is not None
            and _si(getattr(target, "id", None)) == _MUNKIDORI_ID
        )
    if requirement == "DISPATCH":
        if option.type == OptionType.RETREAT:
            return True
        if option.type == OptionType.PLAY:
            return _hand_card_id(obs, option, mi) == _OC_SWITCH
        if option.type == OptionType.ATTACH:
            return _attach_energy_to_active(obs, option, mi)
        if option.type == OptionType.CARD:
            try:
                ctx = int(obs.select.context)
            except Exception:
                return False
            if ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
                return _card_option_id(obs, option, mi) in _MEGA_EX_IDS
    return False


def _munk_can_adrena(obs, my_index: int) -> bool:
    """Dark Munkidori on field with transferable damage — Adrena is live."""
    try:
        me = obs.current.players[my_index]
        field = [*(me.active or []), *(me.bench or [])]
        has_dark_munk = any(
            p
            and _si(getattr(p, "id", None)) == _MUNKIDORI_ID
            and any(_si(e) == DARK_BASIC for e in (getattr(p, "energies", None) or []))
            for p in field
            if p
        )
        if not has_dark_munk:
            return False
        return any(
            p
            and _si(getattr(p, "maxHp", None), 0) - _si(getattr(p, "hp", None), 0) >= 10
            for p in field
            if p
        )
    except Exception:
        return False


def _pre_attack_req_still_needed(obs, sit: dict[str, Any], requirement: str) -> bool:
    """Board/hand truth for whether a required_before_attack step is still open.

    Unlike scanning select_options (often empty during unit tests / partial
    selects), this never treats every requirement as actionable by default.
    """
    mi = sit["my_index"]
    plan = sit.get("turn_plan")
    board = sit.get("board")
    try:
        me = obs.current.players[mi]
        supporter_played = bool(getattr(me, "supporterPlayed", False))
        energy_attached = bool(getattr(me, "energyAttached", False))
    except Exception:
        supporter_played, energy_attached = False, False

    if requirement == "BOSS":
        return (
            not supporter_played
            and _hand_has_id(obs, mi, _BOSS_ID)
            and plan is not None
            and plan.combat.boss_target is not None
        )
    if requirement == "ADRENA":
        return _munk_can_adrena(obs, mi)
    if requirement == "EVOLVE_104":
        return _hand_has_id(obs, mi, _OC_FROSLASS) and bool(
            getattr(board, "snorunt_on_field", False)
        )
    if requirement == "ATTACH_DARK":
        return (
            not energy_attached
            and _hand_has_dark_energy(obs, mi)
            and bool(getattr(board, "munkidori_on_field", False))
            and not bool(getattr(board, "munkidori_has_dark", False))
        )
    if requirement == "DISPATCH":
        if board is None or board.active_is_mega_starmie or plan is None:
            return False
        return bool(getattr(plan.facts, "can_dispatch_bench_mega", False))
    return False


def _actionable_pre_attack(obs, sit: dict[str, Any], combat) -> tuple[str, ...]:
    """Requirements that remain needed AND are live in the current option list.

    Critical: when select_options is non-empty, ghost preps (e.g. ADRENA marked
    needed but ability not offered) must NOT block Jetting — that leak let
    Poffin/supporters win soft-score ties online (55202093).
    When select_options is empty (unit tests), fall back to board/hand need.
    """
    reqs = getattr(combat, "required_before_attack", ()) or ()
    if not reqs:
        return ()
    options = sit.get("select_options") or ()
    out: list[str] = []
    for req in reqs:
        if not _pre_attack_req_still_needed(obs, sit, req):
            continue
        if options:
            if not any(_turn_plan_required_option(obs, o, sit, req) for o in options):
                continue
        out.append(req)
    return tuple(out)


def _must_attack_closeout_bonus(obs, option, sit: dict[str, Any]) -> float:
    """Early hard gate: fueled Active Mega must close with an attack.

    Runs before Alak/ignition-retreat/acquire so construction never outranks
    Jetting/Resentful. Ghost pre-attack reqs do not block the attack.
    """
    board = sit.get("board")
    plan = sit.get("turn_plan")
    if board is None or not _fueled_mega_must_attack(board, plan):
        return 0.0

    mi = sit["my_index"]
    cut_to_starmie = (
        board.active_is_mega_froslass
        and _starmie_promote_over_froslass(obs, mi, board, sit)
    )
    combat = getattr(plan, "combat", None) if plan is not None else None
    live_prep = (
        _actionable_pre_attack(obs, sit, combat) if combat is not None else ()
    )

    if live_prep:
        for req in live_prep:
            if _turn_plan_required_option(obs, option, sit, req):
                return _DOMINATE_OPEN_PATH
        if option.type in (
            OptionType.ATTACK,
            OptionType.END,
            OptionType.PLAY,
            OptionType.ATTACH,
            OptionType.EVOLVE,
            OptionType.ABILITY,
            OptionType.RETREAT,
        ):
            return -_DOMINATE_OPEN_PATH
        return 0.0

    if option.type == OptionType.END:
        return -_DOMINATE_OPEN_PATH

    if option.type == OptionType.ATTACK:
        attack_id = _attack_id(option)
        if board.active_is_mega_starmie:
            if (
                attack_id == _ATK_NEBULA_BEAM
                and plan is not None
                and plan.facts.opp_active
                and 0 < plan.facts.opp_active.hp <= 210
            ):
                return _DOMINATE_OPEN_PATH + 20.0
            if attack_id == _ATK_JETTING_BLOW:
                return _DOMINATE_OPEN_PATH
            if attack_id == _ATK_NEBULA_BEAM:
                return _DOMINATE_OPEN_PATH - 10.0
            return -_DOMINATE
        if board.active_is_mega_froslass:
            if attack_id in (_ATK_RESENTFUL, _ATK_ABS_SNOW):
                return _DOMINATE_OPEN_PATH
            return -_DOMINATE
        return 0.0

    if cut_to_starmie:
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return _DOMINATE_OPEN_PATH
        if option.type == OptionType.RETREAT and _active_can_retreat(obs, mi):
            return _DOMINATE_OPEN_PATH

    # Fueled Starmie: never Switch/Retreat away from the attack.
    if board.active_is_mega_starmie and board.active_has_water and not cut_to_starmie:
        if option.type == OptionType.RETREAT:
            return -_DOMINATE_OPEN_PATH
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return -_DOMINATE_OPEN_PATH

    if option.type in (
        OptionType.PLAY,
        OptionType.ATTACH,
        OptionType.EVOLVE,
        OptionType.ABILITY,
        OptionType.RETREAT,
    ):
        return -_DOMINATE_OPEN_PATH
    return 0.0


def _turn_plan_hard_bonus(obs, option, sit: dict[str, Any]) -> float:
    """Translate TurnPlan into the small hard overlay that legacy rules consume."""
    plan = sit.get("turn_plan")
    if plan is None:
        return 0.0
    mi = sit["my_index"]
    board = sit.get("board")

    # Nested search/recovery/discard choices all use AcquirePlan.targets.
    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        cid = (
            _discard_option_card_id(obs, option, mi)
            if getattr(option, "area", None) == AreaType.DISCARD
            else _card_option_id(obs, option, mi)
        )
        pi = _si(getattr(option, "playerIndex", None), mi)
        index = _si(getattr(option, "index", None), -1)
        boss_target = plan.combat.boss_target
        if (
            boss_target is not None
            and pi != mi
            and ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE))
        ):
            return (
                _DOMINATE_OPEN_PATH
                if index == boss_target.index
                else -_DOMINATE
            )
        rider = plan.combat.rider_target
        if rider is not None and pi != mi and ctx in (
            int(SelectContext.DAMAGE_COUNTER),
            int(SelectContext.DAMAGE),
        ):
            return (
                _DOMINATE_OPEN_PATH
                if index == rider.index
                else -_DOMINATE
            )
        if ctx == int(SelectContext.DISCARD):
            value = discard_value(cid, plan)
            if value >= 8_000:
                return -_DOMINATE_OPEN_PATH
            if value <= 30:
                return _DOMINATE_OPEN_PATH
            if value <= 100:
                return _DOMINATE
        if (
            ctx == int(SelectContext.TO_HAND)
            and getattr(option, "area", None) == AreaType.DISCARD
            and plan.acquire.recover_target is not None
        ):
            return (
                _DOMINATE_OPEN_PATH
                if cid == plan.acquire.recover_target
                else -_DOMINATE
            )
        if ctx in (
            int(SelectContext.TO_HAND),
            int(SelectContext.TO_BENCH),
            int(SelectContext.TO_FIELD),
        ) and plan.acquire.targets:
            if cid in plan.acquire.targets:
                return _DOMINATE_OPEN_PATH - plan.acquire.targets.index(cid)
            return -_DOMINATE

    combat = plan.combat
    must_attack = _fueled_mega_must_attack(board, plan)

    # Must-attack closeout runs BEFORE acquire PLAY boosts — otherwise Poffin /
    # Pad sources at OPEN_PATH outrank Jetting and recreate online empty turns.
    if must_attack:
        # 861 value-cut: allow Switch/Retreat onto a fueled bench Starmie.
        cut_to_starmie = (
            board is not None
            and board.active_is_mega_froslass
            and _starmie_promote_over_froslass(obs, mi, board, sit)
        )
        # Always allow a still-needed prep option that THIS choice performs
        # (Adrena / Boss / DP), even when select_options is empty in tests.
        for req in combat.required_before_attack or ():
            if (
                _pre_attack_req_still_needed(obs, sit, req)
                and _turn_plan_required_option(obs, option, sit, req)
            ):
                return _DOMINATE_OPEN_PATH

        actionable = _actionable_pre_attack(obs, sit, combat)
        if actionable:
            # A different prep is still open — do not attack/END/misc yet.
            if option.type in (
                OptionType.ATTACK,
                OptionType.END,
                OptionType.PLAY,
                OptionType.ATTACH,
                OptionType.EVOLVE,
                OptionType.ABILITY,
                OptionType.RETREAT,
            ):
                return -_DOMINATE_OPEN_PATH

        if option.type == OptionType.END:
            return -_DOMINATE_OPEN_PATH

        if option.type == OptionType.ATTACK:
            attack_id = _attack_id(option)
            if plan.facts.active_id == _OC_MEGA_STARMIE or (
                board is not None and board.active_is_mega_starmie
            ):
                if combat.mode == "DOUBLE_KO":
                    return (
                        _DOMINATE_OPEN_PATH
                        if attack_id == _ATK_JETTING_BLOW
                        else -_DOMINATE
                    )
                # Nebula KO outranks Jetting; non-KO Nebula stays below Jetting.
                if (
                    attack_id == _ATK_NEBULA_BEAM
                    and plan.facts.opp_active
                    and 0 < plan.facts.opp_active.hp <= 210
                ):
                    return _DOMINATE_OPEN_PATH + 20.0
                if attack_id == _ATK_JETTING_BLOW:
                    return _DOMINATE_OPEN_PATH
                if attack_id == _ATK_NEBULA_BEAM:
                    return _DOMINATE_OPEN_PATH - 10.0
                return -_DOMINATE
            if plan.facts.active_id == _CARDS["mega_froslass_ex"] or (
                board is not None and board.active_is_mega_froslass
            ):
                if attack_id in (_ATK_RESENTFUL, _ATK_ABS_SNOW):
                    return _DOMINATE_OPEN_PATH
                return -_DOMINATE
            if is_basic_attack_forbidden(plan.facts.active_id, plan):
                opp = plan.facts.opp_active
                direct_win = bool(
                    opp
                    and plan.facts.prize_self <= opp.prizes
                    and opp.hp <= _card_max_printed_damage(plan.facts.active_id)
                )
                return _DOMINATE_ATTACK if direct_win else -_DOMINATE_OPEN_PATH

        # Ban switching off a fueled Starmie that still owes an attack.
        if (
            board is not None
            and board.active_is_mega_starmie
            and board.active_has_water
            and not cut_to_starmie
        ):
            if option.type == OptionType.RETREAT:
                return -_DOMINATE_OPEN_PATH
            if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
                return -_DOMINATE_OPEN_PATH

        if cut_to_starmie:
            if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
                return _DOMINATE_OPEN_PATH
            if option.type == OptionType.RETREAT and _active_can_retreat(obs, mi):
                return _DOMINATE_OPEN_PATH

        # Generic construction is illegal once the Mega can fire.
        if option.type in (
            OptionType.PLAY,
            OptionType.ATTACH,
            OptionType.EVOLVE,
            OptionType.ABILITY,
            OptionType.RETREAT,
        ):
            return -_DOMINATE_OPEN_PATH

    # DISPATCH / pre-promote: attack_required but Active is not yet the fueled Mega.
    elif combat.attack_required:
        actionable = _actionable_pre_attack(obs, sit, combat)
        if actionable:
            wanted = actionable[0]
            if _turn_plan_required_option(obs, option, sit, wanted):
                return _DOMINATE_OPEN_PATH
            if option.type in (
                OptionType.ATTACK,
                OptionType.END,
                OptionType.PLAY,
                OptionType.ATTACH,
                OptionType.EVOLVE,
                OptionType.ABILITY,
                OptionType.RETREAT,
            ):
                return -_DOMINATE_OPEN_PATH
        if option.type == OptionType.END:
            return -_DOMINATE_OPEN_PATH
        if option.type == OptionType.ATTACK:
            if is_basic_attack_forbidden(plan.facts.active_id, plan):
                opp = plan.facts.opp_active
                direct_win = bool(
                    opp
                    and plan.facts.prize_self <= opp.prizes
                    and opp.hp <= _card_max_printed_damage(plan.facts.active_id)
                )
                return _DOMINATE_ATTACK if direct_win else -_DOMINATE_OPEN_PATH
            return -_DOMINATE_OPEN_PATH
        if option.type in (
            OptionType.PLAY,
            OptionType.ATTACH,
            OptionType.EVOLVE,
            OptionType.ABILITY,
            OptionType.RETREAT,
        ):
            return -_DOMINATE_OPEN_PATH

    # Gap-driven search source and Ultra Ball gate (non-must-attack turns).
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == _OC_ULTRA_BALL:
            return _DOMINATE if plan.acquire.ball_allowed else -_DOMINATE_OPEN_PATH
        if cid in plan.acquire.targets:
            return _DOMINATE_OPEN_PATH
        if cid in plan.acquire.sources:
            return _DOMINATE_OPEN_PATH
        if cid in (DUNSPARCE_A, DUNSPARCE_B):
            duns_n = sum(
                x in (DUNSPARCE_A, DUNSPARCE_B, _CARDS["dudunsparce"])
                for x in (plan.facts.bench_ids + (plan.facts.active_id,))
            )
            if (duns_n == 0 and not plan.draw.allow_first_dunsparce) or (
                duns_n == 1 and not plan.draw.allow_second_dunsparce
            ) or duns_n >= 2:
                return -_DOMINATE

    if (
        option.type == OptionType.ABILITY
        and _ability_source_id(obs, option, mi) == _CARDS["dudunsparce"]
        and not plan.draw.allow_run_away_draw
    ):
        return -_DOMINATE

    if (
        option.type == OptionType.EVOLVE
        and _evolve_to_mega_froslass_ex(obs, option, mi)
        and "BUILD_861" in plan.forbidden_actions
    ):
        return -_DOMINATE_OPEN_PATH

    return 0.0


def _hard_rule_bonus(obs, option, sit: dict[str, Any]) -> float:
    """Return dominate score if a hard rule fires; 0 otherwise."""
    mi = sit["my_index"]
    turn = sit["turn"]
    board = sit.get("board") or build_board_snapshot(obs)
    phase = sit.get("phase") or compute_phase(board)
    prize_ids = sit["prize_path_ids"]
    hand = sit.get("hand")
    resources = sit.get("resources")

    if hand is None or resources is None:
        gust = _gust_target_on_opp_bench(obs, mi, prize_ids)
        hand = build_hand_context_from_obs(obs, gust_target_on_opp_bench=gust)
        resources = build_deck_resources(obs, deck_template=sit.get("deck_template"))

    # ── Ops-fix priority block (before Layer1 axis) ─────────────────────────
    # Global ATTACH bans first so illegal energy never loses to supporter/draw axis.
    attach_ban = _attach_hard_ban_bonus(obs, option, mi)
    if attach_ban != 0.0:
        return attach_ban

    crispin_ban = _crispin_attach_select_bonus(obs, option, sit)
    if crispin_ban != 0.0:
        return crispin_ban

    # Fueled Mega closeout — before Alak / acquire / ignition-retreat so
    # Poffin and supporters cannot soft-tie past Jetting (online 55202093).
    must_close = _must_attack_closeout_bonus(obs, option, sit)
    if must_close != 0.0:
        return must_close

    # When TurnPlan already named a rider/boss target, legacy selectors must
    # not preempt it (especially 51–80 HP riders that old DAMAGE scoring ranks
    # by lowest HP instead of role priority).
    plan = sit.get("turn_plan")
    plan_owns_rider = bool(plan and plan.combat.rider_target is not None)
    plan_owns_boss = bool(plan and plan.combat.boss_target is not None)

    if not plan_owns_rider:
        dmg_sel = _damage_select_bonus(obs, option, mi)
        if dmg_sel != 0.0:
            return dmg_sel

    # Matchup-ALAK Plan B (confirmed only): Budew lock / finisher Stamp+Jetting.
    alak_bonus = alakazam_plan_b_hard_bonus(
        obs,
        option,
        sit,
        dominate=_DOMINATE,
        dominate_mid=_DOMINATE_MID,
        dominate_plus=_DOMINATE_PLUS,
        dominate_open=_DOMINATE_OPEN,
        dominate_attack=_DOMINATE_ATTACK,
        hand_card_id_fn=_hand_card_id,
        attack_id_fn=_attack_id,
        itchy_pollen_id=_ATK_ITCHY_POLLEN,
        jetting_id=_ATK_JETTING_BLOW,
        option_type_play=OptionType.PLAY,
        option_type_attack=OptionType.ATTACK,
        option_type_evolve=OptionType.EVOLVE,
        option_type_card=OptionType.CARD,
        select_switch_contexts=(
            int(SelectContext.SWITCH),
            int(SelectContext.TO_ACTIVE),
        ),
        dominate_path=_DOMINATE_OPEN_PATH,
        attach_target_fn=_attach_target_pokemon,
        attach_energy_fn=_attach_energy_id,
        evolve_104_fn=_evolve_to_froslass_104,
        card_option_id_fn=_card_option_id,
        option_type_attach=OptionType.ATTACH,
        option_type_retreat=OptionType.RETREAT,
        select_search_contexts=(
            int(SelectContext.TO_BENCH),
            int(SelectContext.TO_HAND),
            int(SelectContext.TO_FIELD),
        ),
    )
    if alak_bonus != 0.0:
        return alak_bonus

    turn_plan_bonus = _turn_plan_hard_bonus(obs, option, sit)
    if turn_plan_bonus != 0.0:
        return turn_plan_bonus

    # Going-second Budew dispatch: play / promote / Itchy whenever legal.
    # Runs after TurnPlan so mega-must-attack and exact acquire targets win.
    gs_budew = _going_second_budew_bonus(obs, option, sit)
    if gs_budew != 0.0:
        return gs_budew

    stamp_prot = protect_unfair_stamp_discard(
        obs, option, mi, bool(sit.get("matchup_alakazam_confirmed")), _DOMINATE_PLUS,
    )
    if stamp_prot != 0.0:
        return stamp_prot

    # SP-BOSS-T  Boss gust target: Layer1 deterministic pick (after Plan B so
    # the confirmed-Alakazam Budew-lock gust keeps priority).  Skip when
    # TurnPlan already owns the gust target.
    if not plan_owns_boss:
        boss_sel = _boss_gust_select_bonus(obs, option, sit)
        if boss_sel != 0.0:
            return boss_sel

    # Evolve Snorunt→861 early in ops block (Active+water = next-turn Resentful).
    if option.type == OptionType.EVOLVE and _evolve_to_mega_froslass_ex(obs, option, mi):
        active = _active_pokemon(obs, mi)
        if (
            active
            and _si(getattr(active, "id", None)) == _OC_SNORUNT
            and _has_water_energy(active)
            and _evolve_mega_froslass_targets_snorunt(obs, option, mi)
        ):
            return _DOMINATE_OPEN_PATH
        return _DOMINATE_OPEN

    # Dual-attacker: Active 861 + dead/weak Resentful + bench Mega Starmie
    # → cut back to Starmie (Resentful=0 must not Absolute-Snow stall).
    if _starmie_promote_over_froslass(obs, mi, board, sit):
        can_cut = (
            _hand_has_id(obs, mi, _OC_SWITCH)
            or _active_can_retreat(obs, mi)
        )
        opts = sit.get("select_options") or []
        cut_offered = any(
            getattr(o, "type", None) == OptionType.RETREAT
            or (
                getattr(o, "type", None) == OptionType.PLAY
                and _hand_card_id(obs, o, mi) == _OC_SWITCH
            )
            for o in opts
        ) if opts else can_cut
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return _DOMINATE_OPEN_PATH
        if option.type == OptionType.RETREAT and _active_can_retreat(obs, mi):
            return _DOMINATE_OPEN_PATH
        if option.type == OptionType.CARD:
            try:
                ctx = int(obs.select.context)
            except Exception:
                ctx = -1
            if ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
                pi = _si(getattr(option, "playerIndex", None), mi)
                if pi == mi:
                    pkm = _pokemon_in_area(
                        obs, option.area, _si(getattr(option, "index", None)), mi,
                    )
                    if pkm and _si(getattr(pkm, "id", None)) == _CARDS["mega_starmie_ex"]:
                        return _DOMINATE_OPEN_PATH
                    return -_DOMINATE
        if option.type == OptionType.ATTACK:
            # Soft-lock only while a cut-in action is actually offered.
            if cut_offered:
                return -_DOMINATE
            atk_id = _attack_id(option)
            last = _attack_last_score(sit)
            if atk_id == _ATK_ABS_SNOW:
                return last if last is not None else _DOMINATE_ATTACK
            if atk_id == _ATK_RESENTFUL:
                return -_DOMINATE
        if option.type == OptionType.END and cut_offered:
            return -_DOMINATE

    # Active Mega Froslass + water → Resentful only when it deals real damage.
    opp_hand_n = int(sit.get("opp_hand_count") or 0)
    if (
        _mega_froslass_should_attack(board)
        and not sit.get("harvest_resentful_fired")
        and not _resentful_worthless(opp_hand_n)
        and not _starmie_promote_over_froslass(obs, mi, board, sit)
    ):
        if option.type == OptionType.ATTACK:
            atk_id = _attack_id(option)
            last = _attack_last_score(sit)
            if atk_id == _ATK_RESENTFUL:
                if _resentful_damage(opp_hand_n) >= 200:
                    return last if last is not None else _DOMINATE_PLUS
                return -_DOMINATE
            if atk_id == _ATK_ABS_SNOW:
                if _resentful_damage(opp_hand_n) < 200:
                    return last if last is not None else _DOMINATE_ATTACK
                return -_DOMINATE
            return -_DOMINATE  # never other attacks while 861 is the attacker
        # Allow Switch always; ban other turn-spenders only when Resentful is strong.
        if option.type == OptionType.PLAY:
            cid = _hand_card_id(obs, option, mi)
            if cid == _OC_SWITCH:
                return 0.0
            if _resentful_damage(opp_hand_n) >= 200 and (
                cid in _SUPPORTER_IDS or cid == _BOSS_ID
            ):
                return -_DOMINATE
        if (
            option.type in (OptionType.ABILITY, OptionType.ATTACH, OptionType.EVOLVE)
            and _resentful_damage(opp_hand_n) >= 200
        ):
            return -_DOMINATE
        if option.type == OptionType.RETREAT and _resentful_damage(opp_hand_n) >= 200:
            return -_DOMINATE
        if option.type == OptionType.END:
            return _ATTACH_ILLEGAL

    # Absolute Snow fallback when Resentful is dead but cannot cut to Starmie.
    if (
        option.type == OptionType.ATTACK
        and _mega_froslass_should_attack(board)
        and _resentful_worthless(opp_hand_n)
        and not _starmie_promote_over_froslass(obs, mi, board, sit)
    ):
        atk_id = _attack_id(option)
        last = _attack_last_score(sit)
        if atk_id == _ATK_ABS_SNOW:
            return last if last is not None else _DOMINATE_ATTACK
        if atk_id == _ATK_RESENTFUL:
            return -_DOMINATE

    # Bench 861+water → promote to Active so Resentful can fire at least once.
    if _froslass_promote_needed(obs, mi, board, sit):
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return _DOMINATE_OPEN_PATH
        if option.type == OptionType.CARD:
            try:
                ctx = int(obs.select.context)
            except Exception:
                ctx = -1
            if ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
                pi = _si(getattr(option, "playerIndex", None), mi)
                if pi == mi:
                    pkm = _pokemon_in_area(
                        obs, option.area, _si(getattr(option, "index", None)), mi,
                    )
                    if pkm and _si(getattr(pkm, "id", None)) == _CARDS["mega_froslass_ex"]:
                        if _mega_active_fuel_ok(obs, mi, pkm):
                            return _DOMINATE_OPEN_PATH
                        return -_DOMINATE_OPEN_PATH
                    # Must not promote the wrong bench Pokémon.
                    return -_DOMINATE
        if option.type == OptionType.RETREAT and _active_can_retreat(obs, mi):
            return _DOMINATE_OPEN_PATH
        # Demote blank END / Jetting while fueled 861 waits on bench.
        if option.type == OptionType.END:
            return -_DOMINATE
        if option.type == OptionType.ATTACK and board.active_is_mega_starmie:
            return -_DOMINATE
        if option.type == OptionType.PLAY:
            cid = _hand_card_id(obs, option, mi)
            if cid != _OC_SWITCH:
                return -_DOMINATE_MID

    # Legacy: bench 861 when Active cannot fire — still fuel-gated.
    if (
        option.type == OptionType.CARD
        and getattr(board, "mega_froslass_on_field", False)
        and not _mega_froslass_should_attack(board)
        and not _froslass_promote_needed(obs, mi, board, sit)
    ):
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
            pi = _si(getattr(option, "playerIndex", None), mi)
            if pi == mi:
                pkm = _pokemon_in_area(
                    obs, option.area, _si(getattr(option, "index", None)), mi,
                )
                if pkm and _si(getattr(pkm, "id", None)) == _CARDS["mega_froslass_ex"]:
                    if _mega_active_fuel_ok(obs, mi, pkm):
                        return _DOMINATE_OPEN_PATH
                    return -_DOMINATE_OPEN_PATH

    # Dudunsparce engine: evolve 66 / Run Away Draw — hard PATH all phases.
    if option.type == OptionType.EVOLVE and _evolve_to_dudunsparce(obs, option, mi):
        return _DOMINATE_OPEN_PATH
    if (
        option.type == OptionType.ABILITY
        and _ability_source_id(obs, option, mi) == _CARDS["dudunsparce"]
    ):
        return _DOMINATE_OPEN_PATH
    # Don't blank-end while 66 evolve or Run Away is available.
    if option.type == OptionType.END:
        if _hand_has_id(obs, mi, _CARDS["dudunsparce"]) and (
            _bench_has_id(obs, mi, _CARDS["dunsparce_a"])
            or _bench_has_id(obs, mi, _CARDS["dunsparce_b"])
            or _bench_has_id(obs, mi, DUNSPARCE_A)
            or _bench_has_id(obs, mi, DUNSPARCE_B)
        ):
            return -_DOMINATE
        if _bench_has_id(obs, mi, _CARDS["dudunsparce"]):
            return -_DOMINATE_MID

    # Bench role budget: refuse over-cap basics; prefer Dunsparce while under quota.
    if option.type == OptionType.PLAY and board.bench_open > 0:
        cid = _hand_card_id(obs, option, mi)
        if cid in (
            _OC_STARYU,
            _OC_SNORUNT,
            DUNSPARCE_A,
            DUNSPARCE_B,
            _FAN_ROTOM_ID,
            _BUDEW_ID,
            _OC_MEOWTH_EX,
        ):
            if not _obs_can_bench_card(obs, mi, cid):
                return -_DOMINATE_OPEN_PATH
            if cid in (DUNSPARCE_A, DUNSPARCE_B):
                if board.active_id == _OC_STARYU and not board.mega_starmie_on_field:
                    return _DOMINATE
                return _DOMINATE_MID

    # Poffin TO_BENCH card picks: demote over-cap roles.
    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx == int(SelectContext.TO_BENCH):
            cid = _card_option_id(obs, option, mi)
            if cid and not _obs_can_bench_card(obs, mi, cid):
                return -_DOMINATE_OPEN_PATH

    attach_pri = _attach_priority_bonus(
        obs, option, mi, board, phase, hand,
        alak_matchup=bool(sit.get("matchup_alakazam_confirmed")),
    )
    if attach_pri != 0.0:
        return attach_pri

    axis_bonus = _layer1_supporter_draw_axis(
        obs, option, sit, mi, board, phase, hand, resources,
    )
    if axis_bonus != 0.0:
        return axis_bonus

    # Attach/retreat fuel gates (before OPENING path so bans always apply).
    fuel_bonus = _attach_retreat_fuel_bonus(obs, option, mi, board, phase)
    if fuel_bonus != 0.0:
        return fuel_bonus

    # HR-O-BanBoss — never play Boss's Orders during OPENING (steals supporter).
    if (
        phase.primary == "OPENING"
        and option.type == OptionType.PLAY
        and _hand_card_id(obs, option, mi) == _BOSS_ID
    ):
        return -_DOMINATE

    # P6 — never put a 3rd Staryu onto the field (play / Poffin / Pad bench).
    staryu_ban = _staryu_overflow_ban(obs, option, mi)
    if staryu_ban != 0.0:
        return staryu_ban

    # P7 — non-attacker Active (Meowth ex / Fan Rotom / basics) while a ready
    # Mega waits on the bench: promote the attacker, never stall with utility
    # attacks in the Active Spot.
    if (
        phase.opening_complete
        and not board.active_is_mega_starmie
        and board.active_id not in _MEGA_EX_IDS
        and _bench_ready_attacker(obs, mi)
    ):
        if option.type == OptionType.ATTACK:
            return -_DOMINATE_MID
        if option.type == OptionType.RETREAT and _active_can_retreat(obs, mi):
            return _DOMINATE_RESCUE
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return _DOMINATE_RESCUE

    # Epoch1 OPENING (G*) + Epoch2 AGGRESSION / post-Mega HARVEST (SF*).
    if phase.primary in ("OPENING", "AGGRESSION", "HARVEST"):
        path_bonus = score_opening_option(
            obs,
            option,
            board=board,
            hand=hand,
            resources=resources,
            phase=phase,
            my_index=mi,
            route=sit.get("opening_route"),
            memory=sit.get("epoch_memory"),
        )
        if path_bonus != 0.0:
            return path_bonus

    if phase.primary != "OPENING":
        adrena_sel = _adrena_selection_bonus(obs, option, board, phase, mi)
        if adrena_sel != 0.0:
            return adrena_sel

    harvest_bonus = _harvest_hard_rules(
        obs, option, sit, mi, board, phase, hand, prize_ids,
    )
    if harvest_bonus != 0.0:
        return harvest_bonus

    control_bonus = _control_hard_rules(
        obs, option, sit, mi, board, phase, hand, prize_ids,
    )
    if control_bonus != 0.0:
        return control_bonus

    # HR-0  Fan Rotom dead — never PLAY another copy after My-T1 window
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == _FAN_ROTOM_ID and board.fan_rotom_dead:
            return -_DOMINATE

    # Ignition already on Active → force retreat this turn (don't EOT-discard).
    # Also retreat when bench Mega+water is waiting (usable-Mega promote).
    # Never yank a fueled Mega that still owes an attack (online empty Retreat).
    if (
        option.type == OptionType.RETREAT
        and _active_has_ignition(obs, mi)
        and not _fueled_mega_must_attack(board, plan)
    ):
        _, _bmw = _bench_mega_starmie_with_water(obs, mi)
        if _bmw is not None or _bench_has_free_retreat(obs, mi):
            return _DOMINATE_OPEN_PATH if _bmw is not None else _DOMINATE_PLUS

    synergy = _synergy_window(board, phase)
    post_opening = board.my_turn_number >= 2
    retreat_rescue = _needs_retreat_rescue(obs, mi, board, phase)

    # HR-O6c  OPENING — if Active is unevolved Staryu, Mega not in hand/field, and a
    # non-Staryu bench mate exists, Switch/Retreat Staryu off Active (don't expose base).
    if (
        phase.primary == "OPENING"
        and board.active_id == _OC_STARYU
        and not board.mega_starmie_on_field
        and not _hand_has_id(obs, mi, _OC_MEGA_STARMIE)
        and _bench_has_non_staryu(obs, mi)
    ):
        if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
            return _DOMINATE_OPEN
        if option.type == OptionType.RETREAT and _active_can_retreat(obs, mi):
            return _DOMINATE_OPEN

    # HR-9  Retreat rescue — off-attacker active with no retreat energy.
    # P7: no longer gated by _defer_mega_promotion — a stuck Meowth/Fan/basic
    # must be rescued to keep the engine running (wall cases are filtered
    # inside _needs_retreat_rescue).
    if retreat_rescue:
        if option.type == OptionType.PLAY:
            cid = _hand_card_id(obs, option, mi)
            if cid == _OC_SWITCH:
                return _DOMINATE_RESCUE
            if cid == _OC_POKE_PAD:
                return _DOMINATE_PLUS
        if option.type == OptionType.ATTACH and _attach_energy_to_active(obs, option, mi):
            eid = _attach_energy_id(obs, option, mi)
            if eid in _WATER_ENERGY_IDS and _staryu_needs_water(obs, mi, board):
                return 0.0
            if eid in (DARK_BASIC, IGNITION):
                return _DOMINATE_PLUS
            return _DOMINATE

    # HR-2  Munkidori Adrena-Brain — before attack when dark attached + own damage
    if option.type == OptionType.ABILITY and post_opening:
        src_id = _ability_source_id(obs, option, mi)
        if src_id == _MUNKIDORI_ID:
            try:
                idx = _si(getattr(option, "index", None), -1)
                pkm = _pokemon_in_area(obs, option.area, idx, mi)
                if (
                    pkm
                    and _has_darkness_energy(pkm)
                    and _own_transferable_damage(obs, mi)
                ):
                    return _DOMINATE_PLUS
            except Exception:
                pass

    # HR-EGG (DP boost) — 104 stuck in hand with no spare Snorunt on field:
    # push an egg out NOW (hand / Poffin / Pad) so 104 evolves next turn.
    # Diagnosis: 38% of games had 104 in hand but never fielded, with the
    # lone Snorunt reserved for 861.
    if (
        post_opening
        and option.type == OptionType.PLAY
        and not board.froslass_104_on_field
        and board.bench_open > 0
        and _hand_has_id(obs, mi, _OC_FROSLASS)
    ):
        need = 1 if getattr(board, "mega_froslass_on_field", False) else 2
        if _snorunt_field_count(obs, mi) < need:
            cid = _hand_card_id(obs, option, mi)
            if cid == _OC_SNORUNT:
                return _DOMINATE_PLUS
            if (
                cid in (_OC_POFFIN, _OC_POKE_PAD)
                and resources.copies_left(_OC_SNORUNT) > 0
            ):
                return _DOMINATE_PLUS - 10.0

    # HR-3 / HR-11 — synergy bench (AGGRESSION+ only; OPENING uses path planner)
    # Post-Mega DP incomplete: scores must beat Jetting (_DOMINATE_ATTACK=975)
    # — attacking ends the turn and was starving the DP set.
    dp_urgent = (
        getattr(board, "mega_starmie_on_field", False)
        and not _synergy_core_ready(board)
    )
    if phase.primary != "OPENING" and option.type == OptionType.PLAY and synergy and board.bench_open > 0:
        cid = _hand_card_id(obs, option, mi)
        if cid == _OC_SNORUNT and not board.snorunt_line_on_bench:
            if dp_urgent:
                return _DOMINATE_PLUS - 20.0
            return _DOMINATE if board.munkidori_on_bench else _DOMINATE_MID
        # DP boost: 2nd Snorunt while the twin lines (861 + 104) are not both
        # online — one egg per evolution (overflow ban caps at 2 upstream).
        if (
            cid == _OC_SNORUNT
            and not (
                getattr(board, "mega_froslass_on_field", False)
                and board.froslass_104_on_field
            )
        ):
            return (_DOMINATE_PLUS - 40.0) if dp_urgent else (_DOMINATE_MID - 20.0)
        if cid == _OC_MUNKIDORI and not board.munkidori_on_field:
            return (_DOMINATE_PLUS - 10.0) if dp_urgent else _DOMINATE

    # HR-11  Synergy engine — Poké Pad / Poffin while DP field pieces missing
    # (104/Snorunt line or Munkidori not yet on field; dark-only gaps are an
    # attach problem, not a search problem).
    if (
        phase.primary != "OPENING"
        and option.type == OptionType.PLAY
        and synergy
        and not (
            (board.snorunt_line_on_bench or board.froslass_104_on_field)
            and board.munkidori_on_field
        )
    ):
        cid = _hand_card_id(obs, option, mi)
        if cid == _OC_POKE_PAD:
            if (
                resources.copies_left(_OC_SNORUNT) > 0
                or resources.copies_left(_OC_FROSLASS) > 0
                or resources.copies_left(_MUNKIDORI_ID) > 0
            ):
                return _DOMINATE_PLUS
        if cid == _OC_POFFIN and board.bench_open > 0:
            if (
                resources.copies_left(_OC_SNORUNT) > 0
                or resources.copies_left(_MUNKIDORI_ID) > 0
            ):
                return _DOMINATE_PLUS
        # Ultra Ball dig for DP pieces — below Pad; UB-3 skips when free search covers.
        if cid == _OC_ULTRA_BALL and dp_urgent:
            has_free = _hand_has_id(obs, mi, _OC_POFFIN) or _hand_has_id(
                obs, mi, _OC_POKE_PAD
            )
            need_stage = resources.copies_left(_OC_FROSLASS) > 0 and not board.froslass_104_on_field
            if has_free and not need_stage:
                return -_DOMINATE
            if (
                resources.copies_left(_OC_SNORUNT) > 0
                or resources.copies_left(_OC_FROSLASS) > 0
                or resources.copies_left(_MUNKIDORI_ID) > 0
            ):
                # UB-5: don't dig a name already in hand.
                if (
                    (_hand_has_id(obs, mi, _OC_SNORUNT) or board.snorunt_line_on_bench)
                    and (_hand_has_id(obs, mi, _OC_MUNKIDORI) or board.munkidori_on_field)
                    and (
                        _hand_has_id(obs, mi, _OC_FROSLASS)
                        or board.froslass_104_on_field
                    )
                ):
                    return -_DOMINATE
                return _DOMINATE_PLUS - 30.0

    # HR-10  Double Munkidori — second copy on bench (AGGRESSION/HARVEST)
    if (
        option.type == OptionType.PLAY
        and phase.primary in ("AGGRESSION", "HARVEST")
        and board.bench_open > 0
    ):
        cid = _hand_card_id(obs, option, mi)
        if (
            cid == _OC_MUNKIDORI
            and board.munkidori_on_field
            and _munkidori_count_on_field(obs, mi) < 2
        ):
            return _DOMINATE

    # HR-4  Attach dark/prism to any Munkidori missing dark (My-T2+ / HARVEST)
    # Non-Alakazam: never outrank watering a dry attacker (Mega/Staryu) that
    # can come online this turn — DP fill waits one attach.
    if option.type == OptionType.ATTACH and post_opening:
        target = _attach_target_pokemon(obs, option, mi)
        eid = _attach_energy_id(obs, option, mi)
        if (
            target
            and _si(getattr(target, "id", None)) == _MUNKIDORI_ID
            and not _has_darkness_energy(target)
            and eid in (_OC_PRISM, DARK_BASIC)
        ):
            alak = bool(sit.get("matchup_alakazam_confirmed"))
            if (
                not alak
                and _dry_attacker_needs_water(obs, mi)
                and _hand_has_water_energy(obs, mi)
            ):
                return -_DOMINATE_MID
            # PATH in HARVEST recovery — keep Adrena-Brain online after Starmie trades.
            if phase.primary == "HARVEST" or (synergy and board.munkidori_on_field):
                return _DOMINATE_OPEN_PATH
            return _DOMINATE

    # HR-5  Risky Ruins — only after Snorunt line + Munkidori on bench
    if option.type == OptionType.PLAY and synergy:
        if _hand_card_id(obs, option, mi) == _RISKY_RUINS and board.bench_three_core_ready:
            return _DOMINATE_LOW

    # HR-8 (S3)  104 first — the lone Snorunt goes to 104 by default; 861 is
    # insurance/surplus. Only when the 861 window is open (Starmie dying/gone,
    # or DP already done) AND a single egg remains does the egg stay reserved
    # for 861.
    if option.type == OptionType.EVOLVE and post_opening:
        if _evolve_to_froslass_104(obs, option, mi):
            if not board.froslass_104_on_field:
                reserve_for_861 = (
                    _hand_has_id(obs, mi, _CARDS["mega_froslass_ex"])
                    and _mega_froslass_window_open(obs, mi, board, phase)
                    and not getattr(board, "mega_froslass_on_field", False)
                    and _snorunt_field_count(obs, mi) < 2
                )
                if reserve_for_861:
                    return -_DOMINATE_OPEN  # lone egg held for insurance 861
                return _DOMINATE_OPEN
        if _evolve_to_mega_froslass_ex(obs, option, mi):
            # PATH when recovering / setting up second attacker.
            if phase.primary == "HARVEST" or not board.mega_starmie_on_field:
                return _DOMINATE_OPEN_PATH
            return _DOMINATE_OPEN  # post-Mega setup while Starmie still Active

    # HR-6  Mega Starmie attack — fueled Active must close with Jetting/Nebula.
    # Do NOT soft-trail behind main-phase setup (online empty-turn failure mode).
    if option.type == OptionType.ATTACK and _starmie_should_attack(board):
        if phase.primary == "AGGRESSION" or (
            phase.primary == "OPENING" and board.my_turn_number >= 2
        ):
            atk_id = _attack_id(option)
            nebula_ko = (
                atk_id == _ATK_NEBULA_BEAM
                and _nebula_ko_available(obs, mi, prize_ids)
            )
            if nebula_ko:
                return _DOMINATE_PLUS
            # Pre-attack prep still open (Boss/Adrena/DP) → trail; else dominate.
            plan = sit.get("turn_plan")
            if plan is not None and _actionable_pre_attack(obs, sit, plan.combat):
                last = _attack_last_score(sit, force_now=False)
                if last is not None:
                    return last
            if atk_id in (_ATK_JETTING_BLOW, _ATK_NEBULA_BEAM):
                return _DOMINATE_OPEN_PATH

    # HR-6b  Penalize END when Mega Starmie should attack.
    if option.type == OptionType.END and _starmie_should_attack(board):
        if phase.primary == "AGGRESSION" or (
            phase.primary == "OPENING" and board.my_turn_number >= 2
        ):
            return -_DOMINATE_OPEN_PATH
    # HR-7  Budew Itchy Pollen — OPENING stall when no Mega ex ready.
    # Going second: allow from engine turn 2 (My-T1); going first keeps turn>=3.
    if option.type == OptionType.ATTACK and phase.primary == "OPENING":
        gs = _going_second(board)
        if turn >= (2 if gs else 3) and not sit["mega_ready"]:
            atk_id = _attack_id(option)
            if atk_id == _ATK_ITCHY_POLLEN:
                return _DOMINATE * (0.8 if gs else 0.5)

    # HR-O6  Promote bench Mega Starmie to Active — when the engine asks us to
    # pick a bench Pokémon to swap/bring to the Active Spot (Switch trainer or
    # Retreat follow-up select), choose Mega Starmie (prefer the one already
    # holding water). Hard-ban unevolved Staryu whenever any alternative exists
    # (protect evolution chain — do not feed Staryu to Active KO).
    if option.type == OptionType.CARD:
        try:
            ctx = int(obs.select.context)
        except Exception:
            ctx = -1
        if ctx in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
            pi = _si(getattr(option, "playerIndex", None), mi)
            if pi == mi:
                pkm = _pokemon_in_area(
                    obs, option.area, _si(getattr(option, "index", None)), mi,
                )
                if pkm:
                    pid = _si(getattr(pkm, "id", None))
                    if pid == _CARDS["mega_starmie_ex"]:
                        if _mega_active_fuel_ok(obs, mi, pkm):
                            return (
                                _DOMINATE_PLUS if _has_water_energy(pkm) else _DOMINATE
                            )
                        return -_DOMINATE_OPEN_PATH
                    if pid == _OC_STARYU:
                        if board.mega_starmie_on_field or _bench_has_non_staryu(obs, mi):
                            return -_DOMINATE_OPEN_PATH

    # HR-O6b  OPENING — do not Switch/Retreat into a forced unevolved-Staryu Active
    # when Mega is not yet on field (evolve on bench first).
    if phase.primary == "OPENING" and not board.mega_starmie_on_field:
        if board.active_id != _OC_STARYU and not _bench_has_non_staryu(obs, mi):
            if option.type == OptionType.RETREAT:
                return -_DOMINATE_OPEN_PATH
            if option.type == OptionType.PLAY and _hand_card_id(obs, option, mi) == _OC_SWITCH:
                return -_DOMINATE_OPEN_PATH

    # HR-O7  OPENING — retreat the Active to promote bench Mega Starmie (+water)
    # when no Switch trainer is in hand. The RETREAT option is only offered when
    # the Active can legally retreat, so retreating here opens the follow-up
    # TO_ACTIVE select (handled by HR-O6) to bring Mega up.
    if option.type == OptionType.RETREAT and phase.primary == "OPENING":
        if _opening_g5_switch_needed(phase, board, obs, mi):
            try:
                _hand = obs.current.players[mi].hand or []
            except Exception:
                _hand = []
            if not any(_si(getattr(c, "id", None)) == _OC_SWITCH for c in _hand if c):
                return _DOMINATE_OPEN_PATH

    # P4 — fallback ranking for own SWITCH/TO_ACTIVE selects (no rule above
    # fired): Dunsparce line walls; Staryu/Snorunt/Munkidori stay benched.
    promote_fb = _own_promote_fallback_bonus(obs, option, mi)
    if promote_fb != 0.0:
        return promote_fb

    return 0.0


# ── Layer 2: soft situational nudges ─────────────────────────────────────────

def _soft_bonus(obs, option, weights: dict[str, float], sit: dict[str, Any]) -> float:
    mi        = sit["my_index"]
    opp_hand  = sit["opp_hand_count"]
    prize_ids = sit["prize_path_ids"]
    bonus     = 0.0

    # S-1  Mega Froslass ex harvest nudge — HARVEST phase only (see 03_harvest.md).
    # Layer 1 HR-8b blocks 861 outside HARVEST; this soft dim must not fight AGGRESSION.
    if option.type == OptionType.EVOLVE:
        phase = sit.get("phase")
        if phase and phase.primary == "HARVEST":
            try:
                hand = obs.current.players[mi].hand or []
                idx  = _si(getattr(option, "index", None), -1)
                card = (obs.select.deck[idx] if option.area == AreaType.DECK
                        else hand[idx] if option.area == AreaType.HAND else None)
                if card and _si(getattr(card, "id", None)) == _CARDS["mega_froslass_ex"]:
                    if opp_hand >= 5 or sit["opp_just_took_prize"]:
                        bonus += weights.get("froslass_harvest", 1.5)
            except Exception: pass

    # S-2  Prefer Jetting Blow for bench spread (default attack path)
    elif option.type == OptionType.ATTACK:
        atk = _attack_id(option)
        if atk == _ATK_JETTING_BLOW:
            bonus += weights.get("jetting_blow_pref", 1.2)

        # S-3  Prefer Nebula Beam when it secures a KO on a prize-path target.
        # Nebula Beam deals a fixed 210 ignoring effects, so KO needs hp <= 210.
        if atk == _ATK_NEBULA_BEAM:
            try:
                opp_active = (obs.current.players[1 - mi].active or [None])[0]
                if opp_active:
                    opp_cid = _si(getattr(opp_active, "id", None))
                    opp_hp  = _si(getattr(opp_active, "hp", None), 9999)
                    if opp_cid in prize_ids and opp_hp <= 210:
                        bonus += weights.get("nebula_finish", 2.0)
            except Exception: pass

        # S-4  Resentful Refrain scales with opponent hand size
        if atk == _ATK_RESENTFUL:
            phase = sit.get("phase")
            if phase and phase.primary == "HARVEST" and opp_hand * 50 >= 200:
                bonus += 1.0

    # S-5a  Boss's Orders: nudge PLAYING it when a prize-path bench target exists.
    # Never during OPENING (supporter slot reserved for Hilda/Lillie/path).
    elif option.type == OptionType.PLAY:
        if _hand_card_id(obs, option, mi) == _BOSS_ID:
            phase = sit.get("phase")
            if phase is not None and getattr(phase, "primary", None) == "OPENING":
                bonus -= 5.0
            else:
                try:
                    oi = 1 - mi
                    bench_ids = {
                        _si(getattr(p, "id", None))
                        for p in (obs.current.players[oi].bench or []) if p
                    }
                    if bench_ids & prize_ids:
                        bonus += weights.get("boss_gust_path", 1.8) * 0.5
                except Exception: pass

    # S-5b  Boss's Orders TARGET is chosen via a CARD option pointing at the
    # opponent's bench — score the prize-path target here (the real selection).
    elif option.type == OptionType.CARD:
        try:
            if (_si(getattr(option, "playerIndex", None), mi) != mi
                    and option.area == AreaType.BENCH):
                oi  = 1 - mi
                bch = obs.current.players[oi].bench or []
                idx = _si(getattr(option, "index", None), -1)
                if 0 <= idx < len(bch) and bch[idx]:
                    if _si(getattr(bch[idx], "id", None)) in prize_ids:
                        bonus += weights.get("boss_gust_path", 1.8)
        except Exception: pass

    return bonus


# ── Generic baseline scorer (mirrors submission/main.py without card-id refs) ─

def _baseline_score(obs, option, weights: dict[str, float]) -> float:
    from cg.api import CardType
    score = 0.0
    mi    = obs.current.yourIndex

    def _get_card(area, index, pi):
        try:
            p = obs.current.players[pi]
            if area == AreaType.HAND:    return (p.hand or [])[index]
            if area == AreaType.BENCH:   return (p.bench or [])[index]
            if area == AreaType.ACTIVE:  return (p.active or [])[index]
            if area == AreaType.DISCARD: return (p.discard or [])[index]
            if area == AreaType.PRIZE:   return (p.prize or [])[index]
        except Exception: pass
        return None

    def _ctype_score(card):
        if card is None: return 0.0
        cid = _si(getattr(card, "id", None), -1)
        try:
            from cg.api import all_card_data, CardType
            # Use cached meta
            if not hasattr(_baseline_score, "_meta"):
                _baseline_score._meta = {
                    c.cardId: (int(c.cardType), bool(c.basic)) for c in all_card_data()
                }
            meta = _baseline_score._meta.get(cid)
            if meta:
                ct, is_basic = meta
                if ct == int(CardType.POKEMON):
                    return weights.get("card_basic", 1.1) if is_basic else weights.get("card_pokemon", 0.6)
                if ct == int(CardType.ENERGY):
                    return weights.get("card_energy", 0.45)
                return weights.get("card_trainer", 0.35)
        except Exception: pass
        return 0.0

    if   option.type == OptionType.ATTACK:  score += weights.get("attack", 3.0)
    elif option.type == OptionType.ATTACH:
        score += weights.get("attach", 2.0)
        if option.inPlayArea == AreaType.ACTIVE: score += weights.get("active_bonus", 0.4)
        if option.inPlayArea == AreaType.BENCH:  score += weights.get("bench_penalty",-0.1)
    elif option.type == OptionType.EVOLVE:  score += weights.get("evolve", 1.7)
    elif option.type == OptionType.PLAY:
        score += weights.get("play", 1.2)
        card = _get_card(AreaType.HAND, _si(getattr(option,"index",None)), mi)
        score += _ctype_score(card)
    elif option.type == OptionType.ABILITY: score += weights.get("ability", 1.0)
    elif option.type == OptionType.RETREAT: score += weights.get("retreat", -0.2)
    elif option.type == OptionType.YES:     score += weights.get("yes", 0.1)
    elif option.type == OptionType.NO:      score += weights.get("no", 0.0)
    elif option.type == OptionType.CARD:
        card = _get_card(option.area, _si(getattr(option,"index",None)),
                         _si(getattr(option,"playerIndex",None), mi))
        score += _ctype_score(card)
        if _si(getattr(option, "playerIndex", None), mi) != mi:
            score += weights.get("damage_target", 1.5)
    elif option.type == OptionType.NUMBER:
        score += float(getattr(option, "number", 0))

    score += random.random() * weights.get("random_noise", 0.02)
    return score


# ── Combined scorer ───────────────────────────────────────────────────────────

def option_score(obs, option, weights: dict[str, float], sit: dict[str, Any]) -> float:
    hard = _hard_rule_bonus(obs, option, sit)
    if hard != 0.0:
        return hard
    return _baseline_score(obs, option, weights) + _soft_bonus(obs, option, weights, sit)


# ── RL Actor-Expert opening proposer (torch-free numpy) ────────────────────────

_RL_PROPOSER = None
_RL_TRIED = False
# Proposer is gated off by default for Kaggle deployment: with the v1
# Mega-promotion fix (HR-O6/O7) the v1 pilot completes the opening at ~72% on
# its own, and the sim-trained proposer (whose sup/energy features were encoded
# with an always-False supporter_played/energy_attached on the real engine)
# currently drags completion down ~5pp when it leads. Enable locally for A/B
# audits via RL_ENABLED=1, or after a retrain that beats v1.
_RL_ENABLED = os.environ.get("RL_ENABLED", "1") != "0"
# Decision-level hybrid mode (USE_HYBRID):
#   "1" / "conf" (default) — conf-gated RL takeover (planner stays when
#       low-conf / no-match / hard-rule block). Empirically matches strong
#       opt_v4 rl-only on cabt; score-gated fusion hurt (~60% open).
#   "score" — only takeover when option_score(rl) >= option_score(planner_top)
#   "0" — pure RL takeover (same conf/hard-rule gates, no score compare)
_USE_HYBRID_RAW = os.environ.get("USE_HYBRID", "1").strip().lower()
_USE_HYBRID = _USE_HYBRID_RAW not in ("0", "false", "off", "no")
_HYBRID_SCORE_GATE = _USE_HYBRID_RAW in ("score", "scored", "2")


def _rl_proposer():
    """Lazy-load the numpy RL proposer from pilot/{bundle}.{npz,json}.

    Bundle name defaults to rl_opening; override with RL_OPENING_BUNDLE
    (e.g. rl_opening_v7, rl_opening_unit_poffin).
    """
    global _RL_PROPOSER, _RL_TRIED
    if _RL_TRIED:
        return _RL_PROPOSER
    _RL_TRIED = True
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        bundle = os.environ.get("RL_OPENING_BUNDLE", "rl_opening").strip() or "rl_opening"
        # Allow either basename under pilot/ or an absolute/relative path prefix.
        if os.path.isabs(bundle) or "/" in bundle:
            prefix = bundle
        else:
            prefix = os.path.join(base, bundle)
        if os.path.exists(prefix + ".npz") and os.path.exists(prefix + ".json"):
            from rl_opening_proposer import RLProposer  # noqa: E402
            _RL_PROPOSER = RLProposer.load(prefix)
    except Exception:
        _RL_PROPOSER = None
    return _RL_PROPOSER


_RL_PROPOSER_ALAK = None
_RL_ALAK_TRIED = False


def _rl_proposer_alak():
    """Alakazam-specialized bundle (rl_opening_alak.{npz,json}); confirmed-gated.

    Disable with RL_ALAK_BUNDLE=0. Missing files → None (falls back to the
    base bundle), so shipping without the alak npz is always safe.
    """
    global _RL_PROPOSER_ALAK, _RL_ALAK_TRIED
    if _RL_ALAK_TRIED:
        return _RL_PROPOSER_ALAK
    _RL_ALAK_TRIED = True
    if os.environ.get("RL_ALAK_BUNDLE", "1").strip().lower() in ("0", "false", "off", "no"):
        return None
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        prefix = os.path.join(base, "rl_opening_alak")
        if os.path.exists(prefix + ".npz") and os.path.exists(prefix + ".json"):
            from rl_opening_proposer import RLProposer  # noqa: E402
            _RL_PROPOSER_ALAK = RLProposer.load(prefix)
    except Exception:
        _RL_PROPOSER_ALAK = None
    return _RL_PROPOSER_ALAK


def _build_rl_view(adapter) -> dict[str, Any]:
    active = adapter.active
    bench = adapter.bench
    return {
        "hand": list(adapter.hand),
        "active_id": active.card_id if active else None,
        "active_energies": list(active.energies) if active else [],
        "bench_ids": [p.card_id for p in bench],
        "bench_energies": [list(p.energies) for p in bench],
        "supporter_played": adapter.supporter_played,
        "energy_attached": adapter.energy_attached,
        "fan_call_used": adapter.fan_call_used,
        "my_turn_number": adapter.my_turn_number,
        "deck_len": len(adapter.deck),
        "prize_len": len(adapter.prizes),
        "going_first": adapter.going_first,
        "active_can_evolve": adapter._can_evolve_now(active) if active else False,
        "bench_can_evolve": [adapter._can_evolve_now(p) for p in bench],
    }


# Minimum vote share (out of K=4 samples) for the RL policy to override the
# planner route. 3/4 = strong consensus; otherwise defer to the v1 pilot.
_RL_MIN_CONF = 0.75

# Instrumentation counters for local takeover-rate auditing (not used on Kaggle).
RL_STATS: dict[str, int] = {
    "opening_eligible": 0,
    "takeover": 0,
    "blocked_by_hardrule": 0,
    "deferred_to_planner": 0,
    "low_confidence": 0,
    "no_option_match": 0,
    "non_mappable_decision": 0,
    "proposer_errors": 0,
    "games_started": 0,
    "opening_complete_games": 0,
}
RL_KIND_STATS: dict[str, dict[str, int]] = {"blocked": {}, "nomatch": {}}
# Capped sample of no-match decisions for sim-to-real view-mismatch diagnosis.
RL_NOMATCH_SAMPLES: list[dict] = []


def _rl_kind_tick(bucket: str, kind: str) -> None:
    try:
        RL_KIND_STATS[bucket][str(kind)] = RL_KIND_STATS[bucket].get(str(kind), 0) + 1
    except Exception:
        pass


_PATH_RL_KINDS = frozenset({
    "PLAY_POFFIN", "PLAY_ULTRA_BALL", "PLAY_POKE_PAD",
    "PLAY_POKEMON", "EVOLVE", "ATTACH",
})


def _is_opening_path_rl_action(kind: str, primary, obs, option, mi: int) -> bool:
    """OPENING≤T3 takeover allowlist: fetch / Staryu play / Mega evolve / water attach."""
    k = str(kind or "")
    if k not in _PATH_RL_KINDS:
        return False
    if k in ("PLAY_POFFIN", "PLAY_ULTRA_BALL", "PLAY_POKE_PAD"):
        return True
    if k == "PLAY_POKEMON":
        try:
            pid = int(primary) if primary is not None else 0
        except Exception:
            pid = 0
        if pid == _OC_STARYU:
            return True
        return _hand_card_id(obs, option, mi) == _OC_STARYU
    if k == "EVOLVE":
        return bool(_evolve_to_mega_starmie(obs, option, mi))
    if k == "ATTACH":
        try:
            eid = int(primary) if primary is not None else 0
        except Exception:
            eid = 0
        if eid in _WATER_ENERGY_IDS:
            return True
        # Fall back: energy id on ATTACH option if exposable
        try:
            if option.type == OptionType.ATTACH:
                hand = obs.current.players[mi].hand or []
                idx = _si(getattr(option, "index", None), -1)
                if 0 <= idx < len(hand) and hand[idx]:
                    return _si(getattr(hand[idx], "id", None)) in _WATER_ENERGY_IDS
        except Exception:
            pass
        return False
    return False


# ── Public agent factory ──────────────────────────────────────────────────────

def make_starmie_agent(deck: list[int], weights: dict[str, float] | None = None) -> AgentFn:
    """Build an AgentFn for the starmie_froslass deck."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    agent_state: dict[str, Any] = {
        "last_my_turn": 0,
        "prev_active_was_mega_starmie": False,
        "harvest_ko_last_turn": False,
        "harvest_resentful_fired": False,
        "matchup_alakazam_confirmed": False,
        "alak_finisher_window": False,
        "alak_follow_window": False,
        "alak_budew_ko_last_opp_turn": False,
        "alak_budew_ko_pending": False,
        "alak_prev_my_had_budew": False,
        "alak_last_my_turn": -1,
        "mega_on_field_by_my_turn_4": False,
        "mega_on_field_by_my_turn_3": False,
        "mega_first_seen_my_turn": None,
        "staryu_on_field_by_my_turn_1": False,
        "staryu_on_field_by_my_turn_2": False,
        "staryu_first_seen_my_turn": None,
        "usable_mega_by_my_turn_2": False,
        "usable_mega_by_my_turn_3": False,
        "epoch_memory": default_epoch_memory(),
        "board_at_my_turn_1": None,
        "board_at_my_turn_4": None,
        "board_at_my_turn_3": None,
        "opening_complete_my_turn": None,
        "pending_crispin_energy_id": None,
    }

    def agent(obs_dict: dict[str, Any]) -> list[int]:
        if obs_dict.get("select") is None:
            # Kaggle setup/deck-submission call. (The local harness submits the
            # deck via battle_start, so this branch only fires on Kaggle.)
            agent_state["opening_complete_this_game"] = False
            return deck
        try:
            obs     = to_observation_class(obs_dict)
            options = obs.select.option
            if not options:
                return []
            sit   = _compute_situation(obs, deck_template=deck, agent_state=agent_state)
            agent_state["last_turn_plan"] = sit.get("turn_plan")
            agent_state["last_turn_plan_matchup_override"] = bool(
                sit.get("matchup_alakazam_confirmed")
            )
            # Per-game OPENING-completion flag (set once when the opening is
            # completed). The local harness resets this before each game via
            # `reset_for_new_game()` and reads it after, since the harness — not
            # the agent — knows the game boundary.
            if sit.get("opening_complete") and not agent_state.get("opening_complete_this_game"):
                agent_state["opening_complete_this_game"] = True
                RL_STATS["opening_complete_games"] += 1
                # First time opening completes: record which of our turns it was.
                _b0 = sit.get("board")
                if _b0 is not None:
                    agent_state.setdefault(
                        "opening_complete_my_turn", int(_b0.my_turn_number))
            # Capture the latest board snapshot for post-game failure-mode
            # diagnostics (used by local harnesses; cheap, no engine calls).
            _b = sit.get("board")
            if _b is not None:
                agent_state["max_my_turn"] = max(
                    agent_state.get("max_my_turn", 0), _b.my_turn_number)
                agent_state["final_board"] = (
                    _b.my_turn_number, _b.active_id, _b.active_is_mega_starmie,
                    _b.active_has_water, _b.mega_starmie_on_field,
                    _b.staryu_on_field, _b.prize_self, _b.prize_opp,
                )
                # Within our first 4 turns: did Mega Starmie ever appear on field?
                if int(_b.my_turn_number) <= 4 and (
                    _b.mega_starmie_on_field or _b.active_is_mega_starmie
                ):
                    agent_state["mega_on_field_by_my_turn_4"] = True
                    if int(_b.my_turn_number) <= 3:
                        agent_state["mega_on_field_by_my_turn_3"] = True
                    if agent_state.get("mega_first_seen_my_turn") is None:
                        agent_state["mega_first_seen_my_turn"] = int(
                            _b.my_turn_number)
                # Staryu-on-field timing (B-bucket / expert recipe ≤T1).
                # Mega on field implies the Staryu line was present this turn.
                if (
                    _b.staryu_on_field
                    or _b.active_id == _OC_STARYU
                    or _b.mega_starmie_on_field
                    or _b.active_is_mega_starmie
                ):
                    if agent_state.get("staryu_first_seen_my_turn") is None:
                        agent_state["staryu_first_seen_my_turn"] = int(
                            _b.my_turn_number)
                    # ≤T1 direct, or first seen on T2 (played on T1; snapshot lag).
                    fs = int(agent_state["staryu_first_seen_my_turn"])
                    if fs <= 1 or (
                        fs == 2 and int(_b.my_turn_number) == 2
                    ):
                        agent_state["staryu_on_field_by_my_turn_1"] = True
                    if fs <= 2:
                        agent_state["staryu_on_field_by_my_turn_2"] = True
                # Usable Mega = Mega on field + water on the Starmie line (epoch success).
                if _b.mega_starmie_on_field or _b.active_is_mega_starmie:
                    _usable = False
                    if _b.active_is_mega_starmie and _b.active_has_water:
                        _usable = True
                    else:
                        try:
                            from opening_bridge import _line_has_water as _lhw
                            _usable = bool(_lhw(obs, sit["my_index"]))
                        except Exception:
                            _usable = bool(_b.active_has_water and _b.mega_starmie_on_field)
                    if _usable:
                        mt = int(_b.my_turn_number)
                        if mt <= 2:
                            agent_state["usable_mega_by_my_turn_2"] = True
                        if mt <= 3:
                            agent_state["usable_mega_by_my_turn_3"] = True
                # Snapshot board at my_turn==1 / ==3 / ==4 for expert review.
                if int(_b.my_turn_number) == 1:
                    agent_state["board_at_my_turn_1"] = (
                        _b.my_turn_number, _b.active_id,
                        _b.active_is_mega_starmie, _b.active_has_water,
                        _b.mega_starmie_on_field, _b.staryu_on_field,
                        _b.prize_self, _b.prize_opp,
                    )
                if int(_b.my_turn_number) == 3:
                    agent_state["board_at_my_turn_3"] = (
                        _b.my_turn_number, _b.active_id,
                        _b.active_is_mega_starmie, _b.active_has_water,
                        _b.mega_starmie_on_field, _b.staryu_on_field,
                        _b.prize_self, _b.prize_opp,
                    )
                if int(_b.my_turn_number) == 4:
                    agent_state["board_at_my_turn_4"] = (
                        _b.my_turn_number, _b.active_id,
                        _b.active_is_mega_starmie, _b.active_has_water,
                        _b.mega_starmie_on_field, _b.staryu_on_field,
                        _b.prize_self, _b.prize_opp,
                    )
                elif (
                    int(_b.my_turn_number) > 4
                    and agent_state.get("board_at_my_turn_4") is None
                    and agent_state.get("opening_complete_this_game")
                ):
                    # Opening finished before we ever saw turn 4 selects;
                    # keep a copy of the board at completion as the T4 proxy.
                    agent_state["board_at_my_turn_4"] = agent_state.get(
                        "final_board")
                if (
                    int(_b.my_turn_number) > 3
                    and agent_state.get("board_at_my_turn_3") is None
                    and agent_state.get("opening_complete_this_game")
                ):
                    agent_state["board_at_my_turn_3"] = agent_state.get(
                        "final_board")

            # Expose the full option list so attack-last can see remaining
            # main-phase actions (PLAY/ATTACH/EVOLVE/ABILITY/RETREAT).
            sit["select_options"] = options
            order = sorted(
                range(len(options)),
                key=lambda i: option_score(obs, options[i], w, sit),
                reverse=True,
            )
            # Poffin TO_BENCH: Staryu-first among equal engine options (gold E-POFF-2).
            order = _reorder_poffin_bench(obs, options, order, sit["my_index"], sit)
            # Prefer maxCount (was hard-capped at 1 → Poffin always placed one Basic).
            pick = _select_pick_count(obs, len(options))

            # ── RL Actor-Expert override (OPENING only, single-select) ──────────
            # The torch-free numpy proposer votes among K policy samples; when it
            # reaches strong consensus it leads the turn, otherwise the v1
            # planner route + hard rules (computed above) stay in charge.
            #
            # Production defaults (Phase A rules + epoch memory):
            # - Layer1 OPENING path = epoch_scheduler (conflict demote + Evolve-first)
            # - OPENING_EPOCH_RL=0: defer RL while epoch-1 incomplete (Hybrid≈Planner)
            # - EPOCH_TASK_DRIVE=1: this_turn_task drives full preferred/demote plan
            phase = sit.get("phase")
            board = sit.get("board")
            _epoch_rl = os.environ.get(
                "OPENING_EPOCH_RL", "0"
            ).strip().lower() not in ("0", "false", "off", "no")
            _epoch1_open = False
            if (
                phase is not None
                and phase.primary == "OPENING"
                and board is not None
                and sit.get("hand") is not None
                and sit.get("resources") is not None
            ):
                try:
                    _ep = compute_epoch_plan(
                        obs, board, sit["hand"], sit["resources"], sit["my_index"],
                        memory=sit.get("epoch_memory"),
                        refresh=False,
                    )
                    _epoch1_open = _ep.priority_gap != "DONE" and _ep.epoch_id < 2
                except Exception:
                    _epoch1_open = not bool(sit.get("opening_complete"))
            if (
                _RL_ENABLED
                and pick == 1
                and phase is not None
                and phase.primary == "OPENING"
                and board is not None
                and board.my_turn_number >= 1
                and (_epoch_rl or not _epoch1_open)
            ):
                prop = _rl_proposer()
                # Matchup-ALAK: confirmed games switch to the specialized
                # bundle (unit-bundle style isolation; base games untouched).
                if sit.get("matchup_alakazam_confirmed"):
                    alak_prop = _rl_proposer_alak()
                    if alak_prop is not None:
                        prop = alak_prop
                if prop is not None:
                    try:
                        from opening_bridge import BattleOpeningAdapter
                        mi = sit["my_index"]
                        # Only invoke the proposer on decisions whose option types
                        # it can actually map (PLAY/ATTACH/EVOLVE/ABILITY/RETREAT).
                        _MAPPABLE = (OptionType.PLAY, OptionType.ATTACH,
                                     OptionType.EVOLVE, OptionType.ABILITY,
                                     OptionType.RETREAT)
                        if any(o.type in _MAPPABLE for o in options):
                            adapter = BattleOpeningAdapter(
                                obs, board, sit["hand"], sit["resources"], mi,
                            )
                            view = _build_rl_view(adapter)
                            # Ground-truth sup/energy flags from the engine's
                            # offered options. The real cabt player object has NO
                            # supporterPlayed / energyAttached attributes, so the
                            # adapter reports both as always-False — but training
                            # slices encode the TRUE flags (pre_state.flags), so an
                            # always-False inference view is a train/inference
                            # feature mismatch that makes the policy sample already-
                            # used supporters / a second attach (no-match). Infer the
                            # true flags here and OVERWRITE the view fields so both
                            # the StateEncoder and _is_legal align with training.
                            try:
                                _off_sup = False
                                _off_attach = False
                                for _o in options:
                                    if int(_o.type) == int(OptionType.ATTACH):
                                        _off_attach = True
                                    elif int(_o.type) == int(OptionType.PLAY):
                                        if _hand_card_id(obs, _o, mi) in _SUPPORTER_IDS:
                                            _off_sup = True
                                _vh = view.get("hand", []) or []
                                _has_sup = any(c in _SUPPORTER_IDS for c in _vh)
                                view["supporter_played"] = bool(_has_sup and not _off_sup)
                                view["energy_attached"] = bool(not _off_attach)
                            except Exception:
                                pass
                            # Tell the proposer which abilities the engine is
                            # actually offering this turn, so it never samples an
                            # already-used ability (e.g. Meowth Last-Ditch) and
                            # wastes a proposal on a no-match.
                            try:
                                from rl_opening_proposer import ability_sources_in_options
                                view["offered_ability_srcs"] = ability_sources_in_options(obs, options, mi)
                            except Exception:
                                pass
                            rl_min_votes = int(os.environ.get("RL_MIN_VOTES", "2"))
                            rl_ranked = os.environ.get("RL_RANKED", "1") != "0"
                            rl_k = int(os.environ.get("RL_K", "4"))
                            rl_idx, rl_conf = prop.propose(
                                obs, options, view, mi, k=rl_k, rng=None,
                                min_votes=rl_min_votes, ranked=rl_ranked,
                            )
                            rl_kind = prop.last_action[0] if prop.last_action else "?"
                            # Conf gate tracks the propose min_votes so lowering
                            # RL_MIN_VOTES actually lets the policy lead more.
                            rl_min_conf = rl_min_votes / float(rl_k)
                            RL_STATS["opening_eligible"] += 1
                            if rl_idx is not None and rl_conf >= rl_min_conf:
                                # Lead unless a hard rule actively suppresses the
                                # option with a strong negative score. Using
                                # _hard_rule_bonus (not option_score) avoids
                                # falsely blocking options whose *baseline* score
                                # is naturally low/negative (e.g. RETREAT weight).
                                hard = _hard_rule_bonus(obs, options[rl_idx], sit)
                                # OPENING ≤T3: only allow takeover when RL agrees
                                # with EarlyMega / EarlyStaryu / EarlyFetch tier
                                # (same DOMINATE_OPEN_PATH band); else keep planner.
                                # Default OFF (ungated): Kaggle ungated ~502 beat
                                # earlygate ~395. Set OPENING_EARLY_RL_GATE=1 to enable.
                                _early_gate = os.environ.get(
                                    "OPENING_EARLY_RL_GATE", "0"
                                ).strip().lower() not in ("0", "false", "off", "no")
                                # Path-kind gate (default ON): ≤T3 only allow
                                # fetch / Staryu / Mega evolve / water attach RL
                                # takeover — other kinds defer to planner.
                                # Set OPENING_PATH_RL_GATE=0 to disable.
                                _path_gate = os.environ.get(
                                    "OPENING_PATH_RL_GATE", "1"
                                ).strip().lower() not in ("0", "false", "off", "no")
                                early_open = board.my_turn_number <= 3
                                early_need_path = (
                                    _early_gate
                                    and early_open
                                    and hard < _DOMINATE_OPEN_PATH - 1.0
                                )
                                path_block = False
                                if _path_gate and early_open and prop.last_action:
                                    _pk, _pp = prop.last_action[0], (
                                        prop.last_action[1]
                                        if len(prop.last_action) > 1 else None
                                    )
                                    path_block = not _is_opening_path_rl_action(
                                        _pk, _pp, obs, options[rl_idx], mi
                                    )
                                if hard <= -_DOMINATE / 2 or early_need_path:
                                    RL_STATS["blocked_by_hardrule"] += 1
                                    _rl_kind_tick("blocked", rl_kind)
                                elif path_block:
                                    RL_STATS["deferred_to_planner"] += 1
                                    _rl_kind_tick("blocked", f"path:{rl_kind}")
                                elif _HYBRID_SCORE_GATE:
                                    # Score-gated fusion (experimental; weaker on cabt).
                                    planner_top = order[0]
                                    sc_rl = option_score(obs, options[rl_idx], w, sit)
                                    sc_pl = option_score(obs, options[planner_top], w, sit)
                                    if sc_rl >= sc_pl:
                                        order = [rl_idx] + [i for i in order if i != rl_idx]
                                        RL_STATS["takeover"] += 1
                                    else:
                                        RL_STATS["deferred_to_planner"] += 1
                                else:
                                    # Conf-gated RL lead (default hybrid / rl-only).
                                    order = [rl_idx] + [i for i in order if i != rl_idx]
                                    RL_STATS["takeover"] += 1
                            elif rl_idx is not None:
                                RL_STATS["low_confidence"] += 1
                            else:
                                RL_STATS["no_option_match"] += 1
                                _rl_kind_tick("nomatch", rl_kind)
                                if len(RL_NOMATCH_SAMPLES) < 80:
                                    try:
                                        _rh = [
                                            _si(getattr(c, "id", None))
                                            for c in (obs.current.players[mi].hand or [])
                                        ]
                                        _oc = []
                                        for _o in options:
                                            if int(_o.type) == int(OptionType.PLAY):
                                                _oc.append(_hand_card_id(obs, _o, mi))
                                        RL_NOMATCH_SAMPLES.append({
                                            "top": prop.last_action,
                                            "view_hand": list(view.get("hand", [])),
                                            "real_hand": _rh,
                                            "offered_play_cids": _oc,
                                            "supporter_played": view.get("supporter_played"),
                                            "energy_attached": view.get("energy_attached"),
                                            "ctx": int(getattr(obs.select, "context", -1)),
                                            "opt_types": [int(o.type) for o in options],
                                        })
                                    except Exception:
                                        pass
                        else:
                            RL_STATS["non_mappable_decision"] += 1
                    except Exception:
                        RL_STATS["proposer_errors"] += 1

            chosen = _collapse_multi_attach(options, order, pick)
            chosen = _sanitize_illegal_attaches(obs, options, order, chosen, sit)
            try:
                ctx_now = int(obs.select.context)
            except Exception:
                ctx_now = -1
            for idx in chosen:
                opt = options[idx]
                if opt.type == OptionType.ATTACK and _attack_id(opt) == _ATK_RESENTFUL:
                    agent_state["harvest_resentful_fired"] = True
                # Crispin nested energy memory for ATTACH_FROM.
                if (
                    ctx_now == int(SelectContext.ATTACH_TO)
                    and opt.type == OptionType.CARD
                ):
                    agent_state["pending_crispin_energy_id"] = _card_option_id(
                        obs, opt, sit["my_index"]
                    )
                elif ctx_now == int(SelectContext.ATTACH_FROM):
                    agent_state["pending_crispin_energy_id"] = None
                elif ctx_now == int(SelectContext.MAIN):
                    # Clear stale Crispin pending at next MAIN decision.
                    if opt.type in (
                        OptionType.END,
                        OptionType.ATTACK,
                        OptionType.PLAY,
                    ):
                        agent_state["pending_crispin_energy_id"] = None
            return chosen
        except Exception:
            try:
                obs = to_observation_class(obs_dict)
                if obs.select is None:
                    return []
                n = len(obs.select.option or [])
                if n == 0:
                    return []
                pick = _select_pick_count(obs, n)
                return list(range(pick))
            except Exception:
                return [0]

    # Expose the live agent_state so local harnesses can reset per-game flags
    # (e.g. opening_complete_this_game) at game boundaries — the harness, not the
    # agent, knows when a new battle starts in the local simulator.
    global _LIVE_AGENT_STATE
    _LIVE_AGENT_STATE = agent_state
    return agent


_LIVE_AGENT_STATE: dict[str, Any] | None = None


def reset_for_new_game() -> None:
    """Reset per-game flags in the live agent_state. Call before each game in
    local harnesses so OPENING-completion accounting is per-game."""
    if _LIVE_AGENT_STATE is not None:
        _LIVE_AGENT_STATE["opening_complete_this_game"] = False
        _LIVE_AGENT_STATE["max_my_turn"] = 0
        _LIVE_AGENT_STATE["final_board"] = None
        _LIVE_AGENT_STATE["mega_on_field_by_my_turn_4"] = False
        _LIVE_AGENT_STATE["mega_on_field_by_my_turn_3"] = False
        _LIVE_AGENT_STATE["mega_first_seen_my_turn"] = None
        _LIVE_AGENT_STATE["staryu_on_field_by_my_turn_1"] = False
        _LIVE_AGENT_STATE["staryu_on_field_by_my_turn_2"] = False
        _LIVE_AGENT_STATE["staryu_first_seen_my_turn"] = None
        _LIVE_AGENT_STATE["usable_mega_by_my_turn_2"] = False
        _LIVE_AGENT_STATE["usable_mega_by_my_turn_3"] = False
        _LIVE_AGENT_STATE["epoch_memory"] = default_epoch_memory()
        _LIVE_AGENT_STATE["board_at_my_turn_1"] = None
        _LIVE_AGENT_STATE["board_at_my_turn_4"] = None
        _LIVE_AGENT_STATE["board_at_my_turn_3"] = None
        _LIVE_AGENT_STATE["opening_complete_my_turn"] = None
        _LIVE_AGENT_STATE["pending_crispin_energy_id"] = None
        _LIVE_AGENT_STATE["harvest_resentful_fired"] = False
        _LIVE_AGENT_STATE["harvest_ko_last_turn"] = False
        _LIVE_AGENT_STATE["matchup_alakazam_confirmed"] = False
        _LIVE_AGENT_STATE["alak_finisher_window"] = False
        _LIVE_AGENT_STATE["alak_follow_window"] = False
        _LIVE_AGENT_STATE["alak_budew_ko_last_opp_turn"] = False
        _LIVE_AGENT_STATE["alak_budew_ko_pending"] = False
        _LIVE_AGENT_STATE["alak_prev_my_had_budew"] = False
        _LIVE_AGENT_STATE["alak_last_my_turn"] = -1
        _LIVE_AGENT_STATE["prize_progress"] = {"last": 6, "turn": 0}

