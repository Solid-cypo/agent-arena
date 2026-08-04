#!/usr/bin/env python3
"""Aggregate h2h_audit manifest.json into SUMMARY.md."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def _pct(n: int, d: int) -> str:
    if d <= 0:
        return "—"
    return f"{100.0 * n / d:.1f}%"


def summarize(manifest: dict) -> str:
    games = manifest.get("games") or []
    n = len(games)
    wins = sum(1 for g in games if g.get("cur_win") is True)
    losses = sum(1 for g in games if g.get("cur_win") is False)
    draws = sum(1 for g in games if g.get("cur_win") is None)
    decided = wins + losses
    short = sum(1 for g in games if int(g.get("steps") or 0) < 40)

    seat_a = [g for g in games if g.get("cur_is_a")]
    seat_b = [g for g in games if not g.get("cur_is_a")]

    def seat_wr(rs: list) -> str:
        w = sum(1 for g in rs if g.get("cur_win") is True)
        d = sum(1 for g in rs if g.get("cur_win") is not None)
        return f"{w}/{d} ({_pct(w, d)})"

    # path_bucket × win
    bucket_win: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # win, loss
    for g in games:
        b = (g.get("cur") or {}).get("path_bucket") or "unknown"
        if g.get("cur_win") is True:
            bucket_win[b][0] += 1
        elif g.get("cur_win") is False:
            bucket_win[b][1] += 1

    losses_g = [g for g in games if g.get("cur_win") is False]
    loss_seat_b = sum(1 for g in losses_g if not g.get("cur_is_a"))
    loss_no_mega = sum(
        1 for g in losses_g if (g.get("cur") or {}).get("path_bucket") == "no_mega"
    )
    loss_mega_late = sum(
        1 for g in losses_g
        if (g.get("cur") or {}).get("path_bucket") == "mega_late_>6"
    )
    loss_mega_gap = sum(
        1 for g in losses_g
        if (g.get("cur") or {}).get("mega_gap") is not None
        and int((g.get("cur") or {}).get("mega_gap") or 0) > 0
    )
    loss_evo_no_atk = sum(
        1 for g in losses_g if (g.get("cur") or {}).get("mega_evolved_no_attack")
    )
    loss_zero_boss = sum(
        1 for g in losses_g if int((g.get("cur") or {}).get("boss_play_count") or 0) == 0
    )
    loss_no_munk_dark = sum(
        1 for g in losses_g if not (g.get("cur") or {}).get("munk_dark_attach")
    )
    loss_no_itchy = sum(
        1 for g in losses_g if int((g.get("cur") or {}).get("budew_itchy_count") or 0) == 0
    )
    loss_opp_mega_first = sum(
        1 for g in losses_g if g.get("opp_mega_first")
    )
    loss_solo = sum(
        1 for g in losses_g if (g.get("cur") or {}).get("ever_staryu_solo_exposed")
    )
    loss_wrong = sum(
        1 for g in losses_g if (g.get("cur") or {}).get("ever_wrong_active")
    )
    loss_setup_miss = sum(
        1 for g in losses_g if int((g.get("cur") or {}).get("setup_miss_total") or 0) > 0
    )

    # Aggregate setup miss kinds on losses (and on no_mega / wrong_active subsets).
    miss_all: Counter = Counter()
    miss_no_mega: Counter = Counter()
    miss_wrong: Counter = Counter()
    for g in losses_g:
        cur = g.get("cur") or {}
        counts = cur.get("setup_miss_counts") or {}
        miss_all.update(counts)
        if cur.get("path_bucket") == "no_mega":
            miss_no_mega.update(counts)
        if cur.get("ever_wrong_active"):
            miss_wrong.update(counts)

    # Wrong-active first ID distribution
    wrong_ids = Counter(
        int((g.get("cur") or {}).get("wrong_active_first_id") or 0)
        for g in losses_g
        if (g.get("cur") or {}).get("ever_wrong_active")
    )

    # prize_at_t4 on losses
    t4_deltas = []
    for g in losses_g:
        p = (g.get("cur") or {}).get("prize_at_t4")
        if p and p.get("delta") is not None:
            t4_deltas.append(int(p["delta"]))

    # All-games exposure rates
    all_solo = sum(1 for g in games if (g.get("cur") or {}).get("ever_staryu_solo_exposed"))
    all_wrong = sum(1 for g in games if (g.get("cur") or {}).get("ever_wrong_active"))

    lines: list[str] = []
    lines.append("# H2H 引擎日志审计摘要")
    lines.append("")
    lines.append(f"- baseline: `{manifest.get('baseline')}`")
    lines.append(f"- current: `{manifest.get('current')}`")
    lines.append(f"- n={n} seed0={manifest.get('seed0')} tag=`{manifest.get('tag')}`")
    lines.append("")
    lines.append("## 总表")
    lines.append("")
    lines.append(f"| 项 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| WR (decided) | {wins}-{losses} ({_pct(wins, decided)}) draws={draws} |")
    lines.append(f"| seat A (先手) | {seat_wr(seat_a)} |")
    lines.append(f"| seat B (后手) | {seat_wr(seat_b)} |")
    lines.append(f"| 短局 steps&lt;40 | {short}/{n} ({_pct(short, n)}) |")
    lines.append("")
    lines.append("## 路径桶 × 胜负（current 视角）")
    lines.append("")
    lines.append("| path_bucket | 胜 | 负 | WR |")
    lines.append("|---|---:|---:|---|")
    for b in ("fast_mega_t≤3", "mega_t4-6", "mega_late_>6", "no_mega", "unknown"):
        w, l = bucket_win.get(b, [0, 0])
        if w + l == 0:
            continue
        lines.append(f"| {b} | {w} | {l} | {_pct(w, w + l)} |")
    lines.append("")
    lines.append("## 负局专用")
    lines.append("")
    nl = len(losses_g) or 1
    lines.append(f"- 负局数: **{len(losses_g)}**")
    lines.append(f"- seat B 负局: {loss_seat_b}/{len(losses_g)} ({_pct(loss_seat_b, len(losses_g))})")
    lines.append(f"- no_mega: {loss_no_mega} ({_pct(loss_no_mega, nl)})")
    lines.append(f"- mega_late_>6: {loss_mega_late} ({_pct(loss_mega_late, nl)})")
    lines.append(f"- mega_gap>0（进化后未当回合攻击）: {loss_mega_gap}")
    lines.append(f"- mega_evolved_no_attack: {loss_evo_no_atk}")
    lines.append(f"- zero_boss: {loss_zero_boss} ({_pct(loss_zero_boss, nl)})")
    lines.append(f"- 无 munk_dark: {loss_no_munk_dark} ({_pct(loss_no_munk_dark, nl)})")
    lines.append(f"- 无 Itchy: {loss_no_itchy} ({_pct(loss_no_itchy, nl)})")
    lines.append(f"- 对手 Mega 更早: {loss_opp_mega_first} ({_pct(loss_opp_mega_first, nl)})")
    if t4_deltas:
        avg = sum(t4_deltas) / len(t4_deltas)
        behind = sum(1 for d in t4_deltas if d < 0)
        lines.append(
            f"- 负局 T4 奖差 (opp_prize - self，>0=我方领先): "
            f"n={len(t4_deltas)} avg={avg:+.2f} 落后局={behind}"
        )
    lines.append("")
    lines.append("## 底座暴露 / 前场卡住")
    lines.append("")
    lines.append(
        f"- 全量曾「海星独站空替补」(ever_staryu_solo_exposed): "
        f"{all_solo}/{n} ({_pct(all_solo, n)})"
    )
    lines.append(
        f"- 全量曾「错前场」(ever_wrong_active，Active≠海星/Mega 且替补有海星或手握Mega): "
        f"{all_wrong}/{n} ({_pct(all_wrong, n)})"
    )
    lines.append(
        f"- 负局独站暴露: {loss_solo}/{len(losses_g)} ({_pct(loss_solo, nl)})"
    )
    lines.append(
        f"- 负局错前场: {loss_wrong}/{len(losses_g)} ({_pct(loss_wrong, nl)})"
    )
    lines.append(
        f"- 负局有铺场空过/误用 (setup_miss_total>0): "
        f"{loss_setup_miss}/{len(losses_g)} ({_pct(loss_setup_miss, nl)})"
    )
    if wrong_ids:
        lines.append("- 负局错前场首个 Active ID 分布:")
        for cid, c in wrong_ids.most_common(8):
            if cid:
                lines.append(f"  - `{cid}`: {c}")
    lines.append("")
    lines.append("## 负局铺场道具/支援者空过与误用（pre-Mega）")
    lines.append("")
    if miss_all:
        lines.append("| kind | 负局合计 | no_mega 子集 | 错前场子集 |")
        lines.append("|---|---:|---:|---:|")
        for kind, c in miss_all.most_common():
            lines.append(
                f"| `{kind}` | {c} | {miss_no_mega.get(kind, 0)} | "
                f"{miss_wrong.get(kind, 0)} |"
            )
    else:
        lines.append("- （无 miss 事件，或旧 manifest 无此字段）")
    lines.append("")
    lines.append("## Top 负局（优先 seat B + no_mega/late + 暴露/卡住 + 空过）")
    lines.append("")

    def loss_score(g: dict) -> tuple:
        cur = g.get("cur") or {}
        seat_b = 0 if g.get("cur_is_a") else 1
        bucket = cur.get("path_bucket") or ""
        path_bad = 1 if bucket in ("no_mega", "mega_late_>6") else 0
        expo = 1 if cur.get("ever_staryu_solo_exposed") or cur.get("ever_wrong_active") else 0
        miss = 1 if int(cur.get("setup_miss_total") or 0) > 0 else 0
        short = 1 if int(g.get("steps") or 0) < 40 else 0
        return (-seat_b, -path_bad, -expo, -miss, -short, int(g.get("i") or 0))

    top = sorted(losses_g, key=loss_score)[:20]
    lines.append(
        "| i | seat | steps | path | solo | wrong | miss | miss_kinds | log |"
    )
    lines.append("|---:|---|---:|---|---|---|---:|---|---|")
    for g in top:
        cur = g.get("cur") or {}
        seat = "A" if g.get("cur_is_a") else "B"
        log = g.get("log_path") or f"games/game_{int(g.get('i') or 0):03d}.log"
        counts = cur.get("setup_miss_counts") or {}
        kinds = ",".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "—"
        lines.append(
            f"| {g.get('i')} | {seat} | {g.get('steps')} | {cur.get('path_bucket')} | "
            f"{cur.get('ever_staryu_solo_exposed')} | {cur.get('ever_wrong_active')} | "
            f"{cur.get('setup_miss_total') or 0} | {kinds} | `{log}` |"
        )
    lines.append("")
    lines.append("## 原因解读（自动）")
    lines.append("")
    lines.append(
        "- `ever_wrong_active` 偏高属预期：开局常以土龙/愿增猿/雪童子起步再铺海星；"
        "请结合 `wrong_active_turns` 与 `no_mega` 子集看是否**长期卡住**。"
    )
    top_miss = miss_all.most_common(3)
    if top_miss:
        kinds = ", ".join(f"`{k}`×{v}" for k, v in top_miss)
        lines.append(f"- 负局最常见铺场问题: {kinds}。")
    if miss_no_mega:
        top_nm = miss_no_mega.most_common(3)
        kinds = ", ".join(f"`{k}`×{v}" for k, v in top_nm)
        lines.append(f"- **no_mega 负局**最常见: {kinds}。")
    switch_n = miss_all.get("miss_switch", 0)
    side_n = miss_all.get("wrong_play_side_basic", 0)
    fetch_n = (
        miss_all.get("miss_hilda", 0)
        + miss_all.get("miss_salvator", 0)
        + miss_all.get("miss_ub_mega", 0)
    )
    lines.append(
        f"- 交替空过 (`miss_switch`={switch_n}) 相对少；"
        f"侧基础误铺 (`wrong_play_side_basic`={side_n}) 与 "
        f"Mega 检索支援/Ball 空过 (Hilda+Salvator+UB_mega={fetch_n}) 更突出。"
    )
    lines.append(
        f"- 真·单底座裸露全量 {all_solo}/{n}；负局 {loss_solo} — "
        "多数伴随 Mega 砖在奖/库，而非「有道具却不铺」。"
    )
    lines.append("")
    lines.append(
        "> 指标来自同局 `engine_logs` 双侧派生；勿用同 seed 重跑当 A/B。"
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "manifest",
        type=Path,
        help="Path to manifest.json from h2h_loss_audit",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="SUMMARY.md path (default: next to manifest)",
    )
    args = ap.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    text = summarize(manifest)
    out = args.out or (args.manifest.parent / "SUMMARY.md")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    print(text[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
