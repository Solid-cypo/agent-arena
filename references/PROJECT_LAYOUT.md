# AgentArena 项目结构（2026-06-24 清理后）

仓库仅保留 **Starmie+Froslass 卡组开发线** 与 **理论建模（FSM 三 Skill + arena）**。

## 保留内容

```
agent-arena/
├── .agent/
│   ├── docs/agent_design_spec.md          # FSM-Math 架构规格
│   └── skills/
│       ├── piloting_starmie_froslass/     # 海星卡组 Layer1/2 pilot + OPENING 模拟器
│       ├── assessing_situations/          # 理论：局面评估
│       ├── routing_states/                # 理论：状态路由
│       ├── evaluating_actions/            # 理论：动作打分
│       └── parsing_cards/                 # 卡库解析 + card_db.json
├── arena/                                 # 本地仿真、28维 policy、FSM agent
├── cg/                                    # 官方对战引擎（勿改）
├── data/
│   ├── decks/
│   │   ├── starmie_froslass.csv           # 己方卡组（权威源）
│   │   └── walrein_control.csv            # 默认训练/审计对手
│   └── training/
│       ├── best_weights_starmie_v1.json   # Layer2 默认权重
│       └── best_weights_starmie_v2.json
├── references/
│   ├── ptcg_dimension_theory.md           # 三维理论核心文档
│   └── PROJECT_LAYOUT.md                  # 本文件
├── scripts/
│   ├── sync_starmie_submission.py
│   ├── package_starmie.py
│   └── memory_check.py
├── submission_starmie/                    # Kaggle 提交包（海星）
├── tests/                                 # starmie + opening + draw_axis 测试
├── train_weights.py                       # 理论 28 维权重进化搜索
├── run_arena.py                           # play / eval / fsm 本地对战
└── run_marathon.py                        # 长跑矩阵（默认 starmie vs walrein）
```

## 已移除（legacy）

| 类别 | 示例 |
|---|---|
| 旧提交包 | `submission/`、`deck.csv`（Tea Party） |
| 其他己方 deck | `hops_control.csv`、`future_lightning.csv` |
| 天梯 meta 牌组 | `data/meta_decks/`（30 CSV + index） |
| 旧 deck 权重 | `best_weights_tea_v*.json`、`best_weights_hops*.json` 等 |
| 旧脚本 | `package_submission.py`、`auto_submit.py`、`export_meta_decks.py` |
| 旧参考副本 | `references/competition/`、`references/kernels/` |
| 可再生日志 | `hard_cases/` 大批量 opening 日志（见 HANDOFF 重新生成） |

## 两条并行架构

| 路线 | 入口 | 用途 |
|---|---|---|
| **海星 Pilot** | `make_starmie_agent` → `submission_starmie/main.py` | Kaggle 提交、Layer1 硬规则 + Layer2 4 维软权重 |
| **理论 FSM** | `arena/fsm_agent.py` + 三 Skill | 28 维 policy 研究、局面/路由/动作建模 |

OPENING 模拟器（`simulate_opening.py`）独立于 pilot，用于剪枝优化与 hard-case 导出。

## 关键文档

- 海星交接：`piloting_starmie_froslass/references/HANDOFF_opening_pruning.md`
- OPENING 规格：`piloting_starmie_froslass/references/phases/01_opening.md`
- 团队上手：`ONBOARDING.md`
