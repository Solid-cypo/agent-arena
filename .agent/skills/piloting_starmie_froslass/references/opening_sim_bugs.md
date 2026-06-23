# OPENING 模拟器 — 已知问题备份

> 记录从测试日志中发现的 **规格偏离 / 逻辑错误**。  
> 修复前应先对齐 `01_opening.md` + `deck_knowledge.md`，再改代码。  
> **禁止**用 Lillie 紧急线、无前提 `retreat_promote`、Pad 搜 ex 等方式虚抬达成率。

---

## BUG-001 · Run #1 · seed=42 · X1 线附能 / Pad / 升场

**日志**: `logs/opening_batch_max5_42.log` Run #1  
**结果**: 模拟器判 GOAL（My-T2），但过程多处违法/违规格  
**Setup**: X1 — Active **Munkidori**，手牌 Water + Prism + 2×Pad  

### 错误链

| 回合 | 模拟器行为 | 问题 |
|------|------------|------|
| **My-T1** R3-T1 | Pad→Staryu；**Prism→Bench Staryu** | ① 唯一 ATTACH 应优先 **Water→Staryu**（Goal 水能）或 **Prism→Active Munkidori**（为撤退预备），**禁止 Prism→Bench Staryu** ② 贴 Prism 到 Staryu 后 Munkidori 仍 0 能，下回合无法 Retreat |
| **My-T2** R5-REC | **Pad→Mega Starmie ex**；retreat_promote；进化 | ③ **Poké Pad 不能搜 Rule Box / Mega ex（1031）** ④ Munkidori 无能量时 **retreat_promote 不合法** ⑤ 进化后仅 Prism，缺 **真实 Water**（Jetting 需水能） |

### 应遵循的硬约束（待实现）

| ID | 规则 |
|----|------|
| E-ATT-1 | 附能优先级：Staryu/Mega → **Water (3)** > 基础无色 > **Prism (16) 最后** |
| E-ATT-2 | X1/C1/B1 非 Staryu Active：禁止 Prism→Bench Staryu；可选 Prism→Active 仅为撤退费 |
| E-PAD-1 | Pad 仅可搜 **无 Rule Box** 白名单（1030/860/65/305/235/66 等），**不可搜 1031** |
| E-PAD-2 | F-B（有 1030+水、缺 1031）→ Hilda / Ultra Ball，**不用 Pad** |
| E-RET-1 | Retreat 需 Active 已满足撤退费；否则禁止 promote |
| E-SW-1 | Bench 进化线优先 **Switch (1123)**，非规格禁止的 retreat 捷径（§3.4） |

### 理想 My-T1 sketch（本牌局）

```
Pad → Staryu → Bench
ATTACH Water Energy → Bench Staryu   （或 Prism → Active Munkidori 若战略先换场）
My-T2: Hilda/Ball → 1031 → EVOLVE → Switch（非 retreat_promote）
```

---

## BUG-002 · Run #2 · seed=43 · B1 线 Supporter 链 / 空转

**日志**: `logs/opening_batch_max5_42.log` Run #2  
**结果**: 模拟器判 **GOAL OK（My-T5）** — 结果对、**路线错**  
**Setup**: B1 — Active **Dunsparce**；手牌 **Meowth ex, Lillie, Crispin, Poffin**, …  

### 错误链

| 回合 | 模拟器行为 | 问题 |
|------|------------|------|
| **My-T1** R2-T1 | 仅用 **Poffin** → Bench Staryu + **Snorunt**；未附能 | ① **Supporter 槽空闲** 却未走 Meowth→Hilda 链 ② 未实现 **Meowth ex Last-Ditch Catch** ③ B1 应优先 Meowth→Hilda，而非先 Poffin ④ **Poffin 第二抓错牌**（见下 §Poffin） |
| **My-T2** R5-REC | Water→Staryu；retreat_promote | ④ 应用 **Crispin**（手牌有、G2+G3）一次拿能+贴能，而非单 attach + 非规格 retreat ⑤ Hilda 仍在 deck，应 T1 已拿 |
| **My-T3–T4** R5-REC | **完全空转**（仅抽牌） | ⑥ F-B（Active Staryu+水、缺 1031）时手有 **Meowth/Lillie/Crispin** 却无任何操作 — `R5-REC` 执行分支空转 ⑦ 应用 Ultra Ball / 二次检索 / Meowth 搜 Hilda |
| **My-T5** R3b-REC | 抽到 Hilda → 拿 1031 → 进化 | ⑧ **靠自然抽牌碰 Hilda** 才 Goal — 计划质量差，非 OPENING 设计目标（My-T2 Goal） |

