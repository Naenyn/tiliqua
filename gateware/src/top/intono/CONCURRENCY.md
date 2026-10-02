# Routing and concurrent operations — September 18, 2026

This supersedes the first, mode-owned implementation (e3f48f83). Inputs carry
roles; outputs own one processing chain. TUNER is a passive audio observer, not
a competing operation that needs RUN.

## User model

- **TUNER:** a read-only view of all four inputs, including inputs claimed by
  calibration or CV routes. Observation never claims a jack or changes a route.
  Pitch qualification still determines whether an input has a valid reading.
- **CAL:** one automatic profile-building operation at a time. It exclusively reserves the
  chosen audio input against CV use, and its CV output against playback.
  Measurement, automatic verification and guarded refinement keep the same
  exclusive operation slot. Navigation does not stop the operation; its
  input/output controls remain locked. PROFILES and read-only CHECK are child
  pages; manual REFINE is no longer a normal menu operation.
- **ROUTES:** four groups, each with one CV input and zero to four exclusively
  attached outputs. ROUTE selects the group; OUTPUT selects an output to edit or
  attach. ADD OUT transfers a stopped output from any previous group, REMOVE
  OUT detaches it. The input and membership of a running group cannot change.
- **SCALES:** edits the selected physical output's intervals and mapping.
  Musical key/transpose and correction stay on ROUTES, independently per output.
- START claims the group's single input and all output jacks atomically. Each
  member then arms with its own scale/curve. Any failure stops the whole group
  and releases its claim. STOP and member faults also stop/release the group.
- Independent groups cannot share inputs or outputs. A group supports fan-out;
  multiple inputs per group are not supported. CAL input/output selectors skip
  assigned jacks. Stopped route configurations do not reserve resources.
- SETUPS stores compact group input/membership alongside per-output settings.
  TQS4 adds eight bytes to TQS3. TQS1–3 migrate shared-input output chains into
  one route group per input; recalled groups remain stopped.

One scan at a time is deliberate: it keeps measurement/review state and the UI
bounded. Applying curves is much cheaper and is supported on all four outputs.
Three outputs can therefore play while the fourth is scanning, provided their
input roles do not conflict. No second detector or renderer was added.

## Assigning correction

1. Select a route group and its input, then select/add the output on ROUTES.
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
by group. An accepted RAM profile may be bound to a stopped output while
other outputs run. Storage slots and runtime output bindings are different.

The source profile's original audio/output route is not forced onto playback.
The user must connect the correct oscillator and leave its tuning unchanged.
Changing the physical output may change residual error; verify after rerouting.
Binding a profile defaults the route's 0 V note to the nearest note of its
measured zero-volt pitch and sets the scale root to that pitch class. Exact
measured tuning anchors nominal fallback outside the curve. A stopped route
may override note/root afterward; rebinding restores the natural defaults.
A profile without a measured 0 V reference keeps the route's explicit settings.

SETUPS now saves correction source and quantization enable with each route,
using TQS2. TQS1 setups still load as nominal quantization. Setup recall clears
bindings and never arms output: BIND correction again. Runtime curve snapshots
are not saved in setups; RAM bindings must be recreated after reboot.

## Safety and performance

No curve extrapolation: pitches outside the measured profile use nominal 1 V/oct
output after quantization, with PROFILE BYPASSED status. Nominal output uses
the existing guarded -5..+8 V range. Targets beyond it select the nearest
reachable note in the configured scale (including root and transpose); continuous
routes cap voltage at the edge. Input clipping keeps the route active using the
clipped observation and shows LIMITED status; its true voltage is unknown.
Correction resumes automatically on profile reentry. The existing quantizer
hysteresis prevents noisy note switching at profile boundaries; continuous
corrected/nominal transitions can still jump because the mappings differ.
Stale CV, ACK and hardware faults retain stop behavior.
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
correction NONE versus bound profile, then add a second output. Confirm all
inputs remain available in tuner focus, including claimed CV and calibration inputs.
Attempt conflicting CAL/ROUTE starts and check the running output is untouched.
Finally exercise a scan alongside playback and four corrected outputs, monitoring
serial peak cycles and scheduling gaps. These new combinations are not yet
hardware-qualified. The earlier physical jack-skew investigation also remains open.

## Focused calibration detector — September 30, 2026

CAL, CHECK and refinement read only their captured input/output pair. While an
operation is active, the shared pitch detector alternates the native and low
banks of that input. Unrelated inputs no longer delay calibration readings.
Opening TUNER during an operation requests passive background observations:
two selected-input bank visits alternate with one background bank visit. Each
of the other six banks is revisited every 18 requests. Leaving TUNER restores
exclusive detector service for the operation; ending it restores all eight banks
in round-robin order. An in-flight request always finishes with its original
channel identity. CV routes continue using their independent raw CV path.

Detector qualification, full-window age, settling, independent-window averaging
and final verification rules are unchanged. Faster request cadence does not make
overlapping audio windows independent. Hardware speed and accuracy comparison
are still required before claiming a scan-time improvement.
