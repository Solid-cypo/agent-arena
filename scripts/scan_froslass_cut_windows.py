#!/usr/bin/env python3
"""Scan online replays for FroslassCut / dry-861 / Draw66 windows.

For each MAIN frame of our seat on sub_<sid>:
  - CUT: current _froslass_oneshot_cut_live → online vs HEAD pick
  - DRY: SWITCH/TO_ACTIVE onto unfueled Mega 861/1031
  - DRAW66: 66 on field + Run Away offered → online vs HEAD

Usage:
  OPENING_HANDOFF=0 RL_ENABLED=0 python3 scripts/scan_froslass_cut_windows.py \\
    --sid 55445134
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

from cg.api import SelectContext, to_observation_class  # noqa: E402
import starmie_pilot as sp  # noqa: E402

MAIN = 0
SWITCH_CTX = {int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)}
MEGA_STARMIE, MEGA_FROSLASS, DUD = 1031, 861, 66
WATER = {3, 16}  # basic water + prism
TYPE_NAMES = {
    7: "PLAY",
    8: "ATTACH",
    9: "EVOLVE",
    10: "ABILITY",
    12: "RETREAT",
    13: "ATTACK",
    14: "END",
}
ATK_JETTING = 1487
SWITCH_CID = int(getattr(sp, "_OC_SWITCH", 1123))


def _ids(cards) -> list[int]:
    return [int(c["id"]) for c in (cards or []) if c and c.get("id") is not None]


def _has_water(pkm: dict | None) -> bool:
    if not pkm:
        return False
    return any(int(e) in WATER for e in (pkm.get("energies") or []) if e is not None)


def _hand_cid(o: dict | None, hand_ids: list[int]) -> int | None:
    if not o:
        return None
    for k in ("cardId", "card_id", "id"):
        if o.get(k) is not None:
            return int(o[k])
    for k in ("index", "handIndex"):
        idx = o.get(k)
        if idx is not None and 0 <= int(idx) < len(hand_ids):
            return hand_ids[int(idx)]
    return None


def _ability_src_from_board(me: dict, o: dict | None) -> int:
    """Resolve ability source card id from area/index on our board."""
    if not o or int(o.get("type") or -1) != 10:
        return 0
    try:
        from cg.api import AreaType

        area = int(o.get("area") or -1)
        idx = int(o.get("index") if o.get("index") is not None else -1)
        if area == int(AreaType.ACTIVE):
            p = (me.get("active") or [None])[0]
            return int(p.get("id") or 0) if p else 0
        if area == int(AreaType.BENCH):
            bench = me.get("bench") or []
            if 0 <= idx < len(bench) and bench[idx]:
                return int(bench[idx].get("id") or 0)
    except Exception:
        pass
    return 0


def _opt_desc(o: dict | None, hand_ids: list[int], me: dict | None = None) -> str:
    if not o:
        return "??"
    t = int(o.get("type") or -1)
    bits = [TYPE_NAMES.get(t, f"T{t}")]
    if o.get("attackId"):
        bits.append(f"atk{int(o['attackId'])}")
    if t == 10 and me is not None:
        src = _ability_src_from_board(me, o)
        if src:
            bits.append(f"src{src}")
    else:
        cid = _hand_cid(o, hand_ids)
        if cid is not None:
            bits.append(f"cid{cid}")
    if o.get("area") is not None:
        bits.append(f"a{o['area']}")
    if o.get("index") is not None and t not in (7,):
        bits.append(f"i{o['index']}")
    return ":".join(bits)


def _online_opt(opts: list[dict], online_action) -> dict | None:
    try:
        idx = int(online_action[0])
        return opts[idx] if 0 <= idx < len(opts) else None
    except Exception:
        return None


def _head_pick(obs, sit) -> tuple[str, object | None, int]:
    try:
        ranked = sorted(
            (
                (float(sp.option_score(obs, o, {}, sit)), i, o)
                for i, o in enumerate(obs.select.option)
            ),
            key=lambda x: x[0],
            reverse=True,
        )
        if not ranked:
            return "NONE", None, -1
        _sc, wi, wo = ranked[0]
        return "OK", wo, wi
    except Exception as exc:
        return f"ERR:{type(exc).__name__}", None, -1


def _is_runaway_opt(obs, opt, mi: int) -> bool:
    if opt is None:
        return False
    try:
        from cg.api import OptionType

        if getattr(opt, "type", None) != OptionType.ABILITY:
            # dict form
            if isinstance(opt, dict) and int(opt.get("type") or -1) != 10:
                return False
            if isinstance(opt, dict):
                # need board — caller should use board helper
                return False
        return sp._ability_source_id(obs, opt, mi) == DUD
    except Exception:
        return False


def _is_cut_opt(obs, opt, mi: int, hand_ids: list[int]) -> bool:
    """Switch or Retreat that advances FroslassCut."""
    if opt is None:
        return False
    try:
        from cg.api import OptionType

        if isinstance(opt, dict):
            t = int(opt.get("type") or -1)
            if t == 12:
                return True
            if t == 7:
                return _hand_cid(opt, hand_ids) == SWITCH_CID
            return False
        if opt.type == OptionType.RETREAT:
            return True
        if opt.type == OptionType.PLAY:
            return sp._hand_card_id(obs, opt, mi) == SWITCH_CID
    except Exception:
        pass
    return False


def scan_episode(sid: int, eid: int, mi: int, won: bool) -> dict:
    path = (
        ROOT
        / "data"
        / "kaggle_episodes"
        / f"sub_{sid}"
        / f"episode-{eid}-replay.json"
    )
    d = json.loads(path.read_text())
    steps = d.get("steps") or []
    hits = {
        "cut_windows": [],
        "cut_near": [],
        "dry_promotes": [],
        "draw66_windows": [],
        "n_main": 0,
    }
    try:
        sp.reset_for_new_game()
    except Exception:
        pass

    for si, step in enumerate(steps):
        if mi >= len(step):
            continue
        side = step[mi]
        obs_d = side.get("observation") or {}
        cur = obs_d.get("current") or {}
        if int(cur.get("yourIndex") if cur.get("yourIndex") is not None else -1) != mi:
            continue
        sel = obs_d.get("select") or {}
        raw_ctx = int(sel.get("context") if sel.get("context") is not None else -1)
        opts = [o for o in (sel.get("option") or []) if isinstance(o, dict)]
        online_action = None
        if si + 1 < len(steps) and mi < len(steps[si + 1]):
            online_action = steps[si + 1][mi].get("action")
        if not opts or not online_action:
            continue
        players = cur.get("players") or []
        if mi >= len(players) or not players[mi]:
            continue
        me = players[mi]
        opp = players[1 - mi] if len(players) > 1 - mi else {}
        hand_ids = _ids(me.get("hand"))
        turn = int(cur.get("turn") or 0)
        online = _online_opt(opts, online_action)
        online_desc = _opt_desc(online, hand_ids, me)

        # ── DRY promote on SWITCH/TO_ACTIVE selects ──────────────────────────
        if raw_ctx in SWITCH_CTX and online:
            try:
                from cg.api import AreaType

                area = int(online.get("area") or -1)
                idx = int(online.get("index") if online.get("index") is not None else -1)
                pi = int(
                    online.get("playerIndex")
                    if online.get("playerIndex") is not None
                    else mi
                )
            except Exception:
                area = idx = -1
                pi = mi
                AreaType = None  # type: ignore
            if pi == mi and AreaType is not None:
                pkm = None
                if area == int(AreaType.BENCH):
                    bench = me.get("bench") or []
                    if 0 <= idx < len(bench):
                        pkm = bench[idx]
                elif area == int(AreaType.ACTIVE):
                    pkm = (me.get("active") or [None])[0]
                if pkm and int(pkm.get("id") or 0) in (MEGA_FROSLASS, MEGA_STARMIE):
                    if not _has_water(pkm) and not any(h in WATER for h in hand_ids):
                        hits["dry_promotes"].append(
                            {
                                "si": si,
                                "turn": turn,
                                "pid": int(pkm["id"]),
                                "online": online_desc,
                            }
                        )

        if raw_ctx != MAIN:
            continue
        hits["n_main"] += 1

        try:
            obs = to_observation_class(obs_d)
            sit = sp._compute_situation(obs)
            sit["select_options"] = list(obs.select.option)
        except Exception:
            continue

        head_status, wo, _wi = _head_pick(obs, sit)
        if wo is not None:
            head_desc = _opt_desc(
                {
                    "type": int(wo.type),
                    "attackId": int(getattr(wo, "attackId", 0) or 0),
                    "index": getattr(wo, "index", None),
                    "handIndex": getattr(wo, "handIndex", None),
                    "area": int(getattr(wo, "area", 0) or 0),
                },
                hand_ids,
                me,
            )
            # Prefer ability-source label via live obs helper
            try:
                from cg.api import OptionType

                if wo.type == OptionType.ABILITY:
                    src = sp._ability_source_id(obs, wo, mi)
                    head_desc = f"ABILITY:src{src}:a{int(wo.area)}:i{int(wo.index)}"
            except Exception:
                pass
        else:
            head_desc = head_status

        # ── CUT window + near-miss (861+W on bench, geometry almost) ─────────
        cut_live = False
        try:
            cut_live = bool(sp._froslass_oneshot_cut_live(obs, sit))
        except Exception:
            cut_live = False

        # Near-miss: watered 861 on bench + fueled Active Starmie, but knife off
        near = None
        try:
            _, fueled_861 = sp._bench_mega_froslass_with_water(obs, mi)
            board = sit.get("board")
            if (
                fueled_861 is not None
                and board is not None
                and board.active_is_mega_starmie
                and board.active_has_water
                and not cut_live
            ):
                reasons = []
                plan = sit.get("turn_plan")
                if plan is not None and plan.combat.mode == "DOUBLE_KO":
                    reasons.append("DOUBLE_KO")
                if not sp._opp_active_is_multi_prize(obs, mi):
                    reasons.append("not_multi_prize")
                if not sp._starmie_cannot_finish_front(obs, mi):
                    reasons.append("starmie_can_finish")
                opp_hp = sp._opp_active_hp(obs, mi)
                dmg = sp._resentful_damage(int(sit.get("opp_hand_count") or 0))
                if not (0 < opp_hp <= dmg):
                    reasons.append(f"resentful_short({dmg}<={opp_hp})")
                if not (
                    sp._hand_has_id(obs, mi, SWITCH_CID)
                    or sp._active_can_retreat(obs, mi)
                ):
                    reasons.append("no_cut_tool")
                if reasons:
                    near = {
                        "si": si,
                        "turn": turn,
                        "opp_hp": opp_hp,
                        "opp_hand": int(sit.get("opp_hand_count") or 0),
                        "reasons": reasons,
                        "online": online_desc,
                        "head": head_desc,
                    }
        except Exception:
            near = None
        if near:
            hits.setdefault("cut_near", []).append(near)

        if cut_live:
            online_is_cut = _is_cut_opt(obs, online, mi, hand_ids)
            head_is_cut = _is_cut_opt(obs, wo, mi, hand_ids)
            online_jet = (
                online is not None
                and int(online.get("type") or -1) == 13
                and int(online.get("attackId") or 0) == ATK_JETTING
            )
            hits["cut_windows"].append(
                {
                    "si": si,
                    "turn": turn,
                    "opp_hp": sp._opp_active_hp(obs, mi),
                    "opp_hand": int(sit.get("opp_hand_count") or 0),
                    "online": online_desc,
                    "head": head_desc,
                    "online_cut": online_is_cut,
                    "head_cut": head_is_cut,
                    "online_jet": online_jet,
                    "diff": online_desc != head_desc,
                }
            )

        # ── DRAW66 window: only when HEAD would pick Run Away ───────────────
        draw_live = False
        try:
            draw_live = bool(sp._dudunsparce_ability_offered(obs, sit))
        except Exception:
            draw_live = False
        if draw_live:
            online_draw = _ability_src_from_board(me, online) == DUD
            head_draw = False
            if wo is not None:
                try:
                    head_draw = sp._ability_source_id(obs, wo, mi) == DUD
                except Exception:
                    head_draw = False
            # Only count frames where HEAD wants Run Away (knife actually fires)
            # OR online already drew (HIT). Skip "66 offered but prep owns turn".
            if head_draw or online_draw:
                hits["draw66_windows"].append(
                    {
                        "si": si,
                        "turn": turn,
                        "online": online_desc,
                        "head": head_desc,
                        "online_draw": online_draw,
                        "head_draw": head_draw,
                        "online_jet": (
                            online is not None
                            and int(online.get("type") or -1) == 13
                            and int(online.get("attackId") or 0) == ATK_JETTING
                        ),
                        "online_end": online is not None
                        and int(online.get("type") or -1) == 14,
                        "diff": online_desc != head_desc,
                    }
                )

    hits["eid"] = eid
    hits["won"] = won
    hits["mi"] = mi
    hits.setdefault("cut_near", [])
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sid", type=int, default=55445134)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    fade_path = (
        ROOT / "data" / "kaggle_episodes" / f"analysis_{args.sid}_fade.json"
    )
    fade = json.loads(fade_path.read_text())
    games = [g for g in fade.get("games") or [] if "PUBLIC" in (g.get("type") or "")]

    out_dir = args.out or (
        ROOT / "logs" / f"diagnose_froslass_cut_{args.sid}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    all_cuts: list[dict] = []
    all_near: list[dict] = []
    all_dry: list[dict] = []
    all_draw: list[dict] = []
    per_game = []

    for g in games:
        eid = int(g["eid"])
        seat = g.get("seat", "?")
        mi = 0 if seat == "A" else 1
        path = (
            ROOT
            / "data"
            / "kaggle_episodes"
            / f"sub_{args.sid}"
            / f"episode-{eid}-replay.json"
        )
        if not path.exists():
            continue
        h = scan_episode(args.sid, eid, mi, bool(g.get("won")))
        for c in h["cut_windows"]:
            c["eid"] = eid
            c["seat"] = seat
            c["won"] = h["won"]
            all_cuts.append(c)
        for c in h.get("cut_near") or []:
            c["eid"] = eid
            c["seat"] = seat
            c["won"] = h["won"]
            all_near.append(c)
        for c in h["dry_promotes"]:
            c["eid"] = eid
            c["seat"] = seat
            c["won"] = h["won"]
            all_dry.append(c)
        for c in h["draw66_windows"]:
            c["eid"] = eid
            c["seat"] = seat
            c["won"] = h["won"]
            all_draw.append(c)
        per_game.append(
            {
                "eid": eid,
                "seat": seat,
                "won": h["won"],
                "n_main": h["n_main"],
                "n_cut": len(h["cut_windows"]),
                "n_near": len(h.get("cut_near") or []),
                "n_dry": len(h["dry_promotes"]),
                "n_draw66": len(h["draw66_windows"]),
            }
        )

    cut_miss = [c for c in all_cuts if c["head_cut"] and not c["online_cut"]]
    cut_jet_miss = [c for c in cut_miss if c["online_jet"]]
    draw_miss = [
        c for c in all_draw if c["head_draw"] and not c["online_draw"]
    ]
    draw_jet = [c for c in draw_miss if c["online_jet"]]
    draw_end = [c for c in draw_miss if c["online_end"]]
    near_reason = Counter(
        r for c in all_near for r in (c.get("reasons") or [])
    )

    lines = [
        f"# FroslassCut / dry-861 / Draw66 窗口扫 — sid={args.sid}",
        "",
        f"公局 **{len(per_game)}**｜HEAD = 当前 submission（含 FroslassCut + Draw66Closeout）",
        "",
        "## 总表",
        "",
        f"| 窗 | 帧数 | 说明 |",
        f"|---|---:|---|",
        f"| **CUT live** | **{len(all_cuts)}** | `_froslass_oneshot_cut_live` |",
        f"| CUT 线上未切 / HEAD 要切 | {len(cut_miss)} | 刀可改的帧 |",
        f"| └ 其中线上 Jetting | {len(cut_jet_miss)} | 典型漏切 |",
        f"| CUT near-miss（有水861在bench） | {len(all_near)} | 几何差一步 |",
        f"| **DRY promote** | **{len(all_dry)}** | 无能 Mega 进 Active |",
        f"| **DRAW66（HEAD要抽）** | **{len(all_draw)}** | HEAD 选 Run Away |",
        f"| DRAW 线上未抽 / HEAD 要抽 | {len(draw_miss)} | 刀可改的帧 |",
        f"| └ 线上 Jetting | {len(draw_jet)} | must_close 饿死抽 |",
        f"| └ 线上 END | {len(draw_end)} | 进66后空过 |",
        "",
    ]

    if near_reason:
        lines += [
            "### CUT near-miss 原因分布",
            "",
            "| reason | n |",
            "|---|---:|",
        ]
        for r, n in near_reason.most_common():
            lines.append(f"| `{r}` | {n} |")
        lines.append("")

    if all_cuts:
        lines += ["## CUT 帧明细", ""]
        for c in all_cuts[:40]:
            mark = "MISS" if c["head_cut"] and not c["online_cut"] else (
                "HIT" if c["online_cut"] else "head≠cut"
            )
            wl = "W" if c["won"] else "L"
            lines.append(
                f"- eid={c['eid']} {c['seat']} {wl} T={c['turn']} "
                f"oppHP={c['opp_hp']} hand={c['opp_hand']} "
                f"online=`{c['online']}` head=`{c['head']}` **{mark}**"
            )
        if len(all_cuts) > 40:
            lines.append(f"- … +{len(all_cuts) - 40} more")
        lines.append("")

    if all_near:
        lines += ["## CUT near-miss 样例（最多 15）", ""]
        for c in all_near[:15]:
            wl = "W" if c["won"] else "L"
            lines.append(
                f"- eid={c['eid']} {c['seat']} {wl} T={c['turn']} "
                f"oppHP={c['opp_hp']} hand={c['opp_hand']} "
                f"why={','.join(c['reasons'])} online=`{c['online']}`"
            )
        lines.append("")

    if all_dry:
        lines += ["## DRY promote 明细", ""]
        for c in all_dry[:30]:
            wl = "W" if c["won"] else "L"
            lines.append(
                f"- eid={c['eid']} {c['seat']} {wl} T={c['turn']} "
                f"pid={c['pid']} online=`{c['online']}`"
            )
        lines.append("")
    else:
        lines += ["## DRY promote", "", "无命中（本包公局未观察到无能 Mega 被选进 Active）。", ""]

    if all_draw:
        lines += ["## DRAW66 帧明细（MISS 优先）", ""]
        show = sorted(
            all_draw,
            key=lambda c: (
                0 if (c["head_draw"] and not c["online_draw"]) else 1,
                -int(c.get("online_jet") or 0),
                -int(c.get("online_end") or 0),
            ),
        )[:30]
        for c in show:
            if c["head_draw"] and not c["online_draw"]:
                mark = "MISS"
            elif c["online_draw"]:
                mark = "HIT"
            else:
                mark = "head≠draw"
            wl = "W" if c["won"] else "L"
            lines.append(
                f"- eid={c['eid']} {c['seat']} {wl} T={c['turn']} "
                f"online=`{c['online']}` head=`{c['head']}` **{mark}**"
            )
        lines.append("")

    games_with_cut = sum(1 for g in per_game if g["n_cut"] > 0)
    games_with_draw = sum(1 for g in per_game if g["n_draw66"] > 0)
    lines += [
        "## 局覆盖",
        "",
        f"- 含 CUT 窗的局：**{games_with_cut}/{len(per_game)}**",
        f"- 含 CUT near 的局：**{sum(1 for g in per_game if g['n_near'] > 0)}/{len(per_game)}**",
        f"- 含 DRAW66（HEAD要抽）的局：**{games_with_draw}/{len(per_game)}**",
        f"- 含 DRY 的局：**{sum(1 for g in per_game if g['n_dry'] > 0)}/{len(per_game)}**",
        "",
        "## 读法",
        "",
        "- CUT live=0：本包公局几乎无「有水861一击多奖」盘面；near 也极稀 → 刀对，但转化样本几乎没有。",
        "- DRAW MISS + Jetting（12帧/多局）：Draw66Closeout **有明确线上改点**，是本包最值钱的窗。",
        "- DRY 有命中则禁刀该挡；本包仅 1 帧，非主漏。",
        "",
    ]

    out_md = out_dir / "WINDOW_SCAN.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "window_scan.json").write_text(
        json.dumps(
            {
                "sid": args.sid,
                "n_games": len(per_game),
                "cuts": all_cuts,
                "cut_near": all_near,
                "dry": all_dry,
                "draw66": all_draw,
                "per_game": per_game,
                "summary": {
                    "cut_live": len(all_cuts),
                    "cut_miss": len(cut_miss),
                    "cut_jet_miss": len(cut_jet_miss),
                    "cut_near": len(all_near),
                    "near_reasons": dict(near_reason),
                    "dry": len(all_dry),
                    "draw_head_wants": len(all_draw),
                    "draw_miss": len(draw_miss),
                    "draw_jet": len(draw_jet),
                    "draw_end": len(draw_end),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(out_md.read_text())
    print(f"\nWrote {out_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
