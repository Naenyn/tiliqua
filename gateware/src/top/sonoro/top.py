# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""
SONORO is a spectrum analyzer and spectrograph for Eurorack signals, with a
selectable input and four-channel analog passthrough.

A 512-point Hann-windowed FFT analyzes one selected input. New spectra appear
at the left edge and history extends to the right. Low frequencies are at the
bottom, high frequencies at the top, and brightness represents magnitude.
The analysis rate follows the selected 24/12/6/3kHz display range, using
48/24/12/6kHz feeds respectively. This keeps the full selected bandwidth while
progressively improving FFT resolution from 93.75Hz/bin to 11.72Hz/bin.

All four analog inputs pass directly to their matching outputs:

    .. code-block:: text

        in1 ───────────────────────► out1
        in2 ───────────────────────► out2
        in3 ───────────────────────► out3
        in4 ───────────────────────► out4

SONORO options select a live spectrum analyzer or historical 2D spectrograph,
input, sensitivity, and maximum displayed frequency. Spectrum mode plots the
newest FFT with frequency on X and magnitude on Y. Spectrograph mode offers
analytical or phosphor rendering, history speed, and adjustable phosphor
persistence. The direct-click freeze control holds the last complete analysis
frame, including the spectrum, peak trace, and spectrograph history.

Analytical rendering emphasizes stable, crisp frequency bins. Phosphor
rendering adds temporal smoothing, brighter highlights, and an age-dependent
fade. Both styles use the same uninterrupted spectral history.

The main SONORO page also provides a display-only noise floor shared by all
views. It hides low-level display clutter without changing the analyzed signal.
DISPLAY options toggle labeled frequency/history axes; spectrum mode also
offers an independent plot-grid toggle, plus plot hue and palette. Axis scales
follow the selected range and rate. The Inferno palette supports hue rotation
while preserving its heatmap gradient; grayscale palettes intentionally ignore
hue. MISC contains display rotation and settings save/reset actions.
"""

import os
import sys

from amaranth import Module
from amaranth.lib import wiring

from tiliqua import dsp
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.periph import overlay
from tiliqua.tiliqua_soc import TiliquaSoc

from spectrogram import Spectrogram


class SonoroSoc(TiliquaSoc):

    module_docstring = sys.modules[__name__].__doc__

    bitstream_help = BitstreamHelp(
        brief="Four-channel spectrum analyzer and spectrograph.",
        io_left=['CH1 in', 'CH2 in', 'CH3 in', 'CH4 in',
                 'CH1 thru', 'CH2 thru', 'CH3 thru', 'CH4 thru'],
        io_right=['menu / adjust', '', 'video out', '', '', '']
    )

    def __init__(self, **kwargs):
        self.spectrogram = Spectrogram(
            fs=kwargs["clock_settings"].audio_clock.fs())
        self.overlay_periph = overlay.Peripheral(trace=self.spectrogram)

        super().__init__(
            finalize_csr_bridge=False,
            fb_overlay=self.overlay_periph.overlay,
            register_wb_response=True,
            **kwargs,
        )

        self.spectrogram_periph_base = 0x00001000
        self.overlay_periph_base = 0x00001100
        self.csr_decoder.add(
            self.spectrogram.bus,
            addr=self.spectrogram_periph_base,
            name="spectrogram_periph",
        )
        self.csr_decoder.add(
            self.overlay_periph.bus,
            addr=self.overlay_periph_base,
            name="overlay_periph",
        )
        self.finalize_csr_bridge()

    def elaborate(self, platform):
        m = Module()
        m.submodules.overlay_periph = self.overlay_periph
        m.submodules += super().elaborate(platform)

        pmod0 = self.pmod0_periph.pmod

        # All analog inputs pass straight through to their matching outputs.
        wiring.connect(m, pmod0.o_cal, pmod0.i_cal)
        dsp.connect_peek(m, pmod0.o_cal, self.spectrogram.audio_i)

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(
        SonoroSoc,
        path=this_path,
        archiver_callback=lambda archiver: archiver.with_option_storage(),
        # This deterministic placement has balanced passing margin across the
        # serializer, pixel, system and audio clocks. Unlike the repository
        # default, omit --timing-allow-fail so timing regressions fail the build.
        nextpnr_opts="--seed 2",
    )
