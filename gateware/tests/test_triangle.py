import unittest

from amaranth.sim import Simulator

from tiliqua.raster.triangle import TrianglePlotter


class TrianglePlotterTests(unittest.TestCase):

    def _render(self, vertices):
        dut = TrianglePlotter()
        pixels = []

        async def bench(ctx):
            ctx.set(dut.h_active, 8)
            ctx.set(dut.v_active, 8)
            ctx.set(dut.alternate, 1)
            ctx.set(dut.o.ready, 1)
            for name, value in zip(
                    ("x0", "y0", "x1", "y1", "x2", "y2"),
                    (coordinate for vertex in vertices for coordinate in vertex)):
                ctx.set(getattr(dut.i.payload, name), value)
            ctx.set(dut.i.payload.pixel.color, 3)
            ctx.set(dut.i.payload.pixel.intensity, 11)
            ctx.set(dut.i.valid, 1)
            await ctx.tick()
            ctx.set(dut.i.valid, 0)

            for _ in range(300):
                if ctx.get(dut.o.valid) and ctx.get(dut.o.ready):
                    pixels.append((ctx.get(dut.o.payload.x),
                                   ctx.get(dut.o.payload.y),
                                   ctx.get(dut.o.payload.pixel.color),
                                   ctx.get(dut.o.payload.pixel.intensity),
                                   ctx.get(dut.o.payload.alternate)))
                await ctx.tick()
                if not ctx.get(dut.busy):
                    break
            else:
                self.fail("triangle rasterizer did not finish")

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(bench)
        sim.run()
        return pixels

    def test_fills_triangle_in_either_winding(self):
        clockwise = self._render(((1, 1), (1, 4), (4, 1)))
        counterclockwise = self._render(((1, 1), (4, 1), (1, 4)))

        expected_xy = {
            (1, 1), (2, 1), (3, 1), (4, 1),
            (1, 2), (2, 2), (3, 2),
            (1, 3), (2, 3),
            (1, 4),
        }
        self.assertEqual({pixel[:2] for pixel in clockwise}, expected_xy)
        self.assertEqual({pixel[:2] for pixel in counterclockwise}, expected_xy)
        self.assertTrue(all(pixel[2:] == (3, 11, 1)
                            for pixel in clockwise + counterclockwise))

    def test_clips_to_display_bounds(self):
        pixels = self._render(((-3, -2), (4, 0), (0, 4)))
        self.assertTrue(pixels)
        self.assertTrue(all(0 <= x < 8 and 0 <= y < 8
                            for x, y, *_ in pixels))


if __name__ == "__main__":
    unittest.main()
