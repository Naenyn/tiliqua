# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""
REZO is a first pass at a Graphic Resonant Filterbank-inspired Tiliqua
bitstream.

    .. code-block:: text

        ┌────┐
        │in0 │◄─ configurable audio / CV
        │in1 │◄─ configurable audio / CV
        │in2 │◄─ configurable audio / CV
        │in3 │◄─ configurable audio / CV
        └────┘
        ┌────┐
        │out0│─► assignable G1..G4 / dry mix
        │out1│─► assignable G1..G4 / dry mix
        │out2│─► assignable G1..G4 / dry mix
        │out3│─► assignable G1..G4 / dry mix
        └────┘

This version keeps both sample-by-sample DSP and the beam-raced HDMI interface
in gateware.  The filterbank is mono for now: audio-role inputs are mixed into
ten fixed center-frequency band-pass filters.  CV-role inputs can modulate
resonance, feedback, or one of four assignable bank groups through an
attenuverter.

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
from amaranth.lib.memory import Memory
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
    INPUT_UNITY = 32768
    INPUT_MAX = 65535
    INPUT_UNITY_POS = 52428
    PARAM_SLEW_STEP = 64
    FILTER_PARAM_SLEW_STEP = 256
    INPUT_MODE_AUDIO = 0
    INPUT_MODE_CV = 1
    CV_TARGET_FEEDBACK = 0
    CV_TARGET_RESONANCE = 1
    CV_TARGET_GROUP_BASE = 2
    N_GROUPS = 4
    FILTER_LP = 0
    FILTER_HP = 1
    FILTER_BP = 2
    FILTER_NOTCH = 3
    FILTER_PASS_LEVEL = 8192

    # Erica-inspired nominal centers.  SVF cutoff is approximate because the
    # existing DSP block expects the Chamberlin integration coefficient rather
    # than a frequency in hertz.
    FREQS_HZ = [29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000]

    i: In(stream.Signature(data.ArrayLayout(ASQ, 4)))
    o: Out(stream.Signature(data.ArrayLayout(ASQ, 4)))

    def __init__(self, fs=48_000):
        # REZO's UI coefficients, limiter rails, and feedback tuning use the
        # native 16-bit Q1.15 codec scale.  Building it with another bitstream's
        # ASQ override changes the numeric meaning of every one of those
        # constants while still producing a syntactically valid bitstream.
        if ASQ.as_shape().width != 16 or ASQ.i_bits != 1:
            raise ValueError("REZO requires the default 16-bit Q1.15 ASQ format")
        self.fs = fs
        self.levels = [Signal(signed(16), init=0) for _ in range(self.N_BANDS)]
        self.dry = Signal(unsigned(16), init=0)
        self.resonance = Signal(unsigned(16), init=8192)
        self.feedback = Signal(unsigned(16), init=0)
        self.filter_mode = Signal(init=0)
        self.filter_type = Signal(unsigned(2), init=self.FILTER_LP)
        self.filter_cutoff = Signal(unsigned(16), init=16384)
        self.filter_slope = Signal(unsigned(16), init=16384)
        self.filter_width = Signal(unsigned(16), init=12288)
        self.limit_knee = Signal(unsigned(16), init=12288)
        self.limit_cap = Signal(unsigned(16), init=24576)
        self.damp_mode = Signal(unsigned(3), init=2)
        self.input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n == 0 else 0)
                            for n in range(4)]
        self.input_modes = [Signal(init=0 if n == 0 else 1, name=f"input_mode{n}")
                            for n in range(4)]
        self.cv_targets = [Signal(unsigned(3), init=(1, 1, 2, 0)[n], name=f"cv_target{n}")
                           for n in range(4)]
        self.cv_depths = [Signal(signed(16), init=0, name=f"cv_depth{n}")
                          for n in range(4)]
        self.bank_groups = [Signal(unsigned(4), init=1 << min(n // 3, 3), name=f"bank_group{n}")
                            for n in range(self.N_BANDS)]
        # Bits 0..3 select G1..G4; bit 4 adds the dry/input mix.  Groups are
        # masks so one group can feed several outputs without duplicating DSP.
        self.output_routes = [Signal(unsigned(5), init=route, name=f"output_route{n}")
                              for n, route in enumerate((0b01111, 0b00101,
                                                         0b01010, 0b10000))]
        self.effective_resonance = Signal(unsigned(16), init=8192)
        self.effective_feedback = Signal(unsigned(16), init=0)
        self.effective_filter_cutoff = Signal(unsigned(16), init=16384)
        self.effective_filter_slope = Signal(unsigned(16), init=16384)
        self.effective_filter_width = Signal(unsigned(16), init=12288)
        self.effective_groups = [Signal(signed(16), name=f"effective_group{n}")
                                 for n in range(self.N_GROUPS)]
        self.effective_levels = [Signal(signed(16), name=f"effective_level{n}")
                                 for n in range(self.N_BANDS)]
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
        smooth_input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n == 0 else 0,
                                     name=f"smooth_input_gain{n}")
                              for n in range(4)]
        smooth_cv_depths = [Signal(signed(16), init=0, name=f"smooth_cv_depth{n}")
                            for n in range(4)]
        level_diffs = [Signal(signed(17), name=f"level_diff{n}")
                       for n in range(self.N_BANDS)]
        dry_diff = Signal(signed(17))
        resonance_diff = Signal(signed(17))
        feedback_diff = Signal(signed(17))
        input_gain_diffs = [Signal(signed(17), name=f"input_gain_diff{n}")
                            for n in range(4)]
        input_gain_coeffs = [Signal(unsigned(16), name=f"input_gain_coeff{n}")
                             for n in range(4)]
        input_gain_above = [Signal(unsigned(16), name=f"input_gain_above{n}")
                            for n in range(4)]
        cv_depth_diffs = [Signal(signed(17), name=f"cv_depth_diff{n}")
                          for n in range(4)]
        feedback_gain = Signal(unsigned(16))
        sample_filter_mode = Signal(init=0)
        resonance_cv_term = Signal(signed(18))
        feedback_cv_term = Signal(signed(18))
        group_cv_terms = [Signal(signed(18), name=f"group_cv_term{n}")
                          for n in range(self.N_GROUPS)]
        effective_resonance_raw = Signal(signed(18))
        effective_feedback_raw = Signal(signed(18))
        effective_resonance = Signal(unsigned(16))
        effective_feedback = Signal(unsigned(16))
        m.d.comb += [
            dry_diff.eq(self.dry - smooth_dry),
            resonance_diff.eq(self.resonance - smooth_resonance),
            feedback_diff.eq(self.feedback - smooth_feedback),
            effective_resonance_raw.eq(smooth_resonance + resonance_cv_term),
            effective_feedback_raw.eq(smooth_feedback + feedback_cv_term),
            feedback_gain.eq(Mux(sample_filter_mode, 0,
                                 Mux(effective_feedback > 31744, 31744, effective_feedback))),
        ]
        with m.If(effective_resonance_raw < 0):
            m.d.comb += effective_resonance.eq(0)
        with m.Elif(effective_resonance_raw > 32768):
            m.d.comb += effective_resonance.eq(32768)
        with m.Else():
            m.d.comb += effective_resonance.eq(effective_resonance_raw)
        with m.If(effective_feedback_raw < 0):
            m.d.comb += effective_feedback.eq(0)
        with m.Elif(effective_feedback_raw > 32768):
            m.d.comb += effective_feedback.eq(32768)
        with m.Else():
            m.d.comb += effective_feedback.eq(effective_feedback_raw)
        for n in range(self.N_BANDS):
            m.d.comb += level_diffs[n].eq(self.levels[n] - smooth_levels[n])
        for n in range(4):
            m.d.comb += input_gain_diffs[n].eq(self.input_gains[n] - smooth_input_gains[n])
            m.d.comb += cv_depth_diffs[n].eq(self.cv_depths[n] - smooth_cv_depths[n])
            with m.If(smooth_input_gains[n] <= self.INPUT_UNITY_POS):
                m.d.comb += input_gain_coeffs[n].eq(
                    (smooth_input_gains[n] >> 1) + (smooth_input_gains[n] >> 3)
                )
            with m.Else():
                m.d.comb += [
                    input_gain_above[n].eq(smooth_input_gains[n] - self.INPUT_UNITY_POS),
                    input_gain_coeffs[n].eq(
                        self.INPUT_UNITY + (input_gain_above[n] << 1) + (input_gain_above[n] >> 1)
                    ),
                ]

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
                m.d.comb += feedback_damp.eq(effective_feedback >> 4)
            with m.Case(2):
                m.d.comb += feedback_damp.eq(effective_feedback >> 3)
            with m.Case(3):
                m.d.comb += feedback_damp.eq(effective_feedback >> 2)
            with m.Default():
                m.d.comb += feedback_damp.eq((effective_feedback >> 2) + (effective_feedback >> 3))
        m.d.comb += [
            res_ctl.eq(16384 - (effective_resonance >> 1)),
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
        filter_levels = [Signal(signed(16), init=self.FILTER_PASS_LEVEL,
                                name=f"filter_level{n}")
                         for n in range(self.N_BANDS)]
        filter_level_array = Array(filter_levels)
        active_levels = [Signal(signed(16), name=f"active_level{n}")
                         for n in range(self.N_BANDS)]
        levels = Array(active_levels)

        # FILTER mode is the existing parallel resonator bank under a generated
        # ten-point response curve.  One coefficient is refreshed per sync
        # clock, so cutoff animation costs no cycles in the audio FSM.
        filter_update_band = Signal(range(self.N_BANDS))
        filter_positions = Array(Const((n * 32768) // (self.N_BANDS - 1), 16)
                                 for n in range(self.N_BANDS))
        filter_pos = Signal(unsigned(16))
        filter_distance = Signal(signed(18))
        filter_distance_q = Signal(signed(18))
        filter_half_width_q = Signal(unsigned(17))
        filter_edge = Signal(signed(19))
        filter_edge_q = Signal(signed(19))
        filter_ramp = Signal(signed(20))
        filter_ramp_q = Signal(signed(20))
        filter_low_gain = Signal(signed(16))
        filter_profile_gain = Signal(signed(16))
        filter_band_q0 = Signal(range(self.N_BANDS))
        filter_band_q1 = Signal(range(self.N_BANDS))
        filter_band_q2 = Signal(range(self.N_BANDS))
        filter_type_q0 = Signal(unsigned(2))
        filter_type_q1 = Signal(unsigned(2))
        filter_type_q2 = Signal(unsigned(2))
        filter_slope_q0 = Signal(unsigned(2))
        filter_slope_q1 = Signal(unsigned(2))
        m.d.comb += [
            filter_pos.eq(filter_positions[filter_update_band]),
            filter_distance.eq(self.effective_filter_cutoff - filter_pos),
            filter_edge.eq(Mux((filter_type_q0 == self.FILTER_BP) |
                               (filter_type_q0 == self.FILTER_NOTCH),
                               filter_half_width_q -
                               Mux(filter_distance_q < 0,
                                   -filter_distance_q, filter_distance_q),
                               filter_distance_q)),
            filter_ramp.eq(4096),
            filter_low_gain.eq(0),
            filter_profile_gain.eq(filter_low_gain),
        ]
        # Four useful transition widths, selected by the upper slope bits.
        # The response remains intentionally stepped between the ten physical
        # resonators; slope controls how many neighboring bands crossfade.
        with m.Switch(filter_slope_q1):
            with m.Case(0):
                m.d.comb += filter_ramp.eq(4096 + (filter_edge_q >> 3))
            with m.Case(1):
                m.d.comb += filter_ramp.eq(4096 + (filter_edge_q >> 2))
            with m.Case(2):
                m.d.comb += filter_ramp.eq(4096 + (filter_edge_q >> 1))
            with m.Default():
                m.d.comb += filter_ramp.eq(4096 + filter_edge_q)
        with m.If(filter_ramp_q < 0):
            m.d.comb += filter_low_gain.eq(0)
        with m.Elif(filter_ramp_q > self.FILTER_PASS_LEVEL):
            m.d.comb += filter_low_gain.eq(self.FILTER_PASS_LEVEL)
        with m.Else():
            m.d.comb += filter_low_gain.eq(filter_ramp_q)
        with m.If((filter_type_q2 == self.FILTER_HP) |
                  (filter_type_q2 == self.FILTER_NOTCH)):
            m.d.comb += filter_profile_gain.eq(self.FILTER_PASS_LEVEL - filter_low_gain)
        with m.If(self.filter_mode):
            m.d.sync += [
                filter_distance_q.eq(filter_distance),
                filter_half_width_q.eq(1024 + (self.effective_filter_width >> 1)),
                filter_band_q0.eq(filter_update_band),
                filter_type_q0.eq(self.filter_type),
                filter_slope_q0.eq(self.effective_filter_slope[14:16]),
                filter_edge_q.eq(filter_edge),
                filter_band_q1.eq(filter_band_q0),
                filter_type_q1.eq(filter_type_q0),
                filter_slope_q1.eq(filter_slope_q0),
                filter_ramp_q.eq(filter_ramp),
                filter_band_q2.eq(filter_band_q1),
                filter_type_q2.eq(filter_type_q1),
                filter_level_array[filter_band_q2].eq(filter_profile_gain),
            ]
            with m.If(filter_update_band == self.N_BANDS - 1):
                m.d.sync += filter_update_band.eq(0)
            with m.Else():
                m.d.sync += filter_update_band.eq(filter_update_band + 1)

        state_shape = unsigned(5)
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
        state_cv_commit = 13
        state_feedback_limit_commit = 14
        state_cv_route_commit = 15
        state_output_route_commit = 16
        state_input_limit_commit = 17
        state_output_limit_commit = 18
        state_mac2_apply = 19
        state_input_gain_add = 20
        state_filter_params = 21
        state = Signal(state_shape, init=state_wait)
        band = Signal(range(self.N_BANDS))
        input_chan = Signal(range(4))
        cv_chan = Signal(range(4))
        cv_target_scan = Signal(range(6))
        output_chan = Signal(range(4))
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
        svf_product_raw = Signal(svf_storage)
        svf_product_q_raw = Signal(svf_storage)
        svf_product = svf_shape(svf_product_raw)
        svf_product_q = svf_shape(svf_product_q_raw)
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
            svf_product_raw.eq(
                mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            alp_next.eq(svf_product_q + alp_cur),
            ahp_next.eq(svf_product_q + hp_offset_q),
            abp_next.eq(svf_product_q + abp_cur),
        ]

        mix_shape = signed(ASQ.as_shape().width + 5)
        main_acc = Signal(mix_shape)
        output_acc = [Signal(mix_shape, name=f"output_acc{n}") for n in range(4)]
        output_acc_array = Array(output_acc)
        output_next = Signal(mix_shape)
        output_route_hit = Signal()
        term = Signal(mix_shape)
        term_q = Signal(mix_shape)
        level_cur = Signal(signed(16))
        level_cur_q = Signal(signed(16))
        level_with_cv = Signal(signed(18))
        group_cur = Signal(signed(20))
        group_update_band = Signal(range(self.N_BANDS))
        group_update_raw = Signal(signed(20))
        group_offsets = Array(Signal(signed(20), name=f"group_offset{n}")
                              for n in range(self.N_BANDS))
        band_sample = Signal(dsp.mac.SQNative)
        main_next = Signal(mix_shape)
        filtered_next = Signal(mix_shape)
        feedback_drive = Signal(mix_shape)
        feedback_limited = Signal(ASQ)
        feedback_soft = Signal(mix_shape)
        limit_knee_s = Signal(signed(17))
        limit_cap_s = Signal(signed(17))
        output_limited = Signal(ASQ)
        feedback_term = Signal(dsp.mac.SQNative)
        feedback_term_q = Signal(dsp.mac.SQNative)
        dry_gain_term = Signal(mix_shape)
        input_gain_product_q = Signal(mix_shape)
        input_mix_acc = Signal(mix_shape)
        input_mix_next = Signal(mix_shape)
        input_mix_sample = Signal(ASQ)
        input_mix_limited = Signal(ASQ)
        input_samples = [Signal(ASQ, name=f"input_sample{n}") for n in range(4)]
        cv_product = Signal(signed(18))
        cv_product_q = Signal(signed(18))
        cv_acc = Signal(signed(20))
        cv_acc_next = Signal(signed(20))
        bank_group_array = Array(self.bank_groups)
        output_route_array = Array(self.output_routes)
        input_mode_array = Array(self.input_modes)
        cv_target_array = Array(self.cv_targets)
        filter_cutoff_raw = Signal(signed(19))
        filter_slope_raw = Signal(signed(19))
        filter_width_raw = Signal(signed(19))
        filter_cutoff_target = Signal(unsigned(16))
        filter_slope_target = Signal(unsigned(16))
        filter_width_target = Signal(unsigned(16))
        filter_cutoff_target_q = Signal(unsigned(16), init=16384)
        filter_slope_target_q = Signal(unsigned(16), init=16384)
        filter_width_target_q = Signal(unsigned(16), init=12288)
        filter_cv = [Signal(signed(18), name=f"filter_cv{n}") for n in range(3)]
        m.d.comb += [
            filter_cutoff_raw.eq(self.filter_cutoff + filter_cv[0]),
            filter_slope_raw.eq(self.filter_slope + filter_cv[1]),
            filter_width_raw.eq(self.filter_width + filter_cv[2]),
        ]
        for n in range(3):
            raw_cv = input_samples[n + 1].as_value().as_signed()
            with m.If((raw_cv > -256) & (raw_cv < 256)):
                m.d.comb += filter_cv[n].eq(0)
            with m.Else():
                m.d.comb += filter_cv[n].eq(raw_cv)
        for raw, target in (
                (filter_cutoff_raw, filter_cutoff_target),
                (filter_slope_raw, filter_slope_target),
                (filter_width_raw, filter_width_target)):
            with m.If(raw < 0):
                m.d.comb += target.eq(0)
            with m.Elif(raw > 32768):
                m.d.comb += target.eq(32768)
            with m.Else():
                m.d.comb += target.eq(raw)
        m.d.comb += [
            level_with_cv.eq(levels[band] + group_cur),
            band_sample.eq(abp_cur.as_value().as_signed()),
            term.eq(mac_z.as_value().as_signed() >> (dsp.mac.SQNative.f_bits + 1)),
            feedback_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            dry_gain_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            input_mix_next.eq(input_mix_acc + input_gain_product_q),
            x_drive.eq((input_mix_sample >> 1) + feedback_term_q),
            limit_knee_s.eq(self.limit_knee),
            limit_cap_s.eq(self.limit_cap),
            main_next.eq(main_acc + term_q),
            filtered_next.eq(main_next - dry_sample.as_value().as_signed()),
            feedback_drive.eq(filtered_next),
            cv_product.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            cv_acc_next.eq(cv_acc),
        ]
        m.d.comb += [
            output_route_hit.eq(
                (output_route_array[output_chan][:4] & bank_group_array[band]) != 0),
            output_next.eq(Mux(output_route_hit,
                               output_acc_array[output_chan] + term_q,
                               output_acc_array[output_chan])),
        ]
        m.d.comb += [
            group_cur.eq(group_offsets[band]),
            group_update_raw.eq(
                Mux(bank_group_array[group_update_band][0], group_cv_terms[0], 0) +
                Mux(bank_group_array[group_update_band][1], group_cv_terms[1], 0) +
                Mux(bank_group_array[group_update_band][2], group_cv_terms[2], 0) +
                Mux(bank_group_array[group_update_band][3], group_cv_terms[3], 0)),
        ]
        m.d.sync += group_offsets[group_update_band].eq(group_update_raw)
        with m.If(group_update_band == self.N_BANDS - 1):
            m.d.sync += group_update_band.eq(0)
        with m.Else():
            m.d.sync += group_update_band.eq(group_update_band + 1)
        with m.If((input_mode_array[cv_chan] == self.INPUT_MODE_CV) &
                  (cv_target_array[cv_chan] == cv_target_scan)):
            m.d.comb += cv_acc_next.eq(cv_acc + cv_product_q)
        with m.If(level_with_cv > 16383):
            m.d.comb += level_cur.eq(16383)
        with m.Elif(level_with_cv < -16384):
            m.d.comb += level_cur.eq(-16384)
        with m.Else():
            m.d.comb += level_cur.eq(level_with_cv)
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

        limit_to_asq(output_acc_array[output_chan], output_limited)
        limit_to_asq(input_mix_acc, input_mix_limited)

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
        output_q = [Signal(ASQ, name=f"output_q{n}") for n in range(4)]
        output_q_array = Array(output_q)

        m.d.comb += [
            out_ready.eq(~out_valid | self.o.ready),
            self.i.ready.eq((state == state_wait) & out_ready),
        ]

        with m.If(self.o.ready):
            m.d.sync += out_valid.eq(0)

        with m.Switch(state):
            with m.Case(state_wait):
                with m.If(self.i.valid & self.i.ready):
                    for n in range(4):
                        m.d.sync += input_samples[n].eq(self.i.payload[n])
                    m.d.sync += sample_filter_mode.eq(self.filter_mode)
                    for n, diff in enumerate(level_diffs):
                        with m.If(self.filter_mode):
                            m.d.sync += active_levels[n].eq(filter_levels[n])
                        with m.Elif(diff > self.PARAM_SLEW_STEP):
                            m.d.sync += [
                                smooth_levels[n].eq(smooth_levels[n] + self.PARAM_SLEW_STEP),
                                active_levels[n].eq(smooth_levels[n] + self.PARAM_SLEW_STEP),
                            ]
                        with m.Elif(diff < -self.PARAM_SLEW_STEP):
                            m.d.sync += [
                                smooth_levels[n].eq(smooth_levels[n] - self.PARAM_SLEW_STEP),
                                active_levels[n].eq(smooth_levels[n] - self.PARAM_SLEW_STEP),
                            ]
                        with m.Else():
                            m.d.sync += [
                                smooth_levels[n].eq(self.levels[n]),
                                active_levels[n].eq(self.levels[n]),
                            ]
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
                    m.d.sync += [
                        self.effective_resonance.eq(effective_resonance),
                        self.effective_feedback.eq(effective_feedback),
                    ]
                    for n, diff in enumerate(input_gain_diffs):
                        with m.If(diff > self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_input_gains[n].eq(smooth_input_gains[n] + self.PARAM_SLEW_STEP)
                        with m.Elif(diff < -self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_input_gains[n].eq(smooth_input_gains[n] - self.PARAM_SLEW_STEP)
                        with m.Else():
                            m.d.sync += smooth_input_gains[n].eq(self.input_gains[n])
                    for n, diff in enumerate(cv_depth_diffs):
                        with m.If(diff > self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_cv_depths[n].eq(smooth_cv_depths[n] + self.PARAM_SLEW_STEP)
                        with m.Elif(diff < -self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_cv_depths[n].eq(smooth_cv_depths[n] - self.PARAM_SLEW_STEP)
                        with m.Else():
                            m.d.sync += smooth_cv_depths[n].eq(self.cv_depths[n])
                    m.d.sync += [
                        cv_chan.eq(0),
                        cv_target_scan.eq(0),
                        cv_acc.eq(0),
                    ]
                    with m.If(self.filter_mode):
                        m.d.sync += state.eq(state_filter_params)
                    with m.Else():
                        m.d.sync += [
                            mac_a_q.eq(self.i.payload[0]),
                            mac_b_q.eq(smooth_cv_depths[0]),
                            state.eq(state_cv_commit),
                        ]

            with m.Case(state_filter_params):
                for n in range(self.N_GROUPS):
                    m.d.sync += [group_cv_terms[n].eq(0), self.effective_groups[n].eq(0)]
                m.d.sync += [resonance_cv_term.eq(0), feedback_cv_term.eq(0)]
                m.d.sync += [
                    filter_cutoff_target_q.eq(filter_cutoff_target),
                    filter_slope_target_q.eq(filter_slope_target),
                    filter_width_target_q.eq(filter_width_target),
                ]
                for target, effective in (
                        (filter_cutoff_target_q, self.effective_filter_cutoff),
                        (filter_slope_target_q, self.effective_filter_slope),
                        (filter_width_target_q, self.effective_filter_width)):
                    with m.If(target > effective + self.FILTER_PARAM_SLEW_STEP):
                        m.d.sync += effective.eq(effective + self.FILTER_PARAM_SLEW_STEP)
                    with m.Elif(effective > target + self.FILTER_PARAM_SLEW_STEP):
                        m.d.sync += effective.eq(effective - self.FILTER_PARAM_SLEW_STEP)
                    with m.Else():
                        m.d.sync += effective.eq(target)
                m.d.sync += [
                    self.effective_feedback.eq(0),
                    input_mix_acc.eq(0),
                    input_chan.eq(0),
                    mac_a_q.eq(input_samples[0]),
                    mac_b_q.as_value().eq(self.INPUT_UNITY >> 1),
                    state.eq(state_input_gain_commit),
                ]

            with m.Case(state_cv_commit):
                m.d.sync += [
                    cv_product_q.eq(cv_product),
                    state.eq(state_cv_route_commit),
                ]

            with m.Case(state_cv_route_commit):
                with m.If(cv_chan != 3):
                    m.d.sync += [
                        cv_acc.eq(cv_acc_next),
                        cv_chan.eq(cv_chan + 1),
                        state.eq(state_cv_commit),
                    ]
                    with m.Switch(cv_chan):
                        with m.Case(0):
                            m.d.sync += [
                                mac_a_q.eq(input_samples[1]),
                                mac_b_q.eq(smooth_cv_depths[1]),
                            ]
                        with m.Case(1):
                            m.d.sync += [
                                mac_a_q.eq(input_samples[2]),
                                mac_b_q.eq(smooth_cv_depths[2]),
                            ]
                        with m.Default():
                            m.d.sync += [
                                mac_a_q.eq(input_samples[3]),
                                mac_b_q.eq(smooth_cv_depths[3]),
                            ]
                with m.Else():
                    with m.Switch(cv_target_scan):
                        with m.Case(self.CV_TARGET_FEEDBACK):
                            with m.If(cv_acc_next > 65535):
                                m.d.sync += feedback_cv_term.eq(65535)
                            with m.Elif(cv_acc_next < -65536):
                                m.d.sync += feedback_cv_term.eq(-65536)
                            with m.Else():
                                m.d.sync += feedback_cv_term.eq(cv_acc_next)
                        with m.Case(self.CV_TARGET_RESONANCE):
                            with m.If(cv_acc_next > 65535):
                                m.d.sync += resonance_cv_term.eq(65535)
                            with m.Elif(cv_acc_next < -65536):
                                m.d.sync += resonance_cv_term.eq(-65536)
                            with m.Else():
                                m.d.sync += resonance_cv_term.eq(cv_acc_next)
                        for n in range(self.N_GROUPS):
                            with m.Case(self.CV_TARGET_GROUP_BASE + n):
                                with m.If(cv_acc_next > 16383):
                                    m.d.sync += [
                                        group_cv_terms[n].eq(16383),
                                        self.effective_groups[n].eq(16383),
                                    ]
                                with m.Elif(cv_acc_next < -16384):
                                    m.d.sync += [
                                        group_cv_terms[n].eq(-16384),
                                        self.effective_groups[n].eq(-16384),
                                    ]
                                with m.Else():
                                    m.d.sync += [
                                        group_cv_terms[n].eq(cv_acc_next),
                                        self.effective_groups[n].eq(cv_acc_next),
                                    ]
                    with m.If(cv_target_scan != 5):
                        m.d.sync += [
                            cv_target_scan.eq(cv_target_scan + 1),
                            cv_chan.eq(0),
                            cv_acc.eq(0),
                            mac_a_q.eq(input_samples[0]),
                            mac_b_q.eq(smooth_cv_depths[0]),
                            state.eq(state_cv_commit),
                        ]
                    with m.Else():
                        m.d.sync += [
                            input_mix_acc.eq(0),
                            input_chan.eq(0),
                            mac_a_q.eq(input_samples[0]),
                            mac_b_q.eq(Mux(self.input_modes[0] == self.INPUT_MODE_AUDIO,
                                           input_gain_coeffs[0], 0)),
                            state.eq(state_input_gain_commit),
                        ]

            with m.Case(state_input_gain_commit):
                m.d.sync += [
                    input_gain_product_q.eq(dry_gain_term),
                    state.eq(state_input_gain_add),
                ]

            with m.Case(state_input_gain_add):
                with m.If(sample_filter_mode):
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        state.eq(state_input_limit_commit),
                    ]
                with m.Else():
                    with m.Switch(input_chan):
                      with m.Case(0):
                        m.d.sync += [
                            input_mix_acc.eq(input_mix_next),
                            input_chan.eq(1),
                            mac_a_q.eq(input_samples[1]),
                            mac_b_q.eq(Mux(self.input_modes[1] == self.INPUT_MODE_AUDIO,
                                           input_gain_coeffs[1], 0)),
                            state.eq(state_input_gain_commit),
                        ]
                      with m.Case(1):
                        m.d.sync += [
                            input_mix_acc.eq(input_mix_next),
                            input_chan.eq(2),
                            mac_a_q.eq(input_samples[2]),
                            mac_b_q.eq(Mux(self.input_modes[2] == self.INPUT_MODE_AUDIO,
                                           input_gain_coeffs[2], 0)),
                            state.eq(state_input_gain_commit),
                        ]
                      with m.Case(2):
                        m.d.sync += [
                            input_mix_acc.eq(input_mix_next),
                            input_chan.eq(3),
                            mac_a_q.eq(input_samples[3]),
                            mac_b_q.eq(Mux(self.input_modes[3] == self.INPUT_MODE_AUDIO,
                                           input_gain_coeffs[3], 0)),
                            state.eq(state_input_gain_commit),
                        ]
                      with m.Default():
                        m.d.sync += [
                            input_mix_acc.eq(input_mix_next),
                            state.eq(state_input_limit_commit),
                        ]

            with m.Case(state_input_limit_commit):
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
                    feedback_term_q.eq(feedback_term),
                    state.eq(state_feedback_limit_commit),
                ]

            with m.Case(state_feedback_limit_commit):
                m.d.sync += [
                    x.eq(x_limited),
                    mac_a_q.eq(input_mix_sample),
                    mac_b_q.eq(Mux(sample_filter_mode, 0, smooth_dry)),
                    state.eq(state_dry_gain_commit),
                ]

            with m.Case(state_dry_gain_commit):
                m.d.sync += [
                    dry_sample.eq(dry_gain_term),
                    main_acc.eq(dry_gain_term),
                    state.eq(state_mac0_setup),
                ]
                for n in range(4):
                    m.d.sync += output_acc[n].eq(
                        Mux(~sample_filter_mode & self.output_routes[n][4], dry_gain_term, 0))

            with m.Case(state_mac0_setup):
                m.d.sync += [
                    # Capture the dynamically selected band/group gain at the
                    # beginning of the section.  It is stable long before the
                    # mix MAC needs it, avoiding a ten-way mux and clamp on the
                    # synchronous critical path.
                    level_cur_q.eq(level_cur),
                    mac_a_q.eq(abp_cur),
                    mac_b_q.eq(cutoff_cur),
                    state.eq(state_mac0_commit),
                ]

            with m.Case(state_mac0_commit):
                m.d.sync += [
                    svf_product_q_raw.eq(svf_product_raw),
                    state.eq(state_mac1_setup),
                ]

            with m.Case(state_mac1_setup):
                m.d.sync += [
                    alp[band].eq(alp_next.saturate(svf_shape).as_value()),
                    mac_a_q.eq(abp_cur),
                    mac_b_q.eq(-resonance),
                    hp_offset_q.eq(x - alp_next),
                    state.eq(state_mac1_commit),
                ]

            with m.Case(state_mac1_commit):
                m.d.sync += [
                    svf_product_q_raw.eq(svf_product_raw),
                    state.eq(state_mac2_setup),
                ]

            with m.Case(state_mac2_setup):
                m.d.sync += [
                    ahp[band].eq(ahp_next.saturate(svf_shape).as_value()),
                    mac_a_q.eq(ahp_next),
                    mac_b_q.eq(cutoff_cur),
                    state.eq(state_mac2_commit),
                ]

            with m.Case(state_mac2_commit):
                m.d.sync += [
                    svf_product_q_raw.eq(svf_product_raw),
                    state.eq(state_mac2_apply),
                ]

            with m.Case(state_mac2_apply):
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
                    mac_b_q.eq(level_cur_q),
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
                    output_chan.eq(0),
                    state.eq(state_output_route_commit),
                ]
                for n in range(self.N_BANDS):
                    with m.If(band == n):
                        m.d.sync += self.effective_levels[n].eq(level_cur)

            with m.Case(state_output_route_commit):
                m.d.sync += [
                    output_acc_array[output_chan].eq(output_next),
                    state.eq(state_output_limit_commit),
                ]

            with m.Case(state_output_limit_commit):
                with m.If(band == self.N_BANDS - 1):
                    m.d.sync += output_q_array[output_chan].eq(output_limited)
                with m.If(output_chan != 3):
                    m.d.sync += [
                        output_chan.eq(output_chan + 1),
                        state.eq(state_output_route_commit),
                    ]
                with m.Elif(band == self.N_BANDS - 1):
                    m.d.sync += [
                        feedback_sample.eq(feedback_limited),
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
        ]
        for n in range(4):
            m.d.comb += self.o.payload[n].eq(output_q[n])
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
        io_left=['audio / CV input', 'audio / CV input',
                 'audio / CV input', 'audio / CV input',
                 'assignable out', 'assignable out',
                 'assignable out', 'assignable out'],
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

    PRESET_LEVEL = 8192
    INPUT_UNITY = RezoCore.INPUT_UNITY
    INPUT_MAX = RezoCore.INPUT_MAX
    INPUT_UNITY_POS = RezoCore.INPUT_UNITY_POS
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
    TARGET_GROUP_BASE = RezoCore.N_BANDS + 20
    TARGET_OUTPUT_BASE = RezoCore.N_BANDS + 30
    TARGET_MODE = RezoCore.N_BANDS + 34
    TARGET_FILTER_TYPE = RezoCore.N_BANDS + 35
    TARGET_FILTER_CUTOFF = RezoCore.N_BANDS + 36
    TARGET_FILTER_SLOPE = RezoCore.N_BANDS + 37
    TARGET_FILTER_WIDTH = RezoCore.N_BANDS + 38
    N_TARGETS = RezoCore.N_BANDS + 39

    def __init__(self):
        super().__init__({
            "enc_i": In(1),
            "enc_q": In(1),
            "button": In(1),
            "levels": Out(data.ArrayLayout(signed(16), RezoCore.N_BANDS)),
            "dry": Out(unsigned(16)),
            "resonance": Out(unsigned(16)),
            "feedback": Out(unsigned(16)),
            "filter_mode": Out(1),
            "filter_type": Out(unsigned(2)),
            "filter_cutoff": Out(unsigned(16)),
            "filter_slope": Out(unsigned(16)),
            "filter_width": Out(unsigned(16)),
            "limit_knee": Out(unsigned(16)),
            "limit_cap": Out(unsigned(16)),
            "damp_mode": Out(unsigned(3)),
            "input_gains": Out(data.ArrayLayout(unsigned(16), 4)),
            "input_modes": Out(data.ArrayLayout(unsigned(1), 4)),
            "cv_targets": Out(data.ArrayLayout(unsigned(3), 4)),
            "cv_depths": Out(data.ArrayLayout(signed(16), 4)),
            "bank_groups": Out(data.ArrayLayout(unsigned(4), RezoCore.N_BANDS)),
            "output_routes": Out(data.ArrayLayout(unsigned(5), 4)),
            "selected": Out(unsigned(6)),
            "page": Out(unsigned(3)),
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
    def gray_decode(value):
        decoded = 0
        while value:
            decoded ^= value
            value >>= 1
        return decoded

    @staticmethod
    def apply_preset(m, preset, levels):
        with m.Switch(preset):
            with m.Case(0):  # all bands
                for level in levels:
                    m.d.sync += level.eq(RezoHardwareUI.PRESET_LEVEL)
            with m.Case(1):  # odd bands
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(RezoHardwareUI.PRESET_LEVEL if n & 1 else 0)
            with m.Case(2):  # even bands
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(0 if n & 1 else RezoHardwareUI.PRESET_LEVEL)
            with m.Case(3):  # lows
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(RezoHardwareUI.PRESET_LEVEL if n < 4 else 0)
            with m.Case(4):  # mids
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(RezoHardwareUI.PRESET_LEVEL if 3 <= n <= 6 else 0)
            with m.Case(5):  # highs
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(RezoHardwareUI.PRESET_LEVEL if n >= 6 else 0)
            with m.Case(6):  # zero
                for level in levels:
                    m.d.sync += level.eq(0)

    def elaborate(self, platform):
        m = Module()

        levels = [Signal(signed(16), init=self.PRESET_LEVEL, name=f"ui_level{n}")
                  for n in range(RezoCore.N_BANDS)]
        dry = Signal(unsigned(16), init=0)
        resonance = Signal(unsigned(16), init=8192)
        feedback = Signal(unsigned(16), init=0)
        filter_mode = Signal(init=0)
        filter_type = Signal(unsigned(2), init=RezoCore.FILTER_LP)
        filter_cutoff = Signal(unsigned(16), init=16384)
        filter_slope = Signal(unsigned(16), init=16384)
        filter_width = Signal(unsigned(16), init=12288)
        limit_knee = Signal(unsigned(16), init=12288)
        limit_cap = Signal(unsigned(16), init=24576)
        damp_mode = Signal(unsigned(3), init=2)
        input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n == 0 else 0,
                              name=f"ui_input_gain{n}")
                       for n in range(4)]
        input_modes = [Signal(init=0 if n == 0 else 1, name=f"ui_input_mode{n}")
                       for n in range(4)]
        cv_targets = [Signal(unsigned(3), init=(1, 1, 2, 0)[n], name=f"ui_cv_target{n}")
                      for n in range(4)]
        cv_depths = [Signal(signed(16), init=0, name=f"ui_cv_depth{n}")
                     for n in range(4)]
        initial_bank_masks = [1 << min(n // 3, 3) for n in range(RezoCore.N_BANDS)]
        bank_group_indices = [Signal(unsigned(4), init=self.gray_decode(mask),
                                     name=f"ui_bank_group_index{n}")
                              for n, mask in enumerate(initial_bank_masks)]
        bank_groups = [Signal(unsigned(4), name=f"ui_bank_group{n}")
                       for n in range(RezoCore.N_BANDS)]
        initial_output_masks = (0b01111, 0b00101, 0b01010, 0b10000)
        output_route_indices = [Signal(unsigned(5), init=self.gray_decode(route),
                                       name=f"ui_output_route_index{n}")
                                for n, route in enumerate(initial_output_masks)]
        output_routes = [Signal(unsigned(5), name=f"ui_output_route{n}")
                         for n in range(4)]
        filter_output_route_indices = [Signal(unsigned(4), init=self.gray_decode(route),
                                              name=f"ui_filter_output_route_index{n}")
                                       for n, route in enumerate((0b1111, 0b0101,
                                                                  0b1010, 0b0000))]
        filter_output_routes = [Signal(unsigned(4), name=f"ui_filter_output_route{n}")
                                for n in range(4)]
        for n in range(RezoCore.N_BANDS):
            m.d.comb += bank_groups[n].eq(
                bank_group_indices[n] ^ (bank_group_indices[n] >> 1))
        for n in range(4):
            m.d.comb += filter_output_routes[n].eq(
                filter_output_route_indices[n] ^ (filter_output_route_indices[n] >> 1))
            m.d.comb += output_routes[n].eq(
                Mux(filter_mode, Cat(filter_output_routes[n], Const(0, 1)),
                    output_route_indices[n] ^ (output_route_indices[n] >> 1)))
        selected = Signal(range(self.N_TARGETS), init=self.TARGET_PAGE)
        page = Signal(unsigned(3), init=0)
        preset = Signal(range(7), init=0)
        next_preset = Signal(range(7))
        next_selected = Signal(range(self.N_TARGETS))
        bank_target_visible = Signal()
        tune_target_visible = Signal()
        input_target_visible = Signal()
        group_target_visible = Signal()
        output_target_visible = Signal()
        filter_target_visible = Signal()
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
            bank_target_visible.eq((selected <= self.TARGET_FEEDBACK) |
                                   (selected == self.TARGET_MODE)),
            tune_target_visible.eq((selected == self.TARGET_PAGE) |
                                   ((selected >= self.TARGET_LIMIT_KNEE) &
                                    (selected <= self.TARGET_DAMP))),
            input_target_visible.eq((selected == self.TARGET_PAGE) |
                                    ((selected >= self.TARGET_INPUT_BASE) &
                                     (selected < self.TARGET_INPUT_BASE + 12))),
            group_target_visible.eq((selected == self.TARGET_PAGE) |
                                    ((selected >= self.TARGET_GROUP_BASE) &
                                     (selected < self.TARGET_GROUP_BASE + RezoCore.N_BANDS))),
            output_target_visible.eq((selected == self.TARGET_PAGE) |
                                     ((selected >= self.TARGET_OUTPUT_BASE) &
                                      (selected < self.TARGET_OUTPUT_BASE + 4))),
            filter_target_visible.eq((selected == self.TARGET_PAGE) |
                                     (selected == self.TARGET_MODE) |
                                     ((selected >= self.TARGET_FILTER_TYPE) &
                                      (selected <= self.TARGET_FILTER_WIDTH)) |
                                     (selected == self.TARGET_RESONANCE)),
            next_selected.eq(selected),
        ]
        with m.If(page == 0):
            with m.If(filter_mode):
                with m.If(edit_direction):
                    with m.If(~filter_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Elif(selected == self.TARGET_MODE):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_TYPE)
                    with m.Elif(selected == self.TARGET_FILTER_TYPE):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_CUTOFF)
                    with m.Elif(selected == self.TARGET_FILTER_CUTOFF):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_SLOPE)
                    with m.Elif(selected == self.TARGET_FILTER_SLOPE):
                        m.d.comb += next_selected.eq(
                            Mux(filter_type >= RezoCore.FILTER_BP,
                                self.TARGET_FILTER_WIDTH, self.TARGET_RESONANCE))
                    with m.Elif(selected == self.TARGET_FILTER_WIDTH):
                        m.d.comb += next_selected.eq(self.TARGET_RESONANCE)
                    with m.Else():
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    with m.If(~filter_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_RESONANCE)
                    with m.Elif(selected == self.TARGET_RESONANCE):
                        m.d.comb += next_selected.eq(
                            Mux(filter_type >= RezoCore.FILTER_BP,
                                self.TARGET_FILTER_WIDTH, self.TARGET_FILTER_SLOPE))
                    with m.Elif(selected == self.TARGET_FILTER_WIDTH):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_SLOPE)
                    with m.Elif(selected == self.TARGET_FILTER_SLOPE):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_CUTOFF)
                    with m.Elif(selected == self.TARGET_FILTER_CUTOFF):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_TYPE)
                    with m.Elif(selected == self.TARGET_FILTER_TYPE):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Else():
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
            with m.Else():
                with m.If(edit_direction):
                    with m.If(~bank_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Elif(selected == self.TARGET_MODE):
                        m.d.comb += next_selected.eq(self.TARGET_PRESET)
                    with m.Elif(selected == self.TARGET_FEEDBACK):
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
                    with m.Else():
                        m.d.comb += next_selected.eq(selected + 1)
                with m.Else():
                    with m.If(~bank_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_FEEDBACK)
                    with m.Elif(selected == self.TARGET_PRESET):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Elif(selected == self.TARGET_MODE):
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
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
        with m.Elif(page == 2):
            with m.If(edit_direction):
                with m.If(~input_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_INPUT_BASE)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_INPUT_BASE)
                for n in range(4):
                    target_base = self.TARGET_INPUT_BASE + n * 3
                    next_input = self.TARGET_PAGE if n == 3 else target_base + 3
                    with m.Elif(selected == target_base):
                        m.d.comb += next_selected.eq(target_base + 1)
                    with m.Elif(selected == target_base + 1):
                        m.d.comb += next_selected.eq(
                            Mux(input_modes[n] == RezoCore.INPUT_MODE_CV,
                                target_base + 2, next_input))
                    with m.Elif(selected == target_base + 2):
                        m.d.comb += next_selected.eq(next_input)
            with m.Else():
                with m.If(~input_target_visible):
                    m.d.comb += next_selected.eq(
                        Mux(input_modes[3] == RezoCore.INPUT_MODE_CV,
                            self.TARGET_INPUT_BASE + 11,
                            self.TARGET_INPUT_BASE + 10))
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(
                        Mux(input_modes[3] == RezoCore.INPUT_MODE_CV,
                            self.TARGET_INPUT_BASE + 11,
                            self.TARGET_INPUT_BASE + 10))
                for n in range(4):
                    target_base = self.TARGET_INPUT_BASE + n * 3
                    if n == 0:
                        previous_input = Const(self.TARGET_PAGE)
                    else:
                        previous_base = self.TARGET_INPUT_BASE + (n - 1) * 3
                        previous_input = Mux(input_modes[n - 1] == RezoCore.INPUT_MODE_CV,
                                             previous_base + 2, previous_base + 1)
                    with m.Elif(selected == target_base):
                        m.d.comb += next_selected.eq(previous_input)
                    with m.Elif(selected == target_base + 1):
                        m.d.comb += next_selected.eq(target_base)
                    with m.Elif(selected == target_base + 2):
                        m.d.comb += next_selected.eq(target_base + 1)
        with m.Elif(page == 3):
            with m.If(edit_direction):
                with m.If(~group_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_GROUP_BASE)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_GROUP_BASE)
                with m.Elif(selected == self.TARGET_GROUP_BASE + RezoCore.N_BANDS - 1):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~group_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_GROUP_BASE + RezoCore.N_BANDS - 1)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_GROUP_BASE + RezoCore.N_BANDS - 1)
                with m.Elif(selected == self.TARGET_GROUP_BASE):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.Else():
            with m.If(edit_direction):
                with m.If(~output_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_BASE)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_BASE)
                with m.Elif(selected == self.TARGET_OUTPUT_BASE + 3):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~output_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_BASE + 3)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_BASE + 3)
                with m.Elif(selected == self.TARGET_OUTPUT_BASE):
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
                    with m.If(filter_mode):
                        with m.If(edit_direction):
                            with m.Switch(page):
                                with m.Case(0): m.d.sync += page.eq(1)
                                with m.Case(1): m.d.sync += page.eq(3)
                                with m.Case(3): m.d.sync += page.eq(4)
                                with m.Default(): m.d.sync += page.eq(0)
                        with m.Else():
                            with m.Switch(page):
                                with m.Case(0): m.d.sync += page.eq(4)
                                with m.Case(4): m.d.sync += page.eq(3)
                                with m.Case(3): m.d.sync += page.eq(1)
                                with m.Default(): m.d.sync += page.eq(0)
                    with m.Else():
                        with m.If(edit_direction):
                            m.d.sync += page.eq(Mux(page == 4, 0, page + 1))
                        with m.Else():
                            m.d.sync += page.eq(Mux(page == 0, 4, page - 1))
                with m.Elif(selected == self.TARGET_MODE):
                    m.d.sync += filter_mode.eq(~filter_mode)
                with m.Elif(selected == self.TARGET_FILTER_TYPE):
                    with m.If(edit_direction):
                        m.d.sync += filter_type.eq(filter_type + 1)
                    with m.Else():
                        m.d.sync += filter_type.eq(filter_type - 1)
                with m.Elif(selected == self.TARGET_FILTER_CUTOFF):
                    with m.If(edit_direction):
                        self.clamp_add(m, filter_cutoff, step_amount, 0, 32768)
                    with m.Else():
                        self.clamp_add(m, filter_cutoff, -step_amount, 0, 32768)
                with m.Elif(selected == self.TARGET_FILTER_SLOPE):
                    with m.If(edit_direction):
                        self.clamp_add(m, filter_slope, step_amount, 0, 32768)
                    with m.Else():
                        self.clamp_add(m, filter_slope, -step_amount, 0, 32768)
                with m.Elif(selected == self.TARGET_FILTER_WIDTH):
                    with m.If(edit_direction):
                        self.clamp_add(m, filter_width, step_amount, 0, 32768)
                    with m.Else():
                        self.clamp_add(m, filter_width, -step_amount, 0, 32768)
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
                for n in range(4):
                    with m.Elif(selected == self.TARGET_INPUT_BASE + n * 3):
                        m.d.sync += input_modes[n].eq(~input_modes[n])
                    with m.Elif(selected == self.TARGET_INPUT_BASE + n * 3 + 1):
                        with m.If(input_modes[n] == RezoCore.INPUT_MODE_AUDIO):
                            with m.If(edit_direction):
                                self.clamp_add(m, input_gains[n], step_amount, 0, self.INPUT_MAX)
                            with m.Else():
                                self.clamp_add(m, input_gains[n], -step_amount, 0, self.INPUT_MAX)
                        with m.Else():
                            with m.If(edit_direction):
                                m.d.sync += cv_targets[n].eq(Mux(cv_targets[n] == 5, 0,
                                                                 cv_targets[n] + 1))
                            with m.Else():
                                m.d.sync += cv_targets[n].eq(Mux(cv_targets[n] == 0, 5,
                                                                 cv_targets[n] - 1))
                    with m.Elif(selected == self.TARGET_INPUT_BASE + n * 3 + 2):
                        with m.If(edit_direction):
                            self.clamp_add(m, cv_depths[n], step_amount, -32768, 32767)
                        with m.Else():
                            self.clamp_add(m, cv_depths[n], -step_amount, -32768, 32767)
                for n, bank_group_index in enumerate(bank_group_indices):
                    with m.Elif(selected == self.TARGET_GROUP_BASE + n):
                        with m.If(edit_direction):
                            m.d.sync += bank_group_index.eq(bank_group_index + 1)
                        with m.Else():
                            m.d.sync += bank_group_index.eq(bank_group_index - 1)
                for n, output_route_index in enumerate(output_route_indices):
                    with m.Elif(selected == self.TARGET_OUTPUT_BASE + n):
                        with m.If(filter_mode):
                            with m.If(edit_direction):
                                m.d.sync += filter_output_route_indices[n].eq(
                                    filter_output_route_indices[n] + 1)
                            with m.Else():
                                m.d.sync += filter_output_route_indices[n].eq(
                                    filter_output_route_indices[n] - 1)
                        with m.Else():
                            with m.If(edit_direction):
                                m.d.sync += output_route_index.eq(output_route_index + 1)
                            with m.Else():
                                m.d.sync += output_route_index.eq(output_route_index - 1)
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
        for n in range(4):
            m.d.comb += [
                self.input_modes[n].eq(input_modes[n]),
                self.cv_targets[n].eq(cv_targets[n]),
                self.cv_depths[n].eq(cv_depths[n]),
            ]
        for n, bank_group in enumerate(bank_groups):
            m.d.comb += self.bank_groups[n].eq(bank_group)
        for n, output_route in enumerate(output_routes):
            m.d.comb += self.output_routes[n].eq(output_route)
        m.d.comb += [
            self.dry.eq(dry),
            self.resonance.eq(resonance),
            self.feedback.eq(feedback),
            self.filter_mode.eq(filter_mode),
            self.filter_type.eq(filter_type),
            self.filter_cutoff.eq(filter_cutoff),
            self.filter_slope.eq(filter_slope),
            self.filter_width.eq(filter_width),
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
            "effective_levels": In(data.ArrayLayout(signed(6), RezoCore.N_BANDS)),
            "dry": In(unsigned(6)),
            "resonance": In(unsigned(6)),
            "feedback": In(unsigned(6)),
            "effective_resonance": In(unsigned(6)),
            "effective_feedback": In(unsigned(6)),
            "filter_mode": In(1),
            "filter_type": In(unsigned(2)),
            "filter_cutoff": In(unsigned(6)),
            "filter_slope": In(unsigned(6)),
            "filter_width": In(unsigned(6)),
            "effective_filter_cutoff": In(unsigned(6)),
            "effective_filter_slope": In(unsigned(6)),
            "effective_filter_width": In(unsigned(6)),
            "limit_knee": In(unsigned(6)),
            "limit_cap": In(unsigned(6)),
            "damp_mode": In(unsigned(3)),
            "input_gains": In(data.ArrayLayout(unsigned(6), 4)),
            "cv_mods": In(data.ArrayLayout(unsigned(6), 2)),
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
            "effective_levels": In(data.ArrayLayout(signed(6), RezoCore.N_BANDS)),
            "dry": In(unsigned(6)),
            "resonance": In(unsigned(6)),
            "feedback": In(unsigned(6)),
            "effective_resonance": In(unsigned(6)),
            "effective_feedback": In(unsigned(6)),
            "filter_mode": In(1),
            "filter_type": In(unsigned(2)),
            "filter_cutoff": In(unsigned(6)),
            "filter_slope": In(unsigned(6)),
            "filter_width": In(unsigned(6)),
            "effective_filter_cutoff": In(unsigned(6)),
            "effective_filter_slope": In(unsigned(6)),
            "effective_filter_width": In(unsigned(6)),
            "limit_knee": In(unsigned(6)),
            "limit_cap": In(unsigned(6)),
            "damp_mode": In(unsigned(3)),
            "input_gains": In(data.ArrayLayout(unsigned(6), 4)),
            "input_modes": In(data.ArrayLayout(unsigned(1), 4)),
            "cv_targets": In(data.ArrayLayout(unsigned(3), 4)),
            "cv_depths": In(data.ArrayLayout(signed(6), 4)),
            "bank_groups": In(data.ArrayLayout(unsigned(4), RezoCore.N_BANDS)),
            "output_routes": In(data.ArrayLayout(unsigned(5), 4)),
            "selected": In(unsigned(6)),
            "page": In(unsigned(3)),
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
        band_base_marker_values = [Signal(signed(12), init=zero_y,
                                          name=f"tile_band_base_marker{n}")
                                   for n in range(RezoCore.N_BANDS)]
        band_positive_values = [Signal(name=f"tile_band_positive{n}")
                                for n in range(RezoCore.N_BANDS)]
        band_negative_values = [Signal(name=f"tile_band_negative{n}")
                                for n in range(RezoCore.N_BANDS)]

        for n in range(RezoCore.N_BANDS):
            level = self.effective_levels[n]
            base_level = self.levels[n]
            mag = Signal(unsigned(6), name=f"tile_level_mag{n}")
            base_mag = Signal(unsigned(6), name=f"tile_base_level_mag{n}")
            height = Signal(signed(12), name=f"tile_level_height{n}")
            base_height = Signal(signed(12), name=f"tile_base_level_height{n}")
            filter_height = Signal(signed(12), name=f"tile_filter_height{n}")
            m.d.comb += [
                mag.eq(Mux(level < 0, -level, level)),
                base_mag.eq(Mux(base_level < 0, -base_level, base_level)),
                height.eq((mag << 3) + (mag << 1) + Mux(level < 0, mag >> 2, mag)),
                base_height.eq((base_mag << 3) + (base_mag << 1) +
                               Mux(base_level < 0, base_mag >> 2, base_mag)),
                filter_height.eq((mag << 5) + (mag << 3) + mag),
            ]
            m.d.dvi += [
                band_top_values[n].eq(Mux(self.filter_mode,
                                          532 - filter_height, zero_y - height)),
                band_bottom_values[n].eq(zero_y + height),
                band_base_marker_values[n].eq(
                    Mux(base_level < 0, zero_y + base_height, zero_y - base_height)),
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

        home_page = Signal()
        bank_page = Signal()
        filter_page = Signal()
        tune_page = Signal()
        input_page = Signal()
        group_page = Signal()
        output_page = Signal()
        m.d.comb += [
            home_page.eq(self.page == 0),
            bank_page.eq((self.page == 0) & ~self.filter_mode),
            filter_page.eq((self.page == 0) & self.filter_mode),
            tune_page.eq(self.page == 1),
            input_page.eq(self.page == 2),
            group_page.eq(self.page == 3),
            output_page.eq(self.page == 4),
        ]
        page_cells = 45 * 45
        text_init = [0] * (6 * page_cells)

        def put(page, text_value, x0, y0):
            for offset, ch in enumerate(text_value):
                if 0 <= x0 + offset < 45 and 0 <= y0 < 45:
                    text_init[page * page_cells + y0 * 45 + x0 + offset] = self.code(ch)

        page_titles = ("BANK", "DBG", "IN", "GROUP", "OUT", "FILTER")
        for page_number, title in enumerate(page_titles):
            put(page_number, "REZO", 2, 2)
            put(page_number, title, 31 if page_number == 0 else 30, 2)
        put(0, "PRESET", 2, 6)
        put(0, "BANDS", 2, 11)
        put(0, "FRQ", 22, 11)
        put(0, "DRY", 2, 37)
        put(0, "RES", 2, 39)
        put(0, "FB", 2, 41)
        put(1, "BANDS", 2, 11)
        put(1, "KNE", 2, 37)
        put(1, "CAP", 2, 39)
        put(1, "DMP", 2, 41)
        put(2, "INPUT ROUTING", 2, 11)
        for n in range(4):
            row = 13 + n * 6
            put(2, f"IN{n}", 3, row)
            put(2, "MODE", 8, row)
            put(2, "VALUE", 8, row + 2)
            put(2, "DEPTH", 8, row + 4)
        put(3, "BANK GROUPS", 2, 11)
        for group in range(4):
            put(3, f"G{group + 1}", 3, 19 + group * 4)
        put(4, "OUTPUT ROUTING", 2, 11)
        for source, label in enumerate(("G1", "G2", "G3", "G4", "DRY")):
            put(4, label, 13 + source * 6, 17)
        for n in range(4):
            put(4, f"OUT{n}", 3, 21 + n * 5)
        put(5, "TYPE", 2, 6)
        put(5, "BANDS", 2, 11)
        put(5, "FREQ", 2, 36)
        put(5, "SLP", 2, 38)
        put(5, "WID", 2, 40)
        put(5, "RES", 2, 42)

        m.submodules.text_mem = text_mem = Memory(
            shape=unsigned(6), depth=len(text_init), init=text_init)
        text_rport = text_mem.read_port(domain="dvi")
        text_wport = text_mem.write_port(domain="sync")
        page_offsets = Array(Const(page * page_cells, unsigned(14)) for page in range(6))
        text_address = Signal(unsigned(14))
        text_page_q = Signal(unsigned(3))
        m.d.dvi += text_page_q.eq(
            Mux((self.page == 0) & self.filter_mode, 5, self.page))
        m.d.comb += [
            text_address.eq(page_offsets[text_page_q] + cell_y * 45 + cell_x),
            text_rport.addr.eq(text_address),
        ]

        # Dynamic labels are written into the tile RAM in short bursts at
        # 15 Hz. HDMI therefore sees only a BRAM read, never the control muxes.
        page_sync = Signal.like(self.page)
        preset_sync = Signal.like(self.preset)
        selected_sync = Signal.like(self.selected)
        editing_sync = Signal()
        filter_mode_sync = Signal()
        filter_type_sync = Signal(unsigned(2))
        input_modes_sync = [Signal(name=f"text_input_mode{n}") for n in range(4)]
        cv_targets_sync = [Signal(unsigned(3), name=f"text_cv_target{n}") for n in range(4)]
        m.submodules += [
            FFSynchronizer(self.page, page_sync),
            FFSynchronizer(self.preset, preset_sync),
            FFSynchronizer(self.selected, selected_sync),
            FFSynchronizer(self.editing, editing_sync),
            FFSynchronizer(self.filter_mode, filter_mode_sync),
            FFSynchronizer(self.filter_type, filter_type_sync),
        ]
        for n in range(4):
            m.submodules += FFSynchronizer(self.input_modes[n], input_modes_sync[n])
            m.submodules += FFSynchronizer(self.cv_targets[n], cv_targets_sync[n])

        update_index = Signal(range(42))
        update_active = Signal(init=1)
        refresh_counter = Signal(range(4_000_000))
        writer_address = Signal(unsigned(14))
        writer_char = Signal(unsigned(6))
        selected_band = Signal(range(RezoCore.N_BANDS))
        selected_band_valid = Signal()
        m.d.comb += [
            writer_address.eq(0),
            writer_char.eq(0),
            selected_band.eq(0),
            selected_band_valid.eq((selected_sync >= RezoHardwareUI.TARGET_BAND_BASE) &
                                   (selected_sync < RezoHardwareUI.TARGET_BAND_BASE +
                                    RezoCore.N_BANDS)),
            text_wport.addr.eq(writer_address),
            text_wport.data.eq(writer_char),
            text_wport.en.eq(update_active),
        ]
        with m.If(selected_band_valid):
            m.d.comb += selected_band.eq(selected_sync - RezoHardwareUI.TARGET_BAND_BASE)

        preset_names = ("ALL ", "ODD ", "EVN ", "LOW ", "MID ", "HI  ", "ZERO")
        frequency_names = ("29 ", "61 ", "115", "218", "411",
                           "777", "1K5", "2K8", "5K2", "11K")
        target_names = ("FB ", "RES", "G1 ", "G2 ", "G3 ", "G4 ")
        nav_names = (" NAV", "EDIT")
        nav_chars = [Array(Const(self.code(name[pos]), 6) for name in nav_names)
                     for pos in range(4)]
        preset_chars = [Array(Const(self.code(name[pos]), 6) for name in preset_names)
                        for pos in range(4)]
        frequency_chars = [Array(Const(self.code(name[pos]), 6) for name in frequency_names)
                           for pos in range(3)]
        target_chars = [Array(Const(self.code(name[pos]), 6) for name in target_names)
                        for pos in range(3)]
        filter_type_names = ("LP  ", "HP  ", "BP  ", "NOT ")
        filter_type_chars = [Array(Const(self.code(name[pos]), 6)
                                   for name in filter_type_names)
                             for pos in range(4)]
        with m.Switch(update_index):
            for pos in range(4):
                with m.Case(pos):
                    m.d.comb += [
                        writer_address.eq(
                            page_offsets[Mux((page_sync == 0) & filter_mode_sync,
                                             5, page_sync)] + 2 * 45 + 38 + pos),
                        writer_char.eq(nav_chars[pos][editing_sync]),
                    ]
            for pos in range(4):
                with m.Case(4 + pos):
                    m.d.comb += [
                        writer_address.eq(0 * page_cells + 7 * 45 + 10 + pos),
                        writer_char.eq(preset_chars[pos][preset_sync]),
                    ]
            for pos in range(3):
                with m.Case(8 + pos):
                    m.d.comb += [
                        writer_address.eq(0 * page_cells + 11 * 45 + 28 + pos),
                        writer_char.eq(Mux(selected_band_valid,
                                           frequency_chars[pos][selected_band], 0)),
                    ]
            for n in range(4):
                row = 13 + n * 6
                for pos in range(3):
                    with m.Case(11 + n * 3 + pos):
                        audio_char = self.code("AUD"[pos])
                        cv_char = self.code("CV "[pos])
                        m.d.comb += [
                            writer_address.eq(2 * page_cells + row * 45 + 14 + pos),
                            writer_char.eq(Mux(input_modes_sync[n], cv_char, audio_char)),
                        ]
                    with m.Case(23 + n * 3 + pos):
                        m.d.comb += [
                            writer_address.eq(2 * page_cells + (row + 2) * 45 + 16 + pos),
                            writer_char.eq(Mux(input_modes_sync[n],
                                               target_chars[pos][cv_targets_sync[n]], 0)),
                        ]
            for pos in range(4):
                with m.Case(35 + pos):
                    m.d.comb += [
                        writer_address.eq(5 * page_cells + 6 * 45 + 10 + pos),
                        writer_char.eq(filter_type_chars[pos][filter_type_sync]),
                    ]
            for pos in range(3):
                with m.Case(39 + pos):
                    m.d.comb += [
                        writer_address.eq(4 * page_cells + 17 * 45 + 37 + pos),
                        writer_char.eq(Mux(filter_mode_sync, 0,
                                           Const(self.code("DRY"[pos]), 6))),
                    ]
        with m.If(update_active):
            with m.If(update_index == 41):
                m.d.sync += [update_active.eq(0), refresh_counter.eq(0)]
            with m.Else():
                m.d.sync += update_index.eq(update_index + 1)
        with m.Elif(refresh_counter == 3_999_999):
            m.d.sync += [update_active.eq(1), update_index.eq(0)]
        with m.Else():
            m.d.sync += refresh_counter.eq(refresh_counter + 1)

        cell_x_pre_q = Signal.like(cell_x)
        cell_y_pre_q = Signal.like(cell_y)
        glyph_row_pre_q = Signal(unsigned(3))
        glyph_col_pre_q = Signal(unsigned(3))
        text_active_pre_q = Signal()
        m.d.dvi += [
            cell_x_pre_q.eq(cell_x),
            cell_y_pre_q.eq(cell_y),
            glyph_row_pre_q.eq(glyph_row),
            glyph_col_pre_q.eq(glyph_col),
            text_active_pre_q.eq(active),
        ]
        char_code_q = Signal(unsigned(6))
        glyph_row_q = Signal(unsigned(3))
        glyph_col_q = Signal(unsigned(3))
        text_active_q = Signal()
        m.d.dvi += [
            char_code_q.eq(text_rport.data),
            glyph_row_q.eq(glyph_row_pre_q),
            glyph_col_q.eq(glyph_col_pre_q),
            text_active_q.eq(text_active_pre_q),
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
        meter_panel = active & (bank_page | tune_page) & (
            self.rect(x, y, 118, 584, 650, 608) |
            self.rect(x, y, 118, 616, 650, 640) |
                                self.rect(x, y, 118, 648, 650, 672))
        filter_meter_panel = active & filter_page & (
            self.rect(x, y, 118, 574, 650, 594) |
            self.rect(x, y, 118, 606, 650, 626) |
            self.rect(x, y, 118, 638, 650, 658) |
            self.rect(x, y, 118, 670, 650, 690))

        preset_chip = Signal()
        preset_select = Signal()
        preset_group_select = Signal()
        band_slot = Signal()
        band_zero = Signal()
        band_marker = Signal()
        band_fill = Signal()
        band_select = Signal()
        input_panel = Signal()
        input_fill = Signal()
        input_line = Signal()
        input_select = Signal()
        group_cell = Signal()
        group_fill = Signal()
        group_select = Signal()
        output_cell = Signal()
        output_fill = Signal()
        output_select = Signal()
        mode_chip = home_page & self.rect(x, y, 470, 28, 682, 72)
        mode_select = home_page & (self.selected == RezoHardwareUI.TARGET_MODE) & self.outline(
            x, y, 466, 24, 686, 76, t=3)
        filter_type_chip = filter_page & self.rect(x, y, 136, 96, 264, 132)
        filter_type_select = filter_page & (self.selected == RezoHardwareUI.TARGET_FILTER_TYPE) & self.outline(
            x, y, 131, 91, 269, 137, t=3)

        preset_chip_signals = []
        preset_select_signals = []
        band_slot_signals = []
        band_zero_signals = []
        band_marker_signals = []
        band_fill_signals = []
        band_select_signals = []
        input_panel_signals = []
        input_fill_signals = []
        input_line_signals = []
        input_select_signals = []
        group_cell_signals = []
        group_select_signals = []

        input_gain_ends = [Signal(signed(12), init=326, name=f"input_gain_end{n}")
                           for n in range(4)]
        input_depth_ends = [Signal(signed(12), init=490, name=f"input_depth_end{n}")
                            for n in range(4)]
        for n in range(4):
            m.d.dvi += [
                input_gain_ends[n].eq(326 + (self.input_gains[n] << 3) +
                                           (self.input_gains[n] << 1)),
                input_depth_ends[n].eq(490 + (self.cv_depths[n] << 2) + self.cv_depths[n]),
            ]

        preset_chip_signals.append(bank_page & self.rect(x, y, 136, 96, 264, 132))
        preset_select_signals.append(
            bank_page & self.editing & (self.selected == RezoHardwareUI.TARGET_PRESET) &
            self.outline(x, y, 131, 91, 269, 137, t=3))

        for n in range(RezoCore.N_BANDS):
            x0 = 48 + 66 * n
            x1 = x0 + 42
            top_y = band_top_values[n]
            bottom_y = band_bottom_values[n]
            level_positive = band_positive_values[n]
            level_negative = band_negative_values[n]
            selected_band = self.selected == RezoHardwareUI.TARGET_BAND_BASE + n
            band_slot_signals.append(home_page & self.rect(x, y, x0, 202, x1, 532))
            band_zero_signals.append(
                (bank_page & self.rect(x, y, x0 - 5, zero_y - 1, x1 + 5, zero_y + 2)) |
                (filter_page & self.rect(x, y, x0 - 5, 529, x1 + 5, 532)))
            band_marker_signals.append(
                bank_page & self.rect(x, y, x0, band_base_marker_values[n] - 2,
                                      x1, band_base_marker_values[n] + 3))
            band_fill_signals.append(
                (bank_page & ((level_positive & self.rect(x, y, x0, top_y, x1, zero_y)) |
                              (level_negative & self.rect(x, y, x0, zero_y, x1, bottom_y)))) |
                (filter_page & level_positive & self.rect(x, y, x0, top_y, x1, 532)))
            band_select_signals.append(
                bank_page & selected_band & self.outline(x, y, x0 - 7, 195, x1 + 7, 539, t=3))

        for n in range(4):
            base_y = 198 + n * 96
            target_base = RezoHardwareUI.TARGET_INPUT_BASE + n * 3
            input_panel_signals.extend([
                input_page & self.rect(x, y, 116, base_y, 304, base_y + 28),
                input_page & self.rect(x, y, 116, base_y + 32, 656, base_y + 60),
                input_page & (self.input_modes[n] == RezoCore.INPUT_MODE_CV) &
                self.rect(x, y, 116, base_y + 64, 656, base_y + 92),
            ])
            input_select_signals.extend([
                input_page & (self.selected == target_base) &
                self.outline(x, y, 112, base_y - 4, 308, base_y + 32, t=3),
                input_page & (self.selected == target_base + 1) &
                self.outline(x, y, 112, base_y + 28, 660, base_y + 64, t=3),
                input_page & (self.input_modes[n] == RezoCore.INPUT_MODE_CV) &
                (self.selected == target_base + 2) &
                self.outline(x, y, 112, base_y + 60, 660, base_y + 96, t=3),
            ])
            input_fill_signals.append(
                input_page & (self.input_modes[n] == RezoCore.INPUT_MODE_AUDIO) &
                self.rect(x, y, 326, base_y + 39, input_gain_ends[n], base_y + 53))
            depth_center = 490
            depth = self.cv_depths[n]
            input_fill_signals.append(
                input_page & (self.input_modes[n] == RezoCore.INPUT_MODE_CV) &
                Mux(depth >= 0,
                    self.rect(x, y, depth_center, base_y + 71, input_depth_ends[n], base_y + 85),
                    self.rect(x, y, input_depth_ends[n], base_y + 71, depth_center, base_y + 85)))
            input_line_signals.append(
                input_page & (self.input_modes[n] == RezoCore.INPUT_MODE_CV) &
                self.rect(x, y, depth_center - 1, base_y + 67, depth_center + 2, base_y + 89))

        for group in range(RezoCore.N_GROUPS):
            rail_y = 305 + group * 64
            group_cell_signals.append(
                group_page & self.rect(x, y, 92, rail_y, 666, rail_y + 3))

        for n in range(RezoCore.N_BANDS):
            x0 = 108 + n * 54
            group_select_signals.append(
                group_page & (self.selected == RezoHardwareUI.TARGET_GROUP_BASE + n) &
                self.outline(x, y, x0 - 7, 274, x0 + 31, 548, t=3))
        group_band = Signal(range(RezoCore.N_BANDS))
        group_row = Signal(unsigned(2))
        group_band_active = Signal()
        group_row_active = Signal()
        group_band_q = Signal.like(group_band)
        group_row_q = Signal.like(group_row)
        group_band_active_q = Signal()
        group_row_active_q = Signal()
        group_page_q = Signal()
        bank_group_mask_array = Array(self.bank_groups)
        m.d.comb += [
            group_band.eq(0),
            group_row.eq(0),
            group_band_active.eq(0),
            group_row_active.eq(0),
        ]
        for n in range(RezoCore.N_BANDS):
            x0 = 108 + n * 54
            with m.If((x >= x0) & (x < x0 + 24)):
                m.d.comb += [group_band.eq(n), group_band_active.eq(1)]
        for group in range(RezoCore.N_GROUPS):
            marker_y = 294 + group * 64
            with m.If((y >= marker_y) & (y < marker_y + 24)):
                m.d.comb += [group_row.eq(group), group_row_active.eq(1)]
        # Coordinate decoding is substantially wider than the actual 10x4
        # assignment lookup. Pipeline the two halves so the group page does
        # not put both on one HDMI pixel-clock path.
        m.d.dvi += [
            group_band_q.eq(group_band),
            group_row_q.eq(group_row),
            group_band_active_q.eq(group_band_active),
            group_row_active_q.eq(group_row_active),
            group_page_q.eq(group_page),
        ]
        m.d.comb += group_fill.eq(
            group_page_q & group_band_active_q & group_row_active_q &
            bank_group_mask_array[group_band_q].bit_select(group_row_q, 1))

        output_row = Signal(unsigned(2))
        output_source = Signal(unsigned(3))
        output_row_active = Signal()
        output_col_active = Signal()
        output_row_edge = Signal()
        output_col_edge = Signal()
        output_row_inner = Signal()
        output_col_inner = Signal()
        output_route_array = Array(self.output_routes)
        m.d.comb += [
            output_row.eq(0),
            output_source.eq(0),
            output_row_active.eq(0),
            output_col_active.eq(0),
            output_row_edge.eq(0),
            output_col_edge.eq(0),
            output_row_inner.eq(0),
            output_col_inner.eq(0),
        ]
        for output in range(4):
            row_y = 326 + output * 80
            with m.If((y >= row_y) & (y < row_y + 28)):
                m.d.comb += [
                    output_row.eq(output),
                    output_row_active.eq(1),
                    output_row_edge.eq((y < row_y + 2) | (y >= row_y + 26)),
                    output_row_inner.eq((y >= row_y + 5) & (y < row_y + 23)),
                ]
        for source in range(5):
            cell_x0 = 208 + source * 96
            with m.If((x >= cell_x0) & (x < cell_x0 + 42)):
                m.d.comb += [
                    output_source.eq(source),
                    output_col_active.eq(Const(source != 4) | ~self.filter_mode),
                    output_col_edge.eq((x < cell_x0 + 2) | (x >= cell_x0 + 40)),
                    output_col_inner.eq((x >= cell_x0 + 5) & (x < cell_x0 + 37)),
                ]
        m.d.comb += [
            output_cell.eq(output_page & output_row_active & output_col_active &
                           (output_row_edge | output_col_edge)),
            output_fill.eq(output_page & output_row_inner & output_col_inner &
                           output_route_array[output_row].bit_select(output_source, 1)),
        ]
        output_select_expr = Const(0)
        for output in range(4):
            row_y = 326 + output * 80
            output_select_expr = output_select_expr | (
                output_page & (self.selected == RezoHardwareUI.TARGET_OUTPUT_BASE + output) &
                self.outline(x, y, 116, row_y - 10, 666, row_y + 46, t=3))
        m.d.comb += output_select.eq(output_select_expr)

        for target, signals in [
                (preset_chip, preset_chip_signals),
                (preset_select, preset_select_signals),
                (band_slot, band_slot_signals),
                (band_zero, band_zero_signals),
                (band_select, band_select_signals),
                (input_panel, input_panel_signals),
                (input_fill, input_fill_signals),
                (input_line, input_line_signals),
                (input_select, input_select_signals),
                (group_cell, group_cell_signals),
                (group_select, group_select_signals)]:
            expr = Const(0)
            for sig in signals:
                expr = expr | sig
            m.d.comb += target.eq(expr)

        def tile_registered_or(signals, prefix):
            expr = Const(0)
            for n, sig in enumerate(signals):
                sig_q = Signal(name=f"tile_{prefix}{n}_q")
                m.d.dvi += sig_q.eq(sig)
                expr = expr | sig_q
            return expr

        input_panel_q0 = tile_registered_or(input_panel_signals, "input_panel")
        input_fill_q0 = tile_registered_or(input_fill_signals, "input_fill")
        input_line_q0 = tile_registered_or(input_line_signals, "input_line")
        input_select_q0 = tile_registered_or(input_select_signals, "input_select")
        band_zero_q0 = tile_registered_or(band_zero_signals, "band_zero")
        band_slot_q0 = tile_registered_or(band_slot_signals, "band_slot")
        group_cell_q0 = tile_registered_or(group_cell_signals, "group_cell")
        group_fill_q0 = Signal()
        group_select_q0 = tile_registered_or(group_select_signals, "group_select")
        output_cell_q0 = Signal()
        output_fill_q0 = Signal()
        output_select_q0 = Signal()
        m.d.dvi += [
            output_cell_q0.eq(output_cell),
            output_fill_q0.eq(output_fill),
            output_select_q0.eq(output_select),
        ]
        m.d.comb += group_fill_q0.eq(group_fill)

        m.d.comb += preset_group_select.eq(
            bank_page & (self.selected == RezoHardwareUI.TARGET_PRESET) & ~self.editing &
            self.outline(x, y, 131, 91, 269, 137, t=3))
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
        m.d.comb += [
            row0_value.eq(Mux(tune_page, self.limit_knee, self.dry)),
            row1_value.eq(Mux(bank_page, self.effective_resonance, self.limit_cap)),
            row2_value.eq(Mux(bank_page, self.effective_feedback,
                              Cat(Const(0, 1), self.damp_mode, Const(0, 2)))),
        ]
        dry_fill = (bank_page | tune_page) & self.rect(x, y, 124, 588, 124 + (row0_value << 4), 604)
        dry_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_DRY)) |
                      (tune_page & (self.selected == RezoHardwareUI.TARGET_LIMIT_KNEE))) & self.outline(
            x, y, 118, 584, 650, 608, t=3)
        res_fill = (bank_page | tune_page) & self.rect(x, y, 124, 620, 124 + (row1_value << 4), 636)
        res_mod_marker = bank_page & self.rect(
            x, y, 122 + (self.resonance << 4), 616 + 2,
            126 + (self.resonance << 4), 640 - 2)
        res_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_RESONANCE)) |
                      (tune_page & (self.selected == RezoHardwareUI.TARGET_LIMIT_CAP))) & self.outline(
            x, y, 118, 616, 650, 640, t=3)
        fb_fill = (bank_page | tune_page) & self.rect(x, y, 124, 652, 124 + (row2_value << 4), 668)
        fb_mod_marker = bank_page & self.rect(
            x, y, 122 + (self.feedback << 4), 648 + 2,
            126 + (self.feedback << 4), 672 - 2)
        fb_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_FEEDBACK)) |
                     (tune_page & (self.selected == RezoHardwareUI.TARGET_DAMP))) & self.outline(
            x, y, 118, 648, 650, 672, t=3)
        filter_freq_fill = filter_page & self.rect(
            x, y, 124, 578, 124 + (self.effective_filter_cutoff << 4), 590)
        filter_slope_fill = filter_page & self.rect(
            x, y, 124, 610, 124 + (self.effective_filter_slope << 4), 622)
        filter_width_fill = filter_page & (self.filter_type >= RezoCore.FILTER_BP) & self.rect(
            x, y, 124, 642, 124 + (self.effective_filter_width << 4), 654)
        filter_res_fill = filter_page & self.rect(
            x, y, 124, 674, 124 + (self.effective_resonance << 4), 686)
        filter_freq_select = filter_page & (self.selected == RezoHardwareUI.TARGET_FILTER_CUTOFF) & self.outline(
            x, y, 118, 574, 650, 594, t=3)
        filter_slope_select = filter_page & (self.selected == RezoHardwareUI.TARGET_FILTER_SLOPE) & self.outline(
            x, y, 118, 606, 650, 626, t=3)
        filter_width_select = filter_page & (self.filter_type >= RezoCore.FILTER_BP) & (
            self.selected == RezoHardwareUI.TARGET_FILTER_WIDTH) & self.outline(
                x, y, 118, 638, 650, 658, t=3)
        filter_res_select = filter_page & (self.selected == RezoHardwareUI.TARGET_RESONANCE) & self.outline(
            x, y, 118, 670, 650, 690, t=3)
        input_unity_x = 326 + ((RezoCore.INPUT_UNITY_POS >> 11) * 10)
        input_unity_signals = []
        for n in range(4):
            base_y = 198 + n * 96
            input_unity_signals.append(
                input_page & (self.input_modes[n] == RezoCore.INPUT_MODE_AUDIO) &
                self.rect(x, y, input_unity_x, base_y + 35, input_unity_x + 3, base_y + 57))
        input_unity_q0 = tile_registered_or(input_unity_signals, "input_unity")
        page_select = (self.selected == RezoHardwareUI.TARGET_PAGE) & self.outline(
            x, y, 20, 20, 700, 82, t=3)

        bank_selected_q = Signal()
        filter_selected_q = Signal()
        input_selected_q = Signal()
        routing_selected_q = Signal()
        page_selected_q = Signal()
        m.d.dvi += [
            bank_selected_q.eq(preset_select | preset_group_select | band_select |
                               dry_select | res_select | fb_select | mode_select),
            filter_selected_q.eq(filter_type_select | filter_freq_select |
                                 filter_slope_select | filter_width_select |
                                 filter_res_select),
            input_selected_q.eq(input_select_q0),
            routing_selected_q.eq(group_select_q0 | output_select_q0),
            page_selected_q.eq(page_select),
        ]
        selected = active & (bank_selected_q | filter_selected_q |
                             input_selected_q | routing_selected_q |
                             page_selected_q)

        selected_q = Signal()
        text_q = Signal()
        fill_q = Signal()
        line_q = Signal()
        panel_q = Signal()
        background_q = Signal()
        active_q = Signal()
        geometry_fill_q0 = Signal()
        geometry_line_q0 = Signal()
        geometry_panel_q0 = Signal()
        m.d.dvi += [
            geometry_fill_q0.eq(band_fill | band_marker | dry_fill | res_fill | fb_fill |
                                filter_freq_fill | filter_slope_fill |
                                filter_width_fill | filter_res_fill),
            geometry_line_q0.eq(band_zero_q0 | res_mod_marker | fb_mod_marker | border),
            geometry_panel_q0.eq(preset_chip | filter_type_chip | mode_chip | band_slot_q0 |
                                 meter_panel | filter_meter_panel),
        ]
        m.d.dvi += [
            selected_q.eq(selected),
            text_q.eq(text),
            fill_q.eq(geometry_fill_q0 |
                      input_fill_q0 | group_fill_q0 | output_fill_q0),
            line_q.eq(geometry_line_q0 | input_line_q0 | input_unity_q0),
            panel_q.eq(geometry_panel_q0 | input_panel_q0 | group_cell_q0 | output_cell_q0),
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
        brief="REZO configurable resonant filterbank.",
        io_left=['audio / CV input', 'audio / CV input',
                 'audio / CV input', 'audio / CV input',
                 'assignable out', 'assignable out',
                 'assignable out', 'assignable out'],
        io_right=['', '', 'video out required', '', '', '']
    )
    # This design's DVI PHY placement is seed-sensitive at 720p60. Seed 1
    # provides repeatable margin on all four constrained clocks.
    nextpnr_opts = f"--timing-allow-fail --seed {os.getenv('TILIQUA_REZO_SEED', '1')}"

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
            rezo.filter_mode.eq(ui.filter_mode),
            rezo.filter_type.eq(ui.filter_type),
            rezo.filter_cutoff.eq(ui.filter_cutoff),
            rezo.filter_slope.eq(ui.filter_slope),
            rezo.filter_width.eq(ui.filter_width),
            rezo.limit_knee.eq(ui.limit_knee),
            rezo.limit_cap.eq(ui.limit_cap),
            rezo.damp_mode.eq(ui.damp_mode),
        ]
        for n in range(RezoCore.N_BANDS):
            m.d.comb += rezo.levels[n].eq(ui.levels[n])
        for n in range(4):
            m.d.comb += [
                rezo.input_gains[n].eq(ui.input_gains[n]),
                rezo.input_modes[n].eq(ui.input_modes[n]),
                rezo.cv_targets[n].eq(ui.cv_targets[n]),
                rezo.cv_depths[n].eq(ui.cv_depths[n]),
            ]
        for n in range(RezoCore.N_BANDS):
            m.d.comb += rezo.bank_groups[n].eq(ui.bank_groups[n])
        for n in range(4):
            m.d.comb += rezo.output_routes[n].eq(ui.output_routes[n])

        wiring.connect(m, pmod0.o_cal, rezo.i)
        wiring.connect(m, rezo.o, audio_out_fifo.i)
        wiring.connect(m, audio_out_fifo.o, pmod0.i_cal)

        m.submodules.dvi_tgen = dvi_tgen = dvi.DVITimingGen()
        for member in dvi_tgen.timings.signature.members:
            m.d.comb += getattr(dvi_tgen.timings, member).eq(
                getattr(self.clock_settings.modeline, member))

        m.submodules.display = display = RezoTileDisplay(
            h_active=self.clock_settings.modeline.h_active)
        m.d.comb += [
            display.x.eq(dvi_tgen.x),
            display.y.eq(dvi_tgen.y),
            display.de.eq(dvi_tgen.ctrl.de),
        ]
        for n in range(RezoCore.N_BANDS):
            display_level = Signal(signed(6), name=f"display_level{n}")
            display_effective_level = Signal(signed(6), name=f"display_effective_level{n}")
            m.d.comb += display_level.eq(rezo.levels[n] >> 10)
            m.d.comb += display_effective_level.eq(rezo.effective_levels[n] >> 10)
            m.submodules += FFSynchronizer(
                i=display_level, o=display.levels[n], o_domain="dvi")
            m.submodules += FFSynchronizer(
                i=display_effective_level, o=display.effective_levels[n], o_domain="dvi")
        display_dry = Signal(unsigned(6))
        display_resonance = Signal(unsigned(6))
        display_feedback = Signal(unsigned(6))
        display_effective_resonance = Signal(unsigned(6))
        display_effective_feedback = Signal(unsigned(6))
        display_filter_cutoff = Signal(unsigned(6))
        display_filter_slope = Signal(unsigned(6))
        display_filter_width = Signal(unsigned(6))
        display_effective_filter_cutoff = Signal(unsigned(6))
        display_effective_filter_slope = Signal(unsigned(6))
        display_effective_filter_width = Signal(unsigned(6))
        display_limit_knee = Signal(unsigned(6))
        display_limit_cap = Signal(unsigned(6))
        display_input_gains = [Signal(unsigned(6), name=f"display_input_gain{n}")
                               for n in range(4)]
        display_cv_depths = [Signal(signed(6), name=f"display_cv_depth{n}")
                             for n in range(4)]
        m.d.comb += [
            display_dry.eq(rezo.dry >> 10),
            display_resonance.eq(rezo.resonance >> 10),
            display_feedback.eq(rezo.feedback >> 10),
            display_effective_resonance.eq(rezo.effective_resonance >> 10),
            display_effective_feedback.eq(rezo.effective_feedback >> 10),
            display_filter_cutoff.eq(rezo.filter_cutoff >> 10),
            display_filter_slope.eq(rezo.filter_slope >> 10),
            display_filter_width.eq(rezo.filter_width >> 10),
            display_effective_filter_cutoff.eq(rezo.effective_filter_cutoff >> 10),
            display_effective_filter_slope.eq(rezo.effective_filter_slope >> 10),
            display_effective_filter_width.eq(rezo.effective_filter_width >> 10),
            display_limit_knee.eq(rezo.limit_knee >> 10),
            display_limit_cap.eq(rezo.limit_cap >> 10),
        ]
        for n in range(4):
            m.d.comb += display_input_gains[n].eq(
                Mux(rezo.input_gains[n] >= RezoCore.INPUT_MAX - 1023,
                    32,
                    rezo.input_gains[n] >> 11))
        for n in range(4):
            m.d.comb += display_cv_depths[n].eq(rezo.cv_depths[n] >> 10)
        m.submodules += [
            FFSynchronizer(i=display_dry, o=display.dry, o_domain="dvi"),
            FFSynchronizer(i=display_resonance, o=display.resonance, o_domain="dvi"),
            FFSynchronizer(i=display_feedback, o=display.feedback, o_domain="dvi"),
            FFSynchronizer(i=display_effective_resonance, o=display.effective_resonance, o_domain="dvi"),
            FFSynchronizer(i=display_effective_feedback, o=display.effective_feedback, o_domain="dvi"),
            FFSynchronizer(i=ui.filter_mode, o=display.filter_mode, o_domain="dvi"),
            FFSynchronizer(i=ui.filter_type, o=display.filter_type, o_domain="dvi"),
            FFSynchronizer(i=display_filter_cutoff, o=display.filter_cutoff, o_domain="dvi"),
            FFSynchronizer(i=display_filter_slope, o=display.filter_slope, o_domain="dvi"),
            FFSynchronizer(i=display_filter_width, o=display.filter_width, o_domain="dvi"),
            FFSynchronizer(i=display_effective_filter_cutoff,
                           o=display.effective_filter_cutoff, o_domain="dvi"),
            FFSynchronizer(i=display_effective_filter_slope,
                           o=display.effective_filter_slope, o_domain="dvi"),
            FFSynchronizer(i=display_effective_filter_width,
                           o=display.effective_filter_width, o_domain="dvi"),
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
        for n in range(4):
            m.submodules += FFSynchronizer(
                i=ui.input_modes[n], o=display.input_modes[n], o_domain="dvi")
            m.submodules += FFSynchronizer(
                i=ui.cv_targets[n], o=display.cv_targets[n], o_domain="dvi")
            m.submodules += FFSynchronizer(
                i=display_cv_depths[n], o=display.cv_depths[n], o_domain="dvi")
        for n in range(RezoCore.N_BANDS):
            m.submodules += FFSynchronizer(
                i=ui.bank_groups[n], o=display.bank_groups[n], o_domain="dvi")
        for n in range(4):
            m.submodules += FFSynchronizer(
                i=ui.output_routes[n], o=display.output_routes[n], o_domain="dvi")

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
