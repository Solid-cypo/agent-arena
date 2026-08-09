# firefix vs HEAD 决策探针

合成局面对比 `_hard_rule_bonus` / `option_score` 赢家（`RL_ENABLED=0`）。

| Case | 含义 | firefix | HEAD | 分叉? |
|---|---|---|---|---|
| `A_evolve66_vs_end` | 手持66+场上弟弟 → 应 EVOLVE_66 | **EVOLVE_66** (draw=FORBID) | **EVOLVE_66** (draw=FORBID/TP-DRAW-HOLD) | ✅ |
| `B_gf_budew_no_yank_staryu` | 先手T1含羞苞 → 应 ITCHY（禁切海星） | **ITCHY** (draw=FORBID) | **END** (draw=FORBID/TP-DRAW-HOLD) | ❌ |
| `C_mega_must_fire_not_retreat` | Mega有水 → 应 JETTING | **JETTING** (draw=FORBID) | **JETTING** (draw=FORBID/TP-DRAW-HOLD) | ✅ |
| `D_promote_mega_not_watergun` | 干海星+替补Mega → 应 SWITCH/RETREAT 上位 | **PLAY_SWITCH** (draw=FORBID) | **RETREAT** (draw=FORBID/TP-DRAW-HOLD) | ❌ |
| `E_861_must_resentful` | 861有水手牌≥4 → 应 RESENTFUL | **RESENTFUL** (draw=FORBID) | **RESENTFUL** (draw=FORBID/TP-DRAW-HOLD) | ✅ |
| `F_promote_861_not_fuel_munk` | 愿增猿前+有油861 → 应 SWITCH/RETREAT | **PLAY_SWITCH** (draw=FORBID) | **PLAY_SWITCH** (draw=FORBID/TP-DRAW-HOLD) | ✅ |

## 代码分叉（已坐实）

1. **EVOLVE_66**：firefix 无条件 `DOMINATE_OPEN_PATH`；HEAD 可被 TurnPlan/`draw_axis` `FORBID` → **`-DOMINATE_OPEN_PATH`**。
2. **硬规则前缀**：HEAD 在 ops 块前插入 must_attack / mega_clock / TurnPlan / Alak / Budew Wave，可短路 66/861/OPENING PATH。
3. **861**：firefix ANY-phase 强制 Resentful；HEAD 叠加伤害门/切回海星。
4. **HR-8**：firefix 861 优先；HEAD 注释为 104 first。

负局日志：`logs/h2h_audit_firefix_vs_head/AUDIT_USER_CLAIMS.md`

明细 JSON：`data/restore_peaks/decision_diff_probe.json`

## Knife A 已落地（2026-08-08）

- 源：`.agent/skills/.../starmie_pilot.py` → sync → `submission_starmie`
- 探针 Case A：**EVOLVE_66 vs EVOLVE_66 ✅**（Hilda 被 demote 到 −920）
- 单测：`tests/test_wave_u_online_leaks.py` 11 passed（含 `test_knife_a_evolve66_beats_hilda_despite_tp_draw_hold`）
- 短闸 H2H vs firefix n=40 seed82000：**40%**（对照此前 n=100 为 34%；样本小，仅作方向信号）

