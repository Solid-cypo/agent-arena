# AgentArena — 协作者快速上手指南

> **VPS**：Ubuntu 20.04 | Los Angeles | 1 GB RAM, 2 vCPU  
> **比赛**：[Kaggle PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)  
> **当前最高分**：761.4（Tea Party + tea_v4 + 28维 policy）  
> **更新**：2026-06-23（Starmie Phase 1–4 合并）

---

## ⚡ 同事交接 — 2026-06-23（Starmie 全 Phase 合并）

### 今日合并内容（一条 PR）

| 模块 | 状态 | 说明 |
|---|---|---|
| **Part 1 OPENING** | ✅ | `opening_planner` + `simulate_opening.py`；Goal **9/10**（batch 10 seed 42） |
| **Step A 桥接** | ✅ | `opening_bridge.py` → `starmie_pilot` HR-O Main（1150 分，仅 OPENING） |
| **Part 2 AGGRESSION** | ✅ | HR-2~11、联动 ~15%、大海星 Jetting ≥85%；`audit_aggression_abilities.py` |
| **Phase 2 过牌轴** | ✅ | `deck_resources` / `supporter_planner` / `draw_axis` + `02_draw_axis.md` |
| **Phase 3 HARVEST** | ✅ | HR-H1~H8（861 进化/贴水/Resentful/Judge 顺序）；`audit_harvest.py` |
| **Phase 4 CONTROL** | ✅ | modifier（领先 ≥1 奖）；HR-C1~C4 Meowth/Boss/Judge；`04_control.md` |
| **Submission** | ✅ | `submission_starmie/` 薄封装 + `scripts/sync_starmie_submission.py` |
| **单元测试** | ✅ | `tests/test_starmie_pilot.py` **54/54 PASS** |

**架构解耦（勿混）**

| 模块 | 职责 |
|---|---|
| `opening_planner` + `simulate_opening` | Part 1 独立模拟器，**不 import** `starmie_pilot` |
| `opening_bridge` + HR-O* | 全对局 OPENING 决策 |
| `starmie_pilot` AGGRESSION 规则 | 愿增猿联动、Jetting、HR-8b 封锁 861 |
| `_harvest_hard_rules` | 仅 HARVEST primary |
| `_control_hard_rules` | 仅 `control_active` modifier |

**Phase 文档链**（`.agent/skills/piloting_starmie_froslass/references/phases/`）

```
00_fsm_overview.md → 01_opening.md → 02_draw_axis.md → 03_harvest.md → 04_control.md
```

### 快速验证

```bash
cd /root/agent-arena

# 单元测试（毫秒级）
python3 tests/test_starmie_pilot.py          # 期望 54/54
python3 tests/test_opening_simulator.py      # Opening 模拟器
python3 tests/test_draw_axis_framework.py    # 过牌轴框架

# Opening 模拟（Part 1，独立于 pilot）
python3 .agent/skills/piloting_starmie_froslass/scripts/simulate_opening.py \
  --batch 10 --seed 42

# Layer 1 审计
python3 .agent/skills/piloting_starmie_froslass/scripts/audit_aggression_abilities.py \
  --seeds 42 43 44 45 46 --opponent walrein
python3 .agent/skills/piloting_starmie_froslass/scripts/audit_harvest.py \
  --seeds 42 43 44 45 46 47 48 49 50 51 --opponent walrein
python3 .agent/skills/piloting_starmie_froslass/scripts/audit_control.py \
  --seeds 42 43 44 45 46 --opponent walrein

# 同步 submission 源码（改 skill/scripts 后必跑）
python3 scripts/sync_starmie_submission.py
python3 scripts/package_starmie.py --weights data/training/best_weights_starmie_v1.json
```

### 审计 KPI（最近一次 walrein 10 seeds）

| 审计 | 指标 | 结果 |
|---|---|---|
| AGGRESSION | 愿增猿联动 | ~15%（10–25% 可接受） |
| AGGRESSION | 大海星 Jetting 出招 | ≥85% |
| HARVEST | Resentful 战斗出招 | 6/6 (100%) |
| HARVEST | Judge 先于 Resentful | 0 违规 |
| CONTROL | Judge 先于 Resentful | 0 违规 |

日志目录：`.agent/skills/piloting_starmie_froslass/logs/`

### 打包 & Kaggle 提交（海星）

```bash
python3 scripts/sync_starmie_submission.py
python3 scripts/package_starmie.py --weights data/training/best_weights_starmie_v1.json

kaggle competitions submit -c cabt -f submission_starmie.tar.gz \
  -m "Starmie+Froslass Phase1-4 pilot: opening bridge, harvest, control modifier"
```

Kaggle 认证：`~/.kaggle/kaggle.json`（勿提交到 git；见 `.env.example`）。

### 海星卡组两层架构

**卡组**：`data/decks/starmie_froslass.csv`  
**Skill**：`.agent/skills/piloting_starmie_froslass/`

- **Layer 1 硬规则**：OPENING 路径 / AGGRESSION Jetting+Adrena / HARVEST 861+Resentful / CONTROL Meowth+Judge
- **Layer 2 软维**（4 个可训练）：`froslass_harvest`, `jetting_blow_pref`, `nebula_finish`, `boss_gust_path`

