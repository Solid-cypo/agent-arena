#!/usr/bin/env python3
"""Scan online replays for post-Mega midgame stall: goals vs paths.

Classifies each MAIN decision after our Mega Starmie is on the field:

  goals  — board/hand truth (DP / second attacker / 66 draw / attack/dispatch)
  paths  — engine options that advance a live goal (incl. dig seats)
  choice — END / advance / other

Dig seats (v2):
  DIG_DARK    — PLAY Crispin (useful discard) or Night Stretcher (Dark in discard)
  DIG_PLACER  — PLAY Hilda when Risky Ruins / Froslass not already in hand

Stall buckets:
  NO_GOAL          — no midgame goal (rare post-Mega)
  NO_PATH          — goals exist but no advancing option offered
  PATH_IGNORED     — advancing option offered but we END / junk
  PROGRESS         — we took an advancing option

Usage:
  python3 scripts/scan_midgame_dp_stall.py --sid 55386951 --losses-only
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MEGA_STARMIE, STARYU = 1031, 1030
MEGA_FROSLASS, FROSLASS, SNORUNT = 861, 104, 860
MUNKIDORI, DUDUNSPARCE = 112, 66
DUNSPARCE = {65, 305}
DARK, WATER = 7, 3
RISKY_RUINS = 1260
BOSS = 1182
JETTING = 1487
CRISPIN, NIGHT_STRETCHER, HILDA = 1198, 1152, 1225
LILLIE, JUDGE = 1227, 1213
REDRAW_SUP = {LILLIE, JUDGE}
# Basics Crispin can touch in this meta (deck + common opponents).
BASIC_ENERGIES = {DARK, WATER, 1, 2, 4, 5, 6, 8}  # G/R/F/L/P/M + our W/D

PLAY, ATTACH, EVOLVE, ABILITY, ATTACK, END, RETREAT = 7, 8, 9, 10, 13, 14, 12
MAIN = 0

ARCHALUDON = {169, 170, 190, 839, 840, 992}
DRAGAPULT = {119, 120, 121}
TREVENANT = {878, 879}
LUCARIO = {677, 678}
ALAK = {741, 742, 743}


def _ids(cards) -> list[int]:
    out = []
    for c in cards or []:
        if not c:
            continue
        cid = c.get("id")
        if cid is not None:
            out.append(int(cid))
    return out


def _energies(pkm) -> list[int]:
    return [int(e) for e in (pkm.get("energies") or []) if e is not None]


def _has_dark(pkm) -> bool:
    return any(e == DARK for e in _energies(pkm))


def _has_water(pkm) -> bool:
    return any(e == WATER for e in _energies(pkm))


def _field_pkms(me) -> list[dict]:
    out = []
    for c in (me.get("active") or []) + (me.get("bench") or []):
        if c:
            out.append(c)
    return out


def _find_pkm(me, cid: int):
    for p in _field_pkms(me):
        if int(p.get("id") or 0) == cid:
            return p
    return None


def _opt_card_id(opt, hand_ids: list[int]) -> int | None:
    """Best-effort card id for PLAY/ATTACH/EVOLVE options."""
    for k in ("cardId", "card_id", "id"):
        v = opt.get(k)
        if v is not None:
            return int(v)
    idx = opt.get("index")
    if idx is not None and 0 <= int(idx) < len(hand_ids):
        return hand_ids[int(idx)]
    hi = opt.get("handIndex")
    if hi is not None and 0 <= int(hi) < len(hand_ids):
        return hand_ids[int(hi)]
    return None


def _ban_froslass(opp_field: set[int]) -> bool:
    return bool(
        opp_field & ARCHALUDON
        or opp_field & DRAGAPULT
        or opp_field & TREVENANT
        or opp_field & ALAK
    )


def classify_goals(me, opp, stadium_ids: set[int]) -> dict[str, bool]:
    field = _field_pkms(me)
    field_ids = {int(p.get("id") or 0) for p in field}
    hand = _ids(me.get("hand"))
    hand_set = set(hand)
    active = (me.get("active") or [None])[0]
    active_id = int(active.get("id") or 0) if active else 0
    opp_field = set(_ids((opp.get("active") or [])) + _ids(opp.get("bench") or []))
    ban = _ban_froslass(opp_field)

    munk = _find_pkm(me, MUNKIDORI)
    mega = _find_pkm(me, MEGA_STARMIE)
    dud = _find_pkm(me, DUDUNSPARCE)

    need_munk = MUNKIDORI not in field_ids
    need_dark = (not need_munk) and munk is not None and not _has_dark(munk)
    placer_online = FROSLASS in field_ids or MEGA_FROSLASS in field_ids or RISKY_RUINS in stadium_ids
    need_placer = not placer_online and not ban
    # Second attacker: Mega online, no 861, line not banned
    need_sa = (
        MEGA_STARMIE in field_ids
        and MEGA_FROSLASS not in field_ids
        and not ban
    )
    need_snorunt = need_sa and SNORUNT not in field_ids and MEGA_FROSLASS not in hand_set
    need_861_evo = (
        need_sa
        and SNORUNT in field_ids
        and MEGA_FROSLASS in hand_set
    )
    # 66 draw when dud online (ability may or may not be offered)
    want_66_draw = dud is not None
    # Attack / dispatch when Mega watered
    mega_ready = mega is not None and _has_water(mega)
    need_dispatch = mega_ready and active_id != MEGA_STARMIE
    need_attack = mega_ready and active_id == MEGA_STARMIE

    goals = {
        "MUNK": need_munk,
        "DARK": need_dark,
        "PLACER": need_placer,
        "SNORUNT": need_snorunt,
        "EVOLVE_861": need_861_evo,
        "DRAW_66": want_66_draw,
        "DISPATCH": need_dispatch,
        "ATTACK": need_attack,
    }
    return goals


def _crispin_can_dig_dark(hand_ids: list[int], discard_ids: list[int]) -> bool:
    """Crispin opens a Dark path only when it can actually produce Dark progress.

    - Dark in discard, not in hand → dig Dark to hand (NoPathDark seat)
    - Dark in hand + different basic in discard → TO_HAND other → ATTACH Dark
    Empty / non-energy discard (engine may still list Crispin) → not a path.
    """
    basics_in_disc = set(discard_ids) & BASIC_ENERGIES
    if not basics_in_disc:
        return False
    if DARK not in hand_ids and DARK in basics_in_disc:
        return True
    if DARK in hand_ids and (basics_in_disc - {DARK}):
        return True
    return False


def classify_paths(opts, hand_ids: list[int], goals: dict[str, bool], me) -> set[str]:
    """Which goals have a live MAIN option (incl. dig supporters)."""
    paths: set[str] = set()
    discard_ids = _ids(me.get("discard"))
    for o in opts:
        if not isinstance(o, dict):
            continue
        t = int(o.get("type") or -1)
        cid = _opt_card_id(o, hand_ids)
        if t == PLAY and cid == MUNKIDORI and goals.get("MUNK"):
            paths.add("MUNK")
        if t == ATTACH and goals.get("DARK"):
            # dark attach onto Munk — energy id may be in option
            eid = o.get("energyId") or o.get("cardId") or cid
            if eid == DARK or cid == DARK:
                paths.add("DARK")
            # if any ATTACH while need_dark and hand has dark, count soft
            if DARK in hand_ids:
                paths.add("DARK")
        if t == PLAY and cid in (SNORUNT, FROSLASS, RISKY_RUINS):
            if goals.get("SNORUNT") and cid == SNORUNT:
                paths.add("SNORUNT")
            if goals.get("PLACER") and cid in (FROSLASS, RISKY_RUINS):
                paths.add("PLACER")
        # Dig seats (previously undercounted → false NO_PATH)
        if t == PLAY and cid == CRISPIN and goals.get("DARK"):
            if _crispin_can_dig_dark(hand_ids, discard_ids):
                paths.add("DARK")
                paths.add("DIG_DARK")
        if t == PLAY and cid == NIGHT_STRETCHER and goals.get("DARK"):
            if DARK in discard_ids:
                paths.add("DARK")
                paths.add("DIG_DARK")
        if t == PLAY and cid == HILDA and goals.get("PLACER"):
            # Hilda: Pokemon + Stadium — dig Risky Ruins when placer not in hand
            if RISKY_RUINS not in hand_ids and FROSLASS not in hand_ids:
                paths.add("PLACER")
                paths.add("DIG_PLACER")
        if t == EVOLVE and goals.get("EVOLVE_861"):
            # evolve to 861 from snorunt
            if cid == MEGA_FROSLASS or MEGA_FROSLASS in hand_ids:
                paths.add("EVOLVE_861")
        if t == ABILITY and goals.get("DRAW_66"):
            # ability from dud — source area bench/active
            paths.add("DRAW_66")
        if t == PLAY and cid == 1123 and goals.get("DISPATCH"):  # Switch
            paths.add("DISPATCH")
        if t == RETREAT and goals.get("DISPATCH"):
            paths.add("DISPATCH")
        if t == ATTACK and goals.get("ATTACK"):
            aid = int(o.get("attackId") or 0)
            if aid == JETTING or aid:
                paths.add("ATTACK")
        if t == PLAY and cid in DUNSPARCE and goals.get("MUNK") is False:
            pass  # seating duns is progress-ish but not DP goal
        # Shuffle redraw — live whenever offered (closes scanner blind spot that
        # labeled "Lillie in hand + Jetting" as NO_PATH).
        if t == PLAY and cid in REDRAW_SUP:
            paths.add("REDRAW")
    return paths


def choice_kind(action, opts, paths: set[str], hand_ids: list[int]) -> str:
    if not action:
        return "EMPTY"
    try:
        idx = int(action[0])
    except Exception:
        return "OTHER"
    if not (0 <= idx < len(opts)):
        return "OTHER"
    o = opts[idx]
    t = int(o.get("type") or -1)
    if t == END:
        return "END"
    # did this option advance any path goal?
    cid = _opt_card_id(o, hand_ids)
    advanced = False
    if t == PLAY and cid == MUNKIDORI and "MUNK" in paths:
        advanced = True
    if t == ATTACH and "DARK" in paths:
        eid = o.get("energyId") or o.get("cardId") or cid
        if eid == DARK or cid == DARK:
            advanced = True
    if t == PLAY and cid == SNORUNT and "SNORUNT" in paths:
        advanced = True
    if t == PLAY and cid in (FROSLASS, RISKY_RUINS) and "PLACER" in paths:
        advanced = True
    if t == PLAY and cid == CRISPIN and "DIG_DARK" in paths:
        advanced = True
    if t == PLAY and cid == NIGHT_STRETCHER and "DIG_DARK" in paths:
        advanced = True
    if t == PLAY and cid == HILDA and "DIG_PLACER" in paths:
        advanced = True
    if t == EVOLVE and "EVOLVE_861" in paths:
        advanced = True
    if t == ABILITY and "DRAW_66" in paths:
        advanced = True
    if t == PLAY and cid in REDRAW_SUP and "REDRAW" in paths:
        advanced = True
    if t == PLAY and cid == 1123 and "DISPATCH" in paths:
        advanced = True
    if t == RETREAT and "DISPATCH" in paths:
        advanced = True
    if t == ATTACK and "ATTACK" in paths:
        advanced = True
    if advanced:
        return "ADVANCE"
    return "OTHER"


def stall_bucket(goals: dict[str, bool], paths: set[str], choice: str) -> str | None:
    live = {k for k, v in goals.items() if v}
    # Ignore DRAW_66 alone as "must progress" when attack/dispatch/DP also live —
    # still count it for path analysis.
    hard = live - set()
    if not hard:
        return "NO_GOAL" if choice in ("END", "EMPTY") else None
    if not paths:
        if choice in ("END", "EMPTY", "OTHER"):
            return "NO_PATH"
        return None
    if choice == "END":
        return "PATH_IGNORED"
    if choice == "EMPTY":
        return "PATH_IGNORED"  # offered path, no commit
    if choice == "OTHER" and paths:
        # took non-advancing while path open
        return "PATH_IGNORED"
    if choice == "ADVANCE":
        return "PROGRESS"
    return None


def scan_game(path: Path, mi: int) -> dict:
    d = json.loads(path.read_text())
    mega_seen = False
    rows = []
    buckets = Counter()
    goal_hits = Counter()
    path_hits = Counter()
    # DP / SA progress milestones (first time after mega)
    milestones = {
        "mega_gt": None,
        "munk_gt": None,
        "dark_gt": None,
        "placer_gt": None,
        "snorunt_gt": None,
        "861_gt": None,
        "dud_gt": None,
        "dud_ability_gt": None,
        "jetting_gt": None,
    }

    for si, step in enumerate(d.get("steps") or []):
        if mi >= len(step):
            continue
        side = step[mi]
        obs = side.get("observation") or {}
        cur = obs.get("current") or {}
        raw_yi = cur.get("yourIndex")
        yi = int(raw_yi) if raw_yi is not None else -1
        if yi != mi:
            continue
        players = cur.get("players") or []
        if mi >= len(players) or not players[mi]:
            continue
        me = players[mi]
        opp = players[1 - mi] or {}
        stadium_ids = set(_ids(cur.get("stadium") or []))
        field_ids = {int(p.get("id") or 0) for p in _field_pkms(me)}
        gt = int(cur.get("turn") or 0)

        if MEGA_STARMIE in field_ids and milestones["mega_gt"] is None:
            milestones["mega_gt"] = gt
            mega_seen = True
        if not mega_seen:
            continue

        if MUNKIDORI in field_ids and milestones["munk_gt"] is None:
            milestones["munk_gt"] = gt
        munk = _find_pkm(me, MUNKIDORI)
        if munk and _has_dark(munk) and milestones["dark_gt"] is None:
            milestones["dark_gt"] = gt
        if (FROSLASS in field_ids or MEGA_FROSLASS in field_ids or RISKY_RUINS in stadium_ids) and milestones["placer_gt"] is None:
            milestones["placer_gt"] = gt
        if SNORUNT in field_ids and milestones["snorunt_gt"] is None:
            milestones["snorunt_gt"] = gt
        if MEGA_FROSLASS in field_ids and milestones["861_gt"] is None:
            milestones["861_gt"] = gt
        if DUDUNSPARCE in field_ids and milestones["dud_gt"] is None:
            milestones["dud_gt"] = gt

        sel = obs.get("select") or {}
        # context=0 is MAIN — must not use `or -1` (0 is falsy).
        raw_ctx = sel.get("context")
        ctx = int(raw_ctx) if raw_ctx is not None else -1
        if ctx != MAIN:
            continue
        opts = [o for o in (sel.get("option") or []) if isinstance(o, dict)]
        if not opts:
            continue
        action = side.get("action")
        # Only count committed decisions (non-empty action) to skip window spam
        if not action:
            continue

        hand_ids = _ids(me.get("hand"))
        goals = classify_goals(me, opp, stadium_ids)
        paths = classify_paths(opts, hand_ids, goals, me)
        choice = choice_kind(action, opts, paths, hand_ids)
        bucket = stall_bucket(goals, paths, choice)
        if bucket:
            buckets[bucket] += 1

        live_goals = tuple(sorted(k for k, v in goals.items() if v))
        for g in live_goals:
            goal_hits[g] += 1
        for p in paths:
            path_hits[p] += 1

        # ability use milestone
        try:
            idx = int(action[0])
            if 0 <= idx < len(opts) and int(opts[idx].get("type") or -1) == ABILITY:
                if milestones["dud_ability_gt"] is None and DUDUNSPARCE in field_ids:
                    milestones["dud_ability_gt"] = gt
            if 0 <= idx < len(opts) and int(opts[idx].get("type") or -1) == ATTACK:
                if int(opts[idx].get("attackId") or 0) == JETTING and milestones["jetting_gt"] is None:
                    milestones["jetting_gt"] = gt
        except Exception:
            pass

        rows.append(
            {
                "si": si,
                "gt": gt,
                "goals": live_goals,
                "paths": sorted(paths),
                "choice": choice,
                "bucket": bucket,
                "hand_n": len(hand_ids),
                "hand": hand_ids[:8],
                "field": sorted(field_ids),
                "bench_n": len([c for c in (me.get("bench") or []) if c]),
            }
        )

    return {
        "milestones": milestones,
        "buckets": dict(buckets),
        "goal_hits": dict(goal_hits),
        "path_hits": dict(path_hits),
        "n_main": len(rows),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", type=int, default=55386951)
    ap.add_argument("--losses-only", action="store_true")
    ap.add_argument("--tag", default="midgame_dp_stall")
    args = ap.parse_args()

    fade = json.loads(
        (ROOT / f"data/kaggle_episodes/analysis_{args.sid}_fade.json").read_text()
    )
    sub = ROOT / f"data/kaggle_episodes/sub_{args.sid}"
    games = [g for g in fade["games"] if "PUBLIC" in (g.get("type") or "")]
    if args.losses_only:
        games = [g for g in games if not g["won"]]

    out_dir = ROOT / f"logs/diagnose_{args.tag}_{args.sid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_buckets = Counter()
    all_goals = Counter()
    all_paths = Counter()
    per_game = []
    examples = defaultdict(list)

    for g in games:
        eid = g["eid"]
        mi = 0 if g["seat"] == "A" else 1
        path = sub / f"episode-{eid}-replay.json"
        if not path.exists():
            continue
        r = scan_game(path, mi)
        for k, v in r["buckets"].items():
            all_buckets[k] += v
        for k, v in r["goal_hits"].items():
            all_goals[k] += v
        for k, v in r["path_hits"].items():
            all_paths[k] += v
        # pick first PATH_IGNORED / NO_PATH row as example
        for row in r["rows"]:
            b = row["bucket"]
            if b in ("PATH_IGNORED", "NO_PATH", "NO_GOAL") and len(examples[b]) < 8:
                examples[b].append({"eid": eid, "seat": g["seat"], **row})
        ms = r["milestones"]
        per_game.append(
            {
                "eid": eid,
                "seat": g["seat"],
                "won": g["won"],
                "tags": g["tags"],
                "buckets": r["buckets"],
                "n_main": r["n_main"],
                "milestones": ms,
                "dp_complete": bool(ms["munk_gt"] and ms["dark_gt"] and ms["placer_gt"]),
                "sa_started": bool(ms["snorunt_gt"] or ms["861_gt"]),
                "dud_drew": bool(ms["dud_ability_gt"]),
            }
        )

    n = len(per_game)
    dp_done = sum(1 for x in per_game if x["dp_complete"])
    sa_start = sum(1 for x in per_game if x["sa_started"])
    dud_drew = sum(1 for x in per_game if x["dud_drew"])
    munk_rate = sum(1 for x in per_game if x["milestones"]["munk_gt"] is not None) / n if n else 0
    dark_rate = sum(1 for x in per_game if x["milestones"]["dark_gt"] is not None) / n if n else 0
    placer_rate = sum(1 for x in per_game if x["milestones"]["placer_gt"] is not None) / n if n else 0

    report = {
        "sid": args.sid,
        "n_games": n,
        "losses_only": args.losses_only,
        "buckets": dict(all_buckets),
        "goal_hits": dict(all_goals),
        "path_hits": dict(all_paths),
        "dp_complete_rate": dp_done / n if n else 0,
        "sa_started_rate": sa_start / n if n else 0,
        "dud_drew_rate": dud_drew / n if n else 0,
        "munk_rate": munk_rate,
        "dark_rate": dark_rate,
        "placer_rate": placer_rate,
        "per_game": per_game,
        "examples": {k: v for k, v in examples.items()},
    }
    (out_dir / "scan.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # Markdown
    tot = sum(all_buckets.values()) or 1
    lines = [
        f"# Midgame DP / 第二打手 / 空转扫描 — `{args.sid}`",
        "",
        f"- 样本：公局{'负局' if args.losses_only else ''} **{n}**",
        f"- MAIN 决策桶合计：{tot}",
        "",
        "## 空转桶（Mega 后 MAIN）",
        "",
        "| bucket | n | 占比 | 含义 |",
        "|---|---:|---:|---|",
        f"| PATH_IGNORED | {all_buckets['PATH_IGNORED']} | {all_buckets['PATH_IGNORED']/tot:.0%} | **有目标且有路径，却 END/杂项** |",
        f"| NO_PATH | {all_buckets['NO_PATH']} | {all_buckets['NO_PATH']/tot:.0%} | 有目标，但选项里没有推进手段 |",
        f"| NO_GOAL | {all_buckets['NO_GOAL']} | {all_buckets['NO_GOAL']/tot:.0%} | 板面判无中盘目标却空过 |",
        f"| PROGRESS | {all_buckets['PROGRESS']} | {all_buckets['PROGRESS']/tot:.0%} | 选了推进选项 |",
        "",
        "## DP / 第二打手兑现（负局终局里程碑）",
        "",
        f"| 里程碑 | 率 |",
        f"|---|---:|",
        f"| Munk 上场 | {munk_rate:.0%} |",
        f"| Munk+暗能 | {dark_rate:.0%} |",
        f"| Placer(104/废墟) | {placer_rate:.0%} |",
        f"| DP 三件套齐 | {dp_done/n if n else 0:.0%} |",
        f"| 第二打手启动(雪童/861) | {sa_start/n if n else 0:.0%} |",
        f"| 66 抽过牌 | {dud_drew/n if n else 0:.0%} |",
        "",
        "## 目标出现频率（MAIN 决策上）",
        "",
        "| goal | hits |",
        "|---|---:|",
    ]
    for k, v in all_goals.most_common():
        lines.append(f"| {k} | {v} |")
    lines += [
        "",
        "## 路径出现频率",
        "",
        "| path | hits |",
        "|---|---:|",
    ]
    for k, v in all_paths.most_common():
        lines.append(f"| {k} | {v} |")

    lines += ["", "## 样例（PATH_IGNORED）", ""]
    for ex in examples.get("PATH_IGNORED", [])[:6]:
        lines.append(
            f"- `{ex['eid']}` seat={ex['seat']} T{ex['gt']} goals={list(ex['goals'])} "
            f"paths={ex['paths']} choice={ex['choice']} hand={ex['hand']} field={ex['field']}"
        )
    lines += ["", "## 样例（NO_PATH）", ""]
    for ex in examples.get("NO_PATH", [])[:6]:
        lines.append(
            f"- `{ex['eid']}` seat={ex['seat']} T{ex['gt']} goals={list(ex['goals'])} "
            f"paths={ex['paths']} choice={ex['choice']} hand={ex['hand']} field={ex['field']}"
        )

    # Verdict
    pi = all_buckets["PATH_IGNORED"] / tot
    np_ = all_buckets["NO_PATH"] / tot
    if pi >= np_ and pi >= 0.25:
        verdict = (
            "**主因偏「有目标有路径却不走」（PATH_IGNORED）** — "
            "决策/优先级问题，不是牌库没目标。"
        )
    elif np_ > pi and np_ >= 0.25:
        verdict = (
            "**主因偏「有目标无路径」（NO_PATH）** — "
            "手牌/检索盖不住 DP 或第二打手缺口。"
        )
    else:
        verdict = "**混合型**：PATH_IGNORED 与 NO_PATH 都显著，需分目标拆开。"

    lines += [
        "",
        "## 判决",
        "",
        verdict,
        "",
        f"- DP 三件套齐仅 **{dp_done/n if n else 0:.0%}**；第二打手启动 **{sa_start/n if n else 0:.0%}**；66 抽过 **{dud_drew/n if n else 0:.0%}**。",
        "- `no_861` 标签仍勿当因果；看本表的 SA 启动率与 PATH_IGNORED 里是否含 SNORUNT/EVOLVE_861。",
        "",
        f"原始：[`scan.json`](scan.json)",
    ]
    (out_dir / "DIAGNOSE.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {out_dir / 'DIAGNOSE.md'}")
    print(f"buckets {dict(all_buckets)}")
    print(f"dp_complete={dp_done}/{n} sa={sa_start}/{n} dud_drew={dud_drew}/{n}")
    print(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
