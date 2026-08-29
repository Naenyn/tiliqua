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
        STEREO_TILE_CHARS,
    )
    from .core_common import RezoCoreConstants
    from .feedback import (
        FeedbackShaper, feedback_damping, feedback_gain_from_control,
        resonance_control,
    )
    from .persistence_common import SPIFlashTransfer
    from .ui_specs import StrezoUISpec
    from .ui_common import (
        BASE_TARGET_NAMES, COMMON_PAGE_TITLES, DAMP_NAMES, LAYOUT_NAMES,
        NAV_NAMES, PALETTE_NAMES, SAVE_NAMES, format_frequency_name,
        NATIVE_FEEDBACK_AMOUNT_Y0, NATIVE_FEEDBACK_CEILING_Y0,
        NATIVE_FEEDBACK_FILL_X0, NATIVE_FEEDBACK_FILL_X1,
        NATIVE_FEEDBACK_TRACK_X0, NATIVE_FEEDBACK_TRACK_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_X0, NATIVE_FEEDBACK_DAMPING_CHIP_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_Y0, NATIVE_FEEDBACK_DAMPING_CHIP_Y1,
        NATIVE_FEEDBACK_DAMPING_TEXT_COL, NATIVE_FEEDBACK_DAMPING_TEXT_ROW,
        NATIVE_FEEDBACK_KNEE_Y0, NATIVE_GROUP_CENTERS,
        NATIVE_GROUP_TEXT_ROWS, NATIVE_INPUT_TEXT_ROWS,
        NATIVE_CONTENT_PANEL_X0, NATIVE_CONTENT_PANEL_X1,
        NATIVE_CONTENT_PANEL_Y0, NATIVE_CONTENT_PANEL_Y1,
        NATIVE_PAGE_HEADING_ROW, NATIVE_PAGE_HEADER_CHIP_Y0,
        NATIVE_PAGE_HEADER_CHIP_Y1, NATIVE_PAGE_HEADER_SELECT_Y0,
        NATIVE_PAGE_HEADER_SELECT_Y1,
        NATIVE_INPUT_FILL_X0, NATIVE_INPUT_FILL_X1,
        NATIVE_INPUT_PANEL_Y0, NATIVE_INPUT_PANEL_Y1,
        NATIVE_MAIN_FILL_X0, NATIVE_MAIN_FILL_X1,
        NATIVE_MAIN_CONTROL_TEXT_ROWS, NATIVE_MAIN_CONTROL_Y0S,
        NATIVE_OUTPUT_COL_CENTERS, NATIVE_OUTPUT_ROW_CENTERS,
        NATIVE_OUTPUT_TEXT_ROWS,
        native_group_geometry, native_input_row_geometry,
        native_cross_fader_endpoint, native_input_depth_endpoint,
        native_input_gain_endpoint, native_main_fader_endpoint,
        native_motion_depth_endpoint, native_input_meter_endpoint,
        native_output_column_geometry,
        native_input_unity_x, native_value_chip_x0,
        native_feedback_track_rows, native_viewport_regions,
        output_header_selection,
        put_native_page_heading,
        put_native_page_headers,
        put_native_support_page_labels,
    )
except ImportError:  # top_level_cli executes this file directly.
    from display_common import (
        FONT_5X7, PALETTE_ROLES, RGB_PALETTES, SEMANTIC_PALETTE,
        STEREO_TILE_CHARS,
    )
    from core_common import RezoCoreConstants
    from feedback import (
        FeedbackShaper, feedback_damping, feedback_gain_from_control,
        resonance_control,
    )
    from persistence_common import SPIFlashTransfer
    from ui_specs import StrezoUISpec
    from ui_common import (
        BASE_TARGET_NAMES, COMMON_PAGE_TITLES, DAMP_NAMES, LAYOUT_NAMES,
        NAV_NAMES, PALETTE_NAMES, SAVE_NAMES, format_frequency_name,
        NATIVE_FEEDBACK_AMOUNT_Y0, NATIVE_FEEDBACK_CEILING_Y0,
        NATIVE_FEEDBACK_FILL_X0, NATIVE_FEEDBACK_FILL_X1,
        NATIVE_FEEDBACK_TRACK_X0, NATIVE_FEEDBACK_TRACK_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_X0, NATIVE_FEEDBACK_DAMPING_CHIP_X1,
        NATIVE_FEEDBACK_DAMPING_CHIP_Y0, NATIVE_FEEDBACK_DAMPING_CHIP_Y1,
        NATIVE_FEEDBACK_DAMPING_TEXT_COL, NATIVE_FEEDBACK_DAMPING_TEXT_ROW,
        NATIVE_FEEDBACK_KNEE_Y0, NATIVE_GROUP_CENTERS,
        NATIVE_GROUP_TEXT_ROWS, NATIVE_INPUT_TEXT_ROWS,
        NATIVE_CONTENT_PANEL_X0, NATIVE_CONTENT_PANEL_X1,
        NATIVE_CONTENT_PANEL_Y0, NATIVE_CONTENT_PANEL_Y1,
        NATIVE_PAGE_HEADING_ROW, NATIVE_PAGE_HEADER_CHIP_Y0,
        NATIVE_PAGE_HEADER_CHIP_Y1, NATIVE_PAGE_HEADER_SELECT_Y0,
        NATIVE_PAGE_HEADER_SELECT_Y1,
        NATIVE_INPUT_FILL_X0, NATIVE_INPUT_FILL_X1,
        NATIVE_INPUT_PANEL_Y0, NATIVE_INPUT_PANEL_Y1,
        NATIVE_MAIN_FILL_X0, NATIVE_MAIN_FILL_X1,
        NATIVE_MAIN_CONTROL_TEXT_ROWS, NATIVE_MAIN_CONTROL_Y0S,
        NATIVE_OUTPUT_COL_CENTERS, NATIVE_OUTPUT_ROW_CENTERS,
        NATIVE_OUTPUT_TEXT_ROWS,
        native_group_geometry, native_input_row_geometry,
        native_cross_fader_endpoint, native_input_depth_endpoint,
        native_input_gain_endpoint, native_main_fader_endpoint,
        native_motion_depth_endpoint, native_input_meter_endpoint,
        native_output_column_geometry,
        native_input_unity_x, native_value_chip_x0,
        native_feedback_track_rows, native_viewport_regions,
        output_header_selection,
        put_native_page_heading,
        put_native_page_headers,
        put_native_support_page_labels,
    )


NATIVE_MOTION_LABEL_RIGHT = 17
NATIVE_MOTION_VALUE_TEXT_COL = 19
NATIVE_MOTION_CONTROL_X0 = native_value_chip_x0(
    NATIVE_MOTION_VALUE_TEXT_COL)
NATIVE_MOTION_CONTROL_X1 = 576

# STREZO adds a one-character L/R source chip ahead of each OUTPUT matrix
# row.  Its right edge stays aligned with the established routing matrix;
# the narrower left edge leaves a clear gutter after the OUT# label.
NATIVE_OUTPUT_SIDE_CHIP_X0 = 196
NATIVE_OUTPUT_SIDE_CHIP_X1 = 236
NATIVE_OUTPUT_SIDE_TEXT_COL = 13
NATIVE_MOTION_FILL_X0 = NATIVE_MOTION_CONTROL_X0 + 2
NATIVE_MOTION_CENTER_X = (
    NATIVE_MOTION_CONTROL_X0 + NATIVE_MOTION_CONTROL_X1) // 2


def output_meter_db_value(magnitude):
    """Map a ten-bit absolute sample magnitude onto -60..0 dBFS."""
    if magnitude == 0:
        return 0
    dbfs = 20 * math.log10(magnitude / 1023)
    return max(0, min(63, round((dbfs + 60) * 63 / 60)))


NATIVE_OUTPUT_METER_RADII = (335, 311, 303, 279)
NATIVE_OUTPUT_METER_LABEL_COLS = (3, 5, 39, 41)


