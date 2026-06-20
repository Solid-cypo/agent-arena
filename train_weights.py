#!/usr/bin/env python3
"""Evolution-search policy weights against the local baseline."""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from arena.deck import load_deck_csv
from arena.policy import DEFAULT_WEIGHTS
from arena.simulator import evaluate_weights

DEFAULT_META_MATCHUPS: tuple[tuple[str, str, str, float], ...] = (
    ("mirror", "deck.csv", "deck.csv", 0.5),
    (
        "vs_tea_party",
        "deck.csv",
        "data/meta_decks/decks/02_the-debauchery-tea-party.csv",
        1.0,
    ),
    (
        "vs_lucario",
        "deck.csv",
        "data/meta_decks/decks/08_stagapult.csv",
        1.0,
    ),
)


@dataclass
class MatchupSpec:
    name: str
    deck_a: list[int]
    deck_b: list[int]
    weight: float = 1.0


@dataclass
class MatchupMetrics:
    name: str
    weight: float
    reward: int
    wins: int
    losses: int
    draws: int
    avg_steps: float


@dataclass
class CandidateResult:
    generation: int
    candidate_index: int
    reward: int
    wins: int
    losses: int
    draws: int
    avg_steps: float
    weights: dict[str, float]
    matchups: list[MatchupMetrics] = field(default_factory=list)


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _resolve_deck(path: Path) -> list[int]:
    return load_deck_csv(_resolve_path(path))


def _load_weights(path: Path | None) -> dict[str, float]:
    if path is None:
        return dict(DEFAULT_WEIGHTS)
    payload = json.loads(_resolve_path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object of weight names to floats")
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in payload.items():
        weights[str(key)] = float(value)
    return weights


def _mutate_weights(
    base: dict[str, float],
    rng: random.Random,
    *,
    sigma: float,
    mutation_rate: float,
) -> dict[str, float]:
    child = dict(base)
    mutated = False
    for key, value in child.items():
        if key == "random_noise":
            continue
        if rng.random() < mutation_rate:
            child[key] = value + rng.gauss(0.0, sigma)
            mutated = True
    if not mutated:
        keys = [key for key in child if key != "random_noise"]
        picked = rng.choice(keys)
        child[picked] = child[picked] + rng.gauss(0.0, sigma)

    child["random_noise"] = max(0.0, min(0.2, child.get("random_noise", 0.0)))
    for key in ("attack", "attach", "evolve", "play", "ability", "yes", "no"):
        child[key] = max(-2.0, min(8.0, child[key]))
    for key in ("card_basic", "card_pokemon", "card_energy", "card_trainer"):
        child[key] = max(-2.0, min(4.0, child[key]))
    for key in ("damage_target", "own_damaged", "active_bonus", "bench_penalty", "retreat"):
        child[key] = max(-4.0, min(4.0, child[key]))
    return child


def _parse_matchup(raw: str) -> tuple[str, str, str, float]:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) not in (3, 4):
        raise ValueError(
            f"invalid --matchup {raw!r}; expected name:deck_a:deck_b[:weight]"
        )
    name, deck_a, deck_b = parts[:3]
    weight = float(parts[3]) if len(parts) == 4 else 1.0
    return name, deck_a, deck_b, weight


def _build_matchups(args: argparse.Namespace) -> list[MatchupSpec]:
    raw_matchups: list[tuple[str, str, str, float]] = []
    if args.meta_pool:
        raw_matchups.extend(DEFAULT_META_MATCHUPS)
    if args.matchup:
        raw_matchups.extend(_parse_matchup(item) for item in args.matchup)
    if not raw_matchups:
        raw_matchups.append(("default", str(args.deck_a), str(args.deck_b), 1.0))

    matchups: list[MatchupSpec] = []
    for name, deck_a, deck_b, weight in raw_matchups:
        matchups.append(
            MatchupSpec(
                name=name,
                deck_a=_resolve_deck(Path(deck_a)),
                deck_b=_resolve_deck(Path(deck_b)),
                weight=weight,
            )
        )
    return matchups


def _score_key(result: CandidateResult) -> tuple[float, int, int, float]:
    return (float(result.reward), result.wins, -result.losses, -result.avg_steps)


def _evaluate_candidate(
    *,
    generation: int,
    candidate_index: int,
    weights: dict[str, float],
    matchups: list[MatchupSpec],
    opponent_weights: dict[str, float],
    games: int,
    max_steps: int,
    eval_seed: int,
) -> CandidateResult:
    matchup_metrics: list[MatchupMetrics] = []
    weighted_reward = 0.0
    total_wins = 0
    total_losses = 0
    total_draws = 0
    total_steps = 0.0
    total_games = 0

    for index, matchup in enumerate(matchups):
        # Offset seed per matchup so comparisons stay fair but not identical.
        random.seed(eval_seed + index * 9973)
        metrics = evaluate_weights(
            weights,
            matchup.deck_a,
            matchup.deck_b,
            opponent_weights=opponent_weights,
            games=games,
            max_steps=max_steps,
        )
        item = MatchupMetrics(
            name=matchup.name,
            weight=matchup.weight,
            reward=int(metrics["reward"]),
            wins=int(metrics["wins"]),
            losses=int(metrics["losses"]),
            draws=int(metrics["draws"]),
            avg_steps=float(metrics["avg_steps"]),
        )
        matchup_metrics.append(item)
        weighted_reward += item.reward * matchup.weight
        total_wins += item.wins
        total_losses += item.losses
        total_draws += item.draws
        total_steps += item.avg_steps * games
        total_games += games

    return CandidateResult(
        generation=generation,
        candidate_index=candidate_index,
        reward=int(round(weighted_reward)),
        wins=total_wins,
        losses=total_losses,
        draws=total_draws,
        avg_steps=round(total_steps / total_games, 2) if total_games else 0.0,
        weights=dict(weights),
        matchups=matchup_metrics,
    )


