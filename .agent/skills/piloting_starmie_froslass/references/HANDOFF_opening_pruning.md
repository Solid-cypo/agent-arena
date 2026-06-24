# OPENING 硬编码剪枝 · 开发交接文档

> **受众**：接手 `piloting_starmie_froslass` OPENING 模拟器与剪枝优化的同事  
> **最后更新**：2026-06-24  
> **分支**：`feat/opening-simulator-rules`  
> **规格来源**：`references/phases/01_opening.md`、`references/opening_book.md`、`references/opening_sim_bugs.md`

---

## 1. 项目目标与 KPI

### 1.1 OPENING 终局（Goal）

Active 为 **Mega 大海星 ex (1031)** 且附有 **≥1 水能**（含棱镜贴基础时算水线）。

### 1.2 规格 KPI（`01_opening.md` §9）

| 指标 | 目标 | 当前实测（500 seed, seed_base=0） | 状态 |
|---|---:|---:|---|
| **CP1** — My-T1 结束 1030 在场上 | ≥ **85%** | **78.8%** (394/500) | ❌ 未达标 |
| **Goal@My-T2** — My-T2 内达成 Goal | ≥ **60%** | **35.8%** (179/500) | ❌ 未达标 |
| **Goal@My-T5** — 5 回合内达成 | （参考） | **58.0%** (290/500) | 部分局需 T3–T5 |
| **Goal@My-T12** — 放宽上限 | （诊断用） | **88.4%** (442/500) | 牌库可达，T2 窗口太紧 |
| **规则违规** | 0 | 0（`validate_log` 批量通过） | ✅ |
| **回归 10-seed** | — | **9/10** (seed 42–51, max5) | ✅ |

**结论（给优化者的核心判断）**：

- **My-T2 Goal 85% 在当前 deck + 硬规则下不可达**；即使放宽到 12 回合也只有 ~88% Goal，说明瓶颈在 **T1/T2 路线质量**，不是单纯「多给回合」。
- **CP1 78.8%** 主要被 **B1/C1/X1** 等非 S1 原型拖累（B1 138/500、C1 106/500）。
- 下一优先级：**扩展 T1 候选 / CP1 rescue**（`_ensure_cp1_staryu`），而非放宽 `opening_validate`。

### 1.3 后续路线（团队规划，尚未实现）

| 阶段 | 内容 | 状态 |
|---|---|---|
| Gate + LightGBM | 开局 archetype 分类器 | 规划中 |
| Active Learning | 专家审计 110 条 hard-case → 训练 | 数据已导出 |
| Parser / Feature / Train | 日志解析 + 特征 + 模型 | 未开始 |

---

## 2. 架构总览

```
data/decks/starmie_froslass.csv
    ↓ shuffle + mulligan
setup_planner.run_setup()              Phase 0：Active/Bench + archetype
    ↓ My-T1 .. My-T5
opening_planner.plan_and_execute_turn()  ← 【硬编码剪枝核心】
    ↓
opening_state.OpeningGameState         可变模拟状态 + 动作日志
    ↓
opening_validate.validate_log()        E-CRIS-1 / E-PAD-1 / E-HILDA-1 …
    ↓ 导出
opening_log_formatter                  中文 + 去 debug + 去重 skip
filter_opening_hard_cases              7:3:1 分层 110 条
split_hard_case_packs                  11×10 中文包
```

**战斗侧（独立）**：`opening_bridge.py` — live obs 上 `pick_route()` + `score_opening_option()` 打 **1150** 分 dominate 路径。

**隔离约束**：`simulate_opening.py` **不得 import** `starmie_pilot`（见 `SKILL.md`）。

---

## 3. 「硬编码剪枝」设计与优化记录

代码中无 `prune` 关键字；团队所称 **剪枝** = **固定候选路线集 + 整数启发式打分**，替代全树搜索 / ML。

### 3.1 每回合剪枝流程（`plan_and_execute_turn`）

```
1. diagnose_gaps(st) → GapFlags G1–G5
2. 记录 gaps NOTE（导出时被 formatter 剥离）
3. 枚举候选 (route_name, pre_fn, primary_fn)
4. 对每个候选：
     trial = deepcopy(st)
     _run_turn_pipeline(trial, pre, primary)
     score = _score_opening_state(trial)
5. 取最高分 → _apply_turn_log → 返回 route 名
```

### 3.2 候选集（剪枝边界）

**My-T1**（默认顺序，可被 insert(0) 提升）：

| 候选 | 含义 |
|---|---|
| `GREEDY-T1` | 贪心主链 + CP1 tail |
| `R1-T1` | Hilda 链 |
| `MEOWTH-T1` | 喵头目 → 搜希尔达 |
| `FAN-T1` | 旋转罗盘 Fan Call |
| `POFFIN-T1` | 伙伴糖果铺场 |
| `PAD-T1` | 宝可梦手环 |

**My-T2+**：

| 候选 | 含义 |
|---|---|
| `GREEDY-T2` | 贪心完成 Goal |
| `BENCH-T2` | `_prepare_bench_evolve_line` |
| `WATER-T2` | `_turn_water_first` 优先贴水 |

