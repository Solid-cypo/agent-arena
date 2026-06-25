#!/usr/bin/env python3
"""Audit HARVEST phase: Mega Froslass ex evolve, Resentful attacks, Judge ordering."""
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
from opening_cards import CARD_NAMES, FROSLASS, JUDGE, MEGA_FROSLASS
from phase_fsm import compute_phase
from starmie_pilot import _attack_id, _hand_card_id, make_starmie_agent

RESENTFUL = 1240
ABS_SNOW = 1241

OPPONENT_MATCHUPS: dict[str, str] = {
    "walrein": "data/decks/walrein_control.csv",
    "mirror": "data/decks/starmie_froslass.csv",
}


def _resolve_deck(path: str) -> list[int]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return load_deck_csv(p)


def _name(cid: int) -> str:
    return CARD_NAMES.get(cid, str(cid))


@dataclass
class HarvestTurnSnap:
    my_turn: int
    phase: str
    active_id: int
    fro104: bool
    opp_hand: int
    combat_ready: bool


@dataclass
class HarvestAudit:
    opponent: str
    seed: int
    result: int
    steps: int
    harvest_turns: set[int] = field(default_factory=set)
    froslass_combat_turns: set[int] = field(default_factory=set)
    resentful_turns: set[int] = field(default_factory=set)
    evolve_861_turns: list[int] = field(default_factory=list)
    water_attach_turns: list[int] = field(default_factory=list)
    judge_plays: list[int] = field(default_factory=list)
    judge_before_resentful: bool = False
    turn_snaps: dict[int, HarvestTurnSnap] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)


def audit_game(
    seed: int,
    deck_a,
    deck_b,
    *,
    opponent: str = "walrein",
    max_steps: int = 700,
) -> HarvestAudit:
    random.seed(seed)
    agent_a = make_starmie_agent(deck_a)
    agent_b = make_agent(deck_b)
    obs, _ = battle_start(deck_a, deck_b)
    audit = HarvestAudit(opponent=opponent, seed=seed, result=-1, steps=0)
    first_resentful_turn: int | None = None

    try:
        steps = 0
        while obs["current"]["result"] < 0 and steps < max_steps:
            pi = obs["current"]["yourIndex"]
            agent = agent_a if pi == 0 else agent_b

            if pi == 0:
                oc = to_observation_class(obs)
                board = build_board_snapshot(oc)
                phase = compute_phase(board)
                me = oc.current.players[0]
                opp = oc.current.players[1]
                opp_hand = int(getattr(opp, "handCount", None) or 5)
                mt = board.my_turn_number
                combat_ready = (
                    board.active_is_mega_froslass and board.active_has_water
                )

                if phase.primary == "HARVEST" and mt >= 1:
                    audit.harvest_turns.add(mt)
                    if combat_ready:
                        audit.froslass_combat_turns.add(mt)
                    if mt not in audit.turn_snaps:
                        audit.turn_snaps[mt] = HarvestTurnSnap(
                            my_turn=mt,
                            phase=phase.primary,
                            active_id=board.active_id,
                            fro104=board.froslass_104_on_field,
                            opp_hand=opp_hand,
                            combat_ready=combat_ready,
                        )

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
                        if ot == OptionType.PLAY and phase.primary == "HARVEST":
                            cid = _hand_card_id(oc, opt, 0)
                            if cid == JUDGE:
                                audit.judge_plays.append(mt)
                                audit.events.append(f"My-T{mt} PLAY Judge (HARVEST)")
                                if first_resentful_turn is None or mt < first_resentful_turn:
                                    audit.judge_before_resentful = True
                        elif ot == OptionType.ATTACH and phase.primary == "HARVEST":
                            if board.active_is_mega_froslass and not board.active_has_water:
                                audit.water_attach_turns.append(mt)
                                audit.events.append(f"My-T{mt} ATTACH water →861")
                        elif ot == OptionType.EVOLVE and phase.primary == "HARVEST":
                            hand = me.hand or []
                            idx = raw.get("index", -1)
                            if 0 <= idx < len(hand) and hand[idx]:
                                if int(hand[idx].id) == MEGA_FROSLASS:
                                    audit.evolve_861_turns.append(mt)
                                    audit.events.append(
                                        f"My-T{mt} EVOLVE →Mega Froslass ex (861)"
                                    )
                        elif ot == OptionType.ATTACK and combat_ready:
                            atk = _attack_id(opt)
                            if atk == RESENTFUL:
                                audit.resentful_turns.add(mt)
                                if first_resentful_turn is None:
                                    first_resentful_turn = mt
                                dmg = opp_hand * 50
                                audit.events.append(
                                    f"My-T{mt} ATTACK Resentful (~{dmg} dmg)"
                                )
                            elif atk == ABS_SNOW:
                                audit.events.append(f"My-T{mt} ATTACK Absorbing Snow")
            else:
                action = agent(obs)

            obs = battle_select(action)
            steps += 1

        audit.steps = steps
        audit.result = obs["current"]["result"]
    finally:
        battle_finish()

    return audit


