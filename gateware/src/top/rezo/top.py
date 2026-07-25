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
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out, connect, flipped
from amaranth_soc import csr

from amaranth_future import fixed

from tiliqua import dsp
from tiliqua.build import sim
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.dsp import ASQ
from tiliqua.periph import encoder, eurorack_pmod
from tiliqua.platform import RebootProvider
from tiliqua.tiliqua_soc import TiliquaSoc
from tiliqua.video import dvi


class RezoCore(wiring.Component):
    """Ten-band mono resonant filterbank."""

    N_BANDS = 10
    PARAM_SLEW_STEP = 64

    # Erica-inspired nominal centers.  SVF cutoff is approximate because the
    # existing DSP block expects the Chamberlin integration coefficient rather
    # than a frequency in hertz.
    FREQS_HZ = [29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000]

    i: In(stream.Signature(data.ArrayLayout(ASQ, 4)))
    o: Out(stream.Signature(data.ArrayLayout(ASQ, 4)))

    def __init__(self, fs=48_000):
        self.fs = fs
        self.levels = [Signal(signed(16), init=0) for _ in range(self.N_BANDS)]
        self.dry = Signal(unsigned(16), init=0)
        self.resonance = Signal(unsigned(16), init=8192)
        self.feedback = Signal(unsigned(16), init=0)
        self.limit_knee = Signal(unsigned(16), init=12288)
        self.limit_cap = Signal(unsigned(16), init=24576)
        self.damp_mode = Signal(unsigned(3), init=2)
        self.input_gains = [Signal(unsigned(16), init=32768 if n == 0 else 0)
                            for n in range(4)]
        super().__init__()

    @staticmethod
    def cutoff_coeff(freq_hz, fs):
        # Chamberlin SVF coefficient, kept below 1.0 for fixed-point headroom.
        return min(0.98, 2.0 * math.sin(math.pi * freq_hz / (2.0 * fs)))

    def elaborate(self, platform):
        m = Module()

        # Smooth UI/CV target parameters before the DSP consumes them.  The UI
        # can jump a target by a whole encoder detent; the filterbank should
        # hear a short ramp instead of a coefficient/gain discontinuity.
        smooth_levels = [Signal(signed(16), init=0, name=f"smooth_level{n}")
                         for n in range(self.N_BANDS)]
        smooth_dry = Signal(unsigned(16), init=0)
        smooth_resonance = Signal(unsigned(16), init=8192)
        smooth_feedback = Signal(unsigned(16), init=0)
        smooth_input_gains = [Signal(unsigned(16), init=32768 if n == 0 else 0,
                                     name=f"smooth_input_gain{n}")
                              for n in range(4)]
        level_diffs = [Signal(signed(17), name=f"level_diff{n}")
                       for n in range(self.N_BANDS)]
        dry_diff = Signal(signed(17))
        resonance_diff = Signal(signed(17))
        feedback_diff = Signal(signed(17))
        input_gain_diffs = [Signal(signed(17), name=f"input_gain_diff{n}")
                            for n in range(4)]
        feedback_gain = Signal(unsigned(16))
        m.d.comb += [
            dry_diff.eq(self.dry - smooth_dry),
            resonance_diff.eq(self.resonance - smooth_resonance),
            feedback_diff.eq(self.feedback - smooth_feedback),
            feedback_gain.eq(Mux(smooth_feedback > 31744, 31744, smooth_feedback)),
        ]
        for n in range(self.N_BANDS):
            m.d.comb += level_diffs[n].eq(self.levels[n] - smooth_levels[n])
        for n in range(4):
            m.d.comb += input_gain_diffs[n].eq(self.input_gains[n] - smooth_input_gains[n])

        feedback_sample = Signal(ASQ)

        # Shared values.  Convert the UI values into ASQ-ish fractions.  The
        # SVF uses inverse-Q: lower values are more resonant.  Keep the safer
        # inverse-Q floor from the stable hardware tests, then raise it when
        # feedback is high. This prevents max-Q and max-feedback from combining
        # into a self-sustaining noisy latch-up state.
        resonance_ctl = Signal(ASQ)
        res_ctl = Signal(signed(17))
        feedback_damp = Signal(unsigned(16))
        resonance_floor_raw = Signal(signed(17))
        resonance_floor = Signal(signed(17))
        with m.Switch(self.damp_mode):
            with m.Case(0):
                m.d.comb += feedback_damp.eq(0)
            with m.Case(1):
                m.d.comb += feedback_damp.eq(smooth_feedback >> 4)
            with m.Case(2):
                m.d.comb += feedback_damp.eq(smooth_feedback >> 3)
            with m.Case(3):
                m.d.comb += feedback_damp.eq(smooth_feedback >> 2)
            with m.Default():
                m.d.comb += feedback_damp.eq((smooth_feedback >> 2) + (smooth_feedback >> 3))
        m.d.comb += [
            res_ctl.eq(16384 - (smooth_resonance >> 1)),
            resonance_floor_raw.eq(4096 + feedback_damp),
            resonance_floor.eq(Mux(resonance_floor_raw > 12288, 12288, resonance_floor_raw)),
            resonance_ctl.eq(Mux(res_ctl < resonance_floor, resonance_floor, res_ctl)),
        ]

        # Feedback is smoothed and scheduled through the shared multiplier.
        # Full-scale UI feedback is capped just below the hardware-tested cliff
        # so the final encoder tick stays in the "hot but not runaway" region.
        x = Signal(dsp.mac.SQNative)
        x_drive = Signal(dsp.mac.SQNative)
        x_limited = Signal(dsp.mac.SQNative)
        resonance = Signal(dsp.mac.SQNative)
        dry_sample = Signal(ASQ)

        cutoffs = Array([
            fixed.Const(self.cutoff_coeff(freq, self.fs), dsp.mac.SQNative).as_value()
            for freq in self.FREQS_HZ
        ])
        levels = Array(smooth_levels)

        state_shape = unsigned(4)
        state_wait = 0
        state_feedback_commit = 1
        state_dry_gain_commit = 2
        state_mac0_setup = 3
        state_mac0_commit = 4
        state_mac1_setup = 5
        state_mac1_commit = 6
        state_mac2_setup = 7
        state_mac2_commit = 8
        state_mix_setup = 9
        state_mix_gain_commit = 10
        state_mix_commit = 11
        state_input_gain_commit = 12
        state = Signal(state_shape, init=state_wait)
        band = Signal(range(self.N_BANDS))
        input_chan = Signal(range(4))
        oversample = Signal()

        svf_shape = fixed.SQ(dsp.mac.SQNative.i_bits, dsp.mac.SQNative.f_bits + 2)
        svf_storage = svf_shape.as_shape()
        alp = Array([Signal(svf_storage, name=f"alp{n}") for n in range(self.N_BANDS)])
        abp = Array([Signal(svf_storage, name=f"abp{n}") for n in range(self.N_BANDS)])
        ahp = Array([Signal(svf_storage, name=f"ahp{n}") for n in range(self.N_BANDS)])
        alp_cur_raw = Signal(svf_storage)
        abp_cur_raw = Signal(svf_storage)
        ahp_cur_raw = Signal(svf_storage)
        cutoff_cur_raw = Signal(dsp.mac.SQNative.as_shape())
        alp_cur = svf_shape(alp_cur_raw)
        abp_cur = svf_shape(abp_cur_raw)
        ahp_cur = svf_shape(ahp_cur_raw)
        cutoff_cur = dsp.mac.SQNative(cutoff_cur_raw)

        mac_a_q = Signal(dsp.mac.SQNative)
        mac_b_q = Signal(dsp.mac.SQNative)
        mac_z = Signal(dsp.mac.SQRNative)
        hp_offset_q = Signal(svf_shape)
        alp_next = Signal(svf_shape)
        ahp_next = Signal(svf_shape)
        abp_next = Signal(svf_shape)

        m.d.comb += [
            alp_cur_raw.eq(alp[band]),
            abp_cur_raw.eq(abp[band]),
            ahp_cur_raw.eq(ahp[band]),
            cutoff_cur_raw.eq(cutoffs[band]),
            mac_z.eq(mac_a_q * mac_b_q),
            alp_next.eq(mac_z + alp_cur),
            ahp_next.eq(mac_z + hp_offset_q),
            abp_next.eq(mac_z + abp_cur),
        ]

        mix_shape = signed(ASQ.as_shape().width + 5)
        main_acc = Signal(mix_shape)
        odd_acc = Signal(mix_shape)
        even_acc = Signal(mix_shape)
        term = Signal(mix_shape)
        term_q = Signal(mix_shape)
        band_is_odd_q = Signal()
        level_cur = Signal(signed(16))
        band_sample = Signal(dsp.mac.SQNative)
        main_next = Signal(mix_shape)
        odd_next = Signal(mix_shape)
        even_next = Signal(mix_shape)
        filtered_next = Signal(mix_shape)
        feedback_drive = Signal(mix_shape)
        feedback_limited = Signal(ASQ)
        feedback_soft = Signal(mix_shape)
        limit_knee_s = Signal(signed(17))
        limit_cap_s = Signal(signed(17))
        main_limited = Signal(ASQ)
        odd_limited = Signal(ASQ)
        even_limited = Signal(ASQ)
        feedback_term = Signal(dsp.mac.SQNative)
        dry_gain_term = Signal(mix_shape)
        input_mix_acc = Signal(mix_shape)
        input_mix_next = Signal(mix_shape)
        input_mix_sample = Signal(ASQ)
        input_mix_limited = Signal(ASQ)
        m.d.comb += [
            level_cur.eq(levels[band]),
            band_sample.eq(abp_cur.as_value().as_signed() >> 2),
            term.eq(mac_z.as_value().as_signed() >> (dsp.mac.SQNative.f_bits + 3)),
            feedback_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            dry_gain_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            input_mix_next.eq(input_mix_acc + dry_gain_term),
            x_drive.eq((input_mix_sample >> 1) + feedback_term),
            limit_knee_s.eq(self.limit_knee),
            limit_cap_s.eq(self.limit_cap),
            main_next.eq(main_acc + term_q),
            filtered_next.eq(main_next - dry_sample.as_value().as_signed()),
            feedback_drive.eq(filtered_next << 2),
            odd_next.eq(Mux(band_is_odd_q, odd_acc + term_q, odd_acc)),
            even_next.eq(Mux(band_is_odd_q, even_acc, even_acc + term_q)),
        ]
        # The feedback tap is deliberately driven hot for character, but a hard
        # rail turns high-resonance feedback into square-edged digital hash.
        # Use a cheap piecewise limiter: above the configured knee, extra level
        # is compressed 8:1, then capped before the loop delay.
        with m.If(feedback_drive > limit_knee_s):
            m.d.comb += feedback_soft.eq(limit_knee_s + ((feedback_drive - limit_knee_s) >> 3))
        with m.Elif(feedback_drive < -limit_knee_s):
            m.d.comb += feedback_soft.eq(-limit_knee_s + ((feedback_drive + limit_knee_s) >> 3))
        with m.Else():
            m.d.comb += feedback_soft.eq(feedback_drive)
        with m.If(feedback_soft > limit_cap_s):
            m.d.comb += feedback_limited.as_value().eq(limit_cap_s)
        with m.Elif(feedback_soft < -limit_cap_s):
            m.d.comb += feedback_limited.as_value().eq(-limit_cap_s)
        with m.Else():
            m.d.comb += feedback_limited.as_value().eq(feedback_soft)

        def limit_to_asq(source, target):
            with m.If(source > 32767):
                m.d.comb += target.as_value().eq(32767)
            with m.Elif(source < -32768):
                m.d.comb += target.as_value().eq(-32768)
            with m.Else():
                m.d.comb += target.as_value().eq(source)

        limit_to_asq(main_next, main_limited)
        limit_to_asq(odd_next, odd_limited)
        limit_to_asq(even_next, even_limited)
        limit_to_asq(input_mix_next, input_mix_limited)

        # Limit the signal entering every SVF section too.  The delayed
        # feedback sample can be civilized while the actual bank input is still
        # too hot, which makes high-Q filters chatter harshly at sympathetic
        # pitches.  Keep the center region clean and compress the shove into
        # the resonators above the configured knee.
        with m.If(x_drive > limit_knee_s):
            m.d.comb += x_limited.as_value().eq(limit_knee_s + ((x_drive.as_value().as_signed() - limit_knee_s) >> 3))
        with m.Elif(x_drive < -limit_knee_s):
            m.d.comb += x_limited.as_value().eq(-limit_knee_s + ((x_drive.as_value().as_signed() + limit_knee_s) >> 3))
        with m.Else():
            m.d.comb += x_limited.eq(x_drive)
        out_valid = Signal()
        out_ready = Signal()
        main_q = Signal(ASQ)
        odd_q = Signal(ASQ)
        even_q = Signal(ASQ)
        dry_q = Signal(ASQ)

        m.d.comb += [
            out_ready.eq(~out_valid | self.o.ready),
            self.i.ready.eq((state == state_wait) & out_ready),
        ]

        with m.If(self.o.ready):
            m.d.sync += out_valid.eq(0)

        with m.Switch(state):
            with m.Case(state_wait):
                with m.If(self.i.valid & self.i.ready):
                    for n, diff in enumerate(level_diffs):
                        with m.If(diff > self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_levels[n].eq(smooth_levels[n] + self.PARAM_SLEW_STEP)
                        with m.Elif(diff < -self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_levels[n].eq(smooth_levels[n] - self.PARAM_SLEW_STEP)
                        with m.Else():
                            m.d.sync += smooth_levels[n].eq(self.levels[n])
                    with m.If(dry_diff > self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_dry.eq(smooth_dry + self.PARAM_SLEW_STEP)
                    with m.Elif(dry_diff < -self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_dry.eq(smooth_dry - self.PARAM_SLEW_STEP)
                    with m.Else():
                        m.d.sync += smooth_dry.eq(self.dry)
                    with m.If(resonance_diff > self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_resonance.eq(smooth_resonance + self.PARAM_SLEW_STEP)
                    with m.Elif(resonance_diff < -self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_resonance.eq(smooth_resonance - self.PARAM_SLEW_STEP)
                    with m.Else():
                        m.d.sync += smooth_resonance.eq(self.resonance)
                    with m.If(feedback_diff > self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_feedback.eq(smooth_feedback + self.PARAM_SLEW_STEP)
                    with m.Elif(feedback_diff < -self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_feedback.eq(smooth_feedback - self.PARAM_SLEW_STEP)
                    with m.Else():
                        m.d.sync += smooth_feedback.eq(self.feedback)
                    for n, diff in enumerate(input_gain_diffs):
                        with m.If(diff > self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_input_gains[n].eq(smooth_input_gains[n] + self.PARAM_SLEW_STEP)
                        with m.Elif(diff < -self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_input_gains[n].eq(smooth_input_gains[n] - self.PARAM_SLEW_STEP)
                        with m.Else():
                            m.d.sync += smooth_input_gains[n].eq(self.input_gains[n])
                    m.d.sync += [
                        input_mix_acc.eq(0),
                        input_chan.eq(0),
                        mac_a_q.eq(self.i.payload[0]),
                        mac_b_q.eq(smooth_input_gains[0] >> 1),
                        state.eq(state_input_gain_commit),
                    ]

            with m.Case(state_input_gain_commit):
                with m.Switch(input_chan):
                    with m.Case(0):
                        m.d.sync += [
                            input_mix_acc.eq(input_mix_next),
                            input_chan.eq(1),
                            mac_a_q.eq(self.i.payload[1]),
                            mac_b_q.eq(smooth_input_gains[1] >> 1),
                        ]
                    with m.Case(1):
                        m.d.sync += [
                            input_mix_acc.eq(input_mix_next),
                            input_chan.eq(2),
                            mac_a_q.eq(self.i.payload[2]),
                            mac_b_q.eq(smooth_input_gains[2] >> 1),
                        ]
                    with m.Case(2):
                        m.d.sync += [
                            input_mix_acc.eq(input_mix_next),
                            input_chan.eq(3),
                            mac_a_q.eq(self.i.payload[3]),
                            mac_b_q.eq(smooth_input_gains[3] >> 1),
                        ]
                    with m.Default():
                        m.d.sync += [
                            input_mix_sample.eq(input_mix_limited),
                            resonance.eq(resonance_ctl),
                            mac_a_q.eq(feedback_sample),
                            mac_b_q.eq(feedback_gain >> 1),
                            band.eq(0),
                            oversample.eq(0),
                            state.eq(state_feedback_commit),
                        ]

            with m.Case(state_feedback_commit):
                m.d.sync += [
                    x.eq(x_limited),
                    mac_a_q.eq(input_mix_sample),
                    mac_b_q.eq(smooth_dry >> 1),
                    state.eq(state_dry_gain_commit),
                ]

            with m.Case(state_dry_gain_commit):
                m.d.sync += [
                    dry_sample.eq(dry_gain_term),
                    main_acc.eq(dry_gain_term),
                    odd_acc.eq(0),
                    even_acc.eq(0),
                    state.eq(state_mac0_setup),
                ]

            with m.Case(state_mac0_setup):
                m.d.sync += [
                    mac_a_q.eq(abp_cur),
                    mac_b_q.eq(cutoff_cur),
                    state.eq(state_mac0_commit),
                ]

            with m.Case(state_mac0_commit):
                m.d.sync += [
                    alp[band].eq(alp_next.saturate(svf_shape).as_value()),
                    state.eq(state_mac1_setup),
                ]

            with m.Case(state_mac1_setup):
                m.d.sync += [
                    mac_a_q.eq(abp_cur),
                    mac_b_q.eq(-resonance),
                    hp_offset_q.eq(x - alp_cur),
                    state.eq(state_mac1_commit),
                ]

            with m.Case(state_mac1_commit):
                m.d.sync += [
                    ahp[band].eq(ahp_next.saturate(svf_shape).as_value()),
                    state.eq(state_mac2_setup),
                ]

            with m.Case(state_mac2_setup):
                m.d.sync += [
                    mac_a_q.eq(ahp_cur),
                    mac_b_q.eq(cutoff_cur),
                    state.eq(state_mac2_commit),
                ]

            with m.Case(state_mac2_commit):
                m.d.sync += abp[band].eq(abp_next.saturate(svf_shape).as_value())
                with m.If(~oversample):
                    m.d.sync += [
                        oversample.eq(1),
                        state.eq(state_mac0_setup),
                    ]
                with m.Else():
                    m.d.sync += [
                        oversample.eq(0),
                        state.eq(state_mix_setup),
                    ]

            with m.Case(state_mix_setup):
                m.d.sync += [
                    mac_a_q.eq(band_sample),
                    mac_b_q.eq(level_cur),
                    band_is_odd_q.eq(band[0]),
                    state.eq(state_mix_gain_commit),
                ]

            with m.Case(state_mix_gain_commit):
                m.d.sync += [
                    term_q.eq(term),
                    state.eq(state_mix_commit),
                ]

            with m.Case(state_mix_commit):
                m.d.sync += [
                    main_acc.eq(main_next),
                    odd_acc.eq(odd_next),
                    even_acc.eq(even_next),
                ]
                with m.If(band == self.N_BANDS - 1):
                    m.d.sync += [
                        main_q.eq(main_limited),
                        odd_q.eq(odd_limited),
                        even_q.eq(even_limited),
                        feedback_sample.eq(feedback_limited),
                        dry_q.eq(dry_sample),
                        out_valid.eq(1),
                        state.eq(state_wait),
                    ]
                with m.Else():
                    m.d.sync += [
                        band.eq(band + 1),
                        state.eq(state_mac0_setup),
                    ]

        m.d.comb += [
            self.o.valid.eq(out_valid),
            self.o.payload[0].eq(main_q),
            self.o.payload[1].eq(odd_q),
            self.o.payload[2].eq(even_q),
            self.o.payload[3].eq(dry_q),
        ]
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
        self._feedback = regs.add("feedback", self.UnsignedValue(), offset=0x38)
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

        self.rezo_periph_base = 0x00001000
        self.rezo_periph = RezoPeripheral()
        self.csr_decoder.add(self.rezo_periph.bus, addr=self.rezo_periph_base, name="rezo_periph")

        self.add_rust_constant(f"pub const N_BANDS: usize = {RezoCore.N_BANDS};\n")

        self.finalize_csr_bridge()

    def elaborate(self, platform):
        m = Module()

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

        return m


class RezoHardwareUI(wiring.Component):
    """Small no-SoC control surface for the beam-raced REZO prototype."""

    N_TARGETS = RezoCore.N_BANDS + 12
    TARGET_PAGE = 0
    TARGET_PRESET = 1
    TARGET_BAND_BASE = 2
    TARGET_DRY = RezoCore.N_BANDS + 2
    TARGET_RESONANCE = RezoCore.N_BANDS + 3
    TARGET_FEEDBACK = RezoCore.N_BANDS + 4
    TARGET_LIMIT_KNEE = RezoCore.N_BANDS + 5
    TARGET_LIMIT_CAP = RezoCore.N_BANDS + 6
    TARGET_DAMP = RezoCore.N_BANDS + 7
    TARGET_INPUT_BASE = RezoCore.N_BANDS + 8

    def __init__(self):
        super().__init__({
            "enc_i": In(1),
            "enc_q": In(1),
            "button": In(1),
            "levels": Out(data.ArrayLayout(signed(16), RezoCore.N_BANDS)),
            "dry": Out(unsigned(16)),
            "resonance": Out(unsigned(16)),
            "feedback": Out(unsigned(16)),
            "limit_knee": Out(unsigned(16)),
            "limit_cap": Out(unsigned(16)),
            "damp_mode": Out(unsigned(3)),
            "input_gains": Out(data.ArrayLayout(unsigned(16), 4)),
            "selected": Out(unsigned(5)),
            "page": Out(unsigned(2)),
            "preset": Out(unsigned(3)),
            "editing": Out(1),
        })

    @staticmethod
    def clamp_add(m, signal, delta, min_value, max_value):
        with m.If(delta > 0):
            with m.If(signal <= max_value - delta):
                m.d.sync += signal.eq(signal + delta)
            with m.Else():
                m.d.sync += signal.eq(max_value)
        with m.Else():
            with m.If(signal >= min_value - delta):
                m.d.sync += signal.eq(signal + delta)
            with m.Else():
                m.d.sync += signal.eq(min_value)

    @staticmethod
    def apply_preset(m, preset, levels):
        with m.Switch(preset):
            with m.Case(0):  # all bands
                for level in levels:
                    m.d.sync += level.eq(8192)
            with m.Case(1):  # odd bands
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(8192 if n & 1 else 0)
            with m.Case(2):  # even bands
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(0 if n & 1 else 8192)
            with m.Case(3):  # lows
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(8192 if n < 4 else 0)
            with m.Case(4):  # mids
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(8192 if 3 <= n <= 6 else 0)
            with m.Case(5):  # highs
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(8192 if n >= 6 else 0)
            with m.Case(6):  # zero
                for level in levels:
                    m.d.sync += level.eq(0)

    def elaborate(self, platform):
        m = Module()

        levels = [Signal(signed(16), init=8192, name=f"ui_level{n}")
                  for n in range(RezoCore.N_BANDS)]
        dry = Signal(unsigned(16), init=0)
        resonance = Signal(unsigned(16), init=8192)
        feedback = Signal(unsigned(16), init=0)
        limit_knee = Signal(unsigned(16), init=12288)
        limit_cap = Signal(unsigned(16), init=24576)
        damp_mode = Signal(unsigned(3), init=2)
        input_gains = [Signal(unsigned(16), init=32768 if n == 0 else 0,
                              name=f"ui_input_gain{n}")
                       for n in range(4)]
        selected = Signal(range(self.N_TARGETS), init=self.TARGET_PAGE)
        page = Signal(unsigned(2), init=0)
        preset = Signal(range(7), init=0)
        next_preset = Signal(range(7))
        next_selected = Signal(range(self.N_TARGETS))
        bank_target_visible = Signal()
        tune_target_visible = Signal()
        input_target_visible = Signal()
        editing = Signal()

        iq_sync = Signal(2)
        iq_prev = Signal(2)
        detent_armed = Signal()
        detent_acc = Signal(signed(4))
        transition_delta = Signal(signed(3))
        next_detent_acc = Signal(signed(5))
        iq_is_detent = Signal()
        iq_prev_is_detent = Signal()
        edit_step = Signal()
        edit_direction = Signal()
        m.submodules += FFSynchronizer(Cat(self.enc_i, self.enc_q), iq_sync, init=0)

        forward_transition = (
            ((iq_prev == 0b00) & (iq_sync == 0b01)) |
            ((iq_prev == 0b01) & (iq_sync == 0b11)) |
            ((iq_prev == 0b11) & (iq_sync == 0b10)) |
            ((iq_prev == 0b10) & (iq_sync == 0b00))
        )
        reverse_transition = (
            ((iq_prev == 0b00) & (iq_sync == 0b10)) |
            ((iq_prev == 0b10) & (iq_sync == 0b11)) |
            ((iq_prev == 0b11) & (iq_sync == 0b01)) |
            ((iq_prev == 0b01) & (iq_sync == 0b00))
        )
        m.d.comb += [
            transition_delta.eq(Mux(forward_transition, 1,
                                    Mux(reverse_transition, -1, 0))),
            next_detent_acc.eq(detent_acc + transition_delta),
            iq_is_detent.eq((iq_sync == 0b00) | (iq_sync == 0b11)),
            iq_prev_is_detent.eq((iq_prev == 0b00) | (iq_prev == 0b11)),
        ]

        m.d.sync += [
            edit_step.eq(0),
            iq_prev.eq(iq_sync),
        ]
        with m.If(iq_sync != iq_prev):
            with m.If(transition_delta != 0):
                with m.If(iq_prev_is_detent & ~iq_is_detent):
                    m.d.sync += [
                        detent_armed.eq(1),
                        detent_acc.eq(transition_delta),
                    ]
                with m.Elif(iq_is_detent & detent_armed):
                    with m.If(next_detent_acc > 0):
                        m.d.sync += [
                            edit_step.eq(1),
                            edit_direction.eq(0),
                        ]
                    with m.Elif(next_detent_acc < 0):
                        m.d.sync += [
                            edit_step.eq(1),
                            edit_direction.eq(1),
                        ]
                    m.d.sync += [
                        detent_acc.eq(0),
                        detent_armed.eq(0),
                    ]
                with m.Else():
                    m.d.sync += detent_acc.eq(next_detent_acc)

        button_sync = Signal()
        button_last = Signal()
        click = Signal()
        click_lockout = Signal(unsigned(23))
        click_ready = Signal(init=1)
        m.submodules += FFSynchronizer(self.button, button_sync, init=0)
        m.d.sync += button_last.eq(button_sync)
        m.d.sync += click.eq(0)
        with m.If(click_lockout != 0):
            m.d.sync += click_lockout.eq(click_lockout - 1)
        with m.Elif(~button_sync):
            m.d.sync += click_ready.eq(1)
        with m.Elif(click_ready & button_sync & ~button_last):
            m.d.sync += [
                click.eq(1),
                click_ready.eq(0),
                click_lockout.eq(7200000),
            ]

        m.d.comb += next_preset.eq(preset)
        with m.If(edit_direction):
            m.d.comb += next_preset.eq(Mux(preset == 6, 0, preset + 1))
        with m.Else():
            m.d.comb += next_preset.eq(Mux(preset == 0, 6, preset - 1))

        m.d.comb += [
            bank_target_visible.eq((selected <= self.TARGET_FEEDBACK)),
            tune_target_visible.eq((selected == self.TARGET_PAGE) |
                                   ((selected >= self.TARGET_LIMIT_KNEE) &
                                    (selected <= self.TARGET_DAMP))),
            input_target_visible.eq((selected == self.TARGET_PAGE) |
                                    ((selected >= self.TARGET_INPUT_BASE) &
                                     (selected < self.TARGET_INPUT_BASE + 4))),
            next_selected.eq(selected),
        ]
        with m.If(page == 0):
            with m.If(edit_direction):
                with m.If(~bank_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_PRESET)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_PRESET)
                with m.Elif(selected == self.TARGET_FEEDBACK):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~bank_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_FEEDBACK)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_FEEDBACK)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.Elif(page == 1):
            with m.If(edit_direction):
                with m.If(~tune_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_LIMIT_KNEE)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_LIMIT_KNEE)
                with m.Elif(selected == self.TARGET_DAMP):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~tune_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_DAMP)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_DAMP)
                with m.Elif(selected == self.TARGET_LIMIT_KNEE):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.Else():
            with m.If(edit_direction):
                with m.If(~input_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_INPUT_BASE)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_INPUT_BASE)
                with m.Elif(selected == self.TARGET_INPUT_BASE + 3):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~input_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_INPUT_BASE + 3)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_INPUT_BASE + 3)
                with m.Elif(selected == self.TARGET_INPUT_BASE):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.If(click):
            with m.If(editing):
                with m.If(selected == self.TARGET_PRESET):
                    self.apply_preset(m, preset, levels)
                m.d.sync += editing.eq(0)
            with m.Else():
                m.d.sync += editing.eq(1)

        step_amount = 1024
        with m.If(edit_step):
            with m.If(~editing):
                m.d.sync += selected.eq(next_selected)
            with m.Else():
                with m.If(selected == self.TARGET_PRESET):
                    m.d.sync += preset.eq(next_preset)
                with m.Elif(selected == self.TARGET_PAGE):
                    with m.If(edit_direction):
                        m.d.sync += page.eq(Mux(page == 2, 0, page + 1))
                    with m.Else():
                        m.d.sync += page.eq(Mux(page == 0, 2, page - 1))
                with m.Elif(selected == self.TARGET_DRY):
                    with m.If(edit_direction):
                        self.clamp_add(m, dry, step_amount, 0, 32768)
                    with m.Else():
                        self.clamp_add(m, dry, -step_amount, 0, 32768)
                with m.Elif(selected == self.TARGET_RESONANCE):
                    with m.If(edit_direction):
                        self.clamp_add(m, resonance, step_amount, 0, 32768)
                    with m.Else():
                        self.clamp_add(m, resonance, -step_amount, 0, 32768)
                with m.Elif(selected == self.TARGET_FEEDBACK):
                    with m.If(edit_direction):
                        self.clamp_add(m, feedback, step_amount, 0, 32768)
                    with m.Else():
                        self.clamp_add(m, feedback, -step_amount, 0, 32768)
                with m.Elif(selected == self.TARGET_LIMIT_KNEE):
                    with m.If(edit_direction):
                        self.clamp_add(m, limit_knee, step_amount, 4096, 32768)
                    with m.Else():
                        self.clamp_add(m, limit_knee, -step_amount, 4096, 32768)
                with m.Elif(selected == self.TARGET_LIMIT_CAP):
                    with m.If(edit_direction):
                        self.clamp_add(m, limit_cap, step_amount, 4096, 32768)
                    with m.Else():
                        self.clamp_add(m, limit_cap, -step_amount, 4096, 32768)
                with m.Elif(selected == self.TARGET_DAMP):
                    with m.If(edit_direction):
                        self.clamp_add(m, damp_mode, 1, 0, 4)
                    with m.Else():
                        self.clamp_add(m, damp_mode, -1, 0, 4)
                for n, input_gain in enumerate(input_gains):
                    with m.Elif(selected == self.TARGET_INPUT_BASE + n):
                        with m.If(edit_direction):
                            self.clamp_add(m, input_gain, step_amount, 0, 32768)
                        with m.Else():
                            self.clamp_add(m, input_gain, -step_amount, 0, 32768)
                with m.Else():
                    for n, level in enumerate(levels):
                        with m.If(selected == self.TARGET_BAND_BASE + n):
                            with m.If(edit_direction):
                                self.clamp_add(m, level, step_amount, -16384, 16383)
                            with m.Else():
                                self.clamp_add(m, level, -step_amount, -16384, 16383)

        for n, level in enumerate(levels):
            m.d.comb += self.levels[n].eq(level)
        for n, input_gain in enumerate(input_gains):
            m.d.comb += self.input_gains[n].eq(input_gain)
        m.d.comb += [
            self.dry.eq(dry),
            self.resonance.eq(resonance),
            self.feedback.eq(feedback),
            self.limit_knee.eq(limit_knee),
            self.limit_cap.eq(limit_cap),
            self.damp_mode.eq(damp_mode),
            self.selected.eq(selected),
            self.page.eq(page),
            self.preset.eq(preset),
            self.editing.eq(editing),
        ]

        return m


class RezoBeamDisplay(wiring.Component):
    """Monochrome 720x720 beam-raced REZO panel.

    The renderer is intentionally LCD-like: a bounded 720x720 coordinate space,
    coarse shapes, small bitmap text, and cheap animation.  On 1280x720 it is
    centered; on 720x720 it fills the display.  This keeps the UI predictable
    and leaves headroom for DSP growth and modulation.
    """

    FONT_5X7 = {
        " ": [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000],
        "0": [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
        "1": [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
        "2": [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111],
        "3": [0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110],
        "4": [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
        "5": [0b11111, 0b10000, 0b10000, 0b11110, 0b00001, 0b00001, 0b11110],
        "6": [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
        "7": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
        "8": [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
        "9": [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100],
        "A": [0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
        "B": [0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110],
        "C": [0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110],
        "D": [0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110],
        "E": [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111],
        "F": [0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000],
        "G": [0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110],
        "H": [0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001],
        "I": [0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
        "K": [0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001],
        "L": [0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111],
        "M": [0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001],
        "N": [0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001],
        "O": [0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
        "P": [0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000],
        "Q": [0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101],
        "R": [0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001],
        "S": [0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110],
        "T": [0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100],
        "U": [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110],
        "V": [0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100],
        "W": [0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b10101, 0b01010],
        "X": [0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001],
        "Y": [0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100],
        "Z": [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111],
    }

    PANEL_W = 720
    PANEL_H = 720

    def __init__(self, h_active=1280):
        self.x_offset = max(0, (h_active - self.PANEL_W) // 2)
        super().__init__({
            "x": In(signed(12)),
            "y": In(signed(12)),
            "de": In(1),
            "levels": In(data.ArrayLayout(signed(6), RezoCore.N_BANDS)),
            "dry": In(unsigned(6)),
            "resonance": In(unsigned(6)),
            "feedback": In(unsigned(6)),
            "limit_knee": In(unsigned(6)),
            "limit_cap": In(unsigned(6)),
            "damp_mode": In(unsigned(3)),
            "input_gains": In(data.ArrayLayout(unsigned(6), 4)),
            "selected": In(unsigned(5)),
            "page": In(unsigned(2)),
            "preset": In(unsigned(3)),
            "editing": In(1),
            "r": Out(8),
            "g": Out(8),
            "b": Out(8),
        })

    @classmethod
    def text_pixel(cls, m, x, y, text, x0, y0, scale_shift=1, name="text"):
        """Return a pixel signal for an 8x8-cell 5x7 bitmap text run.

        scale_shift 1 means 2x pixels, 2 means 4x pixels.  Using power-of-two
        cells keeps glyph lookup cheap compared with arbitrary rectangle text.
        """
        cell_shift = 3 + scale_shift
        local_x = Signal(signed(12), name=f"{name}_lx")
        local_y = Signal(signed(12), name=f"{name}_ly")
        char_idx = Signal(unsigned(max(1, (len(text) - 1).bit_length())), name=f"{name}_ci")
        glyph_col = Signal(3, name=f"{name}_col")
        glyph_row = Signal(3, name=f"{name}_row")
        row_bits = Signal(5, name=f"{name}_bits")
        pixel = Signal(name=name)
        in_text = Signal(name=f"{name}_in")

        m.d.comb += [
            local_x.eq(x - x0),
            local_y.eq(y - y0),
            in_text.eq((x >= x0) & (x < x0 + (len(text) << cell_shift)) &
                       (y >= y0) & (y < y0 + (8 << scale_shift))),
            char_idx.eq(local_x[cell_shift:cell_shift + max(1, (len(text) - 1).bit_length())]),
            glyph_col.eq(local_x[scale_shift:scale_shift + 3]),
            glyph_row.eq(local_y[scale_shift:scale_shift + 3]),
            row_bits.eq(0),
            pixel.eq(0),
        ]

        for char_i, char in enumerate(text):
            glyph = cls.FONT_5X7.get(char, cls.FONT_5X7[" "])
            for row, bits in enumerate(glyph):
                with m.If(in_text & (char_idx == char_i) & (glyph_row == row)):
                    m.d.comb += row_bits.eq(bits)

        for col in range(5):
            with m.If(in_text & (glyph_col == col)):
                m.d.comb += pixel.eq(row_bits[4 - col])

        return pixel

    @classmethod
    def fixed_text_pixel(cls, m, x, y, text, x0, y0, scale_shift=1, name="text"):
        """Return a pixel signal for a fixed 5x7 text label.

        Unlike ``text_pixel``, this pre-flattens the whole word into seven row
        bitmaps at elaboration time.  The DVI logic then chooses only one row
        and one bit.  This is much friendlier to 1280x720p60 timing than a
        character-indexed glyph mux for every label.
        """
        cell_w = 6
        text_cols = max(1, len(text) * cell_w - 1)
        col_w = max(1, (text_cols - 1).bit_length())
        row_masks = []
        for row in range(7):
            bits = []
            for char_i, char in enumerate(text):
                glyph = cls.FONT_5X7.get(char, cls.FONT_5X7[" "])
                row_bits = glyph[row]
                for col in range(5):
                    bits.append((row_bits >> (4 - col)) & 1)
                if char_i != len(text) - 1:
                    bits.append(0)
            mask = 0
            for bit in bits:
                mask = (mask << 1) | bit
            row_masks.append(mask)

        local_x = Signal(signed(12), name=f"{name}_lx")
        local_y = Signal(signed(12), name=f"{name}_ly")
        col = Signal(unsigned(col_w), name=f"{name}_col")
        row = Signal(3, name=f"{name}_row")
        bit_offset = Signal(unsigned(col_w), name=f"{name}_bit")
        row_bits = Signal(text_cols, name=f"{name}_bits")
        pixel = Signal(name=name)
        in_text = Signal(name=f"{name}_in")

        m.d.comb += [
            local_x.eq(x - x0),
            local_y.eq(y - y0),
            in_text.eq((x >= x0) & (x < x0 + (text_cols << scale_shift)) &
                       (y >= y0) & (y < y0 + (7 << scale_shift))),
            col.eq(local_x[scale_shift:scale_shift + col_w]),
            row.eq(local_y[scale_shift:scale_shift + 3]),
            bit_offset.eq((text_cols - 1) - col),
            row_bits.eq(0),
        ]

        for row_i, mask in enumerate(row_masks):
            with m.If(in_text & (row == row_i)):
                m.d.comb += row_bits.eq(mask)

        m.d.comb += pixel.eq(in_text & row_bits.bit_select(bit_offset, 1))
        return pixel

    @staticmethod
    def rect(x, y, x0, y0, x1, y1):
        return (x >= x0) & (x < x1) & (y >= y0) & (y < y1)

    @classmethod
    def outline(cls, x, y, x0, y0, x1, y1, t=2):
        return cls.rect(x, y, x0, y0, x1, y1) & (
            (x < x0 + t) | (x >= x1 - t) | (y < y0 + t) | (y >= y1 - t))

    def elaborate(self, platform):
        m = Module()

        sx = self.x
        sy = self.y
        x = Signal(signed(12))
        y = Signal(signed(12))
        active = Signal()
        m.d.comb += [
            x.eq(sx - self.x_offset),
            y.eq(sy),
            active.eq(self.de & (sx >= self.x_offset) & (sx < self.x_offset + self.PANEL_W) &
                      (sy >= 0) & (sy < self.PANEL_H)),
        ]

        frame = Signal(8)
        last_vblank = Signal()
        vblank = Signal()
        m.d.comb += vblank.eq(sy < 0)
        m.d.dvi += last_vblank.eq(vblank)
        with m.If(vblank & ~last_vblank):
            m.d.dvi += frame.eq(frame + 1)

        text_signals = [
            self.fixed_text_pixel(m, x, y, "REZO", 36, 28, scale_shift=2,
                                  name="lcd_rezo"),
            self.fixed_text_pixel(m, x, y, "PRESET", 36, 104,
                                  name="lcd_preset"),
            self.fixed_text_pixel(m, x, y, "BANDS", 36, 168,
                                  name="lcd_bands"),
            self.fixed_text_pixel(m, x, y, "DRY", 36, 604,
                                  name="lcd_dry"),
            self.fixed_text_pixel(m, x, y, "RES", 36, 648,
                                  name="lcd_res"),
        ]

        preset_chip = Signal()
        preset_select = Signal()
        preset_chip_signals = []
        preset_select_signals = []
        preset_names = ["ALL", "ODD", "EVN", "LOW", "MID", "HI"]
        for p in range(6):
            x0 = 166 + 74 * p
            preset_chip_signals.append(self.rect(x, y, x0, 96, x0 + 52, 132))
            preset_select_signals.append(
                (self.preset == p) & self.outline(x, y, x0 - 5, 91, x0 + 57, 137, t=3))
            label = preset_names[p]
            text_signals.append(
                self.fixed_text_pixel(m, x, y, label, x0 + 6, 106,
                                      name=f"lcd_preset_{p}"))

        band_slot = Signal()
        band_fill = Signal()
        band_marker = Signal()
        band_negative = Signal()
        band_select = Signal()
        band_zero = Signal()
        band_slot_signals = []
        band_fill_signals = []
        band_marker_signals = []
        band_negative_signals = []
        band_select_signals = []
        band_zero_signals = []
        band_names = ["29", "61", "115", "218", "411", "777", "1K5", "2K8", "5K2", "11K"]
        zero_y = 366
        for n in range(RezoCore.N_BANDS):
            x0 = 48 + 66 * n
            x1 = x0 + 42
            level = self.levels[n]
            mag = Signal(unsigned(5), name=f"lcd_mag{n}")
            top_y = Signal(signed(12), name=f"lcd_top{n}")
            bottom_y = Signal(signed(12), name=f"lcd_bottom{n}")
            selected_band = self.selected == RezoHardwareUI.TARGET_BAND_BASE + n
            m.d.comb += [
                mag.eq(Mux(level < 0, -level, level)),
                top_y.eq(zero_y - (mag << 4)),
                bottom_y.eq(zero_y + (mag << 4)),
            ]
            band_slot_signals.append(self.rect(x, y, x0, 202, x1, 532))
            band_zero_signals.append(self.rect(x, y, x0 - 5, zero_y - 1, x1 + 5, zero_y + 2))
            band_marker_signals.append(
                ((level > 0) & self.rect(x, y, x0, zero_y - 130, x1, zero_y - 124)) |
                ((level < 0) & self.rect(x, y, x0, zero_y + 124, x1, zero_y + 130)))
            band_fill_signals.append(
                selected_band &
                ((self.rect(x, y, x0, top_y, x1, zero_y) & (level >= 0)) |
                 (self.rect(x, y, x0, zero_y, x1, bottom_y) & (level < 0))))
            band_negative_signals.append(
                selected_band & self.rect(x, y, x0, zero_y, x1, bottom_y) & (level < 0))
            band_select_signals.append(
                selected_band & self.outline(x, y, x0 - 7, 195, x1 + 7, 539, t=3))
            band_label = band_names[n]
            band_label_x = x0 + (5 if len(band_label) == 3 else 10)
            text_signals.append(
                self.fixed_text_pixel(m, x, y, band_label, band_label_x, 548,
                                      name=f"lcd_band_{n}"))

        for target, signals in [
                (preset_chip, preset_chip_signals),
                (preset_select, preset_select_signals),
                (band_slot, band_slot_signals),
                (band_fill, band_fill_signals),
                (band_marker, band_marker_signals),
                (band_negative, band_negative_signals),
                (band_select, band_select_signals),
                (band_zero, band_zero_signals)]:
            expr = Const(0)
            for sig in signals:
                expr = expr | sig
            m.d.comb += target.eq(expr)

        band_fill_q0 = Signal()
        band_marker_q0 = Signal()
        band_negative_q0 = Signal()
        m.d.dvi += [
            band_fill_q0.eq(band_fill),
            band_marker_q0.eq(band_marker),
            band_negative_q0.eq(band_negative),
        ]

        dry_fill = self.rect(x, y, 124, 604, 124 + (self.dry << 4), 624)
        dry_select = (self.selected == RezoHardwareUI.TARGET_DRY) & self.outline(
            x, y, 118, 596, 650, 632, t=3)
        res_fill = self.rect(x, y, 124, 648, 124 + (self.resonance << 4), 668)
        res_select = (self.selected == RezoHardwareUI.TARGET_RESONANCE) & self.outline(
            x, y, 118, 640, 650, 676, t=3)

        text = Signal()
        text_group_q = []
        for group_idx in range(0, len(text_signals), 1):
            text_group = Signal(name=f"lcd_text_group{group_idx}")
            text_group_q_sig = Signal(name=f"lcd_text_group{group_idx}_q")
            text_expr = Const(0)
            for sig in text_signals[group_idx:group_idx + 1]:
                text_expr = text_expr | sig
            m.d.comb += text_group.eq(text_expr)
            m.d.dvi += text_group_q_sig.eq(text_group)
            text_group_q.append(text_group_q_sig)
        text_expr = Const(0)
        for sig in text_group_q:
            text_expr = text_expr | sig
        m.d.comb += text.eq(text_expr)

        border = active & self.outline(x, y, 12, 12, 708, 708, t=2)
        title_panel = active & self.rect(x, y, 20, 20, 700, 82)
        bands_panel = active & self.rect(x, y, 28, 190, 692, 574)
        meter_panel = active & (self.rect(x, y, 118, 596, 650, 632) |
                                self.rect(x, y, 118, 640, 650, 676))
        grid = Const(0)
        scan = Const(0)
        selected = active & (preset_select | band_select | dry_select | res_select)

        selected_q = Signal()
        text_q = Signal()
        band_negative_q = Signal()
        fill_q = Signal()
        line_q = Signal()
        panel_q = Signal()
        background_q = Signal()
        active_q = Signal()
        m.d.dvi += [
            selected_q.eq(selected),
            text_q.eq(text),
            band_negative_q.eq(band_negative_q0),
            fill_q.eq(band_fill_q0 | band_marker_q0 | dry_fill | res_fill),
            line_q.eq(band_zero | border | scan),
            panel_q.eq(preset_chip | band_slot | meter_panel),
            background_q.eq(grid | title_panel | bands_panel),
            active_q.eq(active),
        ]

        mono = Signal(8)
        with m.If(selected_q):
            m.d.comb += mono.eq(0xff)
        with m.Elif(text_q):
            m.d.comb += mono.eq(0xdc)
        with m.Elif(band_negative_q):
            m.d.comb += mono.eq(0xb0)
        with m.Elif(fill_q):
            m.d.comb += mono.eq(0x9a)
        with m.Elif(line_q):
            m.d.comb += mono.eq(0x72)
        with m.Elif(panel_q):
            m.d.comb += mono.eq(0x34)
        with m.Elif(background_q):
            m.d.comb += mono.eq(0x18)
        with m.Elif(active_q):
            m.d.comb += mono.eq(0x05)
        with m.Else():
            m.d.comb += mono.eq(0)

        # Green monochrome LCD palette.  Color can come back later; the logic
        # stays scalar for now so UI growth does not steal timing from DSP.
        m.d.dvi += [
            self.r.eq(mono >> 3),
            self.g.eq(mono),
            self.b.eq(mono >> 2),
        ]

        return m


class RezoTileDisplay(wiring.Component):
    """Low-resolution, character-cell REZO UI.

    This renderer treats the 720x720 panel like a 45x45 grid of 16x16 cells.
    Text is drawn by selecting one character for the current cell, then looking
    up one 5x7 glyph row.  That keeps text cost roughly constant as labels are
    added, instead of OR-ing together a pile of independent pixel label layers.
    """

    PANEL_W = 720
    PANEL_H = 720
    CELL_SHIFT = 4

    CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    CHAR_CODES = {ch: i for i, ch in enumerate(CHARS)}

    def __init__(self, h_active=1280):
        self.x_offset = max(0, (h_active - self.PANEL_W) // 2)
        super().__init__({
            "x": In(signed(12)),
            "y": In(signed(12)),
            "de": In(1),
            "levels": In(data.ArrayLayout(signed(6), RezoCore.N_BANDS)),
            "dry": In(unsigned(6)),
            "resonance": In(unsigned(6)),
            "feedback": In(unsigned(6)),
            "limit_knee": In(unsigned(6)),
            "limit_cap": In(unsigned(6)),
            "damp_mode": In(unsigned(3)),
            "input_gains": In(data.ArrayLayout(unsigned(6), 4)),
            "selected": In(unsigned(5)),
            "page": In(unsigned(2)),
            "preset": In(unsigned(3)),
            "editing": In(1),
            "r": Out(8),
            "g": Out(8),
            "b": Out(8),
        })

    @classmethod
    def code(cls, ch):
        return cls.CHAR_CODES.get(ch, 0)

    @classmethod
    def place_text(cls, m, char_code, cell_x, cell_y, text, x0, y0):
        for idx, ch in enumerate(text):
            if ch != " ":
                with m.If((cell_y == y0) & (cell_x == x0 + idx)):
                    m.d.comb += char_code.eq(cls.code(ch))

    @staticmethod
    def rect(x, y, x0, y0, x1, y1):
        return (x >= x0) & (x < x1) & (y >= y0) & (y < y1)

    @classmethod
    def outline(cls, x, y, x0, y0, x1, y1, t=2):
        return cls.rect(x, y, x0, y0, x1, y1) & (
            (x < x0 + t) | (x >= x1 - t) | (y < y0 + t) | (y >= y1 - t))

    def elaborate(self, platform):
        m = Module()

        sx = self.x
        sy = self.y
        x = Signal(signed(12))
        y = Signal(signed(12))
        active = Signal()
        m.d.comb += [
            x.eq(sx - self.x_offset),
            y.eq(sy),
            active.eq(self.de & (sx >= self.x_offset) & (sx < self.x_offset + self.PANEL_W) &
                      (sy >= 0) & (sy < self.PANEL_H)),
        ]

        zero_y = 366
        band_top_values = [Signal(signed(12), init=zero_y, name=f"tile_band_top_value{n}")
                           for n in range(RezoCore.N_BANDS)]
        band_bottom_values = [Signal(signed(12), init=zero_y, name=f"tile_band_bottom_value{n}")
                              for n in range(RezoCore.N_BANDS)]
        band_positive_values = [Signal(name=f"tile_band_positive{n}")
                                for n in range(RezoCore.N_BANDS)]
        band_negative_values = [Signal(name=f"tile_band_negative{n}")
                                for n in range(RezoCore.N_BANDS)]

        for n in range(RezoCore.N_BANDS):
            level = self.levels[n]
            mag = Signal(unsigned(6), name=f"tile_level_mag{n}")
            height = Signal(signed(12), name=f"tile_level_height{n}")
            m.d.comb += [
                mag.eq(Mux(level < 0, -level, level)),
                height.eq((mag << 3) + (mag << 1) + Mux(level < 0, mag >> 2, mag)),
            ]
            m.d.dvi += [
                band_top_values[n].eq(zero_y - height),
                band_bottom_values[n].eq(zero_y + height),
                band_positive_values[n].eq(level > 0),
                band_negative_values[n].eq(level < 0),
            ]

        cell_x = Signal(unsigned(6))
        cell_y = Signal(unsigned(6))
        glyph_col = Signal(unsigned(3))
        glyph_row = Signal(unsigned(3))
        m.d.comb += [
            cell_x.eq(x[self.CELL_SHIFT:]),
            cell_y.eq(y[self.CELL_SHIFT:]),
            glyph_col.eq(x[1:4]),
            glyph_row.eq(y[1:4]),
        ]

        char_code = Signal(unsigned(6))
        bank_page = Signal()
        tune_page = Signal()
        input_page = Signal()
        m.d.comb += [
            char_code.eq(0),
            bank_page.eq(self.page == 0),
            tune_page.eq(self.page == 1),
            input_page.eq(self.page == 2),
        ]
        self.place_text(m, char_code, cell_x, cell_y, "REZO", 2, 2)
        with m.If(self.editing):
            self.place_text(m, char_code, cell_x, cell_y, "EDIT", 38, 2)
        with m.Else():
            self.place_text(m, char_code, cell_x, cell_y, "NAV", 39, 2)
        with m.If(tune_page):
            self.place_text(m, char_code, cell_x, cell_y, "DBG", 32, 2)
        with m.Elif(input_page):
            self.place_text(m, char_code, cell_x, cell_y, "IN", 33, 2)
        with m.Else():
            self.place_text(m, char_code, cell_x, cell_y, "BANK", 31, 2)
        with m.If(bank_page):
            self.place_text(m, char_code, cell_x, cell_y, "PRESET", 2, 6)
        preset_names = ["ALL", "ODD", "EVN", "LOW", "MID", "HI", "ZERO"]
        preset_label_xs = [9, 13, 18, 22, 27, 32, 36]
        for p, label in enumerate(preset_names):
            with m.If(bank_page):
                self.place_text(m, char_code, cell_x, cell_y, label, preset_label_xs[p], 7)
        with m.If(input_page):
            self.place_text(m, char_code, cell_x, cell_y, "INPUTS", 2, 11)
        with m.Else():
            self.place_text(m, char_code, cell_x, cell_y, "BANDS", 2, 11)
        with m.If(bank_page):
            self.place_text(m, char_code, cell_x, cell_y, "FRQ", 22, 11)
        band_freq_labels = ["29", "61", "115", "218", "411", "777", "1K5", "2K8", "5K2", "11K"]
        for n, label in enumerate(band_freq_labels):
            with m.If(bank_page & (self.selected == RezoHardwareUI.TARGET_BAND_BASE + n)):
                self.place_text(m, char_code, cell_x, cell_y, label, 28, 11)
        with m.If(input_page):
            self.place_text(m, char_code, cell_x, cell_y, "IN0", 2, 37)
            self.place_text(m, char_code, cell_x, cell_y, "IN1", 2, 39)
            self.place_text(m, char_code, cell_x, cell_y, "IN2", 2, 41)
            self.place_text(m, char_code, cell_x, cell_y, "IN3", 2, 43)
        with m.Elif(tune_page):
            self.place_text(m, char_code, cell_x, cell_y, "KNE", 2, 37)
            self.place_text(m, char_code, cell_x, cell_y, "CAP", 2, 39)
            self.place_text(m, char_code, cell_x, cell_y, "DMP", 2, 41)
        with m.Else():
            self.place_text(m, char_code, cell_x, cell_y, "DRY", 2, 37)
            self.place_text(m, char_code, cell_x, cell_y, "RES", 2, 39)
            self.place_text(m, char_code, cell_x, cell_y, "FB", 2, 41)

        char_code_q = Signal(unsigned(6))
        glyph_row_q = Signal(unsigned(3))
        glyph_col_q = Signal(unsigned(3))
        text_active_q = Signal()
        m.d.dvi += [
            char_code_q.eq(char_code),
            glyph_row_q.eq(glyph_row),
            glyph_col_q.eq(glyph_col),
            text_active_q.eq(active),
        ]

        row_bits = Signal(5)
        glyph_bit = Signal(unsigned(3))
        m.d.comb += row_bits.eq(0)
        m.d.comb += glyph_bit.eq(4 - glyph_col_q)
        with m.Switch(char_code_q):
            for ch in self.CHARS:
                code = self.code(ch)
                glyph = RezoBeamDisplay.FONT_5X7.get(ch, RezoBeamDisplay.FONT_5X7[" "])
                with m.Case(code):
                    with m.Switch(glyph_row_q):
                        for row, bits in enumerate(glyph):
                            with m.Case(row):
                                m.d.comb += row_bits.eq(bits)

        text = Signal()
        m.d.dvi += text.eq(
            text_active_q & (glyph_row_q < 7) & (glyph_col_q < 5) &
            row_bits.bit_select(glyph_bit, 1))

        border = active & self.outline(x, y, 12, 12, 708, 708, t=2)
        title_panel = active & self.rect(x, y, 20, 20, 700, 82)
        bands_panel = active & self.rect(x, y, 28, 190, 692, 574)
        meter_panel = active & (self.rect(x, y, 118, 584, 650, 608) |
                                self.rect(x, y, 118, 616, 650, 640) |
                                self.rect(x, y, 118, 648, 650, 672) |
                                (input_page & self.rect(x, y, 118, 680, 650, 704)))

        preset_chip = Signal()
        preset_select = Signal()
        preset_group_select = Signal()
        band_slot = Signal()
        band_zero = Signal()
        band_marker = Signal()
        band_fill = Signal()
        band_select = Signal()
        spectrum_rail = Signal()
        spectrum_tick = Signal()
        spectrum_selected = Signal()

        preset_chip_signals = []
        preset_select_signals = []
        band_slot_signals = []
        band_zero_signals = []
        band_marker_signals = []
        band_fill_signals = []
        band_select_signals = []
        spectrum_tick_signals = []
        spectrum_selected_signals = []

        for p in range(7):
            x0 = 136 + 72 * p
            preset_chip_signals.append(bank_page & self.rect(x, y, x0, 96, x0 + 64, 132))
            preset_select_signals.append(
                bank_page & self.editing & (self.selected == RezoHardwareUI.TARGET_PRESET) &
                (self.preset == p) &
                self.outline(x, y, x0 - 5, 91, x0 + 69, 137, t=3))

        for n in range(RezoCore.N_BANDS):
            x0 = 48 + 66 * n
            x1 = x0 + 42
            top_y = band_top_values[n]
            bottom_y = band_bottom_values[n]
            level_positive = band_positive_values[n]
            level_negative = band_negative_values[n]
            selected_band = self.selected == RezoHardwareUI.TARGET_BAND_BASE + n
            band_slot_signals.append(bank_page & self.rect(x, y, x0, 202, x1, 532))
            band_zero_signals.append(bank_page & self.rect(x, y, x0 - 5, zero_y - 1, x1 + 5, zero_y + 2))
            band_marker_signals.append(
                bank_page & ((level_positive & self.rect(x, y, x0, top_y - 2, x1, top_y + 3)) |
                             (level_negative & self.rect(x, y, x0, bottom_y - 2, x1, bottom_y + 3))))
            band_fill_signals.append(
                bank_page & ((level_positive & self.rect(x, y, x0, top_y, x1, zero_y)) |
                             (level_negative & self.rect(x, y, x0, zero_y, x1, bottom_y))))
            band_select_signals.append(
                bank_page & selected_band & self.outline(x, y, x0 - 7, 195, x1 + 7, 539, t=3))
            spectrum_x = x0 + 21
            spectrum_tick_signals.append(
                bank_page & self.rect(x, y, spectrum_x - 2, 548, spectrum_x + 3, 562))
            spectrum_selected_signals.append(
                bank_page & selected_band &
                self.rect(x, y, spectrum_x - 5, 542, spectrum_x + 6, 568))

        for target, signals in [
                (preset_chip, preset_chip_signals),
                (preset_select, preset_select_signals),
                (band_slot, band_slot_signals),
                (band_zero, band_zero_signals),
                (band_select, band_select_signals),
                (spectrum_tick, spectrum_tick_signals),
                (spectrum_selected, spectrum_selected_signals)]:
            expr = Const(0)
            for sig in signals:
                expr = expr | sig
            m.d.comb += target.eq(expr)

        m.d.comb += preset_group_select.eq(
            bank_page & (self.selected == RezoHardwareUI.TARGET_PRESET) & ~self.editing &
            self.outline(x, y, 130, 91, 638, 137, t=3))
        m.d.comb += spectrum_rail.eq(bank_page & self.rect(x, y, 48, 554, 674, 557))

        band_marker_qs = []
        for n, sig in enumerate(band_marker_signals):
            band_marker_q = Signal(name=f"tile_band_marker{n}_q")
            m.d.dvi += band_marker_q.eq(sig)
            band_marker_qs.append(band_marker_q)
        band_fill_qs = []
        for n, sig in enumerate(band_fill_signals):
            band_fill_q = Signal(name=f"tile_band_fill{n}_q")
            m.d.dvi += band_fill_q.eq(sig)
            band_fill_qs.append(band_fill_q)
        marker_expr = Const(0)
        for sig in band_marker_qs:
            marker_expr = marker_expr | sig
        fill_expr = Const(0)
        for sig in band_fill_qs:
            fill_expr = fill_expr | sig
        m.d.comb += [
            band_marker.eq(marker_expr),
            band_fill.eq(fill_expr),
        ]

        row0_value = Signal(unsigned(6))
        row1_value = Signal(unsigned(6))
        row2_value = Signal(unsigned(6))
        row3_value = Signal(unsigned(6))
        m.d.comb += [
            row0_value.eq(Mux(input_page, self.input_gains[0],
                              Mux(tune_page, self.limit_knee, self.dry))),
            row1_value.eq(Mux(input_page, self.input_gains[1],
                              Mux(tune_page, self.limit_cap, self.resonance))),
            row2_value.eq(Mux(input_page, self.input_gains[2],
                              Mux(tune_page, Cat(Const(0, 1), self.damp_mode, Const(0, 2)), self.feedback))),
            row3_value.eq(Mux(input_page, self.input_gains[3], 0)),
        ]
        dry_fill = self.rect(x, y, 124, 588, 124 + (row0_value << 4), 604)
        dry_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_DRY)) |
                      (input_page & (self.selected == RezoHardwareUI.TARGET_INPUT_BASE)) |
                      (tune_page & (self.selected == RezoHardwareUI.TARGET_LIMIT_KNEE))) & self.outline(
            x, y, 118, 584, 650, 608, t=3)
        res_fill = self.rect(x, y, 124, 620, 124 + (row1_value << 4), 636)
        res_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_RESONANCE)) |
                      (input_page & (self.selected == RezoHardwareUI.TARGET_INPUT_BASE + 1)) |
                      (tune_page & (self.selected == RezoHardwareUI.TARGET_LIMIT_CAP))) & self.outline(
            x, y, 118, 616, 650, 640, t=3)
        fb_fill = self.rect(x, y, 124, 652, 124 + (row2_value << 4), 668)
        fb_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_FEEDBACK)) |
                     (input_page & (self.selected == RezoHardwareUI.TARGET_INPUT_BASE + 2)) |
                     (tune_page & (self.selected == RezoHardwareUI.TARGET_DAMP))) & self.outline(
            x, y, 118, 648, 650, 672, t=3)
        row3_fill = input_page & self.rect(x, y, 124, 684, 124 + (row3_value << 4), 700)
        row3_select = input_page & (self.selected == RezoHardwareUI.TARGET_INPUT_BASE + 3) & self.outline(
            x, y, 118, 680, 650, 704, t=3)
        page_select = (self.selected == RezoHardwareUI.TARGET_PAGE) & self.outline(
            x, y, 20, 20, 700, 82, t=3)

        selected = active & (
            preset_select | preset_group_select | band_select |
            dry_select | res_select | fb_select | row3_select | page_select)

        selected_q = Signal()
        text_q = Signal()
        fill_q = Signal()
        line_q = Signal()
        panel_q = Signal()
        background_q = Signal()
        active_q = Signal()
        m.d.dvi += [
            selected_q.eq(selected),
            text_q.eq(text),
            fill_q.eq(band_fill | band_marker | spectrum_selected | dry_fill | res_fill | fb_fill | row3_fill),
            line_q.eq(band_zero | spectrum_rail | spectrum_tick | border),
            panel_q.eq(preset_chip | band_slot | meter_panel),
            background_q.eq(title_panel | bands_panel),
            active_q.eq(active),
        ]

        mono = Signal(8)
        with m.If(selected_q):
            m.d.comb += mono.eq(0xff)
        with m.Elif(text_q):
            m.d.comb += mono.eq(0xee)
        with m.Elif(fill_q):
            m.d.comb += mono.eq(0xb8)
        with m.Elif(line_q):
            m.d.comb += mono.eq(0x88)
        with m.Elif(panel_q):
            m.d.comb += mono.eq(0x32)
        with m.Elif(background_q):
            m.d.comb += mono.eq(0x14)
        with m.Elif(active_q):
            m.d.comb += mono.eq(0x00)
        with m.Else():
            m.d.comb += mono.eq(0)

        m.d.dvi += [
            self.r.eq(mono),
            self.g.eq(mono),
            self.b.eq(mono),
        ]

        return m


class RezoBeamTop(Elaboratable):
    """REZO without the SoC framebuffer path.

    This is a timing experiment for a REZO-specific HDMI path.  It keeps the
    audio filterbank in gateware and renders a small status view directly in
    the DVI pixel domain.
    """

    bitstream_help = BitstreamHelp(
        brief="REZO beam-raced filterbank timing prototype.",
        io_left=['audio in', 'resonance CV', 'morph CV', 'feedback CV',
                 'main out', 'odd bands', 'even bands', 'dry out'],
        io_right=['', '', 'video out required', '', '', '']
    )

    def __init__(self, clock_settings):
        assert clock_settings.modeline is not None
        self.clock_settings = clock_settings
        self.pmod0 = eurorack_pmod.EurorackPmod(self.clock_settings.audio_clock)

    def elaborate(self, platform):
        m = Module()

        if sim.is_hw(platform):
            m.submodules.car = platform.clock_domain_generator(self.clock_settings)
            m.submodules.reboot = reboot = RebootProvider(self.clock_settings.frequencies.sync)
            enc_pins = platform.request("encoder")
            m.submodules.btn = FFSynchronizer(
                enc_pins.s.i, reboot.button)
            m.submodules.pmod0_provider = pmod0_provider = eurorack_pmod.FFCProvider()
            wiring.connect(m, self.pmod0.pins, pmod0_provider.pins)
            m.d.comb += self.pmod0.codec_mute.eq(reboot.mute)
        else:
            m.submodules.car = sim.FakeTiliquaDomainGenerator()
            enc_pins = None

        m.submodules.pmod0 = pmod0 = self.pmod0
        m.submodules.rezo = rezo = RezoCore(fs=self.clock_settings.audio_clock.fs())
        m.submodules.ui = ui = RezoHardwareUI()
        m.submodules.audio_out_fifo = audio_out_fifo = dsp.SyncFIFOBuffered(
            shape=data.ArrayLayout(ASQ, 4), depth=4)

        if sim.is_hw(platform):
            m.d.comb += [
                ui.enc_i.eq(enc_pins.i.i),
                ui.enc_q.eq(enc_pins.q.i),
                ui.button.eq(enc_pins.s.i),
            ]
        else:
            m.d.comb += [
                ui.enc_i.eq(0),
                ui.enc_q.eq(0),
                ui.button.eq(0),
            ]

        m.d.comb += [
            rezo.dry.eq(ui.dry),
            rezo.resonance.eq(ui.resonance),
            rezo.feedback.eq(ui.feedback),
            rezo.limit_knee.eq(ui.limit_knee),
            rezo.limit_cap.eq(ui.limit_cap),
            rezo.damp_mode.eq(ui.damp_mode),
        ]
        for n in range(RezoCore.N_BANDS):
            m.d.comb += rezo.levels[n].eq(ui.levels[n])
        for n in range(4):
            m.d.comb += rezo.input_gains[n].eq(ui.input_gains[n])

        wiring.connect(m, pmod0.o_cal, rezo.i)
        wiring.connect(m, rezo.o, audio_out_fifo.i)
        wiring.connect(m, audio_out_fifo.o, pmod0.i_cal)

        m.submodules.dvi_tgen = dvi_tgen = dvi.DVITimingGen()
        for member in dvi_tgen.timings.signature.members:
            m.d.comb += getattr(dvi_tgen.timings, member).eq(
                getattr(self.clock_settings.modeline, member))

        m.submodules.display = display = DomainRenamer("dvi")(
            RezoTileDisplay(h_active=self.clock_settings.modeline.h_active))
        m.d.comb += [
            display.x.eq(dvi_tgen.x),
            display.y.eq(dvi_tgen.y),
            display.de.eq(dvi_tgen.ctrl.de),
        ]
        for n in range(RezoCore.N_BANDS):
            display_level = Signal(signed(6), name=f"display_level{n}")
            m.d.comb += display_level.eq(rezo.levels[n] >> 10)
            m.submodules += FFSynchronizer(
                i=display_level, o=display.levels[n], o_domain="dvi")
        display_dry = Signal(unsigned(6))
        display_resonance = Signal(unsigned(6))
        display_feedback = Signal(unsigned(6))
        display_limit_knee = Signal(unsigned(6))
        display_limit_cap = Signal(unsigned(6))
        display_input_gains = [Signal(unsigned(6), name=f"display_input_gain{n}")
                               for n in range(4)]
        m.d.comb += [
            display_dry.eq(rezo.dry >> 10),
            display_resonance.eq(rezo.resonance >> 10),
            display_feedback.eq(rezo.feedback >> 10),
            display_limit_knee.eq(rezo.limit_knee >> 10),
            display_limit_cap.eq(rezo.limit_cap >> 10),
        ]
        for n in range(4):
            m.d.comb += display_input_gains[n].eq(rezo.input_gains[n] >> 10)
        m.submodules += [
            FFSynchronizer(i=display_dry, o=display.dry, o_domain="dvi"),
            FFSynchronizer(i=display_resonance, o=display.resonance, o_domain="dvi"),
            FFSynchronizer(i=display_feedback, o=display.feedback, o_domain="dvi"),
            FFSynchronizer(i=display_limit_knee, o=display.limit_knee, o_domain="dvi"),
            FFSynchronizer(i=display_limit_cap, o=display.limit_cap, o_domain="dvi"),
            FFSynchronizer(i=ui.damp_mode, o=display.damp_mode, o_domain="dvi"),
            FFSynchronizer(i=ui.selected, o=display.selected, o_domain="dvi"),
            FFSynchronizer(i=ui.page, o=display.page, o_domain="dvi"),
            FFSynchronizer(i=ui.preset, o=display.preset, o_domain="dvi"),
            FFSynchronizer(i=ui.editing, o=display.editing, o_domain="dvi"),
        ]
        for n in range(4):
            m.submodules += FFSynchronizer(
                i=display_input_gains[n], o=display.input_gains[n], o_domain="dvi")

        if sim.is_hw(platform):
            m.submodules.dvi_gen = dvi_gen = dvi.DVIPHY()
            display_de0 = Signal()
            display_hsync0 = Signal()
            display_vsync0 = Signal()
            display_de1 = Signal()
            display_hsync1 = Signal()
            display_vsync1 = Signal()
            m.d.dvi += [
                display_de0.eq(dvi_tgen.ctrl_phy.de),
                display_hsync0.eq(dvi_tgen.ctrl_phy.hsync),
                display_vsync0.eq(dvi_tgen.ctrl_phy.vsync),
                display_de1.eq(display_de0),
                display_hsync1.eq(display_hsync0),
                display_vsync1.eq(display_vsync0),
            ]
            m.d.dvi += [
                dvi_gen.i.de.eq(display_de1),
                dvi_gen.i.hsync.eq(display_hsync1),
                dvi_gen.i.vsync.eq(display_vsync1),
                dvi_gen.i.r.eq(display.r),
                dvi_gen.i.g.eq(display.g),
                dvi_gen.i.b.eq(display.b),
            ]

        return m


if __name__ == "__main__":
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(RezoBeamTop, path=this_path)
