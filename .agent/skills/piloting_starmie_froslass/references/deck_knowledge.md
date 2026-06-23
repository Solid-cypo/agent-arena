# Starmie + Froslass 卡组知识库

> 卡组文件：`data/decks/starmie_froslass.csv`（60 张）  
> 战术定位：**TEMPO / BURST** — 两回合铺 Mega Starmie ex，Jetting Blow 持续打后排，愿增猿转伤，大雪妖女收割  
> 本文档是硬编码路线规划的**唯一卡牌事实来源**；所有 card ID 以 `_CARDS` 字典为准。

---

## 1. 卡组构成一览

| 类别 | 张数 | 核心作用 |
|---|---:|---|
| 宝可梦 | 21 | 双 Mega 攻击线 + 引擎 + 干扰 |
| 物品 | 15 | 检索、回收、切换 |
| 支援者 | 13 | 抽牌、检索、控场（工具箱式各 1~4 张） |
| 竞技场 | 3 | Risky Ruins 后场压制 |
| 能量 | 8 | 水为主，暗给愿增猿，特殊能量加速 |

### 1.1 进化线

```
Staryu (1030) ×2  ──→  Mega Starmie ex (1031) ×2     【主攻击线 · 大海星】
Snorunt (860) ×3   ──→  Froslass (104) ×1            【小雪妖女 · 撒点引擎】
                    └──→  Mega Froslass ex (861) ×2   【大雪妖女 · 收割手】

Dunsparce (65/305) ×3 ──→ Dudunsparce (66) ×2         【抽牌引擎 · Fan Call 填充物】
                       └── Dudunsparce ex (306) ×1   【备用打手 · 打 ex 阵容】

独立基础：Munkidori (112) ×2 · Fan Rotom (174) ×1 · Budew (235) ×1 · Meowth ex (1071) ×1
```

### 1.2 能量构成

| ID | 名称 | 张数 | 用途 |
|---|---|---:|---|
| 3 | Basic Water | 4 | Staryu / Snorunt / Mega 水招 |
| 7 | Basic Dark | 2 | **愿增猿 Adrena-Brain 必需** |
| 16 | Prism Energy | 1 | 贴基础宝可梦提供任意 1 能量 |
| 17 | Ignition Energy | 1 | 贴**进化**宝可梦 = 3 无色；回合结束弃置 |

**Ignition 关键用法**：贴 Mega Starmie ex → 当回合可打 Nebula Beam（3 无色，210 伤）。

---

## 2. 核心宝可梦详解

### 2.1 Mega Starmie ex `[1031]` ×2 — 大海星（主 C）

| 属性 | 值 |
|---|---|
| HP | 330 |
| 弱点 | Lightning |
| 撤退 | 2 |
| 进化 | Staryu → Mega Starmie ex |

| attackId | 招式 | 伤害 | 费用 | 硬编码默认 |
|---:|---|---:|---|---|
| 1487 | **Jetting Blow** | 120 + 后排 50 | 1 水 | **AGGRESSION 默认招式** |
| 1488 | Nebula Beam | 210（无视弱点/效果） | 3 无色 | 对手 active hp ≤ 210 可 KO 时用 |

**战术角色**：
- 主输出；不是单发 Nebula 暴毙流，而是 **Jetting 连续打后排 50** 积累伤害
- 配合愿增猿：受伤后每回合转走 30~60 有效 HP
- 配合 Boss：把后排低 HP 目标拉上来 KO

**硬编码锚点**：`OPENING` 阶段唯一目标；`AGGRESSION` 阶段每回合必攻。

---

### 2.2 Mega Froslass ex `[861]` ×2 — 大雪妖女（收割 C）

| 属性 | 值 |
|---|---|
| HP | 310 |
| 弱点 | Metal |
| 撤退 | 1 |

| attackId | 招式 | 伤害 | 费用 | 触发时机 |
|---:|---|---:|---|---|
| 1240 | **Resentful Refrain** | 50 × 对手手牌数 | 1 水 | 对手手牌 ≥5 / 刚拿奖 / Judge 后 |
| 1241 | Absolute Snow | 150 + 睡眠 | 水+2 无 | 手牌少、需控场续战 |

**战术角色**：
- **捏在手里**，不在 OPENING 阶段进化
- `HARVEST` 模式：大海星被 KO 后，对手手牌最肥时出场一击
- 与 Judge 配合：先 Froslass 打 Resentful，**下回合**再 Judge（顺序不能反）

