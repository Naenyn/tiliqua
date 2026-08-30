from amaranth import Module
from amaranth.sim import Simulator

from top.rezo.rezo_variant import (
    INPUT_BUS_NOMINAL_MAGNITUDE, INPUT_BUS_NOMINAL_METER_VALUE,
    NATIVE_INPUT_BUS_FILL_X0, NATIVE_INPUT_BUS_FILL_X1,
    NATIVE_OUTPUT_METER_LABEL_COLS,
    RezoCore, RezoTileDisplay, input_bus_meter_db_value,
    output_meter_db_value,
    native_input_bus_meter_endpoint,
    native_output_meter_bounds,
)
from top.rezo.ui_specs import RezoUISpec


def test_output_meter_uses_calibrated_daw_scale():
    """The telemetry LUT follows a linear -60..0 dBFS display axis."""
    assert [output_meter_db_value(magnitude) for magnitude in
            (0, 1, 4, 16, 65, 129, 257, 513, 1023)] == [
        0, 0, 12, 25, 38, 44, 50, 57, 63,
    ]


def test_input_bus_meter_uses_the_complete_bottom_arc_span():
    assert [native_input_bus_meter_endpoint(value)
            for value in (0, 32, 57, 63)] == [187, 363, 500, 533]
    assert native_input_bus_meter_endpoint(0) == NATIVE_INPUT_BUS_FILL_X0
    assert native_input_bus_meter_endpoint(63) == NATIVE_INPUT_BUS_FILL_X1


def test_input_bus_meter_floors_connected_source_idle_noise():
    assert [input_bus_meter_db_value(magnitude)
            for magnitude in (0, 3, 4, 5, 32, 1023)] == [0, 0, 0, 2, 24, 63]
    assert INPUT_BUS_NOMINAL_MAGNITUDE == 624
    assert INPUT_BUS_NOMINAL_METER_VALUE == 57
    assert native_input_bus_meter_endpoint(
        INPUT_BUS_NOMINAL_METER_VALUE) == 500


def test_output_meter_pairs_and_labels_are_centered_in_side_arcs():
    middle_bounds = native_output_meter_bounds(360)
    assert middle_bounds[0] == 106 - middle_bounds[3] == 25

    bounds = native_output_meter_bounds(461)
    left_meter_centers = (
        (bounds[0] + bounds[1] - 1) // 2,
        (bounds[2] + bounds[3] - 1) // 2,
    )
    meter_centers = left_meter_centers + (
        (1439 - bounds[2] - bounds[3]) // 2,
        (1439 - bounds[0] - bounds[1]) // 2,
    )
    assert meter_centers == (53, 87, 632, 666)
    label_centers = tuple(
        col * 16 + 8 for col in NATIVE_OUTPUT_METER_LABEL_COLS)
    assert all(abs(label - meter) <= 3 for label, meter in zip(
        label_centers, meter_centers))


def _render_text_bounds(*regions, page=0, palette=0, input_modes=(),
                        cv_targets=(), save_default_available=0,
                        filter_mode=0, row_dry_include=1, selected=0):
    """Return visible glyph bounds inside native compact value chips."""
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, page)
        ctx.set(dut.selected, selected)
        ctx.set(dut.filter_mode, filter_mode)
        ctx.set(dut.palette, palette)
        ctx.set(dut.save_default_available, save_default_available)
        ctx.set(dut.row_dry_include, row_dry_include)
        for index, value in enumerate(input_modes):
            ctx.set(dut.input_modes[index], value)
        for index, value in enumerate(cv_targets):
            ctx.set(dut.cv_targets[index], value)
        ctx.set(dut.de, 1)
        # Let the sync-domain dynamic-label writer finish a complete pass.
        for _ in range(450):
            await ctx.tick("dvi")
        for x0, y0, x1, y1 in regions:
            points = []
            for y in range(y0, y1):
                for x in range(x0, x1):
                    ctx.set(dut.x, dut.x_offset + x)
                    ctx.set(dut.y, y)
                    for _ in range(12):
                        await ctx.tick("dvi")
                    points.append((x, y, ctx.get(dut.r),
                                   ctx.get(dut.g), ctx.get(dut.b)))
            samples.append(points)

    sim.add_testbench(bench)
    sim.run()

    packed_text = dut.RGB_PALETTES[palette][1]
    text_rgb = (
        (packed_text >> 16) & 0xff,
        (packed_text >> 8) & 0xff,
        packed_text & 0xff,
    )
    bounds = []
    for points in samples:
        lit = [(x, y) for x, y, r, g, b in points
               if (r, g, b) == text_rgb]
        assert lit
        bounds.append((
            min(x for x, _ in lit), min(y for _, y in lit),
            max(x for x, _ in lit) + 1, max(y for _, y in lit) + 1,
        ))
    return bounds


