# Copyright (c) 2026
# SPDX-License-Identifier: CERN-OHL-S-2.0

import math

from amaranth import Module
from amaranth.sim import Simulator

from tiliqua.dsp import ASQ
from tiliqua.dsp.tuner import ReferenceOscillator, TunerPeripheral


def _asq_raw(value):
    return int(round(value * (1 << ASQ.f_bits)))


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
        for _ in range(4_800):
            await ctx.tick()
            sample = ctx.get(dut.o.as_value())
            crossings += previous < 0 <= sample
            previous = sample
            minimum = min(minimum, sample)
            maximum = max(maximum, sample)
        assert abs(crossings * sample_rate / 4_800 - frequency) <= 10.0
        assert 1990 <= maximum <= 2000
        assert -2000 <= minimum <= -1990

    sim.add_testbench(bench)
    sim.run()


def test_level_windows_report_rms_peak_and_dc_without_pitch_hardware():
    sample_rate = 48_000
    frequency = 440.0
    amplitude = 0.5
    offset = 0.1
    m = Module()
    dut = TunerPeripheral(sample_rate=sample_rate, level_window_log2=10)
    m.submodules.dut = dut
    assert dut._mean_square.f.value.r_data.shape().width == 32

    async def bench(ctx):
        ctx.set(dut.i.valid, 1)
        for n in range(6_000):
            value = offset + amplitude * math.sin(2.0 * math.pi * frequency * n / sample_rate)
            ctx.set(dut.i.payload[0].as_value(), _asq_raw(value))
            await ctx.tick()
        power = ctx.get(dut._mean_square.f.value.r_data)
        measured_rms = math.sqrt(power) / (1 << ASQ.f_bits)
        expected_rms = math.sqrt(offset * offset + amplitude * amplitude / 2.0)
        assert abs(measured_rms - expected_rms) < 0.02
        minimum = ctx.get(dut._minimum.f.value.r_data)
        maximum = ctx.get(dut._maximum.f.value.r_data)
        dc = ctx.get(dut._dc.f.value.r_data)
        if minimum & 0x8000_0000:
            minimum -= 1 << 32
        if dc & 0x8000_0000:
            dc -= 1 << 32
        assert abs(maximum / (1 << ASQ.f_bits) - (offset + amplitude)) < 0.02
        assert abs(minimum / (1 << ASQ.f_bits) - (offset - amplitude)) < 0.02
        assert abs(dc / (1 << ASQ.f_bits) - offset) < 0.03

    sim = Simulator(m)
    sim.add_clock(1e-6)
    sim.add_testbench(bench)
    sim.run()
