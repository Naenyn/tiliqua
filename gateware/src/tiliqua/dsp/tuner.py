# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Low-cost streaming measurements for the tuner proof of concept."""

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In
from amaranth_soc import csr

from . import ASQ


class TunerPeripheral(wiring.Component):
    """Measure pitch period and voltage level on one selected audio input.

    Pitch measurement deliberately uses a hysteretic positive crossing detector
    in this first proof of concept.  Rather than rounding each individual period,
    it counts complete cycles over a minimum observation interval.  This keeps
    the implementation small while giving oscillator waveforms good resolution.

    Level snapshots are independent of pitch snapshots. ``mean_square`` is in
    squared calibrated ADC counts; firmware uses the PMOD counts-per-volt value
    to convert its square root to Vrms.
    """

    class Control(csr.Register, access="rw"):
        channel: csr.Field(csr.action.RW, unsigned(2))

    class Info(csr.Register, access="r"):
        sample_rate: csr.Field(csr.action.R, unsigned(32))

    class PitchSequence(csr.Register, access="r"):
        sequence: csr.Field(csr.action.R, unsigned(16))

    class PeriodSamples(csr.Register, access="r"):
        samples: csr.Field(csr.action.R, unsigned(32))

    class PeriodCycles(csr.Register, access="r"):
        cycles: csr.Field(csr.action.R, unsigned(16))

    class PitchAge(csr.Register, access="r"):
        samples: csr.Field(csr.action.R, unsigned(32))

    class LevelSequence(csr.Register, access="r"):
        sequence: csr.Field(csr.action.R, unsigned(16))

    class MeanSquare(csr.Register, access="r"):
        # ASQ samples are 16-bit. Averaging the square_sum back down by the
        # window length leaves at most a 32-bit squared-sample value. Keeping
        # this register native-width also avoids a non-atomic 64-bit MMIO read
        # on the 32-bit CPU.
        value: csr.Field(csr.action.R, unsigned(32))

    class SignedLevel(csr.Register, access="r"):
        value: csr.Field(csr.action.R, unsigned(32))

    def __init__(self, *, sample_rate, min_pitch_window_s=0.05,
                 level_window_log2=13, hysteresis_counts=64,
                 dc_filter_shift=12):
        self.sample_rate = int(sample_rate)
        self.min_pitch_samples = max(1, round(sample_rate * min_pitch_window_s))
        self.level_window_log2 = level_window_log2
        self.level_window_samples = 1 << level_window_log2
        self.hysteresis_counts = hysteresis_counts
        self.dc_filter_shift = dc_filter_shift

        regs = csr.Builder(addr_width=7, data_width=8)
        self._control = regs.add("control", self.Control(), offset=0x00)
        self._info = regs.add("info", self.Info(), offset=0x04)
        self._pitch_sequence = regs.add(
            "pitch_sequence", self.PitchSequence(), offset=0x08)
        self._period_samples = regs.add(
            "period_samples", self.PeriodSamples(), offset=0x0c)
        self._period_cycles = regs.add(
            "period_cycles", self.PeriodCycles(), offset=0x10)
        self._level_sequence = regs.add(
            "level_sequence", self.LevelSequence(), offset=0x14)
        self._mean_square = regs.add(
            "mean_square", self.MeanSquare(), offset=0x18)
        self._minimum = regs.add("minimum", self.SignedLevel(), offset=0x20)
        self._maximum = regs.add("maximum", self.SignedLevel(), offset=0x24)
        self._dc = regs.add("dc", self.SignedLevel(), offset=0x28)
        self._pitch_age = regs.add(
            "pitch_age", self.PitchAge(), offset=0x2c)
        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "i": In(stream.Signature(data.ArrayLayout(ASQ, 4))),
            "bus": In(csr.Signature(
                addr_width=regs.addr_width, data_width=regs.data_width)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        sample_width = ASQ.as_shape().width
        samples = Array(self.i.payload[n].as_value() for n in range(4))
        sample = Signal(signed(sample_width))
        last_channel = Signal(2)
        dc_estimate = Signal(signed(sample_width + 2))
        ac_sample = Signal(signed(sample_width + 3))

        m.d.comb += [
            self.i.ready.eq(1),
            sample.eq(samples[self._control.f.channel.data]),
            ac_sample.eq(sample - dc_estimate),
            self._info.f.sample_rate.r_data.eq(self.sample_rate),
        ]

        # Pitch measurement state. A crossing is accepted only after the
        # waveform has visited the negative hysteresis band.
        armed = Signal()
        sample_clock = Signal(32)
        first_crossing = Signal(32)
        interval_count = Signal(16)
        pitch_sequence = Signal(16)
        period_samples = Signal(32)
        period_cycles = Signal(16)
        have_crossing = Signal()
        pitch_age = Signal(32, init=(1 << 32) - 1)
        elapsed = Signal(32)
        crossing = Signal()
        m.d.comb += [
            elapsed.eq(sample_clock - first_crossing),
            crossing.eq(armed & (ac_sample >= self.hysteresis_counts)),
            self._pitch_sequence.f.sequence.r_data.eq(pitch_sequence),
            self._period_samples.f.samples.r_data.eq(period_samples),
            self._period_cycles.f.cycles.r_data.eq(period_cycles),
            self._pitch_age.f.samples.r_data.eq(pitch_age),
        ]

        # Level measurement state. The power-of-two window avoids a divider;
        # the latched sum is shifted into a mean square.
        level_index = Signal(self.level_window_log2)
        square = Signal(unsigned(sample_width * 2))
        square_sum = Signal(unsigned(sample_width * 2 + self.level_window_log2))
        minimum = Signal(signed(sample_width))
        maximum = Signal(signed(sample_width))
        mean_square = Signal(32)
        level_minimum = Signal(signed(32))
        level_maximum = Signal(signed(32))
        level_dc = Signal(signed(32))
        level_sequence = Signal(16)
        m.d.comb += [
            square.eq(sample * sample),
            self._level_sequence.f.sequence.r_data.eq(level_sequence),
            self._mean_square.f.value.r_data.eq(mean_square),
            self._minimum.f.value.r_data.eq(level_minimum),
            self._maximum.f.value.r_data.eq(level_maximum),
            self._dc.f.value.r_data.eq(level_dc),
        ]

        with m.If(self.i.valid & self.i.ready):
            m.d.sync += [
                sample_clock.eq(sample_clock + 1),
                pitch_age.eq(Mux(pitch_age.all(), pitch_age, pitch_age + 1)),
                dc_estimate.eq(dc_estimate +
                               ((sample - dc_estimate) >> self.dc_filter_shift)),
            ]

            # Do not let a period straddle an input selection change.
            with m.If(last_channel != self._control.f.channel.data):
                m.d.sync += [
                    last_channel.eq(self._control.f.channel.data),
                    armed.eq(0),
                    have_crossing.eq(0),
                    interval_count.eq(0),
                    pitch_age.eq((1 << 32) - 1),
                ]

            with m.If(ac_sample <= -self.hysteresis_counts):
                m.d.sync += armed.eq(1)
            with m.If(crossing):
                m.d.sync += [armed.eq(0), pitch_age.eq(0)]
                with m.If(~have_crossing):
                    m.d.sync += [
                        have_crossing.eq(1),
                        first_crossing.eq(sample_clock),
                        interval_count.eq(0),
                    ]
                with m.Elif(elapsed >= self.min_pitch_samples):
                    m.d.sync += [
                        period_samples.eq(elapsed),
                        period_cycles.eq(interval_count + 1),
                        pitch_sequence.eq(pitch_sequence + 1),
                        first_crossing.eq(sample_clock),
                        interval_count.eq(0),
                    ]
                with m.Else():
                    m.d.sync += interval_count.eq(interval_count + 1)

            # Use an explicit reduction instead of comparing against an
            # unsized zero literal. The latter becomes a zero-width operand in
            # RTLIL and can lose the accumulator-reset term during synthesis.
            with m.If(~level_index.any()):
                m.d.sync += [
                    minimum.eq(sample),
                    maximum.eq(sample),
                    square_sum.eq(square),
                ]
            with m.Else():
                m.d.sync += square_sum.eq(square_sum + square)
                with m.If(sample < minimum):
                    m.d.sync += minimum.eq(sample)
                with m.If(sample > maximum):
                    m.d.sync += maximum.eq(sample)

            with m.If(level_index == self.level_window_samples - 1):
                # Include the current sample: nonblocking assignments mean the
                # running values here still describe the preceding samples.
                m.d.sync += [
                    mean_square.eq((square_sum + square) >>
                                   self.level_window_log2),
                    level_minimum.eq(Mux(sample < minimum, sample, minimum)),
                    level_maximum.eq(Mux(sample > maximum, sample, maximum)),
                    level_dc.eq(dc_estimate),
                    level_sequence.eq(level_sequence + 1),
                ]
            m.d.sync += level_index.eq(level_index + 1)

        return m
