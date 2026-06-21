# PTCG AI Agent 开发设计规格 (FSM-Math v1.0.0)

> **版本**: 1.0.0  
> **环境**: Kaggle `cabt` Engine [1.2.8] | Remote Ubuntu VPS (LA Node)  
> **理论锚点**: `references/ptcg_dimension_theory.md`  
> **架构**: HFSM + 三维局势量化 + 确定性前向搜索 (Search API)

---

## 1. 核心数据契约

所有 Skill 之间**只传递**这两个 dataclass，不传 obs 原始 dict。

```python
@dataclass(frozen=True)
class SituationScores:
    # 三维原始分（归一化 0-100）
    s_hand: float          # 手牌维度
    s_board: float         # 场面/能量维度
    s_turn: float          # = TC_opp - TC_me，正值代表我方更快

    # 轮次时钟（理论第三部分）
    tc_me: float           # 己方最少终结回合数估算
    tc_opp: float          # 对手最少终结回合数估算
    prize_left_self: int
    prize_left_opp: int

    # 差分
    board_readiness: float # ∈ [0,1]，主力打手能量就绪度
    s_hand_diff: float     # self - opp 手牌数差
    s_board_diff: float    # self - opp 场面分差


@dataclass(frozen=True)
class OpponentProfile:
    style: str             # "Burst" | "Tempo" | "Control" | "Unknown"
    speed: str             # "Fast" | "Medium" | "Slow" | "Unknown"
    signature: str         # meta_signatures.json 匹配键名
    confidence: float      # ∈ [0, 1]


@dataclass(frozen=True)
class PolicyWeights:
    w_turn: float
    w_board: float
    w_hand: float
```

---

## 2. 三 Skill 架构与数据流

```
obs_dict
    │
    ▼
┌──────────────────────────────────────────────┐
│ Skill 1: assessing_situations                │
│  situation_assessor.py  → SituationScores    │
│  opponent_profiler.py   → OpponentProfile    │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│ Skill 2: routing_states                      │
│  state_router.py  → active_state (FSM)       │
│                   → PolicyWeights            │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│ Skill 3: evaluating_actions                  │
│  action_evaluator.py  → action_index         │
│  ko_math.py / survival_math.py               │
└──────────────────────────────────────────────┘
```

**arena/policy.py 保留为 fallback**，当任意 Skill 抛出异常时使用。

---

## 3. Skill 1 规格：assessing_situations

### 3.1 文件布局

```
.agent/skills/assessing_situations/
├── SKILL.md
├── references/
│   ├── meta_signatures.json      # Top10 卡组指纹（自动生成）
│   └── card_tactic_weights.json  # 关键卡 ID 战术系数
└── scripts/
    ├── situation_assessor.py
    └── opponent_profiler.py
```

### 3.2 $S_{\text{hand}}$ 计算（手牌维度）

$$S_{\text{hand}} = N_{\text{hand}} + \sum_{c \in \text{Hand}} \text{DrawPotential}(c)$$

`DrawPotential(c)` 来自 `card_tactic_weights.json["draw_potential"]`，例：
- Dudunsparce (66): 2.0（过牌引擎）
- Buddy-Buddy Poffin (1086): 1.5（检索基础宝可梦）
- Rare Candy (1079): 1.2

### 3.3 $S_{\text{board}}$ 计算（场面/能量维度）

$$S_{\text{board}} = \sum_{p \in \text{MyBoard}} \frac{\text{HP}(p)}{\text{MaxHP}(p)} \times \text{MaxDmg}(p) \times \min\!\left(1, \frac{E_{\text{attached}}(p)}{E_{\text{required}}(p)}\right)$$

- 弱点目标（场上对手宝可梦存在弱点匹配）额外 × 2.0
- Enhanced Hammer (1081) 动作可用时，若对手为 Control，附加常数 `HAMMER_VS_CONTROL_BONUS = 50.0`

### 3.4 $S_{\text{turn}}$ 与轮次时钟

