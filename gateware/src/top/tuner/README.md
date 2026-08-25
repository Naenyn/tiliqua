# TUNER proof of concept

This bitstream measures a selected monophonic audio input and displays:

- nearest chromatic note and octave;
- cents offset, referenced to configurable A4 (440 Hz by default);
- measured frequency;
- calibrated input Vrms and peak-to-peak voltage; and
- the pitch on octave-radius rings (low octaves inside, high octaves outside).

Output 1 can optionally emit a calibrated 1 Vpp sine reference. It can remain
off, follow the configured A4 reference, or follow the nearest equal-tempered
note to the detected input. Its 32-bit phase accumulator is clocked by accepted
DAC samples, so FIFO backpressure does not detune it.

Outputs 2-4 are held at calibrated zero. The bitstream does not yet emit a
reference CV and contains no oscillator calibration or quantization.

## Detector

The first detector is intentionally oscillator-oriented. Gateware removes slow
DC, applies hysteresis, and counts positive-going cycles over at least 50 ms.
This is small, has good resolution for waveforms with one positive crossing per
period, and supplies the measurements needed by a first hardware evaluation.

It is not yet a general fundamental estimator. Signals with several crossings
per period, strong subharmonics, noise, or a louder harmonic than fundamental
can produce an octave or harmonic error. A YIN/autocorrelation detector remains
the expected next step after validating input level behavior and the UI.

## Build and test

From `gateware/`:

```sh
PYTHONPATH=src pdm run pytest tests/test_tuner.py -q
PYTHONPATH=src pdm tuner build --hw r5
```

Add `--fs-192khz` to evaluate the higher codec sample rate. Building does not
flash the archive; flashing is a separate, explicit operation.
