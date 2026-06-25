# AgentArena — 协作者快速上手指南

> **VPS**：Ubuntu 20.04 | Los Angeles  
> **比赛**：[Kaggle PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)  
> **主线**：Starmie+Froslass 卡组 + 理论建模（FSM 三 Skill）  
> **更新**：2026-06-24（项目清理：移除 Tea Party / Hops / meta 旧 deck）

---

## 1. 项目定位

本仓库 **只保留两条线**：

| 路线 | 说明 |
|---|---|
| **海星 Pilot** | Layer1 硬规则 + Layer2 四软维 → `submission_starmie/` Kaggle 提交 |
| **理论建模** | `references/ptcg_dimension_theory.md` + assessing/routing/evaluating 三 Skill + `arena/fsm_agent.py` |

旧卡组（Tea Party、Hops、Lightning、天梯 meta 30 套）已清理，详见 `references/PROJECT_LAYOUT.md`。

---

## 2. 快速验证

```bash
cd /root/agent-arena

python3 -c "from cg.api import all_card_data; print(len(list(all_card_data())), 'cards OK')"

# 单元测试
python3 tests/test_starmie_pilot.py          # 54/54
python3 tests/test_opening_simulator.py
python3 tests/test_draw_axis_framework.py

# OPENING 模拟（10-seed 回归，期望 9/10 Goal@max5）
python3 .agent/skills/piloting_starmie_froslass/scripts/simulate_opening.py \
  --batch 10 --seed 42

# 本地对战（海星 vs Walrein）
python3 run_arena.py eval --games 20

# 同步 + 打包 Kaggle 提交
python3 scripts/sync_starmie_submission.py
python3 scripts/package_starmie.py --weights data/training/best_weights_starmie_v1.json
```

---

## 3. 目录结构

```
agent-arena/
├── .agent/skills/
│   ├── piloting_starmie_froslass/    # 海星：pilot + OPENING 模拟 + 审计
│   ├── assessing_situations/         # 理论：局面评估
│   ├── routing_states/               # 理论：状态路由
│   ├── evaluating_actions/           # 理论：动作打分
│   └── parsing_cards/                # 卡库 card_db.json
├── arena/                            # simulator, policy, fsm_agent
├── cg/                               # 官方引擎（勿改）
├── data/decks/
│   ├── starmie_froslass.csv          # 己方
│   └── walrein_control.csv           # 默认对手
├── submission_starmie/               # Kaggle 提交包
├── references/
│   ├── ptcg_dimension_theory.md
│   └── PROJECT_LAYOUT.md
├── train_weights.py                  # 理论 28 维权重搜索
├── run_arena.py                      # play / eval / fsm
└── tests/
```

---

## 4. 海星架构

**卡组**：`data/decks/starmie_froslass.csv`（60 张）

**两层决策**：
- **Layer 1 硬规则**：OPENING 路径 / Jetting+愿增猿 / HARVEST Resentful / CONTROL Meowth+Judge
- **Layer 2 软维**（4 个可训练）：`froslass_harvest`, `jetting_blow_pref`, `nebula_finish`, `boss_gust_path`

**Phase 文档链**：`.agent/skills/piloting_starmie_froslass/references/phases/00–04`

**OPENING 交接**：`references/HANDOFF_opening_pruning.md`

**解耦**：`simulate_opening.py` **不 import** `starmie_pilot`；全对局 OPENING 走 `opening_bridge.py`。

---

## 5. OPENING KPI（500 seed, seed_base=0）

| 指标 | 目标 | 当前 |
|---|---:|---:|
| CP1（T1 结束 1030 在场上） | ≥85% | **78.8%** |
| Goal@My-T2 | ≥60% | **35.8%** |
| Goal@My-T5 | — | **58.0%** |
| 10-seed 回归 | — | **9/10** |
| 规则违规 | 0 | **0** |

---

## 6. 常用命令

### Kaggle 提交

```bash
python3 scripts/sync_starmie_submission.py
python3 scripts/package_starmie.py --weights data/training/best_weights_starmie_v1.json

kaggle competitions submit -c cabt -f submission_starmie.tar.gz \
  -m "Starmie+Froslass pilot"
```

### Layer 1 审计

```bash
python3 .agent/skills/piloting_starmie_froslass/scripts/audit_aggression_abilities.py \
  --seeds 42 43 44 45 46 --opponent walrein
python3 .agent/skills/piloting_starmie_froslass/scripts/audit_harvest.py \
  --seeds 42 43 44 45 46 --opponent walrein
python3 .agent/skills/piloting_starmie_froslass/scripts/audit_control.py \
  --seeds 42 43 44 45 46 --opponent walrein
```

### Hard-case 导出（Active Learning，可重建）

```bash
python3 .agent/skills/piloting_starmie_froslass/scripts/filter_opening_hard_cases.py \
  --games 2000 --export-limit 110
python3 .agent/skills/piloting_starmie_froslass/scripts/split_hard_case_packs.py \
  --src logs/hard_cases/YYYYMMDD_fmt --out logs/hard_cases/packs_zh
```

### 理论权重搜索

```bash
python3 train_weights.py --meta-pool --games 40 --generations 8
python3 run_arena.py fsm --games 10
```

### Layer 2 海星权重训练

```bash
python3 .agent/skills/piloting_starmie_froslass/scripts/train_starmie.py \
  --generations 20 --games 40
```

---

## 7. 权重文件

| 文件 | 说明 |
|---|---|
| `best_weights_starmie_v1.json` | 海星 Layer2 默认 |
| `best_weights_starmie_v2.json` | 海星 v2 训练输出 |
| `best_weights_theory.json` | 理论 28 维搜索输出（运行 `train_weights.py` 生成） |

---

## 8. 注意事项

1. CSV 注释行以 `#` 开头，加载时跳过  
2. **`cg/` 勿改** — 官方引擎  
3. 改 `piloting_starmie_froslass/scripts/` 后必跑 `sync_starmie_submission.py`  
4. HARVEST 禁 Judge（Resentful 前）；CONTROL Judge 仅在非必攻窗口  
5. 对手 `--opponent` 仅支持 `walrein` / `mirror`（审计脚本）

---

## 9. Git

功能分支：`feat/opening-simulator-rules`  
合并目标：`master`
