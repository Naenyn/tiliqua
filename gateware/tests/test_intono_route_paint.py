"""Sparse route damage and per-bank ownership checks in the firmware module."""
from pathlib import Path
import shutil
import subprocess


def test_route_paint(tmp_path):
    root = Path(__file__).parents[1] / 'src/top/intono/fw/src'
    source = tmp_path / 'route.rs'
    source.write_text(f'''#[path="{root / 'ui_canvas.rs'}"] mod ui_canvas;
mod route_group {{ #[derive(Clone,Copy)] pub struct Layout {{pub inputs:[u8;4],pub outputs:[u8;4]}} }}
#[path="{root / 'ui_route.rs'}"] mod ui_route;
''')
    compiler = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc')
    executable = tmp_path / 'route-tests'
    subprocess.run([compiler, '--edition=2021', '--test', str(source), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
