#!/usr/bin/env python3
"""Phase 2: summarize plan_trace violations / skip-evolve cuts for expert triage.

Reads an H2H audit dir (prefer *.plan.jsonl + PLAN_DISCIPLINE.md inputs) and
writes PLAN_DIFF.md grouping Top execution misses by (step, option_type, card_id).

Usage:
  python3 scripts/diff_plan_vs_actions.py --audit-dir logs/h2h_audit_planStep_full_n200
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_OT_NAMES = {
    3: "CARD",
    6: "ATTACH",
    7: "PLAY",
    8: "EVOLVE",
    9: "ABILITY",
    12: "RETREAT",
    13: "ATTACK",
    14: "END",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--audit-dir", type=Path, required=True)
    args = ap.parse_args()
    audit = args.audit_dir
    man = json.loads((audit / "manifest.json").read_text(encoding="utf-8"))
    viol = Counter()
    viol_examples: dict[tuple, list[str]] = {}
    skip = Counter()
    n_trace = 0
    for g in man.get("games") or []:
        stem = f"game_{g['i']:03d}"
        plan_p = audit / "games" / f"{stem}.plan.jsonl"
        if plan_p.is_file():
            n_trace += 1
            for line in plan_p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if not row.get("plan_violation"):
                    continue
                key = (
                    row.get("primary_step"),
                    _OT_NAMES.get(row.get("option_type"), str(row.get("option_type"))),
                    row.get("card_or_attack_id"),
                )
                viol[key] += 1
                viol_examples.setdefault(key, []).append(stem)
        hit_p = audit / "plan_discipline_hits.jsonl"
    # Also read aggregated hits if present
    hits_path = audit / "plan_discipline_hits.jsonl"
    if hits_path.is_file():
        for line in hits_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            h = json.loads(line)
            if h.get("pattern") == "skip_evolve_after_cut":
                skip[h.get("hint", "?")] += 1

    lines = [
        f"# Plan vs actions diff — `{audit.name}`",
        "",
        f"- games with plan_trace: {n_trace}/{man.get('n')}",
        f"- WR: {man.get('wr_current_decided')}",
        "",
        "## Top plan_violation (execution miss on locked step)",
        "",
        "| step | option | card/atk | n | examples |",
        "|---|---|---:|---:|---|",
    ]
    for (step, ot, cid), n in viol.most_common(25):
        ex = ",".join(viol_examples.get((step, ot, cid), [])[:4])
        lines.append(f"| {step} | {ot} | {cid} | {n} | {ex} |")
    if not viol:
        lines.append("| — | — | — | 0 | |")
    lines.extend([
        "",
        "## skip_evolve_after_cut (zh-log)",
        "",
    ])
    if skip:
        for hint, n in skip.most_common(15):
            lines.append(f"- ×{n}: {hint}")
    else:
        lines.append("- (none)")
    lines.extend([
        "",
        "## Triage guide",
        "",
        "- Same step + wrong PLAY/supporter → **执行错**（扩 `_option_advances` 或收紧 demote）",
        "- step 本身不合理（专家不会走该 gap）→ **Plan 错**（改 `turn_planner`）",
        "- A2 墙 / GS Budew / must_close → **合法例外**，勿当 violation 修掉",
        "",
    ])
    out = audit / "PLAN_DIFF.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} (viol_kinds={len(viol)} skip_kinds={len(skip)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
