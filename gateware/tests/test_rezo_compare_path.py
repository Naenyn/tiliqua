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


def test_input_meters_use_audio_post_value_and_cv_pre_depth():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = {}

    async def bench(ctx):
        ctx.set(dut.o.ready, 1)
        ctx.set(dut.i.payload[0].as_value(), 12_000)
        ctx.set(dut.i.payload[2].as_value(), -12_345)
        # DEPTH must have no bearing on the CV meter.
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
        ctx.set(dut.input_jacks, 1 << 3)
        ctx.set(dut.clock_mode, 1)

        # Forward inserts at band 0 and moves older captures upward.
        await pulse(ctx, 8000)
        assert vector(ctx)[:3] == (4000, 0, 0)
        ctx.set(dut.clock_depth, 64)
        for _ in range(dut.N_BANDS + 2):
            await ctx.tick()
        assert tuple(ctx.get(value) for value in
                     dut.clock_scaled_modulations)[:3] == (2000, 0, 0)
        ctx.set(dut.clock_depth, 128)
        # Holding high, including inside the hysteresis window, cannot retrigger.
        await send(ctx, (0, 0, 12000, 7000))
        await send(ctx, (0, 0, 12000, 2000))
        await send(ctx, (0, 0, 12000, 7000))
        assert vector(ctx)[:3] == (4000, 0, 0)
        await pulse(ctx, -6000)
        assert vector(ctx)[:3] == (-3000, 4000, 0)
        ctx.set(dut.clock_depth, 64)
        for _ in range(dut.N_BANDS + 2):
            await ctx.tick()
        assert tuple(ctx.get(value) for value in
                     dut.clock_scaled_modulations)[:3] == (-1500, 2000, 0)
        ctx.set(dut.clock_depth, 128)

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
        ctx.set(dut.input_jacks, 1 << 1)
        await send(ctx, (6000, 0, 0, 0))
        await send(ctx, (6000, 6000, 0, 0))
        assert vector(ctx)[0] == 3000
        await send(ctx, (0, 0, 0, 6000))
        assert vector(ctx) == (0,) * dut.N_BANDS

        # RAND ignores the external DATA voltage and samples an independent
        # running bipolar noise source. AUTO follows physical patch presence
        # for the jack currently assigned to DATA.
        ctx.set(dut.data_source, dut.DATA_SOURCE_RANDOM)
        ctx.set(dut.input_jacks, 1 << 1)
        await send(ctx, (0, 0, 0, 0))
        await send(ctx, (0, 6000, 0, 0))
        assert ctx.get(dut.data_random_active) == 1
        assert vector(ctx)[0] != 0

        await send(ctx, (0, 0, 0, 6000))
        await send(ctx, (0, 0, 0, 0))
        ctx.set(dut.data_source, dut.DATA_SOURCE_AUTO)
        await send(ctx, (0, 0, 0, 0))
        await send(ctx, (0, 6000, 0, 0))
        assert ctx.get(dut.data_random_active) == 1
        assert vector(ctx)[0] != 0

        await send(ctx, (0, 0, 0, 6000))
        await send(ctx, (0, 0, 0, 0))
        ctx.set(dut.input_jacks, (1 << 0) | (1 << 1))
        await send(ctx, (6000, 0, 0, 0))
        await send(ctx, (6000, 6000, 0, 0))
        assert ctx.get(dut.data_random_active) == 0
        assert vector(ctx)[0] == 3000

    sim.add_testbench(bench)
    sim.run()


def test_clocked_rotate_uses_bank_levels_and_skips_disabled_bands():
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
        ctx.set(dut.input_jacks, 1 << 3)
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

    sim.add_testbench(bench)
    sim.run()