def _print_result(prefix: str, result: CandidateResult) -> None:
    print(
        f"{prefix} gen={result.generation} cand={result.candidate_index} "
        f"reward={result.reward} W/L/D={result.wins}/{result.losses}/{result.draws} "
        f"avg_steps={result.avg_steps}"
    )
    for item in result.matchups:
        print(
            f"  {item.name}: weight={item.weight} reward={item.reward} "
            f"W/L/D={item.wins}/{item.losses}/{item.draws} avg_steps={item.avg_steps}"
        )


def run_search(args: argparse.Namespace) -> tuple[CandidateResult, list[dict[str, object]]]:
    matchups = _build_matchups(args)
    base_weights = _load_weights(args.init_weights)
    opponent_weights = _load_weights(args.opponent_weights)
    rng = random.Random(args.seed)

    print("matchups:")
    for item in matchups:
        print(f"  - {item.name}: weight={item.weight} games={args.games}")

    population: list[dict[str, float]] = [dict(base_weights)]
    for _ in range(max(0, args.population - 1)):
        population.append(
            _mutate_weights(
                base_weights,
                rng,
                sigma=args.sigma,
                mutation_rate=args.mutation_rate,
            )
        )

    history: list[dict[str, object]] = []
    global_best: CandidateResult | None = None

    for generation in range(args.generations):
        results: list[CandidateResult] = []
        for candidate_index, weights in enumerate(population):
            result = _evaluate_candidate(
                generation=generation,
                candidate_index=candidate_index,
                weights=weights,
                matchups=matchups,
                opponent_weights=opponent_weights,
                games=args.games,
                max_steps=args.max_steps,
                eval_seed=args.eval_seed,
            )
            results.append(result)

        results.sort(key=_score_key, reverse=True)
        best = results[0]
        if global_best is None or _score_key(best) > _score_key(global_best):
            global_best = best

        _print_result("best", best)
        history.append(
            {
                "generation": generation,
                "best_reward": best.reward,
                "best_wins": best.wins,
                "best_losses": best.losses,
                "best_draws": best.draws,
                "best_avg_steps": best.avg_steps,
                "best_weights": best.weights,
                "best_matchups": [asdict(item) for item in best.matchups],
            }
        )

        survivor_count = max(1, min(args.elite, len(results)))
        survivors = [dict(item.weights) for item in results[:survivor_count]]
        next_population = [dict(survivors[0])]
        while len(next_population) < args.population:
            parent = dict(rng.choice(survivors))
            next_population.append(
                _mutate_weights(
                    parent,
                    rng,
                    sigma=args.sigma,
                    mutation_rate=args.mutation_rate,
                )
            )
        population = next_population

    assert global_best is not None
    return global_best, history


def write_outputs(
    best: CandidateResult,
    history: list[dict[str, object]],
    *,
    weights_out: Path,
    history_out: Path,
) -> None:
    weights_out.parent.mkdir(parents=True, exist_ok=True)
    history_out.parent.mkdir(parents=True, exist_ok=True)
    weights_out.write_text(
        json.dumps(best.weights, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    history_out.write_text(
        json.dumps(
            {
                "best": asdict(best),
                "history": history,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search policy weights with a simple evolution loop.")
    parser.add_argument("--deck-a", type=Path, default=Path("deck.csv"))
    parser.add_argument("--deck-b", type=Path, default=Path("deck.csv"))
    parser.add_argument(
        "--meta-pool",
        action="store_true",
        help="Train against mirror + #2 Tea Party + #8 Lucario matchups.",
    )
    parser.add_argument(
        "--matchup",
        action="append",
        default=[],
        help="Custom matchup as name:deck_a:deck_b[:weight]. Repeatable.",
    )
    parser.add_argument("--init-weights", type=Path, default=None)
    parser.add_argument("--opponent-weights", type=Path, default=None)
    parser.add_argument("--games", type=int, default=20, help="Games per candidate evaluation.")
    parser.add_argument("--max-steps", type=int, default=700)
    parser.add_argument("--generations", type=int, default=8)
    parser.add_argument("--population", type=int, default=8)
    parser.add_argument("--elite", type=int, default=3)
    parser.add_argument("--sigma", type=float, default=0.35)
    parser.add_argument("--mutation-rate", type=float, default=0.45)
    parser.add_argument("--seed", type=int, default=20260620)
    parser.add_argument(
        "--eval-seed",
        type=int,
        default=4242,
        help="Fixed RNG seed reused for each candidate for fair comparison.",
    )
    parser.add_argument(
        "--weights-out",
        type=Path,
        default=Path("data/training/best_weights_meta.json"),
    )
    parser.add_argument(
        "--history-out",
        type=Path,
        default=Path("data/training/weight_search_meta_history.json"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.population < 2:
        raise ValueError("--population must be >= 2")
    if args.elite < 1:
        raise ValueError("--elite must be >= 1")
    if args.elite > args.population:
        raise ValueError("--elite must be <= --population")
    if args.generations < 1:
        raise ValueError("--generations must be >= 1")
    if args.games < 1:
        raise ValueError("--games must be >= 1")

    best, history = run_search(args)
    weights_out = _resolve_path(args.weights_out)
    history_out = _resolve_path(args.history_out)
    write_outputs(best, history, weights_out=weights_out, history_out=history_out)

    print("\nsearch complete")
    _print_result("global_best", best)
    print(f"weights -> {weights_out}")
    print(f"history -> {history_out}")


if __name__ == "__main__":
    main()
