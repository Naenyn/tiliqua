from amaranth.sim import Simulator

from rezo_ui_support import click as _click
from rezo_ui_support import fast_click_ui
from rezo_ui_support import hold as _hold
from rezo_ui_support import turn as _turn
from top.rezo.strezo_variant import RezoCore, RezoHardwareUI


FastClickRezoUI = fast_click_ui(RezoHardwareUI)


def test_ui_shared_feedback_toggle_path():
    """FEEDBACK navigates top-to-bottom and toggles only the selected band."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> OPTIONS -> CROSS -> FEEDBACK.
        await _click(ctx, dut)
        for _ in range(3):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 1
        await _click(ctx, dut)

        # Forward entry reaches the band row before the lower safety faders.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK_SEND_BASE
        await _click(ctx, dut)
        assert ctx.get(dut.feedback_sends[0]) == 0
        assert all(ctx.get(dut.feedback_sends[n]) == 1 for n in range(1, 10))

        for _ in range(9):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK_SEND_BASE + 9
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_FEEDBACK
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_LIMIT_KNEE

    sim.add_testbench(bench)
    sim.run()

def test_ui_output_headers_bulk_edit_before_saved_stereo_side_selectors():
    """OUTPUT exposes relative columns/rows, then each L/R and send cell."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> OPTIONS -> CROSS -> FEEDBACK -> OUTPUT.
        await _click(ctx, dut)
        for _ in range(4):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 4
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_OUTPUT_COL_BASE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        for _ in range(8):
            await ctx.tick()
        assert tuple(ctx.get(dut.output_sends[n]) for n in (0, 5, 10, 15)) == \
            (15, 15, 15, 15)
        await _click(ctx, dut)

        # Remaining group columns, then DRY.  Its bulk edit must update both
        # the audio-facing send state and the display-facing values.
        for _ in range(4):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_OUTPUT_DRY_COL
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        for _ in range(8):
            await ctx.tick()
        assert tuple(ctx.get(dut.output_sends[n]) for n in (4, 9, 14, 19)) == \
            (1, 1, 1, 1)
        await _click(ctx, dut)

        # Continue to OUT0's relative row header.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_OUTPUT_ROW_BASE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        for _ in range(10):
            await ctx.tick()
        assert tuple(ctx.get(dut.output_sends[n]) for n in range(5)) == \
            (14, 15, 15, 15, 0)
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_OUTPUT_SIDE_BASE
        assert ctx.get(dut.output_sides[0]) == 0
        await _click(ctx, dut)
        assert ctx.get(dut.output_sides[0]) == 1

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_OUTPUT_BASE
        for _ in range(5):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_OUTPUT_ROW_BASE + 1

    sim.add_testbench(bench)
    sim.run()


def test_ui_advanced_palette_and_cross_curve_selection_wrap():
    """OPTIONS exposes the wrapping palette and cross-feedback curve."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> OPTIONS.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 5
        await _click(ctx, dut)

        # Select PALETTE, edit it, and exercise both ends of the wrap.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_PALETTE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.palette) == 1
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.palette) == 0
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.palette) == 4

        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_SAVE_DEFAULT
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_CURVE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.cross_curve) == RezoCore.CROSS_CURVE_LOG
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.cross_curve) == RezoCore.CROSS_CURVE_LINEAR

    sim.add_testbench(bench)
    sim.run()


def test_ui_bands_navigates_and_edits_all_motion_controls():
    """BANDS exposes every persisted motion control after frequency edits."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 6
        await _click(ctx, dut)

        targets = (
                (dut.TARGET_BAND_LAYOUT,) +
                tuple(dut.TARGET_BAND_ENABLE_BASE + n for n in range(10)) +
                tuple(dut.TARGET_BAND_FREQ_BASE + n for n in range(10)) +
                (
                dut.TARGET_MOTION_SOURCE,
                dut.TARGET_MOTION_RATE,
                dut.TARGET_MOTION_PHASE,
                dut.TARGET_MOTION_DEPTH))
        for target in targets:
            endpoint = await _turn(ctx, dut, endpoint, 1)
            assert ctx.get(dut.selected) == target

        # Edit DEPTH, then walk backward and edit PHASE, RATE, and SOURCE.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.motion_depth) == 33
        await _click(ctx, dut)

        for target in (
                dut.TARGET_MOTION_PHASE,
                dut.TARGET_MOTION_RATE,
                dut.TARGET_MOTION_SOURCE):
            endpoint = await _turn(ctx, dut, endpoint, 0)
            assert ctx.get(dut.selected) == target
            await _click(ctx, dut)
            endpoint = await _turn(ctx, dut, endpoint, 1)
            await _click(ctx, dut)

        assert ctx.get(dut.motion_phase) == 29
        assert ctx.get(dut.motion_rate) == 13
        assert ctx.get(dut.motion_source) == 1

        # RANDOM is sample-and-hold noise, so phase has no continuous-wave
        # meaning. Selecting RANDOM removes PHASE from both navigation
        # directions while retaining RATE and DEPTH.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        assert ctx.get(dut.motion_source) == RezoCore.MOTION_SOURCE_RANDOM
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_MOTION_RATE
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_MOTION_DEPTH
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_MOTION_RATE

    sim.add_testbench(bench)
    sim.run()


