# Phase 1: OPENING — 详细设计（v2）

> **唯一目标**：在 **己方第 2 战斗回合（My-T2）结束前**，达成终局场面（§2）。  
> **OPENING 不是从 My-T1 才开始**，其前置是 **Phase 0 Setup**（§0）。

---

## 0. 规划总览（Setup → My-T1 → My-T2）

cabt：`SETUP_ACTIVE_POKEMON` / `SETUP_BENCH_POKEMON` 选项 **只来自起手手牌 Basic**，不能指定理想 Active。

```
Phase 0  Setup（选 Active / Bench）
              ↓ 决定 setup_archetype
My-T1      Checkpoint CP1（1030 在场上 + 尽量附水 + 尽量有 1031）
              ↓
My-T2      Goal：Active 1031 + ≥1 水能 → AGGRESSION
```

| 原型 | Setup Active 条件 | 典型 My-T1 | 详节 |
|---|---|---|---|
| **S1** | 手有 Staryu → Active | 附水 + 找 1031 | §3 |
| **A2** | 1030 + 174 → Active + **Bench Rotom** | Fan Call + 附水 | §3.5 |
| **A1** | 无 1030、有 Fan Rotom → Active | Fan Call 拿 Staryu | §3.5 |
| **B1** | Dunsparce Active | Hilda/Poffin | §3.3 |
| **C1/E1/F1** | Snorunt / Budew / Meowth ex | 降级；Bench 进化 + Switch | §3.4；T2 达成率低 |

**实现模块**：`setup_planner.py`（Phase 0）→ `path_planner.py`（My-T1/T2）→ `phase_fsm.py`。

---

> **核心约束**（战斗阶段）：
> 1. **Setup Active 只能从起手 7 张手牌中的 Basic 里选**，不能凭空指定。
> 2. **场上宝可梦需在场至少一回合才能进化**（`appearThisTurn == false`），Salvatore 是例外。
> 3. 因此必须 **分别设计 My-T1 与 My-T2 的路线**，不能假设「同回合下 Staryu + 附能 + 进化」。

---

## 1. 时间轴与 cabt 字段

### 1.1 `obs.turn` 与「己方第 N 回合」

| cabt `turn` | 谁先手 | 谁行动 | 对应「己方回合」 |
|---:|---|---|---|
| 0 | — | Setup 阶段 | Setup |
| 1 | 先手 | 先手 My-T1 | 先手 T1 |
| 2 | 后手 | 后手 My-T1 | 后手 T1 |
| 3 | 先手 | 先手 My-T2 | 先手 T2 |
| 4 | 后手 | 后手 My-T2 | 后手 T2 |

```python
def my_turn_number(turn: int, first_player: int, my_index: int) -> int:
    """1 = 己方第一战斗回合, 2 = 己方第二战斗回合, 0 = setup 或对手回合."""
    if turn <= 0:
        return 0
    is_first = (my_index == first_player)
    if is_first:
        return (turn + 1) // 2   # 1→1, 3→2, 5→3
    return turn // 2             # 2→1, 4→2, 6→3
```

**Fan Call 窗口**：各自 **My-T1**（`my_turn_number == 1`），且 Fan Rotom 已在场。  
**My-T1 结束后**：手牌中的 **174 标记为废牌**（§3.6）— 不可再 PLAY 上 Bench，Ultra Ball 等弃牌效应 **高优先** 丢弃对象。

### 1.2 进化等待：`appearThisTurn`

```python
def can_evolve_normal(pokemon: Pokemon) -> bool:
    """标准进化：本回合刚上场/刚进化则不能再次普通 EVOLVE。"""
    return not pokemon.appearThisTurn
```

| 上场方式 | My-T1 结束时 | My-T2 开始时 | My-T2 能否 EVOLVE |
|---|---|---|---|
| Setup Active / Setup Bench | 曾 `appearThisTurn=true` | **false** | ✅ |
| My-T1 PLAY 到 Bench/Active | 曾 `appearThisTurn=true` | **false**（上一回合已下场） | ✅ |
| **My-T1 当回合** 刚 PLAY | `appearThisTurn=true` | — | ❌ **同回合**不可 EVOLVE（G4） |
| Salvatore 贴 1031 | — | — | ✅ 当回合可进化（例外） |

**硬 deadline**：Staryu 必须在 **My-T1 结束前** 已在场上（Setup 或 My-T1 的 PLAY）。  
My-T1 才通过 Fan Call / Poffin 拿到并 **PLAY** 的 1030，**My-T2 仍可 EVOLVE**（与 Setup 下的 1030 相同）。

### 1.3 Setup 阶段（Phase 0）

`SelectContext.SETUP_ACTIVE_POKEMON` / `SETUP_BENCH_POKEMON`：选项 **仅来自当前手牌** 中的 Basic 宝可梦。

