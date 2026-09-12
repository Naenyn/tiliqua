"""Replay real frames at bounded window sizes; no synthetic history extension.

Windows overlap and are not independent captures. Smaller windows explicitly
raise the searchable low-frequency limit. Report repeatability, not accuracy.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from spectral_reference import estimate as spectral


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yin-tests',type=Path,required=True)
    p.add_argument('--nsdf-tests',type=Path,required=True)
    a=p.parse_args();sys.path.extend([str(a.yin_tests.resolve()),str(a.nsdf_tests.resolve())])
    from yin_reference import estimate as yin
    from nsdf_reference import estimate as nsdf
    for path in sorted((Path(__file__).parent/'fixtures').glob('tuner-*.json')):
        d=json.loads(path.read_text());h=d['header'];fs=int(h['fs'])/int(h['div'])
        if fs!=192000:continue
        for n,low in [(2048,200),(1024,400),(512,800)]:
            for start in range(0,len(d['samples'])-n+1,64):
                x=d['samples'][start:start+n]
                row=dict(capture=path.name,window=n,start=start,min_hz=low,
                         duration_ms=n*1000/fs)
                for name,fn in [('spectral_1x',lambda x,fs,lo,hi:spectral(x,fs,lo,hi,padding=1)),
                                ('spectral_4x',spectral),('nsdf',nsdf),
                                ('yin',lambda *a:yin(*a,vectorized=True))]:
                    r=fn(x,fs,low,20000);row[name]=asdict(r) if r else None
                print(json.dumps(row),flush=True)
