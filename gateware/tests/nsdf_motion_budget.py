"""Bounded offline motion tradeoff probe; no deployed detector changes.

Isolates exact quantized score calculation/selection at each bank sample rate.
Not an ADC/FIR, asynchronous scheduler, or hardware throughput simulation.
Exponential chirps have known endpoint and window-midpoint frequencies. Their
midpoint error is reported separately from intentional observation latency.
Short-window alternatives are host models, not buildable firmware settings.
"""
import json
import math
from collections import defaultdict
import numpy as np
from nsdf_refinement_probe import scores_for
from nsdf_trace_analysis import select


def chirp(fs,n,end_hz,octaves_per_second,phase,amplitude):
    t=(np.arange(n)-(n-1))/fs
    rate=math.log(2)*octaves_per_second
    cycles=end_hz*t if rate==0 else end_hz*np.expm1(rate*t)/rate
    return np.rint(amplitude*np.sin(2*np.pi*(cycles+phase)))


def run():
    groups=defaultdict(list)
    for low,frequencies in ((True,(25,55,110,220,440)),(False,(880,2000,10000))):
        fs,n,last,minimum,maximum=(6000,604,301,20,1500) if low else (192000,674,321,600,20000)
        for frequency in frequencies:
            for speed in (0,.5,2,8):
                for direction in ((1,) if speed==0 else (-1,1)):
                    rate=speed*direction
                    for phase in (.03,.29,.61,.87):
                        for amplitude in (72,14000):
                            x=chirp(fs,n,frequency,rate,phase,amplitude)
                            variants=[('current',x,last,minimum,True),
                                      ('no_refinement',x,last,minimum,False)]
                            if low:variants.append(('short_low',x[-304:],151,40,True))
                            for name,samples,limit,floor,refine in variants:
                                start=frequency*2**(-rate*(len(samples)-1)/fs)
                                # Explicitly exclude out-of-band chirps from motion statistics.
                                if min(start,frequency)<floor or max(start,frequency)>maximum:
                                    continue
                                r=select(scores_for(samples,limit),fs,floor,maximum,
                                         refine=refine,fallback=True)
                                middle=frequency*2**(-rate*(len(samples)-1)/(2*fs))
                                valid=r is not None and r['qualified']
                                groups[name,frequency,speed].append(dict(valid=valid,
                                    mid_cents=1200*math.log2(r['hz']/middle) if valid else None,
                                    end_cents=1200*math.log2(r['hz']/frequency) if valid else None))
    output=[]
    for (name,frequency,speed),rows in sorted(groups.items()):
        valid=[r for r in rows if r['valid']]
        output.append(dict(variant=name,end_hz=frequency,octaves_per_second=speed,
            cases=len(rows),qualified=len(valid),
            worst_midpoint_cents=max((abs(r['mid_cents']) for r in valid),default=None),
            worst_endpoint_cents=max((abs(r['end_cents']) for r in valid),default=None)))
    return output


if __name__=='__main__':
    print(json.dumps(run(),indent=2))
