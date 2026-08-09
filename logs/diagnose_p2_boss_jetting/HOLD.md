# P2 Boss→Jetting — HOLD（不开刀）

- 日期：2026-08-10
- 权威代码：HandQual+AB + P0 CrispinWater（已提交 `55386951`）
- fade 纠偏：[`scripts/analyze_kaggle_fade.py`](../../scripts/analyze_kaggle_fade.py)（`(attackId,serial)` 去重）

## 纠偏后线上证据（55381818）

| 信号 | 值 | 解读 |
|---|---|---|
| 负局真零 Jetting | **1/12** | 仅 `91350842`（Crispin 错色）→ **P0 已修** |
| 负局真 `no_attack` | **0/12** | 旧 `no_attack:9` 为工具假信号 |
| OL-A1 / OL-B2 | 0 / 0 | AB 站住 |
| Boss 在 Jetting 可选时 PLAY | 1 次（`91352703` si=59） | 专家序允许 Boss→Jetting；**非 bug** |
| 同局随后 END（si=61）水 Mega+Jetting 可选 | 线上 action=END | **本地 HEAD hard 已选 Jetting 1150 ≫ END −1150** |

## 本地复现（91352703 si=61）

- `attack_required=True`，`_fueled_mega_must_attack=True`
- Jetting `hard/close=1150`；END / 非收束 PLAY = `-1150`
- 结论：closeout 闸在 HEAD 已生效；线上 END 属旧包/`55381818` 行为，**不构成新刀口**

## 判决

**HOLD — 不改码、不重开 CombatClose-V1。**

下一动作：等 `55386951` 出分与公局，用已纠偏 fade 再审；若新公局再现「水 Mega+Jetting 可选却 END/非攻」且本地 HEAD 同复现，再开窄刀 `_must_attack_closeout_bonus`（禁锁 primary_step）。
