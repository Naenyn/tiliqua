"""Palette colors and timing stay aligned through CPU updates and blanking."""
from amaranth.sim import Simulator
from tiliqua.video.palette import ColorPalette, compute_color_palette


def test_palette_preserves_one_pixel_latency_and_cpu_updates():
    dut = ColorPalette()
    sim = Simulator(dut)
    sim.add_clock(1 / 60e6, domain="sync")
    sim.add_clock(1 / 74.25e6, domain="dvi")
    initial = list(zip(*compute_color_palette()))
    custom = [(0, 0, 0) if n == 0 else
              ((n * 3) % 256, (n * 7) % 256, (n * 11) % 256)
              for n in range(256)]

    async def check_pixels(ctx, colors):
        # Include sharp changes between black, bright guides and E/F key tags,
        # and transitions into/out of video blanking on each iteration.
        pixels = [0, 0x69, 0, 0xE0, 0xF0, 0, 0xEB, 0xFB, 0xFF] + list(range(256))
        for n, pixel in enumerate(pixels):
            de, hs, vs = int(n % 7 != 0), int(n % 3 == 0), int(n % 11 == 0)
            ctx.set(dut.i.pixel.as_value(), pixel)
            ctx.set(dut.i.de, de); ctx.set(dut.i.hsync, hs); ctx.set(dut.i.vsync, vs)
            await ctx.tick("dvi")
            assert tuple(ctx.get(getattr(dut.o, c)) for c in ("r", "g", "b")) == colors[pixel]
            assert (ctx.get(dut.o.de), ctx.get(dut.o.hsync), ctx.get(dut.o.vsync)) == (de, hs, vs)

    async def bench(ctx):
        await check_pixels(ctx, initial)
        ctx.set(dut.i.de, 0)
        for n, (r, g, b) in enumerate(custom):
            ctx.set(dut.update.payload.position, n)
            ctx.set(dut.update.payload.red, r)
            ctx.set(dut.update.payload.green, g)
            ctx.set(dut.update.payload.blue, b)
            ctx.set(dut.update.valid, 1)
            await ctx.tick("sync")
        ctx.set(dut.update.valid, 0)
        await ctx.tick("dvi").repeat(2)
        await check_pixels(ctx, custom)

    sim.add_testbench(bench)
    sim.run()
