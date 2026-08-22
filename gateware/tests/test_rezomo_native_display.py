from amaranth.sim import Simulator

from rezo_display_support import sample_native_rgb
from top.rezo.top import RezoCore, RezoHardwareUI, RezoTileDisplay


def _render_samples(*, h_active=1280, rotate_left=False, points=(), page=0,
                    preset=0, clock_mode=0,
                    clock_algorithm=RezoCore.CLOCK_ALGORITHM_SHIFT,
                    shift_direction=RezoCore.SHIFT_FORWARD,
                    walk_style=RezoCore.WALK_STYLE_ALL, walk_drunk=0,
                    walk_chance_index=RezoCore.WALK_CHANCE_DEFAULT,
                    turing_length=10, turing_change_index=3,
                    clock_source=RezoCore.CLOCK_SOURCE_AUTO,
                    data_source=RezoCore.DATA_SOURCE_CV,
                    internal_clock_rate=RezoCore.INTERNAL_CLOCK_DEFAULT,
                    data_random_active=0,
                    clock_depth=128,
                    turing_target=RezoCore.TURING_TARGET_ALL,
                    turing_start=0,
                    band_enables=(), feedback_sends=(), input_gains=(),
                    input_modes=(), cv_targets=(), selected=0):
    """Render settled pixels from the native REZOMO coordinate space."""
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
        ctx.set(dut.preset, preset)
        ctx.set(dut.clock_mode, clock_mode)
        ctx.set(dut.clock_algorithm, clock_algorithm)
        ctx.set(dut.shift_direction, shift_direction)
        ctx.set(dut.walk_style, walk_style)
        ctx.set(dut.walk_drunk, walk_drunk)
        ctx.set(dut.walk_chance_index, walk_chance_index)
        ctx.set(dut.turing_length, turing_length)
        ctx.set(dut.turing_change_index, turing_change_index)
        ctx.set(dut.clock_source, clock_source)
        ctx.set(dut.data_source, data_source)
        ctx.set(dut.internal_clock_rate, internal_clock_rate)
        ctx.set(dut.data_random_active, data_random_active)
        ctx.set(dut.clock_depth, clock_depth)
        ctx.set(dut.turing_target, turing_target)
        ctx.set(dut.turing_start, turing_start)
        ctx.set(dut.selected, selected)
        for index, value in enumerate(band_enables):
            ctx.set(dut.band_enables[index], value)
        for index, value in enumerate(feedback_sends):
            ctx.set(dut.feedback_sends[index], value)
        for index, value in enumerate(input_gains):
            ctx.set(dut.input_gains[index], value)
        for index, value in enumerate(input_modes):
            ctx.set(dut.input_modes[index], value)
        for index, value in enumerate(cv_targets):
            ctx.set(dut.cv_targets[index], value)
        ctx.set(dut.de, 1)
        # Dynamic labels refresh through the sync-domain tile writer. Let one
        # complete 185-entry pass settle before inspecting their glyph pixels.
        for _ in range(600):
            await ctx.tick("dvi")
        samples.extend(await sample_native_rgb(
            ctx, dut, points, rotate_left=rotate_left))

    sim.add_testbench(bench)
    sim.run()
    return samples


def _render_text_bounds(*regions, **values):
    """Return the visible text-glyph bounds inside each chip rectangle."""
    points = tuple(
        (x, y)
        for x0, y0, x1, y1 in regions
        for y in range(y0, y1)
        for x in range(x0, x1)
    )
    pixels = _render_samples(points=points, **values)
    text = RezoTileDisplay.PALETTE["text"]
    result = []
    point_index = 0
    for x0, y0, x1, y1 in regions:
        region_points = []
        for y in range(y0, y1):
            for x in range(x0, x1):
                if pixels[point_index] == (text, text, text):
                    region_points.append((x, y))
                point_index += 1
        assert region_points
        result.append((
            min(x for x, _ in region_points),
            min(y for _, y in region_points),
            max(x for x, _ in region_points) + 1,
            max(y for _, y in region_points) + 1,
        ))
    return result


def test_native_canvas_is_centered_without_scaling_on_standard_video():
    points = ((106, 106), (613, 613), (105, 300), (614, 300))
    pixels = _render_samples(points=points)
    line = RezoTileDisplay.PALETTE["line"]
    blank = RezoTileDisplay.PALETTE["blank"]

    assert pixels == [
        (line, line, line),
        (line, line, line),
        (blank, blank, blank),
        (blank, blank, blank),
    ]


def test_interactive_content_stays_inside_the_508_pixel_safe_square():
    # The identity is intentionally allowed in the circular top arc. These
    # samples instead guard the four sides around the interactive content.
    points = ((100, 300), (620, 300), (300, 100), (300, 620))
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(points=points, page=7) == [
        (blank, blank, blank),
    ] * len(points)


