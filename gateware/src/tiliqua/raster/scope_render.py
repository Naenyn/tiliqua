# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import stream, wiring
from amaranth.lib.wiring import In, Out

from .line import LineCmd, LineStripCmd
from .scope_capture import (
    MAX_CAPTURE_COLS,
    ENVELOPE_CHANNEL_BITS,
    ENVELOPE_COORD_BITS,
    ENVELOPE_WORD_BITS,
    VERTICAL_DY_THRESH,
)


class ColumnRenderer(wiring.Component):

    """
    Progressive (live) per-column renderer, with incremental erase.

    Columns arrive one at a time on the ``col_*`` input as the capture sweep
    advances; the renderer draws each immediately rather than waiting for a
    whole sweep.  For each column it keeps a "shown" copy of the envelope
    currently on screen (``shown_mem``).  When a column is (re)drawn it erases
    only the previously-drawn per-channel span (a short black segment) and draws
    the new one, then updates the shown copy.  If every channel's target
    envelope already matches what is shown the column is skipped entirely; if
    only some channels changed, unchanged channels skip both erase and draw.

    Per-channel strokes go through that channel's line plotter port.  Erase and
    draw for a given channel are pushed (in that order) into the same port FIFO,
    so the FIFO guarantees the erase is processed before the draw.
    """

    def __init__(self, *, n_channels=4):
        assert n_channels == 4
        self.n_channels = n_channels
        super().__init__({
            "plot_x_lo": In(signed(16)),
            "hue": In(unsigned(4)).array(n_channels),
            "intensity": In(unsigned(4)).array(n_channels),
            "visible": In(1).array(n_channels),
            # Incoming finished-column stream from the capture (via a FIFO).
            "col_valid": In(1),
            "col_ready": Out(1),
            "col": In(range(MAX_CAPTURE_COLS)),
            "word": In(unsigned(ENVELOPE_WORD_BITS)),
            # Shown-envelope RAM (read + write).
            "s_en": Out(1),
            "s_addr": Out(range(MAX_CAPTURE_COLS)),
            "s_data": In(unsigned(ENVELOPE_WORD_BITS)),
            "sw_en": Out(1),
            "sw_addr": Out(range(MAX_CAPTURE_COLS)),
            "sw_data": Out(unsigned(ENVELOPE_WORD_BITS)),
            "line_o": Out(stream.Signature(LineCmd)).array(n_channels),
            "busy": Out(1),
            "dbg_state": Out(unsigned(3)),
            "dbg_col": Out(range(MAX_CAPTURE_COLS)),
            "dbg_draw_ch": Out(unsigned(2)),
            "dbg_pending": Out(1),
        })

    def elaborate(self, platform):
        m = Module()

        render_col = Signal(range(MAX_CAPTURE_COLS))
        new_word = Signal(unsigned(ENVELOPE_WORD_BITS))
        shown_word = Signal(unsigned(ENVELOPE_WORD_BITS))
        prev_shown_word = Signal(unsigned(ENVELOPE_WORD_BITS))
        have_prev_shown = Signal()

        new_valid = Array(Signal() for _ in range(self.n_channels))
        shown_valid = Array(Signal() for _ in range(self.n_channels))
        prev_valid = Array(Signal() for _ in range(self.n_channels))
        new_ymin = Array(Signal(signed(16)) for _ in range(self.n_channels))
        new_ymax = Array(Signal(signed(16)) for _ in range(self.n_channels))
        shown_ymin = Array(Signal(signed(16)) for _ in range(self.n_channels))
        shown_ymax = Array(Signal(signed(16)) for _ in range(self.n_channels))
        prev_ymin = Array(Signal(signed(16)) for _ in range(self.n_channels))
        prev_ymax = Array(Signal(signed(16)) for _ in range(self.n_channels))
        horiz_corner = Array(Signal() for _ in range(self.n_channels))
        horiz_y = Array(Signal(signed(11)) for _ in range(self.n_channels))
        for ch in range(self.n_channels):
            lo = ENVELOPE_CHANNEL_BITS * ch
            m.d.comb += [
                new_valid[ch].eq(new_word[lo]),
                shown_valid[ch].eq(shown_word[lo]),
                prev_valid[ch].eq(prev_shown_word[lo]),
                new_ymin[ch].eq(new_word[
                    lo + 1:lo + 1 + ENVELOPE_COORD_BITS].as_signed()),
                new_ymax[ch].eq(new_word[
                    lo + 1 + ENVELOPE_COORD_BITS:
                    lo + 1 + 2 * ENVELOPE_COORD_BITS].as_signed()),
                shown_ymin[ch].eq(shown_word[
                    lo + 1:lo + 1 + ENVELOPE_COORD_BITS].as_signed()),
                shown_ymax[ch].eq(shown_word[
                    lo + 1 + ENVELOPE_COORD_BITS:
                    lo + 1 + 2 * ENVELOPE_COORD_BITS].as_signed()),
                prev_ymin[ch].eq(prev_shown_word[
                    lo + 1:lo + 1 + ENVELOPE_COORD_BITS].as_signed()),
                prev_ymax[ch].eq(prev_shown_word[
                    lo + 1 + ENVELOPE_COORD_BITS:
                    lo + 1 + 2 * ENVELOPE_COORD_BITS].as_signed()),
            ]
            prev_span = Signal(signed(17), name=f"prev_span{ch}")
            flat_new = Signal(name=f"flat_new{ch}")
            m.d.comb += [
                prev_span.eq(prev_ymax[ch] - prev_ymin[ch]),
                flat_new.eq(new_ymin[ch] == new_ymax[ch]),
                horiz_corner[ch].eq(
                    have_prev_shown &
                    prev_valid[ch] &
                    self.visible[ch] &
                    new_valid[ch] &
                    (self.intensity[ch] > 0) &
                    flat_new &
                    (prev_span >= VERTICAL_DY_THRESH) &
                    ((new_ymin[ch] == prev_ymax[ch]) |
                     (new_ymin[ch] == prev_ymin[ch]))
                ),
                horiz_y[ch].eq(new_ymin[ch]),
            ]

        draw_ch = Signal(range(self.n_channels + 1))
        latched_x = Signal(signed(12))
        pending = Signal()
        erase_phase = Signal()
        horiz_phase = Signal()
        horiz_done = Array(Signal() for _ in range(self.n_channels))
        render_state = Signal(3)

        # Per-channel selection of the current stroke parameters.
        cur_vis = Signal()
        cur_inten = Signal(unsigned(4))
        cur_hue = Signal(unsigned(4))
        cur_new_lo = Signal(signed(16))
        cur_new_hi = Signal(signed(16))
        cur_shown_lo = Signal(signed(16))
        cur_shown_hi = Signal(signed(16))
        line_ready = Signal()
        with m.Switch(draw_ch):
            for ch in range(self.n_channels):
                with m.Case(ch):
                    m.d.comb += [
                        cur_vis.eq(self.visible[ch]),
                        cur_inten.eq(self.intensity[ch]),
                        cur_hue.eq(self.hue[ch]),
                        cur_new_lo.eq(new_ymin[ch]),
                        cur_new_hi.eq(new_ymax[ch]),
                        cur_shown_lo.eq(shown_ymin[ch]),
                        cur_shown_hi.eq(shown_ymax[ch]),
                        line_ready.eq(self.line_o[ch].ready),
                    ]

        # Validity tests.  A channel was drawn last frame iff its shown span is
        # has its valid bit set; it should be drawn this frame iff it is visible,
        # has intensity and a valid envelope.
        erase_valid = Signal()
        draw_valid = Signal()
        m.d.comb += [
            erase_valid.eq(shown_valid[draw_ch]),
            draw_valid.eq(cur_vis & (cur_inten > 0) & new_valid[draw_ch]),
        ]

        # The draw clamps a flat envelope (ymax==ymin) up to a 1px-tall segment.
        # The erase MUST use the identical clamp on the previously-shown span,
        # otherwise the top pixel of every flat column is left behind.
        new_hi_clamped = Signal(signed(16))
        shown_hi_clamped = Signal(signed(16))
        m.d.comb += [
            new_hi_clamped.eq(
                Mux(cur_new_hi > cur_new_lo, cur_new_hi, cur_new_lo + 1)
            ),
            shown_hi_clamped.eq(
                Mux(cur_shown_hi > cur_shown_lo, cur_shown_hi, cur_shown_lo + 1)
            ),
        ]

        # Stroke payload: erase uses the shown span in black, draw uses the new
        # span in the channel colour.
        seg_y0 = Signal(signed(11))
        seg_y1 = Signal(signed(11))
        seg_x0 = Signal(signed(12))
        seg_x1 = Signal(signed(12))
        seg_color = Signal(unsigned(4))
        seg_inten = Signal(unsigned(4))
        m.d.comb += [
            seg_x0.eq(Mux(horiz_phase, latched_x - 1, latched_x)),
            seg_x1.eq(latched_x),
            seg_y0.eq(Mux(horiz_phase, horiz_y[draw_ch], Mux(erase_phase, cur_shown_lo, cur_new_lo))),
            seg_y1.eq(Mux(horiz_phase, horiz_y[draw_ch], Mux(erase_phase, shown_hi_clamped, new_hi_clamped))),
            seg_color.eq(Mux(erase_phase, 0, cur_hue)),
            seg_inten.eq(Mux(erase_phase, 0, cur_inten)),
        ]
        for ch in range(self.n_channels):
            m.d.comb += [
                self.line_o[ch].payload.x.eq(seg_x1),
                self.line_o[ch].payload.x0.eq(seg_x0),
                self.line_o[ch].payload.y0.eq(seg_y0),
                self.line_o[ch].payload.y.eq(seg_y1),
                self.line_o[ch].payload.use_seg.eq(1),
                self.line_o[ch].payload.pixel.color.eq(seg_color),
                self.line_o[ch].payload.pixel.intensity.eq(seg_inten),
                self.line_o[ch].payload.cmd.eq(LineStripCmd.END),
                self.line_o[ch].valid.eq(pending & (draw_ch == ch)),
            ]

        # Updated shown word: keep channels we drew, sentinel for the rest, so
        # next frame only erases what is really on screen.
        sentinel_chunk = Const(0, unsigned(ENVELOPE_CHANNEL_BITS))
        ch_target = []
        shown_chunks = []
        for ch in range(self.n_channels):
            lo = ENVELOPE_CHANNEL_BITS * ch
            drew = self.visible[ch] & (self.intensity[ch] > 0) & \
                new_valid[ch]
            target = Mux(
                drew,
                new_word[lo:lo + ENVELOPE_CHANNEL_BITS],
                sentinel_chunk,
            )
            ch_target.append(target)
            shown_chunks.append(target)
        m.d.comb += self.sw_data.eq(Cat(*shown_chunks))

        ch_unchanged = Signal()
        with m.Switch(draw_ch):
            for ch in range(self.n_channels):
                with m.Case(ch):
                    m.d.comb += ch_unchanged.eq(
                        shown_word[
                            ENVELOPE_CHANNEL_BITS * ch:
                            ENVELOPE_CHANNEL_BITS * (ch + 1)
                        ] == ch_target[ch]
                    )

        # Fast path: every channel already matches its target on screen.
        col_unchanged = Signal()
        m.d.comb += col_unchanged.eq(self.sw_data == shown_word)

        m.d.comb += [
            self.dbg_state.eq(render_state),
            self.dbg_col.eq(render_col),
            self.dbg_draw_ch.eq(draw_ch),
            self.dbg_pending.eq(pending | erase_phase),
        ]

        with m.FSM(name="render"):
            with m.State("WAIT"):
                m.d.comb += [self.col_ready.eq(1), render_state.eq(0)]
                with m.If(self.col_valid):
                    m.d.comb += self.s_en.eq(1)
                    m.d.sync += [
                        render_col.eq(self.col),
                        new_word.eq(self.word),
                        latched_x.eq(self.plot_x_lo + self.col),
                        draw_ch.eq(0),
                        erase_phase.eq(1),
                        horiz_phase.eq(0),
                        pending.eq(0),
                        have_prev_shown.eq(self.col > 0),
                    ]
                    for ch in range(self.n_channels):
                        m.d.sync += horiz_done[ch].eq(0)
                    with m.If(self.col > 0):
                        m.d.comb += self.s_addr.eq(self.col - 1)
                        m.next = "PREV_READ_WAIT"
                    with m.Else():
                        m.d.comb += self.s_addr.eq(self.col)
                        m.next = "READ_WAIT"

            with m.State("PREV_READ_WAIT"):
                m.d.comb += [self.busy.eq(1), render_state.eq(1)]
                m.d.sync += prev_shown_word.eq(self.s_data)
                m.d.comb += [
                    self.s_en.eq(1),
                    self.s_addr.eq(render_col),
                ]
                m.next = "READ_WAIT"

            with m.State("READ_WAIT"):
                m.d.comb += [self.busy.eq(1), render_state.eq(1)]
                m.d.sync += shown_word.eq(self.s_data)
                m.next = "CHECK"

            with m.State("CHECK"):
                m.d.comb += [self.busy.eq(1), render_state.eq(2)]
                with m.If(col_unchanged):
                    m.next = "WAIT"
                with m.Else():
                    m.next = "ERASE"

            with m.State("ERASE"):
                m.d.comb += [self.busy.eq(1), render_state.eq(3)]
                with m.If(draw_ch == self.n_channels):
                    m.d.sync += [draw_ch.eq(0), erase_phase.eq(0)]
                    m.next = "DRAW"
                with m.Elif(ch_unchanged):
                    m.d.sync += draw_ch.eq(draw_ch + 1)
                with m.Elif(erase_valid):
                    m.d.sync += pending.eq(1)
                    m.next = "ERASE_EMIT"
                with m.Else():
                    m.d.sync += draw_ch.eq(draw_ch + 1)

            with m.State("ERASE_EMIT"):
                m.d.comb += [self.busy.eq(1), render_state.eq(3)]
                with m.If(pending & line_ready):
                    m.d.sync += [pending.eq(0), draw_ch.eq(draw_ch + 1)]
                    m.next = "ERASE"

            with m.State("DRAW"):
                m.d.comb += [self.busy.eq(1), render_state.eq(5)]
                with m.If(draw_ch == self.n_channels):
                    m.next = "WRITE_SHOWN"
                with m.Elif(ch_unchanged):
                    m.d.sync += draw_ch.eq(draw_ch + 1)
                with m.Elif(horiz_corner[draw_ch] & ~horiz_done[draw_ch]):
                    m.d.sync += [horiz_phase.eq(1), pending.eq(1)]
                    m.next = "HORIZ_EMIT"
                with m.Elif(draw_valid):
                    m.d.sync += pending.eq(1)
                    m.next = "DRAW_EMIT"
                with m.Else():
                    m.d.sync += draw_ch.eq(draw_ch + 1)

            with m.State("HORIZ_EMIT"):
                m.d.comb += [self.busy.eq(1), render_state.eq(6)]
                with m.If(pending & line_ready):
                    m.d.sync += [
                        pending.eq(0),
                        horiz_phase.eq(0),
                        horiz_done[draw_ch].eq(1),
                    ]
                    with m.If(draw_valid):
                        m.d.sync += pending.eq(1)
                        m.next = "DRAW_EMIT"
                    with m.Else():
                        m.d.sync += draw_ch.eq(draw_ch + 1)
                        m.next = "DRAW"

            with m.State("DRAW_EMIT"):
                m.d.comb += [self.busy.eq(1), render_state.eq(6)]
                with m.If(pending & line_ready):
                    m.d.sync += [pending.eq(0), draw_ch.eq(draw_ch + 1)]
                    m.next = "DRAW"

            with m.State("WRITE_SHOWN"):
                m.d.comb += [
                    self.busy.eq(1),
                    self.sw_en.eq(1),
                    self.sw_addr.eq(render_col),
                    render_state.eq(7),
                ]
                m.next = "WAIT"

        return m
