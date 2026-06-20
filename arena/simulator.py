"""Local self-play simulator using cg.game bindings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cg.game import battle_finish, battle_select, battle_start

from arena.policy import AgentFn, DEFAULT_WEIGHTS, make_agent


@dataclass
class GameResult:
    reward_for_a: int
    steps: int
    winner: int | None
    deck_a: list[int]
    deck_b: list[int]
    weights_a: dict[str, float]
    weights_b: dict[str, float]
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False


def _winner_from_result(result: int, perspective: int) -> int | None:
    if result < 0:
        return None
    if result == perspective:
        return perspective
    if result in (0, 1):
        return 1 - perspective
    return None


def _compact_step(obs: dict[str, Any], player_index: int, action: list[int]) -> dict[str, Any]:
    current = obs.get("current") or {}
    select = obs.get("select") or {}
    options = select.get("option") or []
    option_types = [option.get("type") for option in options]
    return {
        "player": player_index,
        "action": action,
        "turn": current.get("turn"),
        "turn_action_count": current.get("turnActionCount"),
        "your_index": current.get("yourIndex"),
        "select_type": select.get("type"),
        "select_context": select.get("context"),
        "option_count": len(options),
        "option_types": option_types,
        "min_count": select.get("minCount"),
        "max_count": select.get("maxCount"),
    }


def play_game(
    agent_a: AgentFn,
    agent_b: AgentFn,
    deck_a: list[int],
    deck_b: list[int],
    *,
    weights_a: dict[str, float] | None = None,
    weights_b: dict[str, float] | None = None,
    max_steps: int = 700,
    record_trajectory: bool = False,
) -> GameResult:
    """Play one game. Return +1 if agent_a wins, -1 if agent_a loses, 0 otherwise."""
    resolved_weights_a = dict(DEFAULT_WEIGHTS if weights_a is None else weights_a)
    resolved_weights_b = dict(DEFAULT_WEIGHTS if weights_b is None else weights_b)
    trajectory: list[dict[str, Any]] = []

    obs, start_data = battle_start(deck_a, deck_b)
    if getattr(start_data, "errorPlayer", -1) >= 0:
        raise ValueError(
            f"deck error: player={start_data.errorPlayer}, type={start_data.errorType}"
        )

    steps = 0
    truncated = False
    result = -1
    try:
        while obs["current"]["result"] < 0 and steps < max_steps:
            player_index = obs["current"]["yourIndex"]
            selected = agent_a(obs) if player_index == 0 else agent_b(obs)
            if record_trajectory:
                trajectory.append(_compact_step(obs, player_index, selected))
            obs = battle_select(selected)
            steps += 1
        result = obs["current"]["result"]
        truncated = result < 0
    finally:
        battle_finish()

    if result == 0:
        reward = 1
    elif result == 1:
        reward = -1
    else:
        reward = 0

    return GameResult(
        reward_for_a=reward,
        steps=steps,
        winner=_winner_from_result(result, 0) if result >= 0 else None,
        deck_a=list(deck_a),
        deck_b=list(deck_b),
        weights_a=resolved_weights_a,
        weights_b=resolved_weights_b,
        trajectory=trajectory,
        truncated=truncated,
    )


def evaluate_weights(
    challenger_weights: dict[str, float],
    deck_a: list[int],
    deck_b: list[int],
    *,
    opponent_weights: dict[str, float] | None = None,
    games: int = 4,
    max_steps: int = 700,
    record_last_trajectory: bool = False,
) -> dict[str, Any]:
    """Evaluate challenger policy against a baseline policy."""
    baseline_weights = dict(DEFAULT_WEIGHTS if opponent_weights is None else opponent_weights)
    challenger_agent = make_agent(deck_a, challenger_weights)
    baseline_agent = make_agent(deck_b, baseline_weights)

    rewards: list[int] = []
    trajectories: list[list[dict[str, Any]]] = []
    total_steps = 0

    for game_idx in range(games):
        record = record_last_trajectory and game_idx == games - 1
        if game_idx % 2 == 0:
            game = play_game(
                challenger_agent,
                baseline_agent,
                deck_a,
                deck_b,
                weights_a=challenger_weights,
                weights_b=baseline_weights,
                max_steps=max_steps,
                record_trajectory=record,
            )
            rewards.append(game.reward_for_a)
        else:
            game = play_game(
                baseline_agent,
                challenger_agent,
                deck_b,
                deck_a,
                weights_a=baseline_weights,
                weights_b=challenger_weights,
                max_steps=max_steps,
                record_trajectory=record,
            )
            rewards.append(-game.reward_for_a)
        total_steps += game.steps
        if record:
            trajectories.append(game.trajectory)

    wins = sum(1 for reward in rewards if reward > 0)
    losses = sum(1 for reward in rewards if reward < 0)
    draws = sum(1 for reward in rewards if reward == 0)
    return {
        "games": games,
        "reward": sum(rewards),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "avg_steps": round(total_steps / games, 2),
        "challenger_weights": challenger_weights,
        "opponent_weights": baseline_weights,
        "trajectory": trajectories[0] if trajectories else [],
    }


def run_self_play_batch(
    deck_a: list[int],
    deck_b: list[int],
    *,
    weights_a: dict[str, float] | None = None,
    weights_b: dict[str, float] | None = None,
    games: int = 1,
    max_steps: int = 700,
    record_trajectories: bool = False,
) -> list[GameResult]:
    agent_a = make_agent(deck_a, weights_a)
    agent_b = make_agent(deck_b, weights_b)
    resolved_weights_a = dict(DEFAULT_WEIGHTS if weights_a is None else weights_a)
    resolved_weights_b = dict(DEFAULT_WEIGHTS if weights_b is None else weights_b)

    results: list[GameResult] = []
    for game_idx in range(games):
        swap = game_idx % 2 == 1
        if swap:
            game = play_game(
                agent_b,
                agent_a,
                deck_b,
                deck_a,
                weights_a=resolved_weights_b,
                weights_b=resolved_weights_a,
                max_steps=max_steps,
                record_trajectory=record_trajectories,
            )
            game.reward_for_a = -game.reward_for_a
            if game.winner is not None:
                game.winner = 1 - game.winner
            game.weights_a, game.weights_b = game.weights_b, game.weights_a
            game.deck_a, game.deck_b = game.deck_b, game.deck_a
        else:
            game = play_game(
                agent_a,
                agent_b,
                deck_a,
                deck_b,
                weights_a=resolved_weights_a,
                weights_b=resolved_weights_b,
                max_steps=max_steps,
                record_trajectory=record_trajectories,
            )
        results.append(game)
    return results
