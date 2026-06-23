#!/usr/bin/env python3
"""Audit CONTROL modifier: Meowth ex setup when leading, Judge ordering in HARVEST."""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(SKILL / "scripts")]

from cg.api import OptionType, to_observation_class
from cg.game import battle_finish, battle_select, battle_start
from arena.deck import load_deck_csv
from arena.policy import make_agent
from hand_snapshot import build_board_snapshot
from opening_cards import JUDGE, MEOWTH_EX
from phase_fsm import compute_phase
from starmie_pilot import _attack_id, _hand_card_id, _meowth_on_field, make_starmie_agent

RESENTFUL = 1240

OPPONENT_MATCHUPS: dict[str, str] = {
    "walrein": "data/decks/walrein_control.csv",
    "mirror": "data/decks/starmie_froslass.csv",
}


def _resolve_deck(path: str) -> list[int]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return load_deck_csv(p)


@dataclass
class ControlAudit:
    opponent: str
    seed: int
    result: int
    steps: int
    control_turns: set[int] = field(default_factory=set)
    meowth_opportunities: set[int] = field(default_factory=set)
    meowth_plays: list[int] = field(default_factory=list)
    meowth_abilities: list[int] = field(default_factory=list)
    judge_plays_harvest: list[int] = field(default_factory=list)
    resentful_turns: set[int] = field(default_factory=set)
    judge_before_resentful: bool = False
    events: list[str] = field(default_factory=list)


def audit_game(
    seed: int,
    deck_a,
    deck_b,
    *,
    opponent: str = "walrein",
    max_steps: int = 700,
) -> ControlAudit:
    random.seed(seed)
    agent_a = make_starmie_agent(deck_a)
    agent_b = make_agent(deck_b)
    obs, _ = battle_start(deck_a, deck_b)
    audit = ControlAudit(opponent=opponent, seed=seed, result=-1, steps=0)
    first_resentful: int | None = None

    try:
        steps = 0
        while obs["current"]["result"] < 0 and steps < max_steps:
            pi = obs["current"]["yourIndex"]
            agent = agent_a if pi == 0 else agent_b

            if pi == 0:
                oc = to_observation_class(obs)
                board = build_board_snapshot(oc)
                phase = compute_phase(board)
                mt = board.my_turn_number
                me = oc.current.players[0]
                hand_ids = {int(c.id) for c in (me.hand or []) if c}

                if phase.control_active and mt >= 1:
                    audit.control_turns.add(mt)
                    if (
                        MEOWTH_EX in hand_ids
                        and board.bench_open > 0
                        and not _meowth_on_field(oc, 0)
                        and not (
                            (phase.primary == "AGGRESSION" and board.active_is_mega_starmie and board.active_has_water)
                            or (phase.primary == "HARVEST" and board.active_is_mega_froslass and board.active_has_water)
                        )
                    ):
                        audit.meowth_opportunities.add(mt)

                sel = obs.get("select") or {}
                opts = sel.get("option") or []
                action = agent(obs)

                if opts and action:
                    ch = action[0]
                    if 0 <= ch < len(opts):
                        raw = opts[ch]
                        ot = raw.get("type")
                        opt = NS(
                            type=ot,
                            area=raw.get("area"),
                            index=raw.get("index"),
                            attackId=raw.get("attackId"),
                        )
                        if phase.control_active:
                            if ot == OptionType.PLAY:
                                cid = _hand_card_id(oc, opt, 0)
                                if cid == MEOWTH_EX:
                                    audit.meowth_plays.append(mt)
                                    audit.events.append(f"My-T{mt} PLAY Meowth ex (CONTROL)")
                                elif cid == JUDGE and phase.primary == "HARVEST":
                                    audit.judge_plays_harvest.append(mt)
                                    audit.events.append(f"My-T{mt} PLAY Judge (HARVEST+CONTROL)")
                                    if first_resentful is None or mt < first_resentful:
                                        audit.judge_before_resentful = True
                            elif ot == OptionType.ABILITY:
                                src = (me.bench or []) + (me.active or [])
                                idx = raw.get("index", -1)
                                area = raw.get("area")
                                # ability source tracked loosely via event
                                audit.meowth_abilities.append(mt)
                                audit.events.append(f"My-T{mt} ABILITY Last-Ditch (CONTROL)")
                            elif ot == OptionType.ATTACK:
                                if _attack_id(opt) == RESENTFUL:
                                    audit.resentful_turns.add(mt)
                                    if first_resentful is None:
                                        first_resentful = mt
            else:
                action = agent(obs)

            obs = battle_select(action)
            steps += 1

        audit.steps = steps
        audit.result = obs["current"]["result"]
    finally:
        battle_finish()

    return audit


