#!/usr/bin/env python3
"""Export cabt card pool metadata to assets/card_db.json."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SKILL_ROOT.parents[2]
DEFAULT_OUTPUT = SKILL_ROOT / "assets" / "card_db.json"

sys.path.insert(0, str(PROJECT_ROOT))

from cg.api import (  # noqa: E402
    Attack,
    CardData,
    CardType,
    EnergyType,
    all_attack,
    all_card_data,
)

CARD_TYPE_LABELS = {member.value: member.name.replace("_", " ").title() for member in CardType}
ENERGY_TYPE_LABELS = {member.value: member.name.replace("_", " ").title() for member in EnergyType}


def _skill_to_dict(skill: Any) -> dict[str, str]:
    return {"name": skill.name, "text": skill.text}


def _card_to_dict(card: CardData) -> dict[str, Any]:
    return {
        "cardId": card.cardId,
        "name": card.name,
        "cardType": card.cardType,
        "cardTypeLabel": CARD_TYPE_LABELS.get(card.cardType, str(card.cardType)),
        "pokemonType": card.pokemonType,
        "evolutionType": card.evolutionType,
        "retreatCost": card.retreatCost,
        "hp": card.hp,
        "weakness": card.weakness,
        "weaknessLabel": ENERGY_TYPE_LABELS.get(card.weakness, None)
        if card.weakness is not None
        else None,
        "resistance": card.resistance,
        "resistanceLabel": ENERGY_TYPE_LABELS.get(card.resistance, None)
        if card.resistance is not None
        else None,
        "energyType": card.energyType,
        "energyTypeLabel": ENERGY_TYPE_LABELS.get(card.energyType, str(card.energyType)),
        "basic": card.basic,
        "stage1": card.stage1,
        "stage2": card.stage2,
        "ex": card.ex,
        "megaEx": card.megaEx,
        "tera": card.tera,
        "aceSpec": card.aceSpec,
        "evolvesFrom": card.evolvesFrom,
        "skills": [_skill_to_dict(skill) for skill in card.skills],
        "attacks": card.attacks,
    }


def _attack_to_dict(attack: Attack) -> dict[str, Any]:
    return {
        "attackId": attack.attackId,
        "name": attack.name,
        "text": attack.text,
        "damage": attack.damage,
        "energies": attack.energies,
        "energyLabels": [
            ENERGY_TYPE_LABELS.get(value, str(value)) for value in attack.energies
        ],
    }


def _build_evolution_edges(cards: list[CardData]) -> list[dict[str, Any]]:
    name_to_id: dict[str, int] = {}
    for card in cards:
        name_to_id.setdefault(card.name, card.cardId)

    edges: list[dict[str, Any]] = []
    for card in cards:
        if not card.evolvesFrom:
            continue
        parent_id = name_to_id.get(card.evolvesFrom)
        if parent_id is None:
            continue
        edges.append(
            {
                "from": card.evolvesFrom,
                "to": card.name,
                "from_id": parent_id,
                "to_id": card.cardId,
            }
        )
    return edges


def build_card_db() -> dict[str, Any]:
    cards = all_card_data()
    attacks = all_attack()
    attack_map = {attack.attackId: _attack_to_dict(attack) for attack in attacks}

    cards_dict: dict[str, dict[str, Any]] = {}
    name_to_ids: dict[str, list[int]] = defaultdict(list)
    for card in cards:
        payload = _card_to_dict(card)
        resolved_attacks = [
            attack_map[attack_id]
            for attack_id in card.attacks
            if attack_id in attack_map
        ]
        payload["attackDetails"] = resolved_attacks
        cards_dict[str(card.cardId)] = payload
        name_to_ids[card.name].append(card.cardId)

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "card_count": len(cards),
            "attack_count": len(attacks),
            "source": "cg.api.all_card_data()/all_attack()",
        },
        "cards": cards_dict,
        "attacks": {str(key): value for key, value in attack_map.items()},
        "name_to_ids": dict(name_to_ids),
        "evolution_edges": _build_evolution_edges(cards),
    }


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_card_db()
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    print(
        f"cards={payload['meta']['card_count']} "
        f"attacks={payload['meta']['attack_count']}"
    )


if __name__ == "__main__":
    main()