---

### 2.3 Froslass `[104]` ×1 — 小雪妖女（撒点引擎）

| 能力 | Freezing Shroud |
|---|---|
| 效果 | 每次 Checkup，对所有**有 Ability 的宝可梦**（双方，Froslass 除外）放 1 伤害标记 |

**战术角色**：
- 进化自 Snorunt，**不急于 Mega 861**
- 给对手有 Ability 的宝可梦持续放标记
- 愿增猿把己方（Munkidori/Meowth ex）身上的标记**转给对手**
- Bench 坑位 1 固定给 Snorunt → Froslass 线

**注意**：会伤己方 Munkidori/Meowth ex → 这是刻意设计，由愿增猿转移消化。

---

### 2.4 Munkidori `[112]` ×2 — 愿增猿（枢纽）

| 能力 | Adrena-Brain |
|---|---|
| 条件 | 身上附有 **{D} 暗能量** |
| 效果 | 每回合 1 次：将己方**任意 1 只**宝可梦最多 3 个伤害标记，移到对手 1 只宝可梦上 |

| 攻击 | Mind Bend 60 + 混乱 | 超+无 |

**战术角色**：
- **防御**：大海星 330 HP + 每回合转走 30~60 → 等效 360~390
- **进攻**：Froslass 撒点 + Jetting 后排 50 + 转移标记 → 后排底座进入 KO 范围
- Bench 坑位 2 固定；**硬规则**：有 dark 能量则每回合 DOMINATE 触发能力

---

### 2.5 Fan Rotom `[174]` ×1 — 第一回合铺场

| 能力 | Fan Call |
|---|---|
| 条件 | **仅第一回合**（`turn ≤ 2`） |
| 效果 | 从牌库搜最多 3 只 HP≤100 的 {C} 宝可梦入手 |

**可搜目标（本卡组）**：Dunsparce(65/305)、Snorunt(860)、Staryu(1030)、Budew(235)、Fan Rotom 自身

**战术角色**：
- T1 核心：上 Fan Rotom → Fan Call → 快速填满 bench
- 同时铺 Staryu / Snorunt / Dunsparce 为后续进化链准备
- Assault Landing（70 伤）仅在有 Risky Ruins 场时可用

**My-T1 后生命周期（硬编码 FR-1~4）**：
- Fan Call 窗口关闭后，**手牌中的 174 标记为废牌**
- **禁止** PLAY 174 上 Bench（My-T2+）
- Ultra Ball 等弃牌换收益：**高优先** 弃对象（仅次于 Lillie 副本）
- 已在场的 174 保留占位，不 RETREAT

详见 [phases/01_opening.md §3.6](../phases/01_opening.md)。

### 2.6 Budew `[235]` ×1 — 开局兜底

| 攻击 | Itchy Pollen |
|---|---|
| 费用 | 0 能量 |
| 效果 | 10 伤 + **对手下回合不能打 Item** |

**战术角色**：
- OPENING 第 2 回合仍无大海星 → Active 换 Budew 拖延
- 封锁对手 Poffin / Ultra Ball / Poké Pad
- 仅 30 HP；**Risky Ruins 打出前**使用，否则自伤

---

### 2.7 Meowth ex `[1071]` ×1 — 控场检索

| 能力 | Last-Ditch Catch |
|---|---|
| 触发 | 从手牌放到 Bench 时 |
| 效果 | 从牌库搜 1 张**支援者**入手 |

**战术角色**：
- `CONTROL` 模式（领先 ≥1 奖）：上 Meowth ex → 搜 Boss's Orders / Judge
- Tuck Tail：60 伤后回手（可反复 Last-Ditch Catch）
- Bench 坑位 3 备用

---

### 2.8 Dunsparce 线 ×3+2+1 — 抽牌 / 填充

| 卡牌 | 角色 |
|---|---|
| Dunsparce (65) ×2 | Fan Call 填充；Gnaw/Dig 前期占位 |
| Dunsparce (305) ×1 | Trading Places 换场；Ram 20 |
| Dudunsparce (66) ×2 | Run Away Draw：抽 3 后洗回牌库（循环引擎） |
| Dudunsparce ex (306) ×1 | Tenacious Tail：60×对手 ex 数量；备用 ex 打手 |

