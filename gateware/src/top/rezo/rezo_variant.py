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
from luna_soc.gateware.core import spiflash

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
try:
    from .persistence import RezoStateJournal, SPIFlashTransfer
except ImportError:  # top_level_cli executes this file directly.
    from persistence import RezoStateJournal, SPIFlashTransfer


class RezoCore(wiring.Component):
    """Ten-band mono resonant filterbank."""

    N_BANDS = 10
    INPUT_UNITY = 32768
    INPUT_MAX = 65535
    INPUT_UNITY_POS = 52428
    PARAM_SLEW_STEP = 64
    FILTER_PARAM_SLEW_STEP = 256
    # Proven input conditioner from the last hardware-clean DSP path. Keep it
    # independent of the user-facing feedback safety controls: its job is only
    # to prevent a hot Eurorack input from making an SVF state chatter.
    INPUT_LIMIT_KNEE = 12288
    INPUT_LIMIT_SHIFT = 3  # 8:1 above the knee
    INPUT_MODE_AUDIO = 0
    INPUT_MODE_CV = 1
    CV_TARGET_FEEDBACK = 0
    CV_TARGET_RESONANCE = 1
    CV_TARGET_DRIVE = 2
    CV_TARGET_GROUP_BASE = 3
    N_GROUPS = 4
    FILTER_LP = 0
    FILTER_HP = 1
    FILTER_BP = 2
    FILTER_NOTCH = 3
    FILTER_PASS_LEVEL = 8192
    DRIVE_FLOOR = 8192       # 0.25x resonator excitation
    DRIVE_DEFAULT = 8192     # + floor = established 0.5x excitation
    DRIVE_MAX = 24575        # + floor = just below 1.0x

    # The original REZO prototype used the nominal centers of the filterbank
    # that inspired it. Keep that layout as LEGACY, but make the neutral
    # octave-spaced layout the factory default for new configurations.
    LEGACY_FREQS_HZ = (29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000)
    OCTAVE_FREQS_HZ = (31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
    PERCEPT_FREQS_HZ = (50, 150, 300, 500, 770, 1150, 1700, 2700, 5300, 12000)
    # Factory centers form the coarse grid retained by the version-2 save
    # format. Manual editing inserts three logarithmic subdivisions between
    # adjacent centers. The low five bits previously saved for each band still
    # identify the same exact factory-union value; two former padding bits per
    # band persist the new fine position without growing the record.
    COARSE_FREQUENCIES_HZ = tuple(sorted(set((
        *LEGACY_FREQS_HZ, *OCTAVE_FREQS_HZ, *PERCEPT_FREQS_HZ,
    ))))
    FREQ_COARSE_WIDTH = 5
    FREQ_FINE_WIDTH = 2
    FREQ_SUBDIVISIONS = 1 << FREQ_FINE_WIDTH

    frequencies = []
    for index, frequency in enumerate(COARSE_FREQUENCIES_HZ):
        if index + 1 < len(COARSE_FREQUENCIES_HZ):
            next_frequency = COARSE_FREQUENCIES_HZ[index + 1]
        else:
            next_frequency = round(
                frequency * frequency / COARSE_FREQUENCIES_HZ[index - 1])
        for subdivision in range(FREQ_SUBDIVISIONS):
            interpolated = round(
                frequency * (next_frequency / frequency) **
                (subdivision / FREQ_SUBDIVISIONS))
            if index + 1 < len(COARSE_FREQUENCIES_HZ):
                interpolated = min(interpolated, next_frequency - 1)
            frequencies.append(max(frequency, interpolated))
    FREQUENCIES_HZ = tuple(frequencies)
    del frequencies, index, frequency, next_frequency, subdivision, interpolated
    FREQ_INDEX_WIDTH = (len(FREQUENCIES_HZ) - 1).bit_length()
    LAYOUT_LEGACY = 0
    LAYOUT_OCTAVE = 1
    LAYOUT_PERCEPT = 2
    LAYOUT_USER = 3

    @classmethod
    def frequency_index(cls, frequency):
        return cls.FREQUENCIES_HZ.index(frequency)

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
        self.band_enables = [Signal(init=1, name=f"band_enable{n}")
                             for n in range(self.N_BANDS)]
        self.band_frequencies = [
            Signal(unsigned(self.FREQ_INDEX_WIDTH),
                   init=self.frequency_index(frequency),
                   name=f"band_frequency{n}")
            for n, frequency in enumerate(self.LEGACY_FREQS_HZ)
        ]
        # Wet-path drive amount above DRIVE_FLOOR. The musical range is
        # 0.25x..1.0x, with the established clean 0.5x path as default.
        self.drive = Signal(unsigned(16), init=self.DRIVE_DEFAULT)
        self.resonance = Signal(unsigned(16), init=8192)
        self.feedback = Signal(unsigned(16), init=0)
        self.filter_mode = Signal(init=0)
        self.filter_type = Signal(unsigned(2), init=self.FILTER_LP)
        self.filter_cutoff = Signal(unsigned(16), init=16384)
        self.filter_slope = Signal(unsigned(16), init=16384)
        self.filter_width = Signal(unsigned(16), init=12288)
        # Destination-major 5x3 FILTER modulation matrix:
        # FREQ, RES, WIDTH, SLOPE, DRIVE rows by IN1, IN2, IN3 columns.
        self.filter_cv_matrix = [Signal(signed(8), init=0,
                                        name=f"filter_cv_matrix{n}")
                                 for n in range(15)]
        self.limit_knee = Signal(unsigned(16), init=8192)
        self.limit_cap = Signal(unsigned(16), init=28672)
        self.damp_mode = Signal(unsigned(3), init=3)
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
        self.feedback_sends = [Signal(init=1, name=f"feedback_send{n}")
                               for n in range(self.N_BANDS)]
        # Route bits mirror non-zero sends for display/inspection. The actual
        # mix is controlled by the five G1..G4/DRY send levels below.
        # Unipolar G1..G4/DRY send levels for OUT0..OUT3. A value of 16 is
        # unity. DRY defaults to zero, matching the old global DRY default.
        initial_routes = (0b01111, 0b00101, 0b01010, 0b10000)
        self.output_sends = [
            Signal(unsigned(5),
                   init=16 if source < self.N_GROUPS and
                              initial_routes[output] & (1 << source) else 0,
                   name=f"output_send{output}_{source}")
            for output in range(4) for source in range(self.N_GROUPS + 1)
        ]
        self.effective_resonance = Signal(unsigned(16), init=8192)
        self.effective_feedback = Signal(unsigned(16), init=0)
        self.effective_drive = Signal(unsigned(16), init=16384)
        self.effective_filter_cutoff = Signal(unsigned(16), init=16384)
        self.effective_filter_slope = Signal(unsigned(16), init=16384)
        self.effective_filter_width = Signal(unsigned(16), init=12288)
        self.effective_groups = [Signal(signed(16), name=f"effective_group{n}")
                                 for n in range(self.N_GROUPS)]
        self.effective_levels = [Signal(signed(16), name=f"effective_level{n}")
                                 for n in range(self.N_BANDS)]
        # Display-only input telemetry. Audio inputs report their post-VALUE
        # peak envelope; CV inputs report the raw, pre-DEPTH bipolar sample.
        self.input_meters = [Signal(signed(16), name=f"input_meter{n}")
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
        smooth_drive = Signal(unsigned(16), init=self.DRIVE_DEFAULT)
        smooth_resonance = Signal(unsigned(16), init=8192)
        smooth_feedback = Signal(unsigned(16), init=0)
        smooth_input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n == 0 else 0,
                                     name=f"smooth_input_gain{n}")
                              for n in range(4)]
        smooth_cv_depths = [Signal(signed(16), init=0, name=f"smooth_cv_depth{n}")
                            for n in range(4)]
        level_diffs = [Signal(signed(17), name=f"level_diff{n}")
                       for n in range(self.N_BANDS)]
        drive_diff = Signal(signed(17))
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
        drive_cv_term = Signal(signed(18))
        group_cv_terms = [Signal(signed(18), name=f"group_cv_term{n}")
                          for n in range(self.N_GROUPS)]
        effective_resonance_raw = Signal(signed(18))
        effective_feedback_raw = Signal(signed(18))
        effective_drive_raw = Signal(signed(18))
        effective_resonance = Signal(unsigned(16))
        effective_feedback = Signal(unsigned(16))
        effective_drive = Signal(unsigned(16))
        m.d.comb += [
            drive_diff.eq(self.drive - smooth_drive),
            resonance_diff.eq(self.resonance - smooth_resonance),
            feedback_diff.eq(self.feedback - smooth_feedback),
            effective_resonance_raw.eq(smooth_resonance + resonance_cv_term),
            effective_feedback_raw.eq(smooth_feedback + feedback_cv_term),
            effective_drive_raw.eq(self.DRIVE_FLOOR + smooth_drive + drive_cv_term),
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
        with m.If(effective_drive_raw < self.DRIVE_FLOOR):
            m.d.comb += effective_drive.eq(self.DRIVE_FLOOR)
        with m.Elif(effective_drive_raw > 32767):
            m.d.comb += effective_drive.eq(32767)
        with m.Else():
            m.d.comb += effective_drive.eq(effective_drive_raw)
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
        # Keep the input-plus-feedback sum wide until after saturation. A
        # 16-bit intermediate can wrap before a limiter has a chance to act.
        x_drive = Signal(signed(18))
        resonance = Signal(dsp.mac.SQNative)
        dry_sample = Signal(ASQ)

        cutoff_table = [
            fixed.Const(self.cutoff_coeff(freq, self.fs),
                        dsp.mac.SQNative).as_value().value
            for freq in self.FREQUENCIES_HZ
        ]
        # Runtime frequency selection is table-driven. The next band's block-
        # ROM coefficient is prefetched after the current band's two SVF passes
        # are complete, so the synchronous output is ready before ``band`` is
        # advanced without putting a wide LUT mux in the audio path.
        m.submodules.cutoff_mem = cutoff_mem = Memory(
            shape=dsp.mac.SQNative.as_shape(), depth=len(cutoff_table),
            init=cutoff_table, attrs={"ram_style": "block"})
        cutoff_rport = cutoff_mem.read_port()
        frequency_array = Array(self.band_frequencies)
        self.filter_levels = [Signal(signed(16), init=self.FILTER_PASS_LEVEL,
                                     name=f"filter_level{n}")
                              for n in range(self.N_BANDS)]
        filter_levels = self.filter_levels
        # BANK and FILTER previously selected unrelated ten-band gain vectors
        # in one sample. Slew the existing shared level registers toward the
        # new mode's target instead; this gives mode changes a short click-free
        # crossfade without adding an output multiplier or transition counter.
        for n in range(self.N_BANDS):
            m.d.comb += level_diffs[n].eq(
                Mux(self.filter_mode, filter_levels[n], self.levels[n]) -
                smooth_levels[n])
        filter_level_array = Array(filter_levels)
        active_levels = [Signal(signed(16), name=f"active_level{n}")
                         for n in range(self.N_BANDS)]
        self.active_levels = active_levels
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
        filter_slope_factor = Signal(signed(17))
        filter_slope_factor_q = Signal(signed(17))
        filter_slope_product = Signal(signed(36))
        filter_slope_product_q = Signal(signed(36))
        filter_ramp = Signal(signed(20))
        filter_ramp_q = Signal(signed(20))
        filter_low_gain = Signal(signed(16))
        filter_profile_gain = Signal(signed(16))
        filter_band_q0 = Signal(range(self.N_BANDS))
        filter_band_q1 = Signal(range(self.N_BANDS))
        filter_band_q2 = Signal(range(self.N_BANDS))
        filter_band_q3 = Signal(range(self.N_BANDS))
        filter_type_q0 = Signal(unsigned(2))
        filter_type_q1 = Signal(unsigned(2))
        filter_type_q2 = Signal(unsigned(2))
        filter_type_q3 = Signal(unsigned(2))
        m.d.comb += [
            filter_pos.eq(filter_positions[filter_update_band]),
            filter_distance.eq(self.effective_filter_cutoff - filter_pos),
            filter_edge.eq(Mux((filter_type_q0 == self.FILTER_BP) |
                               (filter_type_q0 == self.FILTER_NOTCH),
                               filter_half_width_q -
                               Mux(filter_distance_q < 0,
                                   -filter_distance_q, filter_distance_q),
                               filter_distance_q)),
            # Continuously interpolate the edge multiplier from 1/8 to 1.
            # This replaces the former four-position shift selector.
            filter_slope_factor.eq(
                4096 + self.effective_filter_slope -
                (self.effective_filter_slope >> 3)),
            filter_slope_product.eq(filter_edge_q * filter_slope_factor_q),
            filter_ramp.eq(4096 + (filter_slope_product_q >> 15)),
            filter_low_gain.eq(0),
            filter_profile_gain.eq(filter_low_gain),
        ]
        with m.If(filter_ramp_q < 0):
            m.d.comb += filter_low_gain.eq(0)
        with m.Elif(filter_ramp_q > self.FILTER_PASS_LEVEL):
            m.d.comb += filter_low_gain.eq(self.FILTER_PASS_LEVEL)
        with m.Else():
            m.d.comb += filter_low_gain.eq(filter_ramp_q)
        with m.If((filter_type_q3 == self.FILTER_HP) |
                  (filter_type_q3 == self.FILTER_NOTCH)):
            m.d.comb += filter_profile_gain.eq(self.FILTER_PASS_LEVEL - filter_low_gain)
        with m.If(self.filter_mode):
            m.d.sync += [
                filter_distance_q.eq(filter_distance),
                filter_half_width_q.eq(1024 + (self.effective_filter_width >> 1)),
                filter_band_q0.eq(filter_update_band),
                filter_type_q0.eq(self.filter_type),
                filter_edge_q.eq(filter_edge),
                filter_slope_factor_q.eq(filter_slope_factor),
                filter_band_q1.eq(filter_band_q0),
                filter_type_q1.eq(filter_type_q0),
                filter_slope_product_q.eq(filter_slope_product),
                filter_band_q2.eq(filter_band_q1),
                filter_type_q2.eq(filter_type_q1),
                filter_ramp_q.eq(filter_ramp),
                filter_band_q3.eq(filter_band_q2),
                filter_type_q3.eq(filter_type_q2),
                filter_level_array[filter_band_q3].eq(filter_profile_gain),
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
        state_filter_cv_setup = 22
        state_filter_cv_commit = 23
        state_filter_cv_route = 24
        state_output_product_commit = 25
        state_saturator_square_commit = 26
        state_drive_commit = 27
        state = Signal(state_shape, init=state_wait)
        band = Signal(range(self.N_BANDS))
        cutoff_band = Signal(range(self.N_BANDS))
        input_chan = Signal(range(4))
        cv_chan = Signal(range(4))
        cv_target_scan = Signal(range(7))
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
            cutoff_rport.addr.eq(frequency_array[cutoff_band]),
            cutoff_cur_raw.eq(cutoff_rport.data),
            mac_z.eq(mac_a_q * mac_b_q),
            svf_product_raw.eq(
                mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            alp_next.eq(svf_product_q + alp_cur),
            ahp_next.eq(svf_product_q + hp_offset_q),
            abp_next.eq(svf_product_q + abp_cur),
        ]

        mix_shape = signed(ASQ.as_shape().width + 5)
        main_acc = Signal(mix_shape)
        feedback_acc = Signal(mix_shape)
        group_acc = [Signal(mix_shape, name=f"group_acc{n}")
                     for n in range(self.N_GROUPS)]
        output_acc = [Signal(mix_shape, name=f"output_acc{n}") for n in range(4)]
        output_acc_array = Array(output_acc)
        output_next = Signal(mix_shape)
        output_source = Signal(range(self.N_GROUPS + 1))
        output_send_index = Signal(unsigned(5))
        output_send_gain = Signal(unsigned(7))
        output_send_gain_q = Signal(unsigned(7))
        output_send_product = Signal(signed(mix_shape.width + 7))
        output_send_term = Signal(mix_shape)
        output_send_term_q = Signal(mix_shape)
        term = Signal(mix_shape)
        term_q = Signal(mix_shape)
        enabled_term = Signal(mix_shape)
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
        limit_cap_safe = Signal(unsigned(16))
        clip_drive = Signal(mix_shape)
        clip_negative = Signal()
        clip_negative_q = Signal()
        clip_mag = Signal(unsigned(16))
        clip_mag_q = Signal(unsigned(16))
        clip_excess = Signal(unsigned(16))
        clip_excess_q = Signal(unsigned(16))
        clip_square = Signal(unsigned(32))
        clip_square_q = Signal(unsigned(32))
        clip_shaped_mag = Signal(unsigned(17))
        clip_output_mag = Signal(unsigned(16))
        clip_limited = Signal(ASQ)
        bank_input_soft = Signal(mix_shape)
        bank_input_limited = Signal(ASQ)
        output_limited = Signal(ASQ)
        feedback_term = Signal(dsp.mac.SQNative)
        feedback_term_q = Signal(dsp.mac.SQNative)
        dry_gain_term = Signal(mix_shape)
        input_gain_product_q = Signal(mix_shape)
        input_mix_acc = Signal(mix_shape)
        input_mix_next = Signal(mix_shape)
        input_gain_magnitude = Signal(unsigned(21))
        input_gain_meter_sample = Signal(unsigned(16))
        input_mix_sample = Signal(ASQ)
        input_mix_limited = Signal(ASQ)
        drive_term = Signal(signed(18))
        drive_term_q = Signal(signed(18))
        input_samples = [Signal(ASQ, name=f"input_sample{n}") for n in range(4)]
        cv_product = Signal(signed(18))
        cv_product_q = Signal(signed(18))
        cv_acc = Signal(signed(20))
        cv_acc_next = Signal(signed(20))
        bank_group_array = Array(self.bank_groups)
        band_enable_array = Array(self.band_enables)
        feedback_send_array = Array(self.feedback_sends)
        output_send_array = Array(self.output_sends)
        # Accumulate each group once while the bands are being processed, then
        # traverse the 4x5 send matrix after the final band.  Routing every
        # band through every output consumed 120 clocks/sample by itself and
        # exceeded the 312-clock budget at 192 kHz.
        output_sources = Array([
            *group_acc,
            Mux(sample_filter_mode, 0,
                input_mix_sample.as_value().as_signed()),
        ])
        output_source_signal = Signal(mix_shape)
        input_mode_array = Array(self.input_modes)
        cv_target_array = Array(self.cv_targets)
        filter_cutoff_raw = Signal(signed(19))
        filter_slope_raw = Signal(signed(19))
        filter_width_raw = Signal(signed(19))
        filter_drive_raw = Signal(signed(19))
        filter_cutoff_target = Signal(unsigned(16))
        filter_slope_target = Signal(unsigned(16))
        filter_width_target = Signal(unsigned(16))
        filter_drive_target = Signal(unsigned(16))
        filter_cutoff_target_q = Signal(unsigned(16), init=16384)
        filter_slope_target_q = Signal(unsigned(16), init=16384)
        filter_width_target_q = Signal(unsigned(16), init=12288)
        filter_drive_target_q = Signal(unsigned(16), init=16384)
        filter_cv_inputs = [Signal(ASQ, name=f"filter_cv_input{n}") for n in range(3)]
        filter_cv_terms = [Signal(signed(20), name=f"filter_cv_term{n}")
                           for n in range(5)]
        filter_cv_term_array = Array(filter_cv_terms)
        filter_cv_product_q = Signal(signed(18))
        filter_cv_acc = Signal(signed(20))
        filter_cv_acc_next = Signal(signed(20))
        filter_cv_source = Signal(range(3))
        filter_cv_destination = Signal(range(5))
        filter_cv_matrix_index = Signal(range(15))
        filter_cv_matrix_array = Array(self.filter_cv_matrix)
        m.d.comb += [
            filter_cutoff_raw.eq(self.filter_cutoff + filter_cv_terms[0]),
            filter_slope_raw.eq(self.filter_slope + filter_cv_terms[3]),
            filter_width_raw.eq(self.filter_width + filter_cv_terms[2]),
            filter_drive_raw.eq(self.DRIVE_FLOOR + self.drive + filter_cv_terms[4]),
            filter_cv_acc_next.eq(filter_cv_acc + filter_cv_product_q),
            filter_cv_matrix_index.eq(filter_cv_source + filter_cv_destination +
                                      (filter_cv_destination << 1)),
        ]
        for n in range(3):
            raw_cv = input_samples[n + 1].as_value().as_signed()
            with m.If((raw_cv > -256) & (raw_cv < 256)):
                m.d.comb += filter_cv_inputs[n].as_value().eq(0)
            with m.Else():
                m.d.comb += filter_cv_inputs[n].as_value().eq(raw_cv)
        for raw, target in (
                (filter_cutoff_raw, filter_cutoff_target),
                (filter_slope_raw, filter_slope_target),
                (filter_width_raw, filter_width_target),
                (filter_drive_raw, filter_drive_target)):
            minimum = self.DRIVE_FLOOR if raw is filter_drive_raw else 0
            with m.If(raw < minimum):
                m.d.comb += target.eq(minimum)
            with m.Elif(raw > 32767):
                m.d.comb += target.eq(32767)
            with m.Else():
                m.d.comb += target.eq(raw)
        m.d.comb += [
            level_with_cv.eq(levels[band] + group_cur),
            # SVF state carries two fractional guard bits beyond SQNative.
            # Dropping its raw 20-bit value directly into the 18-bit MAC input
            # truncated the sign bits instead of rescaling, producing a 4x
            # signal below |1.0| and a hard sign wrap above it. Rescale first,
            # then recover the established output gain after multiplication.
            band_sample.eq(abp_cur.as_value().as_signed() >> 2),
            term.eq(mac_z.as_value().as_signed() >>
                    (dsp.mac.SQNative.f_bits - 1)),
            feedback_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            dry_gain_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            input_gain_magnitude.eq(Mux(
                input_gain_product_q < 0,
                -input_gain_product_q,
                input_gain_product_q)),
            input_gain_meter_sample.eq(Mux(
                input_gain_magnitude > 32767, 32767,
                input_gain_magnitude)),
            input_mix_next.eq(input_mix_acc + input_gain_product_q),
            # Work in raw Q1.15 storage units before widening. Shifting the
            # fixed-point view directly and assigning it to a plain signed
            # guard-bit signal preserves the numeric value rather than the raw
            # half-scale representation, which accidentally drove every
            # resonator 2x harder.
            drive_term.eq(
                mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            x_drive.eq(drive_term_q +
                       feedback_term_q.as_value().as_signed()),
            limit_cap_safe.eq(Mux(self.limit_cap > 32767, 32767,
                                  self.limit_cap)),
            enabled_term.eq(Mux(
                sample_filter_mode | band_enable_array[band], term_q, 0)),
            main_next.eq(main_acc + enabled_term),
            filtered_next.eq(main_next - dry_sample.as_value().as_signed()),
            feedback_drive.eq(feedback_acc),
            cv_product.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            cv_acc_next.eq(cv_acc),
        ]
        m.d.comb += [
            output_send_index.eq(
                output_source + (output_chan << 2) + output_chan),
            output_send_gain.eq(output_send_array[output_send_index]),
            output_source_signal.eq(output_sources[output_source]),
            output_send_product.eq(output_source_signal * output_send_gain_q),
            output_send_term.eq(output_send_product >> 4),
            output_next.eq(output_acc_array[output_chan] + output_send_term_q),
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
        # Smooth-knee quadratic saturation belongs in the feedback loop. The
        # direct bank input must remain linear when feedback is zero; applying
        # this curve there pre-distorts every wet signal while DRY stays clean.
        # Below KNEE the feedback tap is exactly linear. Above it, subtract
        # excess^2 / 65536; CEIL remains the final emergency rail.
        m.d.comb += [
            clip_drive.eq(feedback_drive),
            clip_excess.eq(Mux(
                clip_mag > self.limit_knee,
                clip_mag - self.limit_knee, 0)),
            clip_square.eq(clip_excess_q * clip_excess_q),
            clip_shaped_mag.eq(Mux(
                clip_mag_q > self.limit_knee,
                clip_mag_q - (clip_square_q >> 16),
                clip_mag_q)),
            clip_output_mag.eq(Mux(
                clip_shaped_mag > limit_cap_safe,
                limit_cap_safe, clip_shaped_mag)),
        ]
        with m.If(clip_drive >= 32768):
            m.d.comb += [clip_negative.eq(0), clip_mag.eq(32768)]
        with m.Elif(clip_drive <= -32768):
            m.d.comb += [clip_negative.eq(1), clip_mag.eq(32768)]
        with m.Elif(clip_drive < 0):
            m.d.comb += [clip_negative.eq(1), clip_mag.eq(-clip_drive)]
        with m.Else():
            m.d.comb += [clip_negative.eq(0), clip_mag.eq(clip_drive)]
        with m.If(clip_negative_q):
            m.d.comb += clip_limited.as_value().eq(-clip_output_mag)
        with m.Else():
            m.d.comb += clip_limited.as_value().eq(clip_output_mag)

        # The feedback saturator above shapes the delayed wet signal. This is
        # a separate, deliberately simple conditioner on the signal entering
        # every resonator. It restores the transfer curve used by the last
        # hardware-clean build while retaining the wider pre-limit sum.
        with m.If(x_drive > self.INPUT_LIMIT_KNEE):
            m.d.comb += bank_input_soft.eq(
                self.INPUT_LIMIT_KNEE +
                ((x_drive - self.INPUT_LIMIT_KNEE) >> self.INPUT_LIMIT_SHIFT))
        with m.Elif(x_drive < -self.INPUT_LIMIT_KNEE):
            m.d.comb += bank_input_soft.eq(
                -self.INPUT_LIMIT_KNEE +
                ((x_drive + self.INPUT_LIMIT_KNEE) >> self.INPUT_LIMIT_SHIFT))
        with m.Else():
            m.d.comb += bank_input_soft.eq(x_drive)

        def limit_to_asq(source, target):
            with m.If(source > 32767):
                m.d.comb += target.as_value().eq(32767)
            with m.Elif(source < -32768):
                m.d.comb += target.as_value().eq(-32768)
            with m.Else():
                m.d.comb += target.as_value().eq(source)

        limit_to_asq(output_next, output_limited)
        limit_to_asq(input_mix_acc, input_mix_limited)
        # The input-plus-feedback sum stays wide through the transfer curve so
        # it cannot wrap before this final rail clamp.
        limit_to_asq(bank_input_soft, bank_input_limited)

        # Pipeline magnitude, square, and clamp/sign across three short stages.
        # The feedback sum is stable for many routing cycles; x gets explicit
        # settling states below before clip_limited is captured.
        m.d.sync += [
            clip_negative_q.eq(clip_negative),
            clip_mag_q.eq(clip_mag),
            clip_excess_q.eq(clip_excess),
            clip_square_q.eq(clip_square),
        ]
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
                        with m.If(diff > self.PARAM_SLEW_STEP):
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
                                smooth_levels[n].eq(Mux(
                                    self.filter_mode, filter_levels[n],
                                    self.levels[n])),
                                active_levels[n].eq(Mux(
                                    self.filter_mode, filter_levels[n],
                                    self.levels[n])),
                            ]
                    with m.If(drive_diff > self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_drive.eq(
                            smooth_drive + self.PARAM_SLEW_STEP)
                    with m.Elif(drive_diff < -self.PARAM_SLEW_STEP):
                        m.d.sync += smooth_drive.eq(
                            smooth_drive - self.PARAM_SLEW_STEP)
                    with m.Else():
                        m.d.sync += smooth_drive.eq(self.drive)
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
                    with m.If(~self.filter_mode):
                        m.d.sync += self.effective_drive.eq(effective_drive)
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
                        m.d.sync += [
                            filter_cv_source.eq(0),
                            filter_cv_destination.eq(0),
                            filter_cv_acc.eq(0),
                            state.eq(state_filter_cv_setup),
                        ]
                    with m.Else():
                        m.d.sync += [
                            mac_a_q.eq(self.i.payload[0]),
                            mac_b_q.eq(smooth_cv_depths[0]),
                            state.eq(state_cv_commit),
                        ]

            with m.Case(state_filter_cv_setup):
                with m.Switch(filter_cv_source):
                    for n in range(3):
                        with m.Case(n):
                            m.d.sync += [
                                mac_a_q.eq(filter_cv_inputs[n]),
                                mac_b_q.as_value().eq(
                                    filter_cv_matrix_array[filter_cv_matrix_index] << 8),
                            ]
                m.d.sync += state.eq(state_filter_cv_commit)

            with m.Case(state_filter_cv_commit):
                m.d.sync += [
                    filter_cv_product_q.eq(cv_product),
                    state.eq(state_filter_cv_route),
                ]

            with m.Case(state_filter_cv_route):
                with m.If(filter_cv_source != 2):
                    m.d.sync += [
                        filter_cv_acc.eq(filter_cv_acc_next),
                        filter_cv_source.eq(filter_cv_source + 1),
                        state.eq(state_filter_cv_setup),
                    ]
                with m.Else():
                    m.d.sync += [
                        filter_cv_term_array[filter_cv_destination].eq(filter_cv_acc_next),
                        filter_cv_acc.eq(0),
                        filter_cv_source.eq(0),
                    ]
                    with m.If(filter_cv_destination != 4):
                        m.d.sync += [
                            filter_cv_destination.eq(filter_cv_destination + 1),
                            state.eq(state_filter_cv_setup),
                        ]
                    with m.Else():
                        m.d.sync += state.eq(state_filter_params)

            with m.Case(state_filter_params):
                for n in range(self.N_GROUPS):
                    m.d.sync += [group_cv_terms[n].eq(0), self.effective_groups[n].eq(0)]
                m.d.sync += [
                    resonance_cv_term.eq(filter_cv_terms[1]),
                    feedback_cv_term.eq(0),
                    drive_cv_term.eq(0),
                ]
                m.d.sync += [
                    filter_cutoff_target_q.eq(filter_cutoff_target),
                    filter_slope_target_q.eq(filter_slope_target),
                    filter_width_target_q.eq(filter_width_target),
                    filter_drive_target_q.eq(filter_drive_target),
                ]
                for target, effective in (
                        (filter_cutoff_target_q, self.effective_filter_cutoff),
                        (filter_slope_target_q, self.effective_filter_slope),
                        (filter_width_target_q, self.effective_filter_width),
                        (filter_drive_target_q, self.effective_drive)):
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
                        with m.Case(self.CV_TARGET_DRIVE):
                            with m.If(cv_acc_next > 65535):
                                m.d.sync += drive_cv_term.eq(65535)
                            with m.Elif(cv_acc_next < -65536):
                                m.d.sync += drive_cv_term.eq(-65536)
                            with m.Else():
                                m.d.sync += drive_cv_term.eq(cv_acc_next)
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
                    with m.If(cv_target_scan != 6):
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
                for n in range(4):
                    with m.If(input_chan == n):
                        with m.If(self.input_modes[n] == self.INPUT_MODE_CV):
                            m.d.sync += self.input_meters[n].eq(input_samples[n])
                        with m.Elif(input_gain_meter_sample >= self.input_meters[n]):
                            m.d.sync += self.input_meters[n].eq(
                                input_gain_meter_sample)
                        with m.Elif(self.input_meters[n] > 0):
                            m.d.sync += self.input_meters[n].eq(
                                self.input_meters[n] -
                                (self.input_meters[n].as_unsigned() >> 14) - 1)
                        with m.Else():
                            m.d.sync += self.input_meters[n].eq(0)
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
                            mac_a_q.as_value().eq(
                                input_mix_limited.as_value().as_signed()),
                            mac_b_q.as_value().eq(self.effective_drive),
                            band.eq(0),
                            cutoff_band.eq(0),
                            oversample.eq(0),
                            state.eq(state_drive_commit),
                ]

            with m.Case(state_drive_commit):
                m.d.sync += [
                            drive_term_q.eq(drive_term),
                            mac_a_q.eq(feedback_sample),
                            mac_b_q.eq(feedback_gain >> 1),
                            state.eq(state_feedback_commit),
                ]

            with m.Case(state_feedback_commit):
                m.d.sync += [
                    feedback_term_q.eq(feedback_term),
                    state.eq(state_dry_gain_commit),
                ]

            with m.Case(state_dry_gain_commit):
                # Retain the established sample schedule; the feedback
                # saturator pipeline settles continuously in the background.
                m.d.sync += state.eq(state_saturator_square_commit)

            with m.Case(state_saturator_square_commit):
                # Capture the DSP square before the clamp/sign stage.
                m.d.sync += state.eq(state_feedback_limit_commit)

            with m.Case(state_feedback_limit_commit):
                m.d.sync += [
                    x.eq(bank_input_limited),
                    dry_sample.eq(input_mix_sample),
                    main_acc.eq(input_mix_sample),
                    feedback_acc.eq(0),
                    state.eq(state_mac0_setup),
                ]
                for n in range(self.N_GROUPS):
                    m.d.sync += group_acc[n].eq(0)
                for n in range(4):
                    m.d.sync += output_acc[n].eq(0)

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
                    cutoff_band.eq(Mux(
                        band == self.N_BANDS - 1, 0, band + 1)),
                    state.eq(state_mix_gain_commit),
                ]

            with m.Case(state_mix_gain_commit):
                m.d.sync += [
                    term_q.eq(term),
                    state.eq(state_mix_commit),
                ]

            with m.Case(state_mix_commit):
                m.d.sync += main_acc.eq(main_next)
                with m.If(feedback_send_array[band]):
                    m.d.sync += feedback_acc.eq(feedback_acc + enabled_term)
                for n in range(self.N_GROUPS):
                    with m.If(bank_group_array[band][n]):
                        m.d.sync += group_acc[n].eq(group_acc[n] + enabled_term)
                for n in range(self.N_BANDS):
                    with m.If(band == n):
                        # Report the same registered gain consumed by the mix
                        # MAC instead of rebuilding the band/group/CV clamp at
                        # the end of the band cycle. Disabled BANK bands keep
                        # their stored shape visible; the BANDS page carries
                        # the enable state and the shared accumulator gate
                        # suppresses their audio contribution.
                        m.d.sync += self.effective_levels[n].eq(level_cur_q)
                with m.If(band == self.N_BANDS - 1):
                    m.d.sync += [
                        output_chan.eq(0),
                        output_source.eq(0),
                        state.eq(state_output_route_commit),
                    ]
                with m.Else():
                    m.d.sync += [
                        band.eq(band + 1),
                        state.eq(state_mac0_setup),
                    ]

            with m.Case(state_output_route_commit):
                m.d.sync += [
                    output_send_gain_q.eq(output_send_gain),
                    state.eq(state_output_limit_commit),
                ]

            with m.Case(state_output_limit_commit):
                m.d.sync += [
                    output_send_term_q.eq(output_send_term),
                    state.eq(state_output_product_commit),
                ]

            with m.Case(state_output_product_commit):
                m.d.sync += output_acc_array[output_chan].eq(output_next)
                with m.If(output_source == self.N_GROUPS):
                    m.d.sync += output_q_array[output_chan].eq(output_limited)
                with m.If(output_source != self.N_GROUPS):
                    m.d.sync += [
                        output_source.eq(output_source + 1),
                        state.eq(state_output_route_commit),
                    ]
                with m.Elif(output_chan != 3):
                    m.d.sync += [
                        output_chan.eq(output_chan + 1),
                        output_source.eq(0),
                        state.eq(state_output_route_commit),
                    ]
                with m.Else():
                    m.d.sync += [
                        feedback_sample.eq(clip_limited),
                        out_valid.eq(1),
                        state.eq(state_wait),
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
    CLICK_LOCKOUT_CYCLES = 7_200_000
    INPUT_UNITY = RezoCore.INPUT_UNITY
    INPUT_MAX = RezoCore.INPUT_MAX
    INPUT_UNITY_POS = RezoCore.INPUT_UNITY_POS
    TARGET_PAGE = 0
    TARGET_PRESET = 1
    TARGET_BAND_BASE = 2
    TARGET_DRIVE = RezoCore.N_BANDS + 2
    TARGET_RESONANCE = RezoCore.N_BANDS + 3
    TARGET_FEEDBACK = RezoCore.N_BANDS + 4
    TARGET_LIMIT_KNEE = RezoCore.N_BANDS + 5
    TARGET_LIMIT_CAP = RezoCore.N_BANDS + 6
    TARGET_DAMP = RezoCore.N_BANDS + 7
    TARGET_INPUT_BASE = RezoCore.N_BANDS + 8
    TARGET_GROUP_BASE = RezoCore.N_BANDS + 20
    TARGET_OUTPUT_BASE = RezoCore.N_BANDS + 30
    TARGET_MODE = RezoCore.N_BANDS + 50
    TARGET_FILTER_TYPE = RezoCore.N_BANDS + 51
    TARGET_FILTER_CUTOFF = RezoCore.N_BANDS + 52
    TARGET_FILTER_SLOPE = RezoCore.N_BANDS + 53
    TARGET_FILTER_WIDTH = RezoCore.N_BANDS + 54
    TARGET_FILTER_CV_BASE = RezoCore.N_BANDS + 55
    TARGET_FEEDBACK_SEND_BASE = RezoCore.N_BANDS + 70
    TARGET_PALETTE = RezoCore.N_BANDS + 80
    TARGET_SAVE_DEFAULT = RezoCore.N_BANDS + 81
    TARGET_BAND_LAYOUT = RezoCore.N_BANDS + 82
    TARGET_BAND_ENABLE_BASE = RezoCore.N_BANDS + 83
    TARGET_BAND_FREQ_BASE = RezoCore.N_BANDS + 93
    TARGET_OUTPUT_ROW_BASE = RezoCore.N_BANDS + 103
    TARGET_OUTPUT_COL_BASE = RezoCore.N_BANDS + 107
    TARGET_OUTPUT_DRY_COL = RezoCore.N_BANDS + 111
    N_TARGETS = RezoCore.N_BANDS + 112

    # Stable, versioned packed state layout. Continuous controls edited in
    # 1/256 steps store their significant high byte; input gains retain all
    # 16 bits because their exact unity point is 0xCCCC. Matrix/routing fields
    # are bit-packed at their native widths. V1 therefore uses only 42 of the
    # reserved 1024 words and restores every user-visible setting exactly.
    STATE_LEVELS_BASE = 0       # 5 words: ten signed high bytes
    STATE_DRIVES = 5            # bank, filter high bytes
    STATE_RESONANCE_FEEDBACK = 6
    STATE_CUTOFF_SLOPE = 7
    STATE_WIDTH_KNEE = 8
    STATE_CAP_FLAGS = 9         # cap high byte + damp/mode/type
    STATE_FILTER_CV_BASE = 10   # 8 words: fifteen signed bytes
    STATE_INPUT_GAIN_BASE = 18  # 4 full-width words
    STATE_CV_DEPTH_BASE = 22    # 2 words: four signed high bytes
    STATE_INPUT_CONFIG = 24     # four modes + four 3-bit targets
    STATE_BANK_GROUP_BASE = 25  # 3 words: ten 4-bit indices
    STATE_FEEDBACK_PRESET = 28  # ten sends + preset + palette
    STATE_OUTPUT_BASE = 29      # 13 words: forty 5-bit sends
    STATE_WORDS_V1 = 42
    STATE_BAND_CONFIG_BASE = 42  # 4 words: user frequencies, enables, layout
    STATE_WORDS_V2 = 46
    STATE_CAPACITY_WORDS = 1024

    @classmethod
    def legacy_band_config_words(cls):
        """V2 tail used when importing a V1 state record."""
        packed = 0
        shift = 0
        for frequency in RezoCore.LEGACY_FREQS_HZ:
            packed |= (RezoCore.frequency_index(frequency) >>
                       RezoCore.FREQ_FINE_WIDTH) << shift
            shift += RezoCore.FREQ_COARSE_WIDTH
        packed |= ((1 << RezoCore.N_BANDS) - 1) << shift
        shift += RezoCore.N_BANDS
        packed |= RezoCore.LAYOUT_LEGACY << shift
        return tuple((packed >> (16 * n)) & 0xffff for n in range(4))

    def __init__(self):
        super().__init__({
            "enc_i": In(1),
            "enc_q": In(1),
            "button": In(1),
            "state_read_data": Out(unsigned(16)),
            "state_write_data": In(unsigned(16)),
            "state_shift_enable": In(1),
            "state_shift_load": In(1),
            "save_default_request": Out(1),
            "save_default_available": In(1),
            "save_default_busy": In(1),
            "save_default_done": In(1),
            "save_default_error": In(1),
            "save_default_status": Out(unsigned(2)),
            "levels": Out(data.ArrayLayout(signed(16), RezoCore.N_BANDS)),
            "band_enables": Out(data.ArrayLayout(unsigned(1), RezoCore.N_BANDS)),
            "band_frequencies": Out(data.ArrayLayout(
                unsigned(RezoCore.FREQ_INDEX_WIDTH), RezoCore.N_BANDS)),
            "frequency_layout": Out(unsigned(2)),
            "frequency_layout_preview": Out(unsigned(2)),
            "frequency_preview": Out(unsigned(RezoCore.FREQ_INDEX_WIDTH)),
            "drive": Out(unsigned(16)),
            "resonance": Out(unsigned(16)),
            "feedback": Out(unsigned(16)),
            "filter_mode": Out(1),
            "filter_type": Out(unsigned(2)),
            "filter_cutoff": Out(unsigned(16)),
            "filter_slope": Out(unsigned(16)),
            "filter_width": Out(unsigned(16)),
            "filter_cv_matrix": Out(data.ArrayLayout(signed(8), 15)),
            "limit_knee": Out(unsigned(16)),
            "limit_cap": Out(unsigned(16)),
            "damp_mode": Out(unsigned(3)),
            "input_gains": Out(data.ArrayLayout(unsigned(16), 4)),
            "input_modes": Out(data.ArrayLayout(unsigned(1), 4)),
            "cv_targets": Out(data.ArrayLayout(unsigned(3), 4)),
            "cv_depths": Out(data.ArrayLayout(signed(16), 4)),
            "bank_groups": Out(data.ArrayLayout(unsigned(4), RezoCore.N_BANDS)),
            "feedback_sends": Out(data.ArrayLayout(unsigned(1), RezoCore.N_BANDS)),
            "output_sends": Out(data.ArrayLayout(unsigned(5), 20)),
            "selected": Out(unsigned(7)),
            "page": Out(unsigned(3)),
            "preset": Out(unsigned(3)),
            "palette": Out(unsigned(3)),
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
        preset_level = RezoHardwareUI.PRESET_LEVEL >> 8
        with m.Switch(preset):
            with m.Case(0):  # all bands
                for level in levels:
                    m.d.sync += level.eq(preset_level)
            with m.Case(1):  # odd bands
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(preset_level if n & 1 else 0)
            with m.Case(2):  # even bands
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(0 if n & 1 else preset_level)
            with m.Case(3):  # lows
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(preset_level if n < 4 else 0)
            with m.Case(4):  # mids
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(preset_level if 3 <= n <= 6 else 0)
            with m.Case(5):  # highs
                for n, level in enumerate(levels):
                    m.d.sync += level.eq(preset_level if n >= 6 else 0)
            with m.Case(6):  # zero
                for level in levels:
                    m.d.sync += level.eq(0)

    def elaborate(self, platform):
        m = Module()

        # Encoder-edited controls move on 1/256 boundaries. Retaining their
        # coarse positions directly halves comparator/add widths and removes
        # 152 inactive low-byte registers. Outputs expand back to the original
        # 16-bit values, including the asymmetric positive endpoints.
        levels = [Signal(signed(8), init=self.PRESET_LEVEL >> 8,
                         name=f"ui_level{n}")
                  for n in range(RezoCore.N_BANDS)]
        band_enables = [Signal(init=1, name=f"ui_band_enable{n}")
                        for n in range(RezoCore.N_BANDS)]
        octave_indices = tuple(RezoCore.frequency_index(frequency)
                               for frequency in RezoCore.OCTAVE_FREQS_HZ)
        legacy_indices = tuple(RezoCore.frequency_index(frequency)
                               for frequency in RezoCore.LEGACY_FREQS_HZ)
        percept_indices = tuple(RezoCore.frequency_index(frequency)
                                for frequency in RezoCore.PERCEPT_FREQS_HZ)
        band_frequencies = [
            Signal(unsigned(RezoCore.FREQ_INDEX_WIDTH), init=octave_indices[n],
                   name=f"ui_band_frequency{n}")
            for n in range(RezoCore.N_BANDS)
        ]
        frequency_layout = Signal(unsigned(2), init=RezoCore.LAYOUT_OCTAVE)
        layout_preview = Signal(unsigned(2), init=RezoCore.LAYOUT_OCTAVE)
        frequency_preview = Signal(unsigned(RezoCore.FREQ_INDEX_WIDTH))
        layout_load_active = Signal()
        layout_load_index = Signal(range(RezoCore.N_BANDS + 1))
        layout_load_target = Signal(unsigned(2))
        layout_load_prefetched = Signal()
        state_shift_load_q = Signal()
        layout_frequency_init = [0] * 48
        for layout, table in enumerate(
                (legacy_indices, octave_indices, percept_indices)):
            for band, frequency in enumerate(table):
                layout_frequency_init[(layout << 4) | band] = frequency
        m.submodules.layout_frequency_mem = layout_frequency_mem = Memory(
            shape=unsigned(RezoCore.FREQ_INDEX_WIDTH),
            depth=len(layout_frequency_init), init=layout_frequency_init,
            attrs={"ram_style": "block"})
        layout_frequency_rport = layout_frequency_mem.read_port()
        layout_frequency_addr_band = Signal(unsigned(4))
        m.d.comb += [
            layout_frequency_addr_band.eq(Mux(
                layout_load_prefetched,
                layout_load_index + 1,
                layout_load_index)),
            layout_frequency_rport.addr.eq(Cat(
                layout_frequency_addr_band, layout_load_target)),
        ]
        with m.If(layout_load_active):
            with m.If(layout_load_index == RezoCore.N_BANDS):
                m.d.sync += [
                    layout_load_active.eq(0),
                    layout_load_prefetched.eq(0),
                    frequency_layout.eq(layout_load_target),
                ]
            with m.Elif(~layout_load_prefetched):
                m.d.sync += layout_load_prefetched.eq(1)
            with m.Else():
                m.d.sync += [
                    Array(band_frequencies)[layout_load_index].eq(
                        layout_frequency_rport.data),
                    layout_load_index.eq(layout_load_index + 1),
                ]
        m.d.sync += state_shift_load_q.eq(self.state_shift_load)
        # Older V2 factory-layout records retained a dormant USER vector.
        # Materialize the selected factory vector after restore so the working
        # registers always contain the frequencies that the DSP is using.
        with m.If(state_shift_load_q & ~self.state_shift_load &
                  (frequency_layout != RezoCore.LAYOUT_USER)):
            m.d.sync += [
                layout_load_active.eq(1),
                layout_load_index.eq(0),
                layout_load_target.eq(frequency_layout),
                layout_load_prefetched.eq(0),
            ]
        bank_drive = Signal(unsigned(8), init=RezoCore.DRIVE_DEFAULT >> 8)
        filter_drive = Signal(unsigned(8), init=RezoCore.DRIVE_DEFAULT >> 8)
        drive = Signal(unsigned(16))
        resonance = Signal(unsigned(8), init=8192 >> 8)
        feedback = Signal(unsigned(8), init=0)
        filter_mode = Signal(init=0)
        filter_type = Signal(unsigned(2), init=RezoCore.FILTER_LP)
        filter_cutoff = Signal(unsigned(8), init=16384 >> 8)
        filter_slope = Signal(unsigned(8), init=16384 >> 8)
        filter_width = Signal(unsigned(8), init=12288 >> 8)
        filter_cv_matrix = [Signal(signed(8), init=0,
                                   name=f"ui_filter_cv_matrix{n}")
                            for n in range(15)]
        limit_knee = Signal(unsigned(8), init=8192 >> 8)
        limit_cap = Signal(unsigned(8), init=28672 >> 8)
        damp_mode = Signal(unsigned(3), init=3)
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
        feedback_sends = [Signal(init=1, name=f"ui_feedback_send{n}")
                          for n in range(RezoCore.N_BANDS)]
        initial_output_masks = (0b01111, 0b00101, 0b01010, 0b10000)
        bank_output_sends = [
            Signal(unsigned(5),
                   init=16 if source < RezoCore.N_GROUPS and
                              initial_output_masks[output] & (1 << source) else 0,
                   name=f"ui_bank_output_send{output}_{source}")
            for output in range(4) for source in range(RezoCore.N_GROUPS + 1)
        ]
        filter_output_masks = (0b1111, 0b0101, 0b1010, 0b0000)
        filter_output_sends = [
            Signal(unsigned(5),
                   init=16 if source < RezoCore.N_GROUPS and
                              filter_output_masks[output] & (1 << source) else 0,
                   name=f"ui_filter_output_send{output}_{source}")
            for output in range(4) for source in range(RezoCore.N_GROUPS + 1)
        ]
        output_sends = [Signal(unsigned(5), name=f"ui_output_send{n}")
                        for n in range(20)]
        for n in range(RezoCore.N_BANDS):
            m.d.comb += bank_groups[n].eq(
                bank_group_indices[n] ^ (bank_group_indices[n] >> 1))
        for n in range(20):
            m.d.comb += output_sends[n].eq(
                Mux(filter_mode, filter_output_sends[n], bank_output_sends[n]))
        drive_position = Signal(unsigned(8))
        m.d.comb += [
            drive_position.eq(Mux(filter_mode, filter_drive, bank_drive)),
            drive.eq(Mux(drive_position == 96, RezoCore.DRIVE_MAX,
                         drive_position << 8)),
        ]
        selected = Signal(range(self.N_TARGETS), init=self.TARGET_PAGE)
        page = Signal(unsigned(3), init=0)
        preset = Signal(range(7), init=0)
        palette = Signal(range(5), init=0)
        next_preset = Signal(range(7))
        next_selected = Signal(range(self.N_TARGETS))
        bank_target_visible = Signal()
        tune_target_visible = Signal()
        feedback_send_target = Signal()
        input_target_visible = Signal()
        group_target_visible = Signal()
        output_target_visible = Signal()
        output_cell_target = Signal()
        output_row_target = Signal()
        output_col_target = Signal()
        output_dry_target = Signal()
        filter_target_visible = Signal()
        filter_cv_target_visible = Signal()
        advanced_target_visible = Signal()
        band_edit_target_visible = Signal()
        band_enable_target = Signal()
        band_frequency_target = Signal()
        bank_band_target = Signal()
        bank_band_index = Signal(range(RezoCore.N_BANDS))
        bank_band_enabled = Signal(init=1)
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
        output_edit_pending = Signal()
        output_edit_index = Signal(unsigned(5))
        output_edit_direction = Signal()
        output_relative_active = Signal()
        output_relative_step = Signal(unsigned(3))
        output_relative_index = Signal(unsigned(5))
        output_relative_column = Signal()
        output_relative_direction = Signal()
        detent_timer = Signal(unsigned(21), init=(1 << 21) - 1)
        accelerated_edit_step = Signal(unsigned(4), init=1)
        edit_repeat_remaining = Signal(unsigned(3))
        continuous_accel_target = Signal()
        m.d.comb += continuous_accel_target.eq(editing & (
            bank_band_target |
            (selected == self.TARGET_DRIVE) |
            (selected == self.TARGET_RESONANCE) |
            (selected == self.TARGET_FEEDBACK) |
            (selected == self.TARGET_LIMIT_KNEE) |
            (selected == self.TARGET_LIMIT_CAP) |
            (selected == self.TARGET_FILTER_CUTOFF) |
            (selected == self.TARGET_FILTER_SLOPE) |
            (selected == self.TARGET_FILTER_WIDTH) |
            ((selected == self.TARGET_INPUT_BASE + 1) &
             (input_modes[0] != RezoCore.INPUT_MODE_CV)) |
            ((selected == self.TARGET_INPUT_BASE + 4) &
             (input_modes[1] != RezoCore.INPUT_MODE_CV)) |
            ((selected == self.TARGET_INPUT_BASE + 7) &
             (input_modes[2] != RezoCore.INPUT_MODE_CV)) |
            ((selected == self.TARGET_INPUT_BASE + 10) &
             (input_modes[3] != RezoCore.INPUT_MODE_CV)) |
            (selected == self.TARGET_INPUT_BASE + 2) |
            (selected == self.TARGET_INPUT_BASE + 5) |
            (selected == self.TARGET_INPUT_BASE + 8) |
            (selected == self.TARGET_INPUT_BASE + 11)))
        m.d.sync += output_edit_pending.eq(0)
        with m.If(output_relative_active):
            m.d.sync += [
                output_edit_pending.eq(1),
                output_edit_index.eq(output_relative_index),
                output_edit_direction.eq(output_relative_direction),
            ]
            with m.If(output_relative_step == Mux(
                    output_relative_column, 3, Mux(filter_mode, 3, 4))):
                m.d.sync += output_relative_active.eq(0)
            with m.Else():
                m.d.sync += [
                    output_relative_step.eq(output_relative_step + 1),
                    output_relative_index.eq(
                        output_relative_index +
                        Mux(output_relative_column, 5, 1)),
                ]
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
            self.save_default_request.eq(0),
            iq_prev.eq(iq_sync),
        ]
        with m.If(edit_repeat_remaining != 0):
            m.d.sync += [
                edit_step.eq(1),
                edit_repeat_remaining.eq(edit_repeat_remaining - 1),
            ]
        # Keep the last explicit-save result visible. The journal's done and
        # error outputs are intentionally single-cycle pulses, much too short
        # for either the 15 Hz text refresh or a person to observe directly.
        with m.If(self.save_default_busy):
            m.d.sync += self.save_default_status.eq(1)  # SAVING
        with m.Elif(self.save_default_done):
            m.d.sync += self.save_default_status.eq(2)  # SAVED
        with m.Elif(self.save_default_error):
            m.d.sync += self.save_default_status.eq(3)  # ERROR
        with m.If(detent_timer != (1 << 21) - 1):
            m.d.sync += detent_timer.eq(detent_timer + 1)
        with m.If(iq_sync != iq_prev):
            with m.If(transition_delta != 0):
                with m.If(iq_prev_is_detent & ~iq_is_detent):
                    m.d.sync += [
                        detent_armed.eq(1),
                        detent_acc.eq(transition_delta),
                    ]
                with m.Elif(iq_is_detent & detent_armed):
                    m.d.sync += [
                        detent_timer.eq(0),
                        accelerated_edit_step.eq(
                            Mux(detent_timer < 1_200_000, 8, 1)),
                        edit_repeat_remaining.eq(Mux(
                            (detent_timer < 1_200_000) &
                            continuous_accel_target,
                            7, 0)),
                    ]
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

        # Slow turns retain single-step precision. Faster turns accelerate
        # high-resolution frequency and matrix edits, never navigation or
        # toggles.
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
                click_lockout.eq(self.CLICK_LOCKOUT_CYCLES),
            ]

        m.d.comb += next_preset.eq(preset)
        with m.If(edit_direction):
            m.d.comb += next_preset.eq(Mux(preset == 6, 0, preset + 1))
        with m.Else():
            m.d.comb += next_preset.eq(Mux(preset == 0, 6, preset - 1))

        dry_target_expr = Const(0)
        for output in range(4):
            dry_target_expr = dry_target_expr | (
                selected == self.TARGET_OUTPUT_BASE + output * 5 + 4)
        m.d.comb += [
            bank_target_visible.eq((selected <= self.TARGET_FEEDBACK) |
                                   (selected == self.TARGET_MODE)),
            feedback_send_target.eq(
                (selected >= self.TARGET_FEEDBACK_SEND_BASE) &
                (selected < self.TARGET_FEEDBACK_SEND_BASE + RezoCore.N_BANDS)),
            tune_target_visible.eq((selected == self.TARGET_PAGE) |
                                   ((selected >= self.TARGET_LIMIT_KNEE) &
                                    (selected <= self.TARGET_DAMP)) |
                                   feedback_send_target),
            input_target_visible.eq((selected == self.TARGET_PAGE) |
                                    ((selected >= self.TARGET_INPUT_BASE) &
                                     (selected < self.TARGET_INPUT_BASE + 12))),
            group_target_visible.eq((selected == self.TARGET_PAGE) |
                                    ((selected >= self.TARGET_GROUP_BASE) &
                                     (selected < self.TARGET_GROUP_BASE + RezoCore.N_BANDS))),
            output_dry_target.eq(dry_target_expr),
            output_cell_target.eq(
                (selected >= self.TARGET_OUTPUT_BASE) &
                (selected < self.TARGET_OUTPUT_BASE + 20) &
                (~filter_mode | ~output_dry_target)),
            output_row_target.eq(
                (page == 4) &
                (selected >= self.TARGET_OUTPUT_ROW_BASE) &
                (selected < self.TARGET_OUTPUT_ROW_BASE + 4)),
            output_col_target.eq(
                (page == 4) &
                (((selected >= self.TARGET_OUTPUT_COL_BASE) &
                  (selected < self.TARGET_OUTPUT_COL_BASE + 4)) |
                 ((selected == self.TARGET_OUTPUT_DRY_COL) & ~filter_mode))),
            output_target_visible.eq((selected == self.TARGET_PAGE) |
                                     output_cell_target |
                                     output_row_target |
                                     output_col_target),
            filter_target_visible.eq((selected == self.TARGET_PAGE) |
                                     (selected == self.TARGET_MODE) |
                                     ((selected >= self.TARGET_FILTER_TYPE) &
                                      (selected <= self.TARGET_FILTER_WIDTH)) |
                                     (selected == self.TARGET_DRIVE) |
                                     (selected == self.TARGET_RESONANCE)),
            filter_cv_target_visible.eq(
                (selected == self.TARGET_PAGE) |
                ((selected >= self.TARGET_FILTER_CV_BASE) &
                 (selected < self.TARGET_FILTER_CV_BASE + 15))),
            advanced_target_visible.eq(
                (selected == self.TARGET_PAGE) |
                (selected == self.TARGET_PALETTE) |
                (selected == self.TARGET_SAVE_DEFAULT)),
            band_enable_target.eq(
                (selected >= self.TARGET_BAND_ENABLE_BASE) &
                (selected < self.TARGET_BAND_ENABLE_BASE + RezoCore.N_BANDS)),
            band_frequency_target.eq(
                (selected >= self.TARGET_BAND_FREQ_BASE) &
                (selected < self.TARGET_BAND_FREQ_BASE + RezoCore.N_BANDS)),
            band_edit_target_visible.eq(
                (selected == self.TARGET_PAGE) |
                (selected == self.TARGET_BAND_LAYOUT) |
                band_enable_target | band_frequency_target),
            bank_band_target.eq(0),
            bank_band_index.eq(0),
            next_selected.eq(selected),
        ]
        with m.If((page == 0) &
                  (selected >= self.TARGET_BAND_BASE) &
                  (selected < self.TARGET_BAND_BASE + RezoCore.N_BANDS)):
            m.d.comb += [
                bank_band_target.eq(1),
                bank_band_index.eq(selected - self.TARGET_BAND_BASE),
            ]
        with m.Elif((page == 1) & feedback_send_target):
            m.d.comb += [
                bank_band_target.eq(1),
                bank_band_index.eq(selected - self.TARGET_FEEDBACK_SEND_BASE),
            ]
        with m.Elif((page == 3) &
                    (selected >= self.TARGET_GROUP_BASE) &
                    (selected < self.TARGET_GROUP_BASE + RezoCore.N_BANDS)):
            m.d.comb += [
                bank_band_target.eq(1),
                bank_band_index.eq(selected - self.TARGET_GROUP_BASE),
            ]
        m.d.comb += bank_band_enabled.eq(
            filter_mode | ~bank_band_target |
            Array(band_enables)[bank_band_index])
        with m.If(page == 0):
            with m.If(filter_mode):
                with m.If(edit_direction):
                    with m.If(~filter_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_TYPE)
                    with m.Elif(selected == self.TARGET_FILTER_TYPE):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Elif(selected == self.TARGET_MODE):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_CUTOFF)
                    with m.Elif(selected == self.TARGET_FILTER_CUTOFF):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_SLOPE)
                    with m.Elif(selected == self.TARGET_FILTER_SLOPE):
                        m.d.comb += next_selected.eq(
                            Mux(filter_type >= RezoCore.FILTER_BP,
                                self.TARGET_FILTER_WIDTH, self.TARGET_DRIVE))
                    with m.Elif(selected == self.TARGET_FILTER_WIDTH):
                        m.d.comb += next_selected.eq(self.TARGET_DRIVE)
                    with m.Elif(selected == self.TARGET_DRIVE):
                        m.d.comb += next_selected.eq(self.TARGET_RESONANCE)
                    with m.Else():
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    with m.If(~filter_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_RESONANCE)
                    with m.Elif(selected == self.TARGET_RESONANCE):
                        m.d.comb += next_selected.eq(self.TARGET_DRIVE)
                    with m.Elif(selected == self.TARGET_DRIVE):
                        m.d.comb += next_selected.eq(
                            Mux(filter_type >= RezoCore.FILTER_BP,
                                self.TARGET_FILTER_WIDTH, self.TARGET_FILTER_SLOPE))
                    with m.Elif(selected == self.TARGET_FILTER_WIDTH):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_SLOPE)
                    with m.Elif(selected == self.TARGET_FILTER_SLOPE):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_CUTOFF)
                    with m.Elif(selected == self.TARGET_FILTER_CUTOFF):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Elif(selected == self.TARGET_MODE):
                        m.d.comb += next_selected.eq(self.TARGET_FILTER_TYPE)
                    with m.Else():
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
            with m.Else():
                with m.If(edit_direction):
                    with m.If(~bank_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_PRESET)
                    with m.Elif(selected == self.TARGET_PRESET):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Elif(selected == self.TARGET_MODE):
                        m.d.comb += next_selected.eq(self.TARGET_BAND_BASE)
                    with m.Elif(selected ==
                                self.TARGET_BAND_BASE + RezoCore.N_BANDS - 1):
                        m.d.comb += next_selected.eq(self.TARGET_DRIVE)
                    with m.Elif(selected == self.TARGET_DRIVE):
                        m.d.comb += next_selected.eq(self.TARGET_RESONANCE)
                    with m.Elif(selected == self.TARGET_FEEDBACK):
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
                    with m.Else():
                        m.d.comb += next_selected.eq(selected + 1)
                with m.Else():
                    with m.If(~bank_target_visible | (selected == self.TARGET_PAGE)):
                        m.d.comb += next_selected.eq(self.TARGET_FEEDBACK)
                    with m.Elif(selected == self.TARGET_MODE):
                        m.d.comb += next_selected.eq(self.TARGET_PRESET)
                    with m.Elif(selected == self.TARGET_BAND_BASE):
                        m.d.comb += next_selected.eq(self.TARGET_MODE)
                    with m.Elif(selected == self.TARGET_RESONANCE):
                        m.d.comb += next_selected.eq(self.TARGET_DRIVE)
                    with m.Elif(selected == self.TARGET_DRIVE):
                        m.d.comb += next_selected.eq(
                            self.TARGET_BAND_BASE + RezoCore.N_BANDS - 1)
                    with m.Else():
                        m.d.comb += next_selected.eq(selected - 1)
        with m.Elif(page == 1):
            with m.If(edit_direction):
                with m.If(~tune_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_FEEDBACK_SEND_BASE)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_FEEDBACK_SEND_BASE)
                with m.Elif(selected == self.TARGET_DAMP):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Elif(selected ==
                            self.TARGET_FEEDBACK_SEND_BASE + RezoCore.N_BANDS - 1):
                    m.d.comb += next_selected.eq(self.TARGET_LIMIT_KNEE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~tune_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_DAMP)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_DAMP)
                with m.Elif(selected == self.TARGET_FEEDBACK_SEND_BASE):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Elif(selected == self.TARGET_LIMIT_KNEE):
                    m.d.comb += next_selected.eq(
                        self.TARGET_FEEDBACK_SEND_BASE + RezoCore.N_BANDS - 1)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.Elif((page == 2) & filter_mode):
            with m.If(edit_direction):
                with m.If(~filter_cv_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_FILTER_CV_BASE)
                with m.Elif(selected == self.TARGET_FILTER_CV_BASE + 14):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~filter_cv_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_FILTER_CV_BASE + 14)
                with m.Elif(selected == self.TARGET_FILTER_CV_BASE):
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
        with m.Elif(page == 4):
            with m.If(edit_direction):
                with m.If(~output_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_COL_BASE)
                with m.Elif(output_col_target):
                    with m.If(selected == self.TARGET_OUTPUT_DRY_COL):
                        m.d.comb += next_selected.eq(self.TARGET_OUTPUT_ROW_BASE)
                    with m.Elif(selected == self.TARGET_OUTPUT_COL_BASE + 3):
                        m.d.comb += next_selected.eq(Mux(
                            filter_mode, self.TARGET_OUTPUT_ROW_BASE,
                            self.TARGET_OUTPUT_DRY_COL))
                    with m.Else():
                        m.d.comb += next_selected.eq(selected + 1)
                for output in range(4):
                    row_target = self.TARGET_OUTPUT_ROW_BASE + output
                    last_send = self.TARGET_OUTPUT_BASE + output * 5 + 4
                    filter_last_send = self.TARGET_OUTPUT_BASE + output * 5 + 3
                    with m.Elif(selected == row_target):
                        m.d.comb += next_selected.eq(
                            self.TARGET_OUTPUT_BASE + output * 5)
                    with m.Elif(selected == Mux(
                            filter_mode, filter_last_send, last_send)):
                        m.d.comb += next_selected.eq(
                            self.TARGET_PAGE if output == 3 else row_target + 1)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~output_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(Mux(
                        filter_mode,
                        self.TARGET_OUTPUT_BASE + 18,
                        self.TARGET_OUTPUT_BASE + 19))
                for output in range(4):
                    row_target = self.TARGET_OUTPUT_ROW_BASE + output
                    first_send = self.TARGET_OUTPUT_BASE + output * 5
                    with m.Elif(selected == row_target):
                        m.d.comb += next_selected.eq(
                            Mux(filter_mode,
                                self.TARGET_OUTPUT_COL_BASE + 3 if output == 0 else
                                self.TARGET_OUTPUT_BASE + output * 5 - 2,
                                self.TARGET_OUTPUT_DRY_COL if output == 0 else
                                self.TARGET_OUTPUT_BASE + output * 5 - 1))
                    with m.Elif(selected == first_send):
                        m.d.comb += next_selected.eq(row_target)
                with m.Elif(output_col_target):
                    with m.If(selected == self.TARGET_OUTPUT_COL_BASE):
                        m.d.comb += next_selected.eq(self.TARGET_PAGE)
                    with m.Elif(selected == self.TARGET_OUTPUT_DRY_COL):
                        m.d.comb += next_selected.eq(
                            self.TARGET_OUTPUT_COL_BASE + 3)
                    with m.Else():
                        m.d.comb += next_selected.eq(selected - 1)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.Elif(page == 5):
            with m.If(edit_direction):
                with m.If(~advanced_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_PALETTE)
                with m.Elif(selected == self.TARGET_PALETTE):
                    m.d.comb += next_selected.eq(self.TARGET_SAVE_DEFAULT)
                with m.Else():
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
            with m.Else():
                with m.If(~advanced_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_SAVE_DEFAULT)
                with m.Elif(selected == self.TARGET_SAVE_DEFAULT):
                    m.d.comb += next_selected.eq(self.TARGET_PALETTE)
                with m.Else():
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
        with m.Elif(page == 6):
            # Row-major navigation: layout, ten enables, ten frequencies.
            with m.If(edit_direction):
                with m.If(~band_edit_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_BAND_LAYOUT)
                with m.Elif(selected == self.TARGET_BAND_LAYOUT):
                    m.d.comb += next_selected.eq(self.TARGET_BAND_ENABLE_BASE)
                with m.Elif(selected ==
                            self.TARGET_BAND_ENABLE_BASE + RezoCore.N_BANDS - 1):
                    m.d.comb += next_selected.eq(self.TARGET_BAND_FREQ_BASE)
                with m.Elif(selected ==
                            self.TARGET_BAND_FREQ_BASE + RezoCore.N_BANDS - 1):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~band_edit_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(
                        self.TARGET_BAND_FREQ_BASE + RezoCore.N_BANDS - 1)
                with m.Elif(selected == self.TARGET_BAND_FREQ_BASE):
                    m.d.comb += next_selected.eq(
                        self.TARGET_BAND_ENABLE_BASE + RezoCore.N_BANDS - 1)
                with m.Elif(selected == self.TARGET_BAND_ENABLE_BASE):
                    m.d.comb += next_selected.eq(self.TARGET_BAND_LAYOUT)
                with m.Elif(selected == self.TARGET_BAND_LAYOUT):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.Else():
            m.d.comb += next_selected.eq(self.TARGET_PAGE)

        with m.If(click):
            m.d.sync += [
                edit_step.eq(0),
                edit_repeat_remaining.eq(0),
            ]
            with m.If(feedback_send_target):
                feedback_send = Array(feedback_sends)[
                    selected - self.TARGET_FEEDBACK_SEND_BASE]
                with m.If(bank_band_enabled):
                    m.d.sync += feedback_send.eq(~feedback_send)
                m.d.sync += editing.eq(0)
            with m.Elif(band_enable_target):
                band_enable = Array(band_enables)[
                    selected - self.TARGET_BAND_ENABLE_BASE]
                m.d.sync += [band_enable.eq(~band_enable), editing.eq(0)]
            with m.Elif(selected == self.TARGET_SAVE_DEFAULT):
                # Saving is an explicit one-click action, matching Tiliqua's
                # other bitstreams. Musical state is never auto-saved.
                with m.If(self.save_default_available &
                          ~self.save_default_busy):
                    m.d.sync += self.save_default_request.eq(1)
            with m.Elif(editing):
                with m.If(selected == self.TARGET_PRESET):
                    self.apply_preset(m, preset, levels)
                with m.Elif(selected == self.TARGET_BAND_LAYOUT):
                    with m.If(layout_preview == RezoCore.LAYOUT_USER):
                        m.d.sync += frequency_layout.eq(
                            RezoCore.LAYOUT_USER)
                    with m.Else():
                        m.d.sync += [
                            layout_load_active.eq(1),
                            layout_load_index.eq(0),
                            layout_load_target.eq(layout_preview),
                            layout_load_prefetched.eq(0),
                        ]
                with m.Elif(band_frequency_target):
                    m.d.sync += [
                        Array(band_frequencies)[
                            selected - self.TARGET_BAND_FREQ_BASE].eq(
                                frequency_preview),
                        frequency_layout.eq(RezoCore.LAYOUT_USER),
                    ]
                m.d.sync += editing.eq(0)
            with m.Else():
                with m.If(selected == self.TARGET_BAND_LAYOUT):
                    m.d.sync += layout_preview.eq(frequency_layout)
                for n in range(RezoCore.N_BANDS):
                    with m.If(selected == self.TARGET_BAND_FREQ_BASE + n):
                        m.d.sync += frequency_preview.eq(band_frequencies[n])
                m.d.sync += [
                    # Disabled BANK controls remain traversable, but cannot be
                    # entered or changed. This keeps silent parameters inert
                    # without putting an enable-mask search on the already
                    # dense navigation path.
                    editing.eq(bank_band_enabled),
                    # The first edit detent is always precise. Subsequent
                    # detents accelerate only if they themselves arrive in a
                    # rapid sequence; navigation before the click is ignored.
                    detent_timer.eq((1 << 21) - 1),
                ]

        # One detent changes a continuous control by 1/128 of its nominal
        # unipolar span (and 1/128 of a band's bipolar span).  The DSP and CV
        # paths retain their full underlying 16-bit precision.
        step_amount = 1
        with m.If(edit_step & ~click):
            with m.If(~editing):
                m.d.sync += selected.eq(next_selected)
            with m.Else():
                with m.If(selected == self.TARGET_PRESET):
                    m.d.sync += preset.eq(next_preset)
                with m.Elif(selected == self.TARGET_PAGE):
                    # Main mode -> bands -> inputs/modulation -> groups ->
                    # outputs -> feedback -> advanced.
                    with m.If(edit_direction):
                        with m.Switch(page):
                            with m.Case(0):
                                m.d.sync += page.eq(Mux(filter_mode, 2, 6))
                            with m.Case(6): m.d.sync += page.eq(2)
                            with m.Case(2): m.d.sync += page.eq(3)
                            with m.Case(3): m.d.sync += page.eq(4)
                            with m.Case(4): m.d.sync += page.eq(1)
                            with m.Case(1): m.d.sync += page.eq(5)
                            with m.Default(): m.d.sync += page.eq(0)
                    with m.Else():
                        with m.Switch(page):
                            with m.Case(0): m.d.sync += page.eq(5)
                            with m.Case(5): m.d.sync += page.eq(1)
                            with m.Case(1): m.d.sync += page.eq(4)
                            with m.Case(4): m.d.sync += page.eq(3)
                            with m.Case(3): m.d.sync += page.eq(2)
                            with m.Case(2):
                                m.d.sync += page.eq(Mux(filter_mode, 0, 6))
                            with m.Default(): m.d.sync += page.eq(0)
                with m.Elif(selected == self.TARGET_BAND_LAYOUT):
                    with m.If(edit_direction):
                        m.d.sync += layout_preview.eq(layout_preview + 1)
                    with m.Else():
                        m.d.sync += layout_preview.eq(layout_preview - 1)
                with m.Elif(band_frequency_target):
                    with m.If(edit_direction):
                        with m.If(frequency_preview <=
                                  len(RezoCore.FREQUENCIES_HZ) - 1 -
                                  accelerated_edit_step):
                            m.d.sync += frequency_preview.eq(
                                frequency_preview + accelerated_edit_step)
                        with m.Else():
                            m.d.sync += frequency_preview.eq(
                                len(RezoCore.FREQUENCIES_HZ) - 1)
                    with m.Else():
                        with m.If(frequency_preview >= accelerated_edit_step):
                            m.d.sync += frequency_preview.eq(
                                frequency_preview - accelerated_edit_step)
                        with m.Else():
                            m.d.sync += frequency_preview.eq(0)
                with m.Elif(selected == self.TARGET_MODE):
                    m.d.sync += filter_mode.eq(~filter_mode)
                with m.Elif(selected == self.TARGET_PALETTE):
                    with m.If(edit_direction):
                        m.d.sync += palette.eq(Mux(palette == 4, 0, palette + 1))
                    with m.Else():
                        m.d.sync += palette.eq(Mux(palette == 0, 4, palette - 1))
                with m.Elif(output_row_target):
                    output_row = selected - self.TARGET_OUTPUT_ROW_BASE
                    m.d.sync += [
                        output_relative_active.eq(1),
                        output_relative_step.eq(0),
                        output_relative_index.eq(
                            output_row + (output_row << 2)),
                        output_relative_column.eq(0),
                        output_relative_direction.eq(edit_direction),
                    ]
                with m.Elif(output_col_target):
                    m.d.sync += [
                        output_relative_active.eq(1),
                        output_relative_step.eq(0),
                        output_relative_index.eq(Mux(
                            selected == self.TARGET_OUTPUT_DRY_COL, 4,
                            selected - self.TARGET_OUTPUT_COL_BASE)),
                        output_relative_column.eq(1),
                        output_relative_direction.eq(edit_direction),
                    ]
                with m.Elif(selected == self.TARGET_FILTER_TYPE):
                    with m.If(edit_direction):
                        m.d.sync += filter_type.eq(filter_type + 1)
                    with m.Else():
                        m.d.sync += filter_type.eq(filter_type - 1)
                with m.Elif(selected == self.TARGET_FILTER_CUTOFF):
                    with m.If(edit_direction):
                        self.clamp_add(m, filter_cutoff, step_amount, 0, 128)
                    with m.Else():
                        self.clamp_add(m, filter_cutoff, -step_amount, 0, 128)
                with m.Elif(selected == self.TARGET_FILTER_SLOPE):
                    with m.If(edit_direction):
                        self.clamp_add(m, filter_slope, step_amount, 0, 128)
                    with m.Else():
                        self.clamp_add(m, filter_slope, -step_amount, 0, 128)
                with m.Elif(selected == self.TARGET_FILTER_WIDTH):
                    with m.If(edit_direction):
                        self.clamp_add(m, filter_width, step_amount, 0, 128)
                    with m.Else():
                        self.clamp_add(m, filter_width, -step_amount, 0, 128)
                with m.Elif((selected >= self.TARGET_FILTER_CV_BASE) &
                            (selected < self.TARGET_FILTER_CV_BASE + 15)):
                    matrix_value = Array(filter_cv_matrix)[
                        selected - self.TARGET_FILTER_CV_BASE]
                    with m.If(edit_direction):
                        self.clamp_add(m, matrix_value, accelerated_edit_step,
                                       -128, 127)
                    with m.Else():
                        self.clamp_add(m, matrix_value, -accelerated_edit_step,
                                       -128, 127)
                with m.Elif(output_cell_target):
                    m.d.sync += [
                        output_edit_pending.eq(1),
                        output_edit_index.eq(selected - self.TARGET_OUTPUT_BASE),
                        output_edit_direction.eq(edit_direction),
                    ]
                with m.Elif(selected == self.TARGET_RESONANCE):
                    with m.If(edit_direction):
                        self.clamp_add(m, resonance, step_amount, 0, 128)
                    with m.Else():
                        self.clamp_add(m, resonance, -step_amount, 0, 128)
                with m.Elif(selected == self.TARGET_DRIVE):
                    with m.If(filter_mode):
                        with m.If(edit_direction):
                            self.clamp_add(m, filter_drive, step_amount, 0,
                                           96)
                        with m.Else():
                            self.clamp_add(m, filter_drive, -step_amount, 0,
                                           96)
                    with m.Else():
                        with m.If(edit_direction):
                            self.clamp_add(m, bank_drive, step_amount, 0,
                                           96)
                        with m.Else():
                            self.clamp_add(m, bank_drive, -step_amount, 0,
                                           96)
                with m.Elif(selected == self.TARGET_FEEDBACK):
                    with m.If(edit_direction):
                        self.clamp_add(m, feedback, step_amount, 0, 128)
                    with m.Else():
                        self.clamp_add(m, feedback, -step_amount, 0, 128)
                with m.Elif(selected == self.TARGET_LIMIT_KNEE):
                    with m.If(edit_direction):
                        self.clamp_add(m, limit_knee, step_amount, 16, 128)
                    with m.Else():
                        self.clamp_add(m, limit_knee, -step_amount, 16, 128)
                with m.Elif(selected == self.TARGET_LIMIT_CAP):
                    with m.If(edit_direction):
                        self.clamp_add(m, limit_cap, step_amount, 16, 128)
                    with m.Else():
                        self.clamp_add(m, limit_cap, -step_amount, 16, 128)
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
                            input_gain_coarse = input_gains[n][8:16]
                            with m.If(edit_direction):
                                self.clamp_add(m, input_gain_coarse, 1, 0, 255)
                            with m.Else():
                                self.clamp_add(m, input_gain_coarse, -1, 0, 255)
                        with m.Else():
                            with m.If(edit_direction):
                                m.d.sync += cv_targets[n].eq(Mux(cv_targets[n] == 6, 0,
                                                                 cv_targets[n] + 1))
                            with m.Else():
                                m.d.sync += cv_targets[n].eq(Mux(cv_targets[n] == 0, 6,
                                                                 cv_targets[n] - 1))
                    with m.Elif(selected == self.TARGET_INPUT_BASE + n * 3 + 2):
                        cv_depth_coarse = cv_depths[n][8:16].as_signed()
                        with m.If(edit_direction):
                            self.clamp_add(m, cv_depth_coarse, 1, -128, 127)
                        with m.Else():
                            self.clamp_add(m, cv_depth_coarse, -1, -128, 127)
                with m.Elif((selected >= self.TARGET_GROUP_BASE) &
                            (selected < self.TARGET_GROUP_BASE + RezoCore.N_BANDS)):
                    bank_group_index = Array(bank_group_indices)[
                        selected - self.TARGET_GROUP_BASE]
                    with m.If(edit_direction):
                        m.d.sync += bank_group_index.eq(bank_group_index + 1)
                    with m.Else():
                        m.d.sync += bank_group_index.eq(bank_group_index - 1)
                with m.Else():
                    # Keep the 16-bit band faders explicitly decoded. A
                    # dynamically indexed write saves some cells here, but it
                    # builds a wide read/modify/write mux that cannot meet the
                    # 60 MHz control-clock constraint on ECP5.
                    for n, level in enumerate(levels):
                        with m.If(selected == self.TARGET_BAND_BASE + n):
                            with m.If(edit_direction):
                                self.clamp_add(m, level, step_amount,
                                               -64, 64)
                            with m.Else():
                                self.clamp_add(m, level, -step_amount,
                                               -64, 64)

        with m.If(output_edit_pending):
            bank_send = Array(bank_output_sends)[output_edit_index]
            filter_send = Array(filter_output_sends)[output_edit_index]
            with m.If(output_edit_direction):
                with m.If(filter_mode):
                    self.clamp_add(m, filter_send, 1, 0, 16)
                with m.Else():
                    self.clamp_add(m, bank_send, 1, 0, 16)
            with m.Else():
                with m.If(filter_mode):
                    self.clamp_add(m, filter_send, -1, 0, 16)
                with m.Else():
                    self.clamp_add(m, bank_send, -1, 0, 16)
        # Packed 16-bit state scan port, sampled sequentially by the journal.
        # Packing at each field's native precision is materially smaller than
        # a 114-way 16-bit mux and leaves space for musical features.
        level_bytes = Cat(*(level.as_unsigned() for level in levels))
        # Version 2 already reserved twenty padding bits across the stream.
        # Reuse them for two fine-frequency bits per band. Old records restore
        # zero here and therefore retain their exact coarse-grid frequencies.
        cap_flags_fine = band_frequencies[0][:RezoCore.FREQ_FINE_WIDTH]
        filter_cv_fine = Cat(*(band_frequencies[n][:RezoCore.FREQ_FINE_WIDTH]
                               for n in range(1, 5)))
        bank_group_fine = Cat(*(band_frequencies[n][:RezoCore.FREQ_FINE_WIDTH]
                                for n in range(5, 9)))
        output_send_pad = Signal(8)
        band_config_fine = band_frequencies[9][:RezoCore.FREQ_FINE_WIDTH]
        filter_cv_bits = Cat(*(value.as_unsigned() for value in filter_cv_matrix),
                             filter_cv_fine)
        cv_depth_bytes = Cat(*(value[8:16] for value in cv_depths))
        input_config_bits = Cat(*input_modes, *cv_targets)
        bank_group_bits = Cat(*bank_group_indices, bank_group_fine)
        feedback_preset_bits = Cat(*feedback_sends, preset, palette)
        output_send_bits = Cat(*bank_output_sends, *filter_output_sends,
                               output_send_pad)
        band_config_bits = Cat(
            *(frequency[RezoCore.FREQ_FINE_WIDTH:]
              for frequency in band_frequencies),
            *band_enables, frequency_layout, band_config_fine)
        # The packed state is a circular stream. This temporal interface costs
        # one local shift mux per retained bit instead of a 42-way read mux and
        # a separate 42-way restore decoder. A complete SAVE rotation returns
        # every live register to its original location; LOAD replaces the
        # trailing word on each shift with validated journal data.
        state_bits = Cat(
            level_bytes,
            bank_drive, filter_drive,
            resonance, feedback,
            filter_cutoff, filter_slope,
            filter_width, limit_knee,
            limit_cap, damp_mode, filter_mode, filter_type, cap_flags_fine,
            filter_cv_bits,
            *input_gains,
            cv_depth_bytes,
            input_config_bits,
            bank_group_bits,
            feedback_preset_bits,
            output_send_bits,
            band_config_bits,
        )
        assert len(state_bits) == self.STATE_WORDS_V2 * 16
        m.d.comb += self.state_read_data.eq(state_bits[:16])
        with m.If(self.state_shift_enable):
            m.d.sync += state_bits.eq(Cat(
                state_bits[16:],
                Mux(self.state_shift_load,
                    self.state_write_data, state_bits[:16]),
            ))

        for n, level in enumerate(levels):
            m.d.comb += self.levels[n].eq(Mux(
                level == 64, 16383, level << 8))
        for n in range(RezoCore.N_BANDS):
            m.d.comb += [
                self.band_enables[n].eq(band_enables[n]),
                self.band_frequencies[n].eq(band_frequencies[n]),
            ]
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
        for n, feedback_send in enumerate(feedback_sends):
            m.d.comb += self.feedback_sends[n].eq(feedback_send)
        for n, output_send in enumerate(output_sends):
            m.d.comb += self.output_sends[n].eq(output_send)
        for n, depth in enumerate(filter_cv_matrix):
            m.d.comb += self.filter_cv_matrix[n].eq(depth)
        m.d.comb += [
            self.drive.eq(drive),
            self.resonance.eq(resonance << 8),
            self.feedback.eq(feedback << 8),
            self.filter_mode.eq(filter_mode),
            self.filter_type.eq(filter_type),
            self.filter_cutoff.eq(filter_cutoff << 8),
            self.filter_slope.eq(filter_slope << 8),
            self.filter_width.eq(filter_width << 8),
            self.limit_knee.eq(limit_knee << 8),
            self.limit_cap.eq(limit_cap << 8),
            self.damp_mode.eq(damp_mode),
            self.selected.eq(selected),
            self.page.eq(page),
            self.preset.eq(preset),
            self.palette.eq(palette),
            self.frequency_layout.eq(frequency_layout),
            self.frequency_layout_preview.eq(layout_preview),
            self.frequency_preview.eq(frequency_preview),
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
            "selected": In(unsigned(7)),
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
            active.eq(
                self.de & (sx >= self.x_offset) &
                (sx < self.x_offset + self.PANEL_W) &
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

        border = active & self.outline(
            x, y, 106 if self.compact_layout else 12,
            106 if self.compact_layout else 12,
            614 if self.compact_layout else 708,
            614 if self.compact_layout else 708, t=2)
        title_panel = active & self.rect(
            x, y, 112 if self.compact_layout else 20,
            120 if self.compact_layout else 20,
            608 if self.compact_layout else 700,
            164 if self.compact_layout else 82)
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

    # Semantic palette roles.  The current LCD theme maps every role to a
    # grayscale intensity; a future color palette can map the same roles to
    # related RGB colors without changing any geometry or modulation logic.
    PALETTE = {
        "selected": 0xff,
        "text": 0xee,
        "control": 0xb8,
        "modulation": 0x78,
        "line": 0x88,
        "panel": 0x32,
        "background": 0x14,
        "blank": 0x00,
    }

    PALETTE_ROLES = (
        "selected", "text", "control", "modulation",
        "line", "panel", "background", "blank",
    )
    RGB_PALETTES = (
        # LCD: preserve the existing grayscale renderer bit-for-bit.
        (0xFFFFFF, 0xEEEEEE, 0xB8B8B8, 0x787878,
         0x888888, 0x323232, 0x141414, 0x000000),
        # Warm controls with a cool modulation accent.
        (0xFFF4CC, 0xFFD166, 0xC98A20, 0x4EA5D9,
         0x9A6A22, 0x35270F, 0x171006, 0x000000),
        # Cool controls with a coral modulation accent.
        (0xF4FFFF, 0xC8F7F8, 0x55CBCD, 0xFF7F6A,
         0x2A9D9F, 0x16383A, 0x071718, 0x000000),
        # Green LCD family with a magenta modulation accent.
        (0xF3FFF6, 0xD8F3DC, 0x74C69D, 0xE56BCE,
         0x40916C, 0x1B4332, 0x081C15, 0x000000),
        # Violet controls with a gold modulation accent.
        (0xFFF8DA, 0xE7DCF5, 0x9D7AD2, 0xF2C14E,
         0x6C4AA3, 0x2B1D3A, 0x100A18, 0x000000),
    )

    CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    CHAR_CODES = {ch: i for i, ch in enumerate(CHARS)}

    def __init__(self, h_active=1280, rotate_left=False,
                 compact_layout=False):
        self.x_offset = max(0, (h_active - self.PANEL_W) // 2)
        self.rotate_left = rotate_left
        self.compact_layout = compact_layout
        super().__init__({
            "x": In(signed(12)),
            "y": In(signed(12)),
            "de": In(1),
            "levels": In(data.ArrayLayout(signed(8), RezoCore.N_BANDS)),
            "effective_levels": In(data.ArrayLayout(signed(8), RezoCore.N_BANDS)),
            "drive": In(unsigned(8)),
            "effective_drive": In(unsigned(8)),
            "resonance": In(unsigned(8)),
            "feedback": In(unsigned(8)),
            "effective_resonance": In(unsigned(8)),
            "effective_feedback": In(unsigned(8)),
            "filter_mode": In(1),
            "filter_type": In(unsigned(2)),
            "filter_cutoff": In(unsigned(8)),
            "filter_slope": In(unsigned(8)),
            "filter_width": In(unsigned(8)),
            "effective_filter_cutoff": In(unsigned(8)),
            "effective_filter_slope": In(unsigned(8)),
            "effective_filter_width": In(unsigned(8)),
            "limit_knee": In(unsigned(8)),
            "limit_cap": In(unsigned(8)),
            "damp_mode": In(unsigned(3)),
            "input_gains": In(data.ArrayLayout(unsigned(8), 4)),
            "input_modes": In(data.ArrayLayout(unsigned(1), 4)),
            "cv_targets": In(data.ArrayLayout(unsigned(3), 4)),
            "cv_depths": In(data.ArrayLayout(signed(8), 4)),
            "input_meters": In(data.ArrayLayout(signed(6), 4)),
            "filter_cv_write_addr": In(unsigned(4)),
            "filter_cv_write_data": In(signed(6)),
            "filter_cv_write_en": In(1),
            "output_send_write_addr": In(unsigned(5)),
            "output_send_write_data": In(unsigned(5)),
            "output_send_write_en": In(1),
            "bank_groups": In(data.ArrayLayout(unsigned(4), RezoCore.N_BANDS)),
            "feedback_sends": In(data.ArrayLayout(unsigned(1), RezoCore.N_BANDS)),
            "band_enables": In(data.ArrayLayout(unsigned(1), RezoCore.N_BANDS)),
            "band_frequencies": In(data.ArrayLayout(
                unsigned(RezoCore.FREQ_INDEX_WIDTH), RezoCore.N_BANDS)),
            "frequency_layout": In(unsigned(2)),
            "frequency_layout_preview": In(unsigned(2)),
            "frequency_preview": In(unsigned(RezoCore.FREQ_INDEX_WIDTH)),
            "selected": In(unsigned(7)),
            "page": In(unsigned(3)),
            "preset": In(unsigned(3)),
            "palette": In(unsigned(3)),
            "save_default_available": In(1),
            "save_default_busy": In(1),
            "save_default_status": In(unsigned(2)),
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
        # ``ui_x/ui_y`` are upright native 720x720 canvas coordinates.  The
        # production display is mounted rotated, so undo that mount rotation
        # here.  Layout is otherwise authored directly in final pixels: the
        # page content occupies the centered 508x508 safe square while REZO
        # remains available in the circular top arc.
        ui_x = Signal(signed(11))
        ui_y = Signal(signed(11))
        # The source coordinates may be negative while the standard HDMI
        # viewport is outside the centred 720px canvas, but renderer geometry
        # only ever sees an active 0..719 coordinate.  Keep the latter at its
        # natural unsigned width: signed 11-bit rectangle comparisons across
        # every page cost nearly a thousand LUTs on this almost-full device.
        x = Signal(range(self.PANEL_W))
        y = Signal(range(self.PANEL_H))
        active = Signal()
        if self.rotate_left:
            # The production 720x720 panel is physically mounted with the
            # same left rotation used by the framebuffer HAL. Invert that
            # mapping here so both display targets share one logical UI.
            m.d.comb += [
                ui_x.eq(sy),
                ui_y.eq((self.PANEL_H - 1) - sx),
            ]
        else:
            m.d.comb += [
                ui_x.eq(sx - self.x_offset),
                ui_y.eq(sy),
            ]

        text_x = Signal(range(self.PANEL_W))
        text_y = Signal(range(self.PANEL_H))
        if self.compact_layout:
            # Retain two pipeline stages so the surrounding renderer timing
            # stays unchanged after removing the old 720-to-508 lookup BRAM.
            # Geometry and text now receive the same native pixel coordinate.
            text_x_pre = Signal.like(text_x)
            text_y_pre = Signal.like(text_y)
            active_pre = Signal()
            m.d.dvi += [
                x.eq(text_x_pre),
                y.eq(text_y_pre),
                text_x_pre.eq(ui_x[:10]),
                text_y_pre.eq(ui_y[:10]),
                active_pre.eq(self.de & (ui_x >= 0) &
                              (ui_x < self.PANEL_W) &
                              (ui_y >= 0) & (ui_y < self.PANEL_H)),
                text_x.eq(text_x_pre),
                text_y.eq(text_y_pre),
                active.eq(active_pre),
            ]
        else:
            m.d.comb += [
                x.eq(ui_x[:10]),
                y.eq(ui_y[:10]),
                text_x.eq(ui_x[:10]),
                text_y.eq(ui_y[:10]),
                active.eq(self.de & (ui_x >= 0) &
                          (ui_x < self.PANEL_W) &
                          (ui_y >= 0) & (ui_y < self.PANEL_H)),
            ]

        zero_y = 350 if self.compact_layout else 366
        # Retain the compact field's lower edge while reclaiming the unused
        # space above it.  This leaves modest padding below the BANDS label
        # and a clear gutter before the first horizontal control.
        main_band_y0 = 259 if self.compact_layout else 202
        main_band_y1 = 440 if self.compact_layout else 532
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
            mag = Signal(unsigned(7), name=f"tile_level_mag{n}")
            base_mag = Signal(unsigned(7), name=f"tile_base_level_mag{n}")
            height = Signal(signed(12), name=f"tile_level_height{n}")
            base_height = Signal(signed(12), name=f"tile_base_level_height{n}")
            filter_height = Signal(signed(12), name=f"tile_filter_height{n}")
            m.d.comb += [
                mag.eq(Mux(level < 0, -level, level)),
                base_mag.eq(Mux(base_level < 0, -base_level, base_level)),
            ]
            if self.compact_layout:
                # Native 508px geometry: BANK's 0..64 magnitude spans the
                # 91px half-field, while FILTER's 0..32 response spans the
                # complete 181px unipolar field.  Keep the +32 BANK default
                # visually near half-height without any viewport transform.
                m.d.comb += [
                    height.eq(mag + (mag >> 2) + (mag >> 3) +
                              (mag >> 5)),
                    base_height.eq(base_mag + (base_mag >> 2) +
                                   (base_mag >> 3) + (base_mag >> 5)),
                    filter_height.eq((mag << 2) + mag + (mag >> 1) +
                                     (mag >> 3)),
                ]
            else:
                m.d.comb += [
                    height.eq((mag << 1) + (mag >> 1) +
                              Mux(level < 0, 0, mag >> 3)),
                    base_height.eq((base_mag << 1) + (base_mag >> 1) +
                                   Mux(base_level < 0, 0, base_mag >> 3)),
                    filter_height.eq(
                        (mag << 3) + (mag << 1) + (mag >> 2)),
                ]
            m.d.dvi += [
                band_top_values[n].eq(Mux(self.filter_mode,
                                          main_band_y1 - filter_height,
                                          zero_y - height)),
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
            cell_x.eq(text_x[self.CELL_SHIFT:]),
            cell_y.eq(text_y[self.CELL_SHIFT:]),
            glyph_col.eq(text_x[1:4]),
            glyph_row.eq(text_y[1:4]),
        ]

        home_page = Signal()
        bank_page = Signal()
        filter_page = Signal()
        tune_page = Signal()
        input_page = Signal()
        filter_cv_page = Signal()
        group_page = Signal()
        output_page = Signal()
        advanced_page = Signal()
        bands_page = Signal()
        # Page/mode selection changes at human speed. Register the decoded
        # flags in the pixel domain so every geometry path starts from a local
        # one-bit control rather than repeating the page comparison inside the
        # densely packed renderer.
        m.d.dvi += [
            home_page.eq(self.page == 0),
            bank_page.eq((self.page == 0) & ~self.filter_mode),
            filter_page.eq((self.page == 0) & self.filter_mode),
            tune_page.eq(self.page == 1),
            input_page.eq((self.page == 2) & ~self.filter_mode),
            filter_cv_page.eq((self.page == 2) & self.filter_mode),
            group_page.eq(self.page == 3),
            output_page.eq(self.page == 4),
            advanced_page.eq(self.page == 5),
            bands_page.eq((self.page == 6) & ~self.filter_mode),
        ]
        page_cells = 45 * 45
        text_init = [0] * (9 * page_cells)

        def compact_cell(value):
            # Preserve the native 16x16 character cell and reflow the former
            # 45-cell layout into the 31 cells (7..37) wholly contained by
            # the centered 508-pixel square.
            return 7 + ((value * 30 + 22) // 44)

        def text_cell_x(value):
            return compact_cell(value) if self.compact_layout else value

        def text_cell_y(value):
            return compact_cell(value) if self.compact_layout else value

        def put(page, text_value, x0, y0):
            x0 = text_cell_x(x0)
            y0 = text_cell_y(y0)
            for offset, ch in enumerate(text_value):
                if 0 <= x0 + offset < 45 and 0 <= y0 < 45:
                    text_init[page * page_cells + y0 * 45 + x0 + offset] = self.code(ch)

        def put_native(page, text_value, x0, y0):
            """Place compact-layout text directly on the native 16px grid."""
            for offset, ch in enumerate(text_value):
                if 0 <= x0 + offset < 45 and 0 <= y0 < 45:
                    text_init[page * page_cells + y0 * 45 + x0 + offset] = self.code(ch)

        def text_address_for(page, x0, y0, offset=0):
            return (page * page_cells + text_cell_y(y0) * 45 +
                    text_cell_x(x0) + offset)

        def native_text_address(page, x0, y0, offset=0):
            return page * page_cells + y0 * 45 + x0 + offset

        page_titles = ("BANK", "FEEDBACK", "INPUT", "GROUPS", "OUTPUT",
                       "OPTIONS", "BANDS", "FILTER", "MATRIX")
        compact_input_text_rows = (
            (14, 16, 18), (20, 22, 24),
            (26, 28, 30), (32, 34, 36))
        # GROUPS labels and geometry share this native 48px cadence.  Each
        # 14-scanline glyph has its visual centre at row*16 + 6.5; the rail
        # occupies the two native pixels surrounding that same half-pixel.
        compact_group_text_rows = (20, 23, 26, 29)
        compact_group_centers = tuple(
            row * 16 + 6 for row in compact_group_text_rows)
        # Four native text rows apart gives OUTPUT a uniform 64px cadence.
        # Keep OUT0/OUT1 fixed and place OUT2/OUT3 on the next two positions;
        # the earlier 21/25/28/32 tuple accidentally produced 64/48/64px gaps.
        compact_output_text_rows = (21, 25, 29, 33)
        # OUTPUT headings/labels and their cells share these native visual
        # centres. A glyph's visual centre is at row*16 + 6.5; a two-character
        # heading beginning at column N is centred at N*16 + 14.5, while DRY
        # is centred at N*16 + 22.5. Keeping the upper pixel of each half-pixel
        # centre here lets the native cells use the exact same centreline.
        compact_output_row_centers = tuple(
            row * 16 + 6 for row in compact_output_text_rows)
        compact_output_col_centers = (
            16 * 16 + 14, 20 * 16 + 14, 24 * 16 + 14,
            28 * 16 + 14, 32 * 16 + 22)
        # BANK and FILTER share this bottom-anchored native five-slot grid.
        # Expand upward on alternate 16px text rows while retaining the final
        # row's lower edge. This consumes the otherwise empty band/control
        # gutter without moving the band field or the bottom anchor.
        compact_main_control_text_rows = (28, 30, 32, 34, 36)
        compact_main_control_y0s = (448, 480, 512, 544, 576)
        # MATRIX labels and faders share a native four-character-row cadence.
        # Deriving both from this tuple removes all accumulated scale/rounding
        # drift and keeps the header on its separate row above the matrix.
        compact_matrix_text_rows = (18, 22, 26, 30, 34)
        # FEEDBACK safety labels share one right edge. Their value controls
        # begin seven native pixels later, after the compact geometry lookup.
        # This keeps the two faders and DAMPING chip on one physical x axis.
        compact_feedback_label_x = 9
        if self.compact_layout:
            # The compact UI is authored natively for the centered 508px
            # square.  Text and geometry therefore share one coordinate
            # system instead of independently scaling the old 720px layout.
            compact_titles = ("MAIN", "FEEDBACK", "INPUT", "GROUPS", "OUTPUT",
                              "OPTIONS", "BANDS", "MAIN", "MATRIX")
            for page_number, title in enumerate(compact_titles):
                put_native(page_number, "REZO", 20, 2)
                put_native(page_number, "PAGE", 8, 8)
                put_native(page_number, title,
                           14 + ((8 - len(title)) // 2), 8)

            # BANK main page.
            put_native(0, "PRESET", 8, 11)
            put_native(0, "MODE", 24, 11)
            put_native(0, "BANK", 31, 11)
            put_native(0, "BANDS", 8, 14)
            put_native(0, "FREQ:", 23, 14)
            # BANK occupies the first three slots of the same five-slot grid
            # used by FILTER below.
            put_native(0, "DRIVE", 12, compact_main_control_text_rows[0])
            put_native(0, "RESONANCE", 8, compact_main_control_text_rows[1])
            put_native(0, "FEEDBACK", 9, compact_main_control_text_rows[2])

            # FEEDBACK.
            put_native(1, "FEEDBACK SOURCES", 8, 13)
            put_native(1, "BANDS", 8, 16)
            put_native(1, "FREQ:", 23, 16)
            put_native(1, "FEEDBACK SAFETY", 8, 22)
            put_native(1, "KNEE", compact_feedback_label_x + 3, 25)
            put_native(1, "CEILING", compact_feedback_label_x, 27)
            put_native(1, "DAMPING", compact_feedback_label_x, 29)

            # INPUT uses four identical groups. MODE, VALUE and DEPTH are
            # plain labels; only the editable value beside each label owns a
            # shaded chip/fader. VALUE and DEPTH occupy consecutive alternate
            # rows so they remain distinct without pushing the last group out
            # of the content panel.
            put_native(2, "INPUT ROUTING", 8, 12)
            # The six-native-row cadence consumes the field's former empty
            # bottom margin without pushing the final label outside the
            # centered 508px viewport.
            for n, (mode_row, value_row, depth_row) in enumerate(
                    compact_input_text_rows):
                put_native(2, f"IN{n}", 8, mode_row)
                put_native(2, "MODE", 14, mode_row)
                put_native(2, "VALUE", 13, value_row)
                # DEPTH is dynamic below: CV inputs show it, while AUD inputs
                # leave the entire inapplicable lane blank.

            # GROUPS.
            put_native(3, "BANK GROUPS", 8, 13)
            put_native(3, "BANKS", 20, 16)
            for group, row in enumerate(compact_group_text_rows):
                put_native(3, f"GRP{group + 1}", 8, row)

            # OUTPUT matrix. Geometry below is centred from these exact text
            # starts, so labels and cells cannot accumulate scaling drift.
            put_native(4, "OUTPUT ROUTING", 8, 13)
            for x0, label in zip((16, 20, 24, 28),
                                 ("G1", "G2", "G3", "G4")):
                put_native(4, label, x0, 18)
            for n, row in enumerate(compact_output_text_rows):
                put_native(4, f"OUT{n}", 9, row)

            # OPTIONS.
            put_native(5, "STATE AND DISPLAY", 8, 13)
            put_native(5, "PALETTE", 13, 17)
            put_native(5, "SAVE DEFAULT", 8, 21)

            # BANDS.
            put_native(6, "PRESET", 8, 11)
            put_native(6, "ENABLE", 8, 16)
            put_native(6, "SET FREQ", 8, 22)
            put_native(6, "HZ", 26, 22)

            # FILTER main page.
            put_native(7, "TYPE", 8, 11)
            put_native(7, "MODE", 24, 11)
            put_native(7, "FILTER", 30, 11)
            put_native(7, "BANDS", 8, 14)
            # FILTER uses all five shared slots. Right-align every label at
            # x=272, immediately before the common native fader gutter.
            for row, (x0, label) in zip(compact_main_control_text_rows, (
                    (8, "FREQUENCY"), (12, "SLOPE"), (12, "WIDTH"),
                    (12, "DRIVE"), (8, "RESONANCE"))):
                put_native(7, label, x0, row)

            # FILTER modulation matrix.
            put_native(8, "MOD MATRIX", 8, 13)
            put_native(8, "IN 1", 18, 16)
            put_native(8, "IN 2", 25, 16)
            put_native(8, "IN 3", 32, 16)
            for row, (x0, label) in zip(compact_matrix_text_rows, (
                    (8, "FREQUENCY"), (8, "RESONANCE"), (12, "WIDTH"),
                    (12, "SLOPE"), (12, "DRIVE"))):
                put_native(8, label, x0, row)
        else:
            for page_number, title in enumerate(page_titles):
                put(page_number, "REZO", 2, 3)
                title_x = 29 + max(0, (8 - len(title)) // 2)
                put(page_number, title, title_x, 3)
            put(0, "PRESET", 2, 7)
            put(0, "BANDS", 2, 11)
            put(0, "FREQ:", 22, 11)
            put(0, "DRIVE", 2, 35)
            put(0, "RES", 2, 37)
            put(0, "FB", 2, 39)
            put(1, "FEEDBACK SOURCES", 2, 8)
            put(1, "BANDS", 2, 11)
            put(1, "FREQ:", 22, 11)
            put(1, "FEEDBACK SAFETY", 2, 23)
            put(1, "KNEE", 2, 26)
            put(1, "CEILING", 2, 29)
            put(1, "DAMPING", 2, 32)
            put(2, "INPUT ROUTING", 2, 11)
            for n in range(4):
                row = 13 + n * 6
                put(2, f"IN{n}", 3, row)
                put(2, "MODE", 8, row)
                put(2, "VALUE", 8, row + 2)
                put(2, "DEPTH", 8, row + 4)
            put(3, "BANK GROUPS", 2, 11)
            put(3, "BANKS", 21, 15)
            for group in range(4):
                put(3, f"GRP{group + 1}", 3, 19 + group * 4)
            put(4, "OUTPUT ROUTING", 2, 11)
            for source, label in enumerate(("GRP1", "GRP2", "GRP3", "GRP4", "")):
                put(4, label, 12 + source * 6, 17)
            for n in range(4):
                put(4, f"OUT{n}", 3, 21 + n * 5)
            put(5, "STATE AND DISPLAY", 2, 11)
            put(5, "PALETTE", 8, 15)
            put(5, "SAVE DEFAULT", 3, 19)
            put(6, "PRESET", 2, 7)
            put(6, "ENABLE", 2, 12)
            put(6, "SET FREQ", 2, 22)
            put(6, "HZ", 20, 22)
            put(7, "TYPE", 2, 7)
            put(7, "BANDS", 2, 11)
            put(7, "FREQ", 2, 34)
            put(7, "SLOPE", 2, 36)
            put(7, "WIDTH", 2, 38)
            put(7, "DRIVE", 2, 40)
            put(7, "RES", 2, 42)
            put(8, "MOD MATRIX", 2, 8)
            put(8, "INPUT 1", 14, 11)
            put(8, "INPUT 2", 24, 11)
            put(8, "INPUT 3", 34, 11)
            for row, label in enumerate(
                    ("FREQUENCY", "RESONANCE", "WIDTH", "SLOPE", "DRIVE")):
                put(8, label, 3, 15 + row * 5)

        m.submodules.text_mem = text_mem = Memory(
            shape=unsigned(6), depth=len(text_init), init=text_init)
        text_rport = text_mem.read_port(domain="dvi")
        text_wport = text_mem.write_port(domain="sync")
        page_offsets = Array(Const(page * page_cells, unsigned(15)) for page in range(9))
        text_address = Signal(unsigned(15))
        text_page_q = Signal(unsigned(4))
        m.d.dvi += text_page_q.eq(
            Mux((self.page == 0) & self.filter_mode, 7,
                Mux((self.page == 2) & self.filter_mode, 8, self.page)))
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
        palette_sync = Signal(unsigned(3))
        damp_mode_sync = Signal(unsigned(3))
        save_available_sync = Signal()
        save_busy_sync = Signal()
        save_status_sync = Signal(unsigned(2))
        # These values are used only by this sync-domain text writer. The top
        # connects them directly from the sync-domain UI; do not bounce them
        # through DVI and back through a second pair of synchronizers.
        frequency_layout_sync = self.frequency_layout
        frequency_layout_preview_sync = self.frequency_layout_preview
        frequency_preview_sync = self.frequency_preview
        band_frequencies_sync = self.band_frequencies
        input_modes_sync = [Signal(name=f"text_input_mode{n}") for n in range(4)]
        cv_targets_sync = [Signal(unsigned(3), name=f"text_cv_target{n}") for n in range(4)]
        m.submodules += [
            FFSynchronizer(self.page, page_sync),
            FFSynchronizer(self.preset, preset_sync),
            FFSynchronizer(self.selected, selected_sync),
            FFSynchronizer(self.editing, editing_sync),
            FFSynchronizer(self.filter_mode, filter_mode_sync),
            FFSynchronizer(self.filter_type, filter_type_sync),
            FFSynchronizer(self.palette, palette_sync),
            FFSynchronizer(self.damp_mode, damp_mode_sync),
            FFSynchronizer(self.save_default_available, save_available_sync),
            FFSynchronizer(self.save_default_busy, save_busy_sync),
            FFSynchronizer(self.save_default_status, save_status_sync),
        ]
        for n in range(4):
            m.submodules += FFSynchronizer(self.input_modes[n], input_modes_sync[n])
            m.submodules += FFSynchronizer(self.cv_targets[n], cv_targets_sync[n])

        feedback_selected_band = Signal(range(RezoCore.N_BANDS))
        feedback_selected_valid = Signal()
        m.d.comb += [
            feedback_selected_band.eq(0),
            feedback_selected_valid.eq(
                (selected_sync >= RezoHardwareUI.TARGET_FEEDBACK_SEND_BASE) &
                (selected_sync < RezoHardwareUI.TARGET_FEEDBACK_SEND_BASE +
                 RezoCore.N_BANDS)),
        ]
        with m.If(feedback_selected_valid):
            m.d.comb += feedback_selected_band.eq(
                selected_sync - RezoHardwareUI.TARGET_FEEDBACK_SEND_BASE)

        bands_selected_band = Signal(range(RezoCore.N_BANDS))
        bands_selected_valid = Signal()
        bands_frequency_selected = Signal()
        m.d.comb += [
            bands_selected_band.eq(0),
            bands_selected_valid.eq(
                ((selected_sync >= RezoHardwareUI.TARGET_BAND_ENABLE_BASE) &
                 (selected_sync < RezoHardwareUI.TARGET_BAND_ENABLE_BASE +
                  RezoCore.N_BANDS)) |
                ((selected_sync >= RezoHardwareUI.TARGET_BAND_FREQ_BASE) &
                 (selected_sync < RezoHardwareUI.TARGET_BAND_FREQ_BASE +
                  RezoCore.N_BANDS))),
            bands_frequency_selected.eq(
                (selected_sync >= RezoHardwareUI.TARGET_BAND_FREQ_BASE) &
                (selected_sync < RezoHardwareUI.TARGET_BAND_FREQ_BASE +
                 RezoCore.N_BANDS)),
        ]
        with m.If(bands_frequency_selected):
            m.d.comb += bands_selected_band.eq(
                selected_sync - RezoHardwareUI.TARGET_BAND_FREQ_BASE)
        with m.Elif(bands_selected_valid):
            m.d.comb += bands_selected_band.eq(
                selected_sync - RezoHardwareUI.TARGET_BAND_ENABLE_BASE)

        # Indices 96..103 extend the four compact INPUT MODE fields from
        # three to five characters without disturbing the established
        # writer-address layout below index 96.
        update_index = Signal(range(104))
        update_active = Signal(init=1)
        refresh_counter = Signal(range(4_000_000))
        writer_address = Signal(unsigned(15))
        writer_char = Signal(unsigned(6))
        writer_index_q = Signal.like(update_index)
        writer_page_q = Signal(unsigned(4))
        writer_char_q = Signal.like(writer_char)
        writer_valid_q = Signal()
        selected_band = Signal(range(RezoCore.N_BANDS))
        selected_band_valid = Signal()
        m.d.comb += [
            writer_char.eq(0),
            selected_band.eq(0),
            selected_band_valid.eq((selected_sync >= RezoHardwareUI.TARGET_BAND_BASE) &
                                   (selected_sync < RezoHardwareUI.TARGET_BAND_BASE +
                                    RezoCore.N_BANDS)),
            text_wport.addr.eq(writer_address),
            text_wport.data.eq(writer_char_q),
            text_wport.en.eq(writer_valid_q),
        ]
        m.d.sync += [
            writer_index_q.eq(update_index),
            writer_page_q.eq(Mux(
                (page_sync == 0) & filter_mode_sync, 7,
                Mux((page_sync == 2) & filter_mode_sync, 8, page_sync))),
            writer_char_q.eq(writer_char),
            writer_valid_q.eq(update_active),
        ]
        with m.If(selected_band_valid):
            m.d.comb += selected_band.eq(
                selected_sync - RezoHardwareUI.TARGET_BAND_BASE)

        # These fixed-width strings are padded per visible name so the text is
        # centered inside the shared BANK selector rather than left-aligned.
        preset_names = ("ALL ", "ODD ", "EVEN", "LOW ", "MID ", "HIGH", "ZERO")
        def frequency_name(frequency):
            if frequency < 1000:
                return f"{frequency:<3}"[:3]
            if frequency < 10_000:
                whole, remainder = divmod(frequency, 1000)
                tenth = (remainder + 50) // 100
                return f"{whole}K{tenth}" if tenth else f"{whole}K "
            return f"{round(frequency / 1000):02d}K"

        frequency_names = tuple(frequency_name(frequency)
                                for frequency in RezoCore.FREQUENCIES_HZ)
        displayed_layout = Signal(unsigned(2))
        m.d.comb += displayed_layout.eq(Mux(
            editing_sync & (selected_sync == RezoHardwareUI.TARGET_BAND_LAYOUT),
            frequency_layout_preview_sync, frequency_layout_sync))
        target_names = ("FB ", "RES", "DRV", "G1 ", "G2 ", "G3 ", "G4 ")
        nav_names = ("NAV ", "EDIT")
        nav_chars = [Array(Const(self.code(name[pos]), 6) for name in nav_names)
                     for pos in range(4)]
        preset_chars = [Array(Const(self.code(name[pos]), 6) for name in preset_names)
                        for pos in range(4)]
        damp_names = (" OFF ", "LIGHT", " MED ", "HEAVY", " MAX ")
        damp_chars = [Array(Const(self.code(name[pos]), 6)
                            for name in damp_names)
                      for pos in range(5)]
        damp_name_index = Signal(range(5))
        m.d.comb += damp_name_index.eq(Mux(
            damp_mode_sync > 4, 4, damp_mode_sync))
        # Return one character directly from BRAM. Storing each compact and
        # full label in an eight-character slot makes the address a shift plus
        # OR, avoiding wide-word character selectors in the text writer.
        frequency_full_offset = 1024
        frequency_label_init = [0] * 2048
        for index, name in enumerate(frequency_names):
            full_name = f"{RezoCore.FREQUENCIES_HZ[index]:>5}"
            for pos in range(3):
                frequency_label_init[(index << 3) | pos] = self.code(name[pos])
            for pos in range(5):
                frequency_label_init[
                    frequency_full_offset | (index << 3) | pos
                ] = self.code(full_name[pos])
        m.submodules.frequency_label_mem = frequency_label_mem = Memory(
            shape=unsigned(6), depth=len(frequency_label_init),
            init=frequency_label_init, attrs={"ram_style": "block"})
        frequency_label_rport = frequency_label_mem.read_port()
        m.d.comb += frequency_label_rport.addr.eq(0)
        with m.Switch(update_index):
            for pos in range(3):
                # Prefetch each synchronous ROM character one writer step
                # before it is consumed below.
                with m.Case(7 + pos):
                    with m.If(selected_band_valid):
                        m.d.comb += frequency_label_rport.addr.eq(
                            (Array(band_frequencies_sync)[selected_band] << 3) |
                            pos)
                with m.Case(42 + pos):
                    with m.If(feedback_selected_valid):
                        m.d.comb += frequency_label_rport.addr.eq(
                            (Array(band_frequencies_sync)[
                                feedback_selected_band] << 3) | pos)
            for pos in range(5):
                with m.Case(65 + pos):
                    with m.If(bands_selected_valid):
                        bands_frequency_index = Mux(
                            editing_sync & bands_frequency_selected,
                            frequency_preview_sync,
                            Array(band_frequencies_sync)[bands_selected_band])
                        m.d.comb += frequency_label_rport.addr.eq(
                            frequency_full_offset |
                            (bands_frequency_index << 3) | pos)
        layout_names = (" LEGACY", " OCTAVE", "PERCEPT", "  USER ")
        layout_chars = [Array(Const(self.code(name[pos]), 6)
                              for name in layout_names)
                        for pos in range(7)]
        target_chars = [Array(Const(self.code(name[pos]), 6) for name in target_names)
                        for pos in range(3)]
        filter_type_names = (" LP ", " HP ", " BP ", "NOT ")
        filter_type_chars = [Array(Const(self.code(name[pos]), 6)
                                   for name in filter_type_names)
                             for pos in range(4)]
        palette_names = ("  LCD ", " AMBER", " CYAN ", " GREEN", "VIOLET")
        palette_chars = [Array(Const(self.code(name[pos]), 6)
                               for name in palette_names)
                         for pos in range(6)]
        save_names = (" SAVE  ", "SAVING ", " SAVED ", " ERROR ",
                      "NO SLOT")
        save_chars = [Array(Const(self.code(name[pos]), 6)
                            for name in save_names)
                      for pos in range(7)]
        save_name_index = Signal(range(len(save_names)))
        m.d.comb += save_name_index.eq(
            Mux(~save_available_sync, 4,
                Mux(save_busy_sync | (save_status_sync == 1), 1,
                    Mux(save_status_sync == 2, 2,
                        Mux(save_status_sync == 3, 3, 0)))))

        # Most text destinations are fixed. Keep their addresses in one
        # DP16KD instead of synthesizing a wide 15-bit address mux. The
        # first four NAV/EDIT cells follow the active page and remain the only
        # dynamically calculated destinations.
        writer_address_init = [0] * 128
        if self.compact_layout:
            for pos in range(4):
                writer_address_init[4 + pos] = native_text_address(
                    0, 16, 11, pos)
            for pos in range(3):
                writer_address_init[8 + pos] = native_text_address(
                    0, 29, 14, pos)
            for n, (mode_row, value_row, _) in enumerate(
                    compact_input_text_rows):
                for pos in range(3):
                    writer_address_init[11 + n * 3 + pos] = native_text_address(
                        2, 20, mode_row, pos)
                    writer_address_init[23 + n * 3 + pos] = native_text_address(
                        2, 20, value_row, pos)
                for pos in range(2):
                    writer_address_init[96 + n * 2 + pos] = native_text_address(
                        2, 20, mode_row, pos + 3)
            for pos in range(4):
                writer_address_init[35 + pos] = native_text_address(
                    7, 14, 11, pos)
                # The leading blank begins one cell before DRY, placing the
                # visible three-character label at x=32 and centring it over
                # the fifth native OUTPUT column.
                writer_address_init[39 + pos] = native_text_address(
                    4, 31, 18, pos)
            for pos in range(3):
                writer_address_init[43 + pos] = native_text_address(
                    1, 29, 16, pos)
            for pos in range(6):
                writer_address_init[46 + pos] = native_text_address(
                    5, 22, 17, pos)
            for pos in range(7):
                writer_address_init[52 + pos] = native_text_address(
                    5, 22, 21, pos)
                writer_address_init[59 + pos] = native_text_address(
                    6, 16, 11, pos)
            for pos in range(5):
                writer_address_init[66 + pos] = native_text_address(
                    6, 20, 22, pos)
                writer_address_init[71 + pos] = native_text_address(
                    1, 17, 29, pos)
            for n, (_, _, depth_row) in enumerate(compact_input_text_rows):
                for pos in range(5):
                    writer_address_init[76 + n * 5 + pos] = native_text_address(
                        2, 13, depth_row, pos)
        else:
            for pos in range(4):
                writer_address_init[4 + pos] = text_address_for(
                    0, 11, 7, pos)
            for pos in range(3):
                writer_address_init[8 + pos] = text_address_for(
                    0, 28, 11, pos)
            for n in range(4):
                row = 13 + n * 6
                for pos in range(3):
                    writer_address_init[11 + n * 3 + pos] = text_address_for(
                        2, 14, row, pos)
                    writer_address_init[23 + n * 3 + pos] = text_address_for(
                        2, 16, row + 2, pos)
            for pos in range(4):
                writer_address_init[35 + pos] = text_address_for(
                    7, 11, 7, pos)
                writer_address_init[39 + pos] = text_address_for(
                    4, 36, 17, pos)
            for pos in range(3):
                writer_address_init[43 + pos] = text_address_for(
                    1, 28, 11, pos)
            for pos in range(6):
                writer_address_init[46 + pos] = text_address_for(
                    5, 18, 15, pos)
            for pos in range(7):
                writer_address_init[52 + pos] = text_address_for(
                    5, 18, 19, pos)
                writer_address_init[59 + pos] = text_address_for(
                    6, 9, 7, pos)
            for pos in range(5):
                writer_address_init[66 + pos] = text_address_for(
                    6, 14, 22, pos)
                writer_address_init[71 + pos] = text_address_for(
                    1, 12, 32, pos)
        m.submodules.writer_address_mem = writer_address_mem = Memory(
            shape=unsigned(15), depth=len(writer_address_init),
            init=writer_address_init, attrs={"ram_style": "block"})
        writer_address_rport = writer_address_mem.read_port()
        m.d.comb += [
            writer_address_rport.addr.eq(update_index),
            writer_address.eq(Mux(
                writer_index_q < 4,
                page_offsets[writer_page_q] +
                (8 if self.compact_layout else text_cell_y(3)) * 45 +
                (33 if self.compact_layout else text_cell_x(39)) +
                writer_index_q,
                writer_address_rport.data)),
        ]

        with m.Switch(update_index):
            for pos in range(4):
                with m.Case(pos):
                    m.d.comb += writer_char.eq(
                        nav_chars[pos][editing_sync])
            for pos in range(4):
                with m.Case(4 + pos):
                    m.d.comb += writer_char.eq(
                        preset_chars[pos][preset_sync])
            for pos in range(3):
                with m.Case(8 + pos):
                    m.d.comb += writer_char.eq(Mux(
                        selected_band_valid,
                        frequency_label_rport.data,
                        0))
            for n in range(4):
                row = 13 + n * 6
                for pos in range(3):
                    with m.Case(11 + n * 3 + pos):
                        audio_char = self.code("AUDIO"[pos])
                        cv_char = self.code(" CV  "[pos])
                        m.d.comb += writer_char.eq(Mux(
                            input_modes_sync[n], cv_char, audio_char))
                    with m.Case(23 + n * 3 + pos):
                        m.d.comb += writer_char.eq(Mux(
                            input_modes_sync[n],
                            target_chars[pos][cv_targets_sync[n]], 0))
                if self.compact_layout:
                    for pos in range(2):
                        with m.Case(96 + n * 2 + pos):
                            audio_char = self.code("AUDIO"[pos + 3])
                            cv_char = self.code(" CV  "[pos + 3])
                            m.d.comb += writer_char.eq(Mux(
                                input_modes_sync[n], cv_char, audio_char))
            for pos in range(4):
                with m.Case(35 + pos):
                    m.d.comb += writer_char.eq(
                        filter_type_chars[pos][filter_type_sync])
            for pos in range(4):
                with m.Case(39 + pos):
                    m.d.comb += writer_char.eq(Mux(
                        filter_mode_sync, 0,
                        Const(self.code(" DRY"[pos]), 6)))
            for pos in range(3):
                with m.Case(43 + pos):
                    m.d.comb += writer_char.eq(Mux(
                        feedback_selected_valid,
                        frequency_label_rport.data, 0))
            for pos in range(6):
                with m.Case(46 + pos):
                    m.d.comb += writer_char.eq(
                        palette_chars[pos][palette_sync])
            for pos in range(7):
                with m.Case(52 + pos):
                    m.d.comb += writer_char.eq(
                        save_chars[pos][save_name_index])
            for pos in range(7):
                with m.Case(59 + pos):
                    m.d.comb += writer_char.eq(
                        layout_chars[pos][displayed_layout])
            for pos in range(5):
                with m.Case(66 + pos):
                    m.d.comb += writer_char.eq(Mux(
                        bands_selected_valid,
                        frequency_label_rport.data,
                        0))
            for pos in range(5):
                with m.Case(71 + pos):
                    m.d.comb += writer_char.eq(
                        damp_chars[pos][damp_name_index])
            if self.compact_layout:
                for n in range(4):
                    for pos in range(5):
                        with m.Case(76 + n * 5 + pos):
                            m.d.comb += writer_char.eq(Mux(
                                input_modes_sync[n],
                                Const(self.code("DEPTH"[pos]), 6), 0))
        writer_last_index = 103 if self.compact_layout else 95
        with m.If(update_active):
            with m.If(update_index == writer_last_index):
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
        # Keep glyph decoding out of the pixel-clock combinational path.  The
        # previous nested character/row switches synthesized to more than a
        # hundred LUTs and sat directly on REZO's HDMI critical path.  A
        # 37-character by 8-row ROM is both smaller and, because its
        # synchronous read replaces the old char_code_q register, has the same
        # end-to-end text latency.
        glyph_init = []
        for ch in self.CHARS:
            glyph = RezoBeamDisplay.FONT_5X7.get(
                ch, RezoBeamDisplay.FONT_5X7[" "])
            glyph_init.extend((*glyph, 0))
        m.submodules.glyph_mem = glyph_mem = Memory(
            shape=unsigned(5), depth=len(glyph_init), init=glyph_init,
            attrs={"ram_style": "block"})
        glyph_rport = glyph_mem.read_port(domain="dvi")
        glyph_address = Signal(range(len(glyph_init)))
        m.d.comb += [
            glyph_address.eq((text_rport.data << 3) | glyph_row_pre_q),
            glyph_rport.addr.eq(glyph_address),
        ]

        glyph_col_q = Signal(unsigned(3))
        text_active_q = Signal()
        m.d.dvi += [
            glyph_col_q.eq(glyph_col_pre_q),
            text_active_q.eq(text_active_pre_q),
        ]

        glyph_bit = Signal(unsigned(3))
        m.d.comb += glyph_bit.eq(4 - glyph_col_q)

        text = Signal()
        m.d.dvi += text.eq(
            text_active_q & (glyph_col_q < 5) &
            glyph_rport.data.bit_select(glyph_bit, 1))

        border = active & self.outline(
            x, y,
            106 if self.compact_layout else 12,
            106 if self.compact_layout else 12,
            614 if self.compact_layout else 708,
            614 if self.compact_layout else 708, t=2)
        title_panel = active & self.rect(
            x, y,
            112 if self.compact_layout else 20,
            120 if self.compact_layout else 20,
            608 if self.compact_layout else 700,
            164 if self.compact_layout else 82)
        side_page_chip = Const(0)
        if self.compact_layout:
            # Reuse the former side chip's renderer slot for the PAGE value
            # in the central header.  The circular side wings remain blank.
            side_page_chip = active & self.rect(
                text_x, text_y, 216, 120, 360, 160)
        # One shared rectangle keeps the pixel path shallow. FILTER needs the
        # deepest field because its fifth fader ends at y=690; ending its
        # background at y=666 left RESONANCE floating in the black margin.
        content_y0 = Signal(unsigned(10), init=240 if self.compact_layout else 190)
        content_y1 = Signal(unsigned(10), init=575 if self.compact_layout else 666)
        m.d.dvi += [
            # INPUT starts its field immediately above IN0 MODE (y=167), but
            # below the INPUT ROUTING heading. Other pages retain y=190.
            content_y0.eq(Mux(input_page,
                              218 if self.compact_layout else 160,
                              240 if self.compact_layout else 190)),
            content_y1.eq(Mux(filter_page | input_page,
                              599 if self.compact_layout else 700,
                              Mux(tune_page,
                                  588 if self.compact_layout else 684,
                                  575 if self.compact_layout else 666))),
        ]
        content_panel = active & self.rect(
            x, y, 125 if self.compact_layout else 28, content_y0,
            594 if self.compact_layout else 692, content_y1)
        control_panel_x0 = 283 if self.compact_layout else 118
        control_panel_x1 = 594 if self.compact_layout else 650
        control_fill_x0 = 289 if self.compact_layout else 124
        # FEEDBACK uses a native left-aligned value column. The DAMPING chip
        # and both safety faders begin on the same physical x coordinate.
        tune_panel_x0 = 268 if self.compact_layout else 144
        tune_panel_x1 = 567 if self.compact_layout else control_panel_x1
        tune_fill_x0 = 289 if self.compact_layout else 156
        tune_y_shift = 0
        if self.compact_layout:
            bank_meter_rows = Const(0)
            filter_meter_rows = Const(0)
            for row_y0 in compact_main_control_y0s[:3]:
                bank_meter_rows = bank_meter_rows | self.rect(
                    x, y, control_panel_x0, row_y0 - 2,
                    control_panel_x1, row_y0 + 18)
            for row_y0 in compact_main_control_y0s:
                filter_meter_rows = filter_meter_rows | self.rect(
                    x, y, control_panel_x0, row_y0 - 2,
                    control_panel_x1, row_y0 + 18)
        else:
            bank_meter_rows = (
                self.rect(x, y, control_panel_x0, 552, 650, 576) |
                self.rect(x, y, control_panel_x0, 584, 650, 608) |
                self.rect(x, y, control_panel_x0, 616, 650, 640))
            filter_meter_rows = (
                self.rect(x, y, control_panel_x0, 542, 650, 562) |
                self.rect(x, y, control_panel_x0, 574, 650, 594) |
                self.rect(x, y, control_panel_x0, 606, 650, 626) |
                self.rect(x, y, control_panel_x0, 638, 650, 658) |
                self.rect(x, y, control_panel_x0, 670, 650, 690))
        meter_panel = active & (
            (bank_page & bank_meter_rows) |
            (tune_page & (
                self.rect(x, y, tune_panel_x0,
                          398 + tune_y_shift, tune_panel_x1,
                          418 + tune_y_shift) |
                self.rect(x, y, tune_panel_x0,
                          430 + tune_y_shift, tune_panel_x1,
                          450 + tune_y_shift))))
        filter_meter_panel = active & filter_page & filter_meter_rows
        if self.compact_layout:
            # Six- and seven-character dynamic values have an unavoidable
            # half-cell visual phase in the 16px tile font. Offset their
            # chips by half a cell so the visible glyphs, rather than merely
            # the character slots, are centered in each box.
            palette_chip = advanced_page & self.rect(
                text_x, text_y, 344, 260, 456, 300)
            palette_select = advanced_page & (
                self.selected == RezoHardwareUI.TARGET_PALETTE) & self.outline(
                    text_x, text_y, 340, 256, 460, 304, t=3)
            save_default_chip = advanced_page & self.rect(
                text_x, text_y, 328, 324, 456, 364)
            save_default_select = advanced_page & (
                self.selected == RezoHardwareUI.TARGET_SAVE_DEFAULT) & self.outline(
                    text_x, text_y, 324, 320, 460, 368, t=3)
            damp_chip = tune_page & self.rect(
                text_x, text_y, 264, 456, 360, 488)
            damp_select = tune_page & (
                self.selected == RezoHardwareUI.TARGET_DAMP) & self.outline(
                    text_x, text_y, 260, 452, 364, 492, t=3)
            layout_chip = bands_page & self.rect(
                text_x, text_y, 256, 168, 384, 200)
            layout_select = bands_page & (
                self.selected == RezoHardwareUI.TARGET_BAND_LAYOUT) & self.outline(
                    text_x, text_y, 252, 164, 388, 204, t=3)
        else:
            palette_chip = advanced_page & self.rect(x, y, 264, 228, 408, 268)
            palette_select = advanced_page & (
                self.selected == RezoHardwareUI.TARGET_PALETTE) & self.outline(
                    x, y, 260, 224, 412, 272, t=3)
            save_default_chip = advanced_page & self.rect(x, y, 264, 292, 408, 332)
            save_default_select = advanced_page & (
                self.selected == RezoHardwareUI.TARGET_SAVE_DEFAULT) & self.outline(
                    x, y, 260, 288, 412, 336, t=3)
            damp_chip = tune_page & self.rect(x, y, 156, 504, 316, 536)
            damp_select = tune_page & (
                self.selected == RezoHardwareUI.TARGET_DAMP) & self.outline(
                    x, y, 150, 500, 322, 540, t=3)
            layout_chip = bands_page & self.rect(x, y, 136, 100, 264, 138)
            layout_select = bands_page & (
                self.selected == RezoHardwareUI.TARGET_BAND_LAYOUT) & self.outline(
                    x, y, 131, 95, 269, 143, t=3)

        preset_chip = Signal()
        preset_select = Signal()
        preset_group_select = Signal()
        band_slot = Signal()
        band_zero = Signal()
        band_marker = Signal()
        band_fill = Signal()
        band_mod_fill = Signal()
        group_cell = Signal()
        group_fill = Signal()
        group_select = Signal()
        output_cell = Signal()
        output_fill = Signal()
        output_select = Signal()
        filter_cv_panel = Signal()
        filter_cv_fill = Signal()
        filter_cv_line = Signal()
        filter_cv_select = Signal()
        if self.compact_layout:
            # BANK/FILTER is a main-page control; PAGE owns the header.
            mode_chip = home_page & self.rect(
                text_x, text_y, 464, 168, 584, 200)
            mode_select = home_page & (
                self.selected == RezoHardwareUI.TARGET_MODE) & self.outline(
                    text_x, text_y, 460, 164, 588, 204, t=3)
            filter_type_chip = filter_page & self.rect(
                text_x, text_y, 216, 168, 288, 200)
            filter_type_select = filter_page & (
                self.selected == RezoHardwareUI.TARGET_FILTER_TYPE) & self.outline(
                    text_x, text_y, 212, 164, 292, 204, t=3)
        else:
            mode_chip = home_page & self.rect(x, y, 456, 32, 596, 76)
            mode_select = home_page & (
                self.selected == RezoHardwareUI.TARGET_MODE) & self.outline(
                    x, y, 452, 28, 600, 80, t=3)
            filter_type_chip = filter_page & self.rect(x, y, 136, 100, 264, 138)
            filter_type_select = filter_page & (
                self.selected == RezoHardwareUI.TARGET_FILTER_TYPE) & self.outline(
                    x, y, 131, 95, 269, 143, t=3)

        preset_chip_signals = []
        preset_select_signals = []
        group_cell_signals = []
        group_select_signals = []

        input_control_x0 = 304 if self.compact_layout else 326
        input_control_mid = 440 if self.compact_layout else 490
        input_gain_ends = [Signal(signed(12), init=input_control_x0,
                                  name=f"input_gain_end{n}")
                           for n in range(4)]
        input_depth_ends = [Signal(signed(12), init=input_control_mid,
                                   name=f"input_depth_end{n}")
                            for n in range(4)]
        input_meter_ends = [Signal(signed(12), init=input_control_x0,
                                   name=f"input_meter_end{n}")
                            for n in range(4)]
        for n in range(4):
            if self.compact_layout:
                # Native compact controls begin at text column 19 (x=304).
                # The bipolar CV lane is centred at x=440.
                m.d.dvi += [
                    input_gain_ends[n].eq(
                        # Keep the unsigned gain inside the 272px VALUE lane
                        # [304, 576) without another display-domain adder. The
                        # former 1.5x map reached x=686 at high gains.
                        input_control_x0 + self.input_gains[n]),
                    input_depth_ends[n].eq(
                        440 + self.cv_depths[n] +
                        (self.cv_depths[n] >> 1)),
                    input_meter_ends[n].eq(Mux(
                        self.input_modes[n] == RezoCore.INPUT_MODE_CV,
                        440 + (self.input_meters[n] << 2) +
                              (self.input_meters[n] << 1),
                        304 + (self.input_meters[n] << 3) +
                              (self.input_meters[n] << 2))),
                ]
            else:
                m.d.dvi += [
                    input_gain_ends[n].eq(
                        326 + self.input_gains[n] +
                        (self.input_gains[n] >> 2)),
                    input_depth_ends[n].eq(
                        490 + self.cv_depths[n] +
                        (self.cv_depths[n] >> 2)),
                    input_meter_ends[n].eq(Mux(
                        self.input_modes[n] == RezoCore.INPUT_MODE_CV,
                        490 + (self.input_meters[n] << 2) +
                              self.input_meters[n],
                        326 + (self.input_meters[n] << 3) +
                              (self.input_meters[n] << 1))),
                ]

        filter_cv_panel_signals = []
        filter_cv_fill_signals = []
        filter_cv_line_signals = []
        filter_cv_select_signals = []
        filter_cv_row = Signal(unsigned(3))
        filter_cv_source = Signal(unsigned(2))
        filter_cv_row_y = Signal(signed(12))
        filter_cv_x0 = Signal(signed(12))
        filter_cv_center = Signal(signed(12))
        filter_cv_row_active = Signal()
        filter_cv_col_active = Signal()
        filter_cv_index = Signal(unsigned(4))
        filter_cv_depth_pre = Signal(signed(6))
        filter_cv_target_pre = Signal(unsigned(7))
        filter_cv_x_pre_q = Signal.like(x)
        filter_cv_y_pre_q = Signal.like(y)
        filter_cv_row_y_pre_q = Signal.like(filter_cv_row_y)
        filter_cv_x0_pre_q = Signal.like(filter_cv_x0)
        filter_cv_center_pre_q = Signal.like(filter_cv_center)
        filter_cv_target_pre_q = Signal.like(filter_cv_target_pre)
        filter_cv_row_active_pre_q = Signal()
        filter_cv_col_active_pre_q = Signal()
        filter_cv_page_pre_q = Signal()
        filter_cv_x_q = Signal.like(x)
        filter_cv_y_q = Signal.like(y)
        filter_cv_row_y_q = Signal.like(filter_cv_row_y)
        filter_cv_x0_q = Signal.like(filter_cv_x0)
        filter_cv_center_q = Signal.like(filter_cv_center)
        filter_cv_depth_q = Signal.like(filter_cv_depth_pre)
        filter_cv_target_q = Signal.like(filter_cv_target_pre)
        filter_cv_row_active_q = Signal()
        filter_cv_col_active_q = Signal()
        filter_cv_page_q = Signal()
        filter_cv_end = Signal(signed(12))
        m.submodules.filter_cv_mem = filter_cv_mem = Memory(
            shape=signed(6), depth=15, init=[0] * 15,
            attrs={"ram_style": "block"})
        filter_cv_rport = filter_cv_mem.read_port(domain="dvi")
        filter_cv_wport = filter_cv_mem.write_port(domain="sync")
        m.d.comb += [
            filter_cv_wport.addr.eq(self.filter_cv_write_addr),
            filter_cv_wport.data.eq(self.filter_cv_write_data),
            filter_cv_wport.en.eq(self.filter_cv_write_en),
        ]
        m.d.comb += [
            filter_cv_row.eq(0),
            filter_cv_source.eq(0),
            filter_cv_row_y.eq(
                compact_matrix_text_rows[0] * 16 - 3
                if self.compact_layout else 250),
            filter_cv_x0.eq(284 if self.compact_layout else 220),
            filter_cv_center.eq(318 if self.compact_layout else 280),
            filter_cv_row_active.eq(0),
            filter_cv_col_active.eq(0),
        ]
        for destination in range(5):
            row_y = (
                compact_matrix_text_rows[destination] * 16 - 3
                if self.compact_layout else 250 + destination * 80)
            row_decode_y0 = row_y - (3 if self.compact_layout else 5)
            row_decode_y1 = row_y + (23 if self.compact_layout else 33)
            with m.If((y >= row_decode_y0) & (y < row_decode_y1)):
                m.d.comb += [
                    filter_cv_row.eq(destination),
                    filter_cv_row_y.eq(row_y),
                    filter_cv_row_active.eq(1),
                ]
        for source in range(3):
            x0 = (284 + source * 113 if self.compact_layout
                  else 220 + source * 160)
            cell_width = 68 if self.compact_layout else 120
            cell_center = cell_width // 2
            with m.If((x >= x0 - 5) & (x < x0 + cell_width + 5)):
                m.d.comb += [
                    filter_cv_source.eq(source),
                    filter_cv_x0.eq(x0),
                    filter_cv_center.eq(x0 + cell_center),
                    filter_cv_col_active.eq(1),
                ]
        m.d.comb += [
            filter_cv_index.eq(filter_cv_source + filter_cv_row +
                               (filter_cv_row << 1)),
            filter_cv_rport.addr.eq(filter_cv_index),
            filter_cv_depth_pre.eq(filter_cv_rport.data),
            filter_cv_target_pre.eq(RezoHardwareUI.TARGET_FILTER_CV_BASE +
                                    filter_cv_index),
            filter_cv_end.eq(filter_cv_center_q + filter_cv_depth_q +
                             (filter_cv_depth_q >> 1)),
        ]
        m.d.dvi += [
            filter_cv_x_pre_q.eq(x),
            filter_cv_y_pre_q.eq(y),
            filter_cv_row_y_pre_q.eq(filter_cv_row_y),
            filter_cv_x0_pre_q.eq(filter_cv_x0),
            filter_cv_center_pre_q.eq(filter_cv_center),
            filter_cv_target_pre_q.eq(filter_cv_target_pre),
            filter_cv_row_active_pre_q.eq(filter_cv_row_active),
            filter_cv_col_active_pre_q.eq(filter_cv_col_active),
            filter_cv_page_pre_q.eq(filter_cv_page),
            filter_cv_x_q.eq(filter_cv_x_pre_q),
            filter_cv_y_q.eq(filter_cv_y_pre_q),
            filter_cv_row_y_q.eq(filter_cv_row_y_pre_q),
            filter_cv_x0_q.eq(filter_cv_x0_pre_q),
            filter_cv_center_q.eq(filter_cv_center_pre_q),
            filter_cv_depth_q.eq(filter_cv_depth_pre),
            filter_cv_target_q.eq(filter_cv_target_pre_q),
            filter_cv_row_active_q.eq(filter_cv_row_active_pre_q),
            filter_cv_col_active_q.eq(filter_cv_col_active_pre_q),
            filter_cv_page_q.eq(filter_cv_page_pre_q),
        ]
        filter_cv_cell_active = (filter_cv_page_q & filter_cv_row_active_q &
                                 filter_cv_col_active_q)
        filter_cv_panel_signals.append(
            filter_cv_cell_active &
            (filter_cv_x_q >= filter_cv_x0_q) &
            (filter_cv_x_q < filter_cv_x0_q +
             (68 if self.compact_layout else 120)) &
            (filter_cv_y_q >= filter_cv_row_y_q) &
            (filter_cv_y_q < filter_cv_row_y_q +
             (20 if self.compact_layout else 28)))
        filter_cv_fill_signals.append(
            filter_cv_cell_active &
            (filter_cv_y_q >= filter_cv_row_y_q +
             (4 if self.compact_layout else 7)) &
            (filter_cv_y_q < filter_cv_row_y_q +
             (16 if self.compact_layout else 21)) & Mux(
                filter_cv_depth_q >= 0,
                (filter_cv_x_q >= filter_cv_center_q) &
                (filter_cv_x_q < filter_cv_end),
                (filter_cv_x_q >= filter_cv_end) &
                (filter_cv_x_q < filter_cv_center_q)))
        filter_cv_line_signals.append(
            filter_cv_cell_active &
            (filter_cv_x_q >= filter_cv_center_q - 2) &
            (filter_cv_x_q < filter_cv_center_q + 2) &
            (filter_cv_y_q >= filter_cv_row_y_q +
             (1 if self.compact_layout else 3)) &
            (filter_cv_y_q < filter_cv_row_y_q +
             (19 if self.compact_layout else 25)))
        filter_cv_outer = filter_cv_cell_active
        filter_cv_select_signals.append(
            filter_cv_outer & (self.selected == filter_cv_target_q) &
            ((filter_cv_x_q < filter_cv_x0_q - 2) |
             (filter_cv_x_q >= filter_cv_x0_q +
              (70 if self.compact_layout else 122)) |
             (filter_cv_y_q < filter_cv_row_y_q - 2) |
             (filter_cv_y_q >= filter_cv_row_y_q +
              (22 if self.compact_layout else 30))))

        if self.compact_layout:
            preset_chip_signals.append(bank_page & self.rect(
                text_x, text_y, 248, 168, 328, 200))
            preset_select_signals.append(
                bank_page & self.editing &
                (self.selected == RezoHardwareUI.TARGET_PRESET) &
                self.outline(text_x, text_y, 244, 164, 332, 204, t=3))
        else:
            preset_chip_signals.append(
                bank_page & self.rect(x, y, 136, 100, 264, 138))
            preset_select_signals.append(
                bank_page & self.editing &
                (self.selected == RezoHardwareUI.TARGET_PRESET) &
                self.outline(x, y, 131, 95, 269, 143, t=3))

        # Compact full-width faders use a single x-to-value lookup shared by
        # BANK, FILTER, and FEEDBACK. Comparing the selected control against
        # this threshold preserves a full 0..128 range across the widened
        # control gutter without synthesizing dynamic coordinate arithmetic.
        if self.compact_layout:
            compact_fader_x0 = 289
            compact_fader_x1 = 588
            compact_fader_width = compact_fader_x1 - compact_fader_x0
            compact_fader_x_init = []
            for pixel_x in range(self.PANEL_W):
                if compact_fader_x0 <= pixel_x < compact_fader_x1:
                    compact_fader_x_init.append(
                        ((((pixel_x - compact_fader_x0) * 128) //
                          compact_fader_width + 1) | (1 << 8)))
                else:
                    compact_fader_x_init.append(0)
            m.submodules.compact_fader_x_mem = compact_fader_x_mem = Memory(
                shape=unsigned(9), depth=self.PANEL_W,
                init=compact_fader_x_init,
                attrs={"ram_style": "block"})
            compact_fader_x_rport = compact_fader_x_mem.read_port(
                domain="dvi")
            # FEEDBACK's safety block begins 21 native pixels to the left of
            # BANK/FILTER while retaining the same width and value mapping.
            compact_fader_lookup_x = Signal(range(self.PANEL_W))
            m.d.comb += [
                compact_fader_lookup_x.eq(Mux(
                    tune_page & (x < self.PANEL_W - 21), x + 21,
                    Mux(x < self.PANEL_W, x, 0))),
                compact_fader_x_rport.addr.eq(compact_fader_lookup_x),
            ]
            compact_fader_threshold = compact_fader_x_rport.data[:8]
            compact_fader_x_valid = compact_fader_x_rport.data[8]

        # The ten band columns have identical vertical geometry. Decode their
        # fixed horizontal layout once in a small ROM, then select the active
        # band's dynamic values. This replaces ten parallel copies of every
        # x/y rectangle comparator while preserving the exact pixel layout.
        band_x_init = []
        for address in range(self.PANEL_W):
            # Prefetch one pixel so the extra value-selection register below
            # remains aligned with the renderer's existing geometry pipeline.
            pixel_x = address + 1
            encoded = 0
            for n in range(RezoCore.N_BANDS):
                x0 = (133 + 47 * n if self.compact_layout
                      else 48 + 66 * n)
                x1 = x0 + (30 if self.compact_layout else 42)
                select_margin = 5 if self.compact_layout else 7
                edge_margin = 3 if self.compact_layout else 4
                zero_margin = 4 if self.compact_layout else 5
                if x0 - select_margin <= pixel_x < x1 + select_margin:
                    encoded = n
                    encoded |= 1 << 6  # selection outer span
                    if (pixel_x < x0 - edge_margin or
                            pixel_x >= x1 + edge_margin):
                        encoded |= 1 << 7  # selection vertical edge
                    if x0 <= pixel_x < x1:
                        encoded |= 1 << 4  # fill/slot span
                    if x0 - zero_margin <= pixel_x < x1 + zero_margin:
                        encoded |= 1 << 5  # zero-line span
                    break
            band_x_init.append(encoded)
        m.submodules.band_x_mem = band_x_mem = Memory(
            shape=unsigned(8), depth=self.PANEL_W, init=band_x_init,
            attrs={"ram_style": "block"})
        band_x_rport = band_x_mem.read_port(domain="dvi")
        # The ten native 30px buttons plus nine 17px gutters span [133, 586),
        # centred on the 720px canvas. Every page reuses this exact element.
        band_lookup_x = Signal(range(self.PANEL_W))
        m.d.comb += [
            band_lookup_x.eq(Mux(x < self.PANEL_W, x, 0)),
            band_x_rport.addr.eq(band_lookup_x),
        ]

        band_y_q = Signal.like(y)
        band_active_q = Signal()
        band_home_page_q = Signal()
        band_bank_page_q = Signal()
        band_filter_page_q = Signal()
        band_tune_page_q = Signal()
        band_bands_page_q = Signal()
        band_filter_mode_q = Signal()
        band_selected_target_q = Signal.like(self.selected)
        m.d.dvi += [
            band_y_q.eq(y),
            band_active_q.eq(active),
            band_home_page_q.eq(home_page),
            band_bank_page_q.eq(bank_page),
            band_filter_page_q.eq(filter_page),
            band_tune_page_q.eq(tune_page),
            band_bands_page_q.eq(bands_page),
            band_filter_mode_q.eq(self.filter_mode),
            band_selected_target_q.eq(self.selected),
        ]

        band_index = band_x_rport.data[:4]
        band_index_q = Signal(unsigned(4))
        band_fill_x_q = Signal()
        band_zero_x_q = Signal()
        band_select_x_q = Signal()
        band_select_edge_x_q = Signal()
        band_top_q = Signal.like(band_top_values[0])
        band_bottom_q = Signal.like(band_bottom_values[0])
        band_base_marker_y_q = Signal.like(band_base_marker_values[0])
        band_positive_q = Signal()
        band_negative_q = Signal()
        band_base_level_q = Signal.like(self.levels[0])
        band_feedback_send_q = Signal()
        band_enable_q = Signal()
        band_y_value_q = Signal.like(band_y_q)
        band_active_value_q = Signal()
        band_home_page_value_q = Signal()
        band_bank_page_value_q = Signal()
        band_filter_page_value_q = Signal()
        band_tune_page_value_q = Signal()
        band_bands_page_value_q = Signal()
        band_filter_mode_value_q = Signal()
        band_selected_target_value_q = Signal.like(self.selected)
        m.d.dvi += [
            band_index_q.eq(band_index),
            band_fill_x_q.eq(band_x_rport.data[4]),
            band_zero_x_q.eq(band_x_rport.data[5]),
            band_select_x_q.eq(band_x_rport.data[6]),
            band_select_edge_x_q.eq(band_x_rport.data[7]),
            band_top_q.eq(Array(band_top_values)[band_index]),
            band_bottom_q.eq(Array(band_bottom_values)[band_index]),
            band_base_marker_y_q.eq(
                Array(band_base_marker_values)[band_index]),
            band_positive_q.eq(Array(band_positive_values)[band_index]),
            band_negative_q.eq(Array(band_negative_values)[band_index]),
            band_base_level_q.eq(Array(self.levels)[band_index]),
            band_feedback_send_q.eq(Array(self.feedback_sends)[band_index]),
            band_enable_q.eq(Array(self.band_enables)[band_index]),
            band_y_value_q.eq(band_y_q),
            band_active_value_q.eq(band_active_q),
            band_home_page_value_q.eq(band_home_page_q),
            band_bank_page_value_q.eq(band_bank_page_q),
            band_filter_page_value_q.eq(band_filter_page_q),
            band_tune_page_value_q.eq(band_tune_page_q),
            band_bands_page_value_q.eq(band_bands_page_q),
            band_filter_mode_value_q.eq(band_filter_mode_q),
            band_selected_target_value_q.eq(band_selected_target_q),
        ]

        bands_enable_y0 = 283 if self.compact_layout else 232
        bands_button_h = 34 if self.compact_layout else 48
        bands_frequency_y0 = 382 if self.compact_layout else 392
        bands_button_y = (
            ((band_y_value_q >= bands_enable_y0) &
             (band_y_value_q < bands_enable_y0 + bands_button_h)) |
            ((band_y_value_q >= bands_frequency_y0) &
             (band_y_value_q < bands_frequency_y0 + bands_button_h)))
        band_slot_y = Mux(
            band_bands_page_value_q, bands_button_y,
            Mux(band_tune_page_value_q,
                (band_y_value_q >= bands_enable_y0) &
                (band_y_value_q < bands_enable_y0 + bands_button_h),
                (band_y_value_q >= main_band_y0) &
                (band_y_value_q < main_band_y1)))
        main_band_y = (
            ((band_y_value_q >= main_band_y0) &
             (band_y_value_q < main_band_y1))
            if self.compact_layout else Const(1))
        effective_bank_fill = band_fill_x_q & (
            (band_positive_q & (band_y_value_q >= band_top_q) &
             (band_y_value_q < zero_y)) |
            (band_negative_q & (band_y_value_q >= zero_y) &
             (band_y_value_q < band_bottom_q)))
        base_bank_fill = band_fill_x_q & (
            ((band_base_level_q > 0) &
             (band_y_value_q >= band_base_marker_y_q) &
             (band_y_value_q < zero_y)) |
            ((band_base_level_q < 0) & (band_y_value_q >= zero_y) &
             (band_y_value_q < band_base_marker_y_q)))
        base_marker = (band_fill_x_q &
                       (band_y_value_q >= band_base_marker_y_q - 2) &
                       (band_y_value_q < band_base_marker_y_q + 3))
        selection_outline = (
            band_active_value_q & band_select_x_q &
            (band_y_value_q >= main_band_y0 - 5) &
            (band_y_value_q < main_band_y1 + 5) &
            (band_select_edge_x_q |
             (band_y_value_q < main_band_y0 - 3) |
             (band_y_value_q >= main_band_y1 + 3)))
        feedback_selection_outline = (
            band_active_value_q & band_select_x_q &
            (band_y_value_q >= bands_enable_y0 - 5) &
            (band_y_value_q < bands_enable_y0 + bands_button_h + 5) &
            (band_select_edge_x_q |
             (band_y_value_q < bands_enable_y0 - 3) |
             (band_y_value_q >= bands_enable_y0 + bands_button_h + 3)))
        selected_band = (
            band_selected_target_value_q ==
            RezoHardwareUI.TARGET_BAND_BASE + band_index_q)
        feedback_band_selected = (
            band_selected_target_value_q ==
            RezoHardwareUI.TARGET_FEEDBACK_SEND_BASE + band_index_q)
        enable_band_selected = (
            band_selected_target_value_q ==
            RezoHardwareUI.TARGET_BAND_ENABLE_BASE + band_index_q)
        frequency_band_selected = (
            band_selected_target_value_q ==
            RezoHardwareUI.TARGET_BAND_FREQ_BASE + band_index_q)
        bands_edit_outline = (
            band_active_value_q & band_select_x_q &
            ((enable_band_selected &
              (band_y_value_q >= bands_enable_y0 - 5) &
              (band_y_value_q < bands_enable_y0 + bands_button_h + 5) &
              (band_select_edge_x_q |
               (band_y_value_q < bands_enable_y0 - 3) |
               (band_y_value_q >= bands_enable_y0 + bands_button_h + 3))) |
             (frequency_band_selected &
              (band_y_value_q >= bands_frequency_y0 - 5) &
              (band_y_value_q < bands_frequency_y0 + bands_button_h + 5) &
              (band_select_edge_x_q |
               (band_y_value_q < bands_frequency_y0 - 3) |
               (band_y_value_q >= bands_frequency_y0 +
                bands_button_h + 3)))))
        m.d.comb += [
            band_slot.eq(band_active_value_q &
                         ((band_home_page_value_q &
                           (band_filter_mode_value_q | band_enable_q)) |
                          (band_tune_page_value_q &
                           (band_filter_mode_value_q | band_enable_q)) |
                          band_bands_page_value_q) &
                         band_fill_x_q & band_slot_y),
            band_zero.eq(
                band_active_value_q & (
                (band_bank_page_value_q & band_enable_q & band_zero_x_q &
                 (band_y_value_q >= zero_y - 1) &
                 (band_y_value_q < zero_y + 2)) |
                (band_filter_page_value_q & band_zero_x_q &
                 (band_y_value_q >= main_band_y1 - 3) &
                 (band_y_value_q < main_band_y1)) |
                # Disabled BANK bands retain a dim frame on the main and
                # feedback pages so their position remains legible without
                # implying that they contribute audio.
                (~band_enable_q &
                 (band_bank_page_value_q |
                 (band_tune_page_value_q & ~band_filter_mode_value_q)) &
                 Mux(band_tune_page_value_q,
                     feedback_selection_outline, selection_outline)))),
            band_marker.eq(
                band_active_value_q & band_bank_page_value_q &
                band_enable_q & main_band_y & base_marker),
            band_fill.eq(
                band_active_value_q & (
                (band_bank_page_value_q & band_enable_q & main_band_y &
                 base_bank_fill) |
                (band_filter_page_value_q & main_band_y & band_fill_x_q &
                 band_positive_q &
                 (band_y_value_q >= band_top_q) &
                 (band_y_value_q < main_band_y1)) |
                (band_tune_page_value_q &
                 (band_filter_mode_value_q | band_enable_q) & band_fill_x_q &
                 band_slot_y & band_feedback_send_q) |
                (band_bands_page_value_q & band_fill_x_q & band_enable_q &
                 (band_y_value_q >= bands_enable_y0) &
                 (band_y_value_q < bands_enable_y0 + bands_button_h)))),
            band_mod_fill.eq(
                band_active_value_q & band_bank_page_value_q & band_enable_q &
                main_band_y & (base_bank_fill ^ effective_bank_fill) &
                ~base_marker),
        ]
        band_select_q0 = (
            (band_bank_page_value_q & band_enable_q & selected_band &
             selection_outline) |
            (band_tune_page_value_q &
             (band_filter_mode_value_q | band_enable_q) &
             feedback_band_selected & feedback_selection_outline) |
            (band_bands_page_value_q &
             (enable_band_selected | frequency_band_selected) &
             bands_edit_outline))

        # Share the four INPUT groups through one tiny y-coordinate decoder.
        # Compact INPUT geometry is decoded directly from the same native
        # raster coordinate used by its 16px text cells. The removed scaled
        # renderer independently rounded text and panel edges, accumulating a
        # visible one-pixel phase error between groups. A native 96px cadence
        # makes every MODE/VALUE/DEPTH row exactly congruent. The inactive
        # legacy renderer below retains its original coordinate system.
        input_y_init = []
        for pixel_y in range(self.PANEL_H):
            encoded_input_y = 0
            for input_index_init in range(4):
                # Compact base is three pixels above MODE's glyph cell.  A
                # 20px value panel therefore has the same 6.5px visual centre
                # as the fourteen visible glyph scanlines (the final two
                # lines of each 16px text cell are blank).
                input_base = (221 if self.compact_layout else 232) + input_index_init * 96
                if input_base <= pixel_y < input_base + (
                        96 if self.compact_layout else 96):
                    input_local_init = pixel_y - input_base
                    encoded_input_y = (
                        input_local_init | (input_index_init << 8) | (1 << 10))
                    break
            if encoded_input_y:
                input_y_init.append(
                    encoded_input_y)
            else:
                input_y_init.append(0)
        m.submodules.input_y_mem = input_y_mem = Memory(
            shape=unsigned(11), depth=self.PANEL_H, init=input_y_init,
            attrs={"ram_style": "block"})
        input_y_rport = input_y_mem.read_port(domain="dvi")
        m.d.comb += input_y_rport.addr.eq(
            text_y if self.compact_layout else y)

        input_x_q = Signal.like(x)
        m.d.dvi += input_x_q.eq(x + 1)
        input_local_y = input_y_rport.data[:8]
        input_index = input_y_rport.data[8:10]
        input_row_valid = input_y_rport.data[10]
        input_mode = Array(self.input_modes)[input_index]
        input_depth = Array(self.cv_depths)[input_index]
        input_meter = Array(self.input_meters)[input_index]
        input_gain_end = Array(input_gain_ends)[input_index]
        input_depth_end = Array(input_depth_ends)[input_index]
        input_meter_end = Array(input_meter_ends)[input_index]
        # Decode the four group targets as constants. Expressing this as
        # TARGET_INPUT_BASE + 3 * input_index placed a carry chain after the
        # block-RAM row decoder and became the compact display's pixel-clock
        # critical path at high utilisation.
        input_targets = Array(
            Const(RezoHardwareUI.TARGET_INPUT_BASE + n * 3, 7)
            for n in range(4))
        input_target = input_targets[input_index]
        input_x_value_q = Signal.like(input_x_q)
        input_local_value_q = Signal.like(input_local_y)
        input_valid_value_q = Signal()
        input_page_value_q = Signal()
        input_is_cv_value_q = Signal()
        input_depth_negative_q = Signal()
        input_meter_negative_q = Signal()
        input_gain_end_q = Signal.like(input_gain_end)
        input_depth_end_q = Signal.like(input_depth_end)
        input_meter_end_q = Signal.like(input_meter_end)
        input_target_q = Signal.like(input_target)
        input_row_selected_q = Signal.like(self.selected)
        m.d.dvi += [
            input_x_value_q.eq(input_x_q),
            input_local_value_q.eq(input_local_y),
            input_valid_value_q.eq(input_row_valid),
            input_page_value_q.eq(input_page),
            input_is_cv_value_q.eq(input_mode == RezoCore.INPUT_MODE_CV),
            input_depth_negative_q.eq(input_depth < 0),
            input_meter_negative_q.eq(input_meter < 0),
            input_gain_end_q.eq(input_gain_end),
            input_depth_end_q.eq(input_depth_end),
            input_meter_end_q.eq(input_meter_end),
            input_target_q.eq(input_target),
            input_row_selected_q.eq(self.selected),
        ]
        input_visible = input_page_value_q & input_valid_value_q
        input_is_cv = input_is_cv_value_q
        input_lane_panel_x0 = 136 if self.compact_layout else 116
        input_mode_x1 = 402 if self.compact_layout else 304
        input_value_x1 = 370 if self.compact_layout else 656
        # Compact labels remain on the unshaded field. Only the editable MODE
        # value, CV target value, AUD gain fader and CV DEPTH fader receive a
        # panel, matching the value-only treatment used elsewhere in REZO.
        # Native column 18 is the common right edge of MODE/VALUE/DEPTH. The
        # value chips begin at x=304, while their glyphs begin at column 20 so
        # AUDIO/CV and the three-character targets share the chip center.
        # Native compact lane bounds all derive from the same three-pixel
        # top inset relative to their text cells: MODE 3, VALUE 35, DEPTH 67.
        # This is intentionally one shared grid, not per-input correction.
        input_panel_q0 = input_visible & (
            self.rect(input_x_value_q, input_local_value_q,
                      304 if self.compact_layout else input_lane_panel_x0,
                      0 if self.compact_layout else 4,
                      input_mode_x1 if self.compact_layout else 304,
                      20 if self.compact_layout else 32) |
            Mux(input_is_cv,
                self.rect(input_x_value_q, input_local_value_q,
                          304 if self.compact_layout else input_lane_panel_x0,
                          32 if self.compact_layout else 36,
                          input_value_x1 if self.compact_layout else 656,
                          52 if self.compact_layout else 64),
                self.rect(input_x_value_q, input_local_value_q,
                          304 if self.compact_layout else input_lane_panel_x0,
                          32 if self.compact_layout else 36,
                          576 if self.compact_layout else 656,
                          52 if self.compact_layout else 64)) |
            (input_is_cv & self.rect(
                input_x_value_q, input_local_value_q,
                304 if self.compact_layout else input_lane_panel_x0,
                64 if self.compact_layout else 68,
                576 if self.compact_layout else 656,
                84 if self.compact_layout else 96)))
        input_lane_select_x0 = 132 if self.compact_layout else 112
        input_select_q0 = input_visible & (
            ((input_row_selected_q == input_target_q) &
             self.outline(input_x_value_q, input_local_value_q,
                          300 if self.compact_layout else input_lane_select_x0, 0,
                          input_mode_x1 + 4 if self.compact_layout else 308,
                          24 if self.compact_layout else 38, t=3)) |
            ((input_row_selected_q == input_target_q + 1) &
             Mux(input_is_cv,
                 self.outline(input_x_value_q, input_local_value_q,
                              300 if self.compact_layout else input_lane_select_x0,
                              28 if self.compact_layout else 32,
                              input_value_x1 + 4 if self.compact_layout else 660,
                              56 if self.compact_layout else 68, t=3),
                 self.outline(input_x_value_q, input_local_value_q,
                              300 if self.compact_layout else input_lane_select_x0,
                              28 if self.compact_layout else 32,
                              580 if self.compact_layout else 660,
                              56 if self.compact_layout else 68, t=3))) |
            (input_is_cv & (input_row_selected_q == input_target_q + 2) &
             self.outline(input_x_value_q, input_local_value_q,
                          300 if self.compact_layout else input_lane_select_x0,
                          60 if self.compact_layout else 64,
                          580 if self.compact_layout else 660,
                          88 if self.compact_layout else 100, t=3)))
        input_fill_q0 = input_visible & Mux(
            input_is_cv,
            Mux(~input_depth_negative_q,
                self.rect(input_x_value_q, input_local_value_q,
                          440 if self.compact_layout else 490,
                          68 if self.compact_layout else 75,
                          input_depth_end_q, 80 if self.compact_layout else 89),
                self.rect(input_x_value_q, input_local_value_q,
                          input_depth_end_q, 68 if self.compact_layout else 75,
                          440 if self.compact_layout else 490,
                          80 if self.compact_layout else 89)),
            self.rect(input_x_value_q, input_local_value_q,
                      304 if self.compact_layout else 326,
                      36 if self.compact_layout else 43,
                      input_gain_end_q, 48 if self.compact_layout else 57))
        input_unity_coarse = RezoCore.INPUT_UNITY_POS >> 8
        input_unity_x = (304 + input_unity_coarse +
                         (input_unity_coarse >> 4)) if self.compact_layout else (
                             326 + input_unity_coarse +
                             (input_unity_coarse >> 2))
        input_line_q0 = input_visible & (
            (input_is_cv & self.rect(
                input_x_value_q, input_local_value_q,
                439 if self.compact_layout else 489,
                66 if self.compact_layout else 71,
                442 if self.compact_layout else 492,
                86 if self.compact_layout else 93)) |
            (~input_is_cv & self.rect(
                input_x_value_q, input_local_value_q, input_unity_x,
                34 if self.compact_layout else 39,
                input_unity_x + 3,
                54 if self.compact_layout else 61)))
        # Two logical scanlines collapse to a stable single-pixel physical
        # monitor in the 508px compact viewport. Audio telemetry follows the
        # VALUE/gain lane; raw bipolar CV telemetry follows the DEPTH lane.
        input_audio_meter_y0 = 50 if self.compact_layout else 65
        input_audio_meter_y1 = 52 if self.compact_layout else 66
        input_cv_meter_y0 = 82 if self.compact_layout else 65
        input_cv_meter_y1 = 84 if self.compact_layout else 66
        input_meter_q0 = input_visible & Mux(
            input_is_cv,
            Mux(~input_meter_negative_q,
                self.rect(input_x_value_q, input_local_value_q,
                          440 if self.compact_layout else 490,
                          input_cv_meter_y0,
                          input_meter_end_q, input_cv_meter_y1),
                self.rect(input_x_value_q, input_local_value_q,
                          input_meter_end_q, input_cv_meter_y0,
                          440 if self.compact_layout else 490,
                          input_cv_meter_y1)),
            self.rect(input_x_value_q, input_local_value_q,
                      304 if self.compact_layout else 326,
                      input_audio_meter_y0,
                      input_meter_end_q, input_audio_meter_y1))

        for group in range(RezoCore.N_GROUPS):
            if self.compact_layout:
                # ``compact_group_centers`` is the upper pixel of a 2px rail;
                # its centre is therefore exactly the glyph centre at +0.5.
                rail_y = compact_group_centers[group]
                group_cell_signals.append(
                    group_page & self.rect(
                        x, text_y, 202, rail_y, 576, rail_y + 2))
            else:
                rail_y = 305 + group * 64
                group_cell_signals.append(
                    group_page & self.rect(
                        x, y, 128, rail_y, 640, rail_y + 3))

        group_selected_index = Signal(range(RezoCore.N_BANDS))
        group_selected_x_pre = Signal(unsigned(10), init=208)
        group_selected_x = Signal.like(group_selected_x_pre)
        group_selected_valid_pre = Signal()
        group_selected_valid = Signal()
        m.d.comb += [
            group_selected_index.eq(0),
            group_selected_x_pre.eq(208),
            group_selected_valid_pre.eq(
                (self.selected >= RezoHardwareUI.TARGET_GROUP_BASE) &
                (self.selected < RezoHardwareUI.TARGET_GROUP_BASE +
                 RezoCore.N_BANDS)),
        ]
        with m.If(group_selected_valid_pre):
            m.d.comb += [
                group_selected_index.eq(
                    self.selected - RezoHardwareUI.TARGET_GROUP_BASE),
                group_selected_x_pre.eq(
                    208 + (group_selected_index << 5) +
                    (group_selected_index << 1)),
            ]
        m.d.dvi += [
            group_selected_x.eq(group_selected_x_pre),
            group_selected_valid.eq(group_selected_valid_pre),
        ]
        group_select_signals.append(
            group_page & group_selected_valid & self.outline(
                x, y, group_selected_x - 5, 306,
                group_selected_x + 23, 486, t=3))
        group_band = Signal(range(RezoCore.N_BANDS))
        group_row = Signal(unsigned(2))
        group_band_active = Signal()
        group_row_active = Signal()
        group_row_edge = Signal()
        group_ghost = Signal()
        group_band_q = Signal.like(group_band)
        group_row_q = Signal.like(group_row)
        group_band_active_q = Signal()
        group_row_active_q = Signal()
        group_row_edge_q = Signal()
        group_page_q = Signal()
        group_band_enabled_q = Signal()
        group_filter_mode_q = Signal()
        bank_group_mask_array = Array(self.bank_groups)
        band_enable_mask_array = Array(self.band_enables)
        m.d.comb += [
            group_band.eq(0),
            group_row.eq(0),
            group_band_active.eq(0),
            group_row_active.eq(0),
            # Noncompact markers retain the old y-mod-64 edge decoder. The
            # compact branch is assigned from its native marker bounds below.
            group_row_edge.eq(
                0 if self.compact_layout else
                ((y[:6] < 40) | (y[:6] >= 60))),
        ]
        for n in range(RezoCore.N_BANDS):
            x0 = (208 + n * 34 if self.compact_layout else 144 + n * 48)
            marker_width = 18 if self.compact_layout else 24
            with m.If((x >= x0) & (x < x0 + marker_width)):
                m.d.comb += [
                    group_band.eq(n),
                    group_band_active.eq(1),
                ]
        for group in range(RezoCore.N_GROUPS):
            if self.compact_layout:
                # A 20px marker is symmetric around the same half-pixel as
                # the label and rail. Its 2px top/bottom ghost edges remain
                # visible when a BANK band is disabled.
                marker_y = compact_group_centers[group] - 9
                with m.If((text_y >= marker_y) &
                          (text_y < marker_y + 20)):
                    m.d.comb += [
                        group_row.eq(group),
                        group_row_active.eq(1),
                        group_row_edge.eq(
                            (text_y < marker_y + 2) |
                            (text_y >= marker_y + 18)),
                    ]
            else:
                marker_y = 294 + group * 64
                with m.If((y >= marker_y) & (y < marker_y + 24)):
                    m.d.comb += [
                        group_row.eq(group),
                        group_row_active.eq(1),
                    ]
        # Coordinate decoding is substantially wider than the actual 10x4
        # assignment lookup. Pipeline the two halves so the group page does
        # not put both on one HDMI pixel-clock path.
        m.d.dvi += [
            group_band_q.eq(group_band),
            group_row_q.eq(group_row),
            group_band_active_q.eq(group_band_active),
            group_row_active_q.eq(group_row_active),
            group_row_edge_q.eq(group_row_edge),
            group_page_q.eq(group_page),
            group_band_enabled_q.eq(band_enable_mask_array[group_band]),
            group_filter_mode_q.eq(self.filter_mode),
        ]
        m.d.comb += group_fill.eq(
            group_page_q & group_band_active_q & group_row_active_q &
            (group_filter_mode_q | group_band_enabled_q) &
            bank_group_mask_array[group_band_q].bit_select(group_row_q, 1))
        # Disabled BANK bands retain dim top/bottom rails at all four GROUPS
        # assignments. A full forty-cell rectangle decoder costs more logic
        # than remains available; these shared rails preserve location and
        # inactive state without implying an enabled assignment.
        m.d.comb += group_ghost.eq(
            group_page_q & group_band_active_q & group_row_active_q &
            group_row_edge_q & ~group_filter_mode_q & ~group_band_enabled_q)

        output_row = Signal(unsigned(2))
        output_source = Signal(unsigned(3))
        output_row_active = Signal()
        output_col_active = Signal()
        output_row_edge = Signal()
        output_col_edge = Signal()
        output_row_inner = Signal()
        output_col_inner = Signal()
        m.submodules.output_send_mem = output_send_mem = Memory(
            shape=unsigned(7), depth=20, init=[0] * 20,
            attrs={"ram_style": "block"})
        output_send_rport = output_send_mem.read_port(domain="dvi")
        output_send_wport = output_send_mem.write_port(domain="sync")
        output_send_scaled_write = Signal(unsigned(7))
        if self.compact_layout:
            m.d.comb += output_send_scaled_write.eq(
                self.output_send_write_data +
                (self.output_send_write_data << 1))
        else:
            m.d.comb += output_send_scaled_write.eq(
                self.output_send_write_data << 2)
        m.d.comb += [
            output_send_wport.addr.eq(self.output_send_write_addr),
            output_send_wport.data.eq(output_send_scaled_write),
            output_send_wport.en.eq(self.output_send_write_en),
        ]
        output_cell_x0 = Signal(unsigned(10))
        output_cell_y0 = Signal(unsigned(10))
        output_send_index = Signal(unsigned(5))
        # Compact OUTPUT is authored entirely in native pixels. This is the
        # same coordinate system as its text, avoiding the progressive drift
        # caused by comparing scaled geometry with native glyph positions.
        output_geom_x = text_x if self.compact_layout else x
        output_geom_y = text_y if self.compact_layout else y
        m.d.comb += [
            output_row.eq(0),
            output_source.eq(0),
            output_row_active.eq(0),
            output_col_active.eq(0),
            output_row_edge.eq(0),
            output_col_edge.eq(0),
            output_row_inner.eq(0),
            output_col_inner.eq(0),
            output_cell_x0.eq(188),
            output_cell_y0.eq(326),
            output_send_index.eq(0),
        ]
        for output in range(4):
            row_y = (
                compact_output_row_centers[output] - 13
                if self.compact_layout else 326 + output * 80)
            with m.If((output_geom_y >= row_y) &
                      (output_geom_y < row_y + 28)):
                m.d.comb += [
                    output_row.eq(output),
                    output_row_active.eq(1),
                    output_row_edge.eq(
                        (output_geom_y < row_y + 2) |
                        (output_geom_y >= row_y + 26)),
                    output_row_inner.eq(
                        (output_geom_y >= row_y + 5) &
                        (output_geom_y < row_y + 23)),
                    output_cell_y0.eq(row_y),
                ]
        for source in range(5):
            # Compact sends retain their prior physical size: a 56px cell
            # leaves an 8px gutter on the 64px G1..G4 cadence and maps its
            # 48px interior at exactly three pixels per 0..16 send step.
            # Noncompact keeps the original 72px/64px geometry.
            cell_width = 56 if self.compact_layout else 72
            cell_x0 = (
                compact_output_col_centers[source] - 27
                if self.compact_layout else 188 + source * 96)
            with m.If((output_geom_x >= cell_x0) &
                      (output_geom_x < cell_x0 + cell_width)):
                m.d.comb += [
                    output_source.eq(source),
                    output_col_active.eq(Const(source != 4) | ~self.filter_mode),
                    output_col_edge.eq(
                        (output_geom_x < cell_x0 + 2) |
                        (output_geom_x >= cell_x0 + cell_width - 2)),
                    output_col_inner.eq(
                        (output_geom_x >= cell_x0 + 4) &
                        (output_geom_x < cell_x0 + cell_width - 4)),
                    output_cell_x0.eq(cell_x0),
                ]
        m.d.comb += [
            output_send_index.eq(output_source + (output_row << 2) + output_row),
            output_send_rport.addr.eq(output_send_index),
        ]
        output_x_q = Signal.like(output_geom_x)
        output_y_q = Signal.like(output_geom_y)
        output_x0_q = Signal.like(output_cell_x0)
        output_y0_q = Signal.like(output_cell_y0)
        output_row_active_q = Signal()
        output_col_active_q = Signal()
        output_page_q = Signal()
        m.d.dvi += [
            output_x_q.eq(output_geom_x),
            output_y_q.eq(output_geom_y),
            output_x0_q.eq(output_cell_x0),
            output_y0_q.eq(output_cell_y0),
            output_row_active_q.eq(output_row_active),
            output_col_active_q.eq(output_col_active),
            output_page_q.eq(output_page),
        ]
        output_send_end = Signal(unsigned(10))
        m.d.comb += output_send_end.eq(
            output_x0_q + 4 + output_send_rport.data)
        m.d.comb += [
            output_cell.eq(output_page & output_row_active & output_col_active &
                           (output_row_edge | output_col_edge)),
            output_fill.eq(
                output_page_q & output_row_active_q & output_col_active_q &
                (output_y_q >= output_y0_q + 5) &
                (output_y_q < output_y0_q + 23) &
                (output_x_q >= output_x0_q + 4) &
                (output_x_q < output_send_end)),
        ]
        output_target = Signal(unsigned(7))
        output_header_select = Signal()
        output_header_row = Signal(unsigned(2))
        output_header_col = Signal(unsigned(2))
        output_header_row_target = Signal()
        output_header_col_target = Signal()
        m.d.comb += [
            output_target.eq(RezoHardwareUI.TARGET_OUTPUT_BASE + output_source +
                             output_row + (output_row << 2)),
            output_select.eq(
                (output_page & output_row_active & output_col_active &
                 (self.selected == output_target) &
                 (output_row_edge | output_col_edge)) |
                output_header_select),
            output_header_row.eq(
                self.selected - RezoHardwareUI.TARGET_OUTPUT_ROW_BASE),
            output_header_col.eq(
                self.selected - RezoHardwareUI.TARGET_OUTPUT_COL_BASE),
            output_header_row_target.eq(
                (self.selected >= RezoHardwareUI.TARGET_OUTPUT_ROW_BASE) &
                (self.selected < RezoHardwareUI.TARGET_OUTPUT_ROW_BASE + 4)),
            output_header_col_target.eq(
                (self.selected >= RezoHardwareUI.TARGET_OUTPUT_COL_BASE) &
                (self.selected < RezoHardwareUI.TARGET_OUTPUT_COL_BASE + 4)),
            output_header_select.eq(output_page & (
                (output_row_active & output_header_row_target &
                 (output_header_row == output_row) &
                 (output_geom_x >= (116 if self.compact_layout else 26)) &
                 (output_geom_x < (120 if self.compact_layout else 30))) |
                (output_col_active &
                 (output_geom_y >= (280 if self.compact_layout else 264)) &
                 (output_geom_y < (284 if self.compact_layout else 268)) &
                 ((output_header_col_target &
                   (output_header_col == output_source)) |
                  ((self.selected == RezoHardwareUI.TARGET_OUTPUT_DRY_COL) &
                   (output_source == 4)))))),
        ]

        for target, signals in [
                (preset_chip, preset_chip_signals),
                (preset_select, preset_select_signals),
                (group_cell, group_cell_signals),
                (group_select, group_select_signals),
                (filter_cv_panel, filter_cv_panel_signals),
                (filter_cv_fill, filter_cv_fill_signals),
                (filter_cv_line, filter_cv_line_signals),
                (filter_cv_select, filter_cv_select_signals)]:
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

        band_zero_q0 = band_zero
        band_slot_q0 = band_slot
        group_cell_q0 = tile_registered_or(group_cell_signals, "group_cell")
        group_fill_q0 = Signal()
        group_select_q0 = tile_registered_or(group_select_signals, "group_select")
        output_cell_q0 = Signal()
        output_fill_q0 = Signal()
        output_select_q0 = Signal()
        filter_cv_panel_q0 = tile_registered_or(filter_cv_panel_signals, "filter_cv_panel")
        filter_cv_fill_q0 = tile_registered_or(filter_cv_fill_signals, "filter_cv_fill")
        filter_cv_line_q0 = tile_registered_or(filter_cv_line_signals, "filter_cv_line")
        filter_cv_select_q0 = tile_registered_or(filter_cv_select_signals, "filter_cv_select")
        m.d.dvi += [
            output_cell_q0.eq(output_cell),
            output_select_q0.eq(output_select),
        ]
        m.d.dvi += output_fill_q0.eq(output_fill)
        m.d.comb += group_fill_q0.eq(group_fill)

        if self.compact_layout:
            m.d.comb += preset_group_select.eq(
                bank_page &
                (self.selected == RezoHardwareUI.TARGET_PRESET) &
                ~self.editing & self.outline(
                    text_x, text_y, 244, 164, 332, 204, t=3))
        else:
            m.d.comb += preset_group_select.eq(
                bank_page &
                (self.selected == RezoHardwareUI.TARGET_PRESET) &
                ~self.editing & self.outline(
                    x, y, 131, 95, 269, 143, t=3))
        bank_control_y0s = (
            compact_main_control_y0s[:3] if self.compact_layout
            else (556, 588, 620))
        bank_panel_bounds = (
            tuple((row_y0 - 2, row_y0 + 18)
                  for row_y0 in bank_control_y0s)
            if self.compact_layout else
            ((552, 576), (584, 608), (616, 640)))
        drive_select = (
            bank_page &
            (self.selected == RezoHardwareUI.TARGET_DRIVE) &
            self.outline(x, y, control_panel_x0,
                         bank_panel_bounds[0][0], control_panel_x1,
                         bank_panel_bounds[0][1], t=3))

        # DRIVE, RES and FB use one pipelined row/value decoder.  Keeping the
        # base/effective split here gives all three controls identical CV
        # shading and fixed markers without three copies of wide x compares.
        bank_control_row = Signal(unsigned(2))
        bank_control_y0 = Signal(unsigned(10), init=bank_control_y0s[0])
        bank_control_active = Signal()
        bank_control_base = Signal(unsigned(8))
        bank_control_effective = Signal(unsigned(8))
        m.d.comb += [
            bank_control_row.eq(0),
            bank_control_y0.eq(bank_control_y0s[0]),
            bank_control_active.eq(0),
            bank_control_base.eq(self.drive),
            bank_control_effective.eq(self.effective_drive),
        ]
        for row, row_y0 in enumerate(bank_control_y0s):
            with m.If((y >= row_y0 - 2) & (y < row_y0 + 18)):
                m.d.comb += [
                    bank_control_row.eq(row),
                    bank_control_y0.eq(row_y0),
                    bank_control_active.eq(1),
                ]
        with m.Switch(bank_control_row):
            with m.Case(1):
                m.d.comb += [
                    bank_control_base.eq(self.resonance),
                    bank_control_effective.eq(self.effective_resonance),
                ]
            with m.Case(2):
                m.d.comb += [
                    bank_control_base.eq(self.feedback),
                    bank_control_effective.eq(self.effective_feedback),
                ]
        bank_control_x_q = Signal.like(x)
        bank_control_y_q = Signal.like(y)
        bank_control_y0_q = Signal.like(bank_control_y0)
        bank_control_active_q = Signal()
        bank_control_base_q = Signal.like(bank_control_base)
        bank_control_effective_q = Signal.like(bank_control_effective)
        bank_control_page_q = Signal()
        m.d.dvi += [
            bank_control_x_q.eq(x),
            bank_control_y_q.eq(y),
            bank_control_y0_q.eq(bank_control_y0),
            bank_control_active_q.eq(bank_control_active),
            bank_control_base_q.eq(bank_control_base),
            bank_control_effective_q.eq(bank_control_effective),
            bank_control_page_q.eq(bank_page),
        ]
        bank_control_visible = bank_control_page_q & bank_control_active_q
        if self.compact_layout:
            bank_control_fill = (
                bank_control_visible & compact_fader_x_valid &
                (compact_fader_threshold <= bank_control_base_q) &
                (bank_control_y_q >= bank_control_y0_q) &
                (bank_control_y_q < bank_control_y0_q + 16))
            bank_control_effective_fill = (
                bank_control_visible & compact_fader_x_valid &
                (compact_fader_threshold <= bank_control_effective_q) &
                (bank_control_y_q >= bank_control_y0_q) &
                (bank_control_y_q < bank_control_y0_q + 16))
            bank_control_marker_value = Mux(
                bank_control_base_q == 0, 1, bank_control_base_q)
            bank_control_mod_marker = (
                bank_control_visible & compact_fader_x_valid &
                (compact_fader_threshold == bank_control_marker_value) &
                (bank_control_y_q >= bank_control_y0_q - 2) &
                (bank_control_y_q < bank_control_y0_q + 18))
        else:
            bank_control_end = control_fill_x0 + (bank_control_base_q << 2)
            bank_control_effective_end = (
                control_fill_x0 + (bank_control_effective_q << 2))
            bank_control_fill = bank_control_visible & self.rect(
                bank_control_x_q, bank_control_y_q, control_fill_x0,
                bank_control_y0_q, bank_control_end, bank_control_y0_q + 16)
            bank_control_effective_fill = bank_control_visible & self.rect(
                bank_control_x_q, bank_control_y_q, control_fill_x0,
                bank_control_y0_q, bank_control_effective_end,
                bank_control_y0_q + 16)
            bank_control_mod_marker = bank_control_visible & self.rect(
                bank_control_x_q, bank_control_y_q,
                bank_control_end - 2, bank_control_y0_q - 2,
                bank_control_end + 2, bank_control_y0_q + 18)
        bank_control_mod_fill = (
            bank_control_fill ^ bank_control_effective_fill)

        if self.compact_layout:
            tune_y_q = Signal.like(y)
            tune_page_q = Signal()
            tune_knee_q = Signal.like(self.limit_knee)
            tune_cap_q = Signal.like(self.limit_cap)
            m.d.dvi += [
                tune_y_q.eq(y),
                tune_page_q.eq(tune_page),
                tune_knee_q.eq(self.limit_knee),
                tune_cap_q.eq(self.limit_cap),
            ]
            dry_fill = (
                tune_page_q & compact_fader_x_valid &
                (compact_fader_threshold <= tune_knee_q) &
                (tune_y_q >= 400 + tune_y_shift) &
                (tune_y_q < 416 + tune_y_shift))
            tune_cap_fill = (
                tune_page_q & compact_fader_x_valid &
                (compact_fader_threshold <= tune_cap_q) &
                (tune_y_q >= 432 + tune_y_shift) &
                (tune_y_q < 448 + tune_y_shift))
        else:
            dry_fill = tune_page & self.rect(
                x, y, tune_fill_x0, 412,
                control_fill_x0 + (self.limit_knee << 2), 428)
            tune_cap_fill = tune_page & self.rect(
                x, y, tune_fill_x0, 460,
                control_fill_x0 + (self.limit_cap << 2), 476)
        dry_select = (tune_page &
                      (self.selected == RezoHardwareUI.TARGET_LIMIT_KNEE)) & Mux(
            self.compact_layout,
            self.outline(x, y, tune_panel_x0,
                         396 + tune_y_shift, tune_panel_x1,
                         420 + tune_y_shift, t=3),
            self.rect(x, y, 144, 408, 148, 432))
        res_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_RESONANCE)) |
                      (tune_page & (self.selected == RezoHardwareUI.TARGET_LIMIT_CAP))) & (
            (bank_page & self.outline(
                x, y, control_panel_x0,
                bank_panel_bounds[1][0], control_panel_x1,
                bank_panel_bounds[1][1], t=3)) |
            (tune_page & Mux(
                self.compact_layout,
                self.outline(x, y, tune_panel_x0,
                             428 + tune_y_shift, tune_panel_x1,
                             452 + tune_y_shift, t=3),
                self.rect(x, y, 144, 456, 148, 480))))
        fb_select = (
            bank_page &
            (self.selected == RezoHardwareUI.TARGET_FEEDBACK) &
            self.outline(x, y, control_panel_x0,
                         bank_panel_bounds[2][0], control_panel_x1,
                         bank_panel_bounds[2][1], t=3))
        # All five FILTER faders share one row/value decoder.  Besides saving
        # substantial geometry logic, this gives every row exactly the same
        # base marker and two-tone modulation behavior.
        filter_control_row = Signal(unsigned(3))
        filter_control_y0s = (
            compact_main_control_y0s if self.compact_layout
            else (546, 578, 610, 642, 674))
        filter_panel_bounds = (
            tuple((row_y0 - 2, row_y0 + 18)
                  for row_y0 in filter_control_y0s)
            if self.compact_layout else
            ((542, 562), (574, 594), (606, 626),
             (638, 658), (670, 690)))
        filter_control_y0 = Signal(
            unsigned(10), init=filter_control_y0s[0])
        filter_control_active = Signal()
        filter_control_base = Signal(unsigned(8))
        filter_control_effective = Signal(unsigned(8))
        m.d.comb += [
            filter_control_row.eq(0),
            filter_control_y0.eq(filter_control_y0s[0]),
            filter_control_active.eq(0),
            filter_control_base.eq(self.filter_cutoff),
            filter_control_effective.eq(self.effective_filter_cutoff),
        ]
        filter_decode_y1 = 18 if self.compact_layout else 14
        for row, row_y0 in enumerate(filter_control_y0s):
            with m.If((y >= row_y0 - 2) &
                      (y < row_y0 + filter_decode_y1)):
                m.d.comb += [
                    filter_control_row.eq(row),
                    filter_control_y0.eq(row_y0),
                    filter_control_active.eq(1),
                ]
        with m.Switch(filter_control_row):
            with m.Case(1):
                m.d.comb += [
                    filter_control_base.eq(self.filter_slope),
                    filter_control_effective.eq(self.effective_filter_slope),
                ]
            with m.Case(2):
                m.d.comb += [
                    filter_control_base.eq(self.filter_width),
                    filter_control_effective.eq(self.effective_filter_width),
                ]
            with m.Case(3):
                m.d.comb += [
                    filter_control_base.eq(self.drive),
                    filter_control_effective.eq(self.effective_drive),
                ]
            with m.Case(4):
                m.d.comb += [
                    filter_control_base.eq(self.resonance),
                    filter_control_effective.eq(self.effective_resonance),
                ]
        # Register the shared row decode before the horizontal comparisons.
        # This keeps the dynamic value mux and wide fader comparison
        # out of one DVI cycle; x/y travel through the same stage, so geometry
        # remains spatially aligned.
        filter_control_x_q = Signal.like(x)
        filter_control_y_q = Signal.like(y)
        filter_control_row_q = Signal.like(filter_control_row)
        filter_control_y0_q = Signal.like(filter_control_y0)
        filter_control_active_q = Signal()
        filter_control_base_q = Signal.like(filter_control_base)
        filter_control_effective_q = Signal.like(filter_control_effective)
        filter_control_page_q = Signal()
        filter_control_bp_q = Signal()
        m.d.dvi += [
            filter_control_x_q.eq(x),
            filter_control_y_q.eq(y),
            filter_control_row_q.eq(filter_control_row),
            filter_control_y0_q.eq(filter_control_y0),
            filter_control_active_q.eq(filter_control_active),
            filter_control_base_q.eq(filter_control_base),
            filter_control_effective_q.eq(filter_control_effective),
            filter_control_page_q.eq(filter_page),
            filter_control_bp_q.eq(self.filter_type >= RezoCore.FILTER_BP),
        ]
        filter_control_visible = (
            filter_control_page_q & filter_control_active_q &
            ((filter_control_row_q != 2) | filter_control_bp_q))
        if self.compact_layout:
            filter_control_fill = (
                filter_control_visible & compact_fader_x_valid &
                (compact_fader_threshold <= filter_control_base_q) &
                (filter_control_y_q >= filter_control_y0_q) &
                (filter_control_y_q < filter_control_y0_q + 16))
            filter_control_effective_fill = (
                filter_control_visible & compact_fader_x_valid &
                (compact_fader_threshold <= filter_control_effective_q) &
                (filter_control_y_q >= filter_control_y0_q) &
                (filter_control_y_q < filter_control_y0_q + 16))
            filter_control_marker_value = Mux(
                filter_control_base_q == 0, 1, filter_control_base_q)
            filter_control_mod_marker = (
                filter_control_visible & compact_fader_x_valid &
                (compact_fader_threshold == filter_control_marker_value) &
                (filter_control_y_q >= filter_control_y0_q - 2) &
                (filter_control_y_q < filter_control_y0_q + 18))
        else:
            filter_control_end = (
                control_fill_x0 + (filter_control_base_q << 2))
            filter_control_effective_end = (
                control_fill_x0 + (filter_control_effective_q << 2))
            filter_control_fill = filter_control_visible & self.rect(
                filter_control_x_q, filter_control_y_q, control_fill_x0,
                filter_control_y0_q, filter_control_end,
                filter_control_y0_q + 12)
            filter_control_effective_fill = filter_control_visible & self.rect(
                filter_control_x_q, filter_control_y_q, control_fill_x0,
                filter_control_y0_q, filter_control_effective_end,
                filter_control_y0_q + 12)
            filter_control_mod_marker = filter_control_visible & self.rect(
                filter_control_x_q, filter_control_y_q,
                filter_control_end - 2, filter_control_y0_q - 2,
                filter_control_end + 2, filter_control_y0_q + 14)
        filter_control_mod_fill = (
            filter_control_fill ^ filter_control_effective_fill)
        filter_freq_select = filter_page & (self.selected == RezoHardwareUI.TARGET_FILTER_CUTOFF) & self.outline(
            x, y, control_panel_x0, filter_panel_bounds[0][0], control_panel_x1,
            filter_panel_bounds[0][1], t=3)
        filter_slope_select = filter_page & (self.selected == RezoHardwareUI.TARGET_FILTER_SLOPE) & self.outline(
            x, y, control_panel_x0, filter_panel_bounds[1][0], control_panel_x1,
            filter_panel_bounds[1][1], t=3)
        filter_width_select = filter_page & (self.filter_type >= RezoCore.FILTER_BP) & (
            self.selected == RezoHardwareUI.TARGET_FILTER_WIDTH) & self.outline(
                x, y, control_panel_x0, filter_panel_bounds[2][0], control_panel_x1,
                filter_panel_bounds[2][1], t=3)
        filter_drive_select = filter_page & (self.selected == RezoHardwareUI.TARGET_DRIVE) & self.outline(
            x, y, control_panel_x0, filter_panel_bounds[3][0], control_panel_x1,
            filter_panel_bounds[3][1], t=3)
        filter_res_select = filter_page & (self.selected == RezoHardwareUI.TARGET_RESONANCE) & self.outline(
            x, y, control_panel_x0, filter_panel_bounds[4][0], control_panel_x1,
            filter_panel_bounds[4][1], t=3)
        if self.compact_layout:
            page_select = (
                (self.selected == RezoHardwareUI.TARGET_PAGE) &
                self.outline(text_x, text_y, 212, 116, 364, 164, t=3))
        else:
            page_select = (
                (self.selected == RezoHardwareUI.TARGET_PAGE) &
                self.outline(x, y, 20, 20, 196, 82, t=3))

        bank_selected_q = Signal()
        filter_selected_q = Signal()
        input_selected_q = Signal()
        routing_selected_q = Signal()
        filter_cv_selected_q = Signal()
        advanced_selected_q = Signal()
        bands_selected_q = Signal()
        page_selected_q = Signal()
        m.d.dvi += [
            bank_selected_q.eq(preset_select | preset_group_select | band_select_q0 |
                               drive_select | dry_select | res_select | fb_select |
                               mode_select),
            filter_selected_q.eq(filter_type_select | filter_freq_select |
                                 filter_slope_select | filter_width_select |
                                 filter_drive_select | filter_res_select),
            input_selected_q.eq(input_select_q0),
            routing_selected_q.eq(group_select_q0 | output_select_q0),
            filter_cv_selected_q.eq(filter_cv_select_q0),
            advanced_selected_q.eq(palette_select | save_default_select),
            bands_selected_q.eq(layout_select | band_select_q0),
            page_selected_q.eq(page_select),
        ]
        selected = active & (bank_selected_q | filter_selected_q |
                             input_selected_q | routing_selected_q |
                             filter_cv_selected_q |
                             advanced_selected_q | bands_selected_q |
                             page_selected_q | damp_select)

        selected_q = Signal()
        text_q = Signal()
        fill_q = Signal()
        line_q = Signal()
        mod_q = Signal()
        panel_q = Signal()
        background_q = Signal()
        active_q = Signal()
        geometry_fill_q0 = Signal()
        geometry_line_q0 = Signal()
        geometry_mod_q0 = Signal()
        geometry_panel_q0 = Signal()
        m.d.dvi += [
            geometry_fill_q0.eq(band_fill | band_marker | bank_control_fill |
                                dry_fill | tune_cap_fill |
                                filter_control_fill),
            geometry_line_q0.eq(
                band_zero_q0 | bank_control_mod_marker |
                filter_control_mod_marker | border),
            geometry_mod_q0.eq(band_mod_fill | bank_control_mod_fill |
                               filter_control_mod_fill | input_meter_q0),
            geometry_panel_q0.eq(preset_chip | filter_type_chip | mode_chip |
                                 palette_chip | save_default_chip | layout_chip |
                                 damp_chip | side_page_chip |
                                 band_slot_q0 |
                                 meter_panel | filter_meter_panel),
        ]
        m.d.dvi += [
            selected_q.eq(selected),
            text_q.eq(text),
            fill_q.eq(geometry_fill_q0 |
                      input_fill_q0 | group_fill_q0 | output_fill_q0 |
                      filter_cv_fill_q0),
            line_q.eq(geometry_line_q0 | input_line_q0 |
                      group_ghost | filter_cv_line_q0),
            mod_q.eq(geometry_mod_q0),
            panel_q.eq(geometry_panel_q0 | input_panel_q0 | group_cell_q0 |
                       output_cell_q0 | filter_cv_panel_q0),
            background_q.eq(title_panel | content_panel),
            active_q.eq(active),
        ]

        palette_role = Signal(unsigned(3), init=7)
        with m.If(selected_q):
            m.d.comb += palette_role.eq(0)
        with m.Elif(text_q):
            m.d.comb += palette_role.eq(1)
        with m.Elif(mod_q):
            m.d.comb += palette_role.eq(3)
        with m.Elif(fill_q):
            m.d.comb += palette_role.eq(2)
        with m.Elif(line_q):
            m.d.comb += palette_role.eq(4)
        with m.Elif(panel_q):
            m.d.comb += palette_role.eq(5)
        with m.Elif(background_q):
            m.d.comb += palette_role.eq(6)

        palette_init = [color for theme in self.RGB_PALETTES for color in theme]
        m.submodules.palette_mem = palette_mem = Memory(
            shape=unsigned(24), depth=len(palette_init), init=palette_init,
            attrs={"ram_style": "block"})
        palette_rport = palette_mem.read_port(domain="dvi")
        m.d.comb += palette_rport.addr.eq(Cat(palette_role, self.palette))

        m.d.comb += [
            self.r.eq(palette_rport.data[16:24]),
            self.g.eq(palette_rport.data[8:16]),
            self.b.eq(palette_rport.data[0:8]),
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
    # This design's placement is seed-sensitive at 720p60. Seed 4 is the
    # measured all-clock route for the third compact-display pass, while the
    # environment override remains useful for place-and-route experiments.
    # The compact renderer needs a density pass plus a lower ABC9 wire weight
    # than synth_ecp5's fixed 300 ps. The second photo-alignment pass no longer
    # places at W=140; W=130 restores 137 raw combinational cells of headroom.
    # Keep the override for controlled mapping experiments, and keep the staged
    # commands on the fragment so generated top.ys reproduces the candidate.
    synth_opts = "-abc9 -abc2 -run begin:map_luts"
    abc9_wire_weight = os.getenv("TILIQUA_REZO_ABC9_W", "130")
    script_after_synth = (
        "abc; techmap -map +/lattice/latches_map.v; "
        f"abc9 -W {abc9_wire_weight}; clean; "
        "synth_ecp5 -abc9 -abc2 -top top -run map_cells:check; "
        "autoname; hierarchy -check; stat; check -noinit; "
        "blackbox =A:whitebox"
    )
    nextpnr_opts = f"--timing-allow-fail --seed {os.getenv('TILIQUA_REZO_SEED', '4')}"

    def __init__(self, clock_settings):
        assert clock_settings.modeline is not None
        self.clock_settings = clock_settings
        self.pmod0 = eurorack_pmod.EurorackPmod(
            self.clock_settings.audio_clock, with_boot_slot=True)

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
        else:
            m.submodules.car = sim.FakeTiliquaDomainGenerator()
            enc_pins = None

        m.submodules.pmod0 = pmod0 = self.pmod0
        m.submodules.rezo = rezo = RezoCore(fs=self.clock_settings.audio_clock.fs())
        m.submodules.ui = ui = RezoHardwareUI()
        m.submodules.state_journal = state_journal = RezoStateJournal(
            RezoHardwareUI.STATE_WORDS_V2,
            legacy_state_words=RezoHardwareUI.STATE_WORDS_V1,
            legacy_tail_words=RezoHardwareUI.legacy_band_config_words())
        m.submodules.spi_transfer = spi_transfer = SPIFlashTransfer()
        m.submodules.spi_phy = spi_phy = spiflash.SPIPHYController(
            domain="sync", divisor=1)
        wiring.connect(m, spi_transfer.spi, spi_phy.ctrl)
        if sim.is_hw(platform):
            m.submodules.spi_provider = spi_provider = \
                spiflash.ECP5ConfigurationFlashProvider()
            wiring.connect(m, spi_phy.pins, spi_provider.pins)
        m.submodules.audio_out_fifo = audio_out_fifo = dsp.SyncFIFOBuffered(
            shape=data.ArrayLayout(ASQ, 4), depth=4)

        # Persistent defaults live in the running slot's option window.
        # Palette is part of that explicit state record rather than an
        # independently auto-saved EEPROM preference.
        m.d.comb += [
            state_journal.boot_slot.eq(pmod0.boot_slot),
            state_journal.boot_slot_valid.eq(pmod0.boot_slot_valid),
            state_journal.boot_slot_checked.eq(pmod0.boot_slot_checked),
            state_journal.state_read_data.eq(ui.state_read_data),
            state_journal.save_request.eq(ui.save_default_request),
            ui.state_write_data.eq(state_journal.state_write_data),
            ui.state_shift_enable.eq(state_journal.state_shift_enable),
            ui.state_shift_load.eq(state_journal.state_shift_load),
            ui.save_default_available.eq(state_journal.available),
            ui.save_default_busy.eq(state_journal.busy),
            ui.save_default_done.eq(state_journal.save_done),
            ui.save_default_error.eq(state_journal.save_error),

            spi_transfer.start.eq(state_journal.xfer_start),
            spi_transfer.chip_select.eq(state_journal.xfer_cs),
            spi_transfer.tx_data.eq(state_journal.xfer_tx),
            spi_transfer.length.eq(state_journal.xfer_length),
            spi_transfer.output_mask.eq(state_journal.xfer_mask),
            state_journal.xfer_rx.eq(spi_transfer.rx_data),
            state_journal.xfer_done.eq(spi_transfer.done),
        ]

        if sim.is_hw(platform):
            # Do not expose factory defaults or a partially restored state as
            # an audible startup transient.
            m.d.comb += pmod0.codec_mute.eq(
                reboot.mute | ~state_journal.startup_done)

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
            rezo.drive.eq(ui.drive),
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
            m.d.comb += [
                rezo.levels[n].eq(ui.levels[n]),
                rezo.band_enables[n].eq(ui.band_enables[n]),
                rezo.band_frequencies[n].eq(ui.band_frequencies[n]),
                rezo.feedback_sends[n].eq(ui.feedback_sends[n]),
            ]
        for n in range(4):
            m.d.comb += [
                rezo.input_gains[n].eq(ui.input_gains[n]),
                rezo.input_modes[n].eq(ui.input_modes[n]),
                rezo.cv_targets[n].eq(ui.cv_targets[n]),
                rezo.cv_depths[n].eq(ui.cv_depths[n]),
            ]
        for n in range(RezoCore.N_BANDS):
            m.d.comb += rezo.bank_groups[n].eq(ui.bank_groups[n])
        for n in range(20):
            m.d.comb += rezo.output_sends[n].eq(ui.output_sends[n])
        for n in range(15):
            m.d.comb += rezo.filter_cv_matrix[n].eq(ui.filter_cv_matrix[n])

        wiring.connect(m, pmod0.o_cal, rezo.i)
        wiring.connect(m, rezo.o, audio_out_fifo.i)
        wiring.connect(m, audio_out_fifo.o, pmod0.i_cal)

        m.submodules.dvi_tgen = dvi_tgen = dvi.DVITimingGen()
        for member in dvi_tgen.timings.signature.members:
            m.d.comb += getattr(dvi_tgen.timings, member).eq(
                getattr(self.clock_settings.modeline, member))

        round_display = (
            self.clock_settings.modeline.h_active ==
            RezoTileDisplay.PANEL_W and
            self.clock_settings.modeline.v_active ==
            RezoTileDisplay.PANEL_H)
        # Display-layout invariant:
        #
        # * The official Tiliqua display is a physically rotated 720x720
        #   circular panel. Its REZO content is authored for the centered
        #   508x508 inscribed square; only the REZO identity may use the top
        #   circular arc outside that square.
        # * Standard 1280x720 HDMI is the development preview. It shows those
        #   same compact pixels centered, without rotation or enlargement.
        #
        m.submodules.display = display = RezoTileDisplay(
            h_active=self.clock_settings.modeline.h_active,
            rotate_left=round_display,
            compact_layout=True)
        m.d.comb += [
            display.x.eq(dvi_tgen.x),
            display.y.eq(dvi_tgen.y),
            display.de.eq(dvi_tgen.ctrl.de),
        ]
        for n in range(RezoCore.N_BANDS):
            display_level = Signal(signed(8), name=f"display_level{n}")
            display_effective_level = Signal(signed(8), name=f"display_effective_level{n}")
            m.d.comb += display_level.eq(rezo.levels[n] >> 8)
            # The effective level includes group membership and CV modulation.
            # Register this display-only telemetry before the DVI CDC so that
            # its group-selection and clamp logic is not one 60 MHz path.
            m.d.sync += display_effective_level.eq(rezo.effective_levels[n] >> 8)
            m.submodules += FFSynchronizer(
                i=display_level, o=display.levels[n], o_domain="dvi")
            m.submodules += FFSynchronizer(
                i=display_effective_level, o=display.effective_levels[n], o_domain="dvi")
        display_resonance = Signal(unsigned(8))
        display_feedback = Signal(unsigned(8))
        display_drive = Signal(unsigned(8))
        display_effective_drive = Signal(unsigned(8))
        display_effective_resonance = Signal(unsigned(8))
        display_effective_feedback = Signal(unsigned(8))
        display_filter_cutoff = Signal(unsigned(8))
        display_filter_slope = Signal(unsigned(8))
        display_filter_width = Signal(unsigned(8))
        display_effective_filter_cutoff = Signal(unsigned(8))
        display_effective_filter_slope = Signal(unsigned(8))
        display_effective_filter_width = Signal(unsigned(8))
        display_limit_knee = Signal(unsigned(8))
        display_limit_cap = Signal(unsigned(8))
        display_input_gains = [Signal(unsigned(8), name=f"display_input_gain{n}")
                               for n in range(4)]
        display_cv_depths = [Signal(signed(8), name=f"display_cv_depth{n}")
                             for n in range(4)]
        display_input_meters = [Signal(signed(6), name=f"display_input_meter{n}")
                                for n in range(4)]
        filter_cv_write_index = Signal(range(15))
        filter_cv_write_data = Signal(signed(6))
        filter_cv_matrix_array = Array(ui.filter_cv_matrix)
        output_send_write_index = Signal(range(20))
        output_send_array = Array(ui.output_sends)
        m.d.comb += [
            display_drive.eq((RezoCore.DRIVE_FLOOR + rezo.drive) >> 8),
            display_effective_drive.eq(rezo.effective_drive >> 8),
            display_resonance.eq(rezo.resonance >> 8),
            display_feedback.eq(rezo.feedback >> 8),
            display_effective_resonance.eq(rezo.effective_resonance >> 8),
            display_effective_feedback.eq(rezo.effective_feedback >> 8),
            display_filter_cutoff.eq(rezo.filter_cutoff >> 8),
            display_filter_slope.eq(rezo.filter_slope >> 8),
            display_filter_width.eq(rezo.filter_width >> 8),
            display_effective_filter_cutoff.eq(rezo.effective_filter_cutoff >> 8),
            display_effective_filter_slope.eq(rezo.effective_filter_slope >> 8),
            display_effective_filter_width.eq(rezo.effective_filter_width >> 8),
            display_limit_knee.eq(rezo.limit_knee >> 8),
            display_limit_cap.eq(rezo.limit_cap >> 8),
        ]
        for n in range(4):
            m.d.comb += [
                display_input_gains[n].eq(rezo.input_gains[n] >> 8),
                display_cv_depths[n].eq(rezo.cv_depths[n] >> 8),
            ]
            m.d.sync += display_input_meters[n].eq(
                rezo.input_meters[n] >> 10)
        m.d.comb += [
            filter_cv_write_data.eq(filter_cv_matrix_array[filter_cv_write_index] >> 2),
            display.filter_cv_write_addr.eq(filter_cv_write_index),
            display.filter_cv_write_data.eq(filter_cv_write_data),
            display.filter_cv_write_en.eq(1),
            display.output_send_write_addr.eq(output_send_write_index),
            display.output_send_write_data.eq(
                output_send_array[output_send_write_index]),
            display.output_send_write_en.eq(1),
        ]
        with m.If(filter_cv_write_index == 14):
            m.d.sync += filter_cv_write_index.eq(0)
        with m.Else():
            m.d.sync += filter_cv_write_index.eq(filter_cv_write_index + 1)
        with m.If(output_send_write_index == 19):
            m.d.sync += output_send_write_index.eq(0)
        with m.Else():
            m.d.sync += output_send_write_index.eq(output_send_write_index + 1)
        m.submodules += [
            FFSynchronizer(i=display_drive, o=display.drive, o_domain="dvi"),
            FFSynchronizer(i=display_effective_drive,
                           o=display.effective_drive, o_domain="dvi"),
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
            FFSynchronizer(i=ui.palette, o=display.palette, o_domain="dvi"),
            FFSynchronizer(i=ui.save_default_available,
                           o=display.save_default_available, o_domain="dvi"),
            FFSynchronizer(i=ui.save_default_busy,
                           o=display.save_default_busy, o_domain="dvi"),
            FFSynchronizer(i=ui.save_default_status,
                           o=display.save_default_status, o_domain="dvi"),
            FFSynchronizer(i=ui.editing, o=display.editing, o_domain="dvi"),
        ]
        m.d.comb += [
            display.frequency_layout.eq(ui.frequency_layout),
            display.frequency_layout_preview.eq(ui.frequency_layout_preview),
            display.frequency_preview.eq(ui.frequency_preview),
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
            m.submodules += FFSynchronizer(
                i=display_input_meters[n], o=display.input_meters[n], o_domain="dvi")
        for n in range(RezoCore.N_BANDS):
            m.submodules += FFSynchronizer(
                i=ui.bank_groups[n], o=display.bank_groups[n], o_domain="dvi")
            m.submodules += FFSynchronizer(
                i=ui.feedback_sends[n], o=display.feedback_sends[n], o_domain="dvi")
            m.d.dvi += display.band_enables[n].eq(ui.band_enables[n])
            m.d.comb += display.band_frequencies[n].eq(ui.band_frequencies[n])

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


def run_cli(*, name="REZO", artifact_name=None, modeline=None):
    """Build the non-clocked REZO variant for one explicit display target."""
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(
        RezoBeamTop, path=this_path,
        argparse_callback=lambda parser: parser.set_defaults(
            name=name, artifact_name=artifact_name, modeline=modeline),
        archiver_callback=lambda archiver: archiver.with_option_storage())


if __name__ == "__main__":
    run_cli(
        name=os.getenv("TILIQUA_REZO_FAMILY_NAME", "REZO"),
        artifact_name=os.getenv("TILIQUA_REZO_FAMILY_ARTIFACT_NAME") or None,
        modeline=os.getenv("TILIQUA_REZO_FAMILY_MODELINE") or None,
    )
