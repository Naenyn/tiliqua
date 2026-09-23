"""Whole filter/selector/energy-guard handoff, with synthetic known truth.

Do not feed an unfiltered low-rate sine to an anti-alias rejection test:
qualification depends on the actual quantized FIR and aligned source energy.
"""
from pathlib import Path
import math
import subprocess

import numpy as np
import pytest
from scipy.signal import firwin,freqz
from top.intono.experiment.nsdf_coefficients import coefficients
from nsdf_refinement_probe import scores_for


@pytest.fixture(scope='module')
def binaries(tmp_path_factory):
    folder=tmp_path_factory.mktemp('filter-handoff')
    here=Path(__file__).parent
    result={}
    for name in ('selector','guard','resolve'):
        exe=folder/name
        subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
            '-C','overflow-checks=on',str(here/f'nsdf_{name}_fixture.rs'),'-o',str(exe)],check=True)
        result[name]=exe
    return result


def run(exe,lines):
    return subprocess.check_output([exe],input='\n'.join(lines)+'\n',text=True).splitlines()


def check_cases(binaries,cases,taps=None,legacy_low_guard=False):
    taps=np.asarray(coefficients() if taps is None else taps,dtype=np.int64)
    selectors=[];guards=[]
    for frequency,amplitude,phase,alternating in cases:
        p=np.arange(24576)*frequency/192000+phase
        wave=np.sin(2*np.pi*p)
        if alternating is True:
            wave+=.0076*np.sin(np.pi*p+.7)+.0091*np.sin(3*np.pi*p+.4)
        elif alternating=='triangle':wave=4*np.abs(p%1-.5)-1
        elif alternating=='saw':wave=2*(p%1)-1
        elif isinstance(alternating,float):wave=np.where(p%1<alternating,1.,-1.)
        raw=np.rint(12000+amplitude*wave).astype(np.int64)
        source=raw[-20480:]
        # Exactly the fixed-point FIR accumulator and rounding at /32 ends.
        ends=np.arange(len(raw)-673*32,len(raw)+1,32)
        windows=raw[ends[:,None]-1-np.arange(len(taps))]
        filtered=(windows@taps+65536)>>17
        for low,frame in ((False,raw[-674:]),(True,filtered)):
            centered=frame-int(np.rint(frame.mean()))
            energy=int(centered@centered)
            selectors.append(('low' if low else 'high')+' '+' '.join(map(str,scores_for(frame,621))))
            guards.append(f'{int(low)} 0 24576 24576 24576 20480 '
                f'{int(source.sum())} {int(source@source)} 1 {energy} 0 0')
    selected=run(binaries['selector'],selectors)
    guarded=run(binaries['guard'],guards)
    if legacy_low_guard:
        # Offline policy-3 baseline only. Production always runs actual Rust.
        for k in range(1,len(guards),2):
            v=list(map(int,guards[k].split()));n,total,squares,energy=v[5],v[6],v[7],v[9]
            source_power=(squares*n-total*total+n*n-1)//(n*n)
            old=energy>4*674 and energy*2500>source_power*674
            assert old or guarded[k]=='false'
            guarded[k]='true' if old else 'false'
    arbitration=[];banks=[]
    for line,gate in zip(selected,guarded):
        fields=line.split()
        banks.append((0,False) if fields[0]=='none' else
            (round(float(fields[0])*1000),fields[2]=='true' and gate=='true'))
    for (native,nq),(low,lq) in zip(banks[::2],banks[1::2]):
        arbitration.append(f'{native} 0 {int(nq)} {low} 0 {int(lq)}')
    resolved=run(binaries['resolve'],arbitration)
    return banks,[tuple(map(int,line.split())) for line in resolved]


def test_filter_keeps_low_handoff_and_suppresses_undersampled_upper_band():
    taps=coefficients()
    assert len(taps)==769 # No new MAC slots, history, or coefficient memory.
    f,h=freqz(taps/(1<<17),worN=262144,fs=192000)
    assert np.max(np.abs(20*np.log10(abs(h[f<=1000]))))<.01
    assert np.min(abs(h[f<=1500]))>.85
    assert np.max(abs(h[f>=2200]))<.022 # Margin beneath the 5% RMS gate.


@pytest.mark.parametrize('alternating',[False,True])
def test_filtered_upper_tones_cannot_veto_native_with_false_low_pitch(binaries,alternating):
    # Dense transition sweep plus the physical ~2274-Hz failing point.
    frequencies=sorted(set(range(1501,3100,3))|{1703,1850,2000,2147,2274,4000,7678,10000,18500,19900})
    cases=[(f,amplitude,phase,alternating) for f in frequencies
           for amplitude in (72,14000) for phase in (.03,.39)]
    banks,resolved=check_cases(binaries,cases)
    for case,(native,nq),(low,lq),(mhz,source) in zip(cases,banks[::2],banks[1::2],resolved):
        frequency=case[0]
        assert nq,(case,native)
        assert not lq or abs(1200*math.log2(low/1000/frequency))<35,(case,low)
        assert source==2,(case,native,low,source)
        assert abs(1200*math.log2(mhz/1000/frequency))<1,(case,mhz)


def test_filtered_quiet_and_full_level_in_range_tones_keep_tracking(binaries):
    cases=[(f,amplitude,phase,False)
           for f in (20.37,24.4,25,55,110,440,599.7,600.3,880,997.1,1000,1200,1400,1490,1500)
           for amplitude in (72,14000) for phase in (.03,.39,.81)]
    banks,resolved=check_cases(binaries,cases)
    for case,(mhz,source) in zip(cases,resolved):
        assert source in (1,2),(case,mhz,source)
        assert abs(1200*math.log2(mhz/1000/case[0]))<1,(case,mhz,source)


def test_filter_and_stronger_relative_guard_preserve_basic_and_one_percent_pulses(binaries):
    # Quiet sines are covered above. Pulse RMS depends on duty cycle, so do
    # not equate a 72-count peak narrow pulse with a 72-count peak sine.
    cases=[(f,amplitude,phase,shape)
           for f in (20.37,55.3,440,880,1490)
           for amplitude in (1000,14000) for phase in (.03,.39)
           for shape in ('triangle','saw',.5,.05,.01)]
    _,resolved=check_cases(binaries,cases)
    for case,(mhz,source) in zip(cases,resolved):
        assert source in (1,2),(case,mhz,source)
        assert abs(1200*math.log2(mhz/1000/case[0]))<5,(case,mhz,source)


def test_narrow_pulse_handoff_grid_does_not_regress_previous_valid_cases(binaries):
    # Ideal discontinuous 1%-duty pulses are severely undersampled at 192 kHz
    # here. Policy 3 already rejects/misidentifies some. Keep those limitations
    # explicit; do not claim this filter update solves all narrow pulse cases.
    cases=[(f,14000,phase,.01) for f in range(600,1501,17) for phase in (.03,.39,.81)]
    _,resolved=check_cases(binaries,cases)
    old_taps=np.rint(firwin(769,2250,fs=192000,window=('kaiser',8.6))*131072).astype(np.int64)
    _,baseline=check_cases(binaries,cases,taps=old_taps,legacy_low_guard=True)
    good=lambda case,result:result[1] in (1,2) and abs(1200*math.log2(result[0]/1000/case[0]))<5
    assert any(not good(c,r) for c,r in zip(cases,baseline))
    for case,old,new in zip(cases,baseline,resolved):
        if good(case,old):assert good(case,new),(case,old,new)
    assert sum(good(c,r) for c,r in zip(cases,resolved))>sum(good(c,r) for c,r in zip(cases,baseline))
