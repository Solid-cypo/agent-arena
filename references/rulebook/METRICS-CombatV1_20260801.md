# Combat v1 — 战斗逻辑修复记录（2026-08-01）

> 注：本文件在 2026-08-01 09:40 的磁盘清理事故中丢失后按原文重写。
> rulebook 下其它历史文档（METRICS-胡地Opening与对手_20260731.md 等）
> 为未跟踪文件，已丢失，如需可从 agent 聊天转录中部分找回。

线上 fade（sub_55115028，36 局，胜率 33%）败因驱动的战斗规则修复。
方案四步：C0 口径冻结 → C1 对手池扩容 → C2 loss-tag 修复 → C3 门控打包。

## C0 — 战斗口径与埋点

新工具 `scripts/run_combat_eval.py`：对手池评测 + 每局战斗埋点
（boss_plays / boss_target_koable / dead_turns / prize_timeline / supporter /
66 引擎 / 861），败局自动打 tag，taxonomy 与线上 fade 完全一致
（zero_boss / no_supporter / no_attack / no_mega / no_861 / 861_no_fire /
dun_no_66 / no_dun / dud_no_ability / prize_stuck）。

## C1 — 对手池扩容

`scripts/reconstruct_opp_decks.py`：从 sub_55115028 回放按 **card serial**
重建对手可见牌（serial 每局唯一 → 精确副本数），跨局取 max，≤60 裁 1x
训练家、>60 补 staples/能量。产出 `data/decks/`：

| 牌表 | 回放局数 | 可见牌数 | 补齐 |
|---|---|---|---|
| lucario_fighting | 9 | 69（裁到 60） | — |
| marnie_froslass_munk | 6 | 49 | +11 |
| dragapult | 3 | 44 | +16 |

对手 agent：`arena.policy.make_agent` 启发式（BC 对手为后置选项）。

## T-C 池基线 vs 修复后（5 副 × N=60，seed0=71000）

| 指标 | 基线 | C2a | C2b（最终） | 门槛 |
|---|---|---|---|---|
| 总胜率 | 93.0% | 92.0% | **92.0%** | 不显著下降 ✓（±1.6pp SE 内） |
| zero_boss 占败局 | 76.2% | 33.3% | **45.8%** | <50% ✓（线上口径 96%） |
| dead_turns/局 | 0.117 | 0.100 | **0.043** | 降 ≥50% ✓（−63%） |
| boss/局 | 0.57 | 0.63 | 0.57 | — |
| boss 目标可 KO 率 | 97.1% | 90.5% | 89.0% | — |

分对手（最终）：walrein 98.3%（基线 95.0）/ alakazam 93.3%（93.3）/
lucario 83.3%（86.7）/ marnie 86.7%（90.0）/ dragapult 98.3%（100）。
剩余败局 tag 集中在 no_861/no_mega/no_attack（lucario 快攻碾开局），
属开局被打穿而非战斗决策缺失。

## C2a — zero_boss + prize_stuck（starmie_pilot.py）

- **SP-BOSS-2 tempo gust**：对手 Active 本回合打不死但 bench 有本攻击可 KO
  目标 → gust 触发（`_current_max_damage` 估算 Jetting120/Nebula210/
  Resentful50×hand/AbsSnow150）。
- **SP-BOSS-3 prize_stuck 放宽**：我方 ≤2 奖杯且连续 ≥2 回合未得分
  （agent_state `prize_progress` 追踪）→ bench 任意可 KO / ≤70HP 目标即触发。
- **prize-path 精化**：贪心排序从「按 HP」改为「可 KO 优先 → 奖杯价值密度
  （prizes/HP）→ 低 HP」。
- **SP-BOSS-T**：Boss gust 目标 CARD select 从 soft S-5b 升为 Layer1 确定性
  选择（可 KO +100 / prize-path +40 / ex +20 / 低 HP tiebreak），排在
  Alakazam Plan B 之后，confirmed 链路优先级不变。

## C2b — 死回合与引擎熄火

- **HARVEST 撤退救援**：`_needs_retreat_rescue` 扩到 HARVEST（bench 有
  861/1031 攻击手时）。
