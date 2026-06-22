import json
import os
import random

from cg.api import AreaType, CardType, OptionType, all_card_data, to_observation_class

_EX_CARDS: set[int] | None = None

def _ex_card_set() -> set[int]:
    global _EX_CARDS
    if _EX_CARDS is None:
        _EX_CARDS = {
            c.cardId for c in all_card_data()
            if getattr(c, "ex", False) or getattr(c, "megaEx", False)
        }
    return _EX_CARDS

def _safe_int(v, d=0):
    try: return int(v)
    except: return d

_CRAMORANT_ID = 311
_BOSS_ID = 1182

DEFAULT_WEIGHTS = {
    # 17 original dims
    "attack": 3.0, "attach": 2.0, "evolve": 1.7, "play": 1.2,
    "ability": 1.0, "retreat": -0.2, "yes": 0.1, "no": 0.0,
    "card_basic": 1.1, "card_pokemon": 0.6, "card_energy": 0.45,
    "card_trainer": 0.35, "damage_target": 1.5, "own_damaged": 0.75,
    "active_bonus": 0.4, "bench_penalty": -0.1, "random_noise": 0.02,
    # 12 new situational dims (init 0 = neutral; overridden by weights.json)
    "attach_urgency": 0.0, "evolve_attacker": 0.0, "bench_setup": 0.0,
    "search_attacker": 0.0, "attach_secondary": 0.0, "draw_hand_empty": 0.0,
    "attack_prize_path": 0.0, "boss_prize_path": 0.0, "stagger_retreat": 0.0,
    "shield_bench": 0.0, "sprint_prize_2": 0.0, "cramorant_gate": 0.0,
}

_CARD_META: dict[int, tuple[int, bool]] | None = None
_POLICY_WEIGHTS: dict[str, float] | None = None
_DECK: list[int] | None = None


def _agent_dir() -> str:
    if os.path.exists("deck.csv"):
        return "."
    return "/kaggle_simulations/agent"


def _load_json(name: str) -> dict:
    path = os.path.join(_agent_dir(), name)
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in payload.items():
        weights[str(key)] = float(value)
    return weights


def policy_weights() -> dict[str, float]:
    global _POLICY_WEIGHTS
    if _POLICY_WEIGHTS is None:
        weights_path = os.path.join(_agent_dir(), "weights.json")
        _POLICY_WEIGHTS = _load_json("weights.json") if os.path.exists(weights_path) else dict(DEFAULT_WEIGHTS)
    return _POLICY_WEIGHTS


def card_meta_table() -> dict[int, tuple[int, bool]]:
    global _CARD_META
    if _CARD_META is None:
        _CARD_META = {
            card.cardId: (int(card.cardType), bool(card.basic))
            for card in all_card_data()
        }
    return _CARD_META


