# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""
WATERFALL is a three-dimensional spectrogram for Eurorack signals, with a
selectable input and four-channel analog passthrough.

A 512-point Hann-windowed FFT analyzes one selected input. Sixteen spectra form
either a filled triangular height field or connected wire ridges: frequency
runs across the display, amplitude rises vertically, and older spectra recede
into the screen.
The analysis rate follows the selected 24/12/6/3kHz range, using 48/24/12/6kHz
feeds respectively. This keeps the full selected bandwidth while progressively
improving FFT resolution from 93.75Hz/bin to 11.72Hz/bin.

All four analog inputs pass directly to their matching outputs:

    .. code-block:: text

        in1 ───────────────────────► out1
        in2 ───────────────────────► out2
        in3 ───────────────────────► out3
        in4 ───────────────────────► out4

WATERFALL options select the input, sensitivity, maximum displayed frequency,
and history speed. VIEW selects a wire or filled terrain mesh, its quality, and
rotates the camera independently around the X, Y and Z axes in 15-degree steps.
DISPLAY controls the projected reference axes, plot hue, palette, and a
display-only noise floor. The noise floor hides low-level display clutter
without changing the analyzed signal. The Inferno palette supports hue
rotation while preserving its heatmap gradient; grayscale palettes
intentionally ignore hue. MISC contains display rotation and settings
save/reset actions.
"""

import os
import sys

from amaranth import Module, Signal
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer

from tiliqua import dsp
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.raster import line, triangle
from tiliqua.tiliqua_soc import TiliquaSoc

from spectrogram import Spectrogram


class WaterfallSoc(TiliquaSoc):

    module_docstring = sys.modules[__name__].__doc__

    bitstream_help = BitstreamHelp(
        brief="Four-channel 3D spectrogram.",
        io_left=['CH1 in', 'CH2 in', 'CH3 in', 'CH4 in',
                 'CH1 thru', 'CH2 thru', 'CH3 thru', 'CH4 thru'],
        io_right=['menu / adjust', '', 'video out', '', '', '']
    )

    def __init__(self, **kwargs):
        self.spectrogram = Spectrogram(
            fs=kwargs["clock_settings"].audio_clock.fs())
        self.waterfall_line_plotter = line._LinePlotter()
        self.waterfall_triangle_plotter = triangle.TrianglePlotter()

        super().__init__(
            finalize_csr_bridge=False,
            # Spectrogram is a timing-only pass-through in the DVI path. It
            # observes VSync for atomic surface swaps without paying for the
            # unused general-purpose grid overlay.
            fb_overlay=self.spectrogram,
            extra_plot_ports=2,
            with_persist=False,
            **kwargs,
        )

        self.spectrogram_periph_base = 0x00001000
        self.csr_decoder.add(
            self.spectrogram.bus,
            addr=self.spectrogram_periph_base,
            name="spectrogram_periph",
        )
        self.finalize_csr_bridge()

    def elaborate(self, platform):
        m = Module()
        m.submodules.spectrogram = self.spectrogram
        m.submodules.waterfall_line_plotter = self.waterfall_line_plotter
        m.submodules.waterfall_triangle_plotter = self.waterfall_triangle_plotter
        m.submodules += super().elaborate(platform)

        wiring.connect(
            m, self.spectrogram.line_o, self.waterfall_line_plotter.i)
        wiring.connect(
            m, self.spectrogram.triangle_o,
            self.waterfall_triangle_plotter.i)
        m.d.comb += self.spectrogram.line_busy.eq(
            self.waterfall_line_plotter.busy |
            self.waterfall_triangle_plotter.busy)
        m.d.comb += [
            self.waterfall_line_plotter.alternate.eq(1),
            self.waterfall_triangle_plotter.alternate.eq(1),
            self.waterfall_triangle_plotter.h_active.eq(
                self.fb.fbp.timings.h_active),
            self.waterfall_triangle_plotter.v_active.eq(
                self.fb.fbp.timings.v_active),
        ]
        # Video scanout is the only hard real-time PSRAM client. Backpressure
        # the exact line renderer whenever its FIFO reserve is being refilled;
        # this changes completion latency, not geometry, and prevents complex
        # spectra from starving the visible framebuffer DMA.
        waterfall_pixels = self.waterfall_line_plotter.o
        waterfall_plot = self.framebuffer_plotter.i[3]
        terrain_pixels = self.waterfall_triangle_plotter.o
        terrain_plot = self.framebuffer_plotter.i[4]
        m.d.comb += [
            waterfall_plot.payload.eq(waterfall_pixels.payload),
            waterfall_plot.valid.eq(
                waterfall_pixels.valid & ~self.fb.scanout_urgent),
            waterfall_pixels.ready.eq(
                waterfall_plot.ready & ~self.fb.scanout_urgent),
            terrain_plot.payload.eq(terrain_pixels.payload),
            terrain_plot.valid.eq(
                terrain_pixels.valid & ~self.fb.scanout_urgent),
            terrain_pixels.ready.eq(
                terrain_plot.ready & ~self.fb.scanout_urgent),
        ]

        # A full-cache fence turns "last pixel accepted" into "all pixels are
        # committed to PSRAM" before firmware swaps the displayed base.
        flush_request_sync = Signal()
        m.submodules.flush_request_ff = FFSynchronizer(
            self.spectrogram.flush_request, flush_request_sync,
            o_domain="sync")
        m.d.comb += [
            self.framebuffer_plotter.flush.eq(flush_request_sync),
            self.spectrogram.flush_done.eq(
                self.framebuffer_plotter.flush_done),
        ]

        pmod0 = self.pmod0_periph.pmod

        # All analog inputs pass straight through to their matching outputs.
        wiring.connect(m, pmod0.o_cal, pmod0.i_cal)
        dsp.connect_peek(m, pmod0.o_cal, self.spectrogram.audio_i)

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(
        WaterfallSoc,
        path=this_path,
        archiver_callback=lambda archiver: archiver.with_option_storage(),
    )
