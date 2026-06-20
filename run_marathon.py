#!/usr/bin/env python3
"""Start or resume long-running internal PTCG battle marathons."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from arena.marathon import (
    MarathonConfig,
    MarathonRunner,
    build_matchups,
    load_checkpoint,
    load_deck_spec,
    load_meta_decks,
    write_matrix_csv,
    write_matrix_json,
)
from arena.policy import DEFAULT_WEIGHTS


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _load_weights(path: Path | None) -> dict[str, float]:
    if path is None:
        return dict(DEFAULT_WEIGHTS)
    payload = json.loads(_resolve(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object of weight names to floats")
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in payload.items():
        weights[str(key)] = float(value)
    return weights


def _default_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"marathon_{stamp}"


def _marathon_root() -> Path:
    return _resolve(Path("data/marathon"))


def _run_dir(run_id: str) -> Path:
    return _marathon_root() / run_id


def _write_run_config(run_dir: Path, payload: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_run_config(run_dir: Path) -> dict[str, object]:
    return json.loads((run_dir / "config.json").read_text(encoding="utf-8"))


def _build_decks(args: argparse.Namespace) -> list[DeckSpec]:
    decks: list[DeckSpec] = []
    if args.meta_top:
        index_path = _resolve(args.meta_index)
        decks.extend(load_meta_decks(index_path, top_n=args.meta_top))
    if args.deck:
        for deck_path in args.deck:
            resolved = _resolve(deck_path)
            decks.append(load_deck_spec(resolved))
    if not decks:
        decks.append(load_deck_spec(_resolve(Path("deck.csv")), deck_id="deck", label="deck.csv"))
    return decks


def _make_config(args: argparse.Namespace, *, run_id: str, run_dir: Path) -> MarathonConfig:
    decks = _build_decks(args)
    matchups = build_matchups(
        decks,
        include_mirror=args.include_mirror,
        focus_deck_id=args.focus_deck,
    )
    return MarathonConfig(
        run_id=run_id,
        run_dir=run_dir,
        matchups=matchups,
        games_per_batch=args.games_per_batch,
        total_games=args.total_games,
        max_batches=args.max_batches,
        seed=args.seed,
        max_steps=args.max_steps,
        weights_a=_load_weights(args.weights_a),
        weights_b=_load_weights(args.weights_b),
        record_trajectories=args.record,
        compact_records=not args.full_records,
        checkpoint_every_batches=args.checkpoint_every,
        gc_every_batches=args.gc_every,
        sleep_seconds=args.sleep_seconds,
    )


def cmd_start(args: argparse.Namespace) -> None:
    run_id = args.run_id or _default_run_id()
    run_dir = _run_dir(run_id)
    if (run_dir / "checkpoint.json").exists() and not args.force:
        raise SystemExit(
            f"{run_dir} already exists; use `resume --run-id {run_id}` or `--force`"
        )

    config = _make_config(args, run_id=run_id, run_dir=run_dir)
    _write_run_config(
        run_dir,
        {
            "run_id": run_id,
            "matchups": [item.matchup_id for item in config.matchups],
            "games_per_batch": config.games_per_batch,
            "total_games": config.total_games,
            "max_batches": config.max_batches,
            "seed": config.seed,
            "max_steps": config.max_steps,
            "weights_a": str(args.weights_a) if args.weights_a else "DEFAULT",
            "weights_b": str(args.weights_b) if args.weights_b else "DEFAULT",
            "record_trajectories": config.record_trajectories,
        },
    )
    (_marathon_root() / "latest_run_id.txt").write_text(run_id + "\n", encoding="utf-8")
    MarathonRunner(config).run()


def cmd_resume(args: argparse.Namespace) -> None:
    run_id = args.run_id
    if run_id is None:
        latest_path = _marathon_root() / "latest_run_id.txt"
        if not latest_path.exists():
            raise SystemExit("no --run-id provided and latest_run_id.txt not found")
        run_id = latest_path.read_text(encoding="utf-8").strip()
    run_dir = _run_dir(run_id)
    if not (run_dir / "checkpoint.json").exists():
        raise SystemExit(f"checkpoint not found for run_id={run_id}")

    saved = _read_run_config(run_dir)
    config = _make_config(args, run_id=run_id, run_dir=run_dir)
    if args.total_games is None and saved.get("total_games") is not None:
        config.total_games = int(saved["total_games"])
    if args.max_batches is None and saved.get("max_batches") is not None:
        config.max_batches = int(saved["max_batches"])

    state = load_checkpoint(run_dir)
    state.stop_requested = False
    MarathonRunner(config, state=state).run()


def cmd_status(args: argparse.Namespace) -> None:
    run_id = args.run_id
    if run_id is None:
        latest_path = _marathon_root() / "latest_run_id.txt"
        if latest_path.exists():
            run_id = latest_path.read_text(encoding="utf-8").strip()
    if run_id is None:
        raise SystemExit("no marathon run found")

    run_dir = _run_dir(run_id)
    checkpoint = load_checkpoint(run_dir)
    payload = {
        "run_id": checkpoint.run_id,
        "run_dir": str(run_dir),
        "started_at": checkpoint.started_at,
        "updated_at": checkpoint.updated_at,
        "total_games_completed": checkpoint.total_games_completed,
        "total_batches_completed": checkpoint.total_batches_completed,
        "matchup_index": checkpoint.matchup_index,
        "pairs_tracked": len(checkpoint.pair_summaries),
        "stop_requested": checkpoint.stop_requested,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.show_matrix:
        write_matrix_csv(run_dir, checkpoint)
        write_matrix_json(run_dir, checkpoint, _read_run_config(run_dir))
        print(f"matrix refreshed under {run_dir}")


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=20260620)
    parser.add_argument("--max-steps", type=int, default=700)
    parser.add_argument("--games-per-batch", type=int, default=4)
    parser.add_argument(
        "--total-games",
        type=int,
        default=None,
        help="Stop after this many games. Omit for unlimited until SIGINT.",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Optional hard stop on batch count.",
    )
    parser.add_argument("--meta-top", type=int, default=None, help="Load Top N decks from meta index.")
    parser.add_argument(
        "--meta-index",
        type=Path,
        default=Path("data/meta_decks/index.json"),
    )
    parser.add_argument(
        "--deck",
        action="append",
        default=[],
        type=Path,
        help="Extra deck CSV to include. Repeatable.",
    )
    parser.add_argument(
        "--include-mirror",
        action="store_true",
        help="Include same-deck mirror matchups.",
    )
    parser.add_argument(
        "--focus-deck",
        type=str,
        default=None,
        help="Only matchups that include this deck_id (e.g. 01_trusthub-hiroingk).",
    )
    parser.add_argument("--weights-a", type=Path, default=None)
    parser.add_argument("--weights-b", type=Path, default=None)
    parser.add_argument("--record", action="store_true", help="Append per-game trajectories to results.jsonl")
    parser.add_argument(
        "--full-records",
        action="store_true",
        help="Store full deck/weight copies in results.jsonl (uses more memory/disk).",
    )
    parser.add_argument("--checkpoint-every", type=int, default=1)
    parser.add_argument(
        "--gc-every",
        type=int,
        default=1,
        help="Run gc.collect() every N batches (0 disables).",
    )
    parser.add_argument("--sleep-seconds", type=float, default=0.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run long internal PTCG battle marathons.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start a new marathon run.")
    _add_common_flags(start)
    start.add_argument("--run-id", type=str, default=None)
    start.add_argument("--force", action="store_true")
    start.set_defaults(func=cmd_start)

    resume = subparsers.add_parser("resume", help="Resume an existing marathon run.")
    _add_common_flags(resume)
    resume.add_argument("--run-id", type=str, default=None)
    resume.set_defaults(func=cmd_resume)

    status = subparsers.add_parser("status", help="Show marathon progress.")
    status.add_argument("--run-id", type=str, default=None)
    status.add_argument("--show-matrix", action="store_true")
    status.set_defaults(func=cmd_status)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command in {"start", "resume"} and args.games_per_batch < 1:
        raise SystemExit("--games-per-batch must be >= 1")
    args.func(args)


if __name__ == "__main__":
    main()
