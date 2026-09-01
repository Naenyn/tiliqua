# Copyright (c) 2024 S. Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out

from amaranth_future import fixed

from . import ASQ


class TriggerLowPass(wiring.Component):

    """Cheap two-pole low-pass used only to condition a trigger signal.

    Mode 0 is an exact bypass. Modes 1 through 4 cascade two shift-only
    one-pole sections with shifts 5, 7, 9, and 11. At OSCIO's 1.536 MHz
    interpolated sample rate their combined -3 dB frequencies are
    approximately 5 kHz, 1.2 kHz, 300 Hz, and 75 Hz respectively.

    The filter states track the input while bypassed so enabling a filter does
    not begin with a large zero-to-signal settling transient. Extra fractional
    state bits keep the lower cutoff modes moving even for small input changes.
    """

    def __init__(self, shape=ASQ, *, extra_bits=8):
        self.shape = shape
        self.state_shape = fixed.SQ(shape.i_bits, shape.f_bits + extra_bits)
        super().__init__({
            "i": In(stream.Signature(shape)),
            "mode": In(unsigned(3)),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        state1 = Signal(self.state_shape)
        state2 = Signal(self.state_shape)
        sample = Signal(self.state_shape)
        shift = Signal(unsigned(4), init=5)
        delta1 = Signal(signed(self.state_shape.width + 1))
        delta2 = Signal(signed(self.state_shape.width + 1))

        with m.Switch(self.mode):
            with m.Case(2):
                m.d.comb += shift.eq(7)
            with m.Case(3):
                m.d.comb += shift.eq(9)
            with m.Case(4):
                m.d.comb += shift.eq(11)
            with m.Default():
                m.d.comb += shift.eq(5)

        m.d.comb += [
            sample.as_value().eq(
                self.i.payload.as_value() <<
                (self.state_shape.f_bits - self.shape.f_bits)),
            delta1.eq(sample.as_value() - state1.as_value()),
            delta2.eq(state1.as_value() - state2.as_value()),
            self.o.valid.eq(self.i.valid),
            self.i.ready.eq(self.o.ready),
            self.o.payload.as_value().eq(Mux(
                self.mode == 0,
                self.i.payload.as_value(),
                state2.as_value() >>
                (self.state_shape.f_bits - self.shape.f_bits),
            )),
        ]

        with m.If(self.i.valid & self.o.ready):
            with m.If(self.mode == 0):
                m.d.sync += [
                    state1.eq(sample),
                    state2.eq(sample),
                ]
            with m.Else():
                m.d.sync += [
                    state1.as_value().eq(state1.as_value() + (delta1 >> shift)),
                    state2.as_value().eq(state2.as_value() + (delta2 >> shift)),
                ]

        return m


class AutoTrigger(wiring.Component):

    """Pass trigger edges through, or pulse after a bounded idle wait.

    ``waiting`` must describe a state in which a timeout pulse can actually be
    consumed. This keeps buffer swaps and other downstream stalls from using
    up the timeout invisibly.
    """

    def __init__(self, *, timeout_cycles):
        if timeout_cycles < 2:
            raise ValueError("timeout_cycles must be at least 2")
        self.timeout_cycles = timeout_cycles
        super().__init__({
            "edge": In(1),
            "waiting": In(1),
            "enable": In(1),
            "o": Out(1),
        })

    def elaborate(self, platform):
        m = Module()

        counter = Signal(range(self.timeout_cycles))
        expired = Signal()

        m.d.comb += [
            expired.eq(
                self.enable & self.waiting &
                (counter == self.timeout_cycles - 1)),
            # A real edge always passes through. The caller still decides
            # whether the acquisition engine is in a state that can use it.
            self.o.eq(self.edge | expired),
        ]

        with m.If(~self.enable | ~self.waiting | self.edge | expired):
            m.d.sync += counter.eq(0)
        with m.Else():
            m.d.sync += counter.eq(counter + 1)

        return m


class Trigger(wiring.Component):

    """
    When trigger condition is met, output is set to 1, for 1 stream cycle.

    Rising or falling edge (``falling`` input).  Re-arms once the sample
    returns to the idle side of the threshold by at least ``hysteresis``.
    """

    def __init__(self, shape=ASQ, *, tap=False, hysteresis=0):
        self.shape = shape
        self.tap = tap
        self.hysteresis = hysteresis
        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "sample":    shape,
                "threshold": shape,
            }))),
            "falling": In(unsigned(1)),
            "o": Out(stream.Signature(unsigned(1))),
        })

    def elaborate(self, platform):
        m = Module()

        l_sample = Signal(shape=self.shape)
        armed = Signal(reset=1)
        crossed_rise = Signal()
        crossed_fall = Signal()
        crossed = Signal()
        rearm_rise_level = Signal(shape=self.shape)
        rearm_fall_level = Signal(shape=self.shape)
        hysteresis = fixed.Const(self.hysteresis, shape=self.shape)

        m.d.comb += [
            self.o.valid.eq(self.i.valid),
            rearm_rise_level.eq(self.i.payload.threshold - hysteresis),
            rearm_fall_level.eq(self.i.payload.threshold + hysteresis),
            crossed_rise.eq(
                (l_sample              < self.i.payload.threshold) &
                (self.i.payload.sample >= self.i.payload.threshold)
            ),
            crossed_fall.eq(
                (l_sample              >= self.i.payload.threshold) &
                (self.i.payload.sample <  self.i.payload.threshold)
            ),
            crossed.eq(Mux(self.falling, crossed_fall, crossed_rise)),
            self.o.payload.eq(crossed & armed),
        ]
        if self.tap:
            m.d.comb += self.i.ready.eq(1)
        else:
            m.d.comb += self.i.ready.eq(self.o.ready)

        with m.If(self.i.valid & self.o.ready):
            m.d.sync += l_sample.eq(self.i.payload.sample)
            with m.If(self.falling):
                with m.If(self.i.payload.sample >= rearm_fall_level):
                    m.d.sync += armed.eq(1)
                with m.Elif(crossed):
                    m.d.sync += armed.eq(0)
            with m.Else():
                with m.If(self.i.payload.sample < rearm_rise_level):
                    m.d.sync += armed.eq(1)
                with m.Elif(crossed):
                    m.d.sync += armed.eq(0)

        return m


class Ramp(wiring.Component):

    """
    If trigger strobes a 1, ramps from -1 to 1, staying at 1 until retriggered.
    A retrigger mid-ramp does not restart the ramp until the output has reached 1.
    """

    TIMEBASE_SQ = fixed.SQ(8, 24)

    def __init__(self, shape=ASQ, shift=6, *, timebase_shape=None):
        self.shape = shape
        self.shift = shift
        self.timebase_shape = timebase_shape or self.TIMEBASE_SQ
        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "trigger":  unsigned(1),
                "td":       self.timebase_shape, # time delta
            }))),
            # The default users tie this to approximately +1. OSCilloscope
            # capture can stop earlier so no sample time is spent beyond the
            # visible viewport.
            "end": In(shape),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        s = Signal(self.timebase_shape)
        at_top = Signal()

        m.d.comb += [
            self.o.valid.eq(self.i.valid),
            self.i.ready.eq(self.o.ready),
            self.o.payload.eq(s >> self.shift),
            at_top.eq(self.o.payload >= self.end),
        ]

        with m.If(self.i.valid & self.o.ready):
            with m.If(at_top):
                with m.If(self.i.payload.trigger):
                    m.d.sync += s.eq(fixed.Const(-1.0, shape=self.shape, clamp=True) << self.shift)
            with m.Else():
                m.d.sync += s.eq(s + self.i.payload.td)

        return m