def test_clock_editor_uses_native_stacked_control_rows():
    points = (
        (310, 260),  # algorithm value padding
        (310, 292),  # direction value padding
        (310, 328),  # source value padding
        (310, 356),  # BPM value padding
        (320, 388),  # depth fill
        (310, 420),  # algorithm-specific row padding
        (310, 484),  # third algorithm-specific row padding
        (310, 516),  # fourth algorithm-specific row padding
    )
    panel = RezoTileDisplay.PALETTE["panel"]
    control = RezoTileDisplay.PALETTE["control"]
    assert _render_samples(
        points=points,
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_TURING,
        turing_target=RezoCore.TURING_TARGET_RANGE,
    ) == [
        (panel, panel, panel),
        (panel, panel, panel),
        (panel, panel, panel),
        (panel, panel, panel),
        (control, control, control),
        (panel, panel, panel),
        (panel, panel, panel),
        (panel, panel, panel),
    ]


def test_clock_editor_value_chips_and_depth_end_at_their_content_widths():
    panel = RezoTileDisplay.PALETTE["panel"]
    control = RezoTileDisplay.PALETTE["control"]
    background = RezoTileDisplay.PALETTE["background"]
    pixels = _render_samples(
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_TURING,
        turing_target=RezoCore.TURING_TARGET_RANGE,
        clock_depth=128,
        points=(
            (431, 260), (432, 260),  # six-character algorithm field
            (479, 292), (480, 292),  # nine-character direction field
            (383, 356), (384, 356),  # three-character BPM field
            # DEPTH reaches its maximum while retaining the shared two-pixel
            # inset at the right edge of the chip.
            (585, 388), (586, 388), (587, 388), (588, 388),
            (369, 420), (370, 420),  # three-character CHANGE field
            (409, 452), (410, 452),  # five-character BANDS field
            (353, 516), (354, 516),  # two-character LENGTH field
        ),
    )
    assert pixels == [
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (control, control, control),
        (panel, panel, panel), (panel, panel, panel),
        (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
    ]


def test_clock_walk_and_shift_chips_use_their_own_semantic_widths():
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_WALK,
        points=(
            (385, 420), (386, 420),  # STYLE: four characters
            (345, 452), (346, 452),  # DRUNK: one character
            (369, 484), (370, 484),  # CHANCE: three characters
        ),
    ) == [
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
    ]
    assert _render_samples(
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_SHIFT,
        points=((465, 420), (466, 420)),  # DATA: AUTO RAND is longest
    ) == [
        (panel, panel, panel), (background, background, background),
    ]


def test_bank_mode_value_has_the_same_bright_chip_as_other_values():
    panel = RezoTileDisplay.PALETTE["panel"]
    assert _render_samples(page=0, points=((500, 200),)) == [
        (panel, panel, panel),
    ]


def test_bank_value_chips_keep_fixed_geometry_across_labels():
    panel = RezoTileDisplay.PALETTE["panel"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=0,
        points=((327, 200), (328, 200), (563, 200), (564, 200)),
    ) == [
        (panel, panel, panel), (blank, blank, blank),
        (panel, panel, panel), (blank, blank, blank),
    ]
    assert _render_samples(
        page=0,
        preset=6,
        clock_mode=1,
        points=((327, 200), (328, 200), (563, 200), (564, 200)),
    ) == [
        (panel, panel, panel), (blank, blank, blank),
        (panel, panel, panel), (blank, blank, blank),
    ]


def test_even_preset_uses_all_four_visible_glyphs():
    bounds, = _render_text_bounds(
        (236, 180, 332, 218), page=0, preset=2)
    assert bounds == (256, 192, 314, 206)


def test_feedback_navigation_outlines_share_the_native_track_edges():
    selected = RezoTileDisplay.PALETTE["selected"]
    background = RezoTileDisplay.PALETTE["background"]
    for target, y in (
        (RezoHardwareUI.TARGET_FEEDBACK, 344),
        (RezoHardwareUI.TARGET_LIMIT_KNEE, 424),
        (RezoHardwareUI.TARGET_LIMIT_CAP, 456),
    ):
        assert _render_samples(
            page=1, selected=target, points=((267, y), (268, y), (269, y)),
        ) == [
            (background, background, background),
            (selected, selected, selected),
            (selected, selected, selected),
        ]


def test_input_text_chips_use_fixed_widths_and_shared_row_centres():
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(
        page=2,
        input_modes=(RezoCore.INPUT_MODE_AUDIO, RezoCore.INPUT_MODE_CV),
        cv_targets=(0, RezoCore.CV_TARGET_RESONANCE),
        points=(
            (400, 230), (401, 230),  # AUDIO mode width
            (400, 326), (401, 326),  # MODE is sized for AUDIO, its max value
            (368, 358), (369, 358),  # three-character VALUE field width
            (320, 240), (320, 241),  # MODE chip bottom edge
        ),
    ) == [
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
    ]


