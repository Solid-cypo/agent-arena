#!/usr/bin/env python3
"""Generate an expert-review pack that fills route/kind/archetype gaps.

Unlike generate_approved_high_depth (depth-quota only), this scorer:
  - Caps already-saturated routes (e.g. GREEDY-T1 → GREEDY-T2)
  - Boosts rare route prefixes (PAD / POFFIN / LILLIE / WATER / REC-F / FAN→…)
  - Boosts sparse acquisition methods (Crispin / Judge / Night Stretcher /
    Salvatore / Ultra Ball / Lillie / Pad / Poffin)
  - Boosts under-represented archetypes (F1 / E1 / A* / X1)

Output layout matches review_batch_30/31 for expert handoff.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
import sys
import tarfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
REVIEW_ROOT = SCRIPTS.parent / "logs" / "review_manual"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generate_approved_high_depth import (  # noqa: E402
    TIER_NAMES,
    existing_exclude_seeds,
    scan_candidates,
    write_pack,
)

# Gold-header route counts (approx from expert_gold_v1) — used as soft priors.
# Anything ≥10 is "saturated"; we hard-cap how many we keep.
# Exact route strings already flooded in gold — hard cap in this pack.
SATURATED_ROUTES = {
    "GREEDY-T1 → GREEDY-T2": 1,
    "MEOWTH-T1 → GREEDY-T2": 2,
    "FAN-T1 → GREEDY-T2": 3,
    "GREEDY-T1 → GREEDY-T2 → GREEDY-T2": 1,
    "R1-T1 → GREEDY-T2": 2,
}

# Route FAMILY quotas — primary diversity lever (planner rarely emits LILLIE/REC-F).
# Order = fill priority. Caps sized for a 30-pack (20 high + 10 low).
FAMILY_QUOTAS: list[tuple[str, int]] = [
    ("PAD", 5),
    ("POFFIN", 6),
    ("FAN", 4),
    ("BENCH", 3),
    ("WATER", 5),
    ("MEOWTH", 4),
    ("R1", 3),
]

# Per-method caps so Crispin/WATER don't monopolise every slot.
METHOD_CAPS = {
    "TRAINER:1198": 5,   # Crispin — gold only has 4 slices; need some, not all 30
    "TRAINER:1225": 8,   # Hilda
    "TRAINER:1121": 10,  # Ultra Ball
    "TRAINER:1152": 10,  # Pad
    "TRAINER:1086": 10,  # Poffin
}

SPARSE_METHODS = {
    "TRAINER:1198": 5.0,
    "TRAINER:1189": 6.0,
    "TRAINER:1121": 3.0,
    "TRAINER:1227": 4.0,
    "TRAINER:1152": 2.5,
    "TRAINER:1086": 2.5,
    "TRAINER:1225": 1.5,
    "ABILITY_LAST_DITCH": 4.0,
    "ABILITY_FAN_CALL": 2.0,
    "ABILITY_RUN_AWAY": 1.5,
}

ARCH_BOOST = {"F1": 4.0, "E1": 3.0, "A1": 2.0, "A2": 2.5, "X1": 2.0, "S1": 0.5, "C1": 0.5, "B1": 0.0}


def route_key(c: dict) -> str:
    return " → ".join(c.get("routes") or []) or "?"


def route_family(rk: str) -> str:
    """Single primary family label for quota accounting."""
    if "PAD-T" in rk:
        return "PAD"
    if "POFFIN-T" in rk:
        return "POFFIN"
    if "FAN-T" in rk:
        return "FAN"
    if "BENCH-T" in rk:
        return "BENCH"
    if "WATER-T" in rk:
        return "WATER"
    if "MEOWTH" in rk:
        return "MEOWTH"
    if "R1-T" in rk:
        return "R1"
    if "LILLIE" in rk:
        return "LILLIE"
    if "REC-F" in rk:
        return "REC"
    if "G-BRIDGE" in rk:
        return "BRIDGE"
    if rk == "GREEDY-T1 → GREEDY-T2" or rk.startswith("GREEDY-T1 → GREEDY-T2 → GREEDY"):
        return "GREEDY_SAT"
    return "OTHER"


def gap_score(c: dict) -> float:
    score = 0.0
    rk = route_key(c)
    fam = route_family(rk)
    # Family rarity prior (planner-available families)
    fam_w = {
        "PAD": 10, "POFFIN": 8, "FAN": 9, "BENCH": 11, "WATER": 6,
        "LILLIE": 12, "REC": 12, "BRIDGE": 11, "MEOWTH": 3, "R1": 2,
        "OTHER": 1, "GREEDY_SAT": -10,
    }
    score += fam_w.get(fam, 0)
    for m in c.get("methods") or []:
        score += SPARSE_METHODS.get(m, 0.3)
    score += 0.5 * len(c.get("methods") or [])
    score += 0.8 * max(0, c.get("tier", 1) - 2)
    score += ARCH_BOOST.get(c.get("archetype", ""), 0.0)
    # Prefer Salvatore / Last-Ditch / Lillie method when present
    methods = set(c.get("methods") or [])
    if "TRAINER:1189" in methods:
        score += 4.0
    if "ABILITY_LAST_DITCH" in methods:
        score += 3.0
    if "TRAINER:1227" in methods:
        score += 3.0
    return score


def select_gap_fill(
    cands: list[dict],
    *,
    n_high: int,
    n_low: int,
    rng: random.Random,
) -> list[dict]:
    """Fill by route-family quotas first, then top-up by gap_score."""
    for c in cands:
        c["_gap"] = gap_score(c)
        c["_fam"] = route_family(route_key(c))

    def assign_band(c: dict) -> str:
        return "high" if c["tier"] >= 3 else "low"

    # Bucket by family
    by_fam: dict[str, list[dict]] = defaultdict(list)
    for c in cands:
        by_fam[c["_fam"]].append(c)
    for fam in by_fam:
        rng.shuffle(by_fam[fam])
        by_fam[fam].sort(key=lambda c: c["_gap"], reverse=True)

    picked: list[dict] = []
    have: set[int] = set()
    route_counts: Counter[str] = Counter()
    fam_counts: Counter[str] = Counter()
    method_counts: Counter[str] = Counter()
    n_high_have = 0
    n_low_have = 0

    def can_add(c: dict) -> bool:
        nonlocal n_high_have, n_low_have
        if c["seed"] in have:
            return False
        band = assign_band(c)
        if band == "high" and n_high_have >= n_high:
            return False
        if band == "low" and n_low_have >= n_low:
            return False
        rk = route_key(c)
        if route_counts[rk] >= SATURATED_ROUTES.get(rk, 4):
            return False
        # method caps
        for m in c.get("methods") or []:
            if method_counts[m] >= METHOD_CAPS.get(m, 99):
                return False
        return True

    def add(c: dict) -> None:
        nonlocal n_high_have, n_low_have
        c = dict(c)
        c["band"] = assign_band(c)
        picked.append(c)
        have.add(c["seed"])
        route_counts[route_key(c)] += 1
        fam_counts[c["_fam"]] += 1
        for m in c.get("methods") or []:
            method_counts[m] += 1
        if c["band"] == "high":
            n_high_have += 1
        else:
            n_low_have += 1

    # Pass 1: family quotas
    for fam, quota in FAMILY_QUOTAS:
        for c in by_fam.get(fam, []):
            if fam_counts[fam] >= quota:
                break
            if can_add(c):
                add(c)

    # Pass 2: top-up remaining high/low slots from non-saturated families
    rest = [c for c in cands if c["seed"] not in have and c["_fam"] != "GREEDY_SAT"]
    rng.shuffle(rest)
    rest.sort(key=lambda c: c["_gap"], reverse=True)
    for c in rest:
        if n_high_have >= n_high and n_low_have >= n_low:
            break
        # Keep family from exploding past quota+2
        fam = c["_fam"]
        fam_cap = dict(FAMILY_QUOTAS).get(fam, 3) + 2
        if fam_counts[fam] >= fam_cap:
            continue
        if can_add(c):
            add(c)

    # Pass 3: if still short, allow GREEDY_SAT minimally
    if n_high_have < n_high or n_low_have < n_low:
        for c in sorted(
            (x for x in cands if x["seed"] not in have),
            key=lambda x: x["_gap"],
            reverse=True,
        ):
            if n_high_have >= n_high and n_low_have >= n_low:
                break
            if can_add(c):
                add(c)

    # Stable order: high then low, each by gap desc
    picked.sort(key=lambda c: (0 if c["band"] == "high" else 1, -c["_gap"]))
    return picked


def write_checklist(out_dir: Path, manifest: list[dict]) -> None:
    rows = []
    for c in manifest:
        rows.append(
            {
                "file": c["file"],
                "seed": c["seed"],
                "band": c["band"],
                "difficulty": c["difficulty"],
                "role": "先攻" if c["going_first"] else "后攻",
                "archetype": c["archetype"],
                "final_turn": c["final_turn"],
                "n_methods": c["n_methods"],
                "methods": "|".join(c["methods"]),
                "routes": " → ".join(c["routes"]) if c["routes"] else "",
                "gap_score": f"{c.get('_gap', 0):.1f}",
                "expert_verdict": "",
                "expert_note": "",
            }
        )
    fields = list(rows[0].keys()) if rows else []
    with (out_dir / "REVIEW_CHECKLIST.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-start", type=int, default=39000)
    ap.add_argument("--seed-end", type=int, default=48000)
    ap.add_argument("--n-high", type=int, default=20)
    ap.add_argument("--n-low", type=int, default=10)
    ap.add_argument("--pack", default="review_batch_32_gap")
    ap.add_argument("--sample-seed", type=int, default=20260710)
    args = ap.parse_args()

    deck_path = ROOT / "data" / "decks" / "starmie_froslass.csv"
    if not deck_path.exists():
        deck_path = ROOT / "submission_starmie" / "deck.csv"
    from arena.deck import load_deck_csv

    deck = load_deck_csv(deck_path)
    exclude = existing_exclude_seeds()
    # Also exclude batch_31 seeds so we don't re-ask the same deals
    b31 = REVIEW_ROOT / "approved_review_batch_31"
    if b31.exists():
        import re

        for p in b31.glob("*.log"):
            m = re.search(r"seed[=_]?(\d+)", p.name)
            if m:
                exclude.add(int(m.group(1)))

    print(
        f"deck={len(deck)} exclude={len(exclude)} "
        f"scan=[{args.seed_start},{args.seed_end})"
    )
    cands = scan_candidates(
        deck,
        seed_start=args.seed_start,
        seed_end=args.seed_end,
        exclude=exclude,
        min_tier=1,
    )
    by = Counter(c["tier"] for c in cands)
    print(f"candidates by tier: {dict(sorted(by.items()))} total={len(cands)}")

    rng = random.Random(args.sample_seed)
    selected = select_gap_fill(
        cands, n_high=args.n_high, n_low=args.n_low, rng=rng
    )
    print(f"selected {len(selected)} (high={sum(1 for c in selected if c['band']=='high')}, "
          f"low={sum(1 for c in selected if c['band']=='low')})")

    # Coverage report
    rc = Counter(route_key(c) for c in selected)
    mc = Counter(m for c in selected for m in c["methods"])
    ac = Counter(c["archetype"] for c in selected)
    print("routes:")
    for r, n in rc.most_common():
        print(f"  {n:2d}  {r}")
    print("methods:", dict(mc.most_common()))
    print("archetypes:", dict(ac.most_common()))
    print("gap_score range:",
          f"{min(c['_gap'] for c in selected):.1f} .. {max(c['_gap'] for c in selected):.1f}")

    out_dir = REVIEW_ROOT / f"approved_{args.pack}"
    traj_path = ROOT / "data" / "opening_sft" / f"traj_{args.pack}.jsonl"
    manifest = write_pack(
        selected, out_dir=out_dir, pack=args.pack, traj_path=traj_path, mixed=True
    )
    # Attach gap scores into manifest cases
    seed_gap = {c["seed"]: c["_gap"] for c in selected}
    for row in manifest:
        row["_gap"] = seed_gap.get(row["seed"], 0.0)

    # Annotate README with gap-fill intent
    readme = out_dir / "README_专家审阅.md"
    fam_summary = Counter(route_family(route_key(c)) for c in selected)
    extra = f"""
