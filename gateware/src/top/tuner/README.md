# TUNER proof of concept

## Current interface — September 18, 2026

See [automatic calibration](AUTO_CALIBRATION.md) and [routing](CONCURRENCY.md)
for the current interface. CAL performs measurement, verification and guarded
refinement automatically, followed by explicit review/accept/save. It supports
121 initial positions, up to eight additional refinement points and eight
oscillator profile slots. PROFILES and its optional read-only CHECK sit under
CAL. SCALES edits scales; ROUTES is the only playback RUN page and combines
optional quantization with optional oscillator correction per output. A route
needs at least one stage enabled. NOTES/SETUPS sit under SCALES. Child-page
headers return to the parent. TUNER, SETTINGS and HELP remain top-level pages.

The [USB storage investigation](USB_STORAGE.md) covers upstream read/write
support and the remaining integration/resource work; thumb-drive support is
not enabled yet. Automatic calibration has host-test coverage and awaits its
first hardware trial.

On the selected NSDF feature-development build (`TILIQUA_TUNER_NSDF=1`), both
tuner views, calibration, verification and playback audio checks use the shared
NSDF detector. Calibration hardware trials have passed; the original detector
and verifier are not synthesized in this configuration. See the [pause checkpoint](CHECKPOINT.md)
for current feature status, qualification, remaining work and build instructions, and the [detector decision](DETECTOR_DECISION.md)
for evidence, resource tradeoffs and the boundary between those consumers.

See [detector accuracy baseline](ACCURACY.md) for measured synthetic-signal
limits and the low-level/DC-filter correction. Four-channel acquisition is
implemented. That accuracy document describes the original crossing-based path,
not the current NSDF tuner's absolute accuracy.

This bitstream continuously measures all four monophonic audio inputs and displays:

- nearest chromatic note and octave;
- cents offset, referenced to configurable A4 (440 Hz by default);
- measured frequency;
- calibrated input Vrms and peak-to-peak voltage; and
- the pitch on octave-radius rings (low octaves inside, high octaves outside).

The reference-tone feature has been removed from production firmware and
gateware. All outputs remain at calibrated zero unless an explicitly started
calibration operation, profile check, or explicitly armed route owns them. A4 remains configurable as a tuning reference,
not an audio output.

All channel labels follow the physical panel's 0–3 numbering.
ROUTES supports four independently configured CV outputs, with optional scale
quantization and/or an explicitly bound oscillator correction curve. CAL and
CHECK use fixed A4=440 Hz for profile measurement. Sitting on either page does
not start output; otherwise unowned outputs remain at commanded calibrated zero.

## Controls

Press the encoder to open the boxed menu, rotate to navigate, press to edit,
and press again to finish. The top-level pages are TUNER, CAL, SETTINGS, HELP,
ROUTES and SCALES. Supporting pages are reached through parent-page buttons.
The menu hides after five seconds of inactivity. Boot restores saved settings
but starts navigation at TUNER, with no output armed.

CAL contains input, output, 0v note, run, accept, discard and profiles. RUN
performs the automatic procedure described in [AUTO_CALIBRATION.md](AUTO_CALIBRATION.md).
Initial measurement runs upward with nominal semitone voltage spacing over
-5..+5 V; valid edge limits can yield a smaller range. Ten volts does not
guarantee ten measurable octaves. The 0v note is the musical reference for
nominal voltage display, not the oscillator's measured pitch at zero.

Review shows measured coverage, checked worst error and cautious tuning advice.
ACCEPT replaces RAM only; save explicitly in PROFILES. DISCARD keeps the prior
accepted profile. RUN rescans. Saved slots remain unchanged throughout.
Retuning the oscillator invalidates the old curve even if a new result is
discarded. Pending review must be resolved before saving/recalling profiles.

PROFILES offers eight slots and CHECK for non-mutating accuracy checks of the
accepted/loaded profile. CHECK sweeps corrected pitches on a 50-cent grid,
reports worst signed mean error and within-target span, then returns output
to zero. It requires the original oscillator patch and tuning. Run again stops
it; navigation does not stop it. Measurement freshness, settling, repeatability
and timeouts are shared with automatic calibration. Check results do not modify
or save the curve.

