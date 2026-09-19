"""Validate immutable centered waveform/score pairs from full diagnostic mode.

These are the exact signed samples fed to the score engine, after decimation,
frame centering and any reported scaling. They are not untouched ADC samples.
Replay every integer score and frame energy before accepting waveform evidence.
"""
import argparse
import json
from pathlib import Path
import re
from analyze_nsdf_source import analyze_source


def words(body):
    result=[]
    for line in body.splitlines():
        if not re.fullmatch('[0-9a-fA-F]{8}',line):raise ValueError('invalid waveform/score word')
        value=int(line,16)
        result.append(value-(1<<32) if value&(1<<31) else value)
    return result


def identity(meta):
    return (int(meta['ch']),meta['low']=='true',int(meta['seq']))


def replay(samples,last):
    scores=[]
    for lag in range(last+1):
        a=samples[:len(samples)-lag];b=samples[lag:]
        corr=sum(x*y for x,y in zip(a,b))
        energy=sum(x*x+y*y for x,y in zip(a,b))
        q=(abs(corr)<<21)//energy if energy else 0
        scores.append(-q if corr<0 else q)
    return scores


def analyze_wave(text):
    start=re.search(r'^NSDF SOURCE ',text,re.M)
    if start is None:raise ValueError('no complete waveforms')
    text=text[start.start():]
    reports={(r['channel'],r['bank']=='low',r['sequence']):r for r in analyze_source(text)}
    scores={}
    for header,body in re.findall(r'^NSDF BEGIN ([^\n]+)\n(.*?)^NSDF END\n',text,re.M|re.S):
        meta=dict(v.split('=') for v in header.split())
        scores[identity(meta)]=words(body)
    seen=set()
    for header,body in re.findall(r'^NSDF WAVE ([^\n]+)\n(.*?)^NSDF WAVE END\n',text,re.M|re.S):
        meta=dict(v.split('=') for v in header.split())
        if meta.get('low') not in ('true','false'):raise ValueError('invalid waveform bank')
        key=identity(meta)
        if key in seen:raise ValueError('duplicate waveform')
        seen.add(key)
        if key not in reports or key not in scores:raise ValueError('waveform lacks validated scores')
        samples=words(body)
        n=604 if key[1] else 674
        if int(meta['n'])!=n or len(samples)!=n:raise ValueError('wrong waveform length')
        if any(not -32768<=x<=32767 for x in samples):raise ValueError('sample is not signed 16 bit')
        if sum(x*x for x in samples)!=reports[key]['energy']:raise ValueError('waveform energy mismatch')
        if replay(samples,len(scores[key])-1)!=scores[key]:raise ValueError('waveform score mismatch')
        yield dict(**reports[key],samples=samples,score_parity_checked=True)
    if not seen:raise ValueError('no complete waveforms')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    args=parser.parse_args()
    for report in analyze_wave(args.log.read_text()):print(json.dumps(report))
