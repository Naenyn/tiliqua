"""Parse nextpnr clock summaries and enforce release headroom."""

from dataclasses import dataclass
import re


CLOCK_LINE = re.compile(
    r"Max frequency for clock\s+'(?P<clock>[^']+)':\s+"
    r"(?P<actual>[0-9.]+) MHz \((?P<status>PASS|FAIL) at "
    r"(?P<required>[0-9.]+) MHz\)")


@dataclass(frozen=True)
class ClockTiming:
    clock: str
    actual_mhz: float
    required_mhz: float
    reported_status: str

    @property
    def headroom_percent(self) -> float:
        return (self.actual_mhz / self.required_mhz - 1.0) * 100.0


def parse_timing_report(report: str) -> list[ClockTiming]:
    """Extract the final per-clock frequency summary from a nextpnr log."""
    timings = {}
    for match in CLOCK_LINE.finditer(report):
        timing = ClockTiming(
            clock=match.group("clock"),
            actual_mhz=float(match.group("actual")),
            required_mhz=float(match.group("required")),
            reported_status=match.group("status"),
        )
        # nextpnr prints a placement estimate followed by the authoritative
        # post-route summary. Assignment preserves the original clock order
        # while replacing each estimate with its final value.
        timings[timing.clock] = timing
    return list(timings.values())


def insufficient_clocks(
        timings: list[ClockTiming], minimum_headroom_percent: float,
) -> list[ClockTiming]:
    return [
        timing for timing in timings
        if timing.reported_status != "PASS"
        or timing.headroom_percent < minimum_headroom_percent
    ]
