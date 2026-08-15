from amaranth.sim import Simulator

from top.rezo.strezo_variant import RezoCore, RezoTileDisplay


def _render_samples(*, h_active=1280, rotate_left=False, points=(), page=0,
                    input_gains=(), input_modes=(), cv_targets=(),
                    band_enables=(), feedback_sends=(), same_feedback=0,
                    cross_feedback=0, cross_layout=RezoCore.CROSS_LAYOUT_GLOBAL,
                    drive=0, resonance=0, feedback=0,
                    matrix_values=(), motion_source=0, motion_rate=12,
                    motion_phase=28, motion_depth=0, motion_monitor=0):
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
        ctx.set(dut.drive, drive)
        ctx.set(dut.effective_drive, drive)
        ctx.set(dut.resonance, resonance)
        ctx.set(dut.effective_resonance, resonance)
        ctx.set(dut.feedback, feedback)
        ctx.set(dut.effective_feedback, feedback)
        ctx.set(dut.motion_source, motion_source)
        ctx.set(dut.motion_rate, motion_rate)
        ctx.set(dut.motion_phase, motion_phase)
        ctx.set(dut.motion_depth, motion_depth)
        ctx.set(dut.motion_monitor, motion_monitor)
        for index, value in enumerate(matrix_values):
            ctx.set(dut.output_send_write_addr, index)
            ctx.set(dut.output_send_write_data, value)
            ctx.set(dut.output_send_write_en, 1)
            await ctx.tick("sync")
        ctx.set(dut.output_send_write_en, 0)
        ctx.set(dut.de, 1)
        for _ in range(320):
            await ctx.tick("dvi")
        for panel_x, panel_y in points:
            if rotate_left:
                physical_x = 719 - panel_y
                physical_y = panel_x
            else:
                physical_x = dut.x_offset + panel_x
                physical_y = panel_y
            ctx.set(dut.x, physical_x)
            ctx.set(dut.y, physical_y)
            for _ in range(12):
                await ctx.tick("dvi")
            samples.append((ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)))

    sim.add_testbench(bench)
    sim.run()
    return samples


def test_native_canvas_uses_the_508_pixel_safe_square():
    points = ((106, 106), (613, 613), (105, 300), (614, 300))
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
    pixels = _render_samples(
        page=2,
        input_gains=(255,),
        input_modes=(RezoCore.INPUT_MODE_LEFT,),
        points=((557, 257), (574, 257)),
    )
    assert pixels == [
        (control, control, control),
        (panel, panel, panel),
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
        points=((231, 550), (232, 550), (235, 550), (236, 550),
                (571, 550), (572, 550), (579, 550), (580, 550),
                (236, 582), (571, 582), (572, 582)),
    ) == [
        (background, background, background), (panel, panel, panel),
        (panel, panel, panel), (control, control, control),
        (control, control, control), (panel, panel, panel),
        (panel, panel, panel), (background, background, background),
        (control, control, control), (control, control, control),
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
        points=((592, 456), (593, 456),
                (592, 488), (593, 488),
                (592, 520), (593, 520)),
    ) == [
        (control, control, control), (line, line, line),
        (control, control, control), (line, line, line),
        (control, control, control), (line, line, line),
    ]


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
        (background, background, background), (blank, blank, blank),
    ]


def test_bands_motion_controls_form_one_complete_vertical_column():
    control = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=6,
        motion_depth=32,
        points=((280, 470), (423, 470), (424, 470),
                (280, 502), (359, 502), (360, 502),
                (280, 534), (359, 534), (360, 534),
                (280, 566), (351, 566), (352, 566), (567, 566),
                (568, 566), (448, 470), (448, 534)),
    ) == [
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (control, control, control), (control, control, control),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (background, background, background),
        (background, background, background),
    ]


def test_bands_motion_text_chips_share_centered_twenty_pixel_rows():
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=6,
        points=((300, 459), (300, 460), (300, 479), (300, 480),
                (300, 491), (300, 492), (300, 511), (300, 512),
                (300, 523), (300, 524), (300, 543), (300, 544)),
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
        points=((423, 571), (424, 571), (567, 571), (568, 571)),
    ) == [
        (panel, panel, panel), (mod, mod, mod),
        (mod, mod, mod), (background, background, background),
    ]
    assert _render_samples(
        page=6,
        motion_monitor=-16,
        points=((279, 571), (280, 571), (423, 571), (424, 571)),
    ) == [
        (background, background, background), (mod, mod, mod),
        (mod, mod, mod), (panel, panel, panel),
    ]
