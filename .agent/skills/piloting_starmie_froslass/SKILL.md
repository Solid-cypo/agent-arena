---
name: piloting-starmie-froslass
description: |
  Pilot dual Mega ex deck (Starmie+Froslass) with Layer1 hard rules and trainable soft dims.
  Use when running, training, auditing, or submitting starmie_froslass.csv — opening sim,
  aggression synergy, harvest Resentful, or control modifier (Meowth/Judge).
  Do NOT use for Tea Party / generic 28-dim policy or card-id rules in arena/policy.py.
version: 1.1.0
license: MIT
allowed-tools: [Read, Write, Bash]
metadata:
  author: AgentArena-Peter
---

# Piloting Starmie + Froslass

Deck-specific agent for `data/decks/starmie_froslass.csv`. Two layers on a generic baseline scorer.

## When to use
- Running / training / submitting the Starmie+Froslass deck.
- Opening simulation (`simulate_opening.py`), Layer 1 audits, or Phase FSM work.

## When NOT to use
- Tea Party, Walrein control, or generic 28-dim `arena/policy.py` decks.

## Architecture

### Phase FSM (`phase_fsm.py`)
- **Primary**: OPENING → AGGRESSION → HARVEST
- **Modifier**: `control_active` when `prize_self < prize_opp` (+CONTROL)

### Layer 1 — hard rules (`starmie_pilot.py`)
| Phase | Module | Key rules |
|---|---|---|
| OPENING | `opening_bridge` + HR-O* | opening_planner route (1150) |
| AGGRESSION | HR-2~11 | Adrena, Jetting, HR-8b block 861, synergy T2–T8 |
| HARVEST | `_harvest_hard_rules` | 861 evolve/attach/Resentful; HR-H6 Judge ban |
| CONTROL | `_control_hard_rules` | Meowth Last-Ditch, Boss, Judge (post-Resentful) |
| AGGRESSION+ | `supporter_planner` / `draw_axis` | DR-* / DD-* via Layer1 planner scores |

### Layer 2 — trainable dims
`froslass_harvest`, `jetting_blow_pref`, `nebula_finish`, `boss_gust_path`

## Workflow
1. `make_starmie_agent(deck, weights)` — entry for battles and Kaggle.
2. Part 1 Opening: `simulate_opening.py` (independent of pilot).
3. After editing scripts: `python3 scripts/sync_starmie_submission.py`.
4. Package: `python3 scripts/package_starmie.py`.
5. Audits: `audit_aggression_abilities.py`, `audit_harvest.py`, `audit_control.py`.
6. Tests: `python3 tests/test_starmie_pilot.py` (54 cases).

## References
- `references/deck_knowledge.md` — card roster & chains
- `references/phases/00_fsm_overview.md` — FSM map
- `references/phases/01_opening.md` … `04_control.md` — Phase specs

## Caveats
- Layer 2 nudges stay ~0–5; only Layer 1 may DOMINATE.
- Opening simulator must not import `starmie_pilot`.
- Judge before Resentful in HARVEST is forbidden (HR-H6).
