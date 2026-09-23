"""Bounded, DAC-acknowledged calibration CV with a CPU-heartbeat watchdog."""
from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


class CalibrationOutput(wiring.Component):
    def __init__(self, watchdog_cycles=6_000_000,
                 minimum_counts=-20_000, maximum_counts=20_000):
        if not (-32768 <= minimum_counts < maximum_counts <= 32767):
            raise ValueError("output limits must be ordered signed 16-bit values")
        self.watchdog_cycles = watchdog_cycles
        self.minimum_counts = minimum_counts
        self.maximum_counts = maximum_counts
        super().__init__({
            "command": In(32), "write": In(1), "advance": In(1),
            "value": Out(16), "channel": Out(2), "input": Out(2),
            "active": Out(1), "fault": Out(1), "token": Out(8), "changed": Out(1),
        })

    def elaborate(self, platform):
        m = Module()
        pending = Signal()
        command = Signal(32)
        age = Signal(range(self.watchdog_cycles + 1))
        enabled = Signal()
        value = Signal(16)
        m.d.comb += [self.active.eq(enabled & ~self.fault),
                     self.value.eq(Mux(self.active, value, 0)), self.changed.eq(0),
                     self.input.eq(command[19:21])]
        with m.If(enabled):
            with m.If(age == self.watchdog_cycles - 1):
                m.d.sync += [self.fault.eq(1), enabled.eq(0), pending.eq(0)]
            with m.Else():
                m.d.sync += age.eq(age + 1)
        with m.If(pending & self.advance):
            m.d.sync += [pending.eq(0), self.token.eq(command[21:29]),
                         self.channel.eq(command[16:18]),
                         value.eq(command[:16]), enabled.eq(command[18] & ~self.fault)]
            # Bit 29 marks continuous performance CV: do not repeatedly clear
            # audio pitch acquisition on every acknowledged playback update.
            m.d.comb += self.changed.eq(command[18] & ~command[29] &
                ((self.token != command[21:29]) | ~enabled))
        with m.If(self.write):
            # Calibrated 4 counts/mV. Limits default to the conservative
            # -5..+5 V envelope, but a peripheral may opt into a documented
            # wider hardware range. The payload remains a 16-bit bit pattern
            # all the way to the signed ASQ DAC.
            # A malformed command fails closed. Faults need explicit disable
            # before another enabled command can re-arm the output.
            signed_value = self.command[:16].as_signed()
            with m.If((signed_value < self.minimum_counts) |
                      (signed_value > self.maximum_counts)):
                m.d.sync += [self.fault.eq(1), enabled.eq(0), pending.eq(0)]
            with m.Elif(~self.command[18]):
                m.d.sync += [self.fault.eq(0), enabled.eq(0), age.eq(0),
                             command.eq(self.command), pending.eq(1)]
            with m.Elif(~self.fault):
                m.d.sync += [command.eq(self.command), pending.eq(1), age.eq(0)]
        return m
