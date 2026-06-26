# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import stream, wiring
from amaranth.lib.wiring import In, Out

from .plot import BlendMode, OffsetMode, PlotRequest


class RegionClear(wiring.Component):

    """
    Fill a center-coordinate rectangle with black ``REPLACE`` pixels.

    ``start`` is a one-cycle pulse; bounds are ``[x_lo, x_hi)`` x ``[y_lo, y_hi)``.
    """

    def __init__(self):
        super().__init__({
            "start": In(1),
            "x_lo": In(signed(16)),
            "x_hi": In(signed(16)),
            "y_lo": In(signed(16)),
            "y_hi": In(signed(16)),
            "o": Out(stream.Signature(PlotRequest)),
        })

    def elaborate(self, platform):
        m = Module()

        x = Signal(signed(16))
        y = Signal(signed(16))

        m.d.comb += [
            self.o.payload.x.eq(x),
            self.o.payload.y.eq(y),
            self.o.payload.offset.eq(OffsetMode.CENTER),
            self.o.payload.blend.eq(BlendMode.REPLACE),
            self.o.payload.pixel.intensity.eq(0),
            self.o.payload.pixel.color.eq(0),
        ]

        with m.FSM() as fsm:
            with m.State("IDLE"):
                m.d.comb += self.o.valid.eq(0)
                with m.If(self.start):
                    m.d.sync += [
                        x.eq(self.x_lo),
                        y.eq(self.y_lo),
                    ]
                    m.next = "PLOT"

            with m.State("PLOT"):
                m.d.comb += self.o.valid.eq(1)
                with m.If(self.o.ready):
                    with m.If((x == (self.x_hi - 1)) & (y == (self.y_hi - 1))):
                        m.next = "IDLE"
                    with m.Elif(x == (self.x_hi - 1)):
                        m.d.sync += [
                            x.eq(self.x_lo),
                            y.eq(y + 1),
                        ]
                    with m.Else():
                        m.d.sync += x.eq(x + 1)

        return m