def test_main_bank_band_heading_matches_feedback_heading_row():
    region = (125, 224, 525, 272)
    main, = _render_text_bounds(
        region, page=0, selected=RezoUISpec.TARGET_BAND_BASE)
    feedback, = _render_text_bounds(
        region, page=1, selected=RezoUISpec.TARGET_FEEDBACK_SEND_BASE)
    assert (main[1], main[3]) == (feedback[1], feedback[3])


def test_standard_hdmi_compact_preview_is_native_size_and_unrotated():
    """Both targets render identical upright compact pixels at native size."""
    preview = RezoTileDisplay(
        h_active=1280, rotate_left=False)
    round_panel = RezoTileDisplay(
        h_active=720, rotate_left=True)
    top = Module()
    top.submodules.preview = preview
    top.submodules.round_panel = round_panel
    sim = Simulator(top)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, upright_x, upright_y):
        # Standard HDMI only adds its 280px horizontal centering offset.
        ctx.set(preview.x, preview.x_offset + upright_x)
        ctx.set(preview.y, upright_y)
        ctx.set(preview.de, 1)
        # The circular target applies the physical panel mount correction.
        ctx.set(round_panel.x, 719 - upright_y)
        ctx.set(round_panel.y, upright_x)
        ctx.set(round_panel.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append((ctx.get(preview.r), ctx.get(round_panel.r)))

    async def bench(ctx):
        await sample(ctx, 320, 32)   # REZO top-arc identity
        await sample(ctx, 128, 208)  # content heading
        await sample(ctx, 90, 360)   # persistent circular side chrome

    sim.add_testbench(bench)
    sim.run()

    assert preview.x_offset == 280
    assert not preview.rotate_left
    assert round_panel.rotate_left
    assert samples[0][0] == RezoTileDisplay.PALETTE["text"]
    assert samples[2][0] == RezoTileDisplay.PALETTE["background"]
    assert all(standard == circular for standard, circular in samples)


def test_compact_input_and_options_values_use_fixed_left_origins():
    mode_chips = tuple(
        (304, 221 + 96 * index, 402, 241 + 96 * index)
        for index in range(4))
    value_chips = tuple(
        (304, 253 + 96 * index, 370, 273 + 96 * index)
        for index in range(1, 4))
    input_bounds = _render_text_bounds(
        *(mode_chips + value_chips),
        page=2,
        input_modes=(RezoCore.INPUT_MODE_AUDIO,) +
                    (RezoCore.INPUT_MODE_CV,) * 3,
        cv_targets=(RezoCore.CV_TARGET_FEEDBACK,
                    RezoCore.CV_TARGET_FEEDBACK,
                    RezoCore.CV_TARGET_RESONANCE,
                    RezoCore.CV_TARGET_GROUP_BASE + 3),
    )
    for bounds, chip in zip(input_bounds, mode_chips + value_chips):
        assert 320 <= bounds[0] <= 322
        assert bounds[2] <= chip[2]

    options_chips = (
        (336, 244, 456, 284),
        (336, 308, 472, 348),
        (336, 372, 472, 412),
    )
    options_bounds = _render_text_bounds(
        *options_chips, page=5, palette=3, save_default_available=1)
    for bounds, chip in zip(options_bounds, options_chips):
        assert 352 <= bounds[0] <= 354
        assert bounds[0] - chip[0] in (16, 17, 18)
        assert bounds[2] <= chip[2]


def test_output_dry_label_is_centered_and_hidden_with_its_filter_column():
    dry_bounds, = _render_text_bounds((500, 232, 568, 260), page=4)
    assert dry_bounds[0] + dry_bounds[2] in range(1066, 1074)

    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, filter_mode):
        ctx.set(dut.filter_mode, filter_mode)
        ctx.set(dut.x, dut.x_offset + 534)
        ctx.set(dut.y, 281)
        for _ in range(16):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 4)
        ctx.set(dut.de, 1)
        await sample(ctx, 0)
        await sample(ctx, 1)

    sim.add_testbench(bench)
    sim.run()
    palette = RezoTileDisplay.PALETTE
    assert samples == [palette["panel"], palette["surface"]]


