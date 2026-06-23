# Starmie 开局书 & 硬编码任务规格 v3

> **分阶段详细设计**（逐 Phase 展开）见 `references/phases/`：
> - [00_fsm_overview.md](./phases/00_fsm_overview.md) — FSM 总览 + 全局栈
> - [01_opening.md](./phases/01_opening.md) — **OPENING 完整规格（当前）**
> - 02_aggression / 03_harvest / 04_control — 待续

> **核心目标**：两回合内铺出 **Mega Starmie ex（大海星）**，之后每回合打出有效伤害。  
> **分工**：硬编码 = 战术骨架与路径规划；ML（4 软维）= 微调习惯，不决定生死线。

---

## 1. 三层架构（v3）

```
Phase FSM（开局/压制/收割/控场）
    ↓ 决定当前「任务模式」
Layer 1 硬规则（DOMINATE 拦截，按优先级栈）
    ↓ 未命中则
Layer 2 软维（进化搜索，±0~5 微调）
    ↓ 未命中则
Baseline 17 维通用分
```

| 层 | 职责 | 是否训练 |
|---|---|---|
| Phase FSM | 判断 OPENING / AGGRESSION / HARVEST / CONTROL | 否 |
| Layer 1 | 铺场路径、必攻、Bench 坑位、愿增猿、Fan Call | 否 |
| Layer 2 | Jetting vs Nebula、Boss 目标、大雪妖女时机 | 是（4 维）|

**Kaggle 现状**：v1 硬规则 pilot ≈499 分；v2 过度调参 ≈429 分。  
**v3 方向**：加硬编码，不扩大 ML 维度。

---

## 2. Phase FSM（Setup + 四模式）

### 2.0 Phase 0 — Setup（`obs.turn == 0` 或 `SelectContext.SETUP_*`）

| 项 | 内容 |
|---|---|
| **输入** | 起手 7 张手牌中的 Basic 列表 |
| **决策** | Setup Active（必选）+ Setup Bench（可选，见 [01_opening §3.2](./phases/01_opening.md)） |
| **输出** | `setup_archetype`（S1 / A1 / A2 / B1 / C1 / E1 / F1） |
| **规则** | Active **只能**从手牌 Basic 选；第二张 1030 **不** Setup Bench |

```
Phase 0 Setup → My-T1（CP1）→ My-T2（Goal: Active 1031+水）
```

Setup 原型速查：

| 原型 | Active | My-T1 |
|---|---|---|
| S1 | 手有 1030 | 附水 + 找 1031 |
| A2 | 1030 + Bench 174 | Fan Call + 附水 |
| A1 | 无 1030、有 174 | Fan Call 拿 1030 |
| B1 | Dunsparce | Hilda/Poffin |
| C1/E1/F1 | 降级 Basic | 检索 + Bench 线；T2 达成率低 |

### 2.1 战斗 Phase（Setup 之后）

| 模式 | 进入条件 | 退出条件 | 最高优先级任务 |
|---|---|---|---|
| **OPENING** | Setup 完成；Active ≠ 1031+水 | Active = 1031 且已附 ≥1 水能 | My-T1→CP1；My-T2→Goal；未达成→**RECOVERY**（§5.5） |
| **AGGRESSION** | Goal 达成（Active 1031+水） | 大海星被 KO | 每回合 Jetting Blow；Bench 三坑 |
| **HARVEST** | 大海星被 KO，手牌/牌库仍有 Mega Froslass ex 线 | 大雪妖女出场并完成收割 | 对手手牌多/刚拿奖时进化大雪妖女 |
| **CONTROL** | 我方领先 ≥1 奖（prize_delta ≤ -1） | 领先消失 | Meowth ex 上场搜支援者；Boss/Judge 控场 |

---

## 3. 手牌结构分析 — 要不要做？怎么做？

**要做，但必须轻量、确定性，不用 LLM。**

