import pytest

from amaranth.sim import Simulator

from top.rezo.feedback import (
    DAMP_PROFILES, FeedbackShaper, feedback_damping_reference,
    feedback_gain_from_control, resonance_control_reference,
)


def test_feedback_gain_uses_every_fine_control_position():
    values = [feedback_gain_from_control(raw) for raw in range(0, 32769, 64)]
    assert values[0] == 0
    assert values[-1] == 31744
    assert all(right > left for left, right in zip(values, values[1:]))


@pytest.mark.parametrize("profile,max_reduction", (
    ("rezo", 8192),
    ("rezomo", 4096),
    ("strezo", 12288),
))
def test_damping_profiles_remain_distinct_without_hiding_high_resonance(
        profile, max_reduction):
    reductions = [feedback_damping_reference(32768, mode, profile)
                  for mode in range(5)]
    assert reductions == sorted(reductions)
    assert len(set(reductions)) == len(DAMP_PROFILES[profile])
    assert reductions[-1] == max_reduction
    controls = [resonance_control_reference(resonance, reductions[-1])
                for resonance in range(0, 32769, 64)]
    # Even the strongest profile retains more than half of the RES travel.
    assert sum(right != left for left, right in zip(controls, controls[1:])) > 256


@pytest.mark.parametrize("knee,ceiling", (
    (4096, 8192),
    (8192, 28672),
    (16384, 28672),
    (24576, 32767),
    (16384, 16384),
))
def test_feedback_shaper_is_odd_monotonic_and_bounded(knee, ceiling):
    previous = 0
    for drive in range(0, 262145, 257):
        positive = FeedbackShaper.reference(drive, knee, ceiling)
        negative = FeedbackShaper.reference(-drive, knee, ceiling)
        assert positive >= previous
        assert positive <= min(ceiling, 32767)
        assert negative == -positive
        previous = positive


def test_feedback_shaper_preserves_overload_detail_before_ceiling():
    knee = 8192
    ceiling = 32767
    values = [FeedbackShaper.reference(drive, knee, ceiling)
              for drive in (32768, 34816, 36864)]
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_feedback_shaper_gateware_matches_reference_and_activity_flags():
    dut = FeedbackShaper(input_width=21)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    vectors = (
        (-98304, 8192, 28672),
        (-32768, 8192, 28672),
        (4096, 8192, 28672),
        (8192, 8192, 28672),
        (12288, 8192, 28672),
        (32768, 8192, 28672),
        (65536, 8192, 28672),
        (131072, 8192, 28672),
    )

    async def bench(ctx):
        for drive, knee, ceiling in vectors:
            ctx.set(dut.drive, drive)
            ctx.set(dut.knee, knee)
            ctx.set(dut.ceiling, ceiling)
            await ctx.tick()
            await ctx.tick()
            assert ctx.get(dut.sample) == FeedbackShaper.reference(
                drive, knee, ceiling)
            assert ctx.get(dut.knee_active) == (abs(drive) > knee)
            assert ctx.get(dut.ceiling_active) == (
                abs(FeedbackShaper.reference(drive, knee, 32767)) > ceiling)

    sim.add_testbench(bench)
    sim.run()
