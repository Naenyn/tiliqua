# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Streaming spectral analysis and beam-raced waterfall display."""

import math

from amaranth import *
from amaranth.lib import data, fifo, memory, stream, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from amaranth_future import fixed

from tiliqua import dsp
from tiliqua.dsp import ASQ
from tiliqua.raster.line import LineCmd, LineStripCmd
from tiliqua.video.types import Pixel, ScanPixel


FFT_SIZE = 512
N_BINS = FFT_SIZE // 2
HISTORY_COLS = 256


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


SPECTRUM_LOG_COORD_LUTS = [
    _spectrum_log_coord_lut(24000, 48000 / FFT_SIZE, 255),
    _spectrum_log_coord_lut(12000, 24000 / FFT_SIZE, 255),
    _spectrum_log_coord_lut(6000, 24000 / FFT_SIZE, 127),
    _spectrum_log_coord_lut(3000, 24000 / FFT_SIZE, 63),
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
        view_3d: csr.Field(csr.action.W, unsigned(1))
        spectrum_mode: csr.Field(csr.action.W, unsigned(1))
        display_ack: csr.Field(csr.action.W, unsigned(1))

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

    class Timings(csr.Register, access="w"):
        h_active: csr.Field(csr.action.W, unsigned(12))
        v_active: csr.Field(csr.action.W, unsigned(12))
        menu_visible: csr.Field(csr.action.W, unsigned(1))

    class Status(csr.Register, access="r"):
        display_buffer: csr.Field(csr.action.R, unsigned(1))
        surface_valid: csr.Field(csr.action.R, unsigned(1))

    class Config3d(csr.Register, access="w"):
        quality: csr.Field(csr.action.W, unsigned(2))
        static_surface: csr.Field(csr.action.W, unsigned(1))

    class SpectrumConfig(csr.Register, access="w"):
        style: csr.Field(csr.action.W, unsigned(1))
        bands: csr.Field(csr.action.W, unsigned(2))
        fill: csr.Field(csr.action.W, unsigned(2))
        peaks: csr.Field(csr.action.W, unsigned(3))
        smoothing: csr.Field(csr.action.W, unsigned(2))
        scale: csr.Field(csr.action.W, unsigned(1))
        tilt: csr.Field(csr.action.W, unsigned(2))
        highlight: csr.Field(csr.action.W, unsigned(1))

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
        self._persistence = regs.add("persistence", self.Persistence(), offset=0x10)
        self._hue = regs.add("hue", self.Hue(), offset=0x14)
        self._timings = regs.add("timings", self.Timings(), offset=0x18)
        self._status = regs.add("status", self.Status(), offset=0x1c)
        self._projection_x = regs.add(
            "projection_x", self.ProjectionX(), offset=0x20)
        self._projection_y = regs.add(
            "projection_y", self.ProjectionY(), offset=0x24)
        self._config_3d = regs.add(
            "config_3d", self.Config3d(), offset=0x28)
        self._spectrum_config = regs.add(
            "spectrum_config", self.SpectrumConfig(), offset=0x2c)
        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "i": In(ScanPixel),
            "o": Out(ScanPixel),
            "audio_i": In(stream.Signature(data.ArrayLayout(ASQ, 4))),
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "line_o": Out(stream.Signature(LineCmd)),
            "line_busy": In(1),
            "protect_enable": Out(1),
            "protect_visible": Out(3),
            "protect_drawing": Out(3),
            "flush_request": Out(1),
            "flush_done": In(1),
            "clear_request": Out(1),
            "clear_done": In(1),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        wiring.connect(m, wiring.flipped(self.bus), self._bridge.bus)

        enable = Signal(init=1)
        phosphor = Signal(init=1)
        axes = Signal(init=1)
        view_3d = Signal()
        spectrum_mode = Signal()
        display_ack = Signal()
        input_ch = Signal(2)
        gain = Signal(4)
        range_sel = Signal(2)
        rate_sel = Signal(2, init=2)
        persistence = Signal(2, init=2)
        hue = Signal(4, init=5)
        quality_3d = Signal(2, init=1)
        static_surface_3d = Signal()
        spectrum_style = Signal(init=1)
        spectrum_bands = Signal(2, init=1)
        spectrum_fill = Signal(2, init=3)
        spectrum_peaks = Signal(3, init=5)
        spectrum_smoothing = Signal(2)
        spectrum_scale = Signal(init=1)
        spectrum_tilt = Signal(2)
        spectrum_highlight = Signal()
        h_active = Signal(12, init=720)
        v_active = Signal(12, init=720)
        menu_visible = Signal()
        projection_x = [Signal(signed(10), init=value) for value in (384, 0, 90)]
        projection_y = [Signal(signed(10), init=value) for value in (0, -320, -96)]

        with m.If(self._flags.element.w_stb):
            m.d.sync += [
                enable.eq(self._flags.f.enable.w_data),
                phosphor.eq(self._flags.f.phosphor.w_data),
                axes.eq(self._flags.f.axes.w_data),
                input_ch.eq(self._flags.f.input_ch.w_data),
                view_3d.eq(self._flags.f.view_3d.w_data),
                spectrum_mode.eq(self._flags.f.spectrum_mode.w_data),
                display_ack.eq(self._flags.f.display_ack.w_data),
            ]
        with m.If(self._gain.element.w_stb):
            m.d.sync += gain.eq(self._gain.f.value.w_data)
        with m.If(self._range.element.w_stb):
            m.d.sync += range_sel.eq(self._range.f.value.w_data)
        with m.If(self._rate.element.w_stb):
            m.d.sync += rate_sel.eq(self._rate.f.value.w_data)
        with m.If(self._persistence.element.w_stb):
            m.d.sync += persistence.eq(self._persistence.f.value.w_data)
        with m.If(self._hue.element.w_stb):
            m.d.sync += hue.eq(self._hue.f.value.w_data)
        with m.If(self._timings.element.w_stb):
            m.d.sync += [
                h_active.eq(self._timings.f.h_active.w_data),
                v_active.eq(self._timings.f.v_active.w_data),
                menu_visible.eq(self._timings.f.menu_visible.w_data),
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
                static_surface_3d.eq(
                    self._config_3d.f.static_surface.w_data),
            ]
        with m.If(self._spectrum_config.element.w_stb):
            m.d.sync += [
                spectrum_style.eq(self._spectrum_config.f.style.w_data),
                spectrum_bands.eq(self._spectrum_config.f.bands.w_data),
                spectrum_fill.eq(self._spectrum_config.f.fill.w_data),
                spectrum_peaks.eq(self._spectrum_config.f.peaks.w_data),
                spectrum_smoothing.eq(
                    self._spectrum_config.f.smoothing.w_data),
                spectrum_scale.eq(self._spectrum_config.f.scale.w_data),
                spectrum_tilt.eq(self._spectrum_config.f.tilt.w_data),
                spectrum_highlight.eq(
                    self._spectrum_config.f.highlight.w_data),
            ]

        # ---- audio analysis -------------------------------------------------
        # Build both a wide 48kHz feed and a fine 24kHz feed. The 24kHz range
        # uses the wide feed; all smaller display ranges automatically use the
        # fine feed, restoring 46.875Hz FFT bins instead of the wide mode's
        # 93.75Hz bins. The fine stage stays warm while wide mode is selected,
        # so changing range does not start with stale FIR state.
        wide_fs = min(self.fs, 48_000)
        assert self.fs % wide_fs == 0
        wide_downsample = self.fs // wide_fs
        m.submodules.resample_wide = resample_wide = dsp.Resample(
            fs_in=self.fs, n_up=1, m_down=wide_downsample,
            bw=11/24, order_mult=40, shape=ASQ)
        m.submodules.resample_fine = resample_fine = dsp.Resample(
            fs_in=wide_fs, n_up=1, m_down=2,
            bw=11/24, order_mult=40, shape=ASQ)
        m.submodules.analyzer = analyzer = dsp.fft.STFTAnalyzer(
            shape=ASQ, sz=FFT_SIZE)
        m.submodules.envelope = envelope = dsp.spectral.SpectralEnvelope(
            shape=ASQ, sz=FFT_SIZE)

        def log_lut(x):
            max_v = 1 << ASQ.f_bits
            full_range = math.log2(max_v)
            log_level = math.log2(max(1, x * max_v)) / full_range
            # Discard the lowest part of the numerical noise floor and spend
            # the available display levels on musically useful magnitudes.
            return max(0, min(1, (log_level - 0.30) / 0.70))

        m.submodules.log = log = dsp.block.WrapCore(dsp.WaveShaper(
            lut_function=log_lut, lut_size=512, continuous=False))

        selected_sample = Signal(ASQ)
        fine_mode = Signal()
        with m.Switch(input_ch):
            for ch in range(4):
                with m.Case(ch):
                    m.d.comb += selected_sample.eq(self.audio_i.payload[ch])
        m.d.comb += [
            fine_mode.eq(range_sel != 0),
            resample_wide.i.valid.eq(self.audio_i.valid),
            resample_wide.i.payload.eq(selected_sample),
            self.audio_i.ready.eq(resample_wide.i.ready),

            # Always feed the fine decimator. In wide mode, synchronize its
            # input handshake with the analyzer and discard its output.
            resample_fine.i.valid.eq(
                resample_wide.o.valid & (fine_mode | analyzer.i.ready)),
            resample_fine.i.payload.eq(resample_wide.o.payload),
            resample_wide.o.ready.eq(
                resample_fine.i.ready & (fine_mode | analyzer.i.ready)),
            resample_fine.o.ready.eq(Mux(fine_mode, analyzer.i.ready, 1)),

            analyzer.i.valid.eq(Mux(
                fine_mode,
                resample_fine.o.valid,
                resample_wide.o.valid & resample_fine.i.ready,
            )),
            analyzer.i.payload.eq(Mux(
                fine_mode,
                resample_fine.o.payload,
                resample_wide.o.payload,
            )),
        ]
        wiring.connect(m, analyzer.o, envelope.i)
        wiring.connect(m, envelope.o, log.i)

        # In spectrogram mode this retains the established analytical/phosphor
        # response. In spectrum mode Rate becomes envelope release smoothing:
        # all FFT frames still render and rising bins attack immediately, but
        # falling bins decay more gently so plucks keep their captured peak
        # instead of disappearing between slow display updates.
        spectrum_release_beta = Signal(ASQ)
        with m.Switch(rate_sel):
            with m.Case(0):
                m.d.comb += spectrum_release_beta.eq(
                    fixed.Const(0.82, shape=ASQ))
            with m.Case(1):
                m.d.comb += spectrum_release_beta.eq(
                    fixed.Const(0.92, shape=ASQ))
            with m.Case(2):
                m.d.comb += spectrum_release_beta.eq(
                    fixed.Const(0.97, shape=ASQ))
            with m.Default():
                m.d.comb += spectrum_release_beta.eq(
                    fixed.Const(0.99, shape=ASQ))
        m.d.comb += [
            envelope.block_lpf.beta.eq(Mux(
                spectrum_mode,
                spectrum_release_beta,
                Mux(
                    phosphor,
                    fixed.Const(0.82, shape=ASQ),
                    fixed.Const(0.25, shape=ASQ),
                ),
            )),
            envelope.block_lpf.attack_beta.eq(Mux(
                spectrum_mode,
                fixed.Const(0.0, shape=ASQ),
                envelope.block_lpf.beta,
            )),
        ]

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
                shape=unsigned(6), depth=N_BINS,
                init=[0] * N_BINS,
            )
        )
        m.submodules.spectrum_levels = spectrum_levels
        spectrum_levels_w = spectrum_levels.write_port(domain="sync")
        spectrum_levels_r = spectrum_levels.read_port(domain="dvi")

        # Per-band highlight intensity for spectrum peak-focus mode. This is
        # prepared as FFT bins arrive so the DVI renderer only performs one
        # small lookup instead of recomputing harmonic distances per pixel.
        spectrum_focus_levels = memory.Memory(
            data=memory.MemoryData(
                shape=unsigned(4), depth=N_BINS,
                init=[0] * N_BINS,
            )
        )
        m.submodules.spectrum_focus_levels = spectrum_focus_levels
        spectrum_focus_w = spectrum_focus_levels.write_port(domain="sync")
        spectrum_focus_r = spectrum_focus_levels.read_port(domain="dvi")

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

        # The 3D renderer scans the same history RAM used by the beam-raced
        # heatmap, then crosses projected line-strip commands into the system
        # clock domain. Keeping only commands in this tiny FIFO avoids a
        # second spectral-history buffer (there are only three EBRs left on
        # the target device).
        m.submodules.line_fifo = line_fifo = fifo.AsyncFIFOBuffered(
            width=LineCmd.as_shape().size,
            depth=8,
            w_domain="dvi",
            r_domain="sync",
        )
        m.d.comb += [
            self.line_o.valid.eq(line_fifo.r_rdy),
            self.line_o.payload.eq(line_fifo.r_data),
            line_fifo.r_en.eq(line_fifo.r_rdy & self.line_o.ready),
        ]
        line_busy_dvi = Signal()
        flush_done_dvi = Signal()
        clear_done_dvi = Signal()
        m.submodules.line_busy_ff = FFSynchronizer(
            self.line_busy, line_busy_dvi, o_domain="dvi")
        m.submodules.flush_done_ff = FFSynchronizer(
            self.flush_done, flush_done_dvi, o_domain="dvi")
        m.submodules.clear_done_ff = FFSynchronizer(
            self.clear_done, clear_done_dvi, o_domain="dvi")

        write_col = Signal(8)
        newest_col = Signal(8)
        bin_index = Signal(9)
        frame_seq = Signal(4)
        accept_latched = Signal()

        # A 3D frame is accepted only after the renderer finishes a complete
        # surface sweep. This makes capture and visible animation one-to-one:
        # every front ridge subsequently appears in the consecutive history.
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

        accept_rate = Signal()
        accept_now = Signal()
        with m.Switch(rate_sel):
            with m.Case(0):
                m.d.comb += accept_rate.eq(
                    Mux(fine_mode, 1, frame_seq[0] == 0))
            with m.Case(1):
                m.d.comb += accept_rate.eq(Mux(
                    fine_mode,
                    frame_seq[0] == 0,
                    frame_seq[:2] == 0,
                ))
            with m.Case(2):
                m.d.comb += accept_rate.eq(Mux(
                    fine_mode,
                    frame_seq[:2] == 0,
                    frame_seq[:3] == 0,
                ))
            with m.Default():
                m.d.comb += accept_rate.eq(Mux(
                    fine_mode,
                    frame_seq[:3] == 0,
                    frame_seq == 0,
                ))
        # In 3D the renderer itself applies the selected sweep divider before
        # issuing a token. Do not divide again using the free-running analyzer
        # frame counter, which made the control nearly invisible in practice.
        m.d.comb += accept_now.eq(Mux(
            view_3d,
            render_slot_ready,
            Mux(spectrum_mode, 1, accept_rate),
        ))

        current_bin = Signal(9)
        do_write = Signal()
        raw_level = Signal(6)
        spectrum_octave = Signal(4)
        spectrum_tilt_step = Signal(4)
        spectrum_tilt_boost = Signal(5)
        boosted_level = Signal(8)
        stored_level = Signal(6)
        spectrum_frequency_shift = Signal(2)
        spectrum_desired_group_shift = Signal(2)
        spectrum_group_shift = Signal(2)
        spectrum_active_bin_last = Signal(8)
        spectrum_group_first = Signal()
        spectrum_group_last = Signal()
        spectrum_group_peak = Signal(6)
        spectrum_group_peak_next = Signal(6)
        spectrum_band_index_sync = Signal(8)
        spectrum_peak_candidate_bin = Signal(8)
        spectrum_peak_candidate_level = Signal(6)
        spectrum_fundamental_bin = Signal(8)
        spectrum_focus_level_sync = Signal(4)
        spectrum_focus_exact_sync = Signal()
        spectrum_focus_near_sync = Signal()
        spectrum_focus_mid_sync = Signal()
        spectrum_focus_far_sync = Signal()
        spectrum_focus_found_bin = Signal(8)
        spectrum_focus_centers = [
            Signal(8, name=f"spectrum_focus_{harmonic}_center")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_valids = [
            Signal(name=f"spectrum_focus_{harmonic}_valid")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_lo1 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_lo1")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_hi1 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_hi1")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_lo3 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_lo3")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_hi3 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_hi3")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_lo7 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_lo7")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_hi7 = [
            Signal(8, name=f"spectrum_focus_{harmonic}_hi7")
            for harmonic in range(1, 9)
        ]
        spectrum_focus_center_calc = [
            Signal(12, name=f"spectrum_focus_{harmonic}_center_calc")
            for harmonic in range(1, 9)
        ]
        m.d.comb += spectrum_focus_found_bin.eq(Mux(
            spectrum_peak_candidate_level >= 8,
            spectrum_peak_candidate_bin,
            0))
        exact_hits = []
        near_hits = []
        mid_hits = []
        far_hits = []
        for harmonic in range(1, 9):
            index = harmonic - 1
            valid = spectrum_focus_valids[index]
            center_calc = spectrum_focus_center_calc[index]
            m.d.comb += center_calc.eq(spectrum_focus_found_bin * harmonic)
            exact_hits.append(valid & (current_bin[:8] ==
                                       spectrum_focus_centers[index]))
            near_hits.append(valid &
                             (current_bin[:8] >= spectrum_focus_lo1[index]) &
                             (current_bin[:8] <= spectrum_focus_hi1[index]))
            mid_hits.append(valid &
                            (current_bin[:8] >= spectrum_focus_lo3[index]) &
                            (current_bin[:8] <= spectrum_focus_hi3[index]))
            far_hits.append(valid &
                            (current_bin[:8] >= spectrum_focus_lo7[index]) &
                            (current_bin[:8] <= spectrum_focus_hi7[index]))
        m.d.comb += [
            spectrum_focus_exact_sync.eq(Cat(*exact_hits).any()),
            spectrum_focus_near_sync.eq(Cat(*near_hits).any()),
            spectrum_focus_mid_sync.eq(Cat(*mid_hits).any()),
            spectrum_focus_far_sync.eq(Cat(*far_hits).any()),
            spectrum_focus_level_sync.eq(Mux(
                spectrum_focus_exact_sync,
                15,
                Mux(spectrum_focus_near_sync,
                    12,
                    Mux(spectrum_focus_mid_sync,
                        9,
                        Mux(spectrum_focus_far_sync, 6, 0))))),
        ]
        m.d.comb += [
            log.o.ready.eq(1),
            current_bin.eq(Mux(log.o.payload.first, 0, bin_index)),
            do_write.eq(Mux(log.o.payload.first, accept_now, accept_latched)),
            raw_level.eq(log.o.payload.sample.as_value()[ASQ.f_bits-6:ASQ.f_bits]),
            spectrum_tilt_step.eq(Mux(
                spectrum_tilt == 1, 2,
                Mux(spectrum_tilt == 2, 4, 0))),
            spectrum_tilt_boost.eq(spectrum_octave * spectrum_tilt_step),
            boosted_level.eq(raw_level + gain + spectrum_tilt_boost),
            stored_level.eq(Mux(boosted_level > 63, 63, boosted_level[:6])),
            spectrum_frequency_shift.eq(Mux(
                range_sel == 0, 0, range_sel - 1)),
            spectrum_desired_group_shift.eq(3 - spectrum_bands),
            spectrum_group_shift.eq(Mux(
                spectrum_style,
                0,
                Mux(spectrum_desired_group_shift > spectrum_frequency_shift,
                    spectrum_desired_group_shift - spectrum_frequency_shift,
                    0))),
            spectrum_active_bin_last.eq(Mux(
                spectrum_frequency_shift == 0, 255,
                Mux(spectrum_frequency_shift == 1, 127, 63))),
            spectrum_band_index_sync.eq(
                current_bin[:8] >> spectrum_group_shift),
            spectrum_group_peak_next.eq(Mux(
                spectrum_group_first,
                stored_level,
                Mux(stored_level > spectrum_group_peak,
                    stored_level, spectrum_group_peak),
            )),
            history_w.en.eq(log.o.valid & do_write & (current_bin < N_BINS)),
            history_w.addr.eq((write_col << 8) | current_bin[:8]),
            history_w.data.eq(stored_level),
            spectrum_levels_w.en.eq(
                log.o.valid &
                (current_bin <= spectrum_active_bin_last) &
                spectrum_group_last),
            spectrum_levels_w.addr.eq(spectrum_band_index_sync),
            spectrum_levels_w.data.eq(spectrum_group_peak_next),
            spectrum_focus_w.en.eq(
                log.o.valid &
                (current_bin <= spectrum_active_bin_last) &
                spectrum_group_last),
            spectrum_focus_w.addr.eq(spectrum_band_index_sync),
            spectrum_focus_w.data.eq(spectrum_focus_level_sync),
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

        with m.If(current_bin >= 128):
            m.d.comb += spectrum_octave.eq(6)
        with m.Elif(current_bin >= 64):
            m.d.comb += spectrum_octave.eq(5)
        with m.Elif(current_bin >= 32):
            m.d.comb += spectrum_octave.eq(4)
        with m.Elif(current_bin >= 16):
            m.d.comb += spectrum_octave.eq(3)
        with m.Elif(current_bin >= 8):
            m.d.comb += spectrum_octave.eq(2)
        with m.Elif(current_bin >= 4):
            m.d.comb += spectrum_octave.eq(1)
        with m.Else():
            m.d.comb += spectrum_octave.eq(0)

        with m.If(log.o.valid):
            with m.If(log.o.payload.first):
                m.d.sync += [
                    spectrum_fundamental_bin.eq(spectrum_focus_found_bin),
                    spectrum_peak_candidate_bin.eq(0),
                    spectrum_peak_candidate_level.eq(0),
                ]
                for harmonic in range(1, 9):
                    index = harmonic - 1
                    center_calc = spectrum_focus_center_calc[index]
                    m.d.sync += [
                        spectrum_focus_centers[index].eq(center_calc[:8]),
                        spectrum_focus_valids[index].eq(
                            (spectrum_focus_found_bin != 0) &
                            (center_calc <= spectrum_active_bin_last)),
                        spectrum_focus_lo1[index].eq(Mux(
                            center_calc > 1, center_calc - 1, 0)),
                        spectrum_focus_hi1[index].eq(Mux(
                            center_calc + 1 > spectrum_active_bin_last,
                            spectrum_active_bin_last,
                            center_calc + 1)),
                        spectrum_focus_lo3[index].eq(Mux(
                            center_calc > 3, center_calc - 3, 0)),
                        spectrum_focus_hi3[index].eq(Mux(
                            center_calc + 3 > spectrum_active_bin_last,
                            spectrum_active_bin_last,
                            center_calc + 3)),
                        spectrum_focus_lo7[index].eq(Mux(
                            center_calc > 7, center_calc - 7, 0)),
                        spectrum_focus_hi7[index].eq(Mux(
                            center_calc + 7 > spectrum_active_bin_last,
                            spectrum_active_bin_last,
                            center_calc + 7)),
                    ]
            with m.Elif(do_write & (current_bin >= 2) &
                        (current_bin <= spectrum_active_bin_last) &
                        (stored_level > spectrum_peak_candidate_level)):
                m.d.sync += [
                    spectrum_peak_candidate_bin.eq(current_bin[:8]),
                    spectrum_peak_candidate_level.eq(stored_level),
                ]
            with m.If(current_bin <= spectrum_active_bin_last):
                m.d.sync += spectrum_group_peak.eq(
                    spectrum_group_peak_next)
            with m.If(log.o.payload.first):
                m.d.sync += [
                    bin_index.eq(1),
                    frame_seq.eq(frame_seq + 1),
                    accept_latched.eq(accept_now),
                ]
                with m.If(view_3d & accept_now):
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
        phosphor_dvi = Signal()
        axes_dvi = Signal()
        view_3d_dvi = Signal()
        spectrum_mode_dvi = Signal()
        display_ack_dvi = Signal()
        quality_3d_dvi = Signal(2)
        static_surface_3d_dvi = Signal()
        spectrum_style_dvi = Signal()
        spectrum_bands_dvi = Signal(2)
        spectrum_fill_dvi = Signal(2)
        spectrum_peaks_dvi = Signal(3)
        spectrum_smoothing_dvi = Signal(2)
        spectrum_scale_dvi = Signal()
        spectrum_tilt_dvi = Signal(2)
        spectrum_highlight_dvi = Signal()
        range_dvi = Signal(2)
        rate_dvi = Signal(2)
        persistence_dvi = Signal(2)
        hue_dvi = Signal(4)
        h_active_dvi = Signal(12)
        v_active_dvi = Signal(12)
        menu_visible_dvi = Signal()
        projection_x_dvi = [Signal(signed(10)) for _ in range(3)]
        projection_y_dvi = [Signal(signed(10)) for _ in range(3)]
        newest_gray = Signal(8)
        newest_gray_meta = Signal(8)
        newest_binary_meta = Signal(8)
        m.d.comb += newest_gray.eq(newest_col ^ (newest_col >> 1))
        for name, src, dst in [
            ("enable", enable, enable_dvi),
            ("phosphor", phosphor, phosphor_dvi),
            ("axes", axes, axes_dvi),
            ("view_3d", view_3d, view_3d_dvi),
            ("spectrum_mode", spectrum_mode, spectrum_mode_dvi),
            ("display_ack", display_ack, display_ack_dvi),
            ("quality_3d", quality_3d, quality_3d_dvi),
            ("static_surface_3d", static_surface_3d, static_surface_3d_dvi),
            ("spectrum_style", spectrum_style, spectrum_style_dvi),
            ("spectrum_bands", spectrum_bands, spectrum_bands_dvi),
            ("spectrum_fill", spectrum_fill, spectrum_fill_dvi),
            ("spectrum_peaks", spectrum_peaks, spectrum_peaks_dvi),
            ("spectrum_smoothing", spectrum_smoothing,
             spectrum_smoothing_dvi),
            ("spectrum_scale", spectrum_scale, spectrum_scale_dvi),
            ("spectrum_tilt", spectrum_tilt, spectrum_tilt_dvi),
            ("spectrum_highlight", spectrum_highlight,
             spectrum_highlight_dvi),
            ("range", range_sel, range_dvi),
            ("rate", rate_sel, rate_dvi),
            ("persistence", persistence, persistence_dvi),
            ("h_active", h_active, h_active_dvi),
            ("v_active", v_active, v_active_dvi),
            ("menu_visible", menu_visible, menu_visible_dvi),
            ("newest_gray", newest_gray, newest_gray_meta),
            ("hue", hue, hue_dvi),
        ]:
            setattr(m.submodules, f"{name}_ff", FFSynchronizer(src, dst, o_domain="dvi"))
        for axis_name, sources, destinations in [
            ("projection_x", projection_x, projection_x_dvi),
            ("projection_y", projection_y, projection_y_dvi),
        ]:
            for index, (src, dst) in enumerate(zip(sources, destinations)):
                setattr(m.submodules, f"{axis_name}_{index}_ff",
                        FFSynchronizer(src, dst, o_domain="dvi"))

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
            m.d.dvi += newest_dvi.eq(newest_binary_meta)

        # ---- projected 3D waterfall ---------------------------------------
        # Sixteen frequency ridges are drawn oldest-to-newest so the near
        # spectra naturally overwrite the distant ones. Quality selects 64 or
        # up to 128 peak-pooled vertices without changing history depth.
        scan_slice = Signal(4)
        scan_point = Signal(7)
        scan_group_index = Signal(3)
        scan_group_base = Signal(8)
        scan_group_last = Signal(3)
        scan_peak = Signal(6)
        scan_peak_next = Signal(6)
        scan_history_age = Signal(4)
        scan_depth = Signal(8)
        scan_history_bin = Signal(8)
        scan_read_en = Signal()
        scan_read_addr = Signal(16)
        sweep_newest = Signal(8)
        sweep_range = Signal(2)
        sweep_rate = Signal(2)
        sweep_hue = Signal(4)
        sweep_phosphor = Signal()
        sweep_quality_3d = Signal(2)
        sweep_projection_x = [Signal(signed(10)) for _ in range(3)]
        sweep_projection_y = [Signal(signed(10)) for _ in range(3)]
        visible_generation = Signal(3)
        draw_generation = Signal(3)
        visible_hue = Signal(4)
        completed_generation = Signal(3)
        completed_hue = Signal(4)
        render_activity_seen = Signal()
        clear_request = Signal()
        flush_request = Signal()
        visible_generation_sync = Signal(3)
        draw_generation_sync = Signal(3)
        completed_generation_sync = Signal(3)
        surface_valid = Signal()
        surface_valid_sync = Signal()
        m.submodules.visible_generation_ff = FFSynchronizer(
            visible_generation, visible_generation_sync, o_domain="sync")
        m.submodules.draw_generation_ff = FFSynchronizer(
            draw_generation, draw_generation_sync, o_domain="sync")
        m.submodules.completed_generation_ff = FFSynchronizer(
            completed_generation, completed_generation_sync, o_domain="sync")
        m.submodules.surface_valid_ff = FFSynchronizer(
            surface_valid, surface_valid_sync, o_domain="sync")
        m.d.comb += [
            self.protect_enable.eq(view_3d),
            self.protect_visible.eq(visible_generation_sync),
            self.protect_drawing.eq(draw_generation_sync),
            self.clear_request.eq(clear_request),
            self.flush_request.eq(flush_request),
            self._status.f.display_buffer.r_data.eq(
                completed_generation_sync[0]),
            self._status.f.surface_valid.r_data.eq(surface_valid_sync),
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
        effective_quality = Signal(2)
        scan_point_last = Signal(7)
        scan_group_shift = Signal(2)
        frequency_coordinate = Signal(9)
        static_delta_a = Signal(7)
        static_delta_b = Signal(7)
        static_peak_a = Signal(6)
        static_peak_b = Signal(6)
        static_peak = Signal(6)
        sweep_static_surface = Signal()
        sweep_hue_limited = Signal(3)
        sweep_axis_hue_a = Signal(3)
        sweep_axis_hue_b = Signal(3)

        m.d.comb += [
            # Medium 3D quality keeps the full 24kHz view at 64 vertices so
            # it reads as the wide, coarser overview. The lower ranges are
            # already using the fine 24kHz analysis feed, so promote 12kHz and
            # 6kHz to the denser 128-vertex surface even at medium quality:
            # this makes those ranges behave like true zoom/detail views.
            # 3kHz is naturally capped at 64 vertices because it contains only
            # 64 distinct FFT bins.
            effective_quality.eq(Mux(
                (sweep_range != 3) &
                    ((sweep_quality_3d == 2) | (sweep_range != 0)),
                2,
                1)),
            scan_point_last.eq(Mux(
                effective_quality == 1, 63, 127)),
            scan_group_shift.eq(Mux(
                effective_quality == 1,
                    Mux(sweep_range <= 1, 2,
                        Mux(sweep_range == 2, 1, 0)),
                    Mux(sweep_range <= 1, 1, 0),
            )),
            frequency_coordinate.eq(Mux(
                effective_quality == 1,
                scan_point << 2,
                scan_point << 1)),
            # Static diagnostic: two fixed triangular peaks across all history
            # slices. This is deliberately boring and legible so framebuffer
            # clear/swap problems stand out as missing or duplicated ridges.
            static_delta_a.eq(Mux(
                scan_point > 38,
                scan_point - 38,
                38 - scan_point)),
            static_delta_b.eq(Mux(
                scan_point > 92,
                scan_point - 92,
                92 - scan_point)),
            static_peak_a.eq(Mux(
                static_delta_a < 16,
                60 - (static_delta_a << 2),
                6)),
            static_peak_b.eq(Mux(
                static_delta_b < 12,
                42 - (static_delta_b << 2),
                6)),
            static_peak.eq(Mux(
                static_peak_a > static_peak_b,
                static_peak_a,
                static_peak_b)),
            scan_history_age.eq(Const(15, 4) - scan_slice),
            # Consecutive captures are spread across the full visual Z depth.
            scan_depth.eq(scan_history_age << 4),
            scan_group_base.eq(scan_point << scan_group_shift),
            scan_group_last.eq(Mux(
                scan_group_shift == 0, 0,
                Mux(scan_group_shift == 1, 1,
                    Mux(scan_group_shift == 2, 3, 7)))),
            scan_history_bin.eq(scan_group_base + scan_group_index),
            scan_peak_next.eq(Mux(
                sweep_static_surface,
                static_peak,
                Mux(history_r.data > scan_peak,
                    history_r.data,
                    scan_peak),
            )),
            scan_read_en.eq(0),
            scan_read_addr.eq(
                ((sweep_newest + scan_history_age) << 8) |
                scan_history_bin),
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
            sweep_hue_limited.eq(sweep_hue[:3]),
            sweep_axis_hue_a.eq(sweep_hue_limited + 2),
            sweep_axis_hue_b.eq(sweep_hue_limited + 4),
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

        with m.FSM(domain="dvi", name="waterfall_3d"):
            with m.State("IDLE"):
                m.d.dvi += [
                    clear_request.eq(0),
                    flush_request.eq(0),
                ]
                with m.If(enable_dvi & view_3d_dvi):
                    m.d.dvi += [
                        scan_slice.eq(0),
                        scan_point.eq(0),
                        # Freeze every property that can make one projected
                        # sweep disagree with another. The live analyzer may
                        # continue writing newer columns in the background.
                        sweep_newest.eq(newest_dvi),
                        sweep_range.eq(range_dvi),
                        sweep_rate.eq(rate_dvi),
                        sweep_hue.eq(hue_dvi),
                        sweep_phosphor.eq(phosphor_dvi),
                        sweep_quality_3d.eq(quality_3d_dvi),
                        sweep_static_surface.eq(static_surface_3d_dvi),
                        draw_generation.eq(visible_generation + 1),
                        render_activity_seen.eq(0),
                        clear_request.eq(1),
                    ]
                    for index in range(3):
                        m.d.dvi += [
                            sweep_projection_x[index].eq(projection_x_dvi[index]),
                            sweep_projection_y[index].eq(projection_y_dvi[index]),
                        ]
                    m.next = "WAIT_CLEAR"
                with m.Elif(~view_3d_dvi):
                    m.d.dvi += surface_valid.eq(0)

            with m.State("WAIT_CLEAR"):
                # The inactive physical framebuffer is cleared before every
                # 3D surface. After this point all pixels are literal display
                # pixels; no generation-tag reveal or persistence cleanup is
                # involved in the image shown to the user.
                with m.If(~view_3d_dvi):
                    m.d.dvi += clear_request.eq(0)
                    m.next = "IDLE"
                with m.Elif(clear_done_dvi):
                    m.d.dvi += clear_request.eq(0)
                    m.next = "START_BIN_GROUP"

            with m.State("START_BIN_GROUP"):
                m.d.dvi += [
                    scan_group_index.eq(0),
                    scan_peak.eq(0),
                ]
                m.next = "ISSUE_HISTORY_READ"

            with m.State("ISSUE_HISTORY_READ"):
                m.d.comb += scan_read_en.eq(1)
                m.next = "ACCUMULATE_BIN"

            with m.State("ACCUMULATE_BIN"):
                m.d.dvi += scan_peak.eq(scan_peak_next)
                with m.If(scan_group_index == scan_group_last):
                    m.next = "LOAD_HISTORY_POINT"
                with m.Else():
                    m.d.dvi += scan_group_index.eq(scan_group_index + 1)
                    m.next = "ISSUE_HISTORY_READ"

            with m.State("LOAD_HISTORY_POINT"):
                m.d.dvi += [
                    # Spread pooled vertices across the same 256-unit
                    # frequency coordinate used by the axes and projection.
                    point_frequency_base.eq(
                        frequency_coordinate.as_signed() - 128),
                    point_amplitude.eq(scan_peak << 2),
                    point_time.eq(scan_depth),
                    point_pixel.intensity.eq(Mux(
                        sweep_phosphor,
                        5 + scan_peak[3:6],
                        8 + scan_peak[4:6],
                    )),
                    point_pixel.color.eq(sweep_hue_limited),
                    point_cmd.eq(Mux(
                        scan_point == scan_point_last,
                        LineStripCmd.END, LineStripCmd.CONTINUE)),
                    point_next.eq(0),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("MULTIPLY_POINT"):
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
                m.next = "PUSH_POINT"

            with m.State("PUSH_POINT"):
                m.d.comb += line_fifo.w_en.eq(1)
                with m.If(line_fifo.w_rdy):
                    with m.Switch(point_next):
                        with m.Case(0):
                            with m.If(scan_point == scan_point_last):
                                m.d.dvi += scan_point.eq(0)
                                with m.If(scan_slice == 15):
                                    with m.If(axes_dvi):
                                        m.next = "AXIS_FREQUENCY_START"
                                    with m.Else():
                                        m.next = "WAIT_RENDER_COMPLETE"
                                with m.Elif(enable_dvi & view_3d_dvi):
                                    m.d.dvi += scan_slice.eq(scan_slice + 1)
                                    m.next = "START_BIN_GROUP"
                                with m.Else():
                                    m.next = "IDLE"
                            with m.Else():
                                m.d.dvi += scan_point.eq(scan_point + 1)
                                m.next = "START_BIN_GROUP"
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

            with m.State("WAIT_RENDER_COMPLETE"):
                # First drain commands and Bresenham. Plot requests still pass
                # through a write-back cache, so this is not yet a safe swap
                # boundary; the following state performs an explicit fence.
                with m.If((line_fifo.w_level != 0) | line_busy_dvi):
                    m.d.dvi += render_activity_seen.eq(1)
                with m.If(render_activity_seen &
                          (line_fifo.w_level == 0) & ~line_busy_dvi):
                    m.d.dvi += flush_request.eq(1)
                    m.next = "WAIT_CACHE_FLUSH"

            with m.State("WAIT_CACHE_FLUSH"):
                # ``flush_done`` is held until the request drops, so no pulse
                # can be missed while crossing between sync and DVI domains.
                with m.If(~view_3d_dvi):
                    m.d.dvi += flush_request.eq(0)
                    m.next = "IDLE"
                with m.Elif(flush_done_dvi):
                    m.d.dvi += [
                        flush_request.eq(0),
                        completed_generation.eq(draw_generation),
                        completed_hue.eq(sweep_hue),
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
                with m.If(~view_3d_dvi |
                          (display_ack_dvi == completed_generation[0])):
                    m.next = "WAIT_SWAP_VSYNC"

            with m.State("WAIT_SWAP_VSYNC"):
                # The video DMA latches its base at VSync. Reveal the matching
                # generation on that same frame boundary, never mid-scan.
                with m.If(~view_3d_dvi):
                    m.next = "IDLE"
                with m.Elif(self.i.vsync & ~prev_vsync):
                    m.d.dvi += [
                        visible_generation.eq(completed_generation),
                        visible_hue.eq(completed_hue),
                    ]
                    m.next = "IDLE"

            # Three bright reference axes share the same projection matrix as
            # the waterfall, so their orientation follows every camera move.
            with m.State("AXIS_FREQUENCY_START"):
                m.d.dvi += [
                    point_frequency_base.eq(-128),
                    point_amplitude.eq(0),
                    point_time.eq(0),
                    point_pixel.intensity.eq(13),
                    point_pixel.color.eq(sweep_hue_limited),
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
                    point_pixel.color.eq(sweep_hue_limited),
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
                    point_pixel.color.eq(sweep_axis_hue_a),
                    point_cmd.eq(LineStripCmd.CONTINUE),
                    point_next.eq(3),
                ]
                m.next = "MULTIPLY_POINT"

            with m.State("AXIS_AMPLITUDE_END"):
                m.d.dvi += [
                    point_frequency_base.eq(-128),
                    point_amplitude.eq(252),
                    point_time.eq(0),
                    point_pixel.intensity.eq(14),
                    point_pixel.color.eq(sweep_axis_hue_a),
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
                    point_pixel.color.eq(sweep_axis_hue_b),
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
                    point_pixel.color.eq(sweep_axis_hue_b),
                    point_cmd.eq(LineStripCmd.END),
                    point_next.eq(6),
                ]
                m.next = "MULTIPLY_POINT"

        wide = Signal()
        short = Signal()
        x_scale_shift = Signal(2)
        y_scale_shift = Signal(2)
        plot_w = Signal(12)
        plot_h = Signal(12)
        plot_x0 = Signal(signed(12))
        plot_y0 = Signal(signed(12))
        rel_x = Signal(signed(13))
        rel_y = Signal(signed(13))
        rev_y = Signal(12)
        age = Signal(8)
        completed_age = Signal(8)
        bin_addr = Signal(8)
        spectrum_bin = Signal(8)
        spectrum_linear_bin = Signal(8)
        spectrum_linear_first = Signal()
        spectrum_linear_gap = Signal()
        spectrum_bin_prev = Signal(8)
        frequency_shift = Signal(2)
        spectrum_desired_group_shift_dvi = Signal(2)
        spectrum_group_shift_dvi = Signal(2)
        spectrum_band_pixel_shift = Signal(4)
        spectrum_band_first = Signal()
        spectrum_band_gap = Signal()
        spectrum_prefetch = Signal()
        spectrum_read_region = Signal()
        spectrum_log_col = Signal(8)
        spectrum_log_coord_q8 = Signal(16)
        spectrum_log_bin = Signal(8)
        spectrum_log_frac = Signal(8)
        spectrum_prefetch_calc = Signal()
        spectrum_prefetch_pipe = Signal()
        spectrum_style_pipe = Signal()
        spectrum_scale_pipe = Signal()
        spectrum_log_curve_pipe = Signal()
        spectrum_linear_bin_pipe = Signal(8)
        spectrum_linear_first_pipe = Signal()
        spectrum_linear_gap_pipe = Signal()
        spectrum_plot_pipe = Signal()
        spectrum_read_en_r = Signal()
        spectrum_read_bin_r = Signal(8)
        spectrum_read_first_r = Signal()
        spectrum_read_gap_r = Signal()
        spectrum_read_prefetch_r = Signal()
        spectrum_read_plot_r = Signal()
        spectrum_read_frac_r = Signal(8)
        in_plot = Signal()
        m.d.dvi += [
            spectrum_prefetch_pipe.eq(spectrum_prefetch_calc),
            spectrum_style_pipe.eq(spectrum_style_dvi),
            spectrum_scale_pipe.eq(spectrum_scale_dvi),
            spectrum_log_curve_pipe.eq(spectrum_style_dvi & spectrum_scale_dvi),
            spectrum_linear_bin_pipe.eq(spectrum_linear_bin),
            spectrum_linear_first_pipe.eq(spectrum_linear_first),
            spectrum_linear_gap_pipe.eq(spectrum_linear_gap),
            spectrum_plot_pipe.eq(in_plot & spectrum_mode_dvi),
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
                                        spectrum_log_frac, 0)),
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
        m.d.comb += [
            wide.eq(h_active_dvi >= 1024),
            short.eq(v_active_dvi < 600),
            x_scale_shift.eq(Mux(wide, 2, 1)),
            y_scale_shift.eq(Mux(short, 0, 1)),
            plot_w.eq(HISTORY_COLS << x_scale_shift),
            plot_h.eq(N_BINS << y_scale_shift),
            plot_x0.eq((h_active_dvi - plot_w) >> 1),
            plot_y0.eq((v_active_dvi - plot_h) >> 1),
            rel_x.eq(self.i.x - plot_x0),
            rel_y.eq(self.i.y - plot_y0),
            rev_y.eq(plot_h - 1 - rel_y),
            age.eq(rel_x.as_unsigned() >> x_scale_shift),
            # Age 255 is also the scratch column receiving the next FFT. Read
            # the adjacent completed column at the far edge so a partially
            # written spectrum cannot leak into the visible 2D history.
            completed_age.eq(Mux(age == 255, 254, age)),
            # Wide 24kHz mode uses all 256 bins. Fine mode also uses all bins
            # at 12kHz, then halves them for each smaller range.
            frequency_shift.eq(Mux(range_dvi == 0, 0, range_dvi - 1)),
            spectrum_desired_group_shift_dvi.eq(3 - spectrum_bands_dvi),
            spectrum_group_shift_dvi.eq(Mux(
                spectrum_style_dvi,
                0,
                Mux(spectrum_desired_group_shift_dvi > frequency_shift,
                    spectrum_desired_group_shift_dvi - frequency_shift,
                    0))),
            spectrum_band_pixel_shift.eq(
                x_scale_shift + frequency_shift +
                spectrum_group_shift_dvi),
            bin_addr.eq(rev_y >> (y_scale_shift + frequency_shift)),
            spectrum_linear_bin.eq(
                rel_x.as_unsigned() >> spectrum_band_pixel_shift),
            spectrum_linear_first.eq(
                rel_x.as_unsigned() ==
                (spectrum_linear_bin << spectrum_band_pixel_shift)),
            spectrum_linear_gap.eq(
                (spectrum_band_pixel_shift != 0) &
                (rel_x.as_unsigned() ==
                 (((spectrum_linear_bin + 1) <<
                    spectrum_band_pixel_shift) - 1))),
            # Curve mode follows a conventional analyzer-style logarithmic
            # frequency axis from 10 Hz to the selected range. Bars remain
            # linear and optionally pooled into fewer display bands.
            spectrum_log_col.eq(rel_x.as_unsigned() >> x_scale_shift),
            spectrum_log_bin.eq(spectrum_log_coord_q8[8:16] + 1),
            spectrum_log_frac.eq(spectrum_log_coord_q8[:8]),
            spectrum_prefetch_calc.eq(
                self.i.de & spectrum_mode_dvi & spectrum_style_dvi &
                (rel_x == -1) & (rel_y >= 0) & (rel_y < plot_h)),
            spectrum_prefetch.eq(spectrum_prefetch_pipe),
            spectrum_read_region.eq(
                spectrum_plot_pipe | spectrum_prefetch),
            spectrum_bin.eq(Mux(
                spectrum_prefetch,
                Mux(spectrum_scale_pipe, 1, 0),
                Mux(spectrum_log_curve_pipe,
                    spectrum_log_bin,
                    spectrum_linear_bin_pipe))),
            spectrum_band_first.eq(
                Mux(spectrum_style_pipe,
                    spectrum_prefetch |
                    (spectrum_bin != spectrum_bin_prev),
                    spectrum_linear_first_pipe)),
            spectrum_band_gap.eq(
                ~spectrum_style_pipe & spectrum_linear_gap_pipe),
            in_plot.eq(self.i.de & (rel_x >= 0) & (rel_x < plot_w) &
                       (rel_y >= 0) & (rel_y < plot_h)),
            history_r.en.eq(Mux(view_3d_dvi, scan_read_en, in_plot)),
            history_r.addr.eq(Mux(
                view_3d_dvi,
                scan_read_addr,
                ((newest_dvi + completed_age) << 8) | bin_addr,
            )),
            spectrum_levels_r.en.eq(spectrum_read_en_r),
            spectrum_levels_r.addr.eq(spectrum_read_bin_r),
            spectrum_focus_r.en.eq(spectrum_read_en_r),
            spectrum_focus_r.addr.eq(spectrum_read_bin_r),
            spectrum_peak_r.en.eq(spectrum_read_en_r),
            spectrum_peak_r.addr.eq(spectrum_read_bin_r),
        ]

        # Align scan and styling information with the synchronous BRAM read.
        scan_d = Signal(ScanPixel)
        spectrogram_plot_d = Signal()
        spectrum_plot_d = Signal()
        spectrum_band_d = Signal(8)
        spectrum_band_first_d = Signal()
        spectrum_band_gap_d = Signal()
        spectrum_prefetch_d = Signal()
        spectrum_log_frac_d = Signal(8)
        age_d = Signal(8)
        axes_hit_d = Signal()
        axes_hit = Signal()
        spectrum_grid_hit = Signal()
        spectrum_grid_hit_d = Signal()
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
            with m.If((range_dvi == range_index) & spectrum_style_dvi &
                      spectrum_scale_dvi):
                m.d.comb += curve_major_x.eq(Cat(*tick_hits).any())
        m.d.comb += [
            linear_major_x.eq((rel_x == 0) | (rel_x == (plot_w >> 2)) |
                              (rel_x == (plot_w >> 1)) |
                              (rel_x == plot_w - (plot_w >> 2)) |
                              (rel_x == plot_w - 1)),
            major_x.eq(Mux(
                spectrum_mode_dvi & spectrum_style_dvi & spectrum_scale_dvi,
                curve_major_x,
                linear_major_x)),
            major_y.eq((rel_y == 0) | (rel_y == (plot_h >> 2)) |
                       (rel_y == (plot_h >> 1)) |
                       (rel_y == plot_h - (plot_h >> 2)) |
                       (rel_y == plot_h - 1)),
            axes_hit.eq(~view_3d_dvi & axes_dvi & self.i.de &
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
                in_plot & spectrum_mode_dvi & axes_dvi &
                (major_x | major_y)),
        ]
        m.d.dvi += [
            scan_d.eq(self.i),
            spectrogram_plot_d.eq(
                in_plot & ~view_3d_dvi & ~spectrum_mode_dvi),
            spectrum_plot_d.eq(spectrum_read_plot_r),
            spectrum_band_d.eq(spectrum_read_bin_r),
            spectrum_band_first_d.eq(spectrum_read_first_r),
            spectrum_band_gap_d.eq(spectrum_read_gap_r),
            spectrum_prefetch_d.eq(spectrum_read_prefetch_r),
            spectrum_log_frac_d.eq(spectrum_read_frac_r),
            age_d.eq(age),
            axes_hit_d.eq(axes_hit),
            spectrum_grid_hit_d.eq(spectrum_grid_hit),
        ]

        # ---- persistent, dynamically scaled axis labels -------------------
        # Labels are generated in the beam-raced overlay rather than written
        # into the decaying framebuffer, so they remain crisp and cost no
        # redraw bandwidth. The X scale is elapsed history age (newest = 0)
        # and the Y scale follows the selected maximum frequency.
        label_active = Signal()
        label_char = Signal(7, init=ord(" "))
        label_col = Signal(3)
        label_row = Signal(3)
        m.d.comb += [
            label_active.eq(0),
            label_char.eq(ord(" ")),
            label_col.eq(0),
            label_row.eq(0),
        ]

        label_serial = 0

        def place_text(variants, selector, x0, y0):
            """Place one of several equal-width strings in an 8x8-cell font."""
            nonlocal label_serial
            if isinstance(variants, str):
                variants = [variants]
                selector = None
            width_chars = len(variants[0])
            assert all(len(text) == width_chars for text in variants)
            serial = label_serial
            label_serial += 1
            rel_lx = Signal(signed(13), name=f"axis_label_x_{serial}")
            rel_ly = Signal(signed(13), name=f"axis_label_y_{serial}")
            char_index = Signal(max(1, (width_chars - 1).bit_length()),
                                name=f"axis_char_index_{serial}")
            selected_char = Signal(7, name=f"axis_char_{serial}")
            active = Signal(name=f"axis_label_active_{serial}")
            m.d.comb += [
                rel_lx.eq(scan_d.x - x0),
                rel_ly.eq(scan_d.y - y0),
                char_index.eq(rel_lx.as_unsigned() >> 3),
                active.eq(~view_3d_dvi & axes_dvi & scan_d.de &
                          (rel_lx >= 0) & (rel_lx < width_chars * 8) &
                          (rel_ly >= 0) & (rel_ly < 8)),
                selected_char.eq(ord(" ")),
            ]
            if selector is None:
                chars = Array(Const(ord(ch), 7) for ch in variants[0])
                m.d.comb += selected_char.eq(chars[char_index])
            else:
                with m.Switch(selector):
                    for variant_index, text in enumerate(variants):
                        chars = Array(Const(ord(ch), 7) for ch in text)
                        with m.Case(variant_index):
                            m.d.comb += selected_char.eq(chars[char_index])
            with m.If(active):
                m.d.comb += [
                    label_active.eq(1),
                    label_char.eq(selected_char),
                    label_col.eq(rel_lx[:3]),
                    label_row.eq(rel_ly[:3]),
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
                    spectrum_style_dvi & spectrum_scale_dvi),
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
        place_text(["AGE (s) ", "FREQ(Hz)"], spectrum_mode_dvi,
                   plot_x0 + (plot_w >> 1) - 32,
                   plot_y0 + plot_h + axis_pad + 21)

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
        m.d.comb += label_hit.eq(
            label_active_d & (label_col_d < 5) &
            glyph_row.bit_select(label_col_d, 1))

        # Work in sixteenths of a visible palette step. This makes age fade
        # advance every history column rather than jumping one whole four-bit
        # intensity at a time. A 4x4 ordered dither preserves the fractional
        # part at the final four-bit palette boundary.
        fade = Signal(8)
        source_ext = Signal(9)
        faded_ext = Signal(9)
        display_ext = Signal(8)
        display_base = Signal(4)
        display_frac = Signal(4)
        dither_threshold = Signal(4)
        dither_index = Signal(4)
        display_level = Signal(4)
        with m.Switch(persistence_dvi):
            with m.Case(0):
                m.d.comb += fade.eq(age_d)
            with m.Case(1):
                m.d.comb += fade.eq(age_d >> 1)
            with m.Case(2):
                m.d.comb += fade.eq(age_d >> 2)
            with m.Default():
                m.d.comb += fade.eq(age_d >> 3)
        m.d.comb += dither_index.eq(Cat(scan_d.x[:2], scan_d.y[:2]))
        # 4x4 Bayer matrix, indexed by {y[1:0], x[1:0]}.
        bayer4 = [0, 8, 2, 10, 12, 4, 14, 6,
                  3, 11, 1, 9, 15, 7, 13, 5]
        with m.Switch(dither_index):
            for index, threshold in enumerate(bayer4):
                with m.Case(index):
                    m.d.comb += dither_threshold.eq(threshold)
        m.d.comb += [
            source_ext.eq((history_r.data << 2) + 8),
            faded_ext.eq(Mux(
                source_ext <= fade,
                0,
                source_ext - fade,
            )),
            display_ext.eq(Mux(
                phosphor_dvi,
                Mux(faded_ext > 255, 255, faded_ext[:8]),
                history_r.data << 2,
            )),
            display_base.eq(display_ext[4:8]),
            display_frac.eq(display_ext[:4]),
            display_level.eq(Mux(
                (display_frac > dither_threshold) & (display_base < 15),
                display_base + 1,
                display_base,
            )),
        ]

        # Spectrum mode beam-races pooled FFT bands. Bars and curves share the
        # same current-level table, smooth gradient fill, and falling peak
        # markers without writing a single pixel to the framebuffer.
        spectrum_height = Signal(12)
        spectrum_y = Signal(signed(13))
        spectrum_scan_y = Signal(signed(13))
        spectrum_line_hit = Signal()
        spectrum_curve_glow_hit = Signal()
        spectrum_curve_glow_level = Signal(4)
        spectrum_fill_hit = Signal()
        spectrum_peak_hit = Signal()
        spectrum_shape_pixel = Signal()
        spectrum_peak_height = Signal(12)
        spectrum_peak_y = Signal(signed(13))
        spectrum_peak_level = Signal(6)
        spectrum_peak_hold = Signal(5)
        spectrum_peak_state_epoch = Signal()
        spectrum_peak_state_valid = Signal()
        spectrum_peak_epoch = Signal()
        spectrum_mode_prev_dvi = Signal()
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
        spectrum_amplitude_level = Signal(4)
        spectrum_fill_level = Signal(4)
        spectrum_focus_peak = Signal()
        spectrum_focus_dim = Signal()
        spectrum_line_level = Signal(4)
        spectrum_curve_glow_level_focused = Signal(4)
        spectrum_fill_level_focused = Signal(4)
        spectrum_curve_raw_prev = Signal(6)
        spectrum_curve_target = Signal(6)
        spectrum_curve_light_ext = Signal(8)
        spectrum_curve_strong_ext = Signal(7)
        spectrum_curve_log_start = Signal(6)
        spectrum_curve_log_end = Signal(6)
        spectrum_curve_log_start_effective = Signal(6)
        spectrum_curve_log_end_effective = Signal(6)
        spectrum_curve_delta = Signal(signed(8))
        spectrum_curve_product = Signal(signed(13))
        spectrum_curve_display_q4 = Signal(signed(13))
        spectrum_curve_level = Signal(6)
        spectrum_curve_height = Signal(12)
        spectrum_peak_raw_prev = Signal(6)
        spectrum_peak_curve_start = Signal(6)
        spectrum_peak_curve_end = Signal(6)
        spectrum_peak_curve_start_effective = Signal(6)
        spectrum_peak_curve_end_effective = Signal(6)
        spectrum_peak_curve_delta = Signal(signed(8))
        spectrum_peak_curve_product = Signal(signed(13))
        spectrum_peak_curve_display_q4 = Signal(signed(13))
        spectrum_peak_curve_height = Signal(12)
        spectrum_peak_display_y = Signal(signed(13))
        spectrum_render_plot = Signal()
        spectrum_render_style = Signal()
        spectrum_render_shape = Signal()
        spectrum_render_y = Signal(signed(13))
        spectrum_render_peak_enabled = Signal()
        spectrum_render_peak_y = Signal(signed(13))
        spectrum_render_peak_level = Signal(4)
        spectrum_render_fill_enabled = Signal()
        spectrum_render_fill_level = Signal(4)
        spectrum_render_line_level = Signal(4)
        spectrum_render_glow_level = Signal(4)

        with m.If(self.i.vsync & ~prev_vsync):
            m.d.dvi += spectrum_peak_frame.eq(spectrum_peak_frame + 1)
        m.d.dvi += spectrum_mode_prev_dvi.eq(spectrum_mode_dvi)
        with m.If(spectrum_mode_dvi & ~spectrum_mode_prev_dvi):
            m.d.dvi += spectrum_peak_epoch.eq(~spectrum_peak_epoch)

        # Prefetch bin one immediately before each curve scanline. Curve X
        # then addresses the following endpoint, allowing interpolation
        # between adjacent FFT bins with only one BRAM read port.
        with m.If(spectrum_prefetch_d):
            m.d.dvi += [
                spectrum_curve_raw_prev.eq(spectrum_levels_r.data),
                spectrum_curve_log_start.eq(spectrum_levels_r.data),
                spectrum_curve_log_end.eq(spectrum_levels_r.data),
                spectrum_peak_raw_prev.eq(spectrum_peak_level),
                spectrum_peak_curve_start.eq(spectrum_peak_level),
                spectrum_peak_curve_end.eq(spectrum_peak_level),
            ]
        with m.Elif(spectrum_plot_d):
            with m.If(spectrum_band_first_d):
                m.d.dvi += [
                    spectrum_curve_raw_prev.eq(spectrum_levels_r.data),
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
        with m.Switch(spectrum_log_frac_d[6:8]):
            with m.Case(0):
                m.d.comb += [
                    spectrum_curve_product.eq(0),
                    spectrum_peak_curve_product.eq(0),
                ]
            with m.Case(1):
                m.d.comb += [
                    spectrum_curve_product.eq(spectrum_curve_delta << 2),
                    spectrum_peak_curve_product.eq(
                        spectrum_peak_curve_delta << 2),
                ]
            with m.Case(2):
                m.d.comb += [
                    spectrum_curve_product.eq(spectrum_curve_delta << 3),
                    spectrum_peak_curve_product.eq(
                        spectrum_peak_curve_delta << 3),
                ]
            with m.Default():
                m.d.comb += [
                    spectrum_curve_product.eq(
                        (spectrum_curve_delta << 3) +
                        (spectrum_curve_delta << 2)),
                    spectrum_peak_curve_product.eq(
                        (spectrum_peak_curve_delta << 3) +
                        (spectrum_peak_curve_delta << 2)),
                ]

        # Split fixed-point curve generation from raster hit-testing. This
        # one-pixel pipeline boundary keeps BRAM, smoothing and interpolation
        # off the final DVI output-priority path.
        m.d.dvi += [
            spectrum_render_plot.eq(spectrum_plot_d),
            spectrum_render_style.eq(spectrum_style_dvi),
            spectrum_render_shape.eq(spectrum_shape_pixel),
            spectrum_render_y.eq(spectrum_y),
            spectrum_render_peak_enabled.eq(
                (spectrum_peaks_dvi != 0) & (spectrum_peak_level != 0)),
            spectrum_render_peak_y.eq(spectrum_peak_display_y),
            spectrum_render_peak_level.eq(spectrum_peak_display_level),
            spectrum_render_fill_enabled.eq(spectrum_fill_dvi != 0),
            spectrum_render_fill_level.eq(spectrum_fill_level_focused),
            spectrum_render_line_level.eq(spectrum_line_level),
            spectrum_render_glow_level.eq(spectrum_curve_glow_level_focused),
        ]

        m.d.comb += [
            # Optional spatial smoothing blends only adjacent frequency bands.
            # Off retains the exact pooled analyzer values. Both filters use
            # power-of-two weights so the video path needs no multiplier.
            spectrum_curve_light_ext.eq(
                spectrum_curve_raw_prev +
                (spectrum_levels_r.data << 1) +
                spectrum_levels_r.data + 2),
            spectrum_curve_strong_ext.eq(
                spectrum_curve_raw_prev + spectrum_levels_r.data + 1),
            spectrum_curve_target.eq(Mux(
                spectrum_smoothing_dvi == 1,
                spectrum_curve_light_ext >> 2,
                Mux(spectrum_smoothing_dvi == 2,
                    spectrum_curve_strong_ext >> 1,
                    spectrum_levels_r.data))),
            spectrum_curve_log_start_effective.eq(Mux(
                spectrum_band_first_d,
                spectrum_curve_log_end,
                spectrum_curve_log_start)),
            spectrum_curve_log_end_effective.eq(Mux(
                spectrum_band_first_d,
                spectrum_curve_target,
                spectrum_curve_log_end)),
            spectrum_curve_delta.eq(
                Cat(spectrum_curve_log_end_effective,
                    Const(0, 1)).as_signed() -
                Cat(spectrum_curve_log_start_effective,
                    Const(0, 1)).as_signed()),
            spectrum_curve_display_q4.eq(
                (spectrum_curve_log_start_effective << 4) +
                spectrum_curve_product),
            spectrum_curve_level.eq(spectrum_curve_display_q4[4:10]),
            spectrum_peak_curve_start_effective.eq(Mux(
                spectrum_band_first_d,
                spectrum_peak_curve_end,
                spectrum_peak_curve_start)),
            spectrum_peak_curve_end_effective.eq(Mux(
                spectrum_band_first_d,
                spectrum_peak_level,
                spectrum_peak_curve_end)),
            spectrum_peak_curve_delta.eq(
                Cat(spectrum_peak_curve_end_effective,
                    Const(0, 1)).as_signed() -
                Cat(spectrum_peak_curve_start_effective,
                    Const(0, 1)).as_signed()),
            spectrum_peak_curve_display_q4.eq(
                (spectrum_peak_curve_start_effective << 4) +
                spectrum_peak_curve_product),
            # Keep four fractional amplitude bits through the
            # screen-space conversion. At 720p this improves the vertical
            # granularity from eight pixels to half a pixel before rounding.
            spectrum_curve_height.eq(
                (spectrum_curve_display_q4.as_unsigned() << y_scale_shift) >>
                2),
            spectrum_height.eq(
                Mux(spectrum_style_dvi,
                    spectrum_curve_height,
                    spectrum_levels_r.data << (y_scale_shift + 2))),
            spectrum_y.eq(plot_h - 1 - spectrum_height),
            spectrum_scan_y.eq(scan_d.y - plot_y0),
            spectrum_shape_pixel.eq(
                spectrum_style_dvi |
                ~spectrum_band_gap_d),
            spectrum_line_hit.eq(
                spectrum_render_plot & spectrum_plot_d & Mux(
                    spectrum_render_style,
                    spectrum_scan_y == spectrum_render_y,
                    spectrum_render_shape &
                    (spectrum_scan_y >= spectrum_render_y - 1) &
                    (spectrum_scan_y <= spectrum_render_y + 1))),
            spectrum_curve_glow_hit.eq(
                spectrum_render_plot & spectrum_plot_d &
                spectrum_render_style &
                (spectrum_scan_y >= spectrum_render_y - 1) &
                (spectrum_scan_y <= spectrum_render_y + 1)),
            spectrum_curve_glow_level.eq(Mux(
                spectrum_scan_y == spectrum_render_y,
                6,
                3)),
            # Hi-lite mode emphasizes the strongest detected spectral peak and
            # its integer multiples. The center bin stays bright, immediate
            # neighbors glow slightly less, and bins farther from the detected
            # fundamental/harmonics are dimmed.
            spectrum_focus_peak.eq(~spectrum_highlight_dvi |
                                   (spectrum_focus_r.data != 0)),
            spectrum_focus_dim.eq(spectrum_highlight_dvi &
                                  ~spectrum_focus_peak),
            spectrum_line_level.eq(Mux(
                spectrum_highlight_dvi,
                spectrum_focus_r.data,
                15)),
            spectrum_curve_glow_level_focused.eq(Mux(
                spectrum_focus_dim,
                Mux(spectrum_curve_glow_level > 1,
                    spectrum_curve_glow_level >> 1,
                    spectrum_curve_glow_level),
                spectrum_curve_glow_level)),
            spectrum_fill_hit.eq(
                spectrum_render_plot & spectrum_plot_d &
                spectrum_render_shape & spectrum_render_fill_enabled &
                (spectrum_scan_y > spectrum_render_y)),
            spectrum_peak_state_epoch.eq(spectrum_peak_r.data[11]),
            spectrum_peak_state_valid.eq(
                spectrum_peak_state_epoch == spectrum_peak_epoch),
            spectrum_peak_level.eq(Mux(
                spectrum_peak_state_valid,
                spectrum_peak_r.data[:6],
                0)),
            spectrum_peak_hold.eq(Mux(
                spectrum_peak_state_valid,
                spectrum_peak_r.data[6:11],
                0)),
            spectrum_peak_height.eq(
                spectrum_peak_level << (y_scale_shift + 2)),
            spectrum_peak_y.eq(plot_h - 1 - spectrum_peak_height),
            spectrum_peak_curve_height.eq(
                (spectrum_peak_curve_display_q4.as_unsigned() <<
                 y_scale_shift) >> 2),
            spectrum_peak_display_y.eq(Mux(
                spectrum_style_dvi,
                plot_h - 1 - spectrum_peak_curve_height,
                spectrum_peak_y)),
            spectrum_peak_hit.eq(
                spectrum_render_plot & spectrum_plot_d &
                spectrum_render_peak_enabled &
                Mux(spectrum_render_style,
                    spectrum_scan_y == spectrum_render_peak_y,
                    spectrum_render_shape &
                    (spectrum_scan_y == spectrum_render_peak_y))),
            spectrum_peak_display_level.eq(Mux(
                spectrum_peak_level[2:6] < 8,
                8,
                spectrum_peak_level[2:6])),
            spectrum_peak_update.eq(
                (spectrum_prefetch_d |
                 (spectrum_plot_d & spectrum_band_first_d)) &
                (spectrum_scan_y == 0)),
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
                (spectrum_gradient_frac > dither_threshold) &
                (spectrum_gradient_base < 15),
                spectrum_gradient_base + 1,
                spectrum_gradient_base)),
            # Amplitude fill gives every bar/curve column one palette index
            # derived from its measured level. Heat-map palettes therefore
            # color low and high bands differently across their entire fill.
            spectrum_amplitude_level.eq(Mux(
                spectrum_style_dvi,
                spectrum_curve_level[2:6],
                spectrum_levels_r.data[2:6])),
            spectrum_fill_level.eq(Mux(
                spectrum_fill_dvi == 1,
                4,
                Mux(spectrum_fill_dvi == 2,
                    spectrum_gradient_level,
                    spectrum_amplitude_level))),
            spectrum_fill_level_focused.eq(Mux(
                spectrum_focus_dim,
                spectrum_fill_level >> 1,
                Mux(spectrum_highlight_dvi &
                    (spectrum_fill_level < spectrum_focus_r.data),
                    spectrum_focus_r.data,
                    spectrum_fill_level))),
            spectrum_peak_level_next.eq(Mux(
                spectrum_peaks_dvi == 0,
                spectrum_levels_r.data,
                Mux(~spectrum_peak_state_valid |
                    (spectrum_levels_r.data >= spectrum_peak_level),
                    spectrum_levels_r.data,
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
                    (spectrum_levels_r.data >= spectrum_peak_level),
                    spectrum_peak_hold_init,
                    Mux(spectrum_peaks_dvi == 5,
                        31,
                        Mux(spectrum_peak_hold != 0,
                            spectrum_peak_hold - 1,
                            0))))),
            spectrum_peak_w.en.eq(spectrum_peak_update),
            spectrum_peak_w.addr.eq(spectrum_band_d),
            spectrum_peak_w.data.eq(Cat(
                spectrum_peak_level_next,
                spectrum_peak_hold_next,
                spectrum_peak_epoch)),
        ]

        # Register the spectrum/axis-line result separately from axis glyphs.
        # The final stage below overlays the pipelined glyph without extending
        # the history-BRAM rendering path.
        base_o = Signal(ScanPixel)
        ui_clear = Signal()
        menu_protect = Signal()
        m.d.comb += [
            menu_protect.eq(
                menu_visible_dvi & scan_d.de &
                (scan_d.x >= h_active_dvi - 230) &
                (scan_d.x < h_active_dvi - 32) &
                (scan_d.y >= (v_active_dvi >> 1) - 40) &
                (scan_d.y < (v_active_dvi >> 1) + 220)),
            ui_clear.eq((scan_d.pixel.intensity == 0) & ~menu_protect),
        ]
        m.d.dvi += base_o.eq(scan_d)
        with m.If(enable_dvi & ui_clear & spectrogram_plot_d &
                  (display_level != 0)):
            with m.If(display_level > scan_d.pixel.intensity):
                m.d.dvi += [
                    base_o.pixel.intensity.eq(display_level),
                    base_o.pixel.color.eq(hue_dvi),
                ]
        with m.Elif(enable_dvi & ui_clear & spectrum_peak_hit):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_render_peak_level),
                base_o.pixel.color.eq(hue_dvi + 8),
            ]
        with m.Elif(enable_dvi & ui_clear & spectrum_line_hit):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_render_line_level),
                base_o.pixel.color.eq(hue_dvi),
            ]
        with m.Elif(enable_dvi & ui_clear & spectrum_curve_glow_hit):
            m.d.dvi += [
                base_o.pixel.intensity.eq(spectrum_render_glow_level),
                base_o.pixel.color.eq(hue_dvi),
            ]
        with m.Elif(enable_dvi & ui_clear & spectrum_fill_hit):
            with m.If(scan_d.pixel.intensity < spectrum_render_fill_level):
                m.d.dvi += [
                    base_o.pixel.intensity.eq(spectrum_render_fill_level),
                    base_o.pixel.color.eq(hue_dvi),
                ]
        with m.Elif(enable_dvi & ui_clear & spectrum_grid_hit_d):
            with m.If(scan_d.pixel.intensity < 2):
                m.d.dvi += [
                    base_o.pixel.intensity.eq(2),
                    base_o.pixel.color.eq(hue_dvi),
                ]
        with m.Elif(enable_dvi & ui_clear & axes_dvi & axes_hit_d):
            m.d.dvi += [
                base_o.pixel.intensity.eq(10),
                base_o.pixel.color.eq(hue_dvi),
            ]

        m.d.dvi += self.o.eq(base_o)
        with m.If(enable_dvi & ui_clear & axes_dvi & label_hit):
            m.d.dvi += [
                self.o.pixel.intensity.eq(10),
                self.o.pixel.color.eq(hue_dvi),
            ]

        return m
