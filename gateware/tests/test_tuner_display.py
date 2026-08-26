from amaranth import Module, unsigned
from amaranth.hdl import Fragment
from amaranth.lib.memory import Memory
from amaranth.sim import Simulator

from top.tuner.display import FONT, FONT_CHARS, FONT_INDEX, Peripheral, TunerOverlay
from top.tuner.font_9x15 import MENU_FONT_BOLD, MENU_FONT_NORMAL


def test_tuner_font_contract():
    assert FONT_INDEX[" "] == 0
    assert len(FONT_CHARS) < 64
    assert len(set(FONT_CHARS)) == len(FONT_CHARS)
    assert all(char in FONT for char in FONT_CHARS)
    assert all(len(FONT[char]) == 7 for char in FONT_CHARS)
    assert all(0 <= row < 32 for char in FONT_CHARS for row in FONT[char])
    assert len(MENU_FONT_NORMAL) == 95 * 15
    assert len(MENU_FONT_BOLD) == 95 * 15
    assert all(0 <= row < 512 for row in MENU_FONT_NORMAL + MENU_FONT_BOLD)


def test_tuner_display_elaborates():
    # This catches accidental cross-domain memory-port conflicts and invalid
    # structured pixel expressions before the comparatively expensive FPGA build.
    Fragment.get(Peripheral(), platform=None)


def test_tuner_display_target_transforms_are_compile_time():
    async def check_border(ctx, dut, physical_x, physical_y):
        ctx.set(dut.i.de, 1)
        ctx.set(dut.menu_active, 1)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        ctx.set(dut.i.x, physical_x)
        ctx.set(dut.i.y, physical_y)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 10

    def run_target(*, h_active, rotate_left, physical_x, physical_y):
        tiles = Memory(
            shape=unsigned(6), depth=TunerOverlay.COLS * TunerOverlay.ROWS,
            init=[0] * (TunerOverlay.COLS * TunerOverlay.ROWS))
        menu = Memory(
            shape=unsigned(8),
            depth=TunerOverlay.MENU_COLS * TunerOverlay.MENU_ROWS,
            init=[0] * (TunerOverlay.MENU_COLS * TunerOverlay.MENU_ROWS))
        dut = TunerOverlay(
            tiles, menu, h_active=h_active, rotate_left=rotate_left)
        m = Module()
        m.submodules.dut = dut
        m.submodules.tiles = tiles
        m.submodules.menu = menu
        sim = Simulator(m)
        sim.add_clock(1e-6, domain="dvi")

        async def bench(ctx):
            await check_border(ctx, dut, physical_x, physical_y)

        sim.add_testbench(bench)
        sim.run()

    # Standard HDMI centers the native canvas at x=280 without rotation.
    run_target(
        h_active=1280, rotate_left=False,
        physical_x=TunerOverlay.MENU_X + 280, physical_y=400)
    # The production panel applies the inverse of its physical left rotation.
    run_target(
        h_active=720, rotate_left=True,
        physical_x=719 - 400, physical_y=TunerOverlay.MENU_X)


