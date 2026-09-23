import math

from amaranth.sim import Simulator

from top.rezo.rezo_variant import RezoCore


def test_input_bus_telemetry_reports_pre_drive_mix_and_sum_clipping():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = {}

    async def send(ctx, samples):
        for channel, sample in enumerate(samples):
            ctx.set(dut.i.payload[channel].as_value(), sample)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)

    async def bench(ctx):
        # The default routing exposes only IN0 at unity. DRIVE must not alter
        # the display tap because the tap is immediately before that stage.
        ctx.set(dut.drive, 0)
        await send(ctx, (12_000, 0, 0, 0))
        captured["clean_sample"] = ctx.get(
            dut.input_bus_sample.as_value())
        captured["clean_clip"] = ctx.get(dut.input_bus_clip)

        # Bring the remaining inputs toward unity and overload the sum.
        # Telemetry must show the clamped bus and separately retain the fact
        # that its unclamped sum exceeded it.
        for channel in range(1, 4):
            ctx.set(dut.input_modes[channel], dut.INPUT_MODE_AUDIO)
            ctx.set(dut.input_gains[channel], dut.INPUT_UNITY_POS)
        for _ in range(192):
            await send(ctx, (24_000, 24_000, 24_000, 24_000))
        captured["hot_sample"] = ctx.get(
            dut.input_bus_sample.as_value())
        captured["hot_clip"] = ctx.get(dut.input_bus_clip)

    sim.add_testbench(bench)
    sim.run()

    assert 11_990 <= captured["clean_sample"] <= 12_000
    assert captured["clean_clip"] == 0
    assert captured["hot_sample"] == 32_767
    assert captured["hot_clip"] == 1


def test_extreme_resonance_feedback_and_drive_recovers_after_controls_retreat():
    """Saturated SVF state must not wrap into a persistent full-scale orbit."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    recovered = []

    def swarm_sample(n):
        # Nearby non-harmonic components repeatedly align and separate, which
        # excites the same high-Q multi-band condition reported on hardware.
        return sum(int(9000 * math.sin(n * phase))
                   for phase in (0.071, 0.083, 0.097)) // 3

    async def send(ctx, sample):
        ctx.set(dut.i.payload[0].as_value(), sample)
        for channel in range(1, 4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            *[dut.o.payload[channel].as_value() for channel in range(4)]
        ).until(dut.o.valid == 1)
        return values[0]

    async def bench(ctx):
        for n, level in enumerate(dut.levels):
            ctx.set(level, 8192 if n & 1 else 0)
            ctx.set(dut.band_enables[n], n not in (0, 2, 4))
            ctx.set(dut.bank_groups[n], 1)
            ctx.set(dut.feedback_sends[n], 1)
        ctx.set(dut.drive, 24_575)
        ctx.set(dut.resonance, 32_768)
        ctx.set(dut.feedback, 32_768)
        ctx.set(dut.damp_mode, 0)
        ctx.set(dut.limit_knee, 19_660)
        ctx.set(dut.limit_cap, 32_767)
        for n in range(1536):
            await send(ctx, swarm_sample(n))

        # Pull every destabilizing control back while input continues. A
        # healthy filter should leave the rails without requiring a reboot.
        for level in dut.levels:
            ctx.set(level, 0)
        ctx.set(dut.drive, dut.DRIVE_DEFAULT)
        ctx.set(dut.resonance, 8192)
        ctx.set(dut.feedback, 0)
        ctx.set(dut.damp_mode, 3)
        ctx.set(dut.limit_knee, 12_288)
        ctx.set(dut.limit_cap, 28_672)
        for n in range(512):
            await send(ctx, swarm_sample(1536 + n))

        ctx.set(dut.levels[5], 1024)
        for n in range(512):
            value = await send(ctx, swarm_sample(2048 + n))
            if n >= 384:
                recovered.append(value)

    sim.add_testbench(bench)
    sim.run()

    peak = max(abs(value) for value in recovered)
    rail_count = sum(value in (-32768, 32767) for value in recovered)
    assert peak < 8000 and rail_count == 0, (peak, rail_count, recovered[-32:])


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
        ctx.set(dut.feedback, 8192)
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
            feedback=ctx.get(dut.effective_feedback),
        )

    sim.add_testbench(bench)
    sim.run()

    assert result["cutoff"] > 16384
    assert result["resonance"] < 16384
    assert result["width"] > 12288
    assert result["slope"] > 16384
    assert result["drive"] > 16384
    assert result["feedback"] > 0


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


def test_filter_dry_uses_all_audio_role_inputs():
    """FILTER DRY follows the same per-jack AUDIO/CV mix as BANK."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = {}

    async def send(ctx):
        ctx.set(dut.i.payload[0].as_value(), 2_000)
        ctx.set(dut.i.payload[1].as_value(), 2_000)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            dut.o.payload[0].as_value()).until(dut.o.valid == 1)
        return values[0]

    async def bench(ctx):
        ctx.set(dut.filter_mode, 1)
        for send_level in dut.output_sends:
            ctx.set(send_level, 0)
        ctx.set(dut.output_sends[dut.N_GROUPS], 16)

        # As CV, IN1 is absent from DRY.
        for _ in range(16):
            captured["cv"] = await send(ctx)

        # As AUDIO at unity, the same jack joins IN0 in the DRY mix.
        ctx.set(dut.input_modes[1], dut.INPUT_MODE_AUDIO)
        ctx.set(dut.input_gains[1], dut.INPUT_UNITY_POS)
        for _ in range(224):
            captured["audio"] = await send(ctx)

    sim.add_testbench(bench)
    sim.run()

    assert abs(captured["cv"] - 2_000) <= 2
    # Gain changes are deliberately slewed at 64 counts per audio sample, so
    # the second jack is only partway to unity here; nevertheless it must be
    # clearly present in FILTER's DRY mix once its role changes to AUDIO.
    assert captured["audio"] > captured["cv"] + 400