```python
@dataclass
class SetupSnapshot:
    hand_basics: list[int]          # 手牌中所有 Basic 的 card ID
    has_staryu_in_hand: bool
    has_fan_rotom_in_hand: bool
    has_budew_in_hand: bool
    has_meowth_ex_in_hand: bool
    staryu_count_in_hand: int
    # Setup Bench 可选：同样只能从 hand_basics 里选
```

**Setup 决策不在 OPENING FSM 内**，但是 OPENING 路线的 **前置输入**：`setup_active_id` + `setup_bench_ids` 决定 My-T1 起点。

---

## 2. 终局场面（Goal State）拆解

### 2.1 终局定义

```python
@dataclass
class OpeningGoal:
    active_id: int = 1031
    active_has_water: bool = True
    can_attack_jetting: bool = True   # 1031 + ≥1 水能

def opening_complete(board: BoardSnapshot) -> bool:
    return board.active_id == 1031 and board.active_has_water
```

终局 = **Active 上的 Mega Starmie ex + 至少 1 水能**（可立即 Jetting Blow）。

### 2.2 缺口 taxonomy（每回合自查）

实现 `diagnose_gaps(board, hand) -> GapFlags`：

| 缺口 ID | 含义 | 检测条件 |
|---|---|---|
| **G1** | 场上无 Staryu 线 | 无 1030 在 Active/Bench |
| **G2** | Staryu 在场但无能量 | 有 1030 且 `not staryu_with_water` |
| **G3** | 手牌无 1031 | `not has_mega_starmie_card` |
| **G4** | 进化锁（等待回合） | 有 1030 但 `staryu.appearThisTurn` |
| **G5** | 1031 在 Bench 不在 Active | bench 有 1031+水，active 不是 1031 |
| **G6** | 无 Staryu 来源 | 手/场/检索均无法获得 1030 |
| **G7** | 无能量来源 | 手/场/检索均无法获得水能 |

**My-T2 终局前必须清零**：G1、G2、G3、G4、G5。

### 2.3 缺口 → 动作映射（单步修复）

| 缺口 | 优先修复动作 | 可用卡牌 |
|---|---|---|
| G1 | Setup Bench / PLAY 1030 / 检索 1030 | Poffin, Pad, Ball, Hilda, Fan Call |
| G2 | ATTACH 水 → Staryu | 手牌 3/16, Hilda, Crispin |
| G3 | 检索 1031 | Hilda（进化位）, **Ultra Ball（搜 1031）** |
| G4 | **本回合不能 EVOLVE** → 做 G1/G2/G3 修复，等下一回合 | — |
| G5 | PLAY Switch (1123) | Switch |
| G6 | 同上 G1，且 My-T1 必须完成 | 全部检索轴 |
| G7 | Hilda / Crispin / 抽牌后 attach | 1225, 1198 |

### 2.4 两回合计划模板

每进入 My-T1 / My-T2，先 `diagnose_gaps`，再选 **RouteId**（见 §5）。

```
My-T1 结束状态（Checkpoint CP1）:
  REQUIRED: 1030 在场上（Active 或 Bench）
  DESIRED:  1030 已附 ≥1 水能
  DESIRED:  手牌有 1031（或 My-T2 初可用 Hilda 拿到）

My-T2 结束状态（Checkpoint CP2 = Goal）:
  REQUIRED: Active = 1031 且已附水
  OPTIONAL: 开始 Jetting Blow
```

| 若 CP1 未达成 | 后果 |
|---|---|
| 无 1030 在场上 | 最早 My-T3 进化 → **Opening 超时** |
| 有 1030 无能量 | My-T2 需先 ATTACH 再 EVOLVE（仍可行，占 My-T2 两个动作槽） |
| 有 1030 有能量无 1031 | My-T2 需 Hilda/Ball 检索 + EVOLVE（紧张但可能） |

---

## 3. Setup Active 分型（起手 7 张决定）

deck 内可担任 Setup Active 的 Basic（共 13 张基础体）：

| ID | 名称 | 张数 | Setup 优先级 | 说明 |
|---|---|---:|---:|---|
| 1030 | Staryu | 2 | **S** | 理想 Active：My-T1 直接附能 |
| 174 | Fan Rotom | 1 | **A** | 无 Staryu 时首选 Active：My-T1 Fan Call |
| 65/305 | Dunsparce | 3 | B | 填充；配合 Fan Call 拿 Staryu |
| 860 | Snorunt | 3 | C | 可用但占 Active 浪费；优先放 Bench |
| 112 | Munkidori | 2 | D | 仅当无 S/A/B 类 |
| 235 | Budew | 1 | E | 有 Staryu 时 **绝不** Active Budew |
| 1071 | Meowth ex | 1 | **F（禁止）** | 早期 2 奖风险；仅无其他 Basic 时 |

### 3.1 Setup 决策树