def test_main_preset_selection_uses_the_shared_header_outline():
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, 0)
        ctx.set(dut.selected, RezoUISpec.TARGET_PRESET)
        ctx.set(dut.de, 1)
        for y in (164, 180):
            ctx.set(dut.x, dut.x_offset + 250)
            ctx.set(dut.y, y)
            for _ in range(16):
                await ctx.tick("dvi")
            samples.append(ctx.get(dut.r))

    sim.add_testbench(bench)
    sim.run()
    palette = RezoTileDisplay.PALETTE
    assert samples == [palette["blank"], palette["selected"]]


def test_compact_round_layout_uses_all_four_arcs():
    """Native identity, PAGE, and persistent side chrome share one canvas."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, upright_x, upright_y):
        # Undo the production panel's physical left rotation.
        ctx.set(dut.x, 719 - upright_y)
        ctx.set(dut.y, upright_x)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        # Native REZO identity lives in the top circular arc.
        await sample(ctx, 320, 32)
        # Blank portion of the PAGE value chip remains visibly framed.
        await sample(ctx, 352, 135)
        ctx.set(dut.selected, RezoUISpec.TARGET_PAGE)
        await sample(ctx, 212, 140)
        # MAIN is authored natively in the safe central header.
        await sample(ctx, 256, 128)
        # The side wing now carries persistent circular chrome.
        await sample(ctx, 95, 360)
        # The circular canvas no longer draws a guide at its outer edge.
        await sample(ctx, 360, 0)
        # The extreme square corner is deliberately blank outside the circle.
        await sample(ctx, 0, 0)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["text"],
        palette["panel"],
        palette["selected"],
        palette["text"],
        palette["background"],
        palette["blank"],
        palette["blank"],
    ]


def test_compact_header_controls_are_tight():
    """Header status boxes hug their text."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        for _ in range(240):
            await ctx.tick("sync")
        await sample(ctx, 350, 123)  # immediately above PAGE chip
        await sample(ctx, 350, 124)  # PAGE chip top
        await sample(ctx, 350, 145)  # PAGE chip bottom
        await sample(ctx, 350, 146)  # immediately below PAGE chip
        await sample(ctx, 520, 121)  # immediately above NAV outline
        await sample(ctx, 520, 122)  # NAV outline top/left
        await sample(ctx, 520, 147)  # NAV outline bottom/left
        await sample(ctx, 520, 148)  # immediately below NAV outline
        await sample(ctx, 528, 128)  # NAV begins at the shared text edge
        await sample(ctx, 598, 122)  # NAV's fitted outline ends earlier
        ctx.set(dut.editing, 1)
        await sample(ctx, 598, 122)  # EDIT expands the outline by one cell

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["blank"], palette["panel"],
        palette["panel"], palette["blank"],
        palette["blank"], palette["line"],
        palette["line"], palette["blank"],
        palette["text"], palette["blank"], palette["line"],
    ]


def test_compact_options_surface_has_balanced_vertical_padding():
    """OPTIONS keeps one 20px inset above and below its value chips."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_y):
        ctx.set(dut.x, 400)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 5)
        await sample(ctx, 431)  # 20px below the ROW DRY chip
        await sample(ctx, 432)  # first row beyond the fitted surface

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [palette["surface"], palette["blank"]]


def test_compact_safe_square_cuts_black_field_out_of_curved_chrome():
    """The centered 508px square masks an otherwise shaded circle."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        await sample(ctx, 105, 360)
        await sample(ctx, 106, 360)
        await sample(ctx, 613, 360)
        await sample(ctx, 614, 360)
        await sample(ctx, 360, 105)
        await sample(ctx, 360, 106)
        await sample(ctx, 360, 613)
        await sample(ctx, 360, 614)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert 614 - 106 == 508
    assert samples == [
        palette["background"], palette["blank"],
        palette["blank"], palette["background"],
        palette["background"], palette["blank"],
        palette["blank"], palette["background"],
    ]


