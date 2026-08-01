"""Local self-play simulator using cg.game bindings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
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
    # Engine Log events collected after each battle_select (and initial start).
    # Empty unless collect_engine_logs=True. Each entry is a plain dict.
    engine_logs: list[dict[str, Any]] = field(default_factory=list)


def _log_to_dict(log: Any) -> dict[str, Any]:
    """Normalize a cg.api.Log (dataclass or dict) to a plain dict."""
    if isinstance(log, dict):
        out = dict(log)
    elif is_dataclass(log) and not isinstance(log, type):
        out = asdict(log)
    else:
        out = {
            k: getattr(log, k, None)
            for k in (
                "type", "playerIndex", "hasBasicPokemon", "cardId", "serial",
                "fromArea", "toArea", "cardIdActive", "serialActive",
                "cardIdBench", "serialBench", "cardIdBefore", "serialBefore",
                "cardIdAfter", "serialAfter", "cardIdTarget", "serialTarget",
                "attackId", "value", "putDamageCounter", "isRecover", "head",
                "result", "reason",
            )
        }
    # Enums → ints for JSON / renderer stability.
    for k, v in list(out.items()):
        if hasattr(v, "value") and not isinstance(v, (bool, int, float, str)):
            try:
                out[k] = int(v)
            except Exception:
                out[k] = getattr(v, "value", v)
        elif v is not None and type(v).__name__ in ("AreaType", "LogType"):
            try:
                out[k] = int(v)
            except Exception:
                pass
    if "type" in out and out["type"] is not None:
        try:
            out["type"] = int(out["type"])
        except Exception:
            pass
    return out


def _snapshot_from_obs(obs: Any, player_index: int) -> dict[str, Any]:
    """Board snapshot for NL turn headers (our-side hand only when pi==0)."""
    if isinstance(obs, dict):
        cur = obs.get("current") or {}
    else:
        cur = getattr(obs, "current", None) or {}
        if not isinstance(cur, dict):
            cur = asdict(cur) if is_dataclass(cur) and not isinstance(cur, type) else {}
    players = cur.get("players") or [{}, {}]
    me = players[player_index] if player_index < len(players) else {}
    opp = players[1 - player_index] if len(players) > 1 - player_index else {}

    def _ids(cards):
        out = []
        for c in cards or []:
            if not c:
                continue
            if isinstance(c, dict):
                out.append(int(c.get("id") or 0))
            else:
                out.append(int(getattr(c, "id", 0) or 0))
        return out

    def _poke(zone):
        rows = []
        for p in zone or []:
            if not p:
                continue
            if isinstance(p, dict):
                rows.append({
                    "id": int(p.get("id") or 0),
                    "hp": int(p.get("hp") or 0),
                    "energies": [int(e) for e in (p.get("energies") or [])],
                })
            else:
                rows.append({
                    "id": int(getattr(p, "id", 0) or 0),
                    "hp": int(getattr(p, "hp", 0) or 0),
                    "energies": [int(e) for e in (getattr(p, "energies", None) or [])],
                })
        return rows

    return {
        "type": "SNAPSHOT",  # synthetic; not a LogType
        "playerIndex": player_index,
        "turn": cur.get("turn"),
        "hand": _ids(me.get("hand") if isinstance(me, dict) else getattr(me, "hand", None)),
        "active": _poke(me.get("active") if isinstance(me, dict) else getattr(me, "active", None)),
        "bench": _poke(me.get("bench") if isinstance(me, dict) else getattr(me, "bench", None)),
        "prize_self": len(me.get("prize") or []) if isinstance(me, dict) else len(getattr(me, "prize", None) or []),
        "prize_opp": len(opp.get("prize") or []) if isinstance(opp, dict) else len(getattr(opp, "prize", None) or []),
    }


def _extend_engine_logs(bucket: list[dict[str, Any]], obs: Any) -> None:
    if isinstance(obs, dict):
        logs = obs.get("logs") or []
        cur = obs.get("current") or {}
    else:
        logs = getattr(obs, "logs", None) or []
        cur = getattr(obs, "current", None) or {}
    for lg in logs:
        d = _log_to_dict(lg)
        bucket.append(d)
        # After TURN_START, attach a board snapshot for the acting player.
        if d.get("type") == 2:  # LogType.TURN_START
            pi = d.get("playerIndex")
            if pi is None and isinstance(cur, dict):
                pi = cur.get("yourIndex")
            if pi is not None:
                bucket.append(_snapshot_from_obs(obs, int(pi)))


def _winner_from_result(result: int, perspective: int) -> int | None:
    if result < 0:
        return None
    if result == perspective:
        return perspective
    if result in (0, 1):
        return 1 - perspective
    return None


def _compact_step(
    obs: dict[str, Any],
    player_index: int,
    action: list[int],
    *,
    slim: bool = False,
) -> dict[str, Any]:
    current = obs.get("current") or {}
    select = obs.get("select") or {}
    if slim:
        return {
            "player": player_index,
            "action": action,
            "turn": current.get("turn"),
            "select_type": select.get("type"),
        }
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
    store_metadata: bool = True,
    slim_trajectory: bool = False,
    collect_engine_logs: bool = False,
) -> GameResult:
    """Play one game. Return +1 if agent_a wins, -1 if agent_a loses, 0 otherwise.

    When collect_engine_logs=True, append every engine Log event from
    battle_start and each battle_select into GameResult.engine_logs (for
    NL review rendering). Default off so eval paths stay light.
    """
    resolved_weights_a = dict(DEFAULT_WEIGHTS if weights_a is None else weights_a)
    resolved_weights_b = dict(DEFAULT_WEIGHTS if weights_b is None else weights_b)
    keep_metadata = store_metadata or record_trajectory or collect_engine_logs
    trajectory: list[dict[str, Any]] = []
    engine_logs: list[dict[str, Any]] = []

    obs, start_data = battle_start(deck_a, deck_b)
    if getattr(start_data, "errorPlayer", -1) >= 0:
        raise ValueError(
            f"deck error: player={start_data.errorPlayer}, type={start_data.errorType}"
        )
    if collect_engine_logs:
        _extend_engine_logs(engine_logs, obs)

    steps = 0
    truncated = False
    result = -1
    try:
        while obs["current"]["result"] < 0 and steps < max_steps:
            player_index = obs["current"]["yourIndex"]
            selected = agent_a(obs) if player_index == 0 else agent_b(obs)
            if record_trajectory:
                trajectory.append(
                    _compact_step(obs, player_index, selected, slim=slim_trajectory)
                )
            obs = battle_select(selected)
            if collect_engine_logs:
                _extend_engine_logs(engine_logs, obs)
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
        deck_a=list(deck_a) if keep_metadata else [],
        deck_b=list(deck_b) if keep_metadata else [],
        weights_a=resolved_weights_a if keep_metadata else {},
        weights_b=resolved_weights_b if keep_metadata else {},
        trajectory=trajectory,
        truncated=truncated,
        engine_logs=engine_logs,
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
    store_metadata: bool | None = None,
    agent_a: AgentFn | None = None,
    agent_b: AgentFn | None = None,
    slim_trajectory: bool = False,
) -> list[GameResult]:
    if agent_a is None:
        agent_a = make_agent(deck_a, weights_a)
    if agent_b is None:
        agent_b = make_agent(deck_b, weights_b)
    resolved_store_metadata = record_trajectories if store_metadata is None else store_metadata
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
                store_metadata=resolved_store_metadata,
                slim_trajectory=slim_trajectory,
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
                store_metadata=resolved_store_metadata,
                slim_trajectory=slim_trajectory,
            )
        results.append(game)
    return results