### 用户给出的更优 T1–T2（本牌局）

```
My-T1:
  PLAY Meowth ex → Bench
  ABILITY Last-Ditch Catch → 搜 Hilda（deck 内，非奖品区）
  PLAY Hilda → Mega Starmie ex + Water Energy（或 Staryu + 水）
  （Poffin 非首选；Supporter 槽应用 Hilda）

My-T2:
  PLAY Crispin → 补能/贴能
  EVOLVE（若 T1 拿的是 Staryu）→ Switch 送上 Active
  → Goal（My-T2）
```

### §Poffin 第二抓：应搜 Fan Rotom，实际搜 Snorunt（BUG-002 子项）

**现象（My-T1）**  
Poffin 正确第一抓 **Staryu**，第二抓上了 **Snorunt**，未上 **Fan Rotom (174)**。

**牌库事实（seed=43，Setup 后 deck 顶序）**  
Poffin 合法候选顺序：`Snorunt → Fan Rotom → Staryu → …`  
Fan Rotom 在 deck `[10]`，牌库顶第一张 Snorunt 在 `[0]`。

**代码根因（`opening_state.poffin_to_bench` + `opening_cards.POFFIN_IDS`）**

1. **`POFFIN_IDS` 未含 174** — Fan Rotom 是 HP≤70 基础，Buddy-Buddy Poffin **可搜**，但白名单漏掉。
2. **第二抓按牌库顺序盲扫** — Staryu 优先写入后，`for cid in deck` 遇到第一个 `POFFIN_IDS` 即 Snorunt，**未做 OPENING 优先级**。
3. **与规格冲突** — B1+Rotom / Fan Call 线要求 My-T1 尽量 **Bench 174 → Fan Call**（§3.5）；Snorunt 是 C1 降级坑，OPENING **低优先**（§3.2、deck_knowledge §2.3）。

**应实现的 Poffin 选牌优先级（OPENING，最多 2 只 → Bench）**

```
1030 Staryu          （G1 主轴，已有则跳过）
174  Fan Rotom       （My-T1 Fan Call 窗口；B1/B1+Rotom 高优）
65/305 Dunsparce     （填充 / Fan Call 副目标）
235  Budew           （兜底）
860  Snorunt         （OPENING 低优；C1 外避免占 Bench）
```

**若仍走 Poffin 线，本局第二抓应为 Fan Rotom**，随后同回合可 **ABILITY Fan Call** 再补 Dunsparce 等 — 而非浪费 Bench 位给 Snorunt。

### 应遵循的硬约束（待实现）

| ID | 规则 |
|----|------|
| E-MEOW-1 | 手有 **1071** 且 deck 有关键 Supporter（Hilda）且 Supporter 槽未用 → OPENING 可启用 **Last-Ditch Catch** |
| E-MEOW-2 | Meowth 检索目标 OPENING 优先级：**Hilda > Crispin**（非 CONTROL 时的 Boss/Judge） |
| E-B1-1 | B1 My-T1 路线优先级：**R-Meowth-Hilda > R1-T1 Hilda > R2-T1 Poffin**（当 Meowth+Hilda 在 deck 可达） |
| E-IDLE-1 | F-B/F-D 禁止空转回合；手有 Crispin/Ball/Meowth 必须执行 |
| E-CRIS-1 | 手有 **Crispin** 且 G2 → 优先于纯 ATTACH（搜 2 种基础能，1 入手 1 直贴） |
| E-SW-2 | 同 BUG-001：Bench 线用 Switch，非 retreat_promote |
| E-POFF-1 | Poffin 合法集 = HP≤70 基础，**含 174** |
| E-POFF-2 | Poffin OPENING 选牌序：**1030 > 174 > 65/305 > 235 >> 860**（非牌库顶序） |
| E-POFF-3 | My-T1 Poffin 出 174 后，同回合应接 **Fan Call**（若 174 已在 Bench） |

