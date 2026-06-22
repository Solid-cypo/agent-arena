"""Deck-specific pilot for the Starmie ex + Froslass ex dual-Mega deck.

Two-layer architecture:
  Layer 1 — deterministic hard rules (return DOMINATE score, always wins the sort)
  Layer 2 — soft trainable nudges (bounded ~0-5, nudges the generic baseline)

Public API:
  make_starmie_agent(deck, weights) -> AgentFn
  DEFAULT_WEIGHTS                   -> dict[str, float]   (soft dims only)
"""
from __future__ import annotations

import random
from typing import Any, Callable

from cg.api import AreaType, EnergyType, OptionType, all_card_data, to_observation_class

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

_MEGA_EX_IDS    = {_CARDS["mega_starmie_ex"], _CARDS["mega_froslass_ex"]}
_STARMIE_LINE   = {_CARDS["staryu"], _CARDS["mega_starmie_ex"]}
_FROSLASS_LINE  = {_CARDS["snorunt"], _CARDS["froslass"], _CARDS["mega_froslass_ex"]}
_MUNKIDORI_ID   = _CARDS["munkidori"]
_FAN_ROTOM_ID   = _CARDS["fan_rotom"]
_BUDEW_ID       = _CARDS["budew"]
_BOSS_ID        = _CARDS["boss_orders"]

# Dominating score — hard-rule options always sort first
_DOMINATE = 1_000.0

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
    """True when the Pokemon has at least one Darkness energy attached."""
    try:
        energies = getattr(pokemon, "energies", None) or []
        return any(_si(e) == int(EnergyType.DARKNESS) for e in energies)
    except Exception: return False

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


# ── Situation dict ────────────────────────────────────────────────────────────

def _compute_situation(obs) -> dict[str, Any]:
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

    except Exception: pass
    return sit


# ── Soft-dim default weights (Layer 2 only, bounded 0-5) ─────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    # Layer 2 soft dims
    "froslass_harvest":  1.5,   # Evolve to Mega Froslass ex when opp hand big / just took prize
    "jetting_blow_pref": 1.2,   # Prefer Jetting Blow (attack id 1487) for bench spread
    "nebula_finish":     2.0,   # Prefer Nebula Beam (attack id 1488) when it secures KO
    "boss_gust_path":    1.8,   # Boss's Orders onto prize-path bench target
    # Generic baseline dims forwarded to generic scorer (kept in sync with policy.py)
    "attack":        3.0, "attach":        2.0, "evolve":   1.7,
    "play":          1.2, "ability":       1.0, "retreat": -0.2,
    "yes":           0.1, "no":            0.0, "card_basic": 1.1,
    "card_pokemon":  0.6, "card_energy":   0.45,"card_trainer": 0.35,
    "damage_target": 1.5, "own_damaged":   0.75,"active_bonus": 0.4,
    "bench_penalty":-0.1, "random_noise":  0.02,
}

# Attack IDs from card_db
_ATK_JETTING_BLOW  = 1487   # Mega Starmie ex: 120 + bench 50 (1 Water)
_ATK_NEBULA_BEAM   = 1488   # Mega Starmie ex: 210 ignore effects (3 Colorless)
_ATK_RESENTFUL     = 1240   # Mega Froslass ex: 50×opp_hand (1 Water)
_ATK_ABS_SNOW      = 1241   # Mega Froslass ex: 150 + Sleep (Water+CC)
_ATK_ITCHY_POLLEN  = 323    # Budew: 0 energy, blocks opp Items next turn


# ── Layer 1: hard-rule interceptor ───────────────────────────────────────────

def _hard_rule_bonus(obs, option, sit: dict[str, Any]) -> float:
    """Return _DOMINATE if a hard rule fires; 0 otherwise."""
    mi   = sit["my_index"]
    turn = sit["turn"]

    # HR-1  Fan Rotom Fan Call — use on FIRST TURN ONLY
    # State.turn: 1 = first player's turn 1, 2 = second player's turn 1.
    if option.type == OptionType.ABILITY and turn <= 2:
        src_id = _ability_source_id(obs, option, mi)
        if src_id == _FAN_ROTOM_ID:
            return _DOMINATE

    # HR-2  Munkidori Adrena-Brain — always move damage counters when available
    if option.type == OptionType.ABILITY:
        src_id = _ability_source_id(obs, option, mi)
        if src_id == _MUNKIDORI_ID:
            # Only fire if Munkidori has Darkness energy
            try:
                idx   = _si(getattr(option, "index", None), -1)
                pkm   = _pokemon_in_area(obs, option.area, idx, mi)
                if pkm and _has_darkness_energy(pkm):
                    return _DOMINATE
            except Exception: pass

    # HR-3  Budew Itchy Pollen — fallback stall when no Mega ex is ready turn 2+
    if option.type == OptionType.ATTACK and turn >= 3:
        if not sit["mega_ready"]:
            atk_id = _attack_id(option)
            if atk_id == _ATK_ITCHY_POLLEN:
                return _DOMINATE * 0.5   # strong but below ability dominance

    return 0.0


