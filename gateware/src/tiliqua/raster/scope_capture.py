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

# A displayed trace coordinate never needs the full signed 16-bit range used by
# the capture arithmetic.  The widest supported rotated display spans only
# +/-640 logical pixels, so 12 signed bits leave ample headroom while allowing
# each four-channel envelope column to fit in 100 bits instead of 128.  On ECP5
# this reduces each 1280-column sweep bank from 12 to 9 DP16KD blocks.
ENVELOPE_COORD_BITS = 12
ENVELOPE_CHANNEL_BITS = 1 + 2 * ENVELOPE_COORD_BITS
ENVELOPE_WORD_BITS = 4 * ENVELOPE_CHANNEL_BITS

# Bridge only genuine display discontinuities across a column boundary.  The
# previous one-pixel threshold widened every ordinary slope and turned codec
# settling at square/saw transitions into visible hooks and rounded shoulders.
VERTICAL_DY_THRESH = 12

# Eurorack-friendly V/div LUT for ``yscale_idx`` (must match ``ScopeVScale`` in scope FW).
# Maps sample deflection: in_y = ((-av * mul) >> rshift) + y_offset, where ``av`` is
# the reshaped PSQ sample (~4000 counts per volt).  One 1 V grid step is ppv>>6 = 62 px.
YSCALE_LUT = (
    (159, 10),  # 0: 0.1 V/div
    (127, 11),  # 1: 0.25 V/div
    (127, 12),  # 2: 0.5 V/div
    (127, 13),  # 3: 1.0 V/div
    (205, 15),  # 4: 2.5 V/div
    (203, 16),  # 5: 5.0 V/div
)


def envelope_word(ch_ymin, ch_ymax):
    coord_min = -(1 << (ENVELOPE_COORD_BITS - 1))
    coord_max = (1 << (ENVELOPE_COORD_BITS - 1)) - 1

    def packed_coord(value):
        # Slice the result explicitly: mixing signed bounds with an unsigned
        # value slice otherwise makes Amaranth widen this Mux by one bit.
        return Mux(
            value < coord_min,
            Const(coord_min, signed(ENVELOPE_COORD_BITS)),
            Mux(
                value > coord_max,
                Const(coord_max, signed(ENVELOPE_COORD_BITS)),
                value[:ENVELOPE_COORD_BITS],
            ),
        )[:ENVELOPE_COORD_BITS]

    # Each channel is {valid, ymin[11:0], ymax[11:0]}.  An explicit valid bit
    # avoids spending coordinate encodings on the old 16-bit sentinel.
    chunks = []
    for ch in range(4):
        chunks.append(Cat(
            ch_ymax[ch] >= ch_ymin[ch],
            packed_coord(ch_ymin[ch]),
            packed_coord(ch_ymax[ch]),
        ))
    packed = Cat(*chunks)
    assert len(packed) == ENVELOPE_WORD_BITS
    return packed


# Per-column "no data captured" sentinel: all per-channel valid bits are clear.
ENVELOPE_SENTINEL = 0


