# Concurrent operations (September 18, 2026)

Operation lifetime is independent of the visible menu/page. Explicit RUN reserves
the required physical jacks atomically; a conflicting start reports busy without
changing the operation already running. Stop, completion or fault releases them.
Inputs and outputs are separate resources: IN 0 need not own OUT 0.

| Operation | Reservations |
|---|---|
| TUNER / RUN | Selected input (RUN again releases it) |
| CAL, VERIFY, REFINE | Audio input and calibration CV output |
| PLAY | CV input, profile audio input, profile output |
| QUANT / RUN | Selected output and its assigned CV input |

Idle tuner previews remain available on unreserved inputs. Inputs owned by other
modes show RESERVED rather than a competing tuner reading. Quantizer outputs may
share the same input with each other; stopping one does not release the others'
claim. Running routes/settings are locked. Browsing another page or selecting
another quantizer output does not stop the previous operation.

CAL/VERIFY/REFINE and corrected PLAY still share one control engine and are
mutually exclusive. Only one calibration operation runs at a time. Independent
QUANT lanes can run alongside either. Storage writes/recall are blocked while
outputs run; stop first. No operation automatically resumes after reboot.

Hardware CAL priority and faults now affect only the selected output. Unrelated
quantizer lanes retain shared snapshot/staged commit behavior. CPU protection
includes a combined 500-us quantizer + PLAY processing budget per 1-ms interrupt;
exceeding it stops those outputs. This is a guard, not proof of worst-case timing.

## Validation

- 175 regression tests passed, including reservation atomicity, quantizer sharing,
  locked routes, background calibration navigation, explicit stop and mixed
  CAL/quantizer hardware simulation.
- 720p routed build: 19,148 LUT4 (78%), 44 EBR (78%), 14 DSP (50%). All clocks
  pass: system 65.61 MHz against 60 MHz; video 89.38 against 74.25 MHz;
  serializer 467.51 against 371.33 MHz; audio 67.42 against 49.15 MHz.
- 192-kHz audio and spread_spectrum=0.0 retained. No additional pitch engine,
  renderer, or CPU RAM expansion.
- Mixed-mode physical validation is still pending. Do not claim it is qualified
  solely from allocator tests and hardware simulation.

## First hardware test

1. Reserve IN 0 from TUNER. Run QUANT on IN 2 -> OUT 2 with a slow LFO.
2. Run CAL on IN 1 -> OUT 1 with a separate oscillator; browse all three pages.
3. Confirm tuning, quantization and calibration keep running. Conflicting starts
   must report busy without disturbing the owner.
4. Confirm calibration completion leaves OUT 2 running, explicit stops release
   reservations, and two quantizer outputs may share IN 2.
5. Inspect serial timing/fault counters during navigation and simultaneous work.

Existing physical four-output skew investigation remains open; concurrency does
not establish tighter jack-to-jack synchronization.