The former manual note/POINTS/refinement controls are retained only in internal
measurement helpers/tests, not exposed in the normal interface. Serial
diagnostics remain available. Refinement is now part of CAL, with independent
local tests followed by a full-range recheck and rollback on regression.

## Standalone quantizer

Nominal quantization does not require a loaded oscillator profile or qualified
audio. On ROUTES select CV input, output (both physical 0–3), the note name for
0 V, correction NONE and quantize SCALE, then explicitly RUN.
The output is nominal 1 V/oct over -5..+5 V, with the motherboard's normal
DAC calibration still applied, but no oscillator-specific correction curve.
Choose CHROMATIC, MAJOR, natural MINOR, MAJ PENTA, MIN PENTA, or 24 EDO
(quarter tones). ROOT selects the scale's pitch class; TRANSPOSE shifts the
quantized result by -12..+12 semitones, including in chromatic mode. The scale
root is anchored in the octave containing the selected 0 V note. The 0 V note
still determines CV-to-pitch conversion, not the oscillator's actual tuning.
Running channel settings are locked; stop that channel before changing them.
Navigation does not stop output. It never arms automatically at startup, recall, or page entry.

MAPPING selects NEAREST or EQUAL. EQUAL divides the full repeating input span
into equal-width bins, one per selected degree, beginning at the root. Output
intervals remain the selected pitches; this does not mean equal temperament.
For a five-note one-octave pattern each bin spans 0.2 V of input. A two-octave
pattern with four total notes uses four 0.5 V bins, even if the halves contain
different numbers of notes. Stop the selected channel before changing mapping.

CUSTOM 2 uses the NOTES menu: choose octave A/B, choose a note, then TOGGLE.
CLEAR and FILL affect only the selected octave. Both active halves repeat as
one two-octave pattern across the voltage range; nearest mode searches across
the internal boundary and the repeat boundary. If either half is empty, the
remaining pitch classes repeat every octave (including when only B is populated).
Both halves empty prevents RUN. Notes are relative to C before root and transpose
are applied. The editor starts with chromatic A and empty B. NOTES **SLOT** selects
one of eight pattern slots. **SAVE** stores both masks in that slot's independent,
checksummed record and verifies the write; **LOAD**
explicitly recalls it, including after a reboot or flash. Edits alone remain in
RAM. Existing single-pattern saves remain in slot 1 without migration. These slots
store note masks, not channel setups or imported microtonal scales.
Saving oscillator profiles or settings does not save these masks. The status
line distinguishes edited, saved, loaded, missing, and failed records. Loading
invalid data leaves the current edits intact. Opening NOTES does not stop output;
edits to an active channel are rejected. Return to SCALES, select
CUSTOM 2, then use RUN on ROUTES to audition. No new renderer or microtonal-format restriction
is introduced by this conventional 24-note editor.

SCALES' **output** selector selects independent settings for OUT 0–3:
scale, root, transpose, mapping, and the two note masks. Input and 0 V note
are set on ROUTES for that same selected output.
Switching output recalls that output's settings in RAM without stopping playback.
NOTES edits/loads only the selected output's pattern. Pattern slots are reusable
copies: editing a channel does not modify a saved pattern or another channel.
ROUTES **RUN starts/stops only the selected output**, using its own configuration.
Two outputs are calculated per 1 ms interrupt, giving each output a 500 Hz update
rate. Both batches use the same captured input readings, and all four staged
voltages are committed together at one DAC update boundary. Safety disables
remain immediate rather than waiting for a group commit.
Running settings are locked; channel selection and page navigation do not stop
outputs. An empty custom pattern cannot arm its lane.
Per-lane stale CV, missing ACK, rail, and output faults stop that lane; scheduling
or shared CPU-budget faults stop the whole group. Calibration has
hardware priority only on its reserved output; unrelated quantizer lanes continue.
The earlier four-quantizer implementation passed live operation; mixed-mode
operation passes simulation and routed FPGA timing but awaits hardware validation.
Direct physical CV edge alignment remains unmeasured; see the checkpoint.
Four lightweight lanes share the scale/mapping implementation;
corrected routes retain one immutable measured curve each, without duplicating the detector.