入口：`make_starmie_agent(deck, weights)` → `submission_starmie/main.py`

---

## 1. 快速连接环境

```bash
cd /root/agent-arena
python3 -c "from cg.api import all_card_data; print(len(list(all_card_data())), 'cards OK')"
python3 run_arena.py play --games 4
```

---

## 2. 项目背景

Kaggle PTCG AI 对战：提交 `submission.tar.gz`（`main.py` + `deck.csv` + `weights.json` + `cg/`）。

---

## 3. 目录结构（增补 Starmie）

```
agent-arena/
├── .agent/skills/piloting_starmie_froslass/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── starmie_pilot.py       # Layer 1/2 主 pilot
│   │   ├── opening_planner.py     # Part 1 OPENING 模拟（独立）
│   │   ├── opening_bridge.py      # Step A → 全对局 OPENING
│   │   ├── phase_fsm.py           # OPENING/AGGRESSION/HARVEST + CONTROL modifier
│   │   ├── deck_resources.py      # 牌库资源推断
│   │   ├── supporter_planner.py   # DR-* 支援者
│   │   ├── draw_axis.py           # DD-* 66 循环
│   │   ├── simulate_opening.py    # Opening 批测
│   │   ├── audit_*.py             # Layer 1 KPI 审计
│   │   └── train_starmie.py       # Layer 2 进化搜索
│   └── references/
│       ├── deck_knowledge.md
│       ├── opening_book.md
│       └── phases/                # 00–04 Phase 设计
├── submission_starmie/            # Kaggle 海星提交包源码
│   ├── main.py                    # 薄封装 → make_starmie_agent
│   └── pilot/                     # sync_starmie_submission 同步
├── scripts/
│   ├── sync_starmie_submission.py
│   └── package_starmie.py
└── tests/
    ├── test_starmie_pilot.py      # 54 BDD
    ├── test_opening_simulator.py
    └── test_draw_axis_framework.py
```

---

## 4. 核心架构

### Tea Party（主天梯提交）

29 维 `arena/policy.py` + `submission/main.py` — 详见下文 §5–§7。

### Starmie+Froslass（实验提交）

```
obs → compute_situation → option_score
         │                    ├─ Layer 1 hard rules (DOMINATE 1000+)
         │                    └─ baseline + Layer 2 soft dims
         phase_fsm: primary ∈ {OPENING, AGGRESSION, HARVEST}
                    control_active = prize_self < prize_opp
```

---

## 5. 当前使用的卡组

| 卡组 | 路径 | 提交包 |
|---|---|---|
| Tea Party #2 | `deck.csv` | `submission/submission.tar.gz` |
| Starmie+Froslass | `data/decks/starmie_froslass.csv` | `submission_starmie.tar.gz` |
| Walrein Control | `data/decks/walrein_control.csv` | 训练对手 |

---

## 6. 权重文件

| 文件 | 说明 |
|---|---|
| `best_weights_tea_v4.json` | Tea Party 当前最佳 |
| `best_weights_starmie_v1.json` | 海星 Layer 2 默认权重 |
| `best_weights_starmie_v2.json` | 海星 v2 训练输出（如有） |

---

## 7. 常用命令

```bash
# Tea Party eval
python3 run_arena.py eval --games 40 \
  --deck-a deck.csv \
  --deck-b data/decks/walrein_control.csv \
  --weights data/training/best_weights_tea_v4.json

# 海星本地对战
python3 run_arena.py eval --games 20 \
  --deck-a data/decks/starmie_froslass.csv \
  --deck-b data/decks/walrein_control.csv \
  --agent-a submission_starmie/main.py

# Tea Party 打包
python3 scripts/package_submission.py --weights data/training/best_weights_tea_v4.json
```

---

## 8. BDD 测试

| 套件 | 用例数 |
|---|---|
| assessing_situations | 17 |
| routing_states | 16 |
| evaluating_actions | 30 |
| test_starmie_pilot | 54 |
| test_opening_simulator | 见脚本输出 |
| test_draw_axis_framework | 见脚本输出 |

---

## 9. 注意事项

1. **`deck.csv` 注释行**以 `#` 开头，加载时跳过  
2. **ACE SPEC** 每套牌最多 1 张  
3. **`cg/` 勿改** — 官方引擎  
4. **改 skill/scripts 后** 跑 `sync_starmie_submission.py` 再 `package_starmie.py`  
5. **Opening 模拟器与 pilot 解耦** — Part 1 不 import `starmie_pilot`  
6. **HARVEST 禁 Judge**（Resentful 前）；**CONTROL Judge** 仅在非必攻窗口或 Resentful 后  

---

## 10. Kaggle 提交历史

| 分数 | 卡组 | 备注 |
|---|---|---|
| **761.4** | Tea Party | 当前最高 |
| — | Starmie+Froslass | Phase 1–4 pilot 待交 |

---

## 11. Git 分支

当前功能分支：`feat/opening-simulator-rules` → PR 合并 `master`  
包含：Opening 模拟器 + Phase 2–4 pilot + submission_starmie + 测试/审计脚本。