## 本包采样目标（缺口补齐 / 多路线覆盖）

`expert_gold_v1` 里 **39/128** 已是 `GREEDY-T1 → GREEDY-T2`；batch_31 又采了 15 条同路线 —— **无效补洞**。
本包按 **路线族配额** 强制分散（实际族分布：{dict(fam_summary)}）：

| 族 | 配额意图 | 说明 |
|----|----------|------|
| PAD / POFFIN / FAN / BENCH / WATER | 优先填满 | gold 里各只有个位数 |
| MEOWTH / R1 | 少量 | 避免再灌饱和 GREEDY |
| LILLIE / REC-F | — | **planner approved 采不到**；需专家 CORRECT 改写或另开 edited 包 |

同时限制 Crispin 等方法扎堆（METHOD_CAPS），并抬升 Salvatore / Last-Ditch / Lillie 方法权重。

生成时间：{datetime.now().isoformat(timespec='seconds')}
"""
    readme.write_text(readme.read_text(encoding="utf-8").rstrip() + "\n" + extra, encoding="utf-8")
    write_checklist(out_dir, manifest)

    mirror = SCRIPTS.parent / f"approved_{args.pack}"
    if mirror.resolve() != out_dir.resolve():
        if mirror.exists():
            shutil.rmtree(mirror)
        shutil.copytree(out_dir, mirror)

    tar_path = ROOT / "data" / "opening_sft" / f"expert_review_pack_{args.pack}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for p in sorted(out_dir.iterdir()):
            tar.add(p, arcname=f"approved_{args.pack}/{p.name}")
    print(f"wrote {len(manifest)} → {out_dir}")
    print(f"mirror → {mirror}")
    print(f"pack → {tar_path}")
    for r in manifest:
        print(
            f"  [{r['index']:02d}] gap={seed_gap.get(r['seed'],0):5.1f} "
            f"{r['file']} :: {' → '.join(r['routes'])}"
        )


if __name__ == "__main__":
    main()
