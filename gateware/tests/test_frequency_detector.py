# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

from amaranth import signed
from amaranth.sim import Simulator

from tiliqua.raster.frequency_detector import NativeFrequencyDetector


async def put_sample(ctx, dut, sample):
    """Present one native sample bundle, then allow all channels to run."""
    for ch in range(dut.n_channels):
        ctx.set(dut.sample[ch], sample)
    ctx.set(dut.tick, 1)
    await ctx.tick()
    ctx.set(dut.tick, 0)
    for _ in range(dut.n_channels):
        await ctx.tick()


def test_native_detector_measures_offset_unipolar_period():
    dut = NativeFrequencyDetector(
        shape=signed(18),
        envelope_block_samples=8,
        envelope_release_step=8,
        activity_window_samples=32,
        rapid_crossings=3,
        rapid_hold_windows=2,
    )
    samples = [2000 if (n % 40) < 20 else 6000 for n in range(180)]

    observed = {}

    async def testbench(ctx):
        for sample in samples:
            await put_sample(ctx, dut, sample)
        observed["period"] = ctx.get(dut.period[0])
        observed["valid"] = ctx.get(dut.valid[0])
        observed["rapid"] = ctx.get(dut.rapid[0])

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(testbench)
    sim.run()

    assert observed == {"period": 40, "valid": 1, "rapid": 0}


def test_native_detector_rejects_static_voltage():
    dut = NativeFrequencyDetector(
        shape=signed(18),
        envelope_block_samples=8,
        activity_window_samples=16,
        rapid_hold_windows=2,
    )
    observed = {}

    async def testbench(ctx):
        for _ in range(96):
            await put_sample(ctx, dut, 5000)
        observed["valid"] = ctx.get(dut.valid[0])
        observed["rapid"] = ctx.get(dut.rapid[0])

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(testbench)
    sim.run()

    assert observed == {"valid": 0, "rapid": 0}


def test_native_detector_flags_high_rate_crossing_activity():
    dut = NativeFrequencyDetector(
        shape=signed(18),
        envelope_block_samples=4,
        envelope_release_step=8,
        activity_window_samples=16,
        rapid_crossings=2,
        rapid_hold_windows=3,
    )
    observed = {}

    async def testbench(ctx):
        for n in range(100):
            sample = -6000 if (n % 8) < 4 else 6000
            await put_sample(ctx, dut, sample)
        observed["period"] = ctx.get(dut.period[0])
        observed["valid"] = ctx.get(dut.valid[0])
        observed["rapid"] = ctx.get(dut.rapid[0])

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(testbench)
    sim.run()

    assert observed == {"period": 8, "valid": 1, "rapid": 1}
