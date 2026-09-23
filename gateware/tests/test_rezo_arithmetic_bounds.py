"""Actual scheduled datapath regressions for hot patches and control endpoints."""
import math
import pytest
from amaranth.hdl import Fragment
from amaranth.sim import Simulator

from top.rezo.rezo_variant import RezoCore as Rezo
from top.rezo.top import RezoCore as Rezomo
from top.rezo.strezo_variant import RezoCore as Strezo


def simulation(core):
    fragment = Fragment.get(core, None)
    signals = {s.name: s for statements in fragment.statements.values()
               for s in statements._lhs_signals()}
    sim = Simulator(fragment)
    sim.add_clock(1 / 60_000_000)
    return sim, signals


def clamp(sample):
    return max(-32768, min(32767, sample))


@pytest.mark.parametrize("core_class", [Rezo, Rezomo, Strezo])
def test_audio_overload_matches_full_precision_band_sum(core_class):
    core = core_class(fs=192000)
    sim, signals = simulation(core)

    async def bench(ctx):
        ctx.set(core.o.ready, 1)
        for n in range(10):
            ctx.set(core.levels[n], 16383)
            ctx.set(core.band_frequencies[n], core.frequency_index(1000))
            ctx.set(core.bank_groups[n], 15)
            ctx.set(core.feedback_sends[n], 1)
        ctx.set(core.resonance, 32768)
        ctx.set(core.drive, 24575)
        ctx.set(core.feedback, 0)
        for n in range(4):
            ctx.set(core.output_sends[n], 16)
        ctx.set(core.output_sends[4], 0)
        for n in range(300):
            ctx.set(core.i.payload[0].as_value(),
                    round(24000 * math.sin(2 * math.pi * 1000 * n / 192000)))
            ctx.set(core.i.valid, 1)
            await ctx.tick().until(core.i.ready == 1)
            ctx.set(core.i.valid, 0)
            wet_sum = 0
            while not ctx.get(core.o.valid):
                if ctx.get(signals["state"]) == 11:
                    wet_sum += ctx.get(signals["enabled_term"])
                await ctx.tick()
            assert ctx.get(core.o.payload[0].as_value()) == clamp(wet_sum * 4)
            assert ctx.get(signals["feedback_acc"]) == wet_sum

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("core_class", [Rezo, Rezomo, Strezo])
def test_ten_band_group_and_feedback_accumulators_do_not_wrap(core_class):
    core = core_class(fs=192000)
    sim, signals = simulation(core)

    async def bench(ctx):
        for sign in (1, -1):
            ctx.set(signals["feedback_acc"], 0)
            for group in range(4):
                ctx.set(signals[f"group_acc{group}"], 0)
            for band in range(10):
                ctx.set(core.bank_groups[band], 15)
                ctx.set(core.feedback_sends[band], 1)
                ctx.set(signals["band"], band)
                ctx.set(signals["term_q"], sign * 131071)
                if core_class is Strezo:
                    ctx.set(signals["bank_group_cur_q"], 15)
                    ctx.set(signals["feedback_send_cur_q"], 1)
                ctx.set(signals["state"], 11)
                await ctx.tick()
            expected = sign * 10 * 131071
            assert ctx.get(signals["feedback_acc"]) == expected
            for group in range(4):
                assert ctx.get(signals[f"group_acc{group}"]) == expected

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("core_class", [Rezo, Rezomo, Strezo])
def test_output_sum_retains_sign_and_cancellation(core_class):
    core = core_class(fs=192000)
    sim, signals = simulation(core)

    async def bench(ctx):
        ctx.set(core.o.ready, 1)
        for groups in ((300000,) * 4, (-300000,) * 4,
                       (1310720, 1310720, -1310720, -1300720),
                       (-1310720, -1310720, 1310720, 1300720)):
            for n, value in enumerate(groups):
                ctx.set(signals[f"group_acc{n}"], value)
                ctx.set(signals[f"output_acc{n}"], 0)
                ctx.set(core.output_sends[n], 16)
            ctx.set(core.output_sends[4], 0)
            ctx.set(signals["output_chan"], 0)
            ctx.set(signals["output_source"], 0)
            ctx.set(signals["state"], 16)  # Start the normal output scheduler.
            await ctx.tick().until(core.o.valid == 1)
            assert ctx.get(core.o.payload[0].as_value()) == clamp(sum(groups))
            await ctx.tick()

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("core_class", [Rezo, Rezomo, Strezo])
def test_input_minimum_mutes_retained_low_byte(core_class):
    core = core_class(fs=192000)
    sim, signals = simulation(core)

    async def bench(ctx):
        # These are the complete reachable minimum values, including old saved
        # low bytes. Verify all four mapping lanes, then the actual input bus.
        for minimum in (0, 0xcc, 0xff):
            for n in range(4):
                ctx.set(signals[f"smooth_input_gain{n}"], minimum)
                assert ctx.get(signals[f"input_gain_coeff{n}"]) == 0
        ctx.set(core.o.ready, 1)
        ctx.set(core.input_gains[0], 0xcc)
        ctx.set(signals["smooth_input_gain0"], 0xcc)
        ctx.set(core.i.payload[0].as_value(), 20000)
        ctx.set(core.i.valid, 1)
        await ctx.tick().until(core.i.ready == 1)
        ctx.set(core.i.valid, 0)
        await ctx.tick().until(core.o.valid == 1)
        bus = core.input_bus_samples[0] if core_class is Strezo else core.input_bus_sample
        assert ctx.get(bus.as_value()) == 0

    sim.add_testbench(bench)
    sim.run()


