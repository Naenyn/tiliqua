# Copyright (c) 2024 Seb Holzapfel <me@sebholzapfel.com>
#
# SPDX-License-Identifier: CERN-OHL-S-2.0

import itertools
import math
import sys
import unittest

from amaranth import *
from amaranth.lib import data, stream as amaranth_stream, wiring
from amaranth.lib.wiring import In, Out
from amaranth.sim import *
from parameterized import parameterized
from scipy import signal

from amaranth_future import fixed
from tiliqua import dsp
from tiliqua.dsp import ASQ, delay_effect, mac, stream_util
from tiliqua.test import stream


class DSPTests(unittest.TestCase):


    @parameterized.expand([
        ["dual_sine_small",          100, 16, 1, 17, 0.005, lambda n: 0.4*(math.sin(n*0.2) + math.sin(n))],
        ["dual_sine_large",          100, 64, 1, 65, 0.005, lambda n: 0.4*(math.sin(n*0.2) + math.sin(n))],
        ["dual_sine_odd",            100, 59, 1, 60, 0.005, lambda n: 0.4*(math.sin(n*0.2) + math.sin(n))],
        ["impulse_small_9",          100,  9, 1, 10, 0.005, lambda n: 0.95 if n == 0 else 0.0],
        ["impulse_small_10",         100, 10, 1, 11, 0.005, lambda n: 0.95 if n == 0 else 0.0],
        ["impulse_small_16",         100, 16, 1, 17, 0.005, lambda n: 0.95 if n == 0 else 0.0],
        ["sine_interpolator_s1_n16", 100, 16, 1, 17, 0.005, lambda n: 0.9*math.sin(n*0.2) if n % 4 == 0 else 0.0],
        ["sine_interpolator_s2_n16", 100, 16, 2, 9,  0.005, lambda n: 0.9*math.sin(n*0.2) if n % 4 == 0 else 0.0],
        ["sine_interpolator_s4_n16", 100, 16, 4, 5,  0.005, lambda n: 0.9*math.sin(n*0.2) if n % 4 == 0 else 0.0],
        ["sine_interpolator_s2_n10", 100, 10, 2, 6,  0.005, lambda n: 0.9*math.sin(n*0.2) if n % 2 == 0 else 0.0],
        ["sine_interpolator_s3_n9",  100,  9, 3, 4,  0.005, lambda n: 0.9*math.sin(n*0.2) if n % 3 == 0 else 0.0],
    ])
    def test_fir(self, name, n_samples, n_order, stride_i, expected_latency, tolerance, stimulus_function):

        m = Module()
        dut = dsp.FIR(fs=48000, filter_cutoff_hz=2000,
                      filter_order=n_order, stride_i=stride_i)
        m.submodules.dut = dut

        # fake signals so we can see the expected output in VCD output.
        expected_output = Signal(ASQ)
        s_expected_output = Signal(ASQ)
        m.d.comb += s_expected_output.eq(expected_output)

        def stimulus_values():
            """Create fixed-point samples to stimulate the DUT."""
            for n in range(0, sys.maxsize):
                yield fixed.Const(stimulus_function(n), shape=ASQ)

        def expected_samples():
            """Same samples filtered by scipy.signal (should ~match those from our RTL)."""
            x = itertools.islice(stimulus_values(), n_samples)
            return signal.lfilter(dut.taps_float, [1.0], [v.as_float() for v in x])

        async def stimulus_i(ctx):
            """Send `stimulus_values` to the DUT."""
            s = stimulus_values()
            while True:
                await stream.put(ctx, dut.i, next(s))

        async def testbench(ctx):
            """Observe and measure FIR filter outputs."""
            y_expected = expected_samples()
            n_samples_in = 0
            n_samples_out = 0
            n_latency = 0
            ctx.set(dut.o.ready, 1)
            for n in range(0, sys.maxsize):
                i_sample = ctx.get(dut.i.valid & dut.i.ready)
                o_sample = ctx.get(dut.o.valid & dut.o.ready)
                if i_sample:
                    n_samples_in += 1
                    n_latency     = 0
                if o_sample:
                    ctx.set(expected_output, fixed.Const(y_expected[n_samples_out], shape=ASQ))
                    # Verify latency and value of the payload is as we expect.
                    assert n_latency == expected_latency
                    if tolerance is not None:
                        assert abs(ctx.get(dut.o.payload).as_float() - y_expected[n_samples_out]) < tolerance
                    n_samples_out += 1
                    if n_samples_out == len(y_expected):
                        break
                await ctx.tick()
                n_latency += 1
            assert n_samples_in == n_samples
            assert n_samples_out == n_samples

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus_i)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open(f"test_fir_{name}.vcd", "w")):
            sim.run()

    @parameterized.expand([
        ["dual_sine_n4_m1",     100, 4,  1, 4,   1,   0.005, lambda n: 0.4*(math.sin(n*0.2) + math.sin(n))],
        # TODO (below this comment): all visually look correct, fix reference alignment and reduce tolerance.
        ["dual_sine_n1_m4",     100, 14, 0, 1,   4,   0.1,   lambda n: 0.4*(math.sin(n*0.2) + math.sin(n))],
        ["dual_sine_n2_m3",     100, 5,  0, 2,   3,   0.25,  lambda n: 0.4*(math.sin(n*0.2) + math.sin(n))],
        ["dual_sine_n441_m480", 50,  5,  0, 441, 480, 0.25,  lambda n: 0.4*(math.sin(n*0.2) + math.sin(n))],
    ])
    def test_resample(self, name, n_samples, n_pad, n_align, n_up, m_down, tolerance, stimulus_function):

        m = Module()
        dut = dsp.Resample(fs_in=48000, n_up=n_up, m_down=m_down, order_mult=8)
        m.submodules.dut = dut

        # fake signals so we can see the expected output in VCD output.
        expected_output = Signal(ASQ)
        s_expected_output = Signal(ASQ)
        m.d.comb += s_expected_output.eq(expected_output)

        def stimulus_values():
            """Create fixed-point samples to stimulate the DUT."""
            for n in range(0, sys.maxsize):
                yield fixed.Const(stimulus_function(n), shape=ASQ)

        def expected_samples():
            """Same samples filtered by scipy (should ~match those from our RTL)."""
            x = [v.as_float() for v in itertools.islice(stimulus_values(), n_samples)]
            # zero padding needed to align to the RTL outputs.
            x = [0]*n_pad + x
            resampled = signal.resample_poly(x, dut.n_up, dut.m_down, window=dut.filt.taps_float)
            aligned =  resampled[n_align:-10]
            return aligned

        async def stimulus_i(ctx):
            """Send `stimulus_values` to the DUT."""
            s = stimulus_values()
            while True:
                await stream.put(ctx, dut.i, next(s))
                await ctx.tick()

        async def testbench(ctx):
            """Observe and measure resampler outputs."""
            y_expected = expected_samples()
            n_samples_in = 0
            n_samples_out = 0
            ctx.set(dut.o.ready, 1)
            for n in range(0, sys.maxsize):
                i_sample = ctx.get(dut.i.valid & dut.i.ready)
                o_sample = ctx.get(dut.o.valid & dut.o.ready)
                if i_sample:
                    n_samples_in += 1
                if o_sample:
                    # Verify value of the payload is as we expect.
                    assert abs(ctx.get(dut.o.payload).as_float() - y_expected[n_samples_out]) < tolerance
                    ctx.set(expected_output, fixed.Const(y_expected[n_samples_out], shape=ASQ))
                    n_samples_out += 1
                    if n_samples_out == len(y_expected):
                        break
                await ctx.tick()
            assert n_samples_out == len(y_expected)
            assert abs(n_samples_out - (n_samples * n_up / m_down)) < 10

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus_i)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open(f"test_resample_{name}.vcd", "w")):
            sim.run()

    def test_linear_resample_is_monotonic_across_discontinuities(self):
        m = Module()
        m.submodules.dut = dut = dsp.LinearResample(n_up=8, shape=ASQ)
        outputs = []

        async def stimulus(ctx):
            for sample in (-0.75, 0.75, -0.5):
                await stream.put(ctx, dut.i, fixed.Const(sample, shape=ASQ))

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < 16:
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append(ctx.get(dut.o.payload).as_float())
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        rising = outputs[:8]
        falling = outputs[8:]
        self.assertTrue(all(a <= b for a, b in zip(rising, rising[1:])), rising)
        self.assertTrue(all(a >= b for a, b in zip(falling, falling[1:])), falling)
        self.assertGreaterEqual(min(outputs), -0.75)
        self.assertLessEqual(max(outputs), 0.75)
        self.assertAlmostEqual(rising[-1], 0.75, places=3)
        self.assertAlmostEqual(falling[-1], -0.5, places=3)

    def test_hold_resample_preserves_discontinuities(self):
        m = Module()
        m.submodules.dut = dut = dsp.HoldResample(n_up=8, shape=ASQ)
        outputs = []

        async def stimulus(ctx):
            for sample in (-0.75, 0.75):
                await stream.put(ctx, dut.i, fixed.Const(sample, shape=ASQ))

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < 16:
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append(ctx.get(dut.o.payload).as_float())
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        self.assertEqual(outputs[:8], [-0.75] * 8)
        self.assertEqual(outputs[8:], [0.75] * 8)

    def test_edge_aware_resample_interpolates_smooth_slopes(self):
        m = Module()
        m.submodules.dut = dut = dsp.EdgeAwareResample(n_up=8, shape=ASQ)
        outputs = []

        async def stimulus(ctx):
            for sample in (-0.4, -0.3, -0.2):
                await stream.put(ctx, dut.i, fixed.Const(sample, shape=ASQ))

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < 16:
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append(ctx.get(dut.o.payload).as_float())
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        self.assertTrue(all(a <= b for a, b in zip(outputs, outputs[1:])), outputs)
        self.assertGreater(len(set(outputs[:8])), 2)
        self.assertGreater(len(set(outputs[8:])), 2)
        self.assertAlmostEqual(outputs[7], -0.3, places=3)
        self.assertAlmostEqual(outputs[15], -0.2, places=3)

    def test_edge_aware_resample_holds_hard_edges(self):
        m = Module()
        m.submodules.dut = dut = dsp.EdgeAwareResample(n_up=8, shape=ASQ)
        outputs = []

        async def stimulus(ctx):
            for sample in (-0.5, -0.5, -0.5, 0.5, 0.5):
                await stream.put(ctx, dut.i, fixed.Const(sample, shape=ASQ))

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < 32:
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append(ctx.get(dut.o.payload).as_float())
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        edge = outputs[16:24]
        self.assertEqual(edge[:7], [-0.5] * 7)
        self.assertEqual(edge[7], 0.5)

    def test_discontinuity_reconstruct_sharpens_settling_edge(self):
        m = Module()
        m.submodules.dut = dut = dsp.DiscontinuityReconstruct(shape=ASQ)
        samples = ([-0.5] * 20 +
                   [-0.25, 0.10, 0.40, 0.60, 0.45] +
                   [0.5] * 20)
        outputs = []

        async def stimulus(ctx):
            for sample in samples:
                await stream.put(ctx, dut.i, fixed.Const(sample, shape=ASQ))

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < len(samples) - 16:
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append(ctx.get(dut.o.payload).as_float())
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        self.assertEqual(set(outputs), {-0.5, 0.5})

    def test_discontinuity_reconstruct_preserves_smooth_signal(self):
        m = Module()
        m.submodules.dut = dut = dsp.DiscontinuityReconstruct(shape=ASQ)
        samples = [0.6 * math.sin(2 * math.pi * n / 48) for n in range(96)]
        expected = [fixed.Const(v, shape=ASQ).as_value().value
                    for v in samples[8:-8]]
        outputs = []

        async def stimulus(ctx):
            for sample in samples:
                await stream.put(ctx, dut.i, fixed.Const(sample, shape=ASQ))

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < len(expected):
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append(ctx.get(dut.o.payload).as_value().value)
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        self.assertEqual(outputs, expected)

    def test_multichannel_reconstruct_preserves_aligned_smooth_signals(self):
        m = Module()
        m.submodules.dut = dut = dsp.MultichannelDiscontinuityReconstruct(
            n_channels=4, shape=ASQ)
        frames = [
            [0.5 * math.sin(2 * math.pi * n / period)
             for period in (48, 56, 64, 72)]
            for n in range(80)
        ]
        expected = [
            [fixed.Const(frame[ch], shape=ASQ).as_value().value
             for ch in range(4)]
            for frame in frames[8:-8]
        ]
        outputs = []

        async def stimulus(ctx):
            for frame in frames:
                await stream.put(
                    ctx,
                    dut.i,
                    [fixed.Const(value, shape=ASQ) for value in frame],
                )

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < len(expected):
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append([
                        ctx.get(dut.o.payload[ch]).as_value().value
                        for ch in range(4)
                    ])
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        self.assertEqual(outputs, expected)

    def test_multichannel_edge_aware_resample_keeps_channels_aligned(self):
        m = Module()
        m.submodules.dut = dut = dsp.MultichannelEdgeAwareResample(
            n_channels=4, n_up=8, shape=ASQ)
        frames = [
            [-0.4, -0.5, 0.2, 0.0],
            [-0.3, -0.5, 0.1, 0.1],
            [-0.2, -0.5, 0.0, 0.2],
            [-0.1,  0.5, -0.1, 0.3],
            [ 0.0,  0.5, -0.2, 0.4],
        ]
        outputs = []

        async def stimulus(ctx):
            for frame in frames:
                await stream.put(
                    ctx,
                    dut.i,
                    [fixed.Const(value, shape=ASQ) for value in frame],
                )

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            while len(outputs) < 32:
                if ctx.get(dut.o.valid & dut.o.ready):
                    outputs.append([
                        ctx.get(dut.o.payload[ch]).as_float()
                        for ch in range(4)
                    ])
                await ctx.tick()

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus)
        sim.add_testbench(testbench)
        sim.run()

        self.assertEqual(len(outputs), 32)
        self.assertTrue(all(a[0] <= b[0]
                            for a, b in zip(outputs, outputs[1:])), outputs)
        hard_edge = [frame[1] for frame in outputs[16:24]]
        self.assertEqual(hard_edge[:7], [-0.5] * 7)
        self.assertEqual(hard_edge[7], 0.5)

    @parameterized.expand([
        ["mux_mac", mac.MuxMAC],
        ["ring_mac", mac.RingMAC],
    ])
    def test_pitch(self, name, mac_type):

        m = Module()

        match mac_type:
            case mac.RingMAC:
                m.submodules.server = server = mac.RingMACServer()
                macp = server.new_client()
            case _:
                macp = None

        delayln = dsp.DelayLine(max_delay=256, write_triggers_read=False)
        pitch_shift = dsp.PitchShift(tap=delayln.add_tap(), xfade=32, macp=macp)
        m.submodules += [delayln, pitch_shift]

        def stimulus_values():
            for n in range(0, sys.maxsize):
                yield fixed.Const(0.8*math.sin(n*0.2), shape=ASQ)

        async def stimulus_i(ctx):
            """Send `stimulus_values` to the DUT."""
            s = stimulus_values()
            while True:
                # First clock a sample into the delay line
                await stream.put(ctx, delayln.i, next(s))
                # Now clock a sample into the pitch shifter
                await stream.put(ctx, pitch_shift.i, {
                    'pitch': fixed.Const(0.5, shape=pitch_shift.dtype),
                    'grain_sz': delayln.max_delay//2,
                })

        async def testbench(ctx):
            n_samples_in = 0
            n_samples_out = 0
            ctx.set(pitch_shift.o.ready, 1)
            for n in range(0, 7000):
                n_samples_in  += ctx.get(delayln.i.valid & delayln.i.ready)
                n_samples_out += ctx.get(pitch_shift.o.valid & pitch_shift.o.ready)
                await ctx.tick()
            print("n_samples_in",  n_samples_in)
            print("n_samples_out", n_samples_out)
            assert n_samples_in > 50
            assert (n_samples_out - n_samples_in) < 2

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_process(stimulus_i)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open(f"test_pitch_{name}.vcd", "w")):
            sim.run()


    @parameterized.expand([
        ["mux_mac", mac.MuxMAC],
        ["ring_mac", mac.RingMAC],
    ])
    def test_svf(self, name, mac_type):

        match mac_type:
            case mac.RingMAC:
                m = Module()
                m.submodules.server = server = mac.RingMACServer()
                m.submodules.svf = dut = dsp.SVF(macp=server.new_client())
            case _:
                m = Module()
                m.submodules.svf = dut = dsp.SVF()

        async def stimulus(ctx):
            for n in range(0, 200):
                x = fixed.Const(0.4*(math.sin(n*0.2) + math.sin(n)), shape=ASQ)
                y = fixed.Const(0.8*(math.sin(n*0.1)), shape=ASQ)
                await stream.put(ctx, dut.i, {
                    'x': x,
                    'cutoff': y,
                    'resonance': fixed.Const(0.1, shape=ASQ)
                })

        async def testbench(ctx):
            while True:
                _ = await stream.get(ctx, dut.o)
                # TODO spectral analysis

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(stimulus)
        sim.add_testbench(testbench, background=True)
        with sim.write_vcd(vcd_file=open(f"test_svf_{name}.vcd", "w")):
            sim.run()

    def test_matrix(self):

        matrix = dsp.MatrixMix(
            i_channels=4, o_channels=4,
            coefficients=[[    1, 0,   0,  0],
                          [-0.25, 1,  -2,  0],
                          [    0, 0, 0.5,  0],
                          [    0, 0,   0,  1]])

        async def testbench(ctx):
            await stream.put(ctx, matrix.i, [
                fixed.Const(0.2, shape=ASQ),
                fixed.Const(-0.4, shape=ASQ),
                fixed.Const(0.6, shape=ASQ),
                fixed.Const(-0.8, shape=ASQ)
            ])
            result = await stream.get(ctx, matrix.o)
            self.assertAlmostEqual(result[0].as_float(),  0.3, places=4)
            self.assertAlmostEqual(result[1].as_float(), -0.4, places=4)
            # 1.1 -> saturates to 1
            self.assertAlmostEqual(result[2].as_float(),  1.0, places=4)
            self.assertAlmostEqual(result[3].as_float(), -0.8, places=4)

        sim = Simulator(matrix)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_matrix.vcd", "w")):
            sim.run()

    @parameterized.expand([
        ["mux_mac", mac.MuxMAC],
        ["ring_mac", mac.RingMAC],
    ])
    def test_waveshaper(self, name, mac_type):

        def scaled_tanh(x):
            return math.tanh(3.0*x)

        match mac_type:
            case mac.RingMAC:
                m = Module()
                m.submodules.server = server = mac.RingMACServer()
                m.submodules.waveshaper = dut = dsp.WaveShaper(
                    lut_function=scaled_tanh, lut_size=16, macp=server.new_client())
            case _:
                m = Module()
                m.submodules.waveshaper = dut = dsp.WaveShaper(lut_function=scaled_tanh, lut_size=16)

        async def testbench(ctx):
            for n in range(0, 100):
                x = fixed.Const(math.sin(n*0.10), shape=ASQ)
                await stream.put(ctx, dut.i, x)
                result = await stream.get(ctx, dut.o)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open(f"test_waveshaper_{name}.vcd", "w")):
            sim.run()

    def test_gainvca(self):

        def scaled_tanh(x):
            return math.tanh(3.0*x)

        m = Module()
        m.submodules.vca = vca = dsp.VCA()

        async def testbench(ctx):
            for n in range(0, 100):
                x = fixed.Const(0.8*math.sin(n*0.3), shape=mac.SQNative)
                gain = fixed.Const(3.0*math.sin(n*0.1), shape=mac.SQNative)
                await stream.put(ctx, vca.i, [x, gain])
                _ = await stream.get(ctx, vca.o)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_gainvca.vcd", "w")):
            sim.run()

    def test_nco(self):

        m = Module()

        def sine_osc(x):
            return math.sin(math.pi*x)

        nco = dsp.SawNCO()
        waveshaper = dsp.WaveShaper(lut_function=sine_osc, lut_size=128,
                                    continuous=True)

        m.submodules += [nco, waveshaper]

        wiring.connect(m, nco.o, waveshaper.i)

        async def testbench(ctx):
            for n in range(0, 400):
                phase = fixed.Const(0.1*math.sin(n*0.10), shape=ASQ)
                await stream.put(ctx, nco.i, {
                    'freq_inc': 0.66,
                    'phase': phase
                })
                result = await stream.get(ctx, waveshaper.o)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_nco.vcd", "w")):
            sim.run()

    def test_dwo(self):

        dut = dsp.DWO()

        async def testbench(ctx):
            for n in range(0, 400):
                result = await stream.get(ctx, dut.o)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_dwo.vcd", "w")):
            sim.run()

    def test_boxcar(self):

        boxcar = delay_effect.Boxcar(n=32, hpf=True)

        async def testbench(ctx):
            for n in range(0, 1024):
                x = fixed.Const(0.1+0.4*(math.sin(n*0.2) + math.sin(n)), shape=ASQ)
                await stream.put(ctx, boxcar.i, x)
                _ = await stream.get(ctx, boxcar.o)

        sim = Simulator(boxcar)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_boxcar.vcd", "w")):
            sim.run()

    def test_dcblock(self):

        dut = dsp.DCBlock()

        async def testbench(ctx):
            for n in range(0, 1024*20):
                x = fixed.Const(0.2+0.001*(math.sin(n*0.2) + math.sin(n)), shape=ASQ)
                await stream.put(ctx, dut.i, x)
                _ = await stream.get(ctx, dut.o)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_dcblock.vcd", "w")):
            sim.run()

    def test_onepole(self):

        dut = dsp.OnePole()
        target = 0.5

        async def stimulus(ctx):
            x = fixed.Const(target, shape=ASQ)
            while True:
                await stream.put(ctx, dut.i, x)

        async def testbench(ctx):
            ctx.set(dut.shift, 4)
            for n in range(0, 256):
                y = await stream.get(ctx, dut.o)
            self.assertAlmostEqual(y.as_float(), target, places=2)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(stimulus, background=True)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_onepole.vcd", "w")):
            sim.run()

    def test_stream_arbiter(self):

        n_channels = 3
        n_elements = 5
        dut = stream_util.Arbiter(n_channels=n_channels, shape=unsigned(8))
        def mk_stimulus(n):
            async def stimulus(ctx):
                for z in range(n_elements):
                    await stream.put(ctx, dut.i[n], 10*n + z)
                    await ctx.tick().repeat(n+1)
            return stimulus

        async def testbench(ctx):
            result = []
            expect = [10*n+z for z in range(n_elements) for n in range(n_channels)]
            for n in range(n_channels*n_elements):
                result.append(await stream.get(ctx, dut.o))
            self.assertEqual(sorted(result), sorted(expect))

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        for n in range(n_channels):
            sim.add_process(mk_stimulus(n))
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file=open("test_stream_arbiter.vcd", "w")):
            sim.run()


