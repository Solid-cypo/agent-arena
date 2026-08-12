# AgentArena — Agent 工作指南

> Kaggle [PTCG AI Battle Challenge](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle)（`cabt` 环境）的对战 AI。
> 主线：**Starmie+Froslass 卡组 Pilot**（Layer1 硬规则 + Layer2 软维）+ 理论建模（FSM）。
> 开发：本机 Windows（`D:\Agent\agent-arena`）写代码 + 小测；重测：Ubuntu VPS（洛杉矶，`kag-vps:/root/agent-arena`）。
> 同步：本机 commit 后跑 `scripts/sync_to_vps.ps1`（git bundle → VPS）；GitHub 仍由 VPS `git push origin` 出口。

---

## 当前状态（每次会话结束时更新此节）

- **更新日期**：2026-08-12
- **CutDraw66Ship 已交 Kaggle [`55455986`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（PENDING）：FroslassCut + Draw66Closeout/AfterEvolve + DkAdrena + dryMegaBan，叠在 DpStallDraw 栈上。软地板全 PASS — [`logs/h2h_audit_cutDraw66_n200/GATE.md`](logs/h2h_audit_cutDraw66_n200/GATE.md)：B·fm mean **71.0%** / dark **64.8%** / Opening **79.0%** / WR **65.7%**（3×n200 vs fireform）。窗口扫 [`logs/diagnose_froslass_cut_55445134/WINDOW_SCAN.md`](logs/diagnose_froslass_cut_55445134/WINDOW_SCAN.md)：CUT live=0；DRAW66 Jetting-MISS **12** 帧为主改点。栈 = Field6Narrow+SeatMunk+Jetting+GP+NoPathDark+MidOps+P0+DpStallDraw+FroslassCut+Draw66+DkAdrena
- **DpStallDraw-V2.1 已交 Kaggle [`55445134`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **508.7**）：喷水前莉莉艾/裁判/希尔达。闸 [`logs/h2h_audit_midConvert_n200/GATE.md`](logs/h2h_audit_midConvert_n200/GATE.md)。公局 fade：Mega 100% / ever861 24% / 861开火 1/25；负局 `dun_no_66`/`no_861` 共现
- **Field6Ship explore 已交 Kaggle [`55433727`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**（COMPLETE **465.2**）：[`logs/h2h_audit_field6Ship_n200/GATE.md`](logs/h2h_audit_field6Ship_n200/GATE.md) — Opening mean **78.7%** / B·fm mean **63.7%** / dark mean 50.4%（软地板 dark FAIL，产品覆盖探针）
- **RL 运行时一致性（2026-08-11 已验证，本地对拍替代复交）**：[`logs/h2h_audit_rlOn_n200/GATE.md`](logs/h2h_audit_rlOn_n200/GATE.md) — 打包事实：tar **不含 combat_loop** → 线上 OPENING_HANDOFF 分支死路，线上运行时 = HEAD + RL=1（仅 OPENING 接管）。三 seed n200 对拍：RL=1 ≈ RL=0 全指标噪声带内（WR 60.5 vs 61.3 / Opening 78.2 vs 78.7 / B·fm 62.5 vs 63.7 / B 席 58.3 vs 56.0）。**已证伪**：整局层面 Hybrid 税；`RL_ENABLED=0` 复交不值提交名额；本地 RL=0 闸对线上有代表性
- **重大工具债修复（2026-08-11 晚）：Kaggle 回放 action/obs 错位一帧**：[`logs/diagnose_field6_zero_attack/REPLAY_OFFSET_FIX.md`](logs/diagnose_field6_zero_attack/REPLAY_OFFSET_FIX.md) — `steps[t].action` 应答的是 `steps[t-1].observation`。**作废**：PROBE.md §2/§3「线上该喷没喷 Class A 52-78%」「整局重放 match 仅 29%=回放≠现场」。修正后：整局有状态 match 71%、开局无状态 argmax match **98%**、taxonomy 线上=HEAD 逐行一致（LEAK 1/37）→ **线上运行时与本地政策一致，帧级回放对拍从此可信**。已修 4 个扫描脚本；其余读 replay action 的脚本沿用前先查配对
- **55433727 线上开局重审**（同文档）：「T3 做不出打手」按闸口径不成立 — Mega 按时进化 **16/18=89%**；塌的是「可战斗」Active Mega+水≤T3 仅 **8/18=44%**（无 Mega×2=Budew 锁+水枪局、Mega 困 bench/donk×2、后手差一拍×3）。开局帧 **28% 并列最优**靠 ±0.02 随机 tie-break 掷骰子。可动刀面：① tie-break 政策化；② Mega+水困 bench 归因；③ 后手 T2 慢一拍簇
- **「版本回退」质询终审（2026-08-12 凌晨，两轮）**：[`logs/h2h_audit_ver_compare/COMPARE.md`](logs/h2h_audit_ver_compare/COMPARE.md)
  - **Opening 未回退**：HEAD Opening 合计 78-82%（对 fireform 和老包均保持）vs 老包自测 65-72%；线上进化达标 89%
  - **公榜分实时复核**：P0 初读 610.4 是早期泡沫，**现 398.8**（38局收敛）；现役 Field6Ship 475.8→**494.8↑**（19局爬升中）；8月1日老栈收敛分更高：surplus861_deckfix **524.5** / ops_firefix **516.8**
  - **面对面终审**：HEAD vs surplus861/firefix 四组 n200 全部 **~49.5% 精确打平** — P0→GP→F6S 十天刀工对老栈**净增益=0**；开局优势被中盘回吐（开局达标局 WR 仅 53-58%，B 席 39-49%）。「vs fireform 61.3%」是镜像闸口径高估
  - **判决：不回退**（回退=打平还丢 Opening 增益；老包高分槽位仍在榜活着）。**闸协议必改**：G0 对手池扩为 {fireform, surplus861_deckfix, ops_firefix}，中盘刀必须多对手池同时不回吐才放行
  - **第三轮（严口径「打手出手」先≤T3/后≤T2）**：用户正确 — **绝对水平不合格**：线上现役 44%（B 席 38%）、本地 HEAD 也仅 52-55%；闸文 78.7% 是进化口径，粉饰了 ~25pp「进化了但出不了手」缺口。但**分座位归一后无回退**：P0 线上 52% 吃了 64% 先手局的座位运（其 B 席仅 22%）；现役 B 席 38% 为血统最佳；真回退是 GapParallel 版（A 席 17%）已收复。**Opening 硬指标升级为双轨（进化+出手），出手为主闸**
- **有 Mega 零攻两局（92000238/91988778）已关闭**：[`logs/diagnose_field6_zero_attack/DIAGNOSE.md`](logs/diagnose_field6_zero_attack/DIAGNOSE.md) — 逐帧对拍 0 个 Class A 帧（整局无「充能 Mega+Jetting 可选」），真身=能量荒+短局被碾，无刀可开（该文档帧级数字已加勘误横幅）
- **zero_boss 窄刀 NO-GO**：同文档 — 本地 6/6 跑次（n=1200）lift 全为负（−0.01…−0.12），与 no_861 同族标签≠死因；线上 +0.39 是 n=18 噪声。公局 ≥40 复核 lift 仍 >+0.2 才重开
- **打手出手缺口专项结案（2026-08-12 凌晨）**：[`logs/diagnose_mega_attack_gap/GATE.md`](logs/diagnose_mega_attack_gap/GATE.md) — 三项判决：
  - **归因**：线上 59 局逐帧 — 该攻没攻=0（must_close 无漏）；缺口主簇=「T1 杂兵前场+海星 bench」（B 席 fail 17/20，P0 同构非回退），多数是资源死局且政策有 T3 补救线
  - **SetupActive 刀三版全 NO-GO 已回退**：发现 T0 首发纯 ±0.02 噪声掷骰子（91988778 铁证帧），但硬排序 V1/V2/V3 全不过闸（干净口径 V3 = 57.5% vs 基线 60.5%）；观察性「杂兵首发 WR 63.5% vs 海星首发 56.2%」混杂严重，**首发刀今后必须 same-seed 反事实**。核心张力：**严格出手率与 WR 顶牛**（海星冲前场抬达标掉胜率），出手天花板受墙式开局设计约束
  - **本地审计地雷已拆**：本地 `submission_starmie/combat_loop/`（已移至 `.agent/Versions/combat_loop_vendored/`）+ `OPENING_HANDOFF` 默认=1 → 忘设 env 的本地闸被冻结开局接管，**污染 10pp**（handoff=1 WR 50.3% vs =0 60.5%）。线上不受影响：双配置重放 55433727，handoff=0 开局帧 match **210/211=100%**（handoff=1 仅 53%）→ 线上=HEAD 开局帧级零分歧。拆雷后本地默认=线上行为
- **中盘转化专项（2026-08-12，勘误后开刀）**：[`logs/diagnose_mid_convert/DIAGNOSE.md`](logs/diagnose_mid_convert/DIAGNOSE.md) · 闸 [`logs/h2h_audit_midConvert_n200/GATE.md`](logs/h2h_audit_midConvert_n200/GATE.md)
  - **初版 NO-PATH「资源死局无刀」已勘误**：扫描器 path 不计莉莉艾/裁判；真因是 must_close 把抽牌支援压到 −1150、且 `_DP_STALL_DRAW_ENABLED` 曾关。线上负局 **45–75%** 出现「莉莉艾/裁判可选却直接喷水」
  - **DpStallDraw-V2.1 已开**：中盘缺口且无 typed 路径时，喷水前先打莉莉艾/裁判/希尔达；覆盖 skip→Jet 帧 62–78%
  - 闸：vs fireform WR **60.5→64.2**、达标转化 **64.0→72.1**；出手 −6.2pp（辅闸贴边）；vs firefix +8pp WR；vs surplus 三 seed 均值 **48.5%**（~−1pp）。**PASS 已交 [`55445134`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions)**
- **SeatSnorunt-V1（WIP，未交 Kaggle）**：Mega+水 + 猿已贴暗 + 空席 + 手雪童 → must_close 内 PLAY 雪童 ≻ Jetting（让路一轮）；让路 SeatMunk/dig/combat；不强进 861/废墟。窄刀 A；B/C 未做。单测 `test_seatsnorunt_*`
- **下一步（2026-08-12 晚更新）**：① 本地软地板验收 SeatSnorunt 后再谈交包；② 盯 [`55455986`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) 公局；③ 对照 [`55445134`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) 508.7。**禁止**：CombatClose/DP 宽序/zero_boss/Boss→Jetting/RunAway 宽 PATH；坐猿/开窗/座位宽优先级；观察相关性直接开刀
- **工作流**：日常开发在本机；VPS 专跑 h2h/marathon/Kaggle。同步：`pwsh scripts/sync_to_vps.ps1`（可选 `-PushOrigin`、`-RemoteCmd "..."`）
- **本机环境**：Python 3.10 venv（`.venv`）；冒烟 ` .\.venv\Scripts\python.exe -m pytest tests/test_starmie_pilot.py -q`
- **线上权威峰**：[`55386951`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) **P0 CrispinWater** → publicScore **610.4**；本地档 [`data/restore_peaks/p0CrispinWater_55386951/`](data/restore_peaks/p0CrispinWater_55386951/)；git `ef246cc`（含 handoff WIP）
- **P0（已冻结）**：G0 [`logs/h2h_audit_p0CrispinWater_n200/GATE.md`](logs/h2h_audit_p0CrispinWater_n200/GATE.md) WR **58.5%** / B**61** / Opening **80.5%**；公局初审 n=3 WR2/3、零 Jetting=0 → [`logs/diagnose_p0CrispinWater_55386951/REVIEW.md`](logs/diagnose_p0CrispinWater_55386951/REVIEW.md)
- **P1 fade（已修）**：`(attackId,serial)` 去重；旧包 55381818 真零 Jetting 1/12
- **P2 Boss→Jetting（HOLD）**：[`logs/diagnose_p2_boss_jetting/HOLD.md`](logs/diagnose_p2_boss_jetting/HOLD.md)
- **下一刀**：等 55455986 公局≥12–15 再 SOP-D；勿重开中盘 DP/CombatClose-V1/V2；MidOps 已 SHIP 勿叠 RunAway-V1 宽 PATH
- **本地 Opening 闸**（vs `ops_fireform_55115028`，n=200 seed82000，`OPENING_HANDOFF=0`，TURN_START 去重）：硬指标 **81.5%**（先手≤T3 **86%** / 后手≤T2 **77%**）· WR **53.5%** · 三漏归零（`logs/h2h_audit_engineSeats_n200/`）
- **中盘 CombatClose-V2（证伪已回滚）**：Adrena→Boss + first-prep PATH（无锁）→ prep_ok 54.8%→**42.4%**、负局无有效 Boss↑；Opening 合计持 80.5%；见 [`logs/diagnose_combat_v2/AUTOPSY.md`](logs/diagnose_combat_v2/AUTOPSY.md) · [`logs/h2h_audit_combatV2_n200/GATE.md`](logs/h2h_audit_combatV2_n200/GATE.md)。**已证伪**：无锁窄 PATH 亦不足以抬双穿序
- **MidOps-V1（SHIP）**：第二打手 matchup（控场/烈箭/铝钢禁 861；路卡开窗）+ OL-E2 厚手铺场 + 窄 post-Mega 66 抽；G0 [`logs/h2h_audit_midOps_n200/GATE.md`](logs/h2h_audit_midOps_n200/GATE.md) Opening 合计 **75.5%** / 先≤T3 **81%** / B**54** / WR 56.5%
- **中盘 CombatClose-V1（证伪已回滚）**：露面+锁 ADRENA/BOSS/DISPATCH → prep_ok 31→29%、Opening 合计 81.5→**77.5%**；见 [`logs/diagnose_combat_expert_gap/DIAGNOSE.md`](logs/diagnose_combat_expert_gap/DIAGNOSE.md) · [`logs/h2h_audit_combatClose_n200/GATE.md`](logs/h2h_audit_combatClose_n200/GATE.md)。**已证伪**：仅靠 primary_step 锁修双穿序
- **对照**：历史最佳本地峰 `data/restore_peaks/ops_fireform_55115028`；H2H 权威仍记 Wave I n=400（`logs/h2h_audit_waveI_seat_b/` → **50.5% / A52 / B49**）
- **卡组**：`data/decks/starmie_froslass.csv` — 3×海星星、3×危险废墟、无 306、5 水 + 3 恶（2026-08-10：GapParallel 前恢复 P0 卡组）
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
