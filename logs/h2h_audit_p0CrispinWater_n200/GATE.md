# GATE — P0 Crispin 错色能量 / HR-E1 补水

- baseline: `data/restore_peaks/ops_fireform_55115028`
- current: `submission_starmie`（HandQual+AB + P0 Crispin TO_HAND pocket Dark + wrong-color Water refill）
- n=200 seed0=82000 tag=`p0CrispinWater_n200`
- env: `OPENING_HANDOFF=0` `RL_ENABLED=0` `--rules-only`
- 对照面: `onlineFour_AB_n200`（WR 50.0% / Opening 合计 80.0% / B 47%）

## Red lines

| metric | value | vs AB | target | result |
|---|---:|---:|---:|---|
| 先手 Opening≤T3 | 81% | −2pp | ≥78% | PASS |
| 后手 Opening≤T2 | 80% | +3pp | （辅） | — |
| Opening 合计 | 80.5% | +0.5pp | ≥74% | PASS |
| seat B WR | 61% | +14pp | ≥40% | PASS |
| WR (decided) | 58.5% | +8.5pp | （辅，勿单独宣判） | 绿 |

## 判决

**G0 绿 — 采用 P0**（报警闸通过；n=200 非科学死刑庭，同 seed≠bit 恒等）。

- Opening 硬指标未回吐；seat B 未崩。
- 机制已本地复现：91350842 si=29 HEAD 改选 Dark pocket；错色后 Water refill hard=PATH。

## 旁证（负局 tag，非主 KPI）

| tag | P0 | AB |
|---|---:|---:|
| mega_gap>0 | 27 | 36 |
| mega_evolved_no_attack | 11 | 5 |
| zero_boss | 47 | 65 |
| no_mega 负局 | 15 | 12 |

`mega_evolved_no_attack` 略升，不挡 G0；若线上仍见零 Jetting 再盯 P2 Boss→Jetting。

## Knives

| knife | status |
|---|---|
| P0 Crispin 错色 + HR-E1 补水 | **SHIP** |
| CombatClose-V1 / RunAway / PostMega / ENERGY→Meowth | 仍 NO-GO |