class ColumnCapture(wiring.Component):

    """
    Accumulate per-column min/max envelopes while ``active`` and stream each
    finished column out as soon as it completes (progressive / live rendering).

    ``ramp`` supplies the horizontal position; ``audio`` supplies one PSQ per
    channel.  Accumulation is gated (``armed``) to a single clean ramp sweep at
    a time, and per-channel min/max updates are skipped for channels with
    ``visible`` de-asserted (hidden channels stay at the envelope sentinel).

    Each finished column is emitted on ``flush_*`` as a 1-cycle pulse.  It is
    not back-pressured: if the downstream FIFO is full the column is simply
    dropped, which only ever happens at very fast timebases.
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
            "scale_y": In(unsigned(3)).array(n_channels),
            "y_offset": In(signed(16)).array(n_channels),
            "sample_valid": In(1),
            "ramp": In(PSQ),
            "audio": In(PSQ).array(n_channels),
            "visible": In(1).array(n_channels),
            "sweep_done": Out(1),
            # Finished-column stream (1-cycle pulse, not back-pressured).
            "flush_valid": Out(1),
            "flush_col": Out(range(MAX_CAPTURE_COLS)),
            "flush_word": Out(unsigned(ENVELOPE_WORD_BITS)),
            "max_col": Out(range(MAX_CAPTURE_COLS)),
        })

    def elaborate(self, platform):
        m = Module()

        raw_x = Signal(signed(16))
        raw_y = Array(Signal(signed(16), name=f"raw_y{i}") for i in range(self.n_channels))
        scaled_x = Signal(signed(16))
        in_x = Signal(signed(16))
        in_y = Array(Signal(signed(16), name=f"in_y{i}") for i in range(self.n_channels))
        scaled_valid = Signal()
        scaled_active = Signal()
        scaled_at_end = Signal()
        sample_valid = Signal()
        sample_active = Signal()
        sample_at_end = Signal()
        y_mul = Array(Signal(8, name=f"y_mul{i}") for i in range(self.n_channels))
        y_rshift = Array(Signal(5, name=f"y_rshift{i}") for i in range(self.n_channels))
        y_rshift_scaled = Array(Signal(5, name=f"y_rshift_scaled{i}")
                                for i in range(self.n_channels))
        y_offset_scaled = Array(Signal(signed(16), name=f"y_offset_scaled{i}")
                                for i in range(self.n_channels))
        yprod = Array(Signal(signed(26), name=f"yprod{i}")
                      for i in range(self.n_channels))
        yprod_scaled = Array(Signal(signed(26), name=f"yprod_scaled{i}")
                             for i in range(self.n_channels))

        m.d.comb += raw_x.eq(
            (self.ramp.reshape(PSQ_BASE_FBITS).as_value() >> self.scale_x) +
            self.x_offset
        )
        for ch in range(self.n_channels):
            with m.Switch(self.scale_y[ch]):
                for idx, (mul, rshift) in enumerate(YSCALE_LUT):
                    with m.Case(idx):
                        m.d.comb += [
                            y_mul[ch].eq(mul),
                            y_rshift[ch].eq(rshift),
                        ]
                with m.Default():
                    m.d.comb += [
                        y_mul[ch].eq(YSCALE_LUT[3][0]),
                        y_rshift[ch].eq(YSCALE_LUT[3][1]),
                    ]
            av = self.audio[ch].reshape(PSQ_BASE_FBITS).as_value()
            m.d.comb += [
                yprod[ch].eq(-av * y_mul[ch]),
                raw_y[ch].eq(
                    (yprod_scaled[ch] >> y_rshift_scaled[ch]) +
                    y_offset_scaled[ch]),
            ]

        # Split sample scaling at the multiplier output, then register the
        # shifted/offset coordinate before envelope accumulation. Audio samples
        # arrive much more slowly than sync, so neither stage reduces throughput.
        m.d.sync += scaled_valid.eq(self.sample_valid)
        with m.If(self.sample_valid):
            m.d.sync += [
                scaled_x.eq(raw_x),
                scaled_active.eq(self.active),
                scaled_at_end.eq(self.ramp > RAMP_END),
            ]
            for ch in range(self.n_channels):
                m.d.sync += [
                    yprod_scaled[ch].eq(yprod[ch]),
                    y_rshift_scaled[ch].eq(y_rshift[ch]),
                    y_offset_scaled[ch].eq(self.y_offset[ch]),
                ]

        m.d.sync += sample_valid.eq(scaled_valid)
        with m.If(scaled_valid):
            m.d.sync += [
                in_x.eq(scaled_x),
                sample_active.eq(scaled_active),
                sample_at_end.eq(scaled_at_end),
            ]
            for ch in range(self.n_channels):
                m.d.sync += in_y[ch].eq(raw_y[ch])

        latched_col = Signal(range(MAX_CAPTURE_COLS))
        max_col = Signal(range(MAX_CAPTURE_COLS))
        has_col = Signal()
        prev_x = Signal(signed(16))
        has_prev_x = Signal()
        col_ymin = Array(Signal(signed(16)) for _ in range(self.n_channels))
        col_ymax = Array(Signal(signed(16)) for _ in range(self.n_channels))
        prev_in_y = Array(Signal(signed(16)) for _ in range(self.n_channels))
        flush_ymin = Array(Signal(signed(16)) for _ in range(self.n_channels))
        flush_ymax = Array(Signal(signed(16)) for _ in range(self.n_channels))
        col_changing = Signal()

        prev_at_end = Signal()

        # ``armed`` restricts accumulation to a clean, in-progress sweep.  It is
        # set on a ramp restart and cleared at the top, so partial sweeps and the
        # NORM hold-at-top never pollute the captured columns.
        armed = Signal()

        col_index = Signal(range(MAX_CAPTURE_COLS))
        pen_lift = Signal()
        m.d.comb += pen_lift.eq(
            sample_valid &
            sample_active &
            has_prev_x &
            has_col &
            (in_x < prev_x)
        )

        in_plot = Signal()
        m.d.comb += [
            col_index.eq(in_x - self.plot_x_lo),
            in_plot.eq(
                sample_valid &
                sample_active &
                armed &
                ~pen_lift &
                (in_x >= self.plot_x_lo) &
                (in_x < self.plot_x_hi) &
                (col_index < MAX_CAPTURE_COLS)
            ),
        ]

        m.d.comb += col_changing.eq(
            in_plot & has_col & (col_index != latched_col)
        )
        steep_step = Array(Signal(name=f"steep_step{ch}") for ch in range(self.n_channels))
        bridge_lo = Array(Signal(signed(16), name=f"bridge_lo{ch}") for ch in range(self.n_channels))
        bridge_hi = Array(Signal(signed(16), name=f"bridge_hi{ch}") for ch in range(self.n_channels))
        for ch in range(self.n_channels):
            dy_step = Signal(signed(17), name=f"dy_step{ch}")
            m.d.comb += [
                dy_step.eq(in_y[ch] - prev_in_y[ch]),
                steep_step[ch].eq(
                    self.visible[ch] & col_changing & (
                        (dy_step >= VERTICAL_DY_THRESH) |
                        (dy_step <= -VERTICAL_DY_THRESH)
                    )
                ),
                bridge_lo[ch].eq(Mux(in_y[ch] < prev_in_y[ch], in_y[ch], prev_in_y[ch])),
                bridge_hi[ch].eq(Mux(in_y[ch] > prev_in_y[ch], in_y[ch], prev_in_y[ch])),
                flush_ymin[ch].eq(
                    Mux(steep_step[ch],
                        Mux(bridge_lo[ch] < col_ymin[ch], bridge_lo[ch], col_ymin[ch]),
                        col_ymin[ch])
                ),
                flush_ymax[ch].eq(
                    Mux(steep_step[ch],
                        Mux(bridge_hi[ch] > col_ymax[ch], bridge_hi[ch], col_ymax[ch]),
                        col_ymax[ch])
                ),
            ]

        flush_col = Signal(range(MAX_CAPTURE_COLS))
        do_flush = Signal()

        active_prev = Signal()
        active_rise = Signal()
        sweeping = Signal()
        m.d.sync += active_prev.eq(self.active)
        m.d.comb += active_rise.eq(self.active & ~active_prev)

        end_reached = Signal()
        m.d.comb += end_reached.eq(
            sample_active &
            sample_valid &
            sample_at_end &
            ~prev_at_end &
            sweeping &
            has_col
        )

        sweep_end = Signal()
        m.d.comb += sweep_end.eq(pen_lift | end_reached)
        # Ramp restart (top -> low): start of a fresh sweep.
        sweep_restart = Signal()
        m.d.comb += sweep_restart.eq(
            sample_active &
            sample_valid &
            prev_at_end &
            ~sample_at_end
        )

        with m.If(self.clear | active_rise):
            m.d.sync += [
                has_col.eq(0),
                has_prev_x.eq(0),
                prev_at_end.eq(0),
                sweeping.eq(0),
                max_col.eq(0),
                armed.eq(0),
            ]
            for ch in range(self.n_channels):
                m.d.sync += [
                    col_ymin[ch].eq(0),
                    col_ymax[ch].eq(-1),
                    prev_in_y[ch].eq(0),
                ]
        with m.Elif(sample_active & sample_valid):
            m.d.sync += [
                prev_x.eq(in_x),
                prev_at_end.eq(sample_at_end),
            ]
            for ch in range(self.n_channels):
                m.d.sync += prev_in_y[ch].eq(in_y[ch])
            with m.If(~sample_at_end):
                m.d.sync += sweeping.eq(1)

        # Disarm at sweep end, (re)arm on restart.  sweep_restart is applied
        # last so a wrap that is simultaneously an end and a restart keeps us
        # armed for the new sweep.
        with m.If(sweep_end):
            m.d.sync += [
                has_col.eq(0),
                has_prev_x.eq(0),
                armed.eq(0),
            ]
        with m.If(sweep_restart):
            m.d.sync += armed.eq(1)

        with m.If(in_plot):
            with m.If(~has_col):
                m.d.sync += [
                    has_col.eq(1),
                    has_prev_x.eq(1),
                    latched_col.eq(col_index),
                ]
                for ch in range(self.n_channels):
                    with m.If(self.visible[ch]):
                        m.d.sync += [
                            col_ymin[ch].eq(in_y[ch]),
                            col_ymax[ch].eq(in_y[ch]),
                        ]
                    with m.Else():
                        m.d.sync += [
                            col_ymin[ch].eq(0),
                            col_ymax[ch].eq(-1),
                        ]
            with m.If(col_changing):
                m.d.comb += [
                    do_flush.eq(1),
                    flush_col.eq(latched_col),
                ]
                m.d.sync += latched_col.eq(col_index)
                for ch in range(self.n_channels):
                    with m.If(self.visible[ch]):
                        m.d.sync += [
                            col_ymin[ch].eq(in_y[ch]),
                            col_ymax[ch].eq(in_y[ch]),
                        ]
                    with m.Else():
                        m.d.sync += [
                            col_ymin[ch].eq(0),
                            col_ymax[ch].eq(-1),
                        ]
            with m.Elif(has_col & ~col_changing):
                for ch in range(self.n_channels):
                    with m.If(self.visible[ch]):
                        with m.If(in_y[ch] < col_ymin[ch]):
                            m.d.sync += col_ymin[ch].eq(in_y[ch])
                        with m.If(in_y[ch] > col_ymax[ch]):
                            m.d.sync += col_ymax[ch].eq(in_y[ch])

        with m.If(sweep_end & has_col):
            m.d.comb += [
                do_flush.eq(1),
                flush_col.eq(latched_col),
            ]

        # Register the full-width envelope before compacting it.  This keeps
        # the bridge/min-max selection and the signed saturation comparisons
        # in separate cycles; both stages can still accept one column per
        # clock. Keep sweep_done in the same pipeline as the final column so
        # the last write and bank-swap request remain aligned.
        packed_ymin = Array(Signal(signed(16)) for _ in range(self.n_channels))
        packed_ymax = Array(Signal(signed(16)) for _ in range(self.n_channels))
        flush_pending = Signal()
        flush_col_pending = Signal(range(MAX_CAPTURE_COLS))
        sweep_done_pending = Signal()
        m.d.sync += [
            flush_pending.eq(do_flush),
            flush_col_pending.eq(flush_col),
            sweep_done_pending.eq(sweep_end),
            self.flush_valid.eq(flush_pending),
            self.flush_col.eq(flush_col_pending),
            self.flush_word.eq(envelope_word(packed_ymin, packed_ymax)),
            self.sweep_done.eq(sweep_done_pending),
        ]
        with m.If(do_flush):
            for ch in range(self.n_channels):
                m.d.sync += [
                    packed_ymin[ch].eq(flush_ymin[ch]),
                    packed_ymax[ch].eq(flush_ymax[ch]),
                ]
        # Update progress from the registered column rather than extending the
        # plot-bound/column-selection path through another comparison and mux.
        with m.If(flush_pending & (flush_col_pending > max_col)):
            m.d.sync += max_col.eq(flush_col_pending)
        m.d.comb += self.max_col.eq(max_col)

        return m
