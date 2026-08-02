# TurnPlan 回合目标政策

**日期**：2026-08-02  
**实现**：`.agent/skills/piloting_starmie_froslass/scripts/turn_planner.py`  
**提交同步**：`submission_starmie/pilot/turn_planner.py`

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

## CombatPlan

- Active Mega 有对应能量，或 bench 就绪 Mega 可立即调度：
  `attack_required=True`。
- 必攻时禁止 END 和普通底座攻击；Budew 仅在无就绪 Mega 的后手拖延窗口使用。
- 普通建设动作不得压过攻击。
- 海星 DoubleKO 顺序：`Adrena → Boss（需要时）→ Jetting Blow → rider`。
- rider 阈值：无可转移伤害为 50 HP；可转移至少 30 时为 80 HP。
- 前场可被 120 击倒时不打 Boss；Boss 不得抓走 rider。

## AcquirePlan

- 检索目标只来自当前缺口；已持有的主打手缺件视为路径已锁定。
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

## 优先级与延期

保留：合法性闸、单体一能、能量颜色、bench overflow、861 保险窗口、
HARVEST/CONTROL、胡地专项。  
延期到下一轮：铝钢桥龙专项、对手愿增猿专项及 matchup 级 Boss 威胁表。

## 验证

- 单测：`56/56 + 16/16 + 9/9 + opening 20/20`
- 硬行为：`ready_mega_no_attack=0`、`base_attack_with_ready_mega=0`
- 检索/弃牌：目标一致率 97% 以上，`bad_ultra_ball_discard=0`
- 回归产物：`logs/combat_review_simplified_dp_12/`、
  `logs/combat_eval_simplified_dp_tc_5x60/`、
  `logs/combat_eval_simplified_dp_bc_4x60/`
- 简化 DP 完成率：T-C 29.7%，T-C-BC 28.8%，均达到 25% 门槛
- 伤害生成器上线率：69.7% / 72.1%
- 其中危险废墟上线率：52.3% / 56.7%
