# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Streaming spectral analysis and beam-raced waterfall display."""

import math
import os

from amaranth import *
from amaranth.lib import data, fifo, memory, stream, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from tiliqua import dsp
from tiliqua.dsp import ASQ
from tiliqua.video.types import Pixel, ScanPixel


FFT_SIZE = 512
N_BINS = FFT_SIZE // 2
HISTORY_COLS = 256
SPECTRUM_DB_FLOOR = -96.0
SPECTRUM_CORDIC_GAIN = dsp.cordic.RectToPolarCordic.K
# Axis text is refreshed through the existing framebuffer plotter. Keeping
# the old beam-raced implementation below as a disabled fallback is useful
# for simulation/reference, but omitting its per-label comparators saves the
# routing fabric that was preventing this design from completing placement.
AXIS_LABELS_IN_FRAMEBUFFER = True


def _logical_scan_coordinates_from_last(x, y, h_last, v_last, rotation):
    """Map a scan position using precomputed final active coordinates."""
    return (
        Mux(rotation == 1, y,
            Mux(rotation == 2, h_last - x,
                Mux(rotation == 3, h_last - y, x))),
        Mux(rotation == 1, v_last - x,
            Mux(rotation == 2, v_last - y,
                Mux(rotation == 3, x, y))),
    )


def _logical_scan_coordinates(x, y, h_active, v_active, rotation):
    """Map a physical DVI scan position into framebuffer coordinates.

    ``h_active`` and ``v_active`` are the logical dimensions exposed by the
    rotated framebuffer. The scan timing itself remains physical; only direct
    overlay layout and hit-testing use the returned coordinates.
    """
    return _logical_scan_coordinates_from_last(
        x, y, h_active - 1, v_active - 1, rotation)


MAGNITUDE_LOG_LEVEL_FRAC_BITS = 3


def _magnitude_raw_to_dbfs_position(raw, *, f_bits=ASQ.f_bits):
    """Convert an uncorrected Hann/FFT/CORDIC magnitude to a dBFS position.

    The forward FFT is normalized by 1/N. A real, bin-centred full-scale
    sinusoid contributes half its amplitude to the positive spectrum and the
    Hann window has a coherent gain of one half, while the magnitude CORDIC is
    intentionally left at its gain K. Consequently ``raw / 2**f_bits`` needs
    a factor of ``4/K`` to become conventional single-sided amplitude.
    """
    if raw <= 0:
        return 0.0
    amplitude = (raw / (1 << f_bits)) * (4.0 / SPECTRUM_CORDIC_GAIN)
    dbfs = 20.0 * math.log10(amplitude)
    return (dbfs - SPECTRUM_DB_FLOOR) / -SPECTRUM_DB_FLOOR * 63


def _magnitude_raw_to_dbfs_level(raw, *, f_bits=ASQ.f_bits):
    """Convert an uncorrected Hann/FFT/CORDIC magnitude to 0..63 dBFS."""
    position = _magnitude_raw_to_dbfs_position(raw, f_bits=f_bits)
    return max(0, min(63, round(position)))


def _magnitude_log_tables(shape=ASQ):
    """Build fractional exponent and mantissa contributions for the log LUT."""
    width = shape.as_shape().width
    exponent_bits = (width - 1).bit_length()
    scale = 1 << MAGNITUDE_LOG_LEVEL_FRAC_BITS
    maximum = 63 * scale

    exponent_table = []
    for exponent_value in range(1 << exponent_bits):
        representative = (1 << exponent_value) * (1.0 + 0.5 / 16.0)
        position = _magnitude_raw_to_dbfs_position(
            representative, f_bits=shape.f_bits)
        exponent_table.append(max(0, min(maximum, round(position * scale))))

    mantissa_table = []
    mantissa_base = 1.0 + 0.5 / 16.0
    for mantissa_value in range(16):
        ratio = (1.0 + (mantissa_value + 0.5) / 16.0) / mantissa_base
        correction_db = 20.0 * math.log10(ratio)
        mantissa_table.append(round(correction_db * 63 / 96 * scale))

    return exponent_table, mantissa_table


def _approximate_magnitude_raw_to_dbfs_level(raw, shape=ASQ):
    """Software model of :class:`MagnitudeToDbfs`, used by accuracy tests."""
    if raw <= 0:
        return 0

    exponent_table, mantissa_table = _magnitude_log_tables(shape)
    exponent = raw.bit_length() - 1
    if exponent >= 4:
        mantissa = (raw >> (exponent - 4)) & 0xf
    elif exponent > 0:
        mantissa = (raw & ((1 << exponent) - 1)) << (4 - exponent)
    else:
        mantissa = 0

    fractional_level = exponent_table[exponent] + mantissa_table[mantissa]
    rounded_level = (
        fractional_level + (1 << (MAGNITUDE_LOG_LEVEL_FRAC_BITS - 1))
    ) >> MAGNITUDE_LOG_LEVEL_FRAC_BITS
    return min(63, rounded_level)


def _dbfs_level_q4_to_height(level_q4, tall):
    """Map a 0..63 Q4 dBFS level across a 256- or 512-pixel plot.

    A plain power-of-two scale maps full scale to 252 or 504 pixels, leaving
    the 0dBFS value visibly below the top axis. These shift-add forms closely
    approximate multiplication by 255/63 or 511/63, reach both endpoints
    exactly, and stay within one pixel of the ideal rounded result.
    """
    level_q4 = level_q4.as_unsigned()
    return Mux(
        tall,
        (level_q4 >> 1) + (level_q4 >> 7),
        (level_q4 >> 2) + (level_q4 >> 8),
    )


def _dbfs_level_to_height(level, tall):
    """Integer-level companion to :func:`_dbfs_level_q4_to_height`."""
    return _dbfs_level_q4_to_height(level << 4, tall)


class SpectrumLogFrameHandoff(wiring.Component):
    """Delay log-render controls alongside the synchronous reverse-map ROM.

    The bank is part of the sample transaction: it must not be recomputed
    after publishing the completed frame, because publication immediately
    changes the next write bank.
    """

    def __init__(self):
        super().__init__({
            "i_valid": In(1),
            "i_first": In(1),
            "i_write": In(1),
            "i_frame_write": In(1),
            "i_bin": In(unsigned(9)),
            "i_bank": In(1),
            "o_valid": Out(1),
            "o_first": Out(1),
            "o_write": Out(1),
            "o_frame_write": Out(1),
            "o_bin": Out(unsigned(9)),
            "o_bank": Out(1),
            "o_publish": Out(1),
        })

    def elaborate(self, platform):
        m = Module()
        lookup_valid = Signal()
        lookup_first = Signal()
        lookup_write = Signal()
        lookup_frame_write = Signal()
        lookup_bin = Signal(9)
        lookup_bank = Signal()

        m.d.sync += [
            # The analyzer emits all 512 complex bins. Reject the mirrored
            # negative-frequency half here as well as at the caller so a
            # future integration change cannot fold it into the 256-column
            # positive-frequency display.
            lookup_valid.eq(self.i_valid & (self.i_bin < N_BINS)),
            self.o_valid.eq(lookup_valid),
        ]
        with m.If(self.i_valid):
            m.d.sync += [
                lookup_first.eq(self.i_first),
                lookup_write.eq(self.i_write),
                lookup_frame_write.eq(self.i_frame_write),
                lookup_bin.eq(self.i_bin),
                lookup_bank.eq(self.i_bank),
            ]
        with m.If(lookup_valid):
            m.d.sync += [
                self.o_first.eq(lookup_first),
                self.o_write.eq(lookup_write),
                self.o_frame_write.eq(lookup_frame_write),
                self.o_bin.eq(lookup_bin),
                self.o_bank.eq(lookup_bank),
            ]
        m.d.comb += self.o_publish.eq(
            self.o_valid & self.o_frame_write & (self.o_bin == N_BINS - 1))
        return m


class SpectrumReadRequestAligner(wiring.Component):
    """Keep a spectrum pixel's read address and styling metadata together."""

    def __init__(self):
        super().__init__({
            "i_plot": In(1),
            "i_log_addr": In(unsigned(8)),
            "i_log_frac": In(unsigned(8)),
            "i_color": In(unsigned(4)),
            "o_plot": Out(1),
            "o_log_addr": Out(unsigned(8)),
            "o_log_frac": Out(unsigned(8)),
            "o_color": Out(unsigned(4)),
        })

    def elaborate(self, platform):
        m = Module()
        m.d.dvi += [
            self.o_plot.eq(self.i_plot),
            self.o_log_addr.eq(self.i_log_addr),
            self.o_log_frac.eq(self.i_log_frac),
            self.o_color.eq(self.i_color),
        ]
        return m


class MagnitudeToDbfs(wiring.Component):
    """Streaming calibrated magnitude-to-dBFS converter.

    A leading-bit exponent and four mantissa bits address a compact log LUT.
    Unlike a uniformly addressed linear-magnitude LUT, this retains useful
    precision throughout the fixed-point input's complete dynamic range.
    """

    def __init__(self, shape=ASQ):
        self.shape = shape
        super().__init__({
            "i": In(stream.Signature(dsp.block.Block(shape))),
            "o": Out(stream.Signature(dsp.block.Block(unsigned(6)))),
        })

    def elaborate(self, platform):
        m = Module()
        width = self.shape.as_shape().width
        exponent_bits = (width - 1).bit_length()
        raw = Signal(unsigned(width))
        exponent = Signal(exponent_bits)
        mantissa = Signal(4)

        # log2(exponent * mantissa) is separable. Keeping independent tables
        # avoids both a block RAM and the very large 512:1 mux produced by an
        # Array containing every exponent/mantissa combination. Each entry
        # represents the midpoint of its four-bit mantissa interval; this is
        # comfortably finer than the display's 1.52dB level quantization.
        exponent_table, mantissa_table = _magnitude_log_tables(self.shape)
        fractional_maximum = 63 << MAGNITUDE_LOG_LEVEL_FRAC_BITS
        exponent_level_bits = max(exponent_table).bit_length()
        mantissa_level_bits = max(mantissa_table).bit_length()
        exponent_levels = Array(
            Const(level, exponent_level_bits) for level in exponent_table)
        mantissa_levels = Array(
            Const(level, mantissa_level_bits) for level in mantissa_table)

        lookup_exponent = Signal.like(exponent)
        lookup_mantissa = Signal.like(mantissa)
        input_zero = Signal()
        output_first = Signal()
        output_level = Signal(6)
        level_sum = Signal(range(
            max(exponent_table) + max(mantissa_table) + 1))
        rounded_level = Signal(range(
            ((max(exponent_table) + max(mantissa_table))
             >> MAGNITUDE_LOG_LEVEL_FRAC_BITS) + 2))

        m.d.comb += [
            raw.eq(self.i.payload.sample.as_value()),
            exponent.eq(0),
            mantissa.eq(0),
            level_sum.eq(
                exponent_levels[lookup_exponent]
                + mantissa_levels[lookup_mantissa]),
            rounded_level.eq(
                (level_sum
                 + (1 << (MAGNITUDE_LOG_LEVEL_FRAC_BITS - 1)))
                >> MAGNITUDE_LOG_LEVEL_FRAC_BITS),
        ]

        # Priority-encode the leading one and collect the next four bits as a
        # normalized fractional mantissa. Constant slices avoid a barrel
        # shifter on this already timing-sensitive analyzer path.
        for bit in reversed(range(width)):
            condition = raw[bit]
            if bit == width - 1:
                context = m.If(condition)
            else:
                context = m.Elif(condition)
            with context:
                m.d.comb += exponent.eq(bit)
                if bit >= 4:
                    m.d.comb += mantissa.eq(raw[bit - 4:bit])
                elif bit > 0:
                    m.d.comb += mantissa.eq(raw[:bit] << (4 - bit))
                else:
                    m.d.comb += mantissa.eq(0)

        # Register both halves of the lookup before evaluating the compact
        # tables. This also provides ordinary stream back-pressure and keeps
        # the leading-bit encoder out of the output path.
        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += self.i.ready.eq(1)
                with m.If(self.i.valid):
                    m.d.sync += [
                        lookup_exponent.eq(exponent),
                        lookup_mantissa.eq(mantissa),
                        input_zero.eq(raw == 0),
                        output_first.eq(self.i.payload.first),
                    ]
                    m.next = "LOOKUP"
            with m.State("LOOKUP"):
                m.d.sync += output_level.eq(Mux(
                    input_zero,
                    0,
                    Mux(level_sum >= fractional_maximum, 63, rounded_level)))
                m.next = "OUTPUT"
            with m.State("OUTPUT"):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.payload.first.eq(output_first),
                    self.o.payload.sample.eq(output_level),
                ]
                with m.If(self.o.ready):
                    m.next = "IDLE"

        return m


class DbfsLevelSmoother(wiring.Component):
    """Short display-oriented EMA over calibrated six-bit dB levels."""

    def __init__(self, sz=FFT_SIZE):
        self.sz = sz
        super().__init__({
            "attack_shift": In(unsigned(2)),
            "release_shift": In(unsigned(2)),
            "i": In(stream.Signature(dsp.block.Block(unsigned(6)))),
            "o": Out(stream.Signature(dsp.block.Block(unsigned(6)))),
        })

    def elaborate(self, platform):
        m = Module()
        m.submodules.mem = mem = memory.Memory(
            shape=unsigned(6), depth=self.sz, init=[0] * self.sz,
            attrs={"ram_style": "distributed"})
        # The asynchronous distributed-RAM read follows the registered bin
        # index. A synchronous read here would sample the previous index on
        # the same edge that accepts a new bin, shifting the EMA state by one.
        mem_r = mem.read_port(domain="comb")
        mem_w = mem.write_port()

        index = Signal(range(self.sz + 1))
        input_level = Signal(6)
        previous_level = Signal(6)
        output_level = Signal(6)
        output_first = Signal()
        rising_delta = Signal(7)
        falling_delta = Signal(7)
        shift = Signal(2)
        step = Signal(7)
        smoothed = Signal(7)
        m.d.comb += [
            mem_r.addr.eq(index),
            mem_w.addr.eq(index),
            rising_delta.eq(input_level - previous_level),
            falling_delta.eq(previous_level - input_level),
            shift.eq(Mux(input_level >= previous_level,
                         self.attack_shift, self.release_shift)),
        ]
        with m.Switch(shift):
            with m.Case(0):
                m.d.comb += step.eq(Mux(
                    input_level >= previous_level,
                    rising_delta, falling_delta))
            with m.Case(1):
                m.d.comb += step.eq((Mux(
                    input_level >= previous_level,
                    rising_delta, falling_delta) + 1) >> 1)
            with m.Case(2):
                m.d.comb += step.eq((Mux(
                    input_level >= previous_level,
                    rising_delta, falling_delta) + 3) >> 2)
            with m.Default():
                m.d.comb += step.eq((Mux(
                    input_level >= previous_level,
                    rising_delta, falling_delta) + 7) >> 3)
        m.d.comb += smoothed.eq(Mux(
            input_level >= previous_level,
            previous_level + step,
            previous_level - step))
        m.d.sync += mem_w.en.eq(0)

        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += self.i.ready.eq(1)
                with m.If(self.i.valid):
                    m.d.sync += [
                        input_level.eq(self.i.payload.sample),
                        output_first.eq(self.i.payload.first),
                        index.eq(Mux(self.i.payload.first, 0, index + 1)),
                    ]
                    m.next = "READ"
            with m.State("READ"):
                # End the asynchronous distributed-RAM path at a register.
                # The EMA arithmetic then has a full cycle of its own rather
                # than sharing one with RAM lookup and long interconnect.
                m.d.sync += previous_level.eq(mem_r.data)
                m.next = "CALCULATE"
            with m.State("CALCULATE"):
                m.d.sync += [
                    output_level.eq(smoothed[:6]),
                    mem_w.data.eq(smoothed[:6]),
                    mem_w.en.eq(1),
                ]
                m.next = "OUTPUT"
            with m.State("OUTPUT"):
                m.d.comb += [
                    self.o.valid.eq(1),
                    self.o.payload.first.eq(output_first),
                    self.o.payload.sample.eq(output_level),
                ]
                with m.If(self.o.ready):
                    m.next = "IDLE"

        return m


class AnalyzerSampleBuffer(wiring.Component):
    """Absorb analyzer back-pressure without interrupting live audio time.

    SONORO observes a non-blocking tap of the codec stream, so the producer
    cannot hold a sample while the iterative FFT is busy. Buffering the
    already-resampled stream is inexpensive and keeps every analyzer sample
    contiguous through those periodic stalls.
    """

    def __init__(self, shape=ASQ, depth=64):
        self.shape = shape
        self.depth = depth
        super().__init__({
            "i": In(stream.Signature(shape)),
            "o": Out(stream.Signature(shape)),
            "overflow": Out(1),
        })

    def elaborate(self, platform):
        m = Module()
        # SyncFIFO's asynchronous read forces this small memory into
        # distributed RAM rather than consuming one of SONORO's full EBRs.
        m.submodules.fifo = sample_fifo = fifo.SyncFIFO(
            width=self.shape.as_shape().width,
            depth=self.depth,
        )

        m.d.comb += [
            self.i.ready.eq(sample_fifo.w_rdy),
            sample_fifo.w_en.eq(self.i.valid),
            sample_fifo.w_data.eq(self.i.payload.as_value()),
            self.o.valid.eq(sample_fifo.r_rdy),
            self.o.payload.as_value().eq(sample_fifo.r_data),
            sample_fifo.r_en.eq(self.o.valid & self.o.ready),
        ]
        with m.If(self.i.valid & ~self.i.ready):
            m.d.sync += self.overflow.eq(1)

        return m


