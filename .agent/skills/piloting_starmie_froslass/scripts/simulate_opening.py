#!/usr/bin/env python3
"""Simulate OPENING until Goal: shuffle once at start, deterministic deck ops after."""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
LOG_DIR = SCRIPTS.parent / "logs"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.deck import load_deck_csv  # noqa: E402
from opening_cards import BASIC_IDS, name, names  # noqa: E402
from opening_planner import classify_miss, plan_and_execute_turn  # noqa: E402
from opening_state import Action, OpeningGameState  # noqa: E402
from setup_planner import run_setup  # noqa: E402

MAX_TURNS = 5


@dataclass
class SetupRecord:
    active: str = ""
    bench: list[str] = field(default_factory=list)
    archetype: str = ""
    hand_after: list[str] = field(default_factory=list)
    board_after: str = ""
    actions: list[str] = field(default_factory=list)


@dataclass
class TurnRecord:
    my_turn: int
    hand_start: list[str]
    board_start: str
    actions: list[str]
    hand_end: list[str]
    board_end: str
    route: str


@dataclass
class SimRecord:
    seed: int | None
    prizes: list[str]
    opening_hand: list[str]
    mulligans: int
    setup: SetupRecord
    turns: list[TurnRecord]
    routes: list[str]
    goal: bool
    miss_class: str
    final_turn: int


def shuffle_deck(deck: list[int], seed: int | None = None) -> list[int]:
    out = list(deck)
    rng = random.Random(seed)
    rng.shuffle(out)
    return out


def mulligan_until_basic(st: OpeningGameState, max_mulligans: int = 10) -> int:
    count = 0
    while count < max_mulligans:
        if any(c in BASIC_IDS for c in st.hand):
            return count
        bottom = list(st.hand)
        st.hand.clear()
        st.deck.extend(bottom)
        draw_n = min(7, len(st.deck))
        st.hand = [st.deck.pop(0) for _ in range(draw_n)]
        st._log("NOTE", f"Mulligan #{count + 1} — redraw 7")
        count += 1
    return count


def _format_actions(actions: list[Action]) -> list[str]:
    out: list[str] = []
    for i, a in enumerate(actions, 1):
        out.append(f"  {i}. [{a.kind}] {a.detail}")
    return out


def simulate_opening(
    deck: list[int],
    *,
    going_first: bool = True,
    verbose: bool = True,
    max_turns: int = MAX_TURNS,
    shuffle: bool = False,
    seed: int | None = None,
    record: SimRecord | None = None,
) -> OpeningGameState:
    ordered = shuffle_deck(deck, seed) if shuffle else list(deck)
    st = OpeningGameState.from_ordered_deck(ordered, going_first=going_first)
    mull_count = mulligan_until_basic(st)

    opening_hand = names(list(st.hand))
    prize_names = names(list(st.prizes))

    if verbose:
        tag = f"seed={seed}" if seed is not None else "ordered"
        print(f"=== Deck slice ({tag}) ===")
        print(f"  Prizes (6): {prize_names}")
        print(f"  Opening hand (7): {opening_hand}")
        print(f"  Deck top-5: {names(st.deck[:5])} … ({len(st.deck)} left)")
        print()

    setup_rec = SetupRecord()
    log_before_setup = len(st.log)
    run_setup(st)
    setup_actions = _format_actions(st.log[log_before_setup:])
    setup_rec.active = name(st.active.card_id) if st.active else "—"
    setup_rec.bench = [name(p.card_id) for p in st.bench]
    setup_rec.archetype = st.setup_archetype
    setup_rec.hand_after = names(list(st.hand))
    setup_rec.board_after = st.format_board()
    setup_rec.actions = setup_actions

    routes: list[str] = []
    turn_records: list[TurnRecord] = []
    my_t = 0
    while my_t < max_turns and not st.opening_complete():
        my_t += 1
        log_at_turn = len(st.log)
        hand_start = names(list(st.hand))
        board_start = st.format_board()

        turn = my_t if going_first else my_t + 1
        st.begin_turn(turn, my_t)

        if verbose:
            print(f"--- My-T{my_t} start: {st.snapshot_summary()} ---")

        route = plan_and_execute_turn(st)
        routes.append(route)

        turn_actions = _format_actions(st.log[log_at_turn:])
        turn_records.append(TurnRecord(
            my_turn=my_t,
            hand_start=hand_start,
            board_start=board_start,
            actions=turn_actions,
            hand_end=names(list(st.hand)),
            board_end=st.format_board(),
            route=route,
        ))

        if verbose:
            print(f"  → route {route}")
            print(f"  end: {st.snapshot_summary()}")
            print()

        if route == "GOAL" or st.opening_complete():
            break

    if record is not None:
        record.seed = seed
        record.prizes = prize_names
        record.opening_hand = opening_hand
        record.mulligans = mull_count
        record.setup = setup_rec
        record.turns = turn_records
        record.routes = routes
        record.goal = st.opening_complete()
        record.miss_class = classify_miss(st)
        record.final_turn = st.my_turn_number

    if verbose:
        print(_decision_tree(st, routes))
    return st


def _decision_tree(st: OpeningGameState, routes: list[str]) -> str:
    lines = [
        "=== Decision tree ===",
        f"  Setup → archetype {st.setup_archetype}",
    ]
    for i, r in enumerate(routes, 1):
        lines.append(f"  My-T{i} → {r}")
    lines.append(
        f"  Goal: {'YES' if st.opening_complete() else 'NO'} "
        f"({classify_miss(st)}) after {st.my_turn_number} turns (max {MAX_TURNS})"
    )
    return "\n".join(lines)