# ── Layer 2: soft situational nudges ─────────────────────────────────────────

def _soft_bonus(obs, option, weights: dict[str, float], sit: dict[str, Any]) -> float:
    mi        = sit["my_index"]
    opp_hand  = sit["opp_hand_count"]
    prize_ids = sit["prize_path_ids"]
    bonus     = 0.0

    # S-1  Prefer evolving to Mega Froslass ex when harvest window is open
    if option.type == OptionType.EVOLVE:
        try:
            hand = obs.current.players[mi].hand or []
            idx  = _si(getattr(option, "index", None), -1)
            card = (obs.select.deck[idx] if option.area == AreaType.DECK
                    else hand[idx] if option.area == AreaType.HAND else None)
            if card and _si(getattr(card, "id", None)) == _CARDS["mega_froslass_ex"]:
                harvest_window = (
                    opp_hand >= 5 or sit["opp_just_took_prize"]
                )
                if harvest_window:
                    bonus += weights.get("froslass_harvest", 1.5)
        except Exception: pass

    # S-2  Prefer Jetting Blow for bench spread (default attack path)
    elif option.type == OptionType.ATTACK:
        atk = _attack_id(option)
        if atk == _ATK_JETTING_BLOW:
            bonus += weights.get("jetting_blow_pref", 1.2)

        # S-3  Prefer Nebula Beam when active opponent is in prize path (KO range)
        if atk == _ATK_NEBULA_BEAM:
            try:
                opp_active = (obs.current.players[1 - mi].active or [None])[0]
                if opp_active:
                    opp_cid = _si(getattr(opp_active, "id", None))
                    opp_hp  = _si(getattr(opp_active, "hp", None), 9999)
                    if opp_cid in prize_ids and opp_hp <= 220:
                        bonus += weights.get("nebula_finish", 2.0)
            except Exception: pass

        # S-4  Resentful Refrain scales with opponent hand size
        if atk == _ATK_RESENTFUL:
            # Extra nudge beyond baseline attack weight; hand scaling handles the rest
            expected_dmg = opp_hand * 50
            if expected_dmg >= 200:
                bonus += 1.0   # soft nudge to tip over Jetting Blow when very strong

    # S-5  Boss's Orders to pull up a prize-path bench target
    elif option.type == OptionType.PLAY:
        cid = _hand_card_id(obs, option, mi)
        if cid == _BOSS_ID:
            try:
                oi   = 1 - mi
                bch  = obs.current.players[oi].bench or []
                bidx = _si(getattr(option, "index", None), -1)
                if 0 <= bidx < len(bch) and bch[bidx]:
                    tgt_cid = _si(getattr(bch[bidx], "id", None))
                    if tgt_cid in prize_ids:
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
    if hard > 0:
        return hard
    return _baseline_score(obs, option, weights) + _soft_bonus(obs, option, weights, sit)


# ── Public agent factory ──────────────────────────────────────────────────────

def make_starmie_agent(deck: list[int], weights: dict[str, float] | None = None) -> AgentFn:
    """Build an AgentFn for the starmie_froslass deck."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    def agent(obs_dict: dict[str, Any]) -> list[int]:
        if obs_dict.get("select") is None:
            return deck
        try:
            obs     = to_observation_class(obs_dict)
            options = obs.select.option
            if not options:
                return []
            sit   = _compute_situation(obs)
            order = sorted(
                range(len(options)),
                key=lambda i: option_score(obs, options[i], w, sit),
                reverse=True,
            )
            min_c = max(0, int(obs.select.minCount))
            max_c = min(len(options), int(obs.select.maxCount))
            pick  = max(1, min(max_c, max(min_c, 1)))
            return order[:pick]
        except Exception:
            try:
                obs = to_observation_class(obs_dict)
                pick = max(1, min(len(obs.select.option), int(obs.select.maxCount)))
                return list(range(pick))
            except Exception:
                return [0]

    return agent
