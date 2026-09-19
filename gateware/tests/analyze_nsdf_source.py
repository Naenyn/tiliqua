"""Validate frozen source moments alongside complete CPU/IO/score records.

Relative-energy qualification is a host-only diagnostic here. Low-bank
sequences have a different origin/rate; only new captures with explicit native
frame endpoints receive a low-bank decision. Legacy records remain readable
without inventing alignment. No candidate or device output is changed.
"""
import argparse
import json
import math
from pathlib import Path
import re
from analyze_nsdf_cpu import analyze


def analyze_source(text):
    # A connection can begin after SOURCE but before CPU for the same frame.
    # Discard only the prefix before the first complete source header, matching
    # the capture helper. Never excuse missing metadata inside the capture.
    if re.search(r'^NSDF ERROR',text,re.M):raise ValueError('source capture contains acquisition error')
    start=re.search(r'^NSDF SOURCE ',text,re.M)
    if start is None:raise ValueError('no source metadata')
    text=text[start.start():]
    sources={}
    for line in re.findall(r'^NSDF SOURCE [^\n]+',text,re.M):
        source=dict(p.split('=') for p in line.split()[2:])
        key=tuple(source[k] for k in ('ch','low','seq'))
        if key in sources:raise ValueError('duplicate source identity')
        sources[key]=source
    for report in analyze(text):
        key=(str(report['channel']),'true' if report['bank']=='low' else 'false',str(report['sequence']))
        if key not in sources:raise ValueError('complete score frame lacks source metadata')
        source=sources[key]
        yield source_details(report,source)


def source_details(report,source):
    n=int(source['n']);total=int(source['sum']);squares=int(source['squares'])
    status=int(source['status']);end=int(source['end'])
    if status&~15 or status>>2!=report['channel']:raise ValueError('source channel/status mismatch')
    if status&2:raise ValueError('source acquisition overrun')
    if not 0<=end<1<<32 or not 0<=n<=20480 or n%512:
        raise ValueError('invalid source window')
    if bool(status&1)!=(n==20480):raise ValueError('source readiness mismatch')
    if abs(total)>n*32768 or not 0<=squares<=n*(1<<30) or total*total>squares*n:
        raise ValueError('impossible source moments')
    rms=math.sqrt((squares*n-total*total)/(n*n)) if n else 0.0
    age=None;relative_pass=None;low_relative_pass=None;endpoint_offset=None
    if 'frame_end' in source:
        frame_end=int(source['frame_end'])
        if not 0<=frame_end<1<<32:raise ValueError('invalid frame endpoint')
        endpoint_offset=((frame_end-end+(1<<31))&0xffffffff)-(1<<31)
        if report['bank']=='native' and frame_end!=report['sequence']:
            raise ValueError('native frame endpoint mismatch')
        # Low frames finish FIR computation after their newest contributing
        # native sample. Source publication can lead or trail that endpoint.
        # This bounds alignment, not equality of differently filtered windows.
        if status&1 and not -512<=endpoint_offset<=512:
            raise ValueError('source/frame endpoint separation too large')
        if report['bank']=='low' and status&1:
            low_relative_pass=report['rms_counts']>max(2,.02*rms)
    if report['bank']=='native':
        age=(report['sequence']-end)&0xffffffff
        if status&1:
            # Block publication plus snapshot start may cross one sample
            # group. Keep this allowance explicit and validate on hardware.
            if age>512:raise ValueError('stale or future source window')
            relative_pass=report['rms_counts']>max(2,.1*rms)
    if 'device_guard' in report:
        energy=report['energy']*(4 if report['scaled'] else 1)
        frame_n=report.get('frame_samples',604 if report['bank']=='low' else 674)
        source_power=(squares*n-total*total+n*n-1)//(n*n) if n else 0
        expected=(bool(status&1) and endpoint_offset is not None and not report['clipped']
                  and energy>4*frame_n
                  and energy*(2500 if report['bank']=='low' else 100)>source_power*frame_n)
        if report['device_guard']!=expected:
            raise ValueError('device source guard disagrees with integer reference')
    return dict(**report,source_end=end,source_samples=n,source_rms=rms,
               source_ready=bool(status&1),source_age_native=age,
               native_relative_energy_pass=relative_pass,
               source_frame_offset_native=endpoint_offset,
               low_relative_energy_pass=low_relative_pass)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path);args=parser.parse_args()
    for result in analyze_source(args.log.read_text()):print(json.dumps(result))