**战术角色**：Fan Call 的搜索目标；不是主 C，但提供 bench 厚度与抽牌。

---

## 3. 训练家牌详解

### 3.1 检索链（OPENING 核心）

| ID | 名称 | 张数 | 检索内容 | 路径优先级 |
|---|---|---:|---|---|
| 1225 | **Hilda** | 3 | 1 进化宝可梦 + 1 能量 | **P2** — 拿 **1031/104/861** 等进化件 + 水能；**1030 仅 Poffin/Pad/Ball/Fan Call** |
| 1086 | Buddy-Buddy Poffin | 4 | 最多 2 只 HP≤70 基础 → Bench | **P3** — 铺 Staryu/Snorunt |
| 1121 | Ultra Ball | 3 | 任意宝可梦（需弃 2 张） | **P4** — 搜 Staryu |
| 1152 | **Poké Pad** | 4 | 全牌库搜 1 无 Rule Box 宝可梦入手 | **P5** — 取 Staryu/Snorunt/Dudunsparce 等 |
| 1189 | Salvatore | 1 | 搜无 Ability 进化贴到场上宝可梦 | 特殊：手牌 Staryu 在场上时可直进化 |

**Poké Pad 定位**：card text 为 **Search your deck**（非顶 7）；可搜 Staryu、Snorunt、Dudunsparce、Froslass 等无 Rule Box 宝可梦，**不能**搜 Mega ex / Meowth ex。

### 3.2 纯过牌（增加手牌数）

| ID | 名称 | 张数 | 效果 | 净手牌变化 | 使用时机 |
|---|---|---:|---|---|---|
| 1227 | **Lillie's Determination** | 4 | 手牌洗回牌库 → 抽 6；剩 **6 奖**时抽 **8** | +6 或 +8（相对 0 手） | 手牌断档、需找第二套攻击线/工具 |
| 66 | Dudunsparce **Run Away Draw** | 2 | 抽 3 → 将该 Dudunsparce 及附属洗回牌库 | **+3**（Ability，非支援者） | AGGRESSION 中期维持手牌；见 §3.6 |
| 1080 | Unfair Stamp | 1 | ACE · 双方手牌洗回；你抽 **5** 对手抽 **2** | +5（需上回合被 KO） | HARVEST：大海星被 KO 后反打 |
| 1213 | Judge | 1 | 双方手牌洗回，各抽 4 | 对称重置 | CONTROL；**大雪妖女 Resentful 前禁止** |

**隐式过牌**：每拿 1 奖抽 1 张（KO 对手 active 时尤其肥）。

### 3.3 检索 / 回收（提质或补关键件，非纯抽）

| ID | 名称 | 张数 | 效果 | 净手牌 | 轴 |
|---|---|---:|---|---|---|
| 1225 | Hilda | 3 | 1 进化宝可梦 + 1 能量入手 | +2 | OPENING 主轴 |
| 1121 | Ultra Ball | 3 | 弃 2 → 搜 1 宝可梦入手 | **-1**（Ball 本身消耗） | OPENING 兜底 |
| 1152 | Poké Pad | 4 | 搜 1 无 Rule Box 宝可梦入手 | 0 | OPENING / 中期补件 |
| 1071 | Meowth ex **Last-Ditch Catch** | 1 | 从手牌上 Bench 时搜 1 支援者 | +1 Supporter | CONTROL 工具箱 |
| 1198 | Crispin | 1 | 搜 2 种不同基础能量，1 入手 1 直接贴 | +1 能量 | 暗能给愿增猿 / 水能给 Staryu |
| 1097 | Night Stretcher | 2 | 弃牌区 1 宝可梦或基础能量回手 | +1 | Staryu/能量被 Ultra Ball 弃掉后回收 |
| 1229 | Wally's Compassion | 1 | 治愈 Mega ex 全部伤害，能量回手 | +N 能量 | 大海星续命（非过牌，但重组能量链） |

### 3.4 铺场检索（直接到 Bench，不增加手牌）

| ID | 名称 | 张数 | 效果 | 轴 |
|---|---|---:|---|---|
| 174 | Fan Rotom **Fan Call** | 1 | T1 搜最多 3 只 HP≤100 {C} 基础入手 | OPENING · 与 Dudunsparce 线联动 |
| 1086 | Buddy-Buddy Poffin | 4 | 搜最多 2 只 HP≤70 基础 → 直接上 Bench | OPENING · 不占支援者 slot 的铺场 |