def test_clocked_walk_steps_reflects_skips_disabled_and_resets():
    """WALK independently steps enabled bands and reflects at both rails."""
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

    def vector(ctx):
        return tuple(ctx.get(value) for value in dut.clock_modulations)

    async def bench(ctx):
        ctx.set(dut.input_jacks, 1 << 3)
        ctx.set(dut.clock_mode, 1)
        ctx.set(dut.clock_algorithm, dut.CLOCK_ALGORITHM_WALK)

        # The initial 0xACE1 direction word is deterministic. STEP defaults to
        # four display units, represented by 1024 raw modulation counts.
        await pulse(ctx)
        assert vector(ctx) == (
            1024, -1024, -1024, -1024, -1024,
            1024, 1024, 1024, -1024, -1024,
        )

        # Disabled destinations are forced to zero instead of retaining stale
        # walk state. Re-enabling therefore resumes cleanly from zero.
        ctx.set(dut.band_enables[1], 0)
        await pulse(ctx)
        assert vector(ctx)[1] == 0

        # Either random direction must turn inward at a rail. Use the largest
        # step so both positive and negative reflection are easy to verify.
        ctx.set(dut.walk_step_index, len(dut.WALK_STEPS) - 1)
        ctx.set(dut.clock_modulations[0], dut.WALK_LIMIT)
        ctx.set(dut.clock_modulations[2], -dut.WALK_LIMIT)
        await pulse(ctx)
        assert vector(ctx)[0] == dut.WALK_LIMIT - dut.WALK_STEPS[-1]
        assert vector(ctx)[2] == -dut.WALK_LIMIT + dut.WALK_STEPS[-1]
        assert all(-dut.WALK_LIMIT <= value <= dut.WALK_LIMIT
                   for value in vector(ctx))

        await send(ctx, (0, 6000, 0, 0))
        await send(ctx, (0, 0, 0, 0))
        assert vector(ctx) == (0,) * dut.N_BANDS

    sim.add_testbench(bench)
    sim.run()


def test_clocked_head_walk_stumbles_in_time_and_respects_chance():
    """HEAD takes single spatial steps and can burst between clock pulses."""
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
        ctx.set(dut.input_jacks, 1 << 3)
        ctx.set(dut.clock_mode, 1)
        ctx.set(dut.clock_algorithm, dut.CLOCK_ALGORITHM_WALK)
        ctx.set(dut.walk_style, dut.WALK_STYLE_HEAD)

        # DRUNK 4 with 100% CHANCE turns the second learned external interval
        # into four total landings: one on the clock edge and three evenly
        # spaced extra landings. Each landing still moves exactly one enabled
        # band rather than choosing a wider spatial stride.
        ctx.set(dut.walk_drunk, 3)
        ctx.set(dut.walk_chance_index, len(dut.WALK_CHANCES) - 1)
        await pulse(ctx)  # Learn the first external edge; no interval yet.
        for _ in range(12):
            await send(ctx, (0, 0, 0, 0))
        before = vector(ctx)
        await send(ctx, (0, 0, 0, 6000))
        previous = vector(ctx)
        changes = int(previous != before)
        for _ in range(20):
            await send(ctx, (0, 0, 0, 0))
            current = vector(ctx)
            if current != previous:
                changes += 1
                previous = current
        assert changes == 4

        # Zero chance suppresses the stumble while retaining the ordinary
        # clock-edge landing.
        await reset(ctx)
        ctx.set(dut.walk_chance_index, 0)
        before = vector(ctx)
        await pulse(ctx)
        previous = vector(ctx)
        changes = int(previous != before)
        for _ in range(20):
            await send(ctx, (0, 0, 0, 0))
            current = vector(ctx)
            if current != previous:
                changes += 1
                previous = current
        assert changes == 1

        ctx.set(dut.walk_drunk, 0)
        ctx.set(dut.walk_chance_index, dut.WALK_CHANCE_DEFAULT)
        await reset(ctx)

        # 0xACE1 first requests a move below band zero, which reflects onto
        # band one. Only that landing changes.
        await pulse(ctx)
        assert vector(ctx) == (0, -1024, 0, 0, 0, 0, 0, 0, 0, 0)

        # The next deterministic bit moves back to band zero; the first
        # landing remains untouched rather than every band advancing.
        await pulse(ctx)
        assert vector(ctx) == (-1024, -1024, 0, 0, 0, 0, 0, 0, 0, 0)

        # A one-step move skips disabled band one and lands on band two.
        await reset(ctx)
        ctx.set(dut.band_enables[1], 0)
        await pulse(ctx)
        assert vector(ctx) == (0, 0, -1024, 0, 0, 0, 0, 0, 0, 0)

        # Value reflection is shared with ALL: a requested negative move at
        # the lower rail turns inward by exactly one selected step.
        await reset(ctx)
        ctx.set(dut.band_enables[1], 1)
        ctx.set(dut.clock_modulations[1], -dut.WALK_LIMIT)
        await pulse(ctx)
        assert vector(ctx)[1] == -dut.WALK_LIMIT + dut.WALK_STEPS[
            dut.WALK_STEP_DEFAULT]

    sim.add_testbench(bench)
    sim.run()