```
手牌有 1030?
  YES → Active = 1030
        → 手同时有 174? → Setup Bench = 174（§3.5 A2）
        → 第二张 1030? → 留手，不 Setup Bench
  NO → 手牌有 174?
    YES → Active = 174
    NO → 手牌有 65/305?
      YES → Active = Dunsparce（305 有 Trading Places 略优）
      NO → 手牌有 860?
        YES → Active = Snorunt（差开局，见 §3.4 C1）
        NO → 手牌有 112?
          YES → Active = Munkidori
          NO → Active = Budew（极差）/ Meowth ex（最后手段）
```

### 3.2 Setup Bench — 仅禁止「第二张 Staryu」，其余按 §3.5 使用

**已确认**：起手 **两张 1030** 时，第二张 **留手**（后期计划），**不** Setup Bench。  
**并非**「默认跳过整个 Setup Bench」——风车等仍应充分利用 Setup Bench 位。

| 情况 | Setup Bench 决策 |
|---|---|
| 手有 **1030 + 174**（S1+风车） | Active=1030；**Bench=174** → My-T1 直接 Fan Call，省 1 次 PLAY |
| 手 **无 1030**、有 **174** | Active=174（A1）；Bench **跳过**（风车已在 Active） |
| 手 **无 1030**、有 **174** + 其他 Basic | Active=174；Bench 可选 Dunsparce **仅当**不占用 My-T1 关键动作 |
| 手有 **1030**、无 174 | Active=1030；Bench **跳过**（除非规则强制选 Bench） |
| 第二张 **1030** | **永不** Setup Bench |
| Snorunt / Munkidori | OPENING **低优先** Setup Bench；C1 时 Snorunt 应在 Active 不在 Bench |

```python
def setup_bench_choice(hand_basics, setup_active_id) -> int | None:
    if setup_active_id == 1030 and 174 in hand_basics:
        return 174                    # S1+Rotom：风车 Setup Bench
    if setup_active_id == 174:
        return None                   # A1：风车已在 Active
    if 174 in hand_basics and setup_active_id != 174:
        return 174                    # B1/C1+Rotom：风车 Bench，My-T1 Fan Call
    return None                       # 默认不填
```

### 3.3 Setup 原型 My-T1/My-T2 概要

| 原型 | Setup Active | My-T1 主任务 | My-T2 主任务 |
|---|---|---|---|
| **S1** | Staryu | ATTACH 水；无 1031→Hilda；**有 174→见 §3.5 S1+Rotom** | EVOLVE Active → Jetting |
| ~~S2~~ | ~~双 Staryu Setup Bench~~ | **禁止** | 后期留手 |
| **A1** | Fan Rotom（手有174、无1030） | **§3.5 A1** Fan Call → 1030 下 Bench → ATTACH | Bench EVOLVE → Switch → Jetting |
| **A2** | Staryu（手有1030+174） | Setup Bench=174；My-T1 Fan Call + ATTACH | 同 S1 或 Bench 线（§3.5） |
| **B1** | Dunsparce | **§3.5 B1+Rotom** 或 Hilda/Poffin | Bench EVOLVE → Switch |
| **C1** | Snorunt | 检索 + PLAY 1030 到 **Bench**；Snorunt 留 Active | Bench EVOLVE → Switch → Jetting（§3.4） |
| **E1** | Budew | 检索 1030 到 Bench | 同 C1；失败则 Budew 线（§5.4） |
| **F1** | Meowth ex | 尽快 PLAY 1030 到 Bench | Bench EVOLVE → Switch |

**C1 / E1 / F1** 为降级开局；Staryu **优先 Bench 而非 Active**（见 §3.4）。

### 3.4 C1 / 非 Staryu Active：**Bench 进化 + Switch**（已确认）

**不采用**：Retreat / 提前 Switch 把 Staryu 换到 Active（浪费撤退、能量或 Switch 道具）。

**采用**：

```text
My-T1: Snorunt/Budew/Dunsparce 占 Active；1030 PLAY 到 Bench → ATTACH 水
My-T2: EVOLVE Bench 1030 → 1031（Bench 位较不易被点）→ Switch 送上 Active → Jetting
```

| 理由 | 说明 |
|---|---|
| Bench 保护 | 进化前 1030 在 Bench，对手 Active 攻击通常打不到 |
| 资源 | 省 Retreat / 早期 Switch |
| 终局一致 | 进化后 Switch 到 Active，当回合可 Jetting（1031 已附能） |

**硬编码默认**：检索到的 1030 **优先 PLAY 到 Bench**（除非 S1：Setup Active 已是 1030）。

### 3.5 起手手牌有 Fan Rotom `[174]` 的路线（风车）

Fan Call 条件：`my_turn_number == 1` 且 **174 已在 Active 或 Bench**（Setup 或 My-T1 PLAY）。

#### 分型矩阵（起手 7 张）

