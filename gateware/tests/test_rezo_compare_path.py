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


def test_filter_profile_band_tags_do_not_wrap():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    profiles = {}

    async def bench(ctx):
        ctx.set(dut.filter_mode, 1)
        for filter_type, name in ((dut.FILTER_LP, "lp"),
                                  (dut.FILTER_HP, "hp")):
            ctx.set(dut.filter_type, filter_type)
            for _ in range(64):
                await ctx.tick()
            profiles[name] = [ctx.get(level) for level in dut.filter_levels]

    sim.add_testbench(bench)
    sim.run()

    lp = profiles["lp"]
    hp = profiles["hp"]
    assert lp[0] == dut.FILTER_PASS_LEVEL
    assert lp[-1] == 0
    assert all(left >= right for left, right in zip(lp, lp[1:]))
    assert hp[0] == 0
    assert hp[-1] == dut.FILTER_PASS_LEVEL
    assert all(left <= right for left, right in zip(hp, hp[1:]))


def test_filter_cv_matrix_modulates_all_five_destinations():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    result = {}

    async def send(ctx):
        for channel, sample in enumerate((0, 12_000, 8_000, 10_000)):
            ctx.set(dut.i.payload[channel].as_value(), sample)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)

    async def bench(ctx):
        ctx.set(dut.filter_mode, 1)
        # IN1 raises frequency and slope, IN2 lowers resonance, IN3 raises
        # width, and IN2 raises drive. Matrix storage is destination-major.
        ctx.set(dut.filter_cv_matrix[0], 32)
        ctx.set(dut.filter_cv_matrix[3 + 1], -32)
        ctx.set(dut.filter_cv_matrix[6 + 2], 32)
        ctx.set(dut.filter_cv_matrix[9 + 0], 32)
        ctx.set(dut.filter_cv_matrix[12 + 1], 32)
        for _ in range(160):
            await send(ctx)
        result.update(
            cutoff=ctx.get(dut.effective_filter_cutoff),
            resonance=ctx.get(dut.effective_resonance),
            width=ctx.get(dut.effective_filter_width),
            slope=ctx.get(dut.effective_filter_slope),
            drive=ctx.get(dut.effective_drive),
        )

    sim.add_testbench(bench)
    sim.run()

    assert result["cutoff"] > 16384
    assert result["resonance"] < 16384
    assert result["width"] > 12288
    assert result["slope"] > 16384
    assert result["drive"] > 16384


def test_mode_change_slews_shared_band_gains():
    """BANK/FILTER changes ramp the gain vector instead of switching it."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    levels = []

    async def send(ctx):
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)

    async def bench(ctx):
        # The default BANK shape is zero while the default LP response passes
        # the first band. Its first FILTER sample must move only one slew step.
        ctx.set(dut.filter_mode, 1)
        await send(ctx)
        levels.append(ctx.get(dut.active_levels[0]))
        await send(ctx)
        levels.append(ctx.get(dut.active_levels[0]))

        # Returning to BANK takes the same bounded path toward zero.
        ctx.set(dut.filter_mode, 0)
        await send(ctx)
        levels.append(ctx.get(dut.active_levels[0]))

    sim.add_testbench(bench)
    sim.run()

    assert levels == [dut.PARAM_SLEW_STEP,
                      2 * dut.PARAM_SLEW_STEP,
                      dut.PARAM_SLEW_STEP]


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


def test_strong_band5_resonance_has_no_guard_bit_sign_wrap():
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
            ctx.set(level, 512 if index == 5 else 0)
        ctx.set(dut.band_frequencies[5], dut.frequency_index(16_000))
        # Use an upper table entry so the resonator reaches the guard-bit
        # boundary quickly enough to keep this regression inexpensive.
        for n in range(1024):
            sample = int(32_000 * math.sin(2 * math.pi * 4_000 * n / 192_000))
            await send(ctx, sample)

    sim.add_testbench(bench)
    sim.run()

    tail = output[-256:]
    max_step = max(abs(current - previous)
                   for previous, current in zip(tail, tail[1:]))
    # A correctly rescaled band state remains continuous at this low output
    # gain. The old raw-width truncation flipped sign at the guard-bit boundary
    # and produced a 1,929-count adjacent-sample jump; the corrected 4 kHz
    # waveform stays below 500 counts while retaining its ordinary slope.
    assert max_step < 800, (min(tail), max(tail), max_step, tail[-32:])