$$TC_{\text{me}} = \left\lceil \frac{\sum \text{OppPrizeHP}}{\text{MyMaxDmg}} \right\rceil$$

$$TC_{\text{opp}} = \left\lceil \frac{\sum \text{MyPrizeHP}}{\text{OppMaxDmg}} \right\rceil$$

$$S_{\text{turn}} = TC_{\text{opp}} - TC_{\text{me}}$$

正值代表我方时钟更快（优势），用于 FSM BURST 触发条件。

### 3.5 OpponentProfile 指纹匹配

1. 提取对手已知手牌/场上宝可梦 card ID 集合
2. 与 `meta_signatures.json` 每条 `fingerprint_ids` 取 Jaccard 相似度
3. 最高匹配 confidence ≥ 0.3 则返回匹配签名；否则 `style="Unknown"`

---

## 4. Skill 2 规格：routing_states

### 4.1 FSM 状态

| 状态 | 触发条件 | 基础权重 |
|------|----------|----------|
| `RUSHING_PRIZES` | prize_left_self ≤ 2 且 board_readiness ≥ 1.0 | w_turn=0.90, w_board=0.08, w_hand=0.02 |
| `SETTING_UP_BOARD` | 默认基准 | w_turn=0.20, w_board=0.60, w_hand=0.20 |
| `DENYING_RESOURCES` | prize_left_opp ≤ 2 且 opp 领先 ≥ 2 奖；或对手 Control | w_turn=0.05, w_board=0.35, w_hand=0.60 |

### 4.2 克制链修正（理论第二部分）

| 对手 Style | 理论克制方向 | 己方偏置 |
|------------|--------------|----------|
| Control | 运营克控手 → 侧面工具 | 切 SETTING_UP_BOARD；提高 w_board |
| Burst | 控手克爆发 | 切 DENYING_RESOURCES；提高 w_hand |
| Tempo | 爆发克运营 | 切 RUSHING_PRIZES；提高 w_turn |

### 4.3 手牌劣势覆盖

`s_hand_diff < -3`（落后 3 张以上）→ 强制提升 `w_hand += 0.3`（上限 0.80）

---

## 5. Skill 3 规格：evaluating_actions

### 5.1 主循环

对每个合法 option：
1. `search_begin` → 传入对手预测 deck/prize/hand（来自 OpponentProfile）
2. `search_step` 前向一步 → 得 `SearchState`
3. 提取 `SituationScores` 增量
4. 叠加 `ko_math` / `survival_math` / Iono 修正
5. 加权求和取最大

**Search 分支预算**：
- 每步最多模拟 K=8 个候选 option
- 每步调用 `search_release` 回收内存
- 单步超时 200ms，超时退回 `policy.py` fallback

### 5.2 关键卡 ID 显式分支

```python
# 对手 Control + PLAY 1081 → 反控加成
if opp_profile.style == "Control" and played_card_id == 1081:
    S_board += HAMMER_VS_CONTROL_BONUS  # 50.0

# 落后时 Iono (1227) 加权
if played_card_id == 1227:
    iono_mult = 1.0 + 2.5 * max(0, prize_taken_opp - prize_taken_self) / 6
    S_hand *= iono_mult
```

---

## 6. 接入层：arena/fsm_agent.py（Phase 4）

```python
def make_fsm_agent(deck, weights_fallback):
    def agent(obs_dict):
        try:
            scores = assess(obs_dict)
            profile = profile_opponent(obs_dict)
            state, pw = route(scores, profile)
            return evaluate(obs_dict, state, pw, scores, profile)
        except Exception:
            return policy.choose_options(obs_dict, deck, weights_fallback)
    return agent
```

提交包 `submission/main.py` 最终内联此逻辑，`tar` 结构不变。

---

## 7. 未来拓展（Phase 2+，不阻塞 v1）

- **A2UI v0.9**：`SituationScores` 序列化为 JSON 帧，VPS 本地可视化
- **MCP Server**：`stdio` JSON-RPC 包装 `cg.game`，隔离推理层
- 密钥严格走 `os.environ`，禁止明文写入任何文件
