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
    CRISPIN,
    DARK_BASIC,
    FROSLASS as _OC_FROSLASS,
    JUDGE,
    LILLIE,
    MEOWTH_EX as _OC_MEOWTH_EX,
    MUNKIDORI as _OC_MUNKIDORI,
    POKE_PAD as _OC_POKE_PAD,
    POFFIN as _OC_POFFIN,
    PRISM as _OC_PRISM,
    RISKY_RUINS as _RISKY_RUINS,
    SNORUNT as _OC_SNORUNT,
    STARYU as _OC_STARYU,
    SWITCH as _OC_SWITCH,
    UNFAIR_STAMP,
    WATER_BASIC,
    can_retreat_pokemon,
    ENERGY_IDS as _ENERGY_IDS,
    WATER_ENERGY_IDS as _WATER_ENERGY_IDS,
)
from opening_bridge import compute_opening_route, score_opening_option
from phase_fsm import compute_phase, opening_complete
from supporter_planner import lillie_forbidden, pick_supporter

_MEGA_EX_IDS    = {_CARDS["mega_starmie_ex"], _CARDS["mega_froslass_ex"]}
_STARMIE_LINE   = {_CARDS["staryu"], _CARDS["mega_starmie_ex"]}
_FROSLASS_LINE  = {_CARDS["snorunt"], _CARDS["froslass"], _CARDS["mega_froslass_ex"]}
_MUNKIDORI_ID   = _CARDS["munkidori"]
_FAN_ROTOM_ID   = _CARDS["fan_rotom"]
_BUDEW_ID       = _CARDS["budew"]
_BOSS_ID        = _CARDS["boss_orders"]

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


def _synergy_core_ready(board) -> bool:
    """Froslass 104 + Munkidori + dark all online."""
    return (
        board.froslass_104_on_field
        and board.munkidori_on_field
        and board.munkidori_has_dark
    )


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


def _mega_froslass_needs_water(board) -> bool:
    return board.active_is_mega_froslass and not board.active_has_water


def _hand_has_water_energy(obs, my_index: int) -> bool:
    try:
        for c in obs.current.players[my_index].hand or []:
            if c and _si(getattr(c, "id", None)) in _WATER_ENERGY_IDS:
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

    # HR-H7  Unfair Stamp right after Mega Starmie ex KO (beats evolve on that turn)
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == UNFAIR_STAMP and sit.get("harvest_ko_last_turn"):
            return _DOMINATE_OPEN

    # HR-H8  Boss's Orders onto prize-path bench target
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == _BOSS_ID and hand_ctx and hand_ctx.gust_target_on_opp_bench:
            return _DOMINATE_SUPPORT

    # HR-H6  Forbid Judge in HARVEST until Resentful fired (HR-C3 allows after)
    if option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == JUDGE:
            if not (phase.control_active and sit.get("harvest_resentful_fired")):
                return -_DOMINATE

    # HR-H1  Evolve → Mega Froslass ex when 104 engine online (HR-8b gate)
    if option.type == OptionType.EVOLVE:
        if _evolve_to_mega_froslass_ex(obs, option, mi):
            if not board.froslass_104_on_field:
                return -_DOMINATE
            if _block_mega_froslass_evolve(obs, mi, board, phase, option):
                return -_DOMINATE
            return _DOMINATE

    # HR-H2  Attach water to Active 861 before Resentful
    if option.type == OptionType.ATTACH and _mega_froslass_needs_water(board):
        target = _attach_target_pokemon(obs, option, mi)
        eid = _attach_energy_id(obs, option, mi)
        active = _active_pokemon(obs, mi)
        if target is active and eid in _WATER_ENERGY_IDS:
            return _DOMINATE_PLUS

    # HR-H3 / HR-H4  Resentful default; Absorbing Snow only when hand is small
    if option.type == OptionType.ATTACK and _mega_froslass_should_attack(board):
        atk_id = _attack_id(option)
        if atk_id == _ATK_RESENTFUL:
            return _DOMINATE_ATTACK
        if atk_id == _ATK_ABS_SNOW and opp_hand * 50 < 200:
            return _DOMINATE_ATTACK * 0.5

    # HR-H5  Penalize END when Mega Froslass should attack
    if option.type == OptionType.END and _mega_froslass_should_attack(board):
        return -_DOMINATE

    # HR-H5b  Penalize END when 861 can attach water this turn
    if (
        option.type == OptionType.END
        and _mega_froslass_needs_water(board)
        and _hand_has_water_energy(obs, mi)
    ):
        return -_DOMINATE

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
            if phase.primary == "HARVEST":
                if not sit.get("harvest_resentful_fired"):
                    return 0.0
                if _mega_froslass_should_attack(board):
                    return 0.0
            elif _control_blocks_setup(board, phase):
                return 0.0
            return _DOMINATE_SUPPORT
        if cid == _OC_MEOWTH_EX:
            if board.bench_open <= 0 or _meowth_on_field(obs, mi):
                return 0.0
            if _control_blocks_setup(board, phase):
                return 0.0
            return _DOMINATE_MID
        if cid == _BOSS_ID and phase.primary == "AGGRESSION":
            if hand_ctx and hand_ctx.gust_target_on_opp_bench:
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
        idx = _si(getattr(option, "inPlayIndex", None), _si(getattr(option, "index", None), -1))
        p = obs.current.players[my_index]
        if area == AreaType.ACTIVE:
            return (p.active or [])[idx]
        if area == AreaType.BENCH:
            return (p.bench or [])[idx]
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
    """Stuck on non-Starmie Active without retreat energy — swap or attach out."""
    if phase.primary not in ("AGGRESSION", "OPENING"):
        return False
    if board.active_is_mega_starmie:
        return False
    if phase.primary == "OPENING" and not board.mega_starmie_on_field:
        return False
    active = _active_pokemon(obs, my_index)
    if not active:
        return False
    aid = _si(getattr(active, "id", None))
    if aid in _MEGA_EX_IDS:
        return False
    energies = [_si(e) for e in (getattr(active, "energies", None) or [])]
    return not can_retreat_pokemon(aid, energies)


