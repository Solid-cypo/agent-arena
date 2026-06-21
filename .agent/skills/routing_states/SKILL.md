---
name: routing-states
description: |
  Determine the active FSM tactical state (RUSHING_PRIZES / SETTING_UP_BOARD / DENYING_RESOURCES)
  and PolicyWeights from SituationScores and OpponentProfile.
  Use this skill after assessing_situations, before evaluating_actions.
  Do NOT use for computing board scores, running Search API, or direct action indexing.
version: 1.0.0
license: MIT
allowed-tools: [Read, Write, Bash]
metadata:
  author: AgentArena-Peter
---
# Routing States

## When to use
- Translating three-dimensional board scores into a tactical posture (FSM state)
- Applying counter-chain corrections based on opponent style (Tempo/Control/Burst)
- Producing `PolicyWeights` (w_turn / w_board / w_hand) for action evaluation

## When NOT to use
- Computing S_hand / S_board / TC scores (→ use assessing_situations)
- Selecting or ranking legal actions (→ use evaluating_actions)
- Running Search API simulations

## FSM Priority Order
1. **RUSHING_PRIZES** — prize_left_self ≤ 2 AND board_readiness ≥ 0.8
2. **DENYING_RESOURCES** — opp prize_left ≤ 2 AND opp leads by ≥ 1 prize
3. **Counter-chain bias** — opponent style drives override (Tempo→Burst, Control→Tempo, Burst→Control)
4. **SETTING_UP_BOARD** — default

## Dynamic Corrections
- Hand deficit (s_hand_diff ≤ -3): boost w_hand +0.25
- Opponent Control (confidence ≥ 0.3): boost w_board +0.15 (enable 1081 side-tool plays)
- TEMPO state + fast opponent (s_turn ≤ -2): boost w_turn +0.15

## Workflow
1. `from state_router import route`
2. `result = route(scores, profile)`
3. Pass `result.active_state` and `result.policy_weights` to `evaluating_actions`

## References
- `../../docs/agent_design_spec.md` — §4 full FSM spec and weight table
- `../../../../references/ptcg_dimension_theory.md` — §2 九宫格克制链