def test_ui_input_faders_accelerate_after_precise_first_detent():
    """INPUT gain and depth keep fine first steps but accelerate fast turns."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> BANDS -> INPUT.
        await _click(ctx, dut)
        for _ in range(2):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 2
        await _click(ctx, dut)

        # IN0 is an audio input. Its first detent is the precise 256-unit
        # step; sustained rapid detents ramp through 2x, 3x, and 4x.
        endpoint = await _turn(ctx, dut, endpoint, 1)  # IN0 MODE
        endpoint = await _turn(ctx, dut, endpoint, 1)  # IN0 VALUE
        assert ctx.get(dut.selected) == dut.TARGET_INPUT_BASE + 1
        await _click(ctx, dut)
        start_gain = ctx.get(dut.input_gains[0])
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.input_gains[0]) == start_gain + 256
        endpoint = await _turn(ctx, dut, endpoint, 1)
        for _ in range(8):
            await ctx.tick()
        assert ctx.get(dut.input_gains[0]) == start_gain + 768
        await _click(ctx, dut)

        # Skip IN0 DEPTH and IN1 DEPTH because those inputs are audio, then
        # enter the first CV input's DEPTH control and verify the same curve.
        for _ in range(5):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_INPUT_BASE + 8
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.cv_depths[2]) == 256
        endpoint = await _turn(ctx, dut, endpoint, 1)
        for _ in range(8):
            await ctx.tick()
        assert ctx.get(dut.cv_depths[2]) == 768

    sim.add_testbench(bench)
    sim.run()


def test_ui_cross_layout_presets_and_cell_editing():
    """Factory layouts seed, but never overwrite, persistent USER cells."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> OPTIONS -> CROSS.
        await _click(ctx, dut)
        for _ in range(2):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 7
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_LAYOUT
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        for _ in range(20):
            await ctx.tick()
        assert ctx.get(dut.cross_layout) == RezoCore.CROSS_LAYOUT_DIAGONAL
        # USER defaults to diagonal, but selecting the immutable DIAGONAL
        # view does not rewrite those retained registers.
        assert tuple(ctx.get(dut.cross_matrix[n]) for n in range(16)) == tuple(
            16 if n // 4 == n % 4 else 0 for n in range(16))

        # TO headers, FROM G1, then G1->G1.
        for _ in range(6):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_MATRIX_BASE
        await _click(ctx, dut)
        for _ in range(20):
            await ctx.tick()
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.cross_matrix[0]) == 15
        assert ctx.get(dut.cross_layout) == RezoCore.CROSS_LAYOUT_USER

        # Return to LAYOUT, select ROTATE, then return to USER. The edited USER
        # cell must survive both factory selections.
        await _click(ctx, dut)
        for _ in range(6):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_LAYOUT
        await _click(ctx, dut)
        for _ in range(2):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        for _ in range(20):
            await ctx.tick()
        assert ctx.get(dut.cross_layout) == RezoCore.CROSS_LAYOUT_ROTATE
        assert ctx.get(dut.cross_matrix[0]) == 15

        await _click(ctx, dut)
        for _ in range(3):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        for _ in range(20):
            await ctx.tick()
        assert ctx.get(dut.cross_layout) == RezoCore.CROSS_LAYOUT_USER
        assert ctx.get(dut.cross_matrix[0]) == 15

        # Enter FROM G1 and turn down once: its four cells retain their
        # differences while zero-valued cells clamp at zero.
        for _ in range(6):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_ROW_BASE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert tuple(ctx.get(dut.cross_matrix[n]) for n in range(4)) == \
            (14, 0, 0, 0)

        # TO G1 applies the same relative increment down the first column.
        await _click(ctx, dut)
        for _ in range(4):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_COL_BASE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert tuple(ctx.get(dut.cross_matrix[n]) for n in (0, 4, 8, 12)) == \
            (15, 1, 1, 1)


