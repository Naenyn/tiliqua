# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""
SPECTO is a four-channel-selectable spectral waterfall for Eurorack signals.

A 512-point Hann-windowed FFT analyzes one selected input. New spectra appear
at the left edge and history extends to the right. Low frequencies are at the
bottom, high frequencies at the top, and brightness represents magnitude.
The 24kHz range uses a wide 48kHz analysis feed; lower ranges automatically
switch to a finer 24kHz feed for twice the frequency resolution.

All four analog inputs pass directly to their matching outputs:

    .. code-block:: text

        in1 ───────────────────────► out1
        in2 ───────────────────────► out2
        in3 ───────────────────────► out3
        in4 ───────────────────────► out4

SPECTRO options select the input, analytical or phosphor rendering, input
sensitivity, maximum displayed frequency, history speed, and (in phosphor
mode) persistence.

Analytical rendering emphasizes stable, crisp frequency bins. Phosphor
rendering adds temporal smoothing, brighter highlights, and an age-dependent
fade. Both styles use the same uninterrupted spectral history.

DISPLAY options toggle labeled frequency/history axes and select plot hue,
menu hue, and palette. Axis scales follow the selected range and rate. The
Inferno palette supports hue rotation while preserving its heatmap gradient;
grayscale palettes intentionally ignore hue.
MISC contains display rotation and settings save/reset actions.

The current 2D history representation is designed to support a future 3D
waterfall projection without changing the analyzer or capture path.
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


class SpectoSoc(TiliquaSoc):

    module_docstring = sys.modules[__name__].__doc__

    bitstream_help = BitstreamHelp(
        brief="Four-channel selectable spectral waterfall.",
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

        # Analog inputs pass straight through to their matching outputs. The
        # analyzer observes calibrated samples without backpressuring audio.
        wiring.connect(m, pmod0.o_cal, pmod0.i_cal)
        dsp.connect_peek(m, pmod0.o_cal, self.spectrogram.audio_i)

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(
        SpectoSoc,
        path=this_path,
        archiver_callback=lambda archiver: archiver.with_option_storage(),
    )
