"""28-dimensional situation-aware policy.

Original 16 dims: action shape (attack/attach/evolve/play/...)
New 12 dims: situation cross-features (prize clock, energy urgency, stagger, etc.)

All 28 weights are jointly optimised by train_weights.py evolutionary search.
New situational weights initialise to 0.0 (neutral) so backward compatibility
with existing trained weight files is preserved.
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable

from cg.api import AreaType, CardType, OptionType, all_card_data, to_observation_class

AgentFn = Callable[[dict[str, Any]], list[int]]

# ── 16 original dims (action-shape, learned by evolution) ────────────────────
_BASE_WEIGHTS: dict[str, float] = {
    "attack":        3.0,
    "attach":        2.0,
    "evolve":        1.7,
    "play":          1.2,
    "ability":       1.0,
    "retreat":      -0.2,
    "yes":           0.1,
    "no":            0.0,
    "card_basic":    1.1,
    "card_pokemon":  0.6,
    "card_energy":   0.45,
    "card_trainer":  0.35,
    "damage_target": 1.5,
    "own_damaged":   0.75,
    "active_bonus":  0.4,
    "bench_penalty": -0.1,
    "random_noise":  0.02,
}

# ── 12 new situational dims (zero init → trained) ────────────────────────────
# Resource planning
# s1: ATTACH × (1 - attacker_e_ratio)  urgency signal
# s2: EVOLVE when it creates the main attacker
# s3: PLAY Pokemon when bench is under-developed (< 2 Pokemon)
# s4: PLAY search card when attacker not on board yet
# s5: ATTACH to bench (secondary pipeline)
# s6: PLAY supporter/draw card when hand < 3
# Game tempo
# s7: ATTACK when active opp is on prize-path
# s8: PLAY Boss's Orders (1182) when target is on prize-path
# s9: RETREAT × (active is ex) × (opp_can_ko)  錯開送奨 core
# s10: PLAY non-ex basic to bench when opp_prize_delta < 0 (build shield)
# s11: ATTACK × (prize_left_self ≤ 2)  terminal sprint bonus
# s12: ATTACK with card-id 311 × window(opp_prize ∈ {3,4})  Cramorant gate
_SITUATIONAL_WEIGHTS: dict[str, float] = {
    "attach_urgency":        0.0,
    "evolve_attacker":       0.0,
    "bench_setup":           0.0,
    "search_attacker":       0.0,
    "attach_secondary":      0.0,
    "draw_hand_empty":       0.0,
    "attack_prize_path":     0.0,
    "boss_prize_path":       0.0,
    "stagger_retreat":       0.0,
    "shield_bench":          0.0,
    "sprint_prize_2":        0.0,
    "cramorant_gate":        0.0,
}

DEFAULT_WEIGHTS: dict[str, float] = {**_BASE_WEIGHTS, **_SITUATIONAL_WEIGHTS}

# ── Card metadata caches ──────────────────────────────────────────────────────
_CARD_META: dict[int, tuple[int, bool]] | None = None   # cardId → (cardType, is_basic)
_EX_CARDS: set[int] | None = None                        # cardIds that are ex or megaEx


def card_meta_table() -> dict[int, tuple[int, bool]]:
    global _CARD_META
    if _CARD_META is None:
        _CARD_META = {
            card.cardId: (int(card.cardType), bool(card.basic))
            for card in all_card_data()
        }
    return _CARD_META


def ex_card_set() -> set[int]:
    global _EX_CARDS
    if _EX_CARDS is None:
        _EX_CARDS = {
            card.cardId for card in all_card_data()
            if getattr(card, "ex", False) or getattr(card, "megaEx", False)
        }
    return _EX_CARDS


# ── Situation dict computed once per turn ─────────────────────────────────────

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def compute_situation(obs) -> dict[str, Any]:
    """Extract turn-level signals used by the 12 new situational features.

    Called once per turn in choose_options; result passed to every option_score.
    Returns a safe default dict on any exception.
    """
    sit: dict[str, Any] = {
        "prize_left_self": 6,
        "prize_left_opp": 6,
        "opp_prize_delta": 0,        # (opp taken) - (self taken): positive = opp ahead
        "self_hand_count": 5,
        "opp_hand_count": 5,
        "bench_count_self": 0,
        "best_attacker_idx": 0,      # board index of best attacker (0 = active)
        "attacker_e_ratio": 0.5,     # attached / required energy ∈ [0,1]
        "prize_path_ids": set(),     # opp card IDs on optimal KO path
        "opp_can_ko_active": False,  # can opp KO my active next turn?
        "my_active_is_ex": False,
        "my_active_prizes": 1,
    }
    try:
        my_index  = _safe_int(obs.current.yourIndex)
        opp_index = 1 - my_index
        me  = obs.current.players[my_index]
        opp = obs.current.players[opp_index]

        # Prizes
        p_self = len(me.prize or []) or _safe_int(getattr(me, "prizeCount", None), 6)
        p_opp  = len(opp.prize or []) or _safe_int(getattr(opp, "prizeCount", None), 6)
        sit["prize_left_self"] = p_self
        sit["prize_left_opp"]  = p_opp
        sit["opp_prize_delta"] = (6 - p_opp) - (6 - p_self)  # positive = opp ahead

        # Hands
        sit["self_hand_count"] = _safe_int(getattr(me,  "handCount", None), 5)
        sit["opp_hand_count"]  = _safe_int(getattr(opp, "handCount", None), 5)

        # My bench
        bench = [p for p in (me.bench or []) if p is not None]
        sit["bench_count_self"] = len(bench)

        # Board (active + bench) for energy readiness
        my_board = [p for p in (me.active or []) if p is not None] + bench
        best_idx, best_ratio = 0, -1.0
        for i, p in enumerate(my_board):
            e_attached = len(getattr(p, "energies", None) or [])
            # Estimate required energy from max-damage attack (heuristic: 2 energy avg)
            e_required = max(2, e_attached + 1) if e_attached == 0 else max(e_attached, 2)
            ratio = e_attached / e_required
            if ratio > best_ratio:
                best_ratio, best_idx = ratio, i
        sit["best_attacker_idx"] = best_idx
        sit["attacker_e_ratio"]  = min(1.0, best_ratio)

        # My active ex status
        my_active_list = me.active or []
        if my_active_list and my_active_list[0] is not None:
            active = my_active_list[0]
            cid    = _safe_int(getattr(active, "id", None))
            is_ex  = cid in ex_card_set()
            sit["my_active_is_ex"]  = is_ex
            sit["my_active_prizes"] = 2 if is_ex else 1
            # Conservative KO threat: if active HP ≤ 130 (Trevenant-level)
            cur_hp = _safe_float(getattr(active, "hp", None), 200)
            sit["opp_can_ko_active"] = cur_hp <= 130

        # Opponent prize path: pick targets whose combined prizes = prize_left_self
        opp_board = (
            [p for p in (opp.active or []) if p is not None]
            + [p for p in (opp.bench or []) if p is not None]
        )
        path_ids: set[int] = set()
        prizes_needed = p_self
        for p in sorted(opp_board, key=lambda x: _safe_float(getattr(x, "hp", None), 999)):
            if prizes_needed <= 0:
                break
            cid = _safe_int(getattr(p, "id", None))
            if cid > 0:
                path_ids.add(cid)
                prizes_needed -= (2 if cid in ex_card_set() else 1)
        sit["prize_path_ids"] = path_ids

    except Exception:
        pass
    return sit


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_card(obs, area, index, player_index):
    try:
        player = obs.current.players[player_index]
        if area == AreaType.DECK:
            return obs.select.deck[index]
        if area == AreaType.HAND:
            return player.hand[index]
        if area == AreaType.DISCARD:
            return player.discard[index]
        if area == AreaType.ACTIVE:
            return player.active[index]
        if area == AreaType.BENCH:
            return player.bench[index]
        if area == AreaType.PRIZE:
            return player.prize[index]
        if area == AreaType.STADIUM:
            return obs.current.stadium[index]
        if area == AreaType.LOOKING:
            return obs.current.looking[index]
    except Exception:
        return None
    return None


def damaged_amount(card) -> int:
    try:
        return max(0, int(card.maxHp) - int(card.hp))
    except Exception:
        return 0


def card_type_score(card, weights: dict[str, float]) -> float:
    if card is None:
        return 0.0
    meta = card_meta_table().get(getattr(card, "id", -1))
    if meta is None:
        return 0.0
    card_type, is_basic = meta
    if card_type == CardType.POKEMON:
        return weights["card_basic"] if is_basic else weights["card_pokemon"]
    if card_type == CardType.ENERGY:
        return weights["card_energy"]
    return weights["card_trainer"]


# ── Situational scoring helpers ───────────────────────────────────────────────

_CRAMORANT_ID = 311
_BOSS_ID      = 1182


def _played_card_id(obs, option, my_index: int) -> int:
    """Return card ID of a PLAY option's hand card, or 0."""
    try:
        if option.type != OptionType.PLAY:
            return 0
        hand = obs.current.players[my_index].hand or []
        idx  = _safe_int(getattr(option, "index", None), -1)
        if 0 <= idx < len(hand) and hand[idx] is not None:
            return _safe_int(getattr(hand[idx], "id", None))
    except Exception:
        pass
    return 0


