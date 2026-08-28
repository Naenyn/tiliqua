"""Display behavior shared by two or more REZO-family products."""

import pytest
from amaranth.sim import Simulator

from rezo_display_support import sample_panel_rgb
from top.rezo.display_common import RGB_PALETTES
from top.rezo.rezo_variant import RezoTileDisplay
from top.rezo.strezo_variant import RezoTileDisplay as StrezoTileDisplay
from top.rezo.top import RezoTileDisplay as RezomoTileDisplay
from top.rezo.ui_common import PALETTE_NAMES


ALL_FAMILY_DISPLAYS = (
    pytest.param(RezoTileDisplay, id="rezo"),
    pytest.param(RezomoTileDisplay, id="rezomo"),
    pytest.param(StrezoTileDisplay, id="strezo"),
)
def test_family_palette_store_fills_all_three_bit_theme_addresses():
    assert PALETTE_NAMES == (
        "LCD   ", "AMBER ", "CYAN  ", "GREEN ",
        "VIOLET", "EMBER ", "NEON  ", "AZURE ",
    )
    assert len(RGB_PALETTES) == len(PALETTE_NAMES) == 8
    assert all(len(theme) == 8 for theme in RGB_PALETTES)


def make_sim(display_type):
    dut = display_type(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    return dut, sim


@pytest.mark.parametrize("display_type", ALL_FAMILY_DISPLAYS)
def test_native_preview_uses_round_panel_edge_not_safe_square(display_type):
    dut = display_type(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        # Cardinal points touch the 720x720 canvas boundary. Every family
        # member leaves the former guide unrendered, then begins its dark arc
        # fill just inside it. The 508x508 content square remains black.
        for x, y in ((0, 359), (1, 359), (2, 359),
                     (719, 360), (718, 360), (717, 360),
                     (359, 0), (359, 1), (359, 2),
                     (360, 719), (360, 718), (360, 717),
                     (106, 300), (613, 300),
                     (300, 106), (300, 613)):
            samples.append((await sample_panel_rgb(ctx, dut, x, y))[0])

    sim.add_testbench(bench)
    sim.run()

    blank = display_type.PALETTE["blank"]
    background = display_type.PALETTE["background"]
    assert samples == [
        blank, blank, background,
        blank, blank, background,
        blank, blank, background,
        blank, blank, background,
        blank, blank, blank, blank,
    ]


@pytest.mark.parametrize("display_type", ALL_FAMILY_DISPLAYS)
def test_main_and_bands_preset_chips_share_the_same_left_origin(display_type):
    dut = display_type(h_active=1280)
    sim = Simulator(dut)
    sim.add_clock(1e-6, domain="sync")
    sim.add_clock(1e-6, domain="dvi")
    samples = []

    async def bench(ctx):
        for page, x1 in ((0, 328), (6, 368)):
            ctx.set(dut.page, page)
            for x in (239, 240, x1 - 1, x1):
                # Sample below the row-11 glyphs so the chip boundary, rather
                # than the PRESET/layout text, determines the pixel color.
                samples.append((await sample_panel_rgb(ctx, dut, x, 214))[0])

    sim.add_testbench(bench)
    sim.run()

    palette = display_type.PALETTE
    assert samples == [
        palette["blank"], palette["panel"],
        palette["panel"], palette["blank"],
    ] * 2