- **draw_axis 饥饿放宽**：手牌 ≤2 且无支援者 → 跳过 DD-1/2/3/4/8 tempo
  ban，仅保留物理可行性（DD-2b/DD-7）；OPENING ban 不动。
- **SP-FALLBACK**：post-Mega 无更优支援者计划时兜底打 Hilda/Crispin
  （priority 820）。**Boss 不入兜底**（留给 gust 窗口）；**Wally 不入兜底**
  （无伤时打出会把 Mega 能量收回手——首版入了，walrein 槽 98.3→91.7，
  移除后恢复）。

## C3 — 门控结果（全过）

| 门 | 结果 |
|---|---|
| T1 probe 全绿（bad_attach/waste/multi_attach/dun/mf_fire/evo66） | ✓ pass |
| T1 CABT hybrid：open 86.7%（≥73）megaT3 77.8%（≥65）win 94.4% | ✓ |
| T-C 池：zero_boss <50% + dead_turns −63%，胜率持平 | ✓ |
| T2 胡地：win 91.7%（改前 91.3）confirmed 95%/hard-signal 100%，window 5%/35% 仍触发 | ✓ 不掉 |

## 补充验证（2026-08-01 上午）

- **换种子稳健性**（seed0=81000，全新对局，5×60）：总胜率 92.7%、
  zero_boss 占败局 45.5%（<50% ✓）、dead_turns/局 0.057（✓）——与
  71000 种子结果一致，无固定种子过拟合。
  数据：`combat_eval_c2b2_seed81k_n300.json`
- **触发探针**（`scripts/probe_boss_triggers.py`，spy 三类 gust 触发）：
  lucario 60 局中原 path 触发 51 局、放宽触发（tempo/stuck）3 局 11 个
  决策点；marnie 59/3 局。放宽触发确实在实战出现，但低频——线上
  zero_boss 的主要瓶颈是 Boss 目标选择质量与支援者槽竞争
  （SP-BOSS-T Layer1 化解决），而非触发条件本身完全缺失。
- **BC 胡地压力**（`run_alak_bc_acceptance` N=30）：combat_v1 对 BC 胡地
  50%→56.7%，finisher_window 0→20%（n=30，±9pp，方向参考）。
- **对手代表性阶梯**：启发式胡地（我们 91.7%）≈ 下位替身；BC 胡地
  （我们 56.7%）≈ 中位替身；线上真实胡地 0/2、线上全体 33%。

## 打包与提交

`submission_starmie_combat_v1.tar.gz`（68 entries，解包冒烟 4/4 胜）。
**只替弱槽，不盖强槽。**

已提交：**sub 55150906**（2026-08-01），替换弱槽 ops_alak_planb
477.1（55129509），保留强槽 ops_firefix 516.8（55115028）。
线上回归观察点：fade 样本 zero_boss / no_attack / prize_stuck 占比。

## 数据文件

- 基线/各步 T-C：`data/opening_sft/combat_eval_baseline_n300.json`、
  `combat_eval_c2a_n300.json`、`combat_eval_c2b_n300.json`（首版含 Wally）、
  `combat_eval_c2b2_n300.json`（最终）、`combat_eval_c2b2_seed81k_n300.json`
- T1：`data/opening_sft/ops_fix_full_eval_summary.json`
- T2：`data/opening_sft/alak_planb_vs_alakazam_n60.json`
- 事故备份：`/root/rescue_20260801/`（发船包、解包副本、git 历史、
  三原型回放 arch_replays.tar.gz、评测数据）

## BC 对手池（T-C-BC，2026-08-01 建成）

管线：`scripts/alak_bc.py`（事故后从 pyc 反编译重建，与幸存
`alak_bc_opponent.npz` 验证兼容：我方 60% vs 事故前 56.7%）+ 新
`scripts/train_arch_bc_opponent.py`（从 sub_55115028 回放提取对手侧决策
（obs@t ↔ action@t+1），pointer-BC，D→128→64→1，与 alak_bc 同布局）。

| BC 对手 | 专家决策数 | top-1 | 我方胜率（N=60） |
|---|---|---|---|
| alakazam_main（原 alak_bc_opponent） | — | — | 61.7% |
| lucario_fighting | 551 | 0.72 | **51.7%** |
| marnie_froslass_munk | ~600 | 0.77 | 83.3% |
| dragapult | ~350 | 0.74 | 96.7% |

