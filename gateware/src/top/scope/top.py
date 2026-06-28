# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

"""
Four-channel digital oscilloscope with crisp vector traces.

All four analog inputs are plotted simultaneously with adjustable timebase,
trigger, and per-channel vertical position.  Audio is passed straight through
to the outputs (no USB or delay lines).

The following options are tweakable in the menu.  TRS MIDI CCs mirror the
scope and display pages:

    .. code-block:: text

        Page    Parameter     CC  Description
        ────    ─────────     ──  ───────────
        HELP    scroll         -  scroll help text up/down

        DISPLAY ui-hue        42  menu and grid overlay hue
        DISPLAY palette       43  color palette
        DISPLAY grid          44  grid overlay style
        DISPLAY grid-i        45  grid overlay intensity

        MISC    rotation      52  screen rotation
        MISC    help           -  show/hide help page
        MISC    save-opts      -  save all options to flash
        MISC    wipe-opts      -  reset all options to defaults

        SCOPE1  ypos0         60  channel 0 vertical position
        SCOPE1  ypos1         61  channel 1 vertical position
        SCOPE1  ypos2         62  channel 2 vertical position
        SCOPE1  ypos3         63  channel 3 vertical position
        SCOPE1  yscale0       70  channel 0 volts/div (CC mirror)
        SCOPE1  vis0-3         -  per-channel visibility

        SCOPE2  timebase      71  horizontal time/div
        SCOPE2  trig-mode     73  trigger mode
        SCOPE2  trig-lvl      74  trigger level
        SCOPE2  intensity     75  trace intensity
        SCOPE2  hue           76  trace color
"""

import os
import sys

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.fifo import SyncFIFOBuffered
from amaranth.lib.wiring import In, Out, connect, flipped
from amaranth_soc import csr

from tiliqua import dsp, midi
from tiliqua.build import sim
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.periph import overlay
from tiliqua.periph import ui_overlay
from tiliqua.raster import PSQ
from tiliqua.raster.digital_scope import DigitalScopePeripheral
from tiliqua.raster.plot import FramebufferPlotter
from tiliqua.tiliqua_soc import TiliquaSoc


