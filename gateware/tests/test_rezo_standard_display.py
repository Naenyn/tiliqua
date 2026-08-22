from amaranth import Module
from amaranth.sim import Simulator

from top.rezo.rezo_variant import RezoCore, RezoHardwareUI, RezoTileDisplay


def _render_text_bounds(*regions, page=0, palette=0, input_modes=(),
                        cv_targets=(), save_default_available=0,
                        filter_mode=0):
    """Return visible glyph bounds inside native compact value chips."""
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False, compact_layout=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, page)
        ctx.set(dut.filter_mode, filter_mode)
        ctx.set(dut.palette, palette)
        ctx.set(dut.save_default_available, save_default_available)
        for index, value in enumerate(input_modes):
            ctx.set(dut.input_modes[index], value)
        for index, value in enumerate(cv_targets):
            ctx.set(dut.cv_targets[index], value)
        ctx.set(dut.de, 1)
        # Let the sync-domain dynamic-label writer finish a complete pass.
        for _ in range(400):
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


def test_standard_hdmi_compact_preview_is_native_size_and_unrotated():
    """Both targets render identical upright compact pixels at native size."""
    preview = RezoTileDisplay(
        h_active=1280, rotate_left=False, compact_layout=True)
    round_panel = RezoTileDisplay(
        h_active=720, rotate_left=True, compact_layout=True)
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
        await sample(ctx, 48, 360)   # blank circular side wing

    sim.add_testbench(bench)
    sim.run()

    assert preview.x_offset == 280
    assert not preview.rotate_left
    assert round_panel.rotate_left
    assert samples[0][0] == RezoTileDisplay.PALETTE["text"]
    assert samples[2][0] == RezoTileDisplay.PALETTE["blank"]
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

    options_chips = ((336, 260, 456, 300), (336, 324, 472, 364))
    options_bounds = _render_text_bounds(
        *options_chips, page=5, palette=3, save_default_available=1)
    for bounds, chip in zip(options_bounds, options_chips):
        assert 352 <= bounds[0] <= 354
        assert bounds[0] - chip[0] in (16, 17, 18)
        assert bounds[2] <= chip[2]


def test_output_dry_label_is_centered_and_hidden_with_its_filter_column():
    dry_bounds, = _render_text_bounds((500, 280, 568, 308), page=4)
    assert dry_bounds[0] + dry_bounds[2] in range(1066, 1074)

    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False, compact_layout=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, filter_mode):
        ctx.set(dut.filter_mode, filter_mode)
        ctx.set(dut.x, dut.x_offset + 534)
        ctx.set(dut.y, 329)
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
    assert samples == [palette["panel"], palette["background"]]


def test_main_preset_selection_uses_the_shared_header_outline():
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False, compact_layout=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, 0)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_PRESET)
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


def test_compact_round_layout_keeps_native_text_and_uses_top_arc():
    """The compact layout keeps side wings blank and PAGE in the header."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=True, compact_layout=True)
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
        await sample(ctx, 352, 152)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_PAGE)
        await sample(ctx, 212, 140)
        # MAIN is authored natively in the safe central header.
        await sample(ctx, 256, 128)
        # The side wing remains deliberately blank.
        await sample(ctx, 48, 360)
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
        palette["blank"],
        palette["blank"],
    ]


def test_compact_safe_square_has_exact_native_508px_bounds():
    """The page outline is authored directly at [106,614), not rescaled."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False, compact_layout=True)
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
        palette["blank"], palette["line"],
        palette["line"], palette["blank"],
        palette["blank"], palette["line"],
        palette["line"], palette["blank"],
    ]


def test_compact_labels_use_native_control_rows():
    """Compact text and geometry share final 720-canvas pixel coordinates."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=True, compact_layout=True)
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
        await sample(ctx, 12 * 16, 448)       # DRIVE
        await sample(ctx, 10 * 16, 448)       # old, too-far-left start

        # FILTER's deepest row remains on the content background, and its
        # first label begins on the same inner gutter as MATRIX.
        ctx.set(dut.filter_mode, 1)
        await sample(ctx, 8 * 16, 448)        # FREQUENCY
        await sample(ctx, 160, 592)          # below RESONANCE, inside field

        # MATRIX uses the same native 64px row cadence for text and controls.
        ctx.set(dut.page, 7)
        await sample(ctx, 8 * 16, 18 * 16)   # FREQUENCY

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
        palette["text"], palette["background"],
        palette["text"], palette["background"],
        palette["text"],
        palette["background"], palette["text"],
    ]


def test_compact_input_groups_and_enable_buttons_share_requested_geometry():
    """INPUT uses value-only panels and mode-dependent meter placement."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False, compact_layout=True)
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
        await sample(ctx, 145, 290)  # FEEDBACK full-height button fill
        ctx.set(dut.page, 6)
        ctx.set(dut.band_enables[0], 1)
        await sample(ctx, 145, 290)  # BANDS now matches FEEDBACK

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["background"], palette["panel"], palette["panel"],
        palette["modulation"], palette["background"], palette["panel"],
        palette["panel"], palette["modulation"],
        palette["background"], palette["text"],
        palette["control"], palette["control"],
    ], samples