### 与规格的关系

- `01_opening.md` B1 写「Hilda/Poffin」— 未写 Meowth 链，但 `deck_knowledge.md` §3.6.6：**Meowth 是 deck 内唯一 Supporter 检索**（除 Hilda 自身）。OPENING 缺 Hilda 在手时，**Meowth→Hilda 是合法加速**，应写入路线表。
- OPENING **禁 Lillie**（HR-O6）— 本例不应靠 Lillie；Meowth→Hilda 是正解。
- **判 GOAL ≠ 决策正确** — 本 run 应用「过程验收」而非仅终局判定。

---

## BUG-003 · Run #4 · seed=45 · F1 线非法撤退 + Pad 搜 ex

**日志**: `logs/opening_batch_max5_42.log` Run #4  
**结果**: 模拟器判 **GOAL OK（My-T3）** — **过程含 2 处严重规则违规**  
**Setup**: **F1** — Active **Meowth ex**；奖品含 **Switch**、**Water Energy**；手牌 Water、Poffin、Ultra Ball、Crispin  

### Setup — 合规 ✓

Active = Meowth ex（1071）为基础宝可梦，F1 降级 Setup 合法。

### My-T1 — 部分合规 + 严重违规 1

| 步骤 | 行为 | 判定 |
|------|------|------|
| Ultra Ball 弃 Poffin + Dudunsparce → 搜 **Staryu** → Bench | R3b-T1 | ✓ 高级球合法 |
| **`Retreat promote Active ← Staryu`** | 无能量 Meowth 退场，Staryu 升 Active | ❌ **非法撤退** |

**违规 1 详情（E-RET-2）**

- Meowth ex **撤退费 = 1 无色**；Setup/T1 时 Active **无能量**。
- 未 ATTACH 任何能到 Meowth，也未使用 Switch / 减 retreat 道具。
- **`retreat_promote()` 在模拟器里无前提执行** → 场上「Staryu Active」为**非法状态**。
- 规格 §3.4：**F1 线应为 Bench 1030 + 附水 → T2 Bench 进化 + Switch**，**不是** T1 非法 Retreat 换 Active。

**本局 F1 更合规的 My-T1 sketch**

```
Ultra Ball → Staryu → Bench（Meowth 留 Active）
ATTACH Water Energy → Bench Staryu     ← 应用唯一 ATTACH，不 promote
（Meowth 留 Active 无妨；T2 再 Switch 或合法 Retreat）
```

**附带战术损失（非规则违法但差）**

- Ball 弃 **Poffin** → 失去 Poffin 铺场 / Fan 线选项。
- 手有 **Crispin** 未用（G2+G3 可一次补能）。
- 奖品区有 **Switch**，deck 内 Switch 不可达时，更不应依赖 `retreat_promote` 假换场。

### My-T2 — 继承非法场面

- 仅抽 Judge；F-B（1030+水、缺 1031）**空转**（同 BUG-002 E-IDLE-1）。
- 因 T1 非法 promote，**「Staryu Active」全程建立在违法状态上**。

### My-T3 — 严重违规 2

| 步骤 | 行为 | 判定 |
|------|------|------|
| **`Poké Pad → Mega Starmie ex`** | R5-REC F-B | ❌ **Pad 不能搜 Rule Box / 宝可梦 ex** |
| EVOLVE → Goal | 1030→1031 + Water | 进化本身可合法，但 **1031 来源违法** |

**违规 2 详情** — 同 BUG-001 **E-PAD-1**（跨 run 复发）

- Mega Starmie ex 带 **Pokémon ex 规则箱（Rule Box）**。
- Poké Pad 仅可搜 **无 Rule Box** 宝可梦（1030/860/65 等）。
- 正确拿 1031：**Hilda / Ultra Ball**（本局 T3 刚抽到 Pad，应 Pad→**Staryu** 或不用 Pad，Ball 搜 1031）。

### 与 BUG-001 的关联

| 违规 | BUG-001 | BUG-003 |
|------|---------|---------|
| Pad → 1031 | Run #1 My-T2 | Run #4 My-T3 |
| 无能量 retreat_promote | Munkidori Active | **Meowth ex Active** |

