"""Long-running internal battle runner with checkpointing."""

from __future__ import annotations

import csv
import gc
import json
import random
import signal
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arena.deck import load_deck_csv
from arena.policy import DEFAULT_WEIGHTS, AgentFn, card_meta_table, make_agent
from arena.simulator import GameResult, run_self_play_batch
from arena.trajectories import append_jsonl_line, game_to_record


@dataclass
class DeckSpec:
    deck_id: str
    label: str
    path: Path
    cards: list[int]


@dataclass
class MatchupSpec:
    deck_a: DeckSpec
    deck_b: DeckSpec

    @property
    def matchup_id(self) -> str:
        return f"{self.deck_a.deck_id}__vs__{self.deck_b.deck_id}"


@dataclass
class PairSummary:
    deck_a_id: str
    deck_a_label: str
    deck_b_id: str
    deck_b_label: str
    games: int = 0
    wins_a: int = 0
    losses_a: int = 0
    draws: int = 0
    total_steps: int = 0

    @property
    def win_rate_a(self) -> float:
        return round(self.wins_a / self.games, 4) if self.games else 0.0

    @property
    def avg_steps(self) -> float:
        return round(self.total_steps / self.games, 2) if self.games else 0.0


@dataclass
class MarathonState:
    run_id: str
    started_at: str
    updated_at: str
    total_games_completed: int = 0
    total_batches_completed: int = 0
    matchup_index: int = 0
    seed_cursor: int = 0
    stop_requested: bool = False
    pair_summaries: dict[str, PairSummary] = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_from_path(path: Path) -> str:
    stem = path.stem.replace("__vs__", "_vs_")
    return stem


def load_meta_decks(index_path: Path, *, top_n: int | None = None) -> list[DeckSpec]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if top_n is not None:
        payload = payload[:top_n]
    decks: list[DeckSpec] = []
    for item in payload:
        deck_path = Path(item["deck_path"])
        deck_id = _slug_from_path(deck_path)
        decks.append(
            DeckSpec(
                deck_id=deck_id,
                label=str(item.get("team_name") or deck_id),
                path=deck_path,
                cards=load_deck_csv(deck_path),
            )
        )
    return decks


def load_deck_spec(path: Path, *, deck_id: str | None = None, label: str | None = None) -> DeckSpec:
    resolved = path.resolve()
    resolved_id = deck_id or _slug_from_path(resolved)
    return DeckSpec(
        deck_id=resolved_id,
        label=label or resolved_id,
        path=resolved,
        cards=load_deck_csv(resolved),
    )


def build_matchups(
    decks: list[DeckSpec],
    *,
    include_mirror: bool = False,
    focus_deck_id: str | None = None,
) -> list[MatchupSpec]:
    matchups: list[MatchupSpec] = []
    for index_a, deck_a in enumerate(decks):
        start_b = index_a if include_mirror else index_a + 1
        for index_b in range(start_b, len(decks)):
            deck_b = decks[index_b]
            if focus_deck_id and focus_deck_id not in {deck_a.deck_id, deck_b.deck_id}:
                continue
            matchups.append(MatchupSpec(deck_a=deck_a, deck_b=deck_b))
    if not matchups:
        raise ValueError("no matchups generated; check deck list and filters")
    return matchups


def _pair_key(deck_a_id: str, deck_b_id: str) -> str:
    return f"{deck_a_id}|{deck_b_id}"


def _summary_from_matchup(matchup: MatchupSpec) -> PairSummary:
    return PairSummary(
        deck_a_id=matchup.deck_a.deck_id,
        deck_a_label=matchup.deck_a.label,
        deck_b_id=matchup.deck_b.deck_id,
        deck_b_label=matchup.deck_b.label,
    )


def _apply_game(summary: PairSummary, game: GameResult) -> None:
    summary.games += 1
    summary.total_steps += game.steps
    if game.reward_for_a > 0:
        summary.wins_a += 1
    elif game.reward_for_a < 0:
        summary.losses_a += 1
    else:
        summary.draws += 1


def _serialize_state(state: MarathonState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "started_at": state.started_at,
        "updated_at": state.updated_at,
        "total_games_completed": state.total_games_completed,
        "total_batches_completed": state.total_batches_completed,
        "matchup_index": state.matchup_index,
        "seed_cursor": state.seed_cursor,
        "stop_requested": state.stop_requested,
        "pair_summaries": {
            key: asdict(value) for key, value in state.pair_summaries.items()
        },
    }


