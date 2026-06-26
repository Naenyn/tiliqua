# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.build import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out

from . import PSQ, PSQ_BASE_FBITS
from .line import LineCmd, LineStripCmd

# Split column steps with |ΔY| >= this into a vertical edge then a horizontal run.
VERTICAL_DY_THRESH = 2


class VectorTrace(wiring.Component):

    """
    DSO-style vector trace frontend.

    Emits line segments when the trace advances to a new X column or makes a
    large vertical step at the same X.  Large column steps are drawn as a
    vertical edge followed by a horizontal run so sawtooth resets stay upright.
    The pen lifts on sweep wrap (X moving backwards).
    """

    def __init__(self, *, default_hue=10, default_x=0, default_y=0):

        self.hue       = Signal(4, init=default_hue)
        self.intensity = Signal(4, init=8)
        self.scale_x   = Signal(4, init=6)
        self.scale_y   = Signal(4, init=6)
        self.scale_p   = Signal(4, init=0xf)
        self.x_offset  = Signal(signed(16), init=default_x)
        self.y_offset  = Signal(signed(16), init=default_y)
        self.visible   = Signal(init=1)

        super().__init__({
            "i": In(stream.Signature(data.ArrayLayout(PSQ, 4))),
            "line_o": Out(stream.Signature(LineCmd)),
            "sweep_wrap": Out(1),
            "wrap_x": Out(signed(16)),
        })

    def elaborate(self, platform) -> Module:
        m = Module()

        in_x = Signal(signed(16))
        in_y = Signal(signed(16))
        in_p = Signal(signed(16))

        m.d.comb += [
            in_x.eq((self.i.payload[0].reshape(PSQ_BASE_FBITS).as_value() >> self.scale_x) + self.x_offset),
            in_y.eq((-self.i.payload[1].reshape(PSQ_BASE_FBITS).as_value() >> self.scale_y) + self.y_offset),
            in_p.eq(Mux(self.scale_p != 0xf, self.i.payload[2].reshape(PSQ_BASE_FBITS).as_value() >> self.scale_p, 0)),
        ]

        prev_x = Signal(signed(16))
        prev_y = Signal(signed(16))
        has_prev = Signal()

        trace_color = Signal(unsigned(4))
        trace_intensity = Signal(unsigned(4))
        line_cmd = Signal(LineStripCmd)

        pending = Signal()
        queued = Signal()
        latched_x = Signal(signed(12))
        latched_y = Signal(signed(11))
        latched_x0 = Signal(signed(12))
        latched_y0 = Signal(signed(11))
        latched_intensity = Signal(unsigned(4))

        q_x0 = Signal(signed(12))
        q_y0 = Signal(signed(11))
        q_x = Signal(signed(12))
        q_y = Signal(signed(11))
        step_x = Signal(signed(16))
        step_y = Signal(signed(16))
        deferred_step = Signal()

        m.d.comb += trace_color.eq(self.hue)

        with m.If((in_p + self.intensity > 0) & (in_p + self.intensity <= 0xf)):
            m.d.comb += trace_intensity.eq(in_p + self.intensity)
        with m.Else():
            m.d.comb += trace_intensity.eq(0)

        pen_lift = Signal()
        column_adv = Signal()
        same_column = Signal()
        dy = Signal(signed(17))
        dy_abs = Signal(unsigned(16))
        vertical_jump = Signal()
        steep_step = Signal()
        emit_segment = Signal()

        m.d.comb += [
            pen_lift.eq(self.i.valid & has_prev & (in_x < prev_x)),
            column_adv.eq(self.i.valid & has_prev & (in_x > prev_x)),
            same_column.eq(self.i.valid & has_prev & (in_x == prev_x)),
            dy.eq(in_y - prev_y),
            dy_abs.eq(Mux(dy < 0, -dy, dy)),
            vertical_jump.eq(same_column & (dy_abs >= VERTICAL_DY_THRESH)),
            steep_step.eq(column_adv & (dy_abs >= VERTICAL_DY_THRESH)),
            emit_segment.eq(self.visible & (column_adv | vertical_jump) & (trace_intensity > 0)),
            self.sweep_wrap.eq(pen_lift),
            self.wrap_x.eq(in_x),
        ]

        m.d.comb += line_cmd.eq(LineStripCmd.END)
        m.d.comb += [
            self.line_o.payload.x.eq(latched_x),
            self.line_o.payload.y.eq(latched_y),
            self.line_o.payload.x0.eq(latched_x0),
            self.line_o.payload.y0.eq(latched_y0),
            self.line_o.payload.use_seg.eq(1),
            self.line_o.payload.pixel.color.eq(trace_color),
            self.line_o.payload.pixel.intensity.eq(latched_intensity),
            self.line_o.payload.cmd.eq(line_cmd),
            self.line_o.valid.eq(pending),
        ]

        with m.If(emit_segment & ~pending & ~queued):
            m.d.sync += pending.eq(1)
            with m.If(steep_step):
                m.d.sync += [
                    latched_x0.eq(prev_x),
                    latched_y0.eq(prev_y),
                    latched_x.eq(prev_x),
                    latched_y.eq(in_y),
                    latched_intensity.eq(trace_intensity),
                    q_x0.eq(prev_x),
                    q_y0.eq(in_y),
                    q_x.eq(in_x),
                    q_y.eq(in_y),
                    queued.eq(1),
                ]
            with m.Else():
                m.d.sync += [
                    latched_x0.eq(prev_x),
                    latched_y0.eq(prev_y),
                    latched_x.eq(in_x),
                    latched_y.eq(in_y),
                    latched_intensity.eq(trace_intensity),
                ]

        with m.If(pending & self.line_o.ready):
            with m.If(queued):
                m.d.sync += [
                    latched_x0.eq(q_x0),
                    latched_y0.eq(q_y0),
                    latched_x.eq(q_x),
                    latched_y.eq(q_y),
                    queued.eq(0),
                ]
            with m.Else():
                m.d.sync += pending.eq(0)
                with m.If(deferred_step):
                    m.d.sync += [
                        deferred_step.eq(0),
                        prev_x.eq(step_x),
                        prev_y.eq(step_y),
                    ]

        with m.If(self.i.valid):
            with m.If(pen_lift):
                m.d.sync += [
                    has_prev.eq(0),
                    pending.eq(0),
                    queued.eq(0),
                    deferred_step.eq(0),
                ]
            with m.Elif(column_adv | vertical_jump):
                with m.If(steep_step):
                    m.d.sync += [
                        deferred_step.eq(1),
                        step_x.eq(in_x),
                        step_y.eq(in_y),
                    ]
                with m.Else():
                    m.d.sync += [
                        prev_x.eq(in_x),
                        prev_y.eq(in_y),
                    ]
            with m.Elif(~has_prev):
                m.d.sync += [
                    prev_x.eq(in_x),
                    prev_y.eq(in_y),
                    has_prev.eq(1),
                ]
            with m.Elif(same_column):
                m.d.sync += prev_y.eq(in_y)

        return m
