# Ultra Ball 硬规则（UB-1..5）

**日期**：2026-08-01  
**实证基线**：`logs/combat_review_91000/` → `logs/ultra_ball_audit_91000/`（46 次独立使用；A=14 B=16 C=23 D=7 E=5 ok=12）  
**标注**：`logs/ultra_ball_audit_91000/label_pass.md`（A/D 全量 + B/C 抽样均为 KEEP）

卡组 3× Advanced Ball / Ultra Ball（1121）。决策拆成三闸：**何时打 / 搜什么 / 弃什么**。

---

## 硬规则

### UB-1 — pre_mega 检索白名单

若场上**无** Mega 大海星 ex，则 Ball 检索目标 ∈ `{Mega 大海星 ex, 海星星}`。

禁止：愿增猿 / 雪童子 / 雪妖女 / Mega 大雪妖女 ex / 土龙节节。

含羞苞仅 Budew 线例外（本轮不扩白名单；审阅中 `alakazam_91004` 挖含羞苞记为 D）。

**背书**：`game_alakazam_main_91000:L29`、`91005:L37`、`lucario_fighting_91001:L203`、`dragapult_91007:L54`

### UB-2 — 手持 Mega + 场上海星星 → 禁止 Ball

手牌有 Mega 大海星且场上已有海星星时：本回合优先进化，**禁止**再打 Ball。

**背书**：`game_alakazam_main_91009:L40`、`dragapult_91005:L48`、`dragapult_91006:L23`、`marnie_froslass_munk_91001:L41`

### UB-3 — 能关闭缺口的免费检索优先

仅当 Buddy-Buddy Poffin、宝可梦手环或希尔达能关闭当前 `TurnGap` 时，
才禁止 Ball。只缺 Mega 且免费检索无法取得 Mega 时，允许 Ball。

免费检索仍有效时不得作为 Ball 弃牌；其合法目标耗尽、对应角色已经完成后可动态放开。

**背书**：`game_alakazam_main_91002:L23`（弃手环挖海星星）、`91005:L37`（弃 Poffin）、`marnie_91002:L126`（连弃两张 Poffin）

### UB-4 — 动态弃牌价值

由 `discard_value(card, TurnPlan)` 统一评分。绝对保护：

- 当前/下一回合唯一路径
- 干打手所需水能、DP 唯一恶能
- 当前有效的夜之伸展器
- 终局或 DoubleKO 所需 Boss

角色完成后的重复底座、无合法目标的 Poffin/手环、被禁止的多余 Ball 和无效道具
进入低价值弃牌池。不再使用固定卡种黑名单。

**背书**：`alakazam_91007:L36`（弃水能）、`91009:L40`（弃希尔达）、`dragapult_91002:L23`（弃 Poffin+夜之伸展器）

### UB-5 — dp_urgent + 去重

仅当 Mega 大海星**已上场**且 DP 未齐时，才允许 Ball 高优先挖雪童子 / 雪妖女(104) / 愿增猿。

- 手牌已有同名目标 → 禁止再 Ball 挖该名
- 仍有可用 Pad/Poffin 时，Ball 优先级低于免费检索

**背书**：`dragapult_91000:L62`（Mega 将成/已线仍 Ball 挖土龙节节）、`dragapult_91000:L124`（手牌已有土龙节节仍挖）

---

## 代码映射

| 规则 | 函数 | 改动 |
|---|---|---|
| UB-1..5 | `turn_planner._acquire_plan` | 统一推导目标、来源、Ball 合法性和回收目标 |
| UB-4 | `turn_planner.discard_value` | live 与 opening 共用动态弃牌价值 |
| 执行 | `starmie_pilot._turn_plan_hard_bonus` | PLAY / TO_HAND / TO_BENCH / DISCARD / RECOVER 统一评分 |

源文件位于 `.agent/skills/piloting_starmie_froslass/scripts/`；运行
`python3 scripts/sync_starmie_submission.py` 同步到提交目录。

---

## 验收（2026-08-01 回归）

| 指标 | 基线 `combat_review_91000` | 改后 `combat_review_ub_91000` |
|---|---|---|
| Ball 次数 | 46 | ~32–36 |
| A（pre-Mega 误挖） | 14 | **6–9** |
| B（免费检索冲突） | 16 | **2–7** |
| C（弃牌黑名单） | 23 | **1–4** |
| D | 6 | **3–4** |
| ok 占比 | 26% | **50–72%** |
| T-C-BC 胜场 | 27/40 | **28–32/40** |

未清零的 A 多为：Mega 在奖品导致 Ball 改挖 DP、或 RL 开局接管边缘局。UB-3 严格门控 + `likely_in_deck` 已显著压低。

审计脚本：`scripts/audit_ultra_ball_review.py`  
改后审阅包：`logs/combat_review_ub_91000/`  
审计产出：`logs/ultra_ball_audit_ub_91000/`

## TurnPlan 回归（2026-08-02）

- `bad_ultra_ball_discard=0`
- `search_target_matches_goal`：T-C 97.9%，T-C-BC 97.4%
- 旧审计脚本只读取回合开始的 hand/field，无法重放同回合先发生的进化、Poffin
  和抽牌；A/D/UB2 标签可能产生时序误报。硬验收以 action-aware combat telemetry
  为准，审计包继续用于人工复核。
