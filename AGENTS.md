# AgentArena — Agent 工作指南

> Kaggle [PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)（`cabt` 环境）的对战 AI。
> 主线：**Starmie+Froslass 卡组 Pilot**（Layer1 硬规则 + Layer2 软维）+ 理论建模（FSM）。
> 环境：Ubuntu VPS（洛杉矶），通过 Cursor Remote-SSH 开发。

---

## 当前状态（每次会话结束时更新此节）

- **更新日期**：2026-08-02（夜）
- **分支**：工作区有**未 commit** 的 TurnPlan 规划层、规则瘦身、测试与遥测改动
- **卡组**：`data/decks/starmie_froslass.csv` — 3×海星星、无 306、5 水 + 3 恶
- **近期工作**：
  - 新增统一 `TurnFacts / TurnGap / TurnPlan`，由 `AcquirePlan / CombatPlan / DrawPlan` 接管检索、战斗和抽牌门
  - Mega 必攻、普通底座攻击禁令、DoubleKO（Adrena→Boss→Jetting→rider）已统一进入 CombatPlan
  - 高级球改为缺口驱动 UB-1..5；live/opening 共用动态 `discard_value`，夜之伸展器只回收唯一缺口
  - 861 预计两奖门、土龙 bench budget、结构化坏手 Run Away Draw 已落地
  - DP 目标已简化为“带恶能愿增猿 + 伤害生成器”；生成器可为雪妖女 104 或危险废墟
  - 删除旧 `_synergy_search_bonus`、固定弃牌/担架表、全局 DP defer 和 legacy opening route
  - **继续保留回退 C2b**：不要求每回合消耗支援者或贴能
- **最终回归**：
  - 单测：Pilot 56/56｜TurnPlan 16/16｜Draw axis 9/9｜Opening 20/20
  - T-C 启发式 5×60：283/300 = 94.3%；T-C-BC 4×60：169/240 = 70.4%
  - 简化 DP 12 局审阅：8/12
  - `ready_mega_no_attack=0`、`base_attack_with_ready_mega=0`、`bad_ultra_ball_discard=0`
  - 检索目标一致率：T-C 97.4%，T-C-BC 98.1%
  - 简化 `dp_rate`：29.7% / 28.8%，达到 25% 门槛；伤害生成器上线率 69.7% / 72.1%
- **OPENING KPI**（历史，500 seed）：CP1 78.8%｜Goal@T2 35.8%｜Goal@T5 58.0%｜勿用 Walrein 胜率当主 KPI
- **延期 matchup**：铝钢桥龙专项、对手愿增猿专项、matchup 级 Boss 威胁表
- **工作区**：TurnPlan 改动未入库；`logs/` 大体积未跟踪；skill↔submission 已对齐
- **磁盘**：约 86%；改卡/规则务必立刻 commit
- **指标文档**：`references/rulebook/METRICS-CombatV1_20260801.md`｜`TURN_PLAN_POLICY_20260802.md`｜`ULTRA_BALL_POLICY_20260801.md`｜专家讨论稿：`ULTRA_BALL_EXPERT_BRIEF_20260802.md`

---

## 文档地图（按需 @ 引用，不要一次性全部加载）

| 文档 | 内容 |
|---|---|
| `ONBOARDING.md` | 快速上手、目录结构、全部常用命令 |
| `references/PROJECT_LAYOUT.md` | 项目布局详情 |
| `references/ptcg_dimension_theory.md` | 理论建模（28 维） |
| `.agent/skills/piloting_starmie_froslass/references/phases/00–04` | 海星 Phase 文档链 |
| `references/HANDOFF_opening_pruning.md` | OPENING 交接文档 |
| `.cursorrules` | Agent Skills 编写规范（SKILL.md 格式、YAML 触发器、五大守则） |

## 目录速览

- `arena/` — simulator、policy、fsm_agent
- `cg/` — **官方引擎，禁止修改**
- `.agent/skills/` — 技能（piloting / assessing / routing / evaluating / parsing）
- `submission_starmie/` — Kaggle 提交包
- `data/decks/` — `starmie_froslass.csv`（己方）、`walrein_control.csv`（默认对手）
- `tests/`、`scripts/`、`logs/`

## 硬性规则

1. **`cg/` 勿改**（官方引擎）。
2. 改动 `piloting_starmie_froslass/scripts/` 后**必须**运行 `python3 scripts/sync_starmie_submission.py`。
3. `simulate_opening.py` 不得 import `starmie_pilot`；全对局 OPENING 走 `opening_bridge.py`。
4. HARVEST 阶段禁 Judge（Resentful 前）；CONTROL 阶段 Judge 仅在非必攻窗口。
5. 卡组 CSV 中 `#` 开头为注释行。
6. 禁止硬编码密钥/端口，一律走环境变量（见 `.env.example`）。
7. 外科手术式修改：只改需要的行，保持既有风格。
8. 不引入重型 RL 库（SB3/Ray）；用原生 PyTorch 或 torch-free 实现。
9. 新技能遵循 `.cursorrules` 中的 Google Agent Skills 规范。

## 快速验证

```bash
python3 -c "from cg.api import all_card_data; print(len(list(all_card_data())), 'cards OK')"
python3 tests/test_starmie_pilot.py                    # 期望 56/56
python3 .agent/skills/piloting_starmie_froslass/scripts/simulate_opening.py --batch 10 --seed 42   # 期望 9/10
python3 run_arena.py eval --games 20                   # 本地对战
```

完整命令（提交打包、审计、训练）见 `ONBOARDING.md` 第 6 节。

## 会话协议（控制 token 消耗）

- **一个任务一个对话**；任务结束时把结论落盘（更新本文件"当前状态"节或相关文档），不要依赖聊天历史传递进度。
- 探索/调研类工作交给 explore 子代理，主对话只接收结论。
- 大日志、审计输出写入 `logs/`，聊天中只引用路径和摘要。
