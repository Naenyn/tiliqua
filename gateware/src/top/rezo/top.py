# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0
"""
REZOMO is a clock-oriented Graphic Resonant Filterbank-inspired Tiliqua
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
from amaranth.lib.wiring import In, Out
from luna_soc.gateware.core import spiflash

from amaranth_future import fixed

from tiliqua import dsp
from tiliqua.build import sim
from tiliqua.build.cli import top_level_cli
from tiliqua.build.types import BitstreamHelp
from tiliqua.dsp import ASQ
from tiliqua.periph import encoder, eurorack_pmod
from tiliqua.platform import RebootProvider
from tiliqua.video import dvi
try:
    from .display_common import (
        FONT_5X7, PALETTE_ROLES, RGB_PALETTES, SEMANTIC_PALETTE,
        TILE_CHARS,
    )
    from .encoder_acceleration import progressive_edit_level
    from .persistence import RezoStateJournal, SPIFlashTransfer
    from .ui_common import (
        BASE_TARGET_NAMES, COMMON_PAGE_TITLES, DAMP_NAMES, LAYOUT_NAMES,
        NAV_NAMES, PALETTE_NAMES, SAVE_NAMES, format_frequency_name,
        NATIVE_FEEDBACK_AMOUNT_Y0, NATIVE_FEEDBACK_CEILING_Y0,
        NATIVE_FEEDBACK_TRACK_X0, NATIVE_FEEDBACK_TRACK_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_X0, NATIVE_FEEDBACK_DAMPING_CHIP_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_Y0, NATIVE_FEEDBACK_DAMPING_CHIP_Y1,
        NATIVE_FEEDBACK_DAMPING_TEXT_COL, NATIVE_FEEDBACK_DAMPING_TEXT_ROW,
        NATIVE_FEEDBACK_KNEE_Y0, NATIVE_GROUP_CENTERS,
        NATIVE_GROUP_TEXT_ROWS, NATIVE_INPUT_TEXT_ROWS,
        NATIVE_CONTENT_PANEL_X0, NATIVE_CONTENT_PANEL_X1,
        NATIVE_CONTENT_PANEL_Y0, NATIVE_CONTENT_PANEL_Y1,
        NATIVE_INPUT_FILL_X0, NATIVE_INPUT_FILL_X1,
        NATIVE_INPUT_PANEL_Y0, NATIVE_INPUT_PANEL_Y1,
        NATIVE_MAIN_FILL_X0, NATIVE_MAIN_FILL_X1,
        NATIVE_MAIN_CONTROL_TEXT_ROWS, NATIVE_MAIN_CONTROL_Y0S,
        NATIVE_OUTPUT_COL_CENTERS, NATIVE_OUTPUT_ROW_CENTERS,
        NATIVE_OUTPUT_TEXT_ROWS,
        add_feedback_navigation, add_group_navigation, add_input_navigation,
        native_input_depth_endpoint, native_input_gain_endpoint,
        native_input_unity_x,
        native_feedback_track_rows, output_header_selection,
        put_legacy_support_page_labels, put_native_page_headers,
        put_native_support_page_labels,
    )
except ImportError:  # top_level_cli executes this file directly.
    from display_common import (
        FONT_5X7, PALETTE_ROLES, RGB_PALETTES, SEMANTIC_PALETTE,
        TILE_CHARS,
    )
    from encoder_acceleration import progressive_edit_level
    from persistence import RezoStateJournal, SPIFlashTransfer
    from ui_common import (
        BASE_TARGET_NAMES, COMMON_PAGE_TITLES, DAMP_NAMES, LAYOUT_NAMES,
        NAV_NAMES, PALETTE_NAMES, SAVE_NAMES, format_frequency_name,
        NATIVE_FEEDBACK_AMOUNT_Y0, NATIVE_FEEDBACK_CEILING_Y0,
        NATIVE_FEEDBACK_TRACK_X0, NATIVE_FEEDBACK_TRACK_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_X0, NATIVE_FEEDBACK_DAMPING_CHIP_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_Y0, NATIVE_FEEDBACK_DAMPING_CHIP_Y1,
        NATIVE_FEEDBACK_DAMPING_TEXT_COL, NATIVE_FEEDBACK_DAMPING_TEXT_ROW,
        NATIVE_FEEDBACK_KNEE_Y0, NATIVE_GROUP_CENTERS,
        NATIVE_GROUP_TEXT_ROWS, NATIVE_INPUT_TEXT_ROWS,
        NATIVE_CONTENT_PANEL_X0, NATIVE_CONTENT_PANEL_X1,
        NATIVE_CONTENT_PANEL_Y0, NATIVE_CONTENT_PANEL_Y1,
        NATIVE_INPUT_FILL_X0, NATIVE_INPUT_FILL_X1,
        NATIVE_INPUT_PANEL_Y0, NATIVE_INPUT_PANEL_Y1,
        NATIVE_MAIN_FILL_X0, NATIVE_MAIN_FILL_X1,
        NATIVE_MAIN_CONTROL_TEXT_ROWS, NATIVE_MAIN_CONTROL_Y0S,
        NATIVE_OUTPUT_COL_CENTERS, NATIVE_OUTPUT_ROW_CENTERS,
        NATIVE_OUTPUT_TEXT_ROWS,
        add_feedback_navigation, add_group_navigation, add_input_navigation,
        native_input_depth_endpoint, native_input_gain_endpoint,
        native_input_unity_x,
        native_feedback_track_rows, output_header_selection,
        put_legacy_support_page_labels, put_native_page_headers,
        put_native_support_page_labels,
    )


class RezoCore(wiring.Component):
    """Ten-band mono resonant filterbank."""

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
    INPUT_MODE_AUDIO = 0
    INPUT_MODE_CV = 1
    CV_TARGET_FEEDBACK = 0
    CV_TARGET_RESONANCE = 1
    CV_TARGET_DRIVE = 2
    CV_TARGET_GROUP_BASE = 3
    CV_TARGET_CLOCK = 7
    CV_TARGET_RESET = 8
    CV_TARGET_DATA = 9
    CV_TARGET_LOCK = 10
    CV_TARGET_MAX = CV_TARGET_LOCK
    N_GROUPS = 4
    SHIFT_FORWARD = 0
    SHIFT_BACKWARD = 1
    SHIFT_PING_PONG = 2
    SHIFT_RANDOM = 3
    CLOCK_ALGORITHM_SHIFT = 0
    CLOCK_ALGORITHM_ROTATE = 1
    CLOCK_ALGORITHM_TURING = 2
    CLOCK_ALGORITHM_WALK = 3
    CLOCK_SOURCE_AUTO = 0
    CLOCK_SOURCE_INTERNAL = 1
    CLOCK_SOURCE_EXTERNAL = 2
    DATA_SOURCE_CV = 0
    DATA_SOURCE_RANDOM = 1
    DATA_SOURCE_AUTO = 2
    TURING_TARGET_ALL = 0
    TURING_TARGET_RANGE = 1
    # The internal clock is continuously adjustable. Keep the former eight
    # choices only for importing already-saved version-3 records, where the
    # three-bit field held an index and the following six padding bits were 0.
    LEGACY_INTERNAL_CLOCK_BPMS = (15, 30, 45, 60, 90, 120, 180, 240)
    INTERNAL_CLOCK_MIN_BPM = 15
    INTERNAL_CLOCK_MAX_BPM = 300
    INTERNAL_CLOCK_DEFAULT = 120
    WALK_STEPS = (256, 512, 1024, 2048, 4096)
    WALK_STEP_DEFAULT = WALK_STEPS.index(1024)
    WALK_STYLE_ALL = 0
    WALK_STYLE_HEAD = 1
    WALK_DRUNK_DEFAULT = 0
    WALK_CHANCES = (0, 26, 64, 128, 192, 255)
    WALK_CHANCE_DEFAULT = 2
    WALK_LIMIT = 16384
    CLOCK_HIGH_THRESHOLD = 4096
    CLOCK_LOW_THRESHOLD = 1024
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

    def __init__(self, fs=48_000, internal_clock_periods=None):
        # REZO's UI coefficients, limiter rails, and feedback tuning use the
        # native 16-bit Q1.15 codec scale.  Building it with another bitstream's
        # ASQ override changes the numeric meaning of every one of those
        # constants while still producing a syntactically valid bitstream.
        if ASQ.as_shape().width != 16 or ASQ.i_bits != 1:
            raise ValueError("REZO requires the default 16-bit Q1.15 ASQ format")
        self.fs = fs
        if internal_clock_periods is None:
            internal_clock_periods = tuple(
                max(1, round(fs * 60 / bpm))
                for bpm in range(self.INTERNAL_CLOCK_MIN_BPM,
                                 self.INTERNAL_CLOCK_MAX_BPM + 1))
        if len(internal_clock_periods) != (
                self.INTERNAL_CLOCK_MAX_BPM -
                self.INTERNAL_CLOCK_MIN_BPM + 1):
            raise ValueError("one internal clock period is required per BPM")
        self.internal_clock_periods = tuple(internal_clock_periods)
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
        self.limit_knee = Signal(unsigned(16), init=8192)
        self.limit_cap = Signal(unsigned(16), init=28672)
        self.damp_mode = Signal(unsigned(3), init=3)
        self.input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n == 0 else 0)
                            for n in range(4)]
        self.input_modes = [Signal(init=0 if n == 0 else 1, name=f"input_mode{n}")
                            for n in range(4)]
        self.cv_targets = [Signal(unsigned(4), init=(1, 8, 9, 7)[n], name=f"cv_target{n}")
                           for n in range(4)]
        self.cv_depths = [Signal(signed(16), init=0, name=f"cv_depth{n}")
                          for n in range(4)]
        # Display-only input telemetry. Audio inputs report their post-VALUE
        # peak envelope; CV inputs report the raw, pre-DEPTH bipolar sample.
        self.input_meters = [Signal(signed(16), name=f"input_meter{n}")
                             for n in range(4)]
        self.clock_mode = Signal(init=0)
        self.clock_algorithm = Signal(unsigned(2),
                                      init=self.CLOCK_ALGORITHM_SHIFT)
        self.shift_direction = Signal(unsigned(2), init=self.SHIFT_FORWARD)
        self.turing_length = Signal(unsigned(4), init=self.N_BANDS)
        self.turing_change = Signal(unsigned(8), init=32)
        self.turing_target = Signal(init=self.TURING_TARGET_ALL)
        self.turing_start = Signal(range(self.N_BANDS), init=0)
        # Clock modulation depth uses the same 0..128 control resolution as
        # the other full-width faders. 128 is unity gain.
        self.clock_depth = Signal(unsigned(8), init=128)
        self.walk_step_index = Signal(
            range(len(self.WALK_STEPS)), init=self.WALK_STEP_DEFAULT)
        self.walk_style = Signal(init=self.WALK_STYLE_ALL)
        self.walk_drunk = Signal(unsigned(2), init=self.WALK_DRUNK_DEFAULT)
        self.walk_chance_index = Signal(
            range(len(self.WALK_CHANCES)), init=self.WALK_CHANCE_DEFAULT)
        self.clock_source = Signal(unsigned(2), init=self.CLOCK_SOURCE_AUTO)
        self.data_source = Signal(unsigned(2), init=self.DATA_SOURCE_CV)
        self.internal_clock_rate = Signal(
            range(self.INTERNAL_CLOCK_MIN_BPM,
                  self.INTERNAL_CLOCK_MAX_BPM + 1),
            init=self.INTERNAL_CLOCK_DEFAULT)
        self.input_jacks = Signal(unsigned(4))
        self.clock_external_active = Signal()
        self.data_random_active = Signal()
        self.clock_modulations = [Signal(signed(16), init=0,
                                         name=f"clock_modulation{n}")
                                  for n in range(self.N_BANDS)]
        self.clock_scaled_modulations = [
            Signal(signed(16), name=f"clock_scaled_modulation{n}")
            for n in range(self.N_BANDS)]
        self.bank_groups = [Signal(unsigned(4), init=1 << min(n // 3, 3), name=f"bank_group{n}")
                            for n in range(self.N_BANDS)]
        self.feedback_sends = [Signal(init=1, name=f"feedback_send{n}")
                               for n in range(self.N_BANDS)]
        # Route bits mirror non-zero sends for display/inspection. The actual
        # mix is controlled by the five G1..G4/DRY send levels below.
        self.output_routes = [Signal(unsigned(5), init=route, name=f"output_route{n}")
                              for n, route in enumerate((0b01111, 0b00101,
                                                         0b01010, 0b10000))]
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
        level_targets = [Signal(signed(16), name=f"level_target{n}")
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
        clock_scaled_modulations = self.clock_scaled_modulations
        for n in range(self.N_BANDS):
            # BANK and captured CV each occupy at most half the signed sample
            # range, so their sum fits exactly in signed 16 bits. The existing
            # effective-level clamp after group CV remains the audio/display
            # boundary; clamping here only adds a long redundant mux chain to
            # the 60 MHz parameter-slew path.
            # Register the UI/CV target before the slew subtractor. This
            # breaks the former UI-level-to-smoother critical path while only
            # adding one 60 MHz control tick to an already-slewed parameter.
            m.d.sync += level_targets[n].eq(
                self.levels[n] + Mux(
                    self.clock_mode, clock_scaled_modulations[n], 0))
            m.d.comb += level_diffs[n].eq(
                level_targets[n] - smooth_levels[n])
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
        state_cv_route_commit = 15
        state_output_route_commit = 16
        state_input_limit_commit = 17
        state_output_limit_commit = 18
        state_mac2_apply = 19
        state_input_gain_add = 20
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
        input_mix_sample = Signal(ASQ)
        input_mix_limited = Signal(ASQ)
        input_gain_magnitude = Signal(unsigned(21))
        input_gain_meter_sample = Signal(unsigned(16))
        drive_term = Signal(signed(18))
        drive_term_q = Signal(signed(18))
        input_samples = [Signal(ASQ, name=f"input_sample{n}") for n in range(4)]
        current_inputs = Array(
            self.i.payload[n].as_value().as_signed() for n in range(4))
        clock_sample = Signal(signed(16))
        reset_sample = Signal(signed(16))
        data_sample = Signal(signed(16))
        data_jack_patched = Signal()
        data_random_requested = Signal()
        sampled_modulation = Signal(signed(16))
        clock_high = Signal()
        clock_mode_q = Signal()
        clock_external_active_q = Signal()
        internal_clock_rate_q = Signal.like(self.internal_clock_rate,
                                            init=self.INTERNAL_CLOCK_DEFAULT)
        internal_clock_periods = self.internal_clock_periods
        internal_clock_counter = Signal(
            range(max(internal_clock_periods)),
            init=0)
        internal_clock_period = Signal.like(
            internal_clock_counter,
            init=internal_clock_periods[
                self.INTERNAL_CLOCK_DEFAULT -
                self.INTERNAL_CLOCK_MIN_BPM] - 1)
        # A 15..300 BPM table is large enough that a block ROM is both smaller
        # and faster than a divider or a 286-way LUT mux. Its one-cycle read
        # latency is immaterial beside encoder and accepted-audio timing.
        m.submodules.internal_clock_period_mem = internal_clock_period_mem = \
            Memory(shape=internal_clock_counter.shape(),
                   depth=len(internal_clock_periods),
                   init=[period - 1 for period in internal_clock_periods],
                   attrs={"ram_style": "block"})
        internal_clock_period_rport = internal_clock_period_mem.read_port()
        clock_jack_patched = Signal()
        clock_external_requested = Signal()
        clock_source_changed = Signal()
        clock_mode_changed = Signal()
        internal_clock_rate_changed = Signal()
        clock_pulse = Signal()
        clock_algorithm_q = Signal(unsigned(2),
                                   init=self.CLOCK_ALGORITHM_SHIFT)
        walk_style_q = Signal(init=self.WALK_STYLE_ALL)
        turing_length_q = Signal(unsigned(4), init=self.N_BANDS)
        turing_target_q = Signal(init=self.TURING_TARGET_ALL)
        turing_start_q = Signal.like(self.turing_start)
        rotate_seeded = Signal()
        rotate_origins = [Signal(range(self.N_BANDS), init=n,
                                 name=f"rotate_origin{n}")
                          for n in range(self.N_BANDS)]
        rotate_snapshot_origins = [Signal(range(self.N_BANDS),
                                          name=f"rotate_snapshot_origin{n}")
                                   for n in range(self.N_BANDS)]
        rotate_pending = Signal()
        rotate_searching = Signal()
        rotate_scan_index = Signal(range(self.N_BANDS))
        rotate_carry_origin = Signal(range(self.N_BANDS))
        rotate_worker_forward = Signal(init=1)
        walk_pending = Signal()
        walk_index = Signal(range(self.N_BANDS))
        walk_cursor = Signal(range(self.N_BANDS))
        walk_head_direction = Signal()
        walk_head_next_index = Signal(range(self.N_BANDS))
        walk_target_index = Signal(range(self.N_BANDS))
        walk_head_landing = Signal()
        walk_write_enable = Signal()
        walk_write_value = Signal(signed(16))
        walk_burst_remaining = Signal(unsigned(2))
        # Burst timing only needs musical, not sample-exact, resolution. Store
        # the quarter interval in units of 16 audio samples; this trims the
        # scheduler while retaining sub-0.1 ms precision at 192 kHz.
        walk_burst_period = Signal(unsigned(
            max(1, internal_clock_counter.shape().width - 6)))
        walk_burst_quarter = Signal.like(internal_clock_counter)
        walk_burst_elapsed = Signal(unsigned(
            max(1, internal_clock_counter.shape().width - 4)))
        walk_burst_threshold = Signal(unsigned(
            max(1, internal_clock_counter.shape().width - 4)))
        walk_burst_phase = Signal(unsigned(2))
        external_interval_seen = Signal()
        walk_burst_pulse = Signal()
        walk_chance_threshold = Signal(unsigned(8))
        walk_random_bits = Signal(unsigned(self.N_BANDS), init=0x155)
        # WALK always starts at zero and moves in multiples of 256, so its
        # low byte contains no information.  Perform the reflected walk in
        # compact high-byte units and expand only when writing the modulation
        # vector.  This preserves the exact Q1.15 values while substantially
        # reducing the adder and comparison logic in this congested design.
        walk_step_value = Signal(signed(9))
        walk_value = Signal(signed(9))
        walk_upper_turn = Signal(signed(9))
        walk_lower_turn = Signal(signed(9))
        walk_add = Signal()
        walk_next = Signal(signed(9))
        ping_pong_forward = Signal(init=1)
        ping_pong_steps = Signal(range(self.N_BANDS + 1))
        enabled_band_count = Signal(range(self.N_BANDS + 1))
        shift_lfsr = Signal(unsigned(16), init=0xACE1)
        # SHIFT and WALK make wide pattern updates from the accepted clock
        # sample. Start those two algorithms one control cycle later so live
        # INPUT role/source decoding does not sit in their update cones.
        shift_pending = Signal()
        shift_sample = Signal(signed(16))
        walk_clock_pending = Signal()
        walk_clock_interval = Signal.like(walk_burst_quarter)
        walk_clock_interval_seen = Signal()
        # Independent broadband DATA source. Advancing at the accepted audio
        # sample rate makes a clock pulse genuinely sample the running noise,
        # while a 32-bit maximal-length sequence avoids the short audible
        # repetition of a 16-bit generator at 192 kHz.
        data_lfsr = Signal(unsigned(32), init=0x6D2B79F5)
        lock_sample = Signal(signed(16))
        lock_high = Signal()
        turing_seeded = Signal()
        turing_fill_count = Signal(range(self.N_BANDS + 1))
        # The private TURING loop is accessed sequentially, so a tiny block RAM
        # is substantially cheaper than ten registers behind two wide dynamic
        # muxes. Its synchronous read adds control cycles, not audio latency:
        # even a ten-step update completes well inside one 192 kHz sample.
        m.submodules.turing_pattern_mem = turing_pattern_mem = Memory(
            shape=signed(16), depth=16, init=[0] * 16,
            attrs={"ram_style": "block"})
        turing_pattern_rport = turing_pattern_mem.read_port()
        turing_pattern_wport = turing_pattern_mem.write_port()
        turing_pending = Signal()
        turing_starting = Signal()
        turing_read_wait = Signal()
        turing_scan_index = Signal(range(self.N_BANDS))
        turing_search_count = Signal(range(self.N_BANDS + 1))
        turing_carry = Signal(signed(16))
        turing_worker_forward = Signal(init=1)
        turing_effective_length = Signal(range(self.N_BANDS + 1))
        turing_mutate = Signal()
        turing_map_pending = Signal()
        turing_map_priming = Signal()
        turing_map_index = Signal(range(self.N_BANDS))
        turing_map_pattern_index = Signal(range(self.N_BANDS))
        turing_clear_pending = Signal()
        turing_clear_index = Signal(range(self.N_BANDS))
        clock_scale_index = Signal(range(self.N_BANDS))
        clock_scale_product = Signal(signed(24))
        cv_product = Signal(signed(18))
        cv_product_q = Signal(signed(18))
        cv_acc = Signal(signed(20))
        cv_acc_next = Signal(signed(20))
        bank_group_array = Array(self.bank_groups)
        band_enable_array = Array(self.band_enables)
        clock_modulation_array = Array(self.clock_modulations)
        clock_scaled_modulation_array = Array(clock_scaled_modulations)
        natural_level_array = Array(self.levels)
        rotate_origin_array = Array(rotate_origins)
        rotate_snapshot_origin_array = Array(rotate_snapshot_origins)
        feedback_send_array = Array(self.feedback_sends)
        output_send_array = Array(self.output_sends)
        # Accumulate each group once while the bands are being processed, then
        # traverse the 4x5 send matrix after the final band.  Routing every
        # band through every output consumed 120 clocks/sample by itself and
        # exceeded the 312-clock budget at 192 kHz.
        output_sources = Array([
            *group_acc,
            input_mix_sample.as_value().as_signed(),
        ])
        output_source_signal = Signal(mix_shape)
        input_mode_array = Array(self.input_modes)
        cv_target_array = Array(self.cv_targets)
        clock_role_flags = [
            self.clock_mode &
            (self.input_modes[n] == self.INPUT_MODE_CV) &
            (self.cv_targets[n] >= self.CV_TARGET_CLOCK)
            for n in range(4)
        ]
        clock_role_array = Array(clock_role_flags)
        input_audio_enabled = Array(
            (self.input_modes[n] == self.INPUT_MODE_AUDIO) &
            ~clock_role_flags[n]
            for n in range(4))
        m.d.sync += internal_clock_period.eq(internal_clock_period_rport.data)
        m.d.comb += [
            clock_sample.eq(0),
            clock_jack_patched.eq(0),
            reset_sample.eq(0),
            data_sample.eq(0),
            data_jack_patched.eq(0),
            lock_sample.eq(0),
            sampled_modulation.eq(Mux(
                data_random_requested,
                data_lfsr.as_signed() >> 1,
                data_sample >> 1)),
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
            enabled_term.eq(Mux(band_enable_array[band], term_q, 0)),
            main_next.eq(main_acc + enabled_term),
            filtered_next.eq(main_next - dry_sample.as_value().as_signed()),
            feedback_drive.eq(feedback_acc),
            cv_product.eq(mac_z.as_value().as_signed() >> dsp.mac.SQNative.f_bits),
            cv_acc_next.eq(cv_acc),
            enabled_band_count.eq(sum(self.band_enables)),
            turing_effective_length.eq(Mux(
                self.turing_target == self.TURING_TARGET_ALL,
                self.turing_length,
                Mux(self.turing_length < self.N_BANDS - self.turing_start,
                    self.turing_length,
                    self.N_BANDS - self.turing_start))),
            turing_mutate.eq(
                ~turing_seeded | (~lock_high &
                    ((self.turing_change == 255) |
                     (shift_lfsr[:8] < self.turing_change)))),
            walk_step_value.eq(Array(
                Const(value >> 8, signed(9)) for value in self.WALK_STEPS
            )[self.walk_step_index]),
            walk_target_index.eq(Mux(
                self.walk_style == self.WALK_STYLE_HEAD,
                walk_head_next_index, walk_index)),
            walk_head_landing.eq(
                (self.walk_style == self.WALK_STYLE_HEAD) &
                band_enable_array[walk_head_next_index]),
            walk_write_enable.eq(
                walk_pending &
                ((self.walk_style == self.WALK_STYLE_ALL) |
                 walk_head_landing)),
            walk_write_value.eq(Mux(
                (self.walk_style == self.WALK_STYLE_ALL) &
                ~band_enable_array[walk_index],
                0, Cat(Const(0, 8), walk_next[:8]))),
            walk_value.eq(
                clock_modulation_array[walk_target_index][8:16].as_signed()),
            walk_upper_turn.eq((self.WALK_LIMIT >> 8) - walk_step_value),
            walk_lower_turn.eq(-(self.WALK_LIMIT >> 8) + walk_step_value),
            walk_add.eq(
                (Mux(self.walk_style == self.WALK_STYLE_HEAD,
                     walk_random_bits[3], walk_random_bits[0]) &
                 (walk_value < walk_upper_turn)) |
                (~Mux(self.walk_style == self.WALK_STYLE_HEAD,
                      walk_random_bits[3], walk_random_bits[0]) &
                 (walk_value <= walk_lower_turn))),
            walk_next.eq(walk_value + Mux(
                walk_add, walk_step_value, -walk_step_value)),
            walk_chance_threshold.eq(Array(
                Const(value, unsigned(8)) for value in self.WALK_CHANCES
            )[self.walk_chance_index]),
            walk_burst_quarter.eq(
                Mux(clock_external_active_q,
                    internal_clock_counter, internal_clock_period) >> 2),
            walk_burst_elapsed.eq(internal_clock_counter >> 4),
            walk_burst_phase.eq(
                self.walk_drunk - walk_burst_remaining),
            walk_burst_pulse.eq(
                self.clock_mode &
                (self.clock_algorithm == self.CLOCK_ALGORITHM_WALK) &
                (self.walk_style == self.WALK_STYLE_HEAD) &
                (walk_burst_remaining != 0) &
                (walk_burst_elapsed >= walk_burst_threshold)),
            clock_scale_product.eq(
                clock_modulation_array[clock_scale_index] *
                self.clock_depth),
            internal_clock_period_rport.addr.eq(
                self.internal_clock_rate - self.INTERNAL_CLOCK_MIN_BPM),
            clock_external_requested.eq(
                (self.clock_source == self.CLOCK_SOURCE_EXTERNAL) |
                ((self.clock_source == self.CLOCK_SOURCE_AUTO) &
                 clock_jack_patched)),
            data_random_requested.eq(
                (self.data_source == self.DATA_SOURCE_RANDOM) |
                ((self.data_source == self.DATA_SOURCE_AUTO) &
                 ~data_jack_patched)),
            clock_source_changed.eq(
                clock_external_requested != clock_external_active_q),
            clock_mode_changed.eq(self.clock_mode != clock_mode_q),
            internal_clock_rate_changed.eq(
                self.internal_clock_rate != internal_clock_rate_q),
            clock_pulse.eq(
                self.clock_mode & ~clock_mode_changed &
                ~clock_source_changed & ~internal_clock_rate_changed &
                Mux(clock_external_active_q,
                    ~clock_high &
                    (clock_sample >= self.CLOCK_HIGH_THRESHOLD),
                    internal_clock_counter == internal_clock_period)),
            self.clock_external_active.eq(clock_external_active_q),
        ]
        # This output exists only to annotate the CLOCK page. Register it
        # before the DVI-domain synchronizer so the display crossing does not
        # inherit the input-routing/data-source combinational cone.
        m.d.sync += self.data_random_active.eq(data_random_requested)
        with m.Switch(walk_burst_phase):
            with m.Case(0):
                m.d.comb += walk_burst_threshold.eq(walk_burst_period)
            with m.Case(1):
                m.d.comb += walk_burst_threshold.eq(
                    walk_burst_period << 1)
            with m.Default():
                m.d.comb += walk_burst_threshold.eq(
                    walk_burst_period + (walk_burst_period << 1))
        # Reflect the spatial cursor at the first and last physical bands.
        # Disabled bands are skipped by the sequential worker below.
        with m.If(walk_head_direction):
            m.d.comb += walk_head_next_index.eq(Mux(
                walk_index == self.N_BANDS - 1,
                self.N_BANDS - 2, walk_index + 1))
        with m.Else():
            m.d.comb += walk_head_next_index.eq(Mux(
                walk_index == 0, 1, walk_index - 1))
        # CLOCK roles are ordinary INPUT-page CV targets. If a role is absent
        # its sample remains zero; if it is assigned more than once, the
        # highest-numbered input wins deterministically.
        for n in range(4):
            with m.If(self.clock_mode &
                      (self.input_modes[n] == self.INPUT_MODE_CV)):
                with m.Switch(self.cv_targets[n]):
                    with m.Case(self.CV_TARGET_CLOCK):
                        m.d.comb += [
                            clock_sample.eq(current_inputs[n]),
                            clock_jack_patched.eq(self.input_jacks[n]),
                        ]
                    with m.Case(self.CV_TARGET_RESET):
                        m.d.comb += reset_sample.eq(current_inputs[n])
                    with m.Case(self.CV_TARGET_DATA):
                        m.d.comb += [
                            data_sample.eq(current_inputs[n]),
                            data_jack_patched.eq(self.input_jacks[n]),
                        ]
                    with m.Case(self.CV_TARGET_LOCK):
                        m.d.comb += lock_sample.eq(current_inputs[n])
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
                  ~clock_role_array[cv_chan] &
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
            self.i.ready.eq((state == state_wait) & out_ready &
                            ~shift_pending & ~walk_clock_pending &
                            ~rotate_pending & ~walk_pending & ~turing_pending &
                            ~turing_map_pending & ~turing_clear_pending),
            turing_pattern_wport.en.eq(0),
            turing_pattern_wport.addr.eq(0),
            turing_pattern_wport.data.eq(0),
        ]

        with m.If(self.o.ready):
            m.d.sync += out_valid.eq(0)

        with m.If(shift_pending):
            m.d.sync += [
                shift_pending.eq(0),
                rotate_seeded.eq(0),
                shift_lfsr.eq(Cat(
                    shift_lfsr[1:],
                    shift_lfsr[0] ^ shift_lfsr[2] ^
                    shift_lfsr[3] ^ shift_lfsr[5])),
            ]
            with m.Switch(self.shift_direction):
                with m.Case(self.SHIFT_BACKWARD):
                    for n in range(self.N_BANDS - 1):
                        m.d.sync += self.clock_modulations[n].eq(
                            self.clock_modulations[n + 1])
                    m.d.sync += self.clock_modulations[-1].eq(shift_sample)
                with m.Case(self.SHIFT_RANDOM):
                    with m.If(shift_lfsr[0]):
                        for n in range(self.N_BANDS - 1, 0, -1):
                            m.d.sync += self.clock_modulations[n].eq(
                                self.clock_modulations[n - 1])
                        m.d.sync += self.clock_modulations[0].eq(shift_sample)
                    with m.Else():
                        for n in range(self.N_BANDS - 1):
                            m.d.sync += self.clock_modulations[n].eq(
                                self.clock_modulations[n + 1])
                        m.d.sync += self.clock_modulations[-1].eq(shift_sample)
                with m.Default():
                    for n in range(self.N_BANDS - 1, 0, -1):
                        m.d.sync += self.clock_modulations[n].eq(
                            self.clock_modulations[n - 1])
                    m.d.sync += self.clock_modulations[0].eq(shift_sample)

        with m.If(walk_clock_pending):
            m.d.sync += [
                walk_clock_pending.eq(0),
                rotate_seeded.eq(0),
                walk_random_bits.eq(shift_lfsr),
                shift_lfsr.eq(Cat(
                    shift_lfsr[1:],
                    shift_lfsr[0] ^ shift_lfsr[2] ^
                    shift_lfsr[3] ^ shift_lfsr[5])),
            ]
            with m.If(self.walk_style == self.WALK_STYLE_HEAD):
                with m.If(enabled_band_count != 0):
                    m.d.sync += [
                        walk_pending.eq(1),
                        walk_index.eq(walk_cursor),
                        walk_head_direction.eq(shift_lfsr[2]),
                    ]
                with m.If(
                        (enabled_band_count != 0) &
                        (self.walk_drunk != 0) &
                        (~clock_external_active_q | walk_clock_interval_seen) &
                        ((walk_chance_threshold == 255) |
                         (shift_lfsr[8:16] < walk_chance_threshold))):
                    m.d.sync += [
                        walk_burst_remaining.eq(self.walk_drunk),
                        walk_burst_period.eq(walk_clock_interval >> 4),
                    ]
                with m.Else():
                    m.d.sync += walk_burst_remaining.eq(0)
            with m.Else():
                m.d.sync += [
                    walk_pending.eq(1),
                    walk_index.eq(0),
                    walk_burst_remaining.eq(0),
                ]

        # One small shared multiplier scales all ten raw clock values in ten
        # control cycles. Pattern state remains full resolution, so changing
        # DEPTH is reversible and affects SHIFT, ROTATE, and TURING equally.
        m.d.sync += clock_scaled_modulation_array[clock_scale_index].eq(
            clock_scale_product >> 7)
        with m.If(clock_scale_index == self.N_BANDS - 1):
            m.d.sync += clock_scale_index.eq(0)
        with m.Else():
            m.d.sync += clock_scale_index.eq(clock_scale_index + 1)

        # WALK shares one compact add/reflect path. ALL visits every band after
        # each clock. HEAD instead searches one spatial stride among enabled
        # bands and changes only the destination reached by its cursor.
        with m.If(walk_write_enable):
            m.d.sync += clock_modulation_array[walk_target_index].eq(
                walk_write_value)
        with m.If(walk_pending):
            with m.If(self.walk_style == self.WALK_STYLE_HEAD):
                m.d.sync += walk_index.eq(walk_head_next_index)
                with m.If(
                        (walk_head_direction &
                         (walk_index == self.N_BANDS - 1)) |
                        (~walk_head_direction & (walk_index == 0))):
                    m.d.sync += walk_head_direction.eq(~walk_head_direction)
                with m.If(band_enable_array[walk_head_next_index]):
                    m.d.sync += [
                        walk_cursor.eq(walk_head_next_index),
                        walk_pending.eq(0),
                    ]
            with m.Else():
                m.d.sync += walk_random_bits.eq(walk_random_bits >> 1)
                with m.If(walk_index == self.N_BANDS - 1):
                    m.d.sync += walk_pending.eq(0)
                with m.Else():
                    m.d.sync += walk_index.eq(walk_index + 1)

        # Find the wraparound enabled source, then carry each snapshotted origin
        # through a single pass of the enabled destinations. Keeping source
        # indices rather than ten wide level snapshots makes ROTATE much smaller;
        # the modulation value is read from the current natural BANK level.
        with m.If(rotate_pending):
            with m.If(rotate_searching):
                with m.If(band_enable_array[rotate_scan_index]):
                    m.d.sync += [
                        rotate_carry_origin.eq(
                            rotate_snapshot_origin_array[rotate_scan_index]),
                        rotate_searching.eq(0),
                        rotate_scan_index.eq(Mux(
                            rotate_worker_forward, 0,
                            self.N_BANDS - 1)),
                    ]
                with m.Elif(Mux(rotate_worker_forward,
                                rotate_scan_index == 0,
                                rotate_scan_index == self.N_BANDS - 1)):
                    for modulation in self.clock_modulations:
                        m.d.sync += modulation.eq(0)
                    m.d.sync += rotate_pending.eq(0)
                with m.Elif(rotate_worker_forward):
                    m.d.sync += rotate_scan_index.eq(rotate_scan_index - 1)
                with m.Else():
                    m.d.sync += rotate_scan_index.eq(rotate_scan_index + 1)
            with m.Else():
                with m.If(band_enable_array[rotate_scan_index]):
                    m.d.sync += [
                        rotate_origin_array[rotate_scan_index].eq(
                            rotate_carry_origin),
                        clock_modulation_array[rotate_scan_index].eq(
                            natural_level_array[rotate_carry_origin]),
                        rotate_carry_origin.eq(
                            rotate_snapshot_origin_array[rotate_scan_index]),
                    ]
                with m.Else():
                    m.d.sync += clock_modulation_array[rotate_scan_index].eq(0)
                with m.If(Mux(rotate_worker_forward,
                              rotate_scan_index == self.N_BANDS - 1,
                              rotate_scan_index == 0)):
                    m.d.sync += rotate_pending.eq(0)
                with m.Elif(rotate_worker_forward):
                    m.d.sync += rotate_scan_index.eq(rotate_scan_index + 1)
                with m.Else():
                    m.d.sync += rotate_scan_index.eq(rotate_scan_index - 1)

        # Clear the private loop after an algorithm/length change. This keeps
        # initial fill behavior deterministic while using one RAM write per
        # control cycle instead of a parallel register reset network.
        with m.If(turing_clear_pending):
            m.d.comb += [
                turing_pattern_wport.en.eq(1),
                turing_pattern_wport.addr.eq(turing_clear_index),
                turing_pattern_wport.data.eq(0),
            ]
            with m.If(turing_clear_index == self.N_BANDS - 1):
                m.d.sync += turing_clear_pending.eq(0)
            with m.Else():
                m.d.sync += turing_clear_index.eq(turing_clear_index + 1)

        # TURING evolves a private full-resolution pattern, then maps it to the
        # ten physical bands. Synchronous RAM reads make each shift take two
        # setup cycles plus one cycle per loop element, still negligible beside
        # the audio sample interval.
        with m.Elif(turing_pending):
            with m.If(turing_effective_length == 0):
                for modulation in self.clock_modulations:
                    m.d.sync += modulation.eq(0)
                m.d.sync += [
                    turing_pending.eq(0),
                    turing_map_pending.eq(0),
                    turing_seeded.eq(0),
                    turing_fill_count.eq(0),
                ]
            with m.Elif(turing_read_wait):
                # The block-RAM read port is synchronous. Its address is a
                # registered control signal, so allow one worker cycle for the
                # requested word to reach ``data`` before consuming it.
                m.d.sync += turing_read_wait.eq(0)
            with m.Elif(turing_starting):
                # An unchanged loop needs the departing value as its new carry
                # before the first destination can be read.
                m.d.sync += [
                    turing_carry.eq(turing_pattern_rport.data),
                    turing_pattern_rport.addr.eq(turing_scan_index),
                    turing_starting.eq(0),
                    turing_read_wait.eq(1),
                ]
            with m.Else():
                m.d.comb += [
                    turing_pattern_wport.en.eq(1),
                    turing_pattern_wport.addr.eq(turing_scan_index),
                    turing_pattern_wport.data.eq(turing_carry),
                ]
                m.d.sync += turing_carry.eq(turing_pattern_rport.data)
                with m.If(turing_search_count + 1 >=
                          turing_effective_length):
                    m.d.sync += [
                        turing_pending.eq(0),
                        turing_map_pending.eq(1),
                        turing_map_priming.eq(1),
                        turing_map_index.eq(0),
                        turing_map_pattern_index.eq(0),
                        turing_pattern_rport.addr.eq(0),
                    ]
                    with m.If(~turing_seeded):
                        with m.If(turing_fill_count + 1 >=
                                  turing_effective_length):
                            m.d.sync += [
                                turing_seeded.eq(1),
                                turing_fill_count.eq(
                                    turing_effective_length),
                            ]
                        with m.Else():
                            m.d.sync += turing_fill_count.eq(
                                turing_fill_count + 1)
                with m.Elif(turing_worker_forward):
                    m.d.sync += [
                        turing_scan_index.eq(turing_scan_index + 1),
                        turing_search_count.eq(turing_search_count + 1),
                        turing_pattern_rport.addr.eq(
                            turing_scan_index + 1),
                        turing_read_wait.eq(1),
                    ]
                with m.Else():
                    m.d.sync += [
                        turing_scan_index.eq(turing_scan_index - 1),
                        turing_search_count.eq(turing_search_count + 1),
                        turing_pattern_rport.addr.eq(
                            turing_scan_index - 1),
                        turing_read_wait.eq(1),
                    ]

        with m.If(turing_map_pending):
            # Prime the synchronous read after a shift or remap. This also
            # avoids a read/write collision when reverse evolution finishes at
            # pattern address zero.
            with m.If(turing_map_priming):
                m.d.sync += turing_map_priming.eq(0)
            with m.Elif(self.turing_target == self.TURING_TARGET_ALL):
                with m.If(band_enable_array[turing_map_index] &
                          (turing_effective_length != 0)):
                    m.d.sync += clock_modulation_array[
                        turing_map_index].eq(turing_pattern_rport.data)
                    with m.If(turing_map_pattern_index + 1 >=
                              turing_effective_length):
                        m.d.sync += [
                            turing_map_pattern_index.eq(0),
                            turing_pattern_rport.addr.eq(0),
                            turing_map_priming.eq(1),
                        ]
                    with m.Else():
                        m.d.sync += [
                            turing_map_pattern_index.eq(
                                turing_map_pattern_index + 1),
                            turing_pattern_rport.addr.eq(
                                turing_map_pattern_index + 1),
                            turing_map_priming.eq(1),
                        ]
                with m.Else():
                    m.d.sync += clock_modulation_array[
                        turing_map_index].eq(0)
            with m.Else():
                with m.If(
                        band_enable_array[turing_map_index] &
                        (turing_map_index >= self.turing_start) &
                        (turing_map_index < self.turing_start +
                         turing_effective_length)):
                    m.d.sync += clock_modulation_array[
                        turing_map_index].eq(turing_pattern_rport.data)
                with m.Else():
                    m.d.sync += clock_modulation_array[
                        turing_map_index].eq(0)
                with m.If((turing_map_index >= self.turing_start) &
                          (turing_map_index < self.turing_start +
                           turing_effective_length)):
                    m.d.sync += [
                        turing_pattern_rport.addr.eq(
                            turing_map_index - self.turing_start + 1),
                        turing_map_priming.eq(1),
                    ]
            # A RAM-prime cycle holds the physical destination as well as the
            # pattern address; otherwise every new word would skip one band.
            with m.If(~turing_map_priming):
                with m.If(turing_map_index == self.N_BANDS - 1):
                    m.d.sync += turing_map_pending.eq(0)
                with m.Else():
                    m.d.sync += turing_map_index.eq(turing_map_index + 1)

        with m.Switch(state):
            with m.Case(state_wait):
                with m.If(self.i.valid & self.i.ready):
                    for n in range(4):
                        m.d.sync += input_samples[n].eq(self.i.payload[n])
                    m.d.sync += [
                        data_lfsr.eq(Cat(
                            data_lfsr[1:],
                            data_lfsr[0] ^ data_lfsr[10] ^
                            data_lfsr[30] ^ data_lfsr[31])),
                        clock_mode_q.eq(self.clock_mode),
                        internal_clock_rate_q.eq(self.internal_clock_rate),
                        turing_target_q.eq(self.turing_target),
                        turing_start_q.eq(self.turing_start),
                    ]
                    # The clock counter runs upward for both sources. With an
                    # external source it also measures the period used by a
                    # HEAD stumble; internal timing already knows its period.
                    with m.If(self.clock_mode & clock_external_active_q):
                        with m.If(clock_pulse):
                            m.d.sync += external_interval_seen.eq(1)
                    with m.Else():
                        m.d.sync += external_interval_seen.eq(0)
                    # AUTO follows physical jack insertion rather than pulse
                    # activity, so stopped and very slow external clocks remain
                    # authoritative. Every handoff waits a complete internal
                    # period or a fresh external low-to-high transition.
                    with m.If(clock_mode_changed | clock_source_changed |
                              internal_clock_rate_changed):
                        m.d.sync += [
                            clock_external_active_q.eq(
                                clock_external_requested),
                            internal_clock_counter.eq(0),
                            # Treat a newly selected external source as already
                            # high until it has crossed the low threshold. This
                            # prevents cable insertion into a high gate from
                            # generating a clock.
                            clock_high.eq(
                                clock_external_requested &
                                (clock_sample > self.CLOCK_LOW_THRESHOLD)),
                            walk_burst_remaining.eq(0),
                        ]
                    with m.Elif(self.clock_mode & clock_external_active_q):
                        with m.If(clock_sample >= self.CLOCK_HIGH_THRESHOLD):
                            m.d.sync += clock_high.eq(1)
                        with m.Elif(clock_sample <= self.CLOCK_LOW_THRESHOLD):
                            m.d.sync += clock_high.eq(0)
                        with m.If(clock_pulse):
                            m.d.sync += internal_clock_counter.eq(0)
                        with m.Elif(internal_clock_counter !=
                                    max(internal_clock_periods) - 1):
                            m.d.sync += internal_clock_counter.eq(
                                internal_clock_counter + 1)
                    with m.Elif(self.clock_mode):
                        with m.If(clock_pulse):
                            m.d.sync += internal_clock_counter.eq(0)
                        with m.Else():
                            m.d.sync += internal_clock_counter.eq(
                                internal_clock_counter + 1)
                    with m.If(lock_sample >= self.CLOCK_HIGH_THRESHOLD):
                        m.d.sync += lock_high.eq(1)
                    with m.Elif(lock_sample <= self.CLOCK_LOW_THRESHOLD):
                        m.d.sync += lock_high.eq(0)
                    with m.If(self.clock_mode &
                              (self.clock_algorithm ==
                               self.CLOCK_ALGORITHM_TURING) &
                              ((self.turing_target != turing_target_q) |
                               (self.turing_start != turing_start_q))):
                        m.d.sync += [
                            turing_map_pending.eq(1),
                            turing_map_priming.eq(1),
                            turing_map_index.eq(0),
                            turing_map_pattern_index.eq(0),
                            turing_pattern_rport.addr.eq(0),
                        ]
                    with m.If(self.clock_mode &
                              ((self.clock_algorithm != clock_algorithm_q) |
                               ((self.clock_algorithm ==
                                 self.CLOCK_ALGORITHM_WALK) &
                                (self.walk_style != walk_style_q)) |
                               ((self.clock_algorithm ==
                                 self.CLOCK_ALGORITHM_TURING) &
                                (self.turing_length != turing_length_q)))):
                        for n, modulation in enumerate(self.clock_modulations):
                            m.d.sync += [
                                modulation.eq(0),
                                rotate_origins[n].eq(n),
                            ]
                        m.d.sync += [
                            clock_algorithm_q.eq(self.clock_algorithm),
                            walk_style_q.eq(self.walk_style),
                            turing_length_q.eq(self.turing_length),
                            rotate_seeded.eq(0),
                            rotate_pending.eq(0),
                            walk_pending.eq(0),
                            walk_cursor.eq(0),
                            walk_burst_remaining.eq(0),
                            turing_seeded.eq(0),
                            turing_fill_count.eq(0),
                            turing_pending.eq(0),
                            turing_map_pending.eq(0),
                            turing_clear_pending.eq(1),
                            turing_clear_index.eq(0),
                            ping_pong_forward.eq(1),
                            ping_pong_steps.eq(0),
                        ]
                    with m.Elif(self.clock_mode &
                              (self.clock_algorithm !=
                               self.CLOCK_ALGORITHM_TURING) &
                              (reset_sample >= self.CLOCK_HIGH_THRESHOLD)):
                        for n, modulation in enumerate(self.clock_modulations):
                            m.d.sync += [
                                modulation.eq(0),
                                rotate_origins[n].eq(n),
                            ]
                        m.d.sync += [
                            rotate_seeded.eq(0),
                            rotate_pending.eq(0),
                            walk_pending.eq(0),
                            walk_cursor.eq(0),
                            walk_burst_remaining.eq(0),
                            turing_seeded.eq(0),
                            turing_fill_count.eq(0),
                            turing_pending.eq(0),
                            turing_map_pending.eq(0),
                            ping_pong_forward.eq(1),
                            ping_pong_steps.eq(0),
                            shift_lfsr.eq(0xACE1),
                        ]
                    with m.Elif(clock_pulse):
                        with m.If(self.clock_algorithm ==
                                  self.CLOCK_ALGORITHM_SHIFT):
                            m.d.sync += [
                                shift_pending.eq(1),
                                shift_sample.eq(sampled_modulation),
                            ]
                        with m.Elif(self.clock_algorithm ==
                                    self.CLOCK_ALGORITHM_ROTATE):
                            rotate_forward = (
                                self.shift_direction == self.SHIFT_FORWARD)
                            for n in range(self.N_BANDS):
                                m.d.sync += rotate_snapshot_origins[n].eq(Mux(
                                    rotate_seeded, rotate_origins[n], n))
                            m.d.sync += [
                                rotate_seeded.eq(1),
                                rotate_pending.eq(1),
                                rotate_searching.eq(1),
                                rotate_scan_index.eq(Mux(
                                    rotate_forward,
                                    self.N_BANDS - 1, 0)),
                                rotate_worker_forward.eq(rotate_forward),
                            ]
                        with m.Elif(self.clock_algorithm ==
                                    self.CLOCK_ALGORITHM_WALK):
                            m.d.sync += [
                                walk_clock_pending.eq(1),
                                walk_clock_interval.eq(walk_burst_quarter),
                                walk_clock_interval_seen.eq(
                                    external_interval_seen),
                            ]
                        with m.Else():
                            turing_forward = (
                                (self.shift_direction == self.SHIFT_FORWARD) |
                                ((self.shift_direction == self.SHIFT_PING_PONG) &
                                 ping_pong_forward))
                            m.d.sync += [
                                rotate_seeded.eq(0),
                                shift_lfsr.eq(Cat(
                                    shift_lfsr[1:],
                                    shift_lfsr[0] ^ shift_lfsr[2] ^
                                    shift_lfsr[3] ^ shift_lfsr[5])),
                                turing_pending.eq(1),
                                turing_scan_index.eq(Mux(
                                    turing_forward, 0,
                                    turing_effective_length - 1)),
                                turing_search_count.eq(0),
                                turing_worker_forward.eq(turing_forward),
                                turing_starting.eq(~turing_mutate),
                                turing_read_wait.eq(1),
                                turing_pattern_rport.addr.eq(Mux(
                                    turing_mutate,
                                    Mux(turing_forward, 0,
                                        turing_effective_length - 1),
                                    Mux(turing_forward,
                                        turing_effective_length - 1, 0))),
                            ]
                            with m.If(
                                    self.shift_direction ==
                                    self.SHIFT_PING_PONG):
                                with m.If(ping_pong_steps + 1 >=
                                          turing_effective_length):
                                    m.d.sync += [
                                        ping_pong_steps.eq(0),
                                        ping_pong_forward.eq(~ping_pong_forward),
                                    ]
                                with m.Else():
                                    m.d.sync += ping_pong_steps.eq(
                                        ping_pong_steps + 1)
                            with m.If(turing_mutate):
                                m.d.sync += turing_carry.eq(
                                    shift_lfsr.as_signed() >> 1)
                    with m.Elif(walk_burst_pulse):
                        # Extra HEAD landings reuse the normal one-step worker
                        # but occur on quarter-interval subdivisions between
                        # incoming clocks.
                        m.d.sync += [
                            walk_pending.eq(enabled_band_count != 0),
                            walk_index.eq(walk_cursor),
                            walk_head_direction.eq(shift_lfsr[2]),
                            walk_random_bits.eq(shift_lfsr),
                            walk_burst_remaining.eq(
                                walk_burst_remaining - 1),
                            shift_lfsr.eq(Cat(
                                shift_lfsr[1:],
                                shift_lfsr[0] ^ shift_lfsr[2] ^
                                shift_lfsr[3] ^ shift_lfsr[5])),
                        ]
                    for n, diff in enumerate(level_diffs):
                        with m.If(diff > self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_levels[n].eq(
                                smooth_levels[n] + self.PARAM_SLEW_STEP)
                        with m.Elif(diff < -self.PARAM_SLEW_STEP):
                            m.d.sync += smooth_levels[n].eq(
                                smooth_levels[n] - self.PARAM_SLEW_STEP)
                        with m.Else():
                            m.d.sync += smooth_levels[n].eq(level_targets[n])
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
                        cv_acc.eq(0),
                    ]
                    m.d.sync += [
                        mac_a_q.eq(self.i.payload[0]),
                        mac_b_q.eq(smooth_cv_depths[0]),
                        state.eq(state_cv_commit),
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
                            mac_b_q.eq(Mux(input_audio_enabled[0],
                                           input_gain_coeffs[0], 0)),
                            state.eq(state_input_gain_commit),
                        ]

            with m.Case(state_input_gain_commit):
                m.d.sync += [
                    input_gain_product_q.eq(dry_gain_term),
                    state.eq(state_input_gain_add),
                ]

            with m.Case(state_input_gain_add):
                # Audio channels get a post-VALUE peak meter with fast attack
                # and slow release. CV channels expose the raw jack sample so
                # the indicator remains independent of DEPTH.
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
                with m.Switch(input_chan):
                  with m.Case(0):
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        input_chan.eq(1),
                        mac_a_q.eq(input_samples[1]),
                        mac_b_q.eq(Mux(input_audio_enabled[1],
                                       input_gain_coeffs[1], 0)),
                        state.eq(state_input_gain_commit),
                    ]
                  with m.Case(1):
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        input_chan.eq(2),
                        mac_a_q.eq(input_samples[2]),
                        mac_b_q.eq(Mux(input_audio_enabled[2],
                                       input_gain_coeffs[2], 0)),
                        state.eq(state_input_gain_commit),
                    ]
                  with m.Case(2):
                    m.d.sync += [
                        input_mix_acc.eq(input_mix_next),
                        input_chan.eq(3),
                        mac_a_q.eq(input_samples[3]),
                        mac_b_q.eq(Mux(input_audio_enabled[3],
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
    TARGET_SHIFT_DIRECTION = RezoCore.N_BANDS + 51
    TARGET_CLOCK_ALGORITHM = RezoCore.N_BANDS + 52
    TARGET_TURING_LENGTH = RezoCore.N_BANDS + 53
    TARGET_TURING_CHANGE = RezoCore.N_BANDS + 54
    TARGET_CLOCK_SOURCE = RezoCore.N_BANDS + 55
    TARGET_CLOCK_RATE = RezoCore.N_BANDS + 56
    TARGET_CLOCK_DEPTH = RezoCore.N_BANDS + 57
    TARGET_TURING_TARGET = RezoCore.N_BANDS + 58
    TARGET_TURING_START = RezoCore.N_BANDS + 59
    TARGET_DATA_SOURCE = RezoCore.N_BANDS + 60
    # WALK and TURING never expose these rows together, so sharing target IDs
    # avoids widening the already timing-sensitive navigation state.
    TARGET_WALK_STYLE = TARGET_TURING_TARGET
    TARGET_WALK_DRUNK = TARGET_TURING_LENGTH
    TARGET_WALK_CHANCE = TARGET_TURING_CHANGE
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
    # 16 bits because their exact unity point is 0xCCCC. Legacy FILTER fields
    # remain reserved so existing V1/V2 records still round-trip byte-for-byte.
    STATE_LEVELS_BASE = 0       # 5 words: ten signed high bytes
    STATE_DRIVES = 5            # bank + reserved legacy high bytes
    STATE_RESONANCE_FEEDBACK = 6
    STATE_CUTOFF_SLOPE = 7
    STATE_WIDTH_KNEE = 8
    STATE_CAP_FLAGS = 9         # cap high byte + damp/legacy flags
    STATE_LEGACY_CV_BASE = 10   # 8 reserved legacy words
    STATE_INPUT_GAIN_BASE = 18  # 4 full-width words
    STATE_CV_DEPTH_BASE = 22    # 2 words: four signed high bytes
    STATE_INPUT_CONFIG = 24     # four modes + four 3-bit targets
    STATE_BANK_GROUP_BASE = 25  # 3 words: ten 4-bit indices
    STATE_FEEDBACK_PRESET = 28  # ten sends + preset + palette
    STATE_OUTPUT_BASE = 29      # 13 words: forty 5-bit sends
    STATE_WORDS_V1 = 42
    STATE_BAND_CONFIG_BASE = 42  # 4 words: user frequencies, enables, layout
    STATE_WORDS_V2 = 46
    # V3 reuses six bytes of the removed FILTER modulation matrix. Its payload
    # therefore stays the same size as V2 while preserving every BANK field.
    STATE_CLOCK_CONFIG_BASE = STATE_LEGACY_CV_BASE
    STATE_WORDS_V3 = STATE_WORDS_V2
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

    @classmethod
    def legacy_clock_config_words(cls):
        """V3 tail used when importing a V1 or V2 state record."""
        fields = (
            (0, 1),
            (RezoCore.CLOCK_ALGORITHM_SHIFT, 2),
            (RezoCore.SHIFT_FORWARD, 2),
            (RezoCore.N_BANDS, 4),
            (3, 3),
            (RezoCore.CLOCK_SOURCE_AUTO, 2),
            (RezoCore.LEGACY_INTERNAL_CLOCK_BPMS.index(
                RezoCore.INTERNAL_CLOCK_DEFAULT), 3),
            (128, 8),
            (RezoCore.TURING_TARGET_ALL, 1),
            (0, 4),
            (RezoCore.DATA_SOURCE_CV, 2),
            (0, 4),
            (RezoCore.WALK_STEP_DEFAULT, 3),
            (RezoCore.WALK_STYLE_ALL, 1),
            (RezoCore.WALK_DRUNK_DEFAULT, 2),
            (RezoCore.WALK_CHANCE_DEFAULT, 3),
        )
        packed = 0
        shift = 0
        for value, width in fields:
            packed |= value << shift
            shift += width
        assert shift == 45
        return tuple((packed >> (16 * n)) & 0xffff for n in range(3))

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
            "limit_knee": Out(unsigned(16)),
            "limit_cap": Out(unsigned(16)),
            "damp_mode": Out(unsigned(3)),
            "input_gains": Out(data.ArrayLayout(unsigned(16), 4)),
            "input_modes": Out(data.ArrayLayout(unsigned(1), 4)),
            "cv_targets": Out(data.ArrayLayout(unsigned(4), 4)),
            "cv_depths": Out(data.ArrayLayout(signed(16), 4)),
            "clock_mode": Out(1),
            "clock_algorithm": Out(unsigned(2)),
            "shift_direction": Out(unsigned(2)),
            "turing_length": Out(unsigned(4)),
            "turing_change": Out(unsigned(8)),
            "turing_change_index": Out(unsigned(3)),
            "clock_source": Out(unsigned(2)),
            "data_source": Out(unsigned(2)),
            "internal_clock_rate": Out(
                range(RezoCore.INTERNAL_CLOCK_MIN_BPM,
                      RezoCore.INTERNAL_CLOCK_MAX_BPM + 1)),
            "clock_depth": Out(unsigned(8)),
            "walk_step_index": Out(
                range(len(RezoCore.WALK_STEPS))),
            "walk_style": Out(1),
            "walk_drunk": Out(unsigned(2)),
            "walk_chance_index": Out(
                range(len(RezoCore.WALK_CHANCES))),
            "turing_target": Out(1),
            "turing_start": Out(range(RezoCore.N_BANDS)),
            "bank_groups": Out(data.ArrayLayout(unsigned(4), RezoCore.N_BANDS)),
            "feedback_sends": Out(data.ArrayLayout(unsigned(1), RezoCore.N_BANDS)),
            "output_routes": Out(data.ArrayLayout(unsigned(5), 4)),
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
        legacy_drive = Signal(unsigned(8), init=RezoCore.DRIVE_DEFAULT >> 8)
        drive = Signal(unsigned(16))
        resonance = Signal(unsigned(8), init=8192 >> 8)
        feedback = Signal(unsigned(8), init=0)
        legacy_mode = Signal(init=0)
        # Retain the former FILTER fields only as version-2 state placeholders.
        # A future clocked-state version can reuse their on-flash positions
        # without shifting any of the established BANK fields.
        legacy_type = Signal(unsigned(2), init=0)
        legacy_cutoff = Signal(unsigned(8), init=16384 >> 8)
        legacy_slope = Signal(unsigned(8), init=16384 >> 8)
        legacy_width = Signal(unsigned(8), init=12288 >> 8)
        legacy_cv_matrix = [Signal(signed(8), init=0,
                                   name=f"ui_legacy_cv_matrix{n}")
                            for n in range(15)]
        limit_knee = Signal(unsigned(8), init=8192 >> 8)
        limit_cap = Signal(unsigned(8), init=28672 >> 8)
        damp_mode = Signal(unsigned(3), init=3)
        input_gains = [Signal(unsigned(16), init=self.INPUT_UNITY_POS if n == 0 else 0,
                              name=f"ui_input_gain{n}")
                       for n in range(4)]
        input_modes = [Signal(init=0 if n == 0 else 1, name=f"ui_input_mode{n}")
                       for n in range(4)]
        cv_targets = [Signal(unsigned(4), init=(1, 8, 9, 7)[n], name=f"ui_cv_target{n}")
                      for n in range(4)]
        cv_depths = [Signal(signed(16), init=0, name=f"ui_cv_depth{n}")
                     for n in range(4)]
        clock_mode = Signal(init=0)
        clock_algorithm = Signal(unsigned(2),
                                 init=RezoCore.CLOCK_ALGORITHM_SHIFT)
        shift_direction = Signal(unsigned(2), init=RezoCore.SHIFT_FORWARD)
        turing_length = Signal(unsigned(4), init=RezoCore.N_BANDS)
        turing_change_index = Signal(unsigned(3), init=3)
        turing_change_values = Array(Const(value, unsigned(8)) for value in
                                     (3, 8, 16, 32, 64, 128, 255))
        clock_source = Signal(unsigned(2), init=RezoCore.CLOCK_SOURCE_AUTO)
        data_source = Signal(unsigned(2), init=RezoCore.DATA_SOURCE_CV)
        internal_clock_rate = Signal(
            range(RezoCore.INTERNAL_CLOCK_MIN_BPM,
                  RezoCore.INTERNAL_CLOCK_MAX_BPM + 1),
            init=RezoCore.INTERNAL_CLOCK_DEFAULT)
        clock_depth = Signal(unsigned(8), init=128)
        walk_step_index = Signal(
            range(len(RezoCore.WALK_STEPS)), init=RezoCore.WALK_STEP_DEFAULT)
        walk_style = Signal(init=RezoCore.WALK_STYLE_ALL)
        walk_drunk = Signal(unsigned(2), init=RezoCore.WALK_DRUNK_DEFAULT)
        walk_chance_index = Signal(
            range(len(RezoCore.WALK_CHANCES)),
            init=RezoCore.WALK_CHANCE_DEFAULT)
        turing_target = Signal(init=RezoCore.TURING_TARGET_ALL)
        turing_start = Signal(range(RezoCore.N_BANDS), init=0)
        saved_clock_mode = Signal(init=0)
        saved_clock_algorithm = Signal(
            unsigned(2), init=RezoCore.CLOCK_ALGORITHM_SHIFT)
        saved_shift_direction = Signal(
            unsigned(2), init=RezoCore.SHIFT_FORWARD)
        saved_turing_length = Signal(unsigned(4), init=RezoCore.N_BANDS)
        saved_turing_change_index = Signal(unsigned(3), init=3)
        saved_clock_source = Signal(
            unsigned(2), init=RezoCore.CLOCK_SOURCE_AUTO)
        saved_data_source = Signal(
            unsigned(2), init=RezoCore.DATA_SOURCE_CV)
        saved_internal_clock_rate_low = Signal(3, init=
            RezoCore.INTERNAL_CLOCK_DEFAULT & 0x7)
        saved_internal_clock_rate_high = Signal(6, init=
            RezoCore.INTERNAL_CLOCK_DEFAULT >> 3)
        saved_clock_depth = Signal(unsigned(8), init=128)
        saved_walk_step_index = Signal(
            range(len(RezoCore.WALK_STEPS)), init=RezoCore.WALK_STEP_DEFAULT)
        saved_walk_style = Signal(init=RezoCore.WALK_STYLE_ALL)
        saved_walk_drunk = Signal(
            unsigned(2), init=RezoCore.WALK_DRUNK_DEFAULT)
        saved_walk_chance_index = Signal(
            range(len(RezoCore.WALK_CHANCES)),
            init=RezoCore.WALK_CHANCE_DEFAULT)
        saved_turing_target = Signal(init=RezoCore.TURING_TARGET_ALL)
        saved_turing_start = Signal(range(RezoCore.N_BANDS), init=0)
        saved_cv_target_highs = [
            Signal(init=((1, 8, 9, 7)[n] >> 3) & 1,
                   name=f"saved_cv_target_high{n}")
            for n in range(4)
        ]
        clock_roles_initialized = Signal()
        with m.If(state_shift_load_q & ~self.state_shift_load):
            m.d.sync += [
                clock_mode.eq(saved_clock_mode),
                clock_algorithm.eq(saved_clock_algorithm),
                # Older CLOCK builds allowed PING PONG in ROTATE and did not
                # offer it in TURING. Normalize only values that the restored
                # algorithm no longer exposes; valid SHIFT/TURING directions
                # remain byte-for-byte compatible.
                shift_direction.eq(Mux(
                    ((saved_clock_algorithm ==
                      RezoCore.CLOCK_ALGORITHM_SHIFT) &
                     (saved_shift_direction == RezoCore.SHIFT_PING_PONG)) |
                    ((saved_clock_algorithm ==
                      RezoCore.CLOCK_ALGORITHM_ROTATE) &
                     (saved_shift_direction > RezoCore.SHIFT_BACKWARD)) |
                    ((saved_clock_algorithm ==
                      RezoCore.CLOCK_ALGORITHM_TURING) &
                     (saved_shift_direction == RezoCore.SHIFT_RANDOM)),
                    RezoCore.SHIFT_FORWARD, saved_shift_direction)),
                turing_length.eq(saved_turing_length),
                turing_change_index.eq(saved_turing_change_index),
                clock_source.eq(saved_clock_source),
                data_source.eq(saved_data_source),
                internal_clock_rate.eq(Mux(
                    saved_internal_clock_rate_high == 0,
                    Array(Const(bpm, unsigned(9)) for bpm in
                          RezoCore.LEGACY_INTERNAL_CLOCK_BPMS)[
                              saved_internal_clock_rate_low],
                    Cat(saved_internal_clock_rate_low,
                        saved_internal_clock_rate_high))),
                clock_depth.eq(saved_clock_depth),
                # WALK no longer exposes a step-size row. Normalize legacy
                # saves to its balanced fixed step so hidden state cannot
                # change the sound without a corresponding control.
                walk_step_index.eq(Mux(
                    saved_clock_algorithm ==
                    RezoCore.CLOCK_ALGORITHM_WALK,
                    RezoCore.WALK_STEP_DEFAULT,
                    saved_walk_step_index)),
                walk_style.eq(saved_walk_style),
                walk_drunk.eq(saved_walk_drunk),
                walk_chance_index.eq(saved_walk_chance_index),
                turing_target.eq(saved_turing_target),
                turing_start.eq(saved_turing_start),
            ]
            for n, target in enumerate(cv_targets):
                m.d.sync += target[3].eq(saved_cv_target_highs[n])

        # Keep the journal's wide circular scan mux off the live CLOCK paths.
        # Header and CRC work leaves ample cycles between this snapshot and
        # the first payload word captured by an explicit SAVE.
        with m.If(self.save_default_request):
            m.d.sync += [
                saved_clock_mode.eq(clock_mode),
                saved_clock_algorithm.eq(clock_algorithm),
                saved_shift_direction.eq(shift_direction),
                saved_turing_length.eq(turing_length),
                saved_turing_change_index.eq(turing_change_index),
                saved_clock_source.eq(clock_source),
                saved_data_source.eq(data_source),
                saved_internal_clock_rate_low.eq(internal_clock_rate[:3]),
                saved_internal_clock_rate_high.eq(internal_clock_rate[3:9]),
                saved_clock_depth.eq(clock_depth),
                saved_walk_step_index.eq(walk_step_index),
                saved_walk_style.eq(walk_style),
                saved_walk_drunk.eq(walk_drunk),
                saved_walk_chance_index.eq(walk_chance_index),
                saved_turing_target.eq(turing_target),
                saved_turing_start.eq(turing_start),
            ]
            for n, target in enumerate(cv_targets):
                m.d.sync += saved_cv_target_highs[n].eq(target[3])
        initial_bank_masks = [1 << min(n // 3, 3) for n in range(RezoCore.N_BANDS)]
        bank_group_indices = [Signal(unsigned(4), init=self.gray_decode(mask),
                                     name=f"ui_bank_group_index{n}")
                              for n, mask in enumerate(initial_bank_masks)]
        bank_groups = [Signal(unsigned(4), name=f"ui_bank_group{n}")
                       for n in range(RezoCore.N_BANDS)]
        feedback_sends = [Signal(init=1, name=f"ui_feedback_send{n}")
                          for n in range(RezoCore.N_BANDS)]
        initial_output_masks = (0b01111, 0b00101, 0b01010, 0b10000)
        output_routes = [Signal(unsigned(5), name=f"ui_output_route{n}")
                         for n in range(4)]
        bank_output_sends = [
            Signal(unsigned(5),
                   init=16 if source < RezoCore.N_GROUPS and
                              initial_output_masks[output] & (1 << source) else 0,
                   name=f"ui_bank_output_send{output}_{source}")
            for output in range(4) for source in range(RezoCore.N_GROUPS + 1)
        ]
        legacy_output_masks = (0b1111, 0b0101, 0b1010, 0b0000)
        legacy_output_sends = [
            Signal(unsigned(5),
                   init=16 if source < RezoCore.N_GROUPS and
                              legacy_output_masks[output] & (1 << source) else 0,
                   name=f"ui_legacy_output_send{output}_{source}")
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
        advanced_target_visible = Signal()
        band_edit_target_visible = Signal()
        band_enable_target = Signal()
        band_frequency_target = Signal()
        bank_band_target = Signal()
        bank_band_index = Signal(range(RezoCore.N_BANDS))
        bank_band_enabled = Signal(init=1)
        clock_roles_present = Signal()
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
        input_edit_pending = Signal()
        input_edit_index = Signal(range(12))
        input_edit_direction = Signal()
        # Header edits walk a row or column through the same single-cell
        # write path as ordinary sends. This keeps relative matrix editing
        # cheap enough for the nearly full ECP5.
        output_relative_active = Signal()
        output_relative_step = Signal(unsigned(3))
        output_relative_index = Signal(unsigned(5))
        output_relative_column = Signal()
        output_relative_direction = Signal()
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
            (selected == self.TARGET_LIMIT_KNEE) |
            (selected == self.TARGET_LIMIT_CAP) |
            (selected == self.TARGET_CLOCK_DEPTH) |
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
        m.d.sync += [
            output_edit_pending.eq(0),
            input_edit_pending.eq(0),
        ]
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
        # A fast turn replays the same inexpensive one-step edit. Discrete
        # selectors and routing cells remain one state per detent.
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
            clock_roles_present.eq(
                (cv_targets[0] >= RezoCore.CV_TARGET_CLOCK) |
                (cv_targets[1] >= RezoCore.CV_TARGET_CLOCK) |
                (cv_targets[2] >= RezoCore.CV_TARGET_CLOCK) |
                (cv_targets[3] >= RezoCore.CV_TARGET_CLOCK)),
            bank_target_visible.eq(
                (selected <= self.TARGET_FEEDBACK) |
                (selected == self.TARGET_MODE)),
            feedback_send_target.eq(
                (selected >= self.TARGET_FEEDBACK_SEND_BASE) &
                (selected < self.TARGET_FEEDBACK_SEND_BASE + RezoCore.N_BANDS)),
            tune_target_visible.eq((selected == self.TARGET_PAGE) |
                                   (selected == self.TARGET_FEEDBACK) |
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
                                     output_cell_target |
                                     output_row_target | output_col_target),
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
            ~bank_band_target | Array(band_enables)[bank_band_index])
        with m.If(page == 0):
            with m.If(edit_direction):
                with m.If(~bank_target_visible |
                          (selected == self.TARGET_PAGE)):
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
                with m.If(~bank_target_visible |
                          (selected == self.TARGET_PAGE)):
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
            add_feedback_navigation(
                m, edit_direction=edit_direction, selected=selected,
                next_selected=next_selected,
                target_visible=tune_target_visible,
                page_target=self.TARGET_PAGE,
                send_base=self.TARGET_FEEDBACK_SEND_BASE,
                feedback_target=self.TARGET_FEEDBACK,
                knee_target=self.TARGET_LIMIT_KNEE,
                damping_target=self.TARGET_DAMP,
                band_count=RezoCore.N_BANDS)
        with m.Elif(page == 2):
            add_input_navigation(
                m, edit_direction=edit_direction, selected=selected,
                next_selected=next_selected,
                target_visible=input_target_visible,
                page_target=self.TARGET_PAGE,
                input_base=self.TARGET_INPUT_BASE,
                input_modes=input_modes, cv_mode=RezoCore.INPUT_MODE_CV)
        with m.Elif(page == 3):
            add_group_navigation(
                m, edit_direction=edit_direction, selected=selected,
                next_selected=next_selected,
                target_visible=group_target_visible,
                page_target=self.TARGET_PAGE,
                group_base=self.TARGET_GROUP_BASE,
                group_count=RezoCore.N_BANDS)
        with m.Elif(page == 4):
            # Five column headers, followed by each row header and its five
            # send cells. Turning a header adjusts its sends relatively.
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
                    last_send = self.TARGET_OUTPUT_BASE + output * 5 + 4
                    with m.Elif(selected == row_target):
                        m.d.comb += next_selected.eq(
                            self.TARGET_OUTPUT_BASE + output * 5)
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
                    first_send = self.TARGET_OUTPUT_BASE + output * 5
                    with m.Elif(selected == row_target):
                        m.d.comb += next_selected.eq(
                            self.TARGET_OUTPUT_DRY_COL if output == 0 else
                            self.TARGET_OUTPUT_BASE + output * 5 - 1)
                    with m.Elif(selected == first_send):
                        m.d.comb += next_selected.eq(row_target)
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
        with m.Elif(page == 7):
            with m.If(edit_direction):
                with m.If(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_ALGORITHM)
                with m.Elif(selected == self.TARGET_CLOCK_ALGORITHM):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_CLOCK_SOURCE,
                        self.TARGET_SHIFT_DIRECTION))
                with m.Elif(selected == self.TARGET_SHIFT_DIRECTION):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_SOURCE)
                with m.Elif(selected == self.TARGET_CLOCK_SOURCE):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_RATE)
                with m.Elif(selected == self.TARGET_CLOCK_RATE):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_DEPTH)
                with m.Elif(selected == self.TARGET_CLOCK_DEPTH):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_SHIFT,
                        self.TARGET_DATA_SOURCE,
                        Mux(clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                            self.TARGET_WALK_STYLE,
                            Mux(clock_algorithm ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                self.TARGET_TURING_CHANGE,
                                self.TARGET_PAGE))))
                with m.Elif(selected == self.TARGET_DATA_SOURCE):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Elif(selected == self.TARGET_TURING_CHANGE):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_PAGE, self.TARGET_TURING_TARGET))
                with m.Elif(selected == self.TARGET_TURING_TARGET):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_WALK_DRUNK,
                        Mux(turing_target == RezoCore.TURING_TARGET_RANGE,
                            self.TARGET_TURING_START,
                            self.TARGET_TURING_LENGTH)))
                with m.Elif(selected == self.TARGET_TURING_START):
                    m.d.comb += next_selected.eq(self.TARGET_TURING_LENGTH)
                with m.Else():
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_WALK_CHANCE, self.TARGET_PAGE))
            with m.Else():
                with m.If(selected == self.TARGET_PAGE):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_SHIFT,
                        self.TARGET_DATA_SOURCE,
                        Mux(clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                            self.TARGET_WALK_CHANCE,
                            Mux(clock_algorithm ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                self.TARGET_TURING_LENGTH,
                                self.TARGET_CLOCK_DEPTH))))
                with m.Elif(selected == self.TARGET_CLOCK_ALGORITHM):
                    m.d.comb += next_selected.eq(self.TARGET_PAGE)
                with m.Elif(selected == self.TARGET_SHIFT_DIRECTION):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_ALGORITHM)
                with m.Elif(selected == self.TARGET_CLOCK_SOURCE):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_CLOCK_ALGORITHM,
                        self.TARGET_SHIFT_DIRECTION))
                with m.Elif(selected == self.TARGET_CLOCK_RATE):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_SOURCE)
                with m.Elif(selected == self.TARGET_CLOCK_DEPTH):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_RATE)
                with m.Elif(selected == self.TARGET_DATA_SOURCE):
                    m.d.comb += next_selected.eq(self.TARGET_CLOCK_DEPTH)
                with m.Elif(selected == self.TARGET_TURING_CHANGE):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_WALK_DRUNK, self.TARGET_CLOCK_DEPTH))
                with m.Elif(selected == self.TARGET_TURING_TARGET):
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_CLOCK_DEPTH, self.TARGET_TURING_CHANGE))
                with m.Elif(selected == self.TARGET_TURING_START):
                    m.d.comb += next_selected.eq(self.TARGET_TURING_TARGET)
                with m.Else():
                    m.d.comb += next_selected.eq(Mux(
                        clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK,
                        self.TARGET_WALK_STYLE,
                        Mux(turing_target == RezoCore.TURING_TARGET_RANGE,
                            self.TARGET_TURING_START,
                            self.TARGET_TURING_TARGET)))
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
                    # Main -> bands -> inputs -> groups -> outputs ->
                    # feedback -> options.
                    with m.If(edit_direction):
                        with m.Switch(page):
                            with m.Case(0):
                                m.d.sync += page.eq(Mux(clock_mode, 7, 6))
                            with m.Case(7): m.d.sync += page.eq(6)
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
                                m.d.sync += page.eq(6)
                            with m.Case(6):
                                m.d.sync += page.eq(Mux(clock_mode, 7, 0))
                            with m.Case(7): m.d.sync += page.eq(0)
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
                    with m.If(edit_direction):
                        self.clamp_add(m, bank_drive, step_amount, 0, 96)
                    with m.Else():
                        self.clamp_add(m, bank_drive, -step_amount, 0, 96)
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
                with m.Elif((selected >= self.TARGET_INPUT_BASE) &
                            (selected < self.TARGET_INPUT_BASE + 12)):
                    m.d.sync += [
                        input_edit_pending.eq(1),
                        input_edit_index.eq(selected - self.TARGET_INPUT_BASE),
                        input_edit_direction.eq(edit_direction),
                    ]
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

        with m.If(input_edit_pending):
            for n in range(4):
                with m.If(input_edit_index == n * 3):
                    m.d.sync += input_modes[n].eq(~input_modes[n])
                with m.Elif(input_edit_index == n * 3 + 1):
                    with m.If(input_modes[n] == RezoCore.INPUT_MODE_AUDIO):
                        input_gain_coarse = input_gains[n][8:16]
                        with m.If(input_edit_direction):
                            self.clamp_add(m, input_gain_coarse, 1, 0, 255)
                        with m.Else():
                            self.clamp_add(m, input_gain_coarse, -1, 0, 255)
                    with m.Else():
                        with m.If(input_edit_direction):
                            m.d.sync += cv_targets[n].eq(Mux(
                                cv_targets[n] == RezoCore.CV_TARGET_MAX,
                                0, cv_targets[n] + 1))
                        with m.Else():
                            m.d.sync += cv_targets[n].eq(Mux(
                                cv_targets[n] == 0,
                                RezoCore.CV_TARGET_MAX,
                                cv_targets[n] - 1))
                with m.Elif(input_edit_index == n * 3 + 2):
                    cv_depth_coarse = cv_depths[n][8:16].as_signed()
                    with m.If(input_edit_direction):
                        self.clamp_add(m, cv_depth_coarse, 1, -128, 127)
                    with m.Else():
                        self.clamp_add(m, cv_depth_coarse, -1, -128, 127)

        # CLOCK controls are disjoint from every legacy target. Keeping their
        # edit decoders parallel avoids lengthening the already timing-critical
        # state-restore enable chain for all BANK registers.
        with m.If(edit_step & editing):
            with m.If(selected == self.TARGET_MODE):
                m.d.sync += clock_mode.eq(~clock_mode)
                # A valid version-2 save restores only the legacy three-bit
                # targets. On the first transition into CLOCK, supply the MVP
                # roles if the user has not already assigned any. Subsequent
                # BANK/CLOCK changes preserve all session edits.
                with m.If(~clock_mode & ~clock_roles_initialized):
                    m.d.sync += clock_roles_initialized.eq(1)
                    with m.If(~clock_roles_present):
                        m.d.sync += [
                            input_modes[1].eq(RezoCore.INPUT_MODE_CV),
                            input_modes[2].eq(RezoCore.INPUT_MODE_CV),
                            input_modes[3].eq(RezoCore.INPUT_MODE_CV),
                            cv_targets[1].eq(RezoCore.CV_TARGET_RESET),
                            cv_targets[2].eq(RezoCore.CV_TARGET_DATA),
                            cv_targets[3].eq(RezoCore.CV_TARGET_CLOCK),
                        ]
            with m.If(selected == self.TARGET_SHIFT_DIRECTION):
                with m.If(clock_algorithm == RezoCore.CLOCK_ALGORITHM_SHIFT):
                    with m.If(edit_direction):
                        m.d.sync += shift_direction.eq(Mux(
                            shift_direction == RezoCore.SHIFT_FORWARD,
                            RezoCore.SHIFT_BACKWARD,
                            Mux(shift_direction == RezoCore.SHIFT_BACKWARD,
                                RezoCore.SHIFT_RANDOM,
                                RezoCore.SHIFT_FORWARD)))
                    with m.Else():
                        m.d.sync += shift_direction.eq(Mux(
                            shift_direction == RezoCore.SHIFT_FORWARD,
                            RezoCore.SHIFT_RANDOM,
                            Mux(shift_direction == RezoCore.SHIFT_RANDOM,
                                RezoCore.SHIFT_BACKWARD,
                                RezoCore.SHIFT_FORWARD)))
                with m.Elif(clock_algorithm ==
                            RezoCore.CLOCK_ALGORITHM_ROTATE):
                    m.d.sync += shift_direction.eq(Mux(
                        shift_direction == RezoCore.SHIFT_FORWARD,
                        RezoCore.SHIFT_BACKWARD,
                        RezoCore.SHIFT_FORWARD))
                with m.Elif(clock_algorithm ==
                            RezoCore.CLOCK_ALGORITHM_TURING):
                    with m.If(edit_direction):
                        m.d.sync += shift_direction.eq(Mux(
                            shift_direction == RezoCore.SHIFT_FORWARD,
                            RezoCore.SHIFT_BACKWARD,
                            Mux(shift_direction == RezoCore.SHIFT_BACKWARD,
                                RezoCore.SHIFT_PING_PONG,
                                RezoCore.SHIFT_FORWARD)))
                    with m.Else():
                        m.d.sync += shift_direction.eq(Mux(
                            shift_direction == RezoCore.SHIFT_FORWARD,
                            RezoCore.SHIFT_PING_PONG,
                            Mux(shift_direction == RezoCore.SHIFT_PING_PONG,
                                RezoCore.SHIFT_BACKWARD,
                                RezoCore.SHIFT_FORWARD)))
            with m.If(selected == self.TARGET_CLOCK_ALGORITHM):
                m.d.sync += [
                    # The four algorithms occupy every value of this two-bit
                    # field, so ordinary wrapped arithmetic implements both
                    # traversal directions without a deep mux chain.
                    clock_algorithm.eq(Mux(
                        edit_direction,
                        clock_algorithm + 1,
                        clock_algorithm - 1)),
                    shift_direction.eq(RezoCore.SHIFT_FORWARD),
                    walk_step_index.eq(RezoCore.WALK_STEP_DEFAULT),
                ]
            with m.If(selected == self.TARGET_TURING_LENGTH):
                with m.If(clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK):
                    m.d.sync += walk_drunk.eq(Mux(
                        edit_direction, walk_drunk + 1, walk_drunk - 1))
                with m.Else():
                    with m.If(edit_direction):
                        m.d.sync += turing_length.eq(Mux(
                            turing_length == RezoCore.N_BANDS,
                            2, turing_length + 1))
                        with m.If((turing_length != RezoCore.N_BANDS) &
                                  (turing_start + turing_length >=
                                   RezoCore.N_BANDS)):
                            m.d.sync += turing_start.eq(
                                RezoCore.N_BANDS - turing_length - 1)
                    with m.Else():
                        m.d.sync += turing_length.eq(Mux(
                            turing_length == 2,
                            RezoCore.N_BANDS, turing_length - 1))
                        with m.If(turing_length == 2):
                            m.d.sync += turing_start.eq(0)
            with m.If(selected == self.TARGET_TURING_CHANGE):
                with m.If(clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK):
                    with m.If(edit_direction):
                        m.d.sync += walk_chance_index.eq(Mux(
                            walk_chance_index == len(RezoCore.WALK_CHANCES) - 1,
                            0, walk_chance_index + 1))
                    with m.Else():
                        m.d.sync += walk_chance_index.eq(Mux(
                            walk_chance_index == 0,
                            len(RezoCore.WALK_CHANCES) - 1,
                            walk_chance_index - 1))
                with m.Else():
                    with m.If(edit_direction):
                        m.d.sync += turing_change_index.eq(Mux(
                            turing_change_index == 6,
                            0, turing_change_index + 1))
                    with m.Else():
                        m.d.sync += turing_change_index.eq(Mux(
                            turing_change_index == 0,
                            6, turing_change_index - 1))
            with m.If(selected == self.TARGET_CLOCK_SOURCE):
                with m.If(edit_direction):
                    m.d.sync += clock_source.eq(Mux(
                        clock_source == RezoCore.CLOCK_SOURCE_EXTERNAL,
                        RezoCore.CLOCK_SOURCE_AUTO, clock_source + 1))
                with m.Else():
                    m.d.sync += clock_source.eq(Mux(
                        clock_source == RezoCore.CLOCK_SOURCE_AUTO,
                        RezoCore.CLOCK_SOURCE_EXTERNAL, clock_source - 1))
            with m.If(selected == self.TARGET_DATA_SOURCE):
                with m.If(edit_direction):
                    m.d.sync += data_source.eq(Mux(
                        data_source == RezoCore.DATA_SOURCE_AUTO,
                        RezoCore.DATA_SOURCE_CV, data_source + 1))
                with m.Else():
                    m.d.sync += data_source.eq(Mux(
                        data_source == RezoCore.DATA_SOURCE_CV,
                        RezoCore.DATA_SOURCE_AUTO, data_source - 1))
            with m.If(selected == self.TARGET_CLOCK_RATE):
                with m.If(edit_direction):
                    self.clamp_add(
                        m, internal_clock_rate, accelerated_edit_step,
                        RezoCore.INTERNAL_CLOCK_MIN_BPM,
                        RezoCore.INTERNAL_CLOCK_MAX_BPM)
                with m.Else():
                    self.clamp_add(
                        m, internal_clock_rate, -accelerated_edit_step,
                        RezoCore.INTERNAL_CLOCK_MIN_BPM,
                        RezoCore.INTERNAL_CLOCK_MAX_BPM)
            with m.If(selected == self.TARGET_CLOCK_DEPTH):
                with m.If(edit_direction):
                    self.clamp_add(m, clock_depth, 1, 0, 128)
                with m.Else():
                    self.clamp_add(m, clock_depth, -1, 0, 128)
            with m.If(selected == self.TARGET_TURING_TARGET):
                with m.If(clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK):
                    m.d.sync += walk_style.eq(~walk_style)
                with m.Else():
                    m.d.sync += turing_target.eq(~turing_target)
            with m.If(selected == self.TARGET_TURING_START):
                with m.If(edit_direction):
                    with m.If(turing_start >= RezoCore.N_BANDS - 2):
                        m.d.sync += turing_start.eq(0)
                    with m.Else():
                        m.d.sync += turing_start.eq(turing_start + 1)
                        with m.If(turing_start + turing_length >=
                                  RezoCore.N_BANDS):
                            m.d.sync += turing_length.eq(
                                RezoCore.N_BANDS - turing_start - 1)
                with m.Else():
                    with m.If(turing_start == 0):
                        m.d.sync += [
                            turing_start.eq(RezoCore.N_BANDS - 2),
                            turing_length.eq(2),
                        ]
                    with m.Else():
                        m.d.sync += turing_start.eq(turing_start - 1)

        # Packed 16-bit state scan port, sampled sequentially by the journal.
        # Packing at each field's native precision is materially smaller than
        # a 114-way 16-bit mux and leaves space for musical features.
        level_bytes = Cat(*(level.as_unsigned() for level in levels))
        # Version 2 already reserved twenty padding bits across the stream.
        # Reuse them for two fine-frequency bits per band. Old records restore
        # zero here and therefore retain their exact coarse-grid frequencies.
        cap_flags_fine = band_frequencies[0][:RezoCore.FREQ_FINE_WIDTH]
        legacy_cv_fine = Cat(*(band_frequencies[n][:RezoCore.FREQ_FINE_WIDTH]
                               for n in range(1, 5)))
        bank_group_fine = Cat(*(band_frequencies[n][:RezoCore.FREQ_FINE_WIDTH]
                                for n in range(5, 9)))
        output_send_pad = Signal(8)
        band_config_fine = band_frequencies[9][:RezoCore.FREQ_FINE_WIDTH]
        cv_depth_bytes = Cat(*(value[8:16] for value in cv_depths))
        # Preserve the original sixteen-bit V2 input word. V3 stores the high
        # target bits alongside CLOCK's settings in removed FILTER state.
        input_config_bits = Cat(*input_modes, *(target[:3] for target in cv_targets))
        bank_group_bits = Cat(*bank_group_indices, bank_group_fine)
        feedback_preset_bits = Cat(*feedback_sends, preset, palette)
        output_send_bits = Cat(*bank_output_sends, *legacy_output_sends,
                               output_send_pad)
        band_config_bits = Cat(
            *(frequency[RezoCore.FREQ_FINE_WIDTH:]
              for frequency in band_frequencies),
            *band_enables, frequency_layout, band_config_fine)
        clock_config_bits = Cat(
            saved_clock_mode,
            saved_clock_algorithm,
            saved_shift_direction,
            saved_turing_length,
            saved_turing_change_index,
            saved_clock_source,
            saved_internal_clock_rate_low,
            saved_clock_depth,
            saved_turing_target,
            saved_turing_start,
            saved_data_source,
            *saved_cv_target_highs,
            saved_walk_step_index,
            saved_walk_style,
            saved_walk_drunk,
            saved_walk_chance_index,
            saved_internal_clock_rate_high,
        )
        legacy_cv_bits = Cat(
            clock_config_bits,
            # CLOCK DEPTH gained three persistent precision bits. Reclaim
            # them in place from one removed FILTER placeholder so every
            # subsequent live field keeps its established word offset.
            legacy_cv_matrix[6].as_unsigned()[3:8],
            *(value.as_unsigned() for value in legacy_cv_matrix[7:]),
            legacy_cv_fine)
        # The packed state is a circular stream. This temporal interface costs
        # one local shift mux per retained bit instead of a 42-way read mux and
        # a separate 42-way restore decoder. A complete SAVE rotation returns
        # every live register to its original location; LOAD replaces the
        # trailing word on each shift with validated journal data.
        state_bits = Cat(
            level_bytes,
            bank_drive, legacy_drive,
            resonance, feedback,
            legacy_cutoff, legacy_slope,
            legacy_width, limit_knee,
            limit_cap, damp_mode, legacy_mode, legacy_type, cap_flags_fine,
            legacy_cv_bits,
            *input_gains,
            cv_depth_bytes,
            input_config_bits,
            bank_group_bits,
            feedback_preset_bits,
            output_send_bits,
            band_config_bits,
        )
        assert len(state_bits) == self.STATE_WORDS_V3 * 16
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
        for n, output_send in enumerate(output_sends):
            m.d.comb += self.output_sends[n].eq(output_send)
        m.d.comb += [
            self.drive.eq(drive),
            self.resonance.eq(resonance << 8),
            self.feedback.eq(feedback << 8),
            self.clock_algorithm.eq(clock_algorithm),
            self.turing_length.eq(turing_length),
            self.turing_change.eq(
                turing_change_values[turing_change_index]),
            self.turing_change_index.eq(turing_change_index),
            self.clock_source.eq(clock_source),
            self.data_source.eq(data_source),
            self.internal_clock_rate.eq(internal_clock_rate),
            self.clock_depth.eq(clock_depth),
            self.walk_step_index.eq(walk_step_index),
            self.walk_style.eq(walk_style),
            self.walk_drunk.eq(walk_drunk),
            self.walk_chance_index.eq(walk_chance_index),
            self.turing_target.eq(turing_target),
            self.turing_start.eq(turing_start),
            self.limit_knee.eq(limit_knee << 8),
            self.limit_cap.eq(limit_cap << 8),
            self.damp_mode.eq(damp_mode),
            self.clock_mode.eq(clock_mode),
            self.shift_direction.eq(shift_direction),
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
    PALETTE = SEMANTIC_PALETTE
    PALETTE_ROLES = PALETTE_ROLES
    RGB_PALETTES = RGB_PALETTES
    CHARS = TILE_CHARS
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
            "clock_mode": In(1),
            "clock_algorithm": In(unsigned(2)),
            "shift_direction": In(unsigned(2)),
            "walk_step_index": In(range(len(RezoCore.WALK_STEPS))),
            "walk_style": In(1),
            "walk_drunk": In(unsigned(2)),
            "walk_chance_index": In(
                range(len(RezoCore.WALK_CHANCES))),
            "turing_length": In(unsigned(4)),
            "turing_change_index": In(unsigned(3)),
            "clock_source": In(unsigned(2)),
            "data_source": In(unsigned(2)),
            "internal_clock_rate": In(
                range(RezoCore.INTERNAL_CLOCK_MIN_BPM,
                      RezoCore.INTERNAL_CLOCK_MAX_BPM + 1)),
            "clock_external_active": In(1),
            "data_random_active": In(1),
            "clock_depth": In(unsigned(8)),
            "turing_target": In(1),
            "turing_start": In(range(RezoCore.N_BANDS)),
            "limit_knee": In(unsigned(8)),
            "limit_cap": In(unsigned(8)),
            "damp_mode": In(unsigned(3)),
            "input_gains": In(data.ArrayLayout(unsigned(8), 4)),
            "input_modes": In(data.ArrayLayout(unsigned(1), 4)),
            "cv_targets": In(data.ArrayLayout(unsigned(4), 4)),
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
            text_x_pre = Signal.like(text_x)
            text_y_pre = Signal.like(text_y)
            active_pre = Signal()
            m.d.dvi += [
                x.eq(text_x_pre), y.eq(text_y_pre),
                text_x_pre.eq(ui_x[:10]), text_y_pre.eq(ui_y[:10]),
                active_pre.eq(self.de & (ui_x >= 0) &
                              (ui_x < self.PANEL_W) &
                              (ui_y >= 0) & (ui_y < self.PANEL_H)),
                text_x.eq(text_x_pre), text_y.eq(text_y_pre),
                active.eq(active_pre),
            ]
        else:
            m.d.comb += [
                x.eq(ui_x[:10]), y.eq(ui_y[:10]),
                text_x.eq(ui_x[:10]), text_y.eq(ui_y[:10]),
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

        for n in range(RezoCore.N_BANDS):
            level = self.effective_levels[n]
            base_level = self.levels[n]
            mag = Signal(unsigned(7), name=f"tile_level_mag{n}")
            base_mag = Signal(unsigned(7), name=f"tile_base_level_mag{n}")
            height = Signal(signed(12), name=f"tile_level_height{n}")
            base_height = Signal(signed(12), name=f"tile_base_level_height{n}")
            m.d.comb += [
                mag.eq(Mux(level < 0, -level, level)),
                base_mag.eq(Mux(base_level < 0, -base_level, base_level)),
            ]
            if self.compact_layout:
                m.d.comb += [
                    height.eq(mag + (mag >> 2) + (mag >> 3) +
                              (mag >> 5)),
                    base_height.eq(base_mag + (base_mag >> 2) +
                                   (base_mag >> 3) + (base_mag >> 5)),
                ]
            else:
                m.d.comb += [
                    height.eq((mag << 1) + (mag >> 1) +
                              Mux(level < 0, 0, mag >> 3)),
                    base_height.eq((base_mag << 1) + (base_mag >> 1) +
                                   Mux(base_level < 0, 0, base_mag >> 3)),
                ]
            m.d.dvi += [
                band_top_values[n].eq(zero_y - height),
                band_bottom_values[n].eq(zero_y + height),
                band_base_marker_values[n].eq(
                    Mux(base_level < 0, zero_y + base_height, zero_y - base_height)),
                band_positive_values[n].eq(level > 0),
                band_negative_values[n].eq(level < 0),
            ]

        text_page_q = Signal(unsigned(3))
        m.d.dvi += text_page_q.eq(self.page)

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
        clock_page = Signal()
        tune_page = Signal()
        input_page = Signal()
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
            bank_page.eq(self.page == 0),
            clock_page.eq(self.page == 7),
            tune_page.eq(self.page == 1),
            input_page.eq(self.page == 2),
            group_page.eq(self.page == 3),
            output_page.eq(self.page == 4),
            advanced_page.eq(self.page == 5),
            bands_page.eq(self.page == 6),
        ]
        page_cells = 45 * 45
        text_init = [0] * (8 * page_cells)

        def put(page, text_value, x0, y0):
            for offset, ch in enumerate(text_value):
                if 0 <= x0 + offset < 45 and 0 <= y0 < 45:
                    text_init[page * page_cells + y0 * 45 + x0 + offset] = self.code(ch)

        compact_input_text_rows = NATIVE_INPUT_TEXT_ROWS
        compact_group_text_rows = NATIVE_GROUP_TEXT_ROWS
        compact_group_centers = NATIVE_GROUP_CENTERS
        compact_output_text_rows = NATIVE_OUTPUT_TEXT_ROWS
        compact_output_row_centers = NATIVE_OUTPUT_ROW_CENTERS
        compact_output_col_centers = NATIVE_OUTPUT_COL_CENTERS
        compact_main_control_text_rows = NATIVE_MAIN_CONTROL_TEXT_ROWS
        compact_main_control_y0s = NATIVE_MAIN_CONTROL_Y0S
        compact_fader_threshold = Const(0, unsigned(8))
        compact_fader_x_valid = Const(0)

        # Shared native faders use one x-to-value lookup.  Comparing values
        # against a threshold avoids synthesizing a dynamic multiply for each
        # row and makes BANK, FEEDBACK, and CLOCK agree on their endpoints.
        if self.compact_layout:
            compact_fader_x0 = NATIVE_MAIN_FILL_X0
            compact_fader_x1 = NATIVE_MAIN_FILL_X1
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
            compact_fader_prefetch_x = Signal(range(self.PANEL_W))
            compact_fader_lookup_x = Signal(range(self.PANEL_W))
            compact_fader_data_q = Signal(unsigned(9))
            m.d.comb += [
                compact_fader_prefetch_x.eq(Mux(
                    x < self.PANEL_W - 1, x + 1, 0)),
                compact_fader_lookup_x.eq(Mux(
                    tune_page &
                    (compact_fader_prefetch_x < self.PANEL_W - 15),
                    compact_fader_prefetch_x + 15,
                    compact_fader_prefetch_x)),
                compact_fader_x_rport.addr.eq(compact_fader_lookup_x),
            ]
            m.d.dvi += compact_fader_data_q.eq(compact_fader_x_rport.data)
            compact_fader_threshold = compact_fader_data_q[:8]
            compact_fader_x_valid = compact_fader_data_q[8]

        page_titles = COMMON_PAGE_TITLES + ("CLOCK",)
        if self.compact_layout:
            put_native_page_headers(put, "REZOMO", page_titles)
        else:
            for page_number, title in enumerate(page_titles):
                put(page_number, "REZOMO", 2, 3)
                title_x = 29 + max(0, (8 - len(title)) // 2)
                put(page_number, title, title_x, 3)
        if self.compact_layout:
            # Shared REZO-family pages use the hardware-validated native
            # 508px grid. CLOCK remains REZOMO-specific below.
            put(0, "PRESET", 8, 11)
            put(0, "MODE", 24, 11)
            put(0, "BANDS", 8, 14)
            put(0, "FREQ:", 23, 14)
            put(0, "DRIVE", 12, compact_main_control_text_rows[0])
            put(0, "RESONANCE", 8, compact_main_control_text_rows[1])
            put(0, "FEEDBACK", 9, compact_main_control_text_rows[2])

            put_native_support_page_labels(put)

            # CLOCK is REZOMO-specific, but follows the same native row grid
            # as the shared pages.  Every possible control occupies one row
            # of a 32px-pitch stack.  Labels end at column 18 and values begin
            # at column 19, so neither field depends on the label's length.
            put(7, "CLOCKED SETTINGS", 8, 12)
            put(7, "MODE", 14, 16)
            put(7, "DIRECTION", 9, 18)
            put(7, "SOURCE", 12, 20)
            put(7, "BPM", 15, 22)
            put(7, "DEPTH", 13, 24)
        else:
            put(0, "PRESET", 2, 7)
            put(0, "BANDS", 2, 11)
            put(0, "FREQ:", 22, 11)
            put(0, "DRIVE", 2, 35)
            put(0, "RES", 2, 37)
            put(0, "FB", 2, 39)
            put_legacy_support_page_labels(
                put, frequency_col=22, input_depth_labels=False)
            put(7, "MODE", 2, 7)
            put(7, "DIRECTION", 2, 15)
            put(7, "SOURCE", 5, 20)
            put(7, "BPM", 8, 25)
            put(7, "DEPTH", 5, 30)
        m.submodules.text_mem = text_mem = Memory(
            shape=unsigned(6), depth=len(text_init), init=text_init)
        text_rport = text_mem.read_port(domain="dvi")
        text_wport = text_mem.write_port(domain="sync")
        page_offsets = Array(Const(page * page_cells, unsigned(14))
                             for page in range(8))
        text_address = Signal(unsigned(15))
        m.d.comb += [
            text_address.eq(
                page_offsets[text_page_q] + cell_y * 45 + cell_x),
            text_rport.addr.eq(text_address),
        ]

        # Dynamic labels are written into the tile RAM in short bursts at
        # 15 Hz. HDMI therefore sees only a BRAM read, never the control muxes.
        page_sync = Signal.like(self.page)
        preset_sync = Signal.like(self.preset)
        selected_sync = Signal.like(self.selected)
        editing_sync = Signal()
        clock_mode_sync = Signal()
        clock_algorithm_sync = Signal(unsigned(2))
        shift_direction_sync = Signal(unsigned(2))
        walk_style_sync = Signal()
        walk_drunk_sync = Signal(unsigned(2))
        walk_chance_index_sync = Signal(
            range(len(RezoCore.WALK_CHANCES)))
        turing_length_sync = Signal(unsigned(4))
        turing_change_index_sync = Signal(unsigned(3))
        clock_source_sync = Signal(unsigned(2))
        data_source_sync = Signal(unsigned(2))
        internal_clock_rate_sync = Signal(
            range(RezoCore.INTERNAL_CLOCK_MIN_BPM,
                  RezoCore.INTERNAL_CLOCK_MAX_BPM + 1))
        clock_external_active_sync = Signal()
        data_random_active_sync = Signal()
        turing_target_sync = Signal()
        turing_start_sync = Signal(range(RezoCore.N_BANDS))
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
        cv_targets_sync = [Signal(unsigned(4), name=f"text_cv_target{n}") for n in range(4)]
        m.submodules += [
            FFSynchronizer(self.page, page_sync),
            FFSynchronizer(self.preset, preset_sync),
            FFSynchronizer(self.selected, selected_sync),
            FFSynchronizer(self.editing, editing_sync),
            FFSynchronizer(self.clock_mode, clock_mode_sync),
            FFSynchronizer(self.clock_algorithm, clock_algorithm_sync),
            FFSynchronizer(self.shift_direction, shift_direction_sync),
            FFSynchronizer(self.walk_style, walk_style_sync),
            FFSynchronizer(self.walk_drunk, walk_drunk_sync),
            FFSynchronizer(self.walk_chance_index, walk_chance_index_sync),
            FFSynchronizer(self.turing_length, turing_length_sync),
            FFSynchronizer(self.turing_change_index,
                           turing_change_index_sync),
            FFSynchronizer(self.clock_source, clock_source_sync),
            FFSynchronizer(self.data_source, data_source_sync),
            FFSynchronizer(self.internal_clock_rate,
                           internal_clock_rate_sync),
            FFSynchronizer(self.clock_external_active,
                           clock_external_active_sync),
            FFSynchronizer(self.data_random_active,
                           data_random_active_sync),
            FFSynchronizer(self.turing_target, turing_target_sync),
            FFSynchronizer(self.turing_start, turing_start_sync),
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

        update_index = Signal(range(205))
        update_active = Signal(init=1)
        refresh_counter = Signal(range(4_000_000))
        writer_address = Signal(unsigned(15))
        writer_char = Signal(unsigned(6))
        writer_char_q = Signal.like(writer_char)
        writer_phase = Signal(unsigned(2))
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
            text_wport.data.eq(writer_char_q),
            text_wport.en.eq(update_active & (writer_phase == 2)),
        ]
        with m.If(selected_band_valid):
            m.d.comb += selected_band.eq(
                selected_sync - RezoHardwareUI.TARGET_BAND_BASE)

        # Fixed-width value slots are left-justified; trailing blanks clear
        # characters left behind when a shorter value replaces a longer one.
        preset_names = ("ALL ", "ODD ", "EVEN", "LOW ", "MID ", "HI  ", "ZERO")
        frequency_names = tuple(format_frequency_name(frequency)
                                for frequency in RezoCore.FREQUENCIES_HZ)
        displayed_layout = Signal(unsigned(2))
        m.d.comb += displayed_layout.eq(Mux(
            editing_sync & (selected_sync == RezoHardwareUI.TARGET_BAND_LAYOUT),
            frequency_layout_preview_sync, frequency_layout_sync))
        target_names = BASE_TARGET_NAMES + ("CLK", "RST", "DAT", "LCK")
        nav_names = NAV_NAMES
        def left_field(value, width, total=10):
            """Left-justify a value and clear its complete fixed-width slot."""
            return value[:width].ljust(total)

        direction_names = tuple(left_field(name, 9)
                                for name in ("FORWARD", "REVERSE",
                                             "PING PONG", "RANDOM"))
        walk_style_names = tuple(left_field(name, 4)
                                 for name in ("ALL", "BAND"))
        walk_drunk_names = tuple(left_field(name, 1)
                                 for name in ("1", "2", "3", "4"))
        walk_chance_names = tuple(left_field(name, 3)
                                  for name in ("0", "10", "25", "50",
                                               "75", "100"))
        algorithm_names = tuple(left_field(name, 6, 8)
                                for name in ("SHIFT", "ROTATE", "TURING",
                                             "WALK"))
        turing_length_names = tuple(left_field(str(value), 2)
                                    for value in range(2, 11))
        turing_change_names = tuple(
            left_field(str(value), 3)
            for value in (1, 3, 6, 12, 25, 50, 100))
        clock_source_names = tuple(left_field(name, 8)
                                   for name in ("AUTO INT", "AUTO EXT",
                                                "INTERNAL", "EXTERNAL"))
        data_source_names = tuple(left_field(name, 9)
                                  for name in ("CV", "RANDOM", "AUTO CV",
                                               "AUTO RAND"))
        turing_target_names = tuple(left_field(name, 5)
                                    for name in ("ALL", "RANGE"))
        turing_start_names = tuple(
            left_field(str(value), 2)
            for value in range(1, RezoCore.N_BANDS + 1))
        mode_names = ("BANK    ", "CLOCK   ")
        layout_names = LAYOUT_NAMES
        palette_names = PALETTE_NAMES
        damp_names = DAMP_NAMES
        save_names = SAVE_NAMES
        # Constant value strings used to elaborate into many parallel muxes.
        # Left justification changes their common-bit patterns enough to make
        # that representation costly on this nearly-full device. The refresh
        # writer holds each update index for three sync clocks, so one shared
        # synchronous character ROM can serve all fixed spelling tables
        # without an additional writer stage. Each spelling receives a
        # 16-character power-of-two slot, making live selection cheap. The
        # complete 2Kx6 image still occupies the same single DP16KD as the
        # earlier CLOCK-only 1Kx6 image.
        clock_value_tables = (
            ("direction", direction_names),
            ("walk_style", walk_style_names),
            ("walk_drunk", walk_drunk_names),
            ("walk_chance", walk_chance_names),
            ("algorithm", algorithm_names),
            ("turing_length", turing_length_names),
            ("turing_change", turing_change_names),
            ("clock_source", clock_source_names),
            ("data_source", data_source_names),
            ("turing_target", turing_target_names),
            ("turing_start", turing_start_names),
            ("mode", mode_names),
            ("nav", nav_names),
            ("preset", preset_names),
            ("target", target_names),
            ("palette", palette_names),
            ("damp", damp_names),
            ("save", save_names),
            ("layout", layout_names),
        )
        clock_value_bases = {}
        clock_value_init = [self.code(" ")] * 2048
        clock_value_next_base = 0
        for table_name, names in clock_value_tables:
            clock_value_bases[table_name] = clock_value_next_base
            for value_index, name in enumerate(names):
                value_base = clock_value_next_base + value_index * 16
                for pos, char in enumerate(name):
                    clock_value_init[value_base + pos] = self.code(char)
            clock_value_next_base += len(names) * 16
        clock_value_blank_address = clock_value_next_base
        m.submodules.clock_value_mem = clock_value_mem = Memory(
            shape=unsigned(6), depth=len(clock_value_init),
            init=clock_value_init, attrs={"ram_style": "block"})
        clock_value_rport = clock_value_mem.read_port()
        clock_value_address = Signal(unsigned(11))
        m.d.comb += [
            clock_value_address.eq(clock_value_blank_address),
            clock_value_rport.addr.eq(clock_value_address),
        ]
        clock_source_display = Signal(unsigned(2))
        data_source_display = Signal(unsigned(2))
        m.d.comb += clock_source_display.eq(Mux(
            clock_source_sync == RezoCore.CLOCK_SOURCE_AUTO,
            clock_external_active_sync,
            Mux(clock_source_sync == RezoCore.CLOCK_SOURCE_INTERNAL,
                2, 3)))
        m.d.comb += data_source_display.eq(Mux(
            data_source_sync == RezoCore.DATA_SOURCE_AUTO,
            Mux(data_random_active_sync, 3, 2),
            data_source_sync))
        # One 18-bit ROM serves both the compact three-character frequency
        # labels used on BANK/FEEDBACK and the full five-digit BANDS readout.
        # The 116-entry table uses power-of-two word offsets and still fits in
        # one DP16KD, keeping the address selection to cheap bitwise ORs.
        frequency_head_offset = 128
        frequency_tail_offset = 256
        frequency_label_init = [0] * (
            frequency_tail_offset + len(frequency_names))
        for index, name in enumerate(frequency_names):
            full_name = f"{RezoCore.FREQUENCIES_HZ[index]:<5}"
            frequency_label_init[index] = sum(
                self.code(name[pos]) << (6 * pos) for pos in range(3))
            frequency_label_init[frequency_head_offset + index] = sum(
                self.code(full_name[pos]) << (6 * pos) for pos in range(3))
            frequency_label_init[frequency_tail_offset + index] = sum(
                self.code(full_name[pos + 3]) << (6 * pos) for pos in range(2))
        m.submodules.frequency_label_mem = frequency_label_mem = Memory(
            shape=unsigned(18), depth=len(frequency_label_init),
            init=frequency_label_init, attrs={"ram_style": "block"})
        frequency_label_rport = frequency_label_mem.read_port()
        m.d.comb += frequency_label_rport.addr.eq(0)
        with m.Switch(update_index):
            with m.Case(7, 8, 9, 10):
                with m.If(selected_band_valid):
                    m.d.comb += frequency_label_rport.addr.eq(
                        Array(band_frequencies_sync)[selected_band])
            with m.Case(42, 43, 44, 45):
                with m.If(feedback_selected_valid):
                    m.d.comb += frequency_label_rport.addr.eq(
                        Array(band_frequencies_sync)[feedback_selected_band])
            with m.Case(65, 66, 67, 68):
                with m.If(bands_selected_valid):
                    bands_frequency_index = Mux(
                        editing_sync & bands_frequency_selected,
                        frequency_preview_sync,
                        Array(band_frequencies_sync)[bands_selected_band])
                    m.d.comb += frequency_label_rport.addr.eq(
                        bands_frequency_index | frequency_head_offset)
            with m.Case(69, 70):
                with m.If(bands_selected_valid):
                    bands_frequency_index = Mux(
                        editing_sync & bands_frequency_selected,
                        frequency_preview_sync,
                        Array(band_frequencies_sync)[bands_selected_band])
                    m.d.comb += frequency_label_rport.addr.eq(
                        bands_frequency_index | frequency_tail_offset)
        bpm_label_init = []
        for bpm in range(RezoCore.INTERNAL_CLOCK_MIN_BPM,
                         RezoCore.INTERNAL_CLOCK_MAX_BPM + 1):
            label = f"{bpm:<3}"
            bpm_label_init.append(sum(
                self.code(label[pos]) << (6 * pos) for pos in range(3)))
        m.submodules.bpm_label_mem = bpm_label_mem = Memory(
            shape=unsigned(18), depth=len(bpm_label_init),
            init=bpm_label_init, attrs={"ram_style": "block"})
        bpm_label_rport = bpm_label_mem.read_port()
        m.d.comb += bpm_label_rport.addr.eq(
            internal_clock_rate_sync - RezoCore.INTERNAL_CLOCK_MIN_BPM)
        damp_name_index = Signal(range(5))
        m.d.comb += damp_name_index.eq(Mux(
            damp_mode_sync > 4, 4, damp_mode_sync))
        save_name_index = Signal(range(len(save_names)))
        m.d.comb += save_name_index.eq(
            Mux(~save_available_sync, 4,
                Mux(save_busy_sync | (save_status_sync == 1), 1,
                    Mux(save_status_sync == 2, 2,
                        Mux(save_status_sync == 3, 3, 0)))))
        clock_text_page_offset_sync = Const(7 * page_cells, unsigned(15))
        def writer_cell(page, row, col, legacy_row=None, legacy_col=None):
            if self.compact_layout:
                return page * page_cells + row * 45 + col
            return (page * page_cells +
                    (legacy_row if legacy_row is not None else row) * 45 +
                    (legacy_col if legacy_col is not None else col))

        with m.Switch(update_index):
            for pos in range(4):
                with m.Case(pos):
                    m.d.comb += [
                        writer_address.eq(
                            page_offsets[page_sync] +
                            (8 if self.compact_layout else 3) * 45 +
                            (33 if self.compact_layout else 39) + pos),
                        clock_value_address.eq(
                            clock_value_bases["nav"] |
                            (editing_sync << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(4):
                with m.Case(4 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            # Preset names are fixed-width and use one native
                            # cell of left padding in the selector chip.
                            0, 11, 17 + pos, 7, 11 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["preset"] |
                            (preset_sync << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(3):
                with m.Case(8 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            0, 14, 29 + pos, 11, 28 + pos)),
                        writer_char.eq(Mux(
                            selected_band_valid,
                            frequency_label_rport.data.word_select(pos, 6),
                            0)),
                    ]
            for pos in range(3):
                with m.Case(39 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            0, 11, 30 + pos, 3, 29 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["mode"] |
                            (clock_mode_sync << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for n in range(4):
                row = 13 + n * 6
                for pos in range(3):
                    with m.Case(11 + n * 3 + pos):
                        audio_char = self.code("AUD"[pos])
                        # Both mode names begin at the chip's fixed text
                        # origin; the shorter spelling clears its last cell.
                        cv_char = self.code("CV "[pos])
                        m.d.comb += [
                            writer_address.eq(writer_cell(
                                2, compact_input_text_rows[n][0], 20 + pos,
                                row, 14 + pos)),
                            writer_char.eq(Mux(input_modes_sync[n], cv_char, audio_char)),
                        ]
                    with m.Case(23 + n * 3 + pos):
                        m.d.comb += [
                            writer_address.eq(writer_cell(
                                2, compact_input_text_rows[n][1], 20 + pos,
                                row + 2, 16 + pos)),
                            clock_value_address.eq(
                                clock_value_bases["target"] |
                                (cv_targets_sync[n] << 4) | pos),
                            writer_char.eq(Mux(
                                input_modes_sync[n],
                                clock_value_rport.data, 0)),
                        ]
            for pos in range(3):
                with m.Case(43 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            1, 16, 29 + pos, 11, 28 + pos)),
                        writer_char.eq(Mux(
                            feedback_selected_valid,
                            frequency_label_rport.data.word_select(pos, 6), 0)),
                    ]
            for pos in range(6):
                with m.Case(46 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            5, 17, 22 + pos, 15, 18 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["palette"] |
                            (palette_sync << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(7):
                with m.Case(52 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            5, 21, 22 + pos, 19, 18 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["save"] |
                            (save_name_index << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(5):
                with m.Case(172 + pos):
                    m.d.comb += [
                        writer_address.eq(
                            writer_cell(
                                1, NATIVE_FEEDBACK_DAMPING_TEXT_ROW,
                                NATIVE_FEEDBACK_DAMPING_TEXT_COL + pos,
                                32, 12 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["damp"] |
                            (damp_name_index << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(7):
                with m.Case(59 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            6, 11, 17 + pos, 7, 9 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["layout"] |
                            (displayed_layout << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(5):
                with m.Case(66 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            6, 22, 20 + pos, 22, 14 + pos)),
                        writer_char.eq(Mux(
                            bands_selected_valid,
                            frequency_label_rport.data.word_select(
                                pos if pos < 3 else pos - 3, 6),
                            0)),
                    ]
            for pos in range(3, 8):
                with m.Case(68 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            0, 11, 30 + pos, 3, 29 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["mode"] |
                            (clock_mode_sync << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            # Compact INPUT mode chips spell AUDIO in full. The legacy path
            # receives trailing blanks, so these extra refresh entries are
            # harmless there and keep one writer state machine for both.
            for n in range(4):
                for tail_pos, audio_ch in enumerate("IO"):
                    with m.Case(177 + n * 2 + tail_pos):
                        m.d.comb += [
                            writer_address.eq(writer_cell(
                                2, compact_input_text_rows[n][0],
                                23 + tail_pos,
                                13 + n * 6, 17 + tail_pos)),
                            writer_char.eq(Mux(
                                input_modes_sync[n], 0,
                                self.code(audio_ch))),
                        ]
            # DEPTH is a CV-only control. Refresh its label dynamically so an
            # AUDIO lane cannot retain the static label from another product.
            for n in range(4):
                for pos in range(5):
                    with m.Case(185 + n * 5 + pos):
                        m.d.comb += [
                            writer_address.eq(writer_cell(
                                2, compact_input_text_rows[n][2], 13 + pos,
                                13 + n * 6 + 4, 8 + pos)),
                            writer_char.eq(Mux(
                                input_modes_sync[n],
                                Const(self.code("DEPTH"[pos]), 6), 0)),
                        ]
            for pos in range(8):
                with m.Case(77 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            7, 16, 20 + pos, 7, 9 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["algorithm"] |
                            (clock_algorithm_sync << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(10):
                with m.Case(85 + pos):
                    direction_display = Mux(
                        clock_algorithm_sync ==
                        RezoCore.CLOCK_ALGORITHM_WALK,
                        RezoCore.SHIFT_RANDOM, shift_direction_sync)
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            7, 18, 20 + pos, 15, 12 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["direction"] |
                            (direction_display << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(10):
                with m.Case(95 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            7, 20, 20 + pos, 20, 12 + pos)),
                        clock_value_address.eq(
                            clock_value_bases["clock_source"] |
                            (clock_source_display << 4) | pos),
                        writer_char.eq(clock_value_rport.data),
                    ]
            for pos in range(3):
                with m.Case(105 + pos):
                    m.d.comb += [
                        writer_address.eq(writer_cell(
                            7, 22, 20 + pos, 25, 15 + pos)),
                        writer_char.eq(
                            bpm_label_rport.data.word_select(pos, 6)),
                    ]
            for row in range(4):
                for pos in range(6):
                    with m.Case(108 + row * 6 + pos):
                        if row == 0:
                            label_char = Mux(
                                clock_algorithm_sync ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                self.code("CHANGE"[pos]),
                                Mux(clock_algorithm_sync ==
                                    RezoCore.CLOCK_ALGORITHM_WALK,
                                    self.code(" STYLE"[pos]),
                                    Mux(clock_algorithm_sync ==
                                        RezoCore.CLOCK_ALGORITHM_SHIFT,
                                        self.code("  DATA"[pos]), 0)))
                        elif row == 1:
                            label_char = Mux(
                                clock_algorithm_sync ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                self.code(" BANDS"[pos]),
                                Mux(clock_algorithm_sync ==
                                    RezoCore.CLOCK_ALGORITHM_WALK,
                                    self.code(" DRUNK"[pos]), 0))
                        elif row == 2:
                            label_char = Mux(
                                clock_algorithm_sync ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                Mux(turing_target_sync ==
                                    RezoCore.TURING_TARGET_RANGE,
                                    self.code(" START"[pos]),
                                    self.code("LENGTH"[pos])),
                                Mux(clock_algorithm_sync ==
                                    RezoCore.CLOCK_ALGORITHM_WALK,
                                    self.code("CHANCE"[pos]), 0))
                        else:
                            label_char = Mux(
                                (clock_algorithm_sync ==
                                 RezoCore.CLOCK_ALGORITHM_TURING) &
                                (turing_target_sync ==
                                 RezoCore.TURING_TARGET_RANGE),
                                self.code("LENGTH"[pos]), 0)
                        m.d.comb += [
                            writer_address.eq(writer_cell(
                                7, 26 + row * 2, 12 + pos,
                                15 + row * 5, 24 + pos)),
                            writer_char.eq(label_char),
                        ]
            for row in range(4):
                for pos in range(10):
                    with m.Case(132 + row * 10 + pos):
                        value_address = Const(
                            clock_value_blank_address, unsigned(11))
                        if row == 0:
                            value_address = Mux(
                                clock_algorithm_sync ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                clock_value_bases["turing_change"] |
                                (turing_change_index_sync << 4) | pos,
                                Mux(clock_algorithm_sync ==
                                    RezoCore.CLOCK_ALGORITHM_WALK,
                                    clock_value_bases["walk_style"] |
                                    (walk_style_sync << 4) | pos,
                                    Mux(clock_algorithm_sync ==
                                        RezoCore.CLOCK_ALGORITHM_SHIFT,
                                        clock_value_bases["data_source"] |
                                        (data_source_display << 4) | pos,
                                        clock_value_blank_address)))
                        elif row == 1:
                            value_address = Mux(
                                clock_algorithm_sync ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                clock_value_bases["turing_target"] |
                                (turing_target_sync << 4) | pos,
                                Mux(clock_algorithm_sync ==
                                    RezoCore.CLOCK_ALGORITHM_WALK,
                                    clock_value_bases["walk_drunk"] |
                                    (walk_drunk_sync << 4) | pos,
                                    clock_value_blank_address))
                        elif row == 2:
                            value_address = Mux(
                                clock_algorithm_sync ==
                                RezoCore.CLOCK_ALGORITHM_TURING,
                                Mux(turing_target_sync ==
                                    RezoCore.TURING_TARGET_RANGE,
                                    clock_value_bases["turing_start"] |
                                    (turing_start_sync << 4) | pos,
                                    clock_value_bases["turing_length"] |
                                    ((turing_length_sync - 2) << 4) | pos),
                                Mux(clock_algorithm_sync ==
                                    RezoCore.CLOCK_ALGORITHM_WALK,
                                    clock_value_bases["walk_chance"] |
                                    (walk_chance_index_sync << 4) | pos,
                                    clock_value_blank_address))
                        else:
                            value_address = Mux(
                                (clock_algorithm_sync ==
                                 RezoCore.CLOCK_ALGORITHM_TURING) &
                                (turing_target_sync ==
                                 RezoCore.TURING_TARGET_RANGE),
                                clock_value_bases["turing_length"] |
                                ((turing_length_sync - 2) << 4) | pos,
                                clock_value_blank_address)
                        m.d.comb += [
                            writer_address.eq(writer_cell(
                                7, 26 + row * 2, 20 + pos,
                                15 + row * 5, 32 + pos)),
                            clock_value_address.eq(value_address),
                            writer_char.eq(clock_value_rport.data),
                        ]
        with m.If(update_active):
            # Hold each label index for three clocks: allow synchronous label
            # ROMs to settle, capture the selected character, then write it.
            # This pipelines the former ROM->selector->tile-RAM critical path
            # with only eight flip-flops instead of a full address/data stage.
            with m.If(writer_phase == 0):
                m.d.sync += writer_phase.eq(1)
            with m.Elif(writer_phase == 1):
                m.d.sync += [
                    writer_char_q.eq(writer_char),
                    writer_phase.eq(2),
                ]
            with m.Else():
                m.d.sync += writer_phase.eq(0)
                with m.If(update_index == 204):
                    m.d.sync += [
                        update_active.eq(0),
                        refresh_counter.eq(0),
                    ]
                with m.Else():
                    m.d.sync += update_index.eq(update_index + 1)
        with m.Elif(refresh_counter == 3_999_999):
            m.d.sync += [
                update_active.eq(1),
                update_index.eq(0),
                writer_phase.eq(0),
            ]
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
            glyph = FONT_5X7.get(ch, FONT_5X7[" "])
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
        # One shared rectangle keeps the pixel path shallow and gives every
        # native page the INPUT ROUTING page's canonical content bounds.
        content_y0 = Signal(unsigned(10), init=NATIVE_CONTENT_PANEL_Y0 if self.compact_layout else 190)
        content_y1 = Signal(unsigned(10), init=NATIVE_CONTENT_PANEL_Y1 if self.compact_layout else 666)
        m.d.dvi += [
            content_y0.eq(Mux(self.compact_layout,
                              NATIVE_CONTENT_PANEL_Y0, 190)),
            content_y1.eq(Mux(self.compact_layout,
                              NATIVE_CONTENT_PANEL_Y1,
                              Mux(tune_page, 684, 666))),
        ]
        content_panel = active & self.rect(
            x, y, NATIVE_CONTENT_PANEL_X0 if self.compact_layout else 28,
            content_y0,
            NATIVE_CONTENT_PANEL_X1 if self.compact_layout else 692,
            content_y1)
        control_panel_x0 = 283 if self.compact_layout else 118
        control_panel_x1 = 594 if self.compact_layout else 650
        tune_panel_x0 = NATIVE_FEEDBACK_TRACK_X0 if self.compact_layout else 144
        tune_panel_x1 = NATIVE_FEEDBACK_TRACK_X1 if self.compact_layout else 650
        if self.compact_layout:
            bank_meter_rows = Const(0)
            for row_y0 in compact_main_control_y0s[:3]:
                bank_meter_rows = bank_meter_rows | self.rect(
                    x, y, control_panel_x0, row_y0 - 2,
                    control_panel_x1, row_y0 + 18)
        else:
            bank_meter_rows = (
                self.rect(x, y, 118, 552, 650, 576) |
                self.rect(x, y, 118, 584, 650, 608) |
                self.rect(x, y, 118, 616, 650, 640))
        meter_panel = active & (
            (bank_page & bank_meter_rows) |
            (tune_page & Mux(
                self.compact_layout,
                native_feedback_track_rows(
                    self.rect, x, y, tune_panel_x0, tune_panel_x1),
                (self.rect(x, y, tune_panel_x0, 408,
                           tune_panel_x1, 432) |
                 self.rect(x, y, tune_panel_x0, 456,
                           tune_panel_x1, 480)))))
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
        damp_chip = tune_page & self.rect(
            x, y, (NATIVE_FEEDBACK_DAMPING_CHIP_X0
                   if self.compact_layout else 156),
            NATIVE_FEEDBACK_DAMPING_CHIP_Y0 if self.compact_layout else 504,
            (NATIVE_FEEDBACK_DAMPING_CHIP_X1
             if self.compact_layout else 316),
            NATIVE_FEEDBACK_DAMPING_CHIP_Y1 if self.compact_layout else 536)
        damp_select = tune_page & (
            self.selected == RezoHardwareUI.TARGET_DAMP) & self.outline(
                x, y, 260 if self.compact_layout else 150,
                (NATIVE_FEEDBACK_DAMPING_CHIP_Y0 - 4
                 if self.compact_layout else 500),
                364 if self.compact_layout else 322,
                (NATIVE_FEEDBACK_DAMPING_CHIP_Y1 + 4
                 if self.compact_layout else 540), t=3)
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
        # BANK and CLOCK share one fixed left origin and selector geometry.
        compact_mode_x1 = 564
        mode_chip = home_page & self.rect(
            x, y, 464 if self.compact_layout else 452,
            167 if self.compact_layout else 28,
            compact_mode_x1 if self.compact_layout else 600,
            199 if self.compact_layout else 80)
        mode_select = home_page & (
            self.selected == RezoHardwareUI.TARGET_MODE) & self.outline(
                x, y, 460 if self.compact_layout else 452,
                163 if self.compact_layout else 28,
                compact_mode_x1 + 4 if self.compact_layout else 600,
                203 if self.compact_layout else 80, t=3)
        clock_turing_active = clock_page & (
            self.clock_algorithm == RezoCore.CLOCK_ALGORITHM_TURING)
        clock_data_active = clock_page & (
            self.clock_algorithm == RezoCore.CLOCK_ALGORITHM_SHIFT)
        clock_walk_active = clock_page & (
            self.clock_algorithm == RezoCore.CLOCK_ALGORITHM_WALK)
        clock_value_x0 = 304 if self.compact_layout else 192
        clock_algorithm_x1 = 432 if self.compact_layout else 272
        clock_direction_x1 = 480 if self.compact_layout else 352
        clock_source_x1 = 464 if self.compact_layout else 352
        clock_rate_x1 = 384 if self.compact_layout else 240
        clock_depth_x1 = 588 if self.compact_layout else 680
        # Each algorithm-specific field is sized to the longest value that
        # field can contain, rather than inheriting the widest CLOCK value.
        # The chip and its selection outline share these endpoints.
        if self.compact_layout:
            # Algorithm-specific rows use the maximum value for the field
            # currently occupying that row: DATA/CHANGE/STYLE,
            # BANDS/DRUNK, and START-or-LENGTH/CHANCE respectively.
            clock_right0_x1 = Mux(
                clock_turing_active, 370,
                Mux(clock_walk_active, 386, 466))
            clock_right1_x1 = Mux(clock_turing_active, 410, 346)
            clock_right2_x1 = Mux(clock_turing_active, 354, 370)
        else:
            clock_right0_x1 = 672
            clock_right1_x1 = 672
            clock_right2_x1 = 672
        clock_right3_x1 = 354 if self.compact_layout else 672
        clock_algorithm_chip = clock_page & self.rect(
            x, y, 304 if self.compact_layout else 136,
            252 if self.compact_layout else 100,
            clock_algorithm_x1,
            274 if self.compact_layout else 138)
        clock_direction_chip = clock_page & self.rect(
            x, y, clock_value_x0,
            284 if self.compact_layout else 228,
            clock_direction_x1,
            306 if self.compact_layout else 268)
        clock_source_chip = clock_page & self.rect(
            x, y, clock_value_x0,
            316 if self.compact_layout else 308,
            clock_source_x1,
            338 if self.compact_layout else 348)
        clock_rate_chip = clock_page & self.rect(
            x, y, clock_value_x0,
            348 if self.compact_layout else 388,
            clock_rate_x1,
            370 if self.compact_layout else 428)
        clock_depth_chip = clock_page & self.rect(
            x, y, 304 if self.compact_layout else 168,
            380 if self.compact_layout else 476,
            clock_depth_x1,
            402 if self.compact_layout else 500)
        clock_depth_fill_x0 = 306 if self.compact_layout else 168
        clock_depth_fill_x1 = 586 if self.compact_layout else clock_depth_x1
        clock_depth_end = Signal(unsigned(10))
        m.d.comb += clock_depth_end.eq(
            # The user control is 0..128. Map it across the complete inner
            # 280-pixel lane (2.1875 pixels/step), leaving the shared 2-pixel
            # inset at either side of the chip.
            clock_depth_fill_x0 + (self.clock_depth << 1) +
            (self.clock_depth >> 3) + (self.clock_depth >> 4))
        clock_depth_fill = Mux(
            self.compact_layout,
            clock_page & (x >= clock_depth_fill_x0) &
            (x < Mux(clock_depth_end < clock_depth_fill_x1,
                     clock_depth_end, clock_depth_fill_x1)) &
            (y >= 382) & (y < 400),
            clock_page & self.rect(
                x, y, 168, 480, 168 + (self.clock_depth << 2), 496))
        clock_right0_chip = (clock_turing_active | clock_data_active |
                             clock_walk_active) & self.rect(
            x, y,
            304 if self.compact_layout else 512,
            412 if self.compact_layout else 228,
            clock_right0_x1 if self.compact_layout else 672,
            434 if self.compact_layout else 268)
        clock_right1_chip = (clock_turing_active | clock_walk_active) & self.rect(
            x, y,
            304 if self.compact_layout else 512,
            444 if self.compact_layout else 308,
            clock_right1_x1 if self.compact_layout else 672,
            466 if self.compact_layout else 348)
        clock_right2_chip = (clock_turing_active | clock_walk_active) & self.rect(
            x, y,
            304 if self.compact_layout else 512,
            476 if self.compact_layout else 388,
            clock_right2_x1 if self.compact_layout else 672,
            498 if self.compact_layout else 428)
        clock_right3_chip = clock_turing_active & (
            self.turing_target == RezoCore.TURING_TARGET_RANGE) & self.rect(
            x, y,
            304 if self.compact_layout else 512,
            508 if self.compact_layout else 468,
            clock_right3_x1,
            530 if self.compact_layout else 508)
        clock_chip = (clock_algorithm_chip | clock_direction_chip |
                      clock_source_chip | clock_rate_chip | clock_depth_chip |
                      clock_right0_chip | clock_right1_chip |
                      clock_right2_chip | clock_right3_chip)
        if self.compact_layout:
            clock_select = clock_page & (
                ((self.selected == RezoHardwareUI.TARGET_CLOCK_ALGORITHM) &
                 self.outline(x, y, 300, 249, 436, 277, t=3)) |
                (~clock_walk_active &
                 (self.selected == RezoHardwareUI.TARGET_SHIFT_DIRECTION) &
                 self.outline(x, y, 300, 281,
                              clock_direction_x1 + 4, 309, t=3)) |
                ((self.selected == RezoHardwareUI.TARGET_CLOCK_SOURCE) &
                 self.outline(x, y, 300, 313,
                              clock_source_x1 + 4, 341, t=3)) |
                ((self.selected == RezoHardwareUI.TARGET_CLOCK_RATE) &
                 self.outline(x, y, 300, 345,
                              clock_rate_x1 + 4, 373, t=3)) |
                ((self.selected == RezoHardwareUI.TARGET_CLOCK_DEPTH) &
                 self.outline(x, y, 300, 377,
                              clock_depth_x1 + 4, 405, t=3)) |
                ((clock_data_active &
                  (self.selected == RezoHardwareUI.TARGET_DATA_SOURCE) |
                  clock_turing_active &
                  (self.selected == RezoHardwareUI.TARGET_TURING_CHANGE) |
                  clock_walk_active &
                  (self.selected == RezoHardwareUI.TARGET_WALK_STYLE)) &
                 self.outline(x, y, 300, 409,
                              clock_right0_x1 + 4, 437, t=3)) |
                ((clock_turing_active &
                  (self.selected == RezoHardwareUI.TARGET_TURING_TARGET) |
                  clock_walk_active &
                  (self.selected == RezoHardwareUI.TARGET_WALK_DRUNK)) &
                 self.outline(x, y, 300, 441,
                              clock_right1_x1 + 4, 469, t=3)) |
                ((clock_turing_active &
                  (self.turing_target == RezoCore.TURING_TARGET_RANGE) &
                  (self.selected == RezoHardwareUI.TARGET_TURING_START) |
                  clock_turing_active &
                  (self.turing_target != RezoCore.TURING_TARGET_RANGE) &
                  (self.selected == RezoHardwareUI.TARGET_TURING_LENGTH) |
                  clock_walk_active &
                  (self.selected == RezoHardwareUI.TARGET_WALK_CHANCE)) &
                 self.outline(x, y, 300, 473,
                              clock_right2_x1 + 4, 501, t=3)) |
                (clock_turing_active &
                 (self.turing_target == RezoCore.TURING_TARGET_RANGE) &
                 (self.selected == RezoHardwareUI.TARGET_TURING_LENGTH) &
                 self.outline(x, y, 300, 505,
                              clock_right3_x1 + 4, 533, t=3)))
        else:
            clock_select = clock_page & (
            ((self.selected == RezoHardwareUI.TARGET_CLOCK_ALGORITHM) &
             self.outline(x, y, 131, 95, 277, 143, t=3)) |
            (clock_page & ~clock_walk_active &
             (self.selected == RezoHardwareUI.TARGET_SHIFT_DIRECTION) &
             self.outline(x, y, 187, 223, 357, 273, t=3)) |
            ((self.selected == RezoHardwareUI.TARGET_CLOCK_SOURCE) &
             self.outline(x, y, 187, 303, 357, 353, t=3)) |
            ((self.selected == RezoHardwareUI.TARGET_CLOCK_RATE) &
             self.outline(x, y, 187, 383, 357, 433, t=3)) |
            ((self.selected == RezoHardwareUI.TARGET_CLOCK_DEPTH) &
             self.outline(x, y, 164, 476, 684, 500, t=3)) |
            (clock_data_active &
             (self.selected == RezoHardwareUI.TARGET_DATA_SOURCE) &
             self.outline(x, y, 507, 223, 677, 273, t=3)) |
            (clock_turing_active &
             (self.selected == RezoHardwareUI.TARGET_TURING_CHANGE) &
             self.outline(x, y, 507, 223, 677, 273, t=3)) |
            (clock_walk_active &
             (self.selected == RezoHardwareUI.TARGET_WALK_STYLE) &
             self.outline(x, y, 507, 223, 677, 273, t=3)) |
            (clock_turing_active &
             (self.selected == RezoHardwareUI.TARGET_TURING_TARGET) &
             self.outline(x, y, 507, 303, 677, 353, t=3)) |
            (clock_walk_active &
             (self.selected == RezoHardwareUI.TARGET_WALK_DRUNK) &
             self.outline(x, y, 507, 303, 677, 353, t=3)) |
            (clock_turing_active &
             (self.turing_target == RezoCore.TURING_TARGET_RANGE) &
             (self.selected == RezoHardwareUI.TARGET_TURING_START) &
             self.outline(x, y, 507, 383, 677, 433, t=3)) |
            (clock_turing_active &
             (self.selected == RezoHardwareUI.TARGET_TURING_LENGTH) &
             self.outline(x, y, 507,
                          Mux(self.turing_target == RezoCore.TURING_TARGET_RANGE,
                              463, 383),
                          677,
                          Mux(self.turing_target == RezoCore.TURING_TARGET_RANGE,
                              513, 433), t=3)) |
            (clock_walk_active &
             (self.selected == RezoHardwareUI.TARGET_WALK_CHANCE) &
             self.outline(x, y, 507, 383, 677, 433, t=3)))

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
                m.d.dvi += [
                    input_gain_ends[n].eq(
                        native_input_gain_endpoint(self.input_gains[n])),
                    input_depth_ends[n].eq(
                        native_input_depth_endpoint(self.cv_depths[n])),
                    input_meter_ends[n].eq(Mux(
                        self.input_modes[n] == RezoCore.INPUT_MODE_CV,
                        input_control_mid + (self.input_meters[n] << 2),
                        input_control_x0 + (self.input_meters[n] << 3))),
                ]
            else:
                m.d.dvi += [
                    input_gain_ends[n].eq(
                        326 + self.input_gains[n] + (self.input_gains[n] >> 2)),
                    input_depth_ends[n].eq(
                        490 + self.cv_depths[n] + (self.cv_depths[n] >> 2)),
                    input_meter_ends[n].eq(Mux(
                        self.input_modes[n] == RezoCore.INPUT_MODE_CV,
                        490 + (self.input_meters[n] << 2) + self.input_meters[n],
                        326 + (self.input_meters[n] << 3) +
                              (self.input_meters[n] << 1))),
                ]

        # A shared four-cell value field with a fixed one-cell left inset.
        compact_preset_x1 = 352
        preset_chip_signals.append(bank_page & self.rect(
            x, y,
            256 if self.compact_layout else 136,
            167 if self.compact_layout else 100,
            compact_preset_x1 if self.compact_layout else 264,
            199 if self.compact_layout else 138))
        preset_select_signals.append(
            bank_page & self.editing & (self.selected == RezoHardwareUI.TARGET_PRESET) &
            self.outline(
                x, y,
                252 if self.compact_layout else 131,
                163 if self.compact_layout else 95,
                compact_preset_x1 + 4 if self.compact_layout else 269,
                203 if self.compact_layout else 143, t=3))

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
               (band_y_value_q >= bands_frequency_y0 + bands_button_h + 3)))))
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
                (band_bank_page_value_q & band_enable_q & base_bank_fill) |
                (band_tune_page_value_q & band_enable_q & band_fill_x_q &
                 band_slot_y & band_feedback_send_q) |
                # BANDS enable buttons intentionally reuse FEEDBACK's exact
                # full-height filled-button treatment.
                (band_bands_page_value_q & band_fill_x_q & band_enable_q &
                 (band_y_value_q >= bands_enable_y0) &
                 (band_y_value_q < bands_enable_y0 + bands_button_h)))),
            band_mod_fill.eq(
                band_active_value_q & band_bank_page_value_q & band_enable_q &
                (base_bank_fill ^ effective_bank_fill) & ~base_marker),
        ]
        band_select_q0 = (
            (band_bank_page_value_q & band_enable_q & selected_band &
             bank_selection_outline) |
            (band_tune_page_value_q & band_enable_q & feedback_band_selected &
             feedback_selection_outline) | (
                band_bands_page_value_q &
                (enable_band_selected | frequency_band_selected) &
                bands_edit_outline))

        # Decode the four repeated INPUT rows through one BRAM-backed local-y
        # path. Besides saving four parallel geometry copies, this provides a
        # cheap place to draw the one-pixel input telemetry line.
        input_y_init = []
        # Anchor the repeated geometry one native pixel above the text-cell
        # origin. The font's visible seven-row glyph occupies pixels 1..14 of
        # its 16px cell, so this makes every chip's geometric centre coincide
        # with the visible glyph centre for all four repeated groups.
        input_first_y = 221 if self.compact_layout else 194
        for pixel_y in range(self.PANEL_H):
            if input_first_y <= pixel_y < input_first_y + 384:
                input_offset = pixel_y - input_first_y
                input_index_init = input_offset // 96
                input_local_init = input_offset % 96
                input_y_init.append(
                    input_local_init | (input_index_init << 7) | (1 << 9))
            else:
                input_y_init.append(0)
        m.submodules.input_y_mem = input_y_mem = Memory(
            shape=unsigned(10), depth=self.PANEL_H, init=input_y_init,
            attrs={"ram_style": "block"})
        input_y_rport = input_y_mem.read_port(domain="dvi")
        m.d.comb += input_y_rport.addr.eq(y)

        input_x_q = Signal.like(x)
        input_index_q = Signal(unsigned(2))
        m.d.dvi += [
            input_x_q.eq(x + 1),
            # Retiming only the repeated-row selector removes the BRAM
            # clock-to-output delay from the endpoint muxes without disturbing
            # local-X/Y geometry. The selector settles at the blank left edge,
            # hundreds of pixels before the first INPUT control at x=304.
            input_index_q.eq(input_y_rport.data[7:9]),
        ]
        input_local_y = input_y_rport.data[:7]
        input_index = input_index_q
        input_row_valid = input_y_rport.data[9]
        input_mode = Array(self.input_modes)[input_index]
        input_depth = Array(self.cv_depths)[input_index]
        input_meter = Array(self.input_meters)[input_index]
        input_gain_end = Array(input_gain_ends)[input_index]
        input_depth_end = Array(input_depth_ends)[input_index]
        input_meter_end = Array(input_meter_ends)[input_index]
        input_target = Signal(unsigned(7))
        m.d.comb += input_target.eq(
            RezoHardwareUI.TARGET_INPUT_BASE + input_index +
            (input_index << 1))
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
        # MODE and VALUE chips are sized around each field's longest value;
        # every value begins at the same fixed text-cell origin.
        input_mode_x1 = 402 if self.compact_layout else 304
        input_value_x1 = 370 if self.compact_layout else 656
        input_panel_q0 = input_visible & (
            self.rect(input_x_value_q, input_local_value_q,
                      304 if self.compact_layout else 116,
                      0 if self.compact_layout else 4,
                      input_mode_x1 if self.compact_layout else 304,
                      20 if self.compact_layout else 32) |
            Mux(input_is_cv,
                self.rect(input_x_value_q, input_local_value_q,
                          304 if self.compact_layout else 116,
                          32 if self.compact_layout else 36,
                          input_value_x1 if self.compact_layout else 656,
                          52 if self.compact_layout else 64),
                self.rect(input_x_value_q, input_local_value_q,
                          304 if self.compact_layout else 116,
                          32 if self.compact_layout else 36,
                          576 if self.compact_layout else 656,
                          52 if self.compact_layout else 64)) |
            (input_is_cv & self.rect(
                input_x_value_q, input_local_value_q,
                304 if self.compact_layout else 116,
                64 if self.compact_layout else 68,
                576 if self.compact_layout else 656,
                84 if self.compact_layout else 96)))
        input_select_q0 = input_visible & (
            ((input_row_selected_q == input_target_q) &
             self.outline(input_x_value_q, input_local_value_q,
                          300 if self.compact_layout else 112,
                          0,
                          input_mode_x1 + 4 if self.compact_layout else 308,
                          24 if self.compact_layout else 36, t=3)) |
            ((input_row_selected_q == input_target_q + 1) & Mux(
                input_is_cv,
                self.outline(input_x_value_q, input_local_value_q,
                             300 if self.compact_layout else 112,
                             28 if self.compact_layout else 32,
                             input_value_x1 + 4 if self.compact_layout else 660,
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
                          66 if self.compact_layout else 75,
                          input_depth_end_q, 82 if self.compact_layout else 89),
                self.rect(input_x_value_q, input_local_value_q,
                          input_depth_end_q, 66 if self.compact_layout else 75,
                          440 if self.compact_layout else 490,
                          82 if self.compact_layout else 89)),
            self.rect(input_x_value_q, input_local_value_q,
                      NATIVE_INPUT_FILL_X0 if self.compact_layout else 326,
                      34 if self.compact_layout else 43,
                      input_gain_end_q, 50 if self.compact_layout else 57))
        input_unity_coarse = RezoCore.INPUT_UNITY_POS >> 8
        input_unity_x = (native_input_unity_x(RezoCore.INPUT_UNITY_POS)
                         if self.compact_layout else (
                             326 + ((RezoCore.INPUT_UNITY_POS >> 11) * 10)))
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
                input_unity_x + 3, 54 if self.compact_layout else 61)))
        input_meter_q0 = input_visible & Mux(
            input_is_cv,
            Mux(~input_meter_negative_q,
                self.rect(input_x_value_q, input_local_value_q,
                          440 if self.compact_layout else 490,
                          82 if self.compact_layout else 65,
                          input_meter_end_q, 84 if self.compact_layout else 66),
                self.rect(input_x_value_q, input_local_value_q,
                          input_meter_end_q, 82 if self.compact_layout else 65,
                          440 if self.compact_layout else 490,
                          84 if self.compact_layout else 66)),
            self.rect(input_x_value_q, input_local_value_q,
                      304 if self.compact_layout else 326,
                      50 if self.compact_layout else 65,
                      input_meter_end_q, 52 if self.compact_layout else 66))

        for group in range(RezoCore.N_GROUPS):
            rail_y = (compact_group_centers[group]
                      if self.compact_layout else 305 + group * 64)
            group_cell_signals.append(
                group_page & self.rect(
                    x, y,
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
                group_selected_x_pre.eq(
                    (208 + group_selected_index * 34
                     if self.compact_layout else
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
        group_band_q = Signal.like(group_band)
        group_row_q = Signal.like(group_row)
        group_band_active_q = Signal()
        group_row_active_q = Signal()
        group_row_edge_q = Signal()
        group_page_q = Signal()
        group_band_enabled_q = Signal()
        bank_group_mask_array = Array(self.bank_groups)
        band_enable_mask_array = Array(self.band_enables)
        m.d.comb += [
            group_band.eq(0),
            group_row.eq(0),
            group_band_active.eq(0),
            group_row_active.eq(0),
            # Every group marker begins at y mod 64 == 38 and is 24 pixels
            # tall. Two short comparisons shared by all forty cells retain
            # only its top and bottom ghost rails.
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
                marker_y = compact_group_centers[group] - 9
                with m.If((y >= marker_y) & (y < marker_y + 20)):
                    m.d.comb += [
                        group_row.eq(group),
                        group_row_active.eq(1),
                        group_row_edge.eq(
                            (y < marker_y + 2) | (y >= marker_y + 18)),
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
        ]
        m.d.comb += group_fill.eq(
            group_page_q & group_band_active_q & group_row_active_q &
            group_band_enabled_q &
            bank_group_mask_array[group_band_q].bit_select(group_row_q, 1))
        # Disabled BANK bands retain dim top/bottom rails at all four GROUPS
        # assignments. A full forty-cell rectangle decoder costs more logic
        # than remains available; these shared rails preserve location and
        # inactive state without implying an enabled assignment.
        m.d.comb += group_ghost.eq(
            group_page_q & group_band_active_q & group_row_active_q &
            group_row_edge_q & ~group_band_enabled_q)

        # OUTPUT has a fixed 4x5 grid. Decode its column geometry in a small
        # block ROM instead of keeping five parallel sets of wide
        # pixel-coordinate comparators in the packed renderer.  The x lookup
        # prefetches the following pixel, matching the synchronous ROM latency.
        # Row decoding remains combinational so this change does not add a
        # second constrained lookup to the floorplan.
        output_col_init = []
        for address in range(self.PANEL_W):
            pixel_x = address + 1
            encoded = 0
            for source in range(5):
                cell_width = 56 if self.compact_layout else 72
                cell_x0 = (compact_output_col_centers[source] - 27
                           if self.compact_layout else 188 + source * 96)
                if cell_x0 <= pixel_x < cell_x0 + cell_width:
                    encoded = source
                    encoded |= 1 << 4  # active
                    if (pixel_x < cell_x0 + 2 or
                            pixel_x >= cell_x0 + cell_width - 2):
                        encoded |= 1 << 3  # edge
                    break
            output_col_init.append(encoded)
        m.submodules.output_col_mem = output_col_mem = Memory(
            shape=unsigned(5), depth=self.PANEL_W, init=output_col_init,
            attrs={"ram_style": "block"})
        output_col_rport = output_col_mem.read_port(domain="dvi")
        m.d.comb += output_col_rport.addr.eq(x.as_unsigned())

        output_row = Signal(unsigned(2))
        output_source = output_col_rport.data[:3]
        output_row_edge = Signal()
        output_row_active = Signal()
        output_col_edge = output_col_rport.data[3]
        output_col_active = output_col_rport.data[4]
        m.submodules.output_send_mem = output_send_mem = Memory(
            shape=unsigned(5), depth=20, init=[0] * 20,
            attrs={"ram_style": "block"})
        output_send_rport = output_send_mem.read_port(domain="dvi")
        output_send_wport = output_send_mem.write_port(domain="sync")
        m.d.comb += [
            output_send_wport.addr.eq(self.output_send_write_addr),
            output_send_wport.data.eq(self.output_send_write_data),
            output_send_wport.en.eq(self.output_send_write_en),
        ]
        output_cell_x0 = Signal(unsigned(10))
        output_cell_y0 = Signal(unsigned(10))
        output_send_index = Signal(unsigned(5))
        m.d.comb += [
            output_row.eq(0),
            output_row_active.eq(0),
            output_row_edge.eq(0),
            output_cell_x0.eq(
                (243 + (output_source << 6) +
                 Mux(output_source == 4, 8, 0))
                if self.compact_layout else
                188 + (output_source << 6) + (output_source << 5)),
            output_cell_y0.eq(326),
            output_send_index.eq(output_source + (output_row << 2) + output_row),
            output_send_rport.addr.eq(output_send_index),
        ]
        for output in range(4):
            row_y = (compact_output_row_centers[output] - 13
                     if self.compact_layout else 326 + output * 80)
            with m.If((y >= row_y) & (y < row_y + 28)):
                m.d.comb += [
                    output_row.eq(output),
                    output_row_active.eq(1),
                    output_row_edge.eq((y < row_y + 2) | (y >= row_y + 26)),
                    output_cell_y0.eq(row_y),
                ]
        output_x_inner_q = Signal(unsigned(10))
        output_x_inside_q = Signal()
        output_y_inside_q = Signal()
        output_row_active_q = Signal()
        output_col_active_q = Signal()
        output_page_q = Signal()
        m.d.dvi += [
            # Register position relative to the fill origin before consuming the
            # synchronous send RAM.  This removes the offset carry chain from
            # the RAM-to-pixel path while retaining the compact raw 5-bit value.
            output_x_inner_q.eq(x - output_cell_x0 - 4),
            output_x_inside_q.eq(x >= output_cell_x0 + 4),
            output_y_inside_q.eq(
                (y >= output_cell_y0 + 5) & (y < output_cell_y0 + 23)),
            output_row_active_q.eq(output_row_active),
            output_col_active_q.eq(output_col_active),
            output_page_q.eq(output_page),
        ]
        output_send_width = Signal(unsigned(7))
        if self.compact_layout:
            m.d.comb += output_send_width.eq(
                output_send_rport.data + (output_send_rport.data << 1))
        else:
            m.d.comb += output_send_width.eq(output_send_rport.data << 2)
        m.d.comb += [
            output_cell.eq(output_page & output_row_active & output_col_active &
                           (output_row_edge | output_col_edge)),
            output_fill.eq(
                output_page_q & output_row_active_q & output_col_active_q &
                output_y_inside_q & output_x_inside_q &
                (output_x_inner_q < output_send_width)),
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
            # Solid header bars distinguish relative row/column edits from
            # the outlined individual matrix cells.
            output_header_select.eq(output_header_selection(
                page=output_page,
                row_active=output_row_active,
                col_active=output_col_active,
                row_target=output_header_row_target,
                col_target=output_header_col_target,
                selected_row=output_header_row,
                selected_col=output_header_col,
                matrix_row=output_row,
                matrix_col=output_source,
                dry_selected=(
                    self.selected == RezoHardwareUI.TARGET_OUTPUT_DRY_COL),
                x=x, y=y, compact=self.compact_layout)),
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
        group_select_q0 = tile_registered_or(group_select_signals, "group_select")
        output_cell_q0 = Signal()
        output_fill_q0 = Signal()
        output_select_q0 = Signal()
        m.d.dvi += [
            output_cell_q0.eq(output_cell),
            output_select_q0.eq(output_select),
        ]
        m.d.dvi += output_fill_q0.eq(output_fill)
        m.d.comb += group_fill_q0.eq(group_fill)

        m.d.comb += preset_group_select.eq(
            bank_page & (self.selected == RezoHardwareUI.TARGET_PRESET) &
            ~self.editing & self.outline(
                x, y,
                252 if self.compact_layout else 131,
                164 if self.compact_layout else 95,
                356 if self.compact_layout else 269,
                204 if self.compact_layout else 143, t=3))
        bank_control_y0s = (
            compact_main_control_y0s[:3] if self.compact_layout
            else (556, 588, 620))
        bank_panel_bounds = tuple(
            (row_y0 - 2, row_y0 + 18) for row_y0 in bank_control_y0s)
        drive_select = (
            bank_page & (self.selected == RezoHardwareUI.TARGET_DRIVE) &
            self.outline(x, y,
                         283 if self.compact_layout else 118,
                         bank_panel_bounds[0][0],
                         594 if self.compact_layout else 650,
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
            bank_control_fill = bank_control_visible & self.rect(
                bank_control_x_q, bank_control_y_q, 124, bank_control_y0_q,
                124 + (bank_control_base_q << 2), bank_control_y0_q + 16)
            bank_control_effective_fill = bank_control_visible & self.rect(
                bank_control_x_q, bank_control_y_q, 124, bank_control_y0_q,
                124 + (bank_control_effective_q << 2), bank_control_y0_q + 16)
            bank_control_mod_marker = bank_control_visible & self.rect(
                bank_control_x_q, bank_control_y_q,
                122 + (bank_control_base_q << 2), bank_control_y0_q - 2,
                126 + (bank_control_base_q << 2), bank_control_y0_q + 18)
        bank_control_mod_fill = (
            bank_control_fill ^ bank_control_effective_fill)
        tune_feedback_fill = Mux(
            self.compact_layout,
            tune_page & compact_fader_x_valid &
            (compact_fader_threshold <= self.feedback) &
            (y >= NATIVE_FEEDBACK_AMOUNT_Y0) &
            (y < NATIVE_FEEDBACK_AMOUNT_Y0 + 16),
            tune_page & self.rect(
                x, y, 156, 380, 124 + (self.feedback << 2), 396))
        tune_feedback_select = (
            tune_page &
            (self.selected == RezoHardwareUI.TARGET_FEEDBACK) & Mux(
                self.compact_layout,
                self.outline(x, y, 283,
                             NATIVE_FEEDBACK_AMOUNT_Y0 - 4, 594,
                             NATIVE_FEEDBACK_AMOUNT_Y0 + 20, t=3),
                self.rect(x, y, 144, 376, 148, 400)))
        dry_fill = Mux(
            self.compact_layout,
            tune_page & compact_fader_x_valid &
            (compact_fader_threshold <= self.limit_knee) &
            (y >= NATIVE_FEEDBACK_KNEE_Y0) &
            (y < NATIVE_FEEDBACK_KNEE_Y0 + 16),
            tune_page & self.rect(
                x, y, 156, 412, 124 + (self.limit_knee << 2), 428))
        dry_select = (tune_page &
                      (self.selected == RezoHardwareUI.TARGET_LIMIT_KNEE)) & self.rect(
            x, y, 144, 412, 148, 428)
        tune_cap_fill = Mux(
            self.compact_layout,
            tune_page & compact_fader_x_valid &
            (compact_fader_threshold <= self.limit_cap) &
            (y >= NATIVE_FEEDBACK_CEILING_Y0) &
            (y < NATIVE_FEEDBACK_CEILING_Y0 + 16),
            tune_page & self.rect(
                x, y, 156, 460, 124 + (self.limit_cap << 2), 476))
        res_select = ((bank_page & (self.selected == RezoHardwareUI.TARGET_RESONANCE)) |
                      (tune_page & (self.selected == RezoHardwareUI.TARGET_LIMIT_CAP))) & (
            (bank_page & self.outline(
                x, y, 283 if self.compact_layout else 118,
                bank_panel_bounds[1][0], 594 if self.compact_layout else 650,
                bank_panel_bounds[1][1], t=3)) |
            (tune_page & self.rect(x, y, 144, 460, 148, 476)))
        fb_select = (bank_page &
                     (self.selected == RezoHardwareUI.TARGET_FEEDBACK) &
                     self.outline(
                         x, y, 283 if self.compact_layout else 118,
                         bank_panel_bounds[2][0],
                         594 if self.compact_layout else 650,
                         bank_panel_bounds[2][1], t=3))
        page_select = (self.selected == RezoHardwareUI.TARGET_PAGE) & self.outline(
            x, y,
            212 if self.compact_layout else 20,
            116 if self.compact_layout else 20,
            364 if self.compact_layout else 196,
            164 if self.compact_layout else 82, t=3)

        bank_selected_q = Signal()
        clock_selected_q = Signal()
        input_selected_q = Signal()
        routing_selected_q = Signal()
        advanced_selected_q = Signal()
        bands_selected_q = Signal()
        page_selected_q = Signal()
        m.d.dvi += [
            bank_selected_q.eq(preset_select | preset_group_select | band_select_q0 |
                               drive_select | tune_feedback_select |
                               dry_select | res_select | fb_select |
                               damp_select | mode_select),
            clock_selected_q.eq(clock_select | mode_select),
            input_selected_q.eq(input_select_q0),
            routing_selected_q.eq(group_select_q0 | output_select_q0),
            advanced_selected_q.eq(palette_select | save_default_select),
            bands_selected_q.eq(layout_select | band_select_q0),
            page_selected_q.eq(page_select),
        ]
        selected = active & (bank_selected_q | clock_selected_q |
                             input_selected_q | routing_selected_q |
                             advanced_selected_q | bands_selected_q |
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
                                clock_depth_fill | tune_feedback_fill |
                                dry_fill | tune_cap_fill),
            geometry_line_q0.eq(
                band_zero_q0 | bank_control_mod_marker | border),
            geometry_mod_q0.eq(band_mod_fill | bank_control_mod_fill |
                               input_meter_q0),
            geometry_panel_q0.eq(preset_chip | mode_chip | clock_chip |
                                 palette_chip |
                                 save_default_chip | damp_chip | layout_chip |
                                 band_slot_q0 |
                                 meter_panel),
        ]
        m.d.dvi += [
            selected_q.eq(selected),
            text_q.eq(text),
            fill_q.eq(geometry_fill_q0 |
                      input_fill_q0 | group_fill_q0 | output_fill_q0),
            line_q.eq(geometry_line_q0 | input_line_q0 |
                      group_ghost),
            mod_q.eq(geometry_mod_q0),
            panel_q.eq(geometry_panel_q0 | input_panel_q0 | group_cell_q0 |
                       output_cell_q0),
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
    """REZOMO without the SoC framebuffer path.

    This is a timing experiment for a REZO-specific HDMI path.  It keeps the
    audio filterbank in gateware and renders a small status view directly in
    the DVI pixel domain.
    """

    bitstream_help = BitstreamHelp(
        brief="REZOMO clocked resonant filterbank.",
        io_left=['audio / CV input', 'audio / CV input',
                 'audio / CV input', 'audio / CV input',
                 'assignable out', 'assignable out',
                 'assignable out', 'assignable out'],
        io_right=['', '', 'video out required', '', '', '']
    )
    # This design's DVI PHY placement is seed-sensitive. Seed 8 is the
    # measured all-clock route for the standard 1280x720 target. The circular
    # entry point supplies its own measured seed while the environment
    # override remains useful for place-and-route experiments.
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
    nextpnr_opts = f"--timing-allow-fail --seed {os.getenv('TILIQUA_REZO_SEED', '8')}"

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
            RezoHardwareUI.STATE_WORDS_V3,
            legacy_records=(
                (RezoStateJournal.PREVIOUS_VERSION,
                 RezoHardwareUI.STATE_WORDS_V2),
                (RezoStateJournal.LEGACY_VERSION,
                 RezoHardwareUI.STATE_WORDS_V1),
            ),
            legacy_tail_words=RezoHardwareUI.legacy_band_config_words(),
            legacy_word_defaults=tuple(
                (RezoHardwareUI.STATE_CLOCK_CONFIG_BASE + n, word)
                for n, word in enumerate(
                    RezoHardwareUI.legacy_clock_config_words())))
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
            rezo.limit_knee.eq(ui.limit_knee),
            rezo.limit_cap.eq(ui.limit_cap),
            rezo.damp_mode.eq(ui.damp_mode),
            rezo.clock_mode.eq(ui.clock_mode),
            rezo.clock_algorithm.eq(ui.clock_algorithm),
            rezo.shift_direction.eq(ui.shift_direction),
            rezo.turing_length.eq(ui.turing_length),
            rezo.turing_change.eq(ui.turing_change),
            rezo.clock_source.eq(ui.clock_source),
            rezo.data_source.eq(ui.data_source),
            rezo.internal_clock_rate.eq(ui.internal_clock_rate),
            rezo.input_jacks.eq(pmod0.jack[:4]),
            rezo.clock_depth.eq(ui.clock_depth),
            rezo.walk_step_index.eq(ui.walk_step_index),
            rezo.walk_style.eq(ui.walk_style),
            rezo.walk_drunk.eq(ui.walk_drunk),
            rezo.walk_chance_index.eq(ui.walk_chance_index),
            rezo.turing_target.eq(ui.turing_target),
            rezo.turing_start.eq(ui.turing_start),
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
            m.d.comb += rezo.output_routes[n].eq(ui.output_routes[n])
        for n in range(20):
            m.d.comb += rezo.output_sends[n].eq(ui.output_sends[n])

        wiring.connect(m, pmod0.o_cal, rezo.i)
        wiring.connect(m, rezo.o, audio_out_fifo.i)
        wiring.connect(m, audio_out_fifo.o, pmod0.i_cal)

        m.submodules.dvi_tgen = dvi_tgen = dvi.DVITimingGen()
        for member in dvi_tgen.timings.signature.members:
            m.d.comb += getattr(dvi_tgen.timings, member).eq(
                getattr(self.clock_settings.modeline, member))

        round_display = (
            self.clock_settings.modeline.h_active == 720 and
            self.clock_settings.modeline.v_active == 720)
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
        display_limit_knee = Signal(unsigned(8))
        display_limit_cap = Signal(unsigned(8))
        display_input_gains = [Signal(unsigned(8), name=f"display_input_gain{n}")
                               for n in range(4)]
        display_cv_depths = [Signal(signed(8), name=f"display_cv_depth{n}")
                             for n in range(4)]
        display_input_meters = [Signal(signed(6), name=f"display_input_meter{n}")
                                for n in range(4)]
        output_send_write_index = Signal(range(20))
        output_send_array = Array(ui.output_sends)
        m.d.comb += [
            display_drive.eq((RezoCore.DRIVE_FLOOR + rezo.drive) >> 8),
            display_effective_drive.eq(rezo.effective_drive >> 8),
            display_resonance.eq(rezo.resonance >> 8),
            display_feedback.eq(rezo.feedback >> 8),
            display_effective_resonance.eq(rezo.effective_resonance >> 8),
            display_effective_feedback.eq(rezo.effective_feedback >> 8),
            display_limit_knee.eq(rezo.limit_knee >> 8),
            display_limit_cap.eq(rezo.limit_cap >> 8),
        ]
        for n in range(4):
            m.d.comb += display_input_gains[n].eq(rezo.input_gains[n] >> 8)
        for n in range(4):
            m.d.comb += display_cv_depths[n].eq(rezo.cv_depths[n] >> 8)
            m.d.sync += display_input_meters[n].eq(
                rezo.input_meters[n] >> 10)
        m.d.comb += [
            display.output_send_write_addr.eq(output_send_write_index),
            display.output_send_write_data.eq(
                output_send_array[output_send_write_index]),
            display.output_send_write_en.eq(1),
        ]
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
            FFSynchronizer(i=display_limit_knee, o=display.limit_knee, o_domain="dvi"),
            FFSynchronizer(i=display_limit_cap, o=display.limit_cap, o_domain="dvi"),
            FFSynchronizer(i=ui.damp_mode, o=display.damp_mode, o_domain="dvi"),
            FFSynchronizer(i=ui.selected, o=display.selected, o_domain="dvi"),
            FFSynchronizer(i=ui.page, o=display.page, o_domain="dvi"),
            FFSynchronizer(i=ui.preset, o=display.preset, o_domain="dvi"),
            FFSynchronizer(i=ui.clock_mode,
                           o=display.clock_mode, o_domain="dvi"),
            FFSynchronizer(i=ui.clock_algorithm,
                           o=display.clock_algorithm, o_domain="dvi"),
            FFSynchronizer(i=ui.shift_direction,
                           o=display.shift_direction, o_domain="dvi"),
            FFSynchronizer(i=ui.walk_step_index,
                           o=display.walk_step_index, o_domain="dvi"),
            FFSynchronizer(i=ui.walk_style,
                           o=display.walk_style, o_domain="dvi"),
            FFSynchronizer(i=ui.walk_drunk,
                           o=display.walk_drunk, o_domain="dvi"),
            FFSynchronizer(i=ui.walk_chance_index,
                           o=display.walk_chance_index, o_domain="dvi"),
            FFSynchronizer(i=ui.turing_length,
                           o=display.turing_length, o_domain="dvi"),
            FFSynchronizer(i=ui.turing_change_index,
                           o=display.turing_change_index, o_domain="dvi"),
            FFSynchronizer(i=ui.clock_source,
                           o=display.clock_source, o_domain="dvi"),
            FFSynchronizer(i=ui.data_source,
                           o=display.data_source, o_domain="dvi"),
            FFSynchronizer(i=ui.internal_clock_rate,
                           o=display.internal_clock_rate, o_domain="dvi"),
            FFSynchronizer(i=rezo.clock_external_active,
                           o=display.clock_external_active, o_domain="dvi"),
            FFSynchronizer(i=rezo.data_random_active,
                           o=display.data_random_active, o_domain="dvi"),
            FFSynchronizer(i=ui.clock_depth,
                           o=display.clock_depth, o_domain="dvi"),
            FFSynchronizer(i=ui.turing_target,
                           o=display.turing_target, o_domain="dvi"),
            FFSynchronizer(i=ui.turing_start,
                           o=display.turing_start, o_domain="dvi"),
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


def run_cli(*, name="REZOMO", artifact_name=None, modeline=None):
    """Build REZOMO with an explicitly selected display target."""
    this_path = os.path.dirname(os.path.realpath(__file__))
    top_level_cli(
        RezoBeamTop, path=this_path,
        argparse_callback=lambda parser: parser.set_defaults(
            name=name, artifact_name=artifact_name, modeline=modeline),
        archiver_callback=lambda archiver: archiver.with_option_storage())


if __name__ == "__main__":
    run_cli(
        name=os.getenv("TILIQUA_REZO_FAMILY_NAME", "REZOMO"),
        artifact_name=os.getenv("TILIQUA_REZO_FAMILY_ARTIFACT_NAME") or None,
        modeline=os.getenv("TILIQUA_REZO_FAMILY_MODELINE") or None,
    )
