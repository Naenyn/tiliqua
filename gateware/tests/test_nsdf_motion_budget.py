"""Known exponential chirps through the actual firmware selector, offline."""
import math
from pathlib import Path
import subprocess
from nsdf_motion_budget import chirp
from nsdf_refinement_probe import scores_for
from nsdf_trace_analysis import select


def test_actual_selector_exponential_motion_grid(tmp_path):
    here=Path(__file__).parent;exe=tmp_path/'selector'
    subprocess.run([str(Path.home()/'.cargo/bin/rustc'),'--edition=2021','-O',
                    '-C','overflow-checks=yes',str(here/'nsdf_selector_fixture.rs'),'-o',str(exe)],check=True)
    cases=[]
    for low,frequencies in ((True,(25,55,110,220,440)),(False,(880,2000,10000))):
        fs,n,last,minimum,maximum=(6000,674,621,20,1500) if low else (192000,674,321,600,20000)
        for hz in frequencies:
            for speed in (0,.5,2,8):
                for direction in ((1,) if speed==0 else (-1,1)):
                    rate=speed*direction
                    start=hz*2**(-rate*(n-1)/fs)
                    if min(start,hz)<minimum or max(start,hz)>maximum:continue
                    for phase in (.03,.29,.61,.87):
                        for amplitude in (72,14000):
                            scores=scores_for(chirp(fs,n,hz,rate,phase,amplitude),last)
                            model=select(scores,fs,minimum,maximum,fallback=True,refine_quality=low)
                            cases.append((low,speed,hz*2**(-rate*(n-1)/(2*fs)),scores,model))
    assert len(cases)==440
    payload=''.join(('low' if low else 'native')+' '+' '.join(map(str,scores))+'\n'
                    for low,_,_,scores,_ in cases)
    lines=subprocess.check_output([exe],input=payload,text=True).splitlines()
    assert len(lines)==len(cases)
    for (low,speed,middle,_,model),line in zip(cases,lines):
        assert model is not None
        hz,clarity,qualified,original,reads=line.split()
        assert (qualified=='true')==model['qualified']
        assert abs(1200*math.log2(float(hz)/model['hz']))<.005
        # Bounds for this sine-only grid, not universal tracking guarantees.
        assert (qualified=='true')==(not low or speed<8)
        if qualified=='true':
            assert abs(1200*math.log2(float(hz)/middle)) < (7 if low else 1)
