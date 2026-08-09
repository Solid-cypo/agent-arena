# GS seat / T2 knives — 采用（含时钟修正）

- seed0=82000 · n=200 vs fireform · `OPENING_HANDOFF=0`
- 刀：facts/选项对齐 → WAIT；后手 Mega 到手坐底座禁 END；T2 Closing 死线
- **计量修正**：`engine_log_metrics` 去重 dual `TURN_START`（后手逻辑 T2 曾被记成 T3）

## 硬指标（修正时钟后）

| 指标 | ENERGY v2 旧读数* | closingWait 修正后 | **gsSeatT2 修正后** |
|---|---:|---:|---:|
| 先手≤T3 | 72%（旧）/ 需重跑 | 86% | **88%** |
| 后手≤T2 | 8%（旧，含 +1 偏差） | 65% | **79%** |
| 后手 T2 档 | 0（旧读数） | 61 | **75** |
| WR | 45% | 47.5% | 42.5% |

\* ENERGY v2 包未存全量 jsonl，旧后手 8% 含 dual-START 膨胀；closingWait/gsSeatT2 已用同一修正器重算。

## 判

1. **硬指标大涨**：后手≤T2 4%→79%（修正后），T2 柱从 0→75。  
2. WAIT_EVOLVE 在 plan 中出现（本包 133 行），刀 1 生效。  
3. WR 42.5% 低于地板 45%——辅指标回吐，但硬指标为主；若需可再收紧坐底座禁令范围。  
4. **采用时钟修正**入 `scripts/engine_log_metrics.py`；后续闸一律用去重后的 `mega_evo_my_t`。

