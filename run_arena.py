#!/usr/bin/env python3
"""Local cabt arena: self-play, weight evaluation, and trajectory export."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from arena.deck import load_deck_csv
from arena.policy import DEFAULT_WEIGHTS
from arena.simulator import evaluate_weights, run_self_play_batch
from arena.trajectories import export_game_results, summarize_export


def _load_weights(path: Path | None) -> dict[str, float]:
    if path is None:
        return dict(DEFAULT_WEIGHTS)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object of weight names to floats")
    return {str(key): float(value) for key, value in payload.items()}


def _resolve_deck(path: Path) -> list[int]:
    deck_path = path if path.is_absolute() else PROJECT_ROOT / path
    return load_deck_csv(deck_path)


def cmd_play(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    deck_a = _resolve_deck(args.deck_a)
    deck_b = _resolve_deck(args.deck_b)
    weights_a = _load_weights(args.weights_a)
    weights_b = _load_weights(args.weights_b)

    results = run_self_play_batch(
        deck_a,
        deck_b,
        weights_a=weights_a,
        weights_b=weights_b,
        games=args.games,
        max_steps=args.max_steps,
        record_trajectories=args.record,
    )

    wins_a = sum(1 for game in results if game.reward_for_a > 0)
    losses_a = sum(1 for game in results if game.reward_for_a < 0)
    draws = sum(1 for game in results if game.reward_for_a == 0)
    avg_steps = round(sum(game.steps for game in results) / len(results), 2)

    print(f"self-play games={len(results)} W/L/D={wins_a}/{losses_a}/{draws} avg_steps={avg_steps}")
    if args.record and args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = PROJECT_ROOT / out_path
        export_game_results(results, out_path)
        print(f"trajectories -> {out_path}")


def cmd_eval(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    deck_a = _resolve_deck(args.deck_a)
    deck_b = _resolve_deck(args.deck_b)
    challenger = _load_weights(args.weights)
    opponent = _load_weights(args.opponent_weights)

    metrics = evaluate_weights(
        challenger,
        deck_a,
        deck_b,
        opponent_weights=opponent,
        games=args.games,
        max_steps=args.max_steps,
        record_last_trajectory=args.record,
    )
    print(json.dumps({key: value for key, value in metrics.items() if key != "trajectory"}, indent=2))
    if args.record and args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = PROJECT_ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {
                    "mode": "eval",
                    "metrics": {k: v for k, v in metrics.items() if k != "trajectory"},
                    "trajectory": metrics.get("trajectory", []),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"sample trajectory -> {out_path}")


def cmd_export(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    deck_a = _resolve_deck(args.deck_a)
    deck_b = _resolve_deck(args.deck_b)
    weights_a = _load_weights(args.weights_a)
    weights_b = _load_weights(args.weights_b)

    results = run_self_play_batch(
        deck_a,
        deck_b,
        weights_a=weights_a,
        weights_b=weights_b,
        games=args.games,
        max_steps=args.max_steps,
        record_trajectories=True,
    )

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = PROJECT_ROOT / out_path
    export_game_results(results, out_path)
    summary = summarize_export(out_path)
    print(json.dumps(summary, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local cabt arena simulations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--seed", type=int, default=20260618)
        sub.add_argument("--max-steps", type=int, default=700)

    play = subparsers.add_parser("play", help="Run self-play matches.")
    add_common_flags(play)
    play.add_argument("--games", type=int, default=4)
    play.add_argument("--deck-a", type=Path, default=Path("deck.csv"))
    play.add_argument("--deck-b", type=Path, default=Path("deck.csv"))
    play.add_argument("--weights-a", type=Path, default=None)
    play.add_argument("--weights-b", type=Path, default=None)
    play.add_argument("--record", action="store_true")
    play.add_argument("--out", type=Path, default=Path("data/trajectories/self_play.jsonl"))
    play.set_defaults(func=cmd_play)

    eval_cmd = subparsers.add_parser("eval", help="Evaluate weights against a baseline.")
    add_common_flags(eval_cmd)
    eval_cmd.add_argument("--games", type=int, default=20)
    eval_cmd.add_argument("--deck-a", type=Path, default=Path("deck.csv"))
    eval_cmd.add_argument("--deck-b", type=Path, default=Path("deck.csv"))
    eval_cmd.add_argument("--weights", type=Path, default=None, help="Challenger weights JSON.")
    eval_cmd.add_argument("--opponent-weights", type=Path, default=None)
    eval_cmd.add_argument("--record", action="store_true")
    eval_cmd.add_argument("--out", type=Path, default=Path("data/trajectories/eval_sample.json"))
    eval_cmd.set_defaults(func=cmd_eval)

    export_cmd = subparsers.add_parser("export", help="Export trajectory JSONL for offline training.")
    add_common_flags(export_cmd)
    export_cmd.add_argument("--games", type=int, default=10)
    export_cmd.add_argument("--deck-a", type=Path, default=Path("deck.csv"))
    export_cmd.add_argument("--deck-b", type=Path, default=Path("deck.csv"))
    export_cmd.add_argument("--weights-a", type=Path, default=None)
    export_cmd.add_argument("--weights-b", type=Path, default=None)
    export_cmd.add_argument("--out", type=Path, default=Path("data/trajectories/run.jsonl"))
    export_cmd.set_defaults(func=cmd_export)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
