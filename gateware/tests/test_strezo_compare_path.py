import math

from amaranth.sim import Simulator

from top.rezo.strezo_variant import RezoCore


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
    assert result["cycles"] <= 270


def test_internal_triangle_motion_phase_spreads_across_bands():
    """One oscillator is sampled at a programmable phase per band."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    patterns = []

    async def send(ctx):
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)

    async def bench(ctx):
        for level in dut.levels:
            ctx.set(level, 0)
        ctx.set(dut.motion_source, 1)
        ctx.set(dut.motion_rate, 1)
        ctx.set(dut.motion_phase, 64)  # quarter-cycle between bands
        ctx.set(dut.motion_depth, 64)  # 50%
        await send(ctx)
        patterns.append(tuple(ctx.get(level) for level in dut.effective_levels))

        # RAND is sample-and-hold at RATE, so adjacent audio samples retain
        # exactly the same ten-band pattern rather than becoming audio noise.
        ctx.set(dut.motion_source, 2)
        await send(ctx)
        first_random = tuple(ctx.get(level) for level in dut.effective_levels)
        await send(ctx)
        second_random = tuple(ctx.get(level) for level in dut.effective_levels)
        patterns.extend((first_random, second_random))

    sim.add_testbench(bench)
    sim.run()

    triangle, first_random, second_random = patterns
    assert triangle[0] < -15_000
    assert abs(triangle[1]) < 100
    assert triangle[2] > 15_000
    assert abs(triangle[3]) < 100
    assert first_random == second_random
    assert len(set(first_random)) > 4


def test_motion_monitor_reports_the_post_depth_base_lfo():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = {}

    async def send(ctx):
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)

    async def bench(ctx):
        ctx.set(dut.motion_source, RezoCore.MOTION_SOURCE_TRIANGLE)
        ctx.set(dut.motion_rate, 1)

        ctx.set(dut.motion_depth, 0)
        await send(ctx)
        captured["zero"] = ctx.get(dut.motion_monitor)

        ctx.set(dut.motion_depth, 64)
        await send(ctx)
        captured["half"] = ctx.get(dut.motion_monitor)

        ctx.set(dut.motion_depth, 128)
        await send(ctx)
        captured["full"] = ctx.get(dut.motion_monitor)

    sim.add_testbench(bench)
    sim.run()

    assert captured["zero"] == 0
    assert abs(captured["half"]) > 0
    assert abs(captured["full"]) >= 2 * abs(captured["half"]) - 1


def test_cv_inputs_sum_once_into_their_selected_target():
    """Two CV inputs share one target without a target-first rescan."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = []

    async def send(ctx):
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)

    async def bench(ctx):
        ctx.set(dut.i.payload[2].as_value(), 10_000)
        ctx.set(dut.i.payload[3].as_value(), 10_000)
        ctx.set(dut.cv_depths[2], 256)
        ctx.set(dut.cv_depths[3], 256)
        ctx.set(dut.cv_targets[2], dut.CV_TARGET_RESONANCE)
        ctx.set(dut.cv_targets[3], dut.CV_TARGET_RESONANCE)
        for _ in range(8):
            await send(ctx)
        captured.append(ctx.get(dut.effective_resonance))

        # Removing either contributor on the next sample must leave roughly
        # half the positive offset.  Input-mode routing, not target scanning,
        # decides whether its already-computed product participates.
        ctx.set(dut.input_modes[3], dut.INPUT_MODE_LEFT)
        for _ in range(2):
            await send(ctx)
        captured.append(ctx.get(dut.effective_resonance))

    sim.add_testbench(bench)
    sim.run()

    both, one = captured
    assert both > one > 8192
    assert abs((both - 8192) - 2 * (one - 8192)) <= 3


def test_stereo_dry_path_preserves_channel_separation_and_output_assignment():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = []

    async def send(ctx, left, right):
        ctx.set(dut.i.payload[0].as_value(), left)
        ctx.set(dut.i.payload[1].as_value(), right)
        ctx.set(dut.i.payload[2].as_value(), 0)
        ctx.set(dut.i.payload[3].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            *[dut.o.payload[n].as_value() for n in range(4)]
        ).until(dut.o.valid == 1)
        captured.append(tuple(values))

    async def bench(ctx):
        for send_control in dut.output_sends:
            ctx.set(send_control, 0)
        ctx.set(dut.output_sends[dut.N_GROUPS], 16)
        ctx.set(dut.output_sends[(dut.N_GROUPS + 1) + dut.N_GROUPS], 16)
        await send(ctx, 7000, 0)
        await send(ctx, 0, -9000)
        ctx.set(dut.output_sides[1], 0)
        await send(ctx, 5000, -7000)

    sim.add_testbench(bench)
    sim.run()

    left_only, right_only, reassigned = captured
    assert abs(left_only[0] - 7000) <= 2
    assert left_only[1] == 0
    assert right_only[0] == 0
    assert abs(right_only[1] + 9000) <= 2
    assert abs(reassigned[0] - 5000) <= 2
    assert abs(reassigned[1] - 5000) <= 2


