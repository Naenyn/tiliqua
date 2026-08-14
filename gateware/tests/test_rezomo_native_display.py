from amaranth.sim import Simulator

from top.rezo.top import RezoCore, RezoTileDisplay


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
                    input_modes=(), cv_targets=()):
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
        for panel_x, panel_y in points:
            if rotate_left:
                # ui_x = physical_y; ui_y = 719 - physical_x.
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


def _assert_optically_centered(glyph_bounds, chip_bounds):
    glyph_x0, glyph_y0, glyph_x1, glyph_y1 = glyph_bounds
    chip_x0, chip_y0, chip_x1, chip_y1 = chip_bounds
    # Compare doubled centers so half-pixel centers remain exact. The cell
    # renderer cannot represent a half-character origin. Chips split the two
    # possible parity positions, keeping either case within five native pixels
    # of center without adding a live pixel-coordinate mux.
    assert abs((glyph_x0 + glyph_x1 - 1) -
               (chip_x0 + chip_x1 - 1)) <= 10
    assert (glyph_y0 + glyph_y1 - 1) == (chip_y0 + chip_y1 - 1)


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
            (587, 388), (588, 388),  # DEPTH rail reaches the right inset
            (369, 420), (370, 420),  # three-character CHANGE field
            (409, 452), (410, 452),  # five-character BANDS field
            (353, 516), (354, 516),  # two-character LENGTH field
        ),
    )
    assert pixels == [
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
        (panel, panel, panel), (background, background, background),
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
    assert _render_samples(page=0, points=((500, 180),)) == [
        (panel, panel, panel),
    ]


def test_bank_value_chips_use_parity_balanced_centered_fields():
    panel = RezoTileDisplay.PALETTE["panel"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=0,
        points=((351, 180), (352, 180), (563, 180), (564, 180)),
    ) == [
        (panel, panel, panel), (blank, blank, blank),
        (panel, panel, panel), (blank, blank, blank),
    ]
    assert _render_samples(
        page=0,
        preset=6,
        clock_mode=1,
        points=((351, 180), (352, 180), (563, 180), (564, 180)),
    ) == [
        (panel, panel, panel), (blank, blank, blank),
        (panel, panel, panel), (blank, blank, blank),
    ]


def test_even_preset_uses_all_four_visible_glyphs():
    bounds, = _render_text_bounds(
        (252, 164, 352, 200), page=0, preset=2)
    assert bounds == (272, 176, 330, 190)


def test_input_text_chips_use_centered_content_widths_and_shared_row_centres():
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


def test_bank_and_input_value_glyphs_are_optically_centered():
    bank_chip = (464, 167, 564, 199)
    for clock_mode in (0, 1):
        bounds, = _render_text_bounds(
            bank_chip, page=0, clock_mode=clock_mode)
        _assert_optically_centered(bounds, bank_chip)

    input_mode_chip = (304, 221, 402, 241)
    input_value_chip = (304, 253, 370, 273)
    audio_bounds, = _render_text_bounds(
        input_mode_chip,
        page=2,
        input_modes=(RezoCore.INPUT_MODE_AUDIO,) * 4,
    )
    _assert_optically_centered(audio_bounds, input_mode_chip)
    cv_bounds, fb_bounds = _render_text_bounds(
        input_mode_chip, input_value_chip,
        page=2,
        input_modes=(RezoCore.INPUT_MODE_CV,) * 4,
        cv_targets=(RezoCore.CV_TARGET_FEEDBACK,) * 4,
    )
    _assert_optically_centered(cv_bounds, input_mode_chip)
    _assert_optically_centered(fb_bounds, input_value_chip)


def test_clock_mode_specific_value_glyphs_are_optically_centered():
    turing_chips = ((304, 412, 370, 434), (304, 476, 354, 498))
    turing_bounds = _render_text_bounds(
        *turing_chips,
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_TURING,
        turing_change_index=3,
        turing_length=10,
    )
    for bounds, chip in zip(turing_bounds, turing_chips):
        _assert_optically_centered(bounds, chip)

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
        _assert_optically_centered(bounds, chip)

    data_chip = (304, 412, 466, 434)
    data_bounds, = _render_text_bounds(
        data_chip,
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_SHIFT,
        data_source=RezoCore.DATA_SOURCE_CV,
    )
    _assert_optically_centered(data_bounds, data_chip)


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
    pixels = _render_samples(
        page=2,
        input_gains=(255,),
        points=((570, 260), (575, 260)),
    )
    assert pixels[0] == (accent, accent, accent)
    assert pixels[1] != (accent, accent, accent)
