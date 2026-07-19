import sys
import unittest
from math import pi, sin
from pathlib import Path

import numpy as np
from amaranth import Module, Signal
from amaranth.lib import wiring
from amaranth.sim import Simulator
from amaranth_future import fixed
from tiliqua import dsp
from tiliqua.test import stream as test_stream


SONORO_SRC = Path(__file__).parents[1] / "src" / "top" / "sonoro"
sys.path.insert(0, str(SONORO_SRC))

from spectrogram import (  # noqa: E402
    ASQ,
    DbfsLevelSmoother,
    MagnitudeToDbfs,
    SPECTRUM_CORDIC_GAIN,
    _logical_scan_coordinates,
    _magnitude_raw_to_dbfs_level,
)


class SonoroMagnitudeTests(unittest.TestCase):

    def test_physical_scan_coordinates_follow_display_rotation(self):
        m = Module()
        physical_x = Signal(12)
        physical_y = Signal(12)
        logical_width = Signal(12)
        logical_height = Signal(12)
        rotation = Signal(2)
        logical_x = Signal(12)
        logical_y = Signal(12)
        mapped = _logical_scan_coordinates(
            physical_x, physical_y,
            logical_width, logical_height, rotation)
        m.d.comb += [
            logical_x.eq(mapped[0]),
            logical_y.eq(mapped[1]),
        ]

        async def bench(ctx):
            # (rotation, logical dimensions, physical position, logical
            # position). Non-square cases prove that left/right use the
            # correct physical axis; square cases cover the official display.
            cases = [
                (0, (1280, 720), (100, 200), (100, 200)),
                (1, (720, 1280), (1079, 100), (100, 200)),
                (2, (1280, 720), (1179, 519), (100, 200)),
                (3, (720, 1280), (200, 619), (100, 200)),
                (1, (720, 720), (519, 100), (100, 200)),
                (3, (720, 720), (200, 619), (100, 200)),
            ]
            for mode, dimensions, physical, expected in cases:
                ctx.set(rotation, mode)
                ctx.set(logical_width, dimensions[0])
                ctx.set(logical_height, dimensions[1])
                ctx.set(physical_x, physical[0])
                ctx.set(physical_y, physical[1])
                await ctx.delay(1e-9)
                self.assertEqual(
                    (ctx.get(logical_x), ctx.get(logical_y)), expected)

        sim = Simulator(m)
        sim.add_testbench(bench)
        sim.run()

    def raw_for_dbfs(self, dbfs):
        amplitude = 10 ** (dbfs / 20)
        magnitude = amplitude * SPECTRUM_CORDIC_GAIN / 4
        return round(magnitude * (1 << ASQ.f_bits))

    def expected_level(self, dbfs):
        return max(0, min(63, round((dbfs + 96) * 63 / 96)))

    def test_calibrated_reference_levels(self):
        for dbfs in (0, -6, -12, -24, -48, -72):
            with self.subTest(dbfs=dbfs):
                actual = _magnitude_raw_to_dbfs_level(
                    self.raw_for_dbfs(dbfs))
                self.assertLessEqual(
                    abs(actual - self.expected_level(dbfs)), 1)

    def test_mapping_is_monotonic(self):
        previous = 0
        for raw in range(1, 1 << ASQ.f_bits, 37):
            level = _magnitude_raw_to_dbfs_level(raw)
            self.assertGreaterEqual(level, previous)
            previous = level

    def test_hardware_log_approximation(self):
        dut = MagnitudeToDbfs(ASQ)
        sim = Simulator(dut)
        sim.add_clock(1e-6)

        async def bench(ctx):
            ctx.set(dut.o.ready, 1)
            for dbfs in (0, -6, -12, -24, -48, -72):
                raw = self.raw_for_dbfs(dbfs)
                ctx.set(dut.i.payload.sample.as_value(), raw)
                ctx.set(dut.i.valid, 1)
                while not ctx.get(dut.i.ready):
                    await ctx.tick()
                await ctx.tick()
                ctx.set(dut.i.valid, 0)
                while not ctx.get(dut.o.valid):
                    await ctx.tick()
                actual = ctx.get(dut.o.payload.sample)
                self.assertLessEqual(
                    abs(actual - self.expected_level(dbfs)), 1,
                    f"hardware approximation at {dbfs}dBFS")
                await ctx.tick()

        sim.add_testbench(bench)
        sim.run()

    def test_smoother_state_stays_aligned_with_bins(self):
        dut = DbfsLevelSmoother(sz=2)
        sim = Simulator(dut)
        sim.add_clock(1e-6)

        async def bench(ctx):
            ctx.set(dut.attack_shift, 0)
            ctx.set(dut.release_shift, 1)
            ctx.set(dut.o.ready, 1)

            async def transfer(sample, first):
                ctx.set(dut.i.payload.sample, sample)
                ctx.set(dut.i.payload.first, first)
                ctx.set(dut.i.valid, 1)
                while not ctx.get(dut.i.ready):
                    await ctx.tick()
                await ctx.tick()
                ctx.set(dut.i.valid, 0)
                while not ctx.get(dut.o.valid):
                    await ctx.tick()
                result = ctx.get(dut.o.payload.sample)
                await ctx.tick()
                return result

            self.assertEqual(await transfer(20, True), 20)
            self.assertEqual(await transfer(40, False), 40)
            self.assertEqual(await transfer(0, True), 10)
            self.assertEqual(await transfer(0, False), 20)

        sim.add_testbench(bench)
        sim.run()

    def test_fixed_point_analyzer_pure_tone_floor(self):
        fft_size = 512
        tone_bin = 32
        shape = fixed.SQ(2, 16)
        m = Module()
        m.submodules.analyzer = analyzer = dsp.fft.STFTAnalyzer(
            shape=shape, sz=fft_size)
        m.submodules.envelope = envelope = dsp.spectral.SpectralEnvelope(
            shape=shape, sz=fft_size, smooth=False)
        wiring.connect(m, analyzer.o, envelope.i)
        m.d.comb += envelope.o.ready.eq(1)

        async def stimulus(ctx):
            sample = 0
            while True:
                value = 0.5 * sin(2 * pi * tone_bin * sample / fft_size)
                await test_stream.put(ctx, analyzer.i,
                                      fixed.Const(value, shape=shape))
                sample += 1
                await ctx.tick()

        async def bench(ctx):
            magnitudes = []
            while len(magnitudes) < fft_size:
                if ctx.get(envelope.o.valid & envelope.o.ready):
                    magnitudes.append(
                        ctx.get(envelope.o.payload.sample).as_float())
                await ctx.tick()

            magnitudes = np.abs(np.asarray(magnitudes))
            peak = magnitudes[tone_bin]
            off_tone = np.delete(
                magnitudes[:fft_size // 2],
                [tone_bin - 1, tone_bin, tone_bin + 1])
            self.assertGreater(peak, 0.15)
            self.assertLess(np.max(off_tone), peak * 10 ** (-55 / 20))

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(bench)
        sim.run()

    def test_wide_resampler_pure_tone_floor(self):
        fft_size = 512
        input_fs = 192_000
        analysis_fs = 48_000
        tone_hz = 261.625565
        tone_bin = round(tone_hz * fft_size / analysis_fs)
        shape = fixed.SQ(2, 16)
        m = Module()
        m.submodules.dc_block = dc_block = dsp.filters.DCBlock(
            pole=0.9999, sq=shape)
        m.submodules.resample = resample = dsp.Resample(
            fs_in=input_fs, n_up=1, m_down=input_fs // analysis_fs,
            bw=11 / 24, order_mult=40, shape=shape)
        m.submodules.analyzer = analyzer = dsp.fft.STFTAnalyzer(
            shape=shape, sz=fft_size)
        m.submodules.envelope = envelope = dsp.spectral.SpectralEnvelope(
            shape=shape, sz=fft_size, smooth=False)
        wiring.connect(m, dc_block.o, resample.i)
        wiring.connect(m, resample.o, analyzer.i)
        wiring.connect(m, analyzer.o, envelope.i)
        m.d.comb += envelope.o.ready.eq(1)

        async def stimulus(ctx):
            sample = 0
            while True:
                value = 0.5 * sin(2 * pi * tone_hz * sample / input_fs)
                await test_stream.put(ctx, dc_block.i,
                                      fixed.Const(value, shape=shape))
                sample += 1
                await ctx.tick()

        async def bench(ctx):
            magnitudes = []
            while len(magnitudes) < 4 * fft_size:
                if ctx.get(envelope.o.valid & envelope.o.ready):
                    magnitudes.append(
                        ctx.get(envelope.o.payload.sample).as_float())
                await ctx.tick()

            magnitudes = np.abs(np.asarray(magnitudes[-fft_size:]))
            peak = magnitudes[tone_bin]
            far_bins = magnitudes[4 * (tone_bin + 1):fft_size // 2]
            self.assertGreater(peak, 0.15)
            # The 18-bit decimator's worst distant spur is about -57dBc;
            # retain margin for coefficient and simulator quantization.
            self.assertLess(np.max(far_bins), peak * 10 ** (-55 / 20))

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(bench)
        sim.run()

    def test_dc_block_rejects_static_offset(self):
        shape = fixed.SQ(2, 16)
        dut = dsp.filters.DCBlock(pole=0.9999, sq=shape)
        sim = Simulator(dut)
        sim.add_clock(1e-6)

        async def bench(ctx):
            ctx.set(dut.o.ready, 1)
            output = 0.0
            for _ in range(20_000):
                ctx.set(dut.i.payload, fixed.Const(0.1, shape=shape))
                ctx.set(dut.i.valid, 1)
                while not ctx.get(dut.i.ready):
                    await ctx.tick()
                await ctx.tick()
                ctx.set(dut.i.valid, 0)
                while not ctx.get(dut.o.valid):
                    await ctx.tick()
                output = ctx.get(dut.o.payload).as_float()
                await ctx.tick()
            # Fixed-point error feedback settles a little more slowly than
            # the ideal pole, but must remove at least 80% of static offset
            # over this interval.
            self.assertLess(abs(output), 0.02)

        sim.add_testbench(bench)
        sim.run()

    def test_six_khz_resampler_pure_tone_floor(self):
        fft_size = 512
        input_fs = 192_000
        analysis_fs = 12_000
        tone_hz = 261.625565
        tone_bin = round(tone_hz * fft_size / analysis_fs)
        shape = fixed.SQ(2, 16)
        m = Module()
        m.submodules.dc_block = dc_block = dsp.filters.DCBlock(
            pole=0.9999, sq=shape)
        m.submodules.wide = wide = dsp.Resample(
            fs_in=input_fs, n_up=1, m_down=4,
            bw=11 / 24, order_mult=40, shape=shape)
        m.submodules.fine = fine = dsp.Resample(
            fs_in=48_000, n_up=1, m_down=2,
            bw=11 / 24, order_mult=40, shape=shape)
        m.submodules.mid = mid = dsp.Resample(
            fs_in=24_000, n_up=1, m_down=2,
            bw=11 / 24, order_mult=24, shape=shape)
        m.submodules.analyzer = analyzer = dsp.fft.STFTAnalyzer(
            shape=shape, sz=fft_size)
        m.submodules.envelope = envelope = dsp.spectral.SpectralEnvelope(
            shape=shape, sz=fft_size, smooth=False)
        wiring.connect(m, dc_block.o, wide.i)
        wiring.connect(m, wide.o, fine.i)
        wiring.connect(m, fine.o, mid.i)
        wiring.connect(m, mid.o, analyzer.i)
        wiring.connect(m, analyzer.o, envelope.i)
        m.d.comb += envelope.o.ready.eq(1)

        async def stimulus(ctx):
            sample = 0
            while True:
                value = 0.5 * sin(2 * pi * tone_hz * sample / input_fs)
                await test_stream.put(ctx, dc_block.i,
                                      fixed.Const(value, shape=shape))
                sample += 1
                await ctx.tick()

        async def bench(ctx):
            magnitudes = []
            while len(magnitudes) < 4 * fft_size:
                if ctx.get(envelope.o.valid & envelope.o.ready):
                    magnitudes.append(
                        ctx.get(envelope.o.payload.sample).as_float())
                await ctx.tick()

            magnitudes = np.abs(np.asarray(magnitudes[-fft_size:]))
            peak = magnitudes[tone_bin]
            far_bins = magnitudes[4 * (tone_bin + 1):fft_size // 2]
            self.assertGreater(peak, 0.15)
            self.assertLess(np.max(far_bins), peak * 10 ** (-50 / 20))

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(bench)
        sim.run()


if __name__ == "__main__":
    unittest.main()
