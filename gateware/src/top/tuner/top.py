# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Monophonic audio tuner proof of concept.

One selected audio input is measured in gateware. Firmware displays its
fundamental pitch, chromatic note/cents offset, octave, Vrms and Vpp. Outputs
remain silent in this first proof of concept.
"""

import os
import sys

from amaranth import Module, Mux
from amaranth.lib import wiring

from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.dsp.tuner import TunerPeripheral
from tiliqua.tiliqua_soc import TiliquaSoc

try:
    from .display import Peripheral as TunerDisplayPeripheral
except ImportError:
    from display import Peripheral as TunerDisplayPeripheral


class TunerSoc(TiliquaSoc):
    module_docstring = sys.modules[__name__].__doc__
    bitstream_help = BitstreamHelp(
        brief="Monophonic tuner proof of concept.",
        io_left=["audio input 1", "audio input 2", "audio input 3",
                 "audio input 4", "reference sine", "silent", "silent", "silent"],
        io_right=["navigate / select", "", "video out", "", "", ""],
    )

    def __init__(self, **kwargs):
        self.tuner_display = TunerDisplayPeripheral()
        super().__init__(finalize_csr_bridge=False, mainram_size=0x2000,
                         fb_overlay=self.tuner_display.overlay,
                         pipeline_palette_output=True,
                         with_persistence=False,
                         with_raster_engines=False,
                         **kwargs)
        self.tuner_periph = TunerPeripheral(
            sample_rate=self.clock_settings.audio_clock.fs(),
            # A 50ms observation window limited new pitch estimates to 20Hz.
            # 20ms still gives sub-cent resolution at the normal 192kHz audio
            # rate while responding much more promptly to oscillator changes.
            min_pitch_window_s=0.02)
        self.csr_decoder.add(
            self.tuner_periph.bus, addr=0x1000, name="tuner_periph")
        self.csr_decoder.add(
            self.tuner_display.bus, addr=0x1100, name="tuner_display")
        self.finalize_csr_bridge()

    def elaborate(self, platform):
        m = Module()
        m.submodules.tuner_periph = self.tuner_periph
        m.submodules.tuner_display = self.tuner_display
        m.submodules += super().elaborate(platform)

        pmod = self.pmod0_periph.pmod
        wiring.connect(m, pmod.o_cal, self.tuner_periph.i)

        # Output 1 optionally carries the calibrated 1 Vpp reference sine.
        # The remaining outputs stay at calibrated zero. Advancing the NCO only
        # when the DAC stream accepts a sample preserves its exact frequency
        # through any FIFO backpressure.
        m.d.comb += pmod.i_cal.valid.eq(1)
        m.d.comb += [
            self.tuner_periph.reference_advance.eq(pmod.i_cal.ready),
            pmod.i_cal.payload[0].as_value().eq(Mux(
                self.tuner_periph.reference_enabled,
                self.tuner_periph.reference.as_value(), 0)),
        ]
        for channel in range(1, 4):
            m.d.comb += pmod.i_cal.payload[channel].as_value().eq(0)

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    seed = int(os.getenv("TILIQUA_TUNER_SEED", "1"))
    modeline = os.getenv("TILIQUA_TUNER_MODELINE", "1280x720p60")
    name = os.getenv("TILIQUA_TUNER_NAME", "TUNER")
    top_level_cli(
        TunerSoc,
        path=this_path,
        # Display orientation is a build-time layout decision, just as it is
        # for the REZO family.  The normal target is always the unrotated HDMI
        # preview; tuner_round.py explicitly selects the physically rotated
        # production panel.  Do not infer this from mutable bootloader state.
        argparse_callback=lambda parser: parser.set_defaults(
            modeline=modeline, name=name),
        archiver_callback=lambda archiver: archiver.with_option_storage(),
        # Keep release builds reproducible with a timing-clean placement for
        # the fixed 1280x720 renderer on ECP5-25F R5.
        nextpnr_opts=f"--timing-allow-fail --seed {seed}",
    )
