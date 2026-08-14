#!/usr/bin/env python3
"""Frame-by-frame replay rescore for "has Mega but zero attack" losses.

For each MAIN frame of our seat: rescore all options with HEAD
(option_score), record the HEAD winner vs the online pick, and track the
Mega/energy line (active id, fueled, attack options offered).

Usage:
  OPENING_HANDOFF=0 RL_ENABLED=0 python3 scripts/probe_zero_attack_frames.py \\
    --sid 55433727 --eid 92000238 91988778
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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

MEGA_STARMIE = 1031
TYPE_NAMES = {
    7: "PLAY", 8: "ATTACH", 9: "EVOLVE", 10: "ABILITY",
    12: "RETREAT", 13: "ATTACK", 14: "END", 15: "ATTACK15",
}
MAIN = 0


def _opt_desc(o: dict, hand_ids: list[int]) -> str:
    t = int(o.get("type") or -1)
    name = TYPE_NAMES.get(t, f"T{t}")
    bits = [name]
    aid = o.get("attackId")
    if aid:
        bits.append(f"atk{aid}")
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


def _ids(cards) -> list[int]:
    return [int(c["id"]) for c in (cards or []) if c and c.get("id") is not None]


def probe_episode(sid: int, eid: int, mi: int, seat: str, out_lines: list[str]) -> None:
    path = ROOT / "data" / "kaggle_episodes" / f"sub_{sid}" / f"episode-{eid}-replay.json"
    d = json.loads(path.read_text())
    out_lines.append(f"## eid={eid} seat={seat}")
    out_lines.append("")
    n_main = n_diff = 0
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
        raw_ctx = sel.get("context")
        opts = [o for o in (sel.get("option") or []) if isinstance(o, dict)]
        # kaggle-environments off-by-one: the action answering THIS observation
        # is recorded on the NEXT step (same agent slot).
        online_action = None
        if si + 1 < len(steps) and mi < len(steps[si + 1]):
            online_action = steps[si + 1][mi].get("action")
        if not opts or not online_action:
            continue
        players = cur.get("players") or []
        if mi >= len(players) or not players[mi]:
            continue
        me = players[mi]
        hand_ids = _ids(me.get("hand"))
        act = (me.get("active") or [None])[0] or {}
        act_id = int(act.get("id") or 0)
        act_en = [int(e) for e in (act.get("energies") or []) if e is not None]
        bench_ids = _ids(me.get("bench"))
        turn = int(cur.get("turn") or 0)

        if int(raw_ctx if raw_ctx is not None else -1) != MAIN:
            continue
        n_main += 1

        try:
            online_idx = int(online_action[0])
            online_opt = opts[online_idx] if 0 <= online_idx < len(opts) else None
        except Exception:
            online_opt = None
        online_desc = _opt_desc(online_opt, hand_ids) if online_opt else "??"

        head_desc = "ERR"
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
            _sc, wi, wo = ranked[0]
            wo_d = {
                "type": int(wo.type),
                "attackId": int(getattr(wo, "attackId", 0) or 0),
                "index": getattr(wo, "index", None),
                "handIndex": getattr(wo, "handIndex", None),
                "cardId": getattr(wo, "cardId", None) or getattr(wo, "id", None),
            }
            head_desc = _opt_desc(wo_d, hand_ids)
        except Exception as exc:  # keep scanning
            head_desc = f"ERR:{type(exc).__name__}"

        diff = head_desc != online_desc
        if diff:
            n_diff += 1
        atk_opts = [o for o in opts if int(o.get("type") or -1) == 13]
        mark = "**DIFF**" if diff else "same"
        out_lines.append(
            f"- si={si} T={turn} active={act_id} en={act_en} "
            f"bench={bench_ids} atk_opts={len(atk_opts)} "
            f"online=`{online_desc}` head=`{head_desc}` {mark}"
        )
    out_lines.append("")
    out_lines.append(f"MAIN frames={n_main}, DIFF={n_diff}")
    out_lines.append("")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", type=int, default=55433727)
    ap.add_argument("--eid", type=int, nargs="+", required=True)
    ap.add_argument(
        "--out", type=Path,
        default=ROOT / "logs" / "diagnose_field6_zero_attack" / "ZERO_ATTACK_FRAMES.md",
    )
    args = ap.parse_args()

    fade = json.loads(
        (ROOT / "data" / "kaggle_episodes" / f"analysis_{args.sid}_fade.json").read_text()
    )
    seats = {int(g["eid"]): g.get("seat", "?") for g in fade.get("games") or []}

    lines = [
        f"# 零攻局逐帧对拍 — sid={args.sid} RL_ENABLED={os.environ.get('RL_ENABLED')}",
        "",
    ]
    for eid in args.eid:
        seat = seats.get(eid, "?")
        mi = 0 if seat == "A" else 1
        probe_episode(args.sid, eid, mi, seat, lines)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
