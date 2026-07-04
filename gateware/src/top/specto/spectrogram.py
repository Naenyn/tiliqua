# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""Streaming spectral analysis and beam-raced waterfall display."""

import math

from amaranth import *
from amaranth.lib import data, memory, stream, wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from amaranth_soc import csr
from amaranth_future import fixed

from tiliqua import dsp
from tiliqua.dsp import ASQ
from tiliqua.video.types import Pixel, ScanPixel


FFT_SIZE = 512
N_BINS = FFT_SIZE // 2
HISTORY_COLS = 256

# Compact beam-raced font used for persistent axis labels. Each string is one
# five-pixel row; characters occupy an 8x8 cell to make addressing shift-only.
FONT_5X7 = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
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
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
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

    def __init__(self, *, fs):
        self.fs = fs

        regs = csr.Builder(addr_width=5, data_width=8)
        self._flags = regs.add("flags", self.Flags(), offset=0x00)
        self._gain = regs.add("gain", self.Gain(), offset=0x04)
        self._range = regs.add("range", self.Range(), offset=0x08)
        self._rate = regs.add("rate", self.Rate(), offset=0x0c)
        self._persistence = regs.add("persistence", self.Persistence(), offset=0x10)
        self._hue = regs.add("hue", self.Hue(), offset=0x14)
        self._timings = regs.add("timings", self.Timings(), offset=0x18)
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
        input_ch = Signal(2)
        gain = Signal(4)
        range_sel = Signal(2)
        rate_sel = Signal(2, init=1)
        persistence = Signal(2, init=2)
        hue = Signal(4, init=5)
        h_active = Signal(12, init=720)
        v_active = Signal(12, init=720)

        with m.If(self._flags.element.w_stb):
            m.d.sync += [
                enable.eq(self._flags.f.enable.w_data),
                phosphor.eq(self._flags.f.phosphor.w_data),
                axes.eq(self._flags.f.axes.w_data),
                input_ch.eq(self._flags.f.input_ch.w_data),
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

        # Analytical mode responds quickly; phosphor mode deliberately blends
        # adjacent analysis frames before they enter the history.
        m.d.comb += envelope.block_lpf.beta.eq(Mux(
            phosphor,
            fixed.Const(0.82, shape=ASQ),
            fixed.Const(0.25, shape=ASQ),
        ))

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

        write_col = Signal(8)
        newest_col = Signal(8)
        bin_index = Signal(9)
        frame_seq = Signal(4)
        accept_latched = Signal()

        accept_now = Signal()
        with m.Switch(rate_sel):
            with m.Case(0):
                m.d.comb += accept_now.eq(
                    Mux(fine_mode, 1, frame_seq[0] == 0))
            with m.Case(1):
                m.d.comb += accept_now.eq(Mux(
                    fine_mode,
                    frame_seq[0] == 0,
                    frame_seq[:2] == 0,
                ))
            with m.Case(2):
                m.d.comb += accept_now.eq(Mux(
                    fine_mode,
                    frame_seq[:2] == 0,
                    frame_seq[:3] == 0,
                ))
            with m.Default():
                m.d.comb += accept_now.eq(Mux(
                    fine_mode,
                    frame_seq[:3] == 0,
                    frame_seq == 0,
                ))

        current_bin = Signal(9)
        do_write = Signal()
        raw_level = Signal(6)
        boosted_level = Signal(7)
        stored_level = Signal(6)
        m.d.comb += [
            log.o.ready.eq(1),
            current_bin.eq(Mux(log.o.payload.first, 0, bin_index)),
            do_write.eq(Mux(log.o.payload.first, accept_now, accept_latched)),
            raw_level.eq(log.o.payload.sample.as_value()[ASQ.f_bits-6:ASQ.f_bits]),
            boosted_level.eq(raw_level + gain),
            stored_level.eq(Mux(boosted_level > 63, 63, boosted_level[:6])),
            history_w.en.eq(log.o.valid & do_write & (current_bin < N_BINS)),
            history_w.addr.eq((write_col << 8) | current_bin[:8]),
            history_w.data.eq(stored_level),
        ]

        with m.If(log.o.valid):
            with m.If(log.o.payload.first):
                m.d.sync += [
                    bin_index.eq(1),
                    frame_seq.eq(frame_seq + 1),
                    accept_latched.eq(accept_now),
                ]
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
        range_dvi = Signal(2)
        rate_dvi = Signal(2)
        persistence_dvi = Signal(2)
        hue_dvi = Signal(4)
        h_active_dvi = Signal(12)
        v_active_dvi = Signal(12)
        newest_gray = Signal(8)
        newest_gray_meta = Signal(8)
        newest_binary_meta = Signal(8)
        m.d.comb += newest_gray.eq(newest_col ^ (newest_col >> 1))
        for name, src, dst in [
            ("enable", enable, enable_dvi),
            ("phosphor", phosphor, phosphor_dvi),
            ("axes", axes, axes_dvi),
            ("range", range_sel, range_dvi),
            ("rate", rate_sel, rate_dvi),
            ("persistence", persistence, persistence_dvi),
            ("h_active", h_active, h_active_dvi),
            ("v_active", v_active, v_active_dvi),
            ("newest_gray", newest_gray, newest_gray_meta),
            ("hue", hue, hue_dvi),
        ]:
            setattr(m.submodules, f"{name}_ff", FFSynchronizer(src, dst, o_domain="dvi"))

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
        bin_addr = Signal(8)
        frequency_shift = Signal(2)
        in_plot = Signal()
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
            # Wide 24kHz mode uses all 256 bins. Fine mode also uses all bins
            # at 12kHz, then halves them for each smaller range.
            frequency_shift.eq(Mux(range_dvi == 0, 0, range_dvi - 1)),
            bin_addr.eq(rev_y >> (y_scale_shift + frequency_shift)),
            in_plot.eq(self.i.de & (rel_x >= 0) & (rel_x < plot_w) &
                       (rel_y >= 0) & (rel_y < plot_h)),
            history_r.en.eq(in_plot),
            history_r.addr.eq(((newest_dvi + age) << 8) | bin_addr),
        ]

        # Align scan and styling information with the synchronous BRAM read.
        scan_d = Signal(ScanPixel)
        in_plot_d = Signal()
        age_d = Signal(8)
        axes_hit_d = Signal()
        axes_hit = Signal()
        major_x = Signal()
        major_y = Signal()
        m.d.comb += [
            major_x.eq((rel_x == 0) | (rel_x == (plot_w >> 2)) |
                       (rel_x == (plot_w >> 1)) |
                       (rel_x == plot_w - (plot_w >> 2)) |
                       (rel_x == plot_w - 1)),
            major_y.eq((rel_y == 0) | (rel_y == (plot_h >> 2)) |
                       (rel_y == (plot_h >> 1)) |
                       (rel_y == plot_h - (plot_h >> 2)) |
                       (rel_y == plot_h - 1)),
            axes_hit.eq(axes_dvi & self.i.de &
                        (((rel_x == 0) & (rel_y >= 0) & (rel_y < plot_h)) |
                         ((rel_y == plot_h - 1) & (rel_x >= 0) & (rel_x < plot_w)) |
                         (in_plot & major_x & (rel_y >= plot_h - 6)) |
                         (in_plot & major_y & (rel_x < 6)))),
        ]
        m.d.dvi += [
            scan_d.eq(self.i),
            in_plot_d.eq(in_plot),
            age_d.eq(age),
            axes_hit_d.eq(axes_hit),
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
                active.eq(axes_dvi & scan_d.de &
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

        # Y frequency labels, top to bottom. Fixed-width padding keeps all
        # values aligned against the left-hand axis.
        y_label_x = plot_x0 - 48
        y_tick_positions = [
            plot_y0 - 3,
            plot_y0 + (plot_h >> 2) - 3,
            plot_y0 + (plot_h >> 1) - 3,
            plot_y0 + plot_h - (plot_h >> 2) - 3,
            plot_y0 + plot_h - 8,
        ]
        y_labels = [
            ["  24k", "  12k", "   6k", "   3k"],
            ["  18k", "   9k", " 4.5k", "2.25k"],
            ["  12k", "   6k", "   3k", " 1.5k"],
            ["   6k", "   3k", " 1.5k", "  750"],
            ["    0", "    0", "    0", "    0"],
        ]
        for variants, y_pos in zip(y_labels, y_tick_positions):
            place_text(variants, range_dvi, y_label_x, y_pos)
        place_text("FREQ (Hz)", None, plot_x0 - 72, plot_y0 - 20)

        # Frame acceptance compensates for analyzer rate, so columns remain
        # 10.667ms, 21.333ms, 42.667ms and 85.333ms apart in both modes.
        place_text("0", None, plot_x0, plot_y0 + plot_h + 8)
        place_text(["1.37s", "2.73s", "5.46s", "10.9s"], rate_dvi,
                   plot_x0 + (plot_w >> 1) - 20, plot_y0 + plot_h + 8)
        place_text(["2.72s", "5.44s", "10.9s", "21.8s"], rate_dvi,
                   plot_x0 + plot_w - 40, plot_y0 + plot_h + 8)
        place_text("AGE (s)", None, plot_x0 + (plot_w >> 1) - 28,
                   plot_y0 + plot_h + 24)

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

        # Register the spectrum/axis-line result separately from axis glyphs.
        # The final stage below overlays the pipelined glyph without extending
        # the history-BRAM rendering path.
        base_o = Signal(ScanPixel)
        m.d.dvi += base_o.eq(scan_d)
        with m.If(enable_dvi & in_plot_d & (display_level != 0)):
            with m.If(display_level > scan_d.pixel.intensity):
                m.d.dvi += [
                    base_o.pixel.intensity.eq(display_level),
                    base_o.pixel.color.eq(hue_dvi),
                ]
        with m.Elif(enable_dvi & axes_dvi & axes_hit_d):
            m.d.dvi += [
                base_o.pixel.intensity.eq(10),
                base_o.pixel.color.eq(hue_dvi),
            ]

        m.d.dvi += self.o.eq(base_o)
        with m.If(enable_dvi & axes_dvi & label_hit):
            m.d.dvi += [
                self.o.pixel.intensity.eq(10),
                self.o.pixel.color.eq(hue_dvi),
            ]

        return m
