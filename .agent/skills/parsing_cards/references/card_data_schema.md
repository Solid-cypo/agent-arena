# Card Data Schema (cabt / cg.api)

Source of truth: `cg.api.all_card_data()` and `cg.api.all_attack()` backed by `libcg.so`.

## CardData fields

| Field | Type | Notes |
|-------|------|-------|
| `cardId` | int | Primary deck / log identifier |
| `name` | str | Display name |
| `cardType` | int | See CardType enum below |
| `hp` | int | Pokémon HP; 0 for non-Pokémon |
| `energyType` | int | Pokémon type or basic energy type |
| `retreatCost` | int | Retreat energy cost |
| `weakness` / `resistance` | int \| null | EnergyType enum value |
| `basic` / `stage1` / `stage2` | bool | Evolution stage flags |
| `ex` / `megaEx` / `tera` / `aceSpec` | bool | Special Pokémon tags |
| `evolvesFrom` | str \| null | Pre-evolution name |
| `skills` | list | `{name, text}` ability entries |
| `attacks` | list[int] | Attack IDs referencing attack catalog |
| `pokemonType` | int | Engine-specific Pokémon subtype |
| `evolutionType` | int | Engine-specific evolution marker |

## Attack fields

| Field | Type | Notes |
|-------|------|-------|
| `attackId` | int | Referenced by CardData.attacks |
| `name` | str | Attack name |
| `text` | str | Effect text |
| `damage` | int | Base damage |
| `energies` | list[int] | Required EnergyType values |

## CardType enum

| Value | Label |
|------:|-------|
| 0 | Pokemon |
| 1 | Item |
| 2 | Tool |
| 3 | Supporter |
| 4 | Stadium |
| 5 | Basic Energy |
| 6 | Special Energy |

## EnergyType enum

| Value | Label |
|------:|-------|
| 0 | Colorless |
| 1 | Grass |
| 2 | Fire |
| 3 | Water |
| 4 | Lightning |
| 5 | Psychic |
| 6 | Fighting |
| 7 | Darkness |
| 8 | Metal |
| 9 | Dragon |
| 10 | Rainbow |
| 11 | Psychic/Darkness |

## deck.csv format

Exactly 60 lines, one integer Card ID per line. Duplicate IDs are allowed (e.g., 4× Ultra Ball, many basic energy).

## card_db.json layout

Produced by `scripts/export_card_db.py`:

```json
{
  "meta": {"generated_at": "...", "card_count": 1267, "attack_count": 1556},
  "cards": {"673": {...}, "...": "..."},
  "attacks": {"1": {...}},
  "name_to_ids": {"Riolu": [333, 677, 974]},
  "evolution_edges": [{"from": "Riolu", "to": "Mega Lucario ex", "from_id": 677, "to_id": 678}]
}
```