| 起手 | Setup Active | Setup Bench | 原型 | My-T1 动作序 |
|---|---|---|---|---|
| 有 1030 + 174 | **1030** | **174** | **A2 / S1+Rotom** | ① Fan Call ② 选 1030×1~2 + Dunsparce ③ ATTACH 水到 Bench 1030 ④（可选）Hilda 拿 1031 |
| 无 1030，有 174 | **174** | — | **A1** | ① Fan Call ② 1030 入手→**PLAY Bench** ③ ATTACH ④（可选）Hilda |
| 无 1030，174 + Dunsparce | **174** | 可选 65 | A1 | 同 A1 |
| 有 1030，无 174 | 1030 | — | S1 | 无 Fan Call；ATTACH + Hilda |
| 有 1030 + 174，但 1030 仅 1 张 | 1030 | **174** | A2 | 同第一行；Fan Call **不**再拿 1030，改拿 Dunsparce 填 bench |
| C1：860 Active + 174 在手 | Snorunt | **174** | C1+Rotom | ① Fan Call ② 1030→Bench ③ ATTACH ④ Snorunt 留 Active |
| B1：65 Active + 174 在手 | Dunsparce | **174** | B1+Rotom | ① Fan Call ② 1030→Bench ③ ATTACH；或先 Hilda 再 Fan Call（无 1030 时 Hilda 优先） |

#### A1 — 无 Staryu，风车 Active（最常见风车开局）

```text
Setup:  Active = Fan Rotom (174)
My-T1:  ABILITY Fan Call → 搜最多 3 只 ≤100HP {C} 入手
          → 优先选 1030 到 hand → PLAY 1030 到 Bench
          → ATTACH 水 → Bench 1030
          → （Supporter 槽）Hilda 拿 1031 + 能量，或留 My-T2 Ball 搜 1031
My-T2:  EVOLVE Bench 1030 → Switch → Jetting Blow
```

#### A2 / S1+Rotom — 有 Staryu 也有风车（**应用 Setup Bench**）

```text
Setup:  Active = Staryu (1030)；Bench = Fan Rotom (174)   ← 不占 My-T1 PLAY 槽
My-T1:  ABILITY Fan Call（Rotom 已在 Bench）
          → 若场上已有 1030：Fan Call 优先 Dunsparce(65/305)，不再拿 1030
          → 若需第二套件：Hilda 拿 1031 + 水
          → ATTACH 水到 Active 或 Bench 上的 1030
My-T2:  EVOLVE（Active 1030 则 R1-T2；若在 Bench 则 R2-T2 Switch）
```

**为何 A2 要 Setup Bench 风车**：My-T1 同时要做 Fan Call + ATTACH + 可能 Hilda，若 Rotom 还在手牌则要先 PLAY Rotom，浪费 **1 个动作槽**且 Rotom `appearThisTurn` 与 Fan Call 争顺序。

#### B1/C1 + 风车在手

```text
Setup:  Active = 65/860；Bench = 174（若手有 Rotom）
My-T1:  Fan Call → 1030 → Bench → ATTACH
        （若 Fan Call 前仍 G1 且无 Rotom 在场：先 PLAY 174 到 Bench，再 Fan Call）
My-T2:  EVOLVE Bench → Switch → Jetting
```

#### Fan Call 选牌优先级（My-T1）

```
若场上/Setup 尚无 1030 → Fan Call 选牌: 1030 > 65/305 > 860
若已有 1030 在场上     → Fan Call 选牌: 65/305 > 860（不拿第二张 1030 除非仅差 bench 厚度）
```

#### My-T1 微栈（含风车）

```
1. PLAY Fan Rotom → Bench     （仅当 174 在手且不在场；A1 已 Active 则跳过）
2. ABILITY Fan Call           （174 已在 Active/Bench）
3. PLAY Supporter 检索        （Hilda / Crispin）
4. PLAY Item 检索
5. PLAY 1030 → Bench          （Fan Call 入手后）
6. ATTACH 水 → 1030
```

### 3.6 My-T1 后：Fan Rotom 废牌标记（已确认）

Fan Call **仅在 My-T1 可用**。My-T1 结束后，手牌中剩余的 **Fan Rotom `[174]`** 失去 OPENING/后续铺场价值，标记为 **废牌（dead card）**。

| 规则 ID | 内容 |
|---|---|
| **FR-1** | `my_turn_number >= 2` 且 174 在 **手牌** → `fan_rotom_dead = True` |
| **FR-2** | `fan_rotom_dead` 时 **禁止** PLAY 174 到 Bench/Field（含 R4a-T1，仅 My-T1 有效） |
| **FR-3** | Ultra Ball / 其他「弃手牌换收益」效应：**高优先** 弃 174（仅次于 Lillie 副本、明确无用手牌） |
| **FR-4** | 已在场的 174（Setup Bench / A1 Active）不回收；占位即可，不主动 RETREAT |