→ **`retreat_promote` 与 `poke_pad_search(MEGA)` 是系统性 bug**，非单局偶发。

### 应遵循的硬约束（补充）

| ID | 规则 |
|----|------|
| E-RET-2 | Retreat 前校验：**Active.retreat_cost ≤ 已附能（含 Prism 作 1 任意）**；Meowth ex = 1 无色 |
| E-F1-1 | F1 My-T1：**1030 下 Bench + 水贴 Bench 1030**；禁止 T1 `retreat_promote` |
| E-F1-2 | 升 Active 仅 **Switch (1123)** 或 **合法 Retreat**（§3.4） |
| E-PAD-1 | （重申）Pad **不可搜 1031** — 见 BUG-001 |
| E-BALL-1 | F-B 缺 1031 → **Ultra Ball 搜 1031**（可弃 Risky Ruins 等），非 Pad |

### 验收 implication

本 run 在真实 cabt 中应判 **非法操作链**；模拟器 **GOAL OK 为假阳性**。测试须加：

- `assert not retreat_without_cost(st, before_promote)`
- `assert pad_target not rule_box(ex)`

---

## BUG-004 · Run #6 · seed=47 · X1 线 Hilda 搜基础 + 非法撤退

**日志**: `logs/opening_batch_max5_42.log` Run #6  
**结果**: 模拟器判 **GOAL OK（My-T2）** — **过程含 2 处严重规则违规**  
**Setup**: **X1** — Active **Munkidori**；起手 **2×Hilda、Pad、Poffin、1031（已在手）**  

### Setup — 合规 ✓

Active = Munkidori（112）为基础宝可梦，合法。

### My-T1 — R1-T1：Hilda 检索对象违法

| 步骤 | 模拟器 | 判定 |
|------|--------|------|
| PLAY Hilda | `Hilda → ['Staryu', 'Water Energy']` | ❌ **严重违规 1** |
| Bench ← Staryu；ATTACH Water → Bench Staryu | 后续步骤 | 建立在违法检索上 |

**违规 1 详情（E-HILDA-1）**

- **Hilda（透子）官方效果**：从牌库各检索 **1 张进化宝可梦（Evolution Pokémon）** + **1 张能量** 入手。
- **Staryu (1030) 是基础宝可梦（Basic）**，不是进化宝可梦 → **Hilda 不能检索 1030**。
- 代码 `hilda_search(need_staryu=True)` 在 `opening_state.py` 中 **`picks.append(STARYU)`** — 与卡面不符。

**本局额外上下文**

| 事实 | 含义 |
|------|------|
| 起手已有 **Mega Starmie ex (1031)** | G3 已为 false，**不必**用 Hilda 找进化件 |
| G1 = 缺场上 1030 线 | 应走 **Poffin / Poké Pad / Ultra Ball / Fan Call** 拿 **基础** 1030，**不是 Hilda** |
| 起手无 Water | 合法路径：Pad/Poffin→1030→Bench，T2 再 attach 或 **Crispin** |

**更合规 My-T1 sketch**

```
PLAY Poffin 或 Poké Pad → 1030 上 Bench（Hilda 不参与 G1）
（若本回合有合法能量来源再 ATTACH；或 T2 Crispin/抽牌贴水）
手牌保留 1031 + 第二张 Hilda 备用
```

**规格文档冲突（待修正）**

- `deck_knowledge.md` 写「Hilda … 直接拿 **Staryu/1031** + 水能」— **「Staryu」一句与官方卡面不符**，应改为：**仅进化宝可梦（1031、104、861 等）+ 能量**；**1030 仅能通过 Poffin/Pad/Ball/Fan Call 取得**。

### My-T2 — 非法撤退 + 进化（假阳性 Goal）

| 步骤 | 行为 | 判定 |
|------|------|------|
| **`Retreat promote Active ← Staryu`** | Munkidori 0 能退场 | ❌ **严重违规 2**（同 E-RET-2 / BUG-001、003） |
| EVOLVE → Mega Starmie ex | T1 上场、T2 进化时机 ✓ | 场面建立在违法检索 + 违法升 Active 上 |

