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


def packed_word_pixels(pixels, width):
    """Expand touched pixels to the opaque four-pixel words we store."""
    expanded = set()
    for x, y in pixels:
        word_x = x & ~3
        for lane in range(4):
            if word_x + lane < width:
                expanded.add((word_x + lane, y))
    return expanded


class TriangleSpanRasterizerTests(unittest.TestCase):

    @staticmethod
    async def _send_triangle(ctx, dut, vertices, pixels):
        for index, (x, y) in enumerate(vertices):
            ctx.set(getattr(dut.i.payload, f"x{index}"), x)
            ctx.set(getattr(dut.i.payload, f"y{index}"), y)
        ctx.set(dut.i.payload.pixel.color, 5)
        ctx.set(dut.i.payload.pixel.intensity, 11)
        ctx.set(dut.i.valid, 1)
        while not ctx.get(dut.i.ready):
            await ctx.tick()
        await ctx.tick()
        ctx.set(dut.i.valid, 0)

        for _ in range(10000):
            if ctx.get(dut.o.valid):
                y = ctx.get(dut.o.payload.y)
                for x in range(ctx.get(dut.o.payload.x0),
                               ctx.get(dut.o.payload.x1) + 1):
                    pixels.add((x, y))
            if not ctx.get(dut.busy):
                return
            await ctx.tick()
        raise AssertionError("rasterizer did not finish")

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
                    packed_word_pixels(
                        reference_pixels(transformed, width, height), width),
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
            self.assertEqual(
                pixels,
                packed_word_pixels(reference_pixels(vertices, 16, 12), 16),
            )

    def test_ridge_spans_follow_each_fill_and_stay_on_marked_edge(self):
        """Optional ridges share the ordered span stream with terrain fills."""
        width = 32
        height = 24
        vertices = [(3, 3), (7, 20), (27, 15)]
        dut = TriangleSpanRasterizer()
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        spans = []

        async def bench(ctx):
            ctx.set(dut.h_active, width)
            ctx.set(dut.v_active, height)
            ctx.set(dut.rotation, Rotation.NORMAL)
            ctx.set(dut.alternate, 1)
            ctx.set(dut.o.ready, 1)
            for index, (x, y) in enumerate(vertices):
                ctx.set(getattr(dut.i.payload, f"x{index}"), x)
                ctx.set(getattr(dut.i.payload, f"y{index}"), y)
            ctx.set(dut.i.payload.pixel.color, 5)
            ctx.set(dut.i.payload.pixel.intensity, 11)
            ctx.set(dut.ridge, 1)
            ctx.set(dut.i.valid, 1)
            while not ctx.get(dut.i.ready):
                await ctx.tick()
            await ctx.tick()
            ctx.set(dut.i.valid, 0)

            for _ in range(4000):
                if ctx.get(dut.o.valid):
                    spans.append((
                        ctx.get(dut.o.payload.x0),
                        ctx.get(dut.o.payload.x1),
                        ctx.get(dut.o.payload.y),
                        ctx.get(dut.o.payload.pixel.color),
                        ctx.get(dut.o.payload.pixel.intensity),
                    ))
                if not ctx.get(dut.busy):
                    break
                await ctx.tick()
            else:
                self.fail("rasterizer did not finish")

        sim.add_testbench(bench)
        sim.run()
        self.assertGreater(len(spans), 0)
        fills = [span for span in spans if span[4] == 11]
        ridges = [span for span in spans if span[4] == 0]
        self.assertGreater(len(fills), len(ridges))
        # Only rows crossed by the marked edge 1->2 receive a ridge. Emitting
        # an endpoint on every triangle row was the visible perforation bug.
        self.assertEqual([ridge[2] for ridge in ridges], list(range(15, 21)))
        for ridge in ridges:
            self.assertEqual(ridge[3:], (0, 0))
            self.assertLessEqual(ridge[0], ridge[1])
        # Consecutive scanline spans share the preceding edge intersection,
        # making the projected contour continuous even when it is shallow.
        for previous, current in zip(ridges, ridges[1:]):
            self.assertLessEqual(
                max(previous[0], current[0]),
                min(previous[1], current[1]))

    def test_horizontal_ridge_covers_the_complete_marked_edge(self):
        width = 32
        height = 24
        vertices = [(3, 3), (7, 16), (27, 16)]
        dut = TriangleSpanRasterizer()
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        spans = []

        async def bench(ctx):
            ctx.set(dut.h_active, width)
            ctx.set(dut.v_active, height)
            ctx.set(dut.rotation, Rotation.NORMAL)
            ctx.set(dut.o.ready, 1)
            for index, (x, y) in enumerate(vertices):
                ctx.set(getattr(dut.i.payload, f"x{index}"), x)
                ctx.set(getattr(dut.i.payload, f"y{index}"), y)
            ctx.set(dut.i.payload.pixel.color, 5)
            ctx.set(dut.i.payload.pixel.intensity, 11)
            ctx.set(dut.ridge, 1)
            ctx.set(dut.i.valid, 1)
            while not ctx.get(dut.i.ready):
                await ctx.tick()
            await ctx.tick()
            ctx.set(dut.i.valid, 0)

            for _ in range(4000):
                if ctx.get(dut.o.valid):
                    spans.append((
                        ctx.get(dut.o.payload.x0),
                        ctx.get(dut.o.payload.x1),
                        ctx.get(dut.o.payload.y),
                        ctx.get(dut.o.payload.pixel.intensity),
                    ))
                if not ctx.get(dut.busy):
                    break
                await ctx.tick()

        sim.add_testbench(bench)
        sim.run()
        fill, ridge = spans[-2:]
        self.assertEqual(fill[2], 16)
        self.assertEqual(ridge[2], 16)
        self.assertEqual(ridge[3], 0)
        self.assertEqual((ridge[0], ridge[1]), (fill[0], fill[1]))

    def test_adjacent_triangles_form_watertight_projected_cells(self):
        """Terrain's two triangles must not crack along their shared edge."""
        width = 32
        height = 24
        # Convex cells with horizontal, vertical and diagonal shared edges.
        cells = [
            ((3, 3), (6, 18), (24, 16), (22, 5)),
            ((2, 8), (9, 20), (28, 14), (20, 2)),
            ((5, 2), (5, 21), (26, 19), (26, 4)),
            ((2, 4), (12, 20), (29, 18), (20, 5)),
        ]

        for rotation in Rotation:
            for cell in cells:
                with self.subTest(rotation=rotation, cell=cell):
                    # Match WATERFALL's A-B-C and A-C-D split.
                    triangles = [
                        (cell[0], cell[1], cell[2]),
                        (cell[0], cell[2], cell[3]),
                    ]
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
                        for triangle in triangles:
                            await self._send_triangle(
                                ctx, dut, triangle, actual)

                    sim.add_testbench(bench)
                    sim.run()
                    transformed = [
                        transform_triangle(
                            triangle, rotation, width, height)
                        for triangle in triangles
                    ]
                    expected = set().union(*(
                        packed_word_pixels(
                            reference_pixels(triangle, width, height), width)
                        for triangle in transformed
                    ))
                    self.assertEqual(actual, expected)

                    # No background pixel may be trapped between filled
                    # pixels on a scanline of this convex projected cell.
                    for y in range(height):
                        xs = sorted(x for x, py in actual if py == y)
                        if xs:
                            self.assertEqual(
                                xs, list(range(xs[0], xs[-1] + 1)))