def test_cross_feedback_moves_only_the_feedback_path_between_channels():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    right_outputs = []
    left_outputs = []
    feedback_probes = []

    async def send(ctx, left):
        ctx.set(dut.i.payload[0].as_value(), left)
        for channel in range(1, 4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            *[dut.o.payload[n].as_value() for n in range(4)]
        ).until(dut.o.valid == 1)
        right_outputs.append(values[1])
        left_outputs.append(values[0])
        feedback_probes.append((ctx.get(dut._feedback_sample_l.as_value()),
                                ctx.get(dut._feedback_sample_r.as_value()),
                                ctx.get(dut._feedback_mix_l.as_value()),
                                ctx.get(dut._feedback_mix_r.as_value()),
                                ctx.get(dut._feedback_acc_l),
                                ctx.get(dut._feedback_gain)))

    async def bench(ctx):
        for level in dut.levels:
            ctx.set(level, 8_192)
        ctx.set(dut.feedback, 4_096)
        ctx.set(dut.cross_feedback, dut.CROSS_DEPTH_MAX)
        for n in range(96):
            await send(ctx, int(12_000 * math.sin(n * 0.19)))

    sim.add_testbench(bench)
    sim.run()

    # The direct stimulus remains on the left. Subsequent non-zero right-side
    # energy can therefore only have arrived through the crossed feedback tap.
    assert right_outputs[0] == 0
    assert any(value != 0 for value in right_outputs[1:]), \
        (left_outputs[-16:], feedback_probes[-16:])


def test_cross_curve_lookup_preserves_endpoints_and_shapes_midrange():
    """All curves retain instability at full scale but redistribute travel."""
    curves = (
        RezoCore.CROSS_CURVE_LINEAR,
        RezoCore.CROSS_CURVE_LOG,
    )
    for curve in curves:
        values = [RezoCore.cross_curve_coefficient(curve, raw)
                  for raw in range(RezoCore.CROSS_DEPTH_MAX + 1)]
        assert values[0] == 0
        assert values[-1] == RezoCore.CROSS_COEFFICIENT_MAX
        assert values == sorted(values)
        assert len(set(values)) == RezoCore.CROSS_DEPTH_MAX + 1

    midpoint = RezoCore.CROSS_DEPTH_MAX // 2
    linear, log = (
        RezoCore.cross_curve_coefficient(curve, midpoint)
        for curve in (RezoCore.CROSS_CURVE_LINEAR,
                      RezoCore.CROSS_CURVE_LOG)
    )
    assert log > linear
    assert RezoCore.cross_curve_coefficient(RezoCore.CROSS_CURVE_LOG, 32) == 15941
    assert RezoCore.cross_curve_coefficient(RezoCore.CROSS_CURVE_LOG, 64) == 23701

    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.cross_feedback, midpoint)
        for curve in curves:
            ctx.set(dut.cross_curve, curve)
            for _ in range(3):
                await ctx.tick()
            assert ctx.get(dut._effective_cross_feedback) == \
                RezoCore.cross_curve_coefficient(curve, midpoint)

    sim.add_testbench(bench)
    sim.run()


