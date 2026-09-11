"""Deterministic accepted-sample accuracy probe for the production detector.

Run with PYTHONPATH=src .venv/bin/python tests/tuner_accuracy_probe.py.
This measures numerical detector behavior, not codec clock accuracy or CPU cost.
"""
import json
import argparse
import math
import random
from amaranth.sim import Simulator
from tiliqua.dsp.tuner import TunerPeripheral


def measure(*, frequency=440.0, amplitude=4000, offset=0, waveform="sine",
            initial_phase=0.0, duty=0.5, second_harmonic=0.0,
            noise_counts=0, seed=0, sample_rate=192_000):
    """Probe integer ADC samples, with optional bounded uniform noise.

    Harmonic amplitude is relative to the fundamental; clipping is to the
    signed 16-bit ADC range. Noise is deterministic, not an analog noise model.
    """
    fs = sample_rate
    dut = TunerPeripheral(sample_rate=fs, min_pitch_window_s=0.02)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    readings = []
    first = None
    noise = random.Random(seed)
    waveform_fn = {
        "sine": lambda p: math.sin(math.tau*p),
        "triangle": lambda p: 1-4*abs(p-0.5),
        "saw": lambda p: 2*p-1,
        "square": lambda p: 1 if p >= 0.5 else -1,
        "pulse": lambda p: 1 if p < duty else -1,
    }[waveform]

    async def bench(ctx):
        nonlocal first
        ctx.set(dut.i.valid, 1)
        sequence = 0
        for n in range(int(fs*0.22)):
            phase = (initial_phase+n*frequency/fs) % 1.0
            value = waveform_fn(phase) + second_harmonic*math.sin(2*math.tau*phase)
            sample = round(offset+amplitude*value)
            if noise_counts:
                sample += noise.randint(-noise_counts, noise_counts)
            sample = max(-32768, min(32767, sample))
            ctx.set(dut.i.payload[0].as_value(), sample)
            await ctx.tick()
            new_sequence = ctx.get(dut._pitch_sequence.f.sequence.r_data)
            if new_sequence != sequence:
                sequence = new_sequence
                samples = ctx.get(dut._period_samples.f.samples.r_data)
                cycles = ctx.get(dut._period_cycles.f.cycles.r_data)
                if samples and cycles:
                    hz = fs*cycles/samples
                    if first is None:
                        first = round(1000*(n+1)/fs,2)
                    if n >= int(fs*0.12):
                        readings.append(1200*math.log2(hz/frequency))

    sim.add_testbench(bench)
    sim.run()
    return dict(sample_rate=fs, waveform=waveform, frequency=frequency, amplitude=amplitude,
                offset=offset, initial_phase=initial_phase, duty=duty,
                second_harmonic=second_harmonic, noise_counts=noise_counts,
                seed=seed, first_ms=first, updates=len(readings),
                max_abs_cents=round(max(map(abs,readings)),3) if readings else None,
                mean_cents=round(sum(readings)/len(readings),3) if readings else None)


CASES = ([dict(frequency=f) for f in (32.7032,65.4064,110,440,1760,7040)] +
         [dict(waveform=w) for w in ("triangle","saw","square")] +
         [dict(frequency=110,amplitude=a) for a in (200,800,2000)] +
         [dict(frequency=110,amplitude=2000,offset=d) for d in (-6000,6000)])

WAVEFORM_CASES = (
    [dict(frequency=110, amplitude=72, initial_phase=p)
     for p in (0.125, 0.375, 0.625, 0.875)] +
    [dict(waveform="pulse", duty=d) for d in (0.1, 0.9)] +
    [dict(amplitude=50000), dict(amplitude=4000, noise_counts=32),
     dict(amplitude=200, noise_counts=16), dict(second_harmonic=0.25)])

# These have a 440 Hz fundamental but multiple positive crossings per cycle.
# Kept separate from the passing accuracy envelope, not silently excluded.
HARMONIC_LIMIT_CASES = [dict(second_harmonic=h) for h in (0.75, 1.5)]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waveforms", action="store_true",
                        help="probe phase, pulse, clipping, noise and harmonic limits")
    parser.add_argument("--sample-rate", type=int, choices=(48000,192000), default=192000,
                        help="default hardware uses 48000; earlier baselines used 192000")
    args = parser.parse_args()
    cases = WAVEFORM_CASES + HARMONIC_LIMIT_CASES if args.waveforms else CASES
    for case in cases:
        print(json.dumps(measure(**case, sample_rate=args.sample_rate)),flush=True)