class _NormScopeTrigger(wiring.Component):
    """Trigger + ramp path mirroring ``digital_scope`` NORM / FREE logic."""

    def __init__(self, *, shape=ASQ, td_scale=0.5, hysteresis=0):
        self._shape = shape
        self._td_scale = td_scale
        self._hysteresis = hysteresis
        super().__init__({
            "i": In(amaranth_stream.Signature(data.StructLayout({
                "sample": shape,
                "threshold": shape,
            }))),
            "trigger_always": In(1),
            "falling": In(1),
            "capture_active": In(1, init=1),
            "o": Out(amaranth_stream.Signature(shape)),
            "dbg_restarts": Out(unsigned(16)),
            "dbg_norm_fire": Out(1),
            "dbg_ramp_at_top": Out(1),
            "dbg_norm_fire_count": Out(unsigned(16)),
        })

    def elaborate(self, platform):
        m = Module()
        m.submodules.trig = trig = dsp.Trigger(
            shape=self._shape, hysteresis=self._hysteresis)
        m.d.comb += trig.falling.eq(self.falling)
        m.submodules.ramp = ramp = dsp.Ramp(shape=self._shape)
        td = fixed.Const(self._td_scale, shape=dsp.Ramp.TIMEBASE_SQ)

        ramp_at_top = Signal()
        prev_ramp_at_top = Signal()
        ramp_restarted = Signal()
        trig_seen = Signal()
        norm_fire = Signal()
        ramp_fire = Signal()
        restarts = Signal(16)
        norm_fire_count = Signal(16)

        m.d.comb += [
            ramp_at_top.eq(ramp.o.payload > fixed.Const(0.985, shape=self._shape)),
            ramp_restarted.eq(prev_ramp_at_top & ~ramp_at_top),
            trig_seen.eq(trig.o.payload & trig.i.valid & trig.o.ready),
            norm_fire.eq(trig_seen & ramp_at_top & ~self.trigger_always),
            ramp_fire.eq((self.trigger_always | norm_fire) &
                         self.capture_active),
            self.dbg_norm_fire.eq(norm_fire),
            self.dbg_ramp_at_top.eq(ramp_at_top),
        ]
        m.d.sync += prev_ramp_at_top.eq(ramp_at_top)

        with m.If(norm_fire):
            m.d.sync += norm_fire_count.eq(norm_fire_count + 1)
        with m.If(ramp_restarted):
            m.d.sync += restarts.eq(restarts + 1)

        dsp.connect_remap(m, self.i, trig.i, lambda o, i: [
            i.payload.sample.eq(o.payload.sample),
            i.payload.threshold.eq(o.payload.threshold),
        ])
        dsp.connect_remap(m, trig.o, ramp.i, lambda o, i: [
            i.payload.trigger.eq(ramp_fire),
            i.payload.td.eq(td),
        ])
        m.d.comb += [
            self.o.payload.eq(ramp.o.payload),
            self.o.valid.eq(ramp.o.valid),
            ramp.o.ready.eq(self.o.ready),
            self.dbg_restarts.eq(restarts),
            self.dbg_norm_fire_count.eq(norm_fire_count),
        ]
        return m


