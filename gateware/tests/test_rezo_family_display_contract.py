"""Display behavior shared by two or more REZO-family products."""

import pytest
from amaranth.sim import Simulator

from rezo_display_support import sample_panel_rgb
from top.rezo.rezo_variant import RezoCore, RezoHardwareUI, RezoTileDisplay
from top.rezo.strezo_variant import RezoTileDisplay as StrezoTileDisplay
from top.rezo.top import RezoCore as RezomoCore
from top.rezo.top import RezoHardwareUI as RezomoHardwareUI
from top.rezo.top import RezoTileDisplay as RezomoTileDisplay


REZO_AND_REZOMO = (
    pytest.param(RezoCore, RezoHardwareUI, RezoTileDisplay, id="rezo"),
    pytest.param(RezomoCore, RezomoHardwareUI, RezomoTileDisplay, id="rezomo"),
)
REZO_AND_REZOMO_DISPLAYS = (
    pytest.param(RezoTileDisplay, id="rezo"),
    pytest.param(RezomoTileDisplay, id="rezomo"),
)
REZOMO_AND_STREZO_DISPLAYS = (
    pytest.param(RezomoTileDisplay, id="rezomo"),
    pytest.param(StrezoTileDisplay, id="strezo"),
)
REZO_AND_REZOMO_UI_DISPLAYS = (
    pytest.param(RezoHardwareUI, RezoTileDisplay, id="rezo"),
    pytest.param(RezomoHardwareUI, RezomoTileDisplay, id="rezomo"),
)


