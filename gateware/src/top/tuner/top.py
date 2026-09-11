# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""Four-channel audio tuner proof of concept.

Four monophonic inputs are measured continuously in gateware. Firmware displays
pitch, chromatic note/cents offset, octave, Vrms and Vpp. Outputs remain at
calibrated zero unless an explicitly started calibration sweep owns one.
"""

import os
import sys

from amaranth import Module, Mux
from amaranth.lib import wiring
from luna_soc.gateware.core import timer

from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.dsp.tuner import TunerPeripheral
from tiliqua.tiliqua_soc import TiliquaSoc

try:
    from .display import Peripheral as TunerDisplayPeripheral
    from .background import BackgroundLayout
except ImportError:
    from display import Peripheral as TunerDisplayPeripheral
    from background import BackgroundLayout


class TunerSoc(TiliquaSoc):
    # Keep enough CPU RAM for the retained options/UI state plus nested calls
    # and interrupt frames. See the constructor comment below.
    MAINRAM_SIZE = 0x8000

    module_docstring = sys.modules[__name__].__doc__
    bitstream_help = BitstreamHelp(
        brief="Monophonic tuner proof of concept.",
        io_left=["audio input 0", "audio input 1", "audio input 2",
                 "audio input 3", "calibration CV", "calibration CV", "calibration CV", "calibration CV"],
        io_right=["navigate / select", "", "video out", "", "", ""],
    )

    def __init__(self, **kwargs):
        modeline = kwargs["clock_settings"].modeline
        assert modeline is not None, "tuner display targets require a fixed modeline"
        round_display = modeline.h_active == 720 and modeline.v_active == 720
        self.tuner_display = TunerDisplayPeripheral(
            h_active=modeline.h_active,
            rotate_left=round_display,
            scene_layout=BackgroundLayout(modeline.h_active, modeline.v_active))
        # Retained playback profile plus foreground, storage and interrupt
        # frames need more than the old 16-KiB safety budget. 32 KiB leaves
        # explicit headroom without using external RAM in the playback ISR.
        super().__init__(finalize_csr_bridge=False,
                         mainram_size=self.MAINRAM_SIZE,
                         fb_overlay=self.tuner_display.overlay,
                         pipeline_palette_output=True,
                         with_persistence=False,
                         with_raster_engines=False,
                         isolate_cpu_peripherals=True,
                         **kwargs)
        # Enable the opt-in transaction-safe DMA only for this instrument.
        # Ordinary frame commits preserve the background; a future scene writer
        # must initialize/flush the inactive PSRAM buffer before requesting swap.
        assert self.fw_base - self.psram_base >= 0x200000
        self.fb.frame_exchange = self.tuner_display.exchange
        self.fb.serializer_circular_shift = True
        self.tuner_periph = TunerPeripheral(
            sample_rate=self.clock_settings.audio_clock.fs(),
            multichannel=True,
            with_reference=False,
            # A 50ms observation window limited new pitch estimates to 20Hz.
            # 20ms still gives sub-cent resolution at the normal 192kHz audio
            # rate while responding much more promptly to oscillator changes.
            min_pitch_window_s=0.02)
        self.csr_decoder.add(
            self.tuner_periph.bus, addr=0x1000, name="tuner_periph")
        self.csr_decoder.add(
            self.tuner_display.bus, addr=0x1100, name="tuner_display")
        # This compact CPU has no mcycle CSR. Use a bus-readable cycle timer
        # for playback diagnostics, without another interrupt source.
        self.playback_timer = timer.Peripheral(width=32)
        self.csr_decoder.add(self.playback_timer.bus, addr=0x1200, name="playback_timer")
        self.finalize_csr_bridge()

    def elaborate(self, platform):
        m = Module()
        m.submodules.tuner_periph = self.tuner_periph
        m.submodules.tuner_display = self.tuner_display
        m.submodules.playback_timer = self.playback_timer
        m.submodules += super().elaborate(platform)

        pmod = self.pmod0_periph.pmod
        wiring.connect(m, pmod.o_cal, self.tuner_periph.i)

        # No reference oscillator: idle outputs are always calibrated zero.
        # Keep DAC acceptance connected for calibration command acknowledgments.
        m.d.comb += pmod.i_cal.valid.eq(1)
        m.d.comb += [
            self.tuner_periph.reference_advance.eq(pmod.i_cal.ready),
        ]
        for channel in range(4):
            m.d.comb += pmod.i_cal.payload[channel].as_value().eq(Mux(
                self.tuner_periph.cal_fault, 0, Mux(self.tuner_periph.cal_active,
                Mux(self.tuner_periph.cal_channel == channel, self.tuner_periph.cal_value, 0),
                0)))

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    modeline = os.getenv("TILIQUA_TUNER_MODELINE", "1280x720p60")
    # Qualified placements for the shared-text renderer. The serializer has a
    # tighter routing constraint on the high-clock HDMI target.
    default_seed = "13" if modeline == "720x720p60r2" else "15"
    seed = int(os.getenv("TILIQUA_TUNER_SEED", default_seed))
    name = os.getenv("TILIQUA_TUNER_NAME", "TUNER")
    top_level_cli(
        TunerSoc,
        path=this_path,
        # Display orientation is a build-time layout decision, just as it is
        # for the REZO family.  The normal target is always the unrotated HDMI
        # preview; tuner_round.py explicitly selects the physically rotated
        # production panel.  Do not infer this from mutable bootloader state.
        argparse_callback=lambda parser: parser.set_defaults(
            modeline=modeline, name=name, fs_192khz=True),
        archiver_callback=lambda archiver: archiver.with_option_storage(size=24576),
        # A generated archive must not silently contain timing-failed logic.
        # TILIQUA_TUNER_SEED permits explicit, reproducible qualification runs.
        nextpnr_opts=f"--seed {seed}",
    )