```python
def fan_rotom_dead(my_turn_number: int, hand_has_174: bool, fan_call_used: bool) -> bool:
    """My-T1 结束后，手牌风车视为废牌。"""
    return my_turn_number >= 2 and hand_has_174
```

**Ultra Ball 弃牌优先级（OPENING，更新）**：

```text
1. Lillie (1227) — OPENING 本就不打，但 Ball 可弃
2. Fan Rotom (174) — 若 fan_rotom_dead
3. 重复 Trainer / 已用过的检索副本
4. 非关键能量（非贴 Staryu 的水）
5. Snorunt / Dunsparce 等低优先级 Basic
```

**My-T2 R4-T2** 搜 1031 时：优先弃 `fan_rotom_dead` 的 174 + Lillie/废 Trainer，**不**弃 1031 组合件或 Boss。

**实现**：`hand_snapshot.fan_rotom_dead`；`_hard_rule_bonus` 对 PLAY 174 返回 `-DOMINATE`；Ball 选弃牌时加权。

---

| 动作 | 每回合限制 | OPENING 备注 |
|---|---|---|
| Supporter | 1 张 | Hilda/Crispin/Salvatore 互斥 |
| 手动 ATTACH | 1 次 | 优先贴 Staryu |
| EVOLVE | 每宝可梦链 1 次 | 需 `not appearThisTurn`（Salvatore 除外） |
| Fan Call | 各 My-T1 一次 | Rotom 须在场 |
| 普通 PLAY Basic |  bench 有空 | My-T1 下 1030 会锁 G4 到 My-T2 |

**错误示范（旧 spec 已废弃）**：

```text
❌ My-T1: PLAY Staryu → ATTACH → EVOLVE  （G4 阻止 EVOLVE）
✅ My-T1: PLAY Staryu → ATTACH            （My-T2: EVOLVE）
✅ Setup: Active Staryu → My-T1: ATTACH   （My-T2: EVOLVE）
✅ My-T1: Salvatore 当回合进化            （Salvatore 例外）
```

---

## 5. 两回合路线表（RouteId）

在 **My-T1** 与 **My-T2** 分别调用：

```python
RoutePlan = {
    "turn": 1 | 2,
    "setup_archetype": "S1" | "A1" | ...,
    "gaps": GapFlags,
    "steps": list[Step],      # 本回合有序动作目标
    "cp_target": "CP1" | "CP2",
}
```

### 5.1 My-T1 路线（达成 CP1）

| Route | 条件（缺口） | 本回合动作序列（最大 1 Supporter + 1 Attach + 若干 Item/Ability） |
|---|---|---|
| **R1-T1** | G1，有 Hilda | Hilda → 1030+水 → PLAY 1030（**Bench 优先**，§3.4）→ ATTACH |
| **R2-T1** | G1，有 Poffin | Poffin → 1030 到 Bench → ATTACH |
| **R3-T1** | G1，有 Pad/Ball | 检索 1030 → PLAY → ATTACH（若 slot 够） |
| **R4-T1** | A1/A2/B1/C1+Rotom | **Fan Call** → PLAY 1030 Bench → ATTACH（§3.5） |
| **R4a-T1** | 174 在手但不在场，**My-T1 only** | **PLAY 174 → Bench** → 接 R4-T1（My-T2+ 禁止，§3.6） |
| **R5-T1** | 有 1030 在场上，G2 | ATTACH 水 |
| **R6-T1** | 有 1030，G3（无 1031） | Hilda 拿 1031 + 能量（能量可下回合） |
| **R7-T1** | S1：Setup Staryu Active，G2+G3 | ATTACH + 若 supporter slot 则 Hilda 拿 1031 |
| **R8-T1** | 有 Salvatore+1031+场上 1030 | Salvatore 当回合进化（**跳过 My-T2 EVOLVE**）→ CP2 直接达成 |

**My-T1 优先级**：R8 > R7 > R5 > **R4 / R4a**（风车线）> R1 > R2 > R3。

### 5.2 My-T2 路线（达成 CP2 / Goal）

| Route | 条件 | 本回合动作序列 |
|---|---|---|
| **R1-T2** | 1030+水+1031，`can_evolve`，1030 在 **Active**（S1） | EVOLVE → Jetting |
| **R2-T2** | 1030+水+1031，1030 在 **Bench**（C1/A1/默认） | EVOLVE Bench → Switch → Jetting |
| **R3-T2** | 1030 在场，G2（无能量） | ATTACH → EVOLVE（Bench 则 +Switch） |
| **R4-T2** | 1030 在场，G3，Hilda 已用/不可用 | **Ultra Ball** 弃 2（**优先 174 废牌**）搜 1031 → EVOLVE（+Switch 若 Bench） |
| **R4b-T2** | G3，有 Hilda 且 slot 可用 | Hilda 拿 1031 → EVOLVE |
| **R5-T2** | G4（1030 My-T1 才上场） | **CP1 失败** — 转入 §5.4 可行性评估 |
| **R6-T2** | 仍 G1，但 `can_reach_goal()` | Pad/Poffin/过牌继续找 1030（§5.4） |
| **R7-T2** | `not can_reach_goal()` | **Budew 路线** P7 |