def _pass_criteria(a: ControlAudit) -> tuple[bool, list[str]]:
    ok = True
    notes: list[str] = []
    opps = sorted(a.meowth_opportunities)
    plays = set(a.meowth_plays)

    if not a.control_turns:
        ok = False
        notes.append("全程未进入 CONTROL（领先）窗口")
    else:
        notes.append(
            f"CONTROL 回合 My-T{min(a.control_turns)}..{max(a.control_turns)} "
            f"({len(a.control_turns)} 回合)"
        )

    if opps:
        hit = len(plays & set(opps))
        rate = 100.0 * hit / len(opps)
        notes.append(
            f"Meowth 机会 {len(opps)} 回合，PLAY {hit} ({rate:.0f}%)"
        )
        if rate < 50.0:
            ok = False
    else:
        notes.append("无 Meowth PLAY 机会（或无 Meowth/满 bench/必攻窗口）")

    if a.judge_before_resentful:
        ok = False
        notes.append("违规: HARVEST+CONTROL 内在 Resentful 前 PLAY Judge")
    elif a.judge_plays_harvest:
        notes.append(f"Judge @ My-T{a.judge_plays_harvest}（均在 Resentful 之后）")

    return ok, notes


def format_report(audits: list[ControlAudit]) -> str:
    n = len(audits)
    pass_n = sum(1 for a in audits if _pass_criteria(a)[0])
    opps_total = sum(len(a.meowth_opportunities) for a in audits)
    plays_total = sum(
        len(set(a.meowth_plays) & a.meowth_opportunities) for a in audits
    )
    meowth_rate = 100.0 * plays_total / max(1, opps_total)
    judge_viol = sum(1 for a in audits if a.judge_before_resentful)

    lines = [
        "# CONTROL modifier 审计 — 领先控场",
        f"# generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "## KPI 汇总",
        "",
        "| 指标 | 结果 | 目标 | 状态 |",
        "|---|---:|---:|:---:|",
        f"| CONTROL PASS 率 | {pass_n}/{n} ({100*pass_n/max(1,n):.1f}%) | — | — |",
        f"| Meowth 机会命中率 | {plays_total}/{opps_total} ({meowth_rate:.1f}%) | ≥50% | "
        f"{'✓' if meowth_rate >= 50 else ('—' if not opps_total else '✗')} |",
        f"| HARVEST Judge 先于 Resentful | {judge_viol}/{n} | 0 | "
        f"{'✓' if judge_viol == 0 else '✗'} |",
        "",
    ]

    for a in audits:
        ok, notes = _pass_criteria(a)
        lines.append(f"### `{a.opponent}` seed={a.seed} {'PASS' if ok else 'FAIL'}")
        for note in notes:
            lines.append(f"- {note}")
        if a.events:
            lines.append("")
            lines.append("#### 关键动作")
            for ev in a.events[:15]:
                lines.append(f"- {ev}")
        lines.append("")

    lines.append(f"**总 CONTROL PASS: {pass_n}/{n}**")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(42, 52)))
    parser.add_argument("--opponent", dest="opponents", nargs="+", default=["walrein"])
    parser.add_argument("-o", type=Path, default=None)
    args = parser.parse_args()

    deck_a = _resolve_deck("data/decks/starmie_froslass.csv")
    audits: list[ControlAudit] = []
    for opp in args.opponents:
        if opp not in OPPONENT_MATCHUPS:
            raise SystemExit(f"未知对手: {opp}")
        deck_b = _resolve_deck(OPPONENT_MATCHUPS[opp])
        for seed in args.seeds:
            audits.append(audit_game(seed, deck_a, deck_b, opponent=opp))

    out = args.o or SKILL / "logs" / "control_audit.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = format_report(audits)
    out.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
