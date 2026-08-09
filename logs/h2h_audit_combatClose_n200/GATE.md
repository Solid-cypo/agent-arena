# CombatClose-V1 — **证伪 / 已回滚**

- seed0=82000 · n=200 vs fireform · `OPENING_HANDOFF=0`
- 刀：`_plan_primary_step` 在 Active Mega 就绪时仍返回 `required[0]`；锁定 ADRENA/BOSS/DISPATCH；BOSS 排在 ADRENA 后
- 代码已 `git checkout` 回滚；submission 已 re-sync

## 表变（相对假设卡 / D1）

| 指标 | 基线 | CombatClose | 判 |
|---|---:|---:|---|
| `double_ko_prep_order_ok` (BC) | 31.4% | **28.6%** | 未升（↓） |
| Opening 硬指标合计 | 81.5% | **77.5%** | **<78% 回滚线** |
| 后手≤T2 | 77% | **71%** | 回吐 |
| 先手≤T3 | 86% | 84% | 勉强 |
| H2H WR | 53.5% | 50.5% | ↓ |
| seat B WR | 46% | 48% | 未崩 |
| `ready_mega_no_attack` | 0 | 0 | 持 |
| `boss_grabs_rider` | 0 | 0 | 持 |

纪律（本包）：BOSS primary 0→129（表面成功）；ADRENA n 105→679 但 compliance 仍 ~14%；`plan_violation_rate` 4.8%→**8.0%**。

## 已证伪

1. **「把 BOSS/ADRENA 送进 primary_step + 锁步」不足以抬 `double_ko_prep_order_ok`** — 行数暴涨，序达成率反降。  
2. **宽锁 DISPATCH/ADRENA 伤 Opening 时钟**（后手≤T2 77→71）。  

## 下一归因方向（未开刀）

- ADRENA compliance 低主因是 **ghost / 嵌套 select 行** 还是 MAIN 上能力未 PATH？需 hard-rule trace 抽 5 局 ADRENA MAIN。  
- 勿原样重试「锁三步」；若再试须先保证 `_plan_step_has_advance` 与 `_actionable_pre_attack` 对齐后再锁。
