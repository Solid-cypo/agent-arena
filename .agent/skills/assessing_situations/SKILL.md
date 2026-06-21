---
name: assessing-situations
description: |
  Parse raw cabt Observation to compute SituationScores (S_hand, S_board, S_turn, TC_me, TC_opp)
  and identify opponent deck archetype via fingerprint matching.
  Use this skill at the start of every agent turn to quantify board advantages and classify the opponent.
  Do NOT use for action evaluation, FSM state transitions, or Search API calls.
version: 1.0.0
license: MIT
allowed-tools: [Read, Write, Bash]
metadata:
  author: AgentArena-Peter
---
# Assessing Situations

## When to use
- Computing the three-dimensional board scores (S_hand / S_board / S_turn) from an obs_dict
- Identifying opponent deck style (Tempo / Control / Burst) for routing_states
- Estimating turn-clock distance (TC_me, TC_opp) before action evaluation

## When NOT to use
- Choosing or ranking legal actions (→ use evaluating_actions)
- Transitioning FSM tactical states (→ use routing_states)
- Running Search API simulations

## Workflow
1. Call `situation_assessor.assess(obs_dict)` → `SituationScores`
2. Call `opponent_profiler.profile_opponent(obs_dict)` → `OpponentProfile`
3. Pass both to `routing_states.state_router`

## References
- `references/meta_signatures.json` — Top10 deck fingerprints (Jaccard matching)
- `references/card_tactic_weights.json` — DrawPotential, hammer bonus, Iono multiplier
- `../../docs/agent_design_spec.md` — full math spec (S_hand / S_board / TC formulas)
- `../../../../references/ptcg_dimension_theory.md` — theory anchor (read-only)
