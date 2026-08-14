#!/usr/bin/env python3
"""Mirror KPIs: Mega Froslass make / fire / 3-prize-KO + Opening + DP.

三奖口径（产品）：雪女出手后击杀对面三奖打手，该回合拿满 3 张奖励。
不是「我方剩余奖数 = 3」。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MEGA_F, RESENTFUL, ABS_SNOW = 861, 1240, 1241
DEFAULT_TAGS = ("cutDraw66", "seatSnorunt", "froslassCont", "hildaBC")
ROOT = Path(__file__).resolve().parents[1]


def opening_hit(g: dict) -> bool:
    mega = (g.get("cur") or {}).get("mega_evo_my_t")
    if mega is None:
        return False
    return int(mega) <= (3 if g.get("cur_is_a") else 2)


def scan_plan(path: Path) -> tuple[bool, bool]:
    ever = atk = False
    for line in path.read_text().splitlines():
        obj = json.loads(line)
        cid = int(obj.get("card_or_attack_id") or 0)
        if cid == MEGA_F:
            ever = True
        if cid in (RESENTFUL, ABS_SNOW):
            atk = True
            ever = True
    return ever, atk


def prize_takes(g: dict) -> list[tuple[int, int]]:
    """(my_turn, prizes_taken) — cards taken that turn (= KO prize value)."""
    curve = g.get("prize_curve_cur") or []
    by_t: dict[int, list[int]] = {}
    for pt in curve:
        t = int(pt.get("my_turn") or 0)
        by_t.setdefault(t, []).append(int(pt.get("prize_self") or 6))
    out: list[tuple[int, int]] = []
    prev = None
    for t in sorted(by_t):
        vals = by_t[t]
        start = vals[0] if prev is None else prev
        end = vals[-1]
        delta = start - end
        if delta > 0:
            out.append((t, delta))
        prev = end
    return out


def aggregate(prefix: str) -> dict | None:
    rows: list[dict] = []
    for seed in (82000, 83000, 84000):
        man_p = ROOT / f"logs/h2h_audit_{prefix}_s{seed}_n200/manifest.json"
        if not man_p.exists():
            continue
        games = json.loads(man_p.read_text())["games"]
        games_dir = ROOT / f"logs/h2h_audit_{prefix}_s{seed}_n200/games"
        for g in games:
            i = int(g["i"])
            plan_p = games_dir / f"game_{i:03d}.plan.jsonl"
            ever = atk = False
            if plan_p.exists():
                ever, atk = scan_plan(plan_p)
            # 三奖击杀代理：雪女出手 + 同局曾单回合拿满 3 奖（击杀三奖宝可梦的奖差）
            ko3 = atk and any(d >= 3 for _, d in prize_takes(g))
            cur = g.get("cur") or {}
            mega = cur.get("mega_evo_my_t") is not None
            rows.append(
                {
                    "win": bool(g.get("cur_win")),
                    "opening": opening_hit(g),
                    "cur_is_a": bool(g.get("cur_is_a")),
                    "mega": mega,
                    "dp_seat": mega and cur.get("munk_play_my_t") is not None,
                    "dp_dark": mega and bool(cur.get("munk_dark_attach")),
                    "ever_861": ever,
                    "atk_861": atk,
                    "ko3": ko3,
                }
            )
    if not rows:
        return None
    mega_n = sum(1 for r in rows if r["mega"]) or 1

    def rate(pred, denom=None) -> float:
        xs = [r for r in rows if denom(r)] if denom else rows
        return sum(1 for r in xs if pred(r)) / len(xs) if xs else 0.0

    return {
        "n": len(rows),
        "wr": rate(lambda r: r["win"]),
        "opening": rate(lambda r: r["opening"]),
        "a_open": rate(lambda r: r["opening"], lambda r: r["cur_is_a"]),
        "b_open": rate(lambda r: r["opening"], lambda r: not r["cur_is_a"]),
        "dp_seat": sum(r["dp_seat"] for r in rows) / mega_n,
        "dp_dark": sum(r["dp_dark"] for r in rows) / mega_n,
        "ever_861": rate(lambda r: r["ever_861"]),
        "atk_861": rate(lambda r: r["atk_861"]),
        "ko3": rate(lambda r: r["ko3"]),
        "ko3_given_atk": rate(lambda r: r["ko3"], lambda r: r["atk_861"]),
        "ko3_given_861": rate(lambda r: r["ko3"], lambda r: r["ever_861"]),
        "atk_given_861": rate(lambda r: r["atk_861"], lambda r: r["ever_861"]),
        "wr_ko3": rate(lambda r: r["win"], lambda r: r["ko3"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", nargs="+", default=list(DEFAULT_TAGS))
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "logs/h2h_audit_froslass_kpi/KPI.md",
    )
    args = ap.parse_args()

    print("口径：三奖击杀 = 雪女出手后击杀对面三奖打手（该回合拿满3张奖）")
    print("不是「我方剩余奖数=3」\n")
    hdr = (
        f"{'包':<14} {'WR':>6} {'Open':>6} {'DP暗':>6} "
        f"{'做成861':>8} {'出手':>7} {'三奖击杀':>8} {'三奖|出手':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    results: dict[str, dict] = {}
    for tag in args.tags:
        a = aggregate(tag)
        if a is None:
            print(f"{tag:<14} MISSING")
            continue
        results[tag] = a
        print(
            f"{tag:<14} {a['wr']:6.1%} {a['opening']:6.1%} {a['dp_dark']:6.1%} "
            f"{a['ever_861']:8.1%} {a['atk_861']:7.1%} {a['ko3']:8.1%} "
            f"{a['ko3_given_atk']:8.1%}"
        )

    print("\n漏斗")
    print(f"{'包':<14} {'出手|做成':>8} {'三奖|做成':>8} {'WR|三奖击杀':>10}")
    for tag, a in results.items():
        print(
            f"{tag:<14} {a['atk_given_861']:8.1%} {a['ko3_given_861']:8.1%} "
            f"{a['wr_ko3']:10.1%}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 镜像 KPI — Mega 雪女 / Opening / DP",
        "",
        "## 三奖定义（已更正）",
        "",
        "**不是**「我方奖数等于 3 / 剩三奖」。",
        "**是**：Mega 雪女出手后，**击杀对面三奖打手**，该回合**拿满 3 张奖励**。",
        "",
        "测量代理：plan 有怨念/绝对零度 + 同局 `prize_curve` 存在单回合自奖减少 ≥3"
        "（击杀三奖宝可梦的奖差，非「剩三奖」）。",
        "",
        "| 包 | WR | Opening | DP暗\\|M | 做成861 | 出手861 | 三奖击杀 | 三奖\\|出手 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tag, a in results.items():
        lines.append(
            f"| {tag} | {a['wr']:.1%} | {a['opening']:.1%} | {a['dp_dark']:.1%} "
            f"| {a['ever_861']:.1%} | {a['atk_861']:.1%} | {a['ko3']:.1%} "
            f"| {a['ko3_given_atk']:.1%} |"
        )
    lines += [
        "",
        "## 漏斗",
        "",
        "| 包 | 出手\\|做成 | 三奖击杀\\|做成 | WR\\|三奖击杀 |",
        "|---|---:|---:|---:|",
    ]
    for tag, a in results.items():
        lines.append(
            f"| {tag} | {a['atk_given_861']:.1%} | {a['ko3_given_861']:.1%} "
            f"| {a['wr_ko3']:.1%} |"
        )
    lines += [
        "",
        "## Opening / DP 分项",
        "",
        "| 包 | A≤T3 | B≤T2 | DP座\\|M | DP暗\\|M |",
        "|---|---:|---:|---:|---:|",
    ]
    for tag, a in results.items():
        lines.append(
            f"| {tag} | {a['a_open']:.1%} | {a['b_open']:.1%} "
            f"| {a['dp_seat']:.1%} | {a['dp_dark']:.1%} |"
        )
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nwrote", args.out)


if __name__ == "__main__":
    main()
