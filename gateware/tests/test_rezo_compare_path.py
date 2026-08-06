import math

from amaranth.sim import Simulator

from top.rezo.top import RezoCore


def test_core_meets_192khz_sample_cycle_budget():
    dut = RezoCore(fs=192_000)
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
    # Crossing this limit causes the asynchronous audio FIFOs to drop/repeat
    # samples, which is heard as deterministic harmonic buzz on wet signals.
    assert result["cycles"] <= 60_000_000 // 192_000


def test_bank_zero_wet_and_dry_paths():
    dut = RezoCore(fs=192_000)
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
    print("wet", min(output), max(output), "rails", rail_count, "tail", output[-16:])
    assert zero_output == [0] * len(zero_output)
    assert rail_count == 0
    assert 0.45 < half_rms / full_rms < 0.55
    assert max(abs(source - result) for source, result in dry_pairs) <= 2


def test_band5_zero_feedback_matches_known_good_drive_scale():
    """Guard the Q1.15-to-wide conversion feeding the resonator bank.

    This vector comes from the last hardware-clean implementation.  It catches
    the otherwise visually innocuous fixed-point conversion that doubled the
    direct filter drive while leaving DRY unchanged.
    """
    dut = RezoCore(fs=192_000)
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


def test_clocked_shift_register_directions_hysteresis_roles_and_reset():
    """CLOCK captures DATA exactly once per rising edge and shifts as selected."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def send(ctx, inputs):
        for channel, sample in enumerate(inputs):
            ctx.set(dut.i.payload[channel].as_value(), sample)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)
        ctx.set(dut.o.ready, 0)

    def vector(ctx):
        return tuple(ctx.get(value) for value in dut.clock_modulations)

    async def pulse(ctx, data, high=6000):
        # Default roles: RESET=IN1, DATA=IN2, CLOCK=IN3.
        await send(ctx, (0, 0, data, 0))
        await send(ctx, (0, 0, data, high))

    async def clear(ctx):
        await send(ctx, (0, 6000, 0, 0))
        await send(ctx, (0, 0, 0, 0))
        assert vector(ctx) == (0,) * dut.N_BANDS

    async def bench(ctx):
        assert tuple(ctx.get(target) for target in dut.cv_targets) == (
            dut.CV_TARGET_RESONANCE,
            dut.CV_TARGET_RESET,
            dut.CV_TARGET_DATA,
            dut.CV_TARGET_CLOCK,
        )
        ctx.set(dut.clock_mode, 1)

        # Forward inserts at band 0 and moves older captures upward.
        await pulse(ctx, 8000)
        assert vector(ctx)[:3] == (4000, 0, 0)
        # Holding high, including inside the hysteresis window, cannot retrigger.
        await send(ctx, (0, 0, 12000, 7000))
        await send(ctx, (0, 0, 12000, 2000))
        await send(ctx, (0, 0, 12000, 7000))
        assert vector(ctx)[:3] == (4000, 0, 0)
        await pulse(ctx, -6000)
        assert vector(ctx)[:3] == (-3000, 4000, 0)

        # Backward mirrors the insertion and shift at the high-band end.
        await clear(ctx)
        ctx.set(dut.shift_direction, dut.SHIFT_BACKWARD)
        await pulse(ctx, 2000)
        await pulse(ctx, 4000)
        assert vector(ctx)[-3:] == (0, 1000, 2000)

        # RANDOM inserts at exactly one randomly chosen end.
        await clear(ctx)
        ctx.set(dut.shift_direction, dut.SHIFT_RANDOM)
        await pulse(ctx, 14000)
        assert vector(ctx) in (
            (7000,) + (0,) * 9,
            (0,) * 9 + (7000,),
        )

        # Roles are live INPUT-page targets, not hard-wired jack numbers.
        await clear(ctx)
        ctx.set(dut.shift_direction, dut.SHIFT_FORWARD)
        for n in range(4):
            ctx.set(dut.input_modes[n], dut.INPUT_MODE_CV)
            ctx.set(dut.cv_targets[n], dut.CV_TARGET_FEEDBACK)
        ctx.set(dut.cv_targets[0], dut.CV_TARGET_DATA)
        ctx.set(dut.cv_targets[1], dut.CV_TARGET_CLOCK)
        ctx.set(dut.cv_targets[3], dut.CV_TARGET_RESET)
        await send(ctx, (6000, 0, 0, 0))
        await send(ctx, (6000, 6000, 0, 0))
        assert vector(ctx)[0] == 3000
        await send(ctx, (0, 0, 0, 6000))
        assert vector(ctx) == (0,) * dut.N_BANDS

    sim.add_testbench(bench)
    sim.run()


def test_clocked_rotate_uses_bank_levels_skips_disabled_and_ping_pongs():
    """ROTATE moves an additive copy of BANK levels through enabled bands."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def send(ctx, inputs):
        for channel, sample in enumerate(inputs):
            ctx.set(dut.i.payload[channel].as_value(), sample)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)
        ctx.set(dut.o.ready, 0)

    async def pulse(ctx):
        await send(ctx, (0, 0, 0, 0))
        await send(ctx, (0, 0, 0, 6000))

    async def reset(ctx):
        await send(ctx, (0, 6000, 0, 0))
        await send(ctx, (0, 0, 0, 0))

    def vector(ctx):
        return tuple(ctx.get(value) for value in dut.clock_modulations)

    async def bench(ctx):
        ctx.set(dut.clock_mode, 1)
        ctx.set(dut.clock_algorithm, dut.CLOCK_ALGORITHM_ROTATE)
        for n in range(dut.N_BANDS):
            ctx.set(dut.levels[n], (n + 1) * 1000)

        # First forward pulse copies each natural BANK level into the next
        # band's modulation without changing any natural level.
        await pulse(ctx)
        assert vector(ctx)[:4] == (10000, 1000, 2000, 3000)
        assert tuple(ctx.get(dut.levels[n]) for n in range(4)) == \
            (1000, 2000, 3000, 4000)
        await pulse(ctx)
        assert vector(ctx)[:4] == (9000, 10000, 1000, 2000)

        # Disabled bands disappear from the ring rather than swallowing a
        # rotation step.
        await reset(ctx)
        ctx.set(dut.band_enables[1], 0)
        await pulse(ctx)
        assert vector(ctx)[:4] == (10000, 0, 1000, 3000)

        # Reverse copies from the next enabled band.
        await reset(ctx)
        ctx.set(dut.band_enables[1], 1)
        ctx.set(dut.shift_direction, dut.SHIFT_BACKWARD)
        await pulse(ctx)
        assert vector(ctx)[:4] == (2000, 3000, 4000, 5000)

        # With three enabled bands, PING flips after three pulses and the
        # fourth pulse traverses the ring in reverse.
        await reset(ctx)
        for n in range(3, dut.N_BANDS):
            ctx.set(dut.band_enables[n], 0)
        ctx.set(dut.shift_direction, dut.SHIFT_PING_PONG)
        await pulse(ctx)
        assert vector(ctx)[:3] == (3000, 1000, 2000)
        await pulse(ctx)
        assert vector(ctx)[:3] == (2000, 3000, 1000)
        await pulse(ctx)
        assert vector(ctx)[:3] == (1000, 2000, 3000)
        await pulse(ctx)
        assert vector(ctx)[:3] == (2000, 3000, 1000)

    sim.add_testbench(bench)
    sim.run()
