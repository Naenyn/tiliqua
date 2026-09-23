"""Offline analysis of real captured verifier history; no device access."""
import json
import math
import sys


def score(samples,lag_q8):
    lag,fraction=divmod(lag_q8,256)
    available=len(samples)-32-lag-1
    if available<256:return None
    error=0;low=32767;high=-32768
    for n in range(256):
        index=len(samples)-1-n*(available-1)//256
        current=samples[index]
        delayed=samples[index-lag]+((samples[index-lag-1]-samples[index-lag])*fraction+128>>8)
        error+=abs(current-delayed)
        low=min(low,current,delayed);high=max(high,current,delayed)
    return error,high-low


def analyze(path):
    capture=json.load(open(path));s=capture["samples"];h=capture["header"]
    assert len(s)==2048
    fs=int(h["fs"])/int(h["div"]);lag=int(h["lag"]);raw=float(h["raw"])
    scores=[score(s,lag*n) for n in range(1,5)]
    span=scores[0][1]
    print("Metadata:",h)
    print("Samples:",len(s),"rate:",fs,"min/max:",min(s),max(s),"mean:",sum(s)/len(s))
    print("Candidate mismatch % (common span):",[None if v is None else v[0]*100/(256*span) for v in scores])
    best=min(v[0] for v in scores if v is not None)
    selected=next((n+1 for n,v in enumerate(scores) if v is not None and v[0]<=best+2*span),0) if best*20<=span*256 else 0
    if scores[0][0]*20<=span*256:selected=1
    print("Software selector:",selected)
    for multiple in (1,2):
        nearby=min((score(s,q)[0],q) for q in range(max(1536,lag*multiple-512),lag*multiple+513))
        print("Best nearby lag:",multiple,nearby[1]/256,"mismatch %:",nearby[0]*100/(256*span))
    # Simple spectral projections: a coherent near-Nyquist alternating term
    # would make an odd sample lag appear worse than an even one.
    mean=sum(s)/len(s)
    for frequency in (raw/2,raw,raw*2,fs/2):
        re=sum((v-mean)*math.cos(math.tau*frequency*n/fs) for n,v in enumerate(s))/len(s)
        im=sum((v-mean)*math.sin(math.tau*frequency*n/fs) for n,v in enumerate(s))/len(s)
        print("Projection",frequency,"Hz:",math.hypot(re,im),"counts")


if __name__=="__main__":analyze(sys.argv[1])
