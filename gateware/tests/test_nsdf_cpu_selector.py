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
        fs,n,last,minimum,maximum=(6000,674,621,20,1500) if low else (192000,674,621,600,20000)
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
        expected=select(scores,6000 if low else 192000,20 if low else 600,1500 if low else 20000,
                        fallback=True,refine_quality=True,reject_early_outside=low)
        if expected is None:assert line.startswith('none ');continue
        hz,clarity,qualified,original,reads=line.split()
        assert (qualified=='true')==expected['qualified']
        assert abs(1200*math.log2(float(hz)/expected['hz']))<.005
        assert abs(float(clarity)-expected['clarity'])<2e-6
        assert abs(1200*math.log2(float(original)/expected['unrefined_hz']))<.005
        assert int(reads)<=2*len(scores)+63


def test_fixed_point_fraction_uses_exact_bounded_arithmetic(tmp_path):
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    source=Path(__file__).parents[1]/'src/top/intono/fw/src/nsdf_select.rs'
    exe=tmp_path/'fraction-tests'
    subprocess.run([rustc,'--edition=2021','--test','-O','-C','overflow-checks=on',str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True,capture_output=True,text=True)


def test_native_repeating_interval_covers_calibration_handoff(tmp_path):
    # Controlled synthetic truth, motivated by live ~1017-Hz variation.
    # This does not claim to reproduce Generate3's exact physical waveform.
    here=Path(__file__).parent;exe=tmp_path/'selector'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    '-C','overflow-checks=on',str(here/'nsdf_selector_fixture.rs'),'-o',str(exe)],check=True)
    lines=[];truth=[];old=[]
    for frequency in (980,1000,1016.71,1100,1200,1250,1300,1400,1490,1703,2000,4000,10000,18500,19900):
        for amplitude in (72,14000):
            for phase in np.linspace(0,2,32,endpoint=False):
                p=np.arange(674)*frequency/192000+phase
                x=np.rint(amplitude*(np.sin(2*np.pi*p)+.0076*np.sin(np.pi*p+.7)+.0091*np.sin(3*np.pi*p+.4)))
                scores=scores_for(x,621)
                lines.append('high '+' '.join(map(str,scores)))
                truth.append((frequency,amplitude))
                if frequency==1016.71 and amplitude==14000:
                    previous=select(scores[:322],192000,600,20000,fallback=True)
                    old.append(1200*math.log2(previous['hz']/frequency))
    output=subprocess.check_output([exe],input='\n'.join(lines)+'\n',text=True).splitlines()
    assert len(output)==len(truth)==960
    assert max(old)-min(old)>1.5
    for line,(frequency,amplitude) in zip(output,truth):
        fields=line.split()
        assert fields[0]!='none' and fields[2]=='true'
        assert abs(1200*math.log2(float(fields[0])/frequency))<(.5 if amplitude==72 else .2)
        assert int(fields[4])<=2*322+63 # Extended lags are not rescanned.


@pytest.mark.parametrize('waveform',['sine','triangle'])
def test_bank_boundary_does_not_fold_upper_tone_into_low_bank(tmp_path,waveform):
    # Generate3 CORE at ~1521 Hz produced native ~1521 / low ~761 Hz,
    # causing the unchanged settled disagreement guard to end CAL's range.
    # Exercise actual production selection AND arbitration, with known truth.
    here=Path(__file__).parent
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    selector=tmp_path/'selector';resolver=tmp_path/'resolver'
    for exe,source in ((selector,'nsdf_selector_fixture.rs'),(resolver,'nsdf_resolve_fixture.rs')):
        subprocess.run([rustc,'--edition=2021','-O','-C','overflow-checks=on',
                        str(here/source),'-o',str(exe)],check=True)
    cases=[];lines=[]
    for frequency in (1400,1490,1500,1501,1521,1600,1650,1680,1703,1750,1800,1850,2000):
        for phase in np.linspace(0,1,8,endpoint=False):
            cases.append(frequency)
            for low in (False,True):
                fs,n,last=(6000,674,621) if low else (192000,674,621)
                p=(np.arange(n)*frequency/fs+phase)%1
                x=np.rint(14000*(np.sin(2*np.pi*p) if waveform=='sine' else 4*np.abs(p-.5)-1))
                lines.append(('low' if low else 'high')+' '+' '.join(map(str,scores_for(x,last))))
    output=subprocess.run([str(selector)],input='\n'.join(lines)+'\n',
                          capture_output=True,text=True,check=True).stdout.splitlines()
    arbitration=[]
    for i,frequency in enumerate(cases):
        banks=[]
        for line in output[2*i:2*i+2]:
            words=line.split()
            banks.append((0,0) if words[0]=='none' else (round(float(words[0])*1000),int(words[2]=='true')))
        (native,nq),(low,lq)=banks
        assert nq and abs(1200*math.log2(native/1000/frequency))<.5
        # A boundary estimate may be just inside the range; it must not fold
        # by an octave (or more) to manufacture an in-range candidate.
        assert not lq or abs(1200*math.log2(low/1000/frequency))<35
        arbitration.append(f'{native} 0 {nq} {low} 0 {lq}')
    output=subprocess.run([str(resolver)],input='\n'.join(arbitration)+'\n',
                          capture_output=True,text=True,check=True).stdout.splitlines()
    for frequency,line in zip(cases,output):
        mhz,source=map(int,line.split())
        assert source==2
        assert abs(1200*math.log2(mhz/1000/frequency))<.5


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


