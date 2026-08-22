from amaranth.sim import Simulator

from rezo_display_support import sample_native_rgb
from top.rezo.strezo_variant import (
    NATIVE_MOTION_CONTROL_X0,
    NATIVE_MOTION_CONTROL_X1,
    NATIVE_OUTPUT_SIDE_CHIP_X0,
    NATIVE_OUTPUT_SIDE_CHIP_X1,
    RezoCore,
    RezoHardwareUI,
    RezoTileDisplay,
)
from top.rezo.ui_common import (
    NATIVE_FEEDBACK_CEILING_Y0,
    NATIVE_FEEDBACK_KNEE_Y0,
)


def _render_samples(*, h_active=1280, rotate_left=False, points=(), page=0,
                    input_gains=(), input_modes=(), cv_targets=(),
                    band_enables=(), feedback_sends=(), same_feedback=0,
                    cross_feedback=0, cross_layout=RezoCore.CROSS_LAYOUT_GLOBAL,
                    cross_curve=RezoCore.CROSS_CURVE_LINEAR,
                    drive=0, resonance=0, feedback=0,
                    limit_knee=32, limit_cap=112, selected=0,
                    matrix_values=(), motion_source=0, motion_rate=12,
                    motion_phase=28, motion_depth=0, motion_monitor=0,
                    output_sides=()):
    """Render settled pixels from STREZO's upright native canvas."""
    dut = RezoTileDisplay(
        h_active=h_active,
        rotate_left=rotate_left,
        compact_layout=True,
    )
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, page)
        for index, value in enumerate(input_gains):
            ctx.set(dut.input_gains[index], value)
        for index, value in enumerate(input_modes):
            ctx.set(dut.input_modes[index], value)
        for index, value in enumerate(cv_targets):
            ctx.set(dut.cv_targets[index], value)
        for index, value in enumerate(band_enables):
            ctx.set(dut.band_enables[index], value)
        for index, value in enumerate(feedback_sends):
            ctx.set(dut.feedback_sends[index], value)
        ctx.set(dut.same_feedback, same_feedback)
        ctx.set(dut.cross_feedback, cross_feedback)
        ctx.set(dut.cross_layout, cross_layout)
        ctx.set(dut.cross_curve, cross_curve)
        ctx.set(dut.drive, drive)
        ctx.set(dut.effective_drive, drive)
        ctx.set(dut.resonance, resonance)
        ctx.set(dut.effective_resonance, resonance)
        ctx.set(dut.feedback, feedback)
        ctx.set(dut.effective_feedback, feedback)
        ctx.set(dut.limit_knee, limit_knee)
        ctx.set(dut.limit_cap, limit_cap)
        ctx.set(dut.selected, selected)
        ctx.set(dut.motion_source, motion_source)
        ctx.set(dut.motion_rate, motion_rate)
        ctx.set(dut.motion_phase, motion_phase)
        ctx.set(dut.motion_depth, motion_depth)
        ctx.set(dut.motion_monitor, motion_monitor)
        for index, value in enumerate(output_sides):
            ctx.set(dut.output_sides[index], value)
        for index, value in enumerate(matrix_values):
            ctx.set(dut.output_send_write_addr, index)
            ctx.set(dut.output_send_write_data, value)
            ctx.set(dut.output_send_write_en, 1)
            await ctx.tick("sync")
        ctx.set(dut.output_send_write_en, 0)
        ctx.set(dut.de, 1)
        for _ in range(320):
            await ctx.tick("dvi")
        samples.extend(await sample_native_rgb(
            ctx, dut, points, rotate_left=rotate_left))

    sim.add_testbench(bench)
    sim.run()
    return samples


def _render_text_bounds(region, **values):
    x0, y0, x1, y1 = region
    points = tuple((x, y) for y in range(y0, y1) for x in range(x0, x1))
    pixels = _render_samples(points=points, **values)
    text = RezoTileDisplay.PALETTE["text"]
    lit = [point for point, rgb in zip(points, pixels)
           if rgb == (text, text, text)]
    assert lit
    return (min(x for x, _ in lit), min(y for _, y in lit),
            max(x for x, _ in lit) + 1, max(y for _, y in lit) + 1)


