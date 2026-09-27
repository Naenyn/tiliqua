"""Read an INTONO diagnostic through the apfbug USB-UART bridge.

Run after flashing, before the user starts CAL. Only complete 2048-sample
captures are written; partial/backpressured exports are reported as incomplete.
"""
import argparse
import json
import time
from pathlib import Path
import serial
from serial.tools.list_ports import comports


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    parser.add_argument("--timeout",type=float,default=3600)
    parser.add_argument("--monitor",action="store_true",help="Keep logging results after a waveform export")
    args=parser.parse_args()
    ports=[p.device for p in comports() if (p.vid,p.pid)==(0x1209,0xc0ca)]
    if len(ports)!=1:
        raise SystemExit(f"Expected one Tiliqua diagnostic port, found {ports}")
    link=serial.Serial(port=None,baudrate=115200,timeout=0.5)
    # apfbug's tud_cdc_line_state_cb requires DTR to forward UART data;
    # leaving it low discards the export. DTR enables CDC, not target reset.
    # Keep RTS low and never use the bridge's 1200-baud bootloader trigger.
    link.dtr=True;link.rts=False;link.port=ports[0];link.open()
    print(f"Listening on {ports[0]}; start CAL on the module.",flush=True)
    deadline=time.monotonic()+args.timeout
    header=None;samples=[];buffer=b"";captures=0
    log_path=Path(args.output).with_suffix(".serial.log")
    print(f"Saving serial transcript to {log_path}",flush=True)
    with link,log_path.open("a") as log:
        while time.monotonic()<deadline:
            buffer+=link.read(4096)
            while b"\n" in buffer:
                raw,buffer=buffer.split(b"\n",1)
                line=raw.decode("ascii",errors="replace").strip()
                log.write(line+"\n");log.flush()
                if line=="CAPTURE READY":
                    print("INTONO diagnostic link confirmed; ready for CAL.",flush=True)
                elif line.startswith("CAL SOURCE "):
                    print(line,flush=True)
                elif line.startswith("CAPTURE BEGIN "):
                    header=dict(item.split("=",1) for item in line.split()[2:])
                    samples=[];print(line,flush=True)
                elif line=="CAPTURE END" and header is not None:
                    if len(samples)!=2048:
                        raise SystemExit(f"Incomplete capture: {len(samples)} samples")
                    output=Path(args.output)
                    captures+=1
                    if captures>1:output=output.with_name(f"{output.stem}-{captures}{output.suffix}")
                    output.write_text(json.dumps({"header":header,"samples":samples})+"\n")
                    print(f"Saved 2048 samples to {output}",flush=True)
                    if not args.monitor:return
                    header=None;samples=[]
                elif header is not None:
                    if len(line)!=4 or any(c not in "0123456789ABCDEF" for c in line):
                        raise SystemExit(f"Corrupt capture line: {line!r}")
                    value=int(line,16);samples.append(value if value<32768 else value-65536)
                elif line:
                    print(line,flush=True)
            if len(buffer)>4096:
                raise SystemExit("Malformed diagnostic stream")
    if not args.monitor and not captures:
        raise SystemExit("Timed out without a complete capture")
    print(f"Monitoring ended; saved {captures} captures. Transcript: {log_path}",flush=True)


if __name__=="__main__":
    main()
