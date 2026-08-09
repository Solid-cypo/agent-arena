# H2H 引擎日志审计摘要

- baseline: `data/restore_peaks/ops_fireform_55115028`
- current: `submission_starmie`
- n=200 seed0=82000 tag=`p0CrispinWater_n200`

## 总表

| 项 | 值 |
|---|---|
| WR (decided) | 117-83 (58.5%) draws=0 |
| seat A (先手) WR | 56/100 (56.0%) |
| seat B (后手) WR | 61/100 (61.0%) |
| 短局 steps&lt;40 | 16/200 (8.0%) |

## Opening 核心硬指标（不可回吐）

定义：先手 `mega_evo_my_t≤3`；后手 `mega_evo_my_t≤2`。WR / 全席≤T3 均为辅。

| 项 | 值 |
|---|---|
| **先手 Opening≤T3** | 81/100 (81.0%) |
| **后手 Opening≤T2** | 80/100 (80.0%) |
| **硬指标合计** | 161/200 (80.5%) |
| （辅）全席 Mega≤T3 | 165/200 (82.5%) |

## 路径桶 × 胜负（current 视角）

| path_bucket | 胜 | 负 | WR |
|---|---:|---:|---|
| fast_mega_t≤3 | 106 | 59 | 64.2% |
| mega_t4-6 | 9 | 7 | 56.2% |
| mega_late_>6 | 1 | 2 | 33.3% |
| no_mega | 1 | 15 | 6.2% |

## 负局专用

- 负局数: **83**
- seat B 负局: 39/83 (47.0%)
- no_mega: 15 (18.1%)
- mega_late_>6: 2 (2.4%)
- mega_gap>0（进化后未当回合攻击）: 27
- mega_evolved_no_attack: 11
- zero_boss: 47 (56.6%)
- 无 munk_dark: 55 (66.3%)
- 无 Itchy: 74 (89.2%)
- 对手 Mega 更早: 23 (27.7%)
- 负局 T4 奖差 (opp_prize - self，>0=我方领先): n=78 avg=-0.96 落后局=41

## 底座暴露 / 前场卡住

- 全量曾「海星独站空替补」(ever_staryu_solo_exposed): 30/200 (15.0%)
- 全量曾「错前场」(ever_wrong_active，Active≠海星/Mega 且替补有海星或手握Mega): 150/200 (75.0%)
- 负局独站暴露: 11/83 (13.3%)
- 负局错前场: 64/83 (77.1%)
- 负局有铺场空过/误用 (setup_miss_total>0): 22/83 (26.5%)
- 负局错前场首个 Active ID 分布:
  - `860`: 15
  - `235`: 11
  - `65`: 11
  - `305`: 10
  - `1071`: 7
  - `112`: 5
  - `174`: 4
  - `104`: 1

## 负局铺场道具/支援者空过与误用（pre-Mega）

| kind | 负局合计 | no_mega 子集 | 错前场子集 |
|---|---:|---:|---:|
| `wrong_play_side_basic` | 42 | 14 | 36 |
| `wrong_play_boss` | 12 | 6 | 12 |

## Top 负局（优先 seat B + no_mega/late + 暴露/卡住 + 空过）

| i | seat | steps | path | solo | wrong | miss | miss_kinds | log |
|---:|---|---:|---|---|---|---:|---|---|
| 65 | B | 34 | no_mega | False | True | 2 | wrong_play_boss:2 | `games/game_065.log` |
| 85 | B | 97 | mega_late_>6 | False | True | 2 | wrong_play_side_basic:2 | `games/game_085.log` |
| 89 | B | 54 | no_mega | False | True | 2 | wrong_play_side_basic:2 | `games/game_089.log` |
| 181 | B | 57 | no_mega | False | True | 4 | wrong_play_boss:2,wrong_play_side_basic:2 | `games/game_181.log` |
| 163 | B | 37 | no_mega | False | True | 0 | — | `games/game_163.log` |
| 165 | B | 35 | no_mega | False | True | 0 | — | `games/game_165.log` |
| 187 | B | 16 | no_mega | True | False | 0 | — | `games/game_187.log` |
| 43 | B | 51 | no_mega | True | True | 0 | — | `games/game_043.log` |
| 73 | B | 58 | no_mega | False | True | 0 | — | `games/game_073.log` |
| 153 | B | 81 | no_mega | False | False | 2 | wrong_play_side_basic:2 | `games/game_153.log` |
| 7 | B | 93 | fast_mega_t≤3 | False | True | 2 | wrong_play_boss:2 | `games/game_007.log` |
| 41 | B | 91 | fast_mega_t≤3 | False | True | 2 | wrong_play_side_basic:2 | `games/game_041.log` |
| 79 | B | 71 | fast_mega_t≤3 | True | True | 2 | wrong_play_side_basic:2 | `games/game_079.log` |
| 103 | B | 70 | fast_mega_t≤3 | False | True | 2 | wrong_play_side_basic:2 | `games/game_103.log` |
| 109 | B | 59 | fast_mega_t≤3 | False | True | 2 | wrong_play_side_basic:2 | `games/game_109.log` |
| 173 | B | 97 | mega_t4-6 | False | True | 4 | wrong_play_boss:2,wrong_play_side_basic:2 | `games/game_173.log` |
| 21 | B | 37 | fast_mega_t≤3 | True | False | 0 | — | `games/game_021.log` |
| 27 | B | 46 | fast_mega_t≤3 | False | True | 0 | — | `games/game_027.log` |
| 37 | B | 91 | fast_mega_t≤3 | False | True | 0 | — | `games/game_037.log` |
| 39 | B | 47 | fast_mega_t≤3 | False | True | 0 | — | `games/game_039.log` |

## 原因解读（自动）

- `ever_wrong_active` 偏高属预期：开局常以土龙/愿增猿/雪童子起步再铺海星；请结合 `wrong_active_turns` 与 `no_mega` 子集看是否**长期卡住**。
- 负局最常见铺场问题: `wrong_play_side_basic`×42, `wrong_play_boss`×12。
- **no_mega 负局**最常见: `wrong_play_side_basic`×14, `wrong_play_boss`×6。
- 交替空过 (`miss_switch`=0) 相对少；侧基础误铺 (`wrong_play_side_basic`=42) 与 Mega 检索支援/Ball 空过 (Hilda+Salvator+UB_mega=0) 更突出。
- 真·单底座裸露全量 30/200；负局 11 — 多数伴随 Mega 砖在奖/库，而非「有道具却不铺」。

> 指标来自同局 `engine_logs` 双侧派生；勿用同 seed 重跑当 A/B。
