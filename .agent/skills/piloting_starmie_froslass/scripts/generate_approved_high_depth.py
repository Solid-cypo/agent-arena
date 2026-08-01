#!/usr/bin/env python3
"""Generate high-depth (T3/T4) approved OPENING logs for expert review.

Difficulty = DISTINCT acquisition-method chain depth (not turn count):
  T1 (1): one direct search
  T2 (2): ability-into-search
  T3 (3): ball/double-chain
  T4 (4+): Run Away draw chain or any ≥4-method chain
Pure ATTACH / RETREAT / EVOLVE-from-hand / PLACE do not count.
See references/decompiled/build_approved_supplement.py.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tarfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[3]
REVIEW_ROOT = SCRIPTS.parent / "logs" / "review_manual"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena.deck import load_deck_csv  # noqa: E402
from opening_cards import (  # noqa: E402
    BOSS_ORDERS,
    JUDGE,
    SUPPORTER_IDS,
    SWITCH,
)
from opening_log_formatter import card_names_zh, format_log_text  # noqa: E402
from opening_validate import validate_log  # noqa: E402
from simulate_opening import (  # noqa: E402
    SetupRecord,
    SimRecord,
    export_sim_record,
    simulate_opening,
)

_ACQ_ABILITY = frozenset({"ABILITY_FAN_CALL", "ABILITY_RUN_AWAY", "ABILITY_LAST_DITCH"})
_UTILITY_TRAINERS = frozenset({SWITCH, JUDGE, BOSS_ORDERS})
TIER_NAMES = {1: "T1", 2: "T2", 3: "T3", 4: "T4"}


def going_first_for_seed(seed: int) -> bool:
    return seed % 2 == 0


def turn_limit_for_seed(seed: int) -> tuple[bool, int]:
    """先攻最多 My-T3，后攻最多 My-T2（对齐 expert_gold_v1）。"""
    gf = going_first_for_seed(seed)
    return gf, (3 if gf else 2)


def difficulty_tier_from_log(log) -> int:
    cats: set = set()
    runaway = False
    for a in log:
        k = a.kind
        cid = a.card_id
        if k in _ACQ_ABILITY:
            cats.add(k)
            if k == "ABILITY_RUN_AWAY":
                runaway = True
            continue
        if k == "PLAY_TRAINER" and cid is not None and cid not in _UTILITY_TRAINERS:
            cats.add(("TRAINER", cid))
    eff = len(cats) + (1 if runaway else 0)
    return min(max(eff, 1), 4)


def acquisition_methods(log) -> list[str]:
    seen: list[str] = []
    for a in log:
        if a.kind in _ACQ_ABILITY:
            tag = a.kind
            if tag not in seen:
                seen.append(tag)
        elif a.kind == "PLAY_TRAINER" and a.card_id is not None and a.card_id not in _UTILITY_TRAINERS:
            tag = f"TRAINER:{a.card_id}"
            if tag not in seen:
                seen.append(tag)
    return seen


def has_going_first_t1_supporter(st) -> bool:
    if not st.going_first:
        return False
    cur_t = 0
    for a in st.log:
        if a.kind == "NOTE" and a.detail.startswith("T") and "gaps=" in a.detail:
            try:
                cur_t = int(a.detail.split()[0][1:])
            except Exception:
                pass
        if a.kind == "PLAY_TRAINER" and a.card_id in SUPPORTER_IDS and cur_t == 1:
            return True
    return False


def existing_exclude_seeds() -> set[int]:
    seeds: set[int] = set()
    import re

    folders = [
        REVIEW_ROOT / "expert_gold_v1",
        REVIEW_ROOT / "expert_gold_v1_approved",
        REVIEW_ROOT / "approved_deck_top10",
        REVIEW_ROOT / "approved_high_depth_20",
        REVIEW_ROOT / "approved_review_batch_30",
        SCRIPTS.parent / "approved_review_batch_30",
    ]
    # Any prior approved_* packs under review_manual
    if REVIEW_ROOT.exists():
        folders.extend(sorted(REVIEW_ROOT.glob("approved_*")))
    seen_dirs: set[Path] = set()
    for folder in folders:
        folder = folder.resolve()
        if folder in seen_dirs or not folder.exists():
            continue
        seen_dirs.add(folder)
        for p in folder.rglob("*.log"):
            m = re.search(r"seed[=_]?(\d+)", p.name)
            if m:
                seeds.add(int(m.group(1)))
            try:
                for line in p.read_text(encoding="utf-8").splitlines()[:20]:
                    m2 = re.search(r"seed=(\d+)", line)
                    if m2:
                        seeds.add(int(m2.group(1)))
            except Exception:
                pass
    return seeds


def _build_header(
    *,
    seed: int,
    final_turn: int,
    archetype: str,
    miss_class: str,
    routes: list[str],
    tier: int,
    idx: int,
    pack: str,
) -> list[str]:
    going_first, turn_limit = turn_limit_for_seed(seed)
    role = "先攻" if going_first else "后攻"
    route_s = " → ".join(routes) if routes else "—"
    return [
        "// expert_status=approved",
        f"// difficulty={TIER_NAMES[tier]}",
        f"// PACK={pack} INDEX={idx}",
        "// 样本类型=正面",
        f"// category=CLEAN_T{final_turn} seed={seed} archetype={archetype}",
        f"// role={role} turn_limit={turn_limit}",
        f"// goal=True miss={miss_class} final_turn={final_turn}",
        f"// routes={route_s}",
        "// 专家：positive 路线 OK，步骤无需修改；通读无误即保留 approved",
        "// 勿改起始区/回合快照；勿用 CORRECT 注释",
        "",
    ]


def scan_candidates(
    deck: list[int],
    *,
    seed_start: int,
    seed_end: int,
    exclude: set[int],
    min_tier: int = 3,
) -> list[dict]:
    out: list[dict] = []
    for seed in range(seed_start, seed_end):
        if seed in exclude:
            continue
        gf, _ = turn_limit_for_seed(seed)
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
            deck,
            going_first=gf,
            verbose=False,
            max_turns=5,
            shuffle=True,
            seed=seed,
            record=rec,
        )
        _, turn_limit = turn_limit_for_seed(seed)
        if not rec.goal or rec.final_turn > turn_limit:
            continue
        viol = validate_log(st)
        if viol:
            continue
        if has_going_first_t1_supporter(st):
            continue
        tier = difficulty_tier_from_log(st.log)
        if tier < min_tier:
            continue
        out.append(
            {
                "seed": seed,
                "tier": tier,
                "final_turn": rec.final_turn,
                "archetype": st.setup_archetype,
                "miss_class": rec.miss_class,
                "routes": list(rec.routes),
                "methods": acquisition_methods(st.log),
                "going_first": gf,
                "rec": rec,
                "st": st,
            }
        )
    return out


def pick_quota(
    cands: list[dict],
    *,
    n_total: int,
    n_t4: int,
    rng: random.Random,
) -> list[dict]:
    by_tier: dict[int, list[dict]] = defaultdict(list)
    for c in cands:
        by_tier[c["tier"]].append(c)
    for t in by_tier:
        rng.shuffle(by_tier[t])
    n_t4 = min(n_t4, n_total, len(by_tier[4]))
    n_t3 = min(n_total - n_t4, len(by_tier[3]))
    # If T3 short, fill from remaining T4
    picked = by_tier[4][:n_t4] + by_tier[3][:n_t3]
    need = n_total - len(picked)
    if need > 0:
        rest = by_tier[4][n_t4:] + by_tier[3][n_t3:]
        picked.extend(rest[:need])
    # Prefer higher method-count within tier
    picked.sort(key=lambda c: (c["tier"], len(c["methods"]), -c["seed"]), reverse=True)
    return picked[:n_total]


def pick_low_quota(
    cands: list[dict],
    *,
    n_total: int,
    n_t1: int,
    rng: random.Random,
) -> list[dict]:
    """Pick T1/T2 clean goals (low depth), preferring T2 then T1."""
    by_tier: dict[int, list[dict]] = defaultdict(list)
    for c in cands:
        if c["tier"] in (1, 2):
            by_tier[c["tier"]].append(c)
    for t in by_tier:
        rng.shuffle(by_tier[t])
    n_t1 = min(n_t1, n_total, len(by_tier[1]))
    n_t2 = min(n_total - n_t1, len(by_tier[2]))
    picked = by_tier[2][:n_t2] + by_tier[1][:n_t1]
    need = n_total - len(picked)
    if need > 0:
        rest = by_tier[2][n_t2:] + by_tier[1][n_t1:]
        picked.extend(rest[:need])
    picked.sort(key=lambda c: (c["tier"], len(c["methods"]), -c["seed"]), reverse=True)
    return picked[:n_total]


def write_pack(
    selected: list[dict],
    *,
    out_dir: Path,
    pack: str,
    traj_path: Path,
    mixed: bool = False,
) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.log"):
        old.unlink()
    manifest: list[dict] = []
    traj_lines: list[str] = []
    for idx, c in enumerate(selected, 1):
        seed = c["seed"]
        tier = c["tier"]
        band = c.get("band") or ("high" if tier >= 3 else "low")
        header = _build_header(
            seed=seed,
            final_turn=c["final_turn"],
            archetype=c["archetype"],
            miss_class=c["miss_class"],
            routes=c["routes"],
            tier=tier,
            idx=idx,
            pack=pack,
        )
        body = export_sim_record(c["rec"], run_index=idx)
        text = "\n".join(header) + body
        text = format_log_text(card_names_zh(text))
        if mixed:
            fname = f"{band}_seed{seed}_{TIER_NAMES[tier]}_approved.log"
        else:
            fname = f"seed{seed}_{TIER_NAMES[tier]}_approved.log"
        (out_dir / fname).write_text(text, encoding="utf-8")
        row = {
            "index": idx,
            "file": fname,
            "seed": seed,
            "band": band,
            "difficulty": TIER_NAMES[tier],
            "tier": tier,
            "final_turn": c["final_turn"],
            "archetype": c["archetype"],
            "going_first": c["going_first"],
            "routes": c["routes"],
            "methods": c["methods"],
            "n_methods": len(c["methods"]),
        }
        manifest.append(row)
        # Lightweight traj stub for ingest (steps filled by separate ingest if needed)
        traj_lines.append(
            json.dumps(
                {
                    "seed": seed,
                    "going_first": c["going_first"],
                    "turn_limit": 3 if c["going_first"] else 2,
                    "source": "approved_sim",
                    "expert_status": "approved",
                    "sample_label": "positive",
                    "archetype": c["archetype"],
                    "difficulty": TIER_NAMES[tier],
                    "band": band,
                    "category": f"CLEAN_T{c['final_turn']}",
                    "goal_reached": True,
                    "routes": c["routes"],
                    "methods": c["methods"],
                    "log_file": str(out_dir / fname),
                },
                ensure_ascii=False,
            )
        )
    n_high = sum(1 for r in manifest if r["tier"] >= 3)
    n_low = sum(1 for r in manifest if r["tier"] < 3)
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "pack": pack,
                "n": len(manifest),
                "n_high": n_high,
                "n_low": n_low,
                "theory": "DISTINCT acquisition-method chain depth (T1–T4)",
                "cases": manifest,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    high_rows = [r for r in manifest if r["tier"] >= 3]
    low_rows = [r for r in manifest if r["tier"] < 3]
    title = (
        f"# {pack} — 专家审查包（{n_high} 高深度 + {n_low} 低深度）"
        if mixed
        else f"# {pack} — 高深度 APPROVED 审查包"
    )
    readme_lines = [
        title,
        "",
        "## 难度理论（route depth，非回合数）",
        "- **高深度**：T3/T4（≥3 种获取手段，或含 Run Away +1）",
        "- **低深度**：T1/T2（1–2 种获取手段）",
        "- ATTACH / RETREAT / 手牌进化 / 放置 **不计** 深度",
        "",
        f"全部 `goal=True` 且 `final_turn≤turn_limit`（先攻≤3 / 后攻≤2）、无规则违规。",
        "专家通读无误 → 保留 `approved`；需改 → 直接改正文并改 `expert_status=edited`。",
        "",
    ]
    if high_rows:
        readme_lines += [f"## 高深度（{len(high_rows)}）", ""]
        readme_lines += [
            f"- `{r['file']}` · {r['difficulty']} · methods={r['n_methods']} · "
            f"{'先攻' if r['going_first'] else '后攻'} · arch={r['archetype']}"
            for r in high_rows
        ]
        readme_lines.append("")
    if low_rows:
        readme_lines += [f"## 低深度（{len(low_rows)}）", ""]
        readme_lines += [
            f"- `{r['file']}` · {r['difficulty']} · methods={r['n_methods']} · "
            f"{'先攻' if r['going_first'] else '后攻'} · arch={r['archetype']}"
            for r in low_rows
        ]
        readme_lines.append("")
    elif not mixed:
        readme_lines += [
            "## 清单",
            "",
        ] + [
            f"- `{r['file']}` · {r['difficulty']} · methods={r['n_methods']} · "
            f"{'先攻' if r['going_first'] else '后攻'} · arch={r['archetype']}"
            for r in manifest
        ] + [""]
    (out_dir / "README_专家审阅.md").write_text("\n".join(readme_lines), encoding="utf-8")
    traj_path.parent.mkdir(parents=True, exist_ok=True)
    traj_path.write_text("\n".join(traj_lines) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-start", type=int, default=28000)
    ap.add_argument("--seed-end", type=int, default=32000)
    ap.add_argument("--n", type=int, default=20, help="High-depth (T3/T4) count")
    ap.add_argument("--n-t4", type=int, default=12, help="Prefer this many T4 among high")
    ap.add_argument("--n-low", type=int, default=0, help="Low-depth (T1/T2) count")
    ap.add_argument("--n-t1", type=int, default=4, help="Prefer this many T1 among low")
    ap.add_argument("--pack", default="high_depth_20")
    ap.add_argument("--sample-seed", type=int, default=20260709)
    args = ap.parse_args()

    deck_path = ROOT / "data" / "decks" / "starmie_froslass.csv"
    if not deck_path.exists():
        deck_path = ROOT / "submission_starmie" / "deck.csv"
    deck = load_deck_csv(deck_path)
    exclude = existing_exclude_seeds()
    print(f"deck={len(deck)} exclude_seeds={len(exclude)} scan=[{args.seed_start},{args.seed_end})")

    # Single pass: min_tier=1 when low band requested, else high-only.
    scan_min = 1 if args.n_low > 0 else 3
    all_cands = scan_candidates(
        deck,
        seed_start=args.seed_start,
        seed_end=args.seed_end,
        exclude=exclude,
        min_tier=scan_min,
    )
    by = defaultdict(int)
    for c in all_cands:
        by[c["tier"]] += 1
    print(
        f"candidates T1={by[1]} T2={by[2]} T3={by[3]} T4={by[4]} total={len(all_cands)}"
    )

    rng = random.Random(args.sample_seed)
    high_cands = [c for c in all_cands if c["tier"] >= 3]
    selected = pick_quota(high_cands, n_total=args.n, n_t4=args.n_t4, rng=rng)
    for c in selected:
        c["band"] = "high"
    if len(selected) < args.n:
        print(f"WARN: only {len(selected)}/{args.n} high-depth clean goals found")

    if args.n_low > 0:
        used = {c["seed"] for c in selected}
        low_pool = [c for c in all_cands if c["tier"] <= 2 and c["seed"] not in used]
        by_l = defaultdict(int)
        for c in low_pool:
            by_l[c["tier"]] += 1
        print(f"low pool T1={by_l[1]} T2={by_l[2]} total={len(low_pool)}")
        low_sel = pick_low_quota(low_pool, n_total=args.n_low, n_t1=args.n_t1, rng=rng)
        for c in low_sel:
            c["band"] = "low"
        if len(low_sel) < args.n_low:
            print(f"WARN: only {len(low_sel)}/{args.n_low} low-depth clean goals found")
        selected = selected + low_sel

    mixed = args.n_low > 0
    out_dir = REVIEW_ROOT / f"approved_{args.pack}"
    # Also mirror under skill root for expert drop-off (same as batch_30)
    mirror = SCRIPTS.parent / f"approved_{args.pack}"
    traj_path = ROOT / "data" / "opening_sft" / f"traj_{args.pack}.jsonl"
    manifest = write_pack(
        selected, out_dir=out_dir, pack=args.pack, traj_path=traj_path, mixed=mixed
    )
    if mirror.resolve() != out_dir.resolve():
        if mirror.exists():
            import shutil

            shutil.rmtree(mirror)
        import shutil

        shutil.copytree(out_dir, mirror)

    tar_path = ROOT / "data" / "opening_sft" / f"expert_review_pack_{args.pack}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for p in sorted(out_dir.iterdir()):
            tar.add(p, arcname=f"approved_{args.pack}/{p.name}")
    print(f"wrote {len(manifest)} logs → {out_dir}")
    print(f"mirror → {mirror}")
    print(f"traj → {traj_path}")
    print(f"pack → {tar_path}")
    for r in manifest:
        print(
            f"  [{r['index']:02d}] {r['file']} methods={r['n_methods']} "
            f"{r['methods']}"
        )


if __name__ == "__main__":
    main()
