"""Build distinct Kaggle submission tarballs for the Starmie pilot.

Variants:
  v1off  - pure v1 hard rules (RL proposer OFF)           [best completion/WL]
  rlbc   - v1 + RL proposer (BC-only DAgger retrain)      [proposer-led]
  rlppo  - v1 + RL proposer (PPO+BC DAgger retrain)       [proposer-led, PPO]

Each bundle is self-contained: the RL default is baked into starmie_pilot.py
(Kaggle does not set custom env vars) and the matching rl_opening.{npz,json}
is installed.
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SUB = ROOT / "submission_starmie"
PILOT = SUB / "pilot"

NPZ = {
    "v1off": ("/tmp/rl_opening_71pct", "0"),   # use restored 71pct bundle
    "rlbc":  ("/tmp/rl_opening_dagger3bc", "1"),
    "rlppo": ("/tmp/rl_opening_dagger3", "1"),
}


def _set_rl_default(pilot_dir: Path, default: str) -> None:
    p = pilot_dir / "starmie_pilot.py"
    txt = p.read_text(encoding="utf-8")
    old = 'os.environ.get("RL_ENABLED", "0")'
    new = f'os.environ.get("RL_ENABLED", "{default}")'
    assert old in txt, "RL_ENABLED default line not found"
    p.write_text(txt.replace(old, new), encoding="utf-8")


def _install_npz(pilot_dir: Path, prefix: str) -> None:
    shutil.copy(f"{prefix}.npz", pilot_dir / "rl_opening.npz")
    shutil.copy(f"{prefix}.json", pilot_dir / "rl_opening.json")


def main():
    # Stage the 71pct npz from the backup (current submission_starmie already has it).
    shutil.copy(PILOT / "rl_opening.npz", "/tmp/rl_opening_71pct.npz")
    shutil.copy(PILOT / "rl_opening.json", "/tmp/rl_opening_71pct.json")

    for name, (prefix, default) in NPZ.items():
        stage = ROOT / f"_stage_{name}"
        if stage.exists():
            shutil.rmtree(stage)
        shutil.copytree(SUB, stage, dirs_exist_ok=False,
                        ignore=shutil.ignore_patterns("__pycache__"))
        _set_rl_default(stage / "pilot", default)
        _install_npz(stage / "pilot", prefix)
        out = ROOT / f"submission_starmie_{name}.tar.gz"
        # tar from ROOT so the archive top is submission_starmie_<name>/
        import tarfile
        with tarfile.open(out, "w:gz") as tf:
            tf.add(stage, arcname=f"submission_starmie_{name}")
        shutil.rmtree(stage)
        # report
        rl = "OFF" if default == "0" else "ON"
        print(f"built {out.name}: RL={rl} npz={Path(prefix).name}  ({out.stat().st_size} B)")


if __name__ == "__main__":
    main()
