# Peak archive — ClosableNsRockInn

- Kaggle: [`55517032`](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/submissions) publicScore **549.8**（现役最佳；fade 快照也曾记 ~559）
- Stack: LeakFix Dry861 + **Closable861** + **NsWater861** + **RockInn**（Jetting bench-50 经 Rock Inn 常合法）
- Deck: 2× Staryu / **4× Risky Ruins** / Water×5 + Dark×3（**无引火 17**）
- Local fade: `data/kaggle_episodes/review_ClosableNsRockInn_55517032/`
- Frozen: 2026-08-16

## 近似说明（重要）

线上 `55517032` 的提交 blob **未入库**，无法字节级还原。本档为：

- **deck / main / weights / cg**：对齐 LeakFix 系 Closable 产品卡组（废墟×4）
- **pilot**：工作区 Closable 政策栈上剥 IgnitionNebula / LilliePreserve 主 helper 后的可回滚近似；仍可能残留无卡组入口的引火符号常量（无 `17` 时路径不应开火）

**分数权威仍以线上 `55517032` 为准。** 若 Ignition 公局掉分，优先用本目录或配套 tar 回滚再打包。

## Restore

```bash
cp -a data/restore_peaks/closableNsRockInn_55517032/{deck.csv,main.py,weights.json,cg,pilot} submission_starmie/
# 注意：package_starmie.py 会用 data/decks/starmie_froslass.csv 覆盖 deck.csv
# 回滚时请先把 data/decks/... 与 skill scripts/deck.csv 也改回废墟×4，再 package
python3 scripts/package_starmie.py
```

配套 tar：`data/restore_peaks/submission_starmie_closableNsRockInn_55517032.tar.gz`

Do **not** overlay IgnitionNebula / LilliePreserve / EmptyBench on this peak without a new gate.
