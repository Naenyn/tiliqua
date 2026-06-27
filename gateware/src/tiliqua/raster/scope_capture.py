# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out
from amaranth_future import fixed

from . import PSQ, PSQ_BASE_FBITS

# Must be >= the widest plot we render (display h_active - margins).  720p is
# 1280 wide (~1264 plottable columns); round up so the full screen is covered.
MAX_CAPTURE_COLS = 1280
RAMP_END = fixed.Const(0.985, shape=PSQ)


def envelope_word(ch_ymin, ch_ymax):
    # Channel ``ch`` occupies bits [32*ch : 32*ch+32], with ymin in the low
    # 16 bits and ymax in the high 16 bits.  This must match the unpacking in
    # ColumnRenderer.
    return Cat(
        ch_ymin[0], ch_ymax[0],
        ch_ymin[1], ch_ymax[1],
        ch_ymin[2], ch_ymax[2],
        ch_ymin[3], ch_ymax[3],
    )


# Per-column "no data captured" sentinel: every channel has ymin=0, ymax=-1, so
# the renderer's (ymax >= ymin) test fails and the column is erased but not drawn.
ENVELOPE_SENTINEL = 0xFFFF0000_FFFF0000_FFFF0000_FFFF0000


class ColumnCapture(wiring.Component):

    """
    Accumulate per-column min/max envelopes while ``active``.

    ``ramp`` supplies the horizontal position; ``audio`` supplies one PSQ per
    channel.  Column envelopes are stored in dual-port block RAM for the render
    pass.
    """

    def __init__(self, *, n_channels=4):
        assert n_channels == 4
        self.n_channels = n_channels
        super().__init__({
            "active": In(1),
            "clear": In(1),
            "plot_x_lo": In(signed(16)),
            "plot_x_hi": In(signed(16)),
            "scale_x": In(unsigned(4)),
            "x_offset": In(signed(16)),
            "scale_y": In(unsigned(4)).array(n_channels),
            "y_offset": In(signed(16)).array(n_channels),
            "sample_valid": In(1),
            "ramp": In(PSQ),
            "audio": In(PSQ).array(n_channels),
            "sweep_done": Out(1),
            "w_en": Out(1),
            "w_addr": Out(range(MAX_CAPTURE_COLS)),
            "w_data": Out(unsigned(128)),
            "dbg_in_x": Out(signed(16)),
            "dbg_in_y0": Out(signed(16)),
            "dbg_in_plot": Out(1),
            "dbg_at_end": Out(1),
            "dbg_sweeping": Out(1),
            "dbg_has_col": Out(1),
            "dbg_sweep_end": Out(1),
            "max_col": Out(range(MAX_CAPTURE_COLS)),
        })

    def elaborate(self, platform):
        m = Module()

        in_x = Signal(signed(16))
        in_y = Array(Signal(signed(16), name=f"in_y{i}") for i in range(self.n_channels))

        m.d.comb += in_x.eq(
            (self.ramp.reshape(PSQ_BASE_FBITS).as_value() >> self.scale_x) +
            self.x_offset
        )
        for ch in range(self.n_channels):
            m.d.comb += in_y[ch].eq(
                (-self.audio[ch].reshape(PSQ_BASE_FBITS).as_value() >> self.scale_y[ch]) +
                self.y_offset[ch]
            )

        latched_col = Signal(range(MAX_CAPTURE_COLS))
        max_col = Signal(range(MAX_CAPTURE_COLS))
        has_col = Signal()
        prev_x = Signal(signed(16))
        has_prev_x = Signal()
        col_ymin = Array(Signal(signed(16)) for _ in range(self.n_channels))
        col_ymax = Array(Signal(signed(16)) for _ in range(self.n_channels))

        # Envelope RAM clear: on capture start, blank every column to the "no
        # data" sentinel so unvisited columns from a previous sweep don't render
        # stale envelopes.  Takes MAX_CAPTURE_COLS cycles (block RAM, fast).
        clearing = Signal()
        clear_addr = Signal(range(MAX_CAPTURE_COLS))

        col_index = Signal(range(MAX_CAPTURE_COLS))
        in_plot = Signal()
        m.d.comb += [
            col_index.eq(in_x - self.plot_x_lo),
            in_plot.eq(
                self.sample_valid &
                self.active &
                ~clearing &
                (in_x >= self.plot_x_lo) &
                (in_x < self.plot_x_hi) &
                (col_index < MAX_CAPTURE_COLS)
            ),
        ]

        flush_col = Signal(range(MAX_CAPTURE_COLS))
        flush_word = Signal(unsigned(128))
        do_flush = Signal()
        m.d.comb += flush_word.eq(envelope_word(col_ymin, col_ymax))

        active_prev = Signal()
        active_rise = Signal()
        sweeping = Signal()
        m.d.sync += active_prev.eq(self.active)
        m.d.comb += active_rise.eq(self.active & ~active_prev)

        at_end = Signal()
        prev_at_end = Signal()
        m.d.comb += at_end.eq(self.ramp > RAMP_END)

        pen_lift = Signal()
        m.d.comb += pen_lift.eq(
            self.sample_valid &
            self.active &
            has_prev_x &
            has_col &
            (in_x < prev_x)
        )

        end_reached = Signal()
        m.d.comb += end_reached.eq(
            self.active &
            self.sample_valid &
            at_end &
            ~prev_at_end &
            sweeping &
            has_col
        )

        sweep_end = Signal()
        m.d.comb += sweep_end.eq(pen_lift | end_reached)
        m.d.comb += self.sweep_done.eq(sweep_end)

        with m.If(self.clear | active_rise):
            m.d.sync += [
                has_col.eq(0),
                has_prev_x.eq(0),
                prev_at_end.eq(0),
                sweeping.eq(0),
                max_col.eq(0),
                clearing.eq(1),
                clear_addr.eq(0),
            ]
            for ch in range(self.n_channels):
                m.d.sync += [
                    col_ymin[ch].eq(0),
                    col_ymax[ch].eq(-1),
                ]
        with m.Elif(clearing):
            m.d.sync += clear_addr.eq(clear_addr + 1)
            with m.If(clear_addr == (MAX_CAPTURE_COLS - 1)):
                m.d.sync += clearing.eq(0)

        with m.Elif(self.active & self.sample_valid):
            m.d.sync += [
                prev_x.eq(in_x),
                prev_at_end.eq(at_end),
            ]
            with m.If(~at_end):
                m.d.sync += sweeping.eq(1)

        with m.If(sweep_end):
            m.d.sync += [
                has_col.eq(0),
                has_prev_x.eq(0),
            ]

        with m.If(in_plot):
            with m.If(~has_col):
                m.d.sync += [
                    has_col.eq(1),
                    has_prev_x.eq(1),
                    latched_col.eq(col_index),
                ]
                for ch in range(self.n_channels):
                    m.d.sync += [
                        col_ymin[ch].eq(in_y[ch]),
                        col_ymax[ch].eq(in_y[ch]),
                    ]
            with m.Elif(col_index != latched_col):
                m.d.comb += [
                    do_flush.eq(1),
                    flush_col.eq(latched_col),
                ]
                m.d.sync += latched_col.eq(col_index)
                for ch in range(self.n_channels):
                    m.d.sync += [
                        col_ymin[ch].eq(in_y[ch]),
                        col_ymax[ch].eq(in_y[ch]),
                    ]
            with m.Else():
                for ch in range(self.n_channels):
                    with m.If(in_y[ch] < col_ymin[ch]):
                        m.d.sync += col_ymin[ch].eq(in_y[ch])
                    with m.If(in_y[ch] > col_ymax[ch]):
                        m.d.sync += col_ymax[ch].eq(in_y[ch])

        with m.If(sweep_end & has_col):
            m.d.comb += [
                do_flush.eq(1),
                flush_col.eq(latched_col),
            ]

        m.d.sync += self.w_en.eq(0)
        with m.If(clearing):
            m.d.sync += [
                self.w_en.eq(1),
                self.w_addr.eq(clear_addr),
                self.w_data.eq(ENVELOPE_SENTINEL),
            ]
        with m.Elif(do_flush):
            m.d.sync += [
                self.w_en.eq(1),
                self.w_addr.eq(flush_col),
                self.w_data.eq(flush_word),
            ]
            with m.If(flush_col > max_col):
                m.d.sync += max_col.eq(flush_col)

        m.d.comb += [
            self.dbg_in_x.eq(in_x),
            self.dbg_in_y0.eq(in_y[0]),
            self.dbg_in_plot.eq(in_plot),
            self.dbg_at_end.eq(at_end),
            self.dbg_sweeping.eq(sweeping),
            self.dbg_has_col.eq(has_col),
            self.dbg_sweep_end.eq(sweep_end),
            self.max_col.eq(max_col),
        ]

        return m