def test_stereo_hot_mid_side_has_no_unity_discontinuity():
    core = Strezo(fs=192000)
    sim, signals = simulation(core)

    async def bench(ctx):
        ctx.set(core.o.ready, 1)
        for left, right in ((500000, 500000), (-500000, -500000),
                            (500000, -300000)):
            for mid, side in ((64, 64), (65, 64), (64, 65), (128, 128), (0, 128)):
                for n in range(4):
                    ctx.set(signals[f"group_acc{n}"], left if n == 0 else 0)
                    ctx.set(signals[f"group_acc_r{n}"], right if n == 0 else 0)
                    ctx.set(signals[f"output_acc{n}"], 0)
                    for channel in range(2):
                        ctx.set(core.output_sends[channel * 5 + n], int(n == 0))
                for channel in range(2):
                    ctx.set(core.output_sends[channel * 5 + 4], 0)
                ctx.set(signals["spatial_group"], 0)
                ctx.set(signals["output_chan"], 0)
                ctx.set(signals["output_source"], 0)
                ctx.set(signals["mid_gain_q"], mid)
                ctx.set(signals["side_gain_q"], side)
                ctx.set(signals["state"], 16 if mid == side == 64 else 15)
                await ctx.tick().until(core.o.valid == 1)
                for channel, selected, opposite in ((0, left, right), (1, right, left)):
                    expected = (((mid + side) * selected + (mid - side) * opposite) >> 7) >> 4
                    assert ctx.get(core.o.payload[channel].as_value()) == clamp(expected)
                await ctx.tick()

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("source", [Rezomo.DATA_SOURCE_RANDOM, Rezomo.DATA_SOURCE_AUTO])
def test_shift_random_stays_in_half_range(source):
    core = Rezomo(fs=192000)
    sim, signals = simulation(core)

    async def bench(ctx):
        ctx.set(core.o.ready, 1)
        ctx.set(core.clock_mode, 1)
        ctx.set(core.clock_algorithm, core.CLOCK_ALGORITHM_SHIFT)
        ctx.set(core.clock_source, core.CLOCK_SOURCE_EXTERNAL)
        ctx.set(core.input_jacks, 8)  # Clock patched, DATA unpatched for AUTO.
        ctx.set(core.data_source, source)
        ctx.set(core.levels[0], 16383)
        for _ in range(32):
            for clock in (0, 6000):
                ctx.set(core.i.payload[3].as_value(), clock)
                ctx.set(core.i.valid, 1)
                await ctx.tick().until(core.i.ready == 1)
                ctx.set(core.i.valid, 0)
                await ctx.tick().until(core.o.valid == 1)
            modulation = ctx.get(core.clock_modulations[0])
            assert -16384 <= modulation <= 16383
            assert ctx.get(signals["level_target0"]) == 16383 + modulation

    sim.add_testbench(bench)
    sim.run()