def test_ui_global_skips_matrix_and_exposes_same_then_cross_controls():
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        await _click(ctx, dut)
        for _ in range(2):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        await _click(ctx, dut)

        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_LAYOUT
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_SAME_FEEDBACK
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.same_feedback) == 127
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_CROSS_FEEDBACK
        await _click(ctx, dut)

        # CROSS uses exactly the same progressive curve as every other
        # continuous fader: rapid detents contribute 1, 2, 3, then 4 steps.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.cross_feedback) == 1
        endpoint = await _turn(ctx, dut, endpoint, 1)
        for _ in range(8):
            await ctx.tick()
        assert ctx.get(dut.cross_feedback) == 3
        endpoint = await _turn(ctx, dut, endpoint, 1)
        for _ in range(8):
            await ctx.tick()
        assert ctx.get(dut.cross_feedback) == 6
        endpoint = await _turn(ctx, dut, endpoint, 1)
        for _ in range(8):
            await ctx.tick()
        assert ctx.get(dut.cross_feedback) == 10
        # Reversing direction immediately restores precise one-step editing.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        for _ in range(8):
            await ctx.tick()
        assert ctx.get(dut.cross_feedback) == 9
        for _ in range(40):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.cross_feedback) == RezoCore.CROSS_DEPTH_MAX

    sim.add_testbench(bench)
    sim.run()