def make_sim(display_type):
    dut = display_type(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    return dut, sim


@pytest.mark.parametrize("display_type", REZO_AND_REZOMO_DISPLAYS)
def test_tile_display_static_text_uses_expected_glyph_pixels(display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def bench(ctx):
        samples.append(await sample_panel_rgb(ctx, dut, 32, 48))
        samples.append(await sample_panel_rgb(ctx, dut, 40, 48))

    sim.add_testbench(bench)
    sim.run()

    text = display_type.PALETTE["text"]
    background = display_type.PALETTE["background"]
    assert samples == [
        (text, text, text),
        (background, background, background),
    ]


@pytest.mark.parametrize("display_type", REZO_AND_REZOMO_DISPLAYS)
def test_tile_display_band_geometry_and_modulation_shading(display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def sample(ctx, x, y):
        samples.append((await sample_panel_rgb(ctx, dut, x, y))[0])

    async def bench(ctx):
        for enable in dut.band_enables:
            ctx.set(enable, 1)
        ctx.set(dut.levels[5], 64)
        ctx.set(dut.effective_levels[5], 96)
        await sample(ctx, 387, 150)
        await sample(ctx, 387, 250)
        await sample(ctx, 376, 250)
        await sample(ctx, 418, 250)
        await sample(ctx, 419, 250)
        await sample(ctx, 387, 366)
        await sample(ctx, 387, 500)

    sim.add_testbench(bench)
    sim.run()

    palette = display_type.PALETTE
    assert samples == [
        palette["modulation"], palette["control"], palette["background"],
        palette["control"], palette["background"], palette["line"],
        palette["panel"],
    ]


@pytest.mark.parametrize("ui_type, display_type",
                         REZO_AND_REZOMO_UI_DISPLAYS)
def test_bands_page_uses_two_visible_button_rows(ui_type, display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def sample(ctx, x, y):
        samples.append((await sample_panel_rgb(ctx, dut, x, y))[0])

    async def bench(ctx):
        ctx.set(dut.page, 6)
        ctx.set(dut.band_enables[0], 1)
        ctx.set(dut.band_enables[1], 0)
        await sample(ctx, 60, 250)
        await sample(ctx, 126, 250)
        await sample(ctx, 60, 330)
        await sample(ctx, 60, 410)

        ctx.set(dut.selected, ui_type.TARGET_BAND_ENABLE_BASE)
        await sample(ctx, 41, 250)
        await sample(ctx, 41, 410)
        ctx.set(dut.selected, ui_type.TARGET_BAND_FREQ_BASE)
        await sample(ctx, 41, 250)
        await sample(ctx, 41, 410)

    sim.add_testbench(bench)
    sim.run()

    palette = display_type.PALETTE
    assert samples == [
        palette["control"], palette["panel"], palette["background"],
        palette["panel"], palette["selected"], palette["background"],
        palette["background"], palette["selected"],
    ]


@pytest.mark.parametrize("core_type, ui_type, display_type", REZO_AND_REZOMO)
def test_bands_page_writes_all_five_frequency_digits(core_type, ui_type,
                                                      display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, 6)
        ctx.set(dut.selected, ui_type.TARGET_BAND_FREQ_BASE + 9)
        ctx.set(dut.band_frequencies[9], core_type.frequency_index(16000))
        for _ in range(240):
            await ctx.tick("sync")
        for cell in range(14, 19):
            samples.append((await sample_panel_rgb(
                ctx, dut, cell * 16 + 4, 22 * 16))[0])

    sim.add_testbench(bench)
    sim.run()

    assert samples == [display_type.PALETTE["text"]] * 5


@pytest.mark.parametrize("display_type", REZOMO_AND_STREZO_DISPLAYS)
def test_disabled_band_has_bank_ghosts(display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def sample(ctx, x, y):
        samples.append((await sample_panel_rgb(ctx, dut, x, y))[0])

    async def bench(ctx):
        ctx.set(dut.levels[0], 16)
        ctx.set(dut.effective_levels[0], 16)
        ctx.set(dut.band_enables[0], 0)
        await sample(ctx, 42, 300)
        await sample(ctx, 60, 300)
        ctx.set(dut.page, 3)
        await sample(ctx, 150, 294)
        await sample(ctx, 150, 300)

    sim.add_testbench(bench)
    sim.run()

    palette = display_type.PALETTE
    assert samples == [
        palette["line"], palette["background"],
        palette["line"], palette["background"],
    ]


@pytest.mark.parametrize("display_type", REZOMO_AND_STREZO_DISPLAYS)
def test_tile_display_drive_modulation_shading(display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def sample(ctx, x, y):
        samples.append((await sample_panel_rgb(ctx, dut, x, y))[0])

    async def bench(ctx):
        ctx.set(dut.drive, 64)
        ctx.set(dut.effective_drive, 96)
        await sample(ctx, 300, 560)
        await sample(ctx, 450, 560)
        await sample(ctx, 380, 554)

    sim.add_testbench(bench)
    sim.run()

    palette = display_type.PALETTE
    assert samples == [
        palette["control"], palette["modulation"], palette["line"],
    ]


@pytest.mark.parametrize("ui_type, display_type",
                         REZO_AND_REZOMO_UI_DISPLAYS)
def test_output_page_draws_standardized_header_selection_bars(
        ui_type, display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def bench(ctx):
        ctx.set(dut.page, 4)
        ctx.set(dut.selected, ui_type.TARGET_OUTPUT_ROW_BASE)
        samples.append((await sample_panel_rgb(ctx, dut, 28, 340))[0])
        ctx.set(dut.selected, ui_type.TARGET_OUTPUT_COL_BASE)
        samples.append((await sample_panel_rgb(ctx, dut, 220, 266))[0])

    sim.add_testbench(bench)
    sim.run()

    assert samples == [display_type.PALETTE["selected"]] * 2


@pytest.mark.parametrize("display_type", REZO_AND_REZOMO_DISPLAYS)
def test_tile_display_palette_maps_semantic_roles_to_rgb(display_type):
    dut, sim = make_sim(display_type)
    samples = []

    async def bench(ctx):
        for palette_id in range(len(dut.RGB_PALETTES)):
            ctx.set(dut.palette, palette_id)
            samples.append(await sample_panel_rgb(ctx, dut, 32, 48))

    sim.add_testbench(bench)
    sim.run()

    expected = []
    text_role = dut.PALETTE_ROLES.index("text")
    for theme in dut.RGB_PALETTES:
        rgb = theme[text_role]
        expected.append(((rgb >> 16) & 0xff, (rgb >> 8) & 0xff, rgb & 0xff))
    assert samples == expected
