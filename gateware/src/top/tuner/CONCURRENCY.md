# Routing and concurrent operations — September 18, 2026

This supersedes the first, mode-owned implementation (e3f48f83). Inputs carry
roles; outputs own one processing chain. TUNER is a passive audio observer, not
a competing operation that needs RUN.

## User model

- **TUNER:** shows audio-capable inputs. Active CV-source inputs are hidden and
  skipped by focus selection. The audio input of a calibration scan remains
  visible. With all four inputs used as CV, focus reads NONE. This is explicit
  routing, not a claim that a detector can infer the purpose of every waveform.
- **CAL:** one automatic profile-building operation at a time. It exclusively reserves the
  chosen audio input against CV use, and its CV output against playback.
  Measurement, automatic verification and guarded refinement keep the same
  exclusive operation slot. Navigation does not stop the operation; its
  input/output controls remain locked. PROFILES and read-only CHECK are child
  pages; manual REFINE is no longer a normal menu operation.
- **ROUTES (formerly PLAY):** select OUT 0–3 and any IN 0–3. Select the musical
  0 V note, correction source, and quantize OFF or SCALE. Each output owns:
  CV input -> optional scale quantization -> optional measured curve -> DAC.
- **SCALES:** edits the selected route's scale, root, transpose, mapping and notes.
  ROUTES and SCALES are two editors of the same output, not competing engines.
  RUN exists only on ROUTES and requires quantization or correction. Stop before
  edits. NOTES and SETUPS are reached from SCALES.
- Several outputs may share one CV input, with independent scales/curves.
  Stopping one releases only its claim. A scan cannot take that input until
  every active CV route using it has stopped. Input and output numbers need not
  match; their reservations are separate.

One scan at a time is deliberate: it keeps measurement/review state and the UI
bounded. Applying curves is much cheaper and is supported on all four outputs.
Three outputs can therefore play while the fourth is scanning, provided their
input roles do not conflict. No second detector or renderer was added.

## Assigning correction

1. Select output and input on ROUTES.
2. Choose CORRECTION: NONE, RAM, or SLOT 1–8.
3. With correction enabled, select **BIND** to copy the accepted RAM curve or
   saved slot into that output's immutable runtime snapshot.
4. Choose QUANTIZE: OFF for continuous corrected CV, SCALE for quantize then
   correct. Configure scale on SCALES if enabled, then RUN on ROUTES.

BIND never starts an output. A missing/corrupt/unbound curve cannot run corrected
playback. Active curves cannot be replaced; scans and later RAM profile loads
do not mutate existing bindings. A failed replacement invalidates the binding.
Choosing NONE uses nominal CV regardless of any retained curve.

Saved-slot reads, writes and setup recall require outputs to be stopped to avoid
flash/cache timing stalls. Prepare/bind the outputs first, then start them
individually. An accepted RAM profile may be bound to a stopped output while
other outputs run. Storage slots and runtime output bindings are different.

The source profile's original audio/output route is not forced onto playback.
The user must connect the correct oscillator and leave its tuning unchanged.
Changing the physical output may change residual error; verify after rerouting.
The route's 0 V note is explicit and is not inferred from the oscillator pitch.

SETUPS now saves correction source and quantization enable with each route,
using TQS2. TQS1 setups still load as nominal quantization. Setup recall clears
bindings and never arms output: BIND correction again. Runtime curve snapshots
are not saved in setups; RAM bindings must be recreated after reboot.

## Safety and performance

No extrapolation: out-of-range targets retain the last valid output and resume
on reentry. Stale CV, rail, ACK and hardware faults retain stop behavior.
Unrelated outputs survive scan completion or faults. Routes retain the common
input snapshot and staged DAC commit, two lanes per 1-ms interrupt (500 Hz per
lane). Combined route processing has a 500-us CPU guard; expensive work stops
outputs rather than silently breaking their deadlines.

Four resident curves replace the former single PLAY curve plus four nominal
engines. Target MULTI_QUANT storage is 5,148 bytes; linked stack region is
26,616 bytes within the unchanged 32-KiB CPU RAM. Current foreground frame is
11,968 bytes; this is not a whole-call-tree or measured stack high-water bound.
Serial status buffer is 1,536 bytes to accommodate four routes plus calibration
diagnostics. Live CPU and stack qualification remain important.

176 regression tests pass, including host subtests for optional stage composition,
four independent corrected routes, immutable curve binding, CV sharing, passive
tuner eligibility, conflict rejection, TQS1 migration and TQS2 roundtrips.
This is a firmware-only change using e3f48f83's timing-qualified hardware:
19,148 LUT4, 44 EBR, 14 DSP; 60-MHz system clock passes at 65.61 MHz.
192-kHz audio, 720p output and spread_spectrum=0.0 remain unchanged.
See [AUTO_CALIBRATION.md](AUTO_CALIBRATION.md) for automatic-operation bounds,
129-point capacity, eight-slot journal tests and the next physical trial.

## Physical test still required

Start with one known curve on one output: OFF versus SCALE quantization,
correction NONE versus bound profile, then add a second output. Confirm active
CV inputs disappear from tuner focus while calibration audio remains available.
Attempt conflicting CAL/ROUTE starts and check the running output is untouched.
Finally exercise a scan alongside playback and four corrected outputs, monitoring
serial peak cycles and scheduling gaps. These new combinations are not yet
hardware-qualified. The earlier physical jack-skew investigation also remains open.
