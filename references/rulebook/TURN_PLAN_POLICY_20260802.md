# TurnPlan 回合目标政策

**日期**：2026-08-03  
**实现**：`.agent/skills/piloting_starmie_froslass/scripts/turn_planner.py`  
**角色表**：`.agent/skills/piloting_starmie_froslass/scripts/opponent_roles.py`  
**提交同步**：`submission_starmie/pilot/`（含 `opponent_roles.py`）

## 决策模型

每次引擎请求动作时，以最新 observation 纯计算一次：

`TurnFacts → TurnGap → TurnPlan → AcquirePlan / CombatPlan / DrawPlan`

不保存动作 cursor；动作执行后重新规划。Epoch memory 只记录 G1→G5 / SF
阶段进度。胡地专项 overlay 仍先于普通 TurnPlan，但不得覆盖“就绪 Mega 必攻”
这一全局不变量。

主目标优先级：

1. `MAKE_ATTACKER`：补海星星、Mega 大海星或水能缺口
2. `ATTACK`：可攻击 Mega 已就绪
3. `BUILD_DP`：做出带恶能的愿增猿，并建立伤害指示物生成器
4. `SECOND_ATTACKER`：建立雪童子 / Mega 大雪妖女线
5. `DRAW`：仅结构化坏手进入抽牌目标

打手缺件已在手时，免费检索窗口可提前补 DP；攻击回合只允许不会替代攻击的
明确前置步骤（104 进化、愿增猿恶能、Adrena、Boss、调度）。

DP 的完成定义已简化为：

- 场上有带恶能的愿增猿
- 场上有伤害指示物生成器：雪妖女 104 **或** 危险废墟

雪妖女 104 不再是唯一必需组件；危险废墟在线后，TurnPlan 不再继续强追 104。

## 对手角色与目标选择

公开区 card ID 映射到角色（无需先猜 archetype）：

| 角色 | 含义 | 例 |
|---|---|---|
| `MAIN_ATTACKER_BASE` | 主打手底座 | 凯西、多龙梅西亚、利欧路、捣蛋小妖、海豹球 |
| `MAIN_ATTACKER_STAGE` / `MAIN_ATTACKER` | 中间进化 / 最终打手 | 勇基拉 / 胡地；多龙奇 / 多龙巴鲁托 |
| `SECONDARY_ATTACKER_BASE` / `SECONDARY_ATTACKER` | 副打手线 | 幕下力士 / 铁掌力士 |
| `ENGINE_BASE` / `UTILITY` | 引擎底座 / 工具人 | 夜巡灵、雪童子、谢米、愿增猿、含羞苞 |

Boss 与 DoubleKO rider 使用**分开的优先级**：

- rider：`rider_priority → prizes → -hp`（同 HP 优先切断主打手底座）
- Boss：`本回合可击倒 → prizes → boss_priority → -hp`
- DoubleKO 中 Boss 与 rider 必须为不同目标
- 谢米 `Flower Curtain` 在线时，无规则盒后排视为 `attack_protected`，不可作 Jetting rider；规则盒（ex / megaEx / tera）仍可瞄准
- 未知公开宝可梦回退为 `UNKNOWN`（优先级 0），不阻断规划
- 胡地确认仅叠加 matchup 修正（凯西 rider / 谢米 Boss），不再维护第二套排序

执行层：当 TurnPlan 已给出 `rider_target` / `boss_target` 时，legacy
`_damage_select_bonus` / `_boss_gust_select_bonus` 必须让路。

## CombatPlan

- Active Mega 有对应能量，或 bench 就绪 Mega 可立即调度：
  `attack_required=True`。
- 必攻时禁止 END 和普通底座攻击；Budew 仅在无就绪 Mega 的后手拖延窗口使用。
- 普通建设动作不得压过攻击。
- 海星 DoubleKO 顺序：`Adrena → Boss（需要时）→ Jetting Blow → rider`。
- rider 阈值：无可转移伤害为 50 HP；可转移至少 30 时为 80 HP。
- Boss 不得抓走 rider。

### 有效 Boss（effective Boss）

定义：打出 Boss 后，本回合攻击序列相对不抓人，能多拿至少 1 奖，或完成计划中的
DoubleKO 第二击倒。

- 决策：计算 `expected_prize_delta`（Boss 后前场奖 + rider 奖 − 不 Boss 基线）。
- **仅当** `delta > 0`，或 DoubleKO 必须把不可击倒前场换掉时，才把 `BOSS` 写入
  `required_before_attack` / 设置 `boss_target`。
