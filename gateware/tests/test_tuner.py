# Copyright (c) 2026
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import math
import pytest

from amaranth import Module
from amaranth.sim import Simulator

from tiliqua.dsp import ASQ
from tiliqua.dsp.tuner import ReferenceOscillator, TunerPeripheral


def _asq_raw(value):
    return int(round(value * (1 << ASQ.f_bits)))


@pytest.mark.parametrize("resume_period", [8, 32])
def test_silence_retires_old_pitch_before_reacquiring(resume_period):
    fs = 3200
    dut = TunerPeripheral(sample_rate=fs,min_pitch_window_s=0.01,
                          level_window_log2=5,hysteresis_counts=32)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.i.valid,1)
        for n in range(128):
            ctx.set(dut.i.payload[0].as_value(),1000 if n%16>=8 else -1000)
            await ctx.tick()
        assert ctx.get(dut._period_cycles.f.cycles.r_data)>0
        ctx.set(dut.i.payload[0].as_value(),0)
        await ctx.tick().repeat(fs//2+100)
        assert ctx.get(dut._period_samples.f.samples.r_data)==0
        assert ctx.get(dut._period_cycles.f.cycles.r_data)==0
        sequence = ctx.get(dut._pitch_sequence.f.sequence.r_data)
        await ctx.tick().repeat(100)
        assert ctx.get(dut._pitch_sequence.f.sequence.r_data)==sequence
        updates = 0
        for n in range(192):
            ctx.set(dut.i.payload[0].as_value(),
                    1000 if n%resume_period>=resume_period//2 else -1000)
            await ctx.tick()
            new_sequence = ctx.get(dut._pitch_sequence.f.sequence.r_data)
            if new_sequence != sequence:
                sequence = new_sequence
                samples = ctx.get(dut._period_samples.f.samples.r_data)
                cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
                assert cycles>0
                # Includes the FIRST returned reading, not only settled ones.
                assert samples == cycles*resume_period
                updates += 1
        assert updates>=3

    sim.add_testbench(bench)
    sim.run()


def test_pitch_step_settles_and_stream_stalls_do_not_count_as_samples():
    dut = TunerPeripheral(sample_rate=3200,min_pitch_window_s=0.01,
                          level_window_log2=5,hysteresis_counts=32)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.i.valid,1)
        for period in [32,8,16]:
            for n in range(192):
                ctx.set(dut.i.payload[0].as_value(),1000 if n%period>=period//2 else -1000)
                await ctx.tick()
                if n==64:
                    ctx.set(dut.i.valid,0)
                    age = ctx.get(dut._pitch_age.f.samples.r_data)
                    seq = ctx.get(dut._pitch_sequence.f.sequence.r_data)
                    await ctx.tick().repeat(1700)
                    assert ctx.get(dut._pitch_age.f.samples.r_data)==age
                    assert ctx.get(dut._pitch_sequence.f.sequence.r_data)==seq
                    ctx.set(dut.i.valid,1)
            samples = ctx.get(dut._period_samples.f.samples.r_data)
            cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
            assert cycles>0 and samples == cycles*period

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("warmup", [115, 125])
def test_channel_change_invalidates_pitch_and_restarts_level_window(paused, warmup):
    dut = TunerPeripheral(sample_rate=3200, min_pitch_window_s=0.01,
                          level_window_log2=5, hysteresis_counts=32,
                          dc_filter_shift=20)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.i.valid, 1)
        # First input: 200 Hz square, 1000-count RMS. End mid-level-window.
        for n in range(warmup):
            ctx.set(dut.i.payload[0].as_value(), 1000 if n % 16 >= 8 else -1000)
            await ctx.tick()
        assert ctx.get(dut._period_cycles.f.cycles.r_data) != 0
        assert ctx.get(dut._mean_square.f.value.r_data) == 1_000_000
        pitch_seq = ctx.get(dut._pitch_sequence.f.sequence.r_data)
        level_seq = ctx.get(dut._level_sequence.f.sequence.r_data)
        # A positive sample can trigger an old armed crossing on this change.
        ctx.set(dut.i.payload[1].as_value(), 200)
        ctx.set(dut.i.valid, not paused)
        ctx.set(dut.bus.addr, 0)
        ctx.set(dut.bus.w_data, 1)
        ctx.set(dut.bus.w_stb, 1)
        await ctx.tick()
        ctx.set(dut.bus.w_stb, 0)
        # Bridge write, register update, then selection-reset clock. Keep the
        # stream active through that last clock to exercise reset priority.
        await ctx.tick().repeat(2)
        ctx.set(dut.i.valid, 0)
        await ctx.tick().repeat(4)
        assert ctx.get(dut._period_samples.f.samples.r_data) == 0
        assert ctx.get(dut._period_cycles.f.cycles.r_data) == 0
        assert ctx.get(dut._pitch_age.f.samples.r_data) == 0xFFFF_FFFF
        assert ctx.get(dut._mean_square.f.value.r_data) == 0
        assert ctx.get(dut._minimum.f.value.r_data) == 0
        assert ctx.get(dut._maximum.f.value.r_data) == 0
        assert ctx.get(dut._pitch_sequence.f.sequence.r_data) == pitch_seq + 1
        assert ctx.get(dut._level_sequence.f.sequence.r_data) == level_seq + 1
        # New input: 400 Hz, 200-count RMS. First published window must contain
        # exactly 32 NEW samples, not the tail of the old input's partial window.
        ctx.set(dut.i.valid, 1)
        for n in range(96):
            ctx.set(dut.i.payload[1].as_value(), 200 if n % 8 >= 4 else -200)
            await ctx.tick()
            if n < 31:
                assert ctx.get(dut._mean_square.f.value.r_data) == 0
            else:
                assert ctx.get(dut._mean_square.f.value.r_data) == 40_000
        samples = ctx.get(dut._period_samples.f.samples.r_data)
        cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
        assert 3200 * cycles / samples == 400

    sim.add_testbench(bench)
    sim.run()


def test_reference_oscillator_frequency_and_level():
    sample_rate = 48_000
    frequency = 440.0
    increment = round(frequency * (1 << 32) / sample_rate)

    dut = ReferenceOscillator()
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        ctx.set(dut.enable, 1)
        ctx.set(dut.advance, 1)
        ctx.set(dut.increment, increment)
        previous = 0
        crossings = 0
        minimum = 0
        maximum = 0
        sample_count = 4_800
        for _ in range(sample_count):
            await ctx.tick()
            sample = ctx.get(dut.o.as_value())
            if previous < 0 <= sample:
                crossings += 1
            previous = sample
            minimum = min(minimum, sample)
            maximum = max(maximum, sample)

        measured_hz = crossings * sample_rate / sample_count
        assert abs(measured_hz - frequency) <= 10.0
        # 2000 calibrated counts peak is 0.5 V, hence 1 Vpp.
        assert 1990 <= maximum <= 2000
        assert -2000 <= minimum <= -1990

    sim.add_testbench(bench)
    sim.run()


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
