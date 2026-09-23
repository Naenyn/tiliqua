"""Validate complete diagnostic CPU/IO/score triples from a serial capture.

Connection-boundary fragments are excluded, not joined across captures. Each
included triple must match channel/bank/sequence, scores, and IO checksum.
Timing is elapsed 60-MHz timer time, including interrupts, not isolated cycles.
"""
import argparse
import json
from pathlib import Path
import re
from nsdf_trace_analysis import decode,select


def guard_fields(cpu):
    if 'guard' not in cpu and 'gc' not in cpu:return {}
    if cpu.get('guard') not in ('true','false') or not 0<int(cpu.get('gc','0'))<1<<32:
        raise ValueError('invalid device guard metadata')
    return dict(device_guard=cpu['guard']=='true',guard_ms=int(cpu['gc'])/60000)


def validate(cpu,io,block):
    report=next(decode(block.splitlines()))
    for key in ('ch','low','seq'):
        if cpu[key]!=io[key] or cpu[key]!=str(report[key]):
            raise ValueError('mixed frame metadata')
    words=[int(s,16) for s in block.splitlines()[1:-1]]
    scores=[w-(1<<32) if w&(1<<31) else w for w in words]
    if int(io['reads'])!=len(scores) or int(io['sum'],16)!=(sum(words)&0xffffffff):
        raise ValueError('IO sweep count/checksum mismatch')
    if not 0<=int(cpu['reads'])<=2*len(scores)+63:
        raise ValueError('CPU read bound exceeded')
    if int(cpu['cycles'])<=0 or int(io['cycles'])<=0:
        raise ValueError('invalid elapsed timing')
    gated=report['rms_counts']<=2 or (bool(report['clipped']) and report['bank']!='low')
    low=report['low']=='true'
    # Unversioned archived exports used range-first key-maxima selection.
    # New exports explicitly identify range-after-peak selection; never silently
    # reinterpret historical CPU results or guess an unknown algorithm version.
    policy=cpu.get('policy','0')
    if policy not in ('0','1','2','3','4'):raise ValueError('unknown selector policy')
    if policy in ('2','3','4') and (report['n'],report['last'])!=(674,621 if low or policy in ('3','4') else 321):
        raise ValueError('selector policy/frame shape mismatch')
    expected=None if gated else select(scores,report['fs'],20 if low else 600,
                                      1500 if low else 20000,fallback=True,
                                      legacy_range_first=policy=='0',refine_quality=policy in ('3','4') or (policy=='2' and low),
                                      reject_early_outside=policy in ('3','4') and low)
    if gated and int(cpu['reads'])!=0:raise ValueError('early gate read scores')
    if cpu['ok'] not in ('true','false'):raise ValueError('invalid qualification flag')
    if expected is None:
        if any(cpu[k]!='0' for k in ('mhz','raw','ppm')) or cpu['ok']!='false':
            raise ValueError('unexpected CPU candidate')
    else:
        for field,key in [('mhz','hz'),('raw','unrefined_hz')]:
            tolerance=.001+expected[key]*(2**(.005/1200)-1)
            if abs(int(cpu[field])/1000-expected[key])>=tolerance:
                raise ValueError('CPU frequency disagrees with host model')
        if abs(int(cpu['ppm'])/1000000-expected['clarity'])>=3e-6:
            raise ValueError('CPU clarity disagrees with host model')
        if (cpu['ok']=='true')!=expected['qualified']:
            raise ValueError('CPU qualification disagrees with host model')
    return dict(channel=report['ch'],bank='low' if low else 'native',
                sequence=report['seq'],hz=int(cpu['mhz'])/1000,
                qualified=cpu['ok']=='true',gated=gated,rms_counts=report['rms_counts'],
                select_ms=int(cpu['cycles'])/60000,io_ms=int(io['cycles'])/60000,
                reads=int(cpu['reads']),energy=report['energy'],scaled=report['scaled'],
                clipped=report['clipped'],frame_samples=report['n'],last=report['last'],
                policy=int(policy),**guard_fields(cpu))


def analyze(text):
    errors=re.findall(r'^NSDF ERROR[^\n]*',text,re.M)
    if errors:raise ValueError('acquisition errors: '+repr(errors))
    triples=re.findall(r'^(NSDF CPU [^\n]+)\n(NSDF IO [^\n]+)\n'
                       r'(NSDF BEGIN [^\n]*\n.*?NSDF END\n)',text,re.M|re.S)
    if not triples:raise ValueError('no complete CPU/IO/score triples')
    for c,i,b in triples:
        cpu=dict(p.split('=') for p in c.split()[2:])
        io=dict(p.split('=') for p in i.split()[2:])
        yield validate(cpu,io,b)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    args=parser.parse_args()
    for report in analyze(args.log.read_text()):print(json.dumps(report))