> ⚠️ `pick_route()` 中的 R1–R8 / REC 命名用于**规格语义与 opening_bridge**；模拟器实际输出 `GREEDY-T2` 等，两套命名勿混读。

### 3.3 打分函数 `_score_opening_state`

| 条件 | 分值 |
|---|---:|
| `opening_complete()` | **100,000** |
| Active Mega + 水 | **100,000** |
| 场上有 Staryu | +800；Staryu 有水 +400 |
| 手牌有 1031 | +350 |
| 场上有 Mega | +500；Mega 有水 +600 |
| My-T1 场上无 Staryu | **-3000** |
| gaps.g2（无水） | -250 |
| gaps.g3（手牌无 1031） | -200 |

这是**硬编码启发式**，非训练权重；改分即改剪枝偏好。

### 3.4 缺口 taxonomy（`diagnose_gaps` → `GapFlags`）

| Flag | 含义 | 典型恢复 |
|---|---|---|
| G1 | 场上无 1030/Mega 线 | Poffin/Pad/Ball/Fan |
| G2 | 1030/Mega 在场但无水 | Crispin/Hilda attach / 手贴水 |
| G3 | 手牌无 1031 | Hilda/Ball/Pad |
| G4 | 进化锁（当回合上场） | 等 T2 或 Salvatore |
| G5 | 1031 在 Bench 未升 Active | Switch / retreat 线 |

失败分型 `classify_miss` → **F-A ~ F-F**（见 `opening_planner.classify_miss`）。

### 3.5 已完成的规则修复（勿回退）

| 规则 | 问题 | 修复位置 |
|---|---|---|
| **E-CRIS-1** | Crispin 曾贴 Prism/Ignition | `CRISPIN_BASIC_ENERGY`；`crispin_search()` 仅 3/7 |
| **E-ATT-1** | 贴能优先 Prism 而非水 | `attach_water_to()` 水 > 棱镜 |
| **E-PAD-1** | Pad 搜 ex | `PAD_SEARCH_IDS` + validate |
| **E-HILDA-1** | Hilda 搜 1030 | `HILDA_EVOLUTION_IDS` + validate |
| **贴水贪心** | T2 进化/升场顺序错 | `_greedy_opening_turn` 优先级重写 |
| **Crispin 撤退线** | 恶能贴 Active、水入手 | `crispin_search(attach_target=…)` |

### 3.6 附能优先级 `_best_attach_target`

1. Active Mega 1031 且无水  
2. 场上 Staryu 无水  
3. Bench Mega 无水  

---

## 4. 模块职责速查

| 文件 | 核心 API | 职责 |
|---|---|---|
| `setup_planner.py` | `run_setup`, `classify_archetype` | Phase 0 |
| `opening_state.py` | `OpeningGameState`, `crispin_search`, `attach_water_to` | 状态机 |
| `opening_planner.py` | `plan_and_execute_turn`, `_score_opening_state`, `classify_miss` | **剪枝 + 执行** |
| `opening_validate.py` | `validate_log` | 硬规则回放 |
| `simulate_opening.py` | `simulate_opening`, `run_batch`, `export_sim_record` | CLI / 批量 |
| `opening_log_formatter.py` | `format_actions`, `format_log_text` | 专家可读日志 |
| `filter_opening_hard_cases.py` | `run_batch_and_filter` | 2000 局 → 110 条 7:3:1 |
| `split_hard_case_packs.py` | `split_packs` | 11×10 中文包 |
| `opening_bridge.py` | `score_opening_option` | 对战 Layer1 dominate |
| `opening_cards.py` | 卡 ID、白名单常量 | 单一事实源 |

---

## 5. 测试方法

工作目录：`/root/agent-arena`

### 5.1 单元 / 回归

```bash
# OPENING 模拟器（Setup + Gap + Phase0 seeds）
python3 tests/test_opening_simulator.py

# Layer1 全 Phase（54 tests）
python3 tests/test_starmie_pilot.py
```

### 5.2 单局 / 批量 KPI

```bash
SCRIPTS=.agent/skills/piloting_starmie_froslass/scripts

# 单局 verbose
python3 $SCRIPTS/simulate_opening.py --seed 42 --max-turns 5

# 10-seed 回归（期望 9/10 Goal@max5）
python3 $SCRIPTS/simulate_opening.py --batch 10 --seed 42 \
  --export .agent/skills/piloting_starmie_froslass/logs/test_batch_max5.log

# 500-seed KPI（约 30s）
python3 $SCRIPTS/simulate_opening.py --batch 500 --seed 0 --max-turns 5 \
  --export .agent/skills/piloting_starmie_froslass/logs/opening_batch_max5_0.log

# My-T2 硬 deadline（max-turns=2 等价 Goal@T2）
python3 $SCRIPTS/simulate_opening.py --batch 500 --seed 0 --max-turns 2 \
  --export .agent/skills/piloting_starmie_froslass/logs/opening_batch_max2_0.log
```

### 5.3 规则校验

