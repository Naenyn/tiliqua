# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Flat-shaded triangle rasterization into packed framebuffer spans.

This path is intentionally narrower than :mod:`tiliqua.raster.plot`.  It is
for opaque, flat-shaded geometry such as CASCADO's terrain: vertices are
rotated once, triangles become horizontal spans, and packed 32-bit PSRAM
words are written with optional endpoint byte masks. It deliberately omits
blending, textures, depth and arbitrary per-pixel coordinate transforms.
"""

from amaranth import *
from amaranth.lib import data, fifo, stream, wiring
from amaranth.lib.wiring import In, Out
from amaranth_soc import wishbone

from ..video.framebuffer import DMAFramebuffer
from ..video.types import Pixel, Rotation
from .triangle import TriangleCmd, _max3, _min3


class SpanCmd(data.Struct):
    """One inclusive, horizontal run of opaque pixels."""

    x0: unsigned(12)
    x1: unsigned(12)
    y: unsigned(12)
    pixel: Pixel
    alternate: unsigned(1)
    # Coarse triangle fills cover complete packed words. Detailed fills and
    # contours use endpoint byte masks.
    exact: unsigned(1)


class TriangleSpanRasterizer(wiring.Component):
    """Convert flat-shaded triangles into at most one span per scanline.

    Rotation is applied to the vertices before rasterization.  Consequently
    every emitted span is contiguous in physical framebuffer memory even for
    portrait display rotations.
    """

    i: In(stream.Signature(TriangleCmd))
    o: Out(stream.Signature(SpanCmd))
    h_active: In(unsigned(12))
    v_active: In(unsigned(12))
    rotation: In(Rotation)
    alternate: In(1)
    ridge: In(1)
    busy: Out(1)

    def elaborate(self, platform):
        m = Module()

        transformed = Signal(TriangleCmd)
        input_x = [self.i.payload.x0, self.i.payload.x1, self.i.payload.x2]
        input_y = [self.i.payload.y0, self.i.payload.y1, self.i.payload.y2]
        output_x = [transformed.x0, transformed.x1, transformed.x2]
        output_y = [transformed.y0, transformed.y1, transformed.y2]
        for xin, yin, xout, yout in zip(input_x, input_y, output_x, output_y):
            with m.Switch(self.rotation):
                with m.Case(Rotation.NORMAL):
                    m.d.comb += [xout.eq(xin), yout.eq(yin)]
                with m.Case(Rotation.LEFT):
                    m.d.comb += [
                        xout.eq(self.h_active - 1 - yin),
                        yout.eq(xin),
                    ]
                with m.Case(Rotation.INVERTED):
                    m.d.comb += [
                        xout.eq(self.h_active - 1 - xin),
                        yout.eq(self.v_active - 1 - yin),
                    ]
                with m.Case(Rotation.RIGHT):
                    m.d.comb += [
                        xout.eq(yin),
                        yout.eq(self.v_active - 1 - xin),
                    ]
        m.d.comb += transformed.pixel.eq(self.i.payload.pixel)

        cmd = Signal(TriangleCmd)
        cmd_ridge = Signal()
        fill_detail = Signal(2)
        min_x = Signal(signed(12))
        max_x = Signal(signed(12))
        min_y = Signal(signed(12))
        max_y = Signal(signed(12))
        x = Signal(signed(12))
        y = Signal(signed(12))

        raw_min_x = Signal(signed(12))
        raw_max_x = Signal(signed(12))
        raw_min_y = Signal(signed(12))
        raw_max_y = Signal(signed(12))
        screen_max_x = Signal(signed(13))
        screen_max_y = Signal(signed(13))
        m.d.comb += [
            # ``cmd`` is registered after rotation. Keeping bounds selection
            # on its far side prevents rotation, min/max and screen clipping
            # from becoming one system-clock path.
            raw_min_x.eq(_min3(cmd.x0, cmd.x1, cmd.x2)),
            raw_max_x.eq(_max3(cmd.x0, cmd.x1, cmd.x2)),
            raw_min_y.eq(_min3(cmd.y0, cmd.y1, cmd.y2)),
            raw_max_y.eq(_max3(cmd.y0, cmd.y1, cmd.y2)),
            screen_max_x.eq(self.h_active - 1),
            screen_max_y.eq(self.v_active - 1),
        ]

        # Edge E(a,b,p) = (px-ax)*(by-ay) - (py-ay)*(bx-ax).
        # The scan stage advances all three equations with additions only.
        edge_dx = [Signal(signed(13)) for _ in range(3)]
        edge_dy = [Signal(signed(13)) for _ in range(3)]
        edge = [Signal(signed(26)) for _ in range(3)]
        row_edge = [Signal(signed(26)) for _ in range(3)]

        init_step = Signal(3)
        multiply_a = Signal(signed(13))
        multiply_b = Signal(signed(13))
        product = Signal(signed(26))
        first_product = Signal(signed(26))
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
        # The writer stores four identical 8-bit pixels per PSRAM word. Test
        # the four integer pixel positions in parallel so the rasterizer can
        # advance one packed word per clock without changing which words the
        # previous pixel-at-a-time implementation ultimately wrote.
        lane_inside = [Signal(name=f"lane_{lane}_inside")
                       for lane in range(4)]
        lane_edges = [
            [Signal(signed(27), name=f"lane_{lane}_edge_{n}")
             for n in range(3)]
            for lane in range(4)
        ]
        word_inside = Signal()
        for lane in range(4):
            for n in range(3):
                # Spell constant lane offsets as shift/add expressions. A
                # generic ``* lane`` made synthesis consume the device's last
                # three DSP blocks and put one multiplier directly on the
                # system-clock critical path.
                if lane == 0:
                    lane_offset = Const(0, signed(27))
                elif lane == 1:
                    lane_offset = edge_dy[n]
                elif lane == 2:
                    lane_offset = edge_dy[n] << 1
                else:
                    lane_offset = edge_dy[n] + (edge_dy[n] << 1)
                m.d.comb += lane_edges[lane][n].eq(
                    edge[n] + lane_offset)
            all_nonnegative = (
                (lane_edges[lane][0] >= 0) &
                (lane_edges[lane][1] >= 0) &
                (lane_edges[lane][2] >= 0))
            all_nonpositive = (
                (lane_edges[lane][0] <= 0) &
                (lane_edges[lane][1] <= 0) &
                (lane_edges[lane][2] <= 0))
            m.d.comb += lane_inside[lane].eq(
                all_nonnegative | all_nonpositive)
        m.d.comb += word_inside.eq(
            lane_inside[0] | lane_inside[1] |
            lane_inside[2] | lane_inside[3])

        first_inside_lane = Signal(2)
        last_inside_lane = Signal(2)
        quantized_first_x = Signal(unsigned(12))
        quantized_last_x = Signal(unsigned(12))
        m.d.comb += [
            first_inside_lane.eq(Mux(
                lane_inside[0], 0,
                Mux(lane_inside[1], 1,
                    Mux(lane_inside[2], 2, 3)))),
            last_inside_lane.eq(Mux(
                lane_inside[3], 3,
                Mux(lane_inside[2], 2,
                    Mux(lane_inside[1], 1, 0)))),
            # Detail zero preserves conservative full-word coverage. Detail
            # one rounds only to two-pixel pairs; detail two retains the exact
            # covered byte lanes. ``x`` is always word-aligned, so composing
            # its low bits directly avoids putting two 12-bit adders here.
            # All modes still inspect four pixels at once.
            quantized_first_x.eq(Mux(
                fill_detail == 2,
                Cat(first_inside_lane, x[2:]),
                Mux(fill_detail == 1,
                    Cat(Const(0, 1), first_inside_lane[1], x[2:]),
                    x))),
            quantized_last_x.eq(Mux(
                fill_detail == 2,
                Cat(last_inside_lane, x[2:]),
                Mux(fill_detail == 1,
                    Cat(Const(1, 1), last_inside_lane[1], x[2:]),
                    Cat(Const(3, 2), x[2:])))),
        ]

        span_seen = Signal()
        span_x0 = Signal(unsigned(12))
        span_x1 = Signal(unsigned(12))
        m.d.comb += [
            self.o.payload.x0.eq(span_x0),
            self.o.payload.x1.eq(span_x1),
            self.o.payload.y.eq(y),
            self.o.payload.pixel.eq(cmd.pixel),
            self.o.payload.alternate.eq(self.alternate),
            self.o.payload.exact.eq(fill_detail != 0),
        ]

        # CASCADO changes fill granularity only a few times per surface. A
        # reserved zero-area command updates that state in-order, avoiding two
        # extra bits on every entry of the timing-sensitive asynchronous FIFO.
        encoded_command = Signal()
        detail_control_command = Signal()
        m.d.comb += [
            encoded_command.eq(
                (cmd.x0 == cmd.x1) & (cmd.y0 == cmd.y1)),
            detail_control_command.eq(
                encoded_command & (cmd.pixel.color == 0) &
                (cmd.pixel.intensity != 0)),
        ]

        # A contour command is encoded without widening CASCADO's
        # timing-sensitive asynchronous command FIFO: vertices 0 and 1 are
        # identical, vertex 2 is the other endpoint, and the pixel is black.
        # Genuine zero-area triangles were already discarded, so this
        # representation is unambiguous to the span renderer.
        contour_command = Signal()
        m.d.comb += contour_command.eq(
            encoded_command & (cmd.pixel.as_value() == 0))

        # Contours use a span-producing Bresenham walk. Consecutive pixels on
        # one physical scanline are coalesced into a single exact span, keeping
        # the full history boundary much cheaper than the old pixel-at-a-time
        # overlay while preserving true one-pixel edges.
        line_x = Signal(signed(12))
        line_y = Signal(signed(12))
        line_target_x = Signal(signed(12))
        line_target_y = Signal(signed(12))
        line_dx = Signal(signed(14))
        line_dy = Signal(signed(14))
        line_sx = Signal(signed(2))
        line_sy = Signal(signed(2))
        line_err = Signal(signed(15))
        line_e2 = Signal(signed(16))
        line_step_x = Signal()
        line_step_y = Signal()
        line_next_x = Signal(signed(12))
        line_next_y = Signal(signed(12))
        line_next_err = Signal(signed(15))
        line_at_target = Signal()
        line_visible = Signal()
        line_row_end = Signal()
        line_run_valid = Signal()
        line_run_x0 = Signal(unsigned(12))
        line_run_x1 = Signal(unsigned(12))
        line_candidate_x0 = Signal(unsigned(12))
        line_candidate_x1 = Signal(unsigned(12))
        line_emit_x0 = Signal(unsigned(12))
        line_emit_x1 = Signal(unsigned(12))
        line_emit_needed = Signal()
        m.d.comb += [
            line_e2.eq(line_err << 1),
            line_step_x.eq(line_e2 > -line_dy),
            line_step_y.eq(line_e2 < line_dx),
            line_next_x.eq(line_x + Mux(line_step_x, line_sx, 0)),
            line_next_y.eq(line_y + Mux(line_step_y, line_sy, 0)),
            line_next_err.eq(
                line_err - Mux(line_step_x, line_dy, 0)
                + Mux(line_step_y, line_dx, 0)),
            line_at_target.eq(
                (line_x == line_target_x) & (line_y == line_target_y)),
            line_visible.eq(
                (line_x >= 0) & (line_x <= screen_max_x) &
                (line_y >= 0) & (line_y <= screen_max_y)),
            line_row_end.eq(line_at_target | line_step_y),
            line_candidate_x0.eq(Mux(
                line_run_valid,
                Mux(line_x < line_run_x0, line_x, line_run_x0),
                line_x)),
            line_candidate_x1.eq(Mux(
                line_run_valid,
                Mux(line_x > line_run_x1, line_x, line_run_x1),
                line_x)),
            line_emit_x0.eq(Mux(
                line_visible, line_candidate_x0, line_run_x0)),
            line_emit_x1.eq(Mux(
                line_visible, line_candidate_x1, line_run_x1)),
            line_emit_needed.eq(
                line_row_end & (line_run_valid | line_visible)),
        ]

        def advance_line():
            with m.If(line_at_target):
                m.d.sync += line_run_valid.eq(0)
                m.next = "IDLE"
            with m.Else():
                m.d.sync += [
                    line_x.eq(line_next_x),
                    line_y.eq(line_next_y),
                    line_err.eq(line_next_err),
                ]
                with m.If(line_row_end):
                    m.d.sync += line_run_valid.eq(0)
                with m.Elif(line_visible):
                    m.d.sync += [
                        line_run_valid.eq(1),
                        line_run_x0.eq(line_candidate_x0),
                        line_run_x1.eq(line_candidate_x1),
                    ]

        def advance_row():
            with m.If(y == max_y):
                m.next = "IDLE"
            with m.Else():
                m.d.sync += [
                    x.eq(min_x),
                    y.eq(y + 1),
                    span_seen.eq(0),
                ]
                for n in range(3):
                    m.d.sync += [
                        row_edge[n].eq(row_edge[n] - edge_dx[n]),
                        edge[n].eq(row_edge[n] - edge_dx[n]),
                    ]
                m.next = "SCAN"

        with m.FSM() as fsm:
            with m.State("IDLE"):
                m.d.comb += self.i.ready.eq(1)
                with m.If(self.i.valid):
                    m.d.sync += [
                        cmd.eq(transformed),
                        cmd_ridge.eq(self.ridge),
                    ]
                    m.next = "LOAD_BOUNDS"

            with m.State("LOAD_BOUNDS"):
                with m.If(detail_control_command):
                    m.d.sync += fill_detail.eq(cmd.pixel.intensity - 1)
                    m.next = "IDLE"
                with m.Elif(contour_command):
                    with m.If(cmd_ridge):
                        m.d.sync += [
                            line_x.eq(cmd.x1),
                            line_y.eq(cmd.y1),
                            line_target_x.eq(cmd.x2),
                            line_target_y.eq(cmd.y2),
                            line_run_valid.eq(0),
                        ]
                        m.next = "LINE_SETUP"
                    with m.Else():
                        m.next = "IDLE"
                with m.Else():
                    m.d.sync += [
                        # Align the scan origin to the packed word boundary.
                        # Any leading lanes outside the actual triangle are
                        # rejected by the parallel edge tests above.
                        min_x.eq(Mux(
                            raw_min_x < 0,
                            0,
                            Cat(Const(0, 2), raw_min_x[2:]))),
                        max_x.eq(Mux(raw_max_x > screen_max_x,
                                     screen_max_x, raw_max_x)),
                        min_y.eq(Mux(raw_min_y < 0, 0, raw_min_y)),
                        max_y.eq(Mux(raw_max_y > screen_max_y,
                                     screen_max_y, raw_max_y)),
                        edge_dx[0].eq(cmd.x1 - cmd.x0),
                        edge_dy[0].eq(cmd.y1 - cmd.y0),
                        edge_dx[1].eq(cmd.x2 - cmd.x1),
                        edge_dy[1].eq(cmd.y2 - cmd.y1),
                        edge_dx[2].eq(cmd.x0 - cmd.x2),
                        edge_dy[2].eq(cmd.y0 - cmd.y2),
                    ]
                    m.next = "CHECK_BOUNDS"

            with m.State("LINE_SETUP"):
                m.d.sync += [
                    line_dx.eq(Mux(
                        line_target_x >= line_x,
                        line_target_x - line_x,
                        line_x - line_target_x)),
                    line_dy.eq(Mux(
                        line_target_y >= line_y,
                        line_target_y - line_y,
                        line_y - line_target_y)),
                    line_sx.eq(Mux(line_target_x >= line_x, 1, -1)),
                    line_sy.eq(Mux(line_target_y >= line_y, 1, -1)),
                ]
                m.next = "LINE_START"

            with m.State("LINE_START"):
                m.d.sync += line_err.eq(line_dx - line_dy)
                m.next = "LINE_STEP"

            with m.State("LINE_STEP"):
                with m.If(line_emit_needed):
                    m.d.comb += [
                        self.o.valid.eq(1),
                        self.o.payload.x0.eq(line_emit_x0),
                        self.o.payload.x1.eq(line_emit_x1),
                        self.o.payload.y.eq(line_y),
                        self.o.payload.pixel.color.eq(0),
                        self.o.payload.pixel.intensity.eq(0),
                        self.o.payload.exact.eq(1),
                    ]
                    with m.If(self.o.ready):
                        advance_line()
                with m.Else():
                    advance_line()

            with m.State("CHECK_BOUNDS"):
                with m.If((min_x > max_x) | (min_y > max_y) |
                          (max_x < 0) | (max_y < 0)):
                    m.next = "IDLE"
                with m.Else():
                    m.d.sync += [
                        init_step.eq(0),
                        x.eq(min_x),
                        y.eq(min_y),
                        span_seen.eq(0),
                    ]
                    m.next = "LOAD_SETUP"

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
                    m.d.sync += [
                        first_product.eq(product),
                        init_step.eq(init_step + 1),
                    ]
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
                            m.d.sync += [edge[0].eq(value), row_edge[0].eq(value),
                                         init_step.eq(4)]
                            m.next = "LOAD_SETUP"
                        with m.Case(5):
                            m.d.sync += [edge[1].eq(value), row_edge[1].eq(value),
                                         init_step.eq(6)]
                            m.next = "LOAD_SETUP"
                        with m.Default():
                            m.d.sync += [edge[2].eq(value), row_edge[2].eq(value)]
                            m.next = "SCAN"

            with m.State("SCAN"):
                with m.If(word_inside):
                    with m.If(~span_seen):
                        m.d.sync += [
                            span_seen.eq(1),
                            span_x0.eq(quantized_first_x),
                        ]
                    m.d.sync += span_x1.eq(quantized_last_x)

                # A triangle intersects each scanline in one contiguous run.
                # Once a populated word is followed by an empty one, no later
                # word on this row can contribute and the span is complete.
                with m.If(span_seen & ~word_inside):
                    m.next = "EMIT"
                with m.Elif(x[2:] == max_x[2:]):
                    # The final inside decision is registered above.  EMIT sees
                    # the resulting inclusive endpoints on the following clock.
                    m.next = "EMIT"
                with m.Else():
                    m.d.sync += x.eq(x + 4)
                    for n in range(3):
                        m.d.sync += edge[n].eq(
                            edge[n] + (edge_dy[n] << 2))

            with m.State("EMIT"):
                with m.If(span_seen):
                    m.d.comb += self.o.valid.eq(1)
                    with m.If(self.o.ready):
                        advance_row()
                with m.Else():
                    advance_row()

        m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))
        return m


class PackedSpanWriter(wiring.Component):
    """Write opaque spans directly to PSRAM in bounded incrementing bursts.

    Coarse terrain spans use conservative four-pixel word coverage. Detailed
    terrain and contour spans retain byte masks at their endpoints.
    """

    def __init__(self, *, bus_signature, burst_words=16):
        if burst_words < 1:
            raise ValueError("burst_words must be positive")
        self.burst_words = burst_words
        super().__init__({
            "i": In(stream.Signature(SpanCmd)),
            "pause": In(1),
            "bus": Out(bus_signature),
            "fbp": In(DMAFramebuffer.Properties()),
            "busy": Out(1),
        })

    def elaborate(self, platform):
        m = Module()
        bus = self.bus
        pixels_per_word = bus.data_width // Pixel.as_shape().size
        assert pixels_per_word == 4

        address = Signal(bus.addr_width)
        word_index = Signal(unsigned(10))
        first_word = Signal(unsigned(10))
        last_word = Signal(unsigned(10))
        pixel = Signal(Pixel)
        exact = Signal()
        first_select = Signal(4)
        last_select = Signal(4)
        burst_count = Signal(range(self.burst_words))

        final_word = Signal()
        end_burst = Signal()
        word_select = Signal(4)
        m.d.comb += [
            final_word.eq(word_index == last_word),
            end_burst.eq(final_word |
                         (burst_count == self.burst_words - 1) |
                         self.pause),
            word_select.eq(Mux(
                ~exact,
                0b1111,
                Mux(
                    word_index == first_word,
                    Mux(final_word,
                        first_select & last_select,
                        first_select),
                    Mux(final_word, last_select, 0b1111)))),
        ]

        fb_words_per_line = Signal(unsigned(12))
        m.d.comb += fb_words_per_line.eq(self.fbp.timings.h_active >> 2)

        with m.FSM() as fsm:
            with m.State("IDLE"):
                m.d.comb += self.i.ready.eq(~self.pause)
                with m.If(self.i.valid & ~self.pause):
                    first = self.i.payload.x0 >> 2
                    last = self.i.payload.x1 >> 2
                    m.d.sync += [
                        address.eq(
                            (self.fbp.base ^
                             Mux(self.i.payload.alternate, 0x40000, 0)) +
                            self.i.payload.y * fb_words_per_line + first),
                        word_index.eq(first),
                        first_word.eq(first),
                        last_word.eq(last),
                        pixel.eq(self.i.payload.pixel),
                        exact.eq(self.i.payload.exact),
                        first_select.eq(Array(
                            Const(mask, 4)
                            for mask in (0b1111, 0b1110, 0b1100, 0b1000)
                        )[self.i.payload.x0[:2]]),
                        last_select.eq(Array(
                            Const(mask, 4)
                            for mask in (0b0001, 0b0011, 0b0111, 0b1111)
                        )[self.i.payload.x1[:2]]),
                        burst_count.eq(0),
                    ]
                    m.next = "BURST"

            with m.State("BURST"):
                m.d.comb += [
                    bus.stb.eq(1),
                    bus.cyc.eq(1),
                    bus.we.eq(1),
                    bus.adr.eq(address),
                    bus.dat_w.eq(Cat([pixel] * pixels_per_word)),
                    bus.sel.eq(word_select),
                    bus.cti.eq(Mux(
                        end_burst,
                        wishbone.CycleType.END_OF_BURST,
                        wishbone.CycleType.INCR_BURST)),
                ]
                with m.If(bus.ack):
                    with m.If(final_word):
                        m.next = "IDLE"
                    with m.Else():
                        m.d.sync += [
                            address.eq(address + 1),
                            word_index.eq(word_index + 1),
                        ]
                        with m.If(end_burst):
                            m.d.sync += burst_count.eq(0)
                            m.next = "RELEASE"
                        with m.Else():
                            m.d.sync += burst_count.eq(burst_count + 1)

            with m.State("RELEASE"):
                # Drop CYC for a clock so scanout can win the shared arbiter.
                with m.If(~self.pause):
                    m.next = "BURST"

        m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))
        return m


class TriangleSpanRenderer(wiring.Component):
    """Pipelined triangle-to-span-to-PSRAM renderer."""

    def __init__(self, *, bus_signature, span_fifo_depth=64,
                 burst_words=16):
        self.bus_signature = bus_signature
        self.span_fifo_depth = span_fifo_depth
        self.burst_words = burst_words
        super().__init__({
            "i": In(stream.Signature(TriangleCmd)),
            "pause": In(1),
            "alternate": In(1),
            # CASCADO encodes complete contour segments as otherwise-invalid
            # zero-area triangle commands, avoiding a wider cross-domain FIFO.
            "ridges": In(1),
            "bus": Out(bus_signature),
            "fbp": In(DMAFramebuffer.Properties()),
            "busy": Out(1),
        })

    def elaborate(self, platform):
        m = Module()
        m.submodules.rasterizer = rasterizer = TriangleSpanRasterizer()
        m.submodules.span_fifo = span_fifo = fifo.SyncFIFOBuffered(
            width=SpanCmd.as_shape().size,
            depth=self.span_fifo_depth,
        )
        m.submodules.writer = writer = PackedSpanWriter(
            bus_signature=self.bus_signature,
            burst_words=self.burst_words,
        )

        wiring.connect(m, wiring.flipped(self.i), rasterizer.i)
        wiring.connect(m, wiring.flipped(self.fbp), writer.fbp)
        wiring.connect(m, writer.bus, wiring.flipped(self.bus))
        m.d.comb += [
            rasterizer.h_active.eq(self.fbp.timings.h_active),
            rasterizer.v_active.eq(self.fbp.timings.v_active),
            rasterizer.rotation.eq(self.fbp.rotation),
            rasterizer.alternate.eq(self.alternate),
            rasterizer.ridge.eq(self.ridges),
            span_fifo.w_en.eq(rasterizer.o.valid & span_fifo.w_rdy),
            span_fifo.w_data.eq(rasterizer.o.payload.as_value()),
            rasterizer.o.ready.eq(span_fifo.w_rdy),
            writer.i.valid.eq(span_fifo.r_rdy),
            writer.i.payload.as_value().eq(span_fifo.r_data),
            span_fifo.r_en.eq(span_fifo.r_rdy & writer.i.ready),
            writer.pause.eq(self.pause),
            self.busy.eq(rasterizer.busy | writer.busy |
                         (span_fifo.level != 0)),
        ]
        return m