def native_output_meter_bounds(y):
    """Return left-edge intersections for the four concentric meter radii."""
    dy2 = abs((y << 1) - 719)
    bounds = []
    for radius in NATIVE_OUTPUT_METER_RADII:
        radius2 = radius << 1
        remainder = max(0, radius2 * radius2 - dy2 * dy2)
        dx2 = math.isqrt(remainder)
        bounds.append((719 - dx2 + 1) // 2)
    return tuple(bounds)


class RezoCore(RezoCoreConstants, wiring.Component):
    """Ten-band linked-stereo resonant filterbank."""

    # Fixed-point IIR states can otherwise settle into a low-level periodic
    # orbit after their input has gone quiet. Pull each integrator four guard
    # bits toward zero only below this input floor; normal audio and deliberate
    # resonator tails remain untouched.
    STATE_BLEED_INPUT = 32
    STATE_BLEED_STEP = 4
    INPUT_MODE_LEFT = 0
    INPUT_MODE_RIGHT = 1
    INPUT_MODE_CV = 2
    CROSS_LAYOUT_GLOBAL = 0
    CROSS_LAYOUT_DIAGONAL = 1
    CROSS_LAYOUT_ROTATE = 2
    CROSS_LAYOUT_MIRROR = 3
    CROSS_LAYOUT_ALL = 4
    CROSS_LAYOUT_USER = 5
    CROSS_DEPTH_MAX = 128
    CROSS_COEFFICIENT_MAX = 32768
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
        return round(cls.CROSS_COEFFICIENT_MAX * shaped)

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
        effective_cross_feedback_raw = Signal(unsigned(16))
        effective_cross_feedback = Signal(unsigned(16))
        self._effective_cross_feedback = effective_cross_feedback
        m.d.comb += [
            cross_curve_rport.addr.eq(Cat(
                self.cross_feedback, self.cross_curve, Const(1, 1))),
            effective_cross_feedback_raw.eq(cross_curve_rport.data[:16]),
        ]
        # Break the block-RAM clock-to-Q path before CROSS fans out through the
        # stereo mix, matrix gain, and topology-aware damping law. Controls are
        # stable for hundreds of sync clocks per audio sample, so this extra
        # control-rate cycle is inaudible and materially improves route timing.
        m.d.sync += effective_cross_feedback.eq(effective_cross_feedback_raw)

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
            feedback_gain.eq(feedback_gain_from_control(effective_feedback)),
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

        # STREZO's damping follows the strongest active SAME/CROSS leg rather
        # than the global FB slider alone. A four-region approximation avoids
        # spending another multiplier on this slow safety control. As in the
        # mono cores, damping reduces requested resonance so its upper travel
        # remains useful instead of collapsing against an inverse-Q floor.
        resonance_ctl = Signal(ASQ)
        feedback_damp = Signal(unsigned(16))
        spatial_depth = Signal(unsigned(16))
        spatial_feedback = Signal(unsigned(16))
        resonance_amount_q = Signal(unsigned(16))
        feedback_damp_q = Signal(unsigned(16))
        resonance_reduced_q = Signal(unsigned(16))
        # Simulation probes; unconnected aliases disappear during synthesis.
        self._resonance_ctl = resonance_ctl
        self._feedback_damp = feedback_damp
        self._spatial_feedback = spatial_feedback
        m.d.comb += [
            spatial_depth.eq(Mux(
                (self.same_feedback << 8) > effective_cross_feedback,
                self.same_feedback << 8, effective_cross_feedback)),
            feedback_damp.eq(feedback_damping(
                spatial_feedback, self.damp_mode, "strezo")),
            resonance_ctl.eq(resonance_control(
                effective_resonance, feedback_damp)),
        ]
        with m.If(spatial_depth == 0):
            m.d.comb += spatial_feedback.eq(0)
        with m.Elif(spatial_depth <= 8192):
            m.d.comb += spatial_feedback.eq(effective_feedback >> 2)
        with m.Elif(spatial_depth <= 16384):
            m.d.comb += spatial_feedback.eq(effective_feedback >> 1)
        with m.Elif(spatial_depth <= 24576):
            m.d.comb += spatial_feedback.eq(
                effective_feedback - (effective_feedback >> 2))
        with m.Else():
            m.d.comb += spatial_feedback.eq(effective_feedback)

        # Feedback is smoothed and scheduled through the shared multiplier.
        # A 31/32 scale uses every UI position while keeping the full-scale
        # endpoint just below the hardware-tested runaway cliff.
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
            # The SVF state has two more fractional guard bits than SQNative.
            # Preserve those bits when reducing the Q30 multiplier result to
            # Q17; shifting to Q15 here would make every state update 4x too
            # small, including the inverse-Q damping term.
            svf_product_raw.eq(mac_z.as_value().as_signed() >>
                               (dsp.mac.SQNative.f_bits - 2)),
            svf_next.eq(svf_next_safe),
            svf_product_raw_r.eq(mac_z_r.as_value().as_signed() >>
                                 (dsp.mac.SQNative.f_bits - 2)),
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
        feedback_drive_q = Signal(mix_shape)
        feedback_drive_q_r = Signal(mix_shape)
        m.submodules.feedback_shaper_l = feedback_shaper_l = FeedbackShaper(
            input_width=mix_shape.width)
        m.submodules.feedback_shaper_r = feedback_shaper_r = FeedbackShaper(
            input_width=mix_shape.width)
        m.d.comb += [
            feedback_shaper_l.drive.eq(feedback_drive_q),
            feedback_shaper_l.knee.eq(self.limit_knee),
            feedback_shaper_l.ceiling.eq(self.limit_cap),
            feedback_shaper_r.drive.eq(feedback_drive_q_r),
            feedback_shaper_r.knee.eq(self.limit_knee),
            feedback_shaper_r.ceiling.eq(self.limit_cap),
        ]
        # The routed matrix sum and full-bank accumulator are both wide
        # combinational paths. Register their shared shaper boundary so that
        # neither path has to traverse the shaper's magnitude compare in the
        # same 60 MHz cycle. The output-routing schedule has ample slack for
        # this extra continuously-pipelined stage.
        m.d.sync += [
            feedback_drive_q.eq(feedback_drive),
            feedback_drive_q_r.eq(feedback_drive_r),
        ]
        clip_limited = feedback_shaper_l.sample
        clip_limited_r = feedback_shaper_r.sample
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
        matrix_shape_commit = Signal()
        matrix_shape_capture = Signal()
        matrix_shape_destination = Signal(unsigned(2))
        matrix_source = Signal(unsigned(2))
        matrix_destination = Signal(unsigned(2))
        matrix_coefficient_q = Signal(unsigned(5))
        matrix_next_route_index = Signal(range(20))
        matrix_next_source = Signal(unsigned(2))
        matrix_next_destination = Signal(unsigned(2))
        matrix_next_coefficient = Signal(unsigned(5))
        matrix_cross_feedback_q = Signal(unsigned(16))
        matrix_feedback_gain_q = Signal(unsigned(16))
        matrix_combined_gain_product = Signal(unsigned(32))
        matrix_combined_gain_q = Signal(unsigned(16))
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
        # SAME remains a 0..128 retained position while CROSS is translated to
        # Q1.15 by the curve ROM. Expanding SAME by 256 gives both paths the
        # same full-resolution multiply and preserves their exact endpoints.
        cross_self_gain = Signal(unsigned(16))
        cross_other_gain = Signal(unsigned(16))
        cross_ll = Signal(signed(33))
        cross_lr = Signal(signed(33))
        cross_rr = Signal(signed(33))
        cross_rl = Signal(signed(33))
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
            enabled_term.eq(Mux(band_enable_array[band], term_q, 0)),
            enabled_term_r.eq(Mux(band_enable_array[band], term_q_r, 0)),
            main_next.eq(main_acc + enabled_term),
            filtered_next.eq(main_next - dry_sample.as_value().as_signed()),
            # Once the global tap has settled, reuse its two shapers for the
            # four completed matrix destinations. Destinations finish four
            # route cells apart, leaving enough pipeline time to capture each
            # result without adding another pair of multipliers.
            matrix_shape_commit.eq(
                (state == state_output_product_commit) &
                (matrix_route_index < 16) &
                (matrix_source == self.N_GROUPS - 1)),
            matrix_shape_capture.eq(
                (state == state_output_product_commit) &
                (matrix_route_index >= 4) &
                (matrix_route_index <= 16) &
                (matrix_route_index[:2] == 0)),
            matrix_shape_destination.eq((matrix_route_index - 4) >> 2),
            feedback_drive.eq(Mux(
                matrix_shape_commit, matrix_route_next_l, feedback_acc)),
            feedback_drive_r.eq(Mux(
                matrix_shape_commit, matrix_route_next_r, feedback_acc_r)),
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
            cross_self_gain.eq(self.same_feedback << 8),
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
            cross_sum_l.eq((cross_ll_q + cross_lr_q) >> 15),
            cross_sum_r.eq((cross_rr_q + cross_rl_q) >> 15),
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
            # CROSS is Q1.15 while FEEDBACK remains a 16-bit amount. Divide by
            # 65536 so the later Q1.15 multiply preserves the historical
            # full-scale matrix depth with useful response at every detent.
            matrix_combined_gain_q.eq(
                (matrix_combined_gain_product + 32768) >> 16),
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
        # The feedback saturator above shapes the delayed wet signal. This is
        # a separate, deliberately simple conditioner on the signal entering
        # every resonator. Its 4:1 over-knee slope keeps the sum bounded while
        # leaving useful character across the upper DRIVE range.
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
        with m.If(state == state_drive_commit):
            # Display-only telemetry spans the full signed 6-bit lane at
            # maximum depth. Capture the band-zero term one cycle after its
            # existing pipeline register instead of placing the waveform
            # multiplier on a second direct path into the UI monitor.
            m.d.sync += self.motion_monitor.eq(motion_term_q >> 11)

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
                        resonance_amount_q.eq(effective_resonance),
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
                    resonance_reduced_q.eq(Mux(
                        resonance_amount_q > feedback_damp_q,
                        resonance_amount_q - feedback_damp_q, 0)),
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
                            resonance.eq(
                                16384 - (resonance_reduced_q >> 1)),
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
                # The extra registered shaper boundary makes the full-bank
                # result valid one state after route index zero completes.
                with m.If(matrix_route_index == 1):
                    m.d.sync += [
                        feedback_sample.eq(clip_limited),
                        feedback_sample_r.eq(clip_limited_r),
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
                # The shared shaper was fed the preceding destination's wide
                # route sum in its commit state. Replace the temporary raw
                # value before that destination reaches the final gain phase.
                with m.If(matrix_shape_capture):
                    m.d.sync += [
                        matrix_feedback_array_l[
                            matrix_shape_destination].eq(clip_limited),
                        matrix_feedback_array_r[
                            matrix_shape_destination].eq(clip_limited_r),
                    ]
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
                        out_valid.eq(1),
                        state.eq(state_wait),
                    ]

        m.d.comb += [
            self.o.valid.eq(out_valid),
        ]
        for n in range(4):
            m.d.comb += self.o.payload[n].eq(output_q[n])
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
    CHARS = STEREO_TILE_CHARS
    CHAR_CODES = {ch: i for i, ch in enumerate(CHARS)}

    def __init__(self, h_active=1280, rotate_left=False):
        self.x_offset = max(0, (h_active - self.PANEL_W) // 2)
        self.rotate_left = rotate_left
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
            "output_meters": In(data.ArrayLayout(unsigned(6), 4)),
            "output_clips": In(data.ArrayLayout(unsigned(1), 4)),
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

        # Keep the high-fanout navigation selection local to the pixel domain.
        # UI state changes far more slowly than a frame, so this one-cycle
        # register is visually transparent while removing the control-domain
        # signal from the renderer's distributed decode paths.
        selected_dvi_q = Signal.like(self.selected)
        m.d.dvi += selected_dvi_q.eq(self.selected)

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

        compact_content_shift = 16
        compact_content_row_shift = 1
        zero_y = (366)
        main_band_y0 = (275)
        main_band_y1 = (456)
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
            height_value = (magnitude + (magnitude >> 2) +
                            (magnitude >> 3) + (magnitude >> 5))
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
        # Keep the tile store packed. The live read address is pipelined below,
        # so saving six DP16KDs does not put a multiplier on the pixel path.
        text_row_stride = 45
        page_cells = text_row_stride * 45
        text_init = [0] * (8 * page_cells)

        def put(page, text_value, x0, y0):
            for offset, ch in enumerate(text_value):
                if 0 <= x0 + offset < 45 and 0 <= y0 < 45:
                    text_init[page * page_cells +
                              y0 * text_row_stride + x0 + offset] = self.code(ch)

        def put_native(page, text_value, x0, y0):
            """Place text directly on the native 16px character grid."""
            put(page, text_value, x0, y0)

        page_titles = COMMON_PAGE_TITLES + ("CROSS",)
        compact_input_text_rows = NATIVE_INPUT_TEXT_ROWS
        compact_group_text_rows = tuple(
            row - compact_content_row_shift for row in NATIVE_GROUP_TEXT_ROWS)
        compact_group_centers = tuple(
            center - compact_content_shift for center in NATIVE_GROUP_CENTERS)
        compact_output_text_rows = tuple(
            row - 3 * compact_content_row_shift
            for row in NATIVE_OUTPUT_TEXT_ROWS)
        compact_output_row_centers = tuple(
            center - 3 * compact_content_shift
            for center in NATIVE_OUTPUT_ROW_CENTERS)
        compact_output_col_centers = NATIVE_OUTPUT_COL_CENTERS
        # CROSS has only four columns, so it can use the full panel width and
        # sit higher than OUTPUT's five-column matrix. Keep these values
        # separate to preserve OUTPUT's established composition.
        compact_cross_text_rows = (20, 24, 28, 32)
        compact_cross_row_centers = tuple(
            row * 16 + 6 for row in compact_cross_text_rows)
        compact_cross_col_centers = (254, 334, 414, 494)
        compact_main_control_text_rows = tuple(
            row + compact_content_row_shift
            for row in NATIVE_MAIN_CONTROL_TEXT_ROWS[:3])
        compact_main_control_y0s = tuple(
            y0 + compact_content_shift for y0 in NATIVE_MAIN_CONTROL_Y0S[:3])

        put_native_page_headers(put_native, "STREZO", page_titles)
        for text_page in range(8):
            put_native(text_page, "OUT", 3, 15)
            put_native(text_page, "OUT", 39, 15)
            for label, col in zip(
                    "1234", NATIVE_OUTPUT_METER_LABEL_COLS):
                put_native(text_page, label, col, 29)

        put_native_page_heading(put_native, 0, "PRESET")
        put_native(0, "BANDS", 8, 14)
        put_native(0, "FREQ:", 23, 14)
        put_native(0, "DRIVE", 12, compact_main_control_text_rows[0])
        put_native(0, "RESONANCE", 8, compact_main_control_text_rows[1])
        put_native(0, "FEEDBACK", 9, compact_main_control_text_rows[2])

        put_native_support_page_labels(
            put_native, output_label_col=8,
            content_row_offsets={1: -1, 3: -1, 4: -3, 5: -1, 6: -1},
            feedback_amount_row_offset=1)
        put_native(5, "ADVANCED", 8, 26)
        put_native(5, "CROSS CURVE", 9, 30)

        put_native(6, "MOTION", 8, 27)
        for label, row in (("LFO SHAPE", 29), ("RATE HZ", 31),
                           ("PHASE", 33), ("DEPTH", 35)):
            put_native(6, label,
                       NATIVE_MOTION_LABEL_RIGHT - len(label), row)

        put_native_page_heading(put_native, 7, "LAYOUT")
        put_native(7, "TO", 15, 15)
        put_native(7, "FROM", 8, 18)
        for group, row in enumerate(compact_cross_text_rows):
            put_native(7, f"G{group + 1}", 10, row)
            put_native(7, f"G{group + 1}", 15 + group * 5, 17)
        put_native(7, "SAME", 9, 34)
        put_native(7, "CROSS", 8, 36)
        m.submodules.text_mem = text_mem = Memory(
            shape=unsigned(6), depth=len(text_init), init=text_init)
        text_rport = text_mem.read_port(domain="dvi")
        text_wport = text_mem.write_port(domain="sync")
        page_offsets = Array(Const(page * page_cells, unsigned(14))
                             for page in range(8))
        text_address = Signal(unsigned(15))
        text_page_q = Signal(unsigned(3))
        m.d.dvi += text_page_q.eq(self.page)
        # ``text_y_pre`` leads ``cell_y`` by exactly one pixel clock.
        # Register the page/row base, leaving only the small cell-x add on
        # the BRAM setup path.
        text_row_base_q = Signal(unsigned(15))
        m.d.dvi += text_row_base_q.eq(
            page_offsets[self.page] +
            text_y_pre[self.CELL_SHIFT:] * text_row_stride)
        m.d.comb += text_address.eq(text_row_base_q + cell_x)
        m.d.comb += text_rport.addr.eq(text_address)

        # Dynamic labels are written into the tile RAM in short bursts at
        # 15 Hz. HDMI therefore sees only a BRAM read, never the control muxes.
        page_sync = Signal.like(self.page)
        preset_sync = Signal.like(self.preset)
        selected_sync = Signal.like(selected_dvi_q)
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
            FFSynchronizer(selected_dvi_q, selected_sync),
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
                (selected_sync >= StrezoUISpec.TARGET_FEEDBACK_SEND_BASE) &
                (selected_sync < StrezoUISpec.TARGET_FEEDBACK_SEND_BASE +
                 RezoCore.N_BANDS)),
        ]
        with m.If(feedback_selected_valid):
            m.d.comb += feedback_selected_band.eq(
                selected_sync - StrezoUISpec.TARGET_FEEDBACK_SEND_BASE)

        bands_selected_band = Signal(range(RezoCore.N_BANDS))
        bands_selected_valid = Signal()
        bands_frequency_selected = Signal()
        m.d.comb += [
            bands_selected_band.eq(0),
            bands_selected_valid.eq(
                ((selected_sync >= StrezoUISpec.TARGET_BAND_ENABLE_BASE) &
                 (selected_sync < StrezoUISpec.TARGET_BAND_ENABLE_BASE +
                  RezoCore.N_BANDS)) |
                ((selected_sync >= StrezoUISpec.TARGET_BAND_FREQ_BASE) &
                 (selected_sync < StrezoUISpec.TARGET_BAND_FREQ_BASE +
                  RezoCore.N_BANDS))),
            bands_frequency_selected.eq(
                (selected_sync >= StrezoUISpec.TARGET_BAND_FREQ_BASE) &
                (selected_sync < StrezoUISpec.TARGET_BAND_FREQ_BASE +
                 RezoCore.N_BANDS)),
        ]
        with m.If(bands_frequency_selected):
            m.d.comb += bands_selected_band.eq(
                selected_sync - StrezoUISpec.TARGET_BAND_FREQ_BASE)
        with m.Elif(bands_selected_valid):
            m.d.comb += bands_selected_band.eq(
                selected_sync - StrezoUISpec.TARGET_BAND_ENABLE_BASE)

        update_index = Signal(range(127))
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
            selected_band_valid.eq((selected_sync >= StrezoUISpec.TARGET_BAND_BASE) &
                                   (selected_sync < StrezoUISpec.TARGET_BAND_BASE +
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
                selected_sync - StrezoUISpec.TARGET_BAND_BASE)

        # Fixed-width value slots are left-justified; trailing blanks clear
        # characters left behind when a shorter value replaces a longer one.
        preset_names = ("ALL ", "ODD ", "EVEN", "LOW ", "MID ", "HI  ", "ZERO")
        frequency_names = tuple(format_frequency_name(frequency)
                                for frequency in RezoCore.FREQUENCIES_HZ)
        displayed_layout = Signal(unsigned(2))
        m.d.comb += displayed_layout.eq(Mux(
            editing_sync & (selected_sync == StrezoUISpec.TARGET_BAND_LAYOUT),
            frequency_layout_preview_sync, frequency_layout_sync))
        target_names = BASE_TARGET_NAMES
        nav_names = NAV_NAMES
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
            full_name = f"{RezoCore.FREQUENCIES_HZ[index]:<5}"
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
        # Every BANDS layout name shares column 17 as its fixed left origin.
        layout_names = LAYOUT_NAMES
        layout_chars = [Array(Const(self.code(name[pos]), 6)
                              for name in layout_names)
                        for pos in range(7)]
        cross_layout_names = (
            "GLOBAL  ", "DIAGONAL", "ROTATE  ",
            "MIRROR  ", "ALL     ", "USER    ")
        cross_layout_chars = [
            Array(Const(self.code(name[pos]), 6)
                  for name in cross_layout_names)
            for pos in range(8)
        ]
        cross_curve_names = ("LINEAR  ", "LOG     ")
        cross_curve_chars = [
            Array(Const(self.code(name[pos]), 6)
                  for name in cross_curve_names)
            for pos in range(8)
        ]
        displayed_cross_layout = Signal(unsigned(3))
        m.d.comb += displayed_cross_layout.eq(Mux(
            editing_sync &
            (selected_sync == StrezoUISpec.TARGET_CROSS_LAYOUT),
            cross_layout_preview_sync, cross_layout_sync))
        target_chars = [Array(Const(self.code(name[pos]), 6) for name in target_names)
                        for pos in range(3)]
        palette_names = PALETTE_NAMES
        palette_chars = [Array(Const(self.code(name[pos]), 6)
                               for name in palette_names)
                         for pos in range(6)]
        damp_names = DAMP_NAMES
        damp_chars = [Array(Const(self.code(name[pos]), 6)
                            for name in damp_names)
                      for pos in range(5)]
        damp_name_index = Signal(range(5))
        m.d.comb += damp_name_index.eq(Mux(
            damp_mode_sync > 4, 4, damp_mode_sync))
        save_names = SAVE_NAMES
        save_chars = [Array(Const(self.code(name[pos]), 6)
                            for name in save_names)
                      for pos in range(7)]
        save_name_index = Signal(range(len(save_names)))
        m.d.comb += save_name_index.eq(
            Mux(~save_available_sync, 4,
                Mux(save_busy_sync | (save_status_sync == 1), 1,
                    Mux(save_status_sync == 2, 2,
                        Mux(save_status_sync == 3, 3, 0)))))
        motion_source_names = ("OFF     ", "TRIANGLE", "RANDOM  ")
        # One compact label ROM converts the continuous 0.1 Hz rate to text
        # without synthesizing a decimal divider into the control domain.
        motion_source_offset = 896
        motion_phase_blank_offset = 880
        motion_phase_offset = 1024
        motion_label_init = [0] * 2048
        for value in range(256):
            rate = min(value, 200)
            rate_text = f"{rate // 10}.{rate % 10}"[:4].ljust(4)
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
            phase_text = f"{degrees:<4}"[:4]
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
            return (page * page_cells + y0 * text_row_stride + x0 + offset)

        for pos in range(4):
            writer_address_init[4 + pos] = writer_cell(
                0, 16, NATIVE_PAGE_HEADING_ROW, pos)
        for pos in range(3):
            writer_address_init[8 + pos] = writer_cell(0, 29, 15, pos)
        for n, (mode_row, value_row, _) in enumerate(
                compact_input_text_rows):
            for pos in range(3):
                writer_address_init[11 + n * 3 + pos] = writer_cell(
                    2, 20, mode_row, pos)
                writer_address_init[23 + n * 3 + pos] = writer_cell(
                    2, 20, value_row, pos)
        for pos in range(5):
            writer_address_init[35 + pos] = writer_cell(
                1, NATIVE_FEEDBACK_DAMPING_TEXT_COL,
                NATIVE_FEEDBACK_DAMPING_TEXT_ROW - 1, pos)
        for pos in range(3):
            writer_address_init[43 + pos] = writer_cell(1, 29, 15, pos)
        for pos in range(6):
            writer_address_init[46 + pos] = writer_cell(5, 22, 16, pos)
        for pos in range(7):
            writer_address_init[52 + pos] = writer_cell(5, 22, 20, pos)
            # Every BANDS layout value uses the same fixed left origin.
            writer_address_init[59 + pos] = writer_cell(
                6, 16, NATIVE_PAGE_HEADING_ROW, pos)
        for pos in range(5):
            writer_address_init[66 + pos] = writer_cell(6, 20, 21, pos)
        for n, row in enumerate(compact_output_text_rows):
            writer_address_init[71 + n] = writer_cell(
                4, NATIVE_OUTPUT_SIDE_TEXT_COL, row)
        for pos in range(8):
            writer_address_init[75 + pos] = writer_cell(
                7, 16, NATIVE_PAGE_HEADING_ROW, pos)
        for pos in range(8):
            writer_address_init[83 + pos] = writer_cell(
                6, NATIVE_MOTION_VALUE_TEXT_COL, 29, pos)
        for pos in range(4):
            writer_address_init[91 + pos] = writer_cell(
                6, NATIVE_MOTION_VALUE_TEXT_COL, 31, pos)
            writer_address_init[95 + pos] = writer_cell(
                6, NATIVE_MOTION_VALUE_TEXT_COL, 33, pos)
        for pos in range(8):
            writer_address_init[99 + pos] = writer_cell(5, 22, 30, pos)
        for n, (_, _, depth_row) in enumerate(compact_input_text_rows):
            for pos in range(5):
                writer_address_init[107 + n * 5 + pos] = writer_cell(
                    2, 13, depth_row, pos)
        m.submodules.writer_address_mem = writer_address_mem = Memory(
            shape=unsigned(15), depth=len(writer_address_init),
            init=writer_address_init, attrs={"ram_style": "block"})
        writer_address_rport = writer_address_mem.read_port()
        m.d.comb += [
            writer_address_rport.addr.eq(update_index),
            writer_address.eq(Mux(
                writer_index_q < 4,
                page_offsets[writer_page_q] +
                ((8)) * text_row_stride +
                ((33)) + writer_index_q,
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
                            Const(self.code("L  "[pos]), 6),
                            Const(self.code("R  "[pos]), 6),
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
            for n in range(4):
                for pos in range(5):
                    with m.Case(107 + n * 5 + pos):
                        m.d.comb += writer_char.eq(Mux(
                            input_modes_sync[n] == RezoCore.INPUT_MODE_CV,
                            Const(self.code("DEPTH"[pos]), 6), 0))
        with m.If(update_active):
            with m.If(update_index == 126):
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

        border = ((Const(0)))
        arc_background = Const(0)
        pager_line = Const(0)
        pager_current = Const(0)
        output_meter_panel_q0 = Const(0)
        output_meter_fill_q0 = Const(0)
        output_meter_hot_q0 = Const(0)
        output_meter_clip_q0 = Const(0)
        circle_inside, _ = native_viewport_regions(
            m, x, text_y_pre, inner_radius=250)
        native_safe_square = (
            (x >= 106) & (x < 614) & (y >= 106) & (y < 614))
        arc_background = active & circle_inside & ~native_safe_square

        # Follow STREZO's firmware navigation order rather than its raw
        # page numbers: MAIN, BANDS, INPUT, GROUPS, OUTPUT, FEEDBACK,
        # CROSS, OPTIONS.
        pager_position = Signal(unsigned(3))
        with m.Switch(self.page):
            with m.Case(6):
                m.d.comb += pager_position.eq(1)
            with m.Case(2):
                m.d.comb += pager_position.eq(2)
            with m.Case(3):
                m.d.comb += pager_position.eq(3)
            with m.Case(4):
                m.d.comb += pager_position.eq(4)
            with m.Case(1):
                m.d.comb += pager_position.eq(5)
            with m.Case(7):
                m.d.comb += pager_position.eq(6)
            with m.Case(5):
                m.d.comb += pager_position.eq(7)

        pager_init = [0] * (8 * 256)
        first_center = 360 - 7 * 6
        for selected_position in range(8):
            for box_index in range(8):
                shift = (-4 if box_index < selected_position else
                         4 if box_index > selected_position else 0)
                center = first_center + box_index * 12 + shift
                if box_index == selected_position:
                    for pixel_x in range(center - 9, center + 10):
                        pager_init[(selected_position << 8) |
                                   (pixel_x & 0xff)] |= 0b100
                else:
                    for pixel_x in range(center - 5, center + 6):
                        address = ((selected_position << 8) |
                                   (pixel_x & 0xff))
                        pager_init[address] |= 0b001
                        if pixel_x < center - 3 or pixel_x >= center + 4:
                            pager_init[address] |= 0b010
        m.submodules.pager_mem = pager_mem = Memory(
            shape=unsigned(3), depth=len(pager_init), init=pager_init,
            attrs={"ram_style": "block"})
        pager_rport = pager_mem.read_port(domain="dvi")
        m.d.comb += pager_rport.addr.eq(Cat(
            text_x_pre[:8], pager_position))
        pager_window = (x >= 256) & (x < 512)
        pager_line = active & pager_window & pager_rport.data[0] & (
            pager_rport.data[1] | (y < 80) | (y >= 92)) & \
            (y >= 78) & (y < 94)
        pager_current = active & pager_window & pager_rport.data[2] & \
            (y >= 76) & (y < 97)

        meter_curve_init = []
        for pixel_y in range(720):
            packed_bounds = 0
            for index, bound in enumerate(
                    native_output_meter_bounds(pixel_y)):
                packed_bounds |= bound << (index * 10)
            meter_curve_init.append(packed_bounds)
        m.submodules.output_meter_curve_mem = output_meter_curve_mem = Memory(
            shape=unsigned(40), depth=len(meter_curve_init),
            init=meter_curve_init, attrs={"ram_style": "block"})
        meter_curve_rport = output_meter_curve_mem.read_port(domain="dvi")
        meter_curve_data = Signal(unsigned(40))
        m.d.comb += meter_curve_rport.addr.eq(ui_y[:10])
        m.d.dvi += meter_curve_data.eq(meter_curve_rport.data)

        meter_lane_valid = Signal()
        meter_curve_x = Signal(unsigned(10))
        meter_bound_lo = Signal(unsigned(10))
        meter_bound_hi = Signal(unsigned(10))
        meter_value = Signal(unsigned(6))
        meter_clip = Signal()
        # Meter pixels only exist in the far side arcs (x < 106 or
        # x >= 614), so x[9] is an exact and much shallower left/right
        # selector than a full ``x < 360`` comparison on every lane.
        m.d.comb += meter_curve_x.eq(Mux(x[9], 719 - x, x))
        with m.If((meter_curve_x >= meter_curve_data[0:10]) &
                  (meter_curve_x < meter_curve_data[10:20])):
            m.d.comb += [
                meter_lane_valid.eq(1),
                meter_bound_lo.eq(meter_curve_data[0:10]),
                meter_bound_hi.eq(meter_curve_data[10:20]),
                meter_value.eq(Mux(
                    x[9], self.output_meters[3],
                    self.output_meters[0])),
                meter_clip.eq(Mux(
                    x[9], self.output_clips[3],
                    self.output_clips[0]))]
        with m.Elif(
                (meter_curve_x >= meter_curve_data[20:30]) &
                (meter_curve_x < meter_curve_data[30:40])):
            m.d.comb += [
                meter_lane_valid.eq(1),
                meter_bound_lo.eq(meter_curve_data[20:30]),
                meter_bound_hi.eq(meter_curve_data[30:40]),
                meter_value.eq(Mux(
                    x[9], self.output_meters[2],
                    self.output_meters[1])),
                meter_clip.eq(Mux(
                    x[9], self.output_clips[2],
                    self.output_clips[1]))]

        meter_x_q = Signal.like(x)
        meter_y_q = Signal.like(y)
        meter_bound_lo_q = Signal.like(meter_bound_lo)
        meter_bound_hi_q = Signal.like(meter_bound_hi)
        meter_value_q = Signal.like(meter_value)
        meter_clip_q = Signal()
        meter_lane_valid_q = Signal()
        m.d.dvi += [
            meter_x_q.eq(meter_curve_x),
            meter_y_q.eq(y),
            meter_bound_lo_q.eq(meter_bound_lo),
            meter_bound_hi_q.eq(meter_bound_hi),
            meter_value_q.eq(meter_value),
            meter_clip_q.eq(meter_clip),
            meter_lane_valid_q.eq(meter_lane_valid),
        ]
        meter_top = Signal(unsigned(10))
        m.d.comb += meter_top.eq(
            460 - ((meter_value_q << 1) + meter_value_q))
        meter_shape = meter_lane_valid_q & (meter_y_q >= 260) & \
            (meter_y_q < 462) & (meter_x_q >= meter_bound_lo_q) & \
            (meter_x_q < meter_bound_hi_q)
        meter_interior = (meter_y_q >= 262) & (meter_y_q < 460) & \
            (meter_x_q >= meter_bound_lo_q + 2) & \
            (meter_x_q < meter_bound_hi_q - 2)
        output_meter_panel = meter_shape & ~meter_interior
        output_meter_fill = meter_lane_valid_q & (meter_y_q >= 264) & \
            (meter_y_q >= meter_top) & (meter_y_q < 458) & \
            (meter_x_q >= meter_bound_lo_q + 4) & \
            (meter_x_q < meter_bound_hi_q - 4)
        output_meter_hot = output_meter_fill & (meter_y_q < 290)
        # 260..263 is an aligned four-line span. Decode the shared upper
        # bits directly instead of building two full-width comparators.
        meter_clip_row = meter_y_q[2:] == (260 >> 2)
        output_meter_clip = meter_lane_valid_q & meter_clip_q & \
            meter_clip_row & \
            (meter_x_q >= meter_bound_lo_q + 4) & \
            (meter_x_q < meter_bound_hi_q - 4)
        output_meter_panel_q0 = Signal()
        output_meter_fill_q0 = Signal()
        output_meter_hot_q0 = Signal()
        output_meter_clip_q0 = Signal()
        m.d.dvi += [
            output_meter_panel_q0.eq(output_meter_panel),
            output_meter_fill_q0.eq(output_meter_fill),
            output_meter_hot_q0.eq(output_meter_hot),
            output_meter_clip_q0.eq(output_meter_clip),
        ]
        title_panel = active & self.rect(
            x, y,
            (112),
            (120),
            (608),
            (164))
        side_page_chip = Const(0)
        cursor_chip = Const(0)
        side_page_chip = active & self.rect(
            text_x, text_y, 216, 124, 360, 146)
        cursor_chip = active & self.outline(
            text_x, text_y, 520, 122,
            Mux(self.editing, 600, 584), 148, t=2)
        # One shared rectangle keeps the pixel path shallow. OPTIONS selects
        # a short lower field; all working pages use the taller field needed
        # by the matrix and fourth output row.
        content_y0 = Signal(
            unsigned(10), init=(NATIVE_CONTENT_PANEL_Y0))
        content_y1 = Signal(
            unsigned(10), init=(NATIVE_CONTENT_PANEL_Y1))
        m.d.dvi += [
            content_y0.eq((NATIVE_CONTENT_PANEL_Y0)),
            content_y1.eq((NATIVE_CONTENT_PANEL_Y1)),
        ]
        normal_content_panel = self.rect(
            x, y, (NATIVE_CONTENT_PANEL_X0),
            content_y0,
            (NATIVE_CONTENT_PANEL_X1),
            content_y1)
        content_panel = active & normal_content_panel
        surface_row_y0 = Signal(unsigned(6), init=14)
        surface_row_y1 = Signal(unsigned(6), init=35)
        surface_row_y0s = Array(Const(row, 6) for row in (
            14, 14, 13, 14, 14, 14, 14, 14))
        surface_row_y1s = Array(Const(row, 6) for row in (
            35, 31, 38, 30, 32, 34, 37, 38))
        m.d.comb += [
            surface_row_y0.eq(surface_row_y0s[text_page_q]),
            surface_row_y1.eq(surface_row_y1s[text_page_q]),
        ]
        content_surface = (
            active & True &
            (x >= NATIVE_CONTENT_PANEL_X0) &
            (x < NATIVE_CONTENT_PANEL_X1) &
            (cell_y >= surface_row_y0) & (cell_y < surface_row_y1))
        bank_control_y0s = (
            (compact_main_control_y0s))
        bank_panel_x0 = (283)
        bank_panel_x1 = (594)
        tune_y_shift = (-compact_content_shift)
        meter_panel = active & (
            (bank_page & (
                self.rect(x, y, bank_panel_x0, bank_control_y0s[0] - 2,
                          bank_panel_x1, bank_control_y0s[0] + 18) |
                self.rect(x, y, bank_panel_x0, bank_control_y0s[1] - 2,
                          bank_panel_x1, bank_control_y0s[1] + 18) |
                self.rect(x, y, bank_panel_x0, bank_control_y0s[2] - 2,
                          bank_panel_x1, bank_control_y0s[2] + 18))) |
            (tune_page & (native_feedback_track_rows(
                    self.rect, x, y, NATIVE_FEEDBACK_TRACK_X0,
                    NATIVE_FEEDBACK_TRACK_X1, y_shift=tune_y_shift,
                    amount_y_shift=compact_content_shift))) |
            (cross_page & (
                self.rect(x, y, (232),
                          (542),
                          (580),
                          (562)) |
                self.rect(x, y, (232),
                          (574),
                          (580),
                          (594)))))
        palette_chip = advanced_page & self.rect(
            x, y, (native_value_chip_x0(22)),
            (244),
            (456),
            (284))
        palette_select = advanced_page & (
            selected_dvi_q == StrezoUISpec.TARGET_PALETTE) & self.outline(
                x, y, ((native_value_chip_x0(22) - 4)),
                (240),
                (460),
                (288), t=3)
        save_default_chip = advanced_page & self.rect(
            x, y, (native_value_chip_x0(22)),
            (308),
            (472),
            (348))
        save_default_select = advanced_page & (
            selected_dvi_q == StrezoUISpec.TARGET_SAVE_DEFAULT) & self.outline(
                x, y, ((native_value_chip_x0(22) - 4)),
                (304),
                (476),
                (352), t=3)
        motion_source_x0 = (
            (NATIVE_MOTION_CONTROL_X0))
        motion_source_x1 = (440)
        motion_rate_x0 = (NATIVE_MOTION_CONTROL_X0)
        motion_rate_x1 = (376)
        motion_phase_x0 = (
            (NATIVE_MOTION_CONTROL_X0))
        motion_phase_x1 = (376)
        motion_depth_x0 = (
            (NATIVE_MOTION_CONTROL_X0))
        motion_depth_x1 = (
            (NATIVE_MOTION_CONTROL_X1))
        motion_depth_fill_x0 = (
            (NATIVE_MOTION_FILL_X0))
        motion_center_x = (
            (NATIVE_MOTION_CENTER_X))
        # Native glyph ink occupies y=[row*16, row*16+14). Starting each
        # compact chip two pixels above that span gives exact 2px top/bottom
        # padding instead of leaving the shaded row one pixel above the text.
        motion_top_y0 = (462)
        motion_top_y1 = (480)
        motion_rate_y0 = (494)
        motion_rate_y1 = (512)
        motion_phase_y0 = (526)
        motion_phase_y1 = (544)
        # DEPTH uses a 20px fader row, so three pixels around the same 14px
        # glyph span center both the label and lane at y=583.
        motion_bottom_y0 = (557)
        motion_bottom_y1 = (577)
        # SOURCE, RATE, and PHASE share the same 24-on/8-off vertical cadence.
        # Decode the column once instead of synthesizing three full rectangles.
        motion_value_x1 = Signal(unsigned(10), init=motion_rate_x1)
        m.d.comb += motion_value_x1.eq(Mux(
            y < motion_top_y1,
            motion_source_x1, motion_rate_x1))
        motion_value_chip = (
            bands_page &
            (y >= motion_top_y0) & (y < motion_phase_y1) &
            ((y[:5] >= (motion_top_y0 & 31)) |
             (y[:5] < (motion_top_y1 & 31))) &
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
        with m.Switch(selected_dvi_q):
            with m.Case(StrezoUISpec.TARGET_MOTION_SOURCE):
                m.d.comb += motion_chip_selected.eq(1)
            with m.Case(StrezoUISpec.TARGET_MOTION_RATE):
                m.d.comb += [
                    motion_select_x0.eq(motion_rate_x0 - 4),
                    motion_select_x1.eq(motion_rate_x1 + 4),
                    motion_select_y0.eq(motion_rate_y0 - 4),
                    motion_chip_selected.eq(1),
                ]
            with m.Case(StrezoUISpec.TARGET_MOTION_PHASE):
                m.d.comb += [
                    motion_select_x0.eq(motion_phase_x0 - 4),
                    motion_select_x1.eq(motion_phase_x1 + 4),
                    motion_select_y0.eq(motion_phase_y0 - 4),
                    motion_chip_selected.eq(1),
                ]
        motion_outline_height = (26)
        motion_chip_select = (
            bands_page & motion_chip_selected &
            self.outline(x, y, motion_select_x0, motion_select_y0,
                         motion_select_x1,
                         motion_select_y0 + motion_outline_height, t=3))
        motion_fader_height = (20)
        motion_depth_track = (
            bands_page &
            (y >= motion_bottom_y0) &
            (y < motion_bottom_y0 + motion_fader_height) &
            (x >= motion_depth_x0) & (x < motion_depth_x1))

        # Store absolute pixel endpoints in block memory. Keeping full native
        # coordinates (rather than quarter-pixel coordinates) lets DEPTH obey
        # the same exact 2-pixel inset as every other long fader.
        motion_ui_init = [motion_depth_fill_x0] * 512
        for depth_value in range(256):
            clamped_depth = min(depth_value, RezoCore.CROSS_DEPTH_MAX)
            motion_ui_init[depth_value] = (
                ((native_motion_depth_endpoint(
                    clamped_depth, motion_depth_fill_x0))))
        for raw_value in range(64):
            signed_value = raw_value if raw_value < 32 else raw_value - 64
            # The depth-scaled monitor's reachable source extrema are -16
            # and +15. Map those asymmetrical integer limits onto equal
            # 142-pixel excursions across the inset 284-pixel DEPTH lane.
            # This table is display-only; DSP modulation remains unchanged.
            if signed_value >= 0:
                scaled_value = min(142, round(signed_value * 142 / 15))
            else:
                scaled_value = round(signed_value * 142 / 16)
            motion_ui_init[256 + raw_value] = (
                motion_center_x + scaled_value)
        m.submodules.motion_ui_mem = motion_ui_mem = Memory(
            shape=unsigned(10), depth=len(motion_ui_init),
            init=motion_ui_init, attrs={"ram_style": "block"})
        motion_depth_rport = motion_ui_mem.read_port(domain="dvi")
        motion_monitor_rport = motion_ui_mem.read_port(domain="dvi")
        motion_depth_endpoint_q = Signal.like(motion_depth_rport.data)
        motion_monitor_negative_q = Signal()
        motion_monitor_endpoint_q = Signal.like(motion_monitor_rport.data)
        motion_monitor_negative_q2 = Signal()
        m.d.comb += [
            motion_depth_rport.addr.eq(self.motion_depth),
            motion_monitor_rport.addr.eq(
                256 | self.motion_monitor.as_unsigned()),
        ]
        # Align the sign with the synchronous endpoint-table read.  Without
        # this delay a zero crossing could combine a new sign with the prior
        # endpoint for one pixel clock.
        m.d.dvi += [
            # As with the monitor endpoint below, stage the block-RAM result
            # before the 10-bit pixel comparison. DEPTH changes many orders
            # of magnitude more slowly than the pixel clock.
            motion_depth_endpoint_q.eq(motion_depth_rport.data),
            motion_monitor_negative_q.eq(self.motion_monitor < 0),
            # Isolate the block-RAM clock-to-Q delay from the bipolar-line
            # geometry.  This is display-only telemetry; one 13 ns pixel
            # cycle of latency is invisible and leaves the DSP untouched.
            motion_monitor_endpoint_q.eq(motion_monitor_rport.data),
            motion_monitor_negative_q2.eq(motion_monitor_negative_q),
        ]
        motion_depth_fill = (
            bands_page & (x >= motion_depth_fill_x0) &
            (x < motion_depth_endpoint_q) &
            (y >= motion_bottom_y0 + 2) &
            (y < motion_bottom_y0 + motion_fader_height - 2))
        motion_depth_select = (
            bands_page &
            (selected_dvi_q == StrezoUISpec.TARGET_MOTION_DEPTH) &
            self.rect(x, y, motion_depth_x0 - 6, motion_bottom_y0,
                      motion_depth_x0 - 2,
                      motion_bottom_y0 + motion_fader_height))

        # A thin bipolar telemetry line reuses the same visual language as the
        # INPUT page. Its value comes from the audio engine's existing LFO;
        # the display does not synthesize another oscillator.
        motion_monitor_line = bands_page & self.bipolar_line(
            x, y, motion_center_x, motion_monitor_endpoint_q,
            ((motion_bottom_y0 + 18)),
            ((motion_bottom_y0 + 20)),
            motion_monitor_negative_q2)

        damp_chip = tune_page & self.rect(
            x, y, ((NATIVE_FEEDBACK_DAMPING_CHIP_X0)),
            ((NATIVE_FEEDBACK_DAMPING_CHIP_Y0 + tune_y_shift)),
            ((NATIVE_FEEDBACK_DAMPING_CHIP_X1)),
            ((NATIVE_FEEDBACK_DAMPING_CHIP_Y1 + tune_y_shift)))
        damp_select = tune_page & (
            selected_dvi_q == StrezoUISpec.TARGET_DAMP) & self.outline(
                x, y, ((NATIVE_FEEDBACK_DAMPING_CHIP_X0 - 4)),
                ((NATIVE_FEEDBACK_DAMPING_CHIP_Y0 + tune_y_shift - 4)),
                ((NATIVE_FEEDBACK_DAMPING_CHIP_X1 + 4)),
                ((NATIVE_FEEDBACK_DAMPING_CHIP_Y1 + tune_y_shift + 4)), t=3)
        layout_chip = bands_page & self.rect(
            x, y, ((native_value_chip_x0(16))),
            (NATIVE_PAGE_HEADER_CHIP_Y0),
            (368),
            (NATIVE_PAGE_HEADER_CHIP_Y1))
        layout_select = bands_page & (
            selected_dvi_q == StrezoUISpec.TARGET_BAND_LAYOUT) & self.outline(
                x, y, ((native_value_chip_x0(16) - 4)),
                (NATIVE_PAGE_HEADER_SELECT_Y0),
                (372),
                (NATIVE_PAGE_HEADER_SELECT_Y1),
                t=3)
        cross_layout_chip = cross_page & self.rect(
            x, y, ((native_value_chip_x0(16))),
            (NATIVE_PAGE_HEADER_CHIP_Y0),
            (392),
            (NATIVE_PAGE_HEADER_CHIP_Y1))
        cross_layout_select = cross_page & (
            selected_dvi_q == StrezoUISpec.TARGET_CROSS_LAYOUT) & self.outline(
                x, y, ((native_value_chip_x0(16) - 4)),
                (NATIVE_PAGE_HEADER_SELECT_Y0),
                (396),
                (NATIVE_PAGE_HEADER_SELECT_Y1),
                t=3)
        cross_curve_chip = advanced_page & self.rect(
            x, y, ((native_value_chip_x0(22))),
            (468),
            (488),
            (508))
        cross_curve_select = advanced_page & (
            selected_dvi_q == StrezoUISpec.TARGET_CROSS_CURVE) & self.outline(
                x, y, ((native_value_chip_x0(22) - 4)),
                (464),
                (492),
                (512), t=3)

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

        preset_chip_signals.append(bank_page & self.rect(
            text_x, text_y, native_value_chip_x0(16),
            NATIVE_PAGE_HEADER_CHIP_Y0,
            328, NATIVE_PAGE_HEADER_CHIP_Y1))
        preset_select_signals.append(
            bank_page & self.editing &
            (selected_dvi_q == StrezoUISpec.TARGET_PRESET) &
            self.outline(text_x, text_y, native_value_chip_x0(16) - 4,
                         NATIVE_PAGE_HEADER_SELECT_Y0, 332,
                         NATIVE_PAGE_HEADER_SELECT_Y1, t=3))

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
                x0 = ((133 + 47 * n))
                x1 = x0 + ((30))
                select_margin = (5)
                edge_margin = (3)
                zero_margin = (4)
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
        band_selected_target_q = Signal.like(selected_dvi_q)
        m.d.dvi += [
            band_y_q.eq(y),
            band_active_q.eq(active),
            band_home_page_q.eq(home_page),
            band_bank_page_q.eq(bank_page),
            band_tune_page_q.eq(tune_page),
            band_bands_page_q.eq(bands_page),
            band_selected_target_q.eq(selected_dvi_q),
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
        band_selected_target_value_q = Signal.like(selected_dvi_q)
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

        bands_enable_y0 = (283)
        bands_button_h = (34)
        bands_frequency_y0 = (382)
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
            StrezoUISpec.TARGET_BAND_BASE + band_index_q)
        feedback_band_selected = (
            band_selected_target_value_q ==
            StrezoUISpec.TARGET_FEEDBACK_SEND_BASE + band_index_q)
        enable_band_selected = (
            band_selected_target_value_q ==
            StrezoUISpec.TARGET_BAND_ENABLE_BASE + band_index_q)
        frequency_band_selected = (
            band_selected_target_value_q ==
            StrezoUISpec.TARGET_BAND_FREQ_BASE + band_index_q)
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
                 ((main_band_y)) &
                 base_bank_fill) |
                (band_tune_page_value_q & band_enable_q & band_fill_x_q &
                 band_slot_y & band_feedback_send_q) |
                (band_bands_page_value_q & band_fill_x_q & band_enable_q &
                 (band_y_value_q >= bands_enable_y0) &
                 (band_y_value_q < bands_enable_y0 + bands_button_h)))),
            band_mod_fill.eq(
                band_active_value_q & band_bank_page_value_q & band_enable_q &
                ((main_band_y)) &
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
        input_y_init = native_input_row_geometry(
            self.PANEL_H, first_y=(221))
        m.submodules.input_y_mem = input_y_mem = Memory(
            shape=unsigned(10), depth=self.PANEL_H, init=input_y_init,
            attrs={"ram_style": "block"})
        input_y_rport = input_y_mem.read_port(domain="dvi")
        m.d.comb += input_y_rport.addr.eq(y)

        input_x_q = Signal.like(x)
        # Two registered stages separate the row decoder/lane mux from the
        # endpoint arithmetic while preserving the established prefetch.
        m.d.dvi += input_x_q.eq(x + 1)
        input_local_y = input_y_rport.data[:7]
        input_index = input_y_rport.data[7:9]
        input_row_valid = input_y_rport.data[9]
        input_mode_selected = Array(self.input_modes)[input_index]
        input_gain_selected = Array(self.input_gains)[input_index]
        input_depth_selected = Array(self.cv_depths)[input_index]
        input_meter_selected = Array(self.input_meters)[input_index]
        input_targets = Array(
            Const(StrezoUISpec.TARGET_INPUT_BASE + n * 3, 7)
            for n in range(4))
        input_target_selected = input_targets[input_index]

        input_x_lane_q = Signal.like(input_x_q)
        input_local_lane_q = Signal.like(input_local_y)
        input_valid_lane_q = Signal()
        input_page_lane_q = Signal()
        input_mode_lane_q = Signal.like(input_mode_selected)
        input_gain_lane_q = Signal.like(input_gain_selected)
        input_depth_lane_q = Signal.like(input_depth_selected)
        input_meter_lane_q = Signal.like(input_meter_selected)
        input_target_lane_q = Signal.like(input_target_selected)
        input_selected_lane_q = Signal.like(selected_dvi_q)
        m.d.dvi += [
            input_x_lane_q.eq(input_x_q),
            input_local_lane_q.eq(input_local_y),
            input_valid_lane_q.eq(input_row_valid),
            input_page_lane_q.eq(input_page),
            input_mode_lane_q.eq(input_mode_selected),
            input_gain_lane_q.eq(input_gain_selected),
            input_depth_lane_q.eq(input_depth_selected),
            input_meter_lane_q.eq(input_meter_selected),
            input_target_lane_q.eq(input_target_selected),
            input_selected_lane_q.eq(selected_dvi_q),
        ]
        input_gain_end = native_input_gain_endpoint(input_gain_lane_q)
        input_depth_end = native_input_depth_endpoint(input_depth_lane_q)
        input_meter_end = native_input_meter_endpoint(
            input_meter_lane_q,
            input_mode_lane_q == RezoCore.INPUT_MODE_CV)
        input_unity_coarse = RezoCore.INPUT_UNITY_POS >> 8
        input_unity_x = (
            (native_input_unity_x(RezoCore.INPUT_UNITY_POS)))
        input_x_value_q = Signal.like(input_x_lane_q)
        input_local_value_q = Signal.like(input_local_lane_q)
        input_valid_value_q = Signal()
        input_page_value_q = Signal()
        input_is_cv_value_q = Signal()
        input_depth_negative_q = Signal()
        input_meter_negative_q = Signal()
        input_gain_end_q = Signal.like(input_gain_end)
        input_depth_end_q = Signal.like(input_depth_end)
        input_meter_end_q = Signal.like(input_meter_end)
        input_target_q = Signal.like(input_target_lane_q)
        input_row_selected_q = Signal.like(selected_dvi_q)
        m.d.dvi += [
            input_x_value_q.eq(input_x_lane_q),
            input_local_value_q.eq(input_local_lane_q),
            input_valid_value_q.eq(input_valid_lane_q),
            input_page_value_q.eq(input_page_lane_q),
            input_is_cv_value_q.eq(
                input_mode_lane_q == RezoCore.INPUT_MODE_CV),
            input_depth_negative_q.eq(input_depth_lane_q < 0),
            input_meter_negative_q.eq(input_meter_lane_q < 0),
            input_gain_end_q.eq(input_gain_end),
            input_depth_end_q.eq(input_depth_end),
            input_meter_end_q.eq(input_meter_end),
            input_target_q.eq(input_target_lane_q),
            input_row_selected_q.eq(input_selected_lane_q),
        ]
        input_visible = input_page_value_q & input_valid_value_q
        input_is_cv = input_is_cv_value_q
        input_mode_x0 = (304)
        input_mode_x1 = (402)
        input_value_x0 = (304)
        input_value_x1 = (370)
        input_lane_x1 = (576)
        input_select_x0 = (300)
        input_panel_q0 = input_visible & (
            self.rect(input_x_value_q, input_local_value_q,
                      input_mode_x0, (0),
                      input_mode_x1, (20)) |
            Mux(input_is_cv,
                self.rect(input_x_value_q, input_local_value_q,
                          input_value_x0, (32),
                          input_value_x1, (52)),
                self.rect(input_x_value_q, input_local_value_q,
                          input_value_x0, (32),
                          input_lane_x1, (52))) |
            (input_is_cv & self.rect(
                input_x_value_q, input_local_value_q,
                input_value_x0, (64),
                input_lane_x1, (84))))
        input_select_q0 = input_visible & (
            ((input_row_selected_q == input_target_q) &
             self.outline(input_x_value_q, input_local_value_q,
                          input_select_x0, 0,
                          input_mode_x1 + 4,
                          (24), t=3)) |
            ((input_row_selected_q == input_target_q + 1) & Mux(
                input_is_cv,
                self.outline(input_x_value_q, input_local_value_q,
                             input_select_x0,
                             (28),
                             input_value_x1 + 4,
                             (56), t=3),
                self.rect(input_x_value_q, input_local_value_q,
                          (300),
                          (34),
                          (304),
                          (50)))) |
            (input_is_cv & (input_row_selected_q == input_target_q + 2) &
             self.rect(input_x_value_q, input_local_value_q,
                       (300),
                       (66),
                       (304),
                       (82))))
        input_fill_q0 = input_visible & Mux(
            input_is_cv,
            Mux(~input_depth_negative_q,
                self.rect(input_x_value_q, input_local_value_q,
                          (440),
                          (66),
                          input_depth_end_q,
                          (82)),
                self.rect(input_x_value_q, input_local_value_q,
                          input_depth_end_q,
                          (66),
                          (440),
                          (82))),
            self.rect(input_x_value_q, input_local_value_q,
                      (NATIVE_INPUT_FILL_X0),
                      (34),
                      input_gain_end_q,
                      (50)))
        input_line_q0 = input_visible & (
            (input_is_cv & self.rect(
                input_x_value_q, input_local_value_q,
                (439),
                (66),
                (442),
                (86))) |
            (~input_is_cv & self.rect(
                input_x_value_q, input_local_value_q, input_unity_x,
                (34),
                input_unity_x + 3,
                (54))))
        # A uniform telemetry line immediately below VALUE. Audio is unipolar
        # from the bar's left edge; CV is bipolar around the DEPTH center.
        input_meter_q0 = input_visible & Mux(
            input_is_cv,
            self.bipolar_line(
                input_x_value_q, input_local_value_q,
                (440),
                input_meter_end_q,
                (82),
                (84),
                input_meter_negative_q),
            self.rect(input_x_value_q, input_local_value_q,
                      (304),
                      (50),
                      input_meter_end_q,
                      (52)))

        for group in range(RezoCore.N_GROUPS):
            rail_y = ((compact_group_centers[group]))
            group_cell_signals.append(
                group_page & self.rect(
                    x, (text_y),
                    (202), rail_y,
                    (576),
                    rail_y + ((2))))

        group_selected_index = Signal(range(RezoCore.N_BANDS))
        group_selected_x_pre = Signal(
            unsigned(10), init=(208))
        group_selected_x = Signal.like(group_selected_x_pre)
        group_selected_valid_pre = Signal()
        group_selected_valid = Signal()
        m.d.comb += [
            group_selected_index.eq(0),
            group_selected_x_pre.eq((208)),
            group_selected_valid_pre.eq(
                (selected_dvi_q >= StrezoUISpec.TARGET_GROUP_BASE) &
                (selected_dvi_q < StrezoUISpec.TARGET_GROUP_BASE +
                 RezoCore.N_BANDS)),
        ]
        with m.If(group_selected_valid_pre):
            m.d.comb += [
                group_selected_index.eq(
                    selected_dvi_q - StrezoUISpec.TARGET_GROUP_BASE),
                group_selected_x_pre.eq((208 + (group_selected_index << 5) +
                          (group_selected_index << 1))),
            ]
        m.d.dvi += [
            group_selected_x.eq(group_selected_x_pre),
            group_selected_valid.eq(group_selected_valid_pre),
        ]
        group_select_signals.append(
            group_page & group_selected_valid & self.outline(
                x, y,
                group_selected_x - ((5)),
                (306),
                group_selected_x + ((23)),
                (486), t=3))
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
        group_geometry_init = native_group_geometry(
            self.PANEL_W)
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
        m.d.comb += group_fill.eq(
            ((group_page_value_q)) &
            group_band_active_value_q & group_row_active_value_q &
            band_enable_mask_array[group_band_value_q] &
            bank_group_mask_array[group_band_value_q].bit_select(
                group_row_value_q, 1))
        # Disabled BANK bands retain dim top/bottom rails at all four GROUPS
        # assignments. A full forty-cell rectangle decoder costs more logic
        # than remains available; these shared rails preserve location and
        # inactive state without implying an enabled assignment.
        m.d.comb += group_ghost.eq(
            ((group_page_value_q)) &
            group_band_active_value_q & group_row_active_value_q &
            group_row_edge_value_q &
            ~band_enable_mask_array[group_band_value_q])

        output_row = Signal(unsigned(2))
        output_source = Signal(unsigned(3))
        output_row_active = Signal()
        output_col_active = Signal()
        output_row_edge = Signal()
        output_col_edge = Signal()
        output_col_init = native_output_column_geometry(
            self.PANEL_W)
        m.submodules.output_col_mem = output_col_mem = Memory(
            shape=unsigned(5), depth=self.PANEL_W, init=output_col_init,
            attrs={"ram_style": "block"})
        output_col_rport = output_col_mem.read_port(domain="dvi")
        m.d.comb += output_col_rport.addr.eq(x.as_unsigned())
        standard_output_source = output_col_rport.data[:3]
        m.submodules.output_send_mem = output_send_mem = Memory(
            shape=unsigned(7), depth=20, init=[0] * 20,
            attrs={"ram_style": "block"})
        output_send_rport = output_send_mem.read_port(domain="dvi")
        output_send_wport = output_send_mem.write_port(domain="sync")
        output_send_scaled_write = Signal(unsigned(7))
        m.d.comb += [
            output_send_scaled_write.eq((self.output_send_write_data +
                (self.output_send_write_data << 1))),
            output_send_wport.addr.eq(self.output_send_write_addr),
            output_send_wport.data.eq(output_send_scaled_write),
            output_send_wport.en.eq(self.output_send_write_en),
        ]
        output_cell_x0 = Signal(unsigned(10))
        output_cell_y0 = Signal(unsigned(10))
        output_send_index = Signal(unsigned(5))
        m.d.comb += [
            output_row.eq(0),
            output_row_active.eq(0),
            output_row_edge.eq(0),
            output_source.eq(Mux(cross_page, 0, standard_output_source)),
            output_col_active.eq(~cross_page & output_col_rport.data[4]),
            output_col_edge.eq(~cross_page & output_col_rport.data[3]),
            output_cell_x0.eq(Mux(
                cross_page,
                (227),
                ((243 + (standard_output_source << 6) +
                  Mux(standard_output_source == 4, 8, 0))))),
            output_cell_y0.eq(
                (compact_output_row_centers[0] - 13)),
            output_send_index.eq(0),
        ]
        for output in range(4):
            output_row_y = (
                (compact_output_row_centers[output] - 13))
            row_y = (
                (Mux(cross_page,
                    compact_cross_row_centers[output] - 13,
                    output_row_y)))
            output_geom_y = (text_y)
            with m.If((output_geom_y >= row_y) &
                      (output_geom_y < row_y + 28)):
                m.d.comb += [
                    output_row.eq(output),
                    output_row_active.eq(1),
                    output_row_edge.eq(
                        (output_geom_y < row_y + 2) |
                        (output_geom_y >= row_y + 26)),
                    output_cell_y0.eq(row_y),
                ]
        # CROSS has four genuinely different column positions; only that
        # product-specific page keeps a small comparator decoder. OUTPUT uses
        # the exact shared five-column ROM used by REZO and REZOMO above.
        for source in range(4):
            cell_width = (56)
            cell_x0 = (
                (compact_cross_col_centers[source] - 27))
            output_geom_x = (text_x)
            with m.If(cross_page & (output_geom_x >= cell_x0) &
                      (output_geom_x < cell_x0 + cell_width)):
                m.d.comb += [
                    output_source.eq(source),
                    output_col_active.eq(1),
                    output_col_edge.eq(
                        (output_geom_x < cell_x0 + 2) |
                        (output_geom_x >= cell_x0 + cell_width - 2)),
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
            output_x_q.eq((text_x)),
            output_y_q.eq((text_y)),
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
                (x >= ((NATIVE_OUTPUT_SIDE_CHIP_X0))) &
                (x < ((NATIVE_OUTPUT_SIDE_CHIP_X1)))),
            output_side_select.eq(
                output_page & output_row_active &
                (selected_dvi_q == StrezoUISpec.TARGET_OUTPUT_SIDE_BASE + output_row) &
                (x >= ((NATIVE_OUTPUT_SIDE_CHIP_X0 - 4))) &
                (x < ((NATIVE_OUTPUT_SIDE_CHIP_X1 + 4))) &
                ((x < ((NATIVE_OUTPUT_SIDE_CHIP_X0))) |
                 (x >= ((NATIVE_OUTPUT_SIDE_CHIP_X1))) |
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
        output_selected_row_q = Signal(unsigned(2))
        output_selected_source_q = Signal(unsigned(3))
        output_selected_valid_q = Signal()
        output_header_group = Signal(unsigned(2))
        output_header_row_target = Signal()
        output_header_col_target = Signal()
        # Selection changes only on UI events. Decode its row and source before
        # the live pixel path so OUTPUT does not reconstruct and compare a
        # five-column linear send index after the column BRAM.
        with m.Switch(selected_dvi_q):
            for output_row_index in range(4):
                for output_source_index in range(5):
                    with m.Case(
                            StrezoUISpec.TARGET_OUTPUT_BASE +
                            output_row_index * 5 + output_source_index):
                        m.d.dvi += [
                            output_selected_row_q.eq(output_row_index),
                            output_selected_source_q.eq(output_source_index),
                            output_selected_valid_q.eq(1),
                        ]
            with m.Default():
                m.d.dvi += [
                    output_selected_row_q.eq(0),
                    output_selected_source_q.eq(0),
                    output_selected_valid_q.eq(0),
                ]
        m.d.comb += [
            # Both shared target bases are 2 modulo 4. This wiring maps their
            # low bits back to a zero-based group without subtraction.
            output_header_group[0].eq(selected_dvi_q[0]),
            output_header_group[1].eq(~selected_dvi_q[1]),
            output_header_row_target.eq(
                (selected_dvi_q >= StrezoUISpec.TARGET_OUTPUT_ROW_BASE) &
                (selected_dvi_q < StrezoUISpec.TARGET_OUTPUT_ROW_BASE + 4)),
            output_header_col_target.eq(
                (selected_dvi_q >= StrezoUISpec.TARGET_OUTPUT_COL_BASE) &
                (selected_dvi_q < StrezoUISpec.TARGET_OUTPUT_COL_BASE + 4)),
        ]
        m.d.comb += [
            # Keep the four-column CROSS selection path independent of the
            # five-column OUTPUT send address.  Sharing the target arithmetic
            # made the DVI path unnecessarily deep and also made it too easy
            # to accidentally inherit OUTPUT's row stride here.
            cross_cell_selected.eq(
                cross_page &
                (selected_dvi_q[4:] ==
                 StrezoUISpec.TARGET_CROSS_MATRIX_BASE >> 4) &
                (selected_dvi_q[:4] == Cat(output_source[:2], output_row))),
            output_cell_selected.eq(
                output_page &
                output_selected_valid_q &
                (output_row == output_selected_row_q) &
                (output_source == output_selected_source_q)),
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
                    (x >= ((132))) &
                    (x < ((136))))) |
                  (output_col_active & (output_source < 4) &
                   output_header_col_target &
                   (output_header_group == output_source) &
                   (y >= ((264))) &
                   (y < ((268)))))) |
                output_header_selection(
                    page=output_page,
                    row_active=output_row_active,
                    col_active=output_col_active,
                    row_target=output_header_row_target,
                    col_target=output_header_col_target,
                    selected_row=output_header_group,
                    selected_col=output_header_group,
                    matrix_row=output_row,
                    matrix_col=output_source,
                    dry_selected=(
                        selected_dvi_q ==
                        StrezoUISpec.TARGET_OUTPUT_DRY_COL),
                    x=x, y=y,
                    y_shift=-3 * compact_content_shift)),
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
            bank_page & (selected_dvi_q == StrezoUISpec.TARGET_PRESET) &
            ~self.editing & self.outline(
                (text_x),
                (text_y),
                ((native_value_chip_x0(16) - 4)),
                ((NATIVE_PAGE_HEADER_SELECT_Y0)),
                (332),
                ((NATIVE_PAGE_HEADER_SELECT_Y1)), t=3))
        drive_select = (
            bank_page & (selected_dvi_q == StrezoUISpec.TARGET_DRIVE) &
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
        control_fill_x0 = (NATIVE_MAIN_FILL_X0)
        bank_control_end = (
            (native_main_fader_endpoint(bank_control_base_q, control_fill_x0)))
        bank_control_effective_end = (
            (native_main_fader_endpoint(bank_control_effective_q,
                                       control_fill_x0)))
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

        cross_track_x0 = (234)
        same_y0 = (544)
        cross_y0 = (576)
        # Endpoint arithmetic used to sit on the same DVI-cycle path as the
        # remaining page geometry and palette selection.  The controls update
        # many orders of magnitude more slowly than the pixel clock, so stage
        # both endpoints once here to keep the renderer's timing independent
        # of the shift/add mapping without introducing perceptible UI latency.
        same_feedback_end_q = Signal(unsigned(10))
        cross_feedback_end_q = Signal(unsigned(10))
        m.d.dvi += [
            same_feedback_end_q.eq(
                native_cross_fader_endpoint(self.same_feedback,
                                             cross_track_x0)),
            cross_feedback_end_q.eq(
                native_cross_fader_endpoint(self.cross_feedback,
                                             cross_track_x0)),
        ]
        same_feedback_width = (
            (same_feedback_end_q - cross_track_x0))
        cross_feedback_width = (
            (cross_feedback_end_q - cross_track_x0))
        same_fill = cross_page & self.rect(
            x, y, cross_track_x0, same_y0,
            cross_track_x0 + same_feedback_width,
            same_y0 + 16)
        cross_fill = cross_page & self.rect(
            x, y, cross_track_x0, cross_y0,
            cross_track_x0 + cross_feedback_width,
            cross_y0 + 16)
        cross_select = cross_page & (
            ((selected_dvi_q == StrezoUISpec.TARGET_SAME_FEEDBACK) &
             self.rect(x, y, cross_track_x0 - 6, same_y0,
                       cross_track_x0 - 2, same_y0 + 16)) |
            ((selected_dvi_q == StrezoUISpec.TARGET_CROSS_FEEDBACK) &
             self.rect(x, y, cross_track_x0 - 6, cross_y0,
                       cross_track_x0 - 2, cross_y0 + 16)))
        tune_fill_x0 = (NATIVE_FEEDBACK_FILL_X0)
        tune_fill_scale_shift = (0)
        compact_tune_feedback_end_q = Signal(unsigned(10))
        # KNEE and CEILING are user-facing 16..128 controls.  The old compact
        # map advanced only 1.125 pixels per step, so the valid maximum stopped
        # near the middle of the 320-pixel lane.  A 2.5x shift/add maps 128 to
        # the lane's exact right edge without changing the DSP coefficient.
        compact_tune_knee_end_q = Signal(unsigned(10))
        compact_tune_cap_end_q = Signal(unsigned(10))
        m.d.dvi += [
            compact_tune_feedback_end_q.eq(
                native_main_fader_endpoint(self.feedback, tune_fill_x0)),
            compact_tune_knee_end_q.eq(
                native_main_fader_endpoint(self.limit_knee, tune_fill_x0)),
            compact_tune_cap_end_q.eq(
                native_main_fader_endpoint(self.limit_cap, tune_fill_x0)),
        ]
        tune_feedback_fill = tune_page & self.rect(
            x, y, tune_fill_x0,
            ((NATIVE_FEEDBACK_AMOUNT_Y0)),
            ((compact_tune_feedback_end_q)),
            ((NATIVE_FEEDBACK_AMOUNT_Y0 + 16)))
        tune_feedback_select = (
            tune_page &
            (selected_dvi_q == StrezoUISpec.TARGET_FEEDBACK) &
            self.outline(x, y,
                         (264),
                         ((NATIVE_FEEDBACK_AMOUNT_Y0 - 4)),
                         (592),
                         ((NATIVE_FEEDBACK_AMOUNT_Y0 + 20)), t=3))
        dry_fill = tune_page & self.rect(
            x, y, tune_fill_x0,
            ((NATIVE_FEEDBACK_KNEE_Y0 + tune_y_shift)),
            ((compact_tune_knee_end_q)),
            ((NATIVE_FEEDBACK_KNEE_Y0 + 16 + tune_y_shift)))
        dry_select = (
            tune_page &
            (selected_dvi_q == StrezoUISpec.TARGET_LIMIT_KNEE) &
            self.outline(x, y,
                         (264),
                         ((NATIVE_FEEDBACK_KNEE_Y0 - 4 + tune_y_shift)),
                         (592),
                         ((NATIVE_FEEDBACK_KNEE_Y0 + 20 + tune_y_shift)), t=3))
        tune_cap_fill = tune_page & self.rect(
            x, y, tune_fill_x0,
            ((NATIVE_FEEDBACK_CEILING_Y0 + tune_y_shift)),
            ((compact_tune_cap_end_q)),
            ((NATIVE_FEEDBACK_CEILING_Y0 + 16 + tune_y_shift)))
        limit_relation_marker = tune_page & (
            self.rect(
                x, y, compact_tune_cap_end_q - 1,
                NATIVE_FEEDBACK_KNEE_Y0 + tune_y_shift,
                compact_tune_cap_end_q + 1,
                NATIVE_FEEDBACK_KNEE_Y0 + 16 + tune_y_shift) |
            self.rect(
                x, y, compact_tune_knee_end_q - 1,
                NATIVE_FEEDBACK_CEILING_Y0 + tune_y_shift,
                compact_tune_knee_end_q + 1,
                NATIVE_FEEDBACK_CEILING_Y0 + 16 + tune_y_shift))
        res_select = (
            (bank_page &
             (selected_dvi_q == StrezoUISpec.TARGET_RESONANCE) &
             self.outline(x, y, bank_panel_x0,
                          bank_control_y0s[1] - 2, bank_panel_x1,
                          bank_control_y0s[1] + 18, t=3)) |
            (tune_page &
             (selected_dvi_q == StrezoUISpec.TARGET_LIMIT_CAP) &
             self.outline(x, y,
                          (264),
                          ((NATIVE_FEEDBACK_CEILING_Y0 - 4 + tune_y_shift)),
                          (592),
                          ((NATIVE_FEEDBACK_CEILING_Y0 + 20 + tune_y_shift)), t=3)))
        fb_select = (bank_page &
                     (selected_dvi_q == StrezoUISpec.TARGET_FEEDBACK) &
                     self.outline(x, y, bank_panel_x0,
                                  bank_control_y0s[2] - 2,
                                  bank_panel_x1,
                                  bank_control_y0s[2] + 18, t=3))
        page_select = (
            (selected_dvi_q == StrezoUISpec.TARGET_PAGE) &
            self.outline((text_x),
                         (text_y),
                         (212),
                         (120),
                         (364),
                         (150), t=3))

        bank_selected_q = Signal()
        input_selected_q = Signal()
        routing_selected_q = Signal()
        advanced_selected_q = Signal()
        bands_selected_q = Signal()
        cross_selected_q = Signal()
        page_selected_q = Signal()
        m.d.dvi += [
            bank_selected_q.eq(preset_select | preset_group_select | band_select_q0 |
                               drive_select | tune_feedback_select |
                               dry_select | res_select | fb_select | damp_select),
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
        surface_q = Signal()
        active_q = Signal()
        geometry_fill_q0 = Signal()
        geometry_line_q0 = Signal()
        geometry_mod_q0 = Signal()
        geometry_panel_q0 = Signal()
        m.d.dvi += [
            geometry_fill_q0.eq(band_fill | band_marker | bank_control_fill |
                                same_fill | cross_fill | tune_feedback_fill |
                                dry_fill |
                                tune_cap_fill | motion_depth_fill),
            geometry_line_q0.eq(
                band_zero_q0 | bank_control_mod_marker | border |
                cursor_chip | limit_relation_marker),
            geometry_mod_q0.eq(band_mod_fill | bank_control_mod_fill |
                               input_meter_q0 | motion_monitor_line),
            geometry_panel_q0.eq(preset_chip | palette_chip | cross_curve_chip |
                                 save_default_chip |
                                 motion_value_chip |
                                 damp_chip | layout_chip |
                                 side_page_chip |
                                 band_slot_q0 | output_side_chip |
                                 meter_panel | motion_depth_track |
                                 output_meter_panel_q0),
        ]
        m.d.dvi += [
            selected_q.eq(selected | pager_current |
                          output_meter_hot_q0 | output_meter_clip_q0),
            text_q.eq(text),
            fill_q.eq(geometry_fill_q0 |
                      input_fill_q0 | group_fill_q0 | output_fill_q0 |
                      output_meter_fill_q0),
            line_q.eq(geometry_line_q0 | input_line_q0 |
                      group_ghost_q0 | pager_line),
            mod_q.eq(geometry_mod_q0),
            panel_q.eq(geometry_panel_q0 | input_panel_q0 | group_cell_q0 |
                       output_cell_q0 | cross_layout_chip),
            background_q.eq((arc_background)),
            active_q.eq(active),
            surface_q.eq(content_surface),
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
        with m.Elif(surface_q):
            m.d.comb += palette_role.eq(7)

        # Black is a renderer constant rather than a palette entry. The
        # eighth hardware color is now available for shaded content surfaces.
        palette_visible = (selected_q | text_q | mod_q | fill_q | line_q |
                           panel_q | background_q | surface_q)
        palette_visible_q = Signal()
        m.d.dvi += palette_visible_q.eq(palette_visible)

        palette_init = [color for theme in self.RGB_PALETTES for color in theme]
        m.submodules.palette_mem = palette_mem = Memory(
            shape=unsigned(24), depth=len(palette_init), init=palette_init,
            attrs={"ram_style": "block"})
        palette_rport = palette_mem.read_port(domain="dvi")
        m.d.comb += palette_rport.addr.eq(Cat(palette_role, self.palette))

        m.d.comb += [
            self.r.eq(Mux(palette_visible_q,
                          palette_rport.data[16:24], 0)),
            self.g.eq(Mux(palette_visible_q,
                          palette_rport.data[8:16], 0)),
            self.b.eq(Mux(palette_visible_q,
                          palette_rport.data[0:8], 0)),
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
    # This design's DVI PHY placement is especially tight at 720p60.
    # Placement candidate 8 is the measured all-clock route after
    # persistence-transport consolidation, while the environment override
    # remains useful for place-and-route experiments.
    # The polished BANDS renderer needs a density pass plus a lower ABC9 wire
    # weight than synth_ecp5's fixed 300 ps. W=150 is the measured balance;
    # W=175 and W=200 both map over capacity. Keeping the staged commands on
    # the fragment makes generated top.ys reproduce the candidate with native
    # Yosys.
    synth_opts = "-abc9 -abc2 -run begin:map_luts"
    script_after_synth = (
        "abc; techmap -map +/lattice/latches_map.v; abc9 -W 160; clean; "
        "synth_ecp5 -abc9 -abc2 -top top -run map_cells:check; "
        "attrmvcp -copy -attr BEL; "
        "autoname; hierarchy -check; stat; check -noinit; "
        "blackbox =A:whitebox"
    )
    nextpnr_opts = (
        "--timing-allow-fail --seed "
        f"{os.getenv('TILIQUA_STREZO_SEED', os.getenv('TILIQUA_REZO_SEED', '8'))}"
    )

    def __init__(self, clock_settings, *, firmware_bin_path=None):
        assert clock_settings.modeline is not None
        self.clock_settings = clock_settings
        self.firmware_bin_path = firmware_bin_path
        self.pmod0 = eurorack_pmod.EurorackPmod(
            self.clock_settings.audio_clock, with_boot_slot=True)

    def elaborate(self, platform):
        m = Module()
        cpu_firmware_path = (
            self.firmware_bin_path or
            os.getenv("TILIQUA_STREZO_CPU_FIRMWARE"))
        if cpu_firmware_path is None:
            raise ValueError("STREZO production images require CPU firmware")
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

        try:
            from .cpu_control import StrezoCpuControlPlane
        except ImportError:  # top_level_cli executes this file directly.
            from cpu_control import StrezoCpuControlPlane
        m.submodules.cpu_control = cpu_control = StrezoCpuControlPlane(
            self.clock_settings, firmware_bin_path=cpu_firmware_path)
        if sim.is_hw(platform):
            m.d.comb += [
                cpu_control.encoder0.pins.i.eq(enc_pins.i.i),
                cpu_control.encoder0.pins.q.eq(enc_pins.q.i),
                cpu_control.encoder0.pins.s.eq(enc_pins.s.i),
            ]

        m.submodules.pmod0 = pmod0 = self.pmod0
        m.submodules.rezo = rezo = RezoCore(fs=self.clock_settings.audio_clock.fs())
        ui = cpu_control.ui
        if sim.is_hw(platform):
            m.submodules.cpu_spi_transfer = cpu_spi_transfer = \
                SPIFlashTransfer()
            m.submodules.cpu_spi_phy = cpu_spi_phy = \
                spiflash.SPIPHYController(domain="sync", divisor=1)
            m.submodules.cpu_spi_provider = cpu_spi_provider = \
                spiflash.ECP5ConfigurationFlashProvider()
            wiring.connect(m, cpu_spi_transfer.spi, cpu_spi_phy.ctrl)
            wiring.connect(m, cpu_spi_phy.pins, cpu_spi_provider.pins)
            m.d.comb += [
                cpu_control.flash_window.boot_slot.eq(pmod0.boot_slot),
                cpu_control.flash_window.boot_slot_valid.eq(
                    pmod0.boot_slot_valid),
                cpu_control.flash_window.boot_slot_checked.eq(
                    pmod0.boot_slot_checked),
                cpu_spi_transfer.start.eq(
                    cpu_control.flash_window.xfer_start),
                cpu_spi_transfer.chip_select.eq(
                    cpu_control.flash_window.xfer_cs),
                cpu_spi_transfer.tx_data.eq(
                    cpu_control.flash_window.xfer_tx),
                cpu_spi_transfer.length.eq(
                    cpu_control.flash_window.xfer_length),
                cpu_spi_transfer.output_mask.eq(
                    cpu_control.flash_window.xfer_mask),
                cpu_control.flash_window.xfer_rx.eq(
                    cpu_spi_transfer.rx_data),
                cpu_control.flash_window.xfer_done.eq(
                    cpu_spi_transfer.done),
            ]
        else:
            m.d.comb += [
                cpu_control.flash_window.boot_slot.eq(0),
                cpu_control.flash_window.boot_slot_valid.eq(0),
                cpu_control.flash_window.boot_slot_checked.eq(1),
                cpu_control.flash_window.xfer_rx.eq(0),
                cpu_control.flash_window.xfer_done.eq(0),
            ]
        m.submodules.audio_out_fifo = audio_out_fifo = dsp.SyncFIFOBuffered(
            shape=data.ArrayLayout(ASQ, 4), depth=4)

        if sim.is_hw(platform):
            m.d.comb += pmod0.codec_mute.eq(reboot.mute | ~ui.startup_done)

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

        # Display-only final-output peak envelopes on a calibrated -60..0
        # dBFS scale. One time-multiplexed BRAM serves all four lanes.
        output_meter_values = [
            Signal(unsigned(6), name=f"output_meter_value{n}")
            for n in range(4)]
        output_clip_holds = [
            Signal(unsigned(6), name=f"output_clip_hold{n}")
            for n in range(4)]
        output_meter_decay = Signal(unsigned(11))
        output_frame_accepted = rezo.o.valid & rezo.o.ready
        output_db_init = [
            output_meter_db_value(magnitude) for magnitude in range(1024)]
        m.submodules.output_db_mem = output_db_mem = Memory(
            shape=unsigned(6), depth=len(output_db_init),
            init=output_db_init, attrs={"ram_style": "block"})
        output_db_rport = output_db_mem.read_port()
        output_magnitudes = [
            Signal(unsigned(10), name=f"output_magnitude{n}")
            for n in range(4)]
        output_meter_scan = Signal(unsigned(2))
        output_meter_scan_q = Signal(unsigned(2))
        m.d.comb += output_db_rport.addr.eq(
            Array(output_magnitudes)[output_meter_scan])
        m.d.sync += [
            output_meter_scan.eq(output_meter_scan + 1),
            output_meter_scan_q.eq(output_meter_scan),
        ]
        with m.If(output_frame_accepted):
            m.d.sync += output_meter_decay.eq(output_meter_decay + 1)
            for n in range(4):
                output_magnitude_full = Signal(
                    unsigned(16), name=f"output_magnitude_full{n}")
                output_clip = Signal(name=f"output_clip{n}")
                m.d.comb += [
                    output_magnitude_full.eq(Mux(
                        rezo.o.payload[n].as_value()[-1],
                        (~rezo.o.payload[n].as_value().as_unsigned()) + 1,
                        rezo.o.payload[n].as_value().as_unsigned())),
                    output_clip.eq(
                        (rezo.o.payload[n].as_value() == 32767) |
                        (rezo.o.payload[n].as_value() == -32768)),
                ]
                m.d.sync += output_magnitudes[n].eq(Mux(
                    output_magnitude_full[15], 1023,
                    output_magnitude_full[5:15]))
                with m.If((output_meter_decay == 0x7ff) &
                          (output_meter_values[n] != 0)):
                    m.d.sync += output_meter_values[n].eq(
                        output_meter_values[n] - 1)
                with m.If(output_clip):
                    m.d.sync += output_clip_holds[n].eq(45)
                with m.Elif((output_meter_decay == 0x7ff) &
                            (output_clip_holds[n] != 0)):
                    m.d.sync += output_clip_holds[n].eq(
                        output_clip_holds[n] - 1)
        with m.Switch(output_meter_scan_q):
            for n in range(4):
                with m.Case(n):
                    with m.If(output_db_rport.data > output_meter_values[n]):
                        m.d.sync += output_meter_values[n].eq(
                            output_db_rport.data)

        m.submodules.dvi_tgen = dvi_tgen = dvi.DVITimingGen()
        for member in dvi_tgen.timings.signature.members:
            m.d.comb += getattr(dvi_tgen.timings, member).eq(
                getattr(self.clock_settings.modeline, member))

        round_display = (
            self.clock_settings.modeline.h_active == RezoTileDisplay.PANEL_W and
            self.clock_settings.modeline.v_active == RezoTileDisplay.PANEL_H)
        m.submodules.display = display = RezoTileDisplay(
            h_active=self.clock_settings.modeline.h_active,
            rotate_left=round_display)
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
            m.submodules += FFSynchronizer(
                i=output_meter_values[n], o=display.output_meters[n],
                o_domain="dvi")
            m.submodules += FFSynchronizer(
                i=output_clip_holds[n] != 0, o=display.output_clips[n],
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
            # Keep one shared phase ring for all four lanes. Independently
            # reset rings can leave reset on different dvi5x edges and then
            # serialize the colour and clock lanes at different word phases.
            # Split registered load strobes retain the low-fanout timing shape
            # without sacrificing lane alignment. Keep each lane's strobes
            # and shift registers beside its fixed DVI pin; leaving these
            # unconstrained made an otherwise timing-clean route fail to
            # produce a receiver-lockable signal in hardware.
            m.submodules.dvi_gen = dvi_gen = dvi.DVIPHY(
                split_load_strobes=True,
                serializer_lane_x=(70, 49, 60, 65))
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


def run_cli(*, name="STREZO", artifact_name=None, modeline=None,
            fragment=RezoBeamTop, argparse_fragment=None):
    this_path = os.path.dirname(os.path.realpath(__file__))

    def configure_parser(parser):
        defaults = {"name": name, "artifact_name": artifact_name}
        if modeline is not None:
            defaults["modeline"] = modeline
        parser.set_defaults(**defaults)

    top_level_cli(
        fragment, path=this_path,
        argparse_callback=configure_parser,
        argparse_fragment=argparse_fragment,
        archiver_callback=lambda archiver: archiver.with_option_storage())


if __name__ == "__main__":
    run_cli(
        name=os.getenv("TILIQUA_REZO_FAMILY_NAME", "STREZO"),
        artifact_name=os.getenv("TILIQUA_REZO_FAMILY_ARTIFACT_NAME") or None,
        modeline=os.getenv("TILIQUA_REZO_FAMILY_MODELINE") or None,
    )
