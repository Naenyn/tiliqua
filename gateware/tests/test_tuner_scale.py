"""Exercise the real fixed-point scale engine without target hardware."""
from pathlib import Path
import shutil
import subprocess


def test_scale_engine(tmp_path):
    source = Path(__file__).parents[1] / 'src/top/tuner/fw/src/scale.rs'
    compiler = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc')
    executable = tmp_path / 'scale-tests'
    subprocess.run([compiler, '--edition=2021', '--test', str(source), '-o',
                    str(executable)], check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
