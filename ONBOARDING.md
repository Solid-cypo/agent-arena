# AgentArena — 协作者快速上手指南

> **VPS**：Ubuntu 20.04 | Los Angeles | 1 GB RAM, 2 vCPU  
> **比赛**：[Kaggle PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)  
> **当前最高分**：761.4（Tea Party + tea_v4 + 28维 policy）  
> **更新**：2026-06-22

---

## 1. 快速连接环境

```bash
# Remote-SSH 连接 VPS（IP 在共享文档中）
# 工作区目录
cd /root/agent-arena

# 验证 cabt 环境可用
python3 -c "from cg.api import all_card_data; print(len(list(all_card_data())), 'cards OK')"
# 期望输出: 1267 cards OK

# 快速冒烟测试（4局，约10秒）
python3 run_arena.py play --games 4
```

---

## 2. 项目背景

这是一个 **Kaggle PTCG（宝可梦集换式卡牌）AI对战** 项目。

- **任务**：提交一个 `submission.tar.gz` 到 Kaggle，内含 `main.py` + `deck.csv` + `weights.json` + `cg/` 运行时
- **对战方式**：每次提交后，Kaggle 会自动让你的 Agent 与其他人的 Agent 打天梯，按 TrueSkill 评分
- **核心不是 LLM**：是一个确定性启发式 Agent（29 维加权打分函数）

---

## 3. 目录结构

```
agent-arena/
├── arena/                         # 核心对战引擎
│   ├── policy.py                  # ★ 29维 option_score 决策函数（主攻方向）
│   ├── simulator.py               # 本地自博弈循环
│   ├── marathon.py                # Top10 矩阵对战
│   ├── fsm_agent.py               # FSM-Math 三 Skill 接入层
│   └── deck.py                    # deck.csv 加载
│
├── .agent/
│   ├── docs/agent_design_spec.md  # FSM-Math v1.0 完整设计规格
│   └── skills/
│       ├── assessing_situations/  # Skill 1：三维局势评分 + 对手九宫格识别
│       ├── routing_states/        # Skill 2：FSM状态机 + 克制链 + 战术根
│       ├── evaluating_actions/    # Skill 3：ko_math + survival_math + tempo_planner
│       └── parsing_cards/         # 卡库工具（card_db.json）
│
├── cg/                            # cabt 引擎运行时（勿改）
│   ├── api.py                     # Observation 类 + Search API
│   ├── game.py                    # battle_start/select/finish
│   └── libcg.so                   # 游戏逻辑二进制
│
├── data/
│   ├── decks/                     # 实验卡组（future_lightning.csv, hops_control.csv）
│   ├── meta_decks/                # Top10 天梯卡组 CSV + index.json
│   ├── training/                  # 权重文件（best_weights_*.json）
│   └── marathon/                  # 矩阵对战结果
│
├── deck.csv                       # 当前提交使用的卡组（Tea Party #2）
├── run_arena.py                   # 本地单局/批量 eval
├── run_marathon.py                # Top10 矩阵对战
├── train_weights.py               # 进化搜索权重（主训练脚本）
├── export_meta_decks.py           # 从 Kaggle replay 提取 Top10 卡组
└── scripts/
    ├── package_submission.py      # 打包 submission.tar.gz
    └── auto_submit.py             # 训练完自动提交 Kaggle
```

---

## 4. 核心架构

### 决策层：29 维 Policy

```python
# arena/policy.py

# 17 维基础（动作形状，进化搜索学出）
attack=3.0, attach=2.0, evolve=1.7, play=1.2, ...

# 12 维局势感知（初始0，训练后偏离）
attach_urgency      # 能量缺口越大附能越紧迫
stagger_retreat     # ★ 错开送奖：ex被威胁时撤退（防止送2奖）
shield_bench        # 落后时主动放单奖宝可梦作盾牌
sprint_prize_2      # 最后2奖冲刺
boss_prize_path     # Boss's Orders 命中最优集火目标
cramorant_gate      # 古月鸟只在对手3-4奖窗口有效
attack_prize_path   # 攻击命中最短获胜路径的目标
...
```

每回合流程：
```
obs_dict
 → compute_situation(obs)   # 提取局势信号（1次/回合）
 → option_score × 29维      # 所有合法动作打分
 → 排序 → 返回最高分动作
```

### FSM-Math 三 Skill 层（辅助）

```
Skill 1 assessing_situations → SituationScores + OpponentProfile(Style/Speed/Root)
Skill 2 routing_states       → FSM 态(BURST/TEMPO/CONTROL) + PolicyWeights
Skill 3 evaluating_actions   → policy.py baseline + 数学加成
```

当前 FSM 通过 `arena/fsm_agent.py` 接入，`run_arena.py fsm` 子命令可测试。

---

## 5. 当前使用的卡组

### 主提交：Tea Party（#2 天梯）

```
deck.csv = The Debauchery Tea Party
核心: 878 Hop's Phantump × 4 + 879 Hop's Trevenant × 3
关键能力: Corner (90dmg + 锁退) + Horrifying Revenge (130dmg 反杀)
三重加成: Choice Band(+30) + Snorlax Extra Helpings(+30) + Postwick(+30) = 最高 220dmg
```

### 实验卡组：Hops Control Premium

```
data/decks/hops_control.csv
在 Tea Party 基础上加入:
  310 Hop's Dubwool   — 进化时等效 Boss's Orders
  272 Lillie's Clefairy ex — 暗属宝可梦弱点变 ×2
  343 Shaymin         — 后排无规则框宝可梦免疫攻击伤害
  1209 Ruffian        — 移除对手道具 + 特殊能量
```

