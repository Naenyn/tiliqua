import unittest

from amaranth.sim import Simulator
from amaranth_soc import wishbone

from tiliqua.raster.span import PackedSpanWriter, TriangleSpanRasterizer
from tiliqua.video.types import Rotation


def transform_triangle(vertices, rotation, width, height):
    result = []
    for x, y in vertices:
        if rotation == Rotation.NORMAL:
            result.append((x, y))
        elif rotation == Rotation.LEFT:
            result.append((width - 1 - y, x))
        elif rotation == Rotation.INVERTED:
            result.append((width - 1 - x, height - 1 - y))
        else:
            result.append((y, height - 1 - x))
    return result


def reference_pixels(vertices, width, height):
    def edge(a, b, point):
        return ((point[0] - a[0]) * (b[1] - a[1]) -
                (point[1] - a[1]) * (b[0] - a[0]))

    pixels = set()
    for y in range(height):
        for x in range(width):
            values = [
                edge(vertices[0], vertices[1], (x, y)),
                edge(vertices[1], vertices[2], (x, y)),
                edge(vertices[2], vertices[0], (x, y)),
            ]
            if all(value >= 0 for value in values) or \
                    all(value <= 0 for value in values):
                pixels.add((x, y))
    return pixels


class TriangleSpanRasterizerTests(unittest.TestCase):

    def test_spans_match_edge_equations_in_every_rotation(self):
        width = 12
        height = 10
        logical = [(1, 2), (8, 3), (4, 8)]

        for rotation in Rotation:
            with self.subTest(rotation=rotation):
                dut = TriangleSpanRasterizer()
                sim = Simulator(dut)
                sim.add_clock(1e-6)
                actual = set()

                async def bench(ctx):
                    ctx.set(dut.h_active, width)
                    ctx.set(dut.v_active, height)
                    ctx.set(dut.rotation, rotation)
                    ctx.set(dut.alternate, 1)
                    ctx.set(dut.o.ready, 1)
                    for index, (x, y) in enumerate(logical):
                        ctx.set(getattr(dut.i.payload, f"x{index}"), x)
                        ctx.set(getattr(dut.i.payload, f"y{index}"), y)
                    ctx.set(dut.i.payload.pixel.color, 5)
                    ctx.set(dut.i.payload.pixel.intensity, 11)
                    ctx.set(dut.i.valid, 1)
                    while not ctx.get(dut.i.ready):
                        await ctx.tick()
                    await ctx.tick()
                    ctx.set(dut.i.valid, 0)

                    for _ in range(2000):
                        if ctx.get(dut.o.valid):
                            x0 = ctx.get(dut.o.payload.x0)
                            x1 = ctx.get(dut.o.payload.x1)
                            y = ctx.get(dut.o.payload.y)
                            self.assertLessEqual(x0, x1)
                            for x in range(x0, x1 + 1):
                                actual.add((x, y))
                        if not ctx.get(dut.busy):
                            break
                        await ctx.tick()
                    else:
                        self.fail("rasterizer did not finish")

                sim.add_testbench(bench)
                sim.run()
                transformed = transform_triangle(
                    logical, rotation, width, height)
                self.assertEqual(
                    actual,
                    reference_pixels(transformed, width, height),
                )

    def test_repeated_small_surfaces_do_not_reemit_old_spans(self):
        """Exercise more than the four frames that broke generation tagging."""
        dut = TriangleSpanRasterizer()
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        frames = []

        async def bench(ctx):
            ctx.set(dut.h_active, 16)
            ctx.set(dut.v_active, 12)
            ctx.set(dut.rotation, Rotation.NORMAL)
            ctx.set(dut.alternate, 1)
            ctx.set(dut.o.ready, 1)

            for frame in range(10):
                vertices = [(1, 1), (13 - frame, 2), (2, 10 - frame)]
                for index, (x, y) in enumerate(vertices):
                    ctx.set(getattr(dut.i.payload, f"x{index}"), x)
                    ctx.set(getattr(dut.i.payload, f"y{index}"), y)
                ctx.set(dut.i.payload.pixel.color, frame & 7)
                ctx.set(dut.i.payload.pixel.intensity, 8)
                ctx.set(dut.i.valid, 1)
                while not ctx.get(dut.i.ready):
                    await ctx.tick()
                await ctx.tick()
                ctx.set(dut.i.valid, 0)

                pixels = set()
                for _ in range(2000):
                    if ctx.get(dut.o.valid):
                        y = ctx.get(dut.o.payload.y)
                        for x in range(ctx.get(dut.o.payload.x0),
                                       ctx.get(dut.o.payload.x1) + 1):
                            pixels.add((x, y))
                    if not ctx.get(dut.busy):
                        break
                    await ctx.tick()
                frames.append(pixels)

        sim.add_testbench(bench)
        sim.run()
        for frame, pixels in enumerate(frames):
            vertices = [(1, 1), (13 - frame, 2), (2, 10 - frame)]
            self.assertEqual(pixels, reference_pixels(vertices, 16, 12))


class PackedSpanWriterTests(unittest.TestCase):

    def test_unaligned_span_uses_packed_words_and_byte_selects(self):
        bus_signature = wishbone.Signature(
            addr_width=22,
            data_width=32,
            granularity=8,
            features={"cti", "bte"},
        )
        dut = PackedSpanWriter(bus_signature=bus_signature, burst_words=16)
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        writes = []

        async def bench(ctx):
            ctx.set(dut.fbp.base, 0x100)
            ctx.set(dut.fbp.timings.h_active, 16)
            ctx.set(dut.fbp.timings.v_active, 12)
            ctx.set(dut.fbp.enable, 1)
            ctx.set(dut.pause, 0)
            ctx.set(dut.i.payload.x0, 3)
            ctx.set(dut.i.payload.x1, 10)
            ctx.set(dut.i.payload.y, 2)
            ctx.set(dut.i.payload.pixel.color, 5)
            ctx.set(dut.i.payload.pixel.intensity, 9)
            ctx.set(dut.i.payload.alternate, 0)
            ctx.set(dut.i.valid, 1)
            while not ctx.get(dut.i.ready):
                await ctx.tick()
            await ctx.tick()
            ctx.set(dut.i.valid, 0)

            for _ in range(32):
                ctx.set(dut.bus.ack, 1)
                if ctx.get(dut.bus.cyc) and ctx.get(dut.bus.stb):
                    writes.append((
                        ctx.get(dut.bus.adr),
                        ctx.get(dut.bus.sel),
                        ctx.get(dut.bus.dat_w),
                        ctx.get(dut.bus.cti),
                    ))
                if not ctx.get(dut.busy):
                    break
                await ctx.tick()
            else:
                self.fail("span writer did not finish")

        sim.add_testbench(bench)
        sim.run()
        packed_pixel = 0x95
        self.assertEqual(
            writes,
            [
                (0x108, 0b1000, packed_pixel * 0x01010101,
                 wishbone.CycleType.INCR_BURST.value),
                (0x109, 0b1111, packed_pixel * 0x01010101,
                 wishbone.CycleType.INCR_BURST.value),
                (0x10a, 0b0111, packed_pixel * 0x01010101,
                 wishbone.CycleType.END_OF_BURST.value),
            ],
        )


if __name__ == "__main__":
    unittest.main()
