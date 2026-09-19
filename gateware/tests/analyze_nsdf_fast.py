"""Validate timestamped summaries; no score/model parity claim without scores."""
import argparse
import json
import math
from pathlib import Path
from analyze_nsdf_source import source_details
from analyze_nsdf_cpu import guard_fields


def analyze_fast(text,round_robin=False):
    source=cpu=None;previous=None;seen=False;bank_ends={}
    for line in text.splitlines(keepends=True):
        if line.startswith('NSDF ERROR'):raise ValueError('acquisition error')
        if not line.endswith('\n'):continue # Incomplete final serial line.
        if not line.startswith(('NSDF SOURCE ','NSDF CPU ','NSDF FAST ')):continue
        kind=line.split()[1]
        fields=dict(p.split('=') for p in line.split()[2:])
        if kind=='SOURCE':
            if source is not None:raise ValueError('incomplete summary inside capture')
            source=fields;continue
        if source is None:continue # Connection prefix, never stitch.
        if kind=='CPU':
            if cpu is not None:raise ValueError('duplicate CPU summary')
            cpu=fields;continue
        if cpu is None:raise ValueError('missing CPU summary')
        for k in ('ch','low','seq'):
            if fields[k]!=source[k] or fields[k]!=cpu[k]:raise ValueError('mixed summary identity')
        if fields['low'] not in ('true','false') or cpu['ok'] not in ('true','false'):
            raise ValueError('invalid boolean')
        policy=cpu.get('policy','0')
        if policy not in ('0','1','2','3','4'):raise ValueError('unknown selector policy')
        low=fields['low']=='true';n=604 if low and policy not in ('2','3','4') else 674
        count=(622 if policy in ('2','3','4') else 302) if low else (622 if policy in ('3','4') else 322)
        channel=int(fields['ch']);sequence=int(fields['seq'])
        if not 0<=channel<(4 if round_robin else 1) or not 0<=sequence<1<<32:raise ValueError('invalid fast channel/sequence')
        energy=int(fields['energy']);scaled=int(fields['scaled']);clipped=int(fields['clipped'])
        if not 0<=energy<=n*(1<<30) or scaled not in (0,1) or clipped not in (0,1):
            raise ValueError('invalid frame energy/flags')
        reads=int(cpu['reads']);cycles=int(cpu['cycles']);hz=int(cpu['mhz'])/1000
        if not 0<=reads<=2*count+63 or cycles<=0:
            raise ValueError('invalid selector work')
        if not 0<=int(cpu['ppm'])<=1000000 or not 0<=hz<=20000:
            raise ValueError('invalid pitch summary')
        rms=math.sqrt(energy/n)*(2 if scaled else 1)
        qualified=cpu['ok']=='true';gated=rms<=2 or bool(clipped)
        if gated and (reads or qualified or hz):raise ValueError('early gate mismatch')
        if qualified and not (20<=hz<=1500 if low else 600<=hz<=20000):
            raise ValueError('qualified pitch outside bank')
        start=int(fields['start_ms']);end=int(fields['end_ms'])
        if not 0<=start<=end<1<<64 or end-start>=1000:raise ValueError('invalid summary timing')
        report=dict(channel=channel,bank='low' if low else 'native',sequence=sequence,
                    rms_counts=rms,qualified=qualified,gated=gated,hz=hz,
                    reads=reads,select_ms=cycles/60000,energy=energy,scaled=scaled,
                    clipped=clipped,frame_samples=n,policy=int(policy),**guard_fields(cpu))
        if 'frame_end' not in source:raise ValueError('fast summary lacks native endpoint')
        report=source_details(report,source)
        interval=None
        if previous is not None:
            old_start,old_channel,old_bank=previous
            expected_channel=(old_channel+int(old_bank))&3 if round_robin else old_channel
            expected_low=not old_bank if round_robin else old_bank
            if channel!=expected_channel or low!=expected_low or start-old_start<50:
                raise ValueError('nonmonotonic or over-rate summary')
        key=(channel,low)
        if key in bank_ends:
            advance=(int(source['frame_end'])-bank_ends[key])&0xffffffff
            if not 0<advance<1<<31:raise ValueError('nonmonotonic bank endpoint')
            interval=advance/192 # Native samples to ms at 192 kHz.
        bank_ends[key]=int(source['frame_end'])
        previous=(start,channel,low)
        guard=report['low_relative_energy_pass'] if low else report['native_relative_energy_pass']
        yield dict(**report,start_ms=start,end_ms=end,frame_interval_ms=interval,
                   guarded_qualified=qualified and report.get('device_guard',guard) is True,
                   score_parity_checked=False)
        seen=True;source=cpu=None
    if not seen:raise ValueError('no complete fast summaries')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('log',type=Path)
    args=parser.parse_args()
    for report in analyze_fast(args.log.read_text()):print(json.dumps(report))