**SETUPS** offers eight explicit SAVE/LOAD slots for all four channels together,
including their note masks. Save is read-back verified; load validates the entire
record before replacing RAM settings, clears curve bindings and never arms output.
TQS2 adds per-output quantization enable and correction source; TQS1 is still readable. SETTINGS/Save still
only saves menu settings; use SETUPS/Save to retain all four configurations.
Missing/invalid setups leave current settings intact. Setup slots, pattern slots,
and oscillator profile slots are separate; existing records are preserved.

The shared engine uses nearest-degree rounding with midpoint hysteresis (up to
five cents, capped to a quarter of each adjacent interval for dense scales), retains
the last valid note for out-of-range CV, and stops on stale CV, rails, output
faults, or missed processing deadlines. STOP commands 0 V, not an audio mute.
The tuner acquisition continues independently. This first standalone version
has one active output and no trigger input; multichannel
quantization and optional oscillator-profile correction remain future work.
No new renderer, pitch engine, FPGA logic, or retained profile copy is added.
The scale math supports non-octave periods and fractional intervals. See
[SCALES.md](SCALES.md) for the offline Scala converter, explicit format limits,
and the remaining device-import/storage work. The converter does not yet
upload files to the module. Numerical table precision is 0.001 cent; nominal
DAC steps are 250 microvolts (0.3 cent at 1 V/oct), so table precision is not a
claim of analog output accuracy or distinguishability of arbitrarily close notes.

## Routing, correction and quantization

See [CONCURRENCY.md](CONCURRENCY.md) for the current assignment model and test plan.
ROUTE (formerly PLAY) and QUANT edit the same per-output processing chain.
Each OUT 0–3 can read any CV input, quantize to its selected scale optionally,
then apply an independently bound oscillator calibration curve optionally.
Use CORRECTION NONE for nominal voltage, RAM or SLOT 1–4 plus BIND for correction.
BIND is explicit and never starts playback. RUN controls only the selected output.

TUNER is always read-only: active CV inputs are hidden/unfocusable, but the audio
input of a calibration scan remains available. One calibration/verification
operation can run alongside independent output routes. Simultaneous scans are
not supported. Profile flash access and setup recall require stopped outputs.
Changing route settings requires stopping the affected output; navigation does not.

Curves are immutable per-output snapshots. Setup records save the correction
source and quantization enable, not curve contents; rebind after setup recall
or reboot. Legacy setups remain readable. Keep the oscillator tuning unchanged;
verify residual error if moving a curve to a different physical DAC output.

## Oscillator profiles

PROFILES provides four saved slots inside TUNER's existing settings storage.
After calibration, select a slot and Save. Set `name pos` (1–24) and `letter`
to edit the name draft; a space removes trailing characters. Save replaces the
selected slot and confirms `SAVED SLOT n - READBACK OK` beneath the menu after
reading back and comparing the stored record. Settings/Save is not
required for profiles. Load validates and restores the curve, name, routing and
nominal 0 V note, confirming `LOADED SLOT n - OUTPUT OFF`; the active RAM profile
name, point count, and routing appear beneath that confirmation. It never starts
output. Empty/invalid slots leave the current
RAM profile untouched. Boot remains on TUNER without automatically loading or
enabling a profile. Settings/Reset preserves saved profiles.

To test persistence, save, reload the bitstream, select the same profile slot
and Load, then test VERIFY. Keep oscillator tuning and patching unchanged and
allow the oscillator to warm up: a saved curve cannot compensate for moving its
tuning knob or arbitrary temperature drift.
For Settings/Save, the save row shows `saved` for about two seconds. A failed write
shows `failed`; missing option storage shows `no flash`. These messages report
the save result, not merely the encoder click.

Display offers ARC, VISUALIZER, and LINEAR. Both spiral modes show four colored
pitch markers; VISUALIZER adds emphasis to the focused channel. LINEAR shows
four simultaneous cents rulers, each with note, frequency and voltage readings.
Channel colors are orange, green, cyan and purple for inputs 0–3. The input
setting (now labeled `focus`) chooses the spiral detail readout,
not which inputs are acquired. Each cursor maps -50..+50 cents onto its ruler;
the center is the nearest note. Backgrounds are cached in the two reserved PSRAM buffers. The
unused view is prepared in small idle-time chunks after boot; if selected before
ready, `PREPARING VIEW` appears while the old tuner view stays live. Once cached,
switching does not redraw the backgrounds. Text and cursor switch with the
background, and the same menu overlays either view. The text-only CAL screen
uses an atomically published blank backdrop instead of clearing/rebuilding a
framebuffer. Entering or leaving CAL retains the cached tuner background and
normally takes one UI update plus a video-frame boundary, not a multi-second
background preparation. CAL no longer draws the decorative outer border.

