# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import stream, wiring
from amaranth.lib.wiring import In, Out

from ..video.types import Pixel
from .line import LineCmd, LineStripCmd


class EraseBeforeDraw(wiring.Component):

    """
    Before each trace segment inside the plot rectangle, erase that column
    over ``[plot_y_lo, plot_y_hi)``.  Segments outside the plot bounds pass
    through without a column erase.
    """

    def __init__(self):
        super().__init__({
            "trace": In(stream.Signature(LineCmd)),
            "plot_x_lo": In(signed(16)),
            "plot_x_hi": In(signed(16)),
            "plot_y_lo": In(signed(16)),
            "plot_y_hi": In(signed(16)),
            "o": Out(stream.Signature(LineCmd)),
        })

    def elaborate(self, platform):
        m = Module()

        latched = Signal(LineCmd)
        erase_x = Signal(signed(12))
        in_plot = Signal()
        black = Signal(Pixel)
        m.d.comb += [
            black.color.eq(0),
            black.intensity.eq(0),
        ]

        with m.FSM() as fsm:
            with m.State("IDLE"):
                m.d.comb += [
                    self.o.valid.eq(0),
                    self.trace.ready.eq(1),
                    in_plot.eq(
                        self.trace.valid &
                        (self.trace.payload.x >= self.plot_x_lo) &
                        (self.trace.payload.x < self.plot_x_hi)
                    ),
                ]
                with m.If(self.trace.valid):
                    m.d.sync += [
                        latched.eq(self.trace.payload),
                        erase_x.eq(self.trace.payload.x),
                    ]
                    m.d.comb += self.trace.ready.eq(0)
                    with m.If(in_plot):
                        m.next = "ERASE"
                    with m.Else():
                        m.next = "EMIT"

            with m.State("ERASE"):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.trace.ready.eq(0),
                    self.o.payload.use_seg.eq(1),
                    self.o.payload.x0.eq(erase_x),
                    self.o.payload.y0.eq(self.plot_y_lo),
                    self.o.payload.x.eq(erase_x),
                    self.o.payload.y.eq(self.plot_y_hi - 1),
                    self.o.payload.pixel.eq(black),
                    self.o.payload.cmd.eq(LineStripCmd.END),
                ]
                with m.If(self.o.ready):
                    m.next = "EMIT"

            with m.State("EMIT"):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.payload.eq(latched),
                    self.trace.ready.eq(0),
                ]
                with m.If(self.o.ready):
                    m.d.comb += self.trace.ready.eq(1)
                    m.next = "IDLE"

        return m