def test_ui_state_scan_preserves_all_compact_v5_parameters():
    """The compact STREZO record restores every live static parameter."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        saved_levels = (1, -2, 3, -4, 5, -28, 7, -8, 9, -10)
        saved_drive = 0x12
        saved_resonance = 0x56
        saved_feedback = 0x37
        saved_knee = 0xAD
        saved_cap = 0x70
        saved_damp = 2
        saved_input_gains = (0x1111, 0x2222, 0x3333, 0xCCCC)
        saved_cv_depth_bytes = (0x80, 0x20, 0xE0, 0x7F)
        saved_input_modes = (0, 1, 2, 2)
        saved_cv_targets = (1, 2, 3, 6)
        saved_group_indices = tuple((n * 3) & 0xF for n in range(10))
        saved_feedback_sends = tuple(n & 1 for n in range(10))
        saved_preset = 5
        saved_palette = 3
        saved_output_sends = tuple((n * 5) % 17 for n in range(20))
        saved_output_sides = (1, 0, 1, 0)
        saved_frequencies = tuple((n << RezoCore.FREQ_FINE_WIDTH) | (n & 3)
                                  for n in range(RezoCore.N_BANDS))
        saved_enables = 0b1011010011
        saved_cross_matrix = tuple((n * 3) % 17 for n in range(16))
        saved_same_reduction = 37
        saved_cross_feedback = 91
        saved_cross_curve = RezoCore.CROSS_CURVE_LOG
        saved_motion_source = 2
        saved_motion_rate = 137
        saved_motion_phase = 91
        saved_motion_depth = 77

        packed = 0
        shift = 0

        def append(value, width):
            nonlocal packed, shift
            packed |= (value & ((1 << width) - 1)) << shift
            shift += width

        for value in saved_levels: append(value, 8)
        for value in (saved_drive, saved_resonance, saved_feedback,
                      saved_knee, saved_cap): append(value, 8)
        append(saved_damp, 3)
        for value in saved_input_gains: append(value, 16)
        for value in saved_cv_depth_bytes: append(value, 8)
        for value in saved_input_modes: append(value, 2)
        for value in saved_cv_targets: append(value, 3)
        for value in saved_group_indices: append(value, 4)
        for value in saved_feedback_sends: append(value, 1)
        append(saved_preset, 3)
        append(saved_palette, 3)
        for value in saved_output_sends: append(value, 5)
        for value in saved_output_sides: append(value, 1)
        for value in saved_frequencies: append(value, RezoCore.FREQ_INDEX_WIDTH)
        for n in range(10): append((saved_enables >> n) & 1, 1)
        append(RezoCore.LAYOUT_USER, 2)
        append(RezoCore.CROSS_LAYOUT_USER, 3)
        for value in saved_cross_matrix: append(value, 5)
        append(saved_same_reduction, 5)
        append(saved_cross_feedback, 5)
        # The former V4 padding now persists CROSS CURVE; old zero padding
        # continues to restore the backward-compatible LINEAR curve.
        append(saved_cross_curve, 1)
        append(0, 1)
        append(saved_motion_source, 2)
        append(saved_motion_rate, 8)
        append(saved_motion_phase, 8)
        append(saved_motion_depth, 8)
        append(saved_same_reduction >> 5, 3)
        append(saved_cross_feedback >> 5, 3)
        assert shift == dut.STATE_WORDS_V5 * 16
        state = [(packed >> (16 * n)) & 0xFFFF
                 for n in range(dut.STATE_WORDS_V5)]

        # LOAD shifts a complete validated record into the circular stream.
        ctx.set(dut.state_shift_load, 1)
        ctx.set(dut.state_shift_enable, 1)
        for value in state:
            ctx.set(dut.state_write_data, value)
            await ctx.tick()
        ctx.set(dut.state_shift_enable, 0)
        ctx.set(dut.state_shift_load, 0)
        await ctx.tick()
        # The working DSP matrix is rebuilt serially from the restored USER
        # record without adding a wide restore mux to the audio path.
        for _ in range(20):
            await ctx.tick()

        # SAVE presents words in order and rotates the entire compact state
        # back to its starting position after exactly STATE_WORDS_V5 cycles.
        captured = []
        ctx.set(dut.state_shift_enable, 1)
        for _ in state:
            captured.append(ctx.get(dut.state_read_data))
            await ctx.tick()
        ctx.set(dut.state_shift_enable, 0)
        await ctx.tick()
        assert captured == state

        assert ctx.get(dut.drive) == saved_drive << 8
        assert ctx.get(dut.levels[5]) == -0x1C00
        assert ctx.get(dut.resonance) == saved_resonance << 8
        assert ctx.get(dut.feedback) == saved_feedback << 8
        assert ctx.get(dut.limit_knee) == saved_knee << 8
        assert ctx.get(dut.limit_cap) == saved_cap << 8
        assert ctx.get(dut.damp_mode) == saved_damp
        assert ctx.get(dut.input_gains[3]) == 0xCCCC
        assert tuple(ctx.get(dut.input_modes[n]) for n in range(4)) == \
            saved_input_modes
        assert tuple(ctx.get(dut.cv_targets[n]) for n in range(4)) == \
            saved_cv_targets
        assert tuple(ctx.get(dut.output_sends[n]) for n in range(20)) == \
            saved_output_sends
        assert tuple(ctx.get(dut.output_sides[n]) for n in range(4)) == \
            saved_output_sides
        assert ctx.get(dut.palette) == saved_palette
        assert ctx.get(dut.preset) == saved_preset
        assert ctx.get(dut.frequency_layout) == RezoCore.LAYOUT_USER
        assert tuple(ctx.get(dut.band_frequencies[n]) for n in range(10)) == \
            saved_frequencies
        assert tuple(ctx.get(dut.band_enables[n]) for n in range(10)) == \
            tuple((saved_enables >> n) & 1 for n in range(10))
        assert ctx.get(dut.cross_layout) == RezoCore.CROSS_LAYOUT_USER
        assert ctx.get(dut.same_feedback) == \
            RezoCore.CROSS_DEPTH_MAX - saved_same_reduction
        assert ctx.get(dut.cross_feedback) == saved_cross_feedback
        assert ctx.get(dut.cross_curve) == saved_cross_curve
        assert tuple(ctx.get(dut.cross_matrix[n]) for n in range(16)) == \
            saved_cross_matrix
        assert ctx.get(dut.motion_source) == saved_motion_source
        assert ctx.get(dut.motion_rate) == saved_motion_rate
        assert ctx.get(dut.motion_phase) == saved_motion_phase
        assert ctx.get(dut.motion_depth) == saved_motion_depth

    sim.add_testbench(bench)
    sim.run()


def test_ui_band_page_layout_toggle_and_transactional_user_edit():
    """BANDS applies layouts, toggles masks, and commits edits into USER."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # PAGE edit: BANK -> BANDS.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.page) == 6
        await _click(ctx, dut)

        # Select LAYOUT, preview PERCEPT, then commit it.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_LAYOUT
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.frequency_layout) == 1  # preview is not live
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == 2
        percept = [RezoCore.frequency_index(f) for f in RezoCore.PERCEPT_FREQS_HZ]
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == percept

        # First enable target toggles immediately and retains its band value.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_ENABLE_BASE
        await _click(ctx, dut)
        assert ctx.get(dut.band_enables[0]) == 0

        # Walk across the enable row to frequency 0. Editing previews without
        # touching DSP state; commit snapshots PERCEPT into USER and changes
        # only the selected center.
        for _ in range(10):
            endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_FREQ_BASE
        old_frequency = ctx.get(dut.band_frequencies[0])
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.band_frequencies[0]) == old_frequency
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == 3
        assert ctx.get(dut.band_frequencies[0]) == old_frequency + 1
        assert [ctx.get(dut.band_frequencies[n]) for n in range(1, 10)] == percept[1:]

        # USER is a working state, not a second recalled preset. Select a
        # factory layout, then select USER again: it snapshots that factory
        # vector rather than recalling the previous manual edit.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        for _ in range(10):
            endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_LAYOUT
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)  # USER wraps to LEGACY
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        legacy = [RezoCore.frequency_index(f) for f in RezoCore.LEGACY_FREQS_HZ]
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == legacy
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)  # LEGACY wraps to USER
        await _click(ctx, dut)
        for _ in range(RezoCore.N_BANDS + 1):
            await ctx.tick()
        assert ctx.get(dut.frequency_layout) == RezoCore.LAYOUT_USER
        assert [ctx.get(dut.band_frequencies[n]) for n in range(10)] == legacy

    sim.add_testbench(bench)
    sim.run()