class ScopeCtrlPeripheral(wiring.Component):

    class MidiRead(csr.Register, access="r"):
        msg: csr.Field(csr.action.R, unsigned(32))

    def __init__(self):
        regs = csr.Builder(addr_width=5, data_width=8)
        self._midi_read = regs.add("midi_read", self.MidiRead(), offset=0x0)
        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__({
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "i_midi": In(stream.Signature(midi.MidiMessage)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()

        m.submodules.bridge = self._bridge
        connect(m, flipped(self.bus), self._bridge.bus)

        m.submodules.read_midi_fifo = read_midi_fifo = SyncFIFOBuffered(
            width=24, depth=8)
        m.d.comb += [
            self.i_midi.ready.eq(1),
            read_midi_fifo.w_data.eq(self.i_midi.payload),
            read_midi_fifo.w_en.eq(self.i_midi.valid),
            read_midi_fifo.r_en.eq(self._midi_read.element.r_stb),
        ]
        with m.If(read_midi_fifo.r_level != 0):
            m.d.comb += self._midi_read.f.msg.r_data.eq(read_midi_fifo.r_data)
        with m.Else():
            m.d.comb += self._midi_read.f.msg.r_data.eq(0)

        return m


class ScopeSoc(TiliquaSoc):

    module_docstring = sys.modules[__name__].__doc__

    bitstream_help = BitstreamHelp(
        brief="4-channel digital oscilloscope.",
        io_left=['ch0+trig', 'ch1', 'ch2', 'ch3', 'out0', 'out1', 'out2', 'out3'],
        io_right=['navigate menu', '', 'video out', '', '', '']
    )

    def __init__(self, **kwargs):

        self.overlay_periph = overlay.Peripheral(enable_ui=True)
        self.overlay_ui_mem_base = 0xc1000000

        super().__init__(finalize_csr_bridge=False,
                         fb_overlay=self.overlay_periph.overlay,
                         enable_persist=False,
                         **kwargs)

        # Firmware bitmap scratch in PSRAM (blockram is only 16 KiB).
        self.overlay_ui_scratch_base = self.psram_base + 0x00F0_0000

        self.scope_periph_base  = 0x00001100
        self.scope_ctrl_base    = 0x00001200
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

        self.plotter = FramebufferPlotter(
            bus_signature=self.psram_periph.bus.signature.flip(), n_ports=5)
        self.psram_periph.add_master(self.plotter.bus)

        self.n_upsample = 8 if self.clock_settings.audio_clock.is_192khz() else 32

        self.scope_periph = DigitalScopePeripheral(
            fs=self.clock_settings.audio_clock.fs() * self.n_upsample)
        self.csr_decoder.add(self.scope_periph.bus, addr=self.scope_periph_base, name="scope_periph")

        self.scope_ctrl = ScopeCtrlPeripheral()
        self.csr_decoder.add(self.scope_ctrl.bus, addr=self.scope_ctrl_base, name="scope_ctrl_periph")

        self.csr_decoder.add(self.overlay_periph.bus, addr=self.overlay_periph_base, name="overlay_periph")

        self.finalize_csr_bridge()

    def elaborate(self, platform):

        m = Module()

        m.submodules.plotter = self.plotter
        m.submodules.scope_periph = self.scope_periph
        m.submodules.scope_ctrl = self.scope_ctrl
        m.submodules.overlay_periph = self.overlay_periph

        for n in range(4):
            wiring.connect(m, self.scope_periph.o[n], self.plotter.i[n])
        wiring.connect(m, self.scope_periph.clear_o, self.plotter.i[4])

        m.d.comb += self.scope_periph.dbg_plotter.eq(self.plotter.dbg)

        wiring.connect(m, wiring.flipped(self.fb.fbp), self.plotter.fbp)
        wiring.connect(m, wiring.flipped(self.fb.fbp), self.scope_periph.fbp)

        m.submodules += super().elaborate(platform)

        pmod0 = self.pmod0_periph.pmod

        wiring.connect(m, pmod0.o_cal, pmod0.i_cal)

        if sim.is_hw(platform):
            midi_pins = platform.request("midi")
            m.submodules.serialrx = serialrx = midi.SerialRx(
                    system_clk_hz=60e6, pins=midi_pins)
            m.submodules.midi_decode = midi_decode = midi.MidiDecodeSerial()
            wiring.connect(m, serialrx.o, midi_decode.i)
            wiring.connect(m, midi_decode.o, self.scope_ctrl.i_midi)

        m.submodules.plot_fifo = plot_fifo = dsp.SyncFIFOBuffered(
            shape=data.ArrayLayout(PSQ, 4), depth=256)

        dsp.connect_peek(m, pmod0.o_cal, plot_fifo.i)

        fs = self.clock_settings.audio_clock.fs()
        m.submodules.up_split4 = up_split4 = dsp.Split(n_channels=4, source=plot_fifo.o, shape=PSQ)
        m.submodules.up_merge4 = up_merge4 = dsp.Merge(n_channels=4, shape=PSQ)
        for ch in range(4):
            # SCOPE needs a shape-preserving interpolator: the band-limited FIR
            # resampler rings around discontinuities and draws overshoot spikes
            # on saw/square edges. Linear interpolation stays within the two
            # source samples while remaining dense enough for smooth plotting.
            r = dsp.LinearResample(n_up=self.n_upsample, shape=PSQ)
            setattr(m.submodules, f"resample{ch}", r)
            wiring.connect(m, up_split4.o[ch], r.i)
            wiring.connect(m, r.o, up_merge4.i[ch])

        wiring.connect(m, up_merge4.o, self.scope_periph.i)

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(ScopeSoc, path=this_path, archiver_callback=lambda archiver: archiver.with_option_storage())
