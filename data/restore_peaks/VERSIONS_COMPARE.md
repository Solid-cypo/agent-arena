# Versions 对照：怎么恢复 Opening、中盘怎么接

源包：`.agent/Versions/`（已解包到 `.agent/Versions/unpacked/`）

| 包 | 线上印象 | pilot 行数 | TurnPlan | Opening 入口 |
|---|---|---:|---|---|
| **combat_loop** | ~580（557.6） | 2676 | 无 | `score_opening` 很早（约第 6 个 return 前） |
| **ops_firefix** | 516.8 | 3202 | 无 | 前插 ops/861/66，再 opening |
| **surplus861_deckfix** | 524.5 | 3941 | 无 | 再叠 Alak/Boss，再 opening |
| **HEAD** | 崩后叠刀 | 5666 | **有** | opening 前约 **67** 个 return 点 |

## 结构事实

1. **`opening_planner.py`**：combat / firefix / surplus **md5 相同**；HEAD 仅微差。  
2. **`opening_bridge.py`**：combat ≠ firefix（=surplus）；HEAD 又漂了一版。  
3. **牌组**：combat 是旧能量线（无 Prism/Ignition，+1 水 +1 恶）；firefix=surplus=HEAD 是新能量线。  
4. **退化主因不是 planner 文件丢了**，而是 HEAD 在 `_hard_rule_bonus` 最前面塞了 must-attack / plan-step / mega_clock / TurnPlan，**Opening path 轮不到优先发言**。

## vs walrein Opening 短闸（n=80 s82000，rules-only）

| 包 | open | megaT3 | megaT4 | win |
|---|---:|---:|---:|---:|
| combat_loop | 91.2% | 81.2% | 83.8% | 88.8% |
| ops_firefix | 71.2% | 70.0% | 72.5% | 95.0% |
| surplus861 | 83.8% | 73.8% | 78.8% | 97.5% |
| HEAD | **97.5%** | **88.8%** | 92.5% | 98.8% |

注意：HEAD 在弱对照上 Opening **数字更高**，但同 seed 对战金标时 Active/T1 链仍乱——**不能再用 walrein open% 当「开局好」的唯一闸**。线上 580 的价值是**决策干净 + 对真实分布稳**，不是这个玩具对照上的 open 刷分。

## 建议怎么做（按优先级）

### 推荐：双代理交接（最贴「开局沿用 580」）

```
phase == OPENING（或 not opening_ever_complete）
  → 完全用 combat_loop 的 agent_fn 选招
opening_complete（Active Mega+water）之后
  → 交回 HEAD（TurnPlan / Knife / Alak…）
```

- **利**：不猜该搬哪些 HR；行为就是 580 包。  
- **弊**：要处理两套 `agent_state` / reset；牌组建议仍用 **HEAD 现牌**（surplus 能量线），接受 combat 开局是在「新牌组上跑旧逻辑」（需同 seed 对照验收）。

### 备选：只移植 Opening 入口顺序（改 HEAD）

在 `phase.primary == "OPENING"` 时：

1. 恢复 combat 的前缀：attach ban → discard → fuel → BanBoss → synergy → **`score_opening_option`**  
2. **跳过** plan-step / `_turn_plan_hard_bonus` / mega_clock 抢位（完成后照常）  
3. `opening_bridge.py` 回滚到 combat 版（planner 本就同族）

- **利**：单进程、好维护。  
- **弊**：上次「只关 TurnPlan」已证伪到 37%——必须连 **bridge + 顺序** 一起回，不能只拔规划器。

### 明确不要做的

- 不要再拿 firefix 当「你的开局金标」（那是对照包，不是 580）。  
- 不要在 OPENING 上继续加 plan-step / pre-dig 全局锁。  
- 中盘专家意见（Alak、861、must-attack）只挂在 **`opening_ever_complete` 之后**。

## 验收闸（拆开）

1. **Opening**：同 seed × combat_loop，Active / T1 链一致率；walrein open/megaT3 作辅。  
2. **强度**：vs firefix n200 s82000，WR≥45% 不崩；目标追平曾有的 A2 ~49%。  
3. **纪律**：plan-step 合规只统计 **handoff 之后** 的步。

## 路径

- 解包：`.agent/Versions/unpacked/{combat_loop,ops_firefix,surplus861_deckfix}/`  
- 本对照：`data/restore_peaks/compare_versions_opening_n80.md`
