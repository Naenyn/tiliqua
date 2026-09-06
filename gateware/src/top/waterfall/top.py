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

from amaranth import Module, Mux, Signal
from amaranth.lib import wiring
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from amaranth_soc import wishbone

from tiliqua import dsp
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.raster import line, span
from tiliqua.tiliqua_soc import TiliquaSoc
from tiliqua.video.framebuffer import DMAFramebuffer
from tiliqua.video.types import Pixel

from spectrogram import Spectrogram


class BackbufferClear(wiring.Component):
    """Burst-clear the inactive WATERFALL framebuffer region.

    The 3D renderer draws a complete surface into the framebuffer that is not
    currently being scanned out, then swaps at a VSync boundary. Clearing that
    back buffer explicitly is much more deterministic than relying on tagged
    pixel decay to eventually remove stale geometry.
    """

    def __init__(self, *, bus_signature, burst_words=128):
        self.burst_words = burst_words
        super().__init__({
            "start": In(1),
            "alternate": In(1, init=1),
            "pause": In(1),
            "done": Out(1),
            "busy": Out(1),
            "bus": Out(bus_signature),
            "fbp": In(DMAFramebuffer.Properties()),
        })

    def elaborate(self, platform):
        m = Module()

        bus = self.bus
        pixel_bits = Pixel.as_shape().size
        pixel_bytes = pixel_bits // 8
        fb_len_words = ((self.fbp.timings.active_pixels * pixel_bytes) //
                        (bus.data_width // pixel_bits))

        base = Signal.like(self.fbp.base)
        offset = Signal(bus.addr_width)
        burst_count = Signal(range(self.burst_words))
        done = Signal()
        final_word = Signal()
        final_burst_word = Signal()

        m.d.comb += [
            self.done.eq(done),
            final_word.eq(offset == (fb_len_words - 1)),
            final_burst_word.eq(burst_count == (self.burst_words - 1)),
        ]

        with m.FSM() as fsm:
            with m.State("IDLE"):
                with m.If(~self.start):
                    m.d.sync += done.eq(0)
                with m.Elif(~done & ~self.pause):
                    m.d.sync += [
                        base.eq(self.fbp.base ^ Mux(self.alternate, 0x40000, 0)),
                        offset.eq(0),
                        burst_count.eq(0),
                    ]
                    m.next = "BURST"

            with m.State("BURST"):
                m.d.comb += [
                    bus.stb.eq(1),
                    bus.cyc.eq(1),
                    bus.we.eq(1),
                    bus.sel.eq(2**(bus.data_width // 8) - 1),
                    bus.adr.eq(base + offset),
                    bus.dat_w.eq(0),
                    bus.cti.eq(wishbone.CycleType.INCR_BURST),
                ]
                with m.If(final_word | final_burst_word):
                    m.d.comb += bus.cti.eq(wishbone.CycleType.END_OF_BURST)
                with m.If(bus.ack):
                    with m.If(final_word):
                        m.d.sync += done.eq(1)
                        m.next = "DONE"
                    with m.Elif(final_burst_word):
                        m.d.sync += [
                            offset.eq(offset + 1),
                            burst_count.eq(0),
                        ]
                        m.next = "WAIT"
                    with m.Else():
                        m.d.sync += [
                            offset.eq(offset + 1),
                            burst_count.eq(burst_count + 1),
                        ]

            with m.State("WAIT"):
                with m.If(~self.start):
                    m.d.sync += done.eq(0)
                    m.next = "IDLE"
                with m.Elif(~self.pause):
                    m.next = "BURST"

            with m.State("DONE"):
                with m.If(~self.start):
                    m.d.sync += done.eq(0)
                    m.next = "IDLE"

        m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))

        return m


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

        super().__init__(
            finalize_csr_bridge=False,
            # Spectrogram is a timing-only pass-through in the DVI path. It
            # observes VSync for atomic surface swaps without paying for the
            # unused general-purpose grid overlay.
            fb_overlay=self.spectrogram,
            extra_plot_ports=1,
            with_persist=False,
            # WATERFALL combines every non-CPU PSRAM client below. This keeps
            # the timing-critical central arbiter to a CPU-versus-DMA choice.
            attach_framebuffer_masters=False,
            **kwargs,
        )
        self.waterfall_terrain_renderer = span.TriangleSpanRenderer(
            bus_signature=self.psram_periph.bus.signature.flip())
        self.backbuffer_clear = BackbufferClear(
            bus_signature=self.psram_periph.bus.signature.flip())
        # Present all non-CPU memory traffic as one client to the central PSRAM
        # arbiter. Scanout is added first, and the explicit ``scanout_urgent``
        # backpressure below keeps bulk clear/terrain writes from occupying the
        # local arbiter while its FIFO reserve is being refilled.
        psram_bus = self.psram_periph.bus
        self.waterfall_dma_arbiter = wishbone.Arbiter(
            addr_width=psram_bus.addr_width,
            data_width=psram_bus.data_width,
            granularity=psram_bus.granularity,
            features=psram_bus.features,
        )
        self.waterfall_dma_arbiter.add(self.fb.bus)
        self.waterfall_dma_arbiter.add(self.framebuffer_plotter.bus)
        self.waterfall_dma_arbiter.add(self.backbuffer_clear.bus)
        self.waterfall_dma_arbiter.add(
            self.waterfall_terrain_renderer.bus)
        self.psram_periph.add_master(self.waterfall_dma_arbiter.bus)

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
        m.submodules.waterfall_terrain_renderer = self.waterfall_terrain_renderer
        m.submodules.backbuffer_clear = self.backbuffer_clear
        m.submodules.waterfall_dma_arbiter = self.waterfall_dma_arbiter
        m.submodules += super().elaborate(platform)

        wiring.connect(
            m, self.spectrogram.line_o, self.waterfall_line_plotter.i)
        wiring.connect(
            m, self.spectrogram.triangle_o,
            self.waterfall_terrain_renderer.i)
        m.d.comb += self.spectrogram.line_busy.eq(
            self.waterfall_line_plotter.busy |
            self.waterfall_terrain_renderer.busy)
        m.d.comb += [
            self.waterfall_line_plotter.alternate.eq(1),
            self.waterfall_terrain_renderer.alternate.eq(1),
            self.waterfall_terrain_renderer.pause.eq(
                self.fb.scanout_urgent),
        ]
        wiring.connect(
            m, wiring.flipped(self.fb.fbp), self.backbuffer_clear.fbp)
        wiring.connect(
            m, wiring.flipped(self.fb.fbp),
            self.waterfall_terrain_renderer.fbp)
        # Video scanout is the only hard real-time PSRAM client. Backpressure
        # the exact line renderer whenever its FIFO reserve is being refilled;
        # this changes completion latency, not geometry, and prevents complex
        # spectra from starving the visible framebuffer DMA.
        waterfall_pixels = self.waterfall_line_plotter.o
        waterfall_plot = self.framebuffer_plotter.i[3]
        m.d.comb += [
            waterfall_plot.payload.eq(waterfall_pixels.payload),
            waterfall_plot.valid.eq(
                waterfall_pixels.valid & ~self.fb.scanout_urgent),
            waterfall_pixels.ready.eq(
                waterfall_plot.ready & ~self.fb.scanout_urgent),
            self.backbuffer_clear.alternate.eq(1),
            self.backbuffer_clear.pause.eq(self.fb.scanout_urgent),
        ]

        # A full-cache fence turns "last pixel accepted" into "all pixels are
        # committed to PSRAM" before firmware swaps the displayed base.
        flush_request_sync = Signal()
        clear_request_sync = Signal()
        m.submodules.flush_request_ff = FFSynchronizer(
            self.spectrogram.flush_request, flush_request_sync,
            o_domain="sync")
        m.submodules.clear_request_ff = FFSynchronizer(
            self.spectrogram.clear_request, clear_request_sync,
            o_domain="sync")
        m.d.comb += [
            self.framebuffer_plotter.flush.eq(flush_request_sync),
            self.spectrogram.flush_done.eq(
                self.framebuffer_plotter.flush_done),
            self.backbuffer_clear.start.eq(clear_request_sync),
            self.spectrogram.clear_done.eq(self.backbuffer_clear.done),
            self.spectrogram.clear_busy.eq(self.backbuffer_clear.busy),
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
        # Qualify this dense design with an explicit placement and fail loudly
        # if a source or toolchain change no longer meets every clock. The seed
        # identifies this build recipe; timing is still rechecked on each build.
        nextpnr_opts="--seed 3",
    )