- Munkidori 撤退费 **1**；T2 开始前 Active **无能量**，本回合也未先 ATTACH 再 Retreat。
- 规格 §3.4：X1 线应 **Bench 1030 + 水 → T2 Bench EVOLVE → Switch**，非 `retreat_promote`。
- 奖品区有 **Switch** 时更应走 Switch 线，而非无能量 Retreat。

### 代码根因（两处）

```python
# opening_state.hilda_search — 违法检索 Basic
if need_staryu and STARYU in self.deck:
    picks.append(STARYU)   # ← E-HILDA-1 违反点

# opening_planner — R1-T1 在 G1 时调用 need_staryu=True
# 应禁止：G1 不得走 Hilda 拿 1030
```

### 应遵循的硬约束（补充）

| ID | 规则 |
|----|------|
| **E-HILDA-1** | Hilda 仅可检索 **进化宝可梦**（1031/104/861…）+ **能量**；**不可检索 1030** |
| **E-HILDA-2** | **G1（缺场上 1030 线）** → 禁用 R1-T1 Hilda；改用 Poffin/Pad/Ball/Fan Call |
| **E-HILDA-3** | 手牌已有 1031 时，Hilda 优先 **能量 + 第二进化件（861/104）**，非 1030 |
| E-RET-2 | （重申）Munkidori 无能量禁止 retreat_promote |
| E-SW-1 | （重申）Bench 进化线用 Switch |

### 与既有 BUG 的关系

| 违规 | 首次记录 | 本 run |
|------|----------|--------|
| Hilda 搜 1030 | — | **BUG-004 新** |
| retreat_promote 无能量 | BUG-001/003 | Munkidori Active（同 X1/F1） |
| GOAL 假阳性 | 全系 | My-T2 仍判 OK |

---

## BUG-005 · Run #7 · seed=48 · C1 线非法撤退 + T1 次优检索

**日志**: `logs/opening_batch_max5_42.log` Run #7  
**结果**: 模拟器判 **GOAL OK（My-T2）** — **含 1 处严重规则违规 + 1 处战术次优**  
**Setup**: **C1** — Active **Snorunt**；手牌 Poffin、Lillie、Ultra Ball、Hilda、Prism  

### Setup — 合规 ✓

Active = Snorunt（860）为基础宝可梦，C1 降级 Setup 合法。

### My-T1 — R3b-T1：规则合规，战术次优

| 步骤 | 行为 | 判定 |
|------|------|------|
| Ultra Ball 弃 Lillie + **Poffin** → 搜 Staryu → Bench | R3b-T1 | ✓ 高级球合法 |
| ATTACH **Prism** → Bench Staryu | 唯一手填 | ✓ 规则允许（手填 1 能合法） |

**战术次优（非规则违法，见 BUG-002 §Poffin）**

- 起手同时有 **Poffin + Ultra Ball**，却 Ball 并 **弃掉 Poffin**。
- 更优：**PLAY Poffin** → Staryu + **Fan Rotom (174)**（E-POFF-2），保留 Ball/Hilda 应对 G3。
- 弃 Lillie 作 Ball 代价在 OPENING 虽非违法（HR-O6 禁 **打出** Lillie，弃牌通常允许），但浪费过牌资源。

**附能说明**

- 本局 T1 手牌无 Water，贴 Prism 作为唯一 ATTACH **不违反**「每回合 1 手填」。
- 仍记 **E-ATT-1**：有 Water 时必须优先 Water；本局无 Water 可贴，Prism 可接受。
- Goal/Jetting 长期仍偏好真实 Water — 与 BUG-001 战术层一致，但 **本 run 用户未标此为严重违规**。

### My-T2 — Hilda 合规 + 严重违规 1

| 步骤 | 行为 | 判定 |
|------|------|------|
| Hilda → `['Mega Starmie ex']` | R3b-REC F-B | ✓ 进化检索合法（对比 BUG-004 禁 1030） |
| **`Retreat promote Active ← Staryu`** | Snorunt 0 能 | ❌ **严重违规 1** |
| EVOLVE → Mega on Active | 时机 T2 ✓ | 升 Active 方式违法 |

**严重违规 1（E-RET-2 / E-C1-1）**

