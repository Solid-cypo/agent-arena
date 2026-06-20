#!/usr/bin/env python3
"""Download leaderboard replays and extract 60-card deck lists."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
KAGGLE_BIN = shutil.which("kaggle") or str(Path.home() / ".local/bin/kaggle")


@dataclass
class LeaderboardTeam:
    team_id: int
    team_name: str
    score: float
    submission_date: str


@dataclass
class ExtractedDeck:
    team_id: int
    team_name: str
    score: float
    submission_id: int
    episode_id: int
    deck: list[int]
    opponent_name: str | None
    opponent_deck: list[int] | None
    source_replay: str


def _run_kaggle(args: list[str]) -> str:
    command = [KAGGLE_BIN, *args]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


def _csv_rows(raw_output: str) -> list[dict[str, str]]:
    lines = []
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Next Page Token"):
            continue
        lines.append(stripped)
    if not lines:
        return []
    rows = list(csv.DictReader(lines))
    cleaned: list[dict[str, str]] = []
    for row in rows:
        first_value = next(iter(row.values()), "")
        if str(first_value).strip().isdigit():
            cleaned.append(row)
    return cleaned


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "team"


def fetch_leaderboard(competition: str, top_n: int) -> list[LeaderboardTeam]:
    output = _run_kaggle(
        [
            "competitions",
            "leaderboard",
            competition,
            "--show",
            "--page-size",
            str(top_n),
            "-v",
        ]
    )
    rows = _csv_rows(output)
    teams: list[LeaderboardTeam] = []
    for row in rows:
        teams.append(
            LeaderboardTeam(
                team_id=int(row["teamId"]),
                team_name=row["teamName"].strip(),
                score=float(row["score"]),
                submission_date=row["submissionDate"].strip(),
            )
        )
    return teams


def fetch_best_submission(team_id: int) -> int:
    output = _run_kaggle(["competitions", "team-submissions", str(team_id), "-v"])
    rows = _csv_rows(output)
    if not rows:
        raise ValueError(f"no submissions for team {team_id}")
    best = max(rows, key=lambda row: float(row["publicScore"]))
    return int(best["id"])


def fetch_latest_episode(submission_id: int) -> int:
    output = _run_kaggle(["competitions", "episodes", str(submission_id), "-v"])
    rows = _csv_rows(output)
    completed = [row for row in rows if "COMPLETED" in (row.get("state") or "")]
    if not completed:
        raise ValueError(f"no completed episodes for submission {submission_id}")
    return int(completed[0]["id"])


def download_replay(episode_id: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    _run_kaggle(["competitions", "replay", str(episode_id), "-p", str(output_dir), "-q"])
    matches = sorted(output_dir.glob(f"*{episode_id}*replay*.json"))
    if not matches:
        matches = sorted(output_dir.glob("*.json"))
    if not matches:
        raise FileNotFoundError(f"replay not found for episode {episode_id}")
    return matches[0]


def extract_decks_from_replay(replay_path: Path) -> tuple[list[str], list[list[int]]]:
    payload = json.loads(replay_path.read_text(encoding="utf-8"))
    agent_names = [agent["Name"] for agent in payload.get("info", {}).get("Agents", [])]
    if len(agent_names) < 2:
        agent_names = payload.get("info", {}).get("TeamNames", ["player_0", "player_1"])

    decks: list[list[int]] = []
    for player_index in range(2):
        deck = _find_deck_in_replay(payload, player_index)
        decks.append(deck)
    return agent_names, decks


def _find_deck_in_replay(payload: dict[str, Any], player_index: int) -> list[int]:
    for step in payload.get("steps", []):
        if player_index >= len(step):
            continue
        action = step[player_index].get("action")
        if isinstance(action, list) and len(action) == 60 and all(isinstance(card_id, int) for card_id in action):
            return list(action)
    raise ValueError(f"deck not found for player {player_index}")


def write_deck_csv(path: Path, deck: list[int]) -> None:
    path.write_text("\n".join(str(card_id) for card_id in deck) + "\n", encoding="utf-8")


def export_meta_decks(
    competition: str,
    top_n: int,
    output_dir: Path,
    *,
    keep_replays: bool = False,
) -> list[ExtractedDeck]:
    output_dir.mkdir(parents=True, exist_ok=True)
    replay_root = output_dir / "replays"
    deck_dir = output_dir / "decks"
    deck_dir.mkdir(parents=True, exist_ok=True)

    extracted: list[ExtractedDeck] = []
    leaderboard = fetch_leaderboard(competition, top_n)

    for rank, team in enumerate(leaderboard, start=1):
        print(f"[{rank}/{top_n}] {team.team_name} ({team.score})")
        try:
            submission_id = fetch_best_submission(team.team_id)
            episode_id = fetch_latest_episode(submission_id)
            replay_dir = replay_root / str(team.team_id)
            replay_path = download_replay(episode_id, replay_dir)
            agent_names, decks = extract_decks_from_replay(replay_path)

            team_player = 0
            for index, name in enumerate(agent_names):
                if name.strip() == team.team_name.strip():
                    team_player = index
                    break

            team_deck = decks[team_player]
            opponent_index = 1 - team_player
            opponent_name = agent_names[opponent_index] if opponent_index < len(agent_names) else None
            opponent_deck = decks[opponent_index] if opponent_index < len(decks) else None

            deck_path = deck_dir / f"{rank:02d}_{_slugify(team.team_name)}.csv"
            write_deck_csv(deck_path, team_deck)

            if opponent_deck is not None and opponent_name:
                write_deck_csv(deck_dir / f"{rank:02d}_{_slugify(team.team_name)}__vs__{_slugify(opponent_name)}.csv", opponent_deck)

            item = ExtractedDeck(
                team_id=team.team_id,
                team_name=team.team_name,
                score=team.score,
                submission_id=submission_id,
                episode_id=episode_id,
                deck=team_deck,
                opponent_name=opponent_name,
                opponent_deck=opponent_deck,
                source_replay=str(replay_path),
            )
            extracted.append(item)
            print(f"  -> deck saved: {deck_path.name} ({len(set(team_deck))} unique cards)")
        except Exception as exc:
            print(f"  !! failed: {exc}", file=sys.stderr)

        if not keep_replays:
            shutil.rmtree(replay_root / str(team.team_id), ignore_errors=True)

    index_path = output_dir / "index.json"
    index_payload = [
        {
            "rank": rank,
            "team_id": item.team_id,
            "team_name": item.team_name,
            "score": item.score,
            "submission_id": item.submission_id,
            "episode_id": item.episode_id,
            "deck_path": str(deck_dir / f"{rank:02d}_{_slugify(item.team_name)}.csv"),
            "deck_unique_cards": len(set(item.deck)),
            "deck_top_cards": Counter(item.deck).most_common(5),
            "opponent_name": item.opponent_name,
            "source_replay": item.source_replay,
        }
        for rank, item in enumerate(extracted, start=1)
    ]
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return extracted


def maybe_apply_deck(extracted: list[ExtractedDeck], rank: int, target: Path) -> None:
    if rank < 1 or rank > len(extracted):
        raise ValueError(f"rank {rank} out of range (1..{len(extracted)})")
    write_deck_csv(target, extracted[rank - 1].deck)
    print(f"applied rank #{rank} deck ({extracted[rank - 1].team_name}) -> {target}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export top leaderboard decks from Kaggle replays.")
    parser.add_argument("--competition", default="pokemon-tcg-ai-battle")
    parser.add_argument("--top", type=int, default=10, help="Number of leaderboard teams to export.")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "meta_decks")
    parser.add_argument("--keep-replays", action="store_true")
    parser.add_argument(
        "--apply-rank",
        type=int,
        default=None,
        help="Copy a ranked deck to deck.csv after export (1 = top team).",
    )
    parser.add_argument(
        "--apply-to",
        type=Path,
        default=PROJECT_ROOT / "deck.csv",
        help="Destination deck.csv when using --apply-rank.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_dir = args.out if args.out.is_absolute() else PROJECT_ROOT / args.out
    extracted = export_meta_decks(
        args.competition,
        args.top,
        out_dir,
        keep_replays=args.keep_replays,
    )
    print(f"\nexported {len(extracted)} decks -> {out_dir / 'decks'}")
    print(f"index -> {out_dir / 'index.json'}")
    if args.apply_rank is not None:
        target = args.apply_to if args.apply_to.is_absolute() else PROJECT_ROOT / args.apply_to
        maybe_apply_deck(extracted, args.apply_rank, target)


if __name__ == "__main__":
    main()
