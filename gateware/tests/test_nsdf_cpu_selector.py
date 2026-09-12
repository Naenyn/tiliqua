"""Host-compiled production Rust selector against double-precision score model."""
import json
import math
from pathlib import Path
import shutil
import subprocess
import numpy as np
import pytest
from nsdf_trace_analysis import decode,select
from nsdf_refinement_probe import scores_for


def test_cpu_selector_matches_model_without_frame_buffer(tmp_path):
    here=Path(__file__).parent
    exe=tmp_path/'selector'
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    subprocess.run([rustc,'--edition=2021','-O','-C','overflow-checks=on',str(here/'nsdf_selector_fixture.rs'),'-o',str(exe)],check=True)
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
        if not low:frequencies.extend([9900,10000,10100,18000,18500,19000,19900])
        else:frequencies.extend([22,23.5,25])
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


def test_fixed_point_fraction_uses_exact_bounded_arithmetic(tmp_path):
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    source=Path(__file__).parents[1]/'src/top/tuner/fw/src/nsdf_select.rs'
    exe=tmp_path/'fraction-tests'
    subprocess.run([rustc,'--edition=2021','--test','-O','-C','overflow-checks=on',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True,capture_output=True,text=True)


@pytest.mark.parametrize('frequency,tolerance',[(9900,.04),(10000,.04),(10100,.04),
                                              (18000,.16),(18500,.16),(19000,.16),(19900,.16)])
@pytest.mark.parametrize('amplitude',[72,14000])
def test_synthetic_high_sine_phase_coverage(frequency,tolerance,amplitude):
    # Known synthetic truth; the user's knob setting is not a reference clock.
    for phase in np.linspace(0,1,32,endpoint=False):
        x=np.rint(amplitude*np.sin(2*np.pi*(np.arange(674)*frequency/192000+phase)))
        result=select(scores_for(x,321),192000,600,20000,fallback=True)
        assert result and result['qualified']
        assert abs(1200*math.log2(result['hz']/frequency))<tolerance


@pytest.mark.parametrize('frequency,tolerance',[(22,.25),(23.5,.25),(25,.25),(55,.12)])
@pytest.mark.parametrize('amplitude',[72,14000])
def test_synthetic_low_sine_phase_coverage(frequency,tolerance,amplitude):
    # Known synthetic truth, not an accuracy claim for the analog capture.
    for phase in np.linspace(0,1,32,endpoint=False):
        x=np.rint(amplitude*np.sin(2*np.pi*(np.arange(604)*frequency/6000+phase)))
        result=select(scores_for(x,301),6000,20,1500,fallback=True)
        assert result and result['qualified']
        assert abs(1200*math.log2(result['hz']/frequency))<tolerance
        x=np.rint(amplitude*np.sin(2*np.pi*(np.arange(674)*frequency/192000+phase)))
        result=select(scores_for(x,321),192000,600,20000,fallback=True)
        assert result is None or not result['qualified']


@pytest.mark.parametrize('name',['nsdf-cpu-pulse-lfo.json','nsdf-cpu-integer-screen.json','nsdf-cpu-fixedpoint.json','nsdf-cpu-native-div.json','nsdf-cpu-sine55.json','nsdf-cpu-sine10k.json','nsdf-cpu-sine18500.json','nsdf-cpu-sine-lowedge.json'])
def test_physical_cpu_reports_match_exported_scores(name):
    fixture=json.loads((Path(__file__).parent/'fixtures'/name).read_text())
    assert len(fixture['cpu_reports'])==len(fixture['frames'])
    assert len(fixture['frames'])>=8
    for index,(cpu,block) in enumerate(zip(fixture['cpu_reports'],fixture['frames'])):
        report=next(decode(block.splitlines()))
        for key in ('ch','low','seq'):assert cpu[key]==str(report[key])
        words=[int(s,16) for s in block.splitlines()[1:-1]]
        scores=[w-(1<<32) if w&(1<<31) else w for w in words]
        low=report['low']=='true'
        expected=select(scores,report['fs'],20 if low else 600,1500 if low else 20000,fallback=True)
        if fixture.get('early_gate') and (report['rms_counts']<=2 or report['clipped']):
            expected=None
            assert int(cpu['reads'])==0
        else:assert 0<int(cpu['reads'])<=2*len(scores)+63
        if 'io_reports' in fixture:
            io=fixture['io_reports'][index]
            for key in ('ch','low','seq'):assert io[key]==cpu[key]
            assert int(io['reads'])==len(scores)
            assert int(io['sum'],16)==sum(words)&0xffffffff
            assert int(io['cycles'])>0
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