def _attach_energy_to_active(obs, option, my_index: int) -> bool:
    if option.type != OptionType.ATTACH:
        return False
    target = _attach_target_pokemon(obs, option, my_index)
    active = _active_pokemon(obs, my_index)
    if not target or not active or target is not active:
        return False
    eid = _attach_energy_id(obs, option, my_index)
    return eid in _ENERGY_IDS


def _block_mega_froslass_evolve(obs, my_index: int, board, phase, option) -> bool:
    """HR-8b / Froslass 104 bench lock — block 861 outside HARVEST or without Snorunt backup."""
    if phase.primary != "HARVEST":
        return True
    if _count_froslass_104_on_field(obs, my_index) == 1:
        if _evolve_target_is_froslass_104(obs, option, my_index):
            return not _snorunt_on_bench(obs, my_index)
    if not board.froslass_104_on_field:
        return True
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
    """My-T2..T8 window for Froslass (104) + Munkidori bench synergy."""
    return 2 <= board.my_turn_number <= 8


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


def _synergy_search_bonus(obs, option, board, phase, my_index: int) -> float:
    """Prefer Snorunt / Froslass / Munk when searching deck (Pad, Hilda, Ball)."""
    if not _synergy_window(board, phase):
        return 0.0
    if option.type != OptionType.CARD:
        return 0.0
    try:
        ctx = int(obs.select.context)
    except Exception:
        return 0.0
    if ctx not in (
        int(SelectContext.TO_HAND),
        int(SelectContext.TO_FIELD),
        int(SelectContext.TO_BENCH),
    ):
        return 0.0
    cid = _card_option_id(obs, option, my_index)
    if cid == _OC_SNORUNT and not board.snorunt_line_on_bench:
        return _DOMINATE
    if (
        cid == _OC_FROSLASS
        and not board.froslass_104_on_field
        and (board.snorunt_line_on_bench or cid)
    ):
        return _DOMINATE
    if cid == _OC_MUNKIDORI and not board.munkidori_on_field:
        return _DOMINATE_MID
    return 0.0


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

        # Prize-path: opponent targets whose combined prize value covers self prizes left
        opp_board  = _board_pokemon(opp)
        path_ids: set[int] = set()
        needed = sit["prize_self"]
        for p in sorted(opp_board, key=lambda x: _si(getattr(x, "hp", None), 999)):
            if needed <= 0: break
            cid = _si(getattr(p, "id", None))
            if cid > 0:
                path_ids.add(cid)
                needed -= (2 if cid in _ex_card_set() else 1)
        sit["prize_path_ids"] = path_ids
        board = build_board_snapshot(obs)
        phase = compute_phase(board)
        sit["board"] = board
        sit["phase"] = phase
        sit["opening_complete"] = opening_complete(board)

        if agent_state is not None:
            _refresh_harvest_ko(agent_state, board)
            sit["harvest_ko_last_turn"] = agent_state.get("harvest_ko_last_turn", False)
            sit["harvest_resentful_fired"] = agent_state.get("harvest_resentful_fired", False)
        else:
            sit["harvest_ko_last_turn"] = False
            sit["harvest_resentful_fired"] = False

        gust = _gust_target_on_opp_bench(obs, mi, path_ids)
        hand = build_hand_context_from_obs(obs, gust_target_on_opp_bench=gust)
        resources = build_deck_resources(obs, deck_template=deck_template)
        sit["hand"] = hand
        sit["resources"] = resources

        d66_bench = _bench_has_id(obs, mi, _CARDS["dudunsparce"])
        dun_evolve = _dunsparce_on_bench_can_evolve(obs, mi)
        hp_low = _mega_starmie_hp_low(obs, mi)

        sit["supporter_dec"] = pick_supporter(
            board, phase, hand, resources, mega_starmie_damaged=hp_low,
            harvest_ko_last_turn=sit["harvest_ko_last_turn"],
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

    except Exception: pass
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

    if option.type == OptionType.PLAY and cid == LILLIE:
        forbidden, _rule = lillie_forbidden(board, phase, hand, resources)
        if forbidden:
            return -_DOMINATE

    sup = sit.get("supporter_dec")
    if sup and sup.action == "PLAY" and option.type == OptionType.PLAY:
        if cid == sup.card_id:
            return _planner_score(sup.priority)

    draw = sit.get("draw_axis_dec")
    if draw and draw.action == "ABILITY_DRAW" and option.type == OptionType.ABILITY:
        if _ability_source_id(obs, option, mi) == _CARDS["dudunsparce"]:
            return _planner_score(draw.priority)

    if draw and draw.action in ("EVOLVE_66",) and _evolve_to_dudunsparce(obs, option, mi):
        return _planner_score(draw.priority)

    if draw and draw.action == "PLAY_306" and option.type == OptionType.PLAY:
        if cid == _CARDS["dudunsparce_ex"]:
            return _planner_score(draw.priority)

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

    axis_bonus = _layer1_supporter_draw_axis(
        obs, option, sit, mi, board, phase, hand, resources,
    )
    if axis_bonus != 0.0:
        return axis_bonus

    # HR-O Main — opening_planner route (Step A); wins over legacy HR-O* / synergy
    if phase.primary == "OPENING":
        path_bonus = score_opening_option(
            obs,
            option,
            board=board,
            hand=hand,
            resources=resources,
            phase=phase,
            my_index=mi,
            route=sit.get("opening_route"),
        )
        if path_bonus != 0.0:
            return path_bonus

    if phase.primary != "OPENING":
        search_bonus = _synergy_search_bonus(obs, option, board, phase, mi)
        if search_bonus != 0.0:
            return search_bonus

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

    # HR-1  Fan Rotom Fan Call — OPENING My-T1 only
    if option.type == OptionType.ABILITY and phase.primary == "OPENING" and board.my_turn_number <= 1:
        src_id = _ability_source_id(obs, option, mi)
        if src_id == _FAN_ROTOM_ID:
            return _DOMINATE

    synergy = _synergy_window(board, phase)
    post_opening = board.my_turn_number >= 2
    retreat_rescue = _needs_retreat_rescue(obs, mi, board, phase)

    # HR-O5  OPENING G5 — Switch bench Mega Starmie (+water) to Active
    if option.type == OptionType.PLAY and phase.primary == "OPENING":
        cid = _hand_card_id(obs, option, mi)
        if cid == _OC_SWITCH and _opening_g5_switch_needed(phase, board, obs, mi):
            return _DOMINATE_OPEN

    # HR-O4  OPENING — evolve Staryu → Mega Starmie ex (after synergy core in T2–T8)
    if option.type == OptionType.EVOLVE and phase.primary == "OPENING" and post_opening:
        if _evolve_to_mega_starmie(obs, option, mi):
            if _defer_mega_promotion(board, phase):
                return 0.0
            return _DOMINATE

    # HR-O3  OPENING — attach water to Staryu / bench Mega missing water
    if option.type == OptionType.ATTACH and phase.primary == "OPENING" and post_opening:
        target = _attach_target_pokemon(obs, option, mi)
        eid = _attach_energy_id(obs, option, mi)
        if target and eid in _ENERGY_IDS:
            tid = _si(getattr(target, "id", None))
            if tid == _OC_STARYU and not _has_water_energy(target):
                return _DOMINATE_PLUS
            if tid == _CARDS["mega_starmie_ex"] and not _has_water_energy(target):
                return _DOMINATE_PLUS

    # HR-O2  OPENING — bench Staryu when attack line absent
    if (
        option.type == OptionType.PLAY
        and phase.primary == "OPENING"
        and board.bench_open > 0
        and not board.staryu_on_field
        and not board.mega_starmie_on_field
    ):
        if _hand_card_id(obs, option, mi) == _OC_STARYU:
            return _DOMINATE_MID

    # HR-9  Retreat rescue — AGGRESSION off-Starmie active with no retreat energy
    if retreat_rescue and not _defer_mega_promotion(board, phase):
        if option.type == OptionType.PLAY:
            cid = _hand_card_id(obs, option, mi)
            if cid == _OC_SWITCH:
                return _DOMINATE_RESCUE
            if cid == _OC_POKE_PAD:
                return _DOMINATE_PLUS
        if option.type == OptionType.ATTACH and _attach_energy_to_active(obs, option, mi):
            return _DOMINATE_PLUS

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

    # HR-3 / HR-11 — synergy bench (AGGRESSION+ only; OPENING uses path planner)
    if phase.primary != "OPENING" and option.type == OptionType.PLAY and synergy and board.bench_open > 0:
        cid = _hand_card_id(obs, option, mi)
        if cid == _OC_SNORUNT and not board.snorunt_line_on_bench:
            return _DOMINATE if board.munkidori_on_bench else _DOMINATE_MID
        if cid == _OC_MUNKIDORI and not board.munkidori_on_field:
            return _DOMINATE

    # HR-11  Synergy engine — Poké Pad when Snorunt/Froslass line missing
    if (
        phase.primary != "OPENING"
        and option.type == OptionType.PLAY
        and synergy
        and not board.snorunt_line_on_bench
        and not board.froslass_104_on_field
    ):
        cid = _hand_card_id(obs, option, mi)
        if cid == _OC_POKE_PAD:
            if resources.copies_left(_OC_SNORUNT) > 0 or resources.copies_left(_OC_FROSLASS) > 0:
                return _DOMINATE_PLUS
        if cid == _OC_POFFIN and board.bench_open > 0:
            return _DOMINATE_PLUS

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

    # HR-4  Attach dark/prism to any Munkidori missing dark (My-T2+)
    if option.type == OptionType.ATTACH and post_opening:
        target = _attach_target_pokemon(obs, option, mi)
        eid = _attach_energy_id(obs, option, mi)
        if (
            target
            and _si(getattr(target, "id", None)) == _MUNKIDORI_ID
            and not _has_darkness_energy(target)
            and eid in (_OC_PRISM, DARK_BASIC)
        ):
            if synergy and board.munkidori_on_field:
                return _DOMINATE_PLUS
            return _DOMINATE

    # HR-5  Risky Ruins — only after Snorunt line + Munkidori on bench
    if option.type == OptionType.PLAY and synergy:
        if _hand_card_id(obs, option, mi) == _RISKY_RUINS and board.bench_three_core_ready:
            return _DOMINATE_LOW

    # HR-8  Evolve Snorunt→104 engine; block premature 861 outside HARVEST (HR-8b)
    if option.type == OptionType.EVOLVE and post_opening:
        if _evolve_to_froslass_104(obs, option, mi):
            if not board.froslass_104_on_field:
                return _DOMINATE_OPEN if synergy else _DOMINATE
        if _evolve_to_mega_froslass_ex(obs, option, mi):
            if phase.primary != "HARVEST":
                return -_DOMINATE
            if _block_mega_froslass_evolve(obs, mi, board, phase, option):
                return -_DOMINATE
            if board.froslass_104_on_field:
                return _DOMINATE

    # HR-6  Mega Starmie must attack (AGGRESSION / OPENING late — not HARVEST backup)
    if option.type == OptionType.ATTACK and _starmie_should_attack(board):
        if phase.primary == "AGGRESSION" or (
            phase.primary == "OPENING" and board.my_turn_number >= 2
        ):
            atk_id = _attack_id(option)
            if atk_id == _ATK_NEBULA_BEAM and _nebula_ko_available(obs, mi, prize_ids):
                return _DOMINATE_PLUS
            if atk_id == _ATK_JETTING_BLOW:
                return _DOMINATE_ATTACK

    # HR-6b  Penalize END when Mega Starmie should attack
    if option.type == OptionType.END and _starmie_should_attack(board):
        if phase.primary == "AGGRESSION" or (
            phase.primary == "OPENING" and board.my_turn_number >= 2
        ):
            return -_DOMINATE

    # HR-7  Budew Itchy Pollen — OPENING stall when no Mega ex ready
    if option.type == OptionType.ATTACK and phase.primary == "OPENING" and turn >= 3:
        if not sit["mega_ready"]:
            atk_id = _attack_id(option)
            if atk_id == _ATK_ITCHY_POLLEN:
                return _DOMINATE * 0.5

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
    elif option.type == OptionType.PLAY:
        if _hand_card_id(obs, option, mi) == _BOSS_ID:
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
_RL_ENABLED = True  # toggle for A/B comparison in local audits


def _rl_proposer():
    """Lazy-load the numpy RL proposer from pilot/rl_opening.{npz,json}."""
    global _RL_PROPOSER, _RL_TRIED
    if _RL_TRIED:
        return _RL_PROPOSER
    _RL_TRIED = True
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        prefix = os.path.join(base, "rl_opening")
        if os.path.exists(prefix + ".npz") and os.path.exists(prefix + ".json"):
            from rl_opening_proposer import RLProposer  # noqa: E402
            _RL_PROPOSER = RLProposer.load(prefix)
    except Exception:
        _RL_PROPOSER = None
    return _RL_PROPOSER


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
    "low_confidence": 0,
    "no_option_match": 0,
    "non_mappable_decision": 0,
    "proposer_errors": 0,
    "games_started": 0,
    "opening_complete_games": 0,
}
RL_KIND_STATS: dict[str, dict[str, int]] = {"blocked": {}, "nomatch": {}}