### 3.5 控场支援者（各 1 张 · Meowth ex 可搜）

| ID | 名称 | 效果 | 模式 |
|---|---|---|---|
| 1182 | Boss's Orders ×2 | 指定对手 Bench 到 Active | AGGRESSION / HARVEST / CONTROL |
| 1213 | Judge ×1 | 双方手牌洗回，各抽 4 | CONTROL；**配合大雪妖女前先 Judge 会降伤** |
| 1198 | Crispin ×1 | 搜 2 种不同基础能量，1 入手 1 直接贴 | 给愿增猿贴暗能 / 给 Staryu 贴水能 |
| 1225 | Hilda ×3 | 见上 | OPENING |

### 3.6 过牌轴系统分析

本 deck 的过牌不是单一引擎，而是 **三条并行轴**，共享同一牌库但服务不同阶段。

#### 3.6.1 三轴定义

```
┌─────────────────────────────────────────────────────────────────┐
│  A. 铺场/检索轴（OPENING · T1–T3）                               │
│     Fan Call → Hilda → Poffin → Ultra Ball → Pad → Salvatore    │
│     目标：T2 大海星；不追求手牌数量，追求「正确牌到手/到 Bench」   │
├─────────────────────────────────────────────────────────────────┤
│  B. 纯过牌轴（AGGRESSION · T3+）                                 │
│     Lillie ×4 + Dudunsparce Run Away Draw ×2                     │
│     目标：setup 牌消耗后维持 5–7 张手牌，继续找 Boss/Pad/第二 C   │
├─────────────────────────────────────────────────────────────────┤
│  C. 反打过牌轴（HARVEST · 被动触发）                             │
│     Unfair Stamp + 拿奖抽牌 + Meowth 搜 Boss/Judge               │
│     目标：大海星被 KO 后手牌反超，衔接 Froslass 收割              │
└─────────────────────────────────────────────────────────────────┘
```

#### 3.6.2 牌库资源预算（60 张中的「访问牌库」份额）

| 类别 | 张数 | 占 deck | 轴 |
|---|---:|---:|---|
| Lillie | 4 | 6.7% | B 纯过牌 |
| Hilda | 3 | 5.0% | A 检索 |
| Poffin | 4 | 6.7% | A 铺场 |
| Poké Pad | 4 | 6.7% | A/B 检索 |
| Ultra Ball | 3 | 5.0% | A 检索 |
| Dudunsparce 线（65×2+305×1+66×2+306×1） | 6 | 10.0% | A 填充 + B 循环 |
| Fan Rotom | 1 | 1.7% | A T1 |
| Meowth ex | 1 | 1.7% | C 搜 Supporter |
| Unfair Stamp / Judge / Crispin / Night Stretcher | 各 1–2 | 8.3% | B/C 混合 |
| **合计「访问牌库」相关** | **~28** | **~47%** | — |

**结论**：近半数牌库 dedicated 到 consistency；这是一套 **高一致性 Tempo deck**，靠轴 A 赢速度、靠轴 B 赢中后期资源战。

#### 3.6.3 轴 A ↔ 轴 B 的切换时机

| 信号 | 继续轴 A（检索/铺场） | 切换到轴 B（Lillie / Dudunsparce） |
|---|---|---|
| Phase | OPENING | AGGRESSION 且 Active 已是 Mega Starmie |
| 手牌 | 缺 Staryu/能量/进化件 | 有攻击线但缺 Boss/Pad/第二 1031 |
| 奖区 | prize ≥ 5 | prize ≤ 5（Lillie 8 抽窗口打开） |
| 禁忌 | **有 Hilda+Staryu+水能组合时禁止 Lillie** | OPENING 未出大海星时 **禁止 Lillie**（洗掉组合） |

**Lillie 决策树（硬编码建议）**：

1. `phase == OPENING` 且 `not mega_ready` → **禁止** PLAY Lillie  
2. `hand_size ≤ 2` 且 `phase != OPENING` → **优先** Lillie  
3. `prize_self == 6` 且需要第二攻击线 → **高优先** Lillie（抽 8）  
4. 手牌含 Boss + 目标在场 → **禁止** Lillie（保留 Boss）  
5. 刚 Unfair Stamp 后手牌已 5+ → **禁止** Lillie  

