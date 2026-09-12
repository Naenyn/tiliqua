"""Read one validated four-channel/two-bank diagnostic cycle, then disconnect.

Capture starts at an arbitrary UART position. Boundary fragments are ignored,
never stitched to another session. Reports go to stdout; status goes to stderr.
No commands are sent to firmware and no bitstream is flashed.
"""
import argparse
import sys
import time
from analyze_nsdf_cpu import analyze


def complete_cycle(text):
    try:
        reports=list(analyze(text))
    except ValueError as exc:
        if str(exc)=='no complete CPU/IO/score triples':return False
        raise
    return {(r['channel'],r['bank']) for r in reports} >= {
        (channel,bank) for channel in range(4) for bank in ('native','low')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port',help='Confirmed debug serial device, not flashing port')
    parser.add_argument('--timeout',type=float,default=180,help='Maximum capture seconds')
    args=parser.parse_args()
    if not 0<args.timeout<=600:parser.error('timeout must be >0 and <=600 seconds')
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
                if line=='NSDF END\n' and complete_cycle(''.join(fragments)):
                    print('Validated all four channels and both banks; disconnected.',file=sys.stderr)
                    return
            if sum(map(len,fragments))+len(pending)>1048576:
                raise RuntimeError('diagnostic capture exceeded 1 MiB bound')
    raise RuntimeError('capture timed out before a complete validated cycle')


if __name__=='__main__':main()
