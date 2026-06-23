# OPENING EDGE Cases (v1 checklist)

用于 `simulate_opening.py` 与后续 BDD。默认牌序见 `data/decks/starmie_froslass.csv`。

## Setup (Phase 0)

| ID | 场景 | 期望 |
|----|------|------|
| E-S1 | 起手 7 张无 Basic | 无法合法 Setup → `NONE` |
| E-S2 | 仅 1030，无 174 | S1，My-T1 再 Fan Call 或 Hilda |
| E-S3 | 1030 + 174 | A2（默认测试牌序） |
| E-S4 | Active=174，手牌无 1030 | A1，My-T1 必须 Hilda/Poffin 找 1030 |
| E-S5 | Active=1071 Meowth | F1，My-T1 下 1030 Bench + T2 Switch 线 |
| E-S6 | 禁止 Setup 第二张 1030 Bench | 第二张 1030 留手 |

## My-T1

| ID | 场景 | 期望 |
|----|------|------|
| E-T1 | 起手无能量 | G2 持续，Fan Call 不能解决能量 |
| E-T1b | 有 Hilda + 无 1030 | R1-T1 双搜 |
| E-T1c | 174 在 Bench，R4 Fan Call | 搜 3 Basic，优先非重复 1030 |
| E-T1d | My-T2+ 手牌 174 | FR 废牌，不可 PLAY |
| E-T1e | Salvatore 捷径 | 未实现 v1（待 R8） |

## My-T2 / Goal

| ID | 场景 | 期望 |
|----|------|------|
| E-G1 | Setup 1030 appearThisTurn | G4，T2 才能 EVOLVE |
| E-G2 | Mega 在 Bench 进化 | R2-T2 Switch |
| E-G3 | 无 1031，Hilda 已用 | R4-T2 Ultra Ball |
| E-G4 | 仍无 1030 | can_reach → Budew R7-T2 |
| E-G5 | 双 1031 起手 | 进化消耗 1，留 1 备份 |

## 默认牌序实测

- 奖品：860×3, 861×2, 1030
- 手牌：1030, 1031×2, 112×2, 104, 174
- **EDGE E-T1**：起手无 Water → 两回合内 Goal **可能失败**（符合真实方差）

## RECOVERY (v1 未执行，仅标注)

My-T3–T4：Lillie、Poké Pad、Crispin 等见 `01_opening.md` §5.5。
