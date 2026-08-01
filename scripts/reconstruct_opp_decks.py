#!/usr/bin/env python3
"""Reconstruct opponent decklists from online replays (sub_55115028).

For each target archetype, scan every step of every episode from OUR view and
collect the opponent's visible cards (active/bench incl. pre-evolution stacks,
attached energy cards, tools, discard) keyed by card `serial` — serials are
unique per physical card per game, so distinct-serial counts give exact copy
counts for everything the opponent ever showed. Copies are max'd across the
archetype's episodes, capped at 4 (basic energy uncapped), then padded to 60
with archetype staples / basic energy.

Output: data/decks/<arch>.csv (same format as walrein_control.csv)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cg.api import all_card_data  # noqa: E402

US = "Ying Peter"
SUB_DIR = ROOT / "data" / "kaggle_episodes" / "sub_55115028"
FADE = ROOT / "data" / "kaggle_episodes" / "analysis_55115028_fade.json"
ARCHS = ["lucario_fighting", "marnie_froslass_munk", "dragapult"]

CARDS = {c.cardId: c for c in all_card_data()}


def is_basic_energy(cid: int) -> bool:
    c = CARDS.get(cid)
    return bool(c and c.cardType == 5 and c.name.startswith("Basic"))


def name(cid: int) -> str:
    c = CARDS.get(cid)
    return c.name if c else f"card_{cid}"


def collect_episode(path: Path) -> dict[int, int]:
    d = json.loads(path.read_text())
    mi = d["info"]["TeamNames"].index(US)
    oi = 1 - mi
    serial_id: dict[int, int] = {}

    def add(card) -> None:
        if isinstance(card, dict) and "serial" in card and "id" in card:
            serial_id[int(card["serial"])] = int(card["id"])

    for step in d["steps"]:
        obs = (step[mi] or {}).get("observation") or {}
        players = (obs.get("current") or {}).get("players") or []
        if len(players) <= oi:
            continue
        p = players[oi] or {}
        for pk in (p.get("active") or []) + (p.get("bench") or []):
            if not pk:
                continue
            add(pk)
            for sub in ("preEvolution", "energyCards", "tools"):
                for c in pk.get(sub) or []:
                    add(c)
        for c in p.get("discard") or []:
            add(c)
    counts: dict[int, int] = defaultdict(int)
    for cid in serial_id.values():
        counts[cid] += 1
    return dict(counts)


def main() -> int:
    fade = json.loads(FADE.read_text())
    by_arch: dict[str, list[int]] = defaultdict(list)
    for g in fade["games"]:
        by_arch[g["arch"]].append(g["eid"])

    for arch in ARCHS:
        eids = by_arch[arch]
        per_ep = []
        for eid in eids:
            f = SUB_DIR / f"episode-{eid}-replay.json"
            if f.exists():
                per_ep.append(collect_episode(f))
        merged: Counter = Counter()
        for c in per_ep:
            for cid, n in c.items():
                merged[cid] = max(merged[cid], n)
        # cap at 4 except basic energy
        deck: dict[int, int] = {}
        for cid, n in merged.items():
            deck[cid] = n if is_basic_energy(cid) else min(4, n)
        total = sum(deck.values())
        print(f"\n=== {arch} ({len(per_ep)} eps) observed {total} cards ===")
        for cid, n in sorted(deck.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {n}x {name(cid)} ({cid})")

        # pad to 60: first bump seen trainers/supporters toward 4, then energy
        need = 60 - total
        if need > 0:
            trainers = [
                cid for cid in deck
                if CARDS.get(cid) and CARDS[cid].cardType in (2, 3, 4)
            ]
            trainers.sort(key=lambda c: -deck[c])
            for cid in trainers:
                while deck[cid] < 4 and need > 0:
                    deck[cid] += 1
                    need -= 1
            if need > 0:
                # basic energy matching the deck's dominant energy
                en = [c for c in deck if is_basic_energy(c)]
                fill = max(en, key=lambda c: deck[c]) if en else 4
                deck[fill] = deck.get(fill, 0) + need
                need = 0
        elif need < 0:
            # over 60 (max-union across episodes overcounts): drop copies of
            # low-count trainers first, keep energy and pokemon lines intact
            cands = sorted(
                (c for c in deck
                 if CARDS.get(c) and CARDS[c].cardType in (2, 3, 4)
                 and not is_basic_energy(c)),
                key=lambda c: deck[c],
            )
            for cid in cands:
                if need >= 0:
                    break
                if deck[cid] > 0:
                    deck[cid] -= 1
                    need += 1
            for cid in [c for c in deck if deck[c] == 0]:
                del deck[cid]
            while need < 0:
                en = max(
                    (c for c in deck if is_basic_energy(c)),
                    key=lambda c: deck[c],
                    default=None,
                )
                if en is None:
                    break
                deck[en] -= 1
                need += 1

        out = ROOT / "data" / "decks" / f"{arch}.csv"
        lines = [
            f"# {arch} (reconstructed from sub_55115028 episodes {eids})",
            f"# Total: {sum(deck.values())} cards"
            f" (observed {total}, padded {60 - total if total < 60 else 0})",
        ]
        for cid, n in sorted(deck.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"# {n}x {name(cid)} ({cid})")
        for cid, n in sorted(deck.items()):
            lines.extend([str(cid)] * n)
        out.write_text("\n".join(lines) + "\n")
        print(f"  -> {out} total {sum(deck.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
