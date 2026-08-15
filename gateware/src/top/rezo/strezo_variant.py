# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""
STREZO is a linked-stereo Graphic Resonant Filterbank-inspired Tiliqua
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
in gateware. Ten user-facing bands share controls across independent left and
right resonator state, preserving the stereo image through the wet path.
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
    from .encoder_acceleration import progressive_edit_level
    from .persistence import RezoStateJournal, SPIFlashTransfer
except ImportError:  # top_level_cli executes this file directly.
    from encoder_acceleration import progressive_edit_level
    from persistence import RezoStateJournal, SPIFlashTransfer


class RezoCore(wiring.Component):
    """Ten-band linked-stereo resonant filterbank."""

    N_BANDS = 10
    INPUT_UNITY = 32768
    INPUT_MAX = 65535
    INPUT_UNITY_POS = 52428
    PARAM_SLEW_STEP = 64
    # Proven input conditioner from the last hardware-clean DSP path. Keep it
    # independent of the user-facing feedback safety controls: its job is only
    # to prevent a hot Eurorack input from making an SVF state chatter.
    INPUT_LIMIT_KNEE = 12288
    INPUT_LIMIT_SHIFT = 3  # 8:1 above the knee
    # Fixed-point IIR states can otherwise settle into a low-level periodic
    # orbit after their input has gone quiet. Pull each integrator four guard
    # bits toward zero only below this input floor; normal audio and deliberate
    # resonator tails remain untouched.
    STATE_BLEED_INPUT = 32
    STATE_BLEED_STEP = 4
    INPUT_MODE_LEFT = 0
    INPUT_MODE_RIGHT = 1
    INPUT_MODE_CV = 2
    CV_TARGET_FEEDBACK = 0
    CV_TARGET_RESONANCE = 1
    CV_TARGET_DRIVE = 2
    CV_TARGET_GROUP_BASE = 3
    N_GROUPS = 4
    DRIVE_FLOOR = 8192       # 0.25x resonator excitation
    DRIVE_DEFAULT = 8192     # + floor = established 0.5x excitation
    DRIVE_MAX = 24575        # + floor = just below 1.0x
    CROSS_LAYOUT_GLOBAL = 0
    CROSS_LAYOUT_DIAGONAL = 1
    CROSS_LAYOUT_ROTATE = 2
    CROSS_LAYOUT_MIRROR = 3
    CROSS_LAYOUT_ALL = 4
    CROSS_LAYOUT_USER = 5
    CROSS_DEPTH_MAX = 128
    CROSS_CURVE_LINEAR = 0
    CROSS_CURVE_LOG = 1
    MOTION_SOURCE_OFF = 0
    MOTION_SOURCE_TRIANGLE = 1
    MOTION_SOURCE_RANDOM = 2

    @classmethod
    def cross_coefficient(cls, layout, source, destination, user_value):
        """Return one immutable factory send or the retained USER cell."""
        return Mux(
            layout == cls.CROSS_LAYOUT_USER, user_value,
            Mux(layout == cls.CROSS_LAYOUT_DIAGONAL,
                Mux(source == destination, 16, 0),
                Mux(layout == cls.CROSS_LAYOUT_ROTATE,
                    Mux(destination == ((source + 1)[:2]), 16, 0),
                    Mux(layout == cls.CROSS_LAYOUT_MIRROR,
                        Mux(destination == (3 - source), 16, 0),
                        Mux(layout == cls.CROSS_LAYOUT_ALL, 4, 0)))))

    @classmethod
    def cross_curve_coefficient(cls, curve, raw):
        """Translate a retained fader position to one DSP coefficient."""
        position = min(raw, cls.CROSS_DEPTH_MAX) / cls.CROSS_DEPTH_MAX
        if curve == cls.CROSS_CURVE_LINEAR:
            shaped = position
        else:
            # Early-rising logarithmic response: make the low half audible
            # sooner, then progressively refine the approach to full scale.
            shaped = math.log1p(7.0 * position) / math.log(8.0)
        return round(cls.CROSS_DEPTH_MAX * shaped)

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
            raise ValueError("STREZO requires the default 16-bit Q1.15 ASQ format")
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
        self.same_feedback = Signal(unsigned(8), init=self.CROSS_DEPTH_MAX)
        self.cross_feedback = Signal(unsigned(8), init=0)
        self.cross_curve = Signal(init=self.CROSS_CURVE_LINEAR)
        self.cross_layout = Signal(unsigned(3), init=self.CROSS_LAYOUT_GLOBAL)
        self.cross_matrix = [
            Signal(unsigned(5), init=16 if source == destination else 0,
                   name=f"cross_matrix_{source}_{destination}")
            for source in range(self.N_GROUPS)
            for destination in range(self.N_GROUPS)
        ]
        self.limit_knee = Signal(unsigned(16), init=8192)
        self.limit_cap = Signal(unsigned(16), init=28672)
        self.damp_mode = Signal(unsigned(3), init=3)
        self.motion_source = Signal(unsigned(2), init=0)
        # RATE is tenths of a hertz (1..200 => 0.1..20.0 Hz). PHASE is the
        # full 8-bit per-band phase increment; DEPTH is 0..128.
        self.motion_rate = Signal(unsigned(8), init=12)
        self.motion_phase = Signal(unsigned(8), init=28)
        self.motion_depth = Signal(unsigned(8), init=32)
        # Display-only view of the already-computed bipolar LFO source.
        self.motion_monitor = Signal(signed(6))
        self.input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n < 2 else 0)
                            for n in range(4)]
        self.input_modes = [
            Signal(unsigned(2), init=(self.INPUT_MODE_LEFT,
                                      self.INPUT_MODE_RIGHT,
                                      self.INPUT_MODE_CV,
                                      self.INPUT_MODE_CV)[n],
                   name=f"input_mode{n}")
            for n in range(4)
        ]
        self.cv_targets = [Signal(unsigned(3), init=(1, 1, 2, 0)[n], name=f"cv_target{n}")
                           for n in range(4)]
        self.cv_depths = [Signal(signed(16), init=0, name=f"cv_depth{n}")
                          for n in range(4)]
        # Display-only input telemetry. Audio inputs report their post-VALUE
        # peak envelope; CV inputs report the raw, pre-DEPTH bipolar sample.
        # Keeping the signal in native Q1.15 units makes the capture points
        # explicit and lets the display choose its own compact scale.
        self.input_meters = [Signal(signed(16), name=f"input_meter{n}")
                             for n in range(4)]
        self.bank_groups = [Signal(unsigned(4), init=1 << min(n // 3, 3), name=f"bank_group{n}")
                            for n in range(self.N_BANDS)]
        self.feedback_sends = [Signal(init=1, name=f"feedback_send{n}")
                               for n in range(self.N_BANDS)]
        # Route bits mirror non-zero sends for display/inspection. The actual
        # mix is controlled by the five G1..G4/DRY send levels below.
        self.output_routes = [Signal(unsigned(5), init=route, name=f"output_route{n}")
                              for n, route in enumerate((0b01111, 0b01111,
                                                         0b00101, 0b00101))]
        self.output_sides = [Signal(init=n & 1, name=f"output_side{n}")
                             for n in range(4)]
        # Unipolar G1..G4/DRY send levels for OUT0..OUT3. A value of 16 is
        # unity. DRY defaults to zero, matching the old global DRY default.
        initial_routes = (0b01111, 0b01111, 0b00101, 0b00101)
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

        # CROSS closes a two-channel round trip, so its perceived feedback
        # strength is not linear in its per-leg coefficient. Keep the raw
        # 0..128 position for UI/persistence and translate it through one
        # registered block-ROM lookup before either GLOBAL or matrix routing.
        # Every curve retains the exact 0 and full-scale endpoints.
        cutoff_table = [
            fixed.Const(self.cutoff_coeff(freq, self.fs),
                        dsp.mac.SQNative).as_value().value
            for freq in self.FREQUENCIES_HZ
        ]
        curve_init = []
        for curve in range(2):
            for raw in range(256):
                curve_init.append(self.cross_curve_coefficient(curve, raw))
        # The 18-bit filter coefficient ROM uses only addresses 0..115. Store
        # CROSS curves at 512..1023 and use the spare read port, retaining one
        # DP16KD for both tables without an address adder.
        coefficient_init = [
            *cutoff_table,
            *([0] * (512 - len(cutoff_table))),
            *curve_init,
        ]
        m.submodules.coefficient_mem = coefficient_mem = Memory(
            shape=dsp.mac.SQNative.as_shape(), depth=len(coefficient_init),
            init=coefficient_init,
            attrs={"ram_style": "block"})
        cross_curve_rport = coefficient_mem.read_port()
        effective_cross_feedback = Signal(unsigned(8))
        self._effective_cross_feedback = effective_cross_feedback
        m.d.comb += [
            cross_curve_rport.addr.eq(Cat(
                self.cross_feedback, self.cross_curve, Const(1, 1))),
            effective_cross_feedback.eq(cross_curve_rport.data[:8]),
        ]

        # Smooth UI/CV target parameters before the DSP consumes them.  The UI
        # can jump a target by a whole encoder detent; the filterbank should
        # hear a short ramp instead of a coefficient/gain discontinuity.
        smooth_levels = [Signal(signed(16), init=0, name=f"smooth_level{n}")
                         for n in range(self.N_BANDS)]
        smooth_drive = Signal(unsigned(16), init=self.DRIVE_DEFAULT)
        smooth_resonance = Signal(unsigned(16), init=8192)
        smooth_feedback = Signal(unsigned(16), init=0)
        smooth_input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n < 2 else 0,
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
            feedback_gain.eq(Mux(effective_feedback > 31744, 31744,
                                 effective_feedback)),
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
        feedback_sample = Signal(ASQ, name="feedback_sample_l")
        feedback_sample_r = Signal(ASQ)

        # Shared values.  Convert the UI values into ASQ-ish fractions.  The
        # SVF uses inverse-Q: lower values are more resonant. Keep the safe
        # inverse-Q floor, then add a feedback-proportional amount selected by
        # DAMP. The former max(floor, feedback_damp) law made most positions
        # identical unless RES and FB were already at their extremes; adding
        # the term gives all five modes a useful, audible decay progression.
        resonance_ctl = Signal(ASQ)
        res_ctl = Signal(signed(17))
        feedback_damp = Signal(unsigned(16))
        resonance_base = Signal(unsigned(16))
        resonance_damped_raw = Signal(unsigned(17))
        resonance_base_q = Signal(unsigned(16))
        feedback_damp_q = Signal(unsigned(16))
        resonance_damped_q = Signal(unsigned(17))
        # Simulation probes; unconnected aliases disappear during synthesis.
        self._resonance_ctl = resonance_ctl
        self._feedback_damp = feedback_damp
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
            resonance_base.eq(Mux(res_ctl < 4096, 4096, res_ctl)),
            resonance_damped_raw.eq(resonance_base + feedback_damp),
            resonance_ctl.eq(Mux(
                resonance_damped_raw > 16384,
                16384, resonance_damped_raw)),
        ]

        # Feedback is smoothed and scheduled through the shared multiplier.
        # Full-scale UI feedback is capped just below the hardware-tested cliff
        # so the final encoder tick stays in the "hot but not runaway" region.
        x = Signal(dsp.mac.SQNative, name="x_l")
        x_r = Signal(dsp.mac.SQNative)
        # Keep the input-plus-feedback sum wide until after saturation. A
        # 16-bit intermediate can wrap before a limiter has a chance to act.
        x_drive = Signal(signed(18), name="x_drive_l")
        x_drive_r = Signal(signed(18))
        resonance = Signal(dsp.mac.SQNative)
        dry_sample = Signal(ASQ, name="dry_sample_l")
        dry_sample_r = Signal(ASQ)
        quiet_samples_l = Signal(unsigned(4))
        quiet_samples_r = Signal(unsigned(4))

        # Runtime frequency selection is table-driven. The next band's block-
        # ROM coefficient is prefetched after the current band's two SVF passes
        # are complete, so the synchronous output is ready before ``band`` is
        # advanced without putting a wide LUT mux in the audio path.
        cutoff_rport = coefficient_mem.read_port()
        frequency_array = Array(self.band_frequencies)
        for n in range(self.N_BANDS):
            m.d.comb += level_diffs[n].eq(
                self.levels[n] - smooth_levels[n])
        levels = Array(smooth_levels)

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
        state_output_route_commit = 16
        state_input_limit_commit = 17
        state_output_limit_commit = 18
        state_mac2_apply = 19
        state_input_gain_add = 20
        state_cv_apply = 21
        state_cv_apply_setup = 22
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
        # Each state bank needs one asynchronous read and one synchronous
        # write. ECP5 distributed RAM matches that contract exactly and avoids
        # four 10-way register muxes in the stereo SVF datapath. The high-pass
        # value is combinational in a Chamberlin SVF; only LP and BP are state.
        state_init = [0] * self.N_BANDS
        m.submodules.alp_mem = alp_mem = Memory(
            shape=svf_storage, depth=self.N_BANDS, init=state_init,
            attrs={"ram_style": "distributed"})
        m.submodules.abp_mem = abp_mem = Memory(
            shape=svf_storage, depth=self.N_BANDS, init=state_init,
            attrs={"ram_style": "distributed"})
        m.submodules.alp_r_mem = alp_r_mem = Memory(
            shape=svf_storage, depth=self.N_BANDS, init=state_init,
            attrs={"ram_style": "distributed"})
        m.submodules.abp_r_mem = abp_r_mem = Memory(
            shape=svf_storage, depth=self.N_BANDS, init=state_init,
            attrs={"ram_style": "distributed"})
        alp_rport, alp_wport = alp_mem.read_port(domain="comb"), alp_mem.write_port()
        abp_rport, abp_wport = abp_mem.read_port(domain="comb"), abp_mem.write_port()
        alp_r_rport, alp_r_wport = (
            alp_r_mem.read_port(domain="comb"), alp_r_mem.write_port())
        abp_r_rport, abp_r_wport = (
            abp_r_mem.read_port(domain="comb"), abp_r_mem.write_port())
        alp_cur_raw = Signal(svf_storage)
        abp_cur_raw = Signal(svf_storage)
        alp_cur_raw_r = Signal(svf_storage)
        abp_cur_raw_r = Signal(svf_storage)
        cutoff_cur_raw = Signal(dsp.mac.SQNative.as_shape())
        alp_cur = svf_shape(alp_cur_raw)
        abp_cur = svf_shape(abp_cur_raw)
        alp_cur_r = svf_shape(alp_cur_raw_r)
        abp_cur_r = svf_shape(abp_cur_raw_r)
        cutoff_cur = dsp.mac.SQNative(cutoff_cur_raw)

        mac_a_q = Signal(dsp.mac.SQNative)
        mac_b_q = Signal(dsp.mac.SQNative)
        mac_z = Signal(dsp.mac.SQRNative)
        mac_a_q_r = Signal(dsp.mac.SQNative)
        mac_b_q_r = Signal(dsp.mac.SQNative)
        mac_z_r = Signal(dsp.mac.SQRNative)
        svf_product_raw = Signal(svf_storage)
        svf_product_q_raw = Signal(svf_storage)
        svf_product = svf_shape(svf_product_raw)
        svf_product_q = svf_shape(svf_product_q_raw)
        hp_offset_q = Signal(svf_shape)
        svf_update_base = Signal(svf_shape)
        svf_next = Signal(svf_shape)
        # These aliases document which pipeline stage consumes the shared
        # update. Only one is live in any FSM state, so one adder/clamp serves
        # all three SVF equations.
        alp_next = ahp_next = abp_next = svf_next
        svf_product_raw_r = Signal(svf_storage)
        svf_product_q_raw_r = Signal(svf_storage)
        svf_product_q_r = svf_shape(svf_product_q_raw_r)
        hp_offset_q_r = Signal(svf_shape)
        svf_update_base_r = Signal(svf_shape)
        svf_next_r = Signal(svf_shape)
        alp_next_r = ahp_next_r = abp_next_r = svf_next_r
        alp_store_raw = Signal(svf_storage)
        abp_store_raw = Signal(svf_storage)
        alp_store_raw_r = Signal(svf_storage)
        abp_store_raw_r = Signal(svf_storage)

        def saturate_svf_update(value):
            """Clamp one widened signed add using only its overflow bits."""
            raw = value.as_value()
            width = svf_storage.width
            # All callers add/subtract two width-bit values, so ``raw`` has
            # exactly one guard bit. Equal top bits mean the low ``width``
            # bits are a valid signed result. A mismatch selects the rail from
            # the true widened sign, avoiding full-width magnitude comparators.
            return svf_shape(Mux(
                raw[-1] == raw[width - 1], raw[:width],
                Mux(raw[-1],
                    Const(1 << (width - 1), width),
                    Const((1 << (width - 1)) - 1, width))))

        svf_next_safe = saturate_svf_update(
            svf_product_q + svf_update_base)
        svf_next_safe_r = saturate_svf_update(
            svf_product_q_r + svf_update_base_r)

        # LP, HP, and BP updates occupy distinct FSM states. Their operand is
        # captured in the preceding commit state, keeping the stage-selection
        # mux out of the adder/clamp path without adding any audio cycles.

        m.d.comb += [
            alp_rport.addr.eq(band),
            abp_rport.addr.eq(band),
            alp_r_rport.addr.eq(band),
            abp_r_rport.addr.eq(band),
            alp_cur_raw.eq(alp_rport.data),
            abp_cur_raw.eq(abp_rport.data),
            alp_cur_raw_r.eq(alp_r_rport.data),
            abp_cur_raw_r.eq(abp_r_rport.data),
            cutoff_rport.addr.eq(frequency_array[cutoff_band]),
            cutoff_cur_raw.eq(cutoff_rport.data),
            mac_z.eq(mac_a_q * mac_b_q),
            mac_z_r.eq(mac_a_q_r * mac_b_q_r),
            svf_product_raw.eq(
                mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            svf_next.eq(svf_next_safe),
            svf_product_raw_r.eq(
                mac_z_r.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            svf_next_r.eq(svf_next_safe_r),
            alp_store_raw.eq(alp_next.as_value()),
            abp_store_raw.eq(abp_next.as_value()),
            alp_store_raw_r.eq(alp_next_r.as_value()),
            abp_store_raw_r.eq(abp_next_r.as_value()),
            alp_wport.addr.eq(band),
            alp_wport.data.eq(alp_store_raw),
            alp_wport.en.eq(state == state_mac1_setup),
            alp_r_wport.addr.eq(band),
            alp_r_wport.data.eq(alp_store_raw_r),
            alp_r_wport.en.eq(state == state_mac1_setup),
            abp_wport.addr.eq(band),
            abp_wport.data.eq(abp_store_raw),
            abp_wport.en.eq(state == state_mac2_apply),
            abp_r_wport.addr.eq(band),
            abp_r_wport.data.eq(abp_store_raw_r),
            abp_r_wport.en.eq(state == state_mac2_apply),
        ]

        def bleed_state(source, target, quiet):
            source_raw = source.as_value().as_signed()
            with m.If(quiet):
                with m.If(source_raw > self.STATE_BLEED_STEP):
                    m.d.comb += target.eq(source_raw - self.STATE_BLEED_STEP)
                with m.Elif(source_raw < -self.STATE_BLEED_STEP):
                    m.d.comb += target.eq(source_raw + self.STATE_BLEED_STEP)
                with m.Else():
                    m.d.comb += target.eq(0)

        quiet_l = quiet_samples_l.all()
        quiet_r = quiet_samples_r.all()
        bleed_state(alp_next, alp_store_raw, quiet_l)
        bleed_state(abp_next, abp_store_raw, quiet_l)
        bleed_state(alp_next_r, alp_store_raw_r, quiet_r)
        bleed_state(abp_next_r, abp_store_raw_r, quiet_r)

        mix_shape = signed(ASQ.as_shape().width + 5)
        main_acc = Signal(mix_shape)
        feedback_acc = Signal(mix_shape)
        feedback_acc_r = Signal(mix_shape)
        group_acc = [Signal(mix_shape, name=f"group_acc{n}")
                     for n in range(self.N_GROUPS)]
        group_acc_r = [Signal(mix_shape, name=f"group_acc_r{n}")
                       for n in range(self.N_GROUPS)]
        feedback_group_acc = [
            Signal(mix_shape, name=f"feedback_group_acc{n}")
            for n in range(self.N_GROUPS)
        ]
        feedback_group_acc_r = [
            Signal(mix_shape, name=f"feedback_group_acc_r{n}")
            for n in range(self.N_GROUPS)
        ]
        output_acc = [Signal(mix_shape, name=f"output_acc{n}") for n in range(4)]
        output_acc_array = Array(output_acc)
        output_next = Signal(mix_shape)
        output_source = Signal(range(self.N_GROUPS + 1))
        output_send_index = Signal(unsigned(5))
        # Stored sends are 0..16, so five bits are sufficient throughout this
        # MAC. The former seven-bit path carried two permanent zeroes through
        # its registers, multiplier, and rounding logic.
        output_send_gain = Signal(unsigned(5))
        output_send_gain_q = Signal(unsigned(5))
        output_send_product = Signal(signed(mix_shape.width + 5))
        output_send_term = Signal(mix_shape)
        output_send_term_q = Signal(mix_shape)
        term = Signal(mix_shape)
        term_q = Signal(mix_shape)
        term_r = Signal(mix_shape)
        term_q_r = Signal(mix_shape)
        enabled_term = Signal(mix_shape)
        enabled_term_r = Signal(mix_shape)
        level_cur = Signal(signed(16))
        level_cur_q = Signal(signed(16))
        feedback_send_cur_q = Signal()
        bank_group_cur_q = Signal(unsigned(self.N_GROUPS))
        level_with_cv = Signal(signed(18))
        motion_phase_acc = Signal(unsigned(24))
        motion_phase_cursor = Signal(unsigned(24))
        motion_phase_next = Signal(unsigned(24))
        motion_phase_sum = Signal(unsigned(25))
        motion_rate_increment = Signal(unsigned(12))
        motion_lfsr = Signal(unsigned(16), init=0x1d3f)
        motion_random_cursor = Signal(unsigned(16), init=0x1d3f)
        motion_random_next = Signal(unsigned(16))
        motion_source_phase = Signal(unsigned(24))
        motion_source_random = Signal(unsigned(16))
        motion_triangle_ramp = Signal(unsigned(15))
        motion_triangle = Signal(signed(17))
        motion_wave = Signal(signed(17))
        motion_depth_positive = Signal(signed(9))
        motion_product = Signal(signed(26))
        motion_term = Signal(signed(18))
        motion_term_q = Signal(signed(18))
        group_cur = Signal(signed(20))
        group_update_band = Signal(range(self.N_BANDS))
        group_update_raw = Signal(signed(20))
        group_offsets = Array(Signal(signed(20), name=f"group_offset{n}")
                              for n in range(self.N_BANDS))
        band_sample = Signal(dsp.mac.SQNative)
        band_sample_r = Signal(dsp.mac.SQNative)
        main_next = Signal(mix_shape)
        filtered_next = Signal(mix_shape)
        feedback_drive = Signal(mix_shape)
        feedback_drive_r = Signal(mix_shape)
        limit_cap_safe = Signal(unsigned(16))
        clip_drive = Signal(mix_shape)
        clip_drive_r = Signal(mix_shape)
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
        clip_negative_r = Signal()
        clip_negative_q_r = Signal()
        clip_mag_r = Signal(unsigned(16))
        clip_mag_q_r = Signal(unsigned(16))
        clip_excess_r = Signal(unsigned(16))
        clip_excess_q_r = Signal(unsigned(16))
        clip_square_r = Signal(unsigned(32))
        clip_square_q_r = Signal(unsigned(32))
        clip_shaped_mag_r = Signal(unsigned(17))
        clip_output_mag_r = Signal(unsigned(16))
        clip_limited_r = Signal(ASQ)
        bank_input_soft = Signal(mix_shape)
        bank_input_limited = Signal(ASQ)
        bank_input_soft_r = Signal(mix_shape)
        bank_input_limited_r = Signal(ASQ)
        output_limited = Signal(ASQ)
        feedback_term = Signal(dsp.mac.SQNative)
        feedback_term_q = Signal(dsp.mac.SQNative)
        feedback_term_r = Signal(dsp.mac.SQNative)
        feedback_term_q_r = Signal(dsp.mac.SQNative)
        feedback_mix_l = Signal(ASQ)
        feedback_mix_r = Signal(ASQ)
        feedback_mix_q_l = Signal(ASQ)
        feedback_mix_q_r = Signal(ASQ)
        # Matrix cells are traversed source-fast, one destination at a time.
        # A single accumulator per channel is therefore sufficient; each
        # completed destination is clamped into its existing feedback-term
        # register before the final four gain cells.
        matrix_route_acc_l = Signal(signed(19))
        matrix_route_acc_r = Signal(signed(19))
        matrix_route_next_l = Signal(signed(20))
        matrix_route_next_r = Signal(signed(20))
        matrix_route_next_limited_l = Signal(ASQ)
        matrix_route_next_limited_r = Signal(ASQ)
        matrix_feedback_term_l = [
            Signal(ASQ, name=f"matrix_feedback_term_l{n}")
            for n in range(self.N_GROUPS)
        ]
        matrix_feedback_term_r = [
            Signal(ASQ, name=f"matrix_feedback_term_r{n}")
            for n in range(self.N_GROUPS)
        ]
        matrix_route_index = Signal(range(20))
        matrix_source = Signal(unsigned(2))
        matrix_destination = Signal(unsigned(2))
        matrix_coefficient_q = Signal(unsigned(5))
        matrix_next_route_index = Signal(range(20))
        matrix_next_source = Signal(unsigned(2))
        matrix_next_destination = Signal(unsigned(2))
        matrix_next_coefficient = Signal(unsigned(5))
        matrix_cross_feedback_q = Signal(unsigned(8))
        matrix_feedback_gain_q = Signal(unsigned(16))
        matrix_combined_gain_product = Signal(unsigned(24))
        matrix_combined_gain_q = Signal(unsigned(15))
        matrix_source_l = Signal(mix_shape)
        matrix_source_r = Signal(mix_shape)
        matrix_source_limited_l = Signal(ASQ)
        matrix_source_limited_r = Signal(ASQ)
        matrix_multiply_source_l = Signal(signed(18))
        matrix_multiply_source_r = Signal(signed(18))
        matrix_multiply_source_q_l = Signal(signed(18))
        matrix_multiply_source_q_r = Signal(signed(18))
        # Both phases of the matrix pipeline now fit the same 18x18 DSP per
        # channel. Group sums are clamped to the audio rails before their
        # 0..16 send is applied; the final destination sum was already
        # clamped at the same rails before its feedback gain. Keeping the
        # shared operand at 18 bits prevents the 24-bit mux from splitting
        # each channel's multiply across two DSP blocks.
        matrix_multiply_a_l = Signal(signed(18))
        matrix_multiply_a_r = Signal(signed(18))
        matrix_multiply_b = Signal(unsigned(16))
        matrix_product_l = Signal(signed(34))
        matrix_product_r = Signal(signed(34))
        matrix_product_q_l = Signal(signed(18))
        matrix_product_q_r = Signal(signed(18))
        matrix_cross_sum_l = Signal(signed(19))
        matrix_cross_sum_r = Signal(signed(19))
        matrix_cross_sum_q_l = Signal(signed(19))
        matrix_cross_sum_q_r = Signal(signed(19))
        matrix_x_drive_l = Signal(signed(20))
        matrix_x_drive_r = Signal(signed(20))
        bank_drive_source_l = Signal(signed(20))
        bank_drive_source_r = Signal(signed(20))
        bank_drive_source_q_l = Signal(signed(20))
        bank_drive_source_q_r = Signal(signed(20))
        # Private simulation probes; these aliases do not create additional
        # hardware and make the stereo feedback path directly testable.
        self._feedback_sample_l = feedback_sample
        self._feedback_sample_r = feedback_sample_r
        self._feedback_mix_l = feedback_mix_q_l
        self._feedback_mix_r = feedback_mix_q_r
        self._feedback_acc_l = feedback_acc
        self._feedback_acc_r = feedback_acc_r
        self._feedback_gain = feedback_gain
        self._matrix_feedback_term_l = matrix_feedback_term_l
        self._matrix_feedback_term_r = matrix_feedback_term_r
        # The original 0..16 controls used a /16 normalization. The expanded
        # 0..128 controls use /128, preserving both historical endpoints while
        # providing eight times as many useful positions between them.
        cross_self_gain = Signal(unsigned(8))
        cross_other_gain = Signal(unsigned(8))
        cross_ll = Signal(signed(25))
        cross_lr = Signal(signed(25))
        cross_rr = Signal(signed(25))
        cross_rl = Signal(signed(25))
        cross_ll_q = Signal.like(cross_ll)
        cross_lr_q = Signal.like(cross_lr)
        cross_rr_q = Signal.like(cross_rr)
        cross_rl_q = Signal.like(cross_rl)
        cross_sum_l = Signal(signed(23))
        cross_sum_r = Signal(signed(23))
        dry_gain_term = Signal(mix_shape)
        input_gain_product_q = Signal(mix_shape)
        input_mix_acc = Signal(mix_shape)
        input_mix_acc_r = Signal(mix_shape)
        input_mix_next = Signal(mix_shape)
        input_mix_next_r = Signal(mix_shape)
        input_mix_sample = Signal(ASQ)
        input_mix_sample_r = Signal(ASQ)
        input_mix_limited = Signal(ASQ)
        input_mix_limited_r = Signal(ASQ)
        input_gain_magnitude = Signal(unsigned(21))
        input_gain_meter_sample = Signal(unsigned(16))
        drive_term = Signal(signed(18))
        drive_term_q = Signal(signed(18))
        drive_term_r = Signal(signed(18))
        drive_term_q_r = Signal(signed(18))
        input_samples = [Signal(ASQ, name=f"input_sample{n}") for n in range(4)]
        cv_product = Signal(signed(18))
        # Compute each physical input's product once, then reuse a shared
        # four-term sum while committing the seven possible destinations.
        # This avoids both the former 28 repeated products and an expensive
        # dynamically indexed seven-accumulator write network.
        cv_products = [Signal(signed(18), name=f"cv_product{n}")
                       for n in range(4)]
        cv_product_array = Array(cv_products)
        cv_acc_value = Signal(signed(20))
        cv_acc_value_q = Signal(signed(20))
        cv_apply_target = Signal(range(7))
        bank_group_array = Array(self.bank_groups)
        band_enable_array = Array(self.band_enables)
        feedback_send_array = Array(self.feedback_sends)
        output_send_array = Array(self.output_sends)
        feedback_group_array = Array(feedback_group_acc)
        feedback_group_array_r = Array(feedback_group_acc_r)
        matrix_coefficient_array = Array(self.cross_matrix)
        matrix_feedback_array_l = Array(matrix_feedback_term_l)
        matrix_feedback_array_r = Array(matrix_feedback_term_r)
        # Accumulate each group once while the bands are being processed, then
        # traverse the 4x5 send matrix after the final band.  Routing every
        # band through every output consumed 120 clocks/sample by itself and
        # exceeded the 312-clock budget at 192 kHz.
        output_sources = Array([
            *group_acc,
            input_mix_sample.as_value().as_signed(),
        ])
        output_sources_r = Array([
            *group_acc_r,
            input_mix_sample_r.as_value().as_signed(),
        ])
        output_source_signal = Signal(mix_shape)
        output_source_q = Signal(mix_shape)
        input_mode_array = Array(self.input_modes)
        cv_target_array = Array(self.cv_targets)
        m.d.comb += [
            motion_rate_increment.eq((self.motion_rate << 3) + self.motion_rate),
            motion_phase_sum.eq(motion_phase_acc + motion_rate_increment),
            motion_phase_next.eq(
                motion_phase_cursor + (self.motion_phase << 16)),
            motion_random_next.eq(Cat(
                motion_random_cursor[1:],
                motion_random_cursor[0] ^ motion_random_cursor[2] ^
                motion_random_cursor[3] ^ motion_random_cursor[5])),
            # Band zero is prepared in INPUT_LIMIT; subsequent bands are
            # prepared while the previous band commits its mix.
            motion_source_phase.eq(Mux(
                state == state_input_limit_commit,
                motion_phase_acc, motion_phase_next)),
            motion_source_random.eq(Mux(
                state == state_input_limit_commit,
                motion_lfsr, motion_random_next)),
            motion_triangle_ramp.eq(Mux(
                motion_source_phase[23],
                ~motion_source_phase[8:23],
                motion_source_phase[8:23])),
            motion_triangle.eq((motion_triangle_ramp << 1) - 32768),
            motion_wave.eq(Mux(
                self.motion_source == 1, motion_triangle,
                Mux(self.motion_source == 2,
                    motion_source_random.as_signed(), 0))),
            motion_depth_positive.eq(Cat(self.motion_depth, Const(0, 1)).as_signed()),
            motion_product.eq(motion_wave * motion_depth_positive),
            motion_term.eq(motion_product >> 7),
            level_with_cv.eq(levels[band] + group_cur + motion_term_q),
            # SVF state carries two fractional guard bits beyond SQNative.
            # Dropping its raw 20-bit value directly into the 18-bit MAC input
            # truncated the sign bits instead of rescaling, producing a 4x
            # signal below |1.0| and a hard sign wrap above it. Rescale first,
            # then recover the established output gain after multiplication.
            band_sample.eq(abp_cur.as_value().as_signed() >> 2),
            band_sample_r.eq(abp_cur_r.as_value().as_signed() >> 2),
            term.eq(mac_z.as_value().as_signed() >>
                    (dsp.mac.SQNative.f_bits - 1)),
            term_r.eq(mac_z_r.as_value().as_signed() >>
                      (dsp.mac.SQNative.f_bits - 1)),
            feedback_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            feedback_term_r.eq(mac_z_r.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            dry_gain_term.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            input_gain_magnitude.eq(Mux(
                input_gain_product_q < 0,
                -input_gain_product_q,
                input_gain_product_q)),
            input_gain_meter_sample.eq(Mux(
                input_gain_magnitude > 32767, 32767,
                input_gain_magnitude)),
            input_mix_next.eq(input_mix_acc + Mux(
                input_mode_array[input_chan] == self.INPUT_MODE_LEFT,
                input_gain_product_q, 0)),
            input_mix_next_r.eq(input_mix_acc_r + Mux(
                input_mode_array[input_chan] == self.INPUT_MODE_RIGHT,
                input_gain_product_q, 0)),
            # Work in raw Q1.15 storage units before widening. Shifting the
            # fixed-point view directly and assigning it to a plain signed
            # guard-bit signal preserves the numeric value rather than the raw
            # half-scale representation, which accidentally drove every
            # resonator 2x harder.
            drive_term.eq(
                mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            drive_term_r.eq(
                mac_z_r.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            x_drive.eq(drive_term_q +
                       feedback_term_q.as_value().as_signed()),
            x_drive_r.eq(drive_term_q_r +
                         feedback_term_q_r.as_value().as_signed()),
            limit_cap_safe.eq(Mux(self.limit_cap > 32767, 32767,
                                  self.limit_cap)),
            enabled_term.eq(Mux(band_enable_array[band], term_q, 0)),
            enabled_term_r.eq(Mux(band_enable_array[band], term_q_r, 0)),
            main_next.eq(main_acc + enabled_term),
            filtered_next.eq(main_next - dry_sample.as_value().as_signed()),
            feedback_drive.eq(feedback_acc),
            feedback_drive_r.eq(feedback_acc_r),
            cv_product.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            cv_acc_value.eq(
                Mux((input_mode_array[0] == self.INPUT_MODE_CV) &
                    (cv_target_array[0] == cv_target_scan), cv_products[0], 0) +
                Mux((input_mode_array[1] == self.INPUT_MODE_CV) &
                    (cv_target_array[1] == cv_target_scan), cv_products[1], 0) +
                Mux((input_mode_array[2] == self.INPUT_MODE_CV) &
                    (cv_target_array[2] == cv_target_scan), cv_products[2], 0) +
                Mux((input_mode_array[3] == self.INPUT_MODE_CV) &
                    (cv_target_array[3] == cv_target_scan), cv_products[3], 0)),
            cross_self_gain.eq(self.same_feedback),
            cross_other_gain.eq(Mux(
                self.cross_layout == self.CROSS_LAYOUT_GLOBAL,
                effective_cross_feedback, 0)),
            cross_ll.eq(feedback_sample.as_value().as_signed() *
                        Cat(cross_self_gain, Const(0, 1)).as_signed()),
            cross_lr.eq(feedback_sample_r.as_value().as_signed() *
                        Cat(cross_other_gain, Const(0, 1)).as_signed()),
            cross_rr.eq(feedback_sample_r.as_value().as_signed() *
                        Cat(cross_self_gain, Const(0, 1)).as_signed()),
            cross_rl.eq(feedback_sample.as_value().as_signed() *
                        Cat(cross_other_gain, Const(0, 1)).as_signed()),
            cross_sum_l.eq((cross_ll_q + cross_lr_q) >> 7),
            cross_sum_r.eq((cross_rr_q + cross_rl_q) >> 7),
            matrix_source.eq(matrix_route_index[:2]),
            matrix_destination.eq(Mux(
                matrix_route_index < 16,
                matrix_route_index[2:4], matrix_route_index[:2])),
            matrix_next_route_index.eq(Mux(
                matrix_route_index == 19, 0, matrix_route_index + 1)),
            matrix_next_source.eq(matrix_next_route_index[:2]),
            matrix_next_destination.eq(Mux(
                matrix_next_route_index < 16,
                matrix_next_route_index[2:4], matrix_next_route_index[:2])),
            matrix_next_coefficient.eq(self.cross_coefficient(
                self.cross_layout, matrix_next_source,
                matrix_next_destination,
                matrix_coefficient_array[
                    Cat(matrix_next_destination, matrix_next_source)])),
            matrix_combined_gain_product.eq(
                matrix_cross_feedback_q * matrix_feedback_gain_q),
            matrix_source_l.eq(feedback_group_array_r[matrix_source]),
            matrix_source_r.eq(feedback_group_array[matrix_source]),
            matrix_multiply_source_l.eq(Mux(
                matrix_route_index < 16,
                matrix_source_limited_l.as_value().as_signed(),
                matrix_feedback_array_l[matrix_destination].as_value().as_signed())),
            matrix_multiply_source_r.eq(Mux(
                matrix_route_index < 16,
                matrix_source_limited_r.as_value().as_signed(),
                matrix_feedback_array_r[matrix_destination].as_value().as_signed())),
            matrix_multiply_a_l.eq(matrix_multiply_source_q_l),
            matrix_multiply_a_r.eq(matrix_multiply_source_q_r),
            matrix_multiply_b.eq(Mux(
                matrix_route_index < 16,
                matrix_coefficient_q,
                matrix_combined_gain_q)),
            matrix_product_l.eq(matrix_multiply_a_l * matrix_multiply_b),
            matrix_product_r.eq(matrix_multiply_a_r * matrix_multiply_b),
            matrix_route_next_l.eq(matrix_route_acc_l + matrix_product_q_l),
            matrix_route_next_r.eq(matrix_route_acc_r + matrix_product_q_r),
            matrix_cross_sum_l.eq(
                Mux(bank_group_cur_q[0], matrix_feedback_array_l[0], 0) +
                Mux(bank_group_cur_q[1], matrix_feedback_array_l[1], 0) +
                Mux(bank_group_cur_q[2], matrix_feedback_array_l[2], 0) +
                Mux(bank_group_cur_q[3], matrix_feedback_array_l[3], 0)),
            matrix_cross_sum_r.eq(
                Mux(bank_group_cur_q[0], matrix_feedback_array_r[0], 0) +
                Mux(bank_group_cur_q[1], matrix_feedback_array_r[1], 0) +
                Mux(bank_group_cur_q[2], matrix_feedback_array_r[2], 0) +
                Mux(bank_group_cur_q[3], matrix_feedback_array_r[3], 0)),
            matrix_x_drive_l.eq(
                drive_term_q + feedback_term_q.as_value().as_signed() +
                matrix_cross_sum_q_l),
            matrix_x_drive_r.eq(
                drive_term_q_r + feedback_term_q_r.as_value().as_signed() +
                matrix_cross_sum_q_r),
            bank_drive_source_l.eq(Mux(
                self.cross_layout == self.CROSS_LAYOUT_GLOBAL,
                x_drive, matrix_x_drive_l)),
            bank_drive_source_r.eq(Mux(
                self.cross_layout == self.CROSS_LAYOUT_GLOBAL,
                x_drive_r, matrix_x_drive_r)),
        ]
        # The feedback tap and CROSS control remain stable for hundreds of
        # clocks. Pipeline their convex stereo mix continuously so neither the
        # DSP products nor the normalization/clamp sit on the sample-state
        # critical path.
        m.d.sync += [
            # Matrix membership and its four group terms are selected for the
            # current band here. The following SVF state applies the existing
            # soft conditioner, splitting what would otherwise be a long
            # dynamic-mux + add + saturate path at 60 MHz.
            bank_drive_source_q_l.eq(bank_drive_source_l),
            bank_drive_source_q_r.eq(bank_drive_source_r),
            matrix_cross_sum_q_l.eq(matrix_cross_sum_l),
            matrix_cross_sum_q_r.eq(matrix_cross_sum_r),
            matrix_multiply_source_q_l.eq(matrix_multiply_source_l),
            matrix_multiply_source_q_r.eq(matrix_multiply_source_r),
            matrix_cross_feedback_q.eq(effective_cross_feedback),
            matrix_feedback_gain_q.eq(feedback_gain),
            # source * coefficient / 16 is accumulated per destination.
            # CROSS now has eight times the old UI resolution, so divide by
            # 256 rather than 32. The later Q1.15 shift preserves the exact
            # historical full-scale matrix feedback depth.
            matrix_combined_gain_q.eq(
                (matrix_combined_gain_product + 128) >> 8),
            cross_ll_q.eq(cross_ll),
            cross_lr_q.eq(cross_lr),
            cross_rr_q.eq(cross_rr),
            cross_rl_q.eq(cross_rl),
            feedback_mix_q_l.eq(feedback_mix_l),
            feedback_mix_q_r.eq(feedback_mix_r),
        ]
        m.d.comb += [
            output_send_index.eq(
                output_source + (output_chan << 2) + output_chan),
            output_send_gain.eq(output_send_array[output_send_index]),
            output_source_signal.eq(Mux(
                Array(self.output_sides)[output_chan], output_sources_r[output_source],
                output_sources[output_source])),
            output_send_product.eq(output_source_q * output_send_gain_q),
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
            clip_drive_r.eq(feedback_drive_r),
            clip_excess_r.eq(Mux(
                clip_mag_r > self.limit_knee,
                clip_mag_r - self.limit_knee, 0)),
            clip_square_r.eq(clip_excess_q_r * clip_excess_q_r),
            clip_shaped_mag_r.eq(Mux(
                clip_mag_q_r > self.limit_knee,
                clip_mag_q_r - (clip_square_q_r >> 16),
                clip_mag_q_r)),
            clip_output_mag_r.eq(Mux(
                clip_shaped_mag_r > limit_cap_safe,
                limit_cap_safe, clip_shaped_mag_r)),
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
        with m.If(clip_drive_r >= 32768):
            m.d.comb += [clip_negative_r.eq(0), clip_mag_r.eq(32768)]
        with m.Elif(clip_drive_r <= -32768):
            m.d.comb += [clip_negative_r.eq(1), clip_mag_r.eq(32768)]
        with m.Elif(clip_drive_r < 0):
            m.d.comb += [clip_negative_r.eq(1), clip_mag_r.eq(-clip_drive_r)]
        with m.Else():
            m.d.comb += [clip_negative_r.eq(0), clip_mag_r.eq(clip_drive_r)]
        with m.If(clip_negative_q_r):
            m.d.comb += clip_limited_r.as_value().eq(-clip_output_mag_r)
        with m.Else():
            m.d.comb += clip_limited_r.as_value().eq(clip_output_mag_r)

        # The feedback saturator above shapes the delayed wet signal. This is
        # a separate, deliberately simple conditioner on the signal entering
        # every resonator. It restores the transfer curve used by the last
        # hardware-clean build while retaining the wider pre-limit sum.
        with m.If(bank_drive_source_q_l > self.INPUT_LIMIT_KNEE):
            m.d.comb += bank_input_soft.eq(
                self.INPUT_LIMIT_KNEE +
                ((bank_drive_source_q_l - self.INPUT_LIMIT_KNEE) >>
                 self.INPUT_LIMIT_SHIFT))
        with m.Elif(bank_drive_source_q_l < -self.INPUT_LIMIT_KNEE):
            m.d.comb += bank_input_soft.eq(
                -self.INPUT_LIMIT_KNEE +
                ((bank_drive_source_q_l + self.INPUT_LIMIT_KNEE) >>
                 self.INPUT_LIMIT_SHIFT))
        with m.Else():
            m.d.comb += bank_input_soft.eq(bank_drive_source_q_l)
        with m.If(bank_drive_source_q_r > self.INPUT_LIMIT_KNEE):
            m.d.comb += bank_input_soft_r.eq(
                self.INPUT_LIMIT_KNEE +
                ((bank_drive_source_q_r - self.INPUT_LIMIT_KNEE) >>
                 self.INPUT_LIMIT_SHIFT))
        with m.Elif(bank_drive_source_q_r < -self.INPUT_LIMIT_KNEE):
            m.d.comb += bank_input_soft_r.eq(
                -self.INPUT_LIMIT_KNEE +
                ((bank_drive_source_q_r + self.INPUT_LIMIT_KNEE) >>
                 self.INPUT_LIMIT_SHIFT))
        with m.Else():
            m.d.comb += bank_input_soft_r.eq(bank_drive_source_q_r)

        def limit_to_asq(source, target):
            with m.If(source > 32767):
                m.d.comb += target.as_value().eq(32767)
            with m.Elif(source < -32768):
                m.d.comb += target.as_value().eq(-32768)
            with m.Else():
                m.d.comb += target.as_value().eq(source)

        limit_to_asq(output_next, output_limited)
        limit_to_asq(input_mix_acc, input_mix_limited)
        limit_to_asq(input_mix_acc_r, input_mix_limited_r)
        # The input-plus-feedback sum stays wide through the transfer curve so
        # it cannot wrap before this final rail clamp.
        limit_to_asq(bank_input_soft, bank_input_limited)
        limit_to_asq(bank_input_soft_r, bank_input_limited_r)
        limit_to_asq(cross_sum_l, feedback_mix_l)
        limit_to_asq(cross_sum_r, feedback_mix_r)
        limit_to_asq(matrix_source_l, matrix_source_limited_l)
        limit_to_asq(matrix_source_r, matrix_source_limited_r)
        limit_to_asq(matrix_route_next_l, matrix_route_next_limited_l)
        limit_to_asq(matrix_route_next_r, matrix_route_next_limited_r)

        # Pipeline magnitude, square, and clamp/sign across three short stages.
        # The feedback sum is stable for many routing cycles; x gets explicit
        # settling states below before clip_limited is captured.
        m.d.sync += [
            clip_negative_q.eq(clip_negative),
            clip_mag_q.eq(clip_mag),
            clip_excess_q.eq(clip_excess),
            clip_square_q.eq(clip_square),
            clip_negative_q_r.eq(clip_negative_r),
            clip_mag_q_r.eq(clip_mag_r),
            clip_excess_q_r.eq(clip_excess_r),
            clip_square_q_r.eq(clip_square_r),
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

        # The per-band motion waveform changes as the DSP advances through
        # ten phase-offset bands. Capture only the base, depth-scaled term
        # prepared for band zero so the UI reports the modulation actually
        # applied: zero depth collapses the monitor and full depth preserves
        # the source's full displayed excursion.
        with m.If(state == state_input_limit_commit):
            m.d.sync += self.motion_monitor.eq(motion_term >> 12)

        with m.Switch(state):
            with m.Case(state_wait):
                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += motion_phase_acc.eq(motion_phase_sum[:24])
                    with m.If(motion_phase_sum[24]):
                        # The random source is sample-and-hold at the selected
                        # motion rate, not audio-rate noise. One LFSR state
                        # seeds a deterministic ten-band pattern until the
                        # next phase wrap.
                        m.d.sync += motion_lfsr.eq(Cat(
                            motion_lfsr[1:],
                            motion_lfsr[0] ^ motion_lfsr[2] ^
                            motion_lfsr[3] ^ motion_lfsr[5]))
                    for n in range(4):
                        m.d.sync += input_samples[n].eq(self.i.payload[n])
                    for n, diff in enumerate(level_diffs):
                        with m.If(diff > self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_levels[n].eq(
                                smooth_levels[n] + self.PARAM_SLEW_STEP)
                        with m.Elif(diff < -self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_levels[n].eq(
                                smooth_levels[n] - self.PARAM_SLEW_STEP)
                        with m.Else():
                            m.d.sync += smooth_levels[n].eq(self.levels[n])
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
                        self.effective_drive.eq(effective_drive),
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
                    ]
                    m.d.sync += [
                        mac_a_q.eq(self.i.payload[0]),
                        mac_b_q.eq(smooth_cv_depths[0]),
                        state.eq(state_cv_commit),
                    ]

            with m.Case(state_cv_commit):
                m.d.sync += cv_product_array[cv_chan].eq(cv_product)
                with m.If(cv_chan != 3):
                    m.d.sync += cv_chan.eq(cv_chan + 1)
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
                    m.d.sync += [
                        cv_target_scan.eq(0),
                        state.eq(state_cv_apply_setup),
                    ]

            with m.Case(state_cv_apply_setup):
                # Split the four-term destination sum from its target clamp.
                # Subsequent commits capture the following target in parallel,
                # so this pipeline costs one warm-up clock for the whole pass.
                m.d.sync += [
                    cv_acc_value_q.eq(cv_acc_value),
                    cv_apply_target.eq(0),
                    cv_target_scan.eq(1),
                    state.eq(state_cv_apply),
                ]

            with m.Case(state_cv_apply):
                with m.Switch(cv_apply_target):
                    with m.Case(self.CV_TARGET_FEEDBACK):
                        with m.If(cv_acc_value_q > 65535):
                            m.d.sync += feedback_cv_term.eq(65535)
                        with m.Elif(cv_acc_value_q < -65536):
                            m.d.sync += feedback_cv_term.eq(-65536)
                        with m.Else():
                            m.d.sync += feedback_cv_term.eq(cv_acc_value_q)
                    with m.Case(self.CV_TARGET_RESONANCE):
                        with m.If(cv_acc_value_q > 65535):
                            m.d.sync += resonance_cv_term.eq(65535)
                        with m.Elif(cv_acc_value_q < -65536):
                            m.d.sync += resonance_cv_term.eq(-65536)
                        with m.Else():
                            m.d.sync += resonance_cv_term.eq(cv_acc_value_q)
                    with m.Case(self.CV_TARGET_DRIVE):
                        with m.If(cv_acc_value_q > 65535):
                            m.d.sync += drive_cv_term.eq(65535)
                        with m.Elif(cv_acc_value_q < -65536):
                            m.d.sync += drive_cv_term.eq(-65536)
                        with m.Else():
                            m.d.sync += drive_cv_term.eq(cv_acc_value_q)
                    for n in range(self.N_GROUPS):
                        with m.Case(self.CV_TARGET_GROUP_BASE + n):
                            with m.If(cv_acc_value_q > 16383):
                                m.d.sync += [
                                    group_cv_terms[n].eq(16383),
                                    self.effective_groups[n].eq(16383),
                                ]
                            with m.Elif(cv_acc_value_q < -16384):
                                m.d.sync += [
                                    group_cv_terms[n].eq(-16384),
                                    self.effective_groups[n].eq(-16384),
                                ]
                            with m.Else():
                                m.d.sync += [
                                    group_cv_terms[n].eq(cv_acc_value_q),
                                    self.effective_groups[n].eq(cv_acc_value_q),
                                ]
                with m.If(cv_apply_target != 6):
                    m.d.sync += [
                        cv_acc_value_q.eq(cv_acc_value),
                        cv_apply_target.eq(cv_target_scan),
                    ]
                    with m.If(cv_target_scan != 6):
                        m.d.sync += cv_target_scan.eq(cv_target_scan + 1)
                with m.Else():
                    m.d.sync += [
                        resonance_base_q.eq(resonance_base),
                        feedback_damp_q.eq(feedback_damp),
                        input_mix_acc.eq(0),
                        input_mix_acc_r.eq(0),
                        input_chan.eq(0),
                        mac_a_q.eq(input_samples[0]),
                        mac_b_q.eq(Mux(self.input_modes[0] != self.INPUT_MODE_CV,
                                       input_gain_coeffs[0], 0)),
                        state.eq(state_input_gain_commit),
                    ]

            with m.Case(state_input_gain_commit):
                m.d.sync += [
                    resonance_damped_q.eq(
                        resonance_base_q + feedback_damp_q),
                    input_gain_product_q.eq(dry_gain_term),
                    state.eq(state_input_gain_add),
                ]

            with m.Case(state_input_gain_add):
                # This state sees the completed VALUE multiplication for the
                # current physical input. Audio channels get a fast-attack,
                # slow-release peak meter; CV channels bypass VALUE/DEPTH and
                # expose the signed jack sample directly.
                for n in range(4):
                    with m.If(input_chan == n):
                        with m.If(self.input_modes[n] == self.INPUT_MODE_CV):
                            m.d.sync += self.input_meters[n].eq(input_samples[n])
                        with m.Elif(input_gain_meter_sample >= self.input_meters[n]):
                            m.d.sync += self.input_meters[n].eq(input_gain_meter_sample)
                        with m.Elif(self.input_meters[n] > 0):
                            m.d.sync += self.input_meters[n].eq(
                                self.input_meters[n] -
                                (self.input_meters[n].as_unsigned() >> 14) - 1)
                        with m.Else():
                            m.d.sync += self.input_meters[n].eq(0)
                with m.Switch(input_chan):
                  with m.Case(0):
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        input_mix_acc_r.eq(input_mix_next_r),
                        input_chan.eq(1),
                        mac_a_q.eq(input_samples[1]),
                        mac_b_q.eq(Mux(self.input_modes[1] != self.INPUT_MODE_CV,
                                       input_gain_coeffs[1], 0)),
                        state.eq(state_input_gain_commit),
                    ]
                  with m.Case(1):
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        input_mix_acc_r.eq(input_mix_next_r),
                        input_chan.eq(2),
                        mac_a_q.eq(input_samples[2]),
                        mac_b_q.eq(Mux(self.input_modes[2] != self.INPUT_MODE_CV,
                                       input_gain_coeffs[2], 0)),
                        state.eq(state_input_gain_commit),
                    ]
                  with m.Case(2):
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        input_mix_acc_r.eq(input_mix_next_r),
                        input_chan.eq(3),
                        mac_a_q.eq(input_samples[3]),
                        mac_b_q.eq(Mux(self.input_modes[3] != self.INPUT_MODE_CV,
                                       input_gain_coeffs[3], 0)),
                        state.eq(state_input_gain_commit),
                    ]
                  with m.Default():
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        input_mix_acc_r.eq(input_mix_next_r),
                        state.eq(state_input_limit_commit),
                    ]

            with m.Case(state_input_limit_commit):
                m.d.sync += [
                            input_mix_sample.eq(input_mix_limited),
                            input_mix_sample_r.eq(input_mix_limited_r),
                            resonance.eq(Mux(
                                resonance_damped_q > 16384,
                                16384, resonance_damped_q)),
                            mac_a_q.as_value().eq(
                                input_mix_limited.as_value().as_signed()),
                            mac_b_q.as_value().eq(self.effective_drive),
                            mac_a_q_r.as_value().eq(
                                input_mix_limited_r.as_value().as_signed()),
                            mac_b_q_r.as_value().eq(self.effective_drive),
                            band.eq(0),
                            cutoff_band.eq(0),
                            oversample.eq(0),
                            motion_phase_cursor.eq(motion_phase_acc),
                            motion_random_cursor.eq(motion_lfsr),
                            motion_term_q.eq(motion_term),
                            state.eq(state_drive_commit),
                ]
                with m.If(
                        (input_mix_limited.as_value().as_signed() >=
                         -self.STATE_BLEED_INPUT) &
                        (input_mix_limited.as_value().as_signed() <=
                         self.STATE_BLEED_INPUT)):
                    with m.If(~quiet_samples_l.all()):
                        m.d.sync += quiet_samples_l.eq(quiet_samples_l + 1)
                with m.Else():
                    m.d.sync += quiet_samples_l.eq(0)
                with m.If(
                        (input_mix_limited_r.as_value().as_signed() >=
                         -self.STATE_BLEED_INPUT) &
                        (input_mix_limited_r.as_value().as_signed() <=
                         self.STATE_BLEED_INPUT)):
                    with m.If(~quiet_samples_r.all()):
                        m.d.sync += quiet_samples_r.eq(quiet_samples_r + 1)
                with m.Else():
                    m.d.sync += quiet_samples_r.eq(0)

            with m.Case(state_drive_commit):
                m.d.sync += [
                            drive_term_q.eq(drive_term),
                            drive_term_q_r.eq(drive_term_r),
                            mac_a_q.eq(feedback_mix_q_l),
                            mac_b_q.eq(feedback_gain >> 1),
                            mac_a_q_r.eq(feedback_mix_q_r),
                            mac_b_q_r.eq(feedback_gain >> 1),
                            state.eq(state_feedback_commit),
                ]

            with m.Case(state_feedback_commit):
                m.d.sync += [
                    feedback_term_q.eq(feedback_term),
                    feedback_term_q_r.eq(feedback_term_r),
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
                    x_r.eq(bank_input_limited_r),
                    dry_sample.eq(input_mix_sample),
                    dry_sample_r.eq(input_mix_sample_r),
                    main_acc.eq(input_mix_sample),
                    feedback_acc.eq(0),
                    feedback_acc_r.eq(0),
                    state.eq(state_mac0_setup),
                ]
                for n in range(self.N_GROUPS):
                    m.d.sync += [
                        group_acc[n].eq(0),
                        group_acc_r[n].eq(0),
                        feedback_group_acc[n].eq(0),
                        feedback_group_acc_r[n].eq(0),
                    ]
                for n in range(4):
                    m.d.sync += output_acc[n].eq(0)

            with m.Case(state_mac0_setup):
                m.d.sync += [
                    # Capture the dynamically selected band/group gain at the
                    # beginning of the section.  It is stable long before the
                    # mix MAC needs it, avoiding a ten-way mux and clamp on the
                    # synchronous critical path.
                    level_cur_q.eq(level_cur),
                    feedback_send_cur_q.eq(feedback_send_array[band]),
                    bank_group_cur_q.eq(bank_group_array[band]),
                    mac_a_q.eq(abp_cur),
                    mac_b_q.eq(cutoff_cur),
                    mac_a_q_r.eq(abp_cur_r),
                    mac_b_q_r.eq(cutoff_cur),
                    state.eq(state_mac0_commit),
                ]
            with m.Case(state_mac0_commit):
                m.d.sync += [
                    svf_product_q_raw.eq(svf_product_raw),
                    svf_product_q_raw_r.eq(svf_product_raw_r),
                    svf_update_base.eq(alp_cur),
                    svf_update_base_r.eq(alp_cur_r),
                    state.eq(state_mac1_setup),
                ]
            with m.Case(state_mac1_setup):
                m.d.sync += [
                    mac_a_q.eq(abp_cur),
                    mac_b_q.eq(-resonance),
                    mac_a_q_r.eq(abp_cur_r),
                    mac_b_q_r.eq(-resonance),
                    state.eq(state_mac1_commit),
                ]
                with m.If(self.cross_layout == self.CROSS_LAYOUT_GLOBAL):
                    m.d.sync += [
                        hp_offset_q.eq(
                            saturate_svf_update(x - alp_next)),
                        hp_offset_q_r.eq(
                            saturate_svf_update(x_r - alp_next_r)),
                    ]
                with m.Else():
                    m.d.sync += [
                        hp_offset_q.eq(
                            saturate_svf_update(
                                dsp.mac.SQNative(bank_input_limited) -
                                alp_next)),
                        hp_offset_q_r.eq(
                            saturate_svf_update(
                                dsp.mac.SQNative(bank_input_limited_r) -
                                alp_next_r)),
                    ]

            with m.Case(state_mac1_commit):
                m.d.sync += [
                    svf_product_q_raw.eq(svf_product_raw),
                    svf_product_q_raw_r.eq(svf_product_raw_r),
                    svf_update_base.eq(hp_offset_q),
                    svf_update_base_r.eq(hp_offset_q_r),
                    state.eq(state_mac2_setup),
                ]

            with m.Case(state_mac2_setup):
                m.d.sync += [
                    mac_a_q.eq(ahp_next),
                    mac_b_q.eq(cutoff_cur),
                    mac_a_q_r.eq(ahp_next_r),
                    mac_b_q_r.eq(cutoff_cur),
                    state.eq(state_mac2_commit),
                ]

            with m.Case(state_mac2_commit):
                m.d.sync += [
                    svf_product_q_raw.eq(svf_product_raw),
                    svf_product_q_raw_r.eq(svf_product_raw_r),
                    svf_update_base.eq(abp_cur),
                    svf_update_base_r.eq(abp_cur_r),
                    state.eq(state_mac2_apply),
                ]

            with m.Case(state_mac2_apply):
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
                    mac_a_q_r.eq(band_sample_r),
                    mac_b_q_r.eq(level_cur_q),
                    cutoff_band.eq(Mux(
                        band == self.N_BANDS - 1, 0, band + 1)),
                    state.eq(state_mix_gain_commit),
                ]

            with m.Case(state_mix_gain_commit):
                m.d.sync += [
                    term_q.eq(term),
                    term_q_r.eq(term_r),
                    state.eq(state_mix_commit),
                ]

            with m.Case(state_mix_commit):
                m.d.sync += [
                    main_acc.eq(main_next),
                    motion_phase_cursor.eq(motion_phase_next),
                    motion_random_cursor.eq(motion_random_next),
                    motion_term_q.eq(motion_term),
                ]
                with m.If(feedback_send_cur_q):
                    m.d.sync += [
                        feedback_acc.eq(feedback_acc + enabled_term),
                        feedback_acc_r.eq(feedback_acc_r + enabled_term_r),
                    ]
                    for n in range(self.N_GROUPS):
                        with m.If(bank_group_cur_q[n]):
                            m.d.sync += [
                                feedback_group_acc[n].eq(
                                    feedback_group_acc[n] + enabled_term),
                                feedback_group_acc_r[n].eq(
                                    feedback_group_acc_r[n] + enabled_term_r),
                            ]
                for n in range(self.N_GROUPS):
                    with m.If(bank_group_cur_q[n]):
                        m.d.sync += [
                            group_acc[n].eq(group_acc[n] + enabled_term),
                            group_acc_r[n].eq(group_acc_r[n] + enabled_term_r),
                        ]
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
                        matrix_route_index.eq(0),
                        matrix_coefficient_q.eq(self.cross_coefficient(
                            self.cross_layout, Const(0, 2), Const(0, 2),
                            self.cross_matrix[0])),
                        matrix_route_acc_l.eq(0),
                        matrix_route_acc_r.eq(0),
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
                    output_source_q.eq(output_source_signal),
                    state.eq(state_output_limit_commit),
                ]

            with m.Case(state_output_limit_commit):
                m.d.sync += [
                    output_send_term_q.eq(output_send_term),
                    matrix_product_q_l.eq(Mux(
                        matrix_route_index < 16,
                        matrix_product_l >> 4,
                        matrix_product_l >> dsp.mac.SQNative.f_bits)),
                    matrix_product_q_r.eq(Mux(
                        matrix_route_index < 16,
                        matrix_product_r >> 4,
                        matrix_product_r >> dsp.mac.SQNative.f_bits)),
                    state.eq(state_output_product_commit),
                ]

            with m.Case(state_output_product_commit):
                m.d.sync += output_acc_array[output_chan].eq(output_next)
                with m.If(matrix_route_index < 15):
                    m.d.sync += matrix_coefficient_q.eq(
                        matrix_next_coefficient)
                with m.If(matrix_route_index < 16):
                    with m.If(matrix_source == self.N_GROUPS - 1):
                        m.d.sync += [
                            matrix_feedback_array_l[
                                matrix_destination].eq(
                                    matrix_route_next_limited_l),
                            matrix_feedback_array_r[
                                matrix_destination].eq(
                                    matrix_route_next_limited_r),
                            matrix_route_acc_l.eq(0),
                            matrix_route_acc_r.eq(0),
                        ]
                    with m.Else():
                        m.d.sync += [
                            matrix_route_acc_l.eq(matrix_route_next_l),
                            matrix_route_acc_r.eq(matrix_route_next_r),
                        ]
                with m.Else():
                    m.d.sync += [
                        matrix_feedback_array_l[matrix_destination].as_value().eq(
                            matrix_product_q_l),
                        matrix_feedback_array_r[matrix_destination].as_value().eq(
                            matrix_product_q_r),
                    ]
                with m.If(matrix_route_index != 19):
                    m.d.sync += matrix_route_index.eq(matrix_route_index + 1)
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
                        feedback_sample_r.eq(clip_limited_r),
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
        brief="STREZO linked-stereo resonant filterbank.",
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
    TARGET_CROSS_LAYOUT = RezoCore.N_BANDS + 50
    # The three IDs immediately before the aligned matrix block are otherwise
    # unused. DEPTH safely aliases BANK's PRESET ID because controls are always
    # interpreted in the context of their page; this avoids widening every
    # seven-bit selection path on an already dense device.
    TARGET_MOTION_SOURCE = RezoCore.N_BANDS + 51
    TARGET_MOTION_RATE = RezoCore.N_BANDS + 52
    TARGET_MOTION_PHASE = RezoCore.N_BANDS + 53
    TARGET_MOTION_DEPTH = TARGET_PRESET
    # Keep the sixteen matrix cells on a 16-ID boundary. This lets both the
    # UI and encoder navigation use the low four selected bits directly.
    TARGET_CROSS_MATRIX_BASE = RezoCore.N_BANDS + 54
    TARGET_FEEDBACK_SEND_BASE = RezoCore.N_BANDS + 70
    TARGET_PALETTE = RezoCore.N_BANDS + 80
    TARGET_SAVE_DEFAULT = RezoCore.N_BANDS + 81
    TARGET_BAND_LAYOUT = RezoCore.N_BANDS + 82
    TARGET_BAND_ENABLE_BASE = RezoCore.N_BANDS + 83
    TARGET_BAND_FREQ_BASE = RezoCore.N_BANDS + 93
    TARGET_CROSS_FEEDBACK = RezoCore.N_BANDS + 103
    TARGET_OUTPUT_SIDE_BASE = RezoCore.N_BANDS + 104
    TARGET_CROSS_ROW_BASE = RezoCore.N_BANDS + 108
    TARGET_CROSS_COL_BASE = RezoCore.N_BANDS + 112
    # OUTPUT and CROSS never coexist on screen, so their row/column headers
    # can share selection IDs. DRY needs a fifth column and safely reuses the
    # CROSS layout ID in OUTPUT context. This keeps the global target path at
    # seven bits on a nearly full device.
    TARGET_OUTPUT_ROW_BASE = TARGET_CROSS_ROW_BASE
    TARGET_OUTPUT_COL_BASE = TARGET_CROSS_COL_BASE
    TARGET_OUTPUT_DRY_COL = TARGET_CROSS_LAYOUT
    TARGET_SAME_FEEDBACK = RezoCore.N_BANDS + 116
    # BANDS DEPTH and CROSS CURVE never coexist on screen. Sharing their
    # selection ID avoids extending another decode term through this nearly
    # full design; edit behavior remains page-qualified below.
    TARGET_CROSS_CURVE = TARGET_MOTION_DEPTH
    N_TARGETS = RezoCore.N_BANDS + 117

    # STREZO has its own journal magic and no longer retains dormant FILTER or
    # mono-REZO placeholders. Every live static parameter is densely packed;
    # dynamic modulation/filter state remains intentionally unsaved.
    STATE_WORDS_V4 = 36
    STATE_WORDS_V5 = 38
    STATE_CAPACITY_WORDS = 1024

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
            "same_feedback": Out(unsigned(8)),
            "cross_feedback": Out(unsigned(8)),
            "cross_curve": Out(1),
            "cross_layout": Out(unsigned(3)),
            "cross_layout_preview": Out(unsigned(3)),
            "cross_matrix": Out(data.ArrayLayout(unsigned(5), 16)),
            "limit_knee": Out(unsigned(16)),
            "limit_cap": Out(unsigned(16)),
            "damp_mode": Out(unsigned(3)),
            "motion_source": Out(unsigned(2)),
            "motion_rate": Out(unsigned(8)),
            "motion_phase": Out(unsigned(8)),
            "motion_depth": Out(unsigned(8)),
            "input_gains": Out(data.ArrayLayout(unsigned(16), 4)),
            "input_modes": Out(data.ArrayLayout(unsigned(2), 4)),
            "cv_targets": Out(data.ArrayLayout(unsigned(3), 4)),
            "cv_depths": Out(data.ArrayLayout(signed(16), 4)),
            "bank_groups": Out(data.ArrayLayout(unsigned(4), RezoCore.N_BANDS)),
            "feedback_sends": Out(data.ArrayLayout(unsigned(1), RezoCore.N_BANDS)),
            "output_routes": Out(data.ArrayLayout(unsigned(5), 4)),
            "output_sides": Out(data.ArrayLayout(unsigned(1), 4)),
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
        editing = Signal()

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
        drive = Signal(unsigned(16))
        resonance = Signal(unsigned(8), init=8192 >> 8)
        feedback = Signal(unsigned(8), init=0)
        same_feedback_reduction = Signal(unsigned(8), init=0)
        same_feedback = Signal(unsigned(8))
        m.d.comb += same_feedback.eq(
            RezoCore.CROSS_DEPTH_MAX - same_feedback_reduction)
        cross_feedback = Signal(unsigned(8), init=0)
        cross_curve = Signal(init=RezoCore.CROSS_CURVE_LINEAR)
        cross_curve_pad = Signal()
        cross_layout = Signal(unsigned(3), init=RezoCore.CROSS_LAYOUT_GLOBAL)
        cross_layout_preview = Signal(
            unsigned(3), init=RezoCore.CROSS_LAYOUT_GLOBAL)
        cross_matrix = [
            Signal(unsigned(5), init=16 if source == destination else 0,
                   name=f"ui_cross_matrix_{source}_{destination}")
            for source in range(RezoCore.N_GROUPS)
            for destination in range(RezoCore.N_GROUPS)
        ]
        cross_copy_active = Signal()
        cross_copy_index = Signal(range(16))
        cross_copy_layout = Signal(unsigned(3))
        cross_copy_source = cross_copy_index[2:4]
        cross_copy_destination = cross_copy_index[:2]
        cross_copy_value = RezoCore.cross_coefficient(
            cross_copy_layout, cross_copy_source, cross_copy_destination,
            Const(0, 5))
        with m.If(cross_copy_active):
            with m.If(cross_copy_index == 15):
                m.d.sync += [cross_copy_active.eq(0), editing.eq(1)]
            with m.Else():
                m.d.sync += cross_copy_index.eq(cross_copy_index + 1)
        # Header edits touch four cells, but an encoder detent is vastly
        # slower than four sync clocks. Serializing the relative adjustment
        # avoids adding a broad parallel write mux to every saved matrix bit.
        cross_relative_active = Signal()
        cross_relative_step = Signal(unsigned(2))
        cross_relative_group = Signal(unsigned(2))
        cross_relative_column = Signal()
        cross_relative_direction = Signal()
        cross_relative_index = Signal(unsigned(4))
        m.d.comb += cross_relative_index.eq(Mux(
            cross_relative_column,
            Cat(cross_relative_group, cross_relative_step),
            Cat(cross_relative_step, cross_relative_group)))
        with m.If(cross_relative_active):
            with m.If(cross_relative_step == 3):
                m.d.sync += cross_relative_active.eq(0)
            with m.Else():
                m.d.sync += cross_relative_step.eq(cross_relative_step + 1)
        limit_knee = Signal(unsigned(8), init=8192 >> 8)
        limit_cap = Signal(unsigned(8), init=28672 >> 8)
        damp_mode = Signal(unsigned(3), init=3)
        motion_source = Signal(unsigned(2), init=0)
        motion_rate = Signal(unsigned(8), init=12)
        motion_phase = Signal(unsigned(8), init=28)
        motion_depth = Signal(unsigned(8), init=32)
        input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n < 2 else 0,
                              name=f"ui_input_gain{n}")
                       for n in range(4)]
        input_modes = [Signal(unsigned(2),
                              init=(RezoCore.INPUT_MODE_LEFT,
                                    RezoCore.INPUT_MODE_RIGHT,
                                    RezoCore.INPUT_MODE_CV,
                                    RezoCore.INPUT_MODE_CV)[n],
                              name=f"ui_input_mode{n}")
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
        initial_output_masks = (0b01111, 0b01111, 0b00101, 0b00101)
        output_routes = [Signal(unsigned(5), name=f"ui_output_route{n}")
                         for n in range(4)]
        output_sides = [Signal(init=n & 1, name=f"ui_output_side{n}")
                        for n in range(4)]
        bank_output_sends = [
            Signal(unsigned(5),
                   init=16 if source < RezoCore.N_GROUPS and
                              initial_output_masks[output] & (1 << source) else 0,
                   name=f"ui_bank_output_send{output}_{source}")
            for output in range(4) for source in range(RezoCore.N_GROUPS + 1)
        ]
        output_sends = bank_output_sends
        for n in range(RezoCore.N_BANDS):
            m.d.comb += bank_groups[n].eq(
                bank_group_indices[n] ^ (bank_group_indices[n] >> 1))
        for n in range(4):
            base = n * (RezoCore.N_GROUPS + 1)
            m.d.comb += output_routes[n].eq(Cat(*(
                bank_output_sends[base + group] != 0
                for group in range(RezoCore.N_GROUPS + 1))))
        drive_position = Signal(unsigned(8))
        m.d.comb += [
            drive_position.eq(bank_drive),
            drive.eq(Mux(drive_position == 96, RezoCore.DRIVE_MAX,
                         drive_position << 8)),
        ]
        selected = Signal(range(self.N_TARGETS), init=self.TARGET_PAGE)
        # Row and column target bases are both congruent to two modulo four.
        # Capture the group continuously through direct bit wiring so the
        # detent handler does not place arithmetic inside the large UI mux.
        m.d.sync += [
            cross_relative_group[0].eq(selected[0]),
            cross_relative_group[1].eq(~selected[1]),
        ]
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
        output_side_target = Signal()
        output_row_target = Signal()
        output_col_target = Signal()
        cross_matrix_target = Signal()
        cross_row_target = Signal()
        cross_col_target = Signal()
        cross_edit_target = Signal()
        advanced_target_visible = Signal()
        band_edit_target_visible = Signal()
        band_enable_target = Signal()
        band_frequency_target = Signal()
        bank_band_target = Signal()
        bank_band_index = Signal(range(RezoCore.N_BANDS))
        bank_band_enabled = Signal(init=1)
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
        cross_direct_write = Signal()
        cross_direct_index = Signal(unsigned(4))
        cross_direct_direction = Signal()
        output_edit_pending = Signal()
        output_edit_index = Signal(unsigned(5))
        output_edit_direction = Signal()
        # OUTPUT header edits are serialized through the same one-cell write
        # path as ordinary sends. Four or five sync ticks are instantaneous to
        # the user and far cheaper than a parallel twenty-cell adjustment.
        output_relative_active = Signal()
        output_relative_step = Signal(unsigned(3))
        output_relative_index = Signal(unsigned(5))
        output_relative_column = Signal()
        output_relative_direction = Signal()
        m.d.comb += [
            cross_direct_write.eq(0),
            cross_direct_index.eq(0),
            cross_direct_direction.eq(0),
        ]
        m.d.sync += output_edit_pending.eq(0)
        with m.If(output_relative_active):
            m.d.sync += [
                output_edit_pending.eq(1),
                output_edit_index.eq(output_relative_index),
                output_edit_direction.eq(output_relative_direction),
            ]
            with m.If(output_relative_step == Mux(
                    output_relative_column, 3, 4)):
                m.d.sync += output_relative_active.eq(0)
            with m.Else():
                m.d.sync += [
                    output_relative_step.eq(output_relative_step + 1),
                    output_relative_index.eq(
                        output_relative_index +
                        Mux(output_relative_column, 5, 1)),
                ]
        detent_timer = Signal(unsigned(21), init=(1 << 21) - 1)
        accelerated_edit_level = Signal(unsigned(2))
        next_accelerated_edit_level = Signal(unsigned(2))
        accelerated_edit_step = Signal(unsigned(3))
        edit_repeat_remaining = Signal(unsigned(2))
        continuous_accel_target = Signal()
        m.d.comb += continuous_accel_target.eq(editing & (
            bank_band_target |
            (selected == self.TARGET_DRIVE) |
            (selected == self.TARGET_RESONANCE) |
            (selected == self.TARGET_FEEDBACK) |
            (selected == self.TARGET_SAME_FEEDBACK) |
            (selected == self.TARGET_CROSS_FEEDBACK) |
            ((page == 6) & (selected == self.TARGET_MOTION_DEPTH)) |
            (selected == self.TARGET_LIMIT_KNEE) |
            (selected == self.TARGET_LIMIT_CAP) |
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
        m.d.comb += [
            accelerated_edit_step.eq(accelerated_edit_level + 1),
            next_accelerated_edit_level.eq(progressive_edit_level(
                detent_timer,
                accelerated_edit_level,
                editing,
                Mux(next_detent_acc > 0, ~edit_direction, edit_direction),
            )),
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
        # Accelerate every continuous control by replaying its same cheap
        # one-step edit. Sustained fast turns ramp through 1x, 2x, 3x, and 4x;
        # slow turns and reversals immediately return to precise 1x editing.
        # This avoids a variable-width adder in every parameter path, which is
        # costly on this nearly full ECP5.
        # Routing matrices and other discrete selectors deliberately remain
        # one detent per state.
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
                        accelerated_edit_level.eq(next_accelerated_edit_level),
                        edit_repeat_remaining.eq(Mux(
                            continuous_accel_target,
                            next_accelerated_edit_level, 0)),
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

        m.d.comb += [
            bank_target_visible.eq(selected <= self.TARGET_FEEDBACK),
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
            output_cell_target.eq(
                (selected >= self.TARGET_OUTPUT_BASE) &
                (selected < self.TARGET_OUTPUT_BASE + 20)),
            output_side_target.eq(
                (selected >= self.TARGET_OUTPUT_SIDE_BASE) &
                (selected < self.TARGET_OUTPUT_SIDE_BASE + 4)),
            output_row_target.eq(
                (page == 4) &
                (selected >= self.TARGET_OUTPUT_ROW_BASE) &
                (selected < self.TARGET_OUTPUT_ROW_BASE + 4)),
            output_col_target.eq(
                (page == 4) &
                (((selected >= self.TARGET_OUTPUT_COL_BASE) &
                  (selected < self.TARGET_OUTPUT_COL_BASE + 4)) |
                 (selected == self.TARGET_OUTPUT_DRY_COL))),
            output_target_visible.eq((selected == self.TARGET_PAGE) |
                                     output_cell_target | output_side_target |
                                     output_row_target | output_col_target),
            cross_matrix_target.eq(
                (selected >= self.TARGET_CROSS_MATRIX_BASE) &
                (selected < self.TARGET_CROSS_MATRIX_BASE + 16)),
            cross_row_target.eq(
                (page == 7) &
                (selected >= self.TARGET_CROSS_ROW_BASE) &
                (selected < self.TARGET_CROSS_ROW_BASE + 4)),
            cross_col_target.eq(
                (page == 7) &
                (selected >= self.TARGET_CROSS_COL_BASE) &
                (selected < self.TARGET_CROSS_COL_BASE + 4)),
            cross_edit_target.eq(
                cross_matrix_target | cross_row_target | cross_col_target),
            advanced_target_visible.eq(
                (selected == self.TARGET_PAGE) |
                (selected == self.TARGET_PALETTE) |
                (selected == self.TARGET_CROSS_CURVE) |
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
                band_enable_target | band_frequency_target |
                (selected == self.TARGET_MOTION_SOURCE) |
                (selected == self.TARGET_MOTION_RATE) |
                (selected == self.TARGET_MOTION_PHASE) |
                ((page == 6) & (selected == self.TARGET_MOTION_DEPTH))),
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
            ~bank_band_target | Array(band_enables)[bank_band_index])
        with m.If(page == 0):
            with m.If(edit_direction):
                with m.If(~bank_target_visible | (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_PRESET)
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
                with m.Elif(selected == self.TARGET_PRESET):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
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
            # Five column headers, then each row header, stereo side, and its
            # five send cells. Header turns adjust the associated sends
            # relatively, matching the CROSS matrix interaction.
            with m.If(edit_direction):
                with m.If(~output_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_COL_BASE)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_COL_BASE)
                with m.Elif(output_col_target):
                    m.d.comb += next_selected.eq(Mux(
                        selected == self.TARGET_OUTPUT_DRY_COL,
                        self.TARGET_OUTPUT_ROW_BASE,
                        Mux(selected == self.TARGET_OUTPUT_COL_BASE + 3,
                            self.TARGET_OUTPUT_DRY_COL, selected + 1)))
                for output in range(4):
                    row_target = self.TARGET_OUTPUT_ROW_BASE + output
                    side_target = self.TARGET_OUTPUT_SIDE_BASE + output
                    first_send = self.TARGET_OUTPUT_BASE + output * 5
                    last_send = first_send + 4
                    with m.Elif(selected == row_target):
                        m.d.comb += next_selected.eq(side_target)
                    with m.Elif(selected == side_target):
                        m.d.comb += next_selected.eq(first_send)
                    with m.Elif(selected == last_send):
                        m.d.comb += next_selected.eq(
                            self.TARGET_PAGE if output == 3 else row_target + 1)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~output_target_visible):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_BASE + 19)
                with m.Elif(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_BASE + 19)
                for output in range(4):
                    row_target = self.TARGET_OUTPUT_ROW_BASE + output
                    side_target = self.TARGET_OUTPUT_SIDE_BASE + output
                    first_send = self.TARGET_OUTPUT_BASE + output * 5
                    with m.Elif(selected == row_target):
                        m.d.comb += next_selected.eq(
                            self.TARGET_OUTPUT_DRY_COL if output == 0 else
                            self.TARGET_OUTPUT_BASE + output * 5 - 1)
                    with m.Elif(selected == side_target):
                        m.d.comb += next_selected.eq(row_target)
                    with m.Elif(selected == first_send):
                        m.d.comb += next_selected.eq(side_target)
                with m.Elif(selected == self.TARGET_OUTPUT_DRY_COL):
                    m.d.comb += next_selected.eq(self.TARGET_OUTPUT_COL_BASE + 3)
                with m.Elif(output_col_target &
                            (selected == self.TARGET_OUTPUT_COL_BASE)):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected - 1)
        with m.Elif(page == 5):
            with m.If(edit_direction):
                with m.If(~advanced_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_PALETTE)
                with m.Elif(selected == self.TARGET_PALETTE):
                    m.d.comb += next_selected.eq(self.TARGET_SAVE_DEFAULT)
                with m.Elif(selected == self.TARGET_SAVE_DEFAULT):
                    m.d.comb += next_selected.eq(self.TARGET_CROSS_CURVE)
                with m.Else():
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
            with m.Else():
                with m.If(~advanced_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_CROSS_CURVE)
                with m.Elif(selected == self.TARGET_CROSS_CURVE):
                    m.d.comb += next_selected.eq(self.TARGET_SAVE_DEFAULT)
                with m.Elif(selected == self.TARGET_SAVE_DEFAULT):
                    m.d.comb += next_selected.eq(self.TARGET_PALETTE)
                with m.Else():
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
        with m.Elif(page == 6):
            # Layout, ten enables, ten frequencies, then the two-column
            # internal-motion controls.
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
                    m.d.comb += next_selected.eq(self.TARGET_MOTION_SOURCE)
                with m.Elif(selected == self.TARGET_MOTION_SOURCE):
                    m.d.comb += next_selected.eq(self.TARGET_MOTION_RATE)
                with m.Elif(selected == self.TARGET_MOTION_RATE):
                    m.d.comb += next_selected.eq(Mux(
                        motion_source[1],
                        self.TARGET_MOTION_DEPTH,
                        self.TARGET_MOTION_PHASE))
                with m.Elif(selected == self.TARGET_MOTION_PHASE):
                    m.d.comb += next_selected.eq(self.TARGET_MOTION_DEPTH)
                with m.Elif(selected == self.TARGET_MOTION_DEPTH):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(~band_edit_target_visible |
                          (selected == self.TARGET_PAGE)):
                    m.d.comb += next_selected.eq(self.TARGET_MOTION_DEPTH)
                with m.Elif(selected == self.TARGET_MOTION_DEPTH):
                    m.d.comb += next_selected.eq(Mux(
                        motion_source[1],
                        self.TARGET_MOTION_RATE,
                        self.TARGET_MOTION_PHASE))
                with m.Elif(selected == self.TARGET_MOTION_PHASE):
                    m.d.comb += next_selected.eq(self.TARGET_MOTION_RATE)
                with m.Elif(selected == self.TARGET_MOTION_RATE):
                    m.d.comb += next_selected.eq(self.TARGET_MOTION_SOURCE)
                with m.Elif(selected == self.TARGET_MOTION_SOURCE):
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
        with m.Elif(page == 7):
            # Layout, four TO headers, each FROM header and its four cells,
            # then independent same-side and cross-feedback amounts.
            # GLOBAL skips the matrix because it routes complete stereo sums.
            with m.If(edit_direction):
                with m.If(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_CROSS_LAYOUT)
                with m.Elif(selected == self.TARGET_CROSS_LAYOUT):
                    m.d.comb += next_selected.eq(Mux(
                        cross_layout == RezoCore.CROSS_LAYOUT_GLOBAL,
                        self.TARGET_SAME_FEEDBACK,
                        self.TARGET_CROSS_COL_BASE))
                with m.Elif(cross_col_target):
                    m.d.comb += next_selected.eq(Mux(
                        selected == self.TARGET_CROSS_COL_BASE + 3,
                        self.TARGET_CROSS_ROW_BASE, selected + 1))
                with m.Elif(cross_row_target):
                    m.d.comb += next_selected.eq(
                        self.TARGET_CROSS_MATRIX_BASE +
                        (cross_relative_group << 2))
                with m.Elif(cross_matrix_target &
                            (selected[:2] == 3)):
                    m.d.comb += next_selected.eq(Mux(
                        selected == self.TARGET_CROSS_MATRIX_BASE + 15,
                        self.TARGET_SAME_FEEDBACK,
                        self.TARGET_CROSS_ROW_BASE + 1 +
                        selected[2:4]))
                with m.Elif(selected == self.TARGET_SAME_FEEDBACK):
                    m.d.comb += next_selected.eq(self.TARGET_CROSS_FEEDBACK)
                with m.Elif(selected == self.TARGET_CROSS_FEEDBACK):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Else():
                    m.d.comb += next_selected.eq(selected + 1)
            with m.Else():
                with m.If(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(
                        self.TARGET_CROSS_FEEDBACK)
                with m.Elif(selected == self.TARGET_CROSS_FEEDBACK):
                    m.d.comb += next_selected.eq(self.TARGET_SAME_FEEDBACK)
                with m.Elif(selected == self.TARGET_SAME_FEEDBACK):
                    m.d.comb += next_selected.eq(Mux(
                        cross_layout == RezoCore.CROSS_LAYOUT_GLOBAL,
                        self.TARGET_CROSS_LAYOUT,
                        self.TARGET_CROSS_MATRIX_BASE + 15))
                with m.Elif(cross_matrix_target &
                            (selected[:2] == 0)):
                    m.d.comb += next_selected.eq(
                        self.TARGET_CROSS_ROW_BASE +
                        selected[2:4])
                with m.Elif(cross_row_target):
                    m.d.comb += next_selected.eq(Mux(
                        selected == self.TARGET_CROSS_ROW_BASE,
                        self.TARGET_CROSS_COL_BASE + 3,
                        self.TARGET_CROSS_MATRIX_BASE + 3 +
                        ((cross_relative_group - 1) << 2)))
                with m.Elif(cross_col_target &
                            (selected == self.TARGET_CROSS_COL_BASE)):
                    m.d.comb += next_selected.eq(self.TARGET_CROSS_LAYOUT)
                with m.Elif(selected == self.TARGET_CROSS_LAYOUT):
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
            with m.Elif(output_side_target):
                output_side = Array(output_sides)[
                    selected - self.TARGET_OUTPUT_SIDE_BASE]
                m.d.sync += [output_side.eq(~output_side), editing.eq(0)]
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
                with m.If((page == 0) & (selected == self.TARGET_PRESET)):
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
                with m.Elif(selected == self.TARGET_CROSS_LAYOUT):
                    m.d.sync += cross_layout.eq(cross_layout_preview)
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
                with m.Elif(selected == self.TARGET_CROSS_LAYOUT):
                    m.d.sync += cross_layout_preview.eq(cross_layout)
                for n in range(RezoCore.N_BANDS):
                    with m.If(selected == self.TARGET_BAND_FREQ_BASE + n):
                        m.d.sync += frequency_preview.eq(band_frequencies[n])
                # Editing any immutable factory matrix starts USER from that
                # factory. The sixteen-register copy completes hundreds of
                # thousands of times faster than a human encoder detent.
                with m.If(cross_edit_target &
                          (cross_layout != RezoCore.CROSS_LAYOUT_GLOBAL) &
                          (cross_layout != RezoCore.CROSS_LAYOUT_USER)):
                    m.d.sync += [
                        cross_copy_active.eq(1),
                        cross_copy_index.eq(0),
                        cross_copy_layout.eq(cross_layout),
                        cross_layout.eq(RezoCore.CROSS_LAYOUT_USER),
                        editing.eq(0),
                    ]
                with m.Elif(cross_edit_target &
                            (cross_layout == RezoCore.CROSS_LAYOUT_GLOBAL)):
                    m.d.sync += editing.eq(0)
                with m.Else():
                    # Disabled BANK controls remain traversable, but cannot be
                    # entered or changed. This keeps silent parameters inert
                    # without putting an enable-mask search on the already
                    # dense navigation path.
                    m.d.sync += editing.eq(bank_band_enabled)
                # The first edit detent is always precise. Subsequent detents
                # accelerate only if they arrive in a rapid sequence.
                m.d.sync += detent_timer.eq((1 << 21) - 1)

        # One detent changes a continuous control by 1/128 of its nominal
        # unipolar span (and 1/128 of a band's bipolar span).  The DSP and CV
        # paths retain their full underlying 16-bit precision.
        step_amount = 1
        with m.If(edit_step & ~click):
            with m.If(~editing):
                m.d.sync += selected.eq(next_selected)
            with m.Else():
                with m.If((page == 0) & (selected == self.TARGET_PRESET)):
                    m.d.sync += preset.eq(next_preset)
                with m.Elif(selected == self.TARGET_PAGE):
                    # Main -> bands -> inputs -> groups -> outputs ->
                    # feedback -> cross matrix -> options.
                    with m.If(edit_direction):
                        with m.Switch(page):
                            with m.Case(0): m.d.sync += page.eq(6)
                            with m.Case(6): m.d.sync += page.eq(2)
                            with m.Case(2): m.d.sync += page.eq(3)
                            with m.Case(3): m.d.sync += page.eq(4)
                            with m.Case(4): m.d.sync += page.eq(1)
                            with m.Case(1): m.d.sync += page.eq(7)
                            with m.Case(7): m.d.sync += page.eq(5)
                            with m.Default(): m.d.sync += page.eq(0)
                    with m.Else():
                        with m.Switch(page):
                            with m.Case(0): m.d.sync += page.eq(5)
                            with m.Case(5): m.d.sync += page.eq(7)
                            with m.Case(7): m.d.sync += page.eq(1)
                            with m.Case(1): m.d.sync += page.eq(4)
                            with m.Case(4): m.d.sync += page.eq(3)
                            with m.Case(3): m.d.sync += page.eq(2)
                            with m.Case(2): m.d.sync += page.eq(6)
                            with m.Default(): m.d.sync += page.eq(0)
                with m.Elif(selected == self.TARGET_BAND_LAYOUT):
                    with m.If(edit_direction):
                        m.d.sync += layout_preview.eq(layout_preview + 1)
                    with m.Else():
                        m.d.sync += layout_preview.eq(layout_preview - 1)
                with m.Elif(selected == self.TARGET_CROSS_LAYOUT):
                    with m.If(edit_direction):
                        m.d.sync += cross_layout_preview.eq(Mux(
                            cross_layout_preview == RezoCore.CROSS_LAYOUT_USER,
                            RezoCore.CROSS_LAYOUT_GLOBAL,
                            cross_layout_preview + 1))
                    with m.Else():
                        m.d.sync += cross_layout_preview.eq(Mux(
                            cross_layout_preview == RezoCore.CROSS_LAYOUT_GLOBAL,
                            RezoCore.CROSS_LAYOUT_USER,
                            cross_layout_preview - 1))
                with m.Elif((page == 5) &
                            (selected == self.TARGET_CROSS_CURVE)):
                    with m.If(edit_direction):
                        m.d.sync += cross_curve.eq(cross_curve + 1)
                    with m.Else():
                        m.d.sync += cross_curve.eq(cross_curve - 1)
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
                with m.Elif(selected == self.TARGET_PALETTE):
                    with m.If(edit_direction):
                        m.d.sync += palette.eq(Mux(palette == 4, 0, palette + 1))
                    with m.Else():
                        m.d.sync += palette.eq(Mux(palette == 0, 4, palette - 1))
                with m.Elif(selected == self.TARGET_MOTION_SOURCE):
                    with m.If(edit_direction):
                        m.d.sync += motion_source.eq(Mux(
                            motion_source == 2, 0, motion_source + 1))
                    with m.Else():
                        m.d.sync += motion_source.eq(Mux(
                            motion_source == 0, 2, motion_source - 1))
                with m.Elif(selected == self.TARGET_MOTION_RATE):
                    with m.If(edit_direction):
                        self.clamp_add(m, motion_rate,
                                       accelerated_edit_step, 1, 200)
                    with m.Else():
                        self.clamp_add(m, motion_rate,
                                       -accelerated_edit_step, 1, 200)
                with m.Elif(selected == self.TARGET_MOTION_PHASE):
                    with m.If(edit_direction):
                        self.clamp_add(m, motion_phase,
                                       accelerated_edit_step, 0, 255)
                    with m.Else():
                        self.clamp_add(m, motion_phase,
                                       -accelerated_edit_step, 0, 255)
                with m.Elif((page == 6) &
                            (selected == self.TARGET_MOTION_DEPTH)):
                    with m.If(edit_direction):
                        self.clamp_add(m, motion_depth, 1, 0, 128)
                    with m.Else():
                        self.clamp_add(m, motion_depth, -1, 0, 128)
                with m.Elif(output_row_target):
                    m.d.sync += [
                        output_relative_active.eq(1),
                        output_relative_step.eq(0),
                        # Cat(g, g) is exactly 5*g without an adder tree.
                        output_relative_index.eq(Cat(
                            cross_relative_group, cross_relative_group)),
                        output_relative_column.eq(0),
                        output_relative_direction.eq(edit_direction),
                    ]
                with m.Elif(output_col_target):
                    m.d.sync += [
                        output_relative_active.eq(1),
                        output_relative_step.eq(0),
                        output_relative_index.eq(Mux(
                            selected == self.TARGET_OUTPUT_DRY_COL, 4,
                            cross_relative_group)),
                        output_relative_column.eq(1),
                        output_relative_direction.eq(edit_direction),
                    ]
                with m.Elif(output_cell_target):
                    # Capture this edit and perform the dynamic write on the
                    # following control tick. This keeps the wide Array mux
                    # out of the already-large selected/edit priority path
                    # without paying for twenty parallel write decoders.
                    m.d.sync += [
                        output_edit_pending.eq(1),
                        output_edit_index.eq(selected - self.TARGET_OUTPUT_BASE),
                        output_edit_direction.eq(edit_direction),
                    ]
                with m.Elif(cross_matrix_target):
                    m.d.comb += [
                        cross_direct_write.eq(1),
                        cross_direct_index.eq(selected[:4]),
                        cross_direct_direction.eq(edit_direction),
                    ]
                with m.Elif(cross_row_target):
                    m.d.sync += [
                        cross_relative_active.eq(1),
                        cross_relative_step.eq(0),
                        cross_relative_column.eq(0),
                        cross_relative_direction.eq(edit_direction),
                    ]
                with m.Elif(cross_col_target):
                    m.d.sync += [
                        cross_relative_active.eq(1),
                        cross_relative_step.eq(0),
                        cross_relative_column.eq(1),
                        cross_relative_direction.eq(edit_direction),
                    ]
                with m.Elif(selected == self.TARGET_RESONANCE):
                    with m.If(edit_direction):
                        self.clamp_add(m, resonance, step_amount, 0, 128)
                    with m.Else():
                        self.clamp_add(m, resonance, -step_amount, 0, 128)
                with m.Elif(selected == self.TARGET_DRIVE):
                    with m.If(edit_direction):
                        self.clamp_add(m, bank_drive, step_amount, 0, 96)
                    with m.Else():
                        self.clamp_add(m, bank_drive, -step_amount, 0, 96)
                with m.Elif(selected == self.TARGET_FEEDBACK):
                    with m.If(edit_direction):
                        self.clamp_add(m, feedback, step_amount, 0, 128)
                    with m.Else():
                        self.clamp_add(m, feedback, -step_amount, 0, 128)
                with m.Elif(selected == self.TARGET_CROSS_FEEDBACK):
                    with m.If(edit_direction):
                        self.clamp_add(m, cross_feedback, 1, 0,
                                       RezoCore.CROSS_DEPTH_MAX)
                    with m.Else():
                        self.clamp_add(m, cross_feedback, -1, 0,
                                       RezoCore.CROSS_DEPTH_MAX)
                with m.Elif(selected == self.TARGET_SAME_FEEDBACK):
                    with m.If(edit_direction):
                        self.clamp_add(m, same_feedback_reduction, -1, 0,
                                       RezoCore.CROSS_DEPTH_MAX)
                    with m.Else():
                        self.clamp_add(m, same_feedback_reduction, 1, 0,
                                       RezoCore.CROSS_DEPTH_MAX)
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
                        with m.If(edit_direction):
                            m.d.sync += input_modes[n].eq(Mux(
                                input_modes[n] == RezoCore.INPUT_MODE_CV,
                                RezoCore.INPUT_MODE_LEFT,
                                input_modes[n] + 1))
                        with m.Else():
                            m.d.sync += input_modes[n].eq(Mux(
                                input_modes[n] == RezoCore.INPUT_MODE_LEFT,
                                RezoCore.INPUT_MODE_CV,
                                input_modes[n] - 1))
                    with m.Elif(selected == self.TARGET_INPUT_BASE + n * 3 + 1):
                        with m.If(input_modes[n] != RezoCore.INPUT_MODE_CV):
                            input_gain_coarse = input_gains[n][8:16]
                            with m.If(edit_direction):
                                self.clamp_add(m, input_gain_coarse,
                                               1, 0, 255)
                            with m.Else():
                                self.clamp_add(m, input_gain_coarse,
                                               -1, 0, 255)
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
                            self.clamp_add(m, cv_depth_coarse,
                                           1, -128, 127)
                        with m.Else():
                            self.clamp_add(m, cv_depth_coarse,
                                           -1, -128, 127)
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
            output_edit_send = Array(bank_output_sends)[output_edit_index]
            with m.If(output_edit_direction):
                self.clamp_add(m, output_edit_send, 1, 0, 16)
            with m.Else():
                self.clamp_add(m, output_edit_send, -1, 0, 16)

        # Factory copying, one-cell edits, and relative header edits share a
        # single dynamic write decoder. Three independent Array assignments
        # otherwise synthesize into three large mux trees on this small ECP5.
        cross_write_en = Signal()
        cross_write_index = Signal(unsigned(4))
        cross_write_direction = Signal()
        m.d.comb += [
            cross_write_en.eq(
                cross_copy_active | cross_relative_active |
                cross_direct_write),
            cross_write_index.eq(Mux(
                cross_copy_active, cross_copy_index,
                Mux(cross_relative_active, cross_relative_index,
                    cross_direct_index))),
            cross_write_direction.eq(Mux(
                cross_relative_active, cross_relative_direction,
                cross_direct_direction)),
        ]
        for matrix_index, matrix_send in enumerate(cross_matrix):
            with m.If(cross_write_en &
                      (cross_write_index == matrix_index)):
                with m.If(cross_copy_active):
                    m.d.sync += matrix_send.eq(cross_copy_value)
                with m.Elif(cross_write_direction):
                    # Valid values are 0..16, so bit 4 alone identifies the
                    # upper endpoint and avoids a five-bit comparator/mux.
                    m.d.sync += matrix_send.eq(
                        matrix_send + ~matrix_send[4])
                with m.Else():
                    m.d.sync += matrix_send.eq(
                        matrix_send - matrix_send.any())

        # Packed 16-bit state scan port, sampled sequentially by the journal.
        # Preserve the complete V4 prefix verbatim, including its two padding
        # bits, so a validated 36-word record can migrate by appending only
        # two default tail words. V5 adds all four static motion controls;
        # oscillator phase and LFSR evolution remain intentionally unsaved.
        level_bytes = Cat(*(level.as_unsigned() for level in levels))
        cv_depth_bytes = Cat(*(value[8:16] for value in cv_depths))
        input_config_bits = Cat(*input_modes, *cv_targets)
        bank_group_bits = Cat(*bank_group_indices)
        feedback_preset_bits = Cat(*feedback_sends, preset, palette)
        output_send_bits = Cat(*bank_output_sends, *output_sides)
        band_config_bits = Cat(
            *band_frequencies, *band_enables, frequency_layout)
        cross_matrix_bits = Cat(
            cross_layout, *cross_matrix, same_feedback_reduction[:5],
            cross_feedback[:5])
        # V4/V5 reserved these two bits as zero. Reusing one makes old saves
        # load LINEAR without growing or versioning the compact record.
        # The packed state is a circular stream. This temporal interface costs
        # one local shift mux per retained bit instead of a 42-way read mux and
        # a separate 42-way restore decoder. A complete SAVE rotation returns
        # every live register to its original location; LOAD replaces the
        # trailing word on each shift with validated journal data.
        state_bits = Cat(
            level_bytes,
            bank_drive,
            resonance, feedback,
            limit_knee, limit_cap, damp_mode,
            *input_gains,
            cv_depth_bytes,
            input_config_bits,
            bank_group_bits,
            feedback_preset_bits,
            output_send_bits,
            band_config_bits,
            cross_matrix_bits,
            cross_curve,
            cross_curve_pad,
            motion_source, motion_rate, motion_phase, motion_depth,
            same_feedback_reduction[5:8], cross_feedback[5:8],
        )
        assert len(state_bits) == self.STATE_WORDS_V5 * 16
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
        for n, output_route in enumerate(output_routes):
            m.d.comb += self.output_routes[n].eq(output_route)
        for n, output_side in enumerate(output_sides):
            m.d.comb += self.output_sides[n].eq(output_side)
        for n, output_send in enumerate(output_sends):
            m.d.comb += self.output_sends[n].eq(output_send)
        for n, matrix_send in enumerate(cross_matrix):
            m.d.comb += self.cross_matrix[n].eq(matrix_send)
        m.d.comb += [
            self.drive.eq(drive),
            self.resonance.eq(resonance << 8),
            self.feedback.eq(feedback << 8),
            self.same_feedback.eq(same_feedback),
            self.cross_feedback.eq(cross_feedback),
            self.cross_curve.eq(cross_curve),
            self.cross_layout.eq(cross_layout),
            self.cross_layout_preview.eq(cross_layout_preview),
            self.limit_knee.eq(limit_knee << 8),
            self.limit_cap.eq(limit_cap << 8),
            self.damp_mode.eq(damp_mode),
            self.motion_source.eq(motion_source),
            self.motion_rate.eq(motion_rate),
            self.motion_phase.eq(motion_phase),
            self.motion_depth.eq(motion_depth),
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
        ".": [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b01100, 0b01100],
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
            "same_feedback": In(unsigned(8)),
            "cross_feedback": In(unsigned(8)),
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
        # Rendering is clipped to a 720x720 panel before these local
        # coordinates reach the pixel output. Keep them at their natural
        # unsigned width: the former signed 12-bit shape widened every
        # rectangle/outline comparator into an unnecessary carry chain.
        x = Signal(unsigned(10))
        y = Signal(unsigned(10))
        active = Signal()
        m.d.comb += [
            x.eq(sx - self.x_offset),
            y.eq(sy),
            active.eq(self.de & (sx >= self.x_offset) &
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
            self.fixed_text_pixel(m, x, y, "STREZO", 36, 28, scale_shift=2,
                                  name="lcd_strezo"),
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

    CHARS = " 0123456789.ABCDEFGHIJKLMNOPQRSTUVWXYZ"
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
            "same_feedback": In(unsigned(8)),
            "cross_feedback": In(unsigned(8)),
            "cross_curve": In(1),
            "cross_layout": In(unsigned(3)),
            "cross_layout_preview": In(unsigned(3)),
            "limit_knee": In(unsigned(8)),
            "limit_cap": In(unsigned(8)),
            "damp_mode": In(unsigned(3)),
            "motion_source": In(unsigned(2)),
            "motion_rate": In(unsigned(8)),
            "motion_phase": In(unsigned(8)),
            "motion_depth": In(unsigned(8)),
            "motion_monitor": In(signed(6)),
            "input_gains": In(data.ArrayLayout(unsigned(8), 4)),
            "input_modes": In(data.ArrayLayout(unsigned(2), 4)),
            "cv_targets": In(data.ArrayLayout(unsigned(3), 4)),
            "cv_depths": In(data.ArrayLayout(signed(8), 4)),
            "input_meters": In(data.ArrayLayout(signed(6), 4)),
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
            "output_routes": In(data.ArrayLayout(unsigned(5), 4)),
            "output_sides": In(data.ArrayLayout(unsigned(1), 4)),
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
    def bipolar_line(cls, x, y, center, endpoint, y0, y1, negative):
        """Render a center-to-value bipolar telemetry line."""
        return Mux(
            ~negative,
            cls.rect(x, y, center, y0, endpoint, y1),
            cls.rect(x, y, endpoint, y0, center, y1))

    @classmethod
    def outline(cls, x, y, x0, y0, x1, y1, t=2):
        return cls.rect(x, y, x0, y0, x1, y1) & (
            (x < x0 + t) | (x >= x1 - t) | (y < y0 + t) | (y >= y1 - t))

    def elaborate(self, platform):
        m = Module()

        sx = self.x
        sy = self.y
        # Author one upright native 720x720 canvas. The standard target adds
        # only its 280px horizontal preview offset; the official panel applies
        # its mount correction here, before any page geometry is evaluated.
        ui_x = Signal(signed(11))
        ui_y = Signal(signed(11))
        x = Signal(range(self.PANEL_W))
        y = Signal(range(self.PANEL_H))
        active = Signal()
        if self.rotate_left:
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
            # Match the accepted REZO-family renderer latency. Geometry and
            # text consume the same final native coordinate; there is no
            # 720-to-508 resampling table in this path.
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

        # Display scaling used to duplicate magnitude, shift/add scaling, and
        # endpoint arithmetic for all ten bands. Pixels only consume the
        # registered endpoints, so scan one band per DVI clock through a
        # dual-port lookup instead. A complete refresh takes ten clocks
        # (about 0.14 us at 74.25 MHz) and does not touch the audio datapath.
        band_height_init = []
        for raw_level in range(256):
            signed_level = raw_level if raw_level < 128 else raw_level - 256
            # Preserve the former seven-bit magnitude behavior, including
            # the signed -128 endpoint wrapping to zero.
            magnitude = abs(signed_level) & 0x7f
            if self.compact_layout:
                height_value = (magnitude + (magnitude >> 2) +
                                (magnitude >> 3) + (magnitude >> 5))
            else:
                height_value = ((magnitude << 1) + (magnitude >> 1) +
                                (0 if signed_level < 0 else magnitude >> 3))
            band_height_init.append(
                height_value | ((signed_level > 0) << 9) |
                ((signed_level < 0) << 10))
        m.submodules.band_height_mem = band_height_mem = Memory(
            shape=unsigned(11), depth=256, init=band_height_init,
            attrs={"ram_style": "block"})
        band_effective_height_rport = band_height_mem.read_port(domain="dvi")
        band_base_height_rport = band_height_mem.read_port(domain="dvi")
        band_scan_index = Signal(range(RezoCore.N_BANDS))
        band_write_index = Signal.like(band_scan_index)
        m.d.comb += [
            band_effective_height_rport.addr.eq(
                Array(self.effective_levels)[band_scan_index].as_unsigned()),
            band_base_height_rport.addr.eq(
                Array(self.levels)[band_scan_index].as_unsigned()),
        ]
        with m.If(band_scan_index == RezoCore.N_BANDS - 1):
            m.d.dvi += band_scan_index.eq(0)
        with m.Else():
            m.d.dvi += band_scan_index.eq(band_scan_index + 1)
        m.d.dvi += band_write_index.eq(band_scan_index)

        effective_height = band_effective_height_rport.data[:9]
        base_height = band_base_height_rport.data[:9]
        next_band_top = Signal(signed(12))
        next_band_bottom = Signal(signed(12))
        next_base_marker = Signal(signed(12))
        m.d.comb += [
            next_band_top.eq(zero_y - effective_height),
            next_band_bottom.eq(zero_y + effective_height),
            next_base_marker.eq(Mux(
                band_base_height_rport.data[10],
                zero_y + base_height, zero_y - base_height)),
        ]
        with m.Switch(band_write_index):
            for n in range(RezoCore.N_BANDS):
                with m.Case(n):
                    m.d.dvi += [
                        band_top_values[n].eq(next_band_top),
                        band_bottom_values[n].eq(next_band_bottom),
                        band_base_marker_values[n].eq(next_base_marker),
                        band_positive_values[n].eq(
                            band_effective_height_rport.data[9]),
                        band_negative_values[n].eq(
                            band_effective_height_rport.data[10]),
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
        tune_page = Signal()
        input_page = Signal()
        group_page = Signal()
        output_page = Signal()
        advanced_page = Signal()
        bands_page = Signal()
        cross_page = Signal()
        # Page/mode selection changes at human speed. Register the decoded
        # flags in the pixel domain so every geometry path starts from a local
        # one-bit control rather than repeating the page comparison inside the
        # densely packed renderer.
        m.d.dvi += [
            home_page.eq(self.page == 0),
            bank_page.eq(self.page == 0),
            tune_page.eq(self.page == 1),
            input_page.eq(self.page == 2),
            group_page.eq(self.page == 3),
            output_page.eq(self.page == 4),
            advanced_page.eq(self.page == 5),
            bands_page.eq(self.page == 6),
            cross_page.eq(self.page == 7),
        ]
        page_cells = 45 * 45
        text_init = [0] * (8 * page_cells)

        def put(page, text_value, x0, y0):
            for offset, ch in enumerate(text_value):
                if 0 <= x0 + offset < 45 and 0 <= y0 < 45:
                    text_init[page * page_cells + y0 * 45 + x0 + offset] = self.code(ch)

        def put_native(page, text_value, x0, y0):
            """Place text directly on the native 16px character grid."""
            put(page, text_value, x0, y0)

        page_titles = ("BANK", "FEEDBACK", "INPUT", "GROUPS", "OUTPUT",
                       "OPTIONS", "BANDS", "CROSS")
        compact_input_text_rows = (
            (14, 16, 18), (20, 22, 24),
            (26, 28, 30), (32, 34, 36))
        compact_group_text_rows = (20, 23, 26, 29)
        compact_group_centers = tuple(
            row * 16 + 6 for row in compact_group_text_rows)
        compact_output_text_rows = (21, 25, 29, 33)
        compact_output_row_centers = tuple(
            row * 16 + 6 for row in compact_output_text_rows)
        compact_output_col_centers = (
            16 * 16 + 14, 20 * 16 + 14, 24 * 16 + 14,
            28 * 16 + 14, 32 * 16 + 22)
        # CROSS has only four columns, so it can use the full panel width and
        # sit higher than OUTPUT's five-column matrix. Keep these values
        # separate to preserve OUTPUT's established composition.
        compact_cross_text_rows = (20, 24, 28, 32)
        compact_cross_row_centers = tuple(
            row * 16 + 6 for row in compact_cross_text_rows)
        compact_cross_col_centers = (254, 334, 414, 494)
        compact_main_control_text_rows = (28, 30, 32)
        compact_main_control_y0s = (448, 480, 512)

        if self.compact_layout:
            for page_number, title in enumerate(page_titles):
                put_native(page_number, "STREZO", 19, 2)
                put_native(page_number, "PAGE", 8, 8)
                put_native(page_number, title,
                           14 + ((8 - len(title)) // 2), 8)

            put_native(0, "PRESET", 8, 11)
            put_native(0, "BANDS", 8, 14)
            put_native(0, "FREQ:", 23, 14)
            put_native(0, "DRIVE", 12, compact_main_control_text_rows[0])
            put_native(0, "RESONANCE", 8, compact_main_control_text_rows[1])
            put_native(0, "FEEDBACK", 9, compact_main_control_text_rows[2])

            put_native(1, "FEEDBACK SOURCES", 8, 13)
            put_native(1, "BANDS", 8, 16)
            put_native(1, "FREQ:", 23, 16)
            put_native(1, "FEEDBACK SAFETY", 8, 22)
            put_native(1, "KNEE", 12, 25)
            put_native(1, "CEILING", 9, 27)
            put_native(1, "DAMPING", 9, 29)

            put_native(2, "INPUT ROUTING", 8, 12)
            for n, (mode_row, value_row, depth_row) in enumerate(
                    compact_input_text_rows):
                put_native(2, f"IN{n}", 8, mode_row)
                put_native(2, "MODE", 14, mode_row)
                put_native(2, "VALUE", 13, value_row)
                put_native(2, "DEPTH", 13, depth_row)

            put_native(3, "BANK GROUPS", 8, 13)
            put_native(3, "BANKS", 20, 16)
            for group, row in enumerate(compact_group_text_rows):
                put_native(3, f"GRP{group + 1}", 8, row)

            put_native(4, "OUTPUT ROUTING", 8, 13)
            for x0, label in zip((16, 20, 24, 28, 32),
                                 ("G1", "G2", "G3", "G4", "DRY")):
                put_native(4, label, x0, 18)
            for n, row in enumerate(compact_output_text_rows):
                put_native(4, f"OUT{n}", 9, row)

            put_native(5, "STATE AND DISPLAY", 8, 13)
            put_native(5, "PALETTE", 13, 17)
            put_native(5, "SAVE DEFAULT", 8, 21)
            put_native(5, "ADVANCED", 8, 27)
            put_native(5, "CROSS CURVE", 8, 31)

            put_native(6, "PRESET", 8, 11)
            put_native(6, "ENABLE", 8, 16)
            put_native(6, "SET FREQ", 8, 22)
            put_native(6, "HZ", 26, 22)
            put_native(6, "MOTION", 8, 27)
            put_native(6, "LFO SHAPE", 8, 29)
            put_native(6, "RATE HZ", 8, 31)
            put_native(6, "PHASE", 8, 33)
            put_native(6, "DEPTH", 8, 35)

            put_native(7, "LAYOUT", 8, 11)
            put_native(7, "TO", 15, 15)
            put_native(7, "FROM", 8, 18)
            for group, row in enumerate(compact_cross_text_rows):
                put_native(7, f"G{group + 1}", 10, row)
                put_native(7, f"G{group + 1}", 15 + group * 5, 17)
            put_native(7, "SAME", 9, 34)
            put_native(7, "CROSS", 8, 36)
        else:
            for page_number, title in enumerate(page_titles):
                put(page_number, "STREZO", 2, 3)
                title_x = 29 + max(0, (8 - len(title)) // 2)
                put(page_number, title, title_x, 3)
            put(0, "PRESET", 2, 7)
            put(0, "BANDS", 2, 11)
            put(0, "FREQ:", 18, 11)
            put(0, "DRIVE", 2, 35)
            put(0, "RES", 2, 37)
            put(0, "FB", 2, 39)
            put(1, "FEEDBACK SOURCES", 2, 8)
            put(1, "BANDS", 2, 11)
            put(1, "FREQ:", 18, 11)
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
            for source, label in enumerate(
                    ("GRP1", "GRP2", "GRP3", "GRP4", "DRY")):
                put(4, label, 12 + source * 6, 17)
            for n in range(4):
                put(4, f"OUT{n}", 2, 21 + n * 5)
            put(5, "STATE AND DISPLAY", 2, 11)
            put(5, "PALETTE", 8, 15)
            put(5, "SAVE DEFAULT", 3, 19)
            put(5, "ADVANCED", 3, 25)
            put(5, "CROSS CURVE", 3, 29)
            put(6, "PRESET", 2, 7)
            put(6, "ENABLE", 2, 12)
            put(6, "SET FREQ", 2, 22)
            put(6, "HZ", 20, 22)
            put(6, "MOTION", 2, 30)
            put(6, "SOURCE", 2, 33)
            put(6, "RATE HZ", 2, 37)
            put(6, "PHASE", 23, 33)
            put(6, "DEPTH", 23, 37)
            put(7, "LAYOUT", 2, 7)
            put(7, "TO", 9, 15)
            put(7, "FROM", 2, 18)
            for group in range(4):
                put(7, f"G{group + 1}", 12 + group * 6, 16)
                put(7, f"G{group + 1}", 5, 21 + group * 5)
            put(7, "SAME", 2, 39)
            put(7, "CROSS", 2, 41)
        m.submodules.text_mem = text_mem = Memory(
            shape=unsigned(6), depth=len(text_init), init=text_init)
        text_rport = text_mem.read_port(domain="dvi")
        text_wport = text_mem.write_port(domain="sync")
        page_offsets = Array(Const(page * page_cells, unsigned(14)) for page in range(8))
        text_address = Signal(unsigned(15))
        text_page_q = Signal(unsigned(3))
        m.d.dvi += text_page_q.eq(self.page)
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
        cross_layout_sync = self.cross_layout
        cross_layout_preview_sync = self.cross_layout_preview
        cross_curve_sync = self.cross_curve
        band_frequencies_sync = self.band_frequencies
        input_modes_sync = [Signal(unsigned(2), name=f"text_input_mode{n}")
                            for n in range(4)]
        cv_targets_sync = [Signal(unsigned(3), name=f"text_cv_target{n}") for n in range(4)]
        output_sides_sync = [Signal(name=f"text_output_side{n}")
                             for n in range(4)]
        m.submodules += [
            FFSynchronizer(self.page, page_sync),
            FFSynchronizer(self.preset, preset_sync),
            FFSynchronizer(self.selected, selected_sync),
            FFSynchronizer(self.editing, editing_sync),
            FFSynchronizer(self.palette, palette_sync),
            FFSynchronizer(self.damp_mode, damp_mode_sync),
            FFSynchronizer(self.save_default_available, save_available_sync),
            FFSynchronizer(self.save_default_busy, save_busy_sync),
            FFSynchronizer(self.save_default_status, save_status_sync),
        ]
        for n in range(4):
            m.submodules += FFSynchronizer(self.input_modes[n], input_modes_sync[n])
            m.submodules += FFSynchronizer(self.cv_targets[n], cv_targets_sync[n])
            m.submodules += FFSynchronizer(self.output_sides[n], output_sides_sync[n])

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

        update_index = Signal(range(107))
        update_active = Signal(init=1)
        refresh_counter = Signal(range(4_000_000))
        writer_address = Signal(unsigned(15))
        writer_char = Signal(unsigned(6))
        writer_index_q = Signal.like(update_index)
        writer_page_q = Signal.like(page_sync)
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
            writer_page_q.eq(page_sync),
            writer_char_q.eq(writer_char),
            writer_valid_q.eq(update_active),
        ]
        with m.If(selected_band_valid):
            m.d.comb += selected_band.eq(
                selected_sync - RezoHardwareUI.TARGET_BAND_BASE)

        # These fixed-width strings are padded per visible name so the text is
        # centered inside the shared BANK selector rather than left-aligned.
        preset_names = ("ALL ", "ODD ", "EVEN", "LOW ", "MID ", " HI ", "ZERO")
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
        # Return one character directly from BRAM.  Storing each label in an
        # eight-character slot makes the address a shift plus bitwise OR and
        # avoids wide-word character muxes in the display logic.
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
        cross_layout_names = (
            " GLOBAL ", "DIAGONAL", " ROTATE ",
            " MIRROR ", "  ALL   ", "  USER  ")
        cross_layout_chars = [
            Array(Const(self.code(name[pos]), 6)
                  for name in cross_layout_names)
            for pos in range(8)
        ]
        cross_curve_names = (" LINEAR ", "  LOG   ")
        cross_curve_chars = [
            Array(Const(self.code(name[pos]), 6)
                  for name in cross_curve_names)
            for pos in range(8)
        ]
        displayed_cross_layout = Signal(unsigned(3))
        m.d.comb += displayed_cross_layout.eq(Mux(
            editing_sync &
            (selected_sync == RezoHardwareUI.TARGET_CROSS_LAYOUT),
            cross_layout_preview_sync, cross_layout_sync))
        target_chars = [Array(Const(self.code(name[pos]), 6) for name in target_names)
                        for pos in range(3)]
        palette_names = ("  LCD ", " AMBER", " CYAN ", " GREEN", "VIOLET")
        palette_chars = [Array(Const(self.code(name[pos]), 6)
                               for name in palette_names)
                         for pos in range(6)]
        damp_names = (" OFF ", "LIGHT", " MED ", "HEAVY", " MAX ")
        damp_chars = [Array(Const(self.code(name[pos]), 6)
                            for name in damp_names)
                      for pos in range(5)]
        damp_name_index = Signal(range(5))
        m.d.comb += damp_name_index.eq(Mux(
            damp_mode_sync > 4, 4, damp_mode_sync))
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
        motion_source_names = ("  OFF   ", "TRIANGLE", " RANDOM ")
        # One compact label ROM converts the continuous 0.1 Hz rate to text
        # without synthesizing a decimal divider into the control domain.
        motion_source_offset = 896
        motion_phase_blank_offset = 880
        motion_phase_offset = 1024
        motion_label_init = [0] * 2048
        for value in range(256):
            rate = min(value, 200)
            rate_text = f"{rate // 10:2d}.{rate % 10}"[-4:]
            for pos in range(4):
                motion_label_init[(value << 2) | pos] = self.code(
                    rate_text[pos])
        # RATE is constrained to 0..200, leaving its 224..229 slots available
        # for the three eight-character source names. Reuse the rate read port
        # while those characters are refreshed instead of building eight
        # independent three-way character muxes.
        for source, name in enumerate(motion_source_names):
            for pos, char in enumerate(name):
                motion_label_init[
                    motion_source_offset | (source << 3) | pos
                ] = self.code(char)
        for pos in range(4):
            motion_label_init[motion_phase_blank_offset | pos] = 0
        for value in range(256):
            degrees = round(value * 360 / 256)
            phase_text = f"{degrees:3d} "[-4:]
            for pos in range(4):
                motion_label_init[
                    motion_phase_offset | (value << 2) | pos
                ] = self.code(phase_text[pos])
        m.submodules.motion_label_mem = motion_label_mem = Memory(
            shape=unsigned(6), depth=len(motion_label_init),
            init=motion_label_init,
            attrs={"ram_style": "block"})
        motion_rate_rport = motion_label_mem.read_port()
        motion_phase_rport = motion_label_mem.read_port()
        motion_phase_base = Signal(unsigned(11), init=motion_phase_offset)
        m.d.sync += motion_phase_base.eq(Mux(
            self.motion_source[1], motion_phase_blank_offset,
            motion_phase_offset | (self.motion_phase << 2)))
        m.d.comb += [
            motion_rate_rport.addr.eq(self.motion_rate << 2),
            motion_phase_rport.addr.eq(motion_phase_base),
        ]
        with m.Switch(update_index):
            for pos in range(8):
                with m.Case(82 + pos):
                    m.d.comb += motion_rate_rport.addr.eq(
                        motion_source_offset |
                        (self.motion_source << 3) | pos)
            for pos in range(4):
                with m.Case(90 + pos):
                    m.d.comb += motion_rate_rport.addr.eq(
                        (self.motion_rate << 2) | pos)
                with m.Case(94 + pos):
                    m.d.comb += motion_phase_rport.addr.eq(
                        motion_phase_base | pos)

        # Most text destinations are fixed.  Keep their addresses in one
        # DP16KD instead of synthesizing a 96-way, 15-bit address mux.  The
        # first four NAV/EDIT cells follow the active page and remain the only
        # dynamically calculated destinations.
        writer_address_init = [0] * 128
        def writer_cell(page, x0, y0, offset=0):
            return page * page_cells + y0 * 45 + x0 + offset

        if self.compact_layout:
            for pos in range(4):
                writer_address_init[4 + pos] = writer_cell(0, 16, 11, pos)
            for pos in range(3):
                writer_address_init[8 + pos] = writer_cell(0, 29, 14, pos)
            for n, (mode_row, value_row, _) in enumerate(
                    compact_input_text_rows):
                for pos in range(3):
                    writer_address_init[11 + n * 3 + pos] = writer_cell(
                        2, 21, mode_row, pos)
                    writer_address_init[23 + n * 3 + pos] = writer_cell(
                        2, 20, value_row, pos)
            for pos in range(5):
                writer_address_init[35 + pos] = writer_cell(1, 18, 29, pos)
            for pos in range(3):
                writer_address_init[43 + pos] = writer_cell(1, 29, 16, pos)
            for pos in range(6):
                writer_address_init[46 + pos] = writer_cell(5, 22, 17, pos)
            for pos in range(7):
                writer_address_init[52 + pos] = writer_cell(5, 22, 21, pos)
                writer_address_init[59 + pos] = writer_cell(6, 16, 11, pos)
            for pos in range(5):
                writer_address_init[66 + pos] = writer_cell(6, 20, 22, pos)
            for n, row in enumerate(compact_output_text_rows):
                writer_address_init[71 + n] = writer_cell(4, 13, row)
            for pos in range(8):
                writer_address_init[75 + pos] = writer_cell(7, 16, 11, pos)
            for pos in range(8):
                writer_address_init[83 + pos] = writer_cell(6, 18, 29, pos)
            for pos in range(4):
                writer_address_init[91 + pos] = writer_cell(6, 18, 31, pos)
                writer_address_init[95 + pos] = writer_cell(6, 18, 33, pos)
            for pos in range(8):
                writer_address_init[99 + pos] = writer_cell(5, 20, 31, pos)
        else:
            for pos in range(4):
                writer_address_init[4 + pos] = writer_cell(0, 11, 7, pos)
            for pos in range(3):
                writer_address_init[8 + pos] = writer_cell(0, 24, 11, pos)
            for n in range(4):
                row = 13 + n * 6
                for pos in range(3):
                    writer_address_init[11 + n * 3 + pos] = writer_cell(
                        2, 14, row, pos)
                    writer_address_init[23 + n * 3 + pos] = writer_cell(
                        2, 16, row + 2, pos)
            for pos in range(5):
                writer_address_init[35 + pos] = writer_cell(1, 12, 32, pos)
            for pos in range(3):
                writer_address_init[43 + pos] = writer_cell(1, 24, 11, pos)
            for pos in range(6):
                writer_address_init[46 + pos] = writer_cell(5, 18, 15, pos)
            for pos in range(7):
                writer_address_init[52 + pos] = writer_cell(5, 18, 19, pos)
                writer_address_init[59 + pos] = writer_cell(6, 9, 7, pos)
            for pos in range(5):
                writer_address_init[66 + pos] = writer_cell(6, 14, 22, pos)
            for n in range(4):
                writer_address_init[71 + n] = writer_cell(
                    4, 7, 21 + n * 5)
            for pos in range(8):
                writer_address_init[75 + pos] = writer_cell(7, 10, 7, pos)
            for pos in range(8):
                writer_address_init[83 + pos] = writer_cell(6, 10, 33, pos)
            for pos in range(4):
                writer_address_init[91 + pos] = writer_cell(6, 12, 37, pos)
                writer_address_init[95 + pos] = writer_cell(6, 34, 33, pos)
            for pos in range(8):
                writer_address_init[99 + pos] = writer_cell(5, 20, 29, pos)
        m.submodules.writer_address_mem = writer_address_mem = Memory(
            shape=unsigned(15), depth=len(writer_address_init),
            init=writer_address_init, attrs={"ram_style": "block"})
        writer_address_rport = writer_address_mem.read_port()
        m.d.comb += [
            writer_address_rport.addr.eq(update_index),
            writer_address.eq(Mux(
                writer_index_q < 4,
                page_offsets[writer_page_q] +
                (8 if self.compact_layout else 3) * 45 +
                (33 if self.compact_layout else 39) + writer_index_q,
                writer_address_rport.data)),
        ]

        with m.Switch(update_index):
            for pos in range(4):
                with m.Case(pos):
                    m.d.comb += writer_char.eq(nav_chars[pos][editing_sync])
            for pos in range(4):
                with m.Case(4 + pos):
                    m.d.comb += writer_char.eq(preset_chars[pos][preset_sync])
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
                        mode_chars = Array((
                            Const(self.code(" L "[pos]), 6),
                            Const(self.code(" R "[pos]), 6),
                            Const(self.code("CV "[pos]), 6),
                        ))
                        m.d.comb += writer_char.eq(
                            mode_chars[input_modes_sync[n]])
                    with m.Case(23 + n * 3 + pos):
                        m.d.comb += writer_char.eq(Mux(
                            input_modes_sync[n] == RezoCore.INPUT_MODE_CV,
                            target_chars[pos][cv_targets_sync[n]], 0))
            for pos in range(5):
                with m.Case(35 + pos):
                    m.d.comb += writer_char.eq(
                        damp_chars[pos][damp_name_index])
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
            for n in range(4):
                with m.Case(71 + n):
                    side_chars = Array((Const(self.code("L"), 6),
                                        Const(self.code("R"), 6)))
                    m.d.comb += writer_char.eq(
                        side_chars[output_sides_sync[n]])
            for pos in range(8):
                with m.Case(75 + pos):
                    m.d.comb += writer_char.eq(
                        cross_layout_chars[pos][displayed_cross_layout])
            for pos in range(8):
                with m.Case(83 + pos):
                    m.d.comb += writer_char.eq(motion_rate_rport.data)
            for pos in range(4):
                with m.Case(91 + pos):
                    m.d.comb += writer_char.eq(motion_rate_rport.data)
                with m.Case(95 + pos):
                    m.d.comb += writer_char.eq(motion_phase_rport.data)
            for pos in range(8):
                with m.Case(99 + pos):
                    m.d.comb += writer_char.eq(
                        cross_curve_chars[pos][cross_curve_sync])
        with m.If(update_active):
            with m.If(update_index == 106):
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
        # One shared rectangle keeps the pixel path shallow. OPTIONS selects
        # a short lower field; all working pages use the taller field needed
        # by the matrix and fourth output row.
        content_y0 = Signal(
            unsigned(10), init=218 if self.compact_layout else 190)
        content_y1 = Signal(
            unsigned(10), init=575 if self.compact_layout else 666)
        m.d.dvi += [
            content_y0.eq(218 if self.compact_layout else 190),
            content_y1.eq(Mux(
                bands_page | cross_page,
                603 if self.compact_layout else 684,
                575 if self.compact_layout else 666)),
        ]
        normal_content_panel = self.rect(
            x, y, 125 if self.compact_layout else 28, content_y0,
            594 if self.compact_layout else 692, content_y1)
        options_content_panel = (
            self.rect(x, y,
                      125 if self.compact_layout else 28,
                      218 if self.compact_layout else 190,
                      594 if self.compact_layout else 692,
                      400 if self.compact_layout else 412) |
            self.rect(x, y,
                      125 if self.compact_layout else 28,
                      454 if self.compact_layout else 438,
                      594 if self.compact_layout else 692,
                      555 if self.compact_layout else 548))
        content_panel = active & Mux(
            advanced_page, options_content_panel, normal_content_panel)
        bank_control_y0s = (
            compact_main_control_y0s if self.compact_layout
            else (556, 588, 620))
        bank_panel_x0 = 283 if self.compact_layout else 118
        bank_panel_x1 = 594 if self.compact_layout else 650
        meter_panel = active & (
            (bank_page & (
                self.rect(x, y, bank_panel_x0, bank_control_y0s[0] - 2,
                          bank_panel_x1, bank_control_y0s[0] + 18) |
                self.rect(x, y, bank_panel_x0, bank_control_y0s[1] - 2,
                          bank_panel_x1, bank_control_y0s[1] + 18) |
                self.rect(x, y, bank_panel_x0, bank_control_y0s[2] - 2,
                          bank_panel_x1, bank_control_y0s[2] + 18))) |
            (tune_page & (
                self.rect(x, y, 268 if self.compact_layout else 150,
                          398 if self.compact_layout else 408,
                          588 if self.compact_layout else 650,
                          418 if self.compact_layout else 432) |
                self.rect(x, y, 268 if self.compact_layout else 150,
                          430 if self.compact_layout else 456,
                          588 if self.compact_layout else 650,
                          450 if self.compact_layout else 480))) |
            (cross_page & (
                self.rect(x, y, 232 if self.compact_layout else 118,
                          542 if self.compact_layout else 616,
                          580 if self.compact_layout else 650,
                          562 if self.compact_layout else 640) |
                self.rect(x, y, 232 if self.compact_layout else 118,
                          574 if self.compact_layout else 648,
                          580 if self.compact_layout else 650,
                          594 if self.compact_layout else 672))))
        palette_chip = advanced_page & self.rect(
            x, y, 344 if self.compact_layout else 264,
            260 if self.compact_layout else 228,
            456 if self.compact_layout else 408,
            300 if self.compact_layout else 268)
        palette_select = advanced_page & (
            self.selected == RezoHardwareUI.TARGET_PALETTE) & self.outline(
                x, y, 340 if self.compact_layout else 260,
                256 if self.compact_layout else 224,
                460 if self.compact_layout else 412,
                304 if self.compact_layout else 272, t=3)
        save_default_chip = advanced_page & self.rect(
            x, y, 344 if self.compact_layout else 264,
            324 if self.compact_layout else 292,
            472 if self.compact_layout else 408,
            364 if self.compact_layout else 332)
        save_default_select = advanced_page & (
            self.selected == RezoHardwareUI.TARGET_SAVE_DEFAULT) & self.outline(
                x, y, 340 if self.compact_layout else 260,
                320 if self.compact_layout else 288,
                476 if self.compact_layout else 412,
                368 if self.compact_layout else 336, t=3)
        motion_source_x0 = 280 if self.compact_layout else 160
        motion_source_x1 = 424 if self.compact_layout else 296
        motion_rate_x0 = 280 if self.compact_layout else 160
        motion_rate_x1 = 360 if self.compact_layout else 296
        motion_phase_x0 = 280 if self.compact_layout else 512
        motion_phase_x1 = 360 if self.compact_layout else 640
        motion_depth_x0 = 280 if self.compact_layout else 512
        motion_depth_x1 = 568 if self.compact_layout else 640
        # Dynamic text occupies fourteen pixels at the bottom-biased tile
        # baseline. Inset compact chips by four pixels so their visible
        # padding is balanced above and below the glyphs.
        motion_top_y0 = 460 if self.compact_layout else 520
        motion_top_y1 = 480 if self.compact_layout else 552
        motion_rate_y0 = 492 if self.compact_layout else 584
        motion_rate_y1 = 512 if self.compact_layout else 616
        motion_phase_y0 = 524 if self.compact_layout else 520
        motion_phase_y1 = 544 if self.compact_layout else 552
        motion_bottom_y0 = 552 if self.compact_layout else 584
        motion_bottom_y1 = 572 if self.compact_layout else 616
        # SOURCE, RATE, and PHASE share the same 24-on/8-off vertical cadence.
        # Decode the column once instead of synthesizing three full rectangles.
        motion_value_x1 = Signal(unsigned(10), init=motion_rate_x1)
        m.d.comb += motion_value_x1.eq(Mux(
            y[5:10] == (motion_top_y0 >> 5),
            motion_source_x1, motion_rate_x1))
        motion_value_chip = (
            bands_page &
            (y[5:10] >= (motion_top_y0 >> 5)) &
            (y[5:10] <= (motion_phase_y0 >> 5)) &
            (y[:5] >= (motion_top_y0 & 31)) &
            (x >= motion_source_x0) & (x < motion_value_x1))
        motion_select_x0 = Signal(
            unsigned(10), init=motion_source_x0 - 4)
        motion_select_x1 = Signal(
            unsigned(10), init=motion_source_x1 + 4)
        motion_select_y0 = Signal(
            unsigned(10), init=motion_top_y0 - 4)
        motion_chip_selected = Signal()
        m.d.comb += [
            motion_select_x0.eq(motion_source_x0 - 4),
            motion_select_x1.eq(motion_source_x1 + 4),
            motion_select_y0.eq(motion_top_y0 - 4),
            motion_chip_selected.eq(0),
        ]
        with m.Switch(self.selected):
            with m.Case(RezoHardwareUI.TARGET_MOTION_SOURCE):
                m.d.comb += motion_chip_selected.eq(1)
            with m.Case(RezoHardwareUI.TARGET_MOTION_RATE):
                m.d.comb += [
                    motion_select_x0.eq(motion_rate_x0 - 4),
                    motion_select_x1.eq(motion_rate_x1 + 4),
                    motion_select_y0.eq(motion_rate_y0 - 4),
                    motion_chip_selected.eq(1),
                ]
            with m.Case(RezoHardwareUI.TARGET_MOTION_PHASE):
                m.d.comb += [
                    motion_select_x0.eq(motion_phase_x0 - 4),
                    motion_select_x1.eq(motion_phase_x1 + 4),
                    motion_select_y0.eq(motion_phase_y0 - 4),
                    motion_chip_selected.eq(1),
                ]
        motion_outline_height = 28 if self.compact_layout else 40
        motion_chip_select = (
            bands_page & motion_chip_selected &
            self.outline(x, y, motion_select_x0, motion_select_y0,
                         motion_select_x1,
                         motion_select_y0 + motion_outline_height, t=3))
        motion_fader_height = 20 if self.compact_layout else 32
        motion_depth_track = (
            bands_page &
            (y >= motion_bottom_y0) &
            (y < motion_bottom_y0 + motion_fader_height) &
            (x >= motion_depth_x0) & (x < motion_depth_x1))

        # Store absolute endpoints in block memory to avoid a wide multiply in
        # the near-capacity pixel path.
        motion_ui_init = [motion_depth_x0 >> 2] * 512
        for depth_value in range(256):
            clamped_depth = min(depth_value, RezoCore.CROSS_DEPTH_MAX)
            motion_ui_init[depth_value] = (
                motion_depth_x0 + (clamped_depth << 1) +
                (clamped_depth >> 2)) >> 2
        for raw_value in range(64):
            signed_value = raw_value if raw_value < 32 else raw_value - 64
            # The depth-scaled monitor's reachable source extrema are -16
            # and +15. Map those asymmetrical integer limits onto equal
            # 144-pixel excursions across the full 288-pixel DEPTH track.
            # This table is display-only; DSP modulation remains unchanged.
            if signed_value >= 0:
                scaled_value = min(36, round(signed_value * 36 / 15))
            else:
                scaled_value = round(signed_value * 36 / 16)
            motion_ui_init[256 + raw_value] = 106 + scaled_value
        m.submodules.motion_ui_mem = motion_ui_mem = Memory(
            shape=unsigned(8), depth=len(motion_ui_init),
            init=motion_ui_init, attrs={"ram_style": "block"})
        motion_depth_rport = motion_ui_mem.read_port(domain="dvi")
        motion_monitor_rport = motion_ui_mem.read_port(domain="dvi")
        motion_monitor_negative_q = Signal()
        m.d.comb += [
            motion_depth_rport.addr.eq(self.motion_depth),
            motion_monitor_rport.addr.eq(
                256 | self.motion_monitor.as_unsigned()),
        ]
        # Align the sign with the synchronous endpoint-table read.  Without
        # this delay a zero crossing could combine a new sign with the prior
        # endpoint for one pixel clock.
        m.d.dvi += motion_monitor_negative_q.eq(self.motion_monitor < 0)
        motion_depth_fill = (
            bands_page & (x[2:10] >= (motion_depth_x0 >> 2)) &
            (x[2:10] < motion_depth_rport.data[:8]) &
            (y >= motion_bottom_y0) &
            (y < motion_bottom_y0 + motion_fader_height))
        motion_depth_select = (
            bands_page &
            (self.selected == RezoHardwareUI.TARGET_MOTION_DEPTH) &
            self.rect(x, y, motion_depth_x0 - 6, motion_bottom_y0,
                      motion_depth_x0 - 2,
                      motion_bottom_y0 + motion_fader_height))

        # A thin bipolar telemetry line reuses the same visual language as the
        # INPUT page. Its value comes from the audio engine's existing LFO;
        # the display does not synthesize another oscillator.
        motion_monitor_line = bands_page & self.bipolar_line(
            x[2:10], y, 106, motion_monitor_rport.data,
            570, 572, motion_monitor_negative_q)

        damp_chip = tune_page & self.rect(
            x, y, 268 if self.compact_layout else 156,
            462 if self.compact_layout else 504,
            396 if self.compact_layout else 316,
            486 if self.compact_layout else 536)
        damp_select = tune_page & (
            self.selected == RezoHardwareUI.TARGET_DAMP) & self.outline(
                x, y, 264 if self.compact_layout else 150,
                458 if self.compact_layout else 500,
                400 if self.compact_layout else 322,
                490 if self.compact_layout else 540, t=3)
        layout_chip = bands_page & self.rect(
            x, y, 256 if self.compact_layout else 136,
            168 if self.compact_layout else 100,
            384 if self.compact_layout else 264,
            200 if self.compact_layout else 138)
        layout_select = bands_page & (
            self.selected == RezoHardwareUI.TARGET_BAND_LAYOUT) & self.outline(
                x, y, 252 if self.compact_layout else 131,
                164 if self.compact_layout else 95,
                388 if self.compact_layout else 269,
                204 if self.compact_layout else 143, t=3)
        cross_layout_chip = cross_page & self.rect(
            x, y, 248 if self.compact_layout else 128,
            168 if self.compact_layout else 100,
            392 if self.compact_layout else 272,
            200 if self.compact_layout else 138)
        cross_layout_select = cross_page & (
            self.selected == RezoHardwareUI.TARGET_CROSS_LAYOUT) & self.outline(
                x, y, 244 if self.compact_layout else 123,
                164 if self.compact_layout else 95,
                396 if self.compact_layout else 277,
                204 if self.compact_layout else 143, t=3)
        cross_curve_chip = advanced_page & self.rect(
            x, y, 320,
            484 if self.compact_layout else 452,
            448,
            524 if self.compact_layout else 492)
        cross_curve_select = advanced_page & (
            self.selected == RezoHardwareUI.TARGET_CROSS_CURVE) & self.outline(
                x, y, 316,
                480 if self.compact_layout else 448,
                452,
                528 if self.compact_layout else 496, t=3)

        preset_chip = Signal()
        preset_select = Signal()
        preset_group_select = Signal()
        band_slot = Signal()
        band_zero = Signal()
        band_marker = Signal()
        band_fill = Signal()
        band_mod_fill = Signal()
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
        output_side_chip = Signal()
        output_side_select = Signal()
        cross_header_select = Signal()

        preset_chip_signals = []
        preset_select_signals = []
        group_cell_signals = []
        group_select_signals = []

        input_gain_ends = [Signal(signed(12), init=326, name=f"input_gain_end{n}")
                           for n in range(4)]
        input_depth_ends = [Signal(signed(12), init=490, name=f"input_depth_end{n}")
                            for n in range(4)]
        input_meter_ends = [Signal(signed(12), init=326, name=f"input_meter_end{n}")
                            for n in range(4)]
        for n in range(4):
            if self.compact_layout:
                m.d.dvi += [
                    input_gain_ends[n].eq(304 + self.input_gains[n]),
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
        m.d.comb += band_x_rport.addr.eq(x.as_unsigned())

        band_y_q = Signal.like(y)
        band_active_q = Signal()
        band_home_page_q = Signal()
        band_bank_page_q = Signal()
        band_tune_page_q = Signal()
        band_bands_page_q = Signal()
        band_selected_target_q = Signal.like(self.selected)
        m.d.dvi += [
            band_y_q.eq(y),
            band_active_q.eq(active),
            band_home_page_q.eq(home_page),
            band_bank_page_q.eq(bank_page),
            band_tune_page_q.eq(tune_page),
            band_bands_page_q.eq(bands_page),
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
        band_tune_page_value_q = Signal()
        band_bands_page_value_q = Signal()
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
            band_tune_page_value_q.eq(band_tune_page_q),
            band_bands_page_value_q.eq(band_bands_page_q),
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
        feedback_button_y = (
            (band_y_value_q >= bands_enable_y0) &
            (band_y_value_q < bands_enable_y0 + bands_button_h))
        band_slot_y = Mux(
            band_bands_page_value_q, bands_button_y,
            Mux(band_tune_page_value_q, feedback_button_y,
                (band_y_value_q >= main_band_y0) &
                (band_y_value_q < main_band_y1)))
        main_band_y = ((band_y_value_q >= main_band_y0) &
                       (band_y_value_q < main_band_y1))
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
        bank_selection_outline = (
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
                         ((band_home_page_value_q & band_enable_q) |
                          (band_tune_page_value_q & band_enable_q) |
                          band_bands_page_value_q) &
                         band_fill_x_q & band_slot_y),
            band_zero.eq(
                band_active_value_q & (
                (band_bank_page_value_q & band_enable_q & band_zero_x_q &
                 (band_y_value_q >= zero_y - 1) &
                 (band_y_value_q < zero_y + 2)) |
                # Disabled BANK bands retain a dim frame on the main and
                # feedback pages so their position remains legible without
                # implying that they contribute audio.
                (~band_enable_q &
                 ((band_bank_page_value_q & bank_selection_outline) |
                  (band_tune_page_value_q &
                   feedback_selection_outline))))),
            band_marker.eq(
                band_active_value_q & band_bank_page_value_q &
                band_enable_q & base_marker),
            band_fill.eq(
                band_active_value_q & (
                (band_bank_page_value_q & band_enable_q &
                 (main_band_y if self.compact_layout else Const(1)) &
                 base_bank_fill) |
                (band_tune_page_value_q & band_enable_q & band_fill_x_q &
                 band_slot_y & band_feedback_send_q) |
                (band_bands_page_value_q & band_fill_x_q & band_enable_q &
                 (band_y_value_q >= bands_enable_y0) &
                 (band_y_value_q < bands_enable_y0 + bands_button_h)))),
            band_mod_fill.eq(
                band_active_value_q & band_bank_page_value_q & band_enable_q &
                (main_band_y if self.compact_layout else Const(1)) &
                (base_bank_fill ^ effective_bank_fill) &
                ~base_marker),
        ]
        band_select_q0 = (
            (band_bank_page_value_q & band_enable_q & selected_band &
             bank_selection_outline) |
            (band_tune_page_value_q & band_enable_q & feedback_band_selected &
             feedback_selection_outline) | (
                band_bands_page_value_q &
                (enable_band_selected | frequency_band_selected) &
                bands_edit_outline))

        # INPUT repeats the same geometry four times. Decode y into one local
        # row/index pair in BRAM, then select that row's dynamic settings.
        # Besides replacing four parallel sets of wide y comparisons, this
        # leaves the one-pixel telemetry meter effectively free in the pixel
        # path. local_y is relative to the selection outline's top edge
        # (base_y - 4), hence the +4 offsets below.
        input_y_init = []
        for pixel_y in range(self.PANEL_H):
            encoded_input_y = 0
            for input_index_init in range(4):
                input_base = (
                    (221 if self.compact_layout else 194) +
                    input_index_init * 96)
                if input_base <= pixel_y < input_base + 96:
                    input_local_init = pixel_y - input_base
                    encoded_input_y = (
                        input_local_init | (input_index_init << 8) |
                        (1 << 10))
                    break
            input_y_init.append(encoded_input_y)
        m.submodules.input_y_mem = input_y_mem = Memory(
            shape=unsigned(11), depth=self.PANEL_H, init=input_y_init,
            attrs={"ram_style": "block"})
        input_y_rport = input_y_mem.read_port(domain="dvi")
        m.d.comb += input_y_rport.addr.eq(y)

        input_x_q = Signal.like(x)
        # The selected row's dynamic endpoints are registered once below.
        # Prefetch x by one pixel so this extra value-selection stage remains
        # aligned with the renderer's established geometry pipeline.
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
        input_targets = Array(
            Const(RezoHardwareUI.TARGET_INPUT_BASE + n * 3, 7)
            for n in range(4))
        input_target = input_targets[input_index]
        input_unity_coarse = RezoCore.INPUT_UNITY_POS >> 8
        input_unity_x = (
            304 + input_unity_coarse if self.compact_layout
            else 326 + input_unity_coarse + (input_unity_coarse >> 2))
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
        input_mode_x0 = 304 if self.compact_layout else 116
        input_mode_x1 = 402 if self.compact_layout else 304
        input_value_x0 = 304 if self.compact_layout else 116
        input_value_x1 = 370 if self.compact_layout else 656
        input_lane_x1 = 576 if self.compact_layout else 656
        input_select_x0 = 300 if self.compact_layout else 112
        input_panel_q0 = input_visible & (
            self.rect(input_x_value_q, input_local_value_q,
                      input_mode_x0, 0 if self.compact_layout else 4,
                      input_mode_x1, 20 if self.compact_layout else 32) |
            Mux(input_is_cv,
                self.rect(input_x_value_q, input_local_value_q,
                          input_value_x0, 32 if self.compact_layout else 36,
                          input_value_x1, 52 if self.compact_layout else 64),
                self.rect(input_x_value_q, input_local_value_q,
                          input_value_x0, 32 if self.compact_layout else 36,
                          input_lane_x1, 52 if self.compact_layout else 64)) |
            (input_is_cv & self.rect(
                input_x_value_q, input_local_value_q,
                input_value_x0, 64 if self.compact_layout else 68,
                input_lane_x1, 84 if self.compact_layout else 96)))
        input_select_q0 = input_visible & (
            ((input_row_selected_q == input_target_q) &
             self.outline(input_x_value_q, input_local_value_q,
                          input_select_x0, 0,
                          input_mode_x1 + 4,
                          24 if self.compact_layout else 36, t=3)) |
            ((input_row_selected_q == input_target_q + 1) & Mux(
                input_is_cv,
                self.outline(input_x_value_q, input_local_value_q,
                             input_select_x0,
                             28 if self.compact_layout else 32,
                             input_value_x1 + 4,
                             56 if self.compact_layout else 68, t=3),
                self.rect(input_x_value_q, input_local_value_q,
                          300 if self.compact_layout else 320,
                          34 if self.compact_layout else 43,
                          304 if self.compact_layout else 324,
                          50 if self.compact_layout else 57))) |
            (input_is_cv & (input_row_selected_q == input_target_q + 2) &
             self.rect(input_x_value_q, input_local_value_q,
                       300 if self.compact_layout else 320,
                       66 if self.compact_layout else 75,
                       304 if self.compact_layout else 324,
                       82 if self.compact_layout else 89)))
        input_fill_q0 = input_visible & Mux(
            input_is_cv,
            Mux(~input_depth_negative_q,
                self.rect(input_x_value_q, input_local_value_q,
                          440 if self.compact_layout else 490,
                          68 if self.compact_layout else 75,
                          input_depth_end_q,
                          80 if self.compact_layout else 89),
                self.rect(input_x_value_q, input_local_value_q,
                          input_depth_end_q,
                          68 if self.compact_layout else 75,
                          440 if self.compact_layout else 490,
                          80 if self.compact_layout else 89)),
            self.rect(input_x_value_q, input_local_value_q,
                      304 if self.compact_layout else 326,
                      36 if self.compact_layout else 43,
                      input_gain_end_q,
                      48 if self.compact_layout else 57))
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
        # A uniform telemetry line immediately below VALUE. Audio is unipolar
        # from the bar's left edge; CV is bipolar around the DEPTH center.
        input_meter_q0 = input_visible & Mux(
            input_is_cv,
            self.bipolar_line(
                input_x_value_q, input_local_value_q,
                440 if self.compact_layout else 490,
                input_meter_end_q,
                82 if self.compact_layout else 65,
                84 if self.compact_layout else 66,
                input_meter_negative_q),
            self.rect(input_x_value_q, input_local_value_q,
                      304 if self.compact_layout else 326,
                      50 if self.compact_layout else 65,
                      input_meter_end_q,
                      52 if self.compact_layout else 66))

        for group in range(RezoCore.N_GROUPS):
            rail_y = (compact_group_centers[group]
                      if self.compact_layout else 305 + group * 64)
            group_cell_signals.append(
                group_page & self.rect(
                    x, text_y if self.compact_layout else y,
                    202 if self.compact_layout else 128, rail_y,
                    576 if self.compact_layout else 640,
                    rail_y + (2 if self.compact_layout else 3)))

        group_selected_index = Signal(range(RezoCore.N_BANDS))
        group_selected_x_pre = Signal(
            unsigned(10), init=208 if self.compact_layout else 144)
        group_selected_x = Signal.like(group_selected_x_pre)
        group_selected_valid_pre = Signal()
        group_selected_valid = Signal()
        m.d.comb += [
            group_selected_index.eq(0),
            group_selected_x_pre.eq(208 if self.compact_layout else 144),
            group_selected_valid_pre.eq(
                (self.selected >= RezoHardwareUI.TARGET_GROUP_BASE) &
                (self.selected < RezoHardwareUI.TARGET_GROUP_BASE +
                 RezoCore.N_BANDS)),
        ]
        with m.If(group_selected_valid_pre):
            m.d.comb += [
                group_selected_index.eq(
                    self.selected - RezoHardwareUI.TARGET_GROUP_BASE),
                group_selected_x_pre.eq(Mux(
                    self.compact_layout,
                    208 + (group_selected_index << 5) +
                          (group_selected_index << 1),
                    144 + (group_selected_index << 5) +
                          (group_selected_index << 4))),
            ]
        m.d.dvi += [
            group_selected_x.eq(group_selected_x_pre),
            group_selected_valid.eq(group_selected_valid_pre),
        ]
        group_select_signals.append(
            group_page & group_selected_valid & self.outline(
                x, y,
                group_selected_x - (5 if self.compact_layout else 7),
                306 if self.compact_layout else 274,
                group_selected_x + (23 if self.compact_layout else 31),
                486 if self.compact_layout else 548, t=3))
        group_band = Signal(range(RezoCore.N_BANDS))
        group_row = Signal(unsigned(2))
        group_band_active = Signal()
        group_row_active = Signal()
        group_row_edge = Signal()
        group_ghost = Signal()
        group_page_q = Signal()
        group_page_value_q = Signal()
        bank_group_mask_array = Array(self.bank_groups)
        band_enable_mask_array = Array(self.band_enables)
        # A dual-port block ROM decodes both axes of the 10x4 group grid. It
        # replaces fourteen parallel coordinate ranges with one BRAM while
        # retaining the same single pixel-domain pipeline stage. Bits 0..4
        # describe an x coordinate; bits 5..8 describe a y coordinate.
        group_geometry_init = []
        for coordinate in range(self.PANEL_W):
            encoded = 0
            # Compact GROUPS fill/ghost state gets one extra register after
            # this BRAM. Store its x decoder one pixel ahead so that state
            # remains aligned with the unmodified y decoder and cell rails.
            group_pixel_x = coordinate + (1 if self.compact_layout else 0)
            for n in range(RezoCore.N_BANDS):
                x0 = (208 + n * 34 if self.compact_layout
                      else 144 + n * 48)
                marker_width = 18 if self.compact_layout else 24
                if x0 <= group_pixel_x < x0 + marker_width:
                    encoded |= n
                    encoded |= 1 << 4
                    break
            for group in range(RezoCore.N_GROUPS):
                marker_y = (
                    compact_group_centers[group] - 9
                    if self.compact_layout else 294 + group * 64)
                marker_height = 20 if self.compact_layout else 24
                if marker_y <= coordinate < marker_y + marker_height:
                    encoded |= group << 5
                    encoded |= 1 << 7
                    if (coordinate < marker_y + 2 or coordinate >=
                            marker_y + marker_height - 2):
                        encoded |= 1 << 8
                    break
            group_geometry_init.append(encoded)
        m.submodules.group_geometry_mem = group_geometry_mem = Memory(
            shape=unsigned(9), depth=self.PANEL_W,
            init=group_geometry_init, attrs={"ram_style": "block"})
        group_x_rport = group_geometry_mem.read_port(domain="dvi")
        group_y_rport = group_geometry_mem.read_port(domain="dvi")
        m.d.comb += [
            group_x_rport.addr.eq(x.as_unsigned()),
            group_y_rport.addr.eq(y.as_unsigned()),
            group_band.eq(group_x_rport.data[:4]),
            group_band_active.eq(group_x_rport.data[4]),
            group_row.eq(group_y_rport.data[5:7]),
            group_row_active.eq(group_y_rport.data[7]),
            group_row_edge.eq(group_y_rport.data[8]),
        ]
        if self.compact_layout:
            group_band_value_q = Signal.like(group_band)
            group_row_value_q = Signal.like(group_row)
            group_band_active_value_q = Signal()
            group_row_active_value_q = Signal()
            group_row_edge_value_q = Signal()
            m.d.dvi += [
                # Isolate the BRAM output delay from the dynamic bank/group
                # mask lookup. The one-pixel x prefetch above compensates this
                # stage in the streaming renderer.
                group_band_value_q.eq(group_band),
                group_row_value_q.eq(group_row),
                group_band_active_value_q.eq(group_band_active),
                group_row_active_value_q.eq(group_row_active),
                group_row_edge_value_q.eq(group_row_edge),
                group_page_q.eq(group_page),
                group_page_value_q.eq(group_page_q),
            ]
        else:
            group_band_value_q = group_band
            group_row_value_q = group_row
            group_band_active_value_q = group_band_active
            group_row_active_value_q = group_row_active
            group_row_edge_value_q = group_row_edge
            m.d.dvi += [
                group_page_q.eq(group_page),
                group_page_value_q.eq(group_page_q),
            ]
        m.d.comb += group_fill.eq(
            (group_page_value_q if self.compact_layout else group_page_q) &
            group_band_active_value_q & group_row_active_value_q &
            band_enable_mask_array[group_band_value_q] &
            bank_group_mask_array[group_band_value_q].bit_select(
                group_row_value_q, 1))
        # Disabled BANK bands retain dim top/bottom rails at all four GROUPS
        # assignments. A full forty-cell rectangle decoder costs more logic
        # than remains available; these shared rails preserve location and
        # inactive state without implying an enabled assignment.
        m.d.comb += group_ghost.eq(
            (group_page_value_q if self.compact_layout else group_page_q) &
            group_band_active_value_q & group_row_active_value_q &
            group_row_edge_value_q &
            ~band_enable_mask_array[group_band_value_q])

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
        m.d.comb += [
            output_send_scaled_write.eq(Mux(
                self.compact_layout,
                self.output_send_write_data +
                (self.output_send_write_data << 1),
                self.output_send_write_data << 2)),
            output_send_wport.addr.eq(self.output_send_write_addr),
            output_send_wport.data.eq(output_send_scaled_write),
            output_send_wport.en.eq(self.output_send_write_en),
        ]
        output_cell_x0 = Signal(unsigned(10))
        output_cell_y0 = Signal(unsigned(10))
        output_send_index = Signal(unsigned(5))
        m.d.comb += [
            output_row.eq(0),
            output_source.eq(0),
            output_row_active.eq(0),
            output_col_active.eq(0),
            output_row_edge.eq(0),
            output_col_edge.eq(0),
            output_row_inner.eq(0),
            output_col_inner.eq(0),
            output_cell_x0.eq(243 if self.compact_layout else 188),
            output_cell_y0.eq(
                compact_output_row_centers[0] - 13
                if self.compact_layout else 326),
            output_send_index.eq(0),
        ]
        for output in range(4):
            output_row_y = (
                compact_output_row_centers[output] - 13
                if self.compact_layout else 326 + output * 80)
            row_y = (
                Mux(cross_page,
                    compact_cross_row_centers[output] - 13,
                    output_row_y)
                if self.compact_layout else output_row_y)
            output_geom_y = text_y if self.compact_layout else y
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
            cell_width = 56 if self.compact_layout else 72
            output_cell_left = (
                compact_output_col_centers[source] - 27
                if self.compact_layout else 188 + source * 96)
            cell_x0 = (
                Mux(cross_page,
                    (compact_cross_col_centers[source] - 27
                     if source < 4 else output_cell_left),
                    output_cell_left)
                if self.compact_layout else output_cell_left)
            cell_width = (
                Mux(cross_page,
                    Const(56 if source < 4 else cell_width, 7),
                    Const(cell_width, 7))
                if self.compact_layout else cell_width)
            output_geom_x = text_x if self.compact_layout else x
            source_visible = ~cross_page if source == 4 else Const(1)
            with m.If(source_visible & (output_geom_x >= cell_x0) &
                      (output_geom_x < cell_x0 + cell_width)):
                m.d.comb += [
                    output_source.eq(source),
                    output_col_active.eq(1),
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
        output_x_q = Signal.like(x)
        output_y_q = Signal.like(y)
        output_x0_q = Signal.like(output_cell_x0)
        output_y0_q = Signal.like(output_cell_y0)
        output_send_value_q = Signal.like(output_send_rport.data)
        output_send_end = Signal(unsigned(10))
        output_row_active_q = Signal()
        output_col_active_q = Signal()
        output_page_q = Signal()
        cross_page_q = Signal()
        cross_column_visible_q = Signal()
        m.d.dvi += [
            output_x_q.eq(text_x if self.compact_layout else x),
            output_y_q.eq(text_y if self.compact_layout else y),
            output_x0_q.eq(output_cell_x0),
            output_y0_q.eq(output_cell_y0),
            # The send address changes only at cell boundaries, while each
            # fill begins four pixels into its cell. Registering the BRAM data
            # here removes its 5.8 ns clock-to-Q delay from the endpoint
            # adder/comparator without changing a visible fill boundary.
            output_send_value_q.eq(output_send_rport.data),
            output_row_active_q.eq(output_row_active),
            output_col_active_q.eq(output_col_active),
            output_page_q.eq(output_page),
            cross_page_q.eq(cross_page),
            cross_column_visible_q.eq(output_source < 4),
        ]
        m.d.comb += output_send_end.eq(
            output_x0_q + 4 + output_send_value_q)
        routing_matrix_page = Signal()
        cross_matrix_active = Signal()
        m.d.comb += routing_matrix_page.eq(
            output_page | (cross_page & (output_source < 4)))
        m.d.comb += cross_matrix_active.eq(
            self.cross_layout != RezoCore.CROSS_LAYOUT_GLOBAL)
        m.d.comb += [
            output_cell.eq(routing_matrix_page & output_row_active & output_col_active &
                           (output_row_edge | output_col_edge)),
            output_side_chip.eq(
                output_page & output_row_active &
                (x >= (204 if self.compact_layout else 100)) &
                (x < (236 if self.compact_layout else 156))),
            output_side_select.eq(
                output_page & output_row_active &
                (self.selected == RezoHardwareUI.TARGET_OUTPUT_SIDE_BASE + output_row) &
                (x >= (200 if self.compact_layout else 96)) &
                (x < (240 if self.compact_layout else 160)) &
                ((x < (204 if self.compact_layout else 100)) |
                 (x >= (236 if self.compact_layout else 156)) |
                 output_row_edge)),
            output_fill.eq(
                (output_page_q | (cross_page_q & cross_column_visible_q)) &
                (~cross_page_q | cross_matrix_active) &
                output_row_active_q & output_col_active_q &
                (output_y_q >= output_y0_q + 5) &
                (output_y_q < output_y0_q + 23) &
                (output_x_q >= output_x0_q + 4) &
                (output_x_q < output_send_end)),
        ]
        cross_cell_selected = Signal()
        output_cell_selected = Signal()
        output_header_group = Signal(unsigned(2))
        output_header_row_target = Signal()
        output_header_col_target = Signal()
        m.d.comb += [
            # Both shared target bases are 2 modulo 4. This wiring maps their
            # low bits back to a zero-based group without subtraction.
            output_header_group[0].eq(self.selected[0]),
            output_header_group[1].eq(~self.selected[1]),
            output_header_row_target.eq(
                (self.selected >= RezoHardwareUI.TARGET_OUTPUT_ROW_BASE) &
                (self.selected < RezoHardwareUI.TARGET_OUTPUT_ROW_BASE + 4)),
            output_header_col_target.eq(
                (self.selected >= RezoHardwareUI.TARGET_OUTPUT_COL_BASE) &
                (self.selected < RezoHardwareUI.TARGET_OUTPUT_COL_BASE + 4)),
        ]
        m.d.comb += [
            # Keep the four-column CROSS selection path independent of the
            # five-column OUTPUT send address.  Sharing the target arithmetic
            # made the DVI path unnecessarily deep and also made it too easy
            # to accidentally inherit OUTPUT's row stride here.
            cross_cell_selected.eq(
                cross_page &
                (self.selected[4:] ==
                 RezoHardwareUI.TARGET_CROSS_MATRIX_BASE >> 4) &
                (self.selected[:4] == Cat(output_source[:2], output_row))),
            output_cell_selected.eq(
                output_page &
                (self.selected == RezoHardwareUI.TARGET_OUTPUT_BASE +
                 output_send_index)),
            output_select.eq(
                routing_matrix_page & output_row_active & output_col_active &
                (cross_cell_selected | output_cell_selected) &
                (output_row_edge | output_col_edge)),
            # Header edits use solid left/top bars on both routing matrices.
            # This distinguishes relative bulk edits from individual outlined
            # cells and is substantially cheaper than ten additional boxes.
            cross_header_select.eq(
                (cross_page & cross_matrix_active &
                 (((output_row_active & output_header_row_target &
                    (output_header_group == output_row) &
                    (x >= (132 if self.compact_layout else 72)) &
                    (x < (136 if self.compact_layout else 76)))) |
                  (output_col_active & (output_source < 4) &
                   output_header_col_target &
                   (output_header_group == output_source) &
                   (y >= (264 if self.compact_layout else 248)) &
                   (y < (268 if self.compact_layout else 252))))) |
                (output_page &
                 (((output_row_active & output_header_row_target &
                    (output_header_group == output_row) &
                    (x >= (116 if self.compact_layout else 26)) &
                    (x < (120 if self.compact_layout else 30)))) |
                  (output_col_active &
                   (y >= (280 if self.compact_layout else 264)) &
                   (y < (284 if self.compact_layout else 268)) &
                   ((output_header_col_target &
                     (output_header_group == output_source)) |
                    ((self.selected ==
                      RezoHardwareUI.TARGET_OUTPUT_DRY_COL) &
                     (output_source == 4))))))),
        ]

        for target, signals in [
                (preset_chip, preset_chip_signals),
                (preset_select, preset_select_signals),
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

        band_zero_q0 = band_zero
        band_slot_q0 = band_slot
        group_cell_q0 = tile_registered_or(group_cell_signals, "group_cell")
        group_fill_q0 = Signal()
        group_ghost_q0 = Signal()
        group_select_q0 = tile_registered_or(group_select_signals, "group_select")
        output_cell_q0 = Signal()
        output_fill_q0 = Signal()
        output_select_q0 = Signal()
        cross_header_select_q0 = Signal()
        m.d.dvi += [
            output_cell_q0.eq(output_cell),
            output_select_q0.eq(output_select),
            cross_header_select_q0.eq(cross_header_select),
        ]
        m.d.dvi += output_fill_q0.eq(output_fill)
        m.d.comb += [
            group_fill_q0.eq(group_fill),
            group_ghost_q0.eq(group_ghost),
        ]

        m.d.comb += preset_group_select.eq(
            bank_page & (self.selected == RezoHardwareUI.TARGET_PRESET) &
            ~self.editing & self.outline(
                text_x if self.compact_layout else x,
                text_y if self.compact_layout else y,
                244 if self.compact_layout else 131,
                164 if self.compact_layout else 95,
                332 if self.compact_layout else 269,
                204 if self.compact_layout else 143, t=3))
        drive_select = (
            bank_page & (self.selected == RezoHardwareUI.TARGET_DRIVE) &
            self.outline(x, y, bank_panel_x0,
                         bank_control_y0s[0] - 2, bank_panel_x1,
                         bank_control_y0s[0] + 18, t=3))

        # DRIVE, RES and FB use one pipelined row/value decoder.  Keeping the
        # base/effective split here gives all three controls identical CV
        # shading and fixed markers without three copies of wide x compares.
        bank_control_row = Signal(unsigned(2))
        bank_control_y0 = Signal(
            unsigned(10), init=bank_control_y0s[0])
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
        for row in range(3):
            row_y0 = bank_control_y0s[row]
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
        control_fill_x0 = 289 if self.compact_layout else 124
        bank_control_end = (
            control_fill_x0 + (bank_control_base_q << 1) +
            (bank_control_base_q >> 2) + (bank_control_base_q >> 3)
            if self.compact_layout else
            control_fill_x0 + (bank_control_base_q << 2))
        bank_control_effective_end = (
            control_fill_x0 + (bank_control_effective_q << 1) +
            (bank_control_effective_q >> 2) +
            (bank_control_effective_q >> 3)
            if self.compact_layout else
            control_fill_x0 + (bank_control_effective_q << 2))
        bank_control_fill = bank_control_visible & self.rect(
            bank_control_x_q, bank_control_y_q, control_fill_x0,
            bank_control_y0_q, bank_control_end, bank_control_y0_q + 16)
        bank_control_effective_fill = bank_control_visible & self.rect(
            bank_control_x_q, bank_control_y_q, control_fill_x0,
            bank_control_y0_q, bank_control_effective_end,
            bank_control_y0_q + 16)
        bank_control_mod_fill = (
            bank_control_fill ^ bank_control_effective_fill)
        bank_control_mod_marker = bank_control_visible & self.rect(
            bank_control_x_q, bank_control_y_q,
            bank_control_end - 2, bank_control_y0_q - 2,
            bank_control_end + 2, bank_control_y0_q + 18)

        cross_track_x0 = 236 if self.compact_layout else 124
        same_y0 = 544 if self.compact_layout else 620
        cross_y0 = 576 if self.compact_layout else 652
        same_feedback_width = (
            (self.same_feedback << 1) + (self.same_feedback >> 1) +
            (self.same_feedback >> 3)
            if self.compact_layout else self.same_feedback << 2)
        cross_feedback_width = (
            (self.cross_feedback << 1) + (self.cross_feedback >> 1) +
            (self.cross_feedback >> 3)
            if self.compact_layout else self.cross_feedback << 2)
        same_fill = cross_page & self.rect(
            x, y, cross_track_x0, same_y0,
            cross_track_x0 + same_feedback_width,
            same_y0 + 16)
        cross_fill = cross_page & self.rect(
            x, y, cross_track_x0, cross_y0,
            cross_track_x0 + cross_feedback_width,
            cross_y0 + 16)
        cross_select = cross_page & (
            ((self.selected == RezoHardwareUI.TARGET_SAME_FEEDBACK) &
             self.rect(x, y, cross_track_x0 - 6, same_y0,
                       cross_track_x0 - 2, same_y0 + 16)) |
            ((self.selected == RezoHardwareUI.TARGET_CROSS_FEEDBACK) &
             self.rect(x, y, cross_track_x0 - 6, cross_y0,
                       cross_track_x0 - 2, cross_y0 + 16)))
        tune_fill_x0 = 268 if self.compact_layout else 156
        tune_fill_scale_shift = 0 if self.compact_layout else 2
        dry_fill = tune_page & self.rect(
            x, y, tune_fill_x0,
            400 if self.compact_layout else 412,
            (tune_fill_x0 + self.limit_knee + (self.limit_knee >> 3)
             if self.compact_layout else
             124 + (self.limit_knee << tune_fill_scale_shift)),
            416 if self.compact_layout else 428)
        dry_select = (
            tune_page &
            (self.selected == RezoHardwareUI.TARGET_LIMIT_KNEE) &
            self.outline(x, y,
                         264 if self.compact_layout else 144,
                         396 if self.compact_layout else 408,
                         592 if self.compact_layout else 148,
                         420 if self.compact_layout else 432, t=3))
        tune_cap_fill = tune_page & self.rect(
            x, y, tune_fill_x0,
            432 if self.compact_layout else 460,
            (tune_fill_x0 + self.limit_cap + (self.limit_cap >> 3)
             if self.compact_layout else
             124 + (self.limit_cap << tune_fill_scale_shift)),
            448 if self.compact_layout else 476)
        res_select = (
            (bank_page &
             (self.selected == RezoHardwareUI.TARGET_RESONANCE) &
             self.outline(x, y, bank_panel_x0,
                          bank_control_y0s[1] - 2, bank_panel_x1,
                          bank_control_y0s[1] + 18, t=3)) |
            (tune_page &
             (self.selected == RezoHardwareUI.TARGET_LIMIT_CAP) &
             self.outline(x, y,
                          264 if self.compact_layout else 144,
                          428 if self.compact_layout else 456,
                          592 if self.compact_layout else 148,
                          452 if self.compact_layout else 480, t=3)))
        fb_select = (bank_page &
                     (self.selected == RezoHardwareUI.TARGET_FEEDBACK) &
                     self.outline(x, y, bank_panel_x0,
                                  bank_control_y0s[2] - 2,
                                  bank_panel_x1,
                                  bank_control_y0s[2] + 18, t=3))
        page_select = (
            (self.selected == RezoHardwareUI.TARGET_PAGE) &
            self.outline(text_x if self.compact_layout else x,
                         text_y if self.compact_layout else y,
                         212 if self.compact_layout else 20,
                         116 if self.compact_layout else 20,
                         364 if self.compact_layout else 196,
                         164 if self.compact_layout else 82, t=3))

        bank_selected_q = Signal()
        input_selected_q = Signal()
        routing_selected_q = Signal()
        advanced_selected_q = Signal()
        bands_selected_q = Signal()
        cross_selected_q = Signal()
        page_selected_q = Signal()
        m.d.dvi += [
            bank_selected_q.eq(preset_select | preset_group_select | band_select_q0 |
                               drive_select | dry_select | res_select | fb_select |
                               damp_select),
            input_selected_q.eq(input_select_q0),
            routing_selected_q.eq(group_select_q0 | output_select_q0 |
                                  output_side_select | cross_header_select_q0),
            advanced_selected_q.eq(
                palette_select | cross_curve_select | save_default_select),
            bands_selected_q.eq(layout_select | band_select_q0 |
                                motion_chip_select | motion_depth_select),
            cross_selected_q.eq(cross_layout_select | cross_select),
            page_selected_q.eq(page_select),
        ]
        selected = active & (bank_selected_q | input_selected_q | routing_selected_q |
                             advanced_selected_q | bands_selected_q |
                             cross_selected_q |
                             page_selected_q)

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
                                same_fill | cross_fill | dry_fill |
                                tune_cap_fill | motion_depth_fill),
            geometry_line_q0.eq(
                band_zero_q0 | bank_control_mod_marker | border),
            geometry_mod_q0.eq(band_mod_fill | bank_control_mod_fill |
                               input_meter_q0 | motion_monitor_line),
            geometry_panel_q0.eq(preset_chip | palette_chip | cross_curve_chip |
                                 save_default_chip |
                                 motion_value_chip |
                                 damp_chip | layout_chip |
                                 band_slot_q0 | output_side_chip |
                                 meter_panel | motion_depth_track),
        ]
        m.d.dvi += [
            selected_q.eq(selected),
            text_q.eq(text),
            fill_q.eq(geometry_fill_q0 |
                      input_fill_q0 | group_fill_q0 | output_fill_q0),
            line_q.eq(geometry_line_q0 | input_line_q0 |
                      group_ghost_q0),
            mod_q.eq(geometry_mod_q0),
            panel_q.eq(geometry_panel_q0 | input_panel_q0 | group_cell_q0 |
                       output_cell_q0 | cross_layout_chip),
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
    """STREZO without the SoC framebuffer path.

    This is a timing experiment for a REZO-specific HDMI path.  It keeps the
    audio filterbank in gateware and renders a small status view directly in
    the DVI pixel domain.
    """

    bitstream_help = BitstreamHelp(
        brief="STREZO linked-stereo resonant filterbank.",
        io_left=['audio / CV input', 'audio / CV input',
                 'audio / CV input', 'audio / CV input',
                 'assignable out', 'assignable out',
                 'assignable out', 'assignable out'],
        io_right=['', '', 'video out required', '', '', '']
    )
    # This design's DVI PHY placement is seed-sensitive at 720p60. Seed 7 is
    # the measured high-margin route for the optimized text renderer and
    # coarse INPUT acceleration, while the environment override remains useful
    # for place-and-route experiments.
    # The polished BANDS renderer needs a density pass plus a lower ABC9 wire
    # weight than synth_ecp5's fixed 300 ps. W=150 is the measured balance;
    # W=175 and W=200 both map over capacity. Keeping the staged commands on
    # the fragment makes generated top.ys reproduce the candidate with native
    # Yosys.
    synth_opts = "-abc9 -abc2 -run begin:map_luts"
    script_after_synth = (
        "abc; techmap -map +/lattice/latches_map.v; abc9 -W 160; clean; "
        "synth_ecp5 -abc9 -abc2 -top top -run map_cells:check; "
        "autoname; hierarchy -check; stat; check -noinit; "
        "blackbox =A:whitebox"
    )
    nextpnr_opts = (
        "--timing-allow-fail --seed "
        f"{os.getenv('TILIQUA_STREZO_SEED', os.getenv('TILIQUA_REZO_SEED', '7'))}"
    )

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
            RezoHardwareUI.STATE_WORDS_V5,
            legacy_state_words=RezoHardwareUI.STATE_WORDS_V4,
            # OFF, 1.2 Hz, 39-degree phase spread, 25% depth.
            legacy_tail_words=(0x7030, 0x0080))
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
            rezo.same_feedback.eq(ui.same_feedback),
            rezo.cross_feedback.eq(ui.cross_feedback),
            rezo.cross_curve.eq(ui.cross_curve),
            rezo.cross_layout.eq(ui.cross_layout),
            rezo.limit_knee.eq(ui.limit_knee),
            rezo.limit_cap.eq(ui.limit_cap),
            rezo.damp_mode.eq(ui.damp_mode),
            rezo.motion_source.eq(ui.motion_source),
            rezo.motion_rate.eq(ui.motion_rate),
            rezo.motion_phase.eq(ui.motion_phase),
            rezo.motion_depth.eq(ui.motion_depth),
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
        for n in range(4):
            m.d.comb += [
                rezo.output_routes[n].eq(ui.output_routes[n]),
                rezo.output_sides[n].eq(ui.output_sides[n]),
            ]
        for n in range(20):
            m.d.comb += rezo.output_sends[n].eq(ui.output_sends[n])
        for n in range(16):
            m.d.comb += rezo.cross_matrix[n].eq(ui.cross_matrix[n])

        wiring.connect(m, pmod0.o_cal, rezo.i)
        wiring.connect(m, rezo.o, audio_out_fifo.i)
        wiring.connect(m, audio_out_fifo.o, pmod0.i_cal)

        m.submodules.dvi_tgen = dvi_tgen = dvi.DVITimingGen()
        for member in dvi_tgen.timings.signature.members:
            m.d.comb += getattr(dvi_tgen.timings, member).eq(
                getattr(self.clock_settings.modeline, member))

        round_display = (
            self.clock_settings.modeline.h_active == RezoTileDisplay.PANEL_W and
            self.clock_settings.modeline.v_active == RezoTileDisplay.PANEL_H)
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
        display_cross_feedback = Signal(unsigned(8))
        display_same_feedback = Signal(unsigned(8))
        display_drive = Signal(unsigned(8))
        display_effective_drive = Signal(unsigned(8))
        display_effective_resonance = Signal(unsigned(8))
        display_effective_feedback = Signal(unsigned(8))
        display_limit_knee = Signal(unsigned(8))
        display_limit_cap = Signal(unsigned(8))
        display_input_gains = [Signal(unsigned(8), name=f"display_input_gain{n}")
                               for n in range(4)]
        display_cv_depths = [Signal(signed(8), name=f"display_cv_depth{n}")
                             for n in range(4)]
        display_input_meters = [Signal(signed(6), name=f"display_input_meter{n}")
                                for n in range(4)]
        display_motion_monitor = Signal(signed(6))
        output_send_write_index = Signal(range(20))
        output_send_array = Array(ui.output_sends)
        cross_matrix_write_index = Signal(range(16))
        cross_matrix_array = Array(ui.cross_matrix)
        cross_matrix_write_source = cross_matrix_write_index[2:4]
        cross_matrix_write_destination = cross_matrix_write_index[:2]
        cross_matrix_write_value = RezoCore.cross_coefficient(
            ui.cross_layout, cross_matrix_write_source,
            cross_matrix_write_destination,
            cross_matrix_array[cross_matrix_write_index])
        cross_matrix_display_addr = Signal(unsigned(5))
        m.d.comb += cross_matrix_display_addr.eq(
            cross_matrix_write_index + cross_matrix_write_index[2:4])
        m.d.comb += [
            display_drive.eq((RezoCore.DRIVE_FLOOR + rezo.drive) >> 8),
            display_effective_drive.eq(rezo.effective_drive >> 8),
            display_resonance.eq(rezo.resonance >> 8),
            display_feedback.eq(rezo.feedback >> 8),
            # Render the user-facing positions, not the safety-scaled DSP
            # coefficients, so both faders retain their full visual travel.
            display_same_feedback.eq(ui.same_feedback),
            display_cross_feedback.eq(ui.cross_feedback),
            display_effective_resonance.eq(rezo.effective_resonance >> 8),
            display_effective_feedback.eq(rezo.effective_feedback >> 8),
            display_limit_knee.eq(rezo.limit_knee >> 8),
            display_limit_cap.eq(rezo.limit_cap >> 8),
        ]
        for n in range(4):
            m.d.comb += display_input_gains[n].eq(rezo.input_gains[n] >> 8)
        for n in range(4):
            m.d.comb += display_cv_depths[n].eq(rezo.cv_depths[n] >> 8)
            m.d.sync += display_input_meters[n].eq(rezo.input_meters[n] >> 10)
        m.d.sync += display_motion_monitor.eq(rezo.motion_monitor)
        m.d.comb += [
            # OUTPUT and CROSS are never visible simultaneously, so their
            # identically shaped grids share one display BRAM. Refresh the
            # visible page in at most twenty 60 MHz clocks; this removes a
            # BRAM-output mux from the 74.25 MHz pixel path.
            display.output_send_write_addr.eq(Mux(
                ui.page == 7, cross_matrix_display_addr,
                output_send_write_index)),
            display.output_send_write_data.eq(Mux(
                ui.page == 7,
                cross_matrix_write_value,
                output_send_array[output_send_write_index])),
            display.output_send_write_en.eq(1),
        ]
        with m.If(output_send_write_index == 19):
            m.d.sync += output_send_write_index.eq(0)
        with m.Else():
            m.d.sync += output_send_write_index.eq(output_send_write_index + 1)
        with m.If(cross_matrix_write_index == 15):
            m.d.sync += cross_matrix_write_index.eq(0)
        with m.Else():
            m.d.sync += cross_matrix_write_index.eq(
                cross_matrix_write_index + 1)
        m.submodules += [
            FFSynchronizer(i=display_drive, o=display.drive, o_domain="dvi"),
            FFSynchronizer(i=display_effective_drive,
                           o=display.effective_drive, o_domain="dvi"),
            FFSynchronizer(i=display_resonance, o=display.resonance, o_domain="dvi"),
            FFSynchronizer(i=display_feedback, o=display.feedback, o_domain="dvi"),
            FFSynchronizer(i=display_same_feedback,
                           o=display.same_feedback, o_domain="dvi"),
            FFSynchronizer(i=display_cross_feedback,
                           o=display.cross_feedback, o_domain="dvi"),
            FFSynchronizer(i=display_effective_resonance, o=display.effective_resonance, o_domain="dvi"),
            FFSynchronizer(i=display_effective_feedback, o=display.effective_feedback, o_domain="dvi"),
            FFSynchronizer(i=display_limit_knee, o=display.limit_knee, o_domain="dvi"),
            FFSynchronizer(i=display_limit_cap, o=display.limit_cap, o_domain="dvi"),
            FFSynchronizer(i=display_motion_monitor,
                           o=display.motion_monitor, o_domain="dvi"),
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
            display.cross_layout.eq(ui.cross_layout),
            display.cross_layout_preview.eq(ui.cross_layout_preview),
            display.cross_curve.eq(ui.cross_curve),
            display.motion_source.eq(ui.motion_source),
            display.motion_rate.eq(ui.motion_rate),
            display.motion_phase.eq(ui.motion_phase),
            display.motion_depth.eq(ui.motion_depth),
        ]
        for n in range(4):
            m.d.comb += display.output_sides[n].eq(ui.output_sides[n])
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
                i=display_input_meters[n], o=display.input_meters[n],
                o_domain="dvi")
        for n in range(RezoCore.N_BANDS):
            m.submodules += FFSynchronizer(
                i=ui.bank_groups[n], o=display.bank_groups[n], o_domain="dvi")
            m.submodules += FFSynchronizer(
                i=ui.feedback_sends[n], o=display.feedback_sends[n], o_domain="dvi")
            m.d.dvi += display.band_enables[n].eq(ui.band_enables[n])
            m.d.comb += display.band_frequencies[n].eq(ui.band_frequencies[n])
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


def run_cli(*, name="STREZO", artifact_name=None, modeline=None):
    this_path = os.path.dirname(os.path.realpath(__file__))

    def configure_parser(parser):
        defaults = {"name": name, "artifact_name": artifact_name}
        if modeline is not None:
            defaults["modeline"] = modeline
        parser.set_defaults(**defaults)

    top_level_cli(
        RezoBeamTop, path=this_path,
        argparse_callback=configure_parser,
        archiver_callback=lambda archiver: archiver.with_option_storage())


if __name__ == "__main__":
    run_cli(
        name=os.getenv("TILIQUA_REZO_FAMILY_NAME", "STREZO"),
        artifact_name=os.getenv("TILIQUA_REZO_FAMILY_ARTIFACT_NAME") or None,
        modeline=os.getenv("TILIQUA_REZO_FAMILY_MODELINE") or None,
    )
