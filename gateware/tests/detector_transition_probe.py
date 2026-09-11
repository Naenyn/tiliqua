"""Same-frame, offline abrupt-step responses; excludes firmware and scheduling."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
import numpy as np
from spectral_reference import estimate as spectral


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yin-tests',type=Path,required=True)
    p.add_argument('--nsdf-tests',type=Path,required=True)
    a=p.parse_args();sys.path.extend([str(a.yin_tests.resolve()),str(a.nsdf_tests.resolve())])
    from yin_reference import estimate as yin
    from nsdf_reference import estimate as nsdf
    fs=192000;n=19204
    for old,new in [(110.7,440.3),(440.3,110.7),(997.1,7678.1),(7678.1,997.1)]:
        for ms in range(0,121,5):
            # Phase continuous at t=0, when the source changes frequency.
            t=(np.arange(n)-n)/fs+ms/1000
            phase=np.where(t<0,t*old,t*new)+.17
            x=np.rint(12000*np.sin(2*np.pi*phase)).astype(np.int16)
            row=dict(old=old,new=new,elapsed_ms=ms,frame_ms=n*1000/fs)
            for name,fn in [('spectral',spectral),('nsdf',nsdf),
                            ('yin',lambda x,fs:yin(x,fs,vectorized=True))]:
                r=fn(x,fs);row[name]=asdict(r) if r else None
                row[name+'_target_cents']=1200*math.log2(r.hz/new) if r else None
                if ms>=105:
                    assert r and r.qualified and abs(row[name+'_target_cents'])<10
            print(json.dumps(row),flush=True)