def _deserialize_state(payload: dict[str, Any]) -> MarathonState:
    summaries: dict[str, PairSummary] = {}
    for key, item in (payload.get("pair_summaries") or {}).items():
        summaries[key] = PairSummary(**item)
    return MarathonState(
        run_id=str(payload["run_id"]),
        started_at=str(payload["started_at"]),
        updated_at=str(payload.get("updated_at") or payload["started_at"]),
        total_games_completed=int(payload.get("total_games_completed", 0)),
        total_batches_completed=int(payload.get("total_batches_completed", 0)),
        matchup_index=int(payload.get("matchup_index", 0)),
        seed_cursor=int(payload.get("seed_cursor", 0)),
        stop_requested=bool(payload.get("stop_requested", False)),
        pair_summaries=summaries,
    )


def save_checkpoint(run_dir: Path, state: MarathonState) -> None:
    state.updated_at = _utc_now()
    checkpoint_path = run_dir / "checkpoint.json"
    checkpoint_path.write_text(
        json.dumps(_serialize_state(state), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_checkpoint(run_dir: Path) -> MarathonState:
    checkpoint_path = run_dir / "checkpoint.json"
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    return _deserialize_state(payload)


def write_matrix_csv(run_dir: Path, state: MarathonState) -> Path:
    csv_path = run_dir / "matrix_summary.csv"
    rows = sorted(
        state.pair_summaries.values(),
        key=lambda item: (item.deck_a_id, item.deck_b_id),
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "deck_a_id",
                "deck_a_label",
                "deck_b_id",
                "deck_b_label",
                "games",
                "wins_a",
                "losses_a",
                "draws",
                "win_rate_a",
                "avg_steps",
            ]
        )
        for item in rows:
            writer.writerow(
                [
                    item.deck_a_id,
                    item.deck_a_label,
                    item.deck_b_id,
                    item.deck_b_label,
                    item.games,
                    item.wins_a,
                    item.losses_a,
                    item.draws,
                    item.win_rate_a,
                    item.avg_steps,
                ]
            )
    return csv_path


def write_matrix_json(run_dir: Path, state: MarathonState, config: dict[str, Any]) -> Path:
    json_path = run_dir / "matrix_summary.json"
    payload = {
        "run_id": state.run_id,
        "updated_at": state.updated_at,
        "total_games_completed": state.total_games_completed,
        "total_batches_completed": state.total_batches_completed,
        "config": config,
        "pairs": [asdict(item) for item in state.pair_summaries.values()],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return json_path


def _result_record(
    game: GameResult,
    *,
    run_id: str,
    matchup: MatchupSpec,
    game_number: int,
    compact: bool,
) -> dict[str, Any]:
    record = game_to_record(game, compact=compact)
    record.update(
        {
            "run_id": run_id,
            "game_number": game_number,
            "matchup_id": matchup.matchup_id,
            "deck_a_id": matchup.deck_a.deck_id,
            "deck_a_label": matchup.deck_a.label,
            "deck_b_id": matchup.deck_b.deck_id,
            "deck_b_label": matchup.deck_b.label,
            "source": "marathon",
        }
    )
    return record


@dataclass
class MarathonConfig:
    run_id: str
    run_dir: Path
    matchups: list[MatchupSpec]
    games_per_batch: int
    total_games: int | None
    max_batches: int | None
    seed: int
    max_steps: int
    weights_a: dict[str, float]
    weights_b: dict[str, float]
    record_trajectories: bool
    compact_records: bool
    checkpoint_every_batches: int
    gc_every_batches: int
    sleep_seconds: float


class MarathonRunner:
    def __init__(self, config: MarathonConfig, state: MarathonState | None = None) -> None:
        self.config = config
        self.state = state or MarathonState(
            run_id=config.run_id,
            started_at=_utc_now(),
            updated_at=_utc_now(),
            seed_cursor=config.seed,
        )
        self._install_signal_handlers()
        self._agent_cache: dict[tuple[str, str], tuple[AgentFn, AgentFn]] = {}

    def _agents_for(self, matchup: MatchupSpec) -> tuple[AgentFn, AgentFn]:
        key = (matchup.deck_a.deck_id, matchup.deck_b.deck_id)
        cached = self._agent_cache.get(key)
        if cached is not None:
            return cached
        agents = (
            make_agent(matchup.deck_a.cards, self.config.weights_a),
            make_agent(matchup.deck_b.cards, self.config.weights_b),
        )
        self._agent_cache[key] = agents
        return agents

    def _install_signal_handlers(self) -> None:
        def _handle_stop(signum: int, _frame: Any) -> None:
            print(f"\nreceived signal {signum}; finishing current batch then checkpointing...")
            self.state.stop_requested = True

        signal.signal(signal.SIGINT, _handle_stop)
        signal.signal(signal.SIGTERM, _handle_stop)

    def _ensure_pair_summary(self, matchup: MatchupSpec) -> PairSummary:
        key = _pair_key(matchup.deck_a.deck_id, matchup.deck_b.deck_id)
        if key not in self.state.pair_summaries:
            self.state.pair_summaries[key] = _summary_from_matchup(matchup)
        return self.state.pair_summaries[key]

    def _should_stop(self) -> bool:
        if self.state.stop_requested:
            return True
        if self.config.total_games is not None and self.state.total_games_completed >= self.config.total_games:
            return True
        if self.config.max_batches is not None and self.state.total_batches_completed >= self.config.max_batches:
            return True
        return False

    def _games_this_batch(self) -> int:
        if self.config.total_games is None:
            return self.config.games_per_batch
        remaining = self.config.total_games - self.state.total_games_completed
        return max(0, min(self.config.games_per_batch, remaining))

    def run(self) -> MarathonState:
        config = self.config
        run_dir = config.run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        results_path = run_dir / "results.jsonl"

        print(f"marathon run_id={config.run_id}")
        print(f"matchups={len(config.matchups)} games_per_batch={config.games_per_batch}")
        print(f"output={run_dir}")

        # Warm card metadata once so batch loops do not trigger lazy-load spikes.
        card_meta_table()

        while not self._should_stop():
            games = self._games_this_batch()
            if games <= 0:
                break

            matchup = config.matchups[self.state.matchup_index % len(config.matchups)]
            random.seed(self.state.seed_cursor)
            self.state.seed_cursor += 1

            started = time.time()
            agent_a, agent_b = self._agents_for(matchup)
            results = run_self_play_batch(
                matchup.deck_a.cards,
                matchup.deck_b.cards,
                games=games,
                max_steps=config.max_steps,
                record_trajectories=config.record_trajectories,
                store_metadata=False,
                agent_a=agent_a,
                agent_b=agent_b,
                slim_trajectory=config.compact_records,
            )

            summary = self._ensure_pair_summary(matchup)
            for offset, game in enumerate(results):
                _apply_game(summary, game)
                if config.record_trajectories:
                    append_jsonl_line(
                        _result_record(
                            game,
                            run_id=config.run_id,
                            matchup=matchup,
                            game_number=self.state.total_games_completed + offset + 1,
                            compact=config.compact_records,
                        ),
                        results_path,
                    )
                game.trajectory.clear()

            wins_a = sum(1 for game in results if game.reward_for_a > 0)
            losses_a = sum(1 for game in results if game.reward_for_a < 0)
            draws = sum(1 for game in results if game.reward_for_a == 0)
            elapsed = round(time.time() - started, 2)

            self.state.total_games_completed += len(results)
            self.state.total_batches_completed += 1
            self.state.matchup_index = (self.state.matchup_index + 1) % len(config.matchups)

            print(
                f"batch={self.state.total_batches_completed} "
                f"games_total={self.state.total_games_completed} "
                f"matchup={matchup.matchup_id} "
                f"W/L/D={wins_a}/{losses_a}/{draws} "
                f"elapsed_s={elapsed}",
                flush=True,
            )

            if self.state.total_batches_completed % config.checkpoint_every_batches == 0:
                write_matrix_csv(run_dir, self.state)
                write_matrix_json(
                    run_dir,
                    self.state,
                    {
                        "games_per_batch": config.games_per_batch,
                        "total_games": config.total_games,
                        "max_batches": config.max_batches,
                        "seed": config.seed,
                        "max_steps": config.max_steps,
                    },
                )
                save_checkpoint(run_dir, self.state)

            if config.sleep_seconds > 0:
                time.sleep(config.sleep_seconds)

            results.clear()
            if config.gc_every_batches > 0 and self.state.total_batches_completed % config.gc_every_batches == 0:
                gc.collect()

        write_matrix_csv(run_dir, self.state)
        write_matrix_json(
            run_dir,
            self.state,
            {
                "games_per_batch": config.games_per_batch,
                "total_games": config.total_games,
                "max_batches": config.max_batches,
                "seed": config.seed,
                "max_steps": config.max_steps,
            },
        )
        save_checkpoint(run_dir, self.state)
        print(
            f"marathon stopped games_total={self.state.total_games_completed} "
            f"batches={self.state.total_batches_completed}",
            flush=True,
        )
        return self.state
