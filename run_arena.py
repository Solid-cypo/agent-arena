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


def cmd_fsm(args: argparse.Namespace) -> None:
    """Evaluate FSM agent vs policy.py baseline."""
    from arena.fsm_agent import make_fsm_agent

    random.seed(args.seed)
    deck_a = _resolve_deck(args.deck_a)
    deck_b = _resolve_deck(args.deck_b)
    fw = _load_weights(args.weights)

    fsm_agent    = make_fsm_agent(deck_a, fw)
    base_agent_b = __import__("arena.policy", fromlist=["make_agent"]).make_agent(deck_b, fw)

    wins = losses = draws = steps_total = 0
    for i in range(args.games):
        from arena.simulator import play_game
        if i % 2 == 0:
            g = play_game(fsm_agent, base_agent_b, deck_a, deck_b,
                          weights_a=fw, weights_b=fw, max_steps=args.max_steps)
            r = g.reward_for_a
        else:
            g = play_game(base_agent_b, fsm_agent, deck_b, deck_a,
                          weights_a=fw, weights_b=fw, max_steps=args.max_steps)
            r = -g.reward_for_a
        wins   += r > 0
        losses += r < 0
        draws  += r == 0
        steps_total += g.steps
        print(f"  game {i+1:3d}  {'W' if r>0 else 'L' if r<0 else 'D'}  steps={g.steps}")

    avg = round(steps_total / max(args.games, 1), 2)
    print(f"\nfsm_agent vs baseline: games={args.games} W/L/D={wins}/{losses}/{draws} "
          f"win_rate={wins/args.games:.1%} avg_steps={avg}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local cabt arena simulations.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _deck = Path("data/decks/starmie_froslass.csv")
    _opp = Path("data/decks/walrein_control.csv")

    def add_common_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--seed", type=int, default=20260618)
        sub.add_argument("--max-steps", type=int, default=700)

    play = subparsers.add_parser("play", help="Run self-play matches.")
    add_common_flags(play)
    play.add_argument("--games", type=int, default=4)
    _deck = Path("data/decks/starmie_froslass.csv")
    _opp = Path("data/decks/walrein_control.csv")
    play.add_argument("--deck-a", type=Path, default=_deck)
    play.add_argument("--deck-b", type=Path, default=_opp)
    play.add_argument("--weights-a", type=Path, default=None)
    play.add_argument("--weights-b", type=Path, default=None)
    play.add_argument("--record", action="store_true")
    play.add_argument("--out", type=Path, default=Path("data/trajectories/self_play.jsonl"))
    play.set_defaults(func=cmd_play)

    eval_cmd = subparsers.add_parser("eval", help="Evaluate weights against a baseline.")
    add_common_flags(eval_cmd)
    eval_cmd.add_argument("--games", type=int, default=20)
    eval_cmd.add_argument("--deck-a", type=Path, default=_deck)
    eval_cmd.add_argument("--deck-b", type=Path, default=_opp)
    eval_cmd.add_argument("--weights", type=Path, default=None, help="Challenger weights JSON.")
    eval_cmd.add_argument("--opponent-weights", type=Path, default=None)
    eval_cmd.add_argument("--record", action="store_true")
    eval_cmd.add_argument("--out", type=Path, default=Path("data/trajectories/eval_sample.json"))
    eval_cmd.set_defaults(func=cmd_eval)

    export_cmd = subparsers.add_parser("export", help="Export trajectory JSONL for offline training.")
    add_common_flags(export_cmd)
    export_cmd.add_argument("--games", type=int, default=10)
    export_cmd.add_argument("--deck-a", type=Path, default=_deck)
    export_cmd.add_argument("--deck-b", type=Path, default=_opp)
    export_cmd.add_argument("--weights-a", type=Path, default=None)
    export_cmd.add_argument("--weights-b", type=Path, default=None)
    export_cmd.add_argument("--out", type=Path, default=Path("data/trajectories/run.jsonl"))
    export_cmd.set_defaults(func=cmd_export)

    fsm_cmd = subparsers.add_parser("fsm", help="Evaluate FSM-Math agent vs policy.py baseline.")
    add_common_flags(fsm_cmd)
    fsm_cmd.add_argument("--games", type=int, default=10)
    fsm_cmd.add_argument("--deck-a", type=Path, default=_deck)
    fsm_cmd.add_argument("--deck-b", type=Path, default=_opp)
    fsm_cmd.add_argument("--weights", type=Path, default=None,
                         help="Shared weights for FSM baseline-ranker and opponent (default: DEFAULT_WEIGHTS).")
    fsm_cmd.set_defaults(func=cmd_fsm)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
