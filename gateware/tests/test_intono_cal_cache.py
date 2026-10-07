"""Retained CAL plot ownership, invalidation, and bounded preparation."""
from pathlib import Path
import shutil
import subprocess


def test_calibration_cache_lifecycle(tmp_path):
    source=Path(__file__).parents[1]/"src/top/intono/fw/src/ui_scene.rs"
    compiler=shutil.which("rustc") or str(Path.home()/".cargo/bin/rustc")
    executable=tmp_path/"scene-tests"
    subprocess.run([compiler,"--edition=2021","--test",str(source),"-o",str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
