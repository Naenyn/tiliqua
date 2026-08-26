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

## Controls

Press the encoder to open an OSCIO/SONORO-style boxed menu over the live tuner.
Rotate to navigate, press to begin editing, rotate to change the selected value,
and press again to finish. Select the page heading to switch between TUNER,
SETTINGS, and HELP. The menu hides after five seconds of inactivity and exposes
input, display mode, reference-tone mode, A4 reference, and option persistence.

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
PYTHONPATH=src pdm tuner_round build --hw r5
```

`tuner` is the fixed, unrotated 1280x720 HDMI development target.
`tuner_round` produces a separate `TUNER-ROUND` artifact for the fixed 720x720
production-panel target and compensates for the display's physical 90-degree
mounting. Keeping these as explicit artifacts prevents mutable bootloader video
state from selecting the wrong UI transform.

Add `--fs-192khz` to evaluate the higher codec sample rate. Building does not
flash the archive; flashing is a separate, explicit operation.
