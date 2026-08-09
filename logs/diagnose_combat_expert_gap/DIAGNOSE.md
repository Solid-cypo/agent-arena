# D0/D1 — 专家中盘/战斗差距审计（HEAD @ Opening seats）

**日期**：2026-08-09  
**锚定**：`submission_starmie` vs fireform；H2H `logs/h2h_audit_engineSeats_n200`；BC `logs/combat_eval_midgame_baseline_bc_4x20/`  
**政策**：[`TURN_PLAN_POLICY_20260802.md`](../../references/rulebook/TURN_PLAN_POLICY_20260802.md) · 专家运转/战斗原文

---

## D1 基线数字

### BC 4×20 seed93000（alakazam / dragapult / lucario / marnie）

| KPI | 值 |
|---|---:|
| WR | **56.25%** (45/80) |
| `effective_boss_rate` | **63.6%** |
| `ineffective_boss_count` | 12 |
| `no_effective_boss` 占负局 | **82.9%** |
| `double_ko_prep_order_ok` | **31.4%** (n=35) |
| `boss_grabs_rider` | **0** |
| `ready_mega_no_attack` | **0** |
| `base_attack_with_ready_mega` | **2**（警戒，非 0） |
| `boss_per_game` | 0.41 |

对照 Wave U BC：WR 67.5% · eff_boss 55.9% · prep_ok **34.4%** — 本包 WR 回吐、prep 仍断。

### Plan discipline（engineSeats n=200）

| KPI | 值 |
|---|---:|
| evo_compliance | 100% |
| locked_compliance（仅 EVOLUTION/ENERGY） | 95.2% |
| **DISPATCH** compliance | **49.1%** (n=330) |
| **ADRENA** compliance | **14.3%** (n=105) |
| **BOSS** primary_step 行数 | **0** |

DISPATCH MAIN 失败形：PLAY 杂牌 40 / END 17 / 成功 Retreat 64。  
ADRENA MAIN：ABILITY 成功仅 15；RETREAT/ATTACH/END 抢步常见。

### H2H lift（engineSeats，tag≠死因校验）

| 信号 | lift P(·\|loss)−P(·\|win) | 判 |
|---|---:|---|
| `zero_boss` / boss_play=0 | −0.01 | **≠死因** |
| `mega_gap>0` | −0.05 | ≠死因 |
| `mega_evolved_no_attack` | +0.08（n=9） | 稀有；辅监 |

---

## 专家矩阵（R/C）现状

| ID | 专家要求 | 现状 | 依据 |
|---|---|---|---|
| R1–R2 | 打手/底座检测 | 已覆盖 | TurnGap |
| R3–R4 | 精确检索 / 两回合路径 | 部分 | Opening seats + plan-step；本波不重开 |
| R5–R6 | DP / 找愿增猿 | 部分 | 政策在；M/N NO-GO 不抬建设 |
| R7 | 土龙≤2 不急抽 | 已覆盖 | Opening 座位 + DrawPlan |
| R8 | Active 土龙优先 | 部分 | Wave F |
| R9 | 含羞苞/铝钢/胡地 | 已覆盖 | F3 + GS Budew |
| C1 | Mega 必攻、禁底座攻 | 部分 | `ready_mega_no_attack=0`；`base_attack_with_ready_mega=2` |
| C2 | 861≥2 奖 | 已覆盖 | froslass_exception |
| **C3** | **Adrena→Boss→Jetting** | **缺口** | prep_ok 31%；BOSS step=0 |
| C4–C5 | 胡地/对手猿 | 已覆盖 | matchup / ban_froslass |
| C6 | 有效 Boss 目标 | 部分 | eff_boss 64%；负局仍高标签 |

---

## Top1 死因链（机制）

```text
attack_required ∧ active_ready_mega
  → _plan_primary_step 直接 return None
  → BOSS/ADRENA 永不成为 primary_step，也不进 _PLAN_STEP_LOCKED
  → 仅靠 must_close 软竞分；杂 PLAY/Retreat/END 可抢步
  → double_ko_prep_order_ok ≈ 31%，专家双穿序断裂
```

次要：`DISPATCH` 未锁（compliance 49%）→ 该上 Mega 时 END/铺杂牌。

**唯一杠杆（CombatClose-V1）**：  
[`starmie_pilot.py`](../../.agent/skills/piloting_starmie_froslass/scripts/starmie_pilot.py) `_plan_primary_step` + `_PLAN_STEP_LOCKED`  
辅：[`turn_planner.py`](../../.agent/skills/piloting_starmie_froslass/scripts/turn_planner.py) `_combat_plan` 将 BOSS 排在 ADRENA 之后（对齐政策 Adrena→Boss→Jetting）。

---

## 假设卡（H）

```text
Wave: CombatClose-V1
锚定: Opening seats + Wave I+L+U；engineSeats_n200；BC midgame baseline
死因: 双穿前置序未执行（BOSS/ADRENA 不进 primary_step / 未锁）
杠杆: _plan_primary_step 在 active_ready_mega 时仍返回 required[0]；
      锁定 ADRENA/BOSS/DISPATCH；_combat_plan 中 BOSS 置于 ADRENA 之后
不做: DP prep 序（104/DARK）、PLAY Munk 抬权、861 窗、Opening demote
预期变好: double_ko_prep_order_ok ≥ 36.4%（+5pp）或 BOSS primary 行数>0 且 ADRENA MAIN compliance↑
预期不变: ready_mega_no_attack=0；boss_grabs_rider=0；Opening 硬指标先≤T3≥83 后≤T2≥74
证伪: prep_ok 不升且 seat B<40% 或 Opening 合计<78%
回滚: revert 本刀 + AUTOPSY
```

---

## G0 结果 — **证伪，已回滚**（2026-08-09）

详见 [`logs/h2h_audit_combatClose_n200/GATE.md`](../h2h_audit_combatClose_n200/GATE.md)。

| 项 | 结果 |
|---|---|
| prep_ok | 31.4% → **28.6%** |
| Opening 合计 | 81.5% → **77.5%**（触回滚线） |
| BOSS primary 行 | 0 → 129（杠杆「露面」有效，但无 KPI 收益） |
| ADRENA compliance | 仍 ~14% |

**已证伪**：仅靠 primary_step 露面 + 锁 ADRENA/BOSS/DISPATCH 可修双穿序。  
政策面停在 Opening seats（`f54dab6` / Kaggle 55365769）；CombatClose 不入库。
