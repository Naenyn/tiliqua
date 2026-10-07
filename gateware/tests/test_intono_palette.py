"""Contrast invariants for palette-dependent graphical states."""
from pathlib import Path
import shutil
import subprocess


def test_palette_key_membership_contrast(tmp_path):
    source = Path(__file__).parents[1] / "src/top/intono/fw/src/ui_theme.rs"
    compiler = shutil.which("rustc") or str(Path.home() / ".cargo/bin/rustc")
    executable = tmp_path / "palette-tests"
    subprocess.run([compiler, "--edition=2021", "--test", str(source),
                    "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
