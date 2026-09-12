"""Host-compiled production Rust selector against double-precision score model."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import numpy as np
from nsdf_trace_analysis import decode,select
from nsdf_refinement_probe import scores_for


def test_cpu_selector_matches_model_without_frame_buffer(tmp_path):
    here=Path(__file__).parent
    exe=tmp_path/'selector'
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    subprocess.run([rustc,'--edition=2021','-O',str(here/'nsdf_selector_fixture.rs'),'-o',str(exe)],check=True)
    cases=[]
    for fixture in sorted((here/'fixtures').glob('nsdf-*.json')):
        for block in json.loads(fixture.read_text())['frames']:
            lines=block.splitlines();low='low=true' in lines[0]
            words=[int(x,16) for x in lines[1:-1]]
            cases.append((low,[x-(1<<32) if x&(1<<31) else x for x in words]))
    for low in (False,True):
        fs,n,last,minimum,maximum=(6000,604,301,20,1500) if low else (192000,674,321,600,20000)
        frequencies=list(np.geomspace(minimum*1.001,maximum*.999,24))
        frequencies.extend([minimum,maximum,minimum*(1-2e-6),maximum*(1+2e-6)])
        for f in frequencies:
            for phase in (.03,.39,.81):
                p=np.arange(n)*f/fs+phase
                x=np.rint(72*np.sin(2*np.pi*p))
                cases.append((low,scores_for(x,last)))
        for level in (0,1<<20):cases.append((low,[level]*(last+1)))
        rng=np.random.default_rng(731)
        for _ in range(20):cases.append((low,scores_for(rng.integers(-12000,12001,n),last)))
    for fixture in sorted((here/'fixtures').glob('tuner-*.json')):
        x=json.loads(fixture.read_text()).get('samples',[])
        for start in range(0,len(x)-673,137):cases.append((False,scores_for(x[start:start+674],321)))
    lines=[('low' if low else 'high')+' '+' '.join(map(str,s)) for low,s in cases]
    output=subprocess.run([str(exe)],input='\n'.join(lines)+'\n',capture_output=True,text=True,check=True).stdout.splitlines()
    assert len(output)==len(cases)
    for (low,scores),line in zip(cases,output):
        expected=select(scores,6000 if low else 192000,20 if low else 600,1500 if low else 20000,fallback=True)
        if expected is None:assert line.startswith('none ');continue
        hz,clarity,qualified,original,reads=line.split()
        assert (qualified=='true')==expected['qualified']
        assert abs(1200*math.log2(float(hz)/expected['hz']))<.005
        assert abs(float(clarity)-expected['clarity'])<2e-6
        assert abs(1200*math.log2(float(original)/expected['unrefined_hz']))<.005
        assert int(reads)<=2*len(scores)+63


def test_physical_cpu_reports_match_exported_scores():
    fixture=json.loads((Path(__file__).parent/'fixtures/nsdf-cpu-pulse-lfo.json').read_text())
    assert len(fixture['cpu_reports'])==len(fixture['frames'])
    assert len(fixture['frames'])>=8
    for cpu,block in zip(fixture['cpu_reports'],fixture['frames']):
        report=next(decode(block.splitlines()))
        for key in ('ch','low','seq'):assert cpu[key]==str(report[key])
        words=[int(s,16) for s in block.splitlines()[1:-1]]
        scores=[w-(1<<32) if w&(1<<31) else w for w in words]
        low=report['low']=='true'
        expected=select(scores,report['fs'],20 if low else 600,1500 if low else 20000,fallback=True)
        assert 0<int(cpu['reads'])<=2*len(scores)+63
        assert int(cpu['cycles'])>0
        if expected is None:
            assert cpu['mhz']==cpu['raw']==cpu['ppm']=='0' and cpu['ok']=='false'
            continue
        # Float parity allowance plus one milli-Hz of serial truncation.
        tolerance=expected['hz']*(2**(.005/1200)-1)+.001
        assert abs(int(cpu['mhz'])/1000-expected['hz'])<tolerance
        assert abs(int(cpu['ppm'])/1000000-expected['clarity'])<3e-6
        qualified=expected['qualified'] and report['rms_counts']>2 and not report['clipped']
        assert (cpu['ok']=='true')==qualified
