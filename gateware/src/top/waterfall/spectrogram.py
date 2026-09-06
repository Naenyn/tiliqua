# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Streaming spectral analysis and projected 3D waterfall display."""

import math
import os

from amaranth import *
from amaranth.lib import data, fifo, memory, stream, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from tiliqua import dsp
from tiliqua.dsp import ASQ
from tiliqua.raster.line import LineCmd, LineStripCmd
from tiliqua.raster.triangle import TriangleCmd
from tiliqua.video.types import Pixel, ScanPixel


FFT_SIZE = 512
N_BINS = FFT_SIZE // 2
# The projected view draws exactly sixteen ridges. Keeping older, unreachable
# columns consumed 24 of the device's 56 EBRs and made routing unnecessarily
# difficult, so the capture ring now matches the visible history depth.
HISTORY_COLS = 16
HISTORY_COL_BITS = (HISTORY_COLS - 1).bit_length()
HISTORY_ADDR_BITS = HISTORY_COL_BITS + 8
SPECTRUM_DB_FLOOR = -96.0
SPECTRUM_CORDIC_GAIN = dsp.cordic.RectToPolarCordic.K


class ProjectedPoint(data.Struct):
    """One projected mesh vertex retained while building adjacent cells."""

    x: signed(12)
    y: signed(12)
    level: unsigned(6)


def _magnitude_raw_to_dbfs_level(raw, *, f_bits=ASQ.f_bits):
    """Convert an uncorrected Hann/FFT/CORDIC magnitude to 0..63 dBFS.

    The forward FFT is normalized by 1/N. A real, bin-centred full-scale
    sinusoid contributes half its amplitude to the positive spectrum and the
    Hann window has a coherent gain of one half, while the magnitude CORDIC is
    intentionally left at its gain K. Consequently ``raw / 2**f_bits`` needs
    a factor of ``4/K`` to become conventional single-sided amplitude.
    """
    if raw <= 0:
        return 0
    amplitude = (raw / (1 << f_bits)) * (4.0 / SPECTRUM_CORDIC_GAIN)
    dbfs = 20.0 * math.log10(amplitude)
    normalized = (dbfs - SPECTRUM_DB_FLOOR) / -SPECTRUM_DB_FLOOR
    return max(0, min(63, round(normalized * 63)))


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


def _three_d_scan_geometry(high_quality):
    """Return the final vertex and bin-group shift for a 256-bin sweep."""
    return (
        Mux(high_quality, 127, 63),
        Mux(high_quality, 1, 2),
    )


def _three_d_frequency_coordinate(point, high_quality):
    """Spread 64 or 128 3D vertices across the complete 0..255 axis."""
    return Mux(
        high_quality,
        (point << 1) + (point >> 6),
        _dbfs_level_to_height(point, Const(0)),
    )


def _terrain_visibility_level(level, age, age_fade):
    """Return the post-age level used for fading and visibility culling.

    Level-colored terrain keeps its original amplitude color while the palette
    fades RGB brightness with age.  Applying the same age envelope separately
    here lets sufficiently quiet old facets disappear without moving surviving
    facets through the amplitude palette. Two display levels per history step
    make the complete depth range legible without changing hue.
    """
    age_penalty = age << 1
    return Mux(
        age_fade,
        Mux(level > age_penalty, level - age_penalty, 0),
        level,
    )


