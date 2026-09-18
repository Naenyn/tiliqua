from pathlib import Path
import subprocess

def test_reservations(tmp_path):
    source=Path(__file__).parents[1]/'src/top/tuner/fw/src/ownership.rs'
    binary=tmp_path/'ownership-tests'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','--test',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