- Snorunt 撤退费 **1**；Active **无能量**；T2 未 ATTACH、无 Switch/减 retreat 道具。
- **`retreat_promote` 再次无校验执行** — 同 BUG-001/003/004。
- **C1 规格 §3.4**：Snorunt 留 Active → **Bench 1030 进化 → Switch 送上 Active**，**禁止**无能量 Retreat。

**附带：Hilda 只拿 1031、未拿能量**

- 卡面应「进化 + 能量」各 1；日志仅 `['Mega Starmie ex']`（牌库能量可能已被 T1 消耗或检索逻辑未补第二格）。
- 非用户标定的严重违规，但 `hilda_search` 应保证 **双检索槽** 尽量填满。

### 更合规路线 sketch（C1 + 本手牌）

```
My-T1:
  Poffin → Staryu + Fan Rotom（非 Ball 弃 Poffin）
  ATTACH Prism → Bench Staryu（或无 Water 时暂贴 Prism）

My-T2:
  Hilda → 1031 + Water（若 deck 有）
  EVOLVE Bench 1030 → Switch 送上 Active   （奖品/deck 有 Switch 时）
  — 禁止 retreat_promote
```

### 应遵循的硬约束（补充）

| ID | 规则 |
|----|------|
| **E-C1-1** | C1：Snorunt Active **不可无能量 Retreat**；升 1031 用 **Switch** |
| E-RET-2 | （重申）Active.retreat_cost 未满足 → 禁止 promote |
| E-SW-1 | （重申）Bench 进化线 Switch 优先 |
| E-POFF-2 | （重申）有 Poffin 时优先于 Ball 弃 Poffin（BUG-002） |

### 与既有 BUG 的关系

| 类型 | 记录 |
|------|------|
| 非法 retreat_promote | **第 4 次**（Munkidori×2、Meowth、**Snorunt**）— 全系 bug |
| Poffin vs Ball | BUG-002 再现（弃 Poffin 用 Ball） |
| Hilda 搜 1031 | ✓ 本 run 正确（对比 BUG-004） |
| GOAL 假阳性 | Active Mega + Prism 判 OK |

---

## BUG-006 · Run #9 · seed=50 · C1 线无检索件 G1 空转

**日志**: `logs/test_batch_max5.log` Run #9  
**结果**: **未达成 (F-E) My-T5** — 全程合法，但 **5 回合内无检索动作**  
**Setup**: C1 — Active **Snorunt**；起手 **无 Poffin / Pad / Ball / Hilda**  

### 错误链

| 回合 | 模拟器行为 | 问题 |
|------|------------|------|
| **My-T1–T5** | 路线 **R-IDLE-T1 / R-IDLE-REC**；仅抽牌 | G1 全程为 true，但手牌无检索件，**无法执行任何 G1 动作** |
| 抽牌 | Froslass → Ignition → Boss → Water | 牌库前 4 张均非检索；**Poké Pad 在 deck[7+]**，5 回合内未入手 |

### 牌库事实（seed=50，Setup 后 deck 顶序）

`Froslass → Ignition → Boss → Water → Mega Froslass ex → … → Poké Pad → … → Hilda → Ultra Ball → …`

### 应遵循的硬约束 / 备注

| ID | 规则 |
|----|------|
| E-G1-IDLE-1 | G1 + 手牌无检索 → 允许 R-IDLE，但 **抽入 Pad/Ball/Poffin 后下一回合必须切检索路线** |
| E-G1-DECK-1 | 本局属 **牌库顺序 + 5 回合上限** 导致的不可达，非规则违法 |
| HR-O6 | 仍禁 Lillie；不可用 Lillie 过牌解 G1 |

### Phase 3 方向

- 抽入检索件后强制 R2/R3/R5（已在 F-E 分支；本局 5 回合内未触发）
- 可选：提高 `MAX_TURNS` 或单独标注「慢速 C1 牌序」测试用例

---

## 修复记录（Phase 0～2 · 2026-06-24）

> 对照日志：`logs/test_batch_max5.log`（seed_base=42，上限 5 回合）。  
> 人工审 Run 时请以 **本段 + 新日志** 为准；`opening_batch_max5_42.log` 为 Phase 0 前旧日志。

### Phase 0 · 硬规则层（BUG-001～005 共性）