def test_group_cross_matrix_routes_source_group_to_selected_destination():
    """An immutable factory route is generated without touching USER."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    routed_terms = []

    async def send(ctx, left):
        ctx.set(dut.i.payload[0].as_value(), left)
        for channel in range(1, 4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)
        routed_terms.append(tuple(
            ctx.get(dut._matrix_feedback_term_r[n].as_value())
            for n in range(dut.N_GROUPS)))

    async def bench(ctx):
        for level in dut.levels:
            ctx.set(level, 0)
        ctx.set(dut.levels[0], 8_192)
        ctx.set(dut.feedback, 8_192)
        ctx.set(dut.cross_feedback, dut.CROSS_DEPTH_MAX)
        ctx.set(dut.cross_layout, RezoCore.CROSS_LAYOUT_ROTATE)
        for coefficient in dut.cross_matrix:
            ctx.set(coefficient, 0)
        # ROTATE is generated independently of the all-zero USER matrix:
        # opposite-channel G1 routes only to destination G2.
        for n in range(96):
            await send(ctx, int(12_000 * math.sin(n * 0.19)))

    sim.add_testbench(bench)
    sim.run()

    assert any(values[1] != 0 for values in routed_terms[4:])
    assert all(values[0] == values[2] == values[3] == 0
               for values in routed_terms)


def _matrix_feedback_peak(knee, ceiling):
    """Measure routed feedback after the destination shaper and final gain."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    routed = []

    async def send(ctx, sample):
        ctx.set(dut.i.payload[0].as_value(), sample)
        for channel in range(1, 4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)
        routed.extend(abs(ctx.get(term.as_value()))
                      for term in dut._matrix_feedback_term_r)

    async def bench(ctx):
        for level in dut.levels:
            ctx.set(level, 16_383)
        ctx.set(dut.feedback, 32_768)
        ctx.set(dut.same_feedback, 0)
        ctx.set(dut.cross_feedback, dut.CROSS_DEPTH_MAX)
        ctx.set(dut.cross_layout, RezoCore.CROSS_LAYOUT_USER)
        for coefficient in dut.cross_matrix:
            ctx.set(coefficient, 16)
        ctx.set(dut.limit_knee, knee)
        ctx.set(dut.limit_cap, ceiling)
        for n in range(192):
            sample = ((n * 7919) & 0xffff) - 32768
            await send(ctx, sample)

    sim.add_testbench(bench)
    sim.run()
    return max(routed[96 * dut.N_GROUPS:])


def test_knee_and_ceiling_shape_non_global_matrix_feedback():
    """Matrix CROSS must obey the same safety controls as GLOBAL CROSS."""
    constrained = _matrix_feedback_peak(knee=4096, ceiling=8192)
    open_range = _matrix_feedback_peak(knee=24576, ceiling=32767)
    assert constrained < open_range, (constrained, open_range)