def test_native_canvas_shows_the_round_panel_edge():
    points = ((0, 359), (719, 360), (106, 300), (613, 300))
    line = RezoTileDisplay.PALETTE["line"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(points=points) == [
        (line, line, line),
        (line, line, line),
        (blank, blank, blank),
        (blank, blank, blank),
    ]


def test_every_interactive_page_is_blank_beyond_the_safe_square():
    points = ((100, 300), (620, 300), (300, 100), (300, 620))
    blank = RezoTileDisplay.PALETTE["blank"]
    for page in range(8):
        assert _render_samples(points=points, page=page) == [
            (blank, blank, blank),
        ] * len(points)


def test_standard_and_circular_targets_render_identical_native_pixels():
    points = (
        (106, 106), (120, 130), (140, 283),
        (320, 424), (560, 544), (613, 613),
    )
    preview = _render_samples(points=points, page=6, band_enables=(1,))
    circular = _render_samples(
        h_active=720,
        rotate_left=True,
        points=points,
        page=6,
        band_enables=(1,),
    )
    assert circular == preview


def test_input_audio_fill_remains_inside_its_native_value_lane():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    pixels = _render_samples(
        page=2,
        input_gains=(255,),
        input_modes=(RezoCore.INPUT_MODE_LEFT,),
        points=((572, 257), (573, 257), (574, 257), (575, 257)),
    )
    assert pixels == [
        (control, control, control),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
    ]


def test_input_panel_contains_the_last_native_control_row():
    background = RezoTileDisplay.PALETTE["background"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=2,
        points=((130, 598), (130, 599)),
    ) == [
        (background, background, background),
        (blank, blank, blank),
    ]


def test_cross_matrix_is_raised_and_spread_across_the_panel():
    text = RezoTileDisplay.PALETTE["text"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=7,
        points=((227, 313), (522, 313), (227, 532), (522, 532),
                (300, 219), (300, 533), (300, 541), (300, 542),
                (146, 528), (146, 544), (130, 560), (130, 576)),
    ) == [
        (panel, panel, panel), (panel, panel, panel),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (background, background, background),
        (background, background, background), (panel, panel, panel),
        (background, background, background), (text, text, text),
        (background, background, background), (text, text, text),
    ]


def test_cross_layout_chip_has_symmetric_horizontal_padding():
    panel = RezoTileDisplay.PALETTE["panel"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=7,
        cross_layout=RezoCore.CROSS_LAYOUT_DIAGONAL,
        points=((239, 184), (240, 184), (255, 184),
                (384, 184), (391, 184), (392, 184)),
    ) == [
        (blank, blank, blank),
        (panel, panel, panel), (panel, panel, panel),
        (panel, panel, panel), (panel, panel, panel),
        (blank, blank, blank),
    ]


def test_cross_curve_text_has_the_shared_one_cell_left_inset():
    chip = (336, 484, 488, 524)
    bounds = _render_text_bounds(
        chip, page=5, cross_curve=RezoCore.CROSS_CURVE_LINEAR)
    assert 352 <= bounds[0] <= 354
    assert bounds[0] - chip[0] in (16, 17, 18)


def test_main_preset_selection_uses_the_shared_header_outline():
    selected = RezoTileDisplay.PALETTE["selected"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=0,
        selected=RezoHardwareUI.TARGET_PRESET,
        points=((250, 164), (250, 180)),
    ) == [
        (blank, blank, blank),
        (selected, selected, selected),
    ]


def test_cross_matrix_maximum_fill_matches_the_centered_cell_lane():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=7,
        cross_layout=RezoCore.CROSS_LAYOUT_USER,
        matrix_values=(16,),
        points=((226, 320), (227, 320), (230, 320), (231, 320),
                (278, 320), (279, 320), (282, 320), (283, 320)),
    ) == [
        (background, background, background),
        (panel, panel, panel), (background, background, background),
        (control, control, control), (control, control, control),
        (background, background, background), (panel, panel, panel),
        (background, background, background),
    ]