**My-T2 优先级**：R1-T2 > R2-T2 > R3-T2 > R4b-T2 > R4-T2 > R6-T2 > R7-T2。

### 5.4 My-T2 失败分支：过牌评估 → Budew（已确认）

当 My-T2 仍 **G1（无 1030）** 或 CP1 已失败时，**不立即** Budew，先评估是否还能在 **本回合内** 达成 Goal：

```python
def can_reach_goal_this_turn(hand, board, legal_options) -> bool:
    """本回合是否仍存在达成 Active 1031+水 的动作链。"""
    # 例：手有 Poffin 且 bench 有空 → 可 Poffin 出 1030，但 G4 阻止当回合 EVOLVE → False
    # 例：手有 Hilda+Pad，但 supporter 已用且无 1030 来源 → False
    ...
```

| 步骤 | 动作 |
|---|---|
| 1 | 调用 `can_reach_goal_this_turn()` |
| 2 | **True** → R6-T2：Pad / Poffin / Ultra Ball（搜 1030 或 1031）/ 其他检索，**仍禁止 Lillie**（OPENING） |
| 3 | **False** → R7-T2：**Budew 路线** — Active Budew → Itchy Pollen，封对手 Item，争取 My-T3 |

**Ultra Ball 搜 1031**（R4-T2）：Hilda 已消耗或不在手时，弃 2 张（优先 Lillie 副本、废 Trainer）搜 **1031**；场上已有 Bench 1030+水时，同回合 EVOLVE + Switch。

**仍无 1030 时**：若检索轴（Pad/Poffin/Ball）能在 **本回合** 把 1030 放到场上 — 走 R6-T2；若连 1030 来源都没有 → `can_reach_goal()` 为 False → Budew。

### 5.5 两回合 Goal 未达成 — 失败分型与恢复（RECOVERY）

My-T2 结束时若 **`not opening_complete()`**，不立刻退出 OPENING，进入 **`RECOVERY` 子模式**（仍为 `phase.primary == OPENING`），直到 Goal 达成或触发 **放弃线**。

#### 5.5.1 My-T2 结束时局面分型

| 类型 | 检测（My-T2 末） | 严重度 | My-T3 首选 |
|---|---|---|---|
| **F-A** | 1030+水+1031，`can_evolve`，未 EVOLVE（动作不够） | 低 | **R1-T3** EVOLVE → Switch? → Jetting |
| **F-B** | 1030+水，G3（无 1031） | 中 | **R4-T3** Ball 搜 1031 / Hilda → EVOLVE |
| **F-C** | 1030 在场，G2（无能量） | 中 | ATTACH → **R1-T4** 下回合 EVOLVE |
| **F-D** | 1030 在场，G2+G3 | 高 | Hilda（进化+能）或 Ball + ATTACH 分两回合 |
| **F-E** | **G1** 无 1030；或 R5-T2（1030 My-T2 才上场） | 最高 | **R-RECOVER** 检索链 / Budew 拖延 |
| **F-F** | 1031 在 Bench+水，Active 非 1031（G5 未完成） | 低 | Switch → Jetting |

```python
def classify_opening_miss(board, hand) -> str:
    if board.active_id == 1031 and board.active_has_water:
        return "OK"
    if board.staryu_on_field and board.staryu_with_water and hand.has_1031:
        return "F-A" if board.staryu_can_evolve else "F-E"  # G4 → wait T4
    ...
```

#### 5.5.2 RECOVERY 子模式规则（My-T3+）

| 规则 ID | My-T2 失败后变化 |
|---|---|
| **REC-1** | 仍属 OPENING；`opening_recovery = True`（`my_turn_number >= 3` 且未 Goal） |
| **REC-2** | **Fan Call 永久关闭**；手牌 174 继续 FR 废牌规则 |
| **REC-3** | **允许 Lillie**（打破 DR-1）：仅当 `hand_size <= 2` 且仍 G1/G3 无检索件 |
| **REC-4** | **禁止**无目的 PLAY（风车、多余 Dunsparce）；检索目标仍 **1030 > 1031 > 水** |
| **REC-5** | Bench 1030 线不变：进化 + Switch，不 Retreat 换 Active |
| **REC-6** | **放弃线**：My-T4 末仍 G1 且无 `can_reach_mega_next_turn()` → `STALL`（Budew 循环或被动防守） |