def test_compact_pager_tracks_firmware_navigation_order_and_mode_count():
    """The selected pager box follows encoder order, not raw page number."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        # BANK order is 0,2,6,3,1,4,5. Page 2 therefore selects box 1;
        # surrounding boxes move outward to make room for its larger box.
        ctx.set(dut.page, 2)
        await sample(ctx, 336, 86)
        await sample(ctx, 346, 86)
        await sample(ctx, 347, 86)
        await sample(ctx, 336, 96)  # enlarged box's added bottom row

        # FILTER adds MATRIX as position 3 and keeps OPTIONS last.
        ctx.set(dut.filter_mode, 1)
        ctx.set(dut.page, 5)
        await sample(ctx, 402, 86)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["selected"], palette["background"],
        palette["line"], palette["selected"], palette["selected"],
    ]


def test_compact_pager_keeps_one_pixel_gaps_during_raster_scan():
    """Filled and outlined pager roles remain aligned at one pixel per tick."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    scans = []

    async def scan(ctx, page):
        ctx.set(dut.page, page)
        ctx.set(dut.y, 86)
        ctx.set(dut.de, 1)
        pixels = []
        for native_x in range(290, 430):
            ctx.set(dut.x, native_x)
            await ctx.tick("dvi")
            pixels.append(ctx.get(dut.r))
        scans.append(pixels)

    async def bench(ctx):
        await scan(ctx, 0)
        await scan(ctx, 2)

    sim.add_testbench(bench)
    sim.run()

    selected = RezoTileDisplay.PALETTE["selected"]
    line = RezoTileDisplay.PALETTE["line"]
    selected_runs = []
    for scan_index, pixels in enumerate(scans):
        selected_pixels = [index for index, color in enumerate(pixels)
                           if color == selected]
        start, end = min(selected_pixels), max(selected_pixels)
        assert end - start + 1 == 19
        line_pixels = [index for index, color in enumerate(pixels)
                       if color == line]
        if scan_index:
            assert start - max(
                index for index in line_pixels if index < start) == 2
        assert min(index for index in line_pixels if index > end) - end == 2
        selected_runs.append((start, end))

    # INPUT is the second firmware-navigation position.
    assert selected_runs[1][0] - selected_runs[0][0] == 12


def test_page_surfaces_use_eighth_palette_role_while_header_stays_black():
    """Page work areas are shaded without tinting the header gap."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, palette, page, native_x, native_y):
        ctx.set(dut.palette, palette)
        ctx.set(dut.page, page)
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append((ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)))

    async def bench(ctx):
        for palette in range(len(dut.RGB_PALETTES)):
            await sample(ctx, palette, 0, 350, 240)  # BANK surface
            await sample(ctx, palette, 0, 400, 180)  # header/content gap
            await sample(ctx, palette, 0, 400, 560)  # below BANK surface
            await sample(ctx, palette, 1, 350, 280)  # FEEDBACK surface

    sim.add_testbench(bench)
    sim.run()

    assert dut.PALETTE_ROLES[-1] == "surface"
    for palette, theme in enumerate(dut.RGB_PALETTES):
        packed_surface = theme[-1]
        surface_rgb = (
            (packed_surface >> 16) & 0xff,
            (packed_surface >> 8) & 0xff,
            packed_surface & 0xff,
        )
        assert samples[palette * 4] == surface_rgb
        assert samples[palette * 4 + 1:palette * 4 + 3] == [
            (0, 0, 0), (0, 0, 0),
        ]
        assert samples[palette * 4 + 3] == surface_rgb


def test_sparse_page_content_frames_share_the_main_page_top_edge():
    """Sparse page frames begin one native row below their heading row."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, page, native_y):
        ctx.set(dut.page, page)
        ctx.set(dut.x, 350)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        for page in (1, 3, 4, 5, 6):
            await sample(ctx, page, 223)
            await sample(ctx, page, 224)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        value
        for _ in range(5)
        for value in (palette["blank"], palette["surface"])
    ]