def test_synthetic_high_triangle_fine_steps_do_not_staircase(tmp_path):
    # ACRONYM's measured ~11-kHz response held near-constant for several
    # 10-mV steps, then jumped ~50 cents. A clean triangle at the same pitches
    # must not acquire that staircase from the production NSDF selector.
    here=Path(__file__).parent
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    exe=tmp_path/'selector'
    subprocess.run([rustc,'--edition=2021','-O','-C','overflow-checks=on',
                    str(here/'nsdf_selector_fixture.rs'),'-o',str(exe)],check=True)
    frequencies=[10840*2**(12*i/1200) for i in range(8)]
    cases=[]
    for phase in np.linspace(0,1,8,endpoint=False):
        for frequency in frequencies:
            p=(np.arange(674)*frequency/192000+phase)%1
            x=np.rint(14000*(4*np.abs(p-.5)-1))
            cases.append((frequency,scores_for(x,321)))
    output=subprocess.run([str(exe)],input=''.join(
        'high '+' '.join(map(str,scores))+'\n' for _,scores in cases),
        capture_output=True,text=True,check=True).stdout.splitlines()
    assert len(output)==len(cases)
    for (frequency,_),line in zip(cases,output):
        words=line.split()
        assert words[0]!='none' and words[2]=='true'
        assert abs(1200*math.log2(float(words[0])/frequency))<.3


@pytest.mark.parametrize('frequency,tolerance',[(22,.25),(23.5,.25),
                                              (440*2**((18.5-69)/12),.25),
                                              (25,.25),(55,.12)])
@pytest.mark.parametrize('amplitude',[72,14000])
def test_synthetic_low_sine_phase_coverage(frequency,tolerance,amplitude):
    # Known synthetic truth, not an accuracy claim for the analog capture.
    # Include the 18.5-semitone target (~23.802Hz) that failed automatic
    # verification on Generate3, September 19. Hardware jitter is not a
    # license to increase this clean-signal detector error tolerance.
    for phase in np.linspace(0,1,32,endpoint=False):
        x=np.rint(amplitude*np.sin(2*np.pi*(np.arange(604)*frequency/6000+phase)))
        result=select(scores_for(x,301),6000,20,1500,fallback=True)
        assert result and result['qualified']
        assert abs(1200*math.log2(result['hz']/frequency))<tolerance
        x=np.rint(amplitude*np.sin(2*np.pi*(np.arange(674)*frequency/192000+phase)))
        result=select(scores_for(x,321),192000,600,20000,fallback=True)
        assert result is None or not result['qualified']


@pytest.mark.parametrize('name',[p.name for p in sorted((Path(__file__).parent/'fixtures').glob('nsdf-cpu-*.json'))])
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
        # CPU reports are immutable historical observations of the old policy.
        # Current Rust is separately compared against these same score arrays
        # using the new policy by test_cpu_selector_matches_model_without_frame_buffer.
        expected=select(scores,report['fs'],20 if low else 600,1500 if low else 20000,
                        fallback=True,legacy_range_first=cpu.get('policy','0')=='0')
        if fixture.get('early_gate') and (report['rms_counts']<=2 or
                (report['clipped'] and not low)):
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
        qualified=(expected['qualified'] and report['rms_counts']>2 and
                   (low or not report['clipped']))
        assert (cpu['ok']=='true')==qualified
