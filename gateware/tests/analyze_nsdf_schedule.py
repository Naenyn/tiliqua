"""Continuous latest-value diagnostics: not full score or source parity."""
import argparse
import json
from pathlib import Path


def analyze_schedule(text):
    previous_slot=None
    previous={}
    seen=False
    for line in text.splitlines(keepends=True):
        if not line.endswith('\n'):continue
        if line.startswith('NSDF ERROR'):raise ValueError('device diagnostic error')
        if not line.startswith('NSDF RUN '):continue
        fields=dict(p.split('=') for p in line.split()[2:])
        keys={'ch','low','count','seq','mhz','raw','guard','ok','age','dt','cycles','work','faults','ms'}
        if fields.keys()!=keys:raise ValueError('unexpected scheduler fields')
        for key in ('low','raw','guard','ok'):
            if fields[key] not in ('true','false'):raise ValueError('bad scheduler boolean')
        r={k:(v=='true' if k in ('low','raw','guard','ok') else int(v)) for k,v in fields.items()}
        if any(not 0<=r[k]<2**32 for k in keys-{'low','raw','guard','ok'}):raise ValueError('bad scheduler integer')
        if r['ch']>3 or r['mhz']>20000000:raise ValueError('bad channel or pitch')
        slot=r['ch']*2+int(r['low'])
        if previous_slot is not None and slot!=(previous_slot+1)%8:raise ValueError('skipped report slot')
        previous_slot=slot
        if r['ok'] and not (r['count']>0 and r['raw'] and r['guard'] and r['age']<=500):
            raise ValueError('accepted invalid or stale result')
        if r['raw'] and not ((20000<=r['mhz']<=1500000) if r['low'] else (600000<=r['mhz']<=20000000)):
            raise ValueError('candidate outside bank')
        rate=cpu=None
        if slot in previous:
            old=previous[slot];elapsed=(r['ms']-old['ms'])&0xffffffff
            if not 0<elapsed<2**31 or r['count']<old['count']:
                raise ValueError('nonmonotonic scheduler record')
            delta=r['count']-old['count']
            if delta and not 0<(r['seq']-old['seq'])&0xffffffff<2**31:
                raise ValueError('nonmonotonic sample sequence')
            rate=delta*1000/elapsed
            cpu=((r['work']-old['work'])&0xffffffff)/(60000*elapsed)
        previous[slot]=r
        yield dict(**r,bank='low' if r['low'] else 'native',hz=r['mhz']/1000,
                   updates_per_second=rate,measured_cpu_fraction=cpu,score_parity_checked=False)
        seen=True
    if not seen:raise ValueError('no complete scheduler records')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('log',type=Path)
    args=parser.parse_args()
    for r in analyze_schedule(args.log.read_text()):print(json.dumps(r))
