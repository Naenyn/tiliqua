# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""
OSCIO is a four-channel digital oscilloscope for Eurorack signals.

All four analog inputs are displayed together. Each input is also passed
straight through to the matching output with no USB or delay-line processing.

    .. code-block:: text

        in1 ───────────────────────► out1
        in2 ───────────────────────► out2
        in3 ───────────────────────► out3
        in4 ───────────────────────► out4

        trigger source: selectable from in1, in2, in3, or in4

Turn the encoder to move through the menu. Press it to select a page or
parameter, then turn to edit. The menu hides automatically; turning resumes
the current edit, while pressing reopens it in navigation mode.

CHANNEL 1-2 and CHANNEL 3-4 set each trace's vertical offset, volts per
division, and visibility.

OSCIO sets time/div, trigger mode, source, level, filter, and acquisition.

Rising and falling are strict trigger modes: each sweep waits for the selected
channel to cross trig lvl in the chosen direction. If no crossing arrives, the
completed display is held. Auto rise and auto fall prefer the same locked edge,
but start an untriggered refresh after 50 ms if the edge is lost. Free starts a
new sweep immediately and does not lock to the signal.

Trig filter low-passes trigger detection without filtering any displayed trace.
Start with off or 5kHz and use the highest cutoff that gives stable lock. Lower
cutoffs (1.2kHz, 300Hz, and 75Hz) reject progressively more harmonics, but may
attenuate the trigger waveform or make its crossing arrive later.

Use acquire clean for normal viewing. It is the recommended default and makes
square, saw, and other sharp-edged waves look more like their intended shape.
Use acquire raw when diagnosing the input itself and you want OSCIO to show the
calibrated samples without edge cleanup. Raw may make sharp transitions look
rougher or spikier, so it is usually less useful as the everyday display mode.

DISPLAY sets grid style, grid and trace intensity, trace hue, and graph
palette. MENU changes the overlay hue, automatic hide delay, and whether that
delay remains active while editing. MISC contains screen rotation and settings
save/reset actions. HELP is the final menu page.