**T-C-BC 压力基线（combat_v1 代码，4×60=240 局）**：总胜率 **73.3%**
（启发式池 92%），zero_boss 占败局 59%、boss/g 0.475（启发式池 0.57）——
真实压力下 Boss 使用仍塌陷，本地首次复现了与线上同构的失败模式。
数据：`combat_eval_bc_n240.json`。用法：
`run_combat_eval.py --decks ... --bc <逗号列表>`。

代表性阶梯（我方胜率）：启发式池 92% → BC 池 73% → 线上 33%。
下一轮迭代以 **T-C-BC 池总胜率 + zero_boss/tag 结构**为主 KPI。

## Behavior-Fix v1（BF1，2026-08-01，用户观察 7 问题）

用户观察 → 规则修复（全部 Layer1 硬规则，代码见 starmie_pilot / supporter_planner）：

| # | 问题 | 修复 |
|---|---|---|
| P1 | 达成 MEGA 后停转、不做 DP 套 | `_synergy_window` 不再 T8 关闭：DP 核心（愿增猿+104+恶能）未成型则窗口保持开放 |
| P2 | 支援者滥用 Boss（运转大于一切） | `_boss_ok`/`_boss_engine_gate`：MEGA+DP 成型才放行 Boss；例外＝≤2 奖收尾 / gust 目标当回合可 KO（`gust_target_koable`）/ 手中无其他支援。DR-5（Boss 压 Lillie）同门 |
| P3 | 乱填能（恶能给基础怪） | HR-E3/E4：恶能仅愿增猿、水能仅打手线，唯一例外＝无法撤退的非打手前场贴撤退油 |
| P4 | 无打手时换下土龙弟弟 | `_needs_retreat_rescue`：土龙弟弟站场时仅在替补 Mega 带水就绪才拉下；新增 SWITCH/TO_ACTIVE 兜底排序（土龙线>基础>喵头目>愿增猿>雪童子/海星星） |
| P5 | 夜之伸展器回收错 | `_discard_recover_bonus`（先于 `_synergy_search_bonus`，修复其把弃牌区当牌库检索的根因）：能量优先，宝可梦仅在该打手线全灭时回收 |
| P6 | 海星星铺过多 | `_staryu_overflow_ban`：场上（含战斗区）≥2 只时禁止再上（打出/Poffin/Pad 全覆盖） |
| P7 | 喵头目罚站停转 | HR-9 救援解除 `_defer_mega_promotion` 反向封锁；新增非打手前场+替补 Mega 就绪时禁用工具攻击、强推撤退/换人 |

**BF1 回归（同种子对比）**：

| 池 | BF1 | 基线 | 备注 |
|---|---|---|---|
| T-C 启发式 5 副 n=300 | **92.7%**（walrein 95 / alak 91.7 / lucario 88.3 / marnie 91.7 / drag 96.7） | ≈92% | 持平；dead/g 0.077 |
| T-C-BC 4 副 n=240 | **72.1%**（alak 51.7 / lucario 70.0 / marnie 68.3 / drag 98.3） | 73.3% | 持平；dead/g 0.054（基线 0.071） |

结构变化：Boss 门使 boss/g 0.475→0.32、zero_boss 败局占比 59%→78%
（预期内——门主动放弃了部分早期 Boss）；lucario BC +18.3pp、alak BC
-10pp（DP 成型受压时 Boss 被冻结，代价点，若线上回归恶化可放宽门至
prize≤3 或 MEGA 单独成型）。数据：/tmp/fx_reg_tc4、/tmp/fx_reg_bc4。

## DP-Boost v1（2026-08-01，DP 套达成率专项）

新探针（run_combat_eval）：dp_rate（104+愿增猿+恶能同时在场）、dp_turn、
rate_104/rate_munk_dark、雪童子/海星星超编率、夜之伸展器使用率；另有
决策级探针 `scripts/probe_dp_actions.py`（EGG/EVO104/DARK 状态-行动转化）。