```bash
python3 -c "
import sys; sys.path.insert(0,'$SCRIPTS'); sys.path.insert(0,'.')
from pathlib import Path
from arena.deck import load_deck_csv
from simulate_opening import simulate_opening
from opening_validate import validate_log
base = load_deck_csv('data/decks/starmie_froslass.csv')
for seed in range(100):
    st = simulate_opening(base, shuffle=True, seed=seed, verbose=False)
    v = validate_log(st)
    assert not v, f'seed {seed}: {v}'
print('100 seeds: 0 violations')
"
```

### 5.4 Hard-case 导出（Active Learning 数据）

```bash
# 2000 局 → 110 条（70 负 / 30 待优化 / 10 正）
python3 $SCRIPTS/filter_opening_hard_cases.py \
  --games 2000 --seed-base 0 --export-limit 110 \
  --out .agent/skills/piloting_starmie_froslass/logs/hard_cases/YYYYMMDD_fmt

# 拆 11 包 × 10 条 + 中文
python3 $SCRIPTS/split_hard_case_packs.py \
  --src .agent/skills/piloting_starmie_froslass/logs/hard_cases/YYYYMMDD_fmt \
  --out .agent/skills/piloting_starmie_froslass/logs/hard_cases/packs_zh
```

**样本标签**：

| 标签 | 条件 |
|---|---|
| `negative` | T5 未 Goal 或有规则违规 |
| `to_optimize` | T3–T5 才 Goal（合法但慢） |
| `positive` | My-T1/T2 干净 Goal |

专家在关键步骤后追加：`// [CORRECT: 动作描述]`

### 5.5 同步 Kaggle 提交

```bash
python3 scripts/sync_starmie_submission.py
```

---

## 6. 数据产物

| 路径 | 说明 |
|---|---|
| `logs/opening_batch_max5_0.log` | 500×max5 批量日志 |
| `logs/opening_batch_max2_0.log` | 500×max2（Goal@T2 诊断） |
| `logs/test_batch_max5.log` | 10-seed 回归 |
| `logs/hard_cases/20260624_fmt/` | 110 条 formatter 后导出 + `manifest.json` |
| `logs/hard_cases/packs_zh/` | 11 包 × 10 条中文 + `pack_XX.tar.gz` |
| `logs/hard_cases/opening_packs_zh_all.tar.gz` | 全包合集 |

**manifest 统计（20260624_fmt, 2000 runs）**：

- pool: negative 851 / to_optimize 458 / positive 691  
- exported: 110（7:3:1）

---

## 7. 已知限制与优化方向

| 类别 | 说明 | 建议 |
|---|---|---|
| 候选非完备 | 仅 3–7 条/回合，可能错过更优 R* | 扩展 B1/C1 专属候选 |
| 双 route 命名 | GREEDY-T2 vs R5-REC | 日志对照 `opening_book.md` |
| C1/B1/F1 原型 | Bench 进化 + 撤退费，T2 Goal 低 | 专项 `_prepare_bench_evolve_line` |
| seed 50 类 | 5 回合物理不可达 | 标 E-G1-DECK-1，非 bug |
| 模拟器 vs 战斗 | `plan_and_execute_turn` ≠ `pick_route` 全集 | 对齐 `opening_bridge` 测试 |
| Fan Rotom 废牌 | My-T2+ 手牌 174 禁 PLAY | Ultra Ball 高优先弃 |
| OPENING 禁 Lillie | HR-O6 | RECOVERY 才允许 |

**禁止的「虚抬达成率」手段**（见 `opening_sim_bugs.md`）：Lillie 紧急线、无能量 retreat、Pad 搜 ex、Crispin 贴特殊能等。

---

## 8. 关键函数索引

```python
setup_planner.run_setup(st)
opening_planner.diagnose_gaps(st) → GapFlags
opening_planner.plan_and_execute_turn(st) → "GREEDY-T1"|...
opening_planner._score_opening_state(st) → int
opening_planner._ensure_cp1_staryu(st)      # CP1 rescue
opening_planner._greedy_opening_turn(st)
opening_state.crispin_search(attach_target=...)
opening_state.attach_water_to(target)
opening_validate.validate_log(st) → list[str]
opening_log_formatter.format_actions(actions)
filter_opening_hard_cases.run_batch_and_filter(...)
split_hard_case_packs.split_packs(...)
opening_bridge.score_opening_option(...) → 0.0 | 1150.0±
```

---

## 9. 接手 Checklist

- [ ] `python3 tests/test_opening_simulator.py` 全绿  
- [ ] `--batch 10 --seed 42` → 9/10 Goal  
- [ ] 读 `opening_sim_bugs.md` + `packs_zh/pack_01/` 负样本  
- [ ] 理解 `_score_opening_state` 与候选列表再改剪枝  
- [ ] 改 scripts 后跑 `sync_starmie_submission.py`  
- [ ] 任何 KPI 变更附 500-seed 日志路径

---

## 10. 相关文档

- `references/phases/01_opening.md` — OPENING 完整规格  
- `references/opening_book.md` — 硬编码任务书 v3  
- `references/opening_sim_bugs.md` — BUG-001~006 + E-* 规则  
- `references/deck_knowledge.md` — 卡组战术与卡效  
- `ONBOARDING.md` — 团队快速验证命令
