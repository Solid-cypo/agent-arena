# Phase 3 — HARVEST（大雪妖女收割）

> **前置**：[01_opening.md](./01_opening.md) Goal 达成 → AGGRESSION；[02_draw_axis.md](./02_draw_axis.md) 过牌轴。  
> **与 AGGRESSION 边界**：AGGRESSION 只维护 **Froslass `[104]` 引擎** + 大海星 Jetting；**861 进化与 Resentful 攻击仅在 HARVEST**。

---

## 1. 阶段判定（已有 · `phase_fsm.py`）

| 条件 | Primary |
|---|---|
| Active = 1031 + 水能 | AGGRESSION |
| Active = 861 | HARVEST |
| 曾完成 Opening，1031 离场且场上无 1031 | HARVEST |
| 否则（Opening 未完成） | OPENING |

`CONTROL` 为 modifier（`prize_self < prize_opp`），可与 HARVEST 叠加。

---

## 2. 与 AGGRESSION 的冲突隔离

| 层 | AGGRESSION | HARVEST |
|---|---|---|
| **HR-8 / HR-8b** | 优先 Snorunt→**104**；**禁止** 861（`-DOMINATE`） | 允许 861；104 bench lock 见 HR-H2 |
| **HR-6** | 大海星 Jetting / Nebula | 不强制（Active 通常为 861 或 backup） |
| **HR-2 Adrena** | My-T2+ 有伤可转 | 同左（Munk 仍在 bench） |
| **S-1 `froslass_harvest`** | **不生效**（已 gate） | opp_hand≥5 或刚拿奖 → 软加权 861 进化 |
| **Synergy Pad/Snorunt** | T2–T8 三坑 | 不铺新 Opening 线；保 104 引擎 |

**原则**：HARVEST 不回头走 Opening 路径（`opening_bridge` 仅在 `phase.primary == OPENING"` 触发）。

---

## 3. 硬规则清单（Layer 1 · HR-H1–H8 已实现）

优先级在 synergy/adrena 之后、legacy HR-* 之前；同分按 Pri 小者优先。

| Pri | ID | 触发 | 动作 | 分数带 |
|---:|---|---|---|---|
| H1 | **HR-H1** | HARVEST + Active 非 861 + 手/场可进化 861 + **104 已在场** | EVOLVE → Mega Froslass ex | `DOMINATE` (1000) | ✓ |
| H2 | **HR-H2** | HARVEST + 仅 1 只 104 且进化目标为「最后一只 104」 | 需 bench 有 Snorunt 备份，否则 **block 861**（= HR-8b） | `-DOMINATE` | ✓ (HR-8b) |
| H3 | **HR-H3** | HARVEST + Active 861 + 有水 + Resentful 可用 | ATTACK Resentful (1240) | `DOMINATE_ATTACK` (975) | ✓ |
| H4 | **HR-H4** | HARVEST + opp_hand×50 ≥ 200 | Resentful **优于** Absorbing Snow | 同 H3 | ✓ |
| H5 | **HR-H5** | HARVEST + Nebula 式 KO 不在表 | 禁止 END 当 861 可攻击 | `-DOMINATE` | ✓ |
| H6 | **HR-H6** | 手牌 Judge + 本回合未 Resentful | **禁止 PLAY Judge**（先打后 Judge） | `-DOMINATE` | ✓ |
| H7 | **HR-H7** | 上回合己方 Active 1031 被 KO + 手有 Unfair Stamp | PLAY Stamp (1080) | `DOMINATE_OPEN` (1130) | ✓ |
| H8 | **HR-H8** | HARVEST + Boss + 奖品路径 bench 目标 | PLAY Boss / gust CARD | `DOMINATE_SUPPORT` (960) | ✓ |
| H2w | **HR-H2** | HARVEST + Active 861 缺水 | ATTACH 水能 → Active | `DOMINATE_PLUS` (1100) | ✓ |

### 3.1 与现有实现对齐

```text
已实现                          本 Phase 待补
─────────────────────────────────────────────────
HR-H1–H8 Layer 1 (_harvest_hard_rules)   —
HR-H2 861 贴水 + HR-H5b END 封锁
harvest_ko_last_turn → HR-H7 Stamp
HR-8b block 861 ∉ HARVEST
phase_fsm → HARVEST
froslass_harvest 软维 (HARVEST)
audit_harvest.py KPI
HR-8 evolve 104
```

### 3.2 禁忌（deck_knowledge §7）

- **Judge 在 Resentful 之前**：Judge 对称抽 4，Resentful 50×手牌 → 伤害暴跌。
- **OPENING 线 Pad 搜 861**：Pad 不可搜 Rule Box / Mega ex。
- **AGGRESSION 内进化 861**：与 Froslass 104 引擎冲突，已由 HR-8b 封锁。

---

## 4. 软维（Layer 2 · 可训练）

| Dim | 条件 | 与硬规则关系 |
|---|---|---|
| `froslass_harvest` | HARVEST + EVOLVE 861 + (opp_hand≥5 ∨ opp_just_prized) | 硬规则未命中时的 nudge；**不在 AGGRESSION 生效** |
| Resentful nudge | HARVEST + ATTACK + opp_hand×50≥200 | 辅助 HR-H3，不 override DOMINATE_ATTACK |
| `boss_gust_path` | HARVEST 收尾 gust | 与 AGGRESSION 共用 |

---

## 5. 验收 KPI（草案）

| 指标 | 目标 | 审计方式 |
|---|---|---|
| HARVEST 窗口内 Resentful ≥200 伤 | ≥ 70% | 待 `audit_harvest.py` |
| AGGRESSION 内误进化 861 | 0 | 现有 synergy 审计 + 进化事件 |
| Judge 在 Resentful 前 PLAY | 0 | 回合事件序 |

---

## 6. 实现顺序（建议）

1. `HR-H1` / `HR-H3` / `HR-H6` in `starmie_pilot.py`
2. `audit_harvest.py`（镜像 `audit_aggression_abilities.py`）
3. `HR-H7` Unfair Stamp + `DR-6` 过牌轴
4. ~~Phase 4 CONTROL~~ → 见 [04_control.md](./04_control.md)

---

## 7. 相关文件

| 文件 | 角色 |
|---|---|
| `phase_fsm.py` | HARVEST 转移 |
| `starmie_pilot.py` | HR-8b、HR-H*、软维 gate |
| `opening_bridge.py` | 仅 OPENING；HARVEST 不调用 |
| `deck_knowledge.md` §链 D | 设计来源 |