规则改动：
- 雪童子场上上限 2（同海星星 P6；861 在场→上限 1，861+104 都在场→0）
- HR-EGG：104 卡手（38% 对局的根因）时强推蛋上场/检索（手打/Poffin/Pad）
- HR-8 解锁：雪童子≥2 或 861 已在场时，861 在手不再禁 104 进化
- 恶能贴附：只给「缺水的 Mega」让位，备用海星星不再抢走愿增猿的恶能
- HR-NS：夜之伸展器主动打出回收稀缺基础能（愿增猿缺恶/打手缺水）
- 弃牌保护补漏：愿增猿加入 Ultra Ball 硬保护；愿增猿缺恶时保护恶能
- Pad/Poffin 触发放宽到「DP 场上件未齐」；OPENING 尾（Mega 已在场）检索
  顺带拉 DP 件（收窄门，避免干扰已冻结的开局路径）

结果（同种子）：决策层转化率 EGG 72% / EVO104 48% / DARK 75%（修复前
EGG~40%/DARK 0.6 水恒占）；游戏级 dp_rate tc 22→23%、bc 19.6→21.2%，
胜率持平（tc 94.0%、bc 71.2%）。**游戏级天花板受卡组资源约束**：
1×104、2×愿增猿、3×恶能、6 张压奖品 → 104 上场率与恶能到位率各 ~45-50%
且近独立（乘积≈实测 dp）。要突破 40% 需改卡组（+1 104 / +1 恶能）——
属配置决策，未动。数据：/tmp/dp_base_*、/tmp/dp_new5_*。

## S-策略：MEGA 海星后 DP 优先，861 改为保险/富余（2026-08-01）

用户策略调整：海星做出后优先运转 DP 套（104+愿增猿+恶能），不再默认直做
861；861 仅三种窗口放行——①海星濒死（`_starmie_in_danger`：剩余 HP ≤
对手战斗区最大印刷伤害，`all_attack()` 建表，估不出兜底 130）或已离场
（HARVEST）；②DP 核心已齐（富余选项，用户确认）；③OPENING 未完成的
HARVEST 兜底（原逻辑保留）。

改动（starmie_pilot / epoch_scheduler）：
- S1 `_starmie_in_danger` + 共享门 `_mega_froslass_window_open`
- S2 `_block_mega_froslass_evolve` 重写：濒死/已死/DP 齐才放行 861
- S3 HR-8 蛋分配反转：孤蛋默认进 104；仅窗口开且只剩一蛋时留给 861
- S4 检索反转：OPENING 尾 861 降到 DP 件之下（窗口关时 -90）；AGGRESSION
  尾 861 检索接窗口门；HR-6 `can_setup_861` 让拍同步接门
- 调度器：`set_mega_froslass_window` 每决策刷新；窗口关时 SF2 视作已清，
  Epoch2 直推 SF3（DP），SF2 的 demote-104 分支随之失效

**回归（同种子 71000，vs DP-Boost v1 基线）**：

| 池 | 胜率 | dp_rate | 104 上场 | no_861 / 861_no_fire |
|---|---|---|---|---|
| T-C 5 副 n=300 | 93.0%（基线 94.0%） | **31.7%**（23.0%）✓≥30 | 54.7%（46.3%） | 11/4（基线 11/4，持平） |
| T-C-BC 4 副 n=240 | **75.0%**（71.2%） | 25.8%（21.2%） | 54.2%（41.3%） | 29/13（基线 33/8） |

决策探针（seed 42k）：EVO104 48%→55%、ban861 阻塞仅 2 次、EGG 68%、DARK 63%。
验收全过：dp≥30%（tc）、tc≥92%、bc≥70%、no_861 不恶化。BC `861_no_fire`
8→13 轻微上升（保险偏晚）；A/B 测试 1.2× 濒死阈值——861_no_fire 回落
13→9 但 tc dp 31.7→25.7%、bc 胜率 75→71.7%，**否决**，保留 1.0× 印刷伤害
阈值。数据：/tmp/s5_tc、/tmp/s5_bc（采纳）；/tmp/s5b_*（1.2× 被否）。

## S-策略收紧：861 仅保险，DP 齐富余选项移除（2026-08-01）

用户指示：即便 DP 齐、资源富余也不做 861，全力运转 DP。861 窗口仅剩
濒死/已死（`_mega_froslass_window_open` 删除 `_synergy_core_ready` 分支，
`_block_mega_froslass_evolve` 同步收敛为共享门取反）。