def test_compact_output_meters_are_persistent_and_independent():
    """All four output meters render in their fixed left/right arc lanes."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        for lane, value in enumerate((0, 20, 40, 63)):
            ctx.set(dut.output_meters[lane], value)
        ctx.set(dut.output_clips[0], 1)
        # Empty lane interior, then increasing fills in lanes 2 through 4.
        await sample(ctx, 42, 400)
        await sample(ctx, 75, 400)
        await sample(ctx, 647, 350)
        await sample(ctx, 669, 280)
        # An outline remains visible around an empty lane.
        await sample(ctx, 25, 360)
        # A held clipping lamp sits on the lane's top edge, below OUT.
        await sample(ctx, 60, 261)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["background"],
        palette["control"], palette["control"], palette["selected"],
        palette["panel"], palette["modulation"],
    ]


def test_compact_curved_header_and_footer_host_input_bus_identity():
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        await sample(ctx, 360, 105)  # inside curved top band
        await sample(ctx, 360, 112)  # black centre begins below compact cap
        await sample(ctx, 360, 200)  # black gap below the header cap
        await sample(ctx, 17 * 16, 656)  # former version-text position
        await sample(ctx, 360, 640)  # persistent bottom-arc IN label

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["background"], palette["blank"], palette["blank"],
        palette["background"], palette["text"],
    ]


def test_compact_input_bus_meter_fills_and_clips_in_bottom_arc():
    dut = RezoTileDisplay(h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        # Empty interior and persistent curved outline.
        await sample(ctx, 360, 682)
        await sample(ctx, 360, 671)
        # Nominal 0 dB (5 V peak) leaves visible headroom to the right.
        await sample(ctx, 500, 650)
        # Mid-scale reaches the centre; the upper six dB use the hot role.
        ctx.set(dut.input_bus_meter, 32)
        await sample(ctx, 360, 682)
        ctx.set(dut.input_bus_meter, 63)
        await sample(ctx, 510, 645)
        # The held clip cap occupies the full-scale end of the curved lane.
        ctx.set(dut.input_bus_clip, 1)
        await sample(ctx, 530, 632)
        await sample(ctx, 538, 618)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["background"], palette["panel"], palette["line"],
        palette["control"], palette["selected"],
        palette["modulation"], palette["background"],
    ]


def test_compact_labels_use_native_control_rows():
    """Compact text and geometry share final 720-canvas pixel coordinates."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, upright_x, upright_y):
        ctx.set(dut.x, 719 - upright_y)
        ctx.set(dut.y, upright_x)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        # Seed dynamic INPUT text before the writer's initial refresh burst.
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_CV)
        ctx.set(dut.cv_targets[0], 0)
        for _ in range(240):
            await ctx.tick("sync")

        # BANK labels share the native x=272 right edge of the fader gutter.
        await sample(ctx, 12 * 16, 464)       # DRIVE
        await sample(ctx, 10 * 16, 464)       # left of label

        # FILTER's deepest row remains inside the content field, and its
        # first label begins on the same inner gutter as MATRIX.
        ctx.set(dut.filter_mode, 1)
        await sample(ctx, 8 * 16, 464)        # FREQUENCY
        await sample(ctx, 160, 608)           # below RESONANCE, inside field

        # MATRIX uses the same native 64px row cadence for text and controls.
        ctx.set(dut.page, 7)
        await sample(ctx, 8 * 16, 17 * 16)   # FREQUENCY

        # Dynamic INPUT targets align with the value-only CV chip. Labels to
        # its left remain on the unshaded field.
        ctx.set(dut.filter_mode, 0)
        ctx.set(dut.page, 2)
        await sample(ctx, 12 * 16, 16 * 16)  # left of the VALUE chip
        await sample(ctx, 20 * 16, 16 * 16)  # left-justified FB target

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["text"], palette["surface"],
        palette["text"], palette["surface"],
        palette["text"],
        palette["surface"], palette["text"],
    ]


