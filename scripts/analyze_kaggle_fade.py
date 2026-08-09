#!/usr/bin/env python3
"""Fade-analyze a Kaggle submission's public episodes (SOP online review).

Reads:  data/kaggle_episodes/sub_<SID>/episode-*-replay.json
        data/kaggle_episodes/meta/episodes_<SID>.csv (optional types)
Writes: data/kaggle_episodes/analysis_<SID>_fade.json
        data/kaggle_episodes/review_<tag>_<SID>/FADE_ANALYSIS.md
        data/kaggle_episodes/review_<tag>_<SID>/OL_HITS.md

Usage:
  python3 scripts/analyze_kaggle_fade.py --sid 55312234 --score 406.8 \\
    --label "WaveU_U5.1" --vs 55299191
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
US = "Ying Peter"

# Card / attack IDs
STARYU, MEGA_STARMIE = 1030, 1031
FROSLASS, MEGA_FROSLASS = 104, 861
DUDUNSPARCE, DUNSPARCE_A, DUNSPARCE_B = 66, 65, 305
MUNKIDORI, BUDEW, SNORUNT = 112, 235, 860
ULTRA_BALL, NIGHT_STRETCHER, BOSS = 1121, 1097, 1182
WATER_BASIC = 3
ATK_WATER_GUN, ATK_JETTING = 1486, 1487
ATK_RESENTFUL = 1240  # approx; also match card 861 attacks

NAME = {
    STARYU: "Staryu",
    MEGA_STARMIE: "Mega Starmie ex",
    FROSLASS: "Froslass",
    MEGA_FROSLASS: "Mega Froslass ex",
    DUDUNSPARCE: "Dudunsparce",
    DUNSPARCE_A: "Dunsparce",
    DUNSPARCE_B: "Dunsparce",
    MUNKIDORI: "Munkidori",
    BUDEW: "Budew",
    SNORUNT: "Snorunt",
    ULTRA_BALL: "Ultra Ball",
    NIGHT_STRETCHER: "Night Stretcher",
    BOSS: "Boss's Orders",
    WATER_BASIC: "Basic {W} Energy",
}

ARCH_RULES: list[tuple[str, frozenset[int] | frozenset[str]]] = [
    ("starmie_mirror", frozenset({MEGA_STARMIE, STARYU})),
    ("alakazam", frozenset({65, 66, 305})),  # weak; refined below by name
]


def iter_raw_logs(d: dict):
    """Yield every log dict from every seat observation (sliding windows overlap)."""
    for step in d.get("steps") or []:
        for side in step:
            for lg in (side.get("observation") or {}).get("logs") or []:
                if isinstance(lg, dict):
                    yield lg


def uniq_logs(d: dict) -> list[dict]:
    """Serial-uniq for non-attack events. Prefer keeping type=15 attack rows.

    Sliding windows often re-emit the same serial with a later non-attack payload;
    overwriting blindly deleted Jetting (55381818: 9/12 false zero-jet losses).
    """
    by: dict[int, dict] = {}
    for lg in iter_raw_logs(d):
        s = lg.get("serial")
        if s is None:
            continue
        sid = int(s)
        prev = by.get(sid)
        if prev is None:
            by[sid] = lg
            continue
        # Never let a non-attack clobber an attack at the same serial.
        if prev.get("type") == 15 and lg.get("type") != 15:
            continue
        by[sid] = lg
    return sorted(by.values(), key=lambda x: int(x["serial"]))


def uniq_attacks(d: dict, player_index: int | None = None) -> list[dict]:
    """Dedupe attacks by (attackId, serial); optional filter by playerIndex."""
    by: dict[tuple[int, int], dict] = {}
    for lg in iter_raw_logs(d):
        if lg.get("type") != 15:
            continue
        aid, serial = lg.get("attackId"), lg.get("serial")
        if aid is None or serial is None:
            continue
        key = (int(aid), int(serial))
        prev = by.get(key)
        if prev is None:
            by[key] = lg
            continue
        # Prefer the copy that carries a playerIndex (some windows omit it).
        if prev.get("playerIndex") is None and lg.get("playerIndex") is not None:
            by[key] = lg
    out = list(by.values())
    if player_index is not None:
        out = [lg for lg in out if lg.get("playerIndex") == player_index]
    return sorted(out, key=lambda x: int(x["serial"]))


def field_has_card(d: dict, player_index: int, card_id: int) -> bool:
    """True when card_id appears on Active/Bench in any step observation."""
    for step in d.get("steps") or []:
        if not step:
            continue
        # Prefer our seat's observation; fall back to any side with players.
        sides = []
        if 0 <= player_index < len(step):
            sides.append(step[player_index])
        sides.extend(step)
        for side in sides:
            cur = (side.get("observation") or {}).get("current") or {}
            players = cur.get("players") or []
            if player_index >= len(players) or not players[player_index]:
                continue
            pl = players[player_index]
            for p in list(pl.get("active") or []) + list(pl.get("bench") or []):
                if p and p.get("id") == card_id:
                    return True
    return False


def card_names_from_logs(logs: list[dict], pi: int) -> list[str]:
    """Best-effort opponent card names via known IDs seen for that player."""
    seen: list[str] = []
    for lg in logs:
        if lg.get("playerIndex") != pi:
            continue
        cid = lg.get("cardId")
        if cid in NAME and NAME[cid] not in seen:
            seen.append(NAME[cid])
    return seen


def classify_arch(opp_top: list[str], opp_ids: set[int]) -> str:
    blob = " ".join(opp_top).lower()
    if "mega starmie" in blob or (MEGA_STARMIE in opp_ids and STARYU in opp_ids):
        if "froslass" in blob or MEGA_FROSLASS in opp_ids:
            return "starmie_mirror"
        return "starmie_mirror"
    if "alakazam" in blob or "kadabra" in blob or "abra" in blob:
        return "alakazam"
    if "dragapult" in blob or "dreepy" in blob or "drakloak" in blob:
        return "dragapult"
    if "lucario" in blob or "fighting gong" in blob or "solrock" in blob:
        return "lucario_fighting"
    if "abomasnow" in blob or "kyogre" in blob or "snover" in blob:
        return "abomasnow_kyogre"
    if "ogerpon" in blob or "raging bolt" in blob:
        return "ogerpon"
    if "garchomp" in blob or "cynthia" in blob or "gible" in blob:
        return "cynthia_garchomp"
    if "marnie" in blob or "impidimp" in blob:
        return "marnie_froslass_munk"
    if "team rocket" in blob or "tarountula" in blob or "ariana" in blob:
        return "team_rocket"
    if "charizard" in blob:
        return "charizard"
    if "mismagius" in blob:
        return "mismagius"
    if "okidogi" in blob:
        return "okidogi"
    if "typhlosion" in blob or "ethan" in blob:
        return "ethan_typhlosion"
    return "other"


def analyze_game(path: Path, ep_type: str | None) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    eid = int(path.name.split("-")[1])
    names = d["info"]["TeamNames"]
    if US not in names:
        raise ValueError(f"{eid}: no {US} in {names}")
    mi = names.index(US)
    oi = 1 - mi
    rewards = d.get("rewards") or [0, 0]
    won = bool(rewards[mi] and rewards[mi] > 0)

    logs = uniq_logs(d)
    ours = [lg for lg in logs if lg.get("playerIndex") == mi]
    opps = [lg for lg in logs if lg.get("playerIndex") == oi]
    # Attacks: (attackId, serial) — serial-only uniq was deleting Jetting rows.
    our_atks = uniq_attacks(d, mi)

    # Sliding log windows often drop EVOLVE; count field presence / KO / attacks.
    def _on_field(lg: dict, cid: int) -> bool:
        return lg.get("cardId") == cid and (
            lg.get("type") in (12, 15)
            or lg.get("fromArea") in (4, 5)  # ACTIVE / BENCH
            or lg.get("toArea") in (4, 5)
        )

    jetting = sum(1 for lg in our_atks if lg.get("attackId") == ATK_JETTING)
    ever_mega = (
        field_has_card(d, mi, MEGA_STARMIE)
        or any(_on_field(lg, MEGA_STARMIE) for lg in ours)
        or jetting > 0
    )
    ever_861 = field_has_card(d, mi, MEGA_FROSLASS) or any(
        _on_field(lg, MEGA_FROSLASS) for lg in ours
    )
    mega_ko_active = any(
        lg.get("type") == 6
        and lg.get("cardId") == MEGA_STARMIE
        and lg.get("fromArea") == 4
        and lg.get("toArea") == 3
        for lg in ours
    )
    # True UB burn: hand → discard Mega after Ultra Ball.
    ub_burn_mega = 0
    for i, lg in enumerate(ours):
        if lg.get("type") == 10 and lg.get("cardId") == ULTRA_BALL:
            for lg2 in ours[i + 1 : i + 12]:
                if (
                    lg2.get("type") == 6
                    and lg2.get("cardId") == MEGA_STARMIE
                    and lg2.get("fromArea") == 2
                    and lg2.get("toArea") == 3
                ):
                    ub_burn_mega += 1
                    break
    ever_dun = any(lg.get("cardId") in (DUNSPARCE_A, DUNSPARCE_B) for lg in ours)
    ever_dud = any(
        (lg.get("type") == 12 and lg.get("cardId") == DUDUNSPARCE)
        or (lg.get("type") == 6 and lg.get("cardId") == DUDUNSPARCE and lg.get("toArea") in (4, 5))
        for lg in ours
    )
    evo66 = sum(
        1 for lg in ours if lg.get("type") == 12 and lg.get("cardId") == DUDUNSPARCE
    )
    # ability on 66: type 16 often; also type 10 on 66 rare
    abil66 = sum(
        1
        for lg in ours
        if lg.get("cardId") == DUDUNSPARCE and lg.get("type") in (16, 14)
    )
    boss_n = sum(1 for lg in ours if lg.get("type") == 10 and lg.get("cardId") == BOSS)
    st_atk = sum(
        1 for lg in our_atks if lg.get("cardId") in (STARYU, MEGA_STARMIE)
    )
    mf_atk = sum(1 for lg in our_atks if lg.get("cardId") == MEGA_FROSLASS)
    water_gun = sum(
        1
        for lg in our_atks
        if lg.get("attackId") == ATK_WATER_GUN and lg.get("cardId") == STARYU
    )
    any_atk = len(our_atks)
    ub_n = sum(1 for lg in ours if lg.get("type") == 10 and lg.get("cardId") == ULTRA_BALL)
    # Night stretcher recover water while Mega previously discarded from hand/field
    ns_water_over_mega = 0
    mega_disc = False
    for lg in ours:
        if (
            lg.get("type") == 6
            and lg.get("toArea") == 3
            and lg.get("cardId") == MEGA_STARMIE
            and lg.get("fromArea") in (2, 4, 5)
        ):
            mega_disc = True
        if (
            mega_disc
            and lg.get("type") == 6
            and lg.get("fromArea") == 3
            and lg.get("toArea") == 2
            and lg.get("cardId") == WATER_BASIC
        ):
            ns_water_over_mega += 1
            mega_disc = False
    # water onto active staryu with another staryu (C1 heuristic via attaches)
    water_to_staryu = sum(
        1
        for lg in ours
        if lg.get("type") == 11
        and lg.get("cardId") == WATER_BASIC
        and lg.get("cardIdTarget") == STARYU
    )

    # mega turn: first evolve 1031 serial order among our evolves — approximate as count of prior our attacks+plays
    mega_turn = None
    turn_proxy = 0
    for lg in ours:
        if lg.get("type") in (10, 12, 15, 8):
            turn_proxy += 1
        if lg.get("type") == 12 and lg.get("cardId") == MEGA_STARMIE and mega_turn is None:
            mega_turn = max(1, turn_proxy // 3)  # rough

    # Better mega_turn: use step index where evolve appears
    for si, step in enumerate(d.get("steps") or []):
        for side in step:
            for lg in (side.get("observation") or {}).get("logs") or []:
                if (
                    lg.get("playerIndex") == mi
                    and lg.get("type") == 12
                    and lg.get("cardId") == MEGA_STARMIE
                ):
                    mega_turn = max(1, si // 2)
                    break
            else:
                continue
            break
        else:
            continue
        break

    opp_ids = {lg.get("cardId") for lg in opps if lg.get("cardId")}
    opp_top = card_names_from_logs(opps, oi)[:8]
    # enrich opp_top from configuration? skip
    arch = classify_arch(opp_top, {x for x in opp_ids if isinstance(x, int)})

    tags: list[str] = []
    if boss_n == 0:
        tags.append("zero_boss")
    # Any type=15 after (attackId, serial) dedupe — not serial-clobbered ours.
    if any_atk == 0:
        tags.append("no_attack")
    if not ever_mega:
        tags.append("no_mega")
    if not ever_861:
        tags.append("no_861")
    if ever_861 and mf_atk == 0:
        tags.append("861_no_fire")
    if not ever_dun:
        tags.append("no_dun")
    if ever_dun and evo66 == 0:
        tags.append("dun_no_66")
    if evo66 > 0 and abil66 == 0:
        tags.append("dud_no_ability")
    if water_gun:
        tags.append("ol_a1_water_gun")
    if ub_burn_mega:
        tags.append("ol_b2_ub_burn_mega")
    if ns_water_over_mega:
        tags.append("ol_d1_ns_water")
    if water_to_staryu >= 2:
        tags.append("ol_c1_water_staryu_x2")

    opp_name = names[oi]
    return {
        "eid": eid,
        "type": ep_type or "?",
        "won": won,
        "opp": opp_name,
        "arch": arch,
        "opp_top": opp_top,
        "seat": "A" if mi == 0 else "B",
        "mega_turn": mega_turn,
        "ever_mega": ever_mega,
        "ever_861": ever_861,
        "ever_dun": ever_dun,
        "ever_dud": ever_dud or evo66 > 0,
        "dud_ability": abil66 > 0,
        "boss_n": boss_n,
        "st_atk": st_atk,
        "mf_atk": mf_atk,
        "any_atk": any_atk,
        "jetting": jetting,
        "water_gun": water_gun,
        "ub_n": ub_n,
        "ub_burn_mega": ub_burn_mega,
        "mega_ko_active": mega_ko_active,
        "evo66": evo66,
        "tags": tags,
        "n_our_logs": len(ours),
    }


def load_ep_types(sid: int) -> dict[int, str]:
    csv = ROOT / "data/kaggle_episodes/meta" / f"episodes_{sid}.csv"
    out: dict[int, str] = {}
    if not csv.exists():
        return out
    for line in csv.read_text().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 5:
            out[int(parts[0])] = parts[4]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sid", type=int, required=True)
    ap.add_argument("--score", type=float, required=True)
    ap.add_argument("--label", default="fade")
    ap.add_argument("--vs", type=int, default=None, help="prior submission id for delta")
    args = ap.parse_args()

    sub = ROOT / "data/kaggle_episodes" / f"sub_{args.sid}"
    types = load_ep_types(args.sid)
    games = []
    for p in sorted(sub.glob("episode-*-replay.json")):
        eid = int(p.name.split("-")[1])
        g = analyze_game(p, types.get(eid))
        games.append(g)

    # Prefer public episodes for WR headline
    public = [g for g in games if "PUBLIC" in (g.get("type") or "")]
    pool = public or games
    wins = sum(1 for g in pool if g["won"])
    losses = [g for g in pool if not g["won"]]
    n = len(pool)
    wr = wins / n if n else 0.0

    by_arch: dict[str, dict] = {}
    for g in pool:
        a = by_arch.setdefault(g["arch"], {"n": 0, "wins": 0})
        a["n"] += 1
        a["wins"] += int(g["won"])
    for a, v in by_arch.items():
        v["wr"] = v["wins"] / v["n"] if v["n"] else 0.0

    loss_tags = Counter()
    for g in losses:
        for t in g["tags"]:
            loss_tags[t] += 1

    mega_games = [g for g in pool if g["ever_mega"]]
    structure = {
        "mega_rate": sum(g["ever_mega"] for g in pool) / n if n else 0,
        "mega_t3_rate": sum(
            1 for g in pool if g["mega_turn"] is not None and g["mega_turn"] <= 3
        )
        / n
        if n
        else 0,
        "ever_861_rate": sum(g["ever_861"] for g in pool) / n if n else 0,
        "861_fire_among_861": (
            sum(1 for g in pool if g["ever_861"] and g["mf_atk"] > 0)
            / max(1, sum(g["ever_861"] for g in pool))
        ),
        "boss_rate": sum(1 for g in pool if g["boss_n"] > 0) / n if n else 0,
        "avg_boss": sum(g["boss_n"] for g in pool) / n if n else 0,
        "evo66_rate": sum(1 for g in pool if g["evo66"] > 0) / n if n else 0,
        "water_gun_games": sum(1 for g in pool if g["water_gun"] > 0),
        "ub_burn_mega_games": sum(1 for g in pool if g["ub_burn_mega"] > 0),
        "mega_ko_no_jet_losses": sum(
            1
            for g in losses
            if g.get("mega_ko_active") and g.get("jetting", 0) == 0
        ),
        "zero_jetting_losses": sum(1 for g in losses if g.get("jetting", 0) == 0),
        "no_attack_losses": sum(1 for g in losses if g.get("any_atk", 0) == 0),
        "wr_with_mega": (
            sum(g["won"] for g in mega_games) / len(mega_games) if mega_games else 0
        ),
        "wr_no_mega": (
            sum(g["won"] for g in pool if not g["ever_mega"])
            / max(1, sum(1 for g in pool if not g["ever_mega"]))
        ),
        "seat_a_wr": (
            sum(g["won"] for g in pool if g["seat"] == "A")
            / max(1, sum(1 for g in pool if g["seat"] == "A"))
        ),
        "seat_b_wr": (
            sum(g["won"] for g in pool if g["seat"] == "B")
            / max(1, sum(1 for g in pool if g["seat"] == "B"))
        ),
    }

    out = {
        "submission": args.sid,
        "score": args.score,
        "label": args.label,
        "n": n,
        "n_all": len(games),
        "wr": wr,
        "wins": wins,
        "losses": len(losses),
        "by_arch": by_arch,
        "loss_tags": dict(loss_tags.most_common()),
        "structure": structure,
        "games": games,
    }

    if args.vs:
        prev_path = ROOT / "data/kaggle_episodes" / f"analysis_{args.vs}_fade.json"
        if prev_path.exists():
            prev = json.loads(prev_path.read_text())
            out[f"vs_{args.vs}"] = {
                "prev_score": prev.get("score"),
                "prev_wr": prev.get("wr"),
                "prev_n": prev.get("n"),
                "delta_wr_pp": round((wr - (prev.get("wr") or 0)) * 100, 1),
                "delta_score": round(args.score - (prev.get("score") or 0), 1),
                "prev_loss_tags": prev.get("loss_tags"),
            }

    json_path = ROOT / "data/kaggle_episodes" / f"analysis_{args.sid}_fade.json"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    review = ROOT / "data/kaggle_episodes" / f"review_{args.label}_{args.sid}"
    review.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# {args.label} `{args.sid}` 线上对战分析（SOP-D）",
        "",
        f"公局 **{n}**，胜率 **{wins}/{n} = {wr:.1%}**；公开分 **{args.score}**。",
        "",
        "## 结构指标",
        "",
        f"- Mega 上场率：{structure['mega_rate']:.0%}（≤T3 代理：{structure['mega_t3_rate']:.0%}）",
        f"- 861 上场率：{structure['ever_861_rate']:.0%}（其中开火：{structure['861_fire_among_861']:.0%}）",
        f"- Boss 出场率：{structure['boss_rate']:.0%}（场均 {structure['avg_boss']:.2f}）",
        f"- evo66 率：{structure['evo66_rate']:.0%}",
        f"- seat A WR：{structure['seat_a_wr']:.0%}｜seat B WR：{structure['seat_b_wr']:.0%}",
        f"- 有 Mega 时胜率：{structure['wr_with_mega']:.0%}｜无 Mega：{structure['wr_no_mega']:.0%}",
        f"- **OL-A1 水枪局**：{structure['water_gun_games']}/{n}",
        f"- **OL-B2 UB 烧 Mega 局**：{structure['ub_burn_mega_games']}/{n}",
        f"- **负局真零 Jetting**（attackId=1487+serial 去重）：{structure['zero_jetting_losses']}/{len(losses)}",
        f"- **负局真 no_attack**（任意 type=15）：{structure['no_attack_losses']}/{len(losses)}",
        f"- mega_ko 且零 Jetting：{structure['mega_ko_no_jet_losses']}/{len(losses)}",
        "",
        "## 负局 Jetting 表（纠偏后）",
        "",
        "| eid | jetting | any_atk | ever_mega | tags |",
        "|---:|---:|---:|---|---|",
    ]
    for g in sorted(losses, key=lambda x: x["eid"]):
        tags = ",".join(g["tags"]) or "—"
        lines.append(
            f"| {g['eid']} | {g.get('jetting', 0)} | {g.get('any_atk', 0)} | "
            f"{g.get('ever_mega')} | `{tags}` |"
        )

    lines += [
        "",
        "## 分卡组",
        "",
        "| 对手 | 局数 | 胜率 |",
        "|---|---:|---:|",
    ]
    for arch, v in sorted(by_arch.items(), key=lambda x: (-x[1]["n"], x[0])):
        lines.append(f"| `{arch}` | {v['n']} | {v['wins']}/{v['n']} = {v['wr']:.0%} |")

    lines += [
        "",
        "## 败局标签（共现，非因果）",
        "",
        "| 标签 | 败局占比 |",
        "|---|---:|",
    ]
    for t, c in loss_tags.most_common():
        lines.append(f"| `{t}` | {c}/{len(losses)} = {c/max(1,len(losses)):.0%} |")

    # lift among pool
    lines += ["", "## 标签 lift（负局率 − 胜局率）", "", "| 标签 | P_loss | P_win | lift |", "|---|---:|---:|---:|"]
    win_games = [g for g in pool if g["won"]]
    all_tags = sorted({t for g in pool for t in g["tags"]})
    for t in all_tags:
        pl = sum(1 for g in losses if t in g["tags"]) / max(1, len(losses))
        pw = sum(1 for g in win_games if t in g["tags"]) / max(1, len(win_games))
        lines.append(f"| `{t}` | {pl:.0%} | {pw:.0%} | **{pl-pw:+.2f}** |")

    lines += ["", "## 败局明细", ""]
    for g in sorted(losses, key=lambda x: x["eid"]):
        tags = ",".join(g["tags"]) or "—"
        lines.append(
            f"- `{g['eid']}` seat={g['seat']} vs **{g['opp']}** (`{g['arch']}`) "
            f"megaT={g['mega_turn']} boss={g['boss_n']} st={g['st_atk']} mf={g['mf_atk']} "
            f"wg={g['water_gun']}｜tags={tags}"
        )
        if g["opp_top"]:
            lines.append(f"  - opp: {', '.join(g['opp_top'][:6])}")

    lines += [
        "",
        "## SOP-D 三问（草稿，见 DIAGNOSE 定稿）",
        "",
        "1. 负局最大头：见上表 lift>0 且高占比标签",
        "2. 决策链：优先核对 OL-A1/B2 是否 Wave U 回归；其次成型（no_mega/dun_no_66）",
        "3. 最小杠杆：等深挖 5–10 局后写假设卡，禁止直接开宽刀",
        "",
    ]
    (review / "FADE_ANALYSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # OL hits summary
    ol_lines = ["# OL hits (engine-log)", ""]
    for key, label in (
        ("water_gun", "OL-A1 Water Gun"),
        ("ub_burn_mega", "OL-B2 UB burn Mega"),
    ):
        hits = [g for g in pool if g.get(key)]
        ol_lines.append(f"## {label}: {len(hits)} games")
        for g in hits:
            ol_lines.append(
                f"- `{g['eid']}` won={g['won']} seat={g['seat']} arch={g['arch']} n={g[key]}"
            )
        ol_lines.append("")
    (review / "OL_HITS.md").write_text("\n".join(ol_lines), encoding="utf-8")

    print(f"wrote {json_path}")
    print(f"wrote {review / 'FADE_ANALYSIS.md'}")
    print(f"public n={n} WR={wr:.1%} ({wins}-{len(losses)}) score={args.score}")
    print("loss_tags", dict(loss_tags.most_common(12)))
    print(
        f"OL-A1 games={structure['water_gun_games']} "
        f"OL-B2 games={structure['ub_burn_mega_games']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
