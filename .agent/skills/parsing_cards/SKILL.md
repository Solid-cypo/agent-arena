---
name: parsing-cards
description: |
  Parse cabt card metadata and deck.csv profiles for AgentArena. Use when exporting the card pool, analyzing deck composition, comparing meta decks, or resolving Card IDs to names.
  Do NOT use for in-battle move selection, MCTS search, or LLM tactical planning.
version: 1.0.0
license: MIT
allowed-tools: [Read, Write, Bash]
metadata:
  author: AgentArena-Peter
---
# Parsing Cards

## When to use
- Export `cg.api.all_card_data()` / `all_attack()` into offline JSON
- Turn a 60-line `deck.csv` into a human-readable deck profile
- Compare our deck against meta decks from `export_meta_decks.py`

## When NOT to use
- Choosing actions during a live `cabt` match
- Training or loading Tiny RL policy weights
- Writing or editing Kaggle submission packaging logic

## Workflow
1. Run `scripts/export_card_db.py` to refresh `assets/card_db.json`
2. Run `scripts/parse_deck.py deck.csv` for a deck profile report
3. See `references/card_data_schema.md` for field definitions and enum maps