def test_tuner_display_composites_framebuffer_marker_and_menu():
    tiles = Memory(
        shape=unsigned(6), depth=TunerOverlay.COLS * TunerOverlay.ROWS,
        init=[0] * (TunerOverlay.COLS * TunerOverlay.ROWS))
    menu = Memory(
        shape=unsigned(8),
        depth=TunerOverlay.MENU_COLS * TunerOverlay.MENU_ROWS,
        init=[0] * (TunerOverlay.MENU_COLS * TunerOverlay.MENU_ROWS))
    dut = TunerOverlay(tiles, menu)
    m = Module()
    m.submodules.dut = dut
    m.submodules.tiles = tiles
    m.submodules.menu = menu
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        ctx.set(dut.i.de, 1)

        # Static guide pixels arrive from the retained PSRAM framebuffer and
        # pass through the live overlay unchanged.
        ctx.set(dut.i.pixel.color, 9)
        ctx.set(dut.i.pixel.intensity, 5)
        ctx.set(dut.i.x, 360)
        ctx.set(dut.i.y, 360 - 52)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 5

        # An eighth-turn later, the guide has moved smoothly clockwise and
        # outward rather than remaining on the C0 circle.
        ctx.set(dut.i.x, 399)
        ctx.set(dut.i.y, 321)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 5

        # Consecutive samples on the outer turn are several pixels apart. The
        # connecting raster must fill their midpoint rather than showing dots.
        ctx.set(dut.i.x, 572)
        ctx.set(dut.i.y, 356)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 5

        # Background pixels pass through as black.
        ctx.set(dut.i.pixel.intensity, 0)
        ctx.set(dut.i.x, 393)
        ctx.set(dut.i.y, 400)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 0

        # The modal menu masks only its established right-side panel while leaving the live
        # tuner visible around it.
        ctx.set(dut.menu_active, 1)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        ctx.set(dut.i.x, 500)
        ctx.set(dut.i.y, 400)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 0

        # A retained radial tick outside the box remains live.
        ctx.set(dut.i.pixel.intensity, 2)
        ctx.set(dut.i.x, 477)
        ctx.set(dut.i.y, 157)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 2

        # The panel border is procedural and does not depend on stale tiles.
        ctx.set(dut.i.x, TunerOverlay.MENU_X)
        ctx.set(dut.i.y, 400)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 10
        ctx.set(dut.menu_active, 0)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)

        # Closing the menu reveals the retained guide again.
        ctx.set(dut.i.x, 477)
        ctx.set(dut.i.y, 157)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 2

        # Retained radial divisions continue through the center.
        ctx.set(dut.i.x, 360)
        ctx.set(dut.i.y, 360)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 2

        # ARC mode highlights a short run of the actual spiral around the
        # detected pitch rather than drawing an unrelated cursor shape.
        ctx.set(dut.marker_x, 492)
        ctx.set(dut.marker_y, 228)
        ctx.set(dut.marker_hue, 2)
        ctx.set(dut.marker_valid, 1)
        ctx.set(dut.marker_visualizer, 0)
        ctx.set(dut.marker_lens_base, 8 * 33 * 33)  # 45-degree tangent
        ctx.set(dut.marker_lens_bank, 0)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        # Analytical mode renders a filled, rounded lens centered on the stored
        # spiral rather than only recoloring its thin centerline.
        ctx.set(dut.i.x, 492)
        ctx.set(dut.i.y, 228)
        ctx.set(dut.i.pixel.intensity, 5)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 15

        # The long axis follows the 45-degree tangent.
        ctx.set(dut.i.x, 501)
        ctx.set(dut.i.y, 237)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 15

        # The perpendicular axis remains narrow enough not to touch the next
        # octave band. This also guards against screen-axis widening artifacts.
        ctx.set(dut.i.x, 501)
        ctx.set(dut.i.y, 219)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) != 15

        # Exercise consecutive pixels as HDMI does, instead of holding each
        # coordinate for the complete pipeline. The latter masked a bank/data
        # phase error in a cascaded synchronous ROM and allowed the filled lens
        # to fragment into horizontal slats on hardware.
        ctx.set(dut.marker_lens_base, 0)  # horizontal major axis
        ctx.set(dut.marker_lens_bank, 0)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        white_by_row = {}
        for y in range(210, 247):
            for x in range(470, 515):
                ctx.set(dut.i.x, x)
                ctx.set(dut.i.y, y)
                await ctx.tick("dvi")
                out_x = ctx.get(dut.o.x)
                out_y = ctx.get(dut.o.y)
                if (470 <= out_x < 515 and 210 <= out_y < 247 and
                        ctx.get(dut.o.pixel.intensity) == 15):
                    white_by_row.setdefault(out_y, set()).add(out_x)
        await ctx.tick("dvi").repeat(4)
        center = sorted(white_by_row[228])
        assert len(center) >= 31
        assert center[-1] - center[0] + 1 == len(center)
        assert all(white_by_row.get(y) for y in range(221, 236))

        # VISUALIZER mode provides a rounded, layered halo independent of the
        # static guide, with the middle band deliberately softer than its core.
        ctx.set(dut.marker_x, 500)
        ctx.set(dut.marker_y, 250)
        ctx.set(dut.marker_visualizer, 1)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        ctx.set(dut.i.x, 510)
        ctx.set(dut.i.y, 250)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 8

        # The square corner is outside the official panel's circular viewport.
        ctx.set(dut.i.pixel.intensity, 0)
        ctx.set(dut.i.x, 0)
        ctx.set(dut.i.y, 0)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 0

    sim.add_testbench(bench)
    sim.run()
