# ops_firefix（已解包）vs 当前 HEAD

## 包位置

- 源：[`.agent/submission_starmie_ops_firefix.tar.gz`](../../.agent/submission_starmie_ops_firefix.tar.gz)（你下载）
- 副本+解包：[`ops_firefix_55115028/`](ops_firefix_55115028/)（=提交描述对应的那版）

## Kaggle「提交页下载 Agent」结论

| 通道 | 结果 |
|---|---|
| `kaggle competitions` CLI | **无** submission/agent download 子命令（仅 episodes/replay/logs） |
| SDK `CompetitionApiService` | 有 GetSubmission / episode logs / data download，**无** DownloadSubmission |
| 常见 REST/内部 URL 探测 | 均 404/HTML，拿不到 tar |

→ **自动化下载目前不通**；网页按钮若存在，多半走需登录 Cookie 的前端私有接口。你手动下到 `.agent/` 是正确路径。若还有 `combat_loop` / `combat_v1` / `surplus861`，请同样丢进 `.agent/` 或 `data/restore_peaks/`。

## 结构差（核心）

| | ops_firefix | HEAD |
|---|---:|---:|
| `starmie_pilot.py` | **3202** | **5297** |
| `turn_planner.py` | **无** | 有（1275） |
| `matchup_alakazam.py` | **无** | 有 |
| `DOMINATE_OPEN_PATH` | 49 | 151 |
| TurnPlan / must_attack | 0 | 有 |
| `opening_planner.py` | 1683 | 1687（几乎同代，md5 不同） |
| `opening_bridge.py` | 870 | 869 |

`starmie_pilot` unified diff 约 **+2571 / -476**（HEAD 相对 firefix）。

Opening 模块（planner/bridge/bench）与 firefix **同族**；大分裂在 **pilot 中盘总控**：firefix 无 TurnPlan，靠 DOMINATE + Resentful/861 fire loop；HEAD = TurnPlan + Wave 叠刀。

## 建议下一步

1. 把 firefix 当 **Opening+ops 金标**，对同 seed 跑 hybrid opening / megaT3（不必先改 HEAD）。
2. 若你还能下到 **`combat_loop`（557）** / **`surplus861_deckfix`（524）**，一并解包，组成「能打分的 Opening 世代」三联对照。
3. 差分结论出来前，**不要**再叠 Wave / 盲提。