def _rl_kind_tick(bucket: str, kind: str) -> None:
    d = RL_KIND_STATS.setdefault(bucket, {})
    d[kind] = d.get(kind, 0) + 1


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
            # Per-game OPENING-completion flag (set once when the opening is
            # completed). The local harness resets this before each game via
            # `reset_for_new_game()` and reads it after, since the harness — not
            # the agent — knows the game boundary.
            if sit.get("opening_complete") and not agent_state.get("opening_complete_this_game"):
                agent_state["opening_complete_this_game"] = True
                RL_STATS["opening_complete_games"] += 1
            order = sorted(
                range(len(options)),
                key=lambda i: option_score(obs, options[i], w, sit),
                reverse=True,
            )
            min_c = max(0, int(obs.select.minCount))
            max_c = min(len(options), int(obs.select.maxCount))
            pick  = max(1, min(max_c, max(min_c, 1)))

            # ── RL Actor-Expert override (OPENING only, single-select) ──────────
            # The torch-free numpy proposer votes among K policy samples; when it
            # reaches strong consensus it leads the turn, otherwise the v1
            # planner route + hard rules (computed above) stay in charge.
            phase = sit.get("phase")
            board = sit.get("board")
            if (
                _RL_ENABLED
                and pick == 1
                and phase is not None
                and phase.primary == "OPENING"
                and board is not None
                and board.my_turn_number >= 1
            ):
                prop = _rl_proposer()
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
                            # Tell the proposer which abilities the engine is
                            # actually offering this turn, so it never samples an
                            # already-used ability (e.g. Meowth Last-Ditch) and
                            # wastes a proposal on a no-match.
                            try:
                                from rl_opening_proposer import ability_sources_in_options
                                view["offered_ability_srcs"] = ability_sources_in_options(obs, options, mi)
                            except Exception:
                                pass
                            rl_idx, rl_conf = prop.propose(
                                obs, options, view, mi, k=4, rng=None,
                            )
                            rl_kind = prop.last_action[0] if prop.last_action else "?"
                            RL_STATS["opening_eligible"] += 1
                            if rl_idx is not None and rl_conf >= _RL_MIN_CONF:
                                # Lead unless a hard rule actively suppresses the
                                # option with a strong negative score. Using
                                # _hard_rule_bonus (not option_score) avoids
                                # falsely blocking options whose *baseline* score
                                # is naturally low/negative (e.g. RETREAT weight).
                                hard = _hard_rule_bonus(obs, options[rl_idx], sit)
                                if hard > -_DOMINATE / 2:
                                    order = [rl_idx] + [i for i in order if i != rl_idx]
                                    RL_STATS["takeover"] += 1
                                else:
                                    RL_STATS["blocked_by_hardrule"] += 1
                                    _rl_kind_tick("blocked", rl_kind)
                            elif rl_idx is not None:
                                RL_STATS["low_confidence"] += 1
                            else:
                                RL_STATS["no_option_match"] += 1
                                _rl_kind_tick("nomatch", rl_kind)
                        else:
                            RL_STATS["non_mappable_decision"] += 1
                    except Exception:
                        RL_STATS["proposer_errors"] += 1

            chosen = order[:pick]
            for idx in chosen:
                opt = options[idx]
                if opt.type == OptionType.ATTACK and _attack_id(opt) == _ATK_RESENTFUL:
                    agent_state["harvest_resentful_fired"] = True
            return chosen
        except Exception:
            try:
                obs = to_observation_class(obs_dict)
                pick = max(1, min(len(obs.select.option), int(obs.select.maxCount)))
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
