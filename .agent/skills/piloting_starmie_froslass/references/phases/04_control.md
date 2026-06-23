# Phase 4 — CONTROL（领先控场 · modifier）

> **不是第四个 Primary Phase**。`control_active = (prize_self < prize_opp)` 叠加在 AGGRESSION / HARVEST 之上。  
> **设计来源**：`deck_knowledge.md` §链 E、`00_fsm_overview.md` §2.2。

---

## 1. 判定（已有 · `phase_fsm.py`）

```python
control_active = board.prize_self < board.prize_opp
phase_label → "AGGRESSION+CONTROL" / "HARVEST+CONTROL"
```

| 条件 | CONTROL |
|---|---|
| 我方剩余奖 < 对手 | `control_active = True` |
| OPENING | **不启用** CONTROL 子规则 |
| 领先消失（奖数追平/落后） | 自动关闭 |

---

## 2. 与 Primary Phase 边界

| 层 | AGGRESSION+CONTROL | HARVEST+CONTROL |
|---|---|---|
| **Jetting / Resentful** | 必攻窗口内 **禁止** Meowth/Judge | Resentful 前 **禁止** Judge（HR-H6） |
| **Meowth ex** | bench 有空 → PLAY → Last-Ditch | 同左（非 861 必攻窗口） |
| **Judge** | 可 PLAY（控场重置） | **仅 Resentful 已打出后**（`harvest_resentful_fired`） |
| **Boss** | gust 目标在 bench → PLAY | HR-H8 已覆盖 |
| **Synergy Pad/Snorunt** | 不铺新 Opening 线 | 同 HARVEST |

**原则**：CONTROL 工具（Meowth/Judge）**不得**抢占 Layer 1 必攻（HR-6 Jetting、HR-H3 Resentful）。

---

## 3. 硬规则清单（Layer 1 · HR-C1–C4 已实现）

在 `_harvest_hard_rules` 之后、legacy HR-* 之前评估。

| Pri | ID | 触发 | 动作 | 分数带 |
|---:|---|---|---|---|
| C1 | **HR-C1** | `control_active` + bench 空位 + 手有 1071 + 场上无 Meowth + **非必攻窗口** | PLAY Meowth ex → Bench | `DOMINATE_MID` (920) |
| C2 | **HR-C2** | `control_active` + Meowth ABILITY Last-Ditch | 发动检索 | `DOMINATE_PLUS` (1100) |
| C2b | **HR-C2b** | Last-Ditch `TO_HAND` 选牌 | Boss > Judge > Crispin | `DOMINATE` / `MID` / `LOW` |
| C3 | **HR-C3** | `control_active` + 非必攻窗口；HARVEST 需已 Resentful 且 Active 861 不可攻 | PLAY Judge | `DOMINATE_SUPPORT` (960) |
| C4 | **HR-C4** | `control_active` + AGGRESSION + gust 目标 | PLAY Boss | `DOMINATE_SUPPORT` (960) |

### 3.1 Judge 与 HARVEST 协作

```text
HARVEST + 未 Resentful  → HR-H6  -DOMINATE（禁止 Judge）
HARVEST + 已 Resentful  → HR-C3  +DOMINATE_SUPPORT（允许 Judge 收尾）
AGGRESSION + CONTROL    → HR-C3  +DOMINATE_SUPPORT（非 Jetting 窗口）
```

`harvest_resentful_fired` 由 agent 闭包在打出 Resentful 后置位，整局有效。

### 3.2 Meowth 检索优先级（CONTROL）

```python
MEOWTH_CONTROL_SUPPORTER_PRIORITY = (Boss's Orders, Judge, Crispin, Lillie)
```

与 OPENING 的 `MEOWTH_OPENING_SUPPORTER_PRIORITY = (Hilda, Crispin, Salvator)` **分离**（E-MEOW-2）。

---

## 4. 软维（Layer 2）

| Dim | 条件 | 说明 |
|---|---|---|
| `boss_gust_path` | CONTROL / HARVEST gust | 与 AGGRESSION 共用；Layer 1 HR-C4/HR-H8 优先 |

---

## 5. 验收 KPI（草案）

| 指标 | 目标 | 审计 |
|---|---|---|
| 领先局 Meowth PLAY 率 | ≥ 50% | `audit_control.py` |
| HARVEST+CONTROL Judge 先于 Resentful | 0 | 与 `audit_harvest.py` 共用 |
| AGGRESSION+CONTROL 误跳过 Jetting | 0 | aggression 审计 |

---

## 6. 相关文件

| 文件 | 角色 |
|---|---|
| `phase_fsm.py` | `control_active` modifier |
| `starmie_pilot.py` | `_control_hard_rules()`、HR-H6 协作 |
| `opening_cards.py` | `MEOWTH_CONTROL_SUPPORTER_PRIORITY` |
| `supporter_planner.py` | Boss/Stamp（DR-6）；**移除**冲突 DR-7 |
| `audit_control.py` | 领先局 Meowth / Judge KPI |
