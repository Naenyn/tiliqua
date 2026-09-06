# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Small incremental filled-triangle rasterizer.

The setup path shares one signed multiplier while the pixel path advances
three edge equations using additions only. This is deliberately optimized for
the many small, adjacent triangles used by CASCADO's projected height field.
"""

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out

from ..video.types import Pixel
from .plot import BlendMode, OffsetMode, PlotRequest


class TriangleCmd(data.Struct):
    x0: signed(12)
    y0: signed(12)
    x1: signed(12)
    y1: signed(12)
    x2: signed(12)
    y2: signed(12)
    pixel: Pixel
    # Filled-span endpoint granularity: 0 = packed 4-pixel words,
    # 1 = 2-pixel pairs, 2 = exact pixels. Pixel-at-a-time consumers may
    # ignore this rendering hint.
    detail: unsigned(2)


def _min3(a, b, c):
    return Mux(a < b, Mux(a < c, a, c), Mux(b < c, b, c))


def _max3(a, b, c):
    return Mux(a > b, Mux(a > c, a, c), Mux(b > c, b, c))


class TrianglePlotter(wiring.Component):
    """Rasterize flat-shaded triangles into absolute framebuffer pixels."""

    i: In(stream.Signature(TriangleCmd))
    o: Out(stream.Signature(PlotRequest))
    h_active: In(unsigned(12))
    v_active: In(unsigned(12))
    alternate: In(1)
    busy: Out(1)

    def elaborate(self, platform):
        m = Module()

        cmd = Signal(TriangleCmd)
        min_x = Signal(signed(12))
        max_x = Signal(signed(12))
        min_y = Signal(signed(12))
        max_y = Signal(signed(12))
        x = Signal(signed(12))
        y = Signal(signed(12))

        # Edge E(a,b,p) = (px-ax)*(by-ay) - (py-ay)*(bx-ax).
        # Moving one pixel right adds dy; moving one pixel down subtracts dx.
        edge_dx = [Signal(signed(13)) for _ in range(3)]
        edge_dy = [Signal(signed(13)) for _ in range(3)]
        edge = [Signal(signed(26)) for _ in range(3)]
        row_edge = [Signal(signed(26)) for _ in range(3)]

        raw_min_x = Signal(signed(12))
        raw_max_x = Signal(signed(12))
        raw_min_y = Signal(signed(12))
        raw_max_y = Signal(signed(12))
        screen_max_x = Signal(signed(13))
        screen_max_y = Signal(signed(13))
        m.d.comb += [
            raw_min_x.eq(_min3(self.i.payload.x0,
                               self.i.payload.x1,
                               self.i.payload.x2)),
            raw_max_x.eq(_max3(self.i.payload.x0,
                               self.i.payload.x1,
                               self.i.payload.x2)),
            raw_min_y.eq(_min3(self.i.payload.y0,
                               self.i.payload.y1,
                               self.i.payload.y2)),
            raw_max_y.eq(_max3(self.i.payload.y0,
                               self.i.payload.y1,
                               self.i.payload.y2)),
            screen_max_x.eq(self.h_active - 1),
            screen_max_y.eq(self.v_active - 1),
        ]

        init_step = Signal(3)
        multiply_a = Signal(signed(13))
        multiply_b = Signal(signed(13))
        product = Signal(signed(26))
        first_product = Signal(signed(26))

        # Eight shared multiply cycles: two for signed area, then two for the
        # initial value of each edge at the clipped bounding-box origin.
        setup_a = Array([
            cmd.x2 - cmd.x0,
            cmd.y2 - cmd.y0,
            min_x - cmd.x0,
            min_y - cmd.y0,
            min_x - cmd.x1,
            min_y - cmd.y1,
            min_x - cmd.x2,
            min_y - cmd.y2,
        ])
        setup_b = Array([
            edge_dy[0], edge_dx[0],
            edge_dy[0], edge_dx[0],
            edge_dy[1], edge_dx[1],
            edge_dy[2], edge_dx[2],
        ])
        all_nonnegative = Signal()
        all_nonpositive = Signal()
        inside = Signal()
        m.d.comb += [
            all_nonnegative.eq((edge[0] >= 0) &
                               (edge[1] >= 0) &
                               (edge[2] >= 0)),
            all_nonpositive.eq((edge[0] <= 0) &
                               (edge[1] <= 0) &
                               (edge[2] <= 0)),
            inside.eq(all_nonnegative | all_nonpositive),
            self.o.payload.x.eq(x),
            self.o.payload.y.eq(y),
            self.o.payload.pixel.eq(cmd.pixel),
            self.o.payload.blend.eq(BlendMode.REPLACE),
            self.o.payload.offset.eq(OffsetMode.ABSOLUTE),
            self.o.payload.alternate.eq(self.alternate),
        ]

        def advance_pixel():
            with m.If(x == max_x):
                with m.If(y == max_y):
                    m.next = "IDLE"
                with m.Else():
                    m.d.sync += [
                        x.eq(min_x),
                        y.eq(y + 1),
                    ]
                    for n in range(3):
                        m.d.sync += [
                            row_edge[n].eq(row_edge[n] - edge_dx[n]),
                            edge[n].eq(row_edge[n] - edge_dx[n]),
                        ]
            with m.Else():
                m.d.sync += x.eq(x + 1)
                for n in range(3):
                    m.d.sync += edge[n].eq(edge[n] + edge_dy[n])

        with m.FSM() as fsm:
            with m.State("IDLE"):
                m.d.comb += self.i.ready.eq(1)
                with m.If(self.i.valid):
                    m.d.sync += [
                        cmd.eq(self.i.payload),
                        min_x.eq(Mux(raw_min_x < 0, 0, raw_min_x)),
                        max_x.eq(Mux(raw_max_x > screen_max_x,
                                     screen_max_x, raw_max_x)),
                        min_y.eq(Mux(raw_min_y < 0, 0, raw_min_y)),
                        max_y.eq(Mux(raw_max_y > screen_max_y,
                                     screen_max_y, raw_max_y)),
                        edge_dx[0].eq(self.i.payload.x1 - self.i.payload.x0),
                        edge_dy[0].eq(self.i.payload.y1 - self.i.payload.y0),
                        edge_dx[1].eq(self.i.payload.x2 - self.i.payload.x1),
                        edge_dy[1].eq(self.i.payload.y2 - self.i.payload.y1),
                        edge_dx[2].eq(self.i.payload.x0 - self.i.payload.x2),
                        edge_dy[2].eq(self.i.payload.y0 - self.i.payload.y2),
                    ]
                    m.next = "CHECK_BOUNDS"

            with m.State("CHECK_BOUNDS"):
                # Reject triangles wholly outside the display before scanning.
                with m.If((min_x > max_x) | (min_y > max_y) |
                          (max_x < 0) | (max_y < 0)):
                    m.next = "IDLE"
                with m.Else():
                    m.d.sync += [
                        init_step.eq(0),
                        x.eq(min_x),
                        y.eq(min_y),
                    ]
                    m.next = "LOAD_SETUP"

            # Register each selected operand before the DSP, and register the
            # DSP result before subtracting it from the paired product.  The
            # extra setup cycles are insignificant next to filling a triangle,
            # while the registers keep vertex/bounds muxing, multiplication,
            # subtraction, and FSM control out of one system-clock path.
            with m.State("LOAD_SETUP"):
                m.d.sync += [
                    multiply_a.eq(setup_a[init_step]),
                    multiply_b.eq(setup_b[init_step]),
                ]
                m.next = "SETUP_MULTIPLY"

            with m.State("SETUP_MULTIPLY"):
                m.d.sync += product.eq(multiply_a * multiply_b)
                m.next = "STORE_SETUP"

            with m.State("STORE_SETUP"):
                with m.If(~init_step[0]):
                    m.d.sync += first_product.eq(product)
                    m.d.sync += init_step.eq(init_step + 1)
                    m.next = "LOAD_SETUP"
                with m.Else():
                    value = Signal(signed(26))
                    m.d.comb += value.eq(first_product - product)
                    with m.Switch(init_step):
                        with m.Case(1):
                            with m.If(value == 0):
                                m.next = "IDLE"
                            with m.Else():
                                m.d.sync += init_step.eq(2)
                                m.next = "LOAD_SETUP"
                        with m.Case(3):
                            m.d.sync += [edge[0].eq(value), row_edge[0].eq(value)]
                            m.d.sync += init_step.eq(4)
                            m.next = "LOAD_SETUP"
                        with m.Case(5):
                            m.d.sync += [edge[1].eq(value), row_edge[1].eq(value)]
                            m.d.sync += init_step.eq(6)
                            m.next = "LOAD_SETUP"
                        with m.Default():
                            m.d.sync += [edge[2].eq(value), row_edge[2].eq(value)]
                            m.next = "SCAN"

            with m.State("SCAN"):
                with m.If(inside):
                    m.d.comb += self.o.valid.eq(1)
                    with m.If(self.o.ready):
                        advance_pixel()
                with m.Else():
                    advance_pixel()

        m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))
        return m