def _log_frequency_bin_buckets(point_count, n_bins=N_BINS):
    """Return inclusive FFT-bin bounds for an octave-spaced 3D sweep.

    Bin zero is DC and is intentionally omitted. Repeated low-frequency
    buckets are useful here: there are more display vertices than distinct
    integer FFT bins in the first few octaves, so repetition produces a
    continuous surface instead of holes near the origin.
    """
    if point_count < 2 or n_bins < 2:
        raise ValueError("log-frequency geometry needs at least two points/bins")
    edges = [
        max(1, min(n_bins, round(n_bins ** (index / point_count))))
        for index in range(point_count + 1)
    ]
    return [
        (min(edges[index], n_bins - 1),
         max(min(edges[index], n_bins - 1),
             min(edges[index + 1] - 1, n_bins - 1)))
        for index in range(point_count)
    ]


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
        exponent_table = []
        for exponent_value in range(1 << exponent_bits):
            representative = (1 << exponent_value) * (1.0 + 0.5 / 16.0)
            exponent_table.append(_magnitude_raw_to_dbfs_level(
                representative, f_bits=self.shape.f_bits))
        mantissa_table = []
        mantissa_base = 1.0 + 0.5 / 16.0
        for mantissa_value in range(16):
            ratio = (1.0 + (mantissa_value + 0.5) / 16.0) / mantissa_base
            correction_db = 20.0 * math.log10(ratio)
            mantissa_table.append(round(correction_db * 63 / 96))
        exponent_levels = Array(Const(level, 6) for level in exponent_table)
        mantissa_levels = Array(Const(level, 3) for level in mantissa_table)

        lookup_exponent = Signal.like(exponent)
        lookup_mantissa = Signal.like(mantissa)
        input_zero = Signal()
        output_first = Signal()
        output_level = Signal(6)
        level_sum = Signal(7)

        m.d.comb += [
            raw.eq(self.i.payload.sample.as_value()),
            exponent.eq(0),
            mantissa.eq(0),
            level_sum.eq(
                exponent_levels[lookup_exponent]
                + mantissa_levels[lookup_mantissa]),
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
                    input_zero, 0, Mux(level_sum > 63, 63, level_sum)))
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
        output_level = Signal(6)
        output_first = Signal()
        previous_level = Signal(6)
        rising = Signal()
        delta = Signal(7)
        selected_shift = Signal(2)
        step_next = Signal(7)
        step = Signal(7)
        smoothed = Signal(7)
        m.d.comb += [
            mem_r.addr.eq(index),
            mem_w.addr.eq(index),
        ]
        with m.Switch(selected_shift):
            with m.Case(0):
                m.d.comb += step_next.eq(delta)
            with m.Case(1):
                m.d.comb += step_next.eq((delta + 1) >> 1)
            with m.Case(2):
                m.d.comb += step_next.eq((delta + 3) >> 2)
            with m.Default():
                m.d.comb += step_next.eq((delta + 7) >> 3)
        m.d.comb += smoothed.eq(Mux(
            rising,
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
                # Isolate the asynchronous distributed-RAM read from the EMA
                # arithmetic. Keeping the RAM, comparison, rounded shift and
                # final add in one cycle was WATERFALL's system-clock path.
                m.d.sync += [
                    previous_level.eq(mem_r.data),
                    rising.eq(input_level >= mem_r.data),
                    delta.eq(Mux(
                        input_level >= mem_r.data,
                        input_level - mem_r.data,
                        mem_r.data - input_level)),
                    selected_shift.eq(Mux(
                        input_level >= mem_r.data,
                        self.attack_shift,
                        self.release_shift)),
                ]
                m.next = "CALCULATE_STEP"
            with m.State("CALCULATE_STEP"):
                m.d.sync += step.eq(step_next)
                m.next = "WRITE"
            with m.State("WRITE"):
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

    WATERFALL observes a non-blocking tap of the codec stream, so the producer
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
        # distributed RAM rather than consuming one of WATERFALL's full EBRs.
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


class Spectrogram(wiring.Component):
    """512-point STFT feeding a projected, double-buffered 3D surface."""

    class Flags(csr.Register, access="w"):
        enable: csr.Field(csr.action.W, unsigned(1))
        axes: csr.Field(csr.action.W, unsigned(1))
        input_ch: csr.Field(csr.action.W, unsigned(2))
        display_ack: csr.Field(csr.action.W, unsigned(1))

    class Gain(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(4))

    class Range(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(2))

    class Rate(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(2))

    class Hue(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(4))

    class NoiseFloor(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(2))

    class Timings(csr.Register, access="w"):
        h_active: csr.Field(csr.action.W, unsigned(12))
        v_active: csr.Field(csr.action.W, unsigned(12))

    class Status(csr.Register, access="r"):
        display_buffer: csr.Field(csr.action.R, unsigned(1))
        surface_valid: csr.Field(csr.action.R, unsigned(1))
        renderer_idle: csr.Field(csr.action.R, unsigned(1))

    class Config3d(csr.Register, access="w"):
        quality: csr.Field(csr.action.W, unsigned(2))
        style: csr.Field(csr.action.W, unsigned(1))
        log_scale: csr.Field(csr.action.W, unsigned(1))
        age_fade: csr.Field(csr.action.W, unsigned(1))
        frequency_color: csr.Field(csr.action.W, unsigned(1))
        ridges: csr.Field(csr.action.W, unsigned(1))

    class ProjectionX(csr.Register, access="w"):
        frequency: csr.Field(csr.action.W, signed(10))
        amplitude: csr.Field(csr.action.W, signed(10))
        time: csr.Field(csr.action.W, signed(10))

    class ProjectionY(csr.Register, access="w"):
        frequency: csr.Field(csr.action.W, signed(10))
        amplitude: csr.Field(csr.action.W, signed(10))
        time: csr.Field(csr.action.W, signed(10))

    def __init__(self, *, fs):
        self.fs = fs

        regs = csr.Builder(addr_width=6, data_width=8)
        self._flags = regs.add("flags", self.Flags(), offset=0x00)
        self._gain = regs.add("gain", self.Gain(), offset=0x04)
        self._range = regs.add("range", self.Range(), offset=0x08)
        self._rate = regs.add("rate", self.Rate(), offset=0x0c)
        self._hue = regs.add("hue", self.Hue(), offset=0x14)
        self._timings = regs.add("timings", self.Timings(), offset=0x18)
        self._status = regs.add("status", self.Status(), offset=0x1c)
        self._projection_x = regs.add(
            "projection_x", self.ProjectionX(), offset=0x20)
        self._projection_y = regs.add(
            "projection_y", self.ProjectionY(), offset=0x24)
        self._config_3d = regs.add(
            "config_3d", self.Config3d(), offset=0x28)
        self._noise_floor = regs.add(
            "noise_floor", self.NoiseFloor(), offset=0x30)
        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            "audio_i": In(stream.Signature(data.ArrayLayout(ASQ, 4))),
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "line_o": Out(stream.Signature(LineCmd)),
            "triangle_o": Out(stream.Signature(TriangleCmd)),
            "ridges_enabled": Out(1),
            "line_busy": In(1),
            "flush_request": Out(1),
            "flush_done": In(1),
            "clear_request": Out(1),
            "clear_done": In(1),
            "clear_busy": In(1),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        enable = Signal(init=1)
        axes = Signal(init=1)
        display_ack = Signal()
        input_ch = Signal(2)
        gain = Signal(4)
        range_sel = Signal(2)
        rate_sel = Signal(2, init=2)
        hue = Signal(4, init=5)
        noise_floor = Signal(2)
        quality_3d = Signal(2, init=1)
        terrain_style = Signal(init=1)
        log_scale = Signal(init=1)
        age_fade = Signal(init=1)
        frequency_color = Signal()
        ridges = Signal(init=1)
        h_active = Signal(12, init=720)
        v_active = Signal(12, init=720)
        projection_x = [Signal(signed(10), init=value) for value in (384, 0, 90)]
        projection_y = [Signal(signed(10), init=value) for value in (0, -320, -96)]

        m.d.comb += self.ridges_enabled.eq(ridges)

        with m.If(self._flags.element.w_stb):
            m.d.sync += [
                enable.eq(self._flags.f.enable.w_data),
                axes.eq(self._flags.f.axes.w_data),
                input_ch.eq(self._flags.f.input_ch.w_data),
                display_ack.eq(self._flags.f.display_ack.w_data),
            ]
        with m.If(self._gain.element.w_stb):
            m.d.sync += gain.eq(self._gain.f.value.w_data)
        with m.If(self._range.element.w_stb):
            m.d.sync += range_sel.eq(self._range.f.value.w_data)
        with m.If(self._rate.element.w_stb):
            m.d.sync += rate_sel.eq(self._rate.f.value.w_data)
        with m.If(self._hue.element.w_stb):
            m.d.sync += hue.eq(self._hue.f.value.w_data)
        with m.If(self._noise_floor.element.w_stb):
            m.d.sync += noise_floor.eq(self._noise_floor.f.value.w_data)
        with m.If(self._timings.element.w_stb):
            m.d.sync += [
                h_active.eq(self._timings.f.h_active.w_data),
                v_active.eq(self._timings.f.v_active.w_data),
            ]
        with m.If(self._projection_x.element.w_stb):
            m.d.sync += [
                projection_x[0].eq(self._projection_x.f.frequency.w_data),
                projection_x[1].eq(self._projection_x.f.amplitude.w_data),
                projection_x[2].eq(self._projection_x.f.time.w_data),
            ]
        with m.If(self._projection_y.element.w_stb):
            m.d.sync += [
                projection_y[0].eq(self._projection_y.f.frequency.w_data),
                projection_y[1].eq(self._projection_y.f.amplitude.w_data),
                projection_y[2].eq(self._projection_y.f.time.w_data),
            ]
        with m.If(self._config_3d.element.w_stb):
            m.d.sync += [
                quality_3d.eq(self._config_3d.f.quality.w_data),
                terrain_style.eq(self._config_3d.f.style.w_data),
                log_scale.eq(self._config_3d.f.log_scale.w_data),
                age_fade.eq(self._config_3d.f.age_fade.w_data),
                frequency_color.eq(self._config_3d.f.frequency_color.w_data),
                ridges.eq(self._config_3d.f.ridges.w_data),
            ]
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
        if os.environ.get("TILIQUA_WATERFALL_TEST_TONE", "0") == "1":
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

        # The 3D renderer scans the compact history RAM, then crosses projected
        # line-strip commands into the system clock domain. Only commands need
        # buffering; the spectral history remains shared with the analyzer.
        m.submodules.line_fifo = line_fifo = fifo.AsyncFIFOBuffered(
            width=LineCmd.as_shape().size,
            depth=8,
            w_domain="dvi",
            r_domain="sync",
        )
        m.submodules.triangle_fifo = triangle_fifo = fifo.AsyncFIFOBuffered(
            width=TriangleCmd.as_shape().size,
            depth=8,
            w_domain="dvi",
            r_domain="sync",
        )
        m.d.comb += [
            self.line_o.valid.eq(line_fifo.r_rdy),
            self.line_o.payload.eq(line_fifo.r_data),
            line_fifo.r_en.eq(line_fifo.r_rdy & self.line_o.ready),
            self.triangle_o.valid.eq(triangle_fifo.r_rdy),
            self.triangle_o.payload.eq(triangle_fifo.r_data),
            triangle_fifo.r_en.eq(
                triangle_fifo.r_rdy & self.triangle_o.ready),
        ]
        line_busy_dvi = Signal()
        flush_done_dvi = Signal()
        clear_done_dvi = Signal()
        clear_busy_dvi = Signal()
        m.submodules.line_busy_ff = FFSynchronizer(
            self.line_busy, line_busy_dvi, o_domain="dvi")
        m.submodules.flush_done_ff = FFSynchronizer(
            self.flush_done, flush_done_dvi, o_domain="dvi")
        m.submodules.clear_done_ff = FFSynchronizer(
            self.clear_done, clear_done_dvi, o_domain="dvi")
        m.submodules.clear_busy_ff = FFSynchronizer(
            self.clear_busy, clear_busy_dvi, o_domain="dvi")

        write_col = Signal(HISTORY_COL_BITS)
        newest_col = Signal(HISTORY_COL_BITS)
        bin_index = Signal(9)
        accept_latched = Signal()

        # A new analyzer frame is accepted only after the renderer finishes a
        # complete surface sweep. This keeps captured columns and visible
        # animation one-to-one without retaining SONORO's independent spectrum
        # update cadence or band-publishing machinery.
        render_token_dvi = Signal()
        render_token_sync = Signal()
        render_ack_sync = Signal()
        render_ack_dvi = Signal()
        render_slot_ready = Signal()
        m.submodules.render_token_ff = FFSynchronizer(
            render_token_dvi, render_token_sync, o_domain="sync")
        m.submodules.render_ack_ff = FFSynchronizer(
            render_ack_sync, render_ack_dvi, o_domain="dvi")
        m.d.comb += render_slot_ready.eq(render_token_sync != render_ack_sync)

        accept_now = Signal()
        current_bin = Signal(9)
        do_write = Signal()
        raw_level = Signal(6)
        boosted_level = Signal(8)
        stored_level = Signal(6)
        m.d.comb += [
            accept_now.eq(enable & render_slot_ready),
            level_smoother.o.ready.eq(1),
            current_bin.eq(Mux(level_smoother.o.payload.first, 0, bin_index)),
            do_write.eq(Mux(
                level_smoother.o.payload.first, accept_now, accept_latched)),
            raw_level.eq(level_smoother.o.payload.sample),
            boosted_level.eq(raw_level + gain),
            # Bin zero represents DC. Suppressing it here prevents converter
            # offset from becoming a false ridge at the frequency-axis origin.
            stored_level.eq(Mux(
                current_bin == 0,
                0,
                Mux(boosted_level > 63, 63, boosted_level[:6]))),
            history_w.en.eq(
                level_smoother.o.valid & do_write & (current_bin < N_BINS)),
            history_w.addr.eq(Cat(current_bin[:8], write_col)),
            history_w.data.eq(stored_level),
        ]

        with m.If(level_smoother.o.valid):
            with m.If(level_smoother.o.payload.first):
                m.d.sync += [
                    bin_index.eq(1),
                    accept_latched.eq(accept_now),
                ]
                with m.If(enable & accept_now):
                    m.d.sync += render_ack_sync.eq(render_token_sync)
            with m.Else():
                m.d.sync += bin_index.eq(bin_index + 1)

            with m.If(do_write & (current_bin == N_BINS - 1)):
                m.d.sync += [
                    newest_col.eq(write_col),
                    write_col.eq(write_col - 1),
                ]


        # ---- DVI-domain circular history projection ------------------------
        enable_dvi = Signal()
        axes_dvi = Signal()
        display_ack_dvi = Signal()
        quality_3d_dvi = Signal(2)
        terrain_style_dvi = Signal()
        log_scale_dvi = Signal()
        age_fade_dvi = Signal()
        frequency_color_dvi = Signal()
        ridges_dvi = Signal()
        rate_dvi = Signal(2)
        hue_dvi = Signal(4)
        noise_floor_dvi = Signal(2)
        h_active_dvi = Signal(12)
        v_active_dvi = Signal(12)
        projection_x_dvi = [Signal(signed(10)) for _ in range(3)]
        projection_y_dvi = [Signal(signed(10)) for _ in range(3)]
        newest_gray = Signal(HISTORY_COL_BITS)
        newest_gray_meta = Signal(HISTORY_COL_BITS)
        newest_binary_meta = Signal(HISTORY_COL_BITS)
        m.d.comb += newest_gray.eq(newest_col ^ (newest_col >> 1))
        for name, src, dst in [
            ("enable", enable, enable_dvi),
            ("axes", axes, axes_dvi),
            ("display_ack", display_ack, display_ack_dvi),
            ("quality_3d", quality_3d, quality_3d_dvi),
            ("terrain_style", terrain_style, terrain_style_dvi),
            ("log_scale", log_scale, log_scale_dvi),
            ("age_fade", age_fade, age_fade_dvi),
            ("frequency_color", frequency_color, frequency_color_dvi),
            ("ridges", ridges, ridges_dvi),
            ("rate", rate_sel, rate_dvi),
            ("h_active", h_active, h_active_dvi),
            ("v_active", v_active, v_active_dvi),
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
        for axis_name, sources, destinations in [
            ("projection_x", projection_x, projection_x_dvi),
            ("projection_y", projection_y, projection_y_dvi),
        ]:
            for index, (src, dst) in enumerate(zip(sources, destinations)):
                setattr(m.submodules, f"{axis_name}_{index}_ff",
                        FFSynchronizer(src, dst, o_domain="dvi"))

        # Gray-code the cross-domain history pointer so a video frame can
        # never latch a mixture of old and new binary pointer bits.
        m.d.comb += newest_binary_meta[-1].eq(newest_gray_meta[-1])
        for bit in range(HISTORY_COL_BITS - 2, -1, -1):
            m.d.comb += newest_binary_meta[bit].eq(
                newest_binary_meta[bit + 1] ^ newest_gray_meta[bit])

        newest_dvi = Signal(HISTORY_COL_BITS)
        prev_vsync = Signal()
        m.d.dvi += prev_vsync.eq(self.i.vsync)
        with m.If(self.i.vsync & ~prev_vsync):
            m.d.dvi += newest_dvi.eq(newest_binary_meta)

        # ---- projected 3D waterfall ---------------------------------------
        # Sixteen spectra are drawn oldest-to-newest so the near surface cells
        # naturally overwrite distant cells without a Z buffer. Wire mode emits
        # frequency ridges; terrain mode joins adjacent rows with filled cells.
        scan_slice = Signal(4)
        scan_point = Signal(7)
        scan_group_base = Signal(8)
        scan_group_last = Signal(3)
        scan_bin_last = Signal(8)
        scan_peak = Signal(6)
        scan_peak_next = Signal(6)
        scan_history_level = Signal(6)
        scan_history_age = Signal(4)
        scan_depth = Signal(8)
        scan_history_bin = Signal(8)
        scan_read_en = Signal()
        scan_read_addr = Signal(HISTORY_ADDR_BITS)
        sweep_newest = Signal(HISTORY_COL_BITS)
        sweep_rate = Signal(2)
        sweep_hue = Signal(4)
        sweep_quality_3d = Signal(2)
        sweep_terrain_style = Signal()
        sweep_log_scale = Signal()
        sweep_age_fade = Signal()
        sweep_frequency_color = Signal()
        sweep_ridges = Signal()
        sweep_projection_x = [Signal(signed(10)) for _ in range(3)]
        sweep_projection_y = [Signal(signed(10)) for _ in range(3)]

        # Logarithmic bin groups are static, so keep their inclusive start/end
        # bounds in one small EBR instead of a large combinational mux. The
        # lower half contains 64-vertex geometry and the upper half 128.
        log_bucket_words = [0] * 256
        for index, (first_bin, last_bin) in enumerate(
                _log_frequency_bin_buckets(64)):
            log_bucket_words[index] = first_bin | (last_bin << 8)
        for index, (first_bin, last_bin) in enumerate(
                _log_frequency_bin_buckets(128)):
            log_bucket_words[128 + index] = first_bin | (last_bin << 8)
        log_bucket_memory = memory.Memory(data=memory.MemoryData(
            shape=unsigned(16), depth=256, init=log_bucket_words))
        m.submodules.log_frequency_buckets = log_bucket_memory
        log_bucket_r = log_bucket_memory.read_port(domain="dvi")

        # Terrain cells need the previous projected frequency row. Ping-pong
        # memories retain 128 x/y/level vertices apiece; while one receives
        # the current row, the other supplies the adjacent historical row.
        row_read_ports = []
        row_write_ports = []
        for index in range(2):
            row_memory = memory.Memory(data=memory.MemoryData(
                shape=ProjectedPoint,
                depth=128,
                init=[0] * 128,
            ))
            setattr(m.submodules, f"terrain_row_{index}", row_memory)
            row_read_ports.append(row_memory.read_port(domain="dvi"))
            row_write_ports.append(row_memory.write_port(domain="dvi"))
        row_bank = Signal()
        row_read_point = Signal(ProjectedPoint)
        contour_row_point = Signal(ProjectedPoint)
        terrain_current_left = Signal(ProjectedPoint)
        terrain_previous_left = Signal(ProjectedPoint)
        terrain_previous_right = Signal(ProjectedPoint)
        contour_left = Signal(ProjectedPoint)
        contour_right = Signal(ProjectedPoint)
        contour_point = Signal(7)
        # Complete surfaces alternate between two physical framebuffers. The
        # old multi-bit generation tags existed only for SONORO persistence.
        visible_generation = Signal()
        draw_generation = Signal()
        completed_generation = Signal()
        render_activity_seen = Signal()
        clear_request = Signal()
        flush_request = Signal()
        completed_generation_sync = Signal()
        surface_valid = Signal()
        surface_valid_sync = Signal()
        renderer_idle_dvi = Signal()
        renderer_idle_sync = Signal()
        m.submodules.completed_generation_ff = FFSynchronizer(
            completed_generation, completed_generation_sync, o_domain="sync")
        m.submodules.surface_valid_ff = FFSynchronizer(
            surface_valid, surface_valid_sync, o_domain="sync")
        m.submodules.renderer_idle_ff = FFSynchronizer(
            renderer_idle_dvi, renderer_idle_sync, o_domain="sync")
        m.d.comb += [
            self.clear_request.eq(clear_request),
            self.flush_request.eq(flush_request),
            self._status.f.display_buffer.r_data.eq(
                completed_generation_sync),
            self._status.f.surface_valid.r_data.eq(surface_valid_sync),
            self._status.f.renderer_idle.r_data.eq(renderer_idle_sync),
        ]

        # In 3D, Rate controls how many complete surface redraws occur before
        # a new analyzer frame is admitted. Tying it to completed sweeps makes
        # the setting visible even when the renderer is the limiting stage.
        render_sweep_count = Signal(3)
        capture_sweep_due = Signal()

        # Projection is deliberately split across four DVI clocks: capture,
        # multiply, sum and enqueue. Besides making the 74.25MHz path safe,
        # this isolates the synchronous EBR read from the DSP input path.
        point_frequency_base = Signal(signed(10))
        point_frequency = Signal(signed(11))
        point_amplitude = Signal(signed(10))
        point_time = Signal(signed(10))
        point_pixel = Signal(Pixel)
        point_cmd = Signal(LineStripCmd)
        point_next = Signal(3)
        products_x = [Signal(signed(22)) for _ in range(3)]
        products_y = [Signal(signed(22)) for _ in range(3)]
        projection_sum_x = Signal(signed(24))
        projection_sum_y = Signal(signed(24))
        projected_x = Signal(signed(12))
        projected_y = Signal(signed(12))
        center_x = Signal(signed(13))
        baseline_y = Signal(signed(13))
        line_word = Signal(LineCmd)
        triangle_word = Signal(TriangleCmd)
        current_projected_point = Signal(ProjectedPoint)
        high_quality = Signal()
        terrain_level = Signal(6)
        terrain_cell_sum = Signal(8)
        terrain_cell_level_next = Signal(6)
        terrain_cell_display_level_next = Signal(6)
        terrain_cell_display_level = Signal(6)
        terrain_cell_visibility_level_next = Signal(6)
        terrain_cell_visible = Signal()
        terrain_cell_frequency_intensity = Signal(4)
        wire_display_level = Signal(6)
        wire_frequency_intensity = Signal(4)
        # Palette packing has only 64 possible level inputs. Keep both the
        # faded (5-bit) and full-resolution (6-bit) codes in one tiny ROM.
        # Two registered read ports serve wire and terrain rendering without
        # spreading a wide constant mux across the already-dense DVI domain.
        palette_code_words = []
        for level in range(64):
            fade_level = level * 15 >> 5
            fade_code = (1 + fade_level % 15) | ((fade_level // 15) << 4)
            full_level = level * 15 >> 4
            full_code = (1 + full_level % 15) | ((full_level // 15) << 4)
            palette_code_words.append(fade_code | (full_code << 5))
        palette_code_memory = memory.Memory(data=memory.MemoryData(
            shape=unsigned(11), depth=64, init=palette_code_words))
        m.submodules.palette_codes = palette_code_memory
        palette_wire_r = palette_code_memory.read_port(domain="dvi")
        palette_terrain_r = palette_code_memory.read_port(domain="dvi")
        frequency_hues = Array(Const(
            1 + ((position * 15) >> 4), 4)
            for position in range(16))
        terrain_fade_code = Signal(5)
        wire_fade_code = Signal(5)
        terrain_full_code = Signal(6)
        wire_full_code = Signal(6)
        terrain_level_color = Signal(4)
        wire_level_color = Signal(4)
        terrain_level_intensity = Signal(4)
        wire_level_intensity = Signal(4)
        scan_point_last = Signal(7)
        scan_group_shift = Signal(2)
        frequency_coordinate = Signal(9)
        sweep_frequency_position = Signal(4)
        sweep_frequency_hue = Signal(4)
        scan_geometry = _three_d_scan_geometry(high_quality)
        terrain_row_read_en = Signal()
        terrain_row_write_en = Signal()
        contour_row_read_en = Signal()

        m.d.comb += [
            terrain_row_read_en.eq(0),
            terrain_row_write_en.eq(0),
            contour_row_read_en.eq(0),
            log_bucket_r.en.eq(0),
            log_bucket_r.addr.eq(Cat(scan_point, high_quality)),
            row_read_point.as_value().eq(Mux(
                row_bank == 0,
                row_read_ports[1].data,
                row_read_ports[0].data)),
            contour_row_point.as_value().eq(Mux(
                row_bank == 0,
                row_read_ports[0].data,
                row_read_ports[1].data)),
        ]
        for index, (read_port, write_port) in enumerate(
                zip(row_read_ports, row_write_ports)):
            m.d.comb += [
                read_port.en.eq(
                    (terrain_row_read_en & (row_bank != index)) |
                    (contour_row_read_en & (row_bank == index))),
                read_port.addr.eq(Mux(
                    contour_row_read_en, contour_point, scan_point)),
                write_port.en.eq(
                    terrain_row_write_en & (row_bank == index)),
                write_port.addr.eq(scan_point),
                write_port.data.eq(current_projected_point),
            ]

        m.d.comb += [
            # Every range now has a matching analyzer sample rate and therefore
            # uses all 256 positive-frequency bins. Pool the complete spectrum
            # into 64 or 128 vertices solely according to the quality setting.
            # The previous range-dependent geometry was inherited from the old
            # fixed-rate analyzer and truncated the 6kHz and 3kHz views.
            high_quality.eq(sweep_quality_3d == 2),
            scan_point_last.eq(scan_geometry[0]),
            scan_group_shift.eq(scan_geometry[1]),
            frequency_coordinate.eq(
                _three_d_frequency_coordinate(scan_point, high_quality)),
            scan_history_age.eq(Const(15, 4) - scan_slice),
            # Consecutive captures are spread across the full visual Z depth.
            scan_depth.eq(scan_history_age << 4),
            scan_group_base.eq(scan_point << scan_group_shift),
            scan_group_last.eq(Mux(
                scan_group_shift == 0, 0,
                Mux(scan_group_shift == 1, 1,
                    Mux(scan_group_shift == 2, 3, 7)))),
            # Preserve all six calibrated display-level bits. The packed
            # framebuffer palette has room for 64 amplitude steps and four
            # simultaneous hue rotations, so discarding the low bit here only
            # created visible plateaus in dense terrain.
            terrain_level.eq(scan_peak),
            scan_peak_next.eq(Mux(
                scan_history_level > scan_peak,
                scan_history_level,
                scan_peak)),
            scan_read_en.eq(0),
            scan_read_addr.eq(
                ((sweep_newest + scan_history_age) << 8) |
                scan_history_bin),
            # Drive the DVI-domain RAM port from the renderer scan. Without
            # these connections the port remains at address zero (the
            # deliberately suppressed DC bin), flattening every ridge even
            # though the projection and line renderer continue to work.
            history_r.en.eq(scan_read_en),
            history_r.addr.eq(scan_read_addr),
            point_frequency.eq(Mux(
                h_active_dvi >= 1024,
                point_frequency_base << 1,
                point_frequency_base,
            )),
            projection_sum_x.eq(products_x[0] + products_x[1] + products_x[2]),
            projection_sum_y.eq(products_y[0] + products_y[1] + products_y[2]),
            center_x.eq((h_active_dvi >> 1) - 50),
            # Anchor the 3D volume around screen center instead of pinning its
            # baseline near the bottom. On 720p this places the projected
            # frequency/time floor around y=545, centering the typical
            # amplitude range much more naturally in the display.
            baseline_y.eq((v_active_dvi >> 1) + 185),
            line_word.x.eq(projected_x),
            line_word.y.eq(projected_y),
            line_word.pixel.eq(point_pixel),
            line_word.cmd.eq(point_cmd),
            line_fifo.w_en.eq(0),
            line_fifo.w_data.eq(line_word),
            triangle_fifo.w_en.eq(0),
            triangle_fifo.w_data.eq(triangle_word),
            current_projected_point.x.eq(projected_x),
            current_projected_point.y.eq(projected_y),
            current_projected_point.level.eq(terrain_level),
            # Shade the complete projected cell from all four corners. Giving
            # the two triangles independent three-corner averages made their
            # shared diagonal visible as a dark, perforated-looking seam.
            # Division by four is exact, cheaper, and makes the triangulation
            # an implementation detail rather than part of the picture.
            terrain_cell_sum.eq(
                terrain_previous_left.level
                + terrain_current_left.level
                + current_projected_point.level
                + terrain_previous_right.level),
            terrain_cell_level_next.eq((terrain_cell_sum + 2) >> 2),
            # Frequency coloring already has independent hue and brightness
            # fields, so age can reduce brightness directly. Level coloring
            # instead encodes age as a separate palette dimension below; its
            # amplitude-selected color must not move through the heat map.
            terrain_cell_display_level_next.eq(Mux(
                sweep_frequency_color,
                _terrain_visibility_level(
                    terrain_cell_level_next,
                    scan_history_age,
                    sweep_age_fade,
                ),
                terrain_cell_level_next)),
            # Keep culling independent from shading. In level-color mode the
            # facet retains its original amplitude-selected hue while this
            # parallel envelope removes only old, effectively invisible
            # low-level geometry. Frequency-color mode already applies the
            # same envelope to brightness, so the two modes now agree on
            # which terrain is worth rasterizing.
            terrain_cell_visibility_level_next.eq(
                _terrain_visibility_level(
                    terrain_cell_level_next,
                    scan_history_age,
                    sweep_age_fade,
                )),
            wire_display_level.eq(Mux(
                sweep_frequency_color,
                _terrain_visibility_level(
                    scan_peak,
                    scan_history_age,
                    sweep_age_fade,
                ),
                scan_peak)),
            # Frequency coloring has only four amplitude bits. Round nonzero
            # six-bit levels upward so quiet history does not become black,
            # and saturate the top four codes instead of wrapping at 64.
            terrain_cell_frequency_intensity.eq(Mux(
                terrain_cell_display_level == 0,
                0,
                Mux(terrain_cell_display_level >= 60,
                    15, (terrain_cell_display_level + 3) >> 2))),
            wire_frequency_intensity.eq(Mux(
                wire_display_level == 0,
                0,
                Mux(wire_display_level >= 60,
                    15, (wire_display_level + 3) >> 2))),
            # Physical hue zero is reserved for framebuffer UI and axes.
            # The lookup code packs hue in bits 0..3 and amplitude group in
            # the upper bits. Age is inserted independently below.
            terrain_fade_code.eq(
                palette_terrain_r.data[:5]),
            wire_fade_code.eq(palette_wire_r.data[:5]),
            terrain_full_code.eq(
                palette_terrain_r.data[5:11]),
            wire_full_code.eq(palette_wire_r.data[5:11]),
            terrain_level_color.eq(Mux(
                sweep_age_fade,
                terrain_fade_code[:4], terrain_full_code[:4])),
            wire_level_color.eq(Mux(
                sweep_age_fade,
                wire_fade_code[:4], wire_full_code[:4])),
            terrain_level_intensity.eq(Mux(
                sweep_age_fade,
                Cat(terrain_fade_code[4], scan_history_age[1:4]),
                terrain_full_code[4:6])),
            wire_level_intensity.eq(Mux(
                sweep_age_fade,
                Cat(wire_fade_code[4], scan_history_age[1:4]),
                wire_full_code[4:6])),
            sweep_frequency_position.eq(
                Mux(high_quality, scan_point >> 3, scan_point >> 2)
                + sweep_hue),
            sweep_frequency_hue.eq(
                frequency_hues[sweep_frequency_position]),
            palette_wire_r.en.eq(0),
            palette_wire_r.addr.eq(scan_peak),
            palette_terrain_r.en.eq(0),
            palette_terrain_r.addr.eq(terrain_cell_display_level_next),
        ]
        with m.Switch(sweep_rate):
            with m.Case(0):
                m.d.comb += capture_sweep_due.eq(1)
            with m.Case(1):
                m.d.comb += capture_sweep_due.eq(render_sweep_count[0] == 0)
            with m.Case(2):
                m.d.comb += capture_sweep_due.eq(render_sweep_count[:2] == 0)
            with m.Default():
                m.d.comb += capture_sweep_due.eq(render_sweep_count == 0)

        with m.FSM(domain="dvi", name="waterfall_3d") as waterfall_3d_fsm:
            with m.State("IDLE"):
                m.d.dvi += [
                    clear_request.eq(0),
                    flush_request.eq(0),
                ]
                with m.If(enable_dvi):
                    m.d.dvi += [
                        scan_slice.eq(0),
                        scan_point.eq(0),
                        row_bank.eq(0),
                        # Freeze every property that can make one projected
                        # sweep disagree with another. The live analyzer may
                        # continue writing newer columns in the background.
                        sweep_newest.eq(newest_dvi),
                        sweep_rate.eq(rate_dvi),
                        sweep_hue.eq(hue_dvi),
                        sweep_quality_3d.eq(quality_3d_dvi),
                        sweep_terrain_style.eq(terrain_style_dvi),
                        sweep_log_scale.eq(log_scale_dvi),
                        sweep_age_fade.eq(age_fade_dvi),
                        sweep_frequency_color.eq(frequency_color_dvi),
                        sweep_ridges.eq(ridges_dvi),
                        draw_generation.eq(~visible_generation),
                        render_activity_seen.eq(0),
                        clear_request.eq(1),
                    ]
                    for index in range(3):
                        m.d.dvi += [
                            sweep_projection_x[index].eq(projection_x_dvi[index]),
                            sweep_projection_y[index].eq(projection_y_dvi[index]),
                        ]
                    m.next = "WAIT_CLEAR"
                with m.Elif(~enable_dvi):
                    m.d.dvi += surface_valid.eq(0)

            with m.State("WAIT_CLEAR"):
                # The inactive physical framebuffer is cleared before every
                # 3D surface. After this point all pixels are literal display
                # pixels; no generation-tag reveal or persistence cleanup is
                # involved in the image shown to the user.
                with m.If(~enable_dvi):
                    m.d.dvi += clear_request.eq(0)
                    m.next = "IDLE"
                with m.Elif(clear_done_dvi):
                    m.d.dvi += clear_request.eq(0)
                    m.next = "START_BIN_GROUP"

            with m.State("START_BIN_GROUP"):
                with m.If(sweep_log_scale):
                    m.d.comb += log_bucket_r.en.eq(1)
                    m.next = "LATCH_LOG_BIN_GROUP"
                with m.Else():
                    m.d.dvi += [
                        scan_history_bin.eq(scan_group_base),
                        scan_bin_last.eq(scan_group_base + scan_group_last),
                        scan_peak.eq(0),
                    ]
                    m.next = "ISSUE_HISTORY_READ"

            with m.State("LATCH_LOG_BIN_GROUP"):
                m.d.dvi += [
                    scan_history_bin.eq(log_bucket_r.data[:8]),
                    scan_bin_last.eq(log_bucket_r.data[8:16]),
                    scan_peak.eq(0),
                ]
                m.next = "ISSUE_HISTORY_READ"

            with m.State("ISSUE_HISTORY_READ"):
                m.d.comb += scan_read_en.eq(1)
                m.next = "LATCH_HISTORY_LEVEL"

            with m.State("LATCH_HISTORY_LEVEL"):
                # The EBR output has a relatively large clock-to-Q delay.
                # Register the display-floor result before the peak compare so
                # neither thresholding nor the max mux shares that same cycle.
                m.d.dvi += scan_history_level.eq(
                    apply_display_floor(history_r.data))
                m.next = "ACCUMULATE_BIN"

            with m.State("ACCUMULATE_BIN"):
                m.d.dvi += scan_peak.eq(scan_peak_next)
                with m.If(scan_history_bin == scan_bin_last):
                    m.next = "LOAD_HISTORY_POINT"
                with m.Else():
                    m.d.dvi += scan_history_bin.eq(scan_history_bin + 1)
                    m.next = "ISSUE_HISTORY_READ"

            with m.State("LOAD_HISTORY_POINT"):
                m.d.comb += palette_wire_r.en.eq(1)
                m.d.dvi += [
                    # Spread pooled vertices across the same 256-unit
                    # frequency coordinate used by the axes and projection.
                    point_frequency_base.eq(
                        frequency_coordinate.as_signed() - 128),
                    point_amplitude.eq(
                        _dbfs_level_to_height(scan_peak, Const(0))),
                    point_time.eq(scan_depth),
                    point_cmd.eq(Mux(
                        scan_point == scan_point_last,
                        LineStripCmd.END, LineStripCmd.CONTINUE)),
                    point_next.eq(0),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("MULTIPLY_POINT"):
                # The registered palette ROM requested by LOAD_HISTORY_POINT
                # is valid here. Axis points retain the explicit colors set by
                # their start states because they use nonzero point_next tags.
                with m.If(point_next == 0):
                    m.d.dvi += [
                        point_pixel.intensity.eq(Mux(
                            sweep_frequency_color,
                            wire_frequency_intensity,
                            wire_level_intensity)),
                        point_pixel.color.eq(Mux(
                            sweep_frequency_color,
                            sweep_frequency_hue,
                            wire_level_color)),
                    ]
                for index, coordinate in enumerate(
                        (point_frequency, point_amplitude, point_time)):
                    m.d.dvi += [
                        products_x[index].eq(coordinate * sweep_projection_x[index]),
                        products_y[index].eq(coordinate * sweep_projection_y[index]),
                    ]
                m.next = "PROJECT_POINT"

            with m.State("PROJECT_POINT"):
                m.d.dvi += [
                    projected_x.eq(center_x + (projection_sum_x >> 8)),
                    projected_y.eq(baseline_y + (projection_sum_y >> 8)),
                ]
                with m.If((point_next == 0) & sweep_terrain_style):
                    m.next = "TERRAIN_READ_ROW"
                with m.Else():
                    m.next = "PUSH_POINT"

            with m.State("TERRAIN_READ_ROW"):
                # Fetch the matching vertex from the previous frequency row.
                # Slice zero only primes a row buffer, but sharing this state
                # keeps the write/advance path identical for every slice.
                m.d.comb += terrain_row_read_en.eq(scan_slice != 0)
                m.next = "TERRAIN_LATCH_ROW"

            with m.State("TERRAIN_LATCH_ROW"):
                m.d.comb += terrain_row_write_en.eq(1)
                with m.If((scan_slice == 0) | (scan_point == 0)):
                    m.d.dvi += [
                        terrain_current_left.eq(current_projected_point),
                        terrain_previous_left.eq(row_read_point),
                    ]
                    m.next = "ADVANCE_SURFACE_POINT"
                with m.Else():
                    # Break the EBR-to-triangle path before doing the facet
                    # average. The ECP5 row-memory output itself consumes a
                    # substantial portion of one 74.25MHz DVI clock.
                    m.d.dvi += terrain_previous_right.eq(row_read_point)
                    m.next = "TERRAIN_LATCH_SHADE"

            with m.State("TERRAIN_LATCH_SHADE"):
                m.d.comb += palette_terrain_r.en.eq(1)
                m.d.dvi += [
                    terrain_cell_display_level.eq(
                        terrain_cell_display_level_next),
                    terrain_cell_visible.eq(
                        terrain_cell_visibility_level_next != 0),
                ]
                m.next = "PUSH_TRIANGLE_A"

            with m.State("PUSH_TRIANGLE_A"):
                # First half of A(previous-left), B(current-left),
                # C(current-right), D(previous-right).
                m.d.comb += [
                    triangle_word.x0.eq(terrain_previous_left.x),
                    triangle_word.y0.eq(terrain_previous_left.y),
                    triangle_word.x1.eq(terrain_current_left.x),
                    triangle_word.y1.eq(terrain_current_left.y),
                    triangle_word.x2.eq(current_projected_point.x),
                    triangle_word.y2.eq(current_projected_point.y),
                    triangle_word.pixel.color.eq(Mux(
                        sweep_frequency_color,
                        sweep_frequency_hue,
                        terrain_level_color)),
                    triangle_word.pixel.intensity.eq(
                        Mux(sweep_frequency_color,
                            terrain_cell_frequency_intensity,
                            terrain_level_intensity)),
                    triangle_fifo.w_en.eq(terrain_cell_visible),
                ]
                # The inactive framebuffer was just cleared. Zero-level and
                # age-culled facets are therefore already represented and do
                # not need to consume rasterizer or PSRAM bandwidth.
                with m.If(~terrain_cell_visible):
                    m.next = "PUSH_TRIANGLE_B"
                with m.Elif(triangle_fifo.w_rdy):
                    m.next = "PUSH_TRIANGLE_B"

            with m.State("PUSH_TRIANGLE_B"):
                # Second half closes the cell with D from the previous row.
                m.d.comb += [
                    triangle_word.x0.eq(terrain_previous_left.x),
                    triangle_word.y0.eq(terrain_previous_left.y),
                    triangle_word.x1.eq(current_projected_point.x),
                    triangle_word.y1.eq(current_projected_point.y),
                    triangle_word.x2.eq(terrain_previous_right.x),
                    triangle_word.y2.eq(terrain_previous_right.y),
                    triangle_word.pixel.color.eq(Mux(
                        sweep_frequency_color,
                        sweep_frequency_hue,
                        terrain_level_color)),
                    triangle_word.pixel.intensity.eq(
                        Mux(sweep_frequency_color,
                            terrain_cell_frequency_intensity,
                            terrain_level_intensity)),
                    triangle_fifo.w_en.eq(terrain_cell_visible),
                ]
                with m.If(~terrain_cell_visible | triangle_fifo.w_rdy):
                    m.d.dvi += [
                        terrain_current_left.eq(current_projected_point),
                        terrain_previous_left.eq(terrain_previous_right),
                    ]
                    m.next = "ADVANCE_SURFACE_POINT"

            with m.State("CONTOUR_ISSUE_LEFT"):
                # Replay the completed current row only after every cell in
                # that row has been queued. This prevents later cells in the
                # same row from erasing pieces of its one-pixel contour.
                m.d.comb += contour_row_read_en.eq(1)
                m.next = "CONTOUR_LATCH_LEFT"

            with m.State("CONTOUR_LATCH_LEFT"):
                m.d.dvi += [
                    contour_left.eq(contour_row_point),
                    contour_point.eq(contour_point + 1),
                ]
                m.next = "CONTOUR_ISSUE_RIGHT"

            with m.State("CONTOUR_ISSUE_RIGHT"):
                m.d.comb += contour_row_read_en.eq(1)
                m.next = "CONTOUR_LATCH_RIGHT"

            with m.State("CONTOUR_LATCH_RIGHT"):
                m.d.dvi += contour_right.eq(contour_row_point)
                m.next = "PUSH_TERRAIN_CONTOUR"

            with m.State("PUSH_TERRAIN_CONTOUR"):
                # Vertices 0 and 1 intentionally match: the span renderer
                # recognizes this otherwise-invalid triangle as an exact
                # one-pixel contour segment. The next, nearer history row is
                # still later in this FIFO and therefore occludes it naturally.
                m.d.comb += [
                    triangle_word.x0.eq(contour_left.x),
                    triangle_word.y0.eq(contour_left.y),
                    triangle_word.x1.eq(contour_left.x),
                    triangle_word.y1.eq(contour_left.y),
                    triangle_word.x2.eq(contour_right.x),
                    triangle_word.y2.eq(contour_right.y),
                    triangle_word.pixel.color.eq(0),
                    triangle_word.pixel.intensity.eq(0),
                    triangle_fifo.w_en.eq(1),
                ]
                with m.If(triangle_fifo.w_rdy):
                    with m.If(contour_point == scan_point_last):
                        m.next = "ADVANCE_SURFACE_SLICE"
                    with m.Else():
                        m.d.dvi += [
                            contour_left.eq(contour_right),
                            contour_point.eq(contour_point + 1),
                        ]
                        m.next = "CONTOUR_ISSUE_RIGHT"

            with m.State("PUSH_POINT"):
                m.d.comb += line_fifo.w_en.eq(1)
                with m.If(line_fifo.w_rdy):
                    with m.Switch(point_next):
                        with m.Case(0):
                            m.next = "ADVANCE_SURFACE_POINT"
                        with m.Case(1):
                            m.next = "AXIS_FREQUENCY_END"
                        with m.Case(2):
                            m.next = "AXIS_AMPLITUDE_START"
                        with m.Case(3):
                            m.next = "AXIS_AMPLITUDE_END"
                        with m.Case(4):
                            m.next = "AXIS_TIME_START"
                        with m.Case(5):
                            m.next = "AXIS_TIME_END"
                        with m.Default():
                            m.next = "WAIT_RENDER_COMPLETE"

            with m.State("ADVANCE_SURFACE_POINT"):
                with m.If(scan_point == scan_point_last):
                    with m.If(sweep_terrain_style & sweep_ridges &
                              (scan_slice != 0)):
                        m.d.dvi += contour_point.eq(0)
                        m.next = "CONTOUR_ISSUE_LEFT"
                    with m.Else():
                        m.next = "ADVANCE_SURFACE_SLICE"
                with m.Else():
                    m.d.dvi += scan_point.eq(scan_point + 1)
                    m.next = "START_BIN_GROUP"

            with m.State("ADVANCE_SURFACE_SLICE"):
                m.d.dvi += scan_point.eq(0)
                with m.If(scan_slice == 15):
                    with m.If(axes_dvi):
                        m.next = "AXIS_FREQUENCY_START"
                    with m.Else():
                        m.next = "WAIT_RENDER_COMPLETE"
                with m.Elif(enable_dvi):
                    m.d.dvi += [
                        scan_slice.eq(scan_slice + 1),
                        row_bank.eq(~row_bank),
                    ]
                    m.next = "START_BIN_GROUP"
                with m.Else():
                    m.next = "IDLE"

            with m.State("WAIT_RENDER_COMPLETE"):
                # First drain commands and Bresenham. Plot requests still pass
                # through a write-back cache, so this is not yet a safe swap
                # boundary; the following state performs an explicit fence.
                with m.If((line_fifo.w_level != 0) |
                          (triangle_fifo.w_level != 0) | line_busy_dvi):
                    m.d.dvi += render_activity_seen.eq(1)
                with m.If(render_activity_seen &
                          (line_fifo.w_level == 0) &
                          (triangle_fifo.w_level == 0) & ~line_busy_dvi):
                    m.d.dvi += flush_request.eq(1)
                    m.next = "WAIT_CACHE_FLUSH"

            with m.State("WAIT_CACHE_FLUSH"):
                # ``flush_done`` is held until the request drops, so no pulse
                # can be missed while crossing between sync and DVI domains.
                with m.If(~enable_dvi):
                    m.d.dvi += flush_request.eq(0)
                    m.next = "IDLE"
                with m.Elif(flush_done_dvi):
                    m.d.dvi += [
                        flush_request.eq(0),
                        completed_generation.eq(draw_generation),
                        surface_valid.eq(1),
                        render_sweep_count.eq(render_sweep_count + 1),
                    ]
                    with m.If(capture_sweep_due &
                              (render_token_dvi == render_ack_dvi)):
                        m.d.dvi += render_token_dvi.eq(~render_token_dvi)
                    m.next = "WAIT_DISPLAY_SWAP"

            with m.State("WAIT_DISPLAY_SWAP"):
                # Do not begin drawing into the old front buffer until firmware
                # has moved the video/UI base to the completed back buffer.
                with m.If(~enable_dvi |
                          (display_ack_dvi == completed_generation)):
                    m.next = "WAIT_SWAP_VSYNC"

            with m.State("WAIT_SWAP_VSYNC"):
                # The video DMA latches its base at VSync. Reveal the matching
                # generation on that same frame boundary, never mid-scan.
                with m.If(~enable_dvi):
                    m.next = "IDLE"
                with m.Elif(self.i.vsync & ~prev_vsync):
                    m.d.dvi += visible_generation.eq(completed_generation)
                    m.next = "IDLE"

            # Three bright reference axes share the same projection matrix as
            # the waterfall, so their orientation follows every camera move.
            with m.State("AXIS_FREQUENCY_START"):
                m.d.dvi += [
                    point_frequency_base.eq(-128),
                    point_amplitude.eq(0),
                    point_time.eq(0),
                    point_pixel.intensity.eq(13),
                    point_pixel.color.eq(0),
                    point_cmd.eq(LineStripCmd.CONTINUE),
                    point_next.eq(1),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("AXIS_FREQUENCY_END"):
                m.d.dvi += [
                    point_frequency_base.eq(127),
                    point_amplitude.eq(0),
                    point_time.eq(0),
                    point_pixel.intensity.eq(13),
                    point_pixel.color.eq(0),
                    point_cmd.eq(LineStripCmd.END),
                    point_next.eq(2),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("AXIS_AMPLITUDE_START"):
                m.d.dvi += [
                    point_frequency_base.eq(-128),
                    point_amplitude.eq(0),
                    point_time.eq(0),
                    point_pixel.intensity.eq(14),
                    point_pixel.color.eq(0),
                    point_cmd.eq(LineStripCmd.CONTINUE),
                    point_next.eq(3),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("AXIS_AMPLITUDE_END"):
                m.d.dvi += [
                    point_frequency_base.eq(-128),
                    point_amplitude.eq(255),
                    point_time.eq(0),
                    point_pixel.intensity.eq(14),
                    point_pixel.color.eq(0),
                    point_cmd.eq(LineStripCmd.END),
                    point_next.eq(4),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("AXIS_TIME_START"):
                m.d.dvi += [
                    point_frequency_base.eq(-128),
                    point_amplitude.eq(0),
                    point_time.eq(0),
                    point_pixel.intensity.eq(15),
                    point_pixel.color.eq(0),
                    point_cmd.eq(LineStripCmd.CONTINUE),
                    point_next.eq(5),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("AXIS_TIME_END"):
                m.d.dvi += [
                    point_frequency_base.eq(-128),
                    point_amplitude.eq(0),
                    point_time.eq(240),
                    point_pixel.intensity.eq(15),
                    point_pixel.color.eq(0),
                    point_cmd.eq(LineStripCmd.END),
                    point_next.eq(6),
                ]
                m.next = "MULTIPLY_POINT"

        # Firmware must not draw a static full-screen page until every 3D
        # writer has released PSRAM. ``IDLE`` alone is insufficient because a
        # cancelled clear burst or queued Bresenham command can outlive the
        # renderer state machine by a few cycles.
        m.d.comb += renderer_idle_dvi.eq(
            ~enable_dvi & waterfall_3d_fsm.ongoing("IDLE") &
            (line_fifo.w_level == 0) & (triangle_fifo.w_level == 0) &
            ~line_busy_dvi & ~clear_busy_dvi)

        # WATERFALL contributes no beam-raced trace. Pass the scan stream
        # through unchanged while observing VSync for atomic framebuffer swaps.
        m.d.comb += self.o.eq(self.i)
        return m
