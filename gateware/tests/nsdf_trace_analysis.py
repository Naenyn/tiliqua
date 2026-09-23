"""Decode opt-in NSDF serial frames; selection remains host-side for this trial.

Key-maxima selection follows our McLeod/Wyvill reference. Longer-lag refinement
is the separately guarded engineering extension, not a paper-defined step.
Each bank is reported independently: asynchronously exported frames are not a
validated production bank arbiter. Broken/truncated exports are never accepted.
"""
import argparse
import json
import math
from pathlib import Path


def select(scores,fs,minimum,maximum,refine=True,fallback=False,legacy_range_first=False,
           refine_quality=False,reject_early_outside=False,relative_cutoff=.9):
    values=[v/(1<<20) for v in scores];last=len(values)-1
    peaks=[];skipped=False;best=None
    primary_last=min(last,301 if fs==6000 else 321) if refine_quality else last
    for k in range(1,primary_last):
        if values[k]<=0:
            skipped=True
            if best is not None:peaks.append(best);best=None
        elif skipped and values[k]>=values[k-1] and values[k]>values[k+1]:
            if best is None or values[k]>values[best]:best=k
    if best is not None:peaks.append(best)
    def interpolate(k):
        a,b,c=values[k-1:k+2];curvature=a-2*b+c
        shift=max(-.5,min(.5,.5*(a-c)/curvature)) if curvature<0 else 0
        return k+shift,b+.5*(c-a)*shift+.5*curvature*shift*shift
    def quality(k):
        a,b,c=scores[k-1:k+2];curvature=a-2*b+c
        shift=((abs(a-c)<<19)//(-curvature))*(-1 if a>c else 1) if curvature<0 else 0
        return b+(((c-a)*shift)>>22)
    candidates=[]
    for k in peaks:
        lag,height=interpolate(k);hz=fs/lag
        if not legacy_range_first or minimum*(1-1e-6)<=hz<=maximum*(1+1e-6):
            candidates.append((lag,height))
    if not candidates:return None
    cutoff=relative_cutoff*max(height for _,height in candidates)
    for lag,height in candidates:
        if reject_early_outside and height>=.8 and not minimum*(1-1e-6)<=fs/lag<=maximum*(1+1e-6):
            return None
        if height>=cutoff:break
    hz=fs/lag;original_hz=hz;qualified=height>=.8
    if not minimum*(1-1e-6)<=hz<=maximum*(1+1e-6):return None
    if refine and qualified:
        best_refinement=None
        largest=min(8,int((last-2)/lag))
        multiples=range(largest,1,-1) if fallback else [largest]
        for multiple in multiples:
            if multiple<2:continue
            center=round(lag*multiple)
            choices=[k for k in range(max(1,center-1),min(last,center+2))
                if values[k]>=values[k-1] and values[k]>values[k+1]]
            if choices:
                k=max(choices,key=lambda k:values[k])
                refined_lag,refined_height=interpolate(k)
                refined_lag/=multiple;refined_hz=fs/refined_lag
                if (refined_height>=max(.8,.9*height) and minimum<=refined_hz<=maximum
                        and abs(1200*math.log2(refined_hz/hz))<=10):
                    if best_refinement is None or quality(k)>best_refinement[3]:
                        best_refinement=(refined_hz,refined_lag,refined_height,quality(k))
                    if not refine_quality:break
        if best_refinement is not None:
            hz,lag,refined_height,_=best_refinement
            height=min(height,refined_height)
    return dict(hz=hz,lag=lag,clarity=height,qualified=qualified,unrefined_hz=original_hz)


def decode(lines):
    header=None;scores=[]
    for line in lines:
        line=line.strip()
        if line.startswith('NSDF BEGIN '):
            if header is not None:raise ValueError('new frame before previous END')
            header=dict(part.split('=',1) for part in line.split()[2:]);scores=[]
        elif line=='NSDF END':
            if header is None:raise ValueError('END without BEGIN')
            for key in ('ch','fs','n','last','seq','energy','scaled','clipped'):header[key]=int(header[key])
            if header['low'] not in ('true','false'):raise ValueError('invalid bank')
            low=header['low']=='true'
            shape=tuple(header[k] for k in ('fs','n','last'))
            valid_shapes=((6000,604,301),(6000,674,621)) if low else ((192000,674,321),(192000,674,621))
            if shape not in valid_shapes or len(scores)!=shape[2]+1:
                raise ValueError('wrong frame size or sample rate')
            if not 0<=header['ch']<=3 or any(abs(v)>(1<<20) for v in scores):
                raise ValueError('invalid channel or score')
            # These archived opt-in exports predate range-after-peak selection.
            # Preserve their original interpretation; production-model tests
            # call select() with its current policy instead.
            result=select(scores,header['fs'],20 if low else 600,1500 if low else 20000,
                          legacy_range_first=True)
            rms=math.sqrt(header['energy']/header['n'])*(2 if header['scaled'] else 1)
            if result is not None:
                result['qualified'] &= (header['low'] or not header['clipped']) and rms>2
            yield dict(**header,rms_counts=rms,result=result)
            header=None;scores=[]
        elif header is not None:
            if len(line)!=8 or any(c not in '0123456789abcdefABCDEF' for c in line):
                raise ValueError('non-score data inside frame')
            word=int(line,16);scores.append(word-(1<<32) if word&(1<<31) else word)
    if header is not None:raise ValueError('truncated NSDF frame')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('log',type=Path)
    args=parser.parse_args()
    with args.log.open() as stream:
        for result in decode(stream):print(json.dumps(result))
