#!/usr/bin/env python3
"""Scan H2H audit dirs for ONLINE_LEAK_PATTERNS (OL-A…F) and compute lift.

Reads:
  logs/h2h_audit_<tag>/manifest.json
  games/game_XXX.log   (Chinese combat_review_log)
  games/game_XXX.jsonl (optional raw engine logs — higher confidence)

Writes:
  OL_PATTERNS.md
  ol_hits.jsonl

Usage:
  python3 scripts/scan_ol_patterns.py --audit-dir logs/h2h_audit_waveU_online
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Engine IDs (same as opening_cards)
STARYU, MEGA_STARMIE, WATER_BASIC = 1030, 1031, 3
DUDUNSPARCE, DUNSPARCE_A, DUNSPARCE_B = 66, 65, 305
MUNKIDORI, BUDEW, ULTRA_BALL = 112, 235, 1121
NIGHT_STRETCHER, POKE_PAD, SNORUNT = 1097, 1152, 860
ATK_WATER_GUN = 1486

PATTERNS = (
    "OL-A1",  # Staryu Water Gun
    "OL-A2",  # retreat onto Staryu from Budew/Dunsparce
    "OL-B1",  # UB while Mega+water path held (heuristic)
    "OL-B2",  # UB forced-burn Mega (jsonl)
    "OL-C1",  # water onto Active Staryu with dry bench Staryu
    "OL-D1",  # Night Stretcher recovers water over Mega
    "OL-E1",  # Dudunsparce stuck (could evolve, never did)
    "OL-E2",  # empty bench after Mega with playable basics in hand
    "OL-E3",  # Pad searched Snorunt over Dudunsparce
    "OL-E4",  # Switch onto Staryu (heuristic from retreat/switch line)
)

KNIFED = frozenset({"OL-A1", "OL-A2", "OL-B1", "OL-B2", "OL-C1", "OL-D1", "OL-E1"})
WATCH = frozenset({"OL-E2", "OL-E3", "OL-E4"})


@dataclass
class Hit:
    pattern: str
    game_i: int
    cur_win: bool | None
    seat: str
    conf: str  # high | med | low
    hint: str
    log_path: str | None = None


@dataclass
class GameScan:
    i: int
    cur_win: bool | None
    seat: str
    log_path: str | None
    jsonl_path: str | None
    hits: list[Hit] = field(default_factory=list)
    scanned: bool = False


_RE_OUR_TURN = re.compile(r"^【我方-T(\d+)】")
_RE_OPP_TURN = re.compile(r"^【对手-T(\d+)】")
_RE_FIELD = re.compile(
    r"场上:\s*战斗场=([^\s(]+)(?:\([^)]*\))?\s*替补=([^\s]*)"
)
_RE_HAND = re.compile(r"回合开始手牌:\s*(.+)$")
_RE_WATER_GUN = re.compile(r"\[攻击\]\s*海星星\s*使用\s*Water Gun")
_RE_OPP_PREFIX = re.compile(r"对手")
_RE_UB = re.compile(r"\[操作\]\s*使用\s*高级球")
_RE_ATTACH_WATER_STARYU = re.compile(r"\[贴能\]\s*基本水能量\s*→\s*海星星")
_RE_RETREAT_TO_STARYU = re.compile(
    r"\[撤退/交替\]\s*(含羞苞|土龙弟弟)\s*⇄\s*海星星"
)
_RE_SWITCH_TO_STARYU = re.compile(
    r"\[撤退/交替\]\s*\S+\s*⇄\s*海星星"
)
_RE_NS = re.compile(r"\[操作\]\s*使用\s*夜之伸展器")
_RE_RECOVER = re.compile(r"\[回收\]\s*弃牌区\s*→\s*手牌\s*←\s*(.+)$")
_RE_EVOLVE_66 = re.compile(r"\[进化\]\s*土龙弟弟\s*→\s*土龙节节")
_RE_PAD = re.compile(r"\[操作\]\s*使用\s*宝可梦手环")
_RE_SEARCH_TO_HAND = re.compile(
    r"(?:\[检索\]|\[移动\])\s*.*←\s*(.+)$|\[移动\]\s*(.+)\s*牌库\s*→\s*手牌"
)
_RE_PLAY_BASIC = re.compile(r"\[放置\]\s*(愿增猿|土龙弟弟|土龙节节|含羞苞)\s*上场")
_RE_EVOLVE_MEGA = re.compile(r"\[进化\]\s*海星星\s*→\s*Mega 大海星")
_RE_DISCARD = re.compile(r"\[丢弃\]\s*(.+)$")
_RE_MOVE_TO_HAND = re.compile(r"\[移动\]\s*(.+?)\s*牌库\s*→\s*手牌")
_MEGA_STARMIE_ZH = "Mega 大海星"  # matches "Mega 大海星 ex"


def _parse_bench(bench_raw: str) -> list[str]:
    if not bench_raw or bench_raw in ("空", "—", "-"):
        return []
    # strip HP suffixes like 海星星(HP70)
    parts = []
    for tok in bench_raw.split("/"):
        name = tok.split("(")[0].strip()
        if name:
            parts.append(name)
    return parts


def _scan_chinese_log(text: str, meta: GameScan) -> list[Hit]:
    hits: list[Hit] = []
    lines = text.splitlines()
    our_section = False
    turn = 0
    active = ""
    bench: list[str] = []
    hand_items: list[str] = []
    e1_cooccur_turn: int | None = None
    ever_evolve_66 = False
    ever_mega = False
    mega_turn: int | None = None
    empty_bench_after_mega = 0
    hand_basic_after_mega = False
    pad_pending = False
    ns_pending = False
    ub_pending = False
    ub_discards: list[str] = []
    mega_on_field = False
    mega_left_to_discard = False  # was on field, then gone (KO / prize) — offline
    going_first: bool | None = None

    def add(pattern: str, conf: str, hint: str) -> None:
        hits.append(
            Hit(
                pattern=pattern,
                game_i=meta.i,
                cur_win=meta.cur_win,
                seat=meta.seat,
                conf=conf,
                hint=hint,
                log_path=meta.log_path,
            )
        )

    # Header: we_are_a + first 【我方-T1】 before any opp turn ⇒ going first
    for line in lines[:20]:
        if line.startswith("// we_are_a="):
            # seat alone doesn't tell turn order; infer below
            pass

    for line in lines:
        raw = line.strip()
        if raw.startswith("// we_are_a="):
            continue

        m_our = _RE_OUR_TURN.match(raw)
        if m_our:
            our_section = True
            turn = int(m_our.group(1))
            pad_pending = False
            ns_pending = False
            ub_pending = False
            ub_discards = []
            if going_first is None and turn == 1:
                going_first = True
            continue
        if _RE_OPP_TURN.match(raw):
            if going_first is None:
                going_first = False
            our_section = False
            pad_pending = False
            ns_pending = False
            ub_pending = False
            continue
        if not our_section:
            continue

        hm = _RE_HAND.search(line)
        if hm:
            hand_items = [x.strip() for x in hm.group(1).split(",") if x.strip()]
            continue

        fm = _RE_FIELD.search(line)
        if fm:
            active = fm.group(1)
            bench = _parse_bench(fm.group(2))
            duns_field = ("土龙弟弟" in active) or any("土龙弟弟" in b for b in bench)
            hand66 = any("土龙节节" in h for h in hand_items)
            if hand66 and duns_field and e1_cooccur_turn is None:
                e1_cooccur_turn = turn
            has_mega = _MEGA_STARMIE_ZH in active or any(
                _MEGA_STARMIE_ZH in b for b in bench
            )
            if mega_on_field and not has_mega:
                mega_left_to_discard = True
            mega_on_field = has_mega
            if has_mega:
                ever_mega = True
                mega_left_to_discard = False
                if mega_turn is None:
                    mega_turn = turn
            if ever_mega and not bench:
                empty_bench_after_mega += 1
                joined = "".join(hand_items)
                if any(x in joined for x in ("愿增猿", "土龙弟弟", "含羞苞")):
                    hand_basic_after_mega = True
            continue

        if _RE_EVOLVE_MEGA.search(line) and "对手" not in line:
            ever_mega = True
            if mega_turn is None:
                mega_turn = turn
            continue

        if _RE_EVOLVE_66.search(line) and "对手" not in line:
            ever_evolve_66 = True
            continue

        if _RE_WATER_GUN.search(line) and "对手" not in line:
            add("OL-A1", "med", f"T{turn}: Water Gun on our Staryu (zh log)")
            continue

        if _RE_RETREAT_TO_STARYU.search(line) and "对手" not in line:
            conf = "med"
            hint = f"T{turn}: {raw}"
            if going_first and turn == 1 and "含羞苞" in line:
                conf = "high"
                hint += " [U5 subset: going-first My-T1 Budew]"
            add("OL-A2", conf, hint)
            continue

        if _RE_ATTACH_WATER_STARYU.search(line) and "对手" not in line:
            if active == "海星星" and any(b == "海星星" or b.startswith("海星星") for b in bench):
                add(
                    "OL-C1",
                    "med",
                    f"T{turn}: water→Active Staryu with bench Staryu present",
                )
            continue

        if _RE_UB.search(line) and "对手" not in line:
            ub_pending = True
            ub_discards = []
            has_mega = any(_MEGA_STARMIE_ZH in h for h in hand_items)
            has_water = any("基本水能量" in h for h in hand_items)
            staryu_field = active == "海星星" or any(
                b == "海星星" or b.startswith("海星星") for b in bench
            )
            if has_mega and has_water and staryu_field:
                add(
                    "OL-B1",
                    "low",
                    f"T{turn}: UB with Mega+water in start-hand + Staryu on field "
                    f"(zh heuristic; confirm with jsonl)",
                )
            continue

        if ub_pending:
            dm = _RE_DISCARD.search(line)
            if dm and "对手" not in line:
                ub_discards.append(dm.group(1).strip())
                if _MEGA_STARMIE_ZH in dm.group(1):
                    mega_left_to_discard = True
                    add(
                        "OL-B2",
                        "med",
                        f"T{turn}: UB discarded {_MEGA_STARMIE_ZH} (zh)",
                    )
                    ub_pending = False
                continue
            if _RE_MOVE_TO_HAND.search(line):
                ub_pending = False
                continue

        if _RE_NS.search(line) and "对手" not in line:
            ns_pending = True
            continue

        if ns_pending:
            rm = _RE_RECOVER.search(line)
            if rm:
                got = rm.group(1).strip()
                if _MEGA_STARMIE_ZH in got:
                    mega_left_to_discard = False
                elif "基本水能量" in got and mega_left_to_discard and not mega_on_field:
                    add(
                        "OL-D1",
                        "med",
                        f"T{turn}: Night Stretcher recovered water while Mega offline",
                    )
                ns_pending = False
                continue

        if _RE_PAD.search(line) and "对手" not in line:
            pad_pending = True
            continue

        if pad_pending:
            mm = _RE_MOVE_TO_HAND.search(line)
            if mm:
                name = mm.group(1).strip()
                duns_field = ("土龙弟弟" in active) or any(
                    "土龙弟弟" in b for b in bench
                )
                # E3 watch: fetched Snorunt while Dunsparce already on field
                # (evolution line available; 节节 may have been in Pad options — low conf)
                if "雪童子" in name and duns_field:
                    add(
                        "OL-E3",
                        "low",
                        f"T{turn}: Pad→雪童子 while 土龙弟弟 on field "
                        f"(options not in zh log)",
                    )
                pad_pending = False
                continue

        if _RE_SWITCH_TO_STARYU.search(line) and "对手" not in line:
            if "愿增猿" in line:
                add("OL-E4", "med", f"T{turn}: {raw}")

    # E1: same-turn co-occurrence of hand 节节 + field 弟弟, never evolved
    if e1_cooccur_turn is not None and not ever_evolve_66:
        add(
            "OL-E1",
            "med",
            f"T{e1_cooccur_turn}+ hand had 土龙节节 with 土龙弟弟 on field, never evolved",
        )

    if ever_mega and empty_bench_after_mega >= 2 and hand_basic_after_mega:
        add(
            "OL-E2",
            "med",
            f"empty-bench field snaps after Mega≈{empty_bench_after_mega} "
            f"with playable basic in hand",
        )

    return hits


def _scan_jsonl(path: Path, meta: GameScan) -> list[Hit]:
    """High-confidence detectors from raw engine logs (our playerIndex)."""
    hits: list[Hit] = []
    our_pi = 0 if meta.seat == "A" else 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return hits

    events = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            continue

    def add(pattern: str, conf: str, hint: str) -> None:
        hits.append(
            Hit(
                pattern=pattern,
                game_i=meta.i,
                cur_win=meta.cur_win,
                seat=meta.seat,
                conf=conf,
                hint=hint,
                log_path=str(path),
            )
        )

    # Water gun
    for ev in events:
        if (
            ev.get("type") == 15
            and ev.get("playerIndex") == our_pi
            and ev.get("attackId") == ATK_WATER_GUN
            and ev.get("cardId") == STARYU
        ):
            add("OL-A1", "high", f"jsonl attackId=1486 card=1030")

    # UB discard Mega: play 1121 then two discards including 1031
    for i, ev in enumerate(events):
        if (
            ev.get("type") == 10
            and ev.get("playerIndex") == our_pi
            and ev.get("cardId") == ULTRA_BALL
        ):
            discarded = []
            for j in range(i + 1, min(i + 12, len(events))):
                e2 = events[j]
                if e2.get("playerIndex") != our_pi:
                    continue
                if e2.get("type") == 6 and e2.get("toArea") == 3:  # DISCARD
                    discarded.append(e2.get("cardId"))
                if e2.get("type") == 6 and e2.get("fromArea") == 1 and e2.get("toArea") == 2:
                    # search to hand
                    fetched = e2.get("cardId")
                    if MEGA_STARMIE in discarded:
                        add(
                            "OL-B2",
                            "high",
                            f"jsonl UB discarded Mega; fetched={fetched}",
                        )
                    break

    # Night stretcher: play 1097 then recover from discard
    for i, ev in enumerate(events):
        if (
            ev.get("type") == 10
            and ev.get("playerIndex") == our_pi
            and ev.get("cardId") == NIGHT_STRETCHER
        ):
            # look for move discard→hand
            mega_in_disc = False
            # scan recent discard zone membership is hard; check if Mega was
            # discarded earlier in the game
            for e0 in events[:i]:
                if (
                    e0.get("playerIndex") == our_pi
                    and e0.get("type") == 6
                    and e0.get("toArea") == 3
                    and e0.get("cardId") == MEGA_STARMIE
                ):
                    mega_in_disc = True
            for j in range(i + 1, min(i + 10, len(events))):
                e2 = events[j]
                if (
                    e2.get("playerIndex") == our_pi
                    and e2.get("type") == 6
                    and e2.get("fromArea") == 3
                    and e2.get("toArea") == 2
                ):
                    got = e2.get("cardId")
                    if mega_in_disc and got == WATER_BASIC:
                        add(
                            "OL-D1",
                            "high",
                            "jsonl Night Stretcher recovered water while Mega in discard",
                        )
                    break

    return hits


def _dedupe_hits(hits: list[Hit]) -> list[Hit]:
    """Prefer higher confidence per (game, pattern)."""
    rank = {"high": 3, "med": 2, "low": 1}
    best: dict[tuple[int, str], Hit] = {}
    for h in hits:
        key = (h.game_i, h.pattern)
        prev = best.get(key)
        if prev is None or rank[h.conf] > rank[prev.conf]:
            best[key] = h
    return list(best.values())


def scan_audit_dir(audit_dir: Path) -> tuple[list[GameScan], list[Hit], dict]:
    manifest_path = audit_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    games_meta = manifest.get("games") or []
    scans: list[GameScan] = []
    all_hits: list[Hit] = []

    for g in games_meta:
        i = int(g["i"])
        seat = "A" if g.get("cur_is_a") else "B"
        lp = g.get("log_path")
        log_path = (audit_dir / lp) if lp else None
        jsonl_path = audit_dir / "games" / f"game_{i:03d}.jsonl"
        if not jsonl_path.exists():
            jsonl_path = None

        gs = GameScan(
            i=i,
            cur_win=g.get("cur_win"),
            seat=seat,
            log_path=str(lp) if lp else None,
            jsonl_path=str(jsonl_path.relative_to(audit_dir)) if jsonl_path else None,
        )

        hits: list[Hit] = []
        if log_path and log_path.exists():
            gs.scanned = True
            hits.extend(_scan_chinese_log(log_path.read_text(encoding="utf-8"), gs))
        if jsonl_path is not None:
            gs.scanned = True
            hits.extend(_scan_jsonl(jsonl_path, gs))

        hits = _dedupe_hits(hits)
        gs.hits = hits
        all_hits.extend(hits)
        scans.append(gs)

    # Stats
    n = len(scans)
    n_win = sum(1 for s in scans if s.cur_win is True)
    n_loss = sum(1 for s in scans if s.cur_win is False)
    n_scanned = sum(1 for s in scans if s.scanned)
    n_scanned_win = sum(1 for s in scans if s.scanned and s.cur_win is True)
    n_scanned_loss = sum(1 for s in scans if s.scanned and s.cur_win is False)

    stats: dict = {
        "audit_dir": str(audit_dir),
        "tag": manifest.get("tag"),
        "n": n,
        "n_win": n_win,
        "n_loss": n_loss,
        "n_scanned": n_scanned,
        "n_scanned_win": n_scanned_win,
        "n_scanned_loss": n_scanned_loss,
        "has_jsonl": any(s.jsonl_path for s in scans),
        "patterns": {},
    }

    for pat in PATTERNS:
        g_hits = [h for h in all_hits if h.pattern == pat]
        games_hit = {h.game_i for h in g_hits}
        loss_hit = {h.game_i for h in g_hits if h.cur_win is False}
        win_hit = {h.game_i for h in g_hits if h.cur_win is True}
        # Lift among scanned games only
        p_loss = (len(loss_hit) / n_scanned_loss) if n_scanned_loss else 0.0
        p_win = (len(win_hit) / n_scanned_win) if n_scanned_win else 0.0
        lift = p_loss - p_win
        examples = sorted(loss_hit)[:8] or sorted(games_hit)[:5]
        confs = {h.conf for h in g_hits}
        stats["patterns"][pat] = {
            "games_hit": len(games_hit),
            "loss_hit": len(loss_hit),
            "win_hit": len(win_hit),
            "p_loss_scanned": round(p_loss, 4),
            "p_win_scanned": round(p_win, 4),
            "lift": round(lift, 4),
            "examples": [f"game_{i:03d}" for i in examples],
            "conf": ("high" if "high" in confs else ("med" if "med" in confs else ("low" if confs else "n/a"))),
            "knifed": pat in KNIFED,
            "watch": pat in WATCH,
        }

    return scans, all_hits, stats


def write_report(audit_dir: Path, stats: dict, hits: list[Hit]) -> None:
    lines = [
        f"# OL pattern scan — `{stats.get('tag')}`",
        "",
        f"- audit_dir: `{stats['audit_dir']}`",
        f"- n={stats['n']} (win={stats['n_win']} / loss={stats['n_loss']})",
        f"- scanned logs: **{stats['n_scanned']}** "
        f"(win={stats['n_scanned_win']} / loss={stats['n_scanned_loss']})",
        f"- jsonl present: {stats['has_jsonl']}",
        "",
        "> Lift = P(pattern|loss,scanned) − P(pattern|win,scanned). "
        "Only games with `.log`/`.jsonl` are in the denominator. "
        "Wave U knifed patterns should be near-zero; watch patterns need lift≫0 before a new knife.",
        "",
        "## Summary table",
        "",
        "| Pattern | knifed | games | loss | win | P_loss | P_win | lift | conf | examples |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for pat in PATTERNS:
        p = stats["patterns"][pat]
        flag = "U" if p["knifed"] else ("W" if p["watch"] else "")
        lines.append(
            f"| {pat} | {flag} | {p['games_hit']} | {p['loss_hit']} | {p['win_hit']} | "
            f"{p['p_loss_scanned']:.1%} | {p['p_win_scanned']:.1%} | "
            f"**{p['lift']:+.3f}** | {p['conf']} | {', '.join(p['examples'][:5]) or '—'} |"
        )

    lines += [
        "",
        "## Knifed regression (Wave U)",
        "",
        "> Status: `OK≈0` no hits; `LEAK` loss-rate≥5% **and** lift≥+0.05 "
        "(regression signal); `tag≠cause` hits exist but lift≤0 "
        "(same as Wave T UB-burn discipline); `rare` otherwise. "
        "OL-A2 U5 only covers going-first My-T1 Budew — other A2 hits are expected.",
        "",
    ]
    for pat in sorted(KNIFED):
        p = stats["patterns"][pat]
        if p["games_hit"] == 0:
            status = "OK≈0"
        elif p["p_loss_scanned"] >= 0.05 and p["lift"] >= 0.05:
            status = "LEAK"
        elif p["games_hit"] > 0 and p["lift"] <= 0:
            status = "tag≠cause"
        elif p["p_loss_scanned"] >= 0.05:
            status = "noisy (need jsonl / more win logs)"
        else:
            status = "rare"
        lines.append(
            f"- **{pat}**: {status} — loss_hit={p['loss_hit']} "
            f"lift={p['lift']:+.3f} examples={p['examples'][:5]}"
        )

    lines += ["", "## Watch list (un-knifed)", ""]
    for pat in sorted(WATCH):
        p = stats["patterns"][pat]
        go = "GO-candidate" if p["lift"] >= 0.08 and p["loss_hit"] >= 3 else "hold"
        lines.append(
            f"- **{pat}**: {go} — loss_hit={p['loss_hit']} "
            f"lift={p['lift']:+.3f} examples={p['examples'][:5]}"
        )

    if stats["n_scanned_win"] < 10:
        lines += [
            "",
            f"> ⚠ Only {stats['n_scanned_win']} win logs in this audit "
            f"(`logs=losses` + short games). Lift denominators are biased; "
            "re-run with `--logs all` or `--save-jsonl` for cleaner win contrast.",
            "",
        ]

    lines += [
        "",
        "## How to re-run with high-confidence jsonl",
        "",
        "```bash",
        "PYTHONPATH=submission_starmie:submission_starmie/pilot \\",
        "  python3 scripts/h2h_loss_audit.py \\",
        "  --baseline /tmp/baseline_55202093_f07e541 \\",
        "  -n 200 --seed 140000 --tag waveU_ol_scan --logs losses --rules-only --save-jsonl",
        "",
        "python3 scripts/scan_ol_patterns.py --audit-dir logs/h2h_audit_waveU_ol_scan",
        "```",
        "",
        "Catalog: `references/rulebook/ONLINE_LEAK_PATTERNS_55299191.md`",
        "",
    ]
    (audit_dir / "OL_PATTERNS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (audit_dir / "ol_hits.jsonl").open("w", encoding="utf-8") as f:
        for h in sorted(hits, key=lambda x: (x.pattern, x.game_i)):
            f.write(
                json.dumps(
                    {
                        "pattern": h.pattern,
                        "game_i": h.game_i,
                        "game": f"game_{h.game_i:03d}",
                        "cur_win": h.cur_win,
                        "seat": h.seat,
                        "conf": h.conf,
                        "hint": h.hint,
                        "log_path": h.log_path,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--audit-dir",
        type=Path,
        default=ROOT / "logs/h2h_audit_waveU_online",
    )
    args = ap.parse_args()
    audit_dir = args.audit_dir
    if not audit_dir.is_absolute():
        audit_dir = ROOT / audit_dir
    if not (audit_dir / "manifest.json").exists():
        raise SystemExit(f"missing manifest: {audit_dir / 'manifest.json'}")

    _scans, hits, stats = scan_audit_dir(audit_dir)
    write_report(audit_dir, stats, hits)
    print(f"wrote {audit_dir / 'OL_PATTERNS.md'}")
    print(f"wrote {audit_dir / 'ol_hits.jsonl'} ({len(hits)} hit rows)")
    print(
        f"scanned {stats['n_scanned']}/{stats['n']} "
        f"(loss_logged={stats['n_scanned_loss']} win_logged={stats['n_scanned_win']})"
    )
    for pat in PATTERNS:
        p = stats["patterns"][pat]
        if p["games_hit"]:
            print(
                f"  {pat}: games={p['games_hit']} lift={p['lift']:+.3f} "
                f"loss={p['loss_hit']} conf={p['conf']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
