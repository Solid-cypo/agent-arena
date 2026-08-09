# GATE — onlineFour A+B (Alakazam-Online-V1 + UbSurplusDun-V1)

- baseline: `data/restore_peaks/ops_fireform_55115028`
- current: `submission_starmie` (HandQual tar + knives A/B)
- n=200 seed0=82000 tag=`onlineFour_AB_n200`
- deck: 3× Staryu (ops_fireform / HEAD `data/decks`) — OpsOrder 2×Staryu deck fails Opening red line on this seed

## Red lines

| metric | value | target | result |
|---|---:|---:|---|
| 先手 Opening≤T3 | 83% | ≥78% | PASS |
| Opening 合计 | 80% | ≥74% | PASS |
| seat B WR | 47% | ≥40% | PASS |
| WR (decided) | 50.0% | (辅) | vs HandQual_3sty 56.3% |

## Knives

| knife | status |
|---|---|
| A Alakazam-Online-V1 | SHIP — soft confirm + Plan B under attack_required |
| B UbSurplusDun-V1 | SHIP — line≥3 Dunsparce discard_value=25 |
| C RunAway-V1 | NO-GO — post-Mega default draw crushed WR (v3 44%) |
| D PostMega-Exec-V1 | NO-GO — with C in v3; alone not re-tested after AB |

## Notes

- plan_step ENERGY overrides (v1) also NO-GO for Opening/WR
- Do not retry ThinHand Meowth-before-Jetting
