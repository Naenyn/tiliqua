"""Offline A/B study; no changes to deployed hardware or accepted pitch.

Truth is available only for synthetic signals. Real waveform captures are
compared at different window positions, never tiled to invent prehistory.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import numpy as np
from nsdf_trace_analysis import select
from nsdf_filter_budget import coefficients


def scores_for(samples,last):
    x=np.asarray(samples,dtype=np.int64).copy()
    x-=int(np.rint(x.mean()))
    if max(abs(x))>32767:x=x//2
    scores=[]
    for k in range(last+1):
        a,b=x[:len(x)-k],x[k:]
        corr=int(a@b);energy=int(a@a+b@b)
        q=(abs(corr)<<21)//energy if energy else 0
        scores.append(-q if corr<0 else q)
    return scores


def comparison(x,fs,low,high):
    scores=scores_for(x,math.ceil(fs/low)+1)
    return {name:select(scores,fs,low,high,fallback=fallback)
            for name,fallback in [('single',False),('fallback',True)]}


def run(yin_tests):
    sys.path.insert(0,str(yin_tests))
    from tuner_yin_benchmark import waveform,cases
    taps=coefficients()
    for case in cases():
        raw=waveform(**case,n=23000).astype(np.int64)
        filtered=np.convolve(raw,taps,mode='valid')[::32]
        filtered=np.clip((filtered+(1<<16))>>17,-32768,32767)
        results={}
        for bank,x,fs,lo,hi,ratio in [('high',raw[-674:],192000,600,20000,.1),
                                      ('low',filtered[-604:],6000,20,1500,.02)]:
            results[bank]=comparison(x,fs,lo,hi)
            for r in results[bank].values():
                if r:r['qualified'] &= bool(np.std(x)>max(2,ratio*np.std(raw)))
        selected={}
        for strategy in ('single','fallback'):
            r=next((results[b][strategy] for b in ('high','low')
                    if results[b][strategy] and results[b][strategy]['qualified']),None)
            selected[strategy]=dict(result=r,cents=1200*math.log2(r['hz']/case['frequency']) if r else None)
        yield dict(case=case,banks=results,selected=selected)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yin-tests',type=Path,required=True)
    args=p.parse_args()
    for row in run(args.yin_tests):print(json.dumps(row),flush=True)
