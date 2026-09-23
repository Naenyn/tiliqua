"""Discrete schedule model, NOT synthesized arbitration or streaming gateware.

One write and one read port on four 1024x16 channel rings. Four 192-kHz
samples arrive as a four-cycle burst at 60 MHz. Every /32 boundary requests
four 769-read FIR jobs. Four detector snapshots each read 674 words twice
(mean pass, then copy), using the same frozen head. FIR has dispatch priority;
jobs are non-preemptible. Payloads are sequence tags to detect overwritten data.
"""
from collections import deque
import json


def simulate(snapshot_phase,depth=1024,cycles=30000):
    memory=[[s for s in range(depth)] for _ in range(4)]
    heads=[depth-1]*4;next_sequence=depth;next_adc=0;writes=deque()
    fir=deque();snapshots=deque();active=None;completed=0
    max_snapshot_latency=0;max_fir_latency=0;max_age=0
    for cycle in range(cycles):
        if cycle==next_adc:
            writes.extend((ch,next_sequence) for ch in range(4))
            next_sequence+=1;next_adc=((next_sequence-depth)*625)//2
        if writes:
            ch,seq=writes.popleft();memory[ch][seq%depth]=seq;heads[ch]=seq
            if ch==3 and seq%32==31:
                fir.extend(dict(kind='fir',channel=c,head=heads[c],length=769,
                                passes=1,index=0,created=cycle) for c in range(4))
        if cycle==snapshot_phase:
            snapshots.extend(dict(kind='snapshot',channel=c,head=heads[c],length=674,
                                  passes=2,index=0,created=cycle) for c in range(4))
        if active is None:
            if fir:active=fir.popleft()
            elif snapshots:active=snapshots.popleft()
        if active is None:continue
        ch=active['channel'];index=active['index']%active['length']
        seq=active['head']-active['length']+1+index
        assert memory[ch][seq%depth]==seq, (cycle,active,seq,memory[ch][seq%depth])
        max_age=max(max_age,heads[ch]-seq)
        active['index']+=1
        if active['index']==active['length']*active['passes']:
            latency=cycle-active['created']+1
            if active['kind']=='snapshot':
                completed+=1;max_snapshot_latency=max(max_snapshot_latency,latency)
            else:
                max_fir_latency=max(max_fir_latency,latency)
                assert latency<=10000, 'filter missed its next /32 deadline'
            active=None
    assert completed==4
    return dict(snapshot_latency_cycles=max_snapshot_latency,
                fir_latency_cycles=max_fir_latency,max_sample_age=max_age)


def report():
    phases=sorted(set(range(0,10000,137))|{0,1,3,312,313,624,625,9687,9688,9690,9999})
    results=[simulate(p) for p in phases]
    return dict(phase_cases=len(phases),depth_per_channel=1024,
                **{key:max(r[key] for r in results) for key in results[0]},
                assumptions='dedicated write port, bounded hardware copies, no CPU/PSRAM stalls')


if __name__=='__main__':print(json.dumps(report(),indent=2))
