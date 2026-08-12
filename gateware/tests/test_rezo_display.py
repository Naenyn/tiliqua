from amaranth import Module
from amaranth.sim import Simulator

from top.rezo.top import RezoCore, RezoHardwareUI, RezoTileDisplay


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


def test_compact_labels_use_inner_gutter_and_scaled_control_rows():
    """Compact text remains inside the field and tracks scaled geometry."""
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

        # BANK labels share the x=272 right edge of the fader gutter.
        await sample(ctx, 12 * 16, 448)       # DRIVE
        await sample(ctx, 10 * 16, 448)       # old, too-far-left start

        # FILTER's deepest row remains on the content background, and its
        # first label begins on the same inner gutter as MATRIX.
        ctx.set(dut.filter_mode, 1)
        await sample(ctx, 8 * 16, 448)        # FREQUENCY
        await sample(ctx, 160, 592)          # below RESONANCE, inside field

        # MATRIX row rounding follows the scaled 80-logical-pixel cadence.
        ctx.set(dut.page, 2)
        await sample(ctx, 8 * 16, 17 * 16)   # FREQUENCY

        # Dynamic INPUT targets align with the MODE/value chip and AUD fader.
        ctx.set(dut.filter_mode, 0)
        await sample(ctx, 17 * 16, 19 * 16)  # explicit gap
        await sample(ctx, 18 * 16, 19 * 16)  # FB target

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
    """INPUT gaps stay blank and BANDS uses the FEEDBACK button treatment."""
    dut = RezoTileDisplay(
        h_active=720, rotate_left=False, compact_layout=True)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    def physical(logical):
        # First physical pixel whose compact lookup reaches ``logical``.
        return 106 + (logical * 508 + 719) // 720

    async def sample(ctx, logical_x, logical_y):
        ctx.set(dut.x, physical(logical_x))
        ctx.set(dut.y, physical(logical_y))
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

    async def bench(ctx):
        ctx.set(dut.page, 2)
        ctx.set(dut.input_modes[0], RezoCore.INPUT_MODE_AUDIO)
        ctx.set(dut.input_modes[1], RezoCore.INPUT_MODE_CV)
        for _ in range(260):
            await ctx.tick("sync")
        await sample(ctx, 300, 307)  # AUD DEPTH is hidden.
        await sample(ctx, 300, 336)  # inter-input gap
        await sample(ctx, 300, 419)  # CV DEPTH panel remains visible.
        await sample_native(ctx, 8 * 16, 20 * 16)  # AUD DEPTH label hidden.
        await sample_native(ctx, 8 * 16, 25 * 16)  # CV DEPTH label visible.

        ctx.set(dut.page, 1)
        ctx.set(dut.band_enables[0], 1)
        ctx.set(dut.feedback_sends[0], 1)
        await sample(ctx, 60, 253)   # FEEDBACK full-height button fill
        ctx.set(dut.page, 6)
        ctx.set(dut.band_enables[0], 1)
        await sample(ctx, 60, 253)   # BANDS now matches FEEDBACK

    sim.add_testbench(bench)
    sim.run()

    palette = RezoTileDisplay.PALETTE
    assert samples == [
        palette["background"], palette["background"], palette["panel"],
        palette["background"], palette["text"],
        palette["control"], palette["control"],
    ]


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
