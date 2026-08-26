from amaranth import Module, unsigned
from amaranth.hdl import Fragment
from amaranth.lib.memory import Memory
from amaranth.sim import Simulator

from top.tuner.display import FONT, FONT_CHARS, FONT_INDEX, Peripheral, TunerOverlay


def test_tuner_font_contract():
    assert FONT_INDEX[" "] == 0
    assert len(FONT_CHARS) < 64
    assert len(set(FONT_CHARS)) == len(FONT_CHARS)
    assert all(char in FONT for char in FONT_CHARS)
    assert all(len(FONT[char]) == 7 for char in FONT_CHARS)
    assert all(0 <= row < 32 for char in FONT_CHARS for row in FONT[char])


def test_tuner_display_elaborates():
    # This catches accidental cross-domain memory-port conflicts and invalid
    # structured pixel expressions before the comparatively expensive FPGA build.
    Fragment.get(Peripheral(), platform=None)


def test_tuner_display_regenerates_guide_and_clips_corners():
    tiles = Memory(
        shape=unsigned(6), depth=TunerOverlay.COLS * TunerOverlay.ROWS,
        init=[0] * (TunerOverlay.COLS * TunerOverlay.ROWS))
    dut = TunerOverlay(tiles)
    m = Module()
    m.submodules.dut = dut
    m.submodules.tiles = tiles
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="dvi")

    async def bench(ctx):
        ctx.set(dut.i.de, 1)

        # The pitch guide begins at C0 and winds continuously outward by one
        # revolution per octave.
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

        # A point on the former 52-pixel circle is no longer a guide pixel: the
        # spiral has already expanded at this angle.
        ctx.set(dut.i.x, 393)
        ctx.set(dut.i.y, 400)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 0

        # The on-screen options menu owns the canvas while active, so the
        # underlying spiral cannot compete visually with its text.
        ctx.set(dut.menu_active, 1)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        ctx.set(dut.i.x, 360)
        ctx.set(dut.i.y, 360 - 52)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 0
        ctx.set(dut.menu_active, 0)
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)

        # The C# tick is rasterized at an exact 30-degree chromatic division.
        ctx.set(dut.i.x, 477)
        ctx.set(dut.i.y, 157)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 2

        # Radial divisions continue through the center rather than stopping at
        # the outermost octave ring.
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
        ctx.set(dut.i.vsync, 1)
        await ctx.tick("dvi").repeat(4)
        ctx.set(dut.i.vsync, 0)
        # Analytical mode renders a filled, rounded lens centered on the stored
        # spiral rather than only recoloring its thin centerline.
        ctx.set(dut.marker_lens_base, 8 * 33 * 33)  # 45-degree tangent
        ctx.set(dut.marker_lens_bank, 0)
        ctx.set(dut.i.x, 492)
        ctx.set(dut.i.y, 228)
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
        ctx.set(dut.i.x, 0)
        ctx.set(dut.i.y, 0)
        await ctx.tick("dvi").repeat(5)
        assert ctx.get(dut.o.pixel.intensity) == 0

    sim.add_testbench(bench)
    sim.run()
