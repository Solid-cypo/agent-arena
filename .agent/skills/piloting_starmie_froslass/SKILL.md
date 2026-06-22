---
name: piloting-starmie-froslass
description: |
  Pilot the dual Mega ex deck (Mega Starmie ex + Mega Froslass ex) with a two-layer
  agent: deterministic hard-rule interception plus trainable harvest dimensions.
  Use this skill when running, training, or submitting the starmie_froslass.csv deck,
  or when scoring legal options for that specific archetype.
  Do NOT use for Tea Party / Walrein control / generic 28-dim policy decks, and do
  NOT fold these card-id rules back into the shared arena/policy.py.
version: 1.0.0
license: MIT
allowed-tools: [Read, Write, Bash]
metadata:
  author: AgentArena-Peter
---

# Piloting Starmie + Froslass

A deck-specific agent for the dual Mega ex aggro deck
(`data/decks/starmie_froslass.csv`). It layers two concerns on top of the
generic weighted scorer and never pollutes `arena/policy.py`.

## When to use
- Running / training / submitting the `starmie_froslass` deck.
- Scoring legal options for the Mega Starmie ex + Mega Froslass ex archetype.

## When NOT to use
- Tea Party, Walrein control, or any deck driven by the generic 28-dim policy.
- Adding new card-id branches into the shared `arena/policy.py` (keep them here).

## Architecture (two layers)

### Layer 1 — deterministic hard rules (`scripts/starmie_pilot.py`)
Fires only on exact, certain deck conditions and returns a dominating score so the
option is always chosen. No trainable weights — these are "always do X when Y":

| Rule | Trigger |
| --- | --- |
| Fan Rotom `Fan Call` | First turn (`state.turn in {1,2}`) and ability available |
| Munkidori `Adrena-Brain` | Munkidori has DARKNESS energy and the ability is offered |
| Budew `Itchy Pollen` | Turn 2 fallback when no Mega Starmie/Froslass attack is ready |

### Layer 2 — trainable harvest dimensions
Small situational nudges, bounded to the baseline score range (~0-5) so they nudge
rather than override:

| Dim | Meaning |
| --- | --- |
| `froslass_harvest` | Evolve Snorunt → Mega Froslass ex when opponent hand is large / just took a prize |
| `jetting_blow_pref` | Prefer Jetting Blow (bench spread) for damage accumulation |
| `nebula_finish` | Prefer Nebula Beam when it secures an immediate KO (ignores effects) |
| `boss_gust_path` | Boss's Orders onto a prize-path bench target |

## Workflow
1. Build the agent with `make_starmie_agent(deck, weights)`.
2. Per option-select: Layer 1 hard rules are scanned first; if one fires it wins.
3. Otherwise the generic baseline score + Layer 2 nudges rank the options.
4. Train weights with `scripts/train_starmie.py` (challenger = this pilot,
   opponents = Walrein control + meta decks on the generic policy).
5. See `references/tactics.md` for the full opening book and combo timings.

## Caveats
- Lesson from the prior FSM regression: keep Layer 2 bonuses inside the baseline
  range; only Layer 1 may dominate, and only on certain conditions.
- All card ids live in `scripts/starmie_pilot.py` (`_CARDS`), never in shared code.