def test_compact_group_rails_share_native_label_centers():
    """Every GROUPS rail uses the visual center of its 14px label glyph."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False, compact_layout=True)
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
        # Text rows 20/23/26/29 have visible-glyph centers at +6.5px.
        # Each rail occupies the two pixels straddling that same center.
        for center_y in (326, 374, 422, 470):
            await sample(ctx, 560, center_y)
            await sample(ctx, 560, center_y - 2)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
    ], samples


def test_compact_feedback_sources_and_safety_share_centered_geometry():
    """FEEDBACK sources center as a group and safety values share one edge."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False, compact_layout=True)
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
        await sample(ctx, 268, 421)
        await sample(ctx, 260, 421)
        await sample(ctx, 578, 421)
        await sample(ctx, 579, 421)

        # DAMPING leaves one label-to-chip cell, then one chip-to-text cell.
        await sample(ctx, 272, 474)
        await sample(ctx, 271, 474)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    # Ten 30px buttons and nine 17px gutters occupy one reusable native row.
    rendered_x0, rendered_x1 = 133, 586
    assert rendered_x1 - rendered_x0 == 10 * 30 + 9 * 17
    # On an even-width canvas this odd-width row is centred between pixels.
    assert rendered_x0 + rendered_x1 == 719
    assert samples == [
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
    ], samples


def test_disabled_band_has_bank_ghosts_but_filter_remains_active():
    """Disabled BANK columns and group cells keep frames; FILTER stays active."""
    dut = RezoTileDisplay(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(8):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.levels[0], 64)
        ctx.set(dut.effective_levels[0], 64)
        ctx.set(dut.band_enables[0], 0)
        await sample(ctx, 42, 300)  # ghost frame edge
        await sample(ctx, 60, 300)  # blank frame interior

        ctx.set(dut.filter_mode, 1)
        await sample(ctx, 60, 300)  # FILTER column remains active

        ctx.set(dut.filter_mode, 0)
        ctx.set(dut.page, 3)
        await sample(ctx, 150, 294)  # disabled group-cell top ghost rail
        await sample(ctx, 150, 300)  # empty space between ghost rails

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["line"], palette["background"], palette["control"],
        palette["line"], palette["background"],
    ]


def test_tile_display_drive_modulation_shading_in_both_modes():
    """DRIVE distinguishes its base setting from CV in BANK and FILTER."""
    dut = RezoTileDisplay(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(8):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.drive, 64)
        ctx.set(dut.effective_drive, 96)

        # BANK DRIVE occupies y=556..571. The extension beyond the base
        # setting uses the modulation palette role.
        await sample(ctx, 300, 560)
        await sample(ctx, 450, 560)
        await sample(ctx, 380, 554)

        # FILTER uses the shared fader renderer but must show the same split.
        ctx.set(dut.filter_mode, 1)
        await sample(ctx, 300, 646)
        await sample(ctx, 450, 646)
        await sample(ctx, 380, 640)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["control"],
        palette["modulation"],
        palette["line"],
        palette["control"],
        palette["modulation"],
        palette["line"],
    ]


def test_input_page_draws_post_value_audio_and_raw_bipolar_cv_meters():
    """The one-pixel telemetry line distinguishes audio and CV semantics."""
    dut = RezoTileDisplay(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, panel_x, panel_y):
        ctx.set(dut.x, dut.x_offset + panel_x)
        ctx.set(dut.y, panel_y)
        ctx.set(dut.de, 1)
        for _ in range(8):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        ctx.set(dut.page, 2)
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_AUDIO)
        ctx.set(dut.input_meters[0], 20)
        ctx.set(dut.input_modes[1], RezoCore.INPUT_MODE_CV)
        ctx.set(dut.input_meters[1], -10)

        await sample(ctx, 400, 297)
        await sample(ctx, 550, 297)
        await sample(ctx, 460, 393)
        await sample(ctx, 520, 393)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["modulation"], palette["background"],
        palette["modulation"], palette["background"],
    ]


def test_compact_audio_gain_fader_stays_inside_value_lane():
    """Maximum audio gain leaves the standard two-pixel chip inset."""
    dut = RezoTileDisplay(h_active=1280, compact_layout=True)
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
        palette["background"],
    ]


def test_compact_output_cells_share_native_label_centers():
    """Every OUTPUT cell is centred from the same native label coordinate."""
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False, compact_layout=True)
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
        row_centers = (342, 406, 470, 534)
        assert tuple(b - a for a, b in zip(
            row_centers, row_centers[1:])) == (64, 64, 64)
        for center_y in row_centers:
            await sample(ctx, 270, center_y - 13)
            await sample(ctx, 270, center_y - 14)
        # First-row top edges at each heading centre include the wider DRY
        # label; a pixel beyond each cell verifies the symmetric 56px bounds.
        for center_x in (270, 334, 398, 462, 534):
            await sample(ctx, center_x, 329)
            await sample(ctx, center_x + 29, 329)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples[:8] == [
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
    ]
    assert samples[8:] == [
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
        palette["panel"], palette["background"],
    ]


def test_compact_output_send_scaling_preserves_exact_fill_endpoint():
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
        # First compact cell starts at x=243. Its inset starts at 247 and an
        # eight-step send ends at 247 + 8*3 = 271 (exclusive).
        await sample(ctx, 270)
        await sample(ctx, 271)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [palette["control"], palette["background"]]


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
