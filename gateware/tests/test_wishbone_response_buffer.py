import unittest

from amaranth.sim import Simulator

from tiliqua.wishbone import ResponseBuffer


class WishboneResponseBufferTests(unittest.TestCase):

    def test_registers_response_and_prevents_duplicate_request(self):
        dut = ResponseBuffer()
        sim = Simulator(dut)
        sim.add_clock(1e-6)

        async def bench(ctx):
            ctx.set(dut.upstream.cyc, 1)
            ctx.set(dut.upstream.stb, 1)
            ctx.set(dut.upstream.adr, 0x1234)
            ctx.set(dut.downstream.dat_r, 0x89ABCDEF)
            ctx.set(dut.downstream.ack, 1)

            self.assertEqual(ctx.get(dut.downstream.stb), 1)
            self.assertEqual(ctx.get(dut.upstream.ack), 0)
            await ctx.tick()

            # The captured response is returned one cycle later. Suppressing
            # the downstream request during this cycle prevents a
            # combinational slave from acknowledging the same transfer twice.
            self.assertEqual(ctx.get(dut.upstream.ack), 1)
            self.assertEqual(ctx.get(dut.upstream.dat_r), 0x89ABCDEF)
            self.assertEqual(ctx.get(dut.downstream.stb), 0)
            self.assertEqual(ctx.get(dut.downstream.cyc), 1)

            ctx.set(dut.downstream.ack, 0)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.upstream.ack), 0)
            self.assertEqual(ctx.get(dut.downstream.stb), 1)

        sim.add_testbench(bench)
        sim.run()

    def test_preserves_cycle_across_back_to_back_burst_beats(self):
        dut = ResponseBuffer(features={"cti", "bte"})
        sim = Simulator(dut)
        sim.add_clock(1e-6)

        async def bench(ctx):
            ctx.set(dut.upstream.cyc, 1)
            ctx.set(dut.upstream.stb, 1)
            ctx.set(dut.upstream.cti, 0b010)  # Incrementing burst.
            ctx.set(dut.upstream.adr, 0x100)
            ctx.set(dut.downstream.dat_r, 0x11111111)
            ctx.set(dut.downstream.ack, 1)
            await ctx.tick()

            self.assertEqual(ctx.get(dut.upstream.ack), 1)
            self.assertEqual(ctx.get(dut.upstream.dat_r), 0x11111111)
            self.assertEqual(ctx.get(dut.downstream.cyc), 1)
            self.assertEqual(ctx.get(dut.downstream.stb), 0)

            # Present the next beat while the registered response completes.
            ctx.set(dut.upstream.adr, 0x101)
            ctx.set(dut.downstream.dat_r, 0x22222222)
            await ctx.tick()

            self.assertEqual(ctx.get(dut.upstream.ack), 0)
            self.assertEqual(ctx.get(dut.downstream.cyc), 1)
            self.assertEqual(ctx.get(dut.downstream.stb), 1)
            self.assertEqual(ctx.get(dut.downstream.adr), 0x101)
            await ctx.tick()

            self.assertEqual(ctx.get(dut.upstream.ack), 1)
            self.assertEqual(ctx.get(dut.upstream.dat_r), 0x22222222)
            self.assertEqual(ctx.get(dut.downstream.cyc), 1)
            self.assertEqual(ctx.get(dut.downstream.stb), 0)

        sim.add_testbench(bench)
        sim.run()

    def test_registers_error_instead_of_acknowledge(self):
        dut = ResponseBuffer()
        sim = Simulator(dut)
        sim.add_clock(1e-6)

        async def bench(ctx):
            ctx.set(dut.upstream.cyc, 1)
            ctx.set(dut.upstream.stb, 1)
            ctx.set(dut.downstream.err, 1)
            await ctx.tick()

            self.assertEqual(ctx.get(dut.upstream.ack), 0)
            self.assertEqual(ctx.get(dut.upstream.err), 1)
            self.assertEqual(ctx.get(dut.downstream.stb), 0)

        sim.add_testbench(bench)
        sim.run()


if __name__ == "__main__":
    unittest.main()
