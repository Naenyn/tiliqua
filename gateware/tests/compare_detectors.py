"""Offline comparison with explicit paths to independent, pinned experiments."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
from spectral_reference import estimate as spectral


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yin-tests',type=Path,required=True)
    p.add_argument('--nsdf-tests',type=Path,required=True)
    a=p.parse_args()
    sys.path.extend([str(a.yin_tests.resolve()),str(a.nsdf_tests.resolve())])
    from tuner_yin_benchmark import waveform,cases,FS
    from yin_reference import estimate as yin
    from nsdf_reference import estimate as nsdf
    for case in cases():
        x=waveform(**case); row={'case':case}
        for name,fn in [('spectral',spectral),('nsdf',nsdf),
                        ('yin',lambda x,fs:yin(x,fs,vectorized=True))]:
            r=fn(x,FS)
            row[name]=asdict(r) if r else None
            row[name+'_cents']=(1200*math.log2(r.hz/case['frequency'])
                if r and case.get('kind') not in ('silence','noise') else None)
        print(json.dumps(row),flush=True)
