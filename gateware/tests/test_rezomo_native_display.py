from amaranth.sim import Simulator

from rezo_display_support import sample_native_rgb
from top.rezo.top import RezoCore, RezoTileDisplay
from top.rezo.ui_specs import RezomoUISpec


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
                    input_modes=(), cv_targets=(), selected=0,
                    output_meters=(), output_clips=(),
                    input_bus_meter=0, input_bus_clip=0,
                    row_dry_include=1):
    """Render settled pixels from the native REZOMO coordinate space."""
    dut = RezoTileDisplay(
        h_active=h_active,
        rotate_left=rotate_left,
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
        ctx.set(dut.input_bus_meter, input_bus_meter)
        ctx.set(dut.input_bus_clip, input_bus_clip)
        ctx.set(dut.row_dry_include, row_dry_include)
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
        for index, value in enumerate(output_meters):
            ctx.set(dut.output_meters[index], value)
        for index, value in enumerate(output_clips):
            ctx.set(dut.output_clips[index], value)
        ctx.set(dut.de, 1)
        # Dynamic labels refresh through the sync-domain tile writer. Let one
        # complete dynamic-label pass settle before inspecting glyph pixels.
        for _ in range(900):
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


def test_native_canvas_uses_unoutlined_circular_chrome_on_standard_video():
    points = ((0, 359), (719, 360), (106, 300), (613, 300))
    pixels = _render_samples(points=points)
    blank = RezoTileDisplay.PALETTE["blank"]
    background = RezoTileDisplay.PALETTE["background"]

    assert pixels == [
        (blank, blank, blank),
        (blank, blank, blank),
        (blank, blank, blank),
        (blank, blank, blank),
    ]


def test_main_bank_band_heading_matches_feedback_heading_row():
    region = (125, 224, 525, 272)
    main, = _render_text_bounds(
        region, page=0, selected=RezomoUISpec.TARGET_BAND_BASE)
    feedback, = _render_text_bounds(
        region, page=1, selected=RezomoUISpec.TARGET_FEEDBACK_SEND_BASE)
    assert (main[1], main[3]) == (feedback[1], feedback[3])


def test_outer_arcs_surround_the_508_pixel_safe_square():
    # The centered content square stays black while the surrounding circular
    # canvas carries the darker themed chrome.
    points = ((100, 300), (620, 300), (300, 100), (300, 620))
    background = RezoTileDisplay.PALETTE["background"]
    assert _render_samples(points=points, page=7) == [
        (background, background, background),
    ] * len(points)


def test_groups_surface_has_one_extra_row_of_bottom_padding():
    surface = RezoTileDisplay.PALETTE["surface"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=3,
        points=((130, 479), (130, 480), (130, 495), (130, 496)),
    ) == [
        (surface, surface, surface),
        (surface, surface, surface),
        (surface, surface, surface),
        (blank, blank, blank),
    ]


def test_groups_bank_outline_surrounds_the_full_grid():
    selected = RezoTileDisplay.PALETTE["selected"]
    surface = RezoTileDisplay.PALETTE["surface"]
    assert _render_samples(
        page=3,
        selected=RezomoUISpec.TARGET_GROUP_BASE,
        points=((216, 290), (216, 306)),
    ) == [
        (selected, selected, selected),
        (surface, surface, surface),
    ]


def test_pager_tracks_rezomo_sound_design_order():
    palette = RezoTileDisplay.PALETTE
    # INPUT is position 1 in both modes. CLOCK is inserted at position 3
    # between BANDS and GROUPS only while CLOCK mode is active.
    assert _render_samples(
        page=2,
        points=((336, 86), (346, 86), (347, 86), (336, 96)),
    ) == [
        (palette["selected"],) * 3,
        (palette["background"],) * 3,
        (palette["line"],) * 3,
        (palette["selected"],) * 3,
    ]
    assert _render_samples(
        page=7,
        clock_mode=1,
        points=((354, 86),),
    ) == [(palette["selected"],) * 3]


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
    surface = RezoTileDisplay.PALETTE["surface"]
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
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
        (control, control, control),
        (panel, panel, panel), (panel, panel, panel),
        (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
    ]


def test_clock_walk_and_shift_chips_use_their_own_semantic_widths():
    panel = RezoTileDisplay.PALETTE["panel"]
    surface = RezoTileDisplay.PALETTE["surface"]
    assert _render_samples(
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_WALK,
        points=(
            (385, 420), (386, 420),  # STYLE: four characters
            (345, 452), (346, 452),  # DRUNK: one character
            (369, 484), (370, 484),  # CHANCE: three characters
        ),
    ) == [
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
    ]
    assert _render_samples(
        page=7,
        clock_algorithm=RezoCore.CLOCK_ALGORITHM_SHIFT,
        points=((465, 420), (466, 420)),  # DATA: AUTO RAND is longest
    ) == [
        (panel, panel, panel), (surface, surface, surface),
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
    surface = RezoTileDisplay.PALETTE["surface"]
    for target, y in (
        (RezomoUISpec.TARGET_FEEDBACK, 344),
        (RezomoUISpec.TARGET_LIMIT_KNEE, 408),
        (RezomoUISpec.TARGET_LIMIT_CAP, 440),
    ):
        assert _render_samples(
            page=1, selected=target, points=((267, y), (268, y), (269, y)),
        ) == [
            (surface, surface, surface),
            (selected, selected, selected),
            (selected, selected, selected),
        ]


def test_page_selection_outline_fits_the_page_chip():
    selected = RezoTileDisplay.PALETTE["selected"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        selected=RezomoUISpec.TARGET_PAGE,
        points=((212, 119), (212, 120), (212, 149), (212, 150)),
    ) == [
        (blank, blank, blank),
        (selected, selected, selected),
        (selected, selected, selected),
        (blank, blank, blank),
    ]


def test_clipping_lamp_sits_on_meter_top_edge_below_out_label():
    modulation = RezoTileDisplay.PALETTE["modulation"]
    assert _render_samples(
        output_meters=(63, 0, 0, 0), output_clips=(1, 0, 0, 0),
        points=((60, 261),),
    ) == [(modulation, modulation, modulation)]


def test_bottom_arc_input_bus_meter_marks_nominal_and_clipping():
    palette = RezoTileDisplay.PALETTE
    pixels = _render_samples(
        points=((360, 671), (500, 650), (510, 645), (530, 632)),
        input_bus_meter=63,
        input_bus_clip=1,
    )
    assert pixels == [
        (palette["panel"],) * 3,
        (palette["line"],) * 3,
        (palette["selected"],) * 3,
        (palette["modulation"],) * 3,
    ]


def test_row_dry_option_value_and_selection_use_third_options_row():
    bounds, = _render_text_bounds(
        (336, 308, 472, 348), page=5, row_dry_include=0)
    assert 352 <= bounds[0] <= 354
    selected = RezoTileDisplay.PALETTE["selected"]
    assert _render_samples(
        page=5,
        selected=RezomoUISpec.TARGET_ROW_DRY,
        points=((332, 304),),
    ) == [(selected, selected, selected)]


def test_input_text_chips_use_fixed_widths_and_shared_row_centres():
    panel = RezoTileDisplay.PALETTE["panel"]
    surface = RezoTileDisplay.PALETTE["surface"]
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
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
        (panel, panel, panel), (surface, surface, surface),
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
    surface = RezoTileDisplay.PALETTE["surface"]
    pixels = _render_samples(
        page=2,
        input_gains=(255,),
        points=((572, 260), (573, 260), (574, 260), (575, 260)),
    )
    assert pixels[0] == (accent, accent, accent)
    assert pixels[1:3] == [(panel, panel, panel)] * 2
    assert pixels[3] == (surface, surface, surface)


def test_output_row_selector_uses_native_safe_square_coordinates():
    selected = RezoTileDisplay.PALETTE["selected"]
    blank = RezoTileDisplay.PALETTE["blank"]
    assert _render_samples(
        page=4,
        selected=RezomoUISpec.TARGET_OUTPUT_ROW_BASE,
        points=((105, 294), (116, 294)),
    ) == [
        (RezoTileDisplay.PALETTE["background"],) * 3,
        (selected, selected, selected),
    ]


def test_output_column_header_selection_bars_sit_above_the_labels():
    selected = RezoTileDisplay.PALETTE["selected"]
    group_samples = _render_samples(
        page=4,
        selected=RezomoUISpec.TARGET_OUTPUT_COL_BASE,
        points=((270, 233), (270, 281)),
    )
    dry_samples = _render_samples(
        page=4,
        selected=RezomoUISpec.TARGET_OUTPUT_DRY_COL,
        points=((538, 233), (538, 281)),
    )
    assert group_samples[0] == (selected, selected, selected)
    assert dry_samples[0] == (selected, selected, selected)
    assert group_samples[1] != (selected, selected, selected)
    assert dry_samples[1] != (selected, selected, selected)


def test_output_send_scaling_preserves_exact_fill_endpoint():
    """A send of eight fills 24 pixels after the four-pixel inset."""
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, 294)
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
    assert samples == [palette["control"], palette["surface"]]