def test_internal_clock_auto_jack_detection_and_safe_handoff():
    """AUTO follows physical patch state without transition double-clocks."""
    dut = RezoCore(
        fs=192_000,
        internal_clock_periods=(3,) * (
            RezoCore.INTERNAL_CLOCK_MAX_BPM -
            RezoCore.INTERNAL_CLOCK_MIN_BPM + 1))
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def send(ctx, clock=0, data=8000):
        for channel, sample in enumerate((0, 0, data, clock)):
            ctx.set(dut.i.payload[channel].as_value(), sample)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)
        ctx.set(dut.o.ready, 0)

    def vector(ctx):
        return tuple(ctx.get(value) for value in dut.clock_modulations)

    async def bench(ctx):
        assert ctx.get(dut.clock_source) == dut.CLOCK_SOURCE_AUTO
        ctx.set(dut.clock_mode, 1)

        # Entering CLOCK starts a complete internal period. With no cable in
        # the assigned CLK jack, AUTO reports and uses the internal source.
        await send(ctx)
        assert ctx.get(dut.clock_external_active) == 0
        await send(ctx)
        await send(ctx)
        assert vector(ctx) == (0,) * dut.N_BANDS
        await send(ctx)
        assert vector(ctx)[0] == 4000

        # Inserting a cable while it is high never creates a patch-edge clock.
        ctx.set(dut.input_jacks, 1 << 3)
        await send(ctx, clock=6000, data=12000)
        await send(ctx, clock=6000, data=12000)
        assert ctx.get(dut.clock_external_active) == 1
        assert vector(ctx)[0] == 4000
        await send(ctx, clock=0, data=12000)
        await send(ctx, clock=6000, data=12000)
        assert vector(ctx)[:2] == (6000, 4000)

        # Unpatching restarts a full internal period rather than clocking on
        # the source transition.
        ctx.set(dut.input_jacks, 0)
        await send(ctx, data=-6000)
        assert vector(ctx)[:2] == (6000, 4000)
        await send(ctx, data=-6000)
        await send(ctx, data=-6000)
        assert vector(ctx)[:2] == (6000, 4000)
        await send(ctx, data=-6000)
        assert vector(ctx)[:3] == (-3000, 6000, 4000)

        # Overrides are unconditional: INT ignores a patched cable, while EXT
        # with no cable assigned waits indefinitely instead of timing out.
        ctx.set(dut.clock_source, dut.CLOCK_SOURCE_INTERNAL)
        ctx.set(dut.input_jacks, 1 << 3)
        await send(ctx, clock=6000, data=2000)
        assert ctx.get(dut.clock_external_active) == 0
        ctx.set(dut.clock_source, dut.CLOCK_SOURCE_EXTERNAL)
        ctx.set(dut.input_jacks, 0)
        await send(ctx, data=14000)
        for _ in range(5):
            await send(ctx, data=14000)
        assert ctx.get(dut.clock_external_active) == 1
        assert vector(ctx)[:3] == (-3000, 6000, 4000)

    sim.add_testbench(bench)
    sim.run()


