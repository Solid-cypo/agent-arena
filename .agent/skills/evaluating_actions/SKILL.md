---
name: evaluating-actions
description: |
  Select the highest-utility legal action using Search API forward simulation and deterministic math corrections.
  Use this skill after routing_states to choose the best option index for the current turn.
  Do NOT use for computing board scores, FSM state transitions, or deck/card parsing.
version: 1.0.0
license: MIT
allowed-tools: [Read, Write, Bash]
metadata:
  author: AgentArena-Peter
---
# Evaluating Actions

## When to use
- Selecting the best action index from `obs.select.option` each turn
- Applying ko_math (energy routing), survival_math (retreat bonus, Iono), and hammer vs Control bonus
- Running Search API forward simulation (up to K=8 candidates, 200ms budget)

## When NOT to use
- Computing S_hand / S_board / TC scores (→ use assessing_situations)
- Determining FSM tactical state (→ use routing_states)
- Parsing card metadata or deck profiles (→ use parsing_cards)

## Pipeline
1. Baseline-rank all options with `arena/policy.py option_score`
2. Forward-simulate top-K candidates via `cg.api.search_begin / search_step`
3. Weight simulated scores by `PolicyWeights` from routing_states
4. Add deterministic corrections:
   - `ko_math.energy_routing_bonus` → ATTACH toward best attacker
   - `survival_math.evaluate_survival_bonus` → RETREAT of multi-prize Pokemon
   - `survival_math.get_hammer_bonus` → PLAY 1081 vs Control
   - `survival_math.get_iono_priority_weight` → PLAY 1227 when trailing
5. Return highest-utility option index(es)

## Fallback
Any exception or timeout → `arena/policy.py.choose_options()` (always safe)

## Search Budget
- K = 8 candidates max
- 200ms wall-clock per turn
- Always call `search_release(id)` + `search_end()` to free memory

## References
- `../../docs/agent_design_spec.md` — §5 full evaluator spec
- `../../../../references/ptcg_dimension_theory.md` — §4 动态权重修正
