# AgentArena — Agent 工作指南

> Kaggle [PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)（`cabt` 环境）的对战 AI。
> 主线：**Starmie+Froslass 卡组 Pilot**（Layer1 硬规则 + Layer2 软维）+ 理论建模（FSM）。
> 环境：Ubuntu VPS（洛杉矶），通过 Cursor Remote-SSH 开发。

---

## 当前状态（每次会话结束时更新此节）

- **更新日期**：2026-08-03
- **线上提交**：**`55209165`**（PENDING）— plug must-attack leaks（Poffin/861 贴水后支援/Retreat；ghost prep 修复）
- **对照**：`55202093` 公开分 **455.7**（公局约 41%；有油空转仍漏）｜更早 `55196958` ~421
- **卡组**：`data/decks/starmie_froslass.csv` — 3×海星星、无 306、5 水 + 3 恶
- **本包内容**：
  - 从 `submission_starmie.tar.gz` **恢复**被清盘的 Must-attack/Fuel/861 包（commit `f07e541`）
  - **Must-attack 堵漏**：早期 closeout 闸（先于 Alak/acquire/ignition-retreat）；ghost `required_before_attack` 不挡 Jetting；禁有油 Poffin/支援/Retreat
  - 保留：有效 Boss、Fuel gate、861 控手、AcquirePlan、C2b
- **本地回归**：
  - 单测：Pilot 61/61｜TurnPlan 26/26｜Combat 5/5｜Draw 9/9｜Alak 7/7
  - BC 4×20：**71.25%**（Alak 65%｜Lucario 60%｜DP 95%｜Marnie 65%）；`ready_mega_no_attack=0`
  - 对照堵漏前 BC 58.8%；产物 `logs/combat_eval_must_attack_plug_bc_4x20/`
  - 线上复盘：`data/kaggle_episodes/review_must_attack_55202093/`
- **下一刀决策闸**：公开分回来后若空转消失 → **861 成型**；若仍漏 → 再盯回放新路径
- **OPENING KPI**（历史）：CP1 78.8%｜Goal@T2 35.8%｜Goal@T5 58.0%
- **磁盘**：约 88%；改规则务必立刻 commit（本次清盘教训）
- **指标文档**：`references/rulebook/METRICS-CombatV1_20260801.md`｜`TURN_PLAN_POLICY_20260802.md`｜`ULTRA_BALL_POLICY_20260801.md`

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
