from amaranth.sim import Simulator

from top.rezo.top import RezoCore, RezoHardwareUI, RezoTileDisplay


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
        # Band 5 spans x=378..419. A base value of 16 reaches y=190;
        # its effective value of 24 reaches y=102.
        for enable in dut.band_enables:
            ctx.set(enable, 1)
        ctx.set(dut.levels[5], 16)
        ctx.set(dut.effective_levels[5], 24)
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
        for _ in range(80):
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
        ctx.set(dut.levels[0], 16)
        ctx.set(dut.effective_levels[0], 16)
        ctx.set(dut.band_enables[0], 0)
        await sample(ctx, 42, 300)  # ghost frame edge
        await sample(ctx, 60, 300)  # blank frame interior

        ctx.set(dut.filter_mode, 1)
        await sample(ctx, 60, 300)  # FILTER column remains active

        ctx.set(dut.filter_mode, 0)
        ctx.set(dut.page, 3)
        await sample(ctx, 144, 300)  # disabled group-cell frame edge
        await sample(ctx, 150, 300)  # empty group-cell interior

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
        ctx.set(dut.drive, 16)
        ctx.set(dut.effective_drive, 24)

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
