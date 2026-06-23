# 硬编码 Phase FSM 总览

> 分阶段详细设计目录：
> - [01_opening.md](./01_opening.md) — **OPENING v2**（Setup 分型 + 两回合路线 + 缺口 G1–G7）
> - [02_draw_axis.md](./02_draw_axis.md) — **过牌轴 & 支援者**（轴 B/C · DR/DD 规则 · P-1~P-3）
> - [03_harvest.md](./03_harvest.md) — **HARVEST**（861 收割 · HR-H* 硬规则清单）
> - [04_control.md](./04_control.md) — **CONTROL modifier**（领先控场 · HR-C*）

---

## 1. 四模式关系

```
                    ┌──────────────┐
         开局 ─────►│   OPENING    │ 目标：T2 Active = Mega Starmie ex + 能 Jetting
                    └──────┬───────┘
                           │ 大海星在 Active 且已附 ≥1 水能
                           ▼
                    ┌──────────────┐
                    │  AGGRESSION  │ 目标：每回合 Jetting + 三坑就位
                    └──────┬───────┘
                           │ 大海星被 KO
              ┌────────────┼────────────┐
              ▼            │            ▼
       ┌──────────────┐    │     ┌──────────────┐
       │   HARVEST    │    │     │   CONTROL    │◄── 领先 ≥1 奖时可叠加
       │ 大雪妖女收割  │    │     │ Meowth 控场  │
       └──────────────┘    │     └──────────────┘
                           │
              prize 结束 / 大雪妖女完成收割 → 回到 AGGRESSION 或结束
```

**叠加规则**：CONTROL 是 **modifier**，不是互斥模式。

- `prize_self < prize_opp` 时，在 AGGRESSION / HARVEST 之上启用 CONTROL 子规则（Meowth、Judge 加权）。
- OPENING 期间 **不启用** CONTROL / HARVEST / 过牌轴 B（**RECOVERY 子模式** My-T3+ 可例外 Lillie，见 01_opening §5.5）。

---

## 1.1 Phase 0：Setup（OPENING 的前置阶段）

> **完整规格**：[01_opening.md §1.3、§3、§3.5](./01_opening.md)

cabt 规则：`SelectContext.SETUP_ACTIVE_POKEMON` / `SETUP_BENCH_POKEMON` 的选项 **只来自起手 7 张手牌中的 Basic**，不能指定「理想 Active」。

```
Phase 0  Setup（选 Active / Bench，仅手牌 Basic）
              ↓ 写入 setup_archetype（S1 / A1 / A2 / B1 / C1 / …）
My-T1      Checkpoint CP1（1030 在场上 + 尽量附水 + 尽量有 1031）
              ↓
My-T2      Goal：Active = 1031 + ≥1 水能 → 进入 AGGRESSION
```

| 原型 | Setup Active 条件 | 典型 My-T1 任务 | T2 达成预期 |
|---|---|---|---|
| **S1** | 手有 1030 → Active Staryu | 附水 + Hilda 找 1031 | 高 |
| **A2** | 手有 1030 + 174 → Active Staryu，**Bench Rotom** | Fan Call + 附水 | 高 |
| **A1** | 无 1030、有 174 → Active Fan Rotom | Fan Call 拿 1030 → Bench 附能 | 中高 |
| **B1** | Dunsparce Active（+ 可选 Bench 174） | Hilda/Poffin 或 Fan Call | 中 |
| **C1 / E1 / F1** | Snorunt / Budew / Meowth ex | 检索 1030 下 Bench；Bench 进化 + Switch | **低**（降级） |

实现：`scripts/setup_planner.py` → `pick_setup_active()` / `pick_setup_bench()`；输出写入 `BoardSnapshot.setup_archetype`。

---

## 2. Phase 判定 API（`phase_fsm.py`）

```python
Phase = Literal["OPENING", "AGGRESSION", "HARVEST", "CONTROL"]

@dataclass
class PhaseState:
    primary: Phase           # OPENING | AGGRESSION | HARVEST
    control_active: bool     # prize_delta <= -1
    turn_entered: int        # 进入 primary 时的 obs.turn

def compute_phase(obs, board: BoardSnapshot) -> PhaseState: ...
```

### 2.1 Primary phase 转移表

