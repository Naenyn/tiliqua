# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import stream, wiring
from amaranth.lib.wiring import In, Out

from .plot import PlotRequest


class PlotClip(wiring.Component):

    """Drop ``PlotRequest`` pixels outside the waveform rectangle."""

    def __init__(self):
        super().__init__({
            "x_lo": In(signed(16)),
            "x_hi": In(signed(16)),
            "y_lo": In(signed(16)),
            "y_hi": In(signed(16)),
            "i": In(stream.Signature(PlotRequest)),
            "o": Out(stream.Signature(PlotRequest)),
        })

    def elaborate(self, platform):
        m = Module()

        inside = Signal()
        m.d.comb += inside.eq(
            (self.i.payload.x >= self.x_lo) &
            (self.i.payload.x < self.x_hi) &
            (self.i.payload.y >= self.y_lo) &
            (self.i.payload.y < self.y_hi)
        )

        m.d.comb += [
            self.o.payload.eq(self.i.payload),
            self.o.valid.eq(self.i.valid & inside),
            self.i.ready.eq(Mux(inside, self.o.ready, 1)),
        ]

        return m
