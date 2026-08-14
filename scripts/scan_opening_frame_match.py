#!/usr/bin/env python3
"""Opening-frame match rate: online pick vs HEAD option_score winner.

Scans all public episodes of a submission, keeps MAIN frames with
my_turn <= --max-turn, rescoring each with the HEAD pilot. Reports
per-game and aggregate match rates plus DIFF details.

Usage:
  OPENING_HANDOFF=0 RL_ENABLED=0 python3 scripts/scan_opening_frame_match.py \\
    --sid 55433727
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
sys.path.insert(0, str(ROOT / "submission_starmie" / "pilot"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("OPENING_HANDOFF", "0")
os.environ.setdefault("RL_ENABLED", "0")
os.environ.setdefault("PYTHONHASHSEED", "0")

from cg.api import to_observation_class  # noqa: E402
import starmie_pilot as sp  # noqa: E402

MAIN = 0
TYPE_NAMES = {
    7: "PLAY", 8: "ATTACH", 9: "EVOLVE", 10: "ABILITY",
    12: "RETREAT", 13: "ATTACK", 14: "END",
}


def _desc(o: dict, hand_ids: list[int]) -> str:
    t = int(o.get("type") or -1)
    bits = [TYPE_NAMES.get(t, f"T{t}")]
    if o.get("attackId"):
        bits.append(f"atk{o['attackId']}")
    cid = None
    for k in ("cardId", "card_id", "id"):
        if o.get(k) is not None:
            cid = int(o[k])
            break
    if cid is None:
        for k in ("index", "handIndex"):
            idx = o.get(k)
            if idx is not None and 0 <= int(idx) < len(hand_ids):
                cid = hand_ids[int(idx)]
                break
    if cid is not None:
        bits.append(f"cid{cid}")
    return ":".join(bits)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", type=int, default=55433727)
    ap.add_argument("--max-turn", type=int, default=3, help="my_turn cutoff")
    ap.add_argument(
        "--out", type=Path,
        default=ROOT / "logs" / "diagnose_field6_zero_attack" / "OPENING_MATCH.md",
    )
    args = ap.parse_args()

    fade = json.loads(
        (ROOT / "data" / "kaggle_episodes" / f"analysis_{args.sid}_fade.json").read_text()
    )
    games = [g for g in fade.get("games") or [] if "PUBLIC" in (g.get("type") or "")]

    lines = [
        f"# 开局帧对拍 — sid={args.sid} my_turn≤{args.max_turn} "
        f"RL_ENABLED={os.environ.get('RL_ENABLED')}",
        "",
        "| eid | seat | won | frames | match | diffs (si:T online→head) |",
        "|---|---|---|---:|---:|---|",
    ]
    tot = mat = 0
    diff_kinds: Counter = Counter()
    for g in games:
        eid = int(g["eid"])
        seat = g.get("seat", "?")
        mi = 0 if seat == "A" else 1
        path = ROOT / "data" / "kaggle_episodes" / f"sub_{args.sid}" / f"episode-{eid}-replay.json"
        if not path.exists():
            continue
        d = json.loads(path.read_text())
        n = m = 0
        diffs: list[str] = []
        steps = d.get("steps") or []
        for si, step in enumerate(steps):
            if mi >= len(step):
                continue
            side = step[mi]
            obs_d = side.get("observation") or {}
            cur = obs_d.get("current") or {}
            if int(cur.get("yourIndex") if cur.get("yourIndex") is not None else -1) != mi:
                continue
            sel = obs_d.get("select") or {}
            if int(sel.get("context") if sel.get("context") is not None else -1) != MAIN:
                continue
            opts = [o for o in (sel.get("option") or []) if isinstance(o, dict)]
            # kaggle-environments off-by-one: action answering THIS observation
            # is recorded on the NEXT step (same agent slot).
            online_action = None
            if si + 1 < len(steps) and mi < len(steps[si + 1]):
                online_action = steps[si + 1][mi].get("action")
            if not opts or not online_action:
                continue
            turn = int(cur.get("turn") or 0)
            myt = (turn + 1) // 2 if seat == "A" else turn // 2
            if myt > args.max_turn:
                continue
            players = cur.get("players") or []
            if mi >= len(players) or not players[mi]:
                continue
            me = players[mi]
            hand_ids = [int(c["id"]) for c in (me.get("hand") or []) if c and c.get("id") is not None]
            try:
                online_opt = opts[int(online_action[0])]
            except Exception:
                continue
            online = _desc(online_opt, hand_ids)
            try:
                obs = to_observation_class(obs_d)
                try:
                    sp.reset_for_new_game()
                except Exception:
                    pass
                sit = sp._compute_situation(obs)
                sit["select_options"] = list(obs.select.option)
                ranked = sorted(
                    ((float(sp.option_score(obs, o, {}, sit)), i, o)
                     for i, o in enumerate(obs.select.option)),
                    key=lambda x: x[0], reverse=True,
                )
                wo = ranked[0][2]
                head = _desc(
                    {
                        "type": int(wo.type),
                        "attackId": int(getattr(wo, "attackId", 0) or 0),
                        "index": getattr(wo, "index", None),
                        "handIndex": getattr(wo, "handIndex", None),
                        "cardId": getattr(wo, "cardId", None) or getattr(wo, "id", None),
                    },
                    hand_ids,
                )
            except Exception as exc:
                head = f"ERR:{type(exc).__name__}"
            n += 1
            if head == online:
                m += 1
            else:
                diffs.append(f"si{si}:T{myt} `{online}`→`{head}`")
                diff_kinds[f"{online} → {head}"] += 1
        tot += n
        mat += m
        won = "W" if g.get("won") else "L"
        rate = f"{m}/{n}" if n else "-"
        lines.append(f"| {eid} | {seat} | {won} | {n} | {rate} | {'; '.join(diffs) or '—'} |")

    lines += [
        "",
        f"**合计 match {mat}/{tot} = {mat/tot:.0%}**" if tot else "no frames",
        "",
        "## DIFF 形态分布",
        "",
    ]
    for k, v in diff_kinds.most_common(30):
        lines.append(f"- {v}× {k}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"match {mat}/{tot}" + (f" = {mat/tot:.0%}" if tot else ""))
    for k, v in diff_kinds.most_common(15):
        print(f"  {v}x {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