**Lillie 例外理由**：T2 失败后 combo 已不存在；手牌断档时 Lillie 是找 1030/1031 的最后手段。

#### 5.5.3 My-T3 / My-T4 路线表

| Route | 条件 | 动作 |
|---|---|---|
| **R1-T3** | F-A：1030+水+1031，`can_evolve` | EVOLVE →（Bench 则 Switch）→ Jetting |
| **R2-T3** | F-F：Bench 1031+水 | Switch → Jetting |
| **R3-T3** | F-B / F-D | Hilda 或 Ball 拿 1031 → EVOLVE（+Switch） |
| **R4-T3** | F-C | ATTACH 水；若同回合可 evolve 且 hand 1031 → ATTACH+EVOLVE |
| **R5-T3** | F-E，有检索 | Pad/Poffin/Ball/Hilda 按 G1→G3→G7 修复 |
| **R6-T3** | F-E，R5-T2（1030 My-T2 才上） | **不 EVOLVE**；ATTACH + 找 1031，等 **My-T4 EVOLVE** |
| **R7-T3** | REC-3：手牌 ≤2，无检索 | **PLAY Lillie** → 再评估 |
| **R8-T3** | F-E，`not can_reach_mega_next_turn()` | Active **Budew** → Itchy Pollen |
| **R1-T4** | R6-T3 后：1030+水+1031 | EVOLVE → Switch? → Jetting |
| **R9-T4** | My-T4 末仍无 1030 | **STALL**：Budew / 现有打手苟活 → 同时准备 HARVEST 线 |

**`can_reach_mega_next_turn()`**：下回合能否 Active 1031+水（含「本回合 Poffin 出 1030 → 下回合 evolve」）。

#### 5.5.4 Budew 拖延线（F-E / R8-T3）

```text
My-T2 末：can_reach_goal() == False
  → Active Budew（Switch 或已有 Budew Active）
  → Itchy Pollen：对手下回合不能打 Item

My-T3（对手 Item 被封期间）：
  → 全力检索 1030 + 附水 + 1031（Hilda > Poffin > Pad > Ball）
  → 1030 下 Bench → ATTACH

My-T4：
  → EVOLVE + Switch → 若 Goal 达成进 AGGRESSION
  → 仍失败 → STALL，并开始 Snorunt/Munkidori 三坑（与 AGGRESSION 预备合并）
```

#### 5.5.5 Phase 转移（更新）

```python
def compute_phase(...):
    if opening_complete(board):
        return AGGRESSION
    if my_turn_number >= 3 and not opening_complete(board):
        return OPENING  # sub_mode = RECOVERY or STALL
    ...
```

| 从 | 到 | 条件 |
|---|---|---|
| OPENING/RECOVERY | **AGGRESSION** | `opening_complete()` |
| OPENING/RECOVERY | **STALL**（仍 OPENING 内） | My-T4 末无 1030 且无下回合 mega 路径 |
| STALL | AGGRESSION | 迟来 Goal（1031+水 Active） |
| STALL | HARVEST | 大海星曾出场后被 KO（少见） |

#### 5.5.6 硬规则（RECOVERY 追加）

| ID | 条件 | 动作 |
|---|---|---|
| HR-O11 | RECOVERY + F-A + `can_evolve` | EVOLVE DOMINATE |
| HR-O12 | RECOVERY + REC-3 | PLAY Lillie DOMINATE ×0.8 |
| HR-O13 | RECOVERY + R8-T3 / STALL | Budew Itchy DOMINATE ×0.5 |
| HR-O14 | RECOVERY | PLAY 174（废牌）→ **-DOMINATE** |

#### 5.5.7 决策树（My-T2 结束瞬间）

```text
My-T2 结束 → opening_complete()?
  YES → AGGRESSION
  NO  → classify_opening_miss() → F-A … F-F
        → my_turn_number := 3（RECOVERY）
        → 按 R*-T3 表排本回合（若 My-T2 内还有未用完的动作先耗尽）

My-T3 每回合开始：
  opening_complete()? → AGGRESSION
  else classify_gaps() → R1-T3 … R9-T3

My-T4 末仍失败：
  can_reach_mega_next_turn()? → 继续 RECOVERY
  else → STALL（Budew + 三坑预备）
```

### 5.3 Salvatore 特殊两回合压缩

```
My-T1 结束: 1030 在场上（Setup 或更早），手有 1189 + 1031
My-T1 动作: PLAY Salvatore → 1030 当回合变 1031
My-T2 动作: 若 Active 已是 1031 仅 ATTACH（若缺能）→ Jetting
```

Salvatore 将 **两回合进化链压缩为 1 回合**，但消耗 Supporter slot，My-T1 不能再 Hilda。

---

## 6. 检索路径（嵌入缺口修复）

原 P0–P7 保留为 **单回合内** 的 item/supporter 选择，但必须服从 §4 进化约束：

