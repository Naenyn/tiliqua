# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Completed-sweep buffering for the digital oscilloscope."""

from amaranth import *
from amaranth.lib import memory, wiring
from amaranth.lib.wiring import In, Out

from .scope_capture import MAX_CAPTURE_COLS, ENVELOPE_SENTINEL


class CompletedSweepBuffer(wiring.Component):

    """Capture one complete column-envelope sweep before exposing it.

    Incoming column flushes are written into a compact back buffer.  They are
    invisible to the renderer until ``sweep_done``; the completed buffer is
    then streamed in column order.  Once the renderer has consumed the final
    column, the buffer is cleared to the no-data sentinel and capture resumes.

    Together with the renderer's existing ``shown_mem`` this forms front/back
    sweep buffering without allocating a second video framebuffer.
    """

    def __init__(self):
        super().__init__({
            "enable": In(1),
            "ncols": In(range(MAX_CAPTURE_COLS + 1)),
            "flush_valid": In(1),
            "flush_col": In(range(MAX_CAPTURE_COLS)),
            "flush_word": In(unsigned(128)),
            "sweep_done": In(1),
            "capture_active": Out(1),
            "capture_clear": Out(1),
            "col_valid": Out(1),
            "col_ready": In(1),
            "col": Out(range(MAX_CAPTURE_COLS)),
            "word": Out(unsigned(128)),
            "rendering": Out(1),
            "render_done": Out(1),
        })

    def elaborate(self, platform):
        m = Module()

        sweep_mem = memory.Memory(
            data=memory.MemoryData(
                shape=unsigned(128),
                depth=MAX_CAPTURE_COLS,
                init=[ENVELOPE_SENTINEL] * MAX_CAPTURE_COLS,
            )
        )
        m.submodules.sweep_mem = sweep_mem
        rd = sweep_mem.read_port()
        wr = sweep_mem.write_port()

        clear_col = Signal(range(MAX_CAPTURE_COLS))
        render_col = Signal(range(MAX_CAPTURE_COLS))
        render_ncols = Signal(range(MAX_CAPTURE_COLS + 1))
        render_word = Signal(unsigned(128))

        with m.FSM(name="sweep_buffer"):
            with m.State("DISABLED"):
                with m.If(self.enable):
                    m.d.sync += clear_col.eq(0)
                    m.next = "CLEAR"

            with m.State("CLEAR"):
                m.d.comb += [
                    wr.en.eq(1),
                    wr.addr.eq(clear_col),
                    wr.data.eq(ENVELOPE_SENTINEL),
                ]
                with m.If(~self.enable):
                    m.next = "DISABLED"
                with m.Elif(clear_col == MAX_CAPTURE_COLS - 1):
                    m.next = "ARM"
                with m.Else():
                    m.d.sync += clear_col.eq(clear_col + 1)

            with m.State("ARM"):
                # Reset ColumnCapture immediately before accepting a new sweep.
                m.d.comb += self.capture_clear.eq(1)
                with m.If(~self.enable):
                    m.next = "DISABLED"
                with m.Else():
                    m.next = "CAPTURE"

            with m.State("CAPTURE"):
                m.d.comb += self.capture_active.eq(self.enable)
                with m.If(self.flush_valid):
                    m.d.comb += [
                        wr.en.eq(1),
                        wr.addr.eq(self.flush_col),
                        wr.data.eq(self.flush_word),
                    ]
                with m.If(~self.enable):
                    m.next = "DISABLED"
                with m.Elif(self.sweep_done):
                    m.d.sync += [
                        render_col.eq(0),
                        render_ncols.eq(self.ncols),
                    ]
                    m.next = "READ"

            with m.State("READ"):
                m.d.comb += self.rendering.eq(1)
                with m.If((render_ncols == 0) | ~self.enable):
                    m.next = "DRAIN"
                with m.Else():
                    m.d.comb += [
                        rd.en.eq(1),
                        rd.addr.eq(render_col),
                    ]
                    m.next = "READ_WAIT"

            with m.State("READ_WAIT"):
                m.d.comb += self.rendering.eq(1)
                m.d.sync += render_word.eq(rd.data)
                m.next = "SEND"

            with m.State("SEND"):
                m.d.comb += [
                    self.rendering.eq(1),
                    self.col_valid.eq(1),
                    self.col.eq(render_col),
                    self.word.eq(render_word),
                ]
                with m.If(self.col_ready):
                    with m.If(render_col + 1 >= render_ncols):
                        m.next = "DRAIN"
                    with m.Else():
                        m.d.sync += render_col.eq(render_col + 1)
                        m.next = "READ"

            with m.State("DRAIN"):
                # col_ready returns high only after the renderer has completed
                # the last accepted column and returned to its WAIT state.
                m.d.comb += self.rendering.eq(1)
                with m.If(self.col_ready):
                    m.d.comb += self.render_done.eq(1)
                    m.d.sync += clear_col.eq(0)
                    with m.If(self.enable):
                        m.next = "CLEAR"
                    with m.Else():
                        m.next = "DISABLED"

        return m
