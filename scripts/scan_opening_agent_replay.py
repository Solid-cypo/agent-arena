#!/usr/bin/env python3
"""Stateful agent replay vs online picks on opening frames.

Feeds each public episode's observation stream (our seat, in order) through
the real make_starmie_agent function, and compares its action to the online
action on MAIN frames with my_turn <= --max-turn. Run with RL_ENABLED=0 and
RL_ENABLED=1 to attribute online/local divergence to the RL hybrid.

Usage:
  RL_ENABLED=1 python3 scripts/scan_opening_agent_replay.py --sid 55433727
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONHASHSEED", "0")

from h2h_starmie_vs_baseline import load_starmie_agent  # noqa: E402

MAIN = 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", type=int, default=55433727)
    ap.add_argument("--max-turn", type=int, default=3)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    rl = os.environ.get("RL_ENABLED", "1")
    out = args.out or (
        ROOT / "logs" / "diagnose_field6_zero_attack" / f"OPENING_AGENT_REPLAY_RL{rl}.md"
    )

    agent, reset, _mod, _deck, _state = load_starmie_agent(ROOT / "submission_starmie")

    fade = json.loads(
        (ROOT / "data" / "kaggle_episodes" / f"analysis_{args.sid}_fade.json").read_text()
    )
    games = [g for g in fade.get("games") or [] if "PUBLIC" in (g.get("type") or "")]

    lines = [
        f"# 有状态 agent 重放对拍 — sid={args.sid} my_turn≤{args.max_turn} RL_ENABLED={rl}",
        "",
        "| eid | seat | won | opening帧 | match | 全帧 | 全帧match |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    tot = mat = tot_all = mat_all = 0
    diff_turns: Counter = Counter()
    for g in games:
        eid = int(g["eid"])
        seat = g.get("seat", "?")
        mi = 0 if seat == "A" else 1
        path = ROOT / "data" / "kaggle_episodes" / f"sub_{args.sid}" / f"episode-{eid}-replay.json"
        if not path.exists():
            continue
        d = json.loads(path.read_text())
        reset()
        n = m = n_all = m_all = 0
        # kaggle-environments off-by-one: action recorded at step t answers the
        # observation recorded at step t-1 (same agent slot).
        steps = d.get("steps") or []
        for t in range(len(steps)):
            if mi >= len(steps[t]):
                continue
            obs_d = (steps[t][mi].get("observation")) or {}
            online = None
            if t + 1 < len(steps) and mi < len(steps[t + 1]):
                online = steps[t + 1][mi].get("action")
            if obs_d.get("select") is None:
                # deck-order frame: agent handles internally
                try:
                    agent(obs_d)
                except Exception:
                    pass
                continue
            cur = obs_d.get("current") or {}
            if int(cur.get("yourIndex") if cur.get("yourIndex") is not None else -1) != mi:
                continue
            if not online:
                continue
            try:
                mine = agent(obs_d)
            except Exception:
                mine = None
            sel = obs_d.get("select") or {}
            same = mine is not None and list(mine) == list(online)
            n_all += 1
            m_all += int(same)
            if int(sel.get("context") if sel.get("context") is not None else -1) != MAIN:
                continue
            turn = int(cur.get("turn") or 0)
            myt = (turn + 1) // 2 if seat == "A" else turn // 2
            if myt > args.max_turn:
                continue
            n += 1
            m += int(same)
            if not same:
                diff_turns[f"T{myt}"] += 1
        tot += n
        mat += m
        tot_all += n_all
        mat_all += m_all
        won = "W" if g.get("won") else "L"
        lines.append(
            f"| {eid} | {seat} | {won} | {n} | {m}/{n} | {n_all} | {m_all}/{n_all} |"
        )

    lines += [
        "",
        f"**opening 帧合计 match {mat}/{tot} = {mat/tot:.0%}**" if tot else "no frames",
        f"全帧合计 match {mat_all}/{tot_all} = {mat_all/tot_all:.0%}" if tot_all else "",
        "",
        f"DIFF 按回合：{dict(diff_turns)}",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    print(f"opening match {mat}/{tot}" + (f" = {mat/tot:.0%}" if tot else ""))
    print(f"all-frame match {mat_all}/{tot_all}" + (f" = {mat_all/tot_all:.0%}" if tot_all else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
