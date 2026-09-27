"""Summarize one continuous INTONO serial session, without claiming accuracy.

Input must contain a single boot/session; concatenated boots and missing report
slots are rejected by the existing strict parser. Use --last-seconds to inspect
a stationary tail, not to disguise a reset or repair an incomplete transcript.
Only decimated UART observations are available, not every acquired frame.
"""
import argparse
import json
import math
import statistics
from pathlib import Path
from analyze_nsdf_schedule import analyze_schedule


def summarize(text, last_seconds=None):
    records=list(analyze_schedule(text))
    if last_seconds is not None:
        if not math.isfinite(last_seconds) or last_seconds<=0:
            raise ValueError('Tail duration must be finite and positive')
        end=records[-1]['ms']
        records=[r for r in records if ((end-r['ms'])&0xffffffff)<=last_seconds*1000]
    groups=[];cpu=[]
    for channel in range(4):
        for low in (False,True):
            rows=[r for r in records if (r['ch'],r['low'])==(channel,low)]
            if not rows:continue
            first,last=rows[0],rows[-1]
            elapsed=(last['ms']-first['ms'])&0xffffffff
            qualified=[r['hz'] for r in rows if r['ok']]
            cents=[1200*math.log2(hz) for hz in qualified]
            fraction=((last['work']-first['work'])&0xffffffff)/(60000*elapsed) if elapsed else None
            # Counter wrap is safe over bounded intervals, but an interval long
            # enough for multiple CPU-cycle wraps cannot support this estimate.
            if elapsed>=2**32/60000:fraction=None
            cpu.append(fraction)
            groups.append(dict(channel=channel,bank='low' if low else 'native',
                reports=len(rows),qualified_reports=len(qualified),
                first_ms=first['ms'],last_ms=last['ms'],duration_seconds=elapsed/1000,
                observed_min_hz=min(qualified) if qualified else None,
                observed_max_hz=max(qualified) if qualified else None,
                observed_mean_hz=statistics.mean(qualified) if qualified else None,
                observed_span_cents=max(cents)-min(cents) if cents else None,
                observed_stddev_cents=statistics.pstdev(cents) if cents else None,
                acquisitions_per_second=(last['count']-first['count'])*1000/elapsed if elapsed else None,
                max_reported_age_ms=max(r['age'] for r in rows),
                max_reported_acquisition_ms=max(r['dt'] for r in rows),
                max_reported_selector_ms=max(r['cycles'] for r in rows)/60000,
                observed_selector_cpu_percent=fraction*100 if fraction is not None else None,
                cumulative_faults=max(r['faults'] for r in rows)))
    return dict(banks=groups,
        observed_total_selector_cpu_percent=sum(cpu)*100 if len(cpu)==8 and all(x is not None for x in cpu) else None,
        caveats=['Frequency spread measures repeatability only with a stationary input; not absolute accuracy.',
                 'Qualification and maxima describe logged observations, not every acquired frame or worst-case timing.',
                 'CPU estimate covers selector/guard work only; bank observation intervals are not synchronized.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    parser.add_argument('--last-seconds',type=float)
    args=parser.parse_args()
    try:result=summarize(args.log.read_text(),args.last_seconds)
    except (ValueError,OSError) as exc:parser.exit(1,f'Invalid session: {exc}\n')
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
