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

from tiliqua import midi
from tiliqua.build import sim
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.dsp import ASQ
from tiliqua.dsp.tuner import TunerPeripheral
from tiliqua.tiliqua_soc import TiliquaSoc

try:
    from .display import Peripheral as TunerDisplayPeripheral
    from .background import BackgroundLayout
    from .midi_input import Peripheral as MidiInputPeripheral
except ImportError:
    from display import Peripheral as TunerDisplayPeripheral
    from background import BackgroundLayout
    from midi_input import Peripheral as MidiInputPeripheral


def configure_archive(archiver):
    """TUNER-specific clock policy; do not change other bitstreams' defaults."""
    archiver.with_option_storage(size=24576)
    if archiver.external_pll_config is not None:
        archiver.external_pll_config.spread_spectrum = 0.0


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
        # TUNER deliberately uses the native 16-bit, 4-counts/mV sample
        # representation.  Its CV command protocol and production NSDF
        # detector are both signed 16-bit interfaces.  Reject an accidental
        # widened-ASQ build instead of silently halving DAC voltages or
        # truncating loud detector inputs.
        assert ASQ.width == 16 and ASQ.i_bits == 1, (
            "TUNER requires native 16-bit ASQ (unset TILIQUA_ASQ_WIDTH and "
            "TILIQUA_ASQ_I_BITS)")
        try:
            from .experiment.buffered_uart import Peripheral as BufferedUART
        except ImportError:
            from experiment.buffered_uart import Peripheral as BufferedUART
        self.UART_PERIPHERAL = BufferedUART
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
        # Pitch belongs exclusively to the NSDF peripheral. This block is now
        # only the level/CV/output transport used by all three modes.
        self.tuner_periph = TunerPeripheral(
            sample_rate=self.clock_settings.audio_clock.fs(),
            multichannel=True,
            with_reference=False)
        self.csr_decoder.add(
            self.tuner_periph.bus, addr=0x1000, name="tuner_periph")
        self.csr_decoder.add(
            self.tuner_display.bus, addr=0x1100, name="tuner_display")
        # This compact CPU has no mcycle CSR. Use a bus-readable cycle timer
        # for playback diagnostics, without another interrupt source.
        self.playback_timer = timer.Peripheral(width=32)
        self.csr_decoder.add(self.playback_timer.bus, addr=0x1200, name="playback_timer")
        try:
            from .experiment.nsdf_peripheral import Peripheral as NsdfPeripheral
        except ImportError:
            from experiment.nsdf_peripheral import Peripheral as NsdfPeripheral
        assert self.clock_settings.audio_clock.fs() == 192000
        self.nsdf_periph = NsdfPeripheral()
        self.csr_decoder.add(self.nsdf_periph.bus, addr=0x1300, name="nsdf_periph")
        self.midi_input = MidiInputPeripheral()
        self.csr_decoder.add(self.midi_input.bus, addr=0x1400, name="midi_input")
        self.finalize_csr_bridge()

    def elaborate(self, platform):
        m = Module()
        m.submodules.tuner_periph = self.tuner_periph
        m.submodules.tuner_display = self.tuner_display
        m.submodules.playback_timer = self.playback_timer
        m.submodules += super().elaborate(platform)

        pmod = self.pmod0_periph.pmod
        wiring.connect(m, pmod.o_cal, self.tuner_periph.i)
        m.submodules.nsdf_periph = self.nsdf_periph
        m.submodules.midi_input = self.midi_input
        if sim.is_hw(platform):
            midi_pins = platform.request("midi")
            m.submodules.midi_rx = midi_rx = midi.SerialRx(
                system_clk_hz=60e6, pins=midi_pins)
            m.submodules.midi_decode = midi_decode = midi.MidiDecodeSerial()
            wiring.connect(m, midi_rx.o, midi_decode.i)
            wiring.connect(m, midi_decode.o, self.midi_input.i_midi)
        m.d.comb += self.nsdf_periph.input_valid.eq(pmod.o_cal.valid & pmod.o_cal.ready)
        for channel in range(4):
            m.d.comb += getattr(self.nsdf_periph, f"sample{channel}").eq(pmod.o_cal.payload[channel].as_value())

        # No reference oscillator: idle outputs are always calibrated zero.
        # Keep DAC acceptance connected for calibration command acknowledgments.
        m.d.comb += pmod.i_cal.valid.eq(1)
        m.d.comb += [
            self.tuner_periph.reference_advance.eq(pmod.i_cal.ready),
        ]
        for channel in range(4):
            m.d.comb += pmod.i_cal.payload[channel].as_value().eq(Mux(
                self.tuner_periph.cal_fault & (self.tuner_periph.cal_channel == channel), 0,
                Mux(self.tuner_periph.cal_active & (self.tuner_periph.cal_channel == channel),
                self.tuner_periph.cal_value,
                self.tuner_periph.quant_value[channel])))

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    modeline = os.getenv("TILIQUA_TUNER_MODELINE", "1280x720p60")
    # Qualified placements for the shared-text renderer. The serializer has a
    # tighter routing constraint on the high-clock HDMI target.
    # Seed 15 became marginal after adding MIDI reception (the 5x DVI domain
    # missed timing in one placement). Seed 18 was routed and hardware-checked
    # on the non-circular R5 target with HDMI lock restored.
    default_seed = "13" if modeline == "720x720p60r2" else "18"
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
        archiver_callback=configure_archive,
        # A generated archive must not silently contain timing-failed logic.
        # TILIQUA_TUNER_SEED permits explicit, reproducible qualification runs.
        nextpnr_opts=f"--seed {seed}",
    )
