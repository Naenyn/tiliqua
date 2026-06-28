# Copyright (c) 2024 S. Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out

from amaranth_future import fixed

from . import ASQ


class Trigger(wiring.Component):

    """
    When trigger condition is met, output is set to 1, for 1 stream cycle.

    Rising edge only.  Re-arms once the sample falls back below threshold.
    """

    def __init__(self, shape=ASQ):
        self.shape = shape
        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "sample":    shape,
                "threshold": shape,
            }))),
            "o": Out(stream.Signature(unsigned(1))),
        })

    def elaborate(self, platform):
        m = Module()

        l_sample = Signal(shape=self.shape)
        armed = Signal(reset=1)
        crossed = Signal()

        m.d.comb += [
            self.o.valid.eq(self.i.valid),
            self.i.ready.eq(self.o.ready),
            crossed.eq(
                (l_sample              < self.i.payload.threshold) &
                (self.i.payload.sample >= self.i.payload.threshold)
            ),
            self.o.payload.eq(crossed & armed),
        ]

        with m.If(self.i.valid & self.o.ready):
            m.d.sync += l_sample.eq(self.i.payload.sample)
            with m.If(self.i.payload.sample < self.i.payload.threshold):
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

    def __init__(self, shape=ASQ, shift=6):
        self.shape = shape
        self.shift = shift
        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "trigger":  unsigned(1),
                "td":       self.TIMEBASE_SQ, # time delta
            }))),
            "o": Out(stream.Signature(shape)),
        })

    def elaborate(self, platform):
        m = Module()

        s = Signal(self.TIMEBASE_SQ)
        at_top = Signal()

        m.d.comb += [
            self.o.valid.eq(self.i.valid),
            self.i.ready.eq(self.o.ready),
            self.o.payload.eq(s >> self.shift),
            at_top.eq(self.o.payload > fixed.Const(0.985, shape=self.shape)),
        ]

        with m.If(self.i.valid & self.o.ready):
            with m.If(at_top):
                with m.If(self.i.payload.trigger):
                    m.d.sync += s.eq(fixed.Const(-1.0, shape=self.shape, clamp=True) << self.shift)
            with m.Else():
                m.d.sync += s.eq(s + self.i.payload.td)

        return m
