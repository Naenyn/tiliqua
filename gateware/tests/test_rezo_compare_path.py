import math

from amaranth.sim import Simulator

from top.rezo.top import RezoCore


def test_bank_zero_wet_and_dry_paths():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    zero_output = []
    output = []
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
        ctx.set(dut.output_routes[0], 0b01111)
        for n in range(64):
            sample = int(12_000 * (2 / math.pi) * math.asin(math.sin(n * 0.19)))
            zero_output.append(await send(ctx, sample))

        for level in dut.levels:
            ctx.set(level, 8192)
        for n in range(512):
            sample = int(12_000 * (2 / math.pi) * math.asin(math.sin(n * 0.19)))
            output.append(await send(ctx, sample))

        for level in dut.levels:
            ctx.set(level, 0)
        ctx.set(dut.output_routes[0], 0b10000)
        ctx.set(dut.dry, 32768)
        for n in range(768):
            sample = int(12_000 * (2 / math.pi) * math.asin(math.sin(n * 0.19)))
            result = await send(ctx, sample)
            if n >= 640:
                dry_pairs.append((sample, result))

    sim.add_testbench(bench)
    sim.run()

    rail_count = sum(value in (-32768, 32767) for value in output)
    print("wet", min(output), max(output), "rails", rail_count, "tail", output[-16:])
    assert zero_output == [0] * len(zero_output)
    assert rail_count == 0
    assert max(abs(source - result) for source, result in dry_pairs) <= 2