def _spectrum_log_coord_lut(max_hz, bin_hz, max_bin):
    """Map 256 screen columns to Q8 FFT coordinates on a log axis.

    This is intentionally display-oriented: the analyzer curve should line up
    with the familiar 10/20/50/100/... log grid even though the FFT itself can
    only resolve down to the first real bin. Keeping the fractional bin
    position is important; rounding to an integer bin makes log-axis peaks
    turn into flat rectangular shelves.
    """
    lut = []
    for column in range(256):
        t = column / 255
        hz = 10 * ((max_hz / 10) ** t)
        coord = max(1.0, min(max_bin - (1 / 256), hz / bin_hz))
        lut.append(round(coord * 256))
    return lut


def _spectrum_log_first_bin_column(max_hz, bin_hz, min_bin=1):
    """First visible log column that corresponds to a resolvable FFT bin."""
    span = math.log10(max_hz / 10)
    first_hz = max(10, min_bin * bin_hz)
    return max(0, min(255, math.ceil(
        255 * math.log10(first_hz / 10) / span)))


def _spectrum_bin_log_column_lut(max_hz, bin_hz, max_bin):
    """Map raw FFT bins to their display column on the log frequency axis."""
    span = math.log10(max_hz / 10)
    lut = []
    for bin_index in range(256):
        if bin_index == 0 or bin_index > max_bin:
            lut.append(0)
        else:
            hz = max(10, bin_index * bin_hz)
            lut.append(max(0, min(255, round(
                255 * math.log10(hz / 10) / span))))
    return lut


SPECTRUM_RANGE_ANALYSIS = [
    (24000, 48000 / FFT_SIZE),
    (12000, 24000 / FFT_SIZE),
    (6000, 12000 / FFT_SIZE),
    (3000, 6000 / FFT_SIZE),
]

SPECTRUM_LOG_COORD_LUTS = [
    _spectrum_log_coord_lut(max_hz, bin_hz, 255)
    for max_hz, bin_hz in SPECTRUM_RANGE_ANALYSIS
]

SPECTRUM_LOG_FIRST_BIN_COLUMNS = [
    _spectrum_log_first_bin_column(max_hz, bin_hz)
    for max_hz, bin_hz in SPECTRUM_RANGE_ANALYSIS
]

SPECTRUM_LOG_CURVE_FIRST_BIN_COLUMNS = [
    _spectrum_log_first_bin_column(max_hz, bin_hz, min_bin=2)
    for max_hz, bin_hz in SPECTRUM_RANGE_ANALYSIS
]

SPECTRUM_BIN_LOG_COLUMN_LUTS = [
    _spectrum_bin_log_column_lut(max_hz, bin_hz, 255)
    for max_hz, bin_hz in SPECTRUM_RANGE_ANALYSIS
]


def _spectrum_log_tick_columns(max_hz):
    ticks = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000,
             10000, 20000]
    span = math.log10(max_hz / 10)
    return {
        hz: round(255 * math.log10(hz / 10) / span)
        for hz in ticks
        if hz <= max_hz
    }


SPECTRUM_LOG_TICK_COLUMNS = [
    _spectrum_log_tick_columns(24000),
    _spectrum_log_tick_columns(12000),
    _spectrum_log_tick_columns(6000),
    _spectrum_log_tick_columns(3000),
]

# Compact beam-raced font used for persistent axis labels. Each string is one
# five-pixel row; characters occupy an 8x8 cell to make addressing shift-only.
FONT_5X7 = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "(": ("00100", "01000", "10000", "10000", "10000", "01000", "00100"),
    ")": ("00100", "00010", "00001", "00001", "00001", "00010", "00100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "d": ("00001", "00001", "01111", "10001", "10001", "10011", "01101"),
    "k": ("10000", "10010", "10100", "11000", "10100", "10010", "10001"),
    "s": ("00000", "01111", "10000", "01110", "00001", "11110", "00000"),
    "z": ("00000", "11111", "00010", "00100", "01000", "11111", "00000"),
}


