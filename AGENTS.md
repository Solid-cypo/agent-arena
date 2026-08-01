# AgentArena — Agent 工作指南

> Kaggle [PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)（`cabt` 环境）的对战 AI。
> 主线：**Starmie+Froslass 卡组 Pilot**（Layer1 硬规则 + Layer2 软维）+ 理论建模（FSM）。
> 环境：Ubuntu VPS（洛杉矶），通过 Cursor Remote-SSH 开发。

---

## 当前状态（每次会话结束时更新此节）

- **更新日期**：2026-08-01（晚）
- **分支**：`master`＝`origin/master` @ `4941e0e`（已 push；含正确卡组 5W+3D、无棱镜/引火）
- **卡组**：`data/decks/starmie_froslass.csv` — 3×海星星、无 306、5 水 + 3 恶（事故后从 combat_v1 包恢复并入库）
- **近期工作**：
  - Combat v1 → BF1 → DP-Boost → S 策略（MEGA 后 DP 优先；861 仅保险/富余 A/B）
  - 卡组回滚事故修复；deck-fix 双版重交 Kaggle（收紧 55161062 / 富余 55161069）
  - 全战专家审阅日志管线：`play_game(collect_engine_logs)` + `scripts/combat_log_renderer.py` + `export_combat_review_pack.py`；样包 `logs/combat_review_91000/`
  - 行为续修（**未 commit**）：攻击置最后；对手空手时雪女切回海星；非胡地打手水能优先于愿增猿恶能
- **本地压力 KPI（正确卡组复核）**：T-C 启发式 ~93–95%；T-C-BC ~68–75%（随 861 窗口松紧波动）；`dp_rate` ~25–32%
- **OPENING KPI**（历史，500 seed）：CP1 78.8%｜Goal@T2 35.8%｜Goal@T5 58.0%｜勿用 Walrein 胜率当主 KPI
- **工作区**：行为续修 + 审阅日志管线已入库（本提交）；`logs/` 与大量 opening review batch 仍未跟踪（体积大，按需另存）
- **磁盘**：曾 95% 满→清理至约 86%；回放已压成 `data/kaggle_episodes/*.tar.gz`；改卡/规则务必立刻 commit，防再被 checkout 冲掉
- **指标文档**：`references/rulebook/METRICS-CombatV1_20260801.md`

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
python3 tests/test_starmie_pilot.py                    # 期望 54/54
python3 .agent/skills/piloting_starmie_froslass/scripts/simulate_opening.py --batch 10 --seed 42   # 期望 9/10
python3 run_arena.py eval --games 20                   # 本地对战
```

完整命令（提交打包、审计、训练）见 `ONBOARDING.md` 第 6 节。

## 会话协议（控制 token 消耗）

- **一个任务一个对话**；任务结束时把结论落盘（更新本文件"当前状态"节或相关文档），不要依赖聊天历史传递进度。
- 探索/调研类工作交给 explore 子代理，主对话只接收结论。
- 大日志、审计输出写入 `logs/`，聊天中只引用路径和摘要。
