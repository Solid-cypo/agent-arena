#!/usr/bin/env python3
"""Batch OPENING sim + stratified hard-case export for Active Learning.

Sample labels (7 negative : 3 to_optimize : 1 positive):
  - negative     T5 未达成 Goal（含规则违规）
  - to_optimize  T3–T5 才达成 Goal（拖沓）
  - positive     My-T1/T2 干净达成（专家正例）
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
LOG_DIR = SCRIPTS.parent / "logs" / "hard_cases"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.deck import load_deck_csv  # noqa: E402
from opening_validate import validate_log  # noqa: E402
from opening_log_formatter import dedupe_blocked_notes  # noqa: E402
from simulate_opening import (  # noqa: E402
    SetupRecord,
    SimRecord,
    export_sim_record,
    simulate_opening,
)

LABEL_NEGATIVE = "negative"
LABEL_TO_OPTIMIZE = "to_optimize"
LABEL_POSITIVE = "positive"

RATIO = (7, 3, 1)  # negative : to_optimize : positive

BLOCKED_PATTERNS = re.compile(
    r"blocked|不可用|skipped|违法|Switch unavailable|cannot evolve|ATTACH skipped",
    re.IGNORECASE,
)


@dataclass
class HardCase:
    seed: int
    sample_label: str
    category: str
    goal: bool
    miss_class: str
    final_turn: int
    archetype: str
    violations: list[str] = field(default_factory=list)
    blocked_notes: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"seed{self.seed}_{self.sample_label}_{self.miss_class}.log"


def _blocked_notes(st) -> list[str]:
    out: list[str] = []
    for a in st.log:
        if a.kind != "NOTE":
            continue
        if BLOCKED_PATTERNS.search(a.detail):
            out.append(a.detail)
    return out


def assign_sample_label(rec: SimRecord, st, *, max_turns: int) -> str | None:
    """Classify into negative / to_optimize / positive; None = skip."""
    violations = validate_log(st)

    if violations:
        return LABEL_NEGATIVE

    if rec.goal and rec.final_turn <= 2:
        return LABEL_POSITIVE

    if rec.goal and rec.final_turn >= 3:
        return LABEL_TO_OPTIMIZE

    if not rec.goal and rec.final_turn >= max_turns:
        return LABEL_NEGATIVE

    return None


def _category_detail(label: str, rec: SimRecord) -> str:
    if label == LABEL_POSITIVE:
        return f"CLEAN_T{rec.final_turn}"
    if label == LABEL_TO_OPTIMIZE:
        return f"SLOW_T{rec.final_turn}"
    return f"FAIL_T5_{rec.miss_class}"


def _quota_split(export_limit: int) -> tuple[int, int, int]:
    total_parts = sum(RATIO)
    n_neg = export_limit * RATIO[0] // total_parts
    n_opt = export_limit * RATIO[1] // total_parts
    n_pos = export_limit - n_neg - n_opt
    return n_neg, n_opt, n_pos


def _stratified_pick(
    pools: dict[str, list[tuple[HardCase, SimRecord, object]]],
    export_limit: int,
    rng: random.Random,
) -> list[tuple[HardCase, SimRecord, object]]:
    n_neg, n_opt, n_pos = _quota_split(export_limit)
    quotas = {
        LABEL_NEGATIVE: n_neg,
        LABEL_TO_OPTIMIZE: n_opt,
        LABEL_POSITIVE: n_pos,
    }
    selected: list[tuple[HardCase, SimRecord, object]] = []
    seen_seeds: set[int] = set()

    def _take_from(label: str, count: int) -> int:
        taken = 0
        bucket = list(pools.get(label, []))
        rng.shuffle(bucket)
        for item in bucket:
            if taken >= count:
                break
            seed = item[0].seed
            if seed in seen_seeds:
                continue
            selected.append(item)
            seen_seeds.add(seed)
            taken += 1
        return count - taken

    for label in (LABEL_NEGATIVE, LABEL_TO_OPTIMIZE, LABEL_POSITIVE):
        shortfall = _take_from(label, quotas[label])
        if shortfall > 0 and label == LABEL_TO_OPTIMIZE:
            _take_from(LABEL_NEGATIVE, shortfall)
        elif shortfall > 0 and label == LABEL_POSITIVE:
            _take_from(LABEL_TO_OPTIMIZE, shortfall)
            if len(selected) < export_limit:
                _take_from(LABEL_NEGATIVE, export_limit - len(selected))

    return selected[:export_limit]


def run_batch_and_filter(
    n: int,
    *,
    seed_base: int = 0,
    max_turns: int = 5,
    export_limit: int = 110,
    export_dir: Path | None = None,
    sample_seed: int = 0,
) -> dict:
    deck_path = ROOT / "data" / "decks" / "starmie_froslass.csv"
    base = load_deck_csv(deck_path)
    export_dir = export_dir or LOG_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir.mkdir(parents=True, exist_ok=True)

    pools: dict[str, list[tuple[HardCase, SimRecord, object]]] = {
        LABEL_NEGATIVE: [],
        LABEL_TO_OPTIMIZE: [],
        LABEL_POSITIVE: [],
    }
    skipped = 0
    pool_counts: dict[str, int] = {k: 0 for k in pools}

    for i in range(n):
        seed = seed_base + i
        rec = SimRecord(
            seed=seed,
            prizes=[],
            opening_hand=[],
            mulligans=0,
            setup=SetupRecord(),
            turns=[],
            routes=[],
            goal=False,
            miss_class="",
            final_turn=0,
        )
        st = simulate_opening(
            base,
            shuffle=True,
            seed=seed,
            verbose=False,
            max_turns=max_turns,
            record=rec,
        )
        label = assign_sample_label(rec, st, max_turns=max_turns)
        if label is None:
            skipped += 1
            continue
        violations = validate_log(st)
        blocked = dedupe_blocked_notes(_blocked_notes(st))
        hc = HardCase(
            seed=seed,
            sample_label=label,
            category=_category_detail(label, rec),
            goal=rec.goal,
            miss_class=rec.miss_class,
            final_turn=rec.final_turn,
            archetype=st.setup_archetype,
            violations=violations,
            blocked_notes=blocked[:4],
            routes=list(rec.routes),
        )
        pools[label].append((hc, rec, st))
        pool_counts[label] += 1

    rng = random.Random(sample_seed)
    selected = _stratified_pick(pools, export_limit, rng)
    n_neg, n_opt, n_pos = _quota_split(export_limit)

    manifest = []
    exported_counts: dict[str, int] = {k: 0 for k in pools}
    for hc, rec, _st in selected:
        body = export_sim_record(rec, run_index=hc.seed)
        label_cn = {
            LABEL_NEGATIVE: "负面样本",
            LABEL_TO_OPTIMIZE: "待优化样本",
            LABEL_POSITIVE: "正面样本",
        }[hc.sample_label]
        header = [
            f"// SAMPLE_LABEL={hc.sample_label} ({label_cn})",
            f"// category={hc.category} seed={hc.seed} archetype={hc.archetype}",
            f"// goal={hc.goal} miss={hc.miss_class} final_turn={hc.final_turn}",
            f"// routes={' → '.join(hc.routes) or '—'}",
        ]
        if hc.violations:
            header.append("// VIOLATIONS:")
            header.extend(f"//   - {v}" for v in hc.violations[:12])
        if hc.blocked_notes:
            header.append("// 拦截摘要:")
            header.extend(f"//   - {n}" for n in hc.blocked_notes[:4])
        header.append("// 专家纠错请在本局关键步骤后追加: // [CORRECT: 动作描述]")
        header.append("")
        out_path = export_dir / hc.filename
        out_path.write_text("\n".join(header) + body, encoding="utf-8")
        manifest.append(asdict(hc))
        exported_counts[hc.sample_label] += 1

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_runs": n,
        "seed_base": seed_base,
        "max_turns": max_turns,
        "export_limit": export_limit,
        "ratio": "7:3:1 (negative:to_optimize:positive)",
        "quota_target": {"negative": n_neg, "to_optimize": n_opt, "positive": n_pos},
        "skipped_unclassified": skipped,
        "pool_counts": pool_counts,
        "exported": len(selected),
        "exported_counts": exported_counts,
        "export_dir": str(export_dir),
    }

    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"summary": summary, "cases": manifest}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="OPENING stratified hard-case export (7:3:1)")
    p.add_argument("--games", type=int, default=2000)
    p.add_argument("--seed-base", type=int, default=0)
    p.add_argument("--max-turns", type=int, default=5)
    p.add_argument("--export-limit", type=int, default=110, help="Total export; split 7:3:1")
    p.add_argument("--sample-seed", type=int, default=0, help="RNG for stratified pick")
    p.add_argument("--out", type=str, default="")
    args = p.parse_args()

    out = Path(args.out) if args.out else None
    summary = run_batch_and_filter(
        args.games,
        seed_base=args.seed_base,
        max_turns=args.max_turns,
        export_limit=args.export_limit,
        export_dir=out,
        sample_seed=args.sample_seed,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nExported {summary['exported']} logs -> {summary['export_dir']}")


if __name__ == "__main__":
    main()