def test_compact_input_groups_and_enable_buttons_share_requested_geometry():
    """INPUT uses value-only panels and mode-dependent meter placement."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def sample_native(ctx, upright_x, upright_y):
        ctx.set(dut.x, upright_x)
        ctx.set(dut.y, upright_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def sample_input(ctx, native_x, native_y):
        """INPUT lanes and text use the same native raster coordinates."""
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 2)
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_AUDIO)
        ctx.set(dut.input_modes[1], RezoCore.INPUT_MODE_CV)
        ctx.set(dut.input_meters[0], 20)
        ctx.set(dut.input_meters[1], -10)
        for _ in range(260):
            await ctx.tick("sync")
        await sample_input(ctx, 280, 241)  # MODE label lane is unshaded.
        await sample_input(ctx, 400, 230)  # MODE chip, clear of text glyphs.
        await sample_input(ctx, 400, 260)  # AUD VALUE fader occupies its lane.
        await sample_input(ctx, 400, 271)  # AUD monitor follows VALUE.
        await sample_input(ctx, 400, 292)  # AUD DEPTH remains absent.
        await sample_input(ctx, 368, 356)  # CV target chip, clear of glyphs.
        await sample_input(ctx, 400, 390)  # CV DEPTH fader occupies its lane.
        await sample_input(ctx, 430, 399)  # CV monitor follows DEPTH.
        await sample_native(ctx, 13 * 16, 18 * 16)  # AUD DEPTH label hidden.
        await sample_native(ctx, 13 * 16, 24 * 16)  # CV DEPTH label visible.

        ctx.set(dut.page, 1)
        ctx.set(dut.band_enables[0], 1)
        ctx.set(dut.feedback_sends[0], 1)
        await sample(ctx, 145, 274)  # FEEDBACK full-height button fill
        ctx.set(dut.page, 6)
        ctx.set(dut.band_enables[0], 1)
        await sample(ctx, 145, 274)  # BANDS now matches FEEDBACK

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["surface"], palette["panel"], palette["panel"],
        palette["modulation"], palette["surface"], palette["panel"],
        palette["panel"], palette["modulation"],
        palette["surface"], palette["text"],
        palette["control"], palette["control"],
    ], samples


def test_compact_group_rails_share_native_label_centers():
    """Every GROUPS rail uses the visual center of its 14px label glyph."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, native_x, native_y):
        ctx.set(dut.x, native_x)
        ctx.set(dut.y, native_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 3)
        # Shifted text rows 19/22/25/28 retain their native centres.
        # Each rail occupies the two pixels straddling that same center.
        for center_y in (310, 358, 406, 454):
            await sample(ctx, 560, center_y)
            await sample(ctx, 560, center_y - 2)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
    ], samples


def test_compact_groups_surface_has_one_extra_row_of_bottom_padding():
    dut = RezoTileDisplay(h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, 3)
        ctx.set(dut.de, 1)
        for native_y in (479, 480, 495, 496):
            ctx.set(dut.x, 130)
            ctx.set(dut.y, native_y)
            for _ in range(12):
                await ctx.tick("dvi")
            samples.append(ctx.get(dut.r))

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["surface"], palette["surface"],
        palette["surface"], palette["blank"],
    ], samples