def _attach_target_idx(option) -> int:
    """Board index (0=active, 1-5=bench) for an ATTACH option."""
    try:
        in_play_area  = getattr(option, "inPlayArea", None)
        in_play_index = _safe_int(getattr(option, "inPlayIndex", None))
        if in_play_area == AreaType.ACTIVE:
            return 0
        if in_play_area == AreaType.BENCH:
            return 1 + in_play_index
    except Exception:
        pass
    return 0


def _boss_target_opp_cid(obs, option, my_index: int) -> int:
    """Return the card ID of the opponent bench Pokemon targeted by Boss's Orders."""
    try:
        opp_index = 1 - my_index
        bench     = obs.current.players[opp_index].bench or []
        idx       = _safe_int(getattr(option, "index", None), -1)
        if 0 <= idx < len(bench) and bench[idx] is not None:
            return _safe_int(getattr(bench[idx], "id", None))
    except Exception:
        pass
    return 0


# ── Main scoring function ─────────────────────────────────────────────────────

def option_score(obs, option, weights: dict[str, float],
                 situation: dict[str, Any] | None = None) -> float:
    """Score one legal option.

    Combines 16 action-shape dims (original) with 12 situational dims (new).
    When situation is None, situational dims contribute 0 (neutral).
    """
    score = 0.0
    my_index = obs.current.yourIndex

    # ── Original 16 action-shape dims ────────────────────────────────────────
    if option.type == OptionType.ATTACK:
        score += weights["attack"]
    elif option.type == OptionType.ATTACH:
        score += weights["attach"]
        target = get_card(obs, option.inPlayArea, option.inPlayIndex, my_index)
        if option.inPlayArea == AreaType.ACTIVE:
            score += weights["active_bonus"]
        if option.inPlayArea == AreaType.BENCH:
            score += weights["bench_penalty"]
        score += 0.03 * damaged_amount(target)
    elif option.type == OptionType.EVOLVE:
        score += weights["evolve"]
    elif option.type == OptionType.PLAY:
        score += weights["play"]
        card = get_card(obs, AreaType.HAND, option.index, my_index)
        score += card_type_score(card, weights)
    elif option.type == OptionType.ABILITY:
        score += weights["ability"]
    elif option.type == OptionType.RETREAT:
        score += weights["retreat"]
    elif option.type == OptionType.YES:
        score += weights["yes"]
    elif option.type == OptionType.NO:
        score += weights["no"]
    elif option.type == OptionType.CARD:
        card = get_card(obs, option.area, option.index, option.playerIndex)
        score += card_type_score(card, weights)
        if option.playerIndex != my_index:
            score += weights["damage_target"]
        else:
            score += weights["own_damaged"] * min(1.0, damaged_amount(card) / 100.0)
    elif option.type == OptionType.NUMBER:
        score += float(getattr(option, "number", 0))

    # ── 12 situational dims (zero when situation is None) ────────────────────
    if situation:
        _apply_situational(obs, option, weights, situation, my_index, score_ref := [0.0])
        score += score_ref[0]

    score += random.random() * weights["random_noise"]
    return score


