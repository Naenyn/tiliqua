import math
import json
from pathlib import Path
import numpy as np
import pytest
from nsdf_trace_analysis import decode,select


def scores_for(frequency,fs,n,last):
    x=np.rint(12000*np.sin(np.arange(n)*2*np.pi*frequency/fs)).astype(np.int64)
    x-=int(np.rint(x.mean()));scores=[]
    for lag in range(last+1):
        a=x[:n-lag];b=x[lag:];c=int(a@b);e=int(a@a+b@b)
        q=(abs(c)<<21)//e;scores.append(-q if c<0 else q)
    return scores,int(x@x)


@pytest.mark.parametrize('frequency,low',[(20.37,True),(440.3,True),(600.3,False),(7678.1,False),(19953,False)])
def test_decode_real_fixed_point_scores(frequency,low):
    fs,n,last=(6000,604,301) if low else (192000,674,321)
    scores,energy=scores_for(frequency,fs,n,last)
    lines=[f'NSDF BEGIN ch=2 low={str(low).lower()} fs={fs} n={n} last={last} seq=22 energy={energy} scaled=0 clipped=0']
    lines.extend(f'{v&0xffffffff:08x}' for v in scores);lines.append('NSDF END')
    report=list(decode(lines))[0];assert report['result']['qualified']
    assert abs(1200*math.log2(report['result']['hz']/frequency))<.3


def test_reject_broken_frames_and_constant_scores():
    assert select([1<<20]*322,192000,600,20000) is None
    assert select([0]*322,192000,600,20000) is None
    with pytest.raises(ValueError):list(decode(['NSDF BEGIN ch=0','12345678']))
    with pytest.raises(ValueError):list(decode(['NSDF BEGIN ch=0','CAPTURE READY']))


def test_first_live_local_parks_sine_trial():
    fixture=json.loads((Path(__file__).parent/'fixtures/nsdf-local-parks-sine-880.json').read_text())
    reports=[next(decode(frame.splitlines())) for frame in fixture['frames']]
    tones=[r for r in reports if r['ch']==0]
    assert len(tones)==3
    assert {r['low'] for r in tones}=={'true','false'}
    for report in tones:
        assert report['clipped']==0 and report['scaled']==0
        assert report['result']['qualified'] and report['result']['clarity']>.98
        # The user's approximate setup is an octave/sanity check, NOT an
        # independent calibrated-frequency accuracy assertion.
        assert 870<report['result']['hz']<890
    idle=[r for r in reports if r['ch']!=0]
    assert len(idle)==1
    assert not idle[0]['result']['qualified']