- 无效 Boss：打了但本回合奖进度不变，且不是 DoubleKO 必需步骤 — TurnPlan 不强制。
- 支援者层与 TurnPlan 对齐；去掉“唯一支援者就打 Boss”放宽；终局 ≤2 奖仍可例外。
- `zero_boss` 仅作参考标签；主 KPI / 败因看 `effective_boss` / `no_effective_boss`。

## AcquirePlan

- 检索目标由**手牌持有组件 → 最小激活集**生成，而不是固定
  `海星星→Mega→水能→DP` 死序。
- 专家固化例：
  1. 手有 `66`，场无打手底座且无土龙弟弟 → Poffin 目标 `(STARYU, DUNSPARCE_*)`
  2. 手有愿增猿且打手已在线 → 目标切到恶能，不继续铺无关基础宠
  3. 手有 Mega 海星且场无海星星 → 只找 `STARYU`
  4. DP：已持有件跳过，只补缺失（104 / 危险废墟 / 愿增猿 / 恶能）
- Poffin 执行层严格服从 `acquire.targets` 顺序，再回退开局表 / 后手含羞苞。
- Poffin / 手环 / 希尔达能关闭当前缺口时优先于高级球。
- Night Stretcher 只回收当前唯一缺口。
- `discard_value` 同时供 live 选择和 opening simulator 使用。
- 当前路径、水能、有效担架、终局 Boss 为高保护；失效免费检索和重复完成件可弃。

## 软门

- Mega 大雪妖女 861：主动建设要求预计至少 2 奖；直接获胜、唯一可攻击 Mega、
  或不使用会失去本回合 Mega 攻击时例外。
- 土龙：第一只不得挤占主打手路径；第二只必须满足预留主打手、DP 和第二打手后的
  bench budget。
- Run Away Draw：仅单一进化/能量缺口，或“进化+能量但无底座”的结构化坏手；
  好手、必攻回合和会洗掉唯一路径时 HOLD。

## 遥测口径

新增（`run_combat_eval` / review pack）：

- **主 KPI**：`effective_boss_rate`、`ineffective_boss_count`、`boss_prize_delta_avg`
- 败因：`no_effective_boss`（主）；`zero_boss` 保留为参考，不再作为主 KPI
- `opponent_role_coverage`：公开对手宝可梦在角色表中的覆盖率
- `boss_target_matches_plan` / `rider_target_matches_plan`：CARD 选择与计划一致率
- `boss_grabs_rider`：Boss 误抓 rider 次数（目标 0）
- `double_ko_prep_order_ok`：Adrena→Boss→Attack 顺序达成率（基线统计）
- 先后手分层：`win_rate_going_first/second`
- 后手含羞苞：`budew_play_rate_going_second`、`budew_itchy_turns_avg_going_second`、
  `budew_lock_turns_avg_going_second`、`oa_lock_done_rate_going_second`、
  `oa_lock_by_t2_rate_going_second`

## 后手含羞苞调度

全 matchup、后手通用（非仅胡地）：

- 手牌有含羞苞且有合法空位 → 上场（末席留给缺失的海星星时例外）
- 后排有含羞苞 → Switch/撤退上前；TO_ACTIVE 选含羞苞
- 前场含羞苞 → 优先痒痒花粉，不主动换下
- Mega 必攻 / 可立即调度就绪 Mega 时让路
- 开局模拟器后手也会优先从手牌放下含羞苞

## 优先级与延期

保留：合法性闸、单体一能、能量颜色、bench overflow、861 保险窗口、
HARVEST/CONTROL、胡地专项、后手含羞苞调度。  
延期到下一轮：铝钢桥龙专项、对手愿增猿专项。

## 验证

- 单测：Pilot 57/57｜TurnPlan 26/26｜Combat target 5/5｜Matchup Alak 7/7｜Draw 9/9｜Budew GS 7/7
- 硬行为：`ready_mega_no_attack=0`、`base_attack_with_ready_mega=0`、`bad_ultra_ball_discard=0`、`boss_grabs_rider=0`
- 启发式 5×20：92% 胜；检索一致率 100%；`effective_boss_rate` 见 KPI；败因主看 `no_effective_boss`
- BC 4×20：70% 胜；检索一致率 100%；硬行为仍为 0
- 回归产物：`logs/combat_eval_effboss_5x20/`、`logs/combat_eval_effboss_bc_4x20/`
- 后手含羞苞基线（5×12）：play 13.3%，itchy 0.30 回合/局，lock 0.47 回合/局，OA-LOCK@T2 0%
