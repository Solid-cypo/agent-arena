# ops_firefix 谱系与 Opening 对照

你贴的描述 **100% 命中** 提交 [`55115028`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) `submission_starmie_ops_firefix.tar.gz`（2026-07-30，publicScore **516.8**）。

本地闸与描述一致（`data/opening_sft/ops_firefix_eval_ship.log`）：Hybrid 3×200 **open 81.2% / megaT3 77% / win 96%**。

## 「815 / 580」更贴的读法

| 记忆 | 更可能指 |
|---|---|
| **815** | 这带 Hybrid **open ≈ 81.2–81.5%**（ops_firefix / ops_alak_planb），不是榜分 815 |
| **580** | **`combat_loop` 55014671 = 557.6**（同代强槽） |

## 这版及之后（Opening 仍好看的几发）

| sub | 包名 | 分 | 本地 Opening 信号 | 备注 |
|---|---|---:|---|---|
| `55014671` | combat_loop | 557.6 | open 91.2% megaT3 76.2% | 对照槽，你说的~580 |
| `55030098` | energy_fix | 535.9 | probe bad_attach=0 | 牌组能量改 |
| `55031841` | ops_fix | 489.3 | L0 open/mega偏 | ops 前身 |
| `55032409` | ops_fix FULL | 442.2 | Hybrid open 74.2% megaT3 73.2% | FULL GATES |
| `55114472` | combat_loop RESTORE | 465.6 | 同 557 包重提 | 占位 |
| `55115028` | ops_firefix | 516.8 | Hybrid open 81.2% megaT3 77% win 96% | 你点名的这版 |
| `55129509` | ops_alak_planb | 463.9 | Hybrid open 81.5% megaT3 76.2% | KEEP firefix |
| `55150906` | combat_v1 | 492.7 | T1 open 86.7% megaT3 77.8% | KEEP firefix 516.8 |
| `55161069` | surplus861_deckfix | 524.5 | deck fix on combat_v1 线 | 其后几版 |
| `55202093` | must-attack | 483.3 | TurnPlan 后 | Opening 仍可 |
| `55209165` | must-attack plug | 446.1 | — | — |
| `55299191` | Wave I+L | 438.9 | — | 掉 |
| `55312234` | Wave U+U5.1 | 406.8 | — | 崩 |

## 备份现状（硬事实）

- 本机 **找不到** `submission_starmie_ops_firefix.tar.gz`（磁盘事故后 git 在 **2026-07-05 → 2026-07-31 无提交**）。
- git 里仅有 `v1off` tar（已恢复）；`combat_loop` / `ops_firefix` tar **未进版本库**。
- Kaggle CLI **不能**回下载自己的 submission 文件；只能拉 episode/replay。
- 代码痕迹：当前 HEAD 仍有 Crispin `ATTACH_TO/FROM` ban、`EVOLVE_66` DOMINATE、Resentful 相关路径——但是叠在 TurnPlan/Wave 上的后代，**不是** 7/30 原包。

## 下一步（需你拍板）

1. **若你本地/网盘还有该 tar**：丢到 `data/restore_peaks/`，我立刻解包并对 HEAD 做 Opening/中盘 diff。
2. **若没有 tar**：用「行为复原」——按提交说明 + `ops_firefix_eval_*` + fade 文档，从 `55202093`/`f07e541` 或更早可跑包反推 fire-loop 子集（不如原包干净）。
3. Opening 金标对照建议：**ops_firefix（open~81%）** 为主，`v1off`（W/L 75.8%）为次；不要再用 Wave U 当 Opening 基线。