class Spectrogram(wiring.Component):
    """512-point STFT feeding a fixed-left circular waterfall overlay.

    One six-bit magnitude is retained for every positive-frequency bin in
    each of 256 history columns. The newest complete spectrum is displayed at
    the left edge; older spectra extend to the right. The history RAM has one
    write port in the sync domain and one read port in the DVI domain, so no
    framebuffer copies or PSRAM bandwidth are needed to scroll.
    """

    class Flags(csr.Register, access="w"):
        enable: csr.Field(csr.action.W, unsigned(1))
        phosphor: csr.Field(csr.action.W, unsigned(1))
        axes: csr.Field(csr.action.W, unsigned(1))
        input_ch: csr.Field(csr.action.W, unsigned(2))
        spectrum_mode: csr.Field(csr.action.W, unsigned(1))
        freeze: csr.Field(csr.action.W, unsigned(1))

    class Gain(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(4))

    class Range(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(2))

    class Rate(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(2))

    class Persistence(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(2))

    class Hue(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(4))

    class NoiseFloor(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(2))

    class Timings(csr.Register, access="w"):
        h_active: csr.Field(csr.action.W, unsigned(12))
        v_active: csr.Field(csr.action.W, unsigned(12))
        menu_visible: csr.Field(csr.action.W, unsigned(1))
        rotation: csr.Field(csr.action.W, unsigned(2))

    class SpectrumConfig(csr.Register, access="w"):
        style: csr.Field(csr.action.W, unsigned(1))
        bands: csr.Field(csr.action.W, unsigned(2))
        fill: csr.Field(csr.action.W, unsigned(3))
        peaks: csr.Field(csr.action.W, unsigned(3))
        scale: csr.Field(csr.action.W, unsigned(1))
        highlight: csr.Field(csr.action.W, unsigned(1))
        grid: csr.Field(csr.action.W, unsigned(1))

    def __init__(self, *, fs):
        self.fs = fs

        regs = csr.Builder(addr_width=6, data_width=8)
        self._flags = regs.add("flags", self.Flags(), offset=0x00)
        self._gain = regs.add("gain", self.Gain(), offset=0x04)
        self._range = regs.add("range", self.Range(), offset=0x08)
        self._rate = regs.add("rate", self.Rate(), offset=0x0c)
        self._persistence = regs.add("persistence", self.Persistence(), offset=0x10)
        self._hue = regs.add("hue", self.Hue(), offset=0x14)
        self._timings = regs.add("timings", self.Timings(), offset=0x18)
        self._spectrum_config = regs.add(
            "spectrum_config", self.SpectrumConfig(), offset=0x2c)
        self._noise_floor = regs.add(
            "noise_floor", self.NoiseFloor(), offset=0x30)
        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            "audio_i": In(stream.Signature(data.ArrayLayout(ASQ, 4))),
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        enable = Signal(init=1)
        phosphor = Signal(init=1)
        axes = Signal(init=1)
        spectrum_mode = Signal()
        freeze = Signal()
        input_ch = Signal(2)
        gain = Signal(4)
        range_sel = Signal(2)
        rate_sel = Signal(2, init=2)
        persistence = Signal(2, init=2)
        hue = Signal(4, init=5)
        noise_floor = Signal(2)
        spectrum_style = Signal(init=1)
        spectrum_bands = Signal(2, init=1)
        spectrum_fill = Signal(3, init=3)
        spectrum_peaks = Signal(3, init=5)
        spectrum_scale = Signal(init=1)
        spectrum_highlight = Signal()
        spectrum_grid = Signal(init=1)
        spectrum_log_bucket_generation = Signal(4)
        spectrum_log_config_dirty = Signal()
        spectrum_log_clear_active = Signal()
        spectrum_log_clear_addr = Signal(9)
        h_active = Signal(12, init=720)
        v_active = Signal(12, init=720)
        menu_visible = Signal()
        rotation = Signal(2)

        with m.If(self._flags.element.w_stb):
            m.d.sync += [
                enable.eq(self._flags.f.enable.w_data),
                phosphor.eq(self._flags.f.phosphor.w_data),
                axes.eq(self._flags.f.axes.w_data),
                input_ch.eq(self._flags.f.input_ch.w_data),
                spectrum_mode.eq(self._flags.f.spectrum_mode.w_data),
                freeze.eq(self._flags.f.freeze.w_data),
            ]
        with m.If(self._gain.element.w_stb):
            m.d.sync += gain.eq(self._gain.f.value.w_data)
        with m.If(self._range.element.w_stb):
            m.d.sync += range_sel.eq(self._range.f.value.w_data)
            with m.If(self._range.f.value.w_data != range_sel):
                m.d.sync += spectrum_log_config_dirty.eq(1)
        with m.If(self._rate.element.w_stb):
            m.d.sync += rate_sel.eq(self._rate.f.value.w_data)
        with m.If(self._persistence.element.w_stb):
            m.d.sync += persistence.eq(self._persistence.f.value.w_data)
        with m.If(self._hue.element.w_stb):
            m.d.sync += hue.eq(self._hue.f.value.w_data)
        with m.If(self._noise_floor.element.w_stb):
            m.d.sync += noise_floor.eq(self._noise_floor.f.value.w_data)
        with m.If(self._timings.element.w_stb):
            m.d.sync += [
                h_active.eq(self._timings.f.h_active.w_data),
                v_active.eq(self._timings.f.v_active.w_data),
                menu_visible.eq(self._timings.f.menu_visible.w_data),
                rotation.eq(self._timings.f.rotation.w_data),
            ]
        with m.If(self._spectrum_config.element.w_stb):
            m.d.sync += [
                spectrum_style.eq(self._spectrum_config.f.style.w_data),
                spectrum_bands.eq(self._spectrum_config.f.bands.w_data),
                spectrum_fill.eq(self._spectrum_config.f.fill.w_data),
                spectrum_peaks.eq(self._spectrum_config.f.peaks.w_data),
                spectrum_scale.eq(self._spectrum_config.f.scale.w_data),
                spectrum_highlight.eq(
                    self._spectrum_config.f.highlight.w_data),
                spectrum_grid.eq(self._spectrum_config.f.grid.w_data),
            ]
            with m.If((self._spectrum_config.f.bands.w_data !=
                       spectrum_bands) |
                      (self._spectrum_config.f.scale.w_data !=
                       spectrum_scale)):
                m.d.sync += spectrum_log_config_dirty.eq(1)
        # ---- audio analysis -------------------------------------------------
        # Match the analyzer sample rate to the selected frequency range. This
        # keeps all 256 positive-frequency FFT bins useful at every range rather
        # than truncating a higher-rate transform and pretending it has finer
        # low-frequency resolution.
        #
        #   24kHz range: 48kHz analyzer, 93.750Hz/bin
        #   12kHz range: 24kHz analyzer, 46.875Hz/bin
        #    6kHz range: 12kHz analyzer, 23.438Hz/bin
        #    3kHz range:  6kHz analyzer, 11.719Hz/bin
        wide_fs = min(self.fs, 48_000)
        assert self.fs % wide_fs == 0
        wide_downsample = self.fs // wide_fs
        m.submodules.resample_wide = resample_wide = dsp.Resample(
            fs_in=self.fs, n_up=1, m_down=wide_downsample,
            bw=11/24, order_mult=40, round_products=True, shape=ASQ)
        m.submodules.resample_fine = resample_fine = dsp.Resample(
            fs_in=wide_fs, n_up=1, m_down=2,
            bw=11/24, order_mult=40, round_products=True, shape=ASQ)
        m.submodules.resample_mid = resample_mid = dsp.Resample(
            fs_in=wide_fs // 2, n_up=1, m_down=2,
            bw=11/24, order_mult=24, round_products=True, shape=ASQ)
        m.submodules.resample_low = resample_low = dsp.Resample(
            fs_in=wide_fs // 4, n_up=1, m_down=2,
            bw=11/24, order_mult=24, round_products=True, shape=ASQ)
        # Remove converter/input offset before the Hann window can spread it
        # into FFT bin 1. At 192kHz, the quantized 0.9999 pole has a corner
        # near 3Hz: low enough to preserve the analyzer's 10Hz lower edge,
        # while preventing a stationary zero-volt input from appearing at a
        # different frequency whenever the analysis range changes.
        m.submodules.dc_block = dc_block = dsp.filters.DCBlock(
            pole=0.9999, sq=ASQ)
        m.submodules.analyzer = analyzer = dsp.fft.STFTAnalyzer(
            shape=ASQ, sz=FFT_SIZE)
        m.submodules.envelope = envelope = dsp.spectral.SpectralEnvelope(
            shape=ASQ, sz=FFT_SIZE, smooth=False)
        m.submodules.dbfs = dbfs = MagnitudeToDbfs(ASQ)
        m.submodules.level_smoother = level_smoother = DbfsLevelSmoother(
            FFT_SIZE)
        m.submodules.sample_buffer = sample_buffer = AnalyzerSampleBuffer(
            shape=ASQ, depth=64)

        # A short calibrated-level average calms ADC/numerical shimmer without
        # the two EBRs required by the full-precision magnitude smoother. The
        # shifts compensate for analyzer frame rate; attack is always at least
        # twice as quick as release.
        with m.Switch(range_sel):
            with m.Case(0):
                m.d.comb += [
                    level_smoother.attack_shift.eq(1),
                    level_smoother.release_shift.eq(2),
                ]
            with m.Case(1):
                m.d.comb += [
                    level_smoother.attack_shift.eq(0),
                    level_smoother.release_shift.eq(1),
                ]
            with m.Case(2):
                m.d.comb += [
                    level_smoother.attack_shift.eq(0),
                    level_smoother.release_shift.eq(1),
                ]
            with m.Default():
                m.d.comb += [
                    level_smoother.attack_shift.eq(0),
                    level_smoother.release_shift.eq(0),
                ]

        selected_sample = Signal(ASQ)
        use_wide = Signal()
        use_fine = Signal()
        use_mid = Signal()
        use_low = Signal()
        range_decimated = Signal()
        source_valid = Signal()
        source_ready = Signal()
        with m.Switch(input_ch):
            for ch in range(4):
                with m.Case(ch):
                    m.d.comb += selected_sample.eq(self.audio_i.payload[ch])

        # Diagnostic-only, elaboration-time source selection. The internal
        # oscillator exercises the complete resampler/FFT/display path while
        # bypassing the external source, cable, analog front end, and ADC.
        # 1.5kHz is bin-centred in both the 48kHz and 12kHz analyzer streams;
        # its quantized oscillator coefficient is within 0.6Hz of nominal.
        if os.environ.get("TILIQUA_SONORO_TEST_TONE", "0") == "1":
            m.submodules.test_tone = test_tone = dsp.DWO(
                sq=ASQ,
                c=math.cos(2 * math.pi * 1500.0 / self.fs),
            )
            m.d.comb += [
                selected_sample.eq(test_tone.o.payload),
                source_valid.eq(self.audio_i.valid & test_tone.o.valid),
                source_ready.eq(dc_block.i.ready & test_tone.o.valid),
                test_tone.o.ready.eq(
                    self.audio_i.valid & dc_block.i.ready),
            ]
        else:
            m.d.comb += [
                source_valid.eq(self.audio_i.valid),
                source_ready.eq(dc_block.i.ready),
            ]
        m.d.comb += [
            use_wide.eq(range_sel == 0),
            use_fine.eq(range_sel == 1),
            use_mid.eq(range_sel == 2),
            use_low.eq(range_sel == 3),
            range_decimated.eq(range_sel != 0),
            dc_block.i.valid.eq(source_valid),
            dc_block.i.payload.eq(selected_sample),
            self.audio_i.ready.eq(source_ready),
            resample_wide.i.valid.eq(dc_block.o.valid),
            resample_wide.i.payload.eq(dc_block.o.payload),
            dc_block.o.ready.eq(resample_wide.i.ready),

            resample_fine.i.valid.eq(resample_wide.o.valid & ~use_wide),
            resample_fine.i.payload.eq(resample_wide.o.payload),
            resample_wide.o.ready.eq(Mux(
                use_wide, sample_buffer.i.ready, resample_fine.i.ready)),

            resample_mid.i.valid.eq(
                resample_fine.o.valid & (use_mid | use_low)),
            resample_mid.i.payload.eq(resample_fine.o.payload),
            resample_fine.o.ready.eq(Mux(
                use_fine, sample_buffer.i.ready, resample_mid.i.ready)),

            resample_low.i.valid.eq(resample_mid.o.valid & use_low),
            resample_low.i.payload.eq(resample_mid.o.payload),
            resample_mid.o.ready.eq(Mux(
                use_mid, sample_buffer.i.ready, resample_low.i.ready)),
            resample_low.o.ready.eq(sample_buffer.i.ready),

            sample_buffer.i.valid.eq(Mux(
                use_wide, resample_wide.o.valid,
                Mux(use_fine, resample_fine.o.valid,
                    Mux(use_mid, resample_mid.o.valid,
                        resample_low.o.valid)),
            )),
            sample_buffer.i.payload.eq(Mux(
                use_wide, resample_wide.o.payload,
                Mux(use_fine, resample_fine.o.payload,
                    Mux(use_mid, resample_mid.o.payload,
                        resample_low.o.payload)),
            )),
            analyzer.i.valid.eq(sample_buffer.o.valid),
            analyzer.i.payload.eq(sample_buffer.o.payload),
            sample_buffer.o.ready.eq(analyzer.i.ready),
        ]
        wiring.connect(m, analyzer.o, envelope.i)
        wiring.connect(m, envelope.o, dbfs.i)
        wiring.connect(m, dbfs.o, level_smoother.i)

        history = memory.Memory(
            data=memory.MemoryData(
                # Six stored bits provide four sub-levels for every palette
                # intensity. A spatial dither in the video domain turns those
                # into a much smoother perceived gradient without the 32
                # block RAMs an eight-bit history would require.
                shape=unsigned(6),
                depth=HISTORY_COLS * N_BINS,
                init=[0] * (HISTORY_COLS * N_BINS),
            )
        )
        m.submodules.history = history
        history_w = history.write_port(domain="sync")
        history_r = history.read_port(domain="dvi")

        # Spectrum mode uses a compact, independently prepared band table.
        # Pooling happens once as FFT bins arrive, so the video path still
        # needs only one lookup per pixel regardless of the selected count.
        spectrum_levels = memory.Memory(
            data=memory.MemoryData(
                # Level and focus are always written and read together. Keep
                # them in one word so they consume one block RAM rather than
                # two independently under-filled blocks.
                shape=unsigned(10), depth=2 * N_BINS,
                init=[0] * (2 * N_BINS),
            )
        )
        m.submodules.spectrum_levels = spectrum_levels
        spectrum_levels_w = spectrum_levels.write_port(domain="sync")
        spectrum_levels_r = spectrum_levels.read_port(domain="dvi")

        # Log-scale bars need a display-column representation, not repeated
        # raw FFT-bin samples. Each accepted analyzer frame writes the peak
        # bin level for every log column that received one or more FFT bins.
        # A generation tag makes untouched columns read as empty after the
        # bucket layout changes. Unlike a per-frame epoch, the tag only
        # changes when an address can mean something different (bands/range).
        spectrum_log_levels = memory.Memory(
            data=memory.MemoryData(
                # {level, generation, focus}; these fields share an address
                # and lifetime, so a single 14-bit word is sufficient.
                shape=unsigned(14), depth=2 * HISTORY_COLS,
                init=[0] * (2 * HISTORY_COLS),
            )
        )
        m.submodules.spectrum_log_levels = spectrum_log_levels
        spectrum_log_levels_w = spectrum_log_levels.write_port(domain="sync")
        spectrum_log_levels_r = spectrum_log_levels.read_port(domain="dvi")

        # The reverse log mapping is used in the analyzer clock domain. A
        # single range-major block ROM replaces four parallel distributed
        # lookup tables and their wide selection network.
        spectrum_bin_log_columns = memory.Memory(
            data=memory.MemoryData(
                shape=unsigned(8), depth=4 * N_BINS,
                init=[column
                      for lut in SPECTRUM_BIN_LOG_COLUMN_LUTS
                      for column in lut],
            )
        )
        m.submodules.spectrum_bin_log_columns = spectrum_bin_log_columns
        spectrum_bin_log_r = spectrum_bin_log_columns.read_port(domain="sync")

        # Peak level, five-bit hold timer, and one session epoch bit. This
        # memory lives entirely in the video domain; the epoch invalidates all
        # old peaks instantly whenever spectrum mode is entered again.
        spectrum_peak_state = memory.Memory(
            data=memory.MemoryData(
                shape=unsigned(12), depth=N_BINS,
                init=[0] * N_BINS,
            )
        )
        m.submodules.spectrum_peak_state = spectrum_peak_state
        spectrum_peak_r = spectrum_peak_state.read_port(domain="dvi")
        spectrum_peak_w = spectrum_peak_state.write_port(domain="dvi")

        write_col = Signal(8)
        newest_col = Signal(8)
        bin_index = Signal(9)
        frame_seq = Signal(6)
        freeze_active = Signal()
        accept_latched = Signal()
        spectrum_publish_bank = Signal()
        spectrum_display_ack_sync = Signal()
        spectrum_bank_ready = Signal()
        spectrum_write_bank = Signal()
        spectrum_frame_write = Signal()
        m.d.comb += [
            spectrum_bank_ready.eq(
                spectrum_publish_bank == spectrum_display_ack_sync),
            spectrum_write_bank.eq(~spectrum_publish_bank),
        ]

        accept_rate = Signal()
        spectrum_accept_rate = Signal()
        accept_now = Signal()
        with m.Switch(rate_sel):
            with m.Case(0):
                m.d.comb += accept_rate.eq(
                    Mux(range_decimated, 1, frame_seq[0] == 0))
            with m.Case(1):
                m.d.comb += accept_rate.eq(Mux(
                    range_decimated,
                    frame_seq[0] == 0,
                    frame_seq[:2] == 0,
                ))
            with m.Case(2):
                m.d.comb += accept_rate.eq(Mux(
                    range_decimated,
                    frame_seq[:2] == 0,
                    frame_seq[:3] == 0,
                ))
            with m.Default():
                m.d.comb += accept_rate.eq(Mux(
                    range_decimated,
                    frame_seq[:3] == 0,
                    frame_seq[:4] == 0,
                ))
        with m.Switch(rate_sel):
            with m.Case(0):
                m.d.comb += spectrum_accept_rate.eq(1)
            with m.Case(1):
                m.d.comb += spectrum_accept_rate.eq(frame_seq[:2] == 0)
            with m.Case(2):
                m.d.comb += spectrum_accept_rate.eq(frame_seq[:4] == 0)
            with m.Default():
                m.d.comb += spectrum_accept_rate.eq(frame_seq[:5] == 0)
        m.d.comb += accept_now.eq(Mux(
            freeze,
            0,
            Mux(
                spectrum_mode,
                spectrum_accept_rate & spectrum_bank_ready &
                ~spectrum_log_clear_active,
                accept_rate,
            )))

        current_bin = Signal(9)
        do_write = Signal()
        m.d.comb += spectrum_frame_write.eq(do_write & spectrum_mode)
        raw_level = Signal(6)
        boosted_level = Signal(8)
        stored_level = Signal(6)
        spectrum_desired_group_shift = Signal(2)
        spectrum_group_shift = Signal(2)
        spectrum_active_bin_last = Signal(8)
        spectrum_group_first = Signal()
        spectrum_group_last = Signal()
        spectrum_group_peak = Signal(6)
        spectrum_group_peak_next = Signal(6)
        spectrum_band_index_sync = Signal(8)
        spectrum_log_bucket_shift = Signal(2)
        spectrum_log_bucket_addr_sync = Signal(8)
        spectrum_log_sample_valid = Signal()
        spectrum_log_lookup_valid = Signal()
        spectrum_log_lookup_level = Signal(6)
        spectrum_log_lookup_focus = Signal(4)
        spectrum_log_lookup_bucket_shift = Signal(2)
        spectrum_log_stage_level = Signal(6)
        spectrum_log_stage_focus = Signal(4)
        spectrum_log_column_prev = Signal(8)
        spectrum_log_column_changed = Signal()
        spectrum_log_bucket_peak = Signal(6)
        spectrum_log_bucket_peak_next = Signal(6)
        spectrum_log_bucket_focus = Signal(4)
        spectrum_log_bucket_focus_next = Signal(4)
        spectrum_log_bucket_valid = Signal()
        spectrum_log_bucket_flush = Signal()
        spectrum_peak_candidate_bin = Signal(8)
        spectrum_peak_candidate_level = Signal(6)
        spectrum_low_candidate_bin = Signal(8)
        spectrum_low_candidate_level = Signal(6)
        spectrum_low_candidate_valid = Signal()
        spectrum_low_candidate_score = Signal(7)
        spectrum_prev_bin = Signal(8)
        spectrum_prev_level = Signal(6)
        spectrum_prev_prev_level = Signal(6)
        spectrum_prev_is_peak = Signal()
        spectrum_selected_candidate_bin = Signal(8)
        spectrum_selected_candidate_level = Signal(6)
        spectrum_candidate_valid = Signal()
        spectrum_fundamental_bin = Signal(8)
        spectrum_fundamental_level = Signal(6)
        spectrum_fundamental_misses = Signal(3)
        spectrum_fundamental_next = Signal(8)
        spectrum_fundamental_level_next = Signal(6)
        spectrum_fundamental_misses_next = Signal(3)
        spectrum_fundamental_lock_lo = Signal(8)
        spectrum_fundamental_lock_hi = Signal(8)
        spectrum_fundamental_close = Signal()
        spectrum_fundamental_seen = Signal()
        spectrum_fundamental_seen_level = Signal(6)
        spectrum_fundamental_seen_peak = Signal()
        spectrum_fundamental_switch_level = Signal(7)
        spectrum_fundamental_switch = Signal()
        spectrum_focus_level_sync = Signal(4)
        spectrum_focus_exact_sync = Signal()
        spectrum_focus_near_sync = Signal()
        spectrum_focus_found_bin = Signal(8)
        spectrum_focus_update_pending = Signal()
        spectrum_focus_centers = [
            Signal(8, name=f"spectrum_focus_{harmonic}_center")
            for harmonic in range(1, 6)
        ]
        spectrum_focus_valids = [
            Signal(name=f"spectrum_focus_{harmonic}_valid")
            for harmonic in range(1, 6)
        ]
        spectrum_focus_lo1 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_lo1")
            for harmonic in range(1, 6)
        ]
        spectrum_focus_hi1 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_hi1")
            for harmonic in range(1, 6)
        ]
        spectrum_focus_center_calc = [
            Signal(12, name=f"spectrum_focus_{harmonic}_center_calc")
            for harmonic in range(1, 6)
        ]
        with m.If(spectrum_log_config_dirty):
            m.d.sync += [
                spectrum_log_bucket_generation.eq(
                    spectrum_log_bucket_generation + 1),
                spectrum_log_config_dirty.eq(0),
                spectrum_log_clear_active.eq(1),
                spectrum_log_clear_addr.eq(0),
                spectrum_log_bucket_valid.eq(0),
                spectrum_log_column_prev.eq(0),
                spectrum_log_bucket_peak.eq(0),
                spectrum_log_bucket_focus.eq(0),
            ]
        with m.Elif(spectrum_log_clear_active):
            with m.If(spectrum_log_clear_addr == 511):
                m.d.sync += spectrum_log_clear_active.eq(0)
            with m.Else():
                m.d.sync += spectrum_log_clear_addr.eq(
                    spectrum_log_clear_addr + 1)
        m.d.comb += [
            spectrum_low_candidate_score.eq(
                spectrum_low_candidate_level + 8),
            spectrum_selected_candidate_bin.eq(Mux(
                spectrum_low_candidate_valid &
                (spectrum_low_candidate_score >=
                 spectrum_peak_candidate_level),
                spectrum_low_candidate_bin,
                spectrum_peak_candidate_bin)),
            spectrum_selected_candidate_level.eq(Mux(
                spectrum_low_candidate_valid &
                (spectrum_low_candidate_score >=
                 spectrum_peak_candidate_level),
                spectrum_low_candidate_level,
                spectrum_peak_candidate_level)),
            spectrum_candidate_valid.eq(spectrum_selected_candidate_level >= 8),
            spectrum_focus_found_bin.eq(Mux(
                spectrum_candidate_valid,
                spectrum_selected_candidate_bin,
                0)),
            spectrum_fundamental_lock_lo.eq(Mux(
                spectrum_fundamental_bin > 2,
                spectrum_fundamental_bin - 2,
                0)),
            spectrum_fundamental_lock_hi.eq(Mux(
                spectrum_fundamental_bin < 253,
                spectrum_fundamental_bin + 2,
                255)),
            spectrum_fundamental_close.eq(
                spectrum_candidate_valid &
                (spectrum_fundamental_bin != 0) &
                (spectrum_selected_candidate_bin >=
                 spectrum_fundamental_lock_lo) &
                (spectrum_selected_candidate_bin <=
                 spectrum_fundamental_lock_hi)),
            spectrum_fundamental_seen_peak.eq(
                spectrum_prev_is_peak &
                (spectrum_fundamental_bin != 0) &
                (spectrum_prev_bin >= spectrum_fundamental_lock_lo) &
                (spectrum_prev_bin <= spectrum_fundamental_lock_hi)),
            spectrum_fundamental_switch_level.eq(
                spectrum_fundamental_level + 10),
            spectrum_fundamental_switch.eq(
                spectrum_candidate_valid &
                ((spectrum_fundamental_bin == 0) |
                 (~spectrum_fundamental_seen &
                  (spectrum_selected_candidate_level >=
                   spectrum_fundamental_switch_level)) |
                 (~spectrum_fundamental_seen &
                  (spectrum_fundamental_misses >= 3)))),
            spectrum_fundamental_next.eq(Mux(
                spectrum_fundamental_switch,
                spectrum_selected_candidate_bin,
                spectrum_fundamental_bin)),
            spectrum_fundamental_level_next.eq(Mux(
                spectrum_fundamental_switch,
                spectrum_selected_candidate_level,
                Mux(spectrum_fundamental_seen,
                    spectrum_fundamental_seen_level,
                    spectrum_fundamental_level))),
            spectrum_fundamental_misses_next.eq(Mux(
                spectrum_fundamental_switch |
                spectrum_fundamental_seen |
                spectrum_fundamental_close,
                0,
                Mux(spectrum_fundamental_misses == 7,
                    7,
                    spectrum_fundamental_misses + 1))),
        ]
        exact_hits = []
        near_hits = []
        for harmonic in range(1, 6):
            index = harmonic - 1
            valid = spectrum_focus_valids[index]
            center_calc = spectrum_focus_center_calc[index]
            m.d.comb += center_calc.eq(
                spectrum_fundamental_bin * harmonic)
            exact_hits.append(
                valid & (current_bin[:8] == spectrum_focus_centers[index]))
            near_hits.append(
                valid &
                (current_bin[:8] >= spectrum_focus_lo1[index]) &
                (current_bin[:8] <= spectrum_focus_hi1[index]))
        m.d.comb += [
            spectrum_focus_exact_sync.eq(Cat(*exact_hits).any()),
            spectrum_focus_near_sync.eq(Cat(*near_hits).any()),
            spectrum_focus_level_sync.eq(Mux(
                spectrum_focus_exact_sync,
                15,
                Mux(spectrum_focus_near_sync, 9, 0))),
        ]
        m.d.comb += [
            spectrum_log_bucket_shift.eq(3 - spectrum_bands),
            spectrum_bin_log_r.addr.eq(Cat(current_bin[:8], range_sel)),
            # SpectralEnvelope emits the complete 512-bin complex spectrum.
            # Only bins 0..255 are positive frequencies.  Never feed the
            # mirrored upper half into the log-display pipeline: truncating
            # those bin numbers to the ROM's eight-bit address otherwise
            # folds a real tone onto a false high-frequency display column.
            spectrum_log_sample_valid.eq(
                level_smoother.o.valid & (current_bin < N_BINS)),
        ]
        m.submodules.spectrum_log_handoff = spectrum_log_handoff = \
            SpectrumLogFrameHandoff()
        m.d.comb += [
            spectrum_log_handoff.i_valid.eq(spectrum_log_sample_valid),
            spectrum_log_handoff.i_first.eq(
                level_smoother.o.payload.first),
            spectrum_log_handoff.i_write.eq(do_write),
            spectrum_log_handoff.i_frame_write.eq(spectrum_frame_write),
            spectrum_log_handoff.i_bin.eq(current_bin),
            spectrum_log_handoff.i_bank.eq(spectrum_write_bank),
        ]
        # Analyzer outputs are many clocks apart. Capture a request while the
        # block ROM reads its range/bin address, then reduce the resulting log
        # column on the following cycle.
        m.d.sync += [
            spectrum_log_lookup_valid.eq(spectrum_log_sample_valid),
        ]
        with m.If(spectrum_log_sample_valid):
            m.d.sync += [
                spectrum_log_lookup_level.eq(stored_level),
                spectrum_log_lookup_focus.eq(spectrum_focus_level_sync),
                spectrum_log_lookup_bucket_shift.eq(
                    spectrum_log_bucket_shift),
            ]
        with m.If(spectrum_log_lookup_valid):
            m.d.sync += [
                spectrum_log_stage_level.eq(spectrum_log_lookup_level),
                spectrum_log_stage_focus.eq(spectrum_log_lookup_focus),
                spectrum_log_bucket_addr_sync.eq(
                    spectrum_bin_log_r.data >>
                    spectrum_log_lookup_bucket_shift),
            ]
        m.d.comb += [
            level_smoother.o.ready.eq(1),
            current_bin.eq(Mux(level_smoother.o.payload.first, 0, bin_index)),
            do_write.eq(Mux(level_smoother.o.payload.first,
                            accept_now, accept_latched)),
            raw_level.eq(level_smoother.o.payload.sample),
            boosted_level.eq(raw_level + gain),
            # Bin 0 is DC, not musical frequency content. Leaving it in the
            # raw linear/history paths lets input offset dominate the left
            # edge of spectrum mode and the floor of the spectrogram,
            # while the log analyzer path already starts at the first real
            # bin. Suppress it once here so every view agrees.
            stored_level.eq(Mux(
                current_bin == 0,
                0,
                Mux(boosted_level > 63, 63, boosted_level[:6]))),
            spectrum_desired_group_shift.eq(3 - spectrum_bands),
            spectrum_group_shift.eq(Mux(
                spectrum_style | spectrum_scale,
                0,
                spectrum_desired_group_shift)),
            spectrum_active_bin_last.eq(255),
            spectrum_band_index_sync.eq(
                current_bin[:8] >> spectrum_group_shift),
            spectrum_group_peak_next.eq(Mux(
                spectrum_group_first,
                stored_level,
                Mux(stored_level > spectrum_group_peak,
                    stored_level, spectrum_group_peak),
            )),
            spectrum_log_column_changed.eq(
                spectrum_log_bucket_valid &
                (spectrum_log_bucket_addr_sync != spectrum_log_column_prev)),
            spectrum_log_bucket_peak_next.eq(Mux(
                ~spectrum_log_bucket_valid | spectrum_log_column_changed,
                spectrum_log_stage_level,
                Mux(spectrum_log_stage_level > spectrum_log_bucket_peak,
                    spectrum_log_stage_level, spectrum_log_bucket_peak),
            )),
            spectrum_log_bucket_focus_next.eq(Mux(
                ~spectrum_log_bucket_valid | spectrum_log_column_changed,
                spectrum_log_stage_focus,
                Mux(spectrum_log_stage_focus > spectrum_log_bucket_focus,
                    spectrum_log_stage_focus,
                    spectrum_log_bucket_focus),
            )),
            spectrum_log_bucket_flush.eq(
                spectrum_log_handoff.o_valid &
                ~spectrum_log_handoff.o_first &
                spectrum_log_bucket_valid &
                (spectrum_log_column_changed |
                 (spectrum_log_handoff.o_bin == spectrum_active_bin_last))),
            spectrum_prev_is_peak.eq(
                (spectrum_prev_bin >= 2) &
                (spectrum_prev_bin <= spectrum_active_bin_last) &
                (spectrum_prev_level >= 10) &
                (spectrum_prev_level >= spectrum_prev_prev_level) &
                (spectrum_prev_level >= stored_level)),
            history_w.en.eq(
                level_smoother.o.valid & do_write & (current_bin < N_BINS)),
            history_w.addr.eq((write_col << 8) | current_bin[:8]),
            history_w.data.eq(stored_level),
            spectrum_levels_w.en.eq(
                level_smoother.o.valid &
                spectrum_frame_write &
                (current_bin <= spectrum_active_bin_last) &
                spectrum_group_last),
            spectrum_levels_w.addr.eq(
                Cat(spectrum_band_index_sync, spectrum_write_bank)),
            spectrum_levels_w.data.eq(
                Cat(spectrum_group_peak_next,
                    spectrum_focus_level_sync)),
            spectrum_log_levels_w.en.eq(
                spectrum_log_clear_active |
                (spectrum_log_handoff.o_frame_write &
                 spectrum_log_bucket_flush &
                 ~spectrum_log_clear_active)),
            spectrum_log_levels_w.addr.eq(Mux(
                spectrum_log_clear_active,
                spectrum_log_clear_addr,
                Cat(spectrum_log_column_prev, spectrum_log_handoff.o_bank))),
            spectrum_log_levels_w.data.eq(Mux(
                spectrum_log_clear_active,
                0,
                Cat(Mux(spectrum_log_column_changed,
                        spectrum_log_bucket_peak,
                        spectrum_log_bucket_peak_next),
                    spectrum_log_bucket_generation,
                    Mux(spectrum_log_column_changed,
                        spectrum_log_bucket_focus,
                        spectrum_log_bucket_focus_next)))),
        ]
        with m.Switch(spectrum_group_shift):
            with m.Case(0):
                m.d.comb += [
                    spectrum_group_first.eq(1),
                    spectrum_group_last.eq(1),
                ]
            with m.Case(1):
                m.d.comb += [
                    spectrum_group_first.eq(current_bin[0] == 0),
                    spectrum_group_last.eq(current_bin[0] == 1),
                ]
            with m.Case(2):
                m.d.comb += [
                    spectrum_group_first.eq(current_bin[:2] == 0),
                    spectrum_group_last.eq(current_bin[:2] == 3),
                ]
            with m.Default():
                m.d.comb += [
                    spectrum_group_first.eq(current_bin[:3] == 0),
                    spectrum_group_last.eq(current_bin[:3] == 7),
                ]

        # Fundamental selection has a relatively long comparison path. Update
        # the small harmonic table one clock after latching the new anchor;
        # analyzer bins are several clocks apart, so the table is ready before
        # bin one arrives while removing that path from the table registers.
        with m.If(spectrum_focus_update_pending):
            m.d.sync += spectrum_focus_update_pending.eq(0)
            for harmonic in range(1, 6):
                index = harmonic - 1
                center_calc = spectrum_focus_center_calc[index]
                m.d.sync += [
                    spectrum_focus_centers[index].eq(center_calc[:8]),
                    spectrum_focus_valids[index].eq(
                        (spectrum_fundamental_bin != 0) &
                        (center_calc <= spectrum_active_bin_last)),
                    spectrum_focus_lo1[index].eq(Mux(
                        center_calc > 1, center_calc - 1, 0)),
                    spectrum_focus_hi1[index].eq(Mux(
                        center_calc + 1 > spectrum_active_bin_last,
                        spectrum_active_bin_last,
                        center_calc + 1)),
                ]

        with m.If(level_smoother.o.valid):
            with m.If(level_smoother.o.payload.first):
                # Spectrum display writes are frame-rate limited so slower
                # rates update coherently. Keep the fundamental/harmonic
                # detector on the same accepted-frame cadence: if a skipped
                # analyzer frame can reset the peak candidate, hi-lite loses
                # its detected fundamental before the next visible frame.
                with m.If(accept_now):
                    m.d.sync += [
                        spectrum_fundamental_bin.eq(
                            spectrum_fundamental_next),
                        spectrum_fundamental_level.eq(
                            spectrum_fundamental_level_next),
                        spectrum_fundamental_misses.eq(
                            spectrum_fundamental_misses_next),
                        spectrum_peak_candidate_bin.eq(0),
                        spectrum_peak_candidate_level.eq(0),
                        spectrum_low_candidate_bin.eq(0),
                        spectrum_low_candidate_level.eq(0),
                        spectrum_low_candidate_valid.eq(0),
                        spectrum_fundamental_seen.eq(0),
                        spectrum_fundamental_seen_level.eq(0),
                        spectrum_prev_bin.eq(0),
                        spectrum_prev_level.eq(stored_level),
                        spectrum_prev_prev_level.eq(0),
                        spectrum_focus_update_pending.eq(1),
                    ]
            with m.Elif(do_write &
                        (current_bin <= spectrum_active_bin_last)):
                # Track local maxima to choose a plausible fundamental anchor.
                # The highlight table itself is rendered from harmonics 1..5
                # of that anchor so all harmonic slots remain visible instead
                # of blinking as individual bins jitter around.
                with m.If(spectrum_prev_is_peak):
                    with m.If(spectrum_prev_level >
                              spectrum_peak_candidate_level):
                        m.d.sync += [
                            spectrum_peak_candidate_bin.eq(
                                spectrum_prev_bin),
                            spectrum_peak_candidate_level.eq(
                                spectrum_prev_level),
                        ]
                    with m.If(~spectrum_low_candidate_valid):
                        m.d.sync += [
                            spectrum_low_candidate_bin.eq(spectrum_prev_bin),
                            spectrum_low_candidate_level.eq(
                                spectrum_prev_level),
                            spectrum_low_candidate_valid.eq(1),
                        ]
                    with m.If(spectrum_fundamental_seen_peak):
                        m.d.sync += [
                            spectrum_fundamental_seen.eq(1),
                            spectrum_fundamental_seen_level.eq(Mux(
                                spectrum_prev_level >
                                spectrum_fundamental_seen_level,
                                spectrum_prev_level,
                                spectrum_fundamental_seen_level)),
                        ]
                m.d.sync += [
                    spectrum_prev_prev_level.eq(spectrum_prev_level),
                    spectrum_prev_level.eq(stored_level),
                    spectrum_prev_bin.eq(current_bin[:8]),
                ]
            with m.If(current_bin <= spectrum_active_bin_last):
                m.d.sync += spectrum_group_peak.eq(
                    spectrum_group_peak_next)
            with m.If(level_smoother.o.payload.first):
                m.d.sync += [
                    bin_index.eq(1),
                    frame_seq.eq(frame_seq + 1),
                    # Change frozen state only at an analyzer-frame boundary.
                    # The previous frame has already completed and published,
                    # so the history, spectrum bank, and peak markers stop on
                    # the same coherent capture.
                    freeze_active.eq(freeze),
                    accept_latched.eq(accept_now),
                ]
            with m.Else():
                m.d.sync += bin_index.eq(bin_index + 1)

            with m.If(do_write & (current_bin == N_BINS - 1)):
                m.d.sync += [
                    newest_col.eq(write_col),
                    write_col.eq(write_col - 1),
                ]
        # Complete the staged log-bucket reduction independently of the
        # linear/history paths. A frame marker resets the reducer; subsequent
        # accepted bins update it and may flush the preceding bucket.
        with m.If(spectrum_log_handoff.o_valid &
                  ~spectrum_log_config_dirty):
            with m.If(spectrum_log_handoff.o_first):
                m.d.sync += [
                    spectrum_log_bucket_valid.eq(0),
                    spectrum_log_column_prev.eq(0),
                    spectrum_log_bucket_peak.eq(0),
                    spectrum_log_bucket_focus.eq(0),
                ]
            with m.Elif(spectrum_log_handoff.o_write &
                        (spectrum_log_handoff.o_bin <=
                         spectrum_active_bin_last)):
                m.d.sync += [
                    spectrum_log_column_prev.eq(
                        spectrum_log_bucket_addr_sync),
                    spectrum_log_bucket_peak.eq(
                        spectrum_log_bucket_peak_next),
                    spectrum_log_bucket_focus.eq(
                        spectrum_log_bucket_focus_next),
                    spectrum_log_bucket_valid.eq(1),
                ]
            # The reverse-log ROM adds two clocks after the analyzer output.
            # Publish only after the final delayed bucket is written, using
            # the bank captured with that sample. Publishing at raw bin 255
            # flipped spectrum_write_bank too early and sent the tail of each
            # frame into the bank being displayed, causing torn columns and
            # stale full-height peaks at the right edge.
            with m.If(spectrum_log_handoff.o_publish &
                      ~spectrum_log_clear_active):
                m.d.sync += spectrum_publish_bank.eq(
                    spectrum_log_handoff.o_bank)

        # ---- DVI-domain circular history projection ------------------------
        enable_dvi = Signal()
        phosphor_dvi = Signal()
        axes_dvi = Signal()
        spectrum_mode_dvi = Signal()
        freeze_active_dvi = Signal()
        spectrum_style_dvi = Signal()
        spectrum_bands_dvi = Signal(2)
        spectrum_fill_dvi = Signal(3)
        spectrum_peaks_dvi = Signal(3)
        spectrum_scale_dvi = Signal()
        spectrum_highlight_dvi = Signal()
        spectrum_grid_dvi = Signal()
        spectrum_log_bucket_generation_dvi = Signal(4)
        range_dvi = Signal(2)
        rate_dvi = Signal(2)
        persistence_dvi = Signal(2)
        hue_dvi = Signal(4)
        noise_floor_dvi = Signal(2)
        h_active_dvi = Signal(12)
        v_active_dvi = Signal(12)
        menu_visible_dvi = Signal()
        rotation_dvi = Signal(2)
        spectrum_publish_bank_meta = Signal()
        spectrum_display_bank_dvi = Signal()
        spectrum_display_ack_dvi = Signal()
        newest_gray = Signal(8)
        newest_gray_meta = Signal(8)
        newest_binary_meta = Signal(8)
        m.d.comb += newest_gray.eq(newest_col ^ (newest_col >> 1))
        for name, src, dst in [
            ("enable", enable, enable_dvi),
            ("phosphor", phosphor, phosphor_dvi),
            ("axes", axes, axes_dvi),
            ("spectrum_mode", spectrum_mode, spectrum_mode_dvi),
            ("freeze_active", freeze_active, freeze_active_dvi),
            ("spectrum_style", spectrum_style, spectrum_style_dvi),
            ("spectrum_bands", spectrum_bands, spectrum_bands_dvi),
            ("spectrum_fill", spectrum_fill, spectrum_fill_dvi),
            ("spectrum_peaks", spectrum_peaks, spectrum_peaks_dvi),
            ("spectrum_scale", spectrum_scale, spectrum_scale_dvi),
            ("spectrum_highlight", spectrum_highlight,
             spectrum_highlight_dvi),
            ("spectrum_grid", spectrum_grid, spectrum_grid_dvi),
            ("spectrum_log_bucket_generation", spectrum_log_bucket_generation,
             spectrum_log_bucket_generation_dvi),
            ("range", range_sel, range_dvi),
            ("rate", rate_sel, rate_dvi),
            ("persistence", persistence, persistence_dvi),
            ("h_active", h_active, h_active_dvi),
            ("v_active", v_active, v_active_dvi),
            ("menu_visible", menu_visible, menu_visible_dvi),
            ("rotation", rotation, rotation_dvi),
            ("newest_gray", newest_gray, newest_gray_meta),
            ("hue", hue, hue_dvi),
            ("noise_floor", noise_floor, noise_floor_dvi),
        ]:
            setattr(m.submodules, f"{name}_ff", FFSynchronizer(src, dst, o_domain="dvi"))

        # Display-only floor. Six-bit levels span -96..0 dBFS, so the three
        # thresholds are approximately levels 16, 20 and 24. Ease the first
        # four levels (~6 dB) above the threshold in from the baseline; above
        # that knee the calibrated amplitude is passed through unchanged.
        noise_floor_threshold_dvi = Signal(6)
        with m.Switch(noise_floor_dvi):
            with m.Case(1):
                m.d.comb += noise_floor_threshold_dvi.eq(16)  # -72 dBFS
            with m.Case(2):
                m.d.comb += noise_floor_threshold_dvi.eq(20)  # -66 dBFS
            with m.Case(3):
                m.d.comb += noise_floor_threshold_dvi.eq(24)  # -60 dBFS
            with m.Default():
                m.d.comb += noise_floor_threshold_dvi.eq(0)

        def apply_display_floor(level):
            return Mux(
                noise_floor_dvi == 0,
                level,
                Mux(
                    level <= noise_floor_threshold_dvi,
                    0,
                    Mux(
                        level >= noise_floor_threshold_dvi + 4,
                        level,
                        Mux(
                            level == noise_floor_threshold_dvi + 1,
                            level >> 2,
                            Mux(
                                level == noise_floor_threshold_dvi + 2,
                                level >> 1,
                                level - (level >> 2),
                            ),
                        ),
                    ),
                ),
            )
        m.submodules.spectrum_publish_bank_ff = FFSynchronizer(
            spectrum_publish_bank, spectrum_publish_bank_meta,
            o_domain="dvi")
        m.submodules.spectrum_display_ack_ff = FFSynchronizer(
            spectrum_display_ack_dvi, spectrum_display_ack_sync,
            o_domain="sync")

        # Gray-code the cross-domain history pointer so a video frame can
        # never latch a mixture of old and new binary pointer bits.
        m.d.comb += newest_binary_meta[7].eq(newest_gray_meta[7])
        for bit in range(6, -1, -1):
            m.d.comb += newest_binary_meta[bit].eq(
                newest_binary_meta[bit + 1] ^ newest_gray_meta[bit])

        newest_dvi = Signal(8)
        prev_vsync = Signal()
        m.d.dvi += prev_vsync.eq(self.i.vsync)
        with m.If(self.i.vsync & ~prev_vsync):
            m.d.dvi += [
                newest_dvi.eq(newest_binary_meta),
                spectrum_display_bank_dvi.eq(spectrum_publish_bank_meta),
                spectrum_display_ack_dvi.eq(spectrum_publish_bank_meta),
            ]

        wide = Signal()
        short = Signal()
        x_scale_shift = Signal(2)
        y_scale_shift = Signal(2)
        plot_w = Signal(12)
        plot_h = Signal(12)
        plot_x0 = Signal(signed(12))
        plot_y0 = Signal(signed(12))
        h_active_last_dvi = Signal(12)
        v_active_last_dvi = Signal(12)
        rel_x = Signal(signed(13))
        rel_y = Signal(signed(13))
        rel_x_next = Signal(signed(13))
        rel_y_next = Signal(signed(13))
        logical_x = Signal(12)
        logical_y = Signal(12)
        logical_x_geom = Signal(12)
        logical_y_geom = Signal(12)
        scan_geom = Signal(ScanPixel)
        rev_y = Signal(12)
        age = Signal(8)
        completed_age = Signal(8)
        bin_addr = Signal(8)
        spectrum_bin = Signal(8)
        spectrum_linear_bin = Signal(8)
        spectrum_linear_first = Signal()
        spectrum_linear_gap = Signal()
        spectrum_bin_prev = Signal(8)
        spectrum_active_bin_last_dvi = Signal(8)
        spectrum_desired_group_shift_dvi = Signal(2)
        spectrum_group_shift_dvi = Signal(2)
        spectrum_band_pixel_shift = Signal(4)
        spectrum_band_first = Signal()
        spectrum_band_gap = Signal()
        spectrum_prefetch = Signal()
        spectrum_read_region = Signal()
        spectrum_log_col = Signal(8)
        spectrum_log_coord_q8 = Signal(16)
        spectrum_log_curve_bin = Signal(8)
        spectrum_log_bar_bin = Signal(8)
        spectrum_log_bar_shift = Signal(2)
        spectrum_log_bar_addr = Signal(8)
        spectrum_log_bucket_frac = Signal(8)
        spectrum_log_gap_shift = Signal(3)
        spectrum_log_gap = Signal()
        spectrum_log_frac = Signal(8)
        spectrum_log_underflow = Signal()
        spectrum_log_underflow_pipe = Signal()
        spectrum_log_bar_pipe = Signal()
        spectrum_prefetch_calc = Signal()
        spectrum_prefetch_pipe = Signal()
        spectrum_style_pipe = Signal()
        spectrum_scale_pipe = Signal()
        spectrum_log_curve_pipe = Signal()
        spectrum_linear_bin_pipe = Signal(8)
        spectrum_linear_first_pipe = Signal()
        spectrum_linear_gap_pipe = Signal()
        spectrum_log_gap_pipe = Signal()
        spectrum_read_en_r = Signal()
        spectrum_read_bin_r = Signal(8)
        spectrum_read_first_r = Signal()
        spectrum_read_gap_r = Signal()
        spectrum_read_prefetch_r = Signal()
        spectrum_read_plot_r = Signal()
        spectrum_read_frac_r = Signal(8)
        spectrum_read_color_r = Signal(4)
        spectrum_read_underflow_r = Signal()
        spectrum_read_log_bar_r = Signal()
        spectrum_freq_color = Signal(4)
        spectrum_freq_color_base = Signal(4)
        spectrum_freq_color_frac = Signal(4)
        dither_threshold = Signal(4)
        dither_index = Signal(4)
        in_plot = Signal()
        m.submodules.spectrum_read_aligner = spectrum_read_aligner = \
            SpectrumReadRequestAligner()
        spectrum_plot_pipe = spectrum_read_aligner.o_plot
        m.d.comb += [
            spectrum_read_aligner.i_plot.eq(
                in_plot & spectrum_mode_dvi),
            spectrum_read_aligner.i_log_addr.eq(spectrum_log_bar_addr),
            spectrum_read_aligner.i_log_frac.eq(spectrum_log_bucket_frac),
            spectrum_read_aligner.i_color.eq(spectrum_freq_color),
        ]
        m.d.dvi += [
            spectrum_prefetch_pipe.eq(spectrum_prefetch_calc),
            spectrum_style_pipe.eq(spectrum_style_dvi),
            spectrum_scale_pipe.eq(spectrum_scale_dvi),
            spectrum_log_curve_pipe.eq(spectrum_style_dvi & spectrum_scale_dvi),
            spectrum_log_underflow_pipe.eq(spectrum_log_underflow),
            spectrum_log_bar_pipe.eq(spectrum_scale_dvi),
            spectrum_linear_bin_pipe.eq(spectrum_linear_bin),
            spectrum_linear_first_pipe.eq(spectrum_linear_first),
            spectrum_linear_gap_pipe.eq(spectrum_linear_gap),
            spectrum_log_gap_pipe.eq(spectrum_log_gap),
        ]
        with m.If(spectrum_read_region):
            m.d.dvi += spectrum_bin_prev.eq(spectrum_bin)
        m.d.dvi += [
            spectrum_read_en_r.eq(spectrum_read_region),
            spectrum_read_bin_r.eq(spectrum_bin),
            spectrum_read_first_r.eq(spectrum_band_first),
            spectrum_read_gap_r.eq(spectrum_band_gap),
            spectrum_read_prefetch_r.eq(spectrum_prefetch),
            spectrum_read_plot_r.eq(spectrum_plot_pipe),
            spectrum_read_frac_r.eq(Mux(spectrum_log_curve_pipe,
                                        spectrum_read_aligner.o_log_frac, 0)),
            spectrum_read_color_r.eq(spectrum_read_aligner.o_color),
            spectrum_read_underflow_r.eq(
                spectrum_scale_pipe & spectrum_log_underflow_pipe &
                ~spectrum_prefetch),
            spectrum_read_log_bar_r.eq(spectrum_log_bar_pipe & ~spectrum_prefetch),
        ]
        spectrum_log_coord_luts = [
            Array(Const(coord, 16) for coord in lut)
            for lut in SPECTRUM_LOG_COORD_LUTS
        ]
        with m.Switch(range_dvi):
            for range_index, lut in enumerate(spectrum_log_coord_luts):
                with m.Case(range_index):
                    m.d.comb += spectrum_log_coord_q8.eq(
                        lut[spectrum_log_col])
        spectrum_log_first_bin_columns = [
            Const(column, 8) for column in SPECTRUM_LOG_FIRST_BIN_COLUMNS
        ]
        spectrum_log_curve_first_bin_columns = [
            Const(column, 8)
            for column in SPECTRUM_LOG_CURVE_FIRST_BIN_COLUMNS
        ]
        with m.Switch(range_dvi):
            for range_index, column in enumerate(spectrum_log_first_bin_columns):
                with m.Case(range_index):
                    m.d.comb += spectrum_log_underflow.eq(
                        spectrum_log_col < Mux(
                            spectrum_style_dvi,
                            spectrum_log_curve_first_bin_columns[range_index],
                            # Log bars are pooled into 32/64/128/256 bands.
                            # Align the first resolvable FFT bin to the start
                            # of its complete pooled band. Previously the
                            # exact-frequency boundary cut through that band,
                            # producing the anomalous half-width column around
                            # 100Hz in the 24kHz view.
                            (column >> spectrum_log_bar_shift) <<
                            spectrum_log_bar_shift))
        # Screen dimensions change only when video timing changes. Register
        # their final active coordinates so every rotated pixel does not begin
        # with live dimension arithmetic on the grid/axis critical path.
        m.d.dvi += [
            h_active_last_dvi.eq(h_active_dvi - 1),
            v_active_last_dvi.eq(v_active_dvi - 1),
        ]
        logical_scan = _logical_scan_coordinates_from_last(
            self.i.x, self.i.y,
            h_active_last_dvi, v_active_last_dvi, rotation_dvi)
        # The linear-band mapping only permits shifts 0..5. Express each as
        # fixed wiring so synthesis does not build a variable right shift,
        # then add one and shift back left merely to identify a gap pixel.
        # ``first`` and ``gap`` are exactly the all-zero/all-one tests on the
        # coordinate bits discarded by the selected shift.
        m.d.comb += [
            spectrum_linear_bin.eq(rel_x.as_unsigned()[:8]),
            spectrum_linear_first.eq(1),
            spectrum_linear_gap.eq(0),
        ]
        with m.Switch(spectrum_band_pixel_shift):
            for shift in range(1, 6):
                with m.Case(shift):
                    m.d.comb += [
                        spectrum_linear_bin.eq(
                            rel_x.as_unsigned()[shift:shift + 8]),
                        spectrum_linear_first.eq(
                            rel_x.as_unsigned()[:shift] == 0),
                        spectrum_linear_gap.eq(
                            rel_x.as_unsigned()[:shift] ==
                            (1 << shift) - 1),
                    ]
        m.d.comb += [
            logical_x.eq(logical_scan[0]),
            logical_y.eq(logical_scan[1]),
            wide.eq(h_active_dvi >= 1024),
            short.eq(v_active_dvi < 600),
            x_scale_shift.eq(Mux(wide, 2, 1)),
            y_scale_shift.eq(Mux(short, 0, 1)),
            plot_w.eq(HISTORY_COLS << x_scale_shift),
            plot_h.eq(N_BINS << y_scale_shift),
            plot_x0.eq((h_active_dvi - plot_w) >> 1),
            plot_y0.eq((v_active_dvi - plot_h) >> 1),
            rel_x_next.eq(logical_x - plot_x0),
            rel_y_next.eq(logical_y - plot_y0),
            rev_y.eq(plot_h - 1 - rel_y),
            age.eq(rel_x.as_unsigned() >> x_scale_shift),
            # Age 255 is also the scratch column receiving the next FFT. Read
            # the adjacent completed column at the far edge so a partially
            # written spectrum cannot leak into the visible 2D history.
            completed_age.eq(Mux(age == 255, 254, age)),
            # Each range analyzes at a matching sample rate, so all four
            # ranges use the complete 256-bin half-spectrum.
            spectrum_active_bin_last_dvi.eq(255),
            spectrum_desired_group_shift_dvi.eq(3 - spectrum_bands_dvi),
            spectrum_group_shift_dvi.eq(Mux(
                spectrum_style_dvi,
                0,
                spectrum_desired_group_shift_dvi)),
            spectrum_band_pixel_shift.eq(
                x_scale_shift + spectrum_group_shift_dvi),
            bin_addr.eq(rev_y >> y_scale_shift),
            spectrum_freq_color_base.eq(
                rel_x.as_unsigned() >> (x_scale_shift + 4)),
            spectrum_freq_color_frac.eq(Mux(
                wide,
                rel_x.as_unsigned()[2:6],
                rel_x.as_unsigned()[1:5])),
            spectrum_freq_color.eq(Mux(
                (spectrum_freq_color_frac > dither_threshold) &
                (spectrum_freq_color_base < 15),
                spectrum_freq_color_base + 1,
                spectrum_freq_color_base)),
            # Log scale follows a conventional analyzer-style frequency axis
            # from 10 Hz to the selected range. Linear bars can still pool
            # multiple FFT bins into fewer display bands; log bars use
            # analyzer-style log buckets controlled by the bands option.
            spectrum_log_col.eq(rel_x.as_unsigned() >> x_scale_shift),
            spectrum_log_bar_bin.eq(spectrum_log_coord_q8[8:16]),
            spectrum_log_bar_shift.eq(3 - spectrum_bands_dvi),
            spectrum_log_bar_addr.eq(
                spectrum_log_col >> spectrum_log_bar_shift),
            spectrum_log_gap_shift.eq(
                x_scale_shift + spectrum_log_bar_shift),
            spectrum_log_gap.eq(Mux(
                spectrum_log_gap_shift == 0,
                0,
                Mux(spectrum_log_gap_shift == 1,
                    rel_x.as_unsigned()[0],
                    Mux(spectrum_log_gap_shift == 2,
                        rel_x.as_unsigned()[:2] == 0b11,
                        Mux(spectrum_log_gap_shift == 3,
                            rel_x.as_unsigned()[:3] == 0b111,
                            Mux(spectrum_log_gap_shift == 4,
                                rel_x.as_unsigned()[:4] == 0b1111,
                                rel_x.as_unsigned()[:5] == 0b11111)))))),
            spectrum_log_bucket_frac.eq(Mux(
                spectrum_log_bar_shift == 0,
                0,
                Mux(spectrum_log_bar_shift == 1,
                    Cat(Const(0, 7), spectrum_log_col[0]),
                    Mux(spectrum_log_bar_shift == 2,
                        Cat(Const(0, 6), spectrum_log_col[:2]),
                        Cat(Const(0, 5), spectrum_log_col[:3]))))),
            spectrum_log_curve_bin.eq(Mux(
                spectrum_log_coord_q8[8:16] == spectrum_active_bin_last_dvi,
                spectrum_active_bin_last_dvi,
                spectrum_log_coord_q8[8:16] + 1)),
            spectrum_log_frac.eq(spectrum_log_coord_q8[:8]),
            spectrum_prefetch_calc.eq(
                scan_geom.de & spectrum_mode_dvi & spectrum_style_dvi &
                (rel_x == -1) & (rel_y >= 0) & (rel_y < plot_h)),
            spectrum_prefetch.eq(spectrum_prefetch_pipe),
            spectrum_read_region.eq(
                spectrum_plot_pipe | spectrum_prefetch),
            spectrum_bin.eq(Mux(
                spectrum_prefetch,
                0,
                Mux(spectrum_scale_pipe,
                    spectrum_read_aligner.o_log_addr,
                    spectrum_linear_bin_pipe))),
            spectrum_band_first.eq(
                Mux(spectrum_style_pipe | spectrum_scale_pipe,
                    spectrum_prefetch |
                    (spectrum_bin != spectrum_bin_prev),
                    spectrum_linear_first_pipe)),
            spectrum_band_gap.eq(
                ~spectrum_style_pipe &
                Mux(spectrum_scale_pipe,
                    spectrum_log_gap_pipe,
                    spectrum_linear_gap_pipe)),
            in_plot.eq(scan_geom.de & (rel_x >= 0) & (rel_x < plot_w) &
                       (rel_y >= 0) & (rel_y < plot_h)),
            history_r.en.eq(in_plot),
            history_r.addr.eq(
                ((newest_dvi + completed_age) << 8) | bin_addr),
            spectrum_levels_r.en.eq(spectrum_read_en_r),
            spectrum_levels_r.addr.eq(
                Cat(spectrum_read_bin_r, spectrum_display_bank_dvi)),
            spectrum_log_levels_r.en.eq(spectrum_read_en_r),
            spectrum_log_levels_r.addr.eq(
                Cat(spectrum_read_bin_r, spectrum_display_bank_dvi)),
            spectrum_peak_r.en.eq(spectrum_read_en_r),
            spectrum_peak_r.addr.eq(spectrum_read_bin_r),
        ]

        # Align scan and styling information with the synchronous BRAM read.
        scan_d = Signal(ScanPixel)
        logical_x_d = Signal(12)
        logical_y_d = Signal(12)
        spectrogram_plot_d = Signal()
        spectrum_plot_d = Signal()
        spectrum_band_d = Signal(8)
        spectrum_band_first_d = Signal()
        spectrum_band_gap_d = Signal()
        spectrum_prefetch_d = Signal()
        spectrum_log_frac_d = Signal(8)
        spectrum_log_underflow_d = Signal()
        spectrum_log_bar_d = Signal()
        spectrum_calc_plot = Signal()
        spectrum_calc_band = Signal(8)
        spectrum_calc_band_first = Signal()
        spectrum_calc_band_gap = Signal()
        spectrum_calc_prefetch = Signal()
        spectrum_calc_log_frac = Signal(8)
        spectrum_calc_log_underflow = Signal()
        spectrum_calc_level = Signal(6)
        spectrum_calc_focus = Signal(4)
        spectrum_calc_peak_state = Signal(12)
        spectrum_calc_scan_y = Signal(signed(13))
        spectrum_calc_color = Signal(4)
        spectrum_calc_dither = Signal(4)
        age_d = Signal(8)
        axes_hit_d = Signal()
        axes_hit = Signal()
        spectrum_grid_hit = Signal()
        spectrum_grid_hit_d = Signal()
        menu_protect_geom = Signal()
        menu_protect_d = Signal()
        major_x = Signal()
        linear_major_x = Signal()
        curve_major_x = Signal()
        major_y = Signal()
        axis_pad = 3
        m.d.comb += curve_major_x.eq(0)
        for range_index, tick_columns in enumerate(SPECTRUM_LOG_TICK_COLUMNS):
            tick_hits = []
            for column in tick_columns.values():
                tick_x = Const(column, 10) << x_scale_shift
                tick_hits.append(
                    (rel_x == tick_x) |
                    ((x_scale_shift != 0) & (rel_x == tick_x + 1)))
            with m.If((range_dvi == range_index) & spectrum_scale_dvi):
                m.d.comb += curve_major_x.eq(Cat(*tick_hits).any())
        m.d.comb += [
            linear_major_x.eq((rel_x == 0) | (rel_x == (plot_w >> 2)) |
                              (rel_x == (plot_w >> 1)) |
                              (rel_x == plot_w - (plot_w >> 2)) |
                              (rel_x == plot_w - 1)),
            major_x.eq(Mux(
                spectrum_mode_dvi & spectrum_scale_dvi,
                curve_major_x,
                linear_major_x)),
            major_y.eq((rel_y == 0) | (rel_y == (plot_h >> 2)) |
                       (rel_y == (plot_h >> 1)) |
                       (rel_y == plot_h - (plot_h >> 2)) |
                       (rel_y == plot_h - 1)),
            axes_hit.eq(axes_dvi & scan_geom.de &
                        (((rel_x == -axis_pad) & (rel_y >= 0) &
                          (rel_y <= plot_h + axis_pad)) |
                         ((rel_y == plot_h + axis_pad) &
                          (rel_x >= -axis_pad) & (rel_x < plot_w)) |
                         (major_x & (rel_x >= 0) & (rel_x < plot_w) &
                          (rel_y >= plot_h) &
                          (rel_y < plot_h + axis_pad)) |
                         (major_y & (rel_y >= 0) & (rel_y < plot_h) &
                          (rel_x >= -axis_pad) & (rel_x < 0)))),
            spectrum_grid_hit.eq(
                in_plot & spectrum_mode_dvi & spectrum_grid_dvi &
                (major_x | major_y)),
            # Resolve the menu rectangle beside the shared rotation stage.
            # Registering this single-bit result with ``scan_d`` keeps the
            # coordinate subtraction and rectangle comparisons out of the
            # final spectrum pixel-priority path.
            menu_protect_geom.eq(
                menu_visible_dvi & scan_geom.de &
                (logical_x_geom >= h_active_dvi - 292) &
                (logical_x_geom < h_active_dvi - 28) &
                (logical_y_geom >= (v_active_dvi >> 1) - 18) &
                (logical_y_geom < (v_active_dvi >> 1) + 138)),
        ]
        m.d.dvi += [
            # Rotation and plot-origin subtraction are shared by every
            # renderer, so terminate them once at a common DVI boundary.
            # This avoids the long scan -> rotation -> subtraction -> grid
            # comparison path without duplicating the geometry arithmetic.
            scan_geom.eq(self.i),
            logical_x_geom.eq(logical_x),
            logical_y_geom.eq(logical_y),
            rel_x.eq(rel_x_next),
            rel_y.eq(rel_y_next),
            scan_d.eq(scan_geom),
            # Carry the already-computed logical coordinates across the same
            # BRAM pipeline boundary instead of rebuilding the complete
            # rotation mux/subtract network from ``scan_d``.
            logical_x_d.eq(logical_x_geom),
            logical_y_d.eq(logical_y_geom),
            spectrogram_plot_d.eq(in_plot & ~spectrum_mode_dvi),
            spectrum_plot_d.eq(spectrum_read_plot_r),
            spectrum_band_d.eq(spectrum_read_bin_r),
            spectrum_band_first_d.eq(spectrum_read_first_r),
            spectrum_band_gap_d.eq(spectrum_read_gap_r),
            spectrum_prefetch_d.eq(spectrum_read_prefetch_r),
            spectrum_log_frac_d.eq(spectrum_read_frac_r),
            spectrum_log_underflow_d.eq(spectrum_read_underflow_r),
            spectrum_log_bar_d.eq(spectrum_read_log_bar_r),
            age_d.eq(age),
            axes_hit_d.eq(axes_hit),
            spectrum_grid_hit_d.eq(spectrum_grid_hit),
            menu_protect_d.eq(menu_protect_geom),
        ]

        # Terminate every synchronous spectrum-memory path immediately after
        # the read. The original renderer carried BRAM clock-to-Q through
        # floor shaping, interpolation, height conversion and fill styling in
        # one DVI cycle.
        spectrum_log_level_valid_calc = Signal()
        spectrum_display_level_calc = Signal(6)
        spectrum_focus_level_calc = Signal(4)
        m.d.comb += [
            spectrum_log_level_valid_calc.eq(
                spectrum_log_levels_r.data[6:10] ==
                spectrum_log_bucket_generation_dvi),
            # Capture the selected BRAM value directly. Display-floor shaping
            # runs from this register in the following already-existing
            # renderer stage; leaving it on the block-RAM output was the final
            # DVI timing failure after congestion was removed.
            spectrum_display_level_calc.eq(Mux(
                spectrum_log_bar_d,
                Mux(spectrum_log_level_valid_calc,
                    spectrum_log_levels_r.data[:6], 0),
                spectrum_levels_r.data[:6])),
            spectrum_focus_level_calc.eq(Mux(
                spectrum_log_bar_d & spectrum_log_level_valid_calc,
                spectrum_log_levels_r.data[10:14],
                spectrum_levels_r.data[6:10])),
        ]
        m.d.dvi += [
            spectrum_calc_plot.eq(spectrum_plot_d),
            spectrum_calc_band.eq(spectrum_band_d),
            spectrum_calc_band_first.eq(spectrum_band_first_d),
            spectrum_calc_band_gap.eq(spectrum_band_gap_d),
            spectrum_calc_prefetch.eq(spectrum_prefetch_d),
            spectrum_calc_log_frac.eq(spectrum_log_frac_d),
            spectrum_calc_log_underflow.eq(spectrum_log_underflow_d),
            spectrum_calc_level.eq(spectrum_display_level_calc),
            spectrum_calc_focus.eq(spectrum_focus_level_calc),
            spectrum_calc_peak_state.eq(spectrum_peak_r.data),
            spectrum_calc_scan_y.eq(logical_y_d - plot_y0),
            spectrum_calc_color.eq(spectrum_read_color_r),
            spectrum_calc_dither.eq(dither_threshold),
        ]

        # ---- persistent, dynamically scaled axis labels -------------------
        # Labels are generated in the beam-raced overlay rather than written
        # into the decaying framebuffer, so they remain crisp and cost no
        # redraw bandwidth. The X scale is elapsed history age (newest = 0)
        # and the Y scale follows the selected maximum frequency.
        label_active = Signal()
        label_char = Signal(7, init=ord(" "))
        label_id = Signal(5)
        label_char_index = Signal(4)
        label_col = Signal(3)
        label_row = Signal(3)

        label_serial = 0
        label_group = 0
        label_definitions = []
        label_group_active = [Signal(name=f"axis_group_active_{index}")
                              for index in range(4)]
        label_group_id = [Signal(5, name=f"axis_group_id_{index}")
                          for index in range(4)]
        label_group_char_index = [
            Signal(4, name=f"axis_group_char_index_{index}")
            for index in range(4)
        ]
        label_group_col = [Signal(3, name=f"axis_group_col_{index}")
                           for index in range(4)]
        label_group_row = [Signal(3, name=f"axis_group_row_{index}")
                           for index in range(4)]
        label_group_enables = [
            Const(1),
            ~(spectrum_mode_dvi & spectrum_scale_dvi),
            spectrum_mode_dvi & spectrum_scale_dvi,
            Const(1),
        ]
        for index in range(4):
            m.d.comb += [
                label_group_active[index].eq(0),
                label_group_id[index].eq(0),
                label_group_char_index[index].eq(0),
                label_group_col[index].eq(0),
                label_group_row[index].eq(0),
            ]

        def place_text(variants, selector, x0, y0):
            """Place one of several equal-width strings in an 8x8-cell font."""
            nonlocal label_serial, label_group
            if AXIS_LABELS_IN_FRAMEBUFFER:
                return
            if isinstance(variants, str):
                variants = [variants]
                selector = None
            width_chars = len(variants[0])
            assert all(len(text) == width_chars for text in variants)
            serial = label_serial
            label_serial += 1
            label_definitions.append((serial, variants, selector))
            origin_x_d = Signal(signed(13), name=f"axis_origin_x_d_{serial}")
            origin_y_d = Signal(signed(13), name=f"axis_origin_y_d_{serial}")
            rel_lx = Signal(signed(13), name=f"axis_label_x_{serial}")
            rel_ly = Signal(signed(13), name=f"axis_label_y_{serial}")
            char_index = Signal(max(1, (width_chars - 1).bit_length()),
                                name=f"axis_char_index_{serial}")
            active = Signal(name=f"axis_label_active_{serial}")
            active_d = Signal(name=f"axis_label_active_d_{serial}")
            char_index_d = Signal(4, name=f"axis_char_index_d_{serial}")
            col_d = Signal(3, name=f"axis_col_d_{serial}")
            row_d = Signal(3, name=f"axis_row_d_{serial}")
            m.d.dvi += [
                origin_x_d.eq(x0),
                origin_y_d.eq(y0),
            ]
            m.d.comb += [
                rel_lx.eq(logical_x_d - origin_x_d),
                rel_ly.eq(logical_y_d - origin_y_d),
                char_index.eq(rel_lx.as_unsigned() >> 3),
                active.eq(label_group_enables[label_group] &
                          axes_dvi & scan_d.de &
                          (rel_lx >= 0) & (rel_lx < width_chars * 8) &
                          (rel_ly >= 0) & (rel_ly < 8)),
            ]
            m.d.dvi += [
                active_d.eq(active),
                char_index_d.eq(char_index),
                col_d.eq(rel_lx[:3]),
                row_d.eq(rel_ly[:3]),
            ]
            with m.If(active_d):
                m.d.comb += [
                    label_group_active[label_group].eq(1),
                    label_group_id[label_group].eq(serial),
                    label_group_char_index[label_group].eq(char_index_d),
                    label_group_col[label_group].eq(col_d),
                    label_group_row[label_group].eq(row_d),
                ]

        def curve_variants(*labels):
            variants = ["    "] * 16
            for range_index, label in enumerate(labels):
                variants[12 + range_index] = label
            return variants

        def curve_label_x(columns, x_offset=16):
            selected_column = Signal(8, name=f"curve_label_col_{label_serial}")
            with m.Switch(range_dvi):
                for range_index, column in enumerate(columns):
                    with m.Case(range_index):
                        m.d.comb += selected_column.eq(column)
            return plot_x0 + (selected_column << x_scale_shift) - x_offset

        def log_col(max_hz, hz):
            return round(255 * math.log10(hz / 10) / math.log10(max_hz / 10))

        # The same label generators serve both flat modes. Selector values
        # 0..3 describe spectrograph range/rate; 4..7 describe spectrum
        # magnitude/frequency.
        axis_y_selector = Signal(3)
        axis_x_selector = Signal(4)
        m.d.comb += [
            axis_y_selector.eq(Cat(range_dvi, spectrum_mode_dvi)),
            axis_x_selector.eq(Mux(
                spectrum_mode_dvi,
                Cat(range_dvi, Const(1, 1),
                    spectrum_scale_dvi),
                Cat(rate_dvi, Const(0, 2)),
            )),
        ]

        # Y frequency or magnitude labels, top to bottom. Fixed-width padding
        # keeps all values aligned against the left-hand axis.
        y_label_x = plot_x0 - 48
        y_tick_positions = [
            plot_y0 - 3,
            plot_y0 + (plot_h >> 2) - 3,
            plot_y0 + (plot_h >> 1) - 3,
            plot_y0 + plot_h - (plot_h >> 2) - 3,
            plot_y0 + plot_h - 8,
        ]
        y_labels = [
            ["  24k", "  12k", "   6k", "   3k",
             "    0", "    0", "    0", "    0"],
            ["  18k", "   9k", " 4.5k", "2.25k",
             "  -24", "  -24", "  -24", "  -24"],
            ["  12k", "   6k", "   3k", " 1.5k",
             "  -48", "  -48", "  -48", "  -48"],
            ["   6k", "   3k", " 1.5k", "  750",
             "  -72", "  -72", "  -72", "  -72"],
            ["    0", "    0", "    0", "    0",
             "  -96", "  -96", "  -96", "  -96"],
        ]
        for variants, y_pos in zip(y_labels, y_tick_positions):
            place_text(variants, axis_y_selector, y_label_x, y_pos)
        place_text(["FREQ (Hz)", "AMP(dBFS)"], spectrum_mode_dvi,
                   plot_x0 - 72, plot_y0 - 20)

        # Spectrograph X labels show elapsed age; spectrum labels show the
        # frequency represented at quarter intervals.
        label_group = 1
        place_text(["  0", "  0", "  0", "  0",
                    "  0", "  0", "  0", "  0",
                    "   ", "   ", "   ", "   ",
                    "   ", "   ", "   ", "   "], axis_x_selector,
                   plot_x0 - axis_pad,
                   plot_y0 + plot_h + axis_pad + 5)
        place_text(["0.68s", "1.36s", "2.73s", "5.45s",
                    "  6k ", "  3k ", "1.5k ", " 750 ",
                    "     ", "     ", "     ", "     ",
                    "     ", "     ", "     ", "     "], axis_x_selector,
                   plot_x0 + (plot_w >> 2) - 20,
                   plot_y0 + plot_h + axis_pad + 5)
        place_text(["1.37s", "2.73s", "5.46s", "10.9s",
                    " 12k ", "  6k ", "  3k ", "1.5k ",
                    "     ", "     ", "     ", "     ",
                    "     ", "     ", "     ", "     "], axis_x_selector,
                   plot_x0 + (plot_w >> 1) - 20,
                   plot_y0 + plot_h + axis_pad + 5)
        place_text(["2.04s", "4.08s", "8.18s", "16.4s",
                    " 18k ", "  9k ", "4.5k ", "2.25k",
                    "     ", "     ", "     ", "     ",
                    "     ", "     ", "     ", "     "], axis_x_selector,
                   plot_x0 + plot_w - (plot_w >> 2) - 20,
                   plot_y0 + plot_h + axis_pad + 5)
        place_text(["2.72s", "5.44s", "10.9s", "21.8s",
                    " 24k ", " 12k ", "  6k ", "  3k ",
                    "     ", "     ", "     ", "     ",
                    "     ", "     ", "     ", "     "], axis_x_selector,
                   plot_x0 + plot_w - 40,
                   plot_y0 + plot_h + axis_pad + 5)
        label_group = 2
        curve_label_y = plot_y0 + plot_h + axis_pad + 5
        place_text(curve_variants("  10", "  10", "  10", "  10"),
                   axis_x_selector, plot_x0 - axis_pad, curve_label_y)
        place_text(curve_variants(" 100", " 100", " 100", " 100"),
                   axis_x_selector,
                   curve_label_x([log_col(24000, 100),
                                  log_col(12000, 100),
                                  log_col(6000, 100),
                                  log_col(3000, 100)]),
                   curve_label_y)
        place_text(curve_variants("  1k", "  1k", "  1k", "  1k"),
                   axis_x_selector,
                   curve_label_x([log_col(24000, 1000),
                                  log_col(12000, 1000),
                                  log_col(6000, 1000),
                                  log_col(3000, 1000)]),
                   curve_label_y)
        place_text(curve_variants(" 10k", " 10k", "    ", "    "),
                   axis_x_selector,
                   curve_label_x([log_col(24000, 10000),
                                  log_col(12000, 10000), 255, 255]),
                   curve_label_y)
        place_text(curve_variants(" 20k", " 12k", "  6k", "  3k"),
                   axis_x_selector,
                   plot_x0 + plot_w - 32,
                   curve_label_y)
        label_group = 3
        place_text(["AGE (s) ", "FREQ(Hz)"], spectrum_mode_dvi,
                   plot_x0 + (plot_w >> 1) - 32,
                   plot_y0 + plot_h + axis_pad + 21)

        m.d.comb += [
            label_active.eq(Cat(*label_group_active).any()),
            label_id.eq(Mux(
                label_group_active[3], label_group_id[3],
                Mux(label_group_active[2], label_group_id[2],
                    Mux(label_group_active[1], label_group_id[1],
                        label_group_id[0])))),
            label_char_index.eq(Mux(
                label_group_active[3], label_group_char_index[3],
                Mux(label_group_active[2], label_group_char_index[2],
                    Mux(label_group_active[1], label_group_char_index[1],
                        label_group_char_index[0])))),
            label_col.eq(Mux(
                label_group_active[3], label_group_col[3],
                Mux(label_group_active[2], label_group_col[2],
                    Mux(label_group_active[1], label_group_col[1],
                        label_group_col[0])))),
            label_row.eq(Mux(
                label_group_active[3], label_group_row[3],
                Mux(label_group_active[2], label_group_row[2],
                    Mux(label_group_active[1], label_group_row[1],
                        label_group_row[0])))),
            label_char.eq(ord(" ")),
        ]

        # Resolve the selected label's character once, after placement has
        # reduced all candidates to one label ID and character index. The old
        # structure instantiated a complete dynamic character mux for every
        # label in parallel, even though at most one label can cover a pixel.
        with m.Switch(label_id):
            for serial, variants, selector in label_definitions:
                with m.Case(serial):
                    if selector is None:
                        chars = Array(Const(ord(ch), 7)
                                      for ch in variants[0])
                        m.d.comb += label_char.eq(chars[label_char_index])
                    else:
                        with m.Switch(selector):
                            for variant_index, text in enumerate(variants):
                                chars = Array(Const(ord(ch), 7) for ch in text)
                                with m.Case(variant_index):
                                    m.d.comb += label_char.eq(
                                        chars[label_char_index])

        # Pipeline label selection before glyph lookup. Character selection
        # includes the dynamic range/rate muxes; separating it from the font
        # decoder keeps this path away from the DVI output boundary.
        label_active_d = Signal()
        label_char_d = Signal(7)
        label_col_d = Signal(3)
        label_row_d = Signal(3)
        m.d.dvi += [
            label_active_d.eq(label_active),
            label_char_d.eq(label_char),
            label_col_d.eq(label_col),
            label_row_d.eq(label_row),
        ]

        glyph_row = Signal(5)
        m.d.comb += glyph_row.eq(0)
        with m.Switch(label_char_d):
            for character, rows in FONT_5X7.items():
                row_bits = []
                for row in rows:
                    row_bits.append(sum(
                        (1 << column) for column, value in enumerate(row)
                        if value == "1"))
                row_bits.append(0)
                with m.Case(ord(character)):
                    m.d.comb += glyph_row.eq(
                        Array(Const(bits, 5) for bits in row_bits)[label_row_d])
        label_hit = Signal()
        label_hit_d = Signal()
        m.d.comb += label_hit.eq(
            label_active_d & (label_col_d < 5) &
            glyph_row.bit_select(label_col_d, 1))
        m.d.dvi += label_hit_d.eq(label_hit)

        # Work in sixteenths of a visible palette step. This makes age fade
        # advance every history column rather than jumping one whole four-bit
        # intensity at a time. A 4x4 ordered dither preserves the fractional
        # part at the final four-bit palette boundary.
        fade = Signal(8)
        source_ext = Signal(9)
        history_calc_level = Signal(6)
        history_display_level = Signal(6)
        history_calc_age = Signal(8)
        history_calc_dither = Signal(4)
        history_calc_plot = Signal()
        faded_ext = Signal(9)
        display_ext = Signal(8)
        history_pre_ext = Signal(8)
        history_pre_dither = Signal(4)
        history_pre_plot = Signal()
        display_base = Signal(4)
        display_frac = Signal(4)
        display_level = Signal(4)
        with m.Switch(persistence_dvi):
            with m.Case(0):
                m.d.comb += fade.eq(history_calc_age)
            with m.Case(1):
                m.d.comb += fade.eq(history_calc_age >> 1)
            with m.Case(2):
                m.d.comb += fade.eq(history_calc_age >> 2)
            with m.Default():
                m.d.comb += fade.eq(history_calc_age >> 3)
        m.d.comb += dither_index.eq(
            Cat(logical_x_d[:2], logical_y_d[:2]))
        # 4x4 Bayer matrix, indexed by {y[1:0], x[1:0]}.
        bayer4 = [0, 8, 2, 10, 12, 4, 14, 6,
                  3, 11, 1, 9, 15, 7, 13, 5]
        with m.Switch(dither_index):
            for index, threshold in enumerate(bayer4):
                with m.Case(index):
                    m.d.comb += dither_threshold.eq(threshold)
        # Terminate the history BRAM path before fade, dither, and output
        # composition. The final overlay stage below is already one cycle
        # after ``base_o``, so these values remain aligned with its pixel.
        m.d.dvi += [
            # End the history block-RAM path at a register. Applying the
            # selectable display floor here made its compare/subtract/mux
            # network part of the BRAM clock-to-Q path.
            history_calc_level.eq(history_r.data),
            history_calc_age.eq(age_d),
            history_calc_dither.eq(dither_threshold),
            history_calc_plot.eq(spectrogram_plot_d),
        ]
        m.d.comb += [
            history_display_level.eq(
                apply_display_floor(history_calc_level)),
            source_ext.eq((history_display_level << 2) + 8),
            faded_ext.eq(Mux(
                source_ext <= fade,
                0,
                source_ext - fade,
            )),
            display_ext.eq(Mux(
                phosphor_dvi,
                Mux(faded_ext > 255, 255, faded_ext[:8]),
                history_display_level << 2,
            )),
            display_base.eq(history_pre_ext[4:8]),
            display_frac.eq(history_pre_ext[:4]),
            display_level.eq(Mux(
                (display_frac > history_pre_dither) & (display_base < 15),
                display_base + 1,
                display_base,
            )),
        ]
        # Split floor/fade computation from the final palette quantization.
        # The renderer already had two history alignment registers; this
        # boundary replaces the first one rather than increasing latency.
        m.d.dvi += [
            history_pre_ext.eq(display_ext),
            history_pre_dither.eq(history_calc_dither),
            history_pre_plot.eq(history_calc_plot),
        ]

        # Spectrum mode beam-races pooled FFT bands. Bars and curves share the
        # same current-level table, smooth gradient fill, and falling peak
        # markers without writing a single pixel to the framebuffer.
        spectrum_height = Signal(12)
        spectrum_y = Signal(signed(13))
        spectrum_scan_y = Signal(signed(13))
        spectrum_display_level = Signal(6)
        spectrum_display_level_raw = Signal(6)
        spectrum_log_level_valid = Signal()
        spectrum_focus_display_level = Signal(4)
        spectrum_line_hit = Signal()
        spectrum_curve_glow_hit = Signal()
        spectrum_curve_glow_level = Signal(4)
        spectrum_fill_hit = Signal()
        spectrum_peak_hit = Signal()
        spectrum_shape_pixel = Signal()
        spectrum_peak_y = Signal(signed(13))
        spectrum_peak_level = Signal(6)
        spectrum_peak_hold = Signal(5)
        spectrum_peak_state_epoch = Signal()
        spectrum_peak_state_valid = Signal()
        spectrum_peak_epoch = Signal()
        spectrum_mode_prev_dvi = Signal()
        spectrum_style_prev_dvi = Signal()
        spectrum_bands_prev_dvi = Signal(2)
        spectrum_scale_prev_dvi = Signal()
        range_prev_dvi = Signal(2)
        noise_floor_prev_dvi = Signal(2)
        spectrum_peak_config_changed = Signal()
        spectrum_peak_reset_holdoff = Signal(3)
        spectrum_peak_reset_active = Signal()
        spectrum_peak_clear_active = Signal()
        spectrum_peak_clear_addr = Signal(8)
        spectrum_peak_display_level = Signal(4)
        spectrum_peak_level_next = Signal(6)
        spectrum_peak_hold_next = Signal(5)
        spectrum_peak_hold_init = Signal(5)
        spectrum_peak_decay_tick = Signal()
        spectrum_peak_update = Signal()
        spectrum_peak_frame = Signal(4)
        spectrum_gradient_height = Signal(12)
        spectrum_gradient_ext = Signal(9)
        spectrum_gradient_clamped = Signal(8)
        spectrum_gradient_base = Signal(4)
        spectrum_gradient_frac = Signal(4)
        spectrum_gradient_level = Signal(4)
        spectrum_gradient_fill_level = Signal(4)
        spectrum_amplitude_level = Signal(4)
        spectrum_fill_level = Signal(4)
        spectrum_focus_peak = Signal()
        spectrum_focus_dim = Signal()
        spectrum_line_level = Signal(4)
        spectrum_curve_glow_level_focused = Signal(4)
        spectrum_fill_level_focused = Signal(4)
        spectrum_focus_center = Signal()
        spectrum_focus_shoulder = Signal()
        spectrum_focus_fill_boost = Signal(4)
        spectrum_focus_fill_ext = Signal(5)
        spectrum_focus_glow_ext = Signal(5)
        spectrum_curve_raw_prev = Signal(6)
        spectrum_curve_target = Signal(6)
        spectrum_curve_log_start = Signal(6)
        spectrum_curve_log_end = Signal(6)
        spectrum_curve_log_start_effective = Signal(6)
        spectrum_curve_log_end_effective = Signal(6)
        spectrum_curve_delta = Signal(signed(8))
        spectrum_curve_delta_pipe = Signal(signed(8))
        spectrum_curve_product_next = Signal(signed(13))
        spectrum_curve_product = Signal(signed(13))
        spectrum_curve_base_q4_pipe = Signal(signed(13))
        spectrum_curve_base_q4 = Signal(signed(13))
        spectrum_curve_display_q4 = Signal(signed(13))
        spectrum_curve_level = Signal(6)
        spectrum_height_q4 = Signal(13)
        spectrum_peak_raw_prev = Signal(6)
        spectrum_peak_curve_start = Signal(6)
        spectrum_peak_curve_end = Signal(6)
        spectrum_peak_curve_start_effective = Signal(6)
        spectrum_peak_curve_end_effective = Signal(6)
        spectrum_peak_curve_delta = Signal(signed(8))
        spectrum_peak_curve_delta_pipe = Signal(signed(8))
        spectrum_peak_curve_product_next = Signal(signed(13))
        spectrum_peak_curve_product = Signal(signed(13))
        spectrum_peak_curve_base_q4_pipe = Signal(signed(13))
        spectrum_peak_curve_base_q4 = Signal(signed(13))
        spectrum_peak_curve_display_q4 = Signal(signed(13))
        spectrum_peak_height_q4 = Signal(13)
        spectrum_peak_display_y = Signal(signed(13))
        spectrum_pre_plot = Signal()
        spectrum_pre_style = Signal()
        spectrum_pre_band_gap = Signal()
        spectrum_pre_log_underflow = Signal()
        spectrum_pre_scan_y = Signal(signed(13))
        spectrum_pre_level = Signal(6)
        spectrum_pre_focus = Signal(4)
        spectrum_pre_peak_level = Signal(6)
        spectrum_pre_color = Signal(4)
        spectrum_pre_dither = Signal(4)
        spectrum_pipe_plot = Signal()
        spectrum_pipe_style = Signal()
        spectrum_pipe_band_gap = Signal()
        spectrum_pipe_log_underflow = Signal()
        spectrum_pipe_scan_y = Signal(signed(13))
        spectrum_pipe_level = Signal(6)
        spectrum_pipe_focus = Signal(4)
        spectrum_pipe_peak_level = Signal(6)
        spectrum_pipe_color = Signal(4)
        spectrum_pipe_dither = Signal(4)
        spectrum_render_plot = Signal()
        spectrum_render_style = Signal()
        spectrum_render_shape = Signal()
        spectrum_render_y = Signal(signed(13))
        spectrum_render_scan_y = Signal(signed(13))
        spectrum_render_peak_enabled = Signal()
        spectrum_render_peak_y = Signal(signed(13))
        spectrum_render_peak_level = Signal(4)
        spectrum_render_fill_enabled = Signal()
        spectrum_render_fill_raw = Signal(4)
        spectrum_render_glow_raw = Signal(4)
        spectrum_render_highlight = Signal()
        spectrum_render_focus_peak = Signal()
        spectrum_render_focus_dim = Signal()
        spectrum_render_focus_center = Signal()
        spectrum_render_focus_shoulder = Signal()
        spectrum_render_fill_level = Signal(4)
        spectrum_render_line_level = Signal(4)
        spectrum_render_glow_level = Signal(4)
        spectrum_frequency_color = Signal(4)
        spectrum_render_color = Signal(4)
        spectrum_trace_color = Signal(4)
        spectrum_grid_level = Signal(4)
        spectrum_axis_level = Signal(4)
        spectrum_axis_color = Signal(4)
        spectrum_fill_is_gradient = Signal()
        spectrum_fill_is_freq = Signal()
        spectrum_fill_is_gradient_reverse = Signal()
        spectrum_fill_is_freq_reverse = Signal()

        with m.If(self.i.vsync & ~prev_vsync):
            m.d.dvi += spectrum_peak_frame.eq(spectrum_peak_frame + 1)
        m.d.comb += spectrum_peak_config_changed.eq(
            (spectrum_style_dvi != spectrum_style_prev_dvi) |
            (spectrum_bands_dvi != spectrum_bands_prev_dvi) |
            (spectrum_scale_dvi != spectrum_scale_prev_dvi) |
            (range_dvi != range_prev_dvi) |
            (noise_floor_dvi != noise_floor_prev_dvi))
        m.d.dvi += [
            spectrum_mode_prev_dvi.eq(spectrum_mode_dvi),
            spectrum_style_prev_dvi.eq(spectrum_style_dvi),
            spectrum_bands_prev_dvi.eq(spectrum_bands_dvi),
            spectrum_scale_prev_dvi.eq(spectrum_scale_dvi),
            range_prev_dvi.eq(range_dvi),
            noise_floor_prev_dvi.eq(noise_floor_dvi),
        ]
        with m.If(spectrum_mode_dvi &
                  (~spectrum_mode_prev_dvi | spectrum_peak_config_changed)):
            m.d.dvi += [
                spectrum_peak_epoch.eq(~spectrum_peak_epoch),
                spectrum_peak_reset_holdoff.eq(7),
                spectrum_peak_clear_active.eq(1),
                spectrum_peak_clear_addr.eq(0),
                spectrum_peak_raw_prev.eq(0),
                spectrum_peak_curve_start.eq(0),
                spectrum_peak_curve_end.eq(0),
            ]
        with m.Elif(spectrum_peak_reset_holdoff != 0):
            m.d.dvi += spectrum_peak_reset_holdoff.eq(
                spectrum_peak_reset_holdoff - 1)
        with m.If(spectrum_peak_clear_active):
            with m.If(spectrum_peak_clear_addr == 255):
                m.d.dvi += spectrum_peak_clear_active.eq(0)
            with m.Else():
                m.d.dvi += spectrum_peak_clear_addr.eq(
                    spectrum_peak_clear_addr + 1)

        # Prefetch bin one immediately before each curve scanline. Curve X
        # then addresses the following endpoint, allowing interpolation
        # between adjacent FFT bins with only one BRAM read port.
        with m.If(spectrum_calc_prefetch):
            m.d.dvi += [
                spectrum_curve_raw_prev.eq(spectrum_display_level),
                spectrum_curve_log_start.eq(spectrum_display_level),
                spectrum_curve_log_end.eq(spectrum_display_level),
                spectrum_peak_raw_prev.eq(spectrum_peak_level),
                spectrum_peak_curve_start.eq(spectrum_peak_level),
                spectrum_peak_curve_end.eq(spectrum_peak_level),
            ]
        with m.Elif(spectrum_calc_plot):
            with m.If(spectrum_calc_band_first):
                m.d.dvi += [
                    spectrum_curve_raw_prev.eq(spectrum_display_level),
                    spectrum_curve_log_start.eq(spectrum_curve_log_end),
                    spectrum_curve_log_end.eq(spectrum_curve_target),
                    spectrum_peak_raw_prev.eq(spectrum_peak_level),
                    spectrum_peak_curve_start.eq(spectrum_peak_curve_end),
                    spectrum_peak_curve_end.eq(spectrum_peak_level),
                ]

        # Interpolate between neighboring FFT bins using the fractional part
        # of the log-axis coordinate. This preserves the analyzer-like log
        # scale without turning repeated low-frequency bins into flat-topped
        # rectangles.
        spectrum_frac_signed = Signal(signed(5))
        spectrum_frac_pipe = Signal(signed(5))
        m.d.comb += [
            spectrum_frac_signed.eq(Cat(
                spectrum_calc_log_frac[4:8], Const(0, 1))),
            spectrum_curve_product_next.eq(
                spectrum_curve_delta_pipe * spectrum_frac_pipe),
            spectrum_peak_curve_product_next.eq(
                spectrum_peak_curve_delta_pipe * spectrum_frac_pipe),
        ]

        # Register both sides of the interpolation multipliers. Peak reset
        # selection and endpoint subtraction therefore finish before the DSP
        # input, while the multiplier output remains independently registered
        # before screen-space conversion.
        m.d.dvi += [
            spectrum_curve_delta_pipe.eq(spectrum_curve_delta),
            spectrum_curve_base_q4_pipe.eq(
                spectrum_curve_log_start_effective << 4),
            spectrum_peak_curve_delta_pipe.eq(spectrum_peak_curve_delta),
            spectrum_peak_curve_base_q4_pipe.eq(
                spectrum_peak_curve_start_effective << 4),
            spectrum_frac_pipe.eq(spectrum_frac_signed),
            spectrum_pre_plot.eq(spectrum_calc_plot),
            spectrum_pre_style.eq(spectrum_style_dvi),
            spectrum_pre_band_gap.eq(spectrum_calc_band_gap),
            spectrum_pre_log_underflow.eq(spectrum_calc_log_underflow),
            spectrum_pre_scan_y.eq(spectrum_calc_scan_y),
            spectrum_pre_level.eq(spectrum_display_level),
            spectrum_pre_focus.eq(spectrum_focus_display_level),
            spectrum_pre_peak_level.eq(spectrum_peak_level),
            spectrum_pre_color.eq(spectrum_calc_color),
            spectrum_pre_dither.eq(spectrum_calc_dither),
        ]

        m.d.dvi += [
            spectrum_curve_product.eq(spectrum_curve_product_next),
            spectrum_curve_base_q4.eq(spectrum_curve_base_q4_pipe),
            spectrum_peak_curve_product.eq(
                spectrum_peak_curve_product_next),
            spectrum_peak_curve_base_q4.eq(
                spectrum_peak_curve_base_q4_pipe),
            spectrum_pipe_plot.eq(spectrum_pre_plot),
            spectrum_pipe_style.eq(spectrum_pre_style),
            spectrum_pipe_band_gap.eq(spectrum_pre_band_gap),
            spectrum_pipe_log_underflow.eq(spectrum_pre_log_underflow),
            spectrum_pipe_scan_y.eq(spectrum_pre_scan_y),
            spectrum_pipe_level.eq(spectrum_pre_level),
            spectrum_pipe_focus.eq(spectrum_pre_focus),
            spectrum_pipe_peak_level.eq(spectrum_pre_peak_level),
            spectrum_pipe_color.eq(spectrum_pre_color),
            spectrum_pipe_dither.eq(spectrum_pre_dither),
        ]

        # Split fixed-point curve generation from raster hit-testing. This
        # one-pixel pipeline boundary keeps BRAM, smoothing and interpolation
        # off the final DVI output-priority path.
        m.d.dvi += [
            spectrum_render_plot.eq(spectrum_pipe_plot),
            spectrum_render_style.eq(spectrum_pipe_style),
            spectrum_render_shape.eq(spectrum_shape_pixel),
            spectrum_render_y.eq(spectrum_y),
            spectrum_render_scan_y.eq(spectrum_pipe_scan_y),
            spectrum_render_peak_enabled.eq(
                (spectrum_peaks_dvi != 0) &
                (spectrum_pipe_peak_level != 0) &
                ~spectrum_peak_reset_active),
            spectrum_render_peak_y.eq(spectrum_peak_display_y),
            spectrum_render_peak_level.eq(spectrum_peak_display_level),
            spectrum_render_fill_enabled.eq(spectrum_fill_dvi != 0),
            spectrum_render_fill_raw.eq(spectrum_fill_level),
            spectrum_render_glow_raw.eq(spectrum_curve_glow_level),
            spectrum_render_highlight.eq(spectrum_highlight_dvi),
            spectrum_render_focus_peak.eq(spectrum_focus_peak),
            spectrum_render_focus_dim.eq(spectrum_focus_dim),
            spectrum_render_focus_center.eq(spectrum_focus_center),
            spectrum_render_focus_shoulder.eq(spectrum_focus_shoulder),
            spectrum_render_color.eq(Mux(
                spectrum_fill_is_freq,
                spectrum_frequency_color,
                hue_dvi)),
            spectrum_trace_color.eq(Mux(
                spectrum_fill_is_freq,
                spectrum_axis_color,
                spectrum_render_color)),
            spectrum_grid_level.eq(Mux(spectrum_fill_is_freq, 5, 2)),
            spectrum_axis_level.eq(Mux(spectrum_fill_is_freq, 12, 10)),
            spectrum_axis_color.eq(Mux(spectrum_fill_is_freq, 15, hue_dvi)),
        ]

        m.d.comb += [
            spectrum_log_level_valid.eq(1),
            spectrum_peak_reset_active.eq(
                spectrum_peak_config_changed |
                (spectrum_peak_reset_holdoff != 0) |
                spectrum_peak_clear_active),
            spectrum_display_level_raw.eq(spectrum_calc_level),
            spectrum_display_level.eq(
                apply_display_floor(spectrum_calc_level)),
            spectrum_focus_display_level.eq(spectrum_calc_focus),
            spectrum_curve_target.eq(spectrum_display_level),
            spectrum_curve_log_start_effective.eq(Mux(
                spectrum_calc_band_first,
                spectrum_curve_log_end,
                spectrum_curve_log_start)),
            spectrum_curve_log_end_effective.eq(Mux(
                spectrum_calc_band_first,
                spectrum_curve_target,
                spectrum_curve_log_end)),
            spectrum_curve_delta.eq(
                Cat(spectrum_curve_log_end_effective,
                    Const(0, 1)).as_signed() -
                Cat(spectrum_curve_log_start_effective,
                    Const(0, 1)).as_signed()),
            spectrum_curve_display_q4.eq(
                spectrum_curve_base_q4 + spectrum_curve_product),
            spectrum_curve_level.eq(Mux(
                spectrum_pipe_log_underflow,
                0,
                spectrum_curve_display_q4[4:10])),
            spectrum_peak_curve_start_effective.eq(Mux(
                spectrum_calc_band_first,
                spectrum_peak_curve_end,
                spectrum_peak_curve_start)),
            spectrum_peak_curve_end_effective.eq(Mux(
                spectrum_calc_band_first,
                spectrum_peak_level,
                spectrum_peak_curve_end)),
            spectrum_peak_curve_delta.eq(
                Cat(spectrum_peak_curve_end_effective,
                    Const(0, 1)).as_signed() -
                Cat(spectrum_peak_curve_start_effective,
                    Const(0, 1)).as_signed()),
            spectrum_peak_curve_display_q4.eq(
                spectrum_peak_curve_base_q4 +
                spectrum_peak_curve_product),
            # Keep four fractional amplitude bits through the
            # screen-space conversion. At 720p this improves the vertical
            # granularity from eight pixels to half a pixel before rounding.
            spectrum_height_q4.eq(Mux(
                spectrum_pipe_log_underflow,
                0,
                Mux(spectrum_pipe_style,
                    spectrum_curve_display_q4.as_unsigned(),
                    spectrum_pipe_level << 4))),
            spectrum_height.eq(_dbfs_level_q4_to_height(
                spectrum_height_q4, y_scale_shift)),
            spectrum_y.eq(plot_h - 1 - spectrum_height),
            spectrum_scan_y.eq(spectrum_pipe_scan_y),
            spectrum_shape_pixel.eq(
                spectrum_pipe_style | ~spectrum_pipe_band_gap),
            spectrum_line_hit.eq(
                spectrum_render_plot & Mux(
                    spectrum_render_style,
                    spectrum_render_scan_y == spectrum_render_y,
                    spectrum_render_shape &
                    (spectrum_render_scan_y >= spectrum_render_y - 1) &
                    (spectrum_render_scan_y <= spectrum_render_y + 1))),
            spectrum_curve_glow_hit.eq(
                spectrum_render_plot &
                spectrum_render_style &
                (spectrum_render_scan_y == spectrum_render_y + 1)),
            spectrum_curve_glow_level.eq(2),
            # Hi-lite mode emphasizes the detected fundamental and harmonics
            # 2..5 consistently once the fundamental anchor is found. The
            # center bin is bright and +/-1 bins are dimmer so harmonics stay
            # readable without turning into broad columns.
            spectrum_focus_peak.eq(~spectrum_highlight_dvi |
                                   (spectrum_pipe_focus != 0)),
            spectrum_focus_dim.eq(spectrum_highlight_dvi &
                                  ~spectrum_focus_peak),
            spectrum_focus_center.eq(spectrum_highlight_dvi &
                                     (spectrum_pipe_focus >= 15)),
            spectrum_focus_shoulder.eq(spectrum_highlight_dvi &
                                       (spectrum_pipe_focus != 0) &
                                       (spectrum_pipe_focus < 15)),
            spectrum_focus_fill_boost.eq(Mux(
                spectrum_render_focus_center,
                3,
                Mux(spectrum_render_focus_shoulder, 1, 0))),
            spectrum_focus_fill_ext.eq(
                spectrum_render_fill_raw + spectrum_focus_fill_boost),
            spectrum_focus_glow_ext.eq(
                spectrum_render_glow_raw + Mux(
                    spectrum_render_focus_center,
                    2,
                    Mux(spectrum_render_focus_shoulder, 1, 0))),
            spectrum_line_level.eq(Mux(
                spectrum_render_highlight,
                Mux(spectrum_render_focus_center,
                    12,
                    Mux(spectrum_render_focus_shoulder, 7, 0)),
                15)),
            spectrum_curve_glow_level_focused.eq(Mux(
                spectrum_render_focus_dim,
                Mux(spectrum_render_glow_raw > 1,
                    spectrum_render_glow_raw >> 1,
                    spectrum_render_glow_raw),
                Mux(spectrum_render_focus_peak & spectrum_render_highlight,
                    Mux(spectrum_focus_glow_ext > 9,
                        9,
                        spectrum_focus_glow_ext[:4]),
                    spectrum_render_glow_raw))),
            spectrum_render_line_level.eq(spectrum_line_level),
            spectrum_render_glow_level.eq(
                spectrum_curve_glow_level_focused),
            spectrum_fill_hit.eq(
                spectrum_render_plot &
                spectrum_render_shape & spectrum_render_fill_enabled &
                (spectrum_render_scan_y > spectrum_render_y)),
            spectrum_peak_state_epoch.eq(spectrum_calc_peak_state[11]),
            spectrum_peak_state_valid.eq(
                (spectrum_peak_state_epoch == spectrum_peak_epoch) &
                ~spectrum_peak_reset_active),
            spectrum_peak_level.eq(Mux(
                spectrum_peak_state_valid &
                ~spectrum_calc_log_underflow,
                spectrum_calc_peak_state[:6],
                0)),
            spectrum_peak_hold.eq(Mux(
                spectrum_peak_state_valid,
                spectrum_calc_peak_state[6:11],
                0)),
            spectrum_peak_height_q4.eq(Mux(
                spectrum_pipe_style,
                spectrum_peak_curve_display_q4.as_unsigned(),
                spectrum_pipe_peak_level << 4)),
            spectrum_peak_y.eq(plot_h - 1 - _dbfs_level_q4_to_height(
                spectrum_peak_height_q4, y_scale_shift)),
            spectrum_peak_display_y.eq(spectrum_peak_y),
            spectrum_peak_hit.eq(
                spectrum_render_plot &
                spectrum_render_peak_enabled &
                Mux(spectrum_render_style,
                    spectrum_render_scan_y == spectrum_render_peak_y,
                    spectrum_render_shape &
                    (spectrum_render_scan_y == spectrum_render_peak_y))),
            spectrum_peak_display_level.eq(Mux(
                spectrum_pipe_peak_level[2:6] < 8,
                8,
                spectrum_pipe_peak_level[2:6])),
            spectrum_peak_update.eq(
                (spectrum_calc_prefetch |
                 (spectrum_calc_plot & spectrum_calc_band_first)) &
                (spectrum_calc_scan_y == 0) &
                ~spectrum_peak_reset_active & ~freeze_active_dvi),
            spectrum_peak_hold_init.eq(Mux(
                spectrum_peaks_dvi == 1, 4,
                Mux(spectrum_peaks_dvi == 2, 12,
                    Mux(spectrum_peaks_dvi == 3, 24, 31)))),
            spectrum_peak_decay_tick.eq(Mux(
                spectrum_peaks_dvi == 1, 1,
                Mux(spectrum_peaks_dvi == 2,
                    spectrum_peak_frame[0] == 0,
                    Mux(spectrum_peaks_dvi == 3,
                        spectrum_peak_frame[:2] == 0,
                        Mux(spectrum_peaks_dvi == 4,
                            spectrum_peak_frame == 0,
                            0))))),
            spectrum_gradient_height.eq(plot_h - spectrum_scan_y),
            # Normalize both 256- and 512-pixel plot heights into a common
            # fixed-point 2..11 intensity ramp.
            spectrum_gradient_ext.eq(
                32 + (spectrum_gradient_height >> y_scale_shift)),
            spectrum_gradient_clamped.eq(Mux(
                spectrum_gradient_ext > 176,
                176,
                spectrum_gradient_ext[:8])),
            spectrum_gradient_base.eq(spectrum_gradient_clamped[4:8]),
            spectrum_gradient_frac.eq(spectrum_gradient_clamped[:4]),
            spectrum_gradient_level.eq(Mux(
                (spectrum_gradient_frac > spectrum_pipe_dither) &
                (spectrum_gradient_base < 15),
                spectrum_gradient_base + 1,
                spectrum_gradient_base)),
            spectrum_fill_is_gradient.eq(
                (spectrum_fill_dvi == 2) |
                (spectrum_fill_dvi == 4) |
                (spectrum_fill_dvi == 5) |
                (spectrum_fill_dvi == 6)),
            spectrum_fill_is_freq.eq(
                (spectrum_fill_dvi == 5) |
                (spectrum_fill_dvi == 6)),
            spectrum_fill_is_gradient_reverse.eq(spectrum_fill_dvi == 4),
            spectrum_fill_is_freq_reverse.eq(spectrum_fill_dvi == 6),
            spectrum_gradient_fill_level.eq(Mux(
                spectrum_fill_is_gradient_reverse,
                15 - spectrum_gradient_level,
                spectrum_gradient_level)),
            spectrum_frequency_color.eq(Mux(
                spectrum_fill_is_freq_reverse,
                15 - spectrum_pipe_color,
                spectrum_pipe_color)),
            # Non-frequency gradients vary brightness vertically but keep the
            # selected palette's hue column stable. Frequency gradients vary
            # hue/color by X position and use brightness for fill intensity.
            # Amplitude fill gives every bar/curve column one palette index
            # derived from its measured level. Heat-map palettes therefore
            # color low and high bands differently across their entire fill.
            spectrum_amplitude_level.eq(Mux(
                spectrum_pipe_style,
                spectrum_curve_level[2:6],
                spectrum_pipe_level[2:6])),
            spectrum_fill_level.eq(Mux(
                spectrum_fill_dvi == 1,
                4,
                Mux(spectrum_fill_is_gradient,
                    spectrum_gradient_fill_level,
                    spectrum_amplitude_level))),
            spectrum_fill_level_focused.eq(Mux(
                spectrum_render_focus_dim,
                spectrum_render_fill_raw >> 1,
                Mux(spectrum_render_highlight & spectrum_render_focus_peak,
                    Mux(spectrum_focus_fill_ext > 13,
                        13,
                        spectrum_focus_fill_ext[:4]),
                    spectrum_render_fill_raw))),
            spectrum_render_fill_level.eq(spectrum_fill_level_focused),
            spectrum_peak_level_next.eq(Mux(
                spectrum_peaks_dvi == 0,
                spectrum_display_level,
                Mux(~spectrum_peak_state_valid |
                    (spectrum_display_level >= spectrum_peak_level),
                    spectrum_display_level,
                    Mux((spectrum_peaks_dvi == 5) |
                        (spectrum_peak_hold != 0),
                        spectrum_peak_level,
                        Mux(spectrum_peak_decay_tick &
                            (spectrum_peak_level != 0),
                            spectrum_peak_level - 1,
                            spectrum_peak_level))))),
            spectrum_peak_hold_next.eq(Mux(
                spectrum_peaks_dvi == 0,
                0,
                Mux(~spectrum_peak_state_valid |
                    (spectrum_display_level >= spectrum_peak_level),
                    spectrum_peak_hold_init,
                    Mux(spectrum_peaks_dvi == 5,
                        31,
                        Mux(spectrum_peak_hold != 0,
                            spectrum_peak_hold - 1,
                            0))))),
            spectrum_peak_w.en.eq(
                spectrum_peak_clear_active | spectrum_peak_update),
            spectrum_peak_w.addr.eq(Mux(
                spectrum_peak_clear_active,
                spectrum_peak_clear_addr,
                spectrum_calc_band)),
            spectrum_peak_w.data.eq(Mux(
                spectrum_peak_clear_active,
                0,
                Cat(spectrum_peak_level_next,
                    spectrum_peak_hold_next,
                    spectrum_peak_epoch))),
        ]

        # Register the spectrum/axis-line result separately from axis glyphs.
        # The final stage below overlays the pipelined glyph without extending
        # the history-BRAM rendering path.
        base_o = Signal(ScanPixel)
        base_o_d = Signal(ScanPixel)
        base_o_dd = Signal(ScanPixel)
        base_ui_clear = Signal()
        base_ui_clear_d = Signal()
        base_ui_clear_dd = Signal()
        history_render_level = Signal(4)
        history_render_plot = Signal()
        ui_clear = Signal()
        m.d.comb += ui_clear.eq(
            (scan_d.pixel.intensity == 0) & ~menu_protect_d)
        m.d.dvi += [
            base_o.eq(scan_d),
            base_ui_clear.eq(ui_clear),
        ]
        with m.If(enable_dvi & ui_clear & spectrum_peak_hit):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_render_peak_level),
                base_o.pixel.color.eq(Mux(
                    spectrum_fill_is_freq,
                    spectrum_trace_color,
                    hue_dvi + 8)),
            ]
        with m.Elif(enable_dvi & ui_clear & spectrum_line_hit):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_render_line_level),
                base_o.pixel.color.eq(spectrum_trace_color),
            ]
        with m.Elif(enable_dvi & ui_clear & spectrum_curve_glow_hit):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_render_glow_level),
                base_o.pixel.color.eq(spectrum_trace_color),
            ]
        with m.Elif(enable_dvi & ui_clear & spectrum_fill_hit):
            with m.If(scan_d.pixel.intensity < spectrum_render_fill_level):
                m.d.dvi += [
                    base_o.pixel.intensity.eq(spectrum_render_fill_level),
                    base_o.pixel.color.eq(spectrum_render_color),
                ]
        with m.Elif(enable_dvi & ~menu_protect_d & spectrum_grid_hit_d):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_grid_level),
                base_o.pixel.color.eq(spectrum_axis_color),
            ]
        with m.Elif(enable_dvi & ~menu_protect_d & axes_dvi & axes_hit_d):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_axis_level),
                base_o.pixel.color.eq(spectrum_axis_color),
            ]

        # Match the extra label-selection stage. Spectrum, grid, menu, and
        # history pixels all advance together so the new timing boundary does
        # not introduce a one-pixel displacement.
        m.d.dvi += [
            base_o_d.eq(base_o),
            base_o_dd.eq(base_o_d),
            base_ui_clear_d.eq(base_ui_clear),
            base_ui_clear_dd.eq(base_ui_clear_d),
            history_render_level.eq(display_level),
            history_render_plot.eq(history_pre_plot),
            self.o.eq(base_o_dd),
        ]
        with m.If(enable_dvi & base_ui_clear_dd & history_render_plot &
                  (history_render_level != 0) &
                  (history_render_level > base_o_dd.pixel.intensity)):
            m.d.dvi += [
                self.o.pixel.intensity.eq(history_render_level),
                self.o.pixel.color.eq(hue_dvi),
            ]
        with m.Elif(enable_dvi & base_ui_clear_dd & axes_dvi & label_hit_d):
            m.d.dvi += [
                self.o.pixel.intensity.eq(spectrum_axis_level),
                self.o.pixel.color.eq(spectrum_axis_color),
            ]

        return m
