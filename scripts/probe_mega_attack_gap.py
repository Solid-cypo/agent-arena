#!/usr/bin/env python3
"""Attribute the evolve-vs-first-attack gap on Kaggle replays.

For games where Mega Starmie evolved on curve (A<=T3 / B<=T2) but did NOT
attack on curve, walk our decision turns up to the deadline and classify the
blocker:

  POLICY_NO_ATTACK   Mega active + water, ATTACK offered, we did something else
  POLICY_NO_ATTACH   Mega active, water in hand, ATTACH offered, not attached
                     to Mega (attached elsewhere or skipped)
  POLICY_STUCK_BENCH Mega(+water) on bench, RETREAT/switch offered, not taken
  NO_WATER           No water in hand/board for Mega by deadline (resource)
  STUCK_NO_OUT       Mega benched, no retreat/switch offered (locked)
  KOD                Mega left the board before deadline (opponent)
  SHORT              Game ended before deadline
  OTHER              None of the above

Usage:
  python3 scripts/probe_mega_attack_gap.py --sid 55433727 55386951 55393166
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEGA = 1031
WATER_IDS = {3, 9}
PLAY, ATTACH, EVOLVE, ABILITY, RETREAT, ATTACK = 7, 8, 9, 10, 12, 13
SWITCH_CARD = 1123


def _ids(cards) -> list[int]:
    return [int(c["id"]) for c in (cards or []) if c and c.get("id") is not None]


def probe_game(d: dict, mi: int, seat: str) -> tuple[str, str, list[str]]:
    """Return (verdict, detail, turn_trace)."""
    steps = d.get("steps") or []
    deadline = 3 if seat == "A" else 2

    evo_t = None
    atk_t = None
    trace: list[str] = []
    # Per-my-turn last MAIN frame info within deadline window.
    verdicts: list[tuple[str, str]] = []
    max_myt = 0

    for si, step in enumerate(steps):
        if mi >= len(step):
            continue
        obs = step[mi].get("observation") or {}
        cur = obs.get("current") or {}
        players = cur.get("players") or []
        if mi >= len(players) or not players[mi]:
            continue
        me = players[mi]
        turn = int(cur.get("turn") or 0)
        myt = (turn + 1) // 2 if seat == "A" else turn // 2
        max_myt = max(max_myt, myt)

        pieces = (me.get("active") or []) + (me.get("bench") or [])
        mega_pieces = [p for p in pieces if p and int(p.get("id") or 0) == MEGA]
        if mega_pieces and evo_t is None:
            evo_t = myt

        act = (me.get("active") or [None])[0]
        act_is_mega = bool(act and int(act.get("id") or 0) == MEGA)
        act_water = act_is_mega and any(
            int(e) in WATER_IDS for e in (act.get("energies") or []) if e is not None
        )

        if int(cur.get("yourIndex") if cur.get("yourIndex") is not None else -1) != mi:
            continue
        sel = obs.get("select") or {}
        if int(sel.get("context") if sel.get("context") is not None else -1) != 0:
            continue
        opts = [o for o in (sel.get("option") or []) if isinstance(o, dict)]
        action = None
        if si + 1 < len(steps) and mi < len(steps[si + 1]):
            action = steps[si + 1][mi].get("action")
        if not opts or not action:
            continue
        try:
            picked = opts[int(action[0])]
        except Exception:
            picked = None

        if picked and int(picked.get("type") or -1) == ATTACK and act_is_mega:
            if atk_t is None:
                atk_t = myt

        if myt > deadline or atk_t is not None:
            continue

        # classify this frame's situation
        hand = _ids(me.get("hand"))
        water_in_hand = any(h in WATER_IDS for h in hand)
        atk_offered = any(int(o.get("type") or -1) == ATTACK for o in opts)
        attach_offered = any(int(o.get("type") or -1) == ATTACH for o in opts)
        retreat_offered = any(int(o.get("type") or -1) == RETREAT for o in opts)
        switch_in_hand = SWITCH_CARD in hand
        bench_ids = _ids(me.get("bench"))
        mega_on_bench = MEGA in bench_ids
        bench_mega_water = any(
            p and int(p.get("id") or 0) == MEGA
            and any(int(e) in WATER_IDS for e in (p.get("energies") or []) if e is not None)
            for p in (me.get("bench") or [])
        )
        picked_t = int(picked.get("type") or -1) if picked else -1
        picked_atk = picked_t == ATTACK

        frame_v = None
        if act_is_mega and act_water and atk_offered and not picked_atk:
            frame_v = ("POLICY_NO_ATTACK", f"T{myt} picked type{picked_t}")
        elif act_is_mega and not act_water and water_in_hand and attach_offered:
            frame_v = ("POLICY_NO_ATTACH", f"T{myt} water in hand, picked type{picked_t}")
        elif mega_on_bench and (retreat_offered or switch_in_hand):
            tag = "水已上" if bench_mega_water else "无水"
            frame_v = ("POLICY_STUCK_BENCH", f"T{myt} bench Mega({tag}), retreat={retreat_offered} switch={switch_in_hand}")
        elif act_is_mega and not act_water and not water_in_hand:
            frame_v = ("NO_WATER", f"T{myt} active Mega dry, hand no water")
        elif mega_on_bench:
            frame_v = ("STUCK_NO_OUT", f"T{myt} bench Mega, no retreat/switch")
        if frame_v:
            verdicts.append(frame_v)
            trace.append(f"{frame_v[0]}:{frame_v[1]}")

    if evo_t is None or evo_t > deadline:
        return ("EVOLVE_FAIL", f"evo_t={evo_t}", trace)
    if atk_t is not None and atk_t <= deadline:
        return ("OK", f"atk T{atk_t}", trace)
    if max_myt < deadline:
        return ("SHORT", f"game ended T{max_myt}", trace)

    # mega vanished? check final board
    priority = ["POLICY_NO_ATTACK", "POLICY_NO_ATTACH", "POLICY_STUCK_BENCH",
                "NO_WATER", "STUCK_NO_OUT"]
    for p in priority:
        for v, det in verdicts:
            if v == p:
                return (p, det, trace)
    return ("OTHER", "no classified frame", trace)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", type=int, nargs="+", default=[55433727])
    ap.add_argument(
        "--out", type=Path,
        default=ROOT / "logs" / "diagnose_mega_attack_gap" / "GAP_ATTRIBUTION.md",
    )
    args = ap.parse_args()

    lines = ["# 「进化达标但出手不达标」缺口归因（线上回放）", ""]
    agg: Counter = Counter()
    n_all = 0
    for sid in args.sid:
        fade = json.loads(
            (ROOT / "data" / "kaggle_episodes" / f"analysis_{sid}_fade.json").read_text()
        )
        games = [g for g in fade.get("games") or [] if "PUBLIC" in (g.get("type") or "")]
        lines.append(f"## sid={sid}")
        lines.append("")
        cnt: Counter = Counter()
        for g in games:
            eid = int(g["eid"])
            seat = g.get("seat", "?")
            mi = 0 if seat == "A" else 1
            p = ROOT / "data" / "kaggle_episodes" / f"sub_{sid}" / f"episode-{eid}-replay.json"
            if not p.exists():
                continue
            d = json.loads(p.read_text())
            v, det, trace = probe_game(d, mi, seat)
            cnt[v] += 1
            n_all += 1
            agg[v] += 1
            won = "W" if g.get("won") else "L"
            if v not in ("OK",):
                lines.append(f"- {eid} {seat} {won} → **{v}** ({det})")
                for t in trace[:4]:
                    lines.append(f"    - {t}")
        lines.append("")
        lines.append("| verdict | n |")
        lines.append("|---|---:|")
        for k, vv in cnt.most_common():
            lines.append(f"| {k} | {vv} |")
        lines.append("")

    lines += ["## 合计", "", "| verdict | n | 占比 |", "|---|---:|---:|"]
    for k, vv in agg.most_common():
        lines.append(f"| {k} | {vv} | {vv/n_all:.0%} |")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}")
    for k, vv in agg.most_common():
        print(f"  {k}: {vv} ({vv/n_all:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
