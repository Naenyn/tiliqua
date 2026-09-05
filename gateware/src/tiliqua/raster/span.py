# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Flat-shaded triangle rasterization into packed framebuffer spans.

This path is intentionally narrower than :mod:`tiliqua.raster.plot`.  It is
for opaque, flat-shaded geometry such as WATERFALL's terrain: vertices are
rotated once, triangles become horizontal spans, and four identical 8-bit
pixels are written per 32-bit PSRAM word.  It deliberately omits blending,
textures, depth and arbitrary per-pixel coordinate transforms.
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

        span_seen = Signal()
        span_x0 = Signal(unsigned(12))
        span_x1 = Signal(unsigned(12))
        m.d.comb += [
            self.o.payload.x0.eq(span_x0),
            self.o.payload.x1.eq(span_x1),
            self.o.payload.y.eq(y),
            self.o.payload.pixel.eq(cmd.pixel),
            self.o.payload.alternate.eq(self.alternate),
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
                    m.d.sync += cmd.eq(transformed)
                    m.next = "LOAD_BOUNDS"

            with m.State("LOAD_BOUNDS"):
                m.d.sync += [
                    # Align the scan origin to the packed word boundary. Any
                    # leading lanes outside the actual triangle are rejected
                    # by the parallel edge tests above.
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
                        m.d.sync += [span_seen.eq(1), span_x0.eq(x)]
                    m.d.sync += span_x1.eq(x + 3)

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

    Spans use conservative four-pixel word coverage. WATERFALL renders a
    continuous opaque surface into a freshly cleared backbuffer, so allowing
    neighboring facets to overlap by at most three horizontal pixels is both
    harmless and preferable to leaving partial-byte cracks between them.
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
        last_word = Signal(unsigned(10))
        pixel = Signal(Pixel)
        burst_count = Signal(range(self.burst_words))

        final_word = Signal()
        end_burst = Signal()
        m.d.comb += [
            final_word.eq(word_index == last_word),
            end_burst.eq(final_word |
                         (burst_count == self.burst_words - 1) |
                         self.pause),
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
                        last_word.eq(last),
                        pixel.eq(self.i.payload.pixel),
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
                    bus.sel.eq(0b1111),
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