| 规则 ID | 实现位置 | 状态 |
|---------|----------|------|
| E-PAD-1 | `opening_cards.PAD_SEARCH_IDS` + `poke_pad_search()` 拦截 | ✅ |
| E-HILDA-1/2 | `hilda_search()` 仅进化 + 能量；删除 R1-T1（G1 禁 Hilda 拿 1030） | ✅ |
| E-RET-1/2 | `retreat_promote_bench()` 校验撤退费；日志改 `[RETREAT]` | ✅ |
| E-SW-1 | `switch_mega_to_active()` 无 Switch 不 fallback 非法 retreat | ✅ |
| E-ATT-1 | `attach_water_to()` Water(3) 优先于 Prism(16) | ✅ |
| HR-O6 | 删除全部 Lillie 紧急线（R7-T1-L / R7-REC） | ✅ |
| 过程断言 | `opening_validate.validate_log()` / `assert_legal_simulation()` | ✅ |

**Phase 0 后批量**：Goal 3/10（合法但路线弱）；BUG run seed 42/45/47/48 均 **0 违规、5 回合内未 GOAL**（假阳性消除，预期）。

### Phase 1 · Switch / Salvatore / 合法升场

| 能力 | 实现 | 状态 |
|------|------|------|
| Salvatore F-B | `_try_salvatore_evolve()` + `salvatore_evolve_staryu()` | ✅ |
| Switch 升 Active | 有 Switch → `switch_mega_to_active()` | ✅ |
| 合法 Retreat 升 Mega | 占位 Active 贴能 → `[RETREAT]` 换 Bench Mega（X1/C1/F1） | ✅ |
| F-B 恢复链 | `_execute_f_b_recovery()`：Salvatore → Hilda → Ball 搜 1031 | ✅ |
| R5-REC 空转（F-B） | F-B 分支不再 Pad 重复搜 1030 | ✅ |

### Phase 2 · 能力与选牌

| 能力 | 实现 | 状态 |
|------|------|------|
| Meowth Last-Ditch | `play_meowth_to_bench_with_catch()` + **R-Meowth-T1** | ✅ |
| Poffin 优先级 | `POFFIN_OPENING_PRIORITY`（1030>174>65/305>235>>860） | ✅ |
| Fan Call 选牌 | `fan_call()` 按优先级，非牌库顶序 | ✅ |
| Crispin | 仅 2 种基础能量：1 入手 + 1 直贴（修正误搜训练家） | ✅ |
| B1 路线 | Meowth→Hilda 优先于纯 Poffin（seed 43） | ✅ |

### BUG Run 回归（Phase 0～2 后 · test_batch_max5.log）

| BUG | seed | 旧结果 | 新结果（2026-06-24） |
|-----|------|--------|----------------------|
| BUG-001 | 42 | 假阳性 GOAL T2 | **合法 GOAL My-T2** ✅ |
| BUG-002 | 43 | 假阳性 GOAL T5 | **合法 GOAL My-T3**（R-Meowth-T1） ✅ |
| BUG-003 | 45 | 假阳性 GOAL T3 | **合法 GOAL My-T5**（T1 Poffin 保留 Ball；T2 Ball→1031） ✅ |
| BUG-004 | 47 | 假阳性 GOAL T2 | **合法 GOAL My-T4** ✅ |
| BUG-005 | 48 | 假阳性 GOAL T2 | **合法 GOAL My-T4** ✅ |

**批量**：Goal **9/10**（仅 seed 50 F-E 不可达）；**全程 0 规则违规**。

### 待办（Phase 3+）

| ID | 问题 | 方向 |
|----|------|------|
| BUG-006 / seed 50 | C1 起手无检索，5 回合内 Pad 未入手 | 标注牌序不可达；或 `MAX_TURNS≥8` 专项测试 |
| E-BALL-2 | Ball 弃牌序 | Ruins/Pad 优先于 Poffin（已实现） |
| BUG-003 优化 | seed 45 可压至 My-T2–T3 | Salvatore/Hilda 抽牌后更早进化 |

---

## 人工复核 · 规则漏洞（2026-06-24 第二轮）

> 对照 `logs/test_batch_max5.log` Run #4/#6/#7。以下问题 **属实**，已在代码中修复。

### E-FAN-C1 · Fan Call 仅限 `{C}` 属性

