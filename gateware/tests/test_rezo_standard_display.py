from amaranth import Module
from amaranth.sim import Simulator

from top.rezo.rezo_variant import RezoCore, RezoHardwareUI, RezoTileDisplay


def _render_text_bounds(*regions, page=0, palette=0, input_modes=(),
                        cv_targets=(), save_default_available=0):
    """Return visible glyph bounds inside native compact value chips."""
    dut = RezoTileDisplay(
        h_active=1280, rotate_left=False, compact_layout=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, page)
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


def _assert_optically_centered(glyph_bounds, chip_bounds):
    """Allow only the half-character phase inherent to fixed 16px cells."""
    glyph_x0, glyph_y0, glyph_x1, glyph_y1 = glyph_bounds
    chip_x0, chip_y0, chip_x1, chip_y1 = chip_bounds
    assert abs((glyph_x0 + glyph_x1 - 1) -
               (chip_x0 + chip_x1 - 1)) <= 10
    assert abs((glyph_y0 + glyph_y1 - 1) -
               (chip_y0 + chip_y1 - 1)) <= 2


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


def test_compact_input_and_options_values_are_optically_centered():
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
        _assert_optically_centered(bounds, chip)

    options_chips = ((344, 260, 456, 300), (328, 324, 456, 364))
    options_bounds = _render_text_bounds(
        *options_chips, page=5, palette=3, save_default_available=1)
    for bounds, chip in zip(options_bounds, options_chips):
        _assert_optically_centered(bounds, chip)


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
        ctx.set(dut.page, 2)
        await sample(ctx, 8 * 16, 18 * 16)   # FREQUENCY

        # Dynamic INPUT targets align with the value-only CV chip. Labels to
        # its left remain on the unshaded field.
        ctx.set(dut.filter_mode, 0)
        await sample(ctx, 12 * 16, 16 * 16)  # left of the VALUE chip
        await sample(ctx, 20 * 16, 16 * 16)  # centered FB target

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

        # KNEE and CEILING panels occupy native x=[268,567).
        await sample(ctx, 268, 405)
        await sample(ctx, 260, 405)
        await sample(ctx, 566, 405)
        await sample(ctx, 574, 405)

        # DAMPING's native chip starts on the same physical x edge.
        await sample(ctx, 268, 470)
        await sample(ctx, 260, 470)

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


def test_tile_display_static_text_uses_expected_glyph_pixels():
    """Guard the synchronous text/glyph pipeline used at 720p60.

    Holding a coordinate lets every renderer pipeline stage settle without
    coupling this test to the surrounding DVI timing generator.  The two
    samples exercise an illuminated and a blank pixel in the fixed ``R`` of
    the REZO title.
    """
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
        samples.append((ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)))

    async def bench(ctx):
        # R row 0 is 11110: its first doubled pixel is on and its fifth is off.
        await sample(ctx, 32, 48)
        await sample(ctx, 40, 48)

    sim.add_testbench(bench)
    sim.run()

    text = RezoTileDisplay.PALETTE["text"]
    title_panel = RezoTileDisplay.PALETTE["background"]
    assert samples == [
        (text, text, text),
        (title_panel, title_panel, title_panel),
    ]


def test_tile_display_band_geometry_and_modulation_shading():
    """The shared band-column decoder retains the established pixel bounds."""
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
        # Eight-bit telemetry preserves every encoder step.  Values 64/96
        # occupy the former 16/24 positions in the established geometry.
        for enable in dut.band_enables:
            ctx.set(enable, 1)
        ctx.set(dut.levels[5], 64)
        ctx.set(dut.effective_levels[5], 96)
        # The column ROM intentionally prefetches x+1 to compensate for its
        # added value-selection stage in the streaming pixel pipeline.
        await sample(ctx, 387, 150)  # desired x=388: modulation extension
        await sample(ctx, 387, 250)  # desired x=388: base fill
        await sample(ctx, 376, 250)  # desired x=377: outside fill
        await sample(ctx, 418, 250)  # desired x=419: final included column
        await sample(ctx, 419, 250)  # desired x=420: first excluded column
        await sample(ctx, 387, 366)  # zero line
        await sample(ctx, 387, 500)  # empty band slot panel

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["modulation"],
        palette["control"],
        palette["background"],
        palette["control"],
        palette["background"],
        palette["line"],
        palette["panel"],
    ]


def test_bands_page_uses_two_visible_button_rows():
    """BANDS enable/frequency targets are discrete buttons, not tall faders."""
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
        ctx.set(dut.page, 6)
        ctx.set(dut.band_enables[0], 1)
        ctx.set(dut.band_enables[1], 0)

        await sample(ctx, 60, 250)   # enabled button fill
        await sample(ctx, 126, 250)  # disabled button panel
        await sample(ctx, 60, 330)   # empty gap between rows
        await sample(ctx, 60, 410)   # frequency button panel

        # Each row has its own selection outline; selecting ENABLE must not
        # produce an invisible outline spanning the frequency control.
        ctx.set(dut.selected, RezoHardwareUI.TARGET_BAND_ENABLE_BASE)
        await sample(ctx, 41, 250)
        await sample(ctx, 41, 410)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_BAND_FREQ_BASE)
        await sample(ctx, 41, 250)
        await sample(ctx, 41, 410)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["control"],
        palette["panel"],
        palette["background"],
        palette["panel"],
        palette["selected"],
        palette["background"],
        palette["background"],
        palette["selected"],
    ]


def test_bands_page_writes_all_five_frequency_digits():
    """The selected BANDS value is exact rather than a three-character abbreviation."""
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
        ctx.set(dut.page, 6)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_BAND_FREQ_BASE + 9)
        ctx.set(dut.band_frequencies[9], RezoCore.frequency_index(16000))
        # Let the initial low-rate text refresh reach the BANDS entries.
        # Dynamic labels use a three-phase ROM/capture/write pipeline.
        for _ in range(240):
            await ctx.tick("sync")

        # Row zero, center column is illuminated in every glyph of "16000".
        for cell in range(14, 19):
            await sample(ctx, cell * 16 + 4, 22 * 16)

    sim.add_testbench(bench)
    sim.run()

    text = RezoTileDisplay.PALETTE["text"]
    assert samples == [text] * 5


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
    """Maximum audio gain must stop before the compact lane's x=576 edge."""
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
        await sample(ctx, 550, 260)  # high gain still fills inside VALUE
        await sample(ctx, 580, 260)  # but never escapes past its x=576 box

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [palette["control"], palette["background"]]


def test_output_page_draws_standardized_header_selection_bars():
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
        ctx.set(dut.page, 4)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_OUTPUT_ROW_BASE)
        await sample(ctx, 28, 340)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_OUTPUT_COL_BASE)
        await sample(ctx, 220, 266)

    sim.add_testbench(bench)
    sim.run()

    assert samples == [RezoTileDisplay.PALETTE["selected"]] * 2


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


def test_tile_display_palette_maps_semantic_roles_to_rgb():
    """Changing themes recolors roles without changing their geometry."""
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
        samples.append((ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)))

    async def bench(ctx):
        # The first illuminated pixel of the R in REZO has the text role.
        for palette_id in range(len(dut.RGB_PALETTES)):
            ctx.set(dut.palette, palette_id)
            await sample(ctx, 32, 48)

    sim.add_testbench(bench)
    sim.run()

    expected = []
    text_role = dut.PALETTE_ROLES.index("text")
    for theme in dut.RGB_PALETTES:
        rgb = theme[text_role]
        expected.append(((rgb >> 16) & 0xff, (rgb >> 8) & 0xff, rgb & 0xff))
    assert samples == expected
