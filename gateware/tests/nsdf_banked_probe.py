"""Host model of quantized FIR + exact Q20 scores + provisional bank selection.

The score arithmetic is checked against RTL elsewhere. This is not streaming
gateware or proof of ADC/filter response. Corpus frames include real prehistory,
never repeated short captures. Bank selection is intentionally experimental.
"""
import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import sys
import numpy as np
from nsdf_filter_budget import coefficients


def score_estimate(x,fs,low,high,reference,refine=False):
    x=np.array(x,dtype=np.int64,copy=True);x-=int(np.rint(np.mean(x)))
    while max(abs(x))>32767:x=x//2
    last=math.ceil(fs/low)+1;scores=[]
    for k in range(last+1):
        a=x[:len(x)-k];b=x[k:];corr=int(a@b);energy=int(a@a+b@b)
        scores.append(((-1 if corr<0 else 1)*((abs(corr)<<21)//energy)) if energy else 0)
    original=reference.nsdf
    try:
        reference.nsdf=lambda *a,**kw:np.asarray(scores)/(1<<20)
        result=reference.estimate(x,fs,low,high)
    finally:reference.nsdf=original
    if not refine or not result or not result.qualified:return result
    # Optional engineering extension, NOT part of the paper's selector. Refine
    # at a longer already-computed lag, preserving the selected octave and
    # refusing disagreement >10 cents. No extra correlation products required.
    multiple=min(8,int((last-2)/result.lag))
    if multiple<2:return result
    center=int(round(result.lag*multiple));values=np.asarray(scores)/(1<<20)
    candidates=[k for k in range(max(1,center-1),min(last,center+2))
                if values[k]>=values[k-1] and values[k]>values[k+1]]
    if not candidates:return result
    k=max(candidates,key=lambda k:values[k]);a,b,c=values[k-1:k+2]
    curvature=a-2*b+c
    if curvature>=0:return result
    shift=float(np.clip(.5*(a-c)/curvature,-.5,.5));lag=(k+shift)/multiple
    height=float(b+.5*(c-a)*shift+.5*curvature*shift*shift)
    hz=fs/lag
    if (height<max(.8,.9*result.clarity) or not low<=hz<=high or
            abs(1200*math.log2(hz/result.hz))>10):return result
    return replace(result,hz=hz,lag=lag,clarity=min(height,result.clarity))


def estimate(samples,reference,refine=False):
    raw=np.asarray(samples,dtype=np.int64)
    if len(raw)<20100:raise ValueError('insufficient filter/window prehistory')
    filtered=np.convolve(raw,coefficients(),mode='valid')[::32]
    filtered=np.clip((filtered+(1<<16))>>17,-32768,32767)
    low_x=filtered[-604:];high_x=raw[-674:]
    low=score_estimate(low_x,6000,20,1500,reference,refine)
    high=score_estimate(high_x,192000,600,20000,reference,refine)
    def rms(x):return float(np.std(x))
    source_rms=rms(raw);low_rms=rms(low_x);high_rms=rms(high_x)
    selected=None;bank=None
    # Native-rate bank covers >=600 Hz. Prefer it throughout that range:
    # 6-kHz interpolation has too few samples/cycle around 1 kHz.
    if high and high.qualified and high_rms>max(2,.1*source_rms):
        selected=high;bank='high'
    elif low and low.qualified and low_rms>max(2,.02*source_rms):
        selected=low;bank='low'
    return dict(result=asdict(selected) if selected else None,bank=bank,
                low=asdict(low) if low else None,high=asdict(high) if high else None)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yin-tests',type=Path,required=True)
    p.add_argument('--nsdf-tests',type=Path,required=True)
    p.add_argument('--refine',action='store_true')
    a=p.parse_args();sys.path.extend([str(a.yin_tests.resolve()),str(a.nsdf_tests.resolve())])
    from tuner_yin_benchmark import waveform,cases
    import nsdf_reference
    for case in cases():
        result=estimate(waveform(**case,n=23000),nsdf_reference,a.refine)
        hz=result['result']['hz'] if result['result'] else None
        print(json.dumps(dict(case=case,**result,cents=1200*math.log2(hz/case['frequency'])
            if hz and case.get('kind') not in ('noise','silence') else None)),flush=True)
