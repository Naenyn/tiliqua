import unittest

from amaranth import Module
from amaranth.sim import Simulator

from tiliqua.raster.scope_buffer import CompletedSweepBuffer
from tiliqua.raster.scope_capture import ENVELOPE_SENTINEL, MAX_CAPTURE_COLS


class CompletedSweepBufferTests(unittest.TestCase):

    def test_completed_sweep_is_hidden_until_done_and_missing_columns_clear(self):
        m = Module()
        m.submodules.dut = dut = CompletedSweepBuffer()
        rendered = []

        async def testbench(ctx):
            ctx.set(dut.enable, 1)
            ctx.set(dut.ncols, 3)
            ctx.set(dut.col_ready, 1)

            # Initial clear is intentionally the full hardware depth.
            while not ctx.get(dut.capture_clear):
                self.assertEqual(ctx.get(dut.col_valid), 0)
                await ctx.tick()
            await ctx.tick()
            self.assertEqual(ctx.get(dut.capture_active), 1)

            # Capture columns 0 and 2. Column 1 must retain the sentinel.
            ctx.set(dut.flush_valid, 1)
            ctx.set(dut.flush_col, 0)
            ctx.set(dut.flush_word, 0x1111)
            await ctx.tick()
            ctx.set(dut.flush_col, 2)
            ctx.set(dut.flush_word, 0x3333)
            await ctx.tick()
            ctx.set(dut.flush_valid, 0)

            # Nothing is exposed before the completed-sweep boundary.
            for _ in range(4):
                self.assertEqual(ctx.get(dut.col_valid), 0)
                await ctx.tick()

            ctx.set(dut.sweep_done, 1)
            await ctx.tick()
            ctx.set(dut.sweep_done, 0)

            while len(rendered) < 3:
                if ctx.get(dut.col_valid & dut.col_ready):
                    rendered.append((ctx.get(dut.col), ctx.get(dut.word)))
                await ctx.tick()

            self.assertEqual(rendered, [
                (0, 0x1111),
                (1, ENVELOPE_SENTINEL),
                (2, 0x3333),
            ])

            while not ctx.get(dut.render_done):
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_buffer_returns_to_capture_after_render_and_clear(self):
        m = Module()
        m.submodules.dut = dut = CompletedSweepBuffer()
        clear_pulses = 0

        async def testbench(ctx):
            nonlocal clear_pulses
            ctx.set(dut.enable, 1)
            ctx.set(dut.ncols, 1)
            ctx.set(dut.col_ready, 1)

            while clear_pulses < 2:
                if ctx.get(dut.capture_clear):
                    clear_pulses += 1
                if clear_pulses == 1 and ctx.get(dut.capture_active):
                    ctx.set(dut.flush_valid, 1)
                    ctx.set(dut.flush_col, 0)
                    ctx.set(dut.flush_word, 0x55)
                    ctx.set(dut.sweep_done, 1)
                else:
                    ctx.set(dut.flush_valid, 0)
                    ctx.set(dut.sweep_done, 0)
                await ctx.tick()

            self.assertEqual(clear_pulses, 2)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()


if __name__ == "__main__":
    unittest.main()
