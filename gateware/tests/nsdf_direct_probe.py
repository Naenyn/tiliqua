"""Real NSDF RTL scores with host reference peak selection; not full integration."""
import argparse
import json
import math
from pathlib import Path
import sys
import numpy as np
from test_nsdf_direct_rtl import run_frame


def probe(samples,fs,low,high,reference):
    x=np.asarray(samples,dtype=np.int64)
    x=x-int(np.rint(np.mean(x)))
    # Mean removal can double peak magnitude; attenuate only if necessary.
    while np.max(np.abs(x))>32767:x=x//2
    last=math.ceil(fs/low)+1
    scores,cycles=run_frame(x,last,stall=False,capacity=(674,321))
    expected=[]
    for lag in range(last+1):
        a=x[:len(x)-lag];b=x[lag:]
        corr=int(np.dot(a,b));energy=int(np.dot(a,a)+np.dot(b,b))
        expected.append(((-1 if corr<0 else 1)*((abs(corr)<<21)//energy)) if energy else 0)
    np.testing.assert_array_equal(scores,expected)
    original=reference.nsdf
    try:
        reference.nsdf=lambda *a,**kw:scores/(1<<20)
        measured=reference.estimate(x,fs,low,high)
    finally:reference.nsdf=original
    ideal=reference.estimate(x,fs,low,high)
    return dict(frame=len(x),last_lag=last,fs=fs,cycles=cycles,
        rtl_hz=measured.hz if measured else None,qualified=measured.qualified if measured else False,
        reference_hz=ideal.hz if ideal else None,
        additional_cents=1200*math.log2(measured.hz/ideal.hz) if measured and ideal else None)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--nsdf-tests',type=Path,required=True)
    a=p.parse_args();sys.path.insert(0,str(a.nsdf_tests.resolve()))
    import nsdf_reference
    for fs,n,lo,hi,f in [(6000,604,20,1500,20.37),(6000,604,20,1500,440.3),
                          (192000,674,600,20000,7678.1),(192000,674,600,20000,19953.)]:
        for gain in [12000,72]:
            x=np.rint(gain*np.sin(2*np.pi*(f*np.arange(n)/fs+.17)))
            print(json.dumps(dict(kind='sine',frequency=f,gain=gain,
                **probe(x,fs,lo,hi,nsdf_reference))),flush=True)
    for name in ['tuner-local-parks-narrow-pulse-1001.json',
                 'tuner-local-parks-modulated-blade-attenuated.json']:
        d=json.loads((Path(__file__).parent/'fixtures'/name).read_text())
        print(json.dumps(dict(kind=name,**probe(d['samples'][:674],192000,600,20000,nsdf_reference))),flush=True)