def test_bank_and_input_value_glyphs_use_fixed_left_origins():
    bank_chip = (464, 184, 564, 216)
    for clock_mode in (0, 1):
        bounds, = _render_text_bounds(
            bank_chip, page=0, clock_mode=clock_mode)
        assert 480 <= bounds[0] <= 482
        assert bounds[2] <= bank_chip[2]

    input_mode_chip = (304, 221, 402, 241)
    input_value_chip = (304, 253, 370, 273)
    audio_bounds, = _render_text_bounds(
        input_mode_chip,
        page=2,
        input_modes=(RezoCore.INPUT_MODE_AUDIO,) * 4,
    )
    assert 320 <= audio_bounds[0] <= 322
    assert audio_bounds[2] <= input_mode_chip[2]
    cv_bounds, fb_bounds = _render_text_bounds(
        input_mode_chip, input_value_chip,
        page=2,
        input_modes=(RezoCore.INPUT_MODE_CV,) * 4,
        cv_targets=(RezoCore.CV_TARGET_FEEDBACK,) * 4,
    )
    assert 320 <= cv_bounds[0] <= 322
    assert cv_bounds[2] <= input_mode_chip[2]
    assert 320 <= fb_bounds[0] <= 322
    assert fb_bounds[2] <= input_value_chip[2]


def test_clock_mode_specific_value_glyphs_use_fixed_left_origins():
    turing_chips = ((304, 412, 370, 434), (304, 476, 354, 498))
    turing_bounds = _render_text_bounds(
        *turing_chips,
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_TURING,
        turing_change_index=3,
        turing_length=10,
    )
    for bounds, chip in zip(turing_bounds, turing_chips):
        assert 320 <= bounds[0] <= 322
        assert bounds[2] <= chip[2]

    walk_chips = (
        (304, 412, 386, 434),
        (304, 444, 346, 466),
        (304, 476, 370, 498),
    )
    walk_bounds = _render_text_bounds(
        *walk_chips,
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_WALK,
        walk_style=RezoCore.WALK_STYLE_ALL,
        walk_drunk=0,
        walk_chance_index=2,
    )
    for bounds, chip in zip(walk_bounds, walk_chips):
        assert 320 <= bounds[0] <= 322
        assert bounds[2] <= chip[2]

    data_chip = (304, 412, 466, 434)
    data_bounds, = _render_text_bounds(
        data_chip,
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_SHIFT,
        data_source=RezoCore.DATA_SOURCE_CV,
    )
    assert 320 <= data_bounds[0] <= 322
    assert data_bounds[2] <= data_chip[2]


def test_round_rotation_preserves_native_pixels_without_scaling():
    points = (
        (106, 106),
        (120, 130),
        (140, 260),
        (320, 424),
        (613, 613),
    )
    preview = _render_samples(points=points, page=7)
    circular = _render_samples(
        h_active=720,
        rotate_left=True,
        points=points,
        page=7,
    )
    assert circular == preview


def test_bands_enable_buttons_reuse_feedback_button_geometry():
    points = (
        (140, 283),  # top edge
        (140, 290),  # body
        (140, 316),  # bottom edge
        (140, 317),  # immediately below
    )
    kwargs = dict(
        points=points,
        band_enables=(1,),
        feedback_sends=(1,),
    )
    assert _render_samples(page=6, **kwargs) == _render_samples(page=1, **kwargs)


def test_input_audio_value_fill_stays_inside_its_panel():
    accent = RezoTileDisplay.PALETTE["control"]
    panel = RezoTileDisplay.PALETTE["panel"]
    background = RezoTileDisplay.PALETTE["background"]
    pixels = _render_samples(
        page=2,
        input_gains=(255,),
        points=((572, 260), (573, 260), (574, 260), (575, 260)),
    )
    assert pixels[0] == (accent, accent, accent)
    assert pixels[1:3] == [(panel, panel, panel)] * 2
    assert pixels[3] == (background, background, background)


def test_output_row_selector_uses_native_safe_square_coordinates():
    selected = RezoTileDisplay.PALETTE["selected"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=4,
        selected=RezoHardwareUI.TARGET_OUTPUT_ROW_BASE,
        points=((26, 342), (116, 342)),
    ) == [
        (blank, blank, blank),
        (selected, selected, selected),
    ]


def test_output_send_scaling_preserves_exact_fill_endpoint():
    """A send of eight fills 24 pixels after the four-pixel inset."""
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False, compact_layout=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, 342)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 4)
        ctx.set(dut.output_send_write_addr, 0)
        ctx.set(dut.output_send_write_data, 8)
        ctx.set(dut.output_send_write_en, 1)
        await ctx.tick("sync")
        ctx.set(dut.output_send_write_en, 0)
        await sample(ctx, 270)
        await sample(ctx, 271)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [palette["control"], palette["background"]]