---

## 6. 权重文件说明

| 文件 | 说明 | 状态 |
|------|------|------|
| `best_weights_tea_v2.json` | Tea Party 基线（mirror + 多对手）| 稳定 |
| `best_weights_tea_v4.json` | ★ Tea Party 当前最佳（+Alakazam +foo +gray）| **推荐** |
| `best_weights_hops_v1.json` | Hops Control 专项（从 v4 初始化）| 可用 |
| `best_weights_28dim_tea.json` | Tea Party × 29维（训练中）| 进行中 |
| `best_weights_28dim_hops.json` | Hops Control × 29维（训练中）| 进行中 |

---

## 7. 常用命令

```bash
# 单局测试（4局，约5秒）
python3 run_arena.py play --games 4

# 对比 A 卡组 vs B 卡组（40局，约30秒）
python3 run_arena.py eval --games 40 \
  --deck-a deck.csv \
  --deck-b data/meta_decks/decks/01_trusthub-hiroingk.csv \
  --weights data/training/best_weights_tea_v4.json

# FSM agent 测试（10局）
python3 run_arena.py fsm --games 10 \
  --weights data/training/best_weights_tea_v4.json

# 全 BDD 测试（约1秒）
python3 .agent/skills/assessing_situations/scripts/test_assessing_situations.py
python3 .agent/skills/routing_states/scripts/test_routing_states.py
python3 .agent/skills/evaluating_actions/scripts/test_evaluating_actions.py

# 训练权重（示例：Tea Party 对阵 Alakazam）
python3 train_weights.py \
  --matchup "mirror:deck.csv:deck.csv:0.5" \
  --matchup "vs_alak:deck.csv:data/meta_decks/decks/01_trusthub-hiroingk.csv:1.5" \
  --init-weights data/training/best_weights_tea_v4.json \
  --games 40 --generations 15 --population 10 \
  --weights-out data/training/my_weights.json

# 打包并提交 Kaggle
python3 scripts/package_submission.py \
  --weights data/training/best_weights_tea_v4.json \
  --deck deck.csv
kaggle competitions submit pokemon-tcg-ai-battle -f submission/submission.tar.gz -m "描述"

# 查 Kaggle 提交状态
kaggle competitions submissions pokemon-tcg-ai-battle
```

---

## 8. 后台任务（当前正在运行）

```bash
# 查看训练进度
tail -8 data/training/train_28dim_v1.log     # Tea Party 29维训练
tail -8 data/training/train_28dim_hops.log   # Hops Control 29维训练

# 两个进程各占一个 CPU 核，预计 3-4 小时完成
ps aux | grep train_weights | grep python3
```

---

## 9. 关键理论参考

| 文件 | 内容 |
|------|------|
| `references/ptcg_dimension_theory.md` | 三维理论（S_hand/S_board/S_turn）+ 九宫格风格矩阵 |
| `.agent/docs/agent_design_spec.md` | FSM-Math v1.0 完整设计规格（含数学公式）|
| `data/meta_decks/meta_decks_top10.md` | Top10 天梯卡组完整卡表 |

**九宫格核心：**
- **爆发**（Burst）：根=场面，快速充能攻击  
- **运营**（Tempo）：根=手牌，过牌引擎转化场面（如胡地/嘟嘟利）
- **控手**（Control）：根=多维，四维综合优势（如 Tea Party / Hops Control）

**克制链**：爆发克控手 → 控手克运营 → 运营克爆发

---

## 10. Kaggle 提交历史

| 分数 | 卡组 | 权重 | 备注 |
|------|------|------|------|
| **761.4** | Tea Party | tea_v4 + 28维 | 当前最高 |
| 712.6 | Hops Control | hops_v1 | 新卡组首次成功 |
| 659.2 | Tea Party | tea_v4 | 旧版 17维 |
| 612.7 | Tea Party | v1（早期）| — |

---

## 11. BDD 测试覆盖

目前共 63 个 BDD 测试，全部通过：
- Skill 1（assessing）：17 个用例
- Skill 2（routing）：16 个用例  
- Skill 3（evaluating）：30 个用例

---

## 12. 注意事项

1. **`deck.csv` 注释行**：以 `#` 开头的行都会被跳过，放心写注释
2. **ACE SPEC 规则**：每套牌最多 1 张 ACE SPEC 卡，违规会导致 Kaggle ERROR
3. **`cg/` 目录勿改**：这是官方游戏引擎二进制，改了会崩
4. **VPS 内存紧张**：1GB 总内存，不要同时跑 3 个以上训练进程
5. **`submission.tar.gz` 需含 `cg/`**：否则 Kaggle 报 `No module named 'cg'`
6. **Kaggle 分数波动正常**：TrueSkill 天梯，同一提交分数会随对战更新浮动 ±100

---

## 13. Git 提交历史摘要

```
83a21f0  Fix: read_deck_csv 跳过注释行
8b1d570  Policy 扩展到 29 维（+12 局势感知特征）
b89eebf  对手识别与九宫格理论对齐（控手根=多維）
117cd0d  三维理论 + 九宫格应用于对手模式识别
5df00c6  对手 profiler 加入 3 回合行为信号融合
fd284d8  tempo_planner + Cramorant 拦截 + deck-out 保护
9bd9cf6  FSM-Math v1.0 架构 + Hops Control 新卡组
4471528  换 Tea Party 卡组 + Top10 矩阵 + 提交脚手架
e348a3b  初始化工作区 + 权重搜索训练
```
