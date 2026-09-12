from pathlib import Path
import subprocess
import pytest
from analyze_nsdf_schedule import analyze_comparisons


def test_actual_publication_lifecycle_and_audio_window_age(tmp_path):
    here=Path(__file__).parent;exe=tmp_path/'publish'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O','-C','overflow-checks=yes',
                    str(here/'nsdf_publish_fixture.rs'),'-o',str(exe)],check=True)
    subprocess.run([exe],check=True)


def test_comparison_descriptor_validation():
    line='NSDF COMP ch=0 ms=100 mhz=880000 src=1 gen=1 age=20 win=130 base=880100 bq=true bage=10\n'
    assert list(analyze_comparisons(line))[0]['mhz']==880000
    for bad in (line.replace('age=20','age=253'),line.replace('win=130','win=129'),
                line.replace('gen=1','gen=0'),line.replace('bage=10','bage=251'),
                line.replace('src=1','src=0')):
        with pytest.raises(ValueError):list(analyze_comparisons(bad))