#### 3.6.4 Dudunsparce 循环引擎（轴 B 核心）

**Run Away Draw 原文**：每回合 1 次，抽 3 张 → 将该 Dudunsparce 及附属**洗回牌库**。

```
Fan Call / Poffin 铺 Dunsparce(65/305) 到 Bench
  → EVOLVE → Dudunsparce(66)
  → ABILITY Run Away Draw (+3 手牌)
  → Dudunsparce 回库（bench 空出）
  → 牌库仍有 Dunsparce/66 → 可再次进化循环
```

| 维度 | 分析 |
|---|---|
| **优点** | 不消耗支援者 slot；+3 净牌；与 Fan Call 天然联动（Fan Call 可一次拿 3 只含 Dunsparce） |
| **成本** | 占 1 bench 位 + 1 进化动作 + Dudunsparce 140HP 3  retreat 不适合长期留场 |
| **与主计划冲突** | OPENING 阶段 bench 应留给 Staryu/Snorunt/Munkidori → **T3 前不主动循环** |
| **最佳窗口** | AGGRESSION 三坑就位后；手牌 ≤4 且支援者已用 → Run Away Draw 补牌找 Pad/Boss |
| **306 ex 分支** | Dudunsparce ex 无 Run Away Draw；仅 ex 对局备用打手，**不参与过牌循环** |

**与 Lillie 的分工**：

| 场景 | 优先 |
|---|---|
| 手牌全废、无关键件 | **Lillie**（全洗重来） |
| 手牌尚可、需 +3 微调 | **Run Away Draw**（保留现有 Boss/Hilda） |
| prize=6 需要大量找牌 | **Lillie**（8 抽 > 3 抽） |
| bench 满、无法进化 Dudunsparce | **Lillie** 或 **Pad** |

#### 3.6.5 Ultra Ball 的「伪过牌」

Ultra Ball 弃 2 搜 1 宝可梦：**净 -1 手牌**，但可将废牌（多余能量、已用过的支援者副本）转化为目标宝可梦。

- OPENING：弃非 Staryu 线牌搜 Staryu/1031 — **轴 A**  
- AGGRESSION：弃能量副本搜 Meowth ex / 第二 Staryu — **轴 B 的提质**  
- 与 Night Stretcher 形成 **弃牌→回收** 闭环（Staryu 被弃后 Stretcher 拉回）

#### 3.6.6 Meowth ex 工具箱轴（轴 C 子系统）

```
CONTROL 模式 + bench 有空位
  → PLAY Meowth ex → Last-Ditch Catch 搜 Boss(1182) 或 Judge(1213)
  → Tuck Tail 打 60 → 回手 → 再次 Last-Ditch Catch（每回合 Last-Ditch 限 1 次）
```

- **不是纯过牌**：每次 +1 张**指定类型**（Supporter），精度高于 Lillie  
- Poké Pad **不能**搜支援者；Meowth 是 deck 内唯一的 **Supporter 检索**（除 Hilda 自身）  
- 这解释了 Boss/Judge/Crispin 各 1 张仍够用

#### 3.6.7 与 meta Deck 的过牌轴对比

| Deck | 主过牌 | 本 deck 差异 |
|---|---|---|
| Hops Control (Tea Party) | Lillie ×4 + 控场 | 同样 4 Lillie，但本 deck **OPENING 不能乱 Lillie** |
| Hops Aggro Tempo (foo_foo) | 65/66 Dudunsparce + Lillie | 本 deck 复用 Dudunsparce 线，但 **主 C 是 Starmie 不是 Hops** |
| Alakazam Dudunsparce | 66 循环 + 强化锤 | 本 deck 无 1081；过牌为 **服务双 Mega 切换** |

#### 3.6.8 硬编码模块映射（过牌轴）

| 决策 | 模块 | 规则 ID |
|---|---|---|
| OPENING 禁 Lillie | `phase_fsm.py` | `DR-1` |
| 手牌 ≤2 且非 OPENING → 优先 Lillie | `path_planner.py` | `DR-2` |
| prize=6 → Lillie 加权 | `path_planner.py` | `DR-3` |
| T3+ bench 有 Dunsparce 可进化 → Run Away Draw | `starmie_pilot.py` | `DR-4` |
| 手牌有 Boss 且 gust 目标在场 → 禁 Lillie | `path_planner.py` | `DR-5` |
| HARVEST 被 KO 后 → Unfair Stamp | `phase_fsm.py` | `DR-6` |
| CONTROL → Meowth ex 搜 Boss/Judge | `phase_fsm.py` | `DR-7` |

