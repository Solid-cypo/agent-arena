#!/usr/bin/env python3
"""Scan H2H audit dirs for TurnPlan step-discipline metrics.

Reads:
  logs/h2h_audit_<tag>/manifest.json
  games/game_XXX.plan.jsonl   (preferred — agent plan_trace)
  games/game_XXX.log          (fallback — skip_evolve_after_cut from zh log)

Writes:
  PLAN_DISCIPLINE.md
  plan_discipline_hits.jsonl

Usage:
  python3 scripts/scan_plan_discipline.py --audit-dir logs/h2h_audit_planStep_vs_firefix_n100
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_RE_OUR_TURN = re.compile(r"^【我方-T(\d+)】")
_RE_OPP_TURN = re.compile(r"^【对手-T(\d+)】")
_RE_RETREAT_TO_STARYU = re.compile(
    r"\[撤退/交替\]\s*(含羞苞|土龙弟弟)\s*⇄\s*海星星"
)
_RE_EVOLVE_MEGA = re.compile(r"\[进化\].*海星星\s*→\s*Mega\s*大海星")
_RE_SUPPORTER = re.compile(
    r"\[操作\]\s*使用\s*(希尔达|克里宾|莉莉艾|萨瓦特|不公平)"
)
_RE_ENDISH = re.compile(r"\[攻击\]|回合结束|【对手-T")

# OptionType ints from cg.api
_OT_EVOLVE = 8
_OT_PLAY = 7
_OT_ATTACH = 6
_OT_END = 14
_OT_ATTACK = 13
_OT_RETREAT = 12

LOCKED_DEFAULT = frozenset({
    "EVOLUTION", "ENERGY", "DIG_EVOLUTION", "BASE", "DISPATCH",
    "ADRENA", "BOSS", "EVOLVE_104", "ATTACH_DARK",
})


def _load_manifest(audit_dir: Path) -> dict:
    return json.loads((audit_dir / "manifest.json").read_text(encoding="utf-8"))


def _scan_plan_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _skip_evolve_after_cut_from_log(log_path: Path) -> list[dict]:
    """Detect protector→Staryu cut then no Mega evolve before supporter/opp turn."""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    hits = []
    turn = 0
    our = False
    pending_cut = False
    cut_turn = 0
    evolved = False
    for raw in text.splitlines():
        line = raw.strip()
        m = _RE_OUR_TURN.match(line)
        if m:
            turn = int(m.group(1))
            our = True
            pending_cut = False
            evolved = False
            continue
        if _RE_OPP_TURN.match(line):
            if pending_cut and not evolved:
                hits.append({
                    "pattern": "skip_evolve_after_cut",
                    "turn": cut_turn,
                    "hint": f"T{cut_turn}: cut to Staryu, no Mega evo before opp turn",
                })
            our = False
            pending_cut = False
            continue
        if not our:
            continue
        if _RE_RETREAT_TO_STARYU.search(line) and "对手" not in line:
            pending_cut = True
            cut_turn = turn
            evolved = False
            continue
        if pending_cut and _RE_EVOLVE_MEGA.search(line) and "对手" not in line:
            evolved = True
            pending_cut = False
            continue
        if pending_cut and not evolved and _RE_SUPPORTER.search(line) and "对手" not in line:
            hits.append({
                "pattern": "skip_evolve_after_cut",
                "turn": cut_turn,
                "hint": f"T{cut_turn}: cut to Staryu then supporter before Mega evo",
            })
            pending_cut = False
    return hits


def scan_audit(audit_dir: Path) -> dict:
    man = _load_manifest(audit_dir)
    games = man.get("games") or []
    step_tot: Counter = Counter()
    step_adv: Counter = Counter()
    step_viol: Counter = Counter()
    evo_tot = evo_ok = 0
    locked_tot = locked_adv = locked_viol = 0
    skip_cut_games = 0
    skip_cut_hits = 0
    hit_rows: list[dict] = []
    games_with_trace = 0

    for g in games:
        i = g["i"]
        stem = f"game_{i:03d}"
        plan_path = audit_dir / "games" / f"{stem}.plan.jsonl"
        log_path = audit_dir / "games" / f"{stem}.log"
        cur_win = g.get("cur_win")

        if plan_path.is_file():
            games_with_trace += 1
            for row in _scan_plan_jsonl(plan_path):
                step = row.get("primary_step")
                if not step:
                    continue
                step_tot[step] += 1
                if row.get("advances_step"):
                    step_adv[step] += 1
                if row.get("plan_violation"):
                    step_viol[step] += 1
                    hit_rows.append({
                        "pattern": "plan_violation",
                        "game": stem,
                        "cur_win": cur_win,
                        "step": step,
                        "option_type": row.get("option_type"),
                        "card_or_attack_id": row.get("card_or_attack_id"),
                        "my_turn": row.get("my_turn"),
                    })
                # Compliance only when an advance was offered (else END/nest OK).
                adv_avail = row.get("advance_available")
                if adv_avail is None:
                    adv_avail = True  # legacy traces
                if step == "EVOLUTION" and adv_avail:
                    evo_tot += 1
                    if row.get("advances_step") or row.get("option_type") == _OT_EVOLVE:
                        evo_ok += 1
                if row.get("locked") and adv_avail:
                    locked_tot += 1
                    if row.get("advances_step"):
                        locked_adv += 1
                    if row.get("plan_violation"):
                        locked_viol += 1

        if log_path.is_file():
            skips = _skip_evolve_after_cut_from_log(log_path)
            if skips:
                skip_cut_games += 1
                skip_cut_hits += len(skips)
                for h in skips:
                    hit_rows.append({
                        "pattern": h["pattern"],
                        "game": stem,
                        "cur_win": cur_win,
                        "hint": h["hint"],
                        "turn": h["turn"],
                    })

    def rate(num: int, den: int) -> float:
        return (num / den) if den else 0.0

    by_step = []
    for step in sorted(step_tot.keys()):
        by_step.append({
            "step": step,
            "n": step_tot[step],
            "advances": step_adv[step],
            "violations": step_viol[step],
            "compliance": rate(step_adv[step], step_tot[step]),
            "violation_rate": rate(step_viol[step], step_tot[step]),
        })

    summary = {
        "audit_dir": str(audit_dir),
        "n_games": len(games),
        "games_with_plan_trace": games_with_trace,
        "wr": man.get("wr_current_decided"),
        "evo_compliance": rate(evo_ok, evo_tot),
        "evo_n": evo_tot,
        "step_compliance_locked": rate(locked_adv, locked_tot),
        "plan_violation_rate": rate(locked_viol, locked_tot),
        "locked_n": locked_tot,
        "skip_evolve_after_cut_games": skip_cut_games,
        "skip_evolve_after_cut_hits": skip_cut_hits,
        "by_step": by_step,
    }
    return summary, hit_rows


def write_report(audit_dir: Path, summary: dict, hits: list[dict]) -> None:
    lines = [
        f"# Plan discipline — `{audit_dir.name}`",
        "",
        f"- games: {summary['n_games']} · with plan_trace: {summary['games_with_plan_trace']}",
        f"- WR (manifest): {summary.get('wr')}",
        "",
        "## KPIs",
        "",
        f"| metric | value | target |",
        f"|---|---:|---|",
        f"| evo_compliance | {summary['evo_compliance']:.1%} (n={summary['evo_n']}) | ≥95% |",
        f"| step_compliance (locked) | {summary['step_compliance_locked']:.1%} (n={summary['locked_n']}) | ≥90% |",
        f"| plan_violation_rate | {summary['plan_violation_rate']:.1%} | ≤5% |",
        f"| skip_evolve_after_cut games/hits | {summary['skip_evolve_after_cut_games']} / {summary['skip_evolve_after_cut_hits']} | ↓ vs A2 baseline |",
        "",
        "## By primary_step",
        "",
        "| step | n | compliance | viol_rate |",
        "|---|---:|---:|---:|",
    ]
    for s in summary["by_step"]:
        lines.append(
            f"| {s['step']} | {s['n']} | {s['compliance']:.1%} | {s['violation_rate']:.1%} |"
        )
    lines.append("")
    (audit_dir / "PLAN_DISCIPLINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(audit_dir / "plan_discipline_hits.jsonl", "w", encoding="utf-8") as h:
        for row in hits:
            h.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {audit_dir / 'PLAN_DISCIPLINE.md'}")
    print(
        f"  evo_compliance={summary['evo_compliance']:.1%} "
        f"locked_compliance={summary['step_compliance_locked']:.1%} "
        f"viol={summary['plan_violation_rate']:.1%} "
        f"skip_cut_games={summary['skip_evolve_after_cut_games']}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--audit-dir",
        type=Path,
        default=ROOT / "logs/h2h_audit_planStep_vs_firefix_n100",
    )
    args = ap.parse_args()
    summary, hits = scan_audit(args.audit_dir)
    write_report(args.audit_dir, summary, hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