def _apply_situational(obs, option, weights: dict[str, float],
                       sit: dict[str, Any], my_index: int,
                       out: list[float]) -> None:
    """Compute the 12 situational bonus scores (written to out[0])."""
    bonus = 0.0

    p_self   = sit["prize_left_self"]
    p_opp    = sit["prize_left_opp"]
    p_delta  = sit["opp_prize_delta"]   # positive = opp ahead
    my_hand  = sit["self_hand_count"]
    opp_hand = sit["opp_hand_count"]
    bench_n  = sit["bench_count_self"]
    best_idx = sit["best_attacker_idx"]
    e_ratio  = sit["attacker_e_ratio"]
    path_ids = sit["prize_path_ids"]
    can_ko   = sit["opp_can_ko_active"]
    is_ex    = sit["my_active_is_ex"]

    # s1: ATTACH urgency — scales with energy deficit of best attacker
    if option.type == OptionType.ATTACH:
        tgt_idx = _attach_target_idx(option)
        if tgt_idx == best_idx:
            bonus += weights["attach_urgency"] * (1.0 - e_ratio)   # 0 when full, 1 when empty
        else:
            bonus += weights["attach_secondary"] * (1.0 - e_ratio) * 0.5

    elif option.type == OptionType.EVOLVE:
        # s2: EVOLVE → becomes main attacker (heuristic: active bench position 0)
        bonus += weights["evolve_attacker"]

    elif option.type == OptionType.PLAY:
        card_id  = _played_card_id(obs, option, my_index)
        card     = get_card(obs, AreaType.HAND, _safe_int(getattr(option, "index", None)), my_index)
        card_type = 0
        if card is not None:
            meta = card_meta_table().get(_safe_int(getattr(card, "id", None)), None)
            if meta:
                card_type = meta[0]  # 0=Pokemon, 5/6=Energy, else Trainer

        # s3: bench setup urgency
        if card_type == int(CardType.POKEMON) and bench_n < 2:
            meta2 = card_meta_table().get(_safe_int(getattr(card, "id", None)), None)
            is_basic = meta2[1] if meta2 else False
            if is_basic:
                # s10: shield bench if behind on prizes
                if p_delta > 0:
                    bonus += weights["shield_bench"]
                bonus += weights["bench_setup"]

        # s4: search for attacker when bench is thin
        if card_type not in (int(CardType.POKEMON),) and bench_n < 1:
            bonus += weights["search_attacker"]

        # s6: draw when hand is nearly empty
        if my_hand <= 3:
            bonus += weights["draw_hand_empty"]

        # s8: Boss's Orders on prize-path target
        if card_id == _BOSS_ID:
            tgt_cid = _boss_target_opp_cid(obs, option, my_index)
            if tgt_cid in path_ids:
                bonus += weights["boss_prize_path"]

    elif option.type == OptionType.ATTACK:
        # s7: attack hits a prize-path target
        opp_active = (obs.current.players[1 - my_index].active or [None])[0]
        if opp_active is not None:
            opp_cid = _safe_int(getattr(opp_active, "id", None))
            if opp_cid in path_ids:
                bonus += weights["attack_prize_path"]

        # s11: terminal sprint when at ≤2 prizes
        if p_self <= 2:
            bonus += weights["sprint_prize_2"]

        # s12: Cramorant gate (prize-conditional hard bonus/penalty)
        try:
            atk_id = _safe_int(getattr(option, "cardId", None))
            if atk_id == 0:
                # fallback: active Pokemon id
                active = (obs.current.players[my_index].active or [None])[0]
                if active:
                    atk_id = _safe_int(getattr(active, "id", None))
        except Exception:
            atk_id = 0
        if atk_id == _CRAMORANT_ID:
            if p_opp in (3, 4):
                bonus += abs(weights["cramorant_gate"])     # positive in window
            else:
                bonus -= abs(weights["cramorant_gate"]) * 5 # strong penalty outside

    elif option.type == OptionType.RETREAT:
        # s9: 錯開送奨 — retreat ex when opponent can KO it next turn
        if is_ex and can_ko:
            bonus += weights["stagger_retreat"]

    out[0] = bonus