### 3.7 其他物品

| ID | 名称 | 张数 | 效果 | 使用时机 |
|---|---|---:|---|---|
| 1123 | Switch | 1 | 主动 ↔ 备战交换 | 大海星在 bench 时送上 Active |

### 3.8 竞技场

| ID | 名称 | 张数 | 效果 | 使用规则 |
|---|---|---:|---|---|
| 1260 | Risky Ruins | 3 | 双方放置非暗基础到 Bench 时，该宝可梦受 2 伤害标记 | **Bench 三坑就位后再打出**；Budew(30HP) 打出前会自伤 |

---

## 4. 战术阶段 × 卡牌映射

| 阶段 | 核心任务 | 优先使用的牌 |
|---|---|---|
| **OPENING** | 2 回合内大海星 | Fan Rotom → Hilda/Poffin/Ultra Ball/Pad → Staryu+附能+进化；兜底 Budew |
| **AGGRESSION** | 每回合 Jetting Blow | Mega Starmie ex；Boss 拉 weak；愿增猿转伤；Risky Ruins |
| **HARVEST** | 大雪妖女收割 | Mega Froslass ex Resentful；Boss；Unfair Stamp |
| **CONTROL** | 领先时控场 | Meowth ex → Boss/Judge；Dudunsparce ex 备用 |

---

## 5. Bench 三坑模板（硬编码）

| 坑位 | 优先卡牌 | 进化目标 | 能量需求 |
|---|---|---|---|
| **Bench-1** | Snorunt (860) | Froslass (104) 撒点 | 1 水（Froslass 招） |
| **Bench-2** | Munkidori (112) | 不进化 | **1 暗（能力必需）** |
| **Bench-3** | Staryu / Meowth ex / Dunsparce | 备用打手或 CONTROL | 视角色 |

**附能优先级（AGGRESSION 开始后）**：
1. Active Mega Starmie：1 水（Jetting Blow）
2. Bench Munkidori：1 暗（Adrena-Brain）
3. Bench Snorunt 线：1 水（Froslass 能力链）
4. Ignition → Mega Starmie（当回合 Nebula 秒杀窗口）

---

## 6. 关键联动链（硬编码必须覆盖）

### 链 A — 铺大海星（OPENING）

```
Fan Call(T1) → bench 有 Staryu
  → Hilda / Poffin / Ultra Ball / Pad 加速
  → ATTACH 水能到 Staryu
  → EVOLVE → Mega Starmie ex (1031)
  → T2 结束目标达成
```

### 链 B — 散射 + 转伤（AGGRESSION）

```
每回合 Jetting Blow (1487) → 后排 +50
  + Froslass Freezing Shroud → 能力宝可梦 +10/回合
  + Munkidori Adrena-Brain → 标记转到对手后排
  + Boss's Orders → 拉 weak 目标到 Active → KO
```

### 链 C — 大海星续命

```
Mega Starmie 受伤
  → Munkidori 转走 30~60 伤害标记/回合
  → 等效 HP 360~390，无需 RETREAT
```

### 链 D — 收割（HARVEST）

```
大海星被 KO
  → 对手拿奖后手牌增加
  → EVOLVE Mega Froslass ex
  → Resentful Refrain (50 × 手牌数)
  → 或 Unfair Stamp 进一步压缩对手手牌
```

### 链 E — 控场（CONTROL）

```
prize_self < prize_opp（领先）
  → PLAY Meowth ex → Last-Ditch Catch 搜 Boss/Judge
  → Boss 指定目标 / Judge 重置手牌
```

---

## 7. 约束与禁忌（硬编码护栏）