def test_ui_disabled_bank_controls_do_not_change_stored_values():
    """Muted bands remain configurable on BANDS but are inert on BANK."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00

        # Enter BANDS and disable the first two bands.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)  # layout
        endpoint = await _turn(ctx, dut, endpoint, 1)  # enable 0
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)  # enable 1
        await _click(ctx, dut)
        assert ctx.get(dut.band_enables[0]) == 0
        assert ctx.get(dut.band_enables[1]) == 0

        # Navigate back through BANDS controls to PAGE, then return to BANK.
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.selected) == dut.TARGET_PAGE
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 0
        await _click(ctx, dut)

        # PRESET -> band 0. It may be traversed while navigating, but
        # entering EDIT and turning cannot alter its hidden stored level.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_BAND_BASE
        old_level = ctx.get(dut.levels[0])
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.levels[0]) == old_level

    sim.add_testbench(bench)
    sim.run()


def test_frequency_grid_preserves_factory_centers_and_adds_fine_steps():
    """Every old five-bit index maps to its exact center at fine position zero."""
    assert len(RezoCore.COARSE_FREQUENCIES_HZ) == 29
    assert len(RezoCore.FREQUENCIES_HZ) == 116
    for coarse_index, frequency in enumerate(RezoCore.COARSE_FREQUENCIES_HZ):
        fine_index = coarse_index << RezoCore.FREQ_FINE_WIDTH
        assert RezoCore.FREQUENCIES_HZ[fine_index] == frequency
        assert RezoCore.frequency_index(frequency) == fine_index
    assert all(a <= b for a, b in zip(
        RezoCore.FREQUENCIES_HZ, RezoCore.FREQUENCIES_HZ[1:]))


def test_ui_save_default_click_requests_once():
    """SAVE DEFAULT emits one request from one explicit encoder click."""
    dut = FastClickRezoUI()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        endpoint = 0b00
        ctx.set(dut.save_default_available, 1)

        # PAGE edit: BANK -> OPTIONS.
        await _click(ctx, dut)
        endpoint = await _turn(ctx, dut, endpoint, 0)
        assert ctx.get(dut.page) == 5
        await _click(ctx, dut)

        # Clockwise follows the visual order: PALETTE, then SAVE DEFAULT.
        endpoint = await _turn(ctx, dut, endpoint, 1)
        endpoint = await _turn(ctx, dut, endpoint, 1)
        assert ctx.get(dut.selected) == dut.TARGET_SAVE_DEFAULT
        # Observe the click's one-cycle request pulse.
        saw_request = False
        ctx.set(dut.button, 1)
        for _ in range(5):
            await ctx.tick()
            saw_request |= bool(ctx.get(dut.save_default_request))
        ctx.set(dut.button, 0)
        for _ in range(5):
            await ctx.tick()
            saw_request |= bool(ctx.get(dut.save_default_request))
        assert saw_request
        assert ctx.get(dut.editing) == 0

    sim.add_testbench(bench)
    sim.run()