def test_cross_feedback_tracks_use_nearly_the_full_chip_width():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=7,
        same_feedback=128,
        cross_feedback=RezoCore.CROSS_DEPTH_MAX,
        points=((231, 550), (232, 550), (233, 550), (234, 550),
                (577, 550), (578, 550), (579, 550), (580, 550),
                (577, 582), (578, 582), (579, 582)),
    ) == [
        (background, background, background), (panel, panel, panel),
        (panel, panel, panel), (control, control, control),
        (control, control, control), (panel, panel, panel),
        (panel, panel, panel), (background, background, background),
        (control, control, control), (panel, panel, panel),
        (panel, panel, panel),
    ]


def test_bank_control_maxima_fill_the_compact_tracks():
    control = RezoTileDisplay.PALETTE["control"]
    line = RezoTileDisplay.PALETTE["line"]
    assert _render_samples(
        page=0,
        drive=128,
        resonance=128,
        feedback=128,
        points=((591, 456), (592, 456), (593, 456),
                (591, 488), (592, 488), (593, 488),
                (591, 520), (592, 520), (593, 520)),
    ) == [
        (control, control, control), (line, line, line), (line, line, line),
        (control, control, control), (line, line, line), (line, line, line),
        (control, control, control), (line, line, line), (line, line, line),
    ]


def test_feedback_safety_maxima_fill_the_compact_tracks():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=1,
        limit_knee=128,
        limit_cap=128,
        points=((576, NATIVE_FEEDBACK_KNEE_Y0 + 8),
                (577, NATIVE_FEEDBACK_KNEE_Y0 + 8),
                (578, NATIVE_FEEDBACK_KNEE_Y0 + 8),
                (579, NATIVE_FEEDBACK_KNEE_Y0 + 8),
                (576, NATIVE_FEEDBACK_CEILING_Y0 + 8),
                (577, NATIVE_FEEDBACK_CEILING_Y0 + 8),
                (578, NATIVE_FEEDBACK_CEILING_Y0 + 8),
                (579, NATIVE_FEEDBACK_CEILING_Y0 + 8)),
    ) == [
        (control, control, control), (panel, panel, panel),
        (panel, panel, panel), (background, background, background),
        (control, control, control), (panel, panel, panel),
        (panel, panel, panel), (background, background, background),
    ]


def test_feedback_amount_maximum_fills_the_compact_track():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=1,
        feedback=128,
        points=((576, 344), (577, 344), (578, 344), (579, 344)),
    ) == [
        (control, control, control),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
    ]


def test_output_dry_header_has_the_same_visible_selection_bar_as_groups():
    selected = RezoTileDisplay.PALETTE["selected"]
    assert _render_samples(
        page=4,
        selected=RezoHardwareUI.TARGET_OUTPUT_DRY_COL,
        points=((538, 281),),
    ) == [(selected, selected, selected)]


def test_output_side_chip_clears_row_label_and_keeps_right_edge():
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    label_bounds = _render_text_bounds(
        (120, 336, NATIVE_OUTPUT_SIDE_CHIP_X0, 352), page=4)
    side_bounds = _render_text_bounds(
        (NATIVE_OUTPUT_SIDE_CHIP_X0, 336,
         NATIVE_OUTPUT_SIDE_CHIP_X1, 352),
        page=4, output_sides=(0,))
    # OUT0 has a measured gutter before the narrowed chip, and the L glyph
    # remains wholly inside the fixed right edge.
    assert NATIVE_OUTPUT_SIDE_CHIP_X0 - label_bounds[2] >= 8
    assert side_bounds[0] >= NATIVE_OUTPUT_SIDE_CHIP_X0
    assert side_bounds[2] <= NATIVE_OUTPUT_SIDE_CHIP_X1
    assert _render_samples(
        page=4,
        points=((NATIVE_OUTPUT_SIDE_CHIP_X0 - 1, 342),
                (NATIVE_OUTPUT_SIDE_CHIP_X0, 342),
                (NATIVE_OUTPUT_SIDE_CHIP_X1 - 1, 342),
                (NATIVE_OUTPUT_SIDE_CHIP_X1, 342)),
    ) == [
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
    ]