每回合在 `choose_options` 前算一次 `hand_snapshot`（仅 OPENING / 铺场阶段强制用）：

```python
hand_snapshot = {
    "has_staryu": bool,           # 1030
    "has_mega_starmie_card": bool,# 1031 进化卡在手上
    "has_snorunt": bool,          # 860
    "has_hilda": bool,            # 1225
    "has_poffin": bool,           # 1086
    "has_ultra_ball": bool,       # 1121
    "has_poke_pad": bool,         # 1152
    "has_water_energy": bool,     # 3
    "has_ignition": bool,         # 17
    "has_fan_rotom": bool,        # 174
    "fan_rotom_dead": bool,       # My-T1 后手牌 174 废牌（不可 PLAY Bench）
    "staryu_on_bench": bool,
    "staryu_with_energy": bool,   # bench/active 上 Staryu 已附能
    "mega_starmie_on_field": bool,# active 或 bench 已是 1031
}
```

**用途**：从预设路径表里选出 **当前可行路径**（见第 4 节），对合法 option 打 DOMINATE 或 HIGH 分。

**不需要**：完整牌库贝叶斯、对手手牌推断（OPENING 阶段不做）。

---

## 4. 获取大海星的路径表（预设 + 每回合自查）

> **v3 修订**：须按 **Setup → My-T1（CP1）→ My-T2（Goal）** 两回合设计；  
> 普通 EVOLVE 要求 `appearThisTurn == false`（Salvatore 例外）。  
> 缺口诊断 G1–G7 与 Route R*-T1/T2 见 [phases/01_opening.md](./phases/01_opening.md)。

按优先级从高到低尝试；实现为 `scripts/path_planner.py` 的 `pick_opening_route(my_turn, gaps, setup_archetype)`.

| PathId | 名称 | 前置条件 | 本回合动作链（硬编码优先序） |
|---|---|---|---|
| **P0** | 已就绪 | 1030 在场+已附水+1031 在手+`can_evolve` | **My-T2** EVOLVE → 1031 |
| **P1** | 手牌进化 | 手有 1030+1031+水 | **My-T1** PLAY+ATTACH；**My-T2** EVOLVE（不可同回合进化） |
| **P2** | Hilda 检索 | 手有 Hilda，deck 有 Staryu 或 1031 | PLAY Hilda → 取 Staryu + 能量 → 铺场/附能 |
| **P3** | Poffin 检索 | 手有 Buddy-Buddy Poffin | PLAY Poffin → 取 2 只基础 → 优先 Staryu/Snorunt |
| **P4** | Ultra Ball | 手有 Ultra Ball，弃牌够 | PLAY Ultra Ball → 搜 Staryu/1031；弃 2：**Lillie > My-T1 后手牌 174 废牌 > 重复 Trainer** |
| **P5** | Poké Pad | 手有 Poké Pad | PLAY Pad → 全牌库搜 1 无 Rule Box 宝可梦（Staryu/Snorunt/Dudunsparce 等） |
| **P6** | Fan Call（T1 专属）| turn ≤ 2，Fan Rotom 在场/可上 | ABILITY Fan Call → 搜 3 只 ≤100HP 基础填 bench |
| **P7** | Budew 拖延 | turn ≥ 2，无任何 P0–P6 可行 | Active 换 Budew，Itchy Pollen 封对手物品 |

**自查逻辑（每回合 OPENING 模式）**：

1. 用 `hand_snapshot` + 场面扫描 P0→P7，取第一个 `feasible=True` 的路径。
2. 若本回合 legal options 里存在该路径的下一步 → **DOMINATE** 该 option。
3. 若路径要求「下回合完成」→ 记录 `pending_path` 到 turn state（可用 obs 推导，不必持久化）。

**特殊情况**：
- My-T1：Fan Rotom 在 hand 且不在场 → PLAY 到 bench，再 Fan Call（P6 / R4a-T1）
- **My-T2+**：手牌 174 为 **废牌** — 禁止 PLAY 上 Bench；Ultra Ball **高优先弃**（见 [01_opening §3.6](./phases/01_opening.md)）

