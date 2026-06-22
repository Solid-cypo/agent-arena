"""Evolution search for starmie_froslass soft-dim weights.

Challenger = make_starmie_agent (this pilot's Layer 2 dims trainable).
Opponents  = Walrein control + meta decks using generic baseline policy.

Usage:
    python .agent/skills/piloting_starmie_froslass/scripts/train_starmie.py \
        [--generations 20] [--population 10] [--games 40] [--sigma 0.35] \
        [--init-weights data/training/best_weights_starmie_v1.json]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SKILL_SCRIPTS = Path(__file__).resolve().parent

for p in (str(PROJECT_ROOT), str(SKILL_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from arena.deck import load_deck_csv
from arena.policy import DEFAULT_WEIGHTS as GENERIC_WEIGHTS, make_agent as make_generic_agent
from arena.simulator import play_game
from starmie_pilot import DEFAULT_WEIGHTS as STARMIE_DEFAULTS, make_starmie_agent

# Soft dims that are trainable (hard-rule thresholds are fixed)
_SOFT_KEYS = ["froslass_harvest", "jetting_blow_pref", "nebula_finish", "boss_gust_path"]

MATCHUPS_DEFAULT = (
    ("mirror",      "data/decks/starmie_froslass.csv", "data/decks/starmie_froslass.csv", 0.5),
    ("vs_walrein",  "data/decks/starmie_froslass.csv", "data/decks/walrein_control.csv",  2.0),
    ("vs_alak",     "data/decks/starmie_froslass.csv", "data/meta_decks/decks/01_trusthub-hiroingk.csv", 1.2),
    ("vs_gray",     "data/decks/starmie_froslass.csv", "data/meta_decks/decks/07_graybackcat.csv", 1.0),
)


@dataclass
class MatchupResult:
    name: str
    weight: float
    wins: int
    losses: int
    draws: int

    @property
    def reward(self) -> int:
        return self.wins - self.losses


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _load_deck(path: str) -> list[int]:
    return load_deck_csv(_resolve(path))


def _eval_candidate(weights: dict[str, float],
                    matchups: list[tuple],
                    games: int) -> tuple[int, list[MatchupResult]]:
    results = []
    total_weighted = 0
    for name, path_a, path_b, w in matchups:
        deck_a = _load_deck(path_a)
        deck_b = _load_deck(path_b)
        challenger = make_starmie_agent(deck_a, weights)
        baseline   = make_generic_agent(deck_b, GENERIC_WEIGHTS)
        wins = losses = draws = 0
        for g in range(games):
            if g % 2 == 0:
                result = play_game(challenger, baseline, deck_a, deck_b)
                r = result.reward_for_a
            else:
                result = play_game(baseline, challenger, deck_b, deck_a)
                r = -result.reward_for_a
            if   r > 0: wins   += 1
            elif r < 0: losses += 1
            else:       draws  += 1
        mr = MatchupResult(name, w, wins, losses, draws)
        results.append(mr)
        total_weighted += int(mr.reward * w)
    return total_weighted, results


def _mutate(base: dict[str, float], sigma: float) -> dict[str, float]:
    w = dict(base)
    for k in _SOFT_KEYS:
        w[k] = max(0.0, w[k] + random.gauss(0, sigma))
    return w


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generations",  type=int,   default=20)
    parser.add_argument("--population",   type=int,   default=10)
    parser.add_argument("--games",        type=int,   default=40)
    parser.add_argument("--sigma",        type=float, default=0.35)
    parser.add_argument("--init-weights", type=str,   default=None)
    parser.add_argument("--weights-out",  type=str,
                        default="data/training/best_weights_starmie_v1.json")
    args = parser.parse_args()

    base = dict(STARMIE_DEFAULTS)
    if args.init_weights:
        p = _resolve(args.init_weights)
        if p.exists():
            with open(p) as f:
                base.update(json.load(f))

    matchups = list(MATCHUPS_DEFAULT)
    print("matchups:")
    for m in matchups:
        print(f"  - {m[0]}: weight={m[3]} games={args.games}")

    best_score, _ = _eval_candidate(base, matchups, args.games)
    best_weights  = dict(base)

    for gen in range(args.generations):
        gen_best_score = -999_999
        gen_best_w     = None
        gen_best_mrs   = []
        for ci in range(args.population):
            cand_w = _mutate(best_weights, args.sigma)
            score, mrs = _eval_candidate(cand_w, matchups, args.games)
            if score > gen_best_score:
                gen_best_score = score
                gen_best_w     = cand_w
                gen_best_mrs   = mrs

        if gen_best_score > best_score:
            best_score   = gen_best_score
            best_weights = gen_best_w
            out = _resolve(args.weights_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w") as f:
                json.dump({k: best_weights[k] for k in _SOFT_KEYS}, f, indent=2)

        total_w = sum(mr.wins + mr.losses + mr.draws for mr in gen_best_mrs)
        total_wins = sum(mr.wins for mr in gen_best_mrs)
        print(f"best gen={gen} reward={gen_best_score} "
              f"W/L/D={total_wins}/"
              f"{sum(mr.losses for mr in gen_best_mrs)}/"
              f"{sum(mr.draws for mr in gen_best_mrs)} "
              f"avg_wr={total_wins/max(1,total_w):.2%}")
        for mr in gen_best_mrs:
            print(f"  {mr.name}: weight={mr.weight} reward={mr.reward} "
                  f"W/L/D={mr.wins}/{mr.losses}/{mr.draws}")


if __name__ == "__main__":
    main()
