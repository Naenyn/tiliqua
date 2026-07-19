# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""
REZO is a first pass at a Graphic Resonant Filterbank-inspired Tiliqua
bitstream.

    .. code-block:: text

        ┌────┐
        │in0 │◄─ audio in
        │in1 │◄─ resonance CV
        │in2 │◄─ morph/tilt CV (reserved)
        │in3 │◄─ feedback CV
        └────┘
        ┌────┐
        │out0│─► main mix
        │out1│─► odd bands
        │out2│─► even bands
        │out3│─► dry input
        └────┘

This initial version keeps the sample-by-sample DSP in gateware and uses the
softcore only for the HDMI menu / preset-facing controls.  The filterbank is
mono for now: ten fixed center-frequency band-pass filters are mixed with
runtime-adjustable band gains, dry level, global resonance and feedback amount.

The deliberately conservative goal is to get a useful musical prototype onto
hardware quickly.  Stereo, per-band frequency/Q editing, pattern morphing and
spectral compression are natural follow-up experiments once the mono core has
some listening time on real hardware.
"""

import math
import os
import sys

from amaranth import *
from amaranth.lib import data, stream, wiring
from amaranth.lib.wiring import In, Out, connect, flipped
from amaranth_soc import csr

from amaranth_future import fixed

from tiliqua import dsp
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.dsp import ASQ
from tiliqua.raster import PSQ, scope
from tiliqua.raster.plot import FramebufferPlotter
from tiliqua.tiliqua_soc import TiliquaSoc


class RezoCore(wiring.Component):
    """Ten-band mono resonant filterbank."""

    N_BANDS = 10

    # Erica-inspired nominal centers.  SVF cutoff is approximate because the
    # existing DSP block expects the Chamberlin integration coefficient rather
    # than a frequency in hertz.
    FREQS_HZ = [29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000]

    i: In(stream.Signature(data.ArrayLayout(ASQ, 4)))
    o: Out(stream.Signature(data.ArrayLayout(ASQ, 4)))

    def __init__(self, fs=48_000):
        self.fs = fs
        self.levels = [Signal(signed(16), init=8192) for _ in range(self.N_BANDS)]
        self.dry = Signal(unsigned(16), init=4096)
        self.resonance = Signal(unsigned(16), init=8192)
        self.feedback = Signal(signed(16), init=0)
        super().__init__()

    @staticmethod
    def cutoff_coeff(freq_hz, fs):
        # Chamberlin SVF coefficient, kept below 1.0 for fixed-point headroom.
        return min(0.98, 2.0 * math.sin(math.pi * freq_hz / (2.0 * fs)))

    def elaborate(self, platform):
        m = Module()

        # Shared values.  Convert the 0..65535 UI values into ASQ-ish fractions.
        dry_gain = Signal(ASQ)
        resonance = Signal(ASQ)
        fb_gain = Signal(ASQ)
        fb_sample = Signal(ASQ)
        x = Signal(ASQ)

        m.submodules.mac_server = mac_server = dsp.mac.RingMACServer(
            max_clients=16)

        m.d.comb += [
            dry_gain.eq(self.dry >> (16 - ASQ.f_bits)),
            # The SVF uses inverse-Q.  Lower values are more resonant; keep a
            # floor so the first build does not scream into instability.
            resonance.eq((ASQ.max() >> 4) + (self.resonance >> (16 - ASQ.f_bits + 1))),
            fb_gain.eq(self.feedback.as_signed() >> (16 - ASQ.f_bits)),
        ]

        # Light feedback injection.  This is intentionally modest: enough to
        # make the bank sing, not enough to make first power-up rude.
        fb_term = Signal(dsp.mac.SQRNative)
        m.d.comb += fb_term.eq(fb_sample * fb_gain)
        m.d.comb += x.eq(self.i.payload[0] + (fb_term.saturate(ASQ) >> 2))

        band_bp = []
        for n, freq in enumerate(self.FREQS_HZ):
            svf = dsp.SVF(macp=mac_server.new_client())
            setattr(m.submodules, f"svf{n}", svf)
            band_bp.append(svf.o.payload.bp)
            m.d.comb += [
                svf.i.valid.eq(self.i.valid),
                svf.i.payload.x.eq(x),
                svf.i.payload.cutoff.eq(fixed.Const(self.cutoff_coeff(freq, self.fs), ASQ)),
                svf.i.payload.resonance.eq(resonance),
            ]

        # The source is accepted only when every band can accept a sample.
        m.d.comb += self.i.ready.eq(Cat([svf.i.ready for svf in [getattr(m.submodules, f"svf{n}") for n in range(self.N_BANDS)]]).all())

        mix_shape = signed(ASQ.as_shape().width + 5)
        main_acc = Signal(mix_shape)
        odd_acc = Signal(mix_shape)
        even_acc = Signal(mix_shape)
        dry_acc = Signal(mix_shape)

        main_terms = []
        odd_terms = []
        even_terms = []
        for n in range(self.N_BANDS):
            term = Signal(mix_shape, name=f"term{n}")
            m.d.comb += term.eq(
                Mux(self.levels[n] > 512,
                    band_bp[n].as_value().as_signed() >> 4,
                    Mux(self.levels[n] < -512,
                        -(band_bp[n].as_value().as_signed() >> 4),
                        0)))
            main_terms.append(term)
            if n % 2:
                odd_terms.append(term)
            else:
                even_terms.append(term)

        m.d.comb += [
            dry_acc.eq(Mux(self.dry > 512, self.i.payload[0].as_value().as_signed() >> 2, 0)),
            main_acc.eq(sum(main_terms) + dry_acc),
            odd_acc.eq(sum(odd_terms)),
            even_acc.eq(sum(even_terms)),
        ]

        all_valid = Signal()
        m.d.comb += all_valid.eq(Cat([getattr(m.submodules, f"svf{n}").o.valid for n in range(self.N_BANDS)]).all())
        for n in range(self.N_BANDS):
            m.d.comb += getattr(m.submodules, f"svf{n}").o.ready.eq(self.o.ready & all_valid)

        m.d.comb += [
            self.o.valid.eq(all_valid),
            self.o.payload[0].eq(main_acc),
            self.o.payload[1].eq(odd_acc),
            self.o.payload[2].eq(even_acc),
            self.o.payload[3].eq(dry_acc),
        ]
        with m.If(self.o.valid & self.o.ready):
            m.d.sync += fb_sample.eq(self.o.payload[0])

        return m


class RezoPeripheral(wiring.Component):
    class Level(csr.Register, access="w"):
        value: csr.Field(csr.action.W, signed(16))

    class UnsignedValue(csr.Register, access="w"):
        value: csr.Field(csr.action.W, unsigned(16))

    class SignedValue(csr.Register, access="w"):
        value: csr.Field(csr.action.W, signed(16))

    def __init__(self):
        regs = csr.Builder(addr_width=7, data_width=8)
        self._levels = [
            regs.add(f"level{n}", self.Level(), offset=0x00 + 4*n)
            for n in range(RezoCore.N_BANDS)
        ]
        self._dry = regs.add("dry", self.UnsignedValue(), offset=0x30)
        self._resonance = regs.add("resonance", self.UnsignedValue(), offset=0x34)
        self._feedback = regs.add("feedback", self.SignedValue(), offset=0x38)
        self.core = None
        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        connect(m, flipped(self.bus), self._bridge.bus)

        for n, reg in enumerate(self._levels):
            with m.If(reg.f.value.w_stb):
                m.d.sync += self.core.levels[n].eq(reg.f.value.w_data)
        with m.If(self._dry.f.value.w_stb):
            m.d.sync += self.core.dry.eq(self._dry.f.value.w_data)
        with m.If(self._resonance.f.value.w_stb):
            m.d.sync += self.core.resonance.eq(self._resonance.f.value.w_data)
        with m.If(self._feedback.f.value.w_stb):
            m.d.sync += self.core.feedback.eq(self._feedback.f.value.w_data)

        return m


class RezoSoc(TiliquaSoc):
    module_docstring = sys.modules[__name__].__doc__

    bitstream_help = BitstreamHelp(
        brief="REZO mono resonant filterbank.",
        io_left=['audio in', 'resonance CV', 'morph CV', 'feedback CV',
                 'main out', 'odd bands', 'even bands', 'dry out'],
        io_right=['navigate menu', '', 'video out required', '', '', '']
    )

    def __init__(self, **kwargs):
        super().__init__(finalize_csr_bridge=False, **kwargs)

        self.vector_periph_base = 0x00001000
        self.scope_periph_base = 0x00001100
        self.rezo_periph_base = 0x00001200

        self.plotter = FramebufferPlotter(
            bus_signature=self.psram_periph.bus.signature.flip(), n_ports=5)
        self.psram_periph.add_master(self.plotter.bus)

        self.n_upsample = 16 if self.clock_settings.audio_clock.is_192khz() else 32

        self.vector_periph = scope.VectorPeripheral()
        self.csr_decoder.add(self.vector_periph.bus, addr=self.vector_periph_base, name="vector_periph")

        self.scope_periph = scope.ScopePeripheral(
            fs=self.clock_settings.audio_clock.fs() * self.n_upsample)
        self.csr_decoder.add(self.scope_periph.bus, addr=self.scope_periph_base, name="scope_periph")

        self.rezo_periph = RezoPeripheral()
        self.csr_decoder.add(self.rezo_periph.bus, addr=self.rezo_periph_base, name="rezo_periph")

        self.add_rust_constant(f"pub const N_BANDS: usize = {RezoCore.N_BANDS};\n")

        self.finalize_csr_bridge()

    def elaborate(self, platform):
        m = Module()

        m.submodules.plotter = self.plotter
        m.submodules.vector_periph = self.vector_periph
        m.submodules.scope_periph = self.scope_periph
        wiring.connect(m, self.vector_periph.o, self.plotter.i[0])
        for n in range(4):
            wiring.connect(m, self.scope_periph.o[n], self.plotter.i[n+1])
        wiring.connect(m, wiring.flipped(self.fb.fbp), self.plotter.fbp)

        m.submodules.rezo = rezo = RezoCore(fs=self.clock_settings.audio_clock.fs())
        self.rezo_periph.core = rezo
        m.submodules.rezo_periph = self.rezo_periph

        m.submodules += super().elaborate(platform)

        pmod0 = self.pmod0_periph.pmod
        wiring.connect(m, pmod0.o_cal, rezo.i)
        m.submodules.audio_out_fifo = audio_out_fifo = dsp.SyncFIFOBuffered(
            shape=data.ArrayLayout(ASQ, 4), depth=4)
        wiring.connect(m, rezo.o, audio_out_fifo.i)
        wiring.connect(m, audio_out_fifo.o, pmod0.i_cal)

        m.submodules.plot_fifo = plot_fifo = dsp.SyncFIFOBuffered(
            shape=data.ArrayLayout(PSQ, 4), depth=64)
        dsp.connect_peek(m, audio_out_fifo.o, plot_fifo.i)

        fs = self.clock_settings.audio_clock.fs()
        m.submodules.up_split4 = up_split4 = dsp.Split(n_channels=4, source=plot_fifo.o, shape=PSQ)
        m.submodules.up_merge4 = up_merge4 = dsp.Merge(n_channels=4, shape=PSQ)
        for ch in range(4):
            r = dsp.Resample(fs_in=fs, n_up=self.n_upsample, m_down=1, shape=PSQ)
            setattr(m.submodules, f"resample{ch}", r)
            wiring.connect(m, up_split4.o[ch], r.i)
            wiring.connect(m, r.o, up_merge4.i[ch])

        with m.If(self.scope_periph.soc_en):
            wiring.connect(m, up_merge4.o, self.scope_periph.i)
        with m.Else():
            wiring.connect(m, up_merge4.o, self.vector_periph.i)

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(RezoSoc, path=this_path, archiver_callback=lambda archiver: archiver.with_option_storage())
