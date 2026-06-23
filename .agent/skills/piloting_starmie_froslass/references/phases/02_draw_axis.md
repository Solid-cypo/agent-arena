# Phase 2: 过牌轴 & 支援者 — 全局框架（v2）

> **前置**：Goal 达成（Active 1031 + ≥1 水）→ 进入 **AGGRESSION**（见 [01_opening.md](./01_opening.md)）。  
> **本 Phase 范围**：轴 B/C 支援者决策、土龙弟弟循环、**牌库剩余资源推断**。  
> **决策维度**：**场面 (1) + 手牌 (2) + 牌库资源 (2b)**；**不使用对手卡组分型（维度 3 已移除）**。

---

## 0. 已拍板的 Policy

| # | Policy | 内容 |
|---|--------|------|
| **P-1** | My-T2 首 AGGRESSION 回合 | **禁 Lillie + 禁 66 循环**；三坑 + 必攻 + Boss（有 gust 时） |
| **P-2** | 牌库资源 | AGGRESSION 起通过 **手牌 + 弃牌区 + 场上公开区** 推断 deck 中剩余关键件（见 §5） |
| **P-3** | Dudunsparce ex (306) | 仅当 **1031 受威胁**、**无 backup Staryu 线剩余**、**手有 306** 时 PLAY；不参与 66 循环 |

---

## 1. 三轴定义

（同 v1 — 轴 A OPENING / 轴 B Lillie+66 / 轴 C Stamp+Meowth+Boss）

轴 B 启用：`opening_complete()` 且 `my_turn_number ≥ 3`（My-T2 禁循环见 P-1）。

---

## 2. 土龙弟弟定位

（同 v1 §2 — 一句话 + 卡线分工 + Run Away Draw 循环）

### 2.4 硬约束（更新）

| ID | 规则 |
|----|------|
| **DD-1** | My-T2 首 AGGRESSION：禁 66 循环（P-1） |
| **DD-2** | 三坑未就位：禁循环 |
| **DD-3** | `hand_size > 4`：禁循环 |
| **DD-4** | `prize_self > prize_opp` 且须本回合 Jetting：禁循环（争回合） |
| **DD-5** | Ball 弃牌保护 66/65/305 |
| **DD-6** | 306 ex 见 P-3 |
| **DD-7** | `dudunsparce_66_left + dunsparce_basic_left == 0` 且 bench 无 66：**禁循环** |
| **DD-8** | 手牌 ≤2 或 `lillie_left ≤ 1` 且手有 Lillie：**优先 Lillie**，禁 66 循环 |

---

## 3. 支援者使用原则

（同 v1 §3.1–3.3，Lillie 树增加 DR-1b / DR-3b）

| ID | 条件 | 决策 |
|----|------|------|
| **DR-1b** | `lillie_left == 0` 且手牌无 Lillie | **FORBID** PLAY Lillie |
| **DR-3b** | 手无 Boss、 `boss_left > 0`、手牌断档 | **PLAY** Lillie 找 Boss |
| **SP-HOLD-BOSS** | 手无 Boss 但 `likely_in_deck(Boss) > 0` | **HOLD** 支援者槽等抽牌 |

---

## 4. 决策维度（仅 1 + 2）

| 维度 | 内容 | My-T2 首 AGGRESSION | My-T3+ |
|------|------|---------------------|--------|
| **① 场面 Board** | Jetting/三坑/Munk 暗能/Boss gust/奖区差 | **~55%** | **~45%** |
| **② 手牌 Hand** | 张数、关键件在手、支援者槽 | **~45%** | **~35%** |
| **②b 牌库资源 Deck** | 弃牌+场面反推 deck 剩余副本 | **~0%**（刚 Goal，弃牌少） | **~20%** |

**轮次/奖区** 并入 **场面维度**（`prize_self/opp`、`my_turn_number`），不单独成维。

~~**③ 对手 Profile**~~ — **已移除**，不做 Style/Burst/Control 调制。

---

## 5. 牌库剩余资源推断（P-2 核心）

### 5.1 可见区（己方）

