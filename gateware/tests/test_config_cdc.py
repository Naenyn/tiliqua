import unittest

from amaranth import Module
from amaranth.sim import Simulator

from tiliqua.config_cdc import ConfigCDC


class ConfigCDCTests(unittest.TestCase):

    def test_transfers_complete_snapshots_and_coalesces_changes(self):
        m = Module()
        dut = ConfigCDC(16)
        m.submodules.dut = dut

        observed = []

        async def source(ctx):
            ctx.set(dut.i, 0x1234)
            await ctx.tick("sync").repeat(2)
            # Change again before the first acknowledgement returns. The
            # destination may see the intermediate snapshot, but never a torn
            # mixture, and must eventually receive the latest word.
            ctx.set(dut.i, 0xaaaa)
            await ctx.tick("sync")
            ctx.set(dut.i, 0x5555)
            await ctx.tick("sync").repeat(20)

        async def destination(ctx):
            for _ in range(40):
                await ctx.tick("dvi")
                value = ctx.get(dut.o)
                if not observed or value != observed[-1]:
                    observed.append(value)

        sim = Simulator(m)
        sim.add_clock(1e-6, domain="sync")
        sim.add_clock(0.7e-6, domain="dvi")
        sim.add_testbench(source)
        sim.add_testbench(destination)
        sim.run()

        self.assertTrue(set(observed).issubset({0, 0x1234, 0xaaaa, 0x5555}))
        self.assertEqual(observed[-1], 0x5555)


if __name__ == "__main__":
    unittest.main()
