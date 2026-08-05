# AgentArena — Agent 工作指南

> Kaggle [PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)（`cabt` 环境）的对战 AI。
> 主线：**Starmie+Froslass 卡组 Pilot**（Layer1 硬规则 + Layer2 软维）+ 理论建模（FSM）。
> 环境：Ubuntu VPS（洛杉矶），通过 Cursor Remote-SSH 开发。

---

## 当前状态（每次会话结束时更新此节）

- **更新日期**：2026-08-06
- **线上提交**：仍以 `55209165` / must-attack 包为基线；本机已叠 **Wave D–G + Wave H 软收口**
- **对照**：baseline `/tmp/baseline_55202093_f07e541`（≈ `f07e541`）
- **卡组**：`data/decks/starmie_froslass.csv` — 3×海星星、无 306、5 水 + 3 恶
- **本包内容（Wave H，叠在 Wave G 上）**：
  - H1：`need_base` 时 Lillie 进入 `acquire.sources`；先手 PATH Lillie/Poffin/Pad/UB/Staryu；Active 海星+水且可进化时禁 Water Gun
  - H2：先手 demote Meowth（保留 GS My-T1 含羞苞窗与 Wave G 侧基础门）
  - H3：替补 **fueled** Mega → PATH Switch/Retreat/TO_ACTIVE（**不做** ATTACK/END 硬 demote）
  - H0：仍靠 G0/`attack_required`；对「错前场+未 fueled Mega」的全局禁攻会砸后手 Itchy，本波不做
  - **明确拒绝**：禁空过 END / 禁无意义 Switch / 未 fueled 也抬座 — 试验中 seat B 崩到 ~36–42%
- **本地回归**：
  - 单测：`tests/test_wave_h_seat_a.py` + wave_g + budew → **21 passed**（wave_h 子集）
  - H2H 注意：同 seed140000 对局级复现率约 **48%**（Wave G 原跑 51.5% vs 复测 43.5%）；单次 n=200 不可作硬闸
  - 试验峰（硬 demote 版，后手不可复现）：`logs/h2h_audit_waveH_min_run.log` → 总 **51.5%** / A **57%** / B **46%**
  - 软版验收（HASHSEED=0）：H2H `logs/h2h_audit_waveH_seat_a_n200_s140000/` → 总 **48%** / A **52%** / B **44%**（对照同条件 Wave G 复测约 43.5%/A54/B33）；`miss_lillie` **3**（Wave G 原 15）
  - BC 软版：`logs/combat_eval_waveH_bc_4x20/` → ~**64%**；`ready_mega_no_attack=0`；`base_attack_with_ready_mega`≈2（未清零）
- **下一刀**：先修 H2H 确定性（或 n 加倍）再压 seat B / 必攻泄漏；勿再上全局 END/ATTACK demote；含羞苞让路政策不动
- **磁盘**：改规则务必立刻 commit
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
