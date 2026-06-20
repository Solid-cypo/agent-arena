#!/usr/bin/env python3
"""Render a human-readable profile for a 60-card deck.csv file."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_ROOT.parents[2]
DEFAULT_DB = SKILL_ROOT / "assets" / "card_db.json"
EXPORT_SCRIPT = SKILL_ROOT / "scripts" / "export_card_db.py"


def _load_card_db(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing card database: {path}\n"
            f"Run: python {EXPORT_SCRIPT}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _read_deck(path: Path) -> list[int]:
    ids: list[int] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            ids.append(int(stripped))
        except ValueError as exc:
            raise ValueError(f"{path}:{line_no}: invalid card id {stripped!r}") from exc
    if len(ids) != 60:
        raise ValueError(f"{path}: expected 60 card IDs, found {len(ids)}")
    return ids


def _group_label(card_type: int) -> str:
    if card_type == 0:
        return "Pokemon"
    if card_type in (5, 6):
        return "Energy"
    return "Trainer"


def _format_attack(attack: dict[str, Any]) -> str:
    energy = "/".join(attack.get("energyLabels", [])) or "?"
    damage = attack.get("damage", 0)
    return f"{attack['name']} [{energy}] dmg={damage}"


def build_deck_profile(deck_ids: list[int], card_db: dict[str, Any]) -> dict[str, Any]:
    cards = card_db["cards"]
    counts = Counter(deck_ids)
    missing = sorted({card_id for card_id in deck_ids if str(card_id) not in cards})

    grouped: dict[str, int] = Counter()
    card_type_counts: Counter[str] = Counter()
    energy_type_counts: Counter[str] = Counter()
    entries: list[dict[str, Any]] = []

    total_retreat = 0
    pokemon_with_retreat = 0

    for card_id, count in counts.most_common():
        record = cards.get(str(card_id))
        if record is None:
            entries.append({"cardId": card_id, "count": count, "name": "UNKNOWN"})
            continue

        group = _group_label(record["cardType"])
        grouped[group] += count
        card_type_counts[record["cardTypeLabel"]] += count

        if group == "Pokemon" and record.get("retreatCost", 0) > 0:
            total_retreat += record["retreatCost"] * count
            pokemon_with_retreat += count
        if group == "Energy":
            energy_type_counts[record.get("energyTypeLabel", "?")] += count

        entries.append(
            {
                "cardId": card_id,
                "count": count,
                "name": record["name"],
                "group": group,
                "cardTypeLabel": record["cardTypeLabel"],
                "hp": record.get("hp", 0),
                "energyTypeLabel": record.get("energyTypeLabel"),
                "attacks": [
                    _format_attack(attack) for attack in record.get("attackDetails", [])
                ],
                "evolvesFrom": record.get("evolvesFrom"),
                "tags": _collect_tags(record),
            }
        )

    chains = _build_deck_evolution_chains(entries, card_db.get("evolution_edges", []))

    return {
        "total_cards": len(deck_ids),
        "unique_cards": len(counts),
        "missing_card_ids": missing,
        "group_counts": dict(grouped),
        "card_type_counts": dict(card_type_counts),
        "energy_type_counts": dict(energy_type_counts),
        "avg_retreat_cost": round(total_retreat / pokemon_with_retreat, 2)
        if pokemon_with_retreat
        else 0.0,
        "entries": entries,
        "evolution_chains": chains,
    }


def _collect_tags(record: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for key, label in (
        ("basic", "Basic"),
        ("stage1", "Stage1"),
        ("stage2", "Stage2"),
        ("ex", "ex"),
        ("megaEx", "Mega ex"),
        ("tera", "Tera"),
        ("aceSpec", "ACE SPEC"),
    ):
        if record.get(key):
            tags.append(label)
    return tags


def _build_deck_evolution_chains(
    entries: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[str]:
    deck_names = {entry["name"] for entry in entries if entry.get("name") != "UNKNOWN"}
    chains: list[str] = []
    for edge in edges:
        if edge["from"] in deck_names and edge["to"] in deck_names:
            from_count = sum(
                item["count"] for item in entries if item.get("name") == edge["from"]
            )
            to_count = sum(
                item["count"] for item in entries if item.get("name") == edge["to"]
            )
            chains.append(f"{edge['from']} (×{from_count}) → {edge['to']} (×{to_count})")
    return chains


def render_text_profile(deck_path: Path, profile: dict[str, Any]) -> str:
    lines = [
        f"=== Deck Profile: {deck_path.name} ===",
        f"Cards: {profile['total_cards']} | Unique: {profile['unique_cards']}",
    ]
    if profile["missing_card_ids"]:
        lines.append(f"WARNING missing IDs: {profile['missing_card_ids']}")

    lines.append("")
    lines.append("Composition:")
    for group, count in sorted(profile["group_counts"].items()):
        lines.append(f"  {group}: {count}")

    if profile["energy_type_counts"]:
        lines.append("")
        lines.append("Energy breakdown:")
        for label, count in sorted(
            profile["energy_type_counts"].items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"  {label}: {count}")

    if profile["evolution_chains"]:
        lines.append("")
        lines.append("Evolution chains:")
        for chain in profile["evolution_chains"]:
            lines.append(f"  {chain}")

    lines.append("")
    lines.append(f"Avg retreat cost (Pokemon): {profile['avg_retreat_cost']}")
    lines.append("")
    lines.append("Card list:")
    for entry in profile["entries"]:
        tag_text = f" [{'/'.join(entry['tags'])}]" if entry.get("tags") else ""
        lines.append(f"  {entry['count']:2d}x [{entry['cardId']:4d}] {entry['name']}{tag_text}")
        for attack in entry.get("attacks", [])[:2]:
            lines.append(f"       - {attack}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a cabt deck.csv into a deck profile.")
    parser.add_argument("deck", type=Path, help="Path to deck.csv (60 Card IDs)")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Path to card_db.json (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON profile instead of text report",
    )
    args = parser.parse_args()

    deck_path = args.deck if args.deck.is_absolute() else PROJECT_ROOT / args.deck
    db_path = args.db if args.db.is_absolute() else PROJECT_ROOT / args.db

    card_db = _load_card_db(db_path)
    deck_ids = _read_deck(deck_path)
    profile = build_deck_profile(deck_ids, card_db)

    if args.json:
        payload = {"deck": str(deck_path), **profile}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text_profile(deck_path, profile))


if __name__ == "__main__":
    main()
