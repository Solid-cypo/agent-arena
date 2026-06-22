"""Kaggle agent entry-point for the Starmie + Froslass dual-Mega deck.

Loads deck.csv + weights.json from the agent directory, then routes every
observation through the two-layer starmie_pilot logic.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path
from typing import Any

from cg.api import (AreaType, EnergyType, OptionType,
                    all_card_data, to_observation_class)

# ── Card catalogue ─────────────────────────────────────────────────────────────
_CARDS = {
    "mega_starmie_ex": 1031, "mega_froslass_ex": 861,
    "staryu": 1030, "snorunt": 860, "froslass": 104,
    "munkidori": 112, "fan_rotom": 174, "budew": 235,
    "dunsparce_a": 65, "dunsparce_b": 305,
    "dudunsparce": 66, "dudunsparce_ex": 306, "meowth_ex": 1071,
    "boss_orders": 1182, "hilda": 1225, "ignition_energy": 17,
    "risky_ruins": 1260,
}
_MEGA_EX_IDS   = {_CARDS["mega_starmie_ex"], _CARDS["mega_froslass_ex"]}
_MUNKIDORI_ID  = _CARDS["munkidori"]
_FAN_ROTOM_ID  = _CARDS["fan_rotom"]
_BUDEW_ID      = _CARDS["budew"]
_BOSS_ID       = _CARDS["boss_orders"]

# Attack IDs
_ATK_JETTING_BLOW = 1487
_ATK_NEBULA_BEAM  = 1488
_ATK_RESENTFUL    = 1240
_ATK_ITCHY_POLLEN = 323

_DOMINATE = 1_000.0

DEFAULT_WEIGHTS: dict[str, float] = {
    "froslass_harvest": 1.5, "jetting_blow_pref": 1.2,
    "nebula_finish": 2.0,    "boss_gust_path": 1.8,
    "attack": 3.0, "attach": 2.0, "evolve": 1.7, "play": 1.2,
    "ability": 1.0, "retreat": -0.2, "yes": 0.1, "no": 0.0,
    "card_basic": 1.1, "card_pokemon": 0.6, "card_energy": 0.45,
    "card_trainer": 0.35, "damage_target": 1.5, "own_damaged": 0.75,
    "active_bonus": 0.4, "bench_penalty": -0.1, "random_noise": 0.02,
}

# ── Globals ────────────────────────────────────────────────────────────────────
_POLICY_WEIGHTS: dict[str, float] | None = None
_DECK: list[int] | None = None
_EX_SET: set[int] | None = None
_CARD_META: dict | None = None


def _agent_dir() -> str:
    return "." if os.path.exists("deck.csv") else "/kaggle_simulations/agent"


def _ex_card_set() -> set[int]:
    global _EX_SET
    if _EX_SET is None:
        _EX_SET = {c.cardId for c in all_card_data()
                   if getattr(c, "ex", False) or getattr(c, "megaEx", False)}
    return _EX_SET


def _card_meta() -> dict:
    global _CARD_META
    if _CARD_META is None:
        _CARD_META = {c.cardId: (int(c.cardType), bool(c.basic)) for c in all_card_data()}
    return _CARD_META


def policy_weights() -> dict[str, float]:
    global _POLICY_WEIGHTS
    if _POLICY_WEIGHTS is None:
        path = os.path.join(_agent_dir(), "weights.json")
        w = dict(DEFAULT_WEIGHTS)
        if os.path.exists(path):
            with open(path) as f:
                for k, v in json.load(f).items():
                    w[str(k)] = float(v)
        _POLICY_WEIGHTS = w
    return _POLICY_WEIGHTS


def read_deck() -> list[int]:
    global _DECK
    if _DECK is not None:
        return _DECK
    path = os.path.join(_agent_dir(), "deck.csv")
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    _DECK = [int(l) for l in lines[:60]]
    return _DECK


# ── Observation helpers ────────────────────────────────────────────────────────

def _si(v, d=0):
    try: return int(v)
    except: return d


def _pkm(obs, area, idx, pi):
    try:
        p = obs.current.players[pi]
        if area == AreaType.ACTIVE: return (p.active or [])[idx]
        if area == AreaType.BENCH:  return (p.bench  or [])[idx]
    except Exception: pass
    return None


def _has_dark(pkm) -> bool:
    try:
        return any(_si(e) == int(EnergyType.DARKNESS) for e in (pkm.energies or []))
    except Exception: return False


def _compute_sit(obs) -> dict:
    sit = {"turn": 0, "mi": 0, "prize_self": 6, "prize_opp": 6,
           "opp_hand": 5, "opp_just_prized": False,
           "bench_n": 0, "mega_ready": False, "prize_ids": set()}
    try:
        mi = _si(obs.current.yourIndex); oi = 1 - mi
        me = obs.current.players[mi]; opp = obs.current.players[oi]
        sit["mi"] = mi
        sit["turn"] = _si(obs.current.turn)
        ps = len(me.prize or []) or _si(getattr(me, "prizeCount", None), 6)
        po = len(opp.prize or []) or _si(getattr(opp, "prizeCount", None), 6)
        sit["prize_self"] = ps; sit["prize_opp"] = po
        oh = _si(getattr(opp, "handCount", None), 5)
        sit["opp_hand"] = oh
        sit["bench_n"]  = len([p for p in (me.bench or []) if p])
        # Mega attacker ready?
        act = (me.active or [None])[0]
        sit["mega_ready"] = bool(act and _si(getattr(act, "id", None)) in _MEGA_EX_IDS)
        # Opponent just took a prize heuristic
        sit["opp_just_prized"] = ((6 - po) > 0 and oh >= 5)
        # Prize path
        opp_board = ([p for p in (opp.active or []) if p]
                     + [p for p in (opp.bench or []) if p])
        pids: set[int] = set(); need = ps
        for p in sorted(opp_board, key=lambda x: _si(getattr(x, "hp", None), 999)):
            if need <= 0: break
            cid = _si(getattr(p, "id", None))
            if cid > 0:
                pids.add(cid)
                need -= (2 if cid in _ex_card_set() else 1)
        sit["prize_ids"] = pids
    except Exception: pass
    return sit


def _hand_cid(obs, option, mi) -> int:
    try:
        if option.type != OptionType.PLAY: return 0
        hand = obs.current.players[mi].hand or []
        idx  = _si(getattr(option, "index", None), -1)
        if 0 <= idx < len(hand) and hand[idx]:
            return _si(getattr(hand[idx], "id", None))
    except Exception: pass
    return 0


def _ability_src(obs, option, mi) -> int:
    try:
        if option.type != OptionType.ABILITY: return 0
        p = _pkm(obs, option.area, _si(option.index), mi)
        return _si(getattr(p, "id", None)) if p else 0
    except Exception: return 0


# ── Layer 1: hard rules ────────────────────────────────────────────────────────

def _hard(obs, option, sit) -> float:
    mi = sit["mi"]; turn = sit["turn"]

    if option.type == OptionType.ABILITY:
        src = _ability_src(obs, option, mi)
        # Fan Call: first turn only
        if src == _FAN_ROTOM_ID and turn <= 2:
            return _DOMINATE
        # Adrena-Brain: Munkidori with Darkness energy
        if src == _MUNKIDORI_ID:
            p = _pkm(obs, option.area, _si(option.index, -1), mi)
            if p and _has_dark(p):
                return _DOMINATE

    # Budew Itchy Pollen: fallback stall when no Mega ready turn 3+
    if (option.type == OptionType.ATTACK and turn >= 3
            and not sit["mega_ready"]
            and _si(getattr(option, "attackId", None)) == _ATK_ITCHY_POLLEN):
        return _DOMINATE * 0.5

    return 0.0


# ── Layer 2: soft nudges ───────────────────────────────────────────────────────

def _soft(obs, option, w, sit) -> float:
    mi = sit["mi"]; pids = sit["prize_ids"]
    b = 0.0

    if option.type == OptionType.EVOLVE:
        try:
            area = option.area; idx = _si(getattr(option, "index", None), -1)
            hand = obs.current.players[mi].hand or []
            card = hand[idx] if area == AreaType.HAND and 0 <= idx < len(hand) else None
            if card and _si(getattr(card, "id", None)) == _CARDS["mega_froslass_ex"]:
                if sit["opp_hand"] >= 5 or sit["opp_just_prized"]:
                    b += w.get("froslass_harvest", 1.5)
        except Exception: pass

    elif option.type == OptionType.ATTACK:
        atk = _si(getattr(option, "attackId", None))
        if atk == _ATK_JETTING_BLOW:
            b += w.get("jetting_blow_pref", 1.2)
        if atk == _ATK_NEBULA_BEAM:
            try:
                oa = (obs.current.players[1 - mi].active or [None])[0]
                if oa and _si(getattr(oa, "id", None)) in pids and _si(getattr(oa, "hp", None), 9999) <= 220:
                    b += w.get("nebula_finish", 2.0)
            except Exception: pass
        if atk == _ATK_RESENTFUL and sit["opp_hand"] * 50 >= 200:
            b += 1.0

    elif option.type == OptionType.PLAY:
        if _hand_cid(obs, option, mi) == _BOSS_ID:
            try:
                oi = 1 - mi; bch = obs.current.players[oi].bench or []
                bidx = _si(getattr(option, "index", None), -1)
                if 0 <= bidx < len(bch) and bch[bidx]:
                    if _si(getattr(bch[bidx], "id", None)) in pids:
                        b += w.get("boss_gust_path", 1.8)
            except Exception: pass

    return b


# ── Baseline scorer ────────────────────────────────────────────────────────────

def _baseline(obs, option, w) -> float:
    from cg.api import CardType
    score = 0.0; mi = obs.current.yourIndex

    def _card(area, idx, pi):
        try:
            p = obs.current.players[pi]
            if area == AreaType.HAND:    return (p.hand or [])[idx]
            if area == AreaType.BENCH:   return (p.bench or [])[idx]
            if area == AreaType.ACTIVE:  return (p.active or [])[idx]
            if area == AreaType.DISCARD: return (p.discard or [])[idx]
            if area == AreaType.PRIZE:   return (p.prize or [])[idx]
        except Exception: pass
        return None

    def _ct(card):
        if not card: return 0.0
        meta = _card_meta().get(_si(getattr(card, "id", None), -1))
        if not meta: return 0.0
        ct, is_basic = meta
        if ct == int(CardType.POKEMON):
            return w.get("card_basic", 1.1) if is_basic else w.get("card_pokemon", 0.6)
        if ct == int(CardType.ENERGY): return w.get("card_energy", 0.45)
        return w.get("card_trainer", 0.35)

    t = option.type
    if   t == OptionType.ATTACK:  score += w.get("attack", 3.0)
    elif t == OptionType.ATTACH:
        score += w.get("attach", 2.0)
        if option.inPlayArea == AreaType.ACTIVE: score += w.get("active_bonus", 0.4)
        if option.inPlayArea == AreaType.BENCH:  score += w.get("bench_penalty", -0.1)
    elif t == OptionType.EVOLVE:  score += w.get("evolve", 1.7)
    elif t == OptionType.PLAY:
        score += w.get("play", 1.2)
        score += _ct(_card(AreaType.HAND, _si(getattr(option,"index",None)), mi))
    elif t == OptionType.ABILITY: score += w.get("ability", 1.0)
    elif t == OptionType.RETREAT: score += w.get("retreat", -0.2)
    elif t == OptionType.YES:     score += w.get("yes", 0.1)
    elif t == OptionType.NO:      score += w.get("no", 0.0)
    elif t == OptionType.CARD:
        score += _ct(_card(option.area, _si(getattr(option,"index",None)),
                           _si(getattr(option,"playerIndex",None), mi)))
        if _si(getattr(option, "playerIndex", None), mi) != mi:
            score += w.get("damage_target", 1.5)
    elif t == OptionType.NUMBER:  score += float(getattr(option, "number", 0))

    score += random.random() * w.get("random_noise", 0.02)
    return score


# ── Main chooser ───────────────────────────────────────────────────────────────

def choose_options(obs_dict: dict) -> list[int]:
    obs  = to_observation_class(obs_dict)
    if obs.select is None: return read_deck()
    opts = obs.select.option
    if not opts: return []
    w   = policy_weights()
    sit = _compute_sit(obs)

    def score(i):
        h = _hard(obs, opts[i], sit)
        if h: return h
        return _baseline(obs, opts[i], w) + _soft(obs, opts[i], w, sit)

    order = sorted(range(len(opts)), key=score, reverse=True)
    mn = max(0, int(obs.select.minCount))
    mx = min(len(opts), int(obs.select.maxCount))
    return order[:max(1, min(mx, max(mn, 1)))]


def agent(obs_dict: dict) -> list[int]:
    if obs_dict.get("select") is None:
        return read_deck()
    try:
        return choose_options(obs_dict)
    except Exception:
        try:
            obs  = to_observation_class(obs_dict)
            pick = max(1, min(len(obs.select.option), int(obs.select.maxCount)))
            return list(range(pick))
        except Exception:
            return [0]
