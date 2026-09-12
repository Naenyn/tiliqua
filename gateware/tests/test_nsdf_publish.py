from pathlib import Path
import subprocess
import pytest
from analyze_nsdf_schedule import analyze_comparisons,analyze_picks,analyze_schedule
import math


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


def test_physical_publication_and_baseline_agreement():
    text=(Path(__file__).parent/'fixtures/nsdf-publication-comparison.txt').read_text()
    runs=list(analyze_schedule(text));picks=list(analyze_picks(text));comp=list(analyze_comparisons(text))
    assert (len(runs),len(picks),len(comp))==(200,100,100)
    for ch in range(4):
        group=[r for r in comp if r['ch']==ch]
        assert len(group)==25
        assert all(r['src']==(2 if ch==0 else 1) and r['age']<=92 and r['win']<=202 for r in group)
        # Compare only qualified baseline snapshots; this isn't a reference
        # accuracy test or a simultaneous-window equivalence assertion.
        qualified=[r for r in group if r['bq']]
        assert len(qualified)>=23
        assert all(abs(1200*math.log2(r['mhz']/r['base']))<1.4 for r in qualified)
    assert all(r['faults']==0 for r in runs)


def test_physical_disconnected_input_does_not_publish_old_pitch():
    text=(Path(__file__).parent/'fixtures/nsdf-publication-in0-removed.txt').read_text()
    runs=list(analyze_schedule(text));picks=list(analyze_picks(text));comp=list(analyze_comparisons(text))
    assert (len(runs),len(picks),len(comp))==(200,99,99)
    absent=[r for r in comp if r['ch']==0]
    assert len(absent)==25
    assert all(r['src']==0 and r['mhz']==0 and r['gen']==0
               and r['age']==0xffffffff and r['win']==0xffffffff and not r['bq'] for r in absent)
    assert all(not r['ok'] and not r['raw'] and not r['guard'] for r in runs if r['ch']==0)
    for ch,(lo,hi) in enumerate(((0,0),(775000,778000),(174000,177000),(138000,140000))):
        if ch:
            group=[r for r in comp if r['ch']==ch]
            assert len(group)>=24
            assert all(r['src']==1 and lo<r['mhz']<hi for r in group)
        for low in (False,True):
            group=[r for r in runs if (r['ch'],r['low'])==(ch,low)]
            a,b=group[0],group[-1]
            assert (b['count']-a['count'])*1000/(b['ms']-a['ms'])==12.5
    assert all(r['faults']==0 for r in runs)
    # Capture starts after unplugging: no assertion about removal latency.
