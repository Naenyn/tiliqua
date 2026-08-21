import math

import pytest
from amaranth.sim import Simulator

from top.rezo.rezo_variant import RezoCore as RezoCore
from top.rezo.strezo_variant import RezoCore as StrezoCore
from top.rezo.top import RezoCore as RezomoCore


FAMILY_CORES = (
    pytest.param(RezoCore, id="rezo"),
    pytest.param(RezomoCore, id="rezomo"),
    pytest.param(StrezoCore, id="strezo"),
)


@pytest.mark.parametrize("core_type", (FAMILY_CORES[0], FAMILY_CORES[1]))
def test_core_meets_192khz_sample_cycle_budget(core_type):
    dut = core_type(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    async def bench(ctx):
        ctx.set(dut.o.ready, 1)
        ctx.set(dut.i.payload[0].as_value(), 1000)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)

        processing_cycles = 0
        while not ctx.get(dut.o.valid):
            await ctx.tick()
            processing_cycles += 1
        result["cycles"] = processing_cycles + 1

    sim.add_testbench(bench)
    sim.run()

    # The sync domain is 60 MHz, leaving 312.5 clocks per sample at 192 kHz.
    assert result["cycles"] <= 60_000_000 // 192_000


@pytest.mark.parametrize("core_type", FAMILY_CORES)
def test_input_meters_use_audio_post_value_and_cv_pre_depth(core_type):
    dut = core_type(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = {}

    async def bench(ctx):
        ctx.set(dut.o.ready, 1)
        ctx.set(dut.i.payload[0].as_value(), 12_000)
        ctx.set(dut.i.payload[2].as_value(), -12_345)
        ctx.set(dut.cv_depths[2], 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        await ctx.tick().until(dut.o.valid == 1)
        captured["audio"] = ctx.get(dut.input_meters[0])
        captured["cv"] = ctx.get(dut.input_meters[2])

    sim.add_testbench(bench)
    sim.run()

    assert 5_000 < captured["audio"] < 12_000
    assert captured["cv"] == -12_345


@pytest.mark.parametrize("core_type", FAMILY_CORES)
def test_bank_zero_wet_and_dry_paths(core_type):
    dut = core_type(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    zero_output = []
    output = []
    half_send_output = []
    dry_pairs = []

    async def send(ctx, sample):
        for channel in range(4):
            ctx.set(dut.i.payload[channel].as_value(), sample if channel == 0 else 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            *[dut.o.payload[channel].as_value() for channel in range(4)]
        ).until(dut.o.valid == 1)
        ctx.set(dut.o.ready, 0)
        return values[0]

    async def bench(ctx):
        for n in range(64):
            sample = int(12_000 * (2 / math.pi) * math.asin(math.sin(n * 0.19)))
            zero_output.append(await send(ctx, sample))

        for level in dut.levels:
            ctx.set(level, 8192)
        for n in range(512):
            sample = int(12_000 * (2 / math.pi) * math.asin(math.sin(n * 0.19)))
            output.append(await send(ctx, sample))

        for group in range(dut.N_GROUPS):
            ctx.set(dut.output_sends[group], 8)
        for n in range(512):
            sample = int(12_000 * (2 / math.pi) * math.asin(math.sin(n * 0.19)))
            half_send_output.append(await send(ctx, sample))

        for level in dut.levels:
            ctx.set(level, 0)
        for group in range(dut.N_GROUPS):
            ctx.set(dut.output_sends[group], 0)
        ctx.set(dut.output_sends[dut.N_GROUPS], 16)
        for n in range(768):
            sample = int(12_000 * (2 / math.pi) * math.asin(math.sin(n * 0.19)))
            result = await send(ctx, sample)
            if n >= 640:
                dry_pairs.append((sample, result))

    sim.add_testbench(bench)
    sim.run()

    rail_count = sum(value in (-32768, 32767) for value in output)
    full_rms = math.sqrt(sum(value * value for value in output[-256:]) / 256)
    half_rms = math.sqrt(
        sum(value * value for value in half_send_output[-256:]) / 256)
    assert zero_output == [0] * len(zero_output)
    assert rail_count == 0
    assert 0.45 < half_rms / full_rms < 0.55
    assert max(abs(source - result) for source, result in dry_pairs) <= 2


@pytest.mark.parametrize("core_type", FAMILY_CORES)
def test_band5_zero_feedback_matches_known_good_drive_scale(core_type):
    dut = core_type(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    output = []

    async def send(ctx, sample):
        ctx.set(dut.i.payload[0].as_value(), sample)
        for channel in range(1, 4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            dut.o.payload[0].as_value()).until(dut.o.valid == 1)
        output.append(values[0])

    async def bench(ctx):
        for index, level in enumerate(dut.levels):
            ctx.set(level, 8192 if index == 5 else 0)
        ctx.set(dut.resonance, 0)
        ctx.set(dut.feedback, 0)
        for n in range(180):
            sample = int(5000 * math.sin(2 * math.pi * 777 * n / 192000))
            await send(ctx, sample)

    sim.add_testbench(bench)
    sim.run()

    assert output[-12:] == [
        252, 243, 233, 223, 213, 203, 193, 183, 173, 163, 152, 142,
    ]


@pytest.mark.parametrize("core_type", FAMILY_CORES)
def test_strong_band5_resonance_has_no_guard_bit_sign_wrap(core_type):
    dut = core_type(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    output = []

    async def send(ctx, sample):
        ctx.set(dut.i.payload[0].as_value(), sample)
        for channel in range(1, 4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            dut.o.payload[0].as_value()).until(dut.o.valid == 1)
        output.append(values[0])

    async def bench(ctx):
        for index, level in enumerate(dut.levels):
            ctx.set(level, 512 if index == 5 else 0)
        ctx.set(dut.band_frequencies[5], dut.frequency_index(16_000))
        for n in range(1024):
            sample = int(32_000 * math.sin(2 * math.pi * 4_000 * n / 192_000))
            await send(ctx, sample)

    sim.add_testbench(bench)
    sim.run()

    tail = output[-256:]
    max_step = max(abs(current - previous)
                   for previous, current in zip(tail, tail[1:]))
    assert max_step < 800, (min(tail), max(tail), max_step, tail[-32:])