| 规则 | 说明 |
|---|---|
| ACE SPEC 唯一 | Unfair Stamp (1080) 全牌组仅 1 张 ✅ |
| Fan Call 一次 | 第一回合只能用 1 次 |
| My-T1 后手牌 174 | **废牌**：不可 PLAY Bench；Ultra Ball 高优先弃（FR-1~4） |
| Risky Ruins 时机 | Bench 基础就位后再开；避免 Budew 30HP 被点死 |
| Judge 与 Froslass | **先 Resentful 再 Judge**；反序伤害大减 |
| Ignition 当回合弃 | 贴 Ignition 的回合结束能量消失；规划 One-shot |
| Poké Pad 限制 | 全牌库搜；不能搜 ex/V（Rule Box）；可搜 Staryu、Snorunt、Dudunsparce 等 |
| OPENING 禁 Lillie | 会洗掉 Hilda+Staryu+能量组合，断 T2 大海星 |
| Run Away Draw 时机 | T3 前三坑未就位时不循环；与 Jetting 攻击争 bench 位 |
| Judge 与 Froslass | 见上；Judge 是「对称过牌」不是纯增益 |
| Poffin HP 限制 | 只能搜 HP≤70 基础；Staryu(70) ✅ Snorunt(70) ✅ |
| 每回合 1 支援者 | `supporterPlayed` 为 true 后不再 PLAY 支援者 |
| 每回合 1 手动附能 | `energyAttached` 为 true 后 ATTACH 能量受限 |

---

## 8. 对手应对要点

| 对手类型 | 威胁 | 本卡组应对 |
|---|---|---|
| Walrein 控制 | 能量破坏、拖延 | 快速 T2 大海星；Budew 封 Item；Jetting 打后排 |
| 快速爆发 (foo_foo) | 抢在进化前 KO Staryu | Fan Call 多 bench；Risky Ruins 进场伤害 |
| Alakazam 等 ex 阵容 | 高伤 KO Mega | 愿增猿转伤；Dudunsparce ex Tenacious Tail 备用 |
| 手牌控制 | 压缩手牌 | 大雪妖女伤害降低 → 改 Jetting/Nebula 路线 |

---

## 9. Card ID 速查表

| 别名 | ID | 张数 |
|---|---|---:|
| staryu | 1030 | 2 |
| mega_starmie_ex | 1031 | 2 |
| snorunt | 860 | 3 |
| froslass | 104 | 1 |
| mega_froslass_ex | 861 | 2 |
| munkidori | 112 | 2 |
| fan_rotom | 174 | 1 |
| budew | 235 | 1 |
| meowth_ex | 1071 | 1 |
| dunsparce_a | 65 | 2 |
| dunsparce_b | 305 | 1 |
| dudunsparce | 66 | 2 |
| dudunsparce_ex | 306 | 1 |
| hilda | 1225 | 3 |
| lillie | 1227 | 4 |
| boss_orders | 1182 | 2 |
| judge | 1213 | 1 |
| crispin | 1198 | 1 |
| salvatore | 1189 | 1 |
| wally | 1229 | 1 |
| poffin | 1086 | 4 |
| ultra_ball | 1121 | 3 |
| poke_pad | 1152 | 4 |
| night_stretcher | 1097 | 2 |
| unfair_stamp | 1080 | 1 |
| switch | 1123 | 1 |
| risky_ruins | 1260 | 3 |
| water_energy | 3 | 4 |
| dark_energy | 7 | 2 |
| prism_energy | 16 | 1 |
| ignition_energy | 17 | 1 |

---

## 10. 与硬编码模块的对应关系（下一步）

| 知识模块 | 实现脚本 | 输入 |
|---|---|---|
| **Setup Active/Bench** | `setup_planner.py` | 起手 7 张手牌 Basic；`SETUP_*` context |
| 手牌/场面快照 | `hand_snapshot.py` | obs.hand + board + setup_archetype |
| Setup→My-T1→My-T2 路线 | `path_planner.py` | my_turn + gaps + setup_archetype |
| Fan Rotom 废牌 FR-1~4 | `hand_snapshot.py` + `starmie_pilot.py` | fan_rotom_dead + Ball 弃牌 |
| 过牌轴 DR-1~7 | `path_planner.py` + `phase_fsm.py` | phase + hand_size + prize |
| 阶段 FSM | `phase_fsm.py` | prizes + active id + setup 完成标志 |
| 硬规则栈 | `starmie_pilot.py` | phase + path + option |
| ML 软维 | `train_starmie.py` | 仅 4 维 |

**规划文档入口**：Setup 总览 → [phases/00_fsm_overview.md §1.1](../phases/00_fsm_overview.md)；细节 → [phases/01_opening.md §0–§3](../phases/01_opening.md)。