def test_output_side_value_has_balanced_padding_in_narrow_chip():
    bounds = _render_text_bounds(
        (NATIVE_OUTPUT_SIDE_CHIP_X0, 336,
         NATIVE_OUTPUT_SIDE_CHIP_X1, 352),
        page=4, output_sides=(0,))
    left = bounds[0] - NATIVE_OUTPUT_SIDE_CHIP_X0
    right = NATIVE_OUTPUT_SIDE_CHIP_X1 - bounds[2]
    assert left >= 8
    assert right >= 8
    assert abs(left - right) <= 8


def test_cross_lower_rows_have_balanced_clear_bands():
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=7,
        points=((300, 533), (300, 541), (300, 542), (300, 561),
                (300, 562), (300, 573), (300, 574), (300, 593),
                (300, 594), (300, 602), (300, 603)),
    ) == [
        (background, background, background),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (blank, blank, blank), (blank, blank, blank),
    ]


def test_bands_motion_controls_form_one_complete_vertical_column():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=6,
        motion_depth=32,
        points=((288, 470), (439, 470), (440, 470),
                (288, 502), (375, 502), (376, 502),
                (288, 534), (375, 534), (376, 534),
                (287, 566), (288, 566), (289, 566), (290, 566),
                (360, 566), (361, 566), (575, 566), (576, 566),
                (448, 470), (448, 534)),
    ) == [
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (background, background, background), (panel, panel, panel),
        (panel, panel, panel), (control, control, control),
        (control, control, control), (panel, panel, panel),
        (panel, panel, panel), (background, background, background),
        (background, background, background),
        (background, background, background),
    ]


def test_bands_motion_labels_share_a_right_edge_and_value_gutter():
    for row, control_y0, control_y1, padding in (
        (29, 462, 480, 2),
        (31, 494, 512, 2),
        (33, 526, 544, 2),
        (35, 557, 577, 3),
    ):
        bounds = _render_text_bounds(
            (125, row * 16, NATIVE_MOTION_CONTROL_X0, (row + 1) * 16),
            page=6)
        assert bounds[0] >= 125
        assert bounds[2] == 266
        assert bounds[1] - control_y0 == padding
        assert control_y1 - bounds[3] == padding
    assert NATIVE_MOTION_CONTROL_X0 - 17 * 16 == 16
    assert NATIVE_MOTION_CONTROL_X1 <= 594


def test_bands_motion_text_chips_share_vertically_centered_rows():
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=6,
        points=((300, 461), (300, 462), (300, 479), (300, 480),
                (300, 493), (300, 494), (300, 511), (300, 512),
                (300, 525), (300, 526), (300, 543), (300, 544)),
    ) == [
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
    ]


def test_bands_random_motion_retains_the_blank_phase_value_field():
    panel = RezoTileDisplay.PALETTE["panel"]
    assert _render_samples(
        page=6,
        motion_source=RezoCore.MOTION_SOURCE_RANDOM,
        points=((300, 470), (300, 502), (300, 534)),
    ) == [
        (panel, panel, panel), (panel, panel, panel),
        (panel, panel, panel),
    ]


def test_bands_motion_monitor_is_a_centered_bipolar_line():
    background = RezoTileDisplay.PALETTE["background"]
    mod = RezoTileDisplay.PALETTE["modulation"]
    panel = RezoTileDisplay.PALETTE["panel"]
    assert _render_samples(
        page=6,
        motion_monitor=16,
        points=((431, 576), (432, 576), (575, 576), (576, 576)),
    ) == [
        (panel, panel, panel), (mod, mod, mod),
        (panel, panel, panel), (background, background, background),
    ]
    assert _render_samples(
        page=6,
        motion_monitor=-16,
        points=((287, 576), (288, 576), (431, 576), (432, 576)),
    ) == [
        (background, background, background), (panel, panel, panel),
        (mod, mod, mod), (panel, panel, panel),
    ]