class PackedSpanWriterTests(unittest.TestCase):

    def test_unaligned_span_uses_conservative_packed_words(self):
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
                (0x108, 0b1111, packed_pixel * 0x01010101,
                 wishbone.CycleType.INCR_BURST.value),
                (0x109, 0b1111, packed_pixel * 0x01010101,
                 wishbone.CycleType.INCR_BURST.value),
                (0x10a, 0b1111, packed_pixel * 0x01010101,
                 wishbone.CycleType.END_OF_BURST.value),
            ],
        )

    def test_adjacent_stalled_spans_leave_no_unwritten_bytes(self):
        """Exercise shared words, back-pressure and burst interruption."""
        bus_signature = wishbone.Signature(
            addr_width=22,
            data_width=32,
            granularity=8,
            features={"cti", "bte"},
        )
        dut = PackedSpanWriter(bus_signature=bus_signature, burst_words=4)
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        memory = bytearray(16 * 4)
        spans = [
            (1, 5, 1, 0x31),
            (6, 11, 1, 0x62),
            (12, 14, 1, 0x93),
            (0, 15, 2, 0xc4),
        ]

        async def bench(ctx):
            ctx.set(dut.fbp.base, 0)
            ctx.set(dut.fbp.timings.h_active, 16)
            ctx.set(dut.fbp.timings.v_active, 4)
            ctx.set(dut.fbp.enable, 1)

            cycle = 0
            for x0, x1, y, packed_pixel in spans:
                ctx.set(dut.i.payload.x0, x0)
                ctx.set(dut.i.payload.x1, x1)
                ctx.set(dut.i.payload.y, y)
                ctx.set(dut.i.payload.pixel.color, packed_pixel & 0xf)
                ctx.set(dut.i.payload.pixel.intensity, packed_pixel >> 4)
                ctx.set(dut.i.payload.alternate, 0)
                ctx.set(dut.i.valid, 1)
                while not ctx.get(dut.i.ready):
                    pause = cycle % 11 in (7, 8)
                    ack = cycle % 5 != 2
                    ctx.set(dut.pause, pause)
                    ctx.set(dut.bus.ack, ack)
                    if ack and ctx.get(dut.bus.cyc) and ctx.get(dut.bus.stb):
                        address = ctx.get(dut.bus.adr) * 4
                        select = ctx.get(dut.bus.sel)
                        data = ctx.get(dut.bus.dat_w)
                        for lane in range(4):
                            if select & (1 << lane):
                                memory[address + lane] = (
                                    data >> (lane * 8)) & 0xff
                    cycle += 1
                    await ctx.tick()
                await ctx.tick()
                ctx.set(dut.i.valid, 0)

            for _ in range(200):
                pause = cycle % 11 in (7, 8)
                ack = cycle % 5 != 2
                ctx.set(dut.pause, pause)
                ctx.set(dut.bus.ack, ack)
                if ack and ctx.get(dut.bus.cyc) and ctx.get(dut.bus.stb):
                    address = ctx.get(dut.bus.adr) * 4
                    select = ctx.get(dut.bus.sel)
                    data = ctx.get(dut.bus.dat_w)
                    for lane in range(4):
                        if select & (1 << lane):
                            memory[address + lane] = (
                                data >> (lane * 8)) & 0xff
                if not ctx.get(dut.busy):
                    break
                cycle += 1
                await ctx.tick()
            else:
                self.fail("span writer did not finish")

        sim.add_testbench(bench)
        sim.run()
        expected = bytearray(16 * 4)
        for x0, x1, y, packed_pixel in spans:
            conservative_x0 = x0 & ~3
            conservative_x1 = x1 | 3
            expected[y * 16 + conservative_x0:y * 16 + conservative_x1 + 1] = bytes(
                [packed_pixel] * (conservative_x1 - conservative_x0 + 1))
        self.assertEqual(memory, expected)


if __name__ == "__main__":
    unittest.main()