```
seen = hand + discard + active/bench（含附属能量）
template = 60 张 deck 清单（starmie_froslass.csv）
remaining[cid] = template_count[cid] - seen_count[cid]
deck_count = obs.players[me].deckCount   # 牌库顶剩余张数（身份未知）
prize_count = len(prize)                 # 奖品区张数（身份未知）
likely_in_deck(cid) = min(remaining[cid], deck_count)
```

**含义**：`remaining` = 尚未见到的副本（可能在 **deck 或 prize**）；`likely_in_deck` = 仍可能在牌库顶的上界。

### 5.2 关键资源字段

| 字段 | 用途 |
|------|------|
| `lillie_left` | 是否还有 Lillie 可抽；是否应用 DR-1b |
| `boss_left` / `likely_in_deck(Boss)` | 手无 Boss 时是 HOLD 还是 Lillie |
| `pad_left` | 三坑就位后是否 Pad 补件 |
| `staryu_line_left` | DR-3 第二攻击线 |
| `dudunsparce_66_left` + `dunsparce_basic_left` | DD-7 能否开循环 |
| `deck_count` | 牌库厚度；Lillie 期望收益 |

### 5.3 决策示例

| 场面 | 手牌 | 资源 | 决策 |
|------|------|------|------|
| 三坑齐，Active 1031+水 | 3 张无 Boss | boss_left=2, lillie_left=3 | **66 循环**（保 Lillie） |
| 同上 | 2 张全废 | boss_left=1, lillie_left=1 | **Lillie**（DR-2 + DD-8） |
| gust 目标在 bench | 有 Boss | boss_left=1 | **PLAY Boss**（SP-BOSS-1） |
| 三坑齐 | 无 65/305，66_left=0 | DD-7 | **禁循环** → Lillie 或 Pad |

### 5.4 模块

```python
# deck_resources.py
resources = build_deck_resources(obs, deck_template)
resources.lillie_left
resources.can_run_away_cycle(hand, on_bench_66=...)
resources.prefer_lillie_over_cycle(hand)
resources.prefer_cycle_over_lillie(hand)
```

---

## 6. 每回合决策流程（v2）

```
1. Phase 门控（OPENING → 轴 A；AGGRESSION+ → 本模块）
2. build_board_snapshot + build_hand_context + build_deck_resources
3. 场面硬条件：Boss / Crispin / Wally
4. P-1：My-T2 禁 Lillie + 禁 66
5. 手牌 + 资源：Lillie 树（DR-*）+ 66 循环（DD-* / DR-4）
6. 输出 SupporterDecision / DrawAxisDecision → starmie_pilot Layer 1
```

~~步骤 5 Opponent 调制~~ — **已删除**。

---

## 7. 实现模块

| 脚本 | 职责 |
|------|------|
| `deck_resources.py` | **牌库资源推断**；HandContext |
| `supporter_planner.py` | DR-* / SP-* |
| `draw_axis.py` | DD-* / DR-4 |
| `hand_snapshot.py` | BoardSnapshot |
| `phase_fsm.py` | Phase 门控 |

### API（v2）

```python
def pick_supporter(board, phase, hand, resources) -> SupporterDecision | None
def pick_draw_axis_action(board, phase, hand, resources, ...) -> DrawAxisDecision | None
def build_deck_resources(obs, deck_template=None) -> DeckResourceSnapshot
```

---

## 8. 规则 ID 总表

| 类别 | ID |
|------|-----|
| Lillie | DR-1, DR-1b, DR-2, DR-3, DR-3b, DR-5~5c |
| 循环 | DD-1~8, DR-4, DR-4b |
| 资源 | DR-RES-*（逻辑在 deck_resources 方法名中） |
| Boss/Crispin/Wally/Stamp/Judge | SP-* / DR-6 / DR-7 |

---

## 9. 变更记录

| 日期 | 内容 |
|------|------|
| 2026-06-24 | v1 全局框架 |
| 2026-06-24 | **v2** 移除对手分型维度；新增牌库资源推断（P-2）；DD-7/8、DR-1b/3b |
