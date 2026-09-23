#!/usr/bin/env python3
"""Reject FPGA routes that pass nominal timing without useful headroom."""

import argparse
from pathlib import Path

from tiliqua.build.timing import insufficient_clocks, parse_timing_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="nextpnr top.tim report")
    parser.add_argument(
        "--minimum-headroom-percent", type=float, default=1.25,
        help=("required margin above every constrained clock "
              "(default: 1.25%%)"),
    )
    args = parser.parse_args()

    timings = parse_timing_report(args.report.read_text())
    if not timings:
        parser.error(f"no per-clock frequency summaries found in {args.report}")

    print("clock                         actual   required  headroom  result")
    for timing in timings:
        accepted = (
            timing.reported_status == "PASS"
            and timing.headroom_percent >= args.minimum_headroom_percent)
        print(
            f"{timing.clock:<28} "
            f"{timing.actual_mhz:>7.2f}  {timing.required_mhz:>8.2f}  "
            f"{timing.headroom_percent:>7.2f}%  "
            f"{'ACCEPT' if accepted else 'REJECT'}")

    failures = insufficient_clocks(timings, args.minimum_headroom_percent)
    if failures:
        print(
            f"Rejected: {len(failures)} clock(s) below "
            f"{args.minimum_headroom_percent:.2f}% required headroom.")
        return 1
    print("Accepted: every constrained clock has sufficient headroom.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