On this page, turn the encoder to scroll. Select the HELP page title to return
to the preceding menu pages.
"""

import os
import sys

from amaranth import *
from amaranth.lib import data, wiring

from tiliqua import dsp
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.periph import overlay
from tiliqua.periph import ui_overlay
from tiliqua.raster import PSQ
from tiliqua.raster.digital_scope import DigitalScopePeripheral
from tiliqua.raster.scope_overlay import ScopeTraceOverlay
from tiliqua.tiliqua_soc import TiliquaSoc


class ScopeSoc(TiliquaSoc):

    module_docstring = sys.modules[__name__].__doc__
    help_visible_lines = 28

    bitstream_help = BitstreamHelp(
        brief="Four-channel triggered oscilloscope with audio thru.",
        io_left=['CH1 in', 'CH2 in', 'CH3 in', 'CH4 in',
                 'CH1 thru', 'CH2 thru', 'CH3 thru', 'CH4 thru'],
        io_right=['menu / adjust', '', 'video out', '', '', '']
    )

    def __init__(self, **kwargs):

        self.scope_trace = ScopeTraceOverlay()
        self.overlay_periph = overlay.Peripheral(
            enable_ui=True, trace=self.scope_trace)
        self.overlay_ui_mem_base = 0xc1000000

        super().__init__(finalize_csr_bridge=False,
                         fb_overlay=self.overlay_periph.overlay,
                         enable_persist=False,
                         enable_uart=False,
                         enable_dtr=False,
                         **kwargs)

        # Firmware bitmap scratch in PSRAM (blockram is only 16 KiB).
        self.overlay_ui_scratch_base = self.psram_base + 0x00F0_0000

        self.scope_periph_base  = 0x00001100
        self.overlay_periph_base = 0x00001300

        self.wb_decoder.add(
            self.overlay_periph.ui_mem.bus,
            addr=self.overlay_ui_mem_base,
            name="overlay_ui")

        self.add_rust_constant(
            f"pub const OVERLAY_UI_SCRATCH_BASE: usize = 0x{self.overlay_ui_scratch_base:x};")
        self.add_rust_constant(
            f"pub const OVERLAY_UI_MEM_BASE: usize = 0x{self.overlay_ui_mem_base:x};")
        self.add_rust_constant(
            f"pub const OVERLAY_UI_MENU_W: usize = {ui_overlay.MENU_W};")
        self.add_rust_constant(
            f"pub const OVERLAY_UI_MENU_H: usize = {ui_overlay.MENU_H};")
        self.add_rust_constant(
            f"pub const OVERLAY_UI_MENU_WORDS: usize = {ui_overlay.MENU_WORDS};")
        help_scroll_max = max(
            0,
            len(self.module_docstring.splitlines()) - self.help_visible_lines,
        )
        self.add_rust_constant(
            f"pub const HELP_SCROLL_MAX: u8 = {help_scroll_max};")

        self.n_upsample = 8 if self.clock_settings.audio_clock.is_192khz() else 32

        self.scope_periph = DigitalScopePeripheral(
            fs=self.clock_settings.audio_clock.fs() * self.n_upsample)
        self.csr_decoder.add(self.scope_periph.bus, addr=self.scope_periph_base, name="scope_periph")

        self.csr_decoder.add(self.overlay_periph.bus, addr=self.overlay_periph_base, name="overlay_periph")

        self.finalize_csr_bridge()

    def elaborate(self, platform):

        m = Module()

        m.submodules.scope_periph = self.scope_periph
        m.submodules.overlay_periph = self.overlay_periph

        m.d.comb += [
            self.scope_trace.enable.eq(self.scope_periph.soc_en),
            self.scope_trace.flush_valid.eq(self.scope_periph.flush_valid),
            self.scope_trace.flush_col.eq(self.scope_periph.flush_col),
            self.scope_trace.flush_word.eq(self.scope_periph.flush_word),
            self.scope_trace.sweep_done.eq(self.scope_periph.sweep_done),
            self.scope_trace.progressive.eq(self.scope_periph.progressive_o),
            self.scope_trace.capture_max_col.eq(
                self.scope_periph.capture_max_col_o),
            self.scope_trace.capture_progress_valid.eq(
                self.scope_periph.capture_progress_valid_o),
            self.scope_periph.capture_active.eq(self.scope_trace.capture_active),
            self.scope_periph.capture_clear.eq(self.scope_trace.capture_clear),
            self.scope_periph.swap_done.eq(self.scope_trace.swap_done),
            self.scope_trace.plot_x_lo.eq(self.scope_periph.plot_x_lo_o),
            self.scope_trace.h_active.eq(self.fb.fbp.timings.h_active),
            self.scope_trace.v_active.eq(self.fb.fbp.timings.v_active),
            self.scope_trace.rotation.eq(self.fb.fbp.rotation),
        ]
        for ch in range(4):
            m.d.comb += [
                self.scope_trace.hue[ch].eq(self.scope_periph.hue_o[ch]),
                self.scope_trace.intensity[ch].eq(
                    self.scope_periph.intensity_o[ch]),
            ]

        m.submodules += super().elaborate(platform)

        pmod0 = self.pmod0_periph.pmod

        wiring.connect(m, pmod0.o_cal, pmod0.i_cal)

        m.submodules.plot_fifo = plot_fifo = dsp.SyncFIFOBuffered(
            shape=data.ArrayLayout(dsp.ASQ, 4), depth=256)

        dsp.connect_peek(m, pmod0.o_cal, plot_fifo.i)

        # The four input channels share reconstruction/interpolation arithmetic.
        # Their history and interpolation state remain independent, and both
        # blocks emit channel-aligned bundles. At 192 kHz there are ~312 sync
        # clocks per input frame; the serialized path needs fewer than 50.
        m.submodules.edge_reconstruct = edge = \
            dsp.MultichannelDiscontinuityReconstruct(
                n_channels=4, shape=dsp.ASQ)
        m.submodules.resample = resample = \
            dsp.MultichannelEdgeAwareResample(
                n_channels=4, n_up=self.n_upsample, shape=dsp.ASQ)
        m.submodules.plot_convert = plot_convert = \
            dsp.MultichannelFixedPointConvert(
                n_channels=4, input_shape=dsp.ASQ, output_shape=PSQ)
        m.d.comb += edge.enable.eq(self.scope_periph.clean_o)
        wiring.connect(m, plot_fifo.o, edge.i)
        wiring.connect(m, edge.o, resample.i)
        wiring.connect(m, resample.o, plot_convert.i)
        wiring.connect(m, plot_convert.o, self.scope_periph.i)

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(ScopeSoc, path=this_path, archiver_callback=lambda archiver: archiver.with_option_storage())