def _render_cross_feedback(layout, depth):
    """Render unlike stereo sources through one CROSS configuration."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    captured = []

    async def send(ctx, left, right):
        ctx.set(dut.i.payload[0].as_value(), left)
        ctx.set(dut.i.payload[1].as_value(), right)
        ctx.set(dut.i.payload[2].as_value(), 0)
        ctx.set(dut.i.payload[3].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        values = await ctx.tick().sample(
            dut.o.payload[0].as_value(), dut.o.payload[1].as_value()
        ).until(dut.o.valid == 1)
        captured.append(tuple(values))

    async def bench(ctx):
        for level in dut.levels:
            ctx.set(level, 8_192)
        ctx.set(dut.feedback, 16_384)
        ctx.set(dut.cross_feedback, depth)
        ctx.set(dut.cross_layout, layout)
        for n in range(320):
            await send(ctx,
                       int(11_000 * math.sin(n * 0.19)),
                       int(9_000 * math.sin(n * 0.113 + 0.7)))

    sim.add_testbench(bench)
    sim.run()
    return captured[128:]


def test_cross_layout_and_depth_materially_change_stereo_audio_outputs():
    """CROSS must be an audible output behavior, not just an internal value."""
    uncrossed = _render_cross_feedback(RezoCore.CROSS_LAYOUT_GLOBAL, 0)
    global_cross = _render_cross_feedback(
        RezoCore.CROSS_LAYOUT_GLOBAL, RezoCore.CROSS_DEPTH_MAX)
    matrix_cross = _render_cross_feedback(
        RezoCore.CROSS_LAYOUT_DIAGONAL, RezoCore.CROSS_DEPTH_MAX)

    def total_delta(left, right):
        return sum(abs(a_l - b_l) + abs(a_r - b_r)
                   for (a_l, a_r), (b_l, b_r) in zip(left, right))

    assert total_delta(uncrossed, global_cross) > 100_000
    assert total_delta(uncrossed, matrix_cross) > 100_000


def test_quiet_resonator_state_decays_after_frequency_layout_change():
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    tail = []

    async def send(ctx, left, right):
        ctx.set(dut.i.payload[0].as_value(), left)
        ctx.set(dut.i.payload[1].as_value(), right)
        ctx.set(dut.i.payload[2].as_value(), 0)
        ctx.set(dut.i.payload[3].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        return await ctx.tick().sample(
            *[dut.o.payload[n].as_value() for n in range(2)]
        ).until(dut.o.valid == 1)

    async def bench(ctx):
        for level in dut.levels:
            ctx.set(level, 8_192)
        for n in range(256):
            await send(ctx,
                       int(10_000 * math.sin(n * 0.17)),
                       int(9_000 * math.sin(n * 0.113)))

        # Reproduce the hardware report: change factory layout, choose ZERO,
        # then let a very small negative middle-group amount expose residual
        # filter state while the input is silent.
        for band, frequency in enumerate(dut.PERCEPT_FREQS_HZ):
            ctx.set(dut.band_frequencies[band], dut.frequency_index(frequency))
            await send(ctx, 0, 0)
        for band, level in enumerate(dut.levels):
            ctx.set(level, -256 if 3 <= band <= 5 else 0)
        for n in range(768):
            values = await send(ctx, 0, 0)
            if n >= 640:
                tail.append(tuple(values))

    sim.add_testbench(bench)
    sim.run()

    assert tail == [(0, 0)] * len(tail)


def test_damp_modes_have_distinct_feedback_dependent_decay_coefficients():
    """Every named DAMP step must change inverse-Q at high feedback."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    observed = []

    async def send_zero(ctx):
        for channel in range(4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        await ctx.tick().until(dut.o.valid == 1)

    async def bench(ctx):
        ctx.set(dut.resonance, 32_768)
        ctx.set(dut.feedback, 32_768)
        # Parameter smoothing advances once per accepted audio sample.
        for _ in range(516):
            await send_zero(ctx)
        for mode in range(5):
            ctx.set(dut.damp_mode, mode)
            await ctx.tick()
            observed.append((ctx.get(dut._feedback_damp),
                             ctx.get(dut._resonance_ctl.as_value())))

    sim.add_testbench(bench)
    sim.run()

    assert observed == [
        (0, 0),
        (2048, 1024),
        (4096, 2048),
        (8192, 4096),
        (12288, 6144),
    ]


def test_extreme_feedback_low_damping_recovers_without_reboot():
    """Wrapped SVF state must not survive after controls return to safety."""
    dut = RezoCore(fs=192_000)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    recovered = []

    def swarm_sample(n):
        def saw(frequency):
            phase = (n * frequency * 65536 // 192_000) & 0xFFFF
            return phase - 32768
        return (saw(741) + saw(773) + saw(809)) // 3

    async def send(ctx, sample):
        ctx.set(dut.i.payload[0].as_value(), sample)
        # In-phase stereo makes full SAME + CROSS feedback reinforce instead
        # of partially cancel. This is the shortest deterministic route to the
        # hardware's extreme-feedback condition.
        ctx.set(dut.i.payload[1].as_value(), sample)
        for channel in range(2, 4):
            ctx.set(dut.i.payload[channel].as_value(), 0)
        ctx.set(dut.i.valid, 1)
        await ctx.tick().until(dut.i.ready == 1)
        ctx.set(dut.i.valid, 0)
        ctx.set(dut.o.ready, 1)
        return await ctx.tick().sample(
            dut.o.payload[0].as_value(), dut.o.payload[1].as_value()
        ).until(dut.o.valid == 1)

    async def bench(ctx):
        for index, level in enumerate(dut.levels):
            ctx.set(level, 16_384 if index == 5 else 0)
        ctx.set(dut.band_frequencies[5], dut.frequency_index(773))
        ctx.set(dut.drive, 24_576)
        ctx.set(dut.resonance, 32_768)
        ctx.set(dut.feedback, 32_768)
        ctx.set(dut.same_feedback, dut.CROSS_DEPTH_MAX)
        ctx.set(dut.cross_feedback, dut.CROSS_DEPTH_MAX)
        ctx.set(dut.cross_layout, dut.CROSS_LAYOUT_GLOBAL)
        ctx.set(dut.damp_mode, 0)
        for n in range(1536):
            await send(ctx, swarm_sample(n))

        # Return every destabilizing control to a conservative value while
        # the input continues, just as on hardware. Hide the wet state briefly,
        # then expose band 5 at a very low level to detect a latched orbit.
        for level in dut.levels:
            ctx.set(level, 0)
        ctx.set(dut.drive, dut.DRIVE_DEFAULT)
        ctx.set(dut.resonance, 8192)
        ctx.set(dut.feedback, 0)
        ctx.set(dut.cross_feedback, 0)
        ctx.set(dut.damp_mode, 3)
        for n in range(512):
            await send(ctx, swarm_sample(1536 + n))

        ctx.set(dut.levels[5], 1024)
        for n in range(512):
            values = await send(ctx, swarm_sample(2048 + n))
            if n >= 384:
                recovered.append(tuple(values))

    sim.add_testbench(bench)
    sim.run()

    peak = max(abs(value) for pair in recovered for value in pair)
    rail_count = sum(value in (-32768, 32767)
                     for pair in recovered for value in pair)
    assert peak < 8000 and rail_count == 0, (peak, rail_count, recovered[-32:])