**回归（同种子 71000，vs S 策略富余版）**：

| 池 | 胜率 | dp_rate | no_861 / 861_no_fire | zero_boss |
|---|---|---|---|---|
| T-C n=300 | 93.0%（持平） | 27.0%（31.7%，降） | 9/3（11/4） | 15（17） |
| T-C-BC n=240 | **67.9%**（75.0%，**-7.1pp 破 70% 线**） | 32.1%（25.8%，升） | 31/18（29/13，恶化） | 54（43） |

解读：压力池 DP 达成率如预期上行（+6.3pp），但第二打手真空的代价更大——
海星死后 861 从零起步慢一拍，`861_no_fire`/`zero_boss` 显著上升，BC 胜率
-7.1pp。富余版（DP 齐后顺手做 861）是更优平衡点。**数据结论：收紧版
局部指标（dp）改善、全局（胜率）恶化；已按用户指示保留收紧版代码，
若线上/后续验证同样恶化建议回退富余版**（差异仅两处放行分支）。
数据：/tmp/t2_tc、/tmp/t2_bc（收紧版）vs /tmp/s5_tc、/tmp/s5_bc（富余版）。

**线上 A/B（2026-08-01）**：两版同日提交对比线上表现——
收紧版（861 仅保险）sub **55159630**（`submission_starmie_861_insurance_only.tar.gz`），
富余版（DP 齐后可做 861）sub **55159648**（`submission_starmie_dp_first_surplus861.tar.gz`）。
本地工作区保留收紧版；切富余版只需在 `_mega_froslass_window_open` 尾行
补回 `or _synergy_core_ready(board)`。

## 卡组回滚事故（2026-08-01 晚发现，已修复）

**症状**：55159630/55159648 线上表现远差于 combat_v1（492.7）。
**根因**：`data/decks/starmie_froslass.csv` 的两次改卡（07-15 +1 海星星/裁
306；07-27 裁 Prism+Ignition → +1 水 +1 恶）**从未 commit 进 git**。7-31
磁盘清理事故后 `git checkout -- .` 把它回滚成初版（2 海星星、含 306、
4水2恶+Prism+Ignition）；恢复用的备份 tar 里也是旧版。`package_starmie.py`
每次打包静默用该文件覆盖 `submission_starmie/deck.csv`，提交前未校验
卡组内容 → 两个 A/B 包都是「旧卡组 + 按新卡组调的规则」错配（规则
硬编码 3 海星星上限/无 306/恶能仅愿增猿，与旧卡组冲突）。
**影响面**：事故恢复后的全部本地回归（BF1、DP-Boost v1、S 策略、收紧
A/B，即 /tmp/fx_*、/tmp/dp_*、/tmp/s5*、/tmp/t2_*）都在旧卡组上跑，
结论需用正确卡组复核（正确版哈希 56f1f93e，源自 combat_v1 包）。
**修复**：正确卡组已恢复到 data/decks + submission_starmie；deck-fix 包
重新提交（收紧版 `submission_starmie_861_insurance_deckfix.tar.gz`、富余版
`submission_starmie_surplus861_deckfix.tar.gz`）。

**正确卡组复核回归（seed 71000）**：

| 版本 | TC 胜率 | TC dp | BC 胜率 | BC dp |
|---|---|---|---|---|
| 收紧（861 仅保险） | 92.7% | 31.0% | 67.9% | 26.7% |
| 富余（DP 齐可 861） | 94.7% | 30.3% | 68.3% | 25.4% |

正确卡组下两版差距大幅缩小（BC 仅差 0.4pp；旧卡组下富余版 +7pp 的
优势是卡组错配伪影）。两版 deck-fix 均在线上，A/B 继续观察。
数据：/tmp/fix_ins_*、/tmp/fix_sur_*。
**防再发**：改卡必须立即 git commit；打包后校验 deck.csv 哈希再提交。
磁盘仍 95% 满（余 935M），清理压力仍在，重要产物勿只放工作区。

## 后置选项（未启动）

Boss 目标/攻击选择 unit 学习组件、小步 PPO——待 combat_v1 线上回归
（sub 55150906）与 T-C-BC 迭代结果决定。
