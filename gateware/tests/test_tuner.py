# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import math

from amaranth import Module
from amaranth.sim import Simulator

from tiliqua.dsp import ASQ
from tiliqua.dsp.tuner import TunerPeripheral


def _asq_raw(value):
    return int(round(value * (1 << ASQ.f_bits)))


def test_tuner_sine_pitch_and_level():
    sample_rate = 48_000
    frequency = 440.0
    amplitude = 0.5

    m = Module()
    dut = TunerPeripheral(
        sample_rate=sample_rate,
        min_pitch_window_s=0.02,
        level_window_log2=10,
        hysteresis_counts=32,
    )
    m.submodules.dut = dut

    # The published mean is a native 32-bit CPU register. A wider CSR causes
    # a split MMIO read on RV32 even though a mean of squared ASQ samples can
    # never require more than 32 bits.
    assert dut._mean_square.f.value.r_data.shape().width == 32

    async def bench(ctx):
        ctx.set(dut.i.valid, 1)
        ctx.set(dut.i.payload[1], 0)
        ctx.set(dut.i.payload[2], 0)
        ctx.set(dut.i.payload[3], 0)
        rms_snapshots = []

        for n in range(6_000):
            value = amplitude * math.sin(2.0 * math.pi * frequency * n / sample_rate)
            ctx.set(dut.i.payload[0].as_value(), _asq_raw(value))
            await ctx.tick()
            if (n + 1) % (1 << 10) == 0:
                power = ctx.get(dut._mean_square.f.value.r_data)
                rms_snapshots.append(math.sqrt(power) / (1 << ASQ.f_bits))

        period_samples = ctx.get(dut._period_samples.f.samples.r_data)
        period_cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
        measured_hz = sample_rate * period_cycles / period_samples
        assert abs(measured_hz - frequency) < 0.5

        mean_square = ctx.get(dut._mean_square.f.value.r_data)
        measured_rms = math.sqrt(mean_square) / (1 << ASQ.f_bits)
        expected_rms = amplitude / math.sqrt(2.0)
        assert abs(measured_rms - expected_rms) < 0.01
        # Every completed window must stand alone; an accumulator that is not
        # reset would grow by roughly sqrt(window number).
        assert len(rms_snapshots) >= 5
        assert all(abs(value - expected_rms) < 0.02 for value in rms_snapshots)

        minimum = ctx.get(dut._minimum.f.value.r_data)
        maximum = ctx.get(dut._maximum.f.value.r_data)
        # CSR fields preserve signed sample bits in a 32-bit container.
        if minimum & 0x8000_0000:
            minimum -= 1 << 32
        assert abs(maximum / (1 << ASQ.f_bits) - amplitude) < 0.01
        assert abs(minimum / (1 << ASQ.f_bits) + amplitude) < 0.01

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()


def test_tuner_rejects_dc_offset_for_pitch():
    sample_rate = 48_000
    frequency = 110.0

    m = Module()
    dut = TunerPeripheral(
        sample_rate=sample_rate,
        min_pitch_window_s=0.04,
        level_window_log2=10,
        hysteresis_counts=32,
        dc_filter_shift=8,
    )
    m.submodules.dut = dut

    async def bench(ctx):
        ctx.set(dut.i.valid, 1)
        for n in range(12_000):
            value = 0.2 + 0.35 * math.sin(
                2.0 * math.pi * frequency * n / sample_rate)
            ctx.set(dut.i.payload[0].as_value(), _asq_raw(value))
            await ctx.tick()

        period_samples = ctx.get(dut._period_samples.f.samples.r_data)
        period_cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
        measured_hz = sample_rate * period_cycles / period_samples
        assert abs(measured_hz - frequency) < 0.5

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
