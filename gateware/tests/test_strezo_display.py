from amaranth.sim import Simulator

from top.rezo.strezo_variant import RezoCore, RezoHardwareUI, RezoTileDisplay


def test_tile_display_static_text_uses_expected_glyph_pixels():
    """Guard the synchronous text/glyph pipeline used at 720p60.

    Holding a coordinate lets every renderer pipeline stage settle without
    coupling this test to the surrounding DVI timing generator.  The two
    samples exercise a blank and an illuminated pixel in the fixed ``S`` of
    the STREZO title.
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
        # S row 0 leaves its first doubled pixel off and illuminates its fifth.
        await sample(ctx, 32, 48)
        await sample(ctx, 40, 48)

    sim.add_testbench(bench)
    sim.run()

    text = RezoTileDisplay.PALETTE["text"]
    title_panel = RezoTileDisplay.PALETTE["background"]
    assert samples == [
        (title_panel, title_panel, title_panel),
        (text, text, text),
    ]


def test_round_display_rotates_scan_coordinates_into_logical_panel_space():
    """The official square panel uses the production framebuffer rotation."""
    dut = RezoTileDisplay(h_active=720, rotate_left=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def sample(ctx, scan_x, scan_y):
        ctx.set(dut.x, scan_x)
        ctx.set(dut.y, scan_y)
        ctx.set(dut.de, 1)
        for _ in range(8):
            await ctx.tick("dvi")
        samples.append((ctx.get(dut.r), ctx.get(dut.g), ctx.get(dut.b)))

    async def bench(ctx):
        # Logical title coordinates (32,48) and (40,48) become scan
        # coordinates (671,32) and (671,40) after a left rotation.
        await sample(ctx, 671, 32)
        await sample(ctx, 671, 40)

    sim.add_testbench(bench)
    sim.run()

    text = RezoTileDisplay.PALETTE["text"]
    title_panel = RezoTileDisplay.PALETTE["background"]
    assert samples == [
        (title_panel, title_panel, title_panel),
        (text, text, text),
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
        # STREZO's extra band-value selection stage makes the first sample in
        # a simulation require a few more clocks than subsequent pixels.
        for _ in range(12):
            await ctx.tick("dvi")
        samples.append(ctx.get(dut.r))

    async def bench(ctx):
        # Band 5 spans x=378..419. The 8-bit display path retains individual
        # UI steps; use a larger synthetic effective value to expose the
        # modulation extension independently of the normal audio clamp.
        for enable in dut.band_enables:
            ctx.set(enable, 1)
        ctx.set(dut.levels[5], 48)
        ctx.set(dut.effective_levels[5], 80)
        # The column ROM intentionally prefetches x+1 to compensate for its
        # added value-selection stage in the streaming pixel pipeline.
        await sample(ctx, 387, 180)  # desired x=388: modulation extension
        await sample(ctx, 387, 280)  # desired x=388: base fill
        await sample(ctx, 376, 280)  # desired x=377: outside fill
        await sample(ctx, 418, 280)  # desired x=419: final included column
        await sample(ctx, 419, 280)  # desired x=420: first excluded column
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

        await sample(ctx, 60, 234)   # enabled button fills full height
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
        palette["control"],
        palette["panel"],
        palette["background"],
        palette["panel"],
        palette["selected"],
        palette["background"],
        palette["background"],
        palette["selected"],
    ]


def test_feedback_page_uses_compact_band_buttons():
    """Feedback sends are buttons rather than BANK-height columns."""
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
        ctx.set(dut.page, 1)
        for enable in dut.band_enables:
            ctx.set(enable, 1)
        ctx.set(dut.feedback_sends[0], 1)
        ctx.set(dut.feedback_sends[1], 0)

        await sample(ctx, 60, 250)   # included send button
        await sample(ctx, 126, 250)  # excluded send button
        await sample(ctx, 60, 400)   # former tall-column interior

        ctx.set(dut.selected, RezoHardwareUI.TARGET_FEEDBACK_SEND_BASE)
        await sample(ctx, 41, 250)   # compact selection outline
        await sample(ctx, 41, 400)   # no tall selection outline

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["control"], palette["panel"], palette["background"],
        palette["selected"], palette["background"],
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
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_LEFT)
        ctx.set(dut.input_meters[0], 20)
        ctx.set(dut.input_modes[1], RezoCore.INPUT_MODE_CV)
        ctx.set(dut.input_meters[1], -10)

        # Audio starts at x=326 and grows right. CV is bipolar about x=490.
        await sample(ctx, 400, 259)
        await sample(ctx, 550, 259)
        await sample(ctx, 460, 355)
        await sample(ctx, 520, 355)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["modulation"], palette["background"],
        palette["modulation"], palette["background"],
    ]


def test_routing_pages_draw_standardized_header_selection_bars():
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
        await sample(ctx, 28, 340)   # OUTPUT OUT0 left bar
        ctx.set(dut.selected, RezoHardwareUI.TARGET_OUTPUT_COL_BASE)
        await sample(ctx, 220, 266)  # OUTPUT GRP1 top bar

        ctx.set(dut.page, 7)
        ctx.set(dut.cross_layout, RezoCore.CROSS_LAYOUT_DIAGONAL)
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CROSS_ROW_BASE)
        await sample(ctx, 74, 340)   # CROSS FROM G1 left bar
        ctx.set(dut.selected, RezoHardwareUI.TARGET_CROSS_COL_BASE)
        await sample(ctx, 220, 250)  # CROSS TO G1 top bar

    sim.add_testbench(bench)
    sim.run()

    assert samples == [RezoTileDisplay.PALETTE["selected"]] * 4


def test_bands_page_draws_two_column_motion_controls():
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
        ctx.set(dut.motion_depth, 32)
        await sample(ctx, 200, 536)  # SOURCE chip, left column
        await sample(ctx, 200, 600)  # RATE chip, left column
        await sample(ctx, 520, 536)  # PHASE chip, right column
        await sample(ctx, 520, 600)  # DEPTH fill, right column
        await sample(ctx, 620, 600)  # unfilled depth track

        ctx.set(dut.selected, RezoHardwareUI.TARGET_MOTION_DEPTH)
        await sample(ctx, 508, 600)  # large-fader edit marker

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["panel"], palette["panel"], palette["panel"],
        palette["control"], palette["panel"], palette["selected"],
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
        for _ in range(80):
            await ctx.tick("sync")

        # Row zero, center column is illuminated in every glyph of "16000".
        for cell in range(14, 19):
            await sample(ctx, cell * 16 + 4, 22 * 16)

    sim.add_testbench(bench)
    sim.run()

    text = RezoTileDisplay.PALETTE["text"]
    assert samples == [text] * 5


def test_feedback_damp_is_a_named_discrete_selector():
    """DAMP uses a compact named button instead of a misleading fader."""
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
        ctx.set(dut.page, 1)
        ctx.set(dut.damp_mode, 4)
        # Initial text refresh writes left-aligned "MAX" in the fixed slot.
        for _ in range(48):
            await ctx.tick("sync")
        await sample(ctx, 212, 32 * 16)  # illuminated center of the A
        await sample(ctx, 220, 512)      # compact button panel
        await sample(ctx, 400, 512)      # no full-width DAMP meter
        ctx.set(dut.selected, RezoHardwareUI.TARGET_DAMP)
        await sample(ctx, 150, 512)      # visible button selection outline

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["text"], palette["panel"],
        palette["background"], palette["selected"],
    ]


def test_feedback_safety_faders_are_compact_and_moved_below_band_buttons():
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
        ctx.set(dut.page, 1)
        ctx.set(dut.limit_knee, 64)
        ctx.set(dut.limit_cap, 128)
        await sample(ctx, 250, 420)  # KNEE fill
        await sample(ctx, 400, 420)  # KNEE track beyond fill
        await sample(ctx, 400, 468)  # CEILING fill
        await sample(ctx, 500, 560)  # old lower-fader area is empty

        ctx.set(dut.selected, RezoHardwareUI.TARGET_LIMIT_KNEE)
        await sample(ctx, 144, 420)  # standard large-fader edit marker

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["control"], palette["panel"], palette["control"],
        palette["background"], palette["selected"],
    ]


def test_bands_motion_rate_label_supports_decimal_point():
    """RATE uses readable decimal Hz text rather than a blank glyph."""
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
        ctx.set(dut.motion_rate, 8)
        for _ in range(100):
            await ctx.tick("sync")
        # RATE " 0.8" begins at cell 12; the decimal's bottom row is lit.
        await sample(ctx, 14 * 16 + 4, 37 * 16 + 12)

    sim.add_testbench(bench)
    sim.run()

    assert samples == [RezoTileDisplay.PALETTE["text"]]


def test_group_geometry_rom_decodes_every_band_and_row():
    """The BRAM coordinate decoder preserves all forty GROUPS cells."""
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
        ctx.set(dut.page, 3)
        for band in range(RezoCore.N_BANDS):
            ctx.set(dut.band_enables[band], 1)
            ctx.set(dut.bank_groups[band], 1 << (band % RezoCore.N_GROUPS))
        for group in range(RezoCore.N_GROUPS):
            for band in range(RezoCore.N_BANDS):
                await sample(ctx, 150 + band * 48, 300 + group * 64)

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    expected = []
    for group in range(RezoCore.N_GROUPS):
        for band in range(RezoCore.N_BANDS):
            expected.append(
                palette["control"] if band % RezoCore.N_GROUPS == group
                else palette["background"])
    assert samples == expected


def test_cross_matrix_selection_tracks_all_four_rows():
    """CROSS cell target IDs advance four columns per displayed row."""
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
        ctx.set(dut.page, 7)
        ctx.set(dut.cross_layout, RezoCore.CROSS_LAYOUT_DIAGONAL)
        for row in range(4):
            for column in range(4):
                ctx.set(
                    dut.selected,
                    RezoHardwareUI.TARGET_CROSS_MATRIX_BASE + row * 4 + column)
                await sample(ctx, 188 + column * 96, 336 + row * 80)

    sim.add_testbench(bench)
    sim.run()

    selected = RezoTileDisplay.PALETTE["selected"]
    assert samples == [selected] * 16


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
        # An illuminated pixel of the S in STREZO has the text role.
        for palette_id in range(len(dut.RGB_PALETTES)):
            ctx.set(dut.palette, palette_id)
            await sample(ctx, 40, 48)

    sim.add_testbench(bench)
    sim.run()

    expected = []
    text_role = dut.PALETTE_ROLES.index("text")
    for theme in dut.RGB_PALETTES:
        rgb = theme[text_role]
        expected.append(((rgb >> 16) & 0xff, (rgb >> 8) & 0xff, rgb & 0xff))
    assert samples == expected