# ── Public API ────────────────────────────────────────────────────────────────

def choose_options(obs_dict: dict[str, Any], deck: list[int],
                   weights: dict[str, float]) -> list[int]:
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return deck
    options = obs.select.option
    if not options:
        return []

    # Compute situation once for all options
    sit = compute_situation(obs)

    order = sorted(
        range(len(options)),
        key=lambda i: option_score(obs, options[i], weights, sit),
        reverse=True,
    )
    min_count = max(0, int(obs.select.minCount))
    max_count = min(len(options), int(obs.select.maxCount))
    pick = max(1, min(max_count, max(min_count, 1)))
    return order[:pick]


def make_agent(deck: list[int], weights: dict[str, float] | None = None) -> AgentFn:
    policy_weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    # Back-fill any missing situational keys so old weight files still work
    for k, v in DEFAULT_WEIGHTS.items():
        policy_weights.setdefault(k, v)

    def agent(obs_dict: dict[str, Any]) -> list[int]:
        if obs_dict.get("select") is None:
            return deck
        try:
            return choose_options(obs_dict, deck, policy_weights)
        except Exception:
            obs = to_observation_class(obs_dict)
            option_count = len(obs.select.option)
            pick = max(1, min(option_count, int(obs.select.maxCount)))
            return list(range(pick))

    return agent
