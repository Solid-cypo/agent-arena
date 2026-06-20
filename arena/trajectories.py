"""Trajectory export skeleton for offline training on rented compute."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from arena.simulator import GameResult


def game_to_record(game: GameResult, *, game_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "game_id": game_id or uuid4().hex,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "deck_a": game.deck_a,
        "deck_b": game.deck_b,
        "weights_a": game.weights_a,
        "weights_b": game.weights_b,
        "winner": game.winner,
        "reward_for_a": game.reward_for_a,
        "steps": game.steps,
        "truncated": game.truncated,
        "steps_data": game.trajectory,
    }


def write_jsonl(records: Iterable[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def export_game_results(results: list[GameResult], output_path: Path) -> Path:
    records = [game_to_record(result) for result in results]
    write_jsonl(records, output_path)
    return output_path


def summarize_export(path: Path) -> dict[str, Any]:
    wins_a = 0
    total_steps = 0
    games = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            games += 1
            total_steps += int(payload.get("steps", 0))
            if payload.get("reward_for_a", 0) > 0:
                wins_a += 1
    return {
        "games": games,
        "wins_a": wins_a,
        "avg_steps": round(total_steps / games, 2) if games else 0.0,
        "path": str(path),
    }