def test_clocked_turing_fills_mutates_locks_and_skips_disabled_bands():
    """TURING evolves internally, then repeats exactly while LOCK is high."""
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

    async def pulse(ctx, lock=0):
        await send(ctx, (0, lock, 0, 0))
        await send(ctx, (0, lock, 0, 6000))

    def vector(ctx):
        return tuple(ctx.get(value) for value in dut.clock_modulations)

    async def bench(ctx):
        ctx.set(dut.input_jacks, 1 << 3)
        ctx.set(dut.clock_mode, 1)
        ctx.set(dut.clock_algorithm, dut.CLOCK_ALGORITHM_TURING)
        ctx.set(dut.turing_length, 3)
        ctx.set(dut.turing_change, 255)
        ctx.set(dut.cv_targets[1], dut.CV_TARGET_LOCK)
        ctx.set(dut.band_enables[1], 0)

        # Initial fill always admits internal random values, even if LOCK is
        # already high. ALL repeats the short pattern across enabled bands.
        for _ in range(3):
            await pulse(ctx, lock=6000)
        filled = vector(ctx)
        filled_pattern = (filled[0], filled[2], filled[3])
        assert all(value != 0 for value in filled_pattern)
        assert filled == (
            filled_pattern[0], 0,
            filled_pattern[1], filled_pattern[2],
            filled_pattern[0], filled_pattern[1], filled_pattern[2],
            filled_pattern[0], filled_pattern[1], filled_pattern[2])

        # One forward locked pulse rotates [0, 2, 3] and recycles the departing
        # value; a complete three-pulse period returns exactly to its start.
        await pulse(ctx, lock=6000)
        assert vector(ctx)[:4] == (
            filled_pattern[2], 0, filled_pattern[0], filled_pattern[1])
        await pulse(ctx, lock=6000)
        await pulse(ctx, lock=6000)
        assert vector(ctx) == filled

        # Low LOCK plus 100% CHANGE injects a fresh internal value while still
        # shifting the previous loop. DATA is not involved.
        await pulse(ctx, lock=0)
        changed = vector(ctx)
        assert changed[1] == 0
        assert changed[2] == filled[0]
        assert changed[3] == filled[2]
        assert changed[0] != filled[3]

        # Reverse circulates the same selected loop in the opposite direction.
        await send(ctx, (0, 6000, 0, 0))
        ctx.set(dut.shift_direction, dut.SHIFT_BACKWARD)
        before_reverse = vector(ctx)
        await pulse(ctx, lock=6000)
        assert vector(ctx)[:4] == (
            before_reverse[2], 0, before_reverse[3], before_reverse[0])

        # PING PONG begins forward, reverses after one complete loop-length
        # traversal, and therefore retraces the most recent rotation.
        ctx.set(dut.shift_direction, dut.SHIFT_PING_PONG)
        before_ping = (vector(ctx)[0], vector(ctx)[2], vector(ctx)[3])
        await pulse(ctx, lock=6000)
        assert (vector(ctx)[0], vector(ctx)[2], vector(ctx)[3]) == (
            before_ping[2], before_ping[0], before_ping[1])
        await pulse(ctx, lock=6000)
        await pulse(ctx, lock=6000)
        assert (vector(ctx)[0], vector(ctx)[2], vector(ctx)[3]) == before_ping
        await pulse(ctx, lock=6000)
        assert (vector(ctx)[0], vector(ctx)[2], vector(ctx)[3]) == (
            before_ping[1], before_ping[2], before_ping[0])

        # RANGE maps the private pattern once to physical bands 6..8 and
        # clears every band outside that explicit target window.
        range_pattern = (vector(ctx)[0], vector(ctx)[2], vector(ctx)[3])
        ctx.set(dut.turing_target, dut.TURING_TARGET_RANGE)
        ctx.set(dut.turing_start, 5)
        await send(ctx, (0, 6000, 0, 0))
        ranged = vector(ctx)
        assert ranged[:5] == (0,) * 5
        assert ranged[5:8] == range_pattern
        assert ranged[8:] == (0,) * 2

        # RESET is intentionally ignored by TURING.
        ctx.set(dut.cv_targets[2], dut.CV_TARGET_RESET)
        before_reset = vector(ctx)
        await send(ctx, (0, 6000, 6000, 0))
        assert vector(ctx) == before_reset

    sim.add_testbench(bench)
    sim.run()