def export_sim_record(rec: SimRecord, *, run_index: int | None = None) -> str:
    header = f"Run #{run_index}" if run_index is not None else "Run"
    seed_line = f"seed={rec.seed}" if rec.seed is not None else "ordered deck"
    lines = [
        f"{'=' * 72}",
        f"{header} ({seed_line})",
        f"结果: {'GOAL 达成' if rec.goal else '未达成'} "
        f"({rec.miss_class}) · 结束于 My-T{rec.final_turn} · 上限 {MAX_TURNS} 回合",
        "",
        "【起始】",
        f"  奖品区 (6): {', '.join(rec.prizes)}",
        f"  起手手牌 (7): {', '.join(rec.opening_hand)}",
        f"  Mulligan 次数: {rec.mulligans}",
        "",
        "【Setup】",
        f"  原型: {rec.setup.archetype}",
        f"  操作:",
    ]
    lines.extend(rec.setup.actions or ["  （无）"])
    lines.extend([
        f"  Setup 后手牌: {', '.join(rec.setup.hand_after) or '（空）'}",
        "  Setup 后场面:",
        rec.setup.board_after,
        "",
    ])

    for tr in rec.turns:
        lines.extend([
            f"【My-T{tr.my_turn}】 路线: {tr.route}",
            "  回合开始手牌:",
            f"    {', '.join(tr.hand_start) or '（空）'}",
            "  回合开始场面:",
            tr.board_start,
            "  本回合操作:",
        ])
        lines.extend(tr.actions or ["  （无）"])
        lines.extend([
            "  回合结束手牌:",
            f"    {', '.join(tr.hand_end) or '（空）'}",
            "  回合结束场面:",
            tr.board_end,
            "",
        ])

    return "\n".join(lines)


def export_batch_log(records: list[SimRecord], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for r in records if r.goal)
    summary = [
        "OPENING 批量测试日志",
        f"生成时间: {datetime.now().isoformat(timespec='seconds')}",
        f"回合上限: {MAX_TURNS}",
        f"测试局数: {len(records)}",
        f"Goal 达成: {passed}/{len(records)}",
        "",
    ]
    body = [export_sim_record(r, run_index=i + 1) for i, r in enumerate(records)]
    path.write_text("\n".join(summary + body), encoding="utf-8")
    return path


def run_batch(
    n: int = 10,
    *,
    seed_base: int = 42,
    verbose_failures: bool = True,
    max_turns: int = MAX_TURNS,
    export_path: Path | None = None,
) -> bool:
    deck_path = ROOT / "data" / "decks" / "starmie_froslass.csv"
    base = load_deck_csv(deck_path)
    records: list[SimRecord] = []
    passed = 0

    for i in range(n):
        seed = seed_base + i
        rec = SimRecord(
            seed=seed, prizes=[], opening_hand=[], mulligans=0,
            setup=SetupRecord(), turns=[], routes=[], goal=False,
            miss_class="", final_turn=0,
        )
        st = simulate_opening(
            base, shuffle=True, seed=seed, verbose=False,
            max_turns=max_turns, record=rec,
        )
        records.append(rec)
        if st.opening_complete():
            passed += 1
            print(f"  run {i + 1}/{n} seed={seed}: PASS in My-T{st.my_turn_number}")
        else:
            print(f"  run {i + 1}/{n} seed={seed}: FAIL ({classify_miss(st)}) "
                  f"after My-T{st.my_turn_number} active="
                  f"{name(st.active.card_id) if st.active else '—'}")
            if verbose_failures:
                for a in st.log[-5:]:
                    print(f"    [{a.kind}] {a.detail}")

    out = export_path or LOG_DIR / f"opening_batch_max{max_turns}_{seed_base}.log"
    export_batch_log(records, out)
    print(f"\n日志已导出: {out}")
    print(f"Goal 达成: {passed}/{n} (上限 {max_turns} 回合)")
    return passed == n


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="OPENING simulator")
    p.add_argument("--batch", type=int, default=0, help="Run N shuffled tests")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ordered", action="store_true", help="Use CSV order (no shuffle)")
    p.add_argument("--export", type=str, default="", help="Export log file path")
    p.add_argument("--max-turns", type=int, default=MAX_TURNS)
    args = p.parse_args()

    deck_path = ROOT / "data" / "decks" / "starmie_froslass.csv"
    base = load_deck_csv(deck_path)

    if args.batch > 0:
        export_path = Path(args.export) if args.export else None
        success = run_batch(
            args.batch, seed_base=args.seed, max_turns=args.max_turns,
            export_path=export_path,
        )
        sys.exit(0 if success else 1)

    rec = SimRecord(
        seed=None if args.ordered else args.seed,
        prizes=[], opening_hand=[], mulligans=0,
        setup=SetupRecord(), turns=[], routes=[], goal=False,
        miss_class="", final_turn=0,
    )
    st = simulate_opening(
        base,
        shuffle=not args.ordered,
        seed=None if args.ordered else args.seed,
        verbose=True,
        max_turns=args.max_turns,
        record=rec,
    )
    ok = st.opening_complete()
    print()
    print(f"VALID: {'pass' if ok else 'fail'} in My-T{st.my_turn_number}")

    if args.export:
        out = Path(args.export)
    else:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        tag = "ordered" if args.ordered else f"seed{args.seed}"
        out = LOG_DIR / f"opening_single_max{args.max_turns}_{tag}.log"
    out.write_text(export_sim_record(rec), encoding="utf-8")
    print(f"日志已导出: {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
