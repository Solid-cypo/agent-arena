# ops_firefix vs HEAD Opening 对照

- 对手：`walrein_control`  ·  每侧 N=200  ·  seed0=71000
- 时间：2026-08-08T01:56:47.042803+08:00

| 包 | open | megaT3 | megaT4 | win | W-L-D |
|---|---:|---:|---:|---:|---|
| firefix | 82.0% | 76.0% | 80.5% | 94.5% | 189-9-2 |
| head | 92.0% | 81.0% | 85.0% | 93.0% | 186-14-0 |

H2H（N=80）：firefix **46** – head **34** （draw 0），firefix 胜率 **57.5%**

历史 ops_firefix ship 闸（不同 seed 批次）：Hybrid 3×200 open **81.2%** / megaT3 **77%** / win **96%**。

## 解读（同 seed0=71000，N=200 vs walrein；H2H N=80）

| | firefix | HEAD | Δ (HEAD−firefix) |
|---|---:|---:|---:|
| open | 82.0% | **92.0%** | **+10.0pp** |
| megaT3 | 76.0% | **81.0%** | +5.0pp |
| megaT4 | 80.5% | **85.0%** | +4.5pp |
| win vs walrein | **94.5%** | 93.0% | −1.5pp |
| H2H | **57.5%** (46–34) | 42.5% | firefix 胜 |

配对：Opening 不一致 46/200（仅 firefix 完成 13，仅 HEAD 完成 33）；megaT3 不一致 68/200。

**结论：** 对弱启发式（walrein），HEAD 的 Opening/Mega 时钟指标 **并不差于** firefix，甚至更高；但 **H2H 里 firefix 仍打赢 HEAD ~57%**——说明线上掉分主因更可能在 **中盘对强策略的决策**（TurnPlan/Wave），而不是 Opening KPI 本身掉了。历史 ship 闸 open 81.2% 与本次 firefix 82.0% 吻合，包可信。

## ⚠ 纠正（日志审查后）

对 walrein 的 open/megaT3 偏高 **不能**否定录像问题。  
HEAD vs firefix H2H 审计（n=100）：**34%**，且 OL-A2/E1/侧基础/乱换位等在负局日志中大量复现。  
见 [`logs/h2h_audit_firefix_vs_head/AUDIT_USER_CLAIMS.md`](../../logs/h2h_audit_firefix_vs_head/AUDIT_USER_CLAIMS.md)。

