import json
import os
import random

from cg.api import AreaType, CardType, OptionType, all_card_data, to_observation_class

DEFAULT_WEIGHTS = {
    "attack": 3.0,
    "attach": 2.0,
    "evolve": 1.7,
    "play": 1.2,
    "ability": 1.0,
    "retreat": -0.2,
    "yes": 0.1,
    "no": 0.0,
    "card_basic": 1.1,
    "card_pokemon": 0.6,
    "card_energy": 0.45,
    "card_trainer": 0.35,
    "damage_target": 1.5,
    "own_damaged": 0.75,
    "active_bonus": 0.4,
    "bench_penalty": -0.1,
    "random_noise": 0.02,
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
        lines = [line.strip() for line in handle.read().splitlines() if line.strip()]
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


def option_score(obs, option, weights: dict[str, float]) -> float:
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

    score += random.random() * weights["random_noise"]
    return score


def choose_options(obs_dict: dict, weights: dict[str, float]) -> list[int]:
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return read_deck_csv()
    options = obs.select.option
    if not options:
        return []
    order = sorted(
        range(len(options)),
        key=lambda index: option_score(obs, options[index], weights),
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
