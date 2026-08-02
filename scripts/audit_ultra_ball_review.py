#!/usr/bin/env python3
"""Audit Ultra Ball plays from combat expert-review .log packs.

Parses NL logs, dedupes dual-render turns, auto-tags buckets A–E, writes:
  logs/ultra_ball_audit_<ts>/catalog.jsonl
  logs/ultra_ball_audit_<ts>/summary.md

Usage:
  python3 scripts/audit_ultra_ball_review.py \
    --pack-dir logs/combat_review_91000 \
    --out-dir logs/ultra_ball_audit_manual
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Card-name constants (ZH as rendered by combat_log_renderer)
MEGA_STARMIE = "Mega 大海星 ex"
STARYU = "海星星"
MEGA_FROSLASS = "Mega 大雪妖女 ex"
SNORUNT = "雪童子"
FROSLASS = "雪妖女"
MUNK = "愿增猿"
DUDUN = "土龙节节"
BUDEW = "含羞苞"
POFFIN = "Buddy-Buddy Poffin"
PAD = "宝可梦手环"
WATER = "基本水能量"
HILDA = "希尔达"
STRETCHER = "夜之伸展器"

PRE_MEGA_BAD = frozenset({
    MUNK, SNORUNT, FROSLASS, MEGA_FROSLASS, DUDUN, "土龙弟弟", BUDEW,
})
WHITELIST_PRE_MEGA = frozenset({MEGA_STARMIE, STARYU})
BASIC_FETCHABLE = frozenset({STARYU, SNORUNT, MUNK, BUDEW})  # Poffin/Pad territory
PAD_FETCHABLE = BASIC_FETCHABLE | frozenset({FROSLASS, DUDUN})
# Late-game 861 dig after Starmie leaves is legal — not bucket A.
HARVEST_OK = frozenset({MEGA_FROSLASS, SNORUNT})

RE_OUR_TURN = re.compile(r"^【我方-T(\d+)】\s*$")
RE_OPP_TURN = re.compile(r"^【对手-T(\d+)】\s*$")
RE_HAND = re.compile(r"^\s*回合开始手牌:\s*(.+)\s*$")
RE_FIELD = re.compile(r"^\s*场上:\s*(.+)\s*$")
RE_BALL = re.compile(r"^\s*\d+\.\s*\[操作\]\s*使用\s+高级球\s*$")
RE_DISCARD = re.compile(r"^\s*\d+\.\s*\[丢弃\]\s*(.+)\s*$")
RE_MOVE_SEARCH = re.compile(
    r"^\s*\d+\.\s*\[移动\]\s*(.+?)\s+牌库\s*→\s*手牌\s*$"
)
RE_RETRIEVE = re.compile(
    r"^\s*\d+\.\s*\[检索\]\s*(?:我方)?牌库\s*→\s*手牌\s*←\s*(.+)\s*$"
)


def _split_csv_zh(s: str) -> list[str]:
    parts = [p.strip() for p in s.split(",")]
    return [p for p in parts if p]


def _field_has(field: str, name: str) -> bool:
    return name in (field or "")


def _hand_has(hand: list[str], name: str) -> bool:
    return name in hand


def _parse_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    game = path.stem
    events: list[dict] = []

    in_our = False
    turn = 0
    hand: list[str] = []
    field = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        m_our = RE_OUR_TURN.match(line)
        m_opp = RE_OPP_TURN.match(line)
        if m_our:
            in_our = True
            turn = int(m_our.group(1))
            hand = []
            field = ""
            i += 1
            continue
        if m_opp:
            in_our = False
            i += 1
            continue
        if not in_our:
            i += 1
            continue

        m_hand = RE_HAND.match(line)
        if m_hand:
            hand = _split_csv_zh(m_hand.group(1))
            i += 1
            continue
        m_field = RE_FIELD.match(line)
        if m_field:
            field = m_field.group(1)
            i += 1
            continue

        if RE_BALL.match(line):
            discards: list[str] = []
            target = ""
            j = i + 1
            # Consume following discard / search lines belonging to this Ball.
            while j < len(lines):
                if RE_OUR_TURN.match(lines[j]) or RE_OPP_TURN.match(lines[j]):
                    break
                if RE_BALL.match(lines[j]):
                    break
                md = RE_DISCARD.match(lines[j])
                if md:
                    discards.append(md.group(1).strip())
                    j += 1
                    continue
                mm = RE_MOVE_SEARCH.match(lines[j])
                if mm and not target:
                    target = mm.group(1).strip()
                    j += 1
                    continue
                mr = RE_RETRIEVE.match(lines[j])
                if mr and not target:
                    target = mr.group(1).strip()
                    j += 1
                    continue
                # Stop at unrelated ops after we've seen discards+target, or
                # after a short look-ahead window.
                if discards and target:
                    break
                if j > i + 8:
                    break
                j += 1

            mega_on_field = _field_has(field, MEGA_STARMIE)
            staryu_on_field = _field_has(field, STARYU)
            mega_in_hand = _hand_has(hand, MEGA_STARMIE)
            staryu_in_hand = _hand_has(hand, STARYU)
            has_poffin = _hand_has(hand, POFFIN)
            has_pad = _hand_has(hand, PAD)
            target_in_hand = bool(target) and _hand_has(hand, target)

            events.append(
                {
                    "game": game,
                    "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                    "line": i + 1,
                    "turn": turn,
                    "target": target,
                    "discards": discards,
                    "hand": hand,
                    "field": field,
                    "mega_on_field": mega_on_field,
                    "staryu_on_field": staryu_on_field,
                    "mega_in_hand": mega_in_hand,
                    "staryu_in_hand": staryu_in_hand,
                    "has_poffin": has_poffin,
                    "has_pad": has_pad,
                    "target_in_hand": target_in_hand,
                }
            )
            i = j
            continue
        i += 1
    return events


def _dedupe(events: list[dict]) -> list[dict]:
    """Drop dual-render duplicates (T1≈T2, T3≈T4, …) within a game.

    Dual renders share target+discards but T2 often lacks hand/field headers.
    Keep the richer copy (non-empty hand preferred, then odd turn).
    """
    best: dict[tuple, dict] = {}

    def _richer(a: dict, b: dict) -> dict:
        score_a = (1 if a["hand"] else 0, 1 if a["field"] else 0, 1 if a["turn"] % 2 == 1 else 0)
        score_b = (1 if b["hand"] else 0, 1 if b["field"] else 0, 1 if b["turn"] % 2 == 1 else 0)
        return a if score_a >= score_b else b

    for ev in events:
        key = (ev["game"], ev["target"], tuple(ev["discards"]))
        if key in best:
            best[key] = _richer(best[key], ev)
        else:
            best[key] = ev
    # Preserve encounter order by first-seen line within each game.
    return sorted(best.values(), key=lambda e: (e["game"], e["line"]))


def _auto_tags(ev: dict) -> list[str]:
    tags: list[str] = []
    target = ev["target"]
    discards = set(ev["discards"])
    pre_mega = not ev["mega_on_field"]

    # A: pre-Mega dig DP / Froslass / Dudun (861 after Starmie dies is OK)
    harvest_ok = (
        pre_mega
        and not ev["mega_in_hand"]
        and not ev["staryu_on_field"]
        and target in HARVEST_OK
        and ev["turn"] >= 7
    )
    if pre_mega and target in PRE_MEGA_BAD and not harvest_ok:
        tags.append("A")

    # B: free search was discarded/held *and could close this exact gap*.
    discarded_free_closes = (
        (POFFIN in discards and target in BASIC_FETCHABLE)
        or (PAD in discards and target in PAD_FETCHABLE)
    )
    held_free_closes = (
        (ev["has_poffin"] and target in BASIC_FETCHABLE)
        or (ev["has_pad"] and target in PAD_FETCHABLE)
    )
    if discarded_free_closes:
        tags.append("B")
    elif held_free_closes:
        tags.append("B")

    # C: dynamic path protection. Completed-role duplicates and free searches
    # that cannot hit the current target are intentionally discardable.
    bad_discard = WATER in discards
    bad_discard = bad_discard or (
        MEGA_STARMIE in discards and ev["hand"].count(MEGA_STARMIE) <= 1
    )
    bad_discard = bad_discard or (
        STARYU in discards
        and not ev["staryu_on_field"]
        and ev["hand"].count(STARYU) <= 1
    )
    bad_discard = bad_discard or (
        HILDA in discards
        and target in {MEGA_STARMIE, MEGA_FROSLASS, FROSLASS, WATER}
    )
    bad_discard = bad_discard or discarded_free_closes
    if bad_discard:
        tags.append("C")

    # D: should fetch Mega/Staryu but fetched something else
    if (
        pre_mega
        and not ev["mega_in_hand"]
        and target
        and target not in WHITELIST_PRE_MEGA
        and not harvest_ok
    ):
        tags.append("D")

    # E: already had same name in hand
    if ev["target_in_hand"]:
        tags.append("E")

    # UB-2: Mega in hand + (Staryu on field OR not fetching Staryu) → shouldn't Ball
    if (
        ev["mega_in_hand"]
        and ev["staryu_on_field"]
        and pre_mega
        and target != STARYU
    ):
        if "UB2" not in tags:
            tags.append("UB2")
        if target in PRE_MEGA_BAD and "A" not in tags:
            tags.append("A")

    return tags


def audit_pack(pack_dir: Path) -> list[dict]:
    all_ev: list[dict] = []
    for path in sorted(pack_dir.glob("game_*.log")):
        all_ev.extend(_parse_file(path))
    deduped = _dedupe(all_ev)
    for idx, ev in enumerate(deduped):
        tags = _auto_tags(ev)
        ev["tags"] = tags
        ev["ok"] = len(tags) == 0
        ev["case_id"] = f"{ev['game']}:L{ev['line']}"
        ev["label_override"] = None  # filled by human pass
        ev["idx"] = idx
    return deduped


def _write_outputs(events: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = out_dir / "catalog.jsonl"
    with catalog.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    tag_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    for ev in events:
        target_counts[ev["target"] or "(unknown)"] += 1
        if ev["ok"]:
            tag_counts["ok"] += 1
        for t in ev["tags"]:
            tag_counts[t] += 1

    lines = [
        "# Ultra Ball audit summary",
        "",
        f"- events (deduped): **{len(events)}**",
        f"- games with Ball: **{len({e['game'] for e in events})}**",
        "",
        "## Tag counts (multi-label)",
        "",
        "| Tag | Count |",
        "|---|---|",
    ]
    for k in ("A", "B", "C", "D", "E", "UB2", "ok"):
        lines.append(f"| {k} | {tag_counts.get(k, 0)} |")

    lines += ["", "## Search targets", "", "| Target | Count |", "|---|---|"]
    for name, n in target_counts.most_common():
        lines.append(f"| {name} | {n} |")

    def _bucket_rows(tag: str, limit: int = 8) -> list[str]:
        rows = []
        for ev in events:
            if tag == "ok":
                if not ev["ok"]:
                    continue
            elif tag not in ev["tags"]:
                continue
            rows.append(
                f"- `{ev['case_id']}` turn=T{ev['turn']} → **{ev['target']}** "
                f"discard={ev['discards']} "
                f"mega_field={ev['mega_on_field']} mega_hand={ev['mega_in_hand']} "
                f"pad/poffin={ev['has_pad']}/{ev['has_poffin']} "
                f"tags={ev['tags']}"
            )
            if len(rows) >= limit:
                break
        return rows

    for tag, title in (
        ("A", "A — pre-Mega bad dig"),
        ("B", "B — free search / discard Pad·Poffin"),
        ("C", "C — discard blacklist"),
        ("D", "D — should fetch Mega/Staryu"),
        ("E", "E — duplicate in hand"),
        ("UB2", "UB2 — Mega in hand + Staryu on field"),
        ("ok", "ok — clean plays"),
    ):
        lines += ["", f"## {title}", ""]
        rows = _bucket_rows(tag)
        lines.extend(rows or ["- (none)"])

    # A/D full list for human pass
    lines += ["", "## Human pass checklist (A+D full)", ""]
    for ev in events:
        if "A" in ev["tags"] or "D" in ev["tags"]:
            lines.append(
                f"- [ ] `{ev['case_id']}` → {ev['target']} disc={ev['discards']} "
                f"tags={ev['tags']} path={ev['path']}:{ev['line']}"
            )

    lines += ["", "## Human pass sample (B/C, first 5 each)", ""]
    for tag in ("B", "C"):
        n = 0
        lines.append(f"### {tag}")
        for ev in events:
            if tag not in ev["tags"]:
                continue
            lines.append(
                f"- [ ] `{ev['case_id']}` → {ev['target']} disc={ev['discards']} "
                f"path={ev['path']}:{ev['line']}"
            )
            n += 1
            if n >= 5:
                break

    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--pack-dir",
        type=Path,
        default=ROOT / "logs" / "combat_review_91000",
    )
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    pack = args.pack_dir if args.pack_dir.is_absolute() else ROOT / args.pack_dir
    if args.out_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out = ROOT / "logs" / f"ultra_ball_audit_{ts}"
    else:
        out = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir

    events = audit_pack(pack)
    _write_outputs(events, out)
    print(f"wrote {len(events)} events → {out}")
    print(f"  catalog: {out / 'catalog.jsonl'}")
    print(f"  summary: {out / 'summary.md'}")


if __name__ == "__main__":
    main()
