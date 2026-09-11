"""Production-rate accuracy envelope and explicit fundamental-detection limits."""
import pytest
import math
from amaranth.sim import Simulator
from tiliqua.dsp.tuner import TunerPeripheral
from tuner_accuracy_probe import measure, WAVEFORM_CASES, HARMONIC_LIMIT_CASES


@pytest.mark.parametrize("frequency", [20, 20.37, 55, 997, 7040, 16000, 19753, 20000])
@pytest.mark.parametrize("phase", [0.13, 0.61])
def test_full_audio_band_sine_accuracy(frequency, phase):
    result = measure(frequency=frequency, initial_phase=phase, sample_rate=192000)
    assert result["updates"] >= 2, result
    assert result["max_abs_cents"] < 2.0, result
    assert result["first_ms"] < 120, result


@pytest.mark.parametrize("amplitude,offset", [(200,0),(800,0),(2000,0),
                                               (2000,-6000),(2000,6000)])
def test_low_level_and_dc_offset_sines_keep_tracking(amplitude, offset):
    result = measure(frequency=110, amplitude=amplitude, offset=offset)
    assert result["updates"] >= 3, result
    assert result["max_abs_cents"] < 2.0, result
    assert result["first_ms"] < 120, result


@pytest.mark.parametrize("sample_rate", [48000,192000])
@pytest.mark.parametrize("offset", [-6000,6000])
def test_dc_settling_time_is_consistent_across_codec_rates(sample_rate, offset):
    result = measure(frequency=110, amplitude=2000, offset=offset, sample_rate=sample_rate)
    assert result["updates"] >= 3, result
    assert result["max_abs_cents"] < 3.0, result
    assert result["first_ms"] < 70, result


@pytest.mark.parametrize("phase", [0.125,0.375,0.625,0.875])
def test_default_rate_low_notes_remain_sensitive(phase):
    result = measure(frequency=32.7032, amplitude=72, initial_phase=phase, sample_rate=48000)
    assert result["updates"] >= 2, result
    assert result["max_abs_cents"] < 3.0, result
    assert result["first_ms"] < 100, result


@pytest.mark.parametrize("offset", [-6000,6000])
def test_default_rate_live_dc_step_settles_without_losing_pitch(offset):
    fs = 48000
    dut = TunerPeripheral(sample_rate=fs, min_pitch_window_s=0.02)
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    async def bench(ctx):
        sequence, updates = 0, 0
        ctx.set(dut.i.valid,1)
        for n in range(round(fs*0.34)):
            dc = offset if n >= round(fs*0.12) else 0
            ctx.set(dut.i.payload[0].as_value(),round(dc+2000*math.sin(math.tau*110*n/fs)))
            await ctx.tick()
            new_sequence = ctx.get(dut._pitch_sequence.f.sequence.r_data)
            if new_sequence != sequence:
                sequence = new_sequence
                # Allow 120 ms after the step, then check every published
                # observation, not only the final readout.
                if n >= round(fs*0.24):
                    samples = ctx.get(dut._period_samples.f.samples.r_data)
                    cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
                    assert samples > 0 and cycles > 0
                    assert abs(1200*math.log2(fs*cycles/samples/110)) < 3
                    updates += 1
        assert updates >= 3

    sim.add_testbench(bench)
    sim.run()


@pytest.mark.parametrize("case", WAVEFORM_CASES)
def test_phase_pulse_clipping_and_bounded_noise(case):
    result = measure(**case)
    assert result["updates"] >= 3, result
    assert result["max_abs_cents"] < 2.0, result
    assert result["first_ms"] < 120, result


@pytest.mark.parametrize("case", HARMONIC_LIMIT_CASES)
@pytest.mark.xfail(strict=True, reason="Crossing counter mistakes strong second harmonic for fundamental")
def test_strong_second_harmonic_reports_fundamental(case):
    result = measure(**case)
    assert result["updates"] >= 3, result
    assert result["max_abs_cents"] < 2.0, result
