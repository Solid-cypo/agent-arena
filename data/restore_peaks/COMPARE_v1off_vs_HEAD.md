# 峰值版本找回与对比（v1off / Opening 金标时代）

## 你说的「815 / 稳定 580」在账本上最接近什么？

Kaggle **没有** publicScore=815 的提交。和记忆最对齐的是两套数字：

| 你的记忆 | 账本对应 | 证据 |
|---|---|---|
| **最佳 ~815** | 本地 `combat_loop` hybrid **megaT4 = 0.815**（r2） | `data/opening_sft/deploy_combat_loop_3x200_summary.json` |
| **稳定 ~580** | 线上 **`55014671` combat_loop = 557.6**（同代 ops_firefix 516–557 带） | Kaggle submissions |
| Opening「约 75 分人类」 | **`54318518` v1off**：本地 OPENING **72.4%** / W/L **75.8%**（N=500 vs walrein）；线上曾到 **600** | commit `71c25ee` 说明；tag `v1-opening-71pct` |

更早还有 Tea Party 时代 672/655（**另一副牌**，不是海星线）。

> 若你记得的 815 是线上总分而不是 megaT4，请指出来源（截图/别的账号）；当前账号提交峰值海星线是 **600（v1off）** 与 **557（combat_loop）**。

## 已找回的备份

| 产物 | 路径 |
|---|---|
| v1off 原包（=提交 `54318518` 同族） | [`data/restore_peaks/submission_starmie_v1off.tar.gz`](submission_starmie_v1off.tar.gz) |
| 解包目录 | [`data/restore_peaks/v1off_54318518/`](v1off_54318518/) |
| git 源 | `git show 71c25ee:submission_starmie_v1off.tar.gz` |
| Opening HR-O6/O7 代码点 | commit `5ae4cae`（completion 34%→71%） |
| git tag | `v1-opening-71pct` → `eedc841` |

**尚未在本机找到** `submission_starmie_combat_loop.tar.gz` 二进制；`combat_loop` 时代代码多半在 7 月底磁盘事故前后，git 主线在 TurnPlan（`449043f`）才又变厚。若你本地/网盘还有该 tar，丢进 `data/restore_peaks/` 即可并排 diff。

## 与当前 HEAD 的结构差（核心）

| 文件 | v1off | 现在 | Δ |
|---|---:|---:|---:|
| `starmie_pilot.py` | **1695** | **5297** | +3602 |
| `opening_planner.py` | 1049 | 1687 | +638 |
| `opening_bridge.py` | 370 | 869 | +499 |
| `turn_planner.py` | **无** | **1275** | 新增总控 |
| pilot 目录文件数 | ~13 | **50+**（大量 unit RL npz） | 膨胀 |

符号级：

| 符号 | v1off | 现在 |
|---|---:|---:|
| `TurnPlan` / `build_turn_plan` | 0 | 有 |
| `_fueled_mega_must_attack` | 0 | 有 |
| `must_attack` / `attack_required` | 0 | 有 |
| `DOMINATE_OPEN_PATH` | 1 | **151** |
| `HR-O6` / `HR-O7` | 有（Opening 筋） | 仍有残留 |

**结论：** 你要的「Opening ~75% 那版」就是 **v1off 硬规则时代**——没有 TurnPlan，pilot 约 1.7k 行。现在是 TurnPlan + Wave 叠刀后的 **5.3k 行** 总控架构；Opening 金标筋（HR-O6/O7）还在，但决策主路径已被 `_turn_plan_hard_bonus` / `DOMINATE_OPEN_PATH` 淹没。

## 建议下一步（对照，不先改码）

1. 把 `v1off` 固定为 Opening 行为金标：对同 seed 跑 opening completion vs 当前 HEAD。  
2. 若你确认「稳定 580」= `combat_loop` 557：继续追该 tar（Kaggle 网页手动下载 / 旧机器），再做 combat 段 diff。  
3. 差分报告只回答两个问题：  
   - Opening：现在相对 v1off 掉在哪些 HR / bridge？  
   - 中盘：TurnPlan must-attack 相对 combat_loop/v1 是否把「有 Mega 必打」搞丢？

```bash
# 已解包，可直接当 baseline 跑
ls data/restore_peaks/v1off_54318518/pilot/starmie_pilot.py
```