---

## 5. 两回合铺大海星 — 验收标准

| 指标 | 目标 | 测量方式 |
|---|---|---|
| T2 大海星率 | ≥ 60%（对 Walrein/meta） | marathon 统计 turn≤4 时 active=1031 |
| T1 Fan Call 使用率 | 后手/先手 My-T1 有 Rotom 在场则 100% 触发 | 轨迹 ABILITY on 174 |
| My-T2+ 误 PLAY 手牌 174 | 0% | fan_rotom_dead 时 PLAY 174 |
| 空过回合 | OPENING 阶段 0% | turn 内无 PLAY/EVOLVE/ATTACH 且非 Budew 拖延 |
| RECOVERY 内 My-T3 大海星率 | ≥ 40%（F-A~F-D 合计） | turn=5/6 active=1031 |
| STALL 触发率 | 尽量低 | My-T4 末仍 G1 |

---

## 5b. 两回合 Goal 未达成 — 处理概要

> 完整规格：[phases/01_opening.md §5.5](./phases/01_opening.md)

```text
My-T2 末未 Goal
  → classify F-A … F-F
  → RECOVERY（My-T3–T4，仍 OPENING）
       ├─ F-A/F-F：差一步 → EVOLVE / Switch
       ├─ F-B~D：缺 1031/能量 → Ball/Hilda/ATTACH
       ├─ F-E：无 1030 → 检索；My-T2 才上 1030 → 等 My-T4 进化
       ├─ 手牌 ≤2 无检索 → Lillie（REC-3，打破 OPENING 禁 Lillie）
       └─ 完全断档 → Budew 封 Item → My-T3 再检索
  → My-T4 末仍无望 → STALL（Budew 循环 + 三坑预备）
  → 任意时刻 Goal → AGGRESSION
```

---

## 6. AGGRESSION 阶段硬规则

### 6.1 每回合必攻

- Active = Mega Starmie ex 且存在 ATTACK option → **必须选 ATTACK**（DOMINATE）。
- 默认招式：**Jetting Blow（1487）**（打后排 50 + 主动 120）。
- 例外：Nebula Beam 可确认 KO（对手 active hp ≤ 210）→ 优先 Nebula（硬规则覆盖 Jetting）。

### 6.2 无伤害溯因（实现为日志 + 降权，非 LLM）

若上一回合 AGGRESSION 结束时：

- Active 是 Mega Starmie ex，且
- 对手 HP/后排 damage 无变化（需从 obs 快照 diff）

→ 本回合提高：附能、进化 backup、Boss 拉 weak bench 的硬规则优先级；并写 `data/training/starmie_regret.jsonl` 供复盘。

### 6.3 Bench 固定三坑（硬编码 PLAY 优先级）

| 坑位 | 优先放置 | 说明 |
|---|---|---|
| Bench-1 | Snorunt → 小雪妖女 Froslass（104） | 伤害标记引擎，不急于 Mega 104 |
| Bench-2 | Munkidori（112）+ **暗能量** | 每回合 Adrena-Brain；大海星受伤转走 |
| Bench-3 | 备用：Staryu / Meowth ex / Dunsparce | 大海星死后补位或 CONTROL |

**硬规则**：

- PLAY 基础时：若 bench 无 Snorunt 线 → 优先 PLAY Snorunt。
- PLAY 基础时：若 bench 无 Munkidori → 优先 PLAY Munkidori。
- ATTACH：Munkidori 无 dark → 优先附 `{D}` 或 Prism（16）。
- 已有 Munkidori + dark → ABILITY Adrena-Brain **DOMINATE**。

**Risky Ruins（1260）**：仅当 bench 上 Snorunt/Staryu/Munkidori 三条线都已就位后再 PLAY（避免 Budew 级低 HP 自伤）。