def read_deck_csv() -> list[int]:
    global _DECK
    if _DECK is not None:
        return _DECK
    path = os.path.join(_agent_dir(), "deck.csv")
    with open(path, encoding="utf-8") as handle:
        lines = [
            line.strip() for line in handle.read().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    _DECK = [int(line) for line in lines[:60]]
    return _DECK


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


def _compute_situation(obs) -> dict:
    sit = {
        "prize_left_self": 6, "prize_left_opp": 6, "opp_prize_delta": 0,
        "self_hand_count": 5, "opp_hand_count": 5, "bench_count_self": 0,
        "best_attacker_idx": 0, "attacker_e_ratio": 0.5,
        "prize_path_ids": set(), "opp_can_ko_active": False,
        "my_active_is_ex": False,
    }
    try:
        mi = _safe_int(obs.current.yourIndex)
        oi = 1 - mi
        me = obs.current.players[mi]; opp = obs.current.players[oi]
        ps = len(me.prize or []) or _safe_int(getattr(me, "prizeCount", None), 6)
        po = len(opp.prize or []) or _safe_int(getattr(opp, "prizeCount", None), 6)
        sit["prize_left_self"] = ps; sit["prize_left_opp"] = po
        sit["opp_prize_delta"] = (6 - po) - (6 - ps)
        sit["self_hand_count"] = _safe_int(getattr(me, "handCount", None), 5)
        sit["opp_hand_count"]  = _safe_int(getattr(opp, "handCount", None), 5)
        bench = [p for p in (me.bench or []) if p is not None]
        sit["bench_count_self"] = len(bench)
        board = [p for p in (me.active or []) if p is not None] + bench
        bi, br = 0, -1.0
        for i, p in enumerate(board):
            ec = len(getattr(p, "energies", None) or [])
            r = ec / max(2, ec + 1)
            if r > br: br, bi = r, i
        sit["best_attacker_idx"] = bi; sit["attacker_e_ratio"] = min(1.0, br)
        act = (me.active or [None])[0]
        if act:
            cid = _safe_int(getattr(act, "id", None))
            sit["my_active_is_ex"] = cid in _ex_card_set()
            sit["opp_can_ko_active"] = _safe_int(getattr(act, "hp", None), 200) <= 130
        ob = [p for p in (opp.active or []) if p is not None] + [p for p in (opp.bench or []) if p is not None]
        pids: set[int] = set(); prz = ps
        for p in sorted(ob, key=lambda x: _safe_int(getattr(x, "hp", None), 999)):
            if prz <= 0: break
            cid = _safe_int(getattr(p, "id", None))
            if cid > 0: pids.add(cid); prz -= (2 if cid in _ex_card_set() else 1)
        sit["prize_path_ids"] = pids
    except Exception: pass
    return sit


def option_score(obs, option, weights: dict[str, float], sit=None) -> float:
    score = 0.0
    my_index = obs.current.yourIndex

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

    if sit:
        score += _situational(obs, option, weights, sit, my_index)

    score += random.random() * weights["random_noise"]
    return score


def _situational(obs, option, w, s, mi):
    b = 0.0
    try:
        ps = s["prize_left_self"]; po = s["prize_left_opp"]
        mh = s["self_hand_count"]; bn = s["bench_count_self"]
        bi = s["best_attacker_idx"]; er = s["attacker_e_ratio"]
        pids = s["prize_path_ids"]; ko = s["opp_can_ko_active"]; is_ex = s["my_active_is_ex"]
        pd = s["opp_prize_delta"]
        def tgt_idx():
            ia = getattr(option, "inPlayArea", None)
            ii = _safe_int(getattr(option, "inPlayIndex", None))
            return 0 if ia == AreaType.ACTIVE else 1 + ii
        def played_id():
            if option.type != OptionType.PLAY: return 0
            hand = obs.current.players[mi].hand or []
            idx = _safe_int(getattr(option, "index", None), -1)
            if 0 <= idx < len(hand) and hand[idx] is not None:
                return _safe_int(getattr(hand[idx], "id", None))
            return 0
        if option.type == OptionType.ATTACH:
            ti = tgt_idx()
            b += w.get("attach_urgency", 0) * (1 - er) if ti == bi else w.get("attach_secondary", 0) * (1 - er) * 0.5
        elif option.type == OptionType.EVOLVE:
            b += w.get("evolve_attacker", 0)
        elif option.type == OptionType.PLAY:
            cid = played_id()
            card = get_card(obs, AreaType.HAND, _safe_int(getattr(option, "index", None)), mi)
            ct = 0
            if card:
                meta = card_meta_table().get(_safe_int(getattr(card, "id", None)))
                if meta: ct = meta[0]
            if ct == int(CardType.POKEMON) and bn < 2:
                if pd > 0: b += w.get("shield_bench", 0)
                b += w.get("bench_setup", 0)
            if ct not in (int(CardType.POKEMON),) and bn < 1:
                b += w.get("search_attacker", 0)
            if mh <= 3: b += w.get("draw_hand_empty", 0)
            if cid == _BOSS_ID:
                oi = 1 - mi; bch = obs.current.players[oi].bench or []
                idx2 = _safe_int(getattr(option, "index", None), -1)
                if 0 <= idx2 < len(bch) and bch[idx2]:
                    if _safe_int(getattr(bch[idx2], "id", None)) in pids:
                        b += w.get("boss_prize_path", 0)
        elif option.type == OptionType.ATTACK:
            oa = (obs.current.players[1 - mi].active or [None])[0]
            if oa and _safe_int(getattr(oa, "id", None)) in pids:
                b += w.get("attack_prize_path", 0)
            if ps <= 2: b += w.get("sprint_prize_2", 0)
            act = (obs.current.players[mi].active or [None])[0]
            aid = _safe_int(getattr(act, "id", None)) if act else 0
            if aid == _CRAMORANT_ID:
                b += abs(w.get("cramorant_gate", 0)) if po in (3, 4) else -abs(w.get("cramorant_gate", 0)) * 5
        elif option.type == OptionType.RETREAT:
            if is_ex and ko: b += w.get("stagger_retreat", 0)
    except Exception: pass
    return b


def choose_options(obs_dict: dict, weights: dict[str, float]) -> list[int]:
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return read_deck_csv()
    options = obs.select.option
    if not options:
        return []
    sit = _compute_situation(obs)
    order = sorted(
        range(len(options)),
        key=lambda index: option_score(obs, options[index], weights, sit),
        reverse=True,
    )
    min_count = max(0, int(obs.select.minCount))
    max_count = min(len(options), int(obs.select.maxCount))
    pick = max(1, min(max_count, max(min_count, 1)))
    return order[:pick]


def agent(obs_dict: dict) -> list[int]:
    if obs_dict.get("select") is None:
        return read_deck_csv()
    weights = policy_weights()
    try:
        return choose_options(obs_dict, weights)
    except Exception:
        obs = to_observation_class(obs_dict)
        option_count = len(obs.select.option)
        pick = max(1, min(option_count, int(obs.select.maxCount)))
        return list(range(pick))