class NormTriggerTests(unittest.TestCase):

    def _make_dut(self, *, trigger_always=False, falling=False, hysteresis=0,
                  td_scale=0.5):
        m = Module()
        dut = _NormScopeTrigger(td_scale=td_scale, hysteresis=hysteresis)
        m.submodules.dut = dut
        m.d.comb += [
            dut.trigger_always.eq(trigger_always),
            dut.falling.eq(falling),
        ]
        return m, dut

    async def _put(self, ctx, dut, sample, threshold=0.0):
        await stream.put(ctx, dut.i, {
            "sample": fixed.Const(sample, shape=ASQ),
            "threshold": fixed.Const(threshold, shape=ASQ),
        })

    def test_mid_sweep_crossing_not_replayed_at_top(self):
        """A crossing during the sweep must not restart when the ramp later idles at top."""
        m, dut = self._make_dut()
        state = {"saw_mid_crossing": False}

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            threshold = 0.0
            await self._put(ctx, dut, -0.5, threshold)
            for sample in (-0.2, 0.2):
                await self._put(ctx, dut, sample, threshold)
                if not ctx.get(dut.dbg_ramp_at_top) and ctx.get(dut.dbg_norm_fire) == 0:
                    state["saw_mid_crossing"] = True
            restarts_before_top = ctx.get(dut.dbg_restarts)
            for _ in range(500):
                await self._put(ctx, dut, 0.9, threshold)
                if ctx.get(dut.dbg_ramp_at_top):
                    break
            self.assertTrue(ctx.get(dut.dbg_ramp_at_top))
            for _ in range(40):
                await self._put(ctx, dut, 0.9, threshold)
            self.assertEqual(ctx.get(dut.dbg_restarts), restarts_before_top)
            await self._put(ctx, dut, -0.5, threshold)
            await self._put(ctx, dut, 0.2, threshold)
            self.assertGreater(ctx.get(dut.dbg_norm_fire_count), 0)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()
        self.assertTrue(state["saw_mid_crossing"])

    def test_restart_preceded_by_norm_fire(self):
        m, dut = self._make_dut()
        saw_norm_before_restart = []

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            prev_restarts = 0
            prev_norm_count = 0
            for n in range(4000):
                y = 0.9 * math.sin(2 * math.pi * 0.11 * n)
                await self._put(ctx, dut, y)
                restarts = ctx.get(dut.dbg_restarts)
                norm_count = ctx.get(dut.dbg_norm_fire_count)
                if restarts != prev_restarts:
                    saw_norm_before_restart.append(norm_count > prev_norm_count)
                    prev_restarts = restarts
                    prev_norm_count = norm_count
            self.assertGreater(len(saw_norm_before_restart), 3)
            self.assertTrue(all(saw_norm_before_restart), saw_norm_before_restart)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_consecutive_restarts_keep_input_phase(self):
        """Awkward sweep/input ratio should not alternate by 180 degrees."""
        m, dut = self._make_dut()
        restart_samples = []
        freq = 0.11
        period = 1.0 / freq

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            prev_restarts = 0
            for n in range(6000):
                y = 0.9 * math.sin(2 * math.pi * freq * n)
                await self._put(ctx, dut, y)
                restarts = ctx.get(dut.dbg_restarts)
                if restarts != prev_restarts:
                    restart_samples.append(n)
                    prev_restarts = restarts
            self.assertGreaterEqual(len(restart_samples), 4)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

        ref = restart_samples[0] % period
        for sample in restart_samples[1:]:
            phase = sample % period
            delta = min((phase - ref) % period, (ref - phase) % period)
            self.assertLess(
                delta, 1.5,
                f"restart phase drift: ref={ref} got={phase} samples={restart_samples}",
            )

    def test_free_mode_restarts_without_crossing(self):
        m, dut = self._make_dut(trigger_always=True)

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            for n in range(2000):
                await self._put(ctx, dut, 0.9)
            self.assertGreater(ctx.get(dut.dbg_restarts), 2)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_ramp_waits_at_top_while_capture_is_inactive(self):
        """A bank swap must not consume a whole unseen ramp sweep."""
        m, dut = self._make_dut(trigger_always=True)

        async def testbench(ctx):
            ctx.set(dut.o.ready, 1)
            ctx.set(dut.capture_active, 0)

            for _ in range(500):
                await self._put(ctx, dut, 0.0)
                if ctx.get(dut.dbg_ramp_at_top):
                    break
            self.assertTrue(ctx.get(dut.dbg_ramp_at_top))

            for _ in range(40):
                await self._put(ctx, dut, 0.0)
            self.assertEqual(ctx.get(dut.dbg_restarts), 0)
            self.assertTrue(ctx.get(dut.dbg_ramp_at_top))

            ctx.set(dut.capture_active, 1)
            await self._put(ctx, dut, 0.0)
            await self._put(ctx, dut, 0.0)
            self.assertGreater(ctx.get(dut.dbg_restarts), 0)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_hysteresis_rejects_opposite_edge_recrossing(self):
        """Rising mode must not fire on chatter around the falling crossing."""
        hysteresis = 0.002
        m = Module()
        m.submodules.dut = dut = dsp.Trigger(shape=ASQ, hysteresis=hysteresis)
        pulse_count = Signal(8)
        m.d.comb += [dut.falling.eq(0), dut.o.ready.eq(1)]
        with m.If(dut.o.valid & dut.o.ready & dut.o.payload):
            m.d.sync += pulse_count.eq(pulse_count + 1)

        async def testbench(ctx):
            async def put(sample):
                await stream.put(ctx, dut.i, {
                    "sample": fixed.Const(sample, shape=ASQ),
                    "threshold": fixed.Const(0, shape=ASQ),
                })

            # Launch one legitimate rising trigger. This leaves Trigger
            # disarmed until the input passes the lower Schmitt threshold.
            await put(-0.02)
            await put(0.02)
            first_count = ctx.get(pulse_count)
            self.assertEqual(first_count, 1)

            # A tiny below/above-zero recrossing at the falling edge must not
            # launch an inverted sweep.
            await put(0.001)
            await put(-0.0005)
            await put(0.0005)
            self.assertEqual(ctx.get(pulse_count), first_count)

            # Once the signal moves beyond the Schmitt re-arm margin, the next
            # genuine rising crossing must trigger normally.
            await put(-0.01)
            await put(0.01)
            self.assertEqual(ctx.get(pulse_count), first_count + 1)

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()
