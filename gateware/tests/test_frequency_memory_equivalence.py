"""Cycle-exact comparison of the rejected RAM prototype with production."""

import random

import pytest
from amaranth import Module, ResetInserter, Signal, signed
from amaranth.sim import Simulator

from tiliqua.raster.frequency_detector import NativeFrequencyDetector as Reference
from reference_frequency_memory import NativeFrequencyDetector


@pytest.mark.parametrize("channels,bits", [(1, 8), (4, 8), (4, 24)])
def test_frequency_state_memory_equivalence(channels, bits):
    class Old(Reference):
        PERIOD_BITS = bits

    class New(NativeFrequencyDetector):
        PERIOD_BITS = bits

    kwargs = dict(shape=signed(18), n_channels=channels,
                  envelope_block_samples=8, activity_window_samples=19,
                  rapid_hold_windows=3)
    old, new = Old(**kwargs), New(**kwargs)
    reset = Signal()
    m = Module()
    m.submodules.old = ResetInserter(reset)(old)
    m.submodules.new = ResetInserter(reset)(new)

    async def bench(ctx):
        rng = random.Random(715)
        for clock in range(24000):
            # Normal cadence, dense bursts, pauses, and reset during work.
            phase = clock // 4000
            tick = clock % (channels + 2) == 0 if phase != 1 else rng.randrange(3) == 0
            if phase == 4:
                tick = False
            ctx.set(reset, clock in (3501, 8102, 19500))
            for dut in (old, new):
                ctx.set(dut.tick, tick)
            for ch in range(channels):
                sample = (6000 if (clock // (23 + 13*ch)) % 2 else -6000) + 1100*ch
                if phase == 2:
                    sample = rng.randrange(-131072, 131072)
                if phase == 3:
                    sample = 0
                for dut in (old, new):
                    ctx.set(dut.sample[ch], sample)
            await ctx.tick()
            for ch in range(channels):
                for name in ('period', 'valid', 'rapid'):
                    assert ctx.get(getattr(new, name)[ch]) == ctx.get(getattr(old, name)[ch]), (clock, ch, name)

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