def _pass_criteria(a: HarvestAudit) -> tuple[bool, list[str]]:
    ok = True
    notes: list[str] = []
    combat = sorted(a.froslass_combat_turns)
    resentful = sorted(a.resentful_turns)
    missed = sorted(set(combat) - set(resentful))

    if not a.harvest_turns:
        ok = False
        notes.append("全程未进入 HARVEST 阶段")
    else:
        notes.append(
            f"HARVEST 回合 My-T{min(a.harvest_turns)}..{max(a.harvest_turns)} "
            f"({len(a.harvest_turns)} 回合)"
        )

    if a.evolve_861_turns:
        notes.append(f"861 进化 @ My-T{a.evolve_861_turns}")
    elif a.harvest_turns:
        notes.append("HARVEST 内未进化 Mega Froslass ex (861)")

    if combat:
        rate = 100.0 * len(resentful) / len(combat)
        notes.append(
            f"861 战斗回合 {len(combat)}，Resentful {len(resentful)}，漏攻 {len(missed)} "
            f"({rate:.0f}%)"
        )
        if missed:
            notes.append(f"  漏攻 My-T{missed}")
        if rate < 70.0:
            ok = False
    else:
        notes.append("无 Active 861+水 战斗回合")

    if a.judge_before_resentful:
        ok = False
        notes.append("违规: HARVEST 内在首次 Resentful 前 PLAY Judge")
    elif a.judge_plays:
        notes.append(f"Judge 使用 @ My-T{a.judge_plays}（均在 Resentful 之后或无关）")

    return ok, notes


def _kpi_summary(audits: list[HarvestAudit]) -> list[str]:
    n = len(audits)
    pass_n = sum(1 for a in audits if _pass_criteria(a)[0])
    combat_total = sum(len(g.froslass_combat_turns) for g in audits)
    resentful_total = sum(len(g.resentful_turns) for g in audits)
    atk_rate = 100.0 * resentful_total / max(1, combat_total)
    judge_viol = sum(1 for g in audits if g.judge_before_resentful)
    lines = [
        "## KPI 汇总（目标：Resentful 出招率 ≥70%，Judge 顺序违规 0）",
        "",
        "| 指标 | 结果 | 目标 | 状态 |",
        "|---|---:|---:|:---:|",
        f"| HARVEST PASS 率 | {pass_n}/{n} ({100*pass_n/max(1,n):.1f}%) | — | — |",
        f"| Resentful 战斗出招率 | {resentful_total}/{combat_total} ({atk_rate:.1f}%) | ≥70% | "
        f"{'✓' if atk_rate >= 70 else ('—' if not combat_total else '✗')} |",
        f"| Judge 先于 Resentful | {judge_viol}/{n} 局违规 | 0 | "
        f"{'✓' if judge_viol == 0 else '✗'} |",
        "",
    ]
    return lines


def format_report(audits: list[HarvestAudit], *, opponents: list[str]) -> str:
    lines = [
        "# HARVEST 阶段审计 — Mega Froslass ex 收割",
        f"# generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "## 审计标准",
        "- 进入 HARVEST 后，Active 861+水 时应 Resentful (1240)",
        "- HR-H6：首次 Resentful 前禁止 PLAY Judge",
        "- HR-H1：104 在场时应进化 861",
        "",
    ]
    lines.extend(_kpi_summary(audits))

    by_opp: dict[str, list[HarvestAudit]] = {}
    for a in audits:
        by_opp.setdefault(a.opponent, []).append(a)

    for opp in sorted(by_opp):
        games = by_opp[opp]
        pass_n = sum(1 for g in games if _pass_criteria(g)[0])
        combat = sum(len(g.froslass_combat_turns) for g in games)
        atk = sum(len(g.resentful_turns) for g in games)
        lines.append(f"## 对手 `{opp}` — {pass_n}/{len(games)} PASS")
        lines.append("")
        lines.append("| seed | 结果 | HARVEST回合 | 861进化 | Resentful | PASS |")
        lines.append("|---:|---|---:|---|---:|:---:|")
        for a in games:
            ok, _ = _pass_criteria(a)
            evo = f"T{a.evolve_861_turns[0]}" if a.evolve_861_turns else "—"
            res = len(a.resentful_turns)
            result = "胜" if a.result == 0 else ("负" if a.result == 1 else "?")
            lines.append(
                f"| {a.seed} | {result} | {len(a.harvest_turns)} | {evo} | {res} | "
                f"{'✓' if ok else '✗'} |"
            )
        lines.append("")
        for a in games:
            ok, notes = _pass_criteria(a)
            lines.append(f"### `{opp}` seed={a.seed} {'PASS' if ok else 'FAIL'}")
            for n in notes:
                lines.append(f"- {n}")
            if a.events:
                lines.append("")
                lines.append("#### 关键动作")
                for ev in a.events[:20]:
                    lines.append(f"- {ev}")
            lines.append("")

    total_pass = sum(1 for a in audits if _pass_criteria(a)[0])
    lines.append(f"**总 HARVEST PASS: {total_pass}/{len(audits)}**")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(42, 52)))
    parser.add_argument(
        "--opponent",
        dest="opponents",
        nargs="+",
        default=["walrein"],
    )
    parser.add_argument("-o", type=Path, default=None)
    args = parser.parse_args()

    opponents = args.opponents
    if opponents == ["all"]:
        opponents = sorted(OPPONENT_MATCHUPS)

    deck_a = _resolve_deck("data/decks/starmie_froslass.csv")
    audits: list[HarvestAudit] = []
    for opp in opponents:
        if opp not in OPPONENT_MATCHUPS:
            raise SystemExit(f"未知对手: {opp}")
        deck_b = _resolve_deck(OPPONENT_MATCHUPS[opp])
        for seed in args.seeds:
            audits.append(audit_game(seed, deck_a, deck_b, opponent=opp))

    out = args.o or SKILL / "logs" / "harvest_audit.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = format_report(audits, opponents=opponents)
    out.write_text(report, encoding="utf-8")
    print(report)
    combat = sum(len(g.froslass_combat_turns) for g in audits)
    atk = sum(len(g.resentful_turns) for g in audits)
    print(f"\nWrote {out} — Resentful {atk}/{combat} combat turns")


if __name__ == "__main__":
    main()