| From | To | 条件（全部基于己方视角） |
|---|---|---|
| OPENING | AGGRESSION | `board.active_id == 1031` 且 Active 已附 ≥1 `{W}` |
| AGGRESSION | HARVEST | 上一回合 Active 为 1031，本回合 Active 不是 1031（被 KO 或 retreat） |
| HARVEST | AGGRESSION | Active 为 1031 或 861，且能攻击；或 HARVEST 任务超时（turn 在 HARVEST ≥3 仍无 861） |
| HARVEST | OPENING | **不转移** — 大海星死后不回头铺场，走 backup Staryu / Froslass |

### 2.2 CONTROL modifier

```python
control_active = (prize_self < prize_opp)
```

---

## 3. 全局硬规则栈（跨 Phase）

同一 option 多重命中时，**priority 越小越优先**：

| Pri | 规则 ID | Phase | 动作 |
|---:|---|---|---|
| 1 | HR-G1 | OPENING T1–T2 | Fan Call |
| 2 | HR-G2 | OPENING | 路径表 P0–P6 当前步 |
| 3 | HR-G3 | AGGRESSION+ | Munkidori Adrena-Brain（有 dark） |
| 4 | HR-G4 | AGGRESSION | Mega Starmie 必攻 |
| 5 | HR-G5 | HARVEST | Mega Froslass 进化窗口 |
| 6 | HR-G6 | CONTROL | Meowth ex 上场 / Last-Ditch |
| 7 | HR-G7 | OPENING 失败 | Budew Itchy Pollen |
| 8 | DR-* | AGGRESSION+ | 过牌轴（见 deck_knowledge §3.6.8） |

Phase 专属规则 **不得** 突破 Pri 1–2（OPENING 路径优先于一切 baseline）。

---

## 4. 共享数据结构

### 4.1 `BoardSnapshot`（每回合刷新）

```python
@dataclass
class BoardSnapshot:
    turn: int
    first_player: int
    my_index: int
    my_turn_number: int       # 0=setup/opp, 1=My-T1, 2=My-T2, ...
    prize_self: int
    prize_opp: int
    hand_size: int
    bench_count: int
    bench_open: int
    supporter_played: bool
    energy_attached: bool
    active_id: int
    active_has_water: bool
    active_is_mega_starmie: bool
    staryu_on_field: bool
    staryu_on_active: bool
    staryu_with_water: bool
    staryu_can_evolve: bool   # on field AND NOT appearThisTurn
    mega_starmie_on_field: bool
    setup_active_id: int      # Phase 0 写入，整局不变
    setup_archetype: str      # S1/A1/B1/...
    fan_rotom_on_field: bool
    snorunt_on_bench: bool
    munkidori_on_bench: bool
```

### 4.2 Setup（Phase 0，在 OPENING 之前）

- `SelectContext.SETUP_ACTIVE_POKEMON`：Active **只能从起手手牌中的 Basic 选择**。
- `SelectContext.SETUP_BENCH_POKEMON`：Bench 同理。
- 详见 [01_opening.md §3](./01_opening.md) Setup 原型分型。

### 4.3 `HandSnapshot` / 缺口诊断

---

## 5. 实现顺序（与 opening_book §9 对齐）

1. **Phase 1 文档 + OPENING 脚本** ← 当前
2. **Phase 2 过牌轴 & 支援者** → [02_draw_axis.md](./02_draw_axis.md) + `deck_resources.py` / `supporter_planner.py` / `draw_axis.py`（**场面+手牌+牌库资源**，不用对手分型）
3. Phase 3 HARVEST 详细设计 → `03_harvest.md` + 硬规则
4. Phase 4 CONTROL
5. 过牌轴 DR-1~7 嵌入 AGGRESSION / HARVEST

---

## 6. 验收矩阵（全 Phase）

| Phase | 核心 KPI | 目标 |
|---|---|---|
| OPENING | T2 大海星率（turn≤4, active=1031） | ≥ 60% vs Walrein |
| AGGRESSION | 无伤害回合率 | ≤ 10% |
| AGGRESSION | 三坑就位 turn | ≤ turn 6 |
| HARVEST | Resentful ≥200 伤触发率 | 窗口内 ≥ 70% |
| CONTROL | 领先局 Meowth 使用率 | ≥ 50% |
