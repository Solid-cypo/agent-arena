# AgentArena — Agent 工作指南

> Kaggle [PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)（`cabt` 环境）的对战 AI。
> 主线：**Starmie+Froslass 卡组 Pilot**（Layer1 硬规则 + Layer2 软维）+ 理论建模（FSM）。
> 开发：本机 Windows（`D:\Agent\agent-arena`）写代码 + 小测；重测：Ubuntu VPS（洛杉矶，`kag-vps:/root/agent-arena`）。
> 同步：本机 commit 后跑 `scripts/sync_to_vps.ps1`（git bundle → VPS）；GitHub 仍由 VPS `git push origin` 出口。

---

## 当前状态（每次会话结束时更新此节）

- **更新日期**：2026-08-16（比赛末日）
- **现役最佳本地档（回滚用）**：ClosableNsRockInn [`55517032`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) **549.8** → [`data/restore_peaks/closableNsRockInn_55517032/`](data/restore_peaks/closableNsRockInn_55517032/) + tar [`data/restore_peaks/submission_starmie_closableNsRockInn_55517032.tar.gz`](data/restore_peaks/submission_starmie_closableNsRockInn_55517032.tar.gz)
- **IgnitionNebula+LilliePreserve 已交 Kaggle [`55538325`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) / [`55538332`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（PENDING）：Deck −1 废墟 +1 引火；星云窗希尔达/贴能；引火撤退油仅万不得已；LilliePreserve（93425582）。对照 Closable **549.8**。本地档 tar [`data/restore_peaks/submission_starmie_ignitionNebula_55538325.tar.gz`](data/restore_peaks/submission_starmie_ignitionNebula_55538325.tar.gz)
- **LastDayAutopsy 已交 Kaggle [`55528724`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **496.0**）：叠在 Closable 上 — MeowthSeat / DryCrispin / Lillie>Judge / OpeningJudgeYield / 禁第二只干 Mega 等。**撤回 EmptyBenchJetting**（55523046 549→456）。
- **Closable861+NsWater861+RockInn 已交 Kaggle [`55517032`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **549.8**）：公局约 15/29≈52%。相对 LeakFix 55488542（**528.2**）仍领先。EmptyBench [`55523046`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) **456.5** 已证伪勿再交。
- **LeakFix Dry861 已交 Kaggle [`55488542`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **528.2**）：公局曾记 12/27=44.4%。fade [`data/kaggle_episodes/review_LeakFixDry861_55488542/FADE_ANALYSIS.md`](data/kaggle_episodes/review_LeakFixDry861_55488542/FADE_ANALYSIS.md)。
- **SecondAtk+Adrena+UbGhost 已交 Kaggle [`55473608`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **478.2**，曾 505.4/491.7）：公局 **9/25=36%**。861 开火 **6/10**；路卡 **0/6**（3 局干 861 进前场）。fade [`data/kaggle_episodes/review_SecondAtk_55473608/FADE_ANALYSIS.md`](data/kaggle_episodes/review_SecondAtk_55473608/FADE_ANALYSIS.md)
- **FroslassCont 已交 Kaggle [`55462041`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **466.5**）：公局 **12/27=44%**；Mega 89%；861 上场 8/27=30%、开火仅 **1/8**；进 66 = 0。未超过同血统 DpStall [`55445134`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) **526.5**。fade [`data/kaggle_episodes/review_FroslassCont_55462041/FADE_ANALYSIS.md`](data/kaggle_episodes/review_FroslassCont_55462041/FADE_ANALYSIS.md)
- **CutDraw66Ship 已交 Kaggle [`55455986`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **453.8**，曾记 383.1）：FroslassCut + Draw66Closeout/AfterEvolve + DkAdrena + dryMegaBan，叠在 DpStallDraw 栈上。软地板全 PASS — [`logs/h2h_audit_cutDraw66_n200/GATE.md`](logs/h2h_audit_cutDraw66_n200/GATE.md)
- **DpStallDraw-V2.1 已交 Kaggle [`55445134`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **526.5**，曾记 508.7）：喷水前莉莉艾/裁判/希尔达。闸 [`logs/h2h_audit_midConvert_n200/GATE.md`](logs/h2h_audit_midConvert_n200/GATE.md)
- **Field6Ship explore 已交 Kaggle [`55433727`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **465.2**）：[`logs/h2h_audit_field6Ship_n200/GATE.md`](logs/h2h_audit_field6Ship_n200/GATE.md) — Opening mean **78.7%** / B·fm mean **63.7%** / dark mean 50.4%（软地板 dark FAIL，产品覆盖探针）
- **下一步**：八点刷新后盯 Ignition 包公局；分掉则回滚 Closable restore peak。deadline **2026-08-16 23:59 UTC**。**禁止** CombatClose / surplus861 / DP 宽序 / Boss→Jetting / RunAway 宽 PATH / SetupActive / HildaDig / EmptyBench。
- **工作流**：日常开发在本机；VPS 专跑 h2h/marathon/Kaggle。同步：`pwsh scripts/sync_to_vps.ps1`（可选 `-PushOrigin`、`-RemoteCmd "..."`）
- **本机环境**：Python 3.10 venv（`.venv`）；冒烟 ` .\.venv\Scripts\python.exe -m pytest tests/test_starmie_pilot.py -q`
- **线上权威峰**：[`55386951`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) **P0 CrispinWater** → publicScore **610.4**；本地档 [`data/restore_peaks/p0CrispinWater_55386951/`](data/restore_peaks/p0CrispinWater_55386951/)；git `ef246cc`（含 handoff WIP）
- **P0（已冻结）**：G0 [`logs/h2h_audit_p0CrispinWater_n200/GATE.md`](logs/h2h_audit_p0CrispinWater_n200/GATE.md) WR **58.5%** / B**61** / Opening **80.5%**；公局初审 n=3 WR2/3、零 Jetting=0 → [`logs/diagnose_p0CrispinWater_55386951/REVIEW.md`](logs/diagnose_p0CrispinWater_55386951/REVIEW.md)
- **P1 fade（已修）**：`(attackId,serial)` 去重；旧包 55381818 真零 Jetting 1/12
- **P2 Boss→Jetting（HOLD）**：[`logs/diagnose_p2_boss_jetting/HOLD.md`](logs/diagnose_p2_boss_jetting/HOLD.md)
- **下一刀**：等 Ignition 公局≥8 再 SOP-D；勿重开中盘 DP/CombatClose-V1/V2；MidOps 已 SHIP 勿叠 RunAway-V1 宽 PATH
- **本地 Opening 闸**（vs `ops_fireform_55115028`，n=200 seed82000，`OPENING_HANDOFF=0`，TURN_START 去重）：硬指标 **81.5%**（先手≤T3 **86%** / 后手≤T2 **77%**）· WR **53.5%** · 三漏归零（`logs/h2h_audit_engineSeats_n200/`）
- **中盘 CombatClose-V2（证伪已回滚）**：Adrena→Boss + first-prep PATH（无锁）→ prep_ok 54.8%→**42.4%**、负局无有效 Boss↑；Opening 合计持 80.5%；见 [`logs/diagnose_combat_v2/AUTOPSY.md`](logs/diagnose_combat_v2/AUTOPSY.md) · [`logs/h2h_audit_combatV2_n200/GATE.md`](logs/h2h_audit_combatV2_n200/GATE.md)。**已证伪**：无锁窄 PATH 亦不足以抬双穿序
- **MidOps-V1（SHIP）**：第二打手 matchup（控场/烈箭/铝钢禁 861；路卡开窗）+ OL-E2 厚手铺场 + 窄 post-Mega 66 抽；G0 [`logs/h2h_audit_midOps_n200/GATE.md`](logs/h2h_audit_midOps_n200/GATE.md) Opening 合计 **75.5%** / 先≤T3 **81%** / B**54** / WR 56.5%
- **中盘 CombatClose-V1（证伪已回滚）**：露面+锁 ADRENA/BOSS/DISPATCH → prep_ok 31→29%、Opening 合计 81.5→**77.5%**；见 [`logs/diagnose_combat_expert_gap/DIAGNOSE.md`](logs/diagnose_combat_expert_gap/DIAGNOSE.md) · [`logs/h2h_audit_combatClose_n200/GATE.md`](logs/h2h_audit_combatClose_n200/GATE.md)。**已证伪**：仅靠 primary_step 锁修双穿序
- **对照**：历史最佳本地峰 `data/restore_peaks/ops_fireform_55115028`；H2H 权威仍记 Wave I n=400（`logs/h2h_audit_waveI_seat_b/` → **50.5% / A52 / B49**）
- **卡组（工作区 Ignition）**：`data/decks/starmie_froslass.csv` — 废墟×3 · 水×5 · 恶×3 · 引火×1 · 海星底座×2；Closable 回滚档仍为废墟×4、无引火
- **OPENING 座位预设（采用）**：打手底座×1 · 土龙×2 · 愿增猿×1 · 机动×1；填充不得压过贴水/底座；`opening_bench.py` 已纳入 `sync_starmie_submission.py`
- **本包内容（Wave U，叠在 Wave I+L 上；修线上 90447438/90443511/90444305 簇）**：
  - U1：底座海星水枪硬禁（`_ATTACH_ILLEGAL`）；可进化节节在 MAKE_ATTACKER 压过 END
  - U2：UB 禁打时硬非法；手持 Mega 弃牌保护；`UB-forced-burn`（打出后不足 2 张非 Mega 弃牌）
  - U3：双海星 / Active 不可进化 → 禁唯一水贴 Active，优先 Bench
  - U4：场上无 Mega 时夜伸优先捞弃牌 Mega（场上已有 Mega 缺油仍先水）
  - U5：先手 My-T1 Active 含羞苞禁撤退/交替上底座
  - 继承 Wave L：Boss PATH / closing gust / 夜伸捞 Boss；Wave I seat B / evolve / dispatch
- **本地回归（Wave U）**：
  - 单测：`tests/test_wave_u_online_leaks.py`（9）+ wave_h/i/l + turn_planner 通过；`sync_starmie_submission.py` 已同步
  - 三局离线形状抽检：水枪禁 / UB forced-burn / 夜伸 Mega / 双海星贴 Bench / 先手含羞苞留场 — ALL_OK
  - H2H n=200 seed140000 rules-only：`logs/h2h_audit_waveU_online/` → 总 **55.0%** / A **59%** / B **51%**（对照 Wave L n=200：51%/A55/B47）
  - BC 4×20 seed93000：`logs/combat_eval_waveU_bc_4x20/` → WR **67.5%**；`ready_mega_no_attack=0`；`base_attack_with_ready_mega=0`；`bad_ultra_ball_discard=0`
- **Wave L（已冻结，仍在栈上）**：
  - L1–L3 Boss / closing / 夜伸捞 Boss；BC 曾 WR 62.5%、`effective_boss_rate` 0.77（U 烟测同 seed WR 更高，Boss 率噪声带内）
- **Wave M（中盘 DP）试刀已回滚**：抬 `ATTACH_DARK`/PLAY Munk/无效 Boss demote → H2H **41.5% / B32%**（`logs/h2h_audit_waveM_dp/`）
- **Wave N（超窄 DP 仅 prep 序）已回滚 + 已解剖**：H2H 总 **51%** / B **39%**（`logs/h2h_audit_waveN_dp/`）；解剖见 [`logs/h2h_audit_waveN_dp/AUTOPSY.md`](logs/h2h_audit_waveN_dp/AUTOPSY.md)
  - **已证伪**：序刀可抬 `munk_dark`（29%→28.5%，seat B 反降）
  - **未证实**：序刀机制性害死 seat B（总 WR 平、配对翻转不显著、同 seed≠同局）
  - **监视信号**：seat B `mega_evolved_no_attack` 6%→14% — 再动 DP prep 前必须 hard-rule trace
  - 禁止再改 `_dp_prep_steps` 序直至决策探针；**撤回**「DP 硬改已榨干」
- **Wave O / 861 归因（SOP-D）NO-GO**：[`logs/diagnose_waveO_861/DIAGNOSE.md`](logs/diagnose_waveO_861/DIAGNOSE.md)
  - `no_861` 胜/负均为 **90%（lift+0）** → 标签≠死因；全池 `ever_861` 仅 10%，胜局 45/50 无 861 仍赢
  - `861_no_fire`≈可忽略；**禁止**为刷掉 `no_861` 放宽 861 窗
  - **已证伪**：「负局最大 tag=no_861 ⇒ 主攻 HARVEST 861」
- **`no_attack` 归因（SOP-D）NO-GO 全局必攻再收紧**：[`logs/diagnose_waveP_no_attack/DIAGNOSE.md`](logs/diagnose_waveP_no_attack/DIAGNOSE.md)
  - 全池 lift 被无 Mega 灌水；`ever_mega` 且零攻仅 **4** 局（全胡地）；`ready_mega_no_attack=0`
- **seat B × `no_mega` 归因（SOP-D）**：[`logs/diagnose_seatB_no_mega/DIAGNOSE.md`](logs/diagnose_seatB_no_mega/DIAGNOSE.md)
  - 负 32% vs 胜 8.5%；主簇=线死/无 Mega/砖，**不是** OPENING 宽 demote 理由
  - 决策针候选：`mega_clock` facts/选项不一致时的 −PATH 平台（`game_045`/`155`）
- **Wave Q 已回滚 + 已解剖**：[`logs/h2h_audit_waveQ_mega_clock/AUTOPSY.md`](logs/h2h_audit_waveQ_mega_clock/AUTOPSY.md)
  - 刀：`_mega_evolve_legal_now` 强制选项接地 → H2H **40.5% / B34%**（红）
  - **已证伪**：宽 options 接地；禁止原样重试
- **实机 EVOLVE dump（已完成）**：[`logs/dump_evolve_options/DUMP.md`](logs/dump_evolve_options/DUMP.md)
  - 结构：`EVOLVE` + `area=HAND(1031)` + `inPlayArea/Index→1030`；helper **认得** Mega
  - 平台真身：`facts` 忽略 `appearThisTurn`（cg.Pokemon 无 canEvolve/turnPlayed）
- **Wave R 已回滚 + 已解剖**：[`logs/h2h_audit_waveR_appear/AUTOPSY.md`](logs/h2h_audit_waveR_appear/AUTOPSY.md)
  - 刀：`can_evolve_now` 尊重 `appearThisTurn` → dump plateau 55→9（探针过），H2H **46% / B36%**（红）
  - **已证伪**：只修 facts/appear 关平台即可抬 seat B——与 Q 同族：关假 mega_clock 窗口伤后手
  - 禁止第三刀「只关平台 demote」
- **平台拍 option_score dump（已完成）**：[`logs/dump_plateau_scores/DUMP.md`](logs/dump_plateau_scores/DUMP.md)（`scripts/dump_plateau_scores.py`）
  - MAIN + mega window + facts can evolve + 无 EVOLVE + mega_legal；60 events / 20 games seed140000
  - Boss 胜出率 **1.7%**；选项含 Boss PLAY **1.7%**（≪35% 闸）→ Wave S「假窗口 Boss 单卡再降权」**NO-GO**
  - 全员同分率 **0.72**；主赢=ATTACH/END/侧基本/ATTACK/杂 PLAY（−PATH 平台上排序近乎任意）
  - **已证伪**：game_045 叙事的 Boss 平台赢家假设
- **UB 烧 Mega 归因（SOP-D）NO-GO**：[`logs/diagnose_ub_burn_mega/DIAGNOSE.md`](logs/diagnose_ub_burn_mega/DIAGNOSE.md)（`scripts/dump_ub_discard_mega.py`）
  - H2H n=200 seed140000：burn 局率 **4%**；lift **0.004** / seatB **0.021** → 标签≠死因
  - 引擎 UB 弃 **2** 张；本跑次 UB-2 泄漏 0；错杀多为手持 Mega 挖底座时 `dv=100` 同分
  - **已证伪**：「game_155 族 UB 烧 Mega ⇒ 值得开 Wave T WR 刀」；**不另开 Wave T**
- **政策面**：Wave L **已冻结 commit**（`28c6e08`）；挂起表只读（OPENING / DP / 861 / 平台 Q–S / UB 烧 Mega）
- **权威面**：Wave I H2H + Wave L 政策叠加
- **迭代 SOP（强制）**：[`references/rulebook/SOP-PilotIteration.md`](references/rulebook/SOP-PilotIteration.md) — D→H→P→G0→G1→G2；黄/红必解剖；禁止抽奖式换维
- **磁盘**：改规则务必立刻 commit
- **指标文档**：`references/rulebook/METRICS-CombatV1_20260801.md`｜`TURN_PLAN_POLICY_20260802.md`｜`ULTRA_BALL_POLICY_20260801.md`｜**`SOP-PilotIteration.md`**｜**`ONLINE_LEAK_PATTERNS_55299191.md`**

---


## 本机 / VPS 分工

| 场景 | 在哪 | 怎么做 |
|------|------|--------|
| 改 pilot / 单测 | 本机 | `.venv` + `pytest` |
| n200+ h2h / marathon | VPS | `sync_to_vps.ps1` 后 SSH 跑脚本 |
| 推 GitHub | VPS | `sync_to_vps.ps1 -PushOrigin` 或 VPS 上 `git push origin master` |
| 大日志 `logs/` | 仅 VPS | 默认不同步到本机 |

## 文档地图（按需 @ 引用，不要一次性全部加载）

| 文档 | 内容 |
|---|---|
| `ONBOARDING.md` | 快速上手、目录结构、全部常用命令 |
| **`references/rulebook/SOP-PilotIteration.md`** | **Pilot 迭代 SOP（先归因再动刀；闸门与回滚纪律）** |
| **`references/rulebook/ONLINE_LEAK_PATTERNS_55299191.md`** | **线上可追溯失误模式（OL-A…F）+ 日志识别式 + Wave U 对照** |
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
- **政策迭代**必须遵循 `references/rulebook/SOP-PilotIteration.md`：无假设卡不改码；G0 黄/红先解剖再回滚；n=200 不单独封杀维度。
