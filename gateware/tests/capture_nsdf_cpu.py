"""Read one validated four-channel/two-bank diagnostic cycle, then disconnect.

Capture starts at an arbitrary UART position. Boundary fragments are ignored,
never stitched to another session. Reports go to stdout; status goes to stderr.
No commands are sent to firmware and no bitstream is flashed.
"""
import argparse
import sys
import time
import re
from analyze_nsdf_cpu import analyze


def complete_cycle(text,require_source=False):
    analyzer=analyze
    if require_source:
        from analyze_nsdf_source import analyze_source
        start=re.search(r'^NSDF SOURCE ',text,re.M)
        if start is None:return False
        text=text[start.start():];analyzer=analyze_source
    try:
        reports=list(analyzer(text))
    except ValueError as exc:
        if str(exc)=='no complete CPU/IO/score triples':return False
        raise
    return {(r['channel'],r['bank']) for r in reports} >= {
        (channel,bank) for channel in range(4) for bank in ('native','low')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port',help='Confirmed debug serial device, not flashing port')
    parser.add_argument('--timeout',type=float,default=180,help='Maximum capture seconds')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--source',action='store_true',help='Also require validated frozen source metadata')
    mode.add_argument('--fast',action='store_true',help='Capture timestamped summaries instead of scores')
    parser.add_argument('--fast-frames',type=int,default=200,help='Complete fast summaries to collect')
    args=parser.parse_args()
    if not 0<args.timeout<=600:parser.error('timeout must be >0 and <=600 seconds')
    if not 2<=args.fast_frames<=6000:parser.error('fast frame count must be 2..6000')
    import serial
    fragments=[]
    # Preserve partial lines across serial read timeouts. A single OS read is
    # not necessarily an entire newline-terminated protocol record.
    pending=b''
    with serial.Serial(args.port,115200,timeout=.25) as port:
        port.dtr=True;port.rts=False
        deadline=time.monotonic()+args.timeout
        while time.monotonic()<deadline:
            data=port.readline()
            if not data:continue
            sys.stdout.write(data.decode('utf-8',errors='replace'));sys.stdout.flush()
            pending+=data
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1)
                line=line.decode('utf-8',errors='replace').rstrip('\r')+'\n'
                fragments.append(line)
                if line.startswith('NSDF ERROR'):
                    raise RuntimeError(line.strip())
                if args.fast and line.startswith('NSDF BEGIN '):
                    raise RuntimeError('expected fast-summary firmware, received full score export')
                if not args.fast and line.startswith('NSDF FAST '):
                    raise RuntimeError('fast-summary firmware requires --fast capture')
                if args.fast and line.startswith('NSDF FAST '):
                    from analyze_nsdf_fast import analyze_fast
                    try:reports=list(analyze_fast(''.join(fragments)))
                    except ValueError as exc:
                        if str(exc)=='no complete fast summaries':continue
                        raise
                    if len(reports)>=args.fast_frames:
                        print(f'Validated {len(reports)} fast summaries; disconnected.',file=sys.stderr)
                        return
                if not args.fast and line=='NSDF END\n' and complete_cycle(''.join(fragments),args.source):
                    print('Validated all four channels and both banks; disconnected.',file=sys.stderr)
                    return
            # Human-operated level adjustments need more than a 50-second
            # window. This is host RAM only; retain a hard bound and deadline.
            limit=4*1048576 if args.fast else 1048576
            if sum(map(len,fragments))+len(pending)>limit:
                raise RuntimeError(f'diagnostic capture exceeded {limit//1048576} MiB bound')
    raise RuntimeError('capture timed out before a complete validated cycle')


if __name__=='__main__':main()