The main view uses 9x15 glyphs on a centered, 12-pixel horizontal pitch (previously
16 pixels). Its 45-column text area spans logical x=90..629, leaving the circular
edges free. Main-view labels are positioned for this pitch; the established
OSCIO/SONORO menu geometry and font spacing are unchanged.

## Original detector (historical, not the selected NSDF build)

The first detector is intentionally oscillator-oriented. Gateware removes slow
DC, applies hysteresis, and counts positive-going cycles over at least 20 ms.
The DC tracker uses approximately the same 21 ms time constant at 48 and
192 kHz, so the standard build does not take four times longer to settle.
This is small, has good resolution for waveforms with one positive crossing per
period, and supplies the measurements needed by a first hardware evaluation.

A bounded waveform-repetition verifier checks the crossing period and up to
four multiples against a 2048-sample capture at 24 kHz on both the standard
48 kHz and optional 192 kHz codec builds. It chooses the shortest matching
period, allowing some harmonic-rich oscillator signals to be corrected without
blindly halving ordinary notes. Checks run independently of audio and rendering.

This is still not a general fundamental estimator or a calibration-confidence
test. Insufficient history, poor matches and crossing estimates above 4 kHz
remain unverified and use the original crossing result. Weak fundamentals,
complex/noisy signals and transitions may still produce harmonic errors. A new
input needs about 85 ms of capture before verification. One shared verifier
visits each input for eight UI frames (nominally 160 ms), giving a nominal
640 ms round trip. Basic crossing measurements continue on all four channels
throughout; complex-waveform corrections can take a visit to settle. No "verified" status
is exposed in the UI yet. See [accuracy qualification](ACCURACY.md).

The supported priority is accurate basic oscillator waveforms (sine, triangle,
saw and ordinary square), with best-effort handling of complex shapes. Very
narrow pulses, evolving waveshapers and atonal outputs are not guaranteed to
track. Tune from a basic output when available; the module cannot infer an
oscillator's hidden core frequency from an ambiguous output.

## Runtime architecture

Startup, interrupt-shared UI state, and the perpetual real-time loop have
separate storage lifetimes. Allocation-heavy boot manifest and option decoding
complete before interrupts are enabled, the retained UI lives in static main
RAM, and the live loop consumes only a small copyable control snapshot. This is
intentional: calibration profiles and quantizer scales must not enlarge the
real-time stack as their menus grow.

The original implementation's four independent measurement lanes populate a retained four-entry bank through
a foreground-owned CSR read selector. Selecting a read bank does not reset any
lane. Only the bounded harmonic verifier is time-shared; its history is cleared
when it changes channels. The renderer remains shared.

## Build and test

The reusable renderer migration, compatibility boundary, tests and remaining
work are documented in [RENDERER.md](RENDERER.md). The integrated renderer
shares the tuner/menu text pipeline and publishes double-buffered text,
marker and menu state together at a blanking boundary. Deploy matching
firmware/gateware archives; firmware now explicitly commits each display update.

From `gateware/`:

```sh
PYTHONPATH=src pdm run pytest tests/test_tuner.py -q
PYTHONPATH=src pdm run pytest tests/test_tuner_display.py tests/test_tuner_renderer.py -q
PYTHONPATH=src pdm run pytest tests/test_tuner_frames.py -q
PYTHONPATH=src pdm tuner build --hw r5
PYTHONPATH=src pdm tuner_round build --hw r5
```

`tuner` is the fixed, unrotated 1280x720 HDMI development target.
`tuner_round` produces a separate `TUNER-ROUND` artifact for the fixed 720x720
production-panel target and compensates for the display's physical 90-degree
mounting. Keeping these as explicit artifacts prevents mutable bootloader video
state from selecting the wrong UI transform.

Both TUNER targets default to 192 kHz codec sampling for the 20 Hz–20 kHz
measurement target. This default is local to TUNER, not other bitstreams.
Building does not flash the archive; flashing is a separate operation.