def test_compact_feedback_sources_and_safety_share_centered_geometry():
    """FEEDBACK sources center as a group and safety values share one edge."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, physical_x, physical_y):
        ctx.set(dut.x, physical_x)
        ctx.set(dut.y, physical_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 1)
        ctx.set(dut.feedback_sends[0], 1)
        for _ in range(260):
            await ctx.tick("sync")

        # KNEE and CEILING use the shared x=[268,579) track. Their maximum
        # fill retains two visible panel pixels at the right edge.
        await sample(ctx, 268, 405)
        await sample(ctx, 260, 405)
        await sample(ctx, 578, 405)
        await sample(ctx, 579, 405)

        # DAMPING leaves one label-to-chip cell, then one chip-to-text cell.
        await sample(ctx, 272, 458)
        await sample(ctx, 271, 458)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    # Ten 30px buttons and nine 17px gutters occupy one reusable native row.
    rendered_x0, rendered_x1 = 133, 586
    assert rendered_x1 - rendered_x0 == 10 * 30 + 9 * 17
    # On an even-width canvas this odd-width row is centred between pixels.
    assert rendered_x0 + rendered_x1 == 719
    assert samples == [
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
    ], samples


def test_compact_audio_gain_fader_stays_inside_value_lane():
    """Maximum audio gain leaves the standard two-pixel chip inset."""
    dut = RezoTileDisplay(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 2)
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_AUDIO)
        ctx.set(dut.input_gains[0], 255)
        await sample(ctx, 572, 260)  # last pixel inside the padded fill lane
        await sample(ctx, 573, 260)  # first pixel of the right-hand padding
        await sample(ctx, 574, 260)  # second pixel of the right-hand padding
        await sample(ctx, 575, 260)  # outside the VALUE chip

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["control"], palette["panel"], palette["panel"],
        palette["surface"],
    ]


def test_compact_input_meter_clamps_and_marks_clipping_inside_value_lane():
    """Full-scale telemetry cannot escape the chip; clipping gets an end stop."""
    dut = RezoTileDisplay(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 2)
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_AUDIO)
        ctx.set(dut.input_meters[0], 31)
        await sample(ctx, 574, 271)  # final meter pixel inside the value chip
        await sample(ctx, 576, 271)  # no telemetry beyond the chip
        ctx.set(dut.input_clips[0], 1)
        await sample(ctx, 573, 268)  # bright clip end stop
        await sample(ctx, 576, 268)  # marker also remains inside the chip

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["modulation"], palette["surface"],
        palette["modulation"], palette["surface"],
    ]


def test_compact_output_cells_share_native_label_centers():
    """Every OUTPUT cell is centred from the same native label coordinate."""
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 4)
        # Top edges at each row centre verify the native vertical centres.
        row_centers = (294, 358, 422, 486)
        assert tuple(b - a for a, b in zip(
            row_centers, row_centers[1:])) == (64, 64, 64)
        for center_y in row_centers:
            await sample(ctx, 270, center_y - 13)
            await sample(ctx, 270, center_y - 14)
        # First-row top edges at each heading centre include the wider DRY
        # label; a pixel beyond each cell verifies the symmetric 56px bounds.
        for center_x in (270, 334, 398, 462, 534):
            await sample(ctx, center_x, 281)
            await sample(ctx, center_x + 29, 281)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples[:8] == [
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
    ]
    assert samples[8:] == [
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
        palette["panel"], palette["surface"],
    ]


def test_compact_output_send_scaling_preserves_exact_fill_endpoint():
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
        # First compact cell starts at x=243. Its inset starts at 247 and an
        # eight-step send ends at 247 + 8*3 = 271 (exclusive).
        await sample(ctx, 270)
        await sample(ctx, 271)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [palette["control"], palette["surface"]]


def test_compact_matrix_labels_share_control_row_centers():
    """MATRIX labels use the faders' cadence and one right-hand edge."""
    text_rows = (16, 21, 26, 31, 36)
    control_y0s = tuple(250 + destination * 80 for destination in range(5))

    # Work in half-pixels: the visible 14-pixel glyph centre is row*16+6.5;
    # each 28-pixel fader panel is centred at y0+13.5. Every label therefore
    # sits at the same intentional one-pixel optical offset from its control.
    glyph_centers_2 = tuple(row * 32 + 13 for row in text_rows)
    control_centers_2 = tuple(y0 * 2 + 27 for y0 in control_y0s)
    assert tuple(b - a for a, b in zip(
        glyph_centers_2, glyph_centers_2[1:])) == (160, 160, 160, 160)
    assert tuple(control - glyph for control, glyph in zip(
        control_centers_2, glyph_centers_2)) == (2, 2, 2, 2, 2)

    # FREQUENCY/RESONANCE begin at x=8; the shorter labels begin at x=12.
    # All five terminate at the same native right edge, x=17 (exclusive).
    label_x0s = (8, 8, 12, 12, 12)
    label_lengths = (9, 9, 5, 5, 5)
    assert tuple(x0 + width for x0, width in zip(
        label_x0s, label_lengths)) == (17, 17, 17, 17, 17)