| Run | 违规现象 | 根因 | 修复 |
|-----|----------|------|------|
| #4 seed=45 T1 | Fan Call → Dunsparce, **Snorunt**, **Budew** | `FAN_CALL_IDS` 误含 1030/860/235（水/草） | 白名单改为 **174/65/305** 仅无色 |
| #7 seed=48 T1 | Fan Call → Dunsparce, Dunsparce, **Snorunt** | 同上 | 同上 |

官方文本：`search … up to 3 {C} Pokémon with 100 HP or less`。Staryu(水)、Snorunt(水)、Budew(草) **不可**被 Fan Call 检索。

### E-RET-DISC · 手动撤退须丢弃撤退费能量

| Run | 违规现象 | 根因 | 修复 |
|-----|----------|------|------|
| #4 seed=45 T5 | Meowth ex 退场后 Bench 仍带 **Darkness Energy** | `retreat_promote_bench` 未 `discard` 支付能量 | 撤退前 `_discard_retreat_cost()` → `[DISCARD]` |
| #6 seed=47 T4 | Munkidori 退场后 Bench 仍带 **Prism Energy** | 同上 | 同上 |
| #7 seed=48 T3 | Snorunt 退场后 Bench 仍带 **Darkness Energy** | 同上 | 同上 |

### E-PRISM-1 · 棱镜能量仅可贴基础宝可梦

| Run | 违规现象 | 根因 | 修复 |
|-----|----------|------|------|
| #7 seed=48 T2 | 进化后 Mega Starmie ex 仍保留 **Prism Energy** | `evolve_staryu` 未执行进化解除丢弃 | `_enforce_prism_on_basic_only()` 进化后丢弃 Prism |

### 修复后回归（同日志批次重跑）

| seed | 修复前 Goal | 修复后 Goal |  validator |
|------|-------------|-------------|------------|
| 45 | GOAL T5（含上述违规） | GOAL T5 **合法** | 0 违规 |
| 47 | GOAL T4（含撤退违规） | GOAL T4 **合法** | 0 违规 |
| 48 | GOAL T3（含 3 处违规） | **GOAL T5 合法**（Prism 进化丢弃 + T4 贴暗能备退 + T5 贴水 Retreat） | 0 违规 |

**说明**：seed 48 修复后需 **T4 给 Snorunt 贴 retreat 费、T5 给 Bench Mega 贴 Water 再合法 Retreat**；与官方流程一致。

---

## 修复顺序建议

1. 写死 **E-PAD / E-ATT / E-RET / E-SW / E-HILDA / E-C1**（BUG-001～005）
2. 实现 **Meowth Last-Ditch Catch + B1 路线优先级 + Poffin 选牌**（BUG-002）
3. 消除 **R5-REC / R-IDLE-REC 空转**（BUG-002 §T3–T4）
4. 再跑批量测试；**不以达成率为先**，以日志人工抽检 + **过程规则断言**为先

---

## 变更记录

| 日期 | 条目 |
|------|------|
| 2026-06-23 | 新增 BUG-001（seed=42 / Run #1） |
| 2026-06-23 | 新增 BUG-002（seed=43 / Run #2） |
| 2026-06-23 | BUG-002 补充：Poffin 第二抓 Snorunt 应 Fan Rotom（E-POFF-1~3） |
| 2026-06-23 | 新增 BUG-003（seed=45 / Run #4）非法 Retreat + Pad 搜 1031 |
| 2026-06-23 | 新增 BUG-004（seed=47 / Run #6）Hilda 搜 Basic 1030 + 非法 Retreat |
| 2026-06-23 | 新增 BUG-005（seed=48 / Run #7）C1 Snorunt 非法 Retreat + Poffin 次优 |
| 2026-06-24 | Phase 0～2 修复记录；BUG-001/002/004/005 合法 GOAL；BUG-003 仍 F-B |
| 2026-06-24 | 新增 BUG-006（seed=50 / Run #9）C1 无检索件 G1 空转 |
| 2026-06-24 | Phase 3：T1 Poffin>Ball、Ball 弃牌序；BUG-003 seed45 GOAL；批量 9/10 |
| 2026-06-24 | 人工复核 E-FAN-C1 / E-RET-DISC / E-PRISM-1 修复；validator 增强 |
