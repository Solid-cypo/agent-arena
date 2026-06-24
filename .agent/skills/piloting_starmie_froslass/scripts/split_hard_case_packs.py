#!/usr/bin/env python3
"""Split exported hard-case logs into 10-case packs (7:3:1) with Chinese card names."""
from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from opening_log_formatter import card_names_zh, format_log_text  # noqa: E402


def to_chinese(text: str) -> str:
    return format_log_text(card_names_zh(text))


def _log_path(src_dir: Path, case: dict) -> Path:
    seed = case["seed"]
    label = case["sample_label"]
    miss = case["miss_class"]
    return src_dir / f"seed{seed}_{label}_{miss}.log"


# 11 包 × 10 条，合计 70 负 / 30 待优化 / 10 正（≈7:3:1）
PACK_COMPOSITIONS: list[tuple[int, int, int]] = (
    [(6, 3, 1)] * 7 + [(7, 3, 0)] * 1 + [(7, 2, 1)] * 3
)


def split_packs(
    src_dir: Path,
    out_root: Path,
    *,
    pack_size: int = 10,
    compositions: list[tuple[int, int, int]] | None = None,
) -> dict:
    """Split into packs; each tuple is (negative, to_optimize, positive) counts."""
    manifest_path = src_dir / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = data["cases"]
    neg = [c for c in cases if c["sample_label"] == "negative"]
    opt = [c for c in cases if c["sample_label"] == "to_optimize"]
    pos = [c for c in cases if c["sample_label"] == "positive"]
    comps = compositions or PACK_COMPOSITIONS
    if sum(sum(c) for c in comps) != len(cases):
        raise ValueError("Composition total != case count")
    if any(sum(c) != pack_size for c in comps):
        raise ValueError("Each pack must sum to pack_size")

    out_root.mkdir(parents=True, exist_ok=True)
    pack_summaries: list[dict] = []
    ni = no = np = 0

    for i, (take_neg, take_opt, take_pos) in enumerate(comps):
        pack_id = f"pack_{i + 1:02d}"
        pack_dir = out_root / pack_id
        pack_dir.mkdir(parents=True, exist_ok=True)
        batch = (
            neg[ni : ni + take_neg]
            + opt[no : no + take_opt]
            + pos[np : np + take_pos]
        )
        ni += take_neg
        no += take_opt
        np += take_pos
        pack_cases = []
        for case in batch:
            src_log = _log_path(src_dir, case)
            if not src_log.is_file():
                raise FileNotFoundError(src_log)
            zh_body = to_chinese(src_log.read_text(encoding="utf-8"))
            # 头部标签中文化
            zh_body = zh_body.replace("SAMPLE_LABEL=negative (负面样本)", "样本类型=负面")
            zh_body = zh_body.replace("SAMPLE_LABEL=to_optimize (待优化样本)", "样本类型=待优化")
            zh_body = zh_body.replace("SAMPLE_LABEL=positive (正面样本)", "样本类型=正面")
            out_name = f"seed{case['seed']}_{case['sample_label']}_{case['miss_class']}.log"
            (pack_dir / out_name).write_text(zh_body, encoding="utf-8")
            pack_cases.append({**case, "log_file": out_name})

        pack_manifest = {
            "pack_id": pack_id,
            "ratio": f"{take_neg}:{take_opt}:{take_pos}",
            "counts": {
                "negative": take_neg,
                "to_optimize": take_opt,
                "positive": take_pos,
            },
            "cases": pack_cases,
        }
        (pack_dir / "manifest.json").write_text(
            json.dumps(pack_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tar_path = out_root / f"{pack_id}.tar.gz"
        with tarfile.open(tar_path, "w:gz") as tar:
            for f in pack_dir.iterdir():
                tar.add(f, arcname=f"{pack_id}/{f.name}")
        pack_summaries.append(
            {
                "pack_id": pack_id,
                "tar": str(tar_path),
                "seeds": [c["seed"] for c in batch],
            }
        )

    index = {
        "source": str(src_dir),
        "output": str(out_root),
        "packs": len(comps),
        "pack_size": pack_size,
        "ratio_note": "7×(6:3:1) + 1×(7:3:0) + 3×(7:2:1) ≈ 全局 7:3:1",
        "card_names": "zh",
        "pack_summaries": pack_summaries,
    }
    (out_root / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return index


def main() -> None:
    p = argparse.ArgumentParser(description="Split hard-case logs into packs of 10 (6:3:1 ≈ 7:3:1)")
    p.add_argument(
        "--src",
        type=str,
        default="",
        help="Source export dir with manifest.json",
    )
    p.add_argument(
        "--out",
        type=str,
        default="",
        help="Output packs root",
    )
    args = p.parse_args()
    scripts = Path(__file__).resolve().parent
    default_src = scripts.parent / "logs" / "hard_cases" / "20260624_193417"
    src = Path(args.src) if args.src else default_src
    out = Path(args.out) if args.out else src.parent / "packs_zh"
    index = split_packs(src, out)
    print(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"\n{index['packs']} packs -> {out}")


if __name__ == "__main__":
    main()