| 旧 Path | 新定位 | 修正 |
|---|---|---|
| P0 EVOLVE | My-T2 的 R1-T2 | 仅当 `can_evolve_normal(staryu)` |
| P1 一条龙 | **拆成两回合** | My-T1: PLAY+ATTACH；My-T2: EVOLVE |
| P1-S Salvatore | R8-T1 | 当回合完成进化 |
| P2–P5 | G1/G3 修复 | 不变 |
| P6 Fan Call | R4-T1 | 仅 My-T1 |
| P7 Budew | R7-T2 | 仅当 `not can_reach_goal_this_turn()` |

---

## 7. 快照字段（修订）

```python
@dataclass
class OpeningSnapshot:
    # Setup 输入（Phase 0 写入，整局不变）
    setup_archetype: str          # S1, A1, ...
    setup_active_id: int

    # 手牌
    has_staryu: bool
    has_mega_starmie_card: bool
    has_hilda: bool
    # ... 同 v1 ...

    # 场面 + 进化锁
    staryu_on_field: bool
    staryu_on_active: bool
    staryu_with_water: bool
    staryu_can_evolve: bool       # on field AND NOT appearThisTurn
    my_turn_number: int           # 0=setup, 1=My-T1, 2=My-T2

    # 缺口 + 可行性
    gaps: GapFlags
    can_reach_goal_this_turn: bool   # §5.4
    prefer_bench_staryu: bool        # True：1030 下 Bench（C1/A1/默认）
    fan_rotom_dead: bool             # My-T1 后手牌 174 废牌（§3.6）
    fan_call_used: bool              # My-T1 是否已 Fan Call
    opening_recovery: bool           # My-T3+ 且未 Goal（§5.5）
    opening_miss_class: str         # F-A … F-F 或 OK
```

---

## 8. 硬规则（修订）

| ID | 条件 | 动作 |
|---|---|---|
| HR-O0 | Setup context | Active 按 §3.1；**Bench：174 优先**（§3.2），禁第二张 1030 Bench |
| HR-O1 | My-T1 + Fan Call 可用（174 在 Active/Bench） | ABILITY Fan Call DOMINATE |
| HR-O1a | My-T1 + 174 在手但不在场 | PLAY 174 → Bench（R4a-T1）；**My-T2+ 禁止** |
| HR-O10 | `fan_rotom_dead` + PLAY 174 | **-DOMINATE**（废牌不可上场） |
| HR-O2 | My-T2 + R1-T2 + `staryu_can_evolve` + 手有 1031 | EVOLVE DOMINATE |
| HR-O3 | gap G2 + can_attach | ATTACH → Staryu DOMINATE |
| HR-O4 | gap G1/G3 | 按 Route 表 PLAY 检索 |
| HR-O5 | gap G5 或 R2-T2 Switch 步 | Switch 1031 → Active DOMINATE |
| HR-O6 | OPENING | PLAY Lillie → **禁止** |
| HR-O7 | My-T2 + R4-T2 | Ultra Ball 搜 1031 DOMINATE |
| HR-O8 | My-T2 + `not can_reach_goal()` | Budew Itchy DOMINATE ×0.5 |
| HR-O9 | My-T2 + R6-T2 | 检索 1030（Pad/Poffin/Ball）DOMINATE |

---

## 9. 验收标准（修订）

| 指标 | 目标 |
|---|---|
| **CP1 达成率**（My-T1 结束 1030 在场上） | ≥ 85% |
| **Goal 达成率**（My-T2 结束 Active 1031+水） | ≥ 60% vs Walrein |
| Setup S1+A1 占比 | 越高越好（可日志统计） |
| My-T1 误 EVOLVE（G4 仍存在时 EVOLVE） | 0% |

---

## 10. 已确认决策（2025-06 评审）

| # | 问题 | 决策 |
|---|---|---|
| 1 | Setup Bench 第二张 Staryu（S2）？ | **不要**。第二张 1030 留手；**但 174 等仍应 Setup Bench**（§3.2、§3.5） |
| 2 | C1 Snorunt Active 如何换 Staryu？ | Bench 进化 + Switch（§3.4） |
| 3 | My-T2 无 1031 且 Hilda 已用？ | Ultra Ball 搜 1031；不可达再 Budew（§5.4） |
| 4 | My-T1 后手牌风车？ | **废牌**：不可 PLAY 上 Bench；Ultra Ball 等 **高优先弃**（§3.6） |
| 5 | 两回合未 Goal？ | **RECOVERY**（My-T3–T4）→ 仍失败则 **STALL**（§5.5） |

**OPENING 全局默认**：检索到的 1030 优先 Bench（S1 Active 除外）；**手有 174 时优先 Setup Bench 174（Active 已是 Staryu 或 Snorunt/Dunsparce 时）**。

---

**下一篇**：[02_aggression.md](./02_aggression.md)