---

## 7. 两手准备（硬编码 Phase 切换）

### Plan A — 大海星被 KO → HARVEST

触发：`active` 从 1031 消失且 prize 未结束。

1. 若手牌有 Mega Froslass ex（861）且 opp_hand ≥ 5 或 opp 刚拿奖 → EVOLVE Snorunt（DOMINATE）。
2. 否则：Boss 拉 weak → Resentful Refrain（1240）或 Absolute Snow（1241）。
3. 仍保持 Munkidori 转伤链。

### Plan B — 优势控场 → CONTROL

触发：`prize_self < prize_opp`（我方领先）。

1. 若 bench 无 Meowth ex（1071）且手有 → PLAY Meowth ex（DOMINATE）。
2. Meowth ex Last-Ditch Catch → 搜 Boss's Orders（1182）或 Judge（1213）。
3. Boss 拉 prize-path 目标；Judge 重置对手手牌（配合下回合 Froslass 可选）。

---

## 8. ML 培养什么「潜意识」？

**只训练 Layer 2 四维，不训练路径选择：**

| 软维 | 习惯含义 | 训练信号 |
|---|---|---|
| `jetting_blow_pref` | 默认散射节奏 | AGGRESSION 局 reward |
| `nebula_finish` | 秒杀阈值敏感度 | KO 成功局 |
| `froslass_harvest` | 收割时机早晚 | HARVEST 局 win |
| `boss_gust_path` | 拉谁更优 | CONTROL/HARVEST win |

**对手池（训练用）**：

- vs_walrein **2.0**（核心目标）
- vs_foo / vs_gray / vs_alak **1.0**
- mirror **0.8**
- **不要** vs_tea28 28维（会学控制坏习惯）

---

## 9. 实现任务清单（给同事）

### P0 — 脚本拆分（1 天）

- [ ] `scripts/setup_planner.py` — Phase 0：Setup Active/Bench + setup_archetype
- [ ] `scripts/hand_snapshot.py` — 手牌/场面快照（含 setup_archetype）
- [ ] `scripts/path_planner.py` — My-T1/My-T2 路线 + 缺口 G1–G7
- [ ] `scripts/phase_fsm.py` — Setup 完成 → OPENING/AGGRESSION/…
- [ ] 接入 `starmie_pilot.py` 的 `_hard_rule_bonus`（优先级栈）

### P1 — Setup + OPENING 硬规则（1 天）

- [ ] Phase 0 Setup 决策树（§01_opening §3.1–§3.2）
- [ ] A1/A2 风车线（§3.5）
- [ ] My-T1/My-T2 路径 DOMINATE
- [ ] Budew 兜底

### P2 — AGGRESSION 硬规则（1 天）

- [ ] 必攻 + Jetting 默认
- [ ] Bench 三坑 PLAY/ATTACH 优先级
- [ ] Munkidori 暗能 + Adrena-Brain

### P3 — HARVEST / CONTROL（0.5 天）

- [ ] Plan A / Plan B Phase 切换
- [ ] Meowth ex 搜 Boss

### P4 — 测试 & 验证

- [ ] 扩展 `tests/test_starmie_pilot.py`：路径选择、Phase 切换
- [ ] 本地 40 局 vs Walrein：T2 大海星率、胜率
- [ ] 打包提交：`best_weights_starmie_v1.json` + v3 硬规则

---

## 10. 硬规则优先级栈（实现顺序）

同一 option 多重命中时，**数字越小越优先**：

1. Fan Call（T1）
2. OPENING 路径表当前步（P0–P6）
3. Munkidori Adrena-Brain（有 dark）
4. AGGRESSION 必攻（Mega Starmie active）
5. HARVEST 进化大雪妖女（窗口内）
6. CONTROL Meowth ex 上场 / 搜 Boss
7. Budew Itchy Pollen（OPENING 失败兜底）
