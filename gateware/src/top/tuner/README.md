# TUNER proof of concept

On the selected NSDF feature-development build (`TILIQUA_TUNER_NSDF=1`), both
tuner views use the shared NSDF detector; calibration and playback audio checks
retain the original measurement path. See the [detector decision](DETECTOR_DECISION.md)
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
calibration sweep, corrected-note verification, or explicitly armed PLAY owns one. A4 remains configurable as a tuning reference,
not an audio output.

All channel labels follow the physical panel's 0–3 numbering.
The bitstream does not yet emit a
general-purpose reference CV or quantization. CAL now exposes an explicitly
started -5..+5 V oscillator tracking sweep with up to 121 points; see
[calibration status and hardware test](CALIBRATION.md). VERIFY can apply the
RAM profile to a requested note name/octave and cents offset, showing measured error
against that target (fixed A4=440 Hz). It uses the successful calibration's
route, requires Run to start, and stops on leaving VERIFY or a range/output
error. PLAY provides single-channel external-CV playback through that same curve.
Otherwise outputs remain at zero, including
while sitting on CAL before a run.

## Controls

Press the encoder to open an OSCIO/SONORO-style boxed menu over the live tuner.
Rotate to navigate, press to begin editing, rotate to change the selected value,
and press again to finish. Select the page heading to switch between TUNER,
CAL, VERIFY, PROFILES, SETTINGS, HELP, and PLAY. CAL contains input,
output, 0v note, run, accept, and discard. Every sweep uses nominal semitone voltage spacing,
up to 121 points across -5..+5 V, scanning upward from low to high.
Unmeasurable edges and qualified boundary plateaus can produce a limited-range
profile; internal tracking failures remain errors.
Coverage depends on the oscillator and detector; 10 V does not guarantee ten
measurable octaves. Existing saved density settings are ignored.
Completed scans now open a review showing measured CV/pitch coverage and cautious
tuning advice. ACCEPT replaces the active RAM profile; it does not save a slot.
RUN discards the pending result and rescans, allowing oscillator adjustment first.
DISCARD keeps the previous profile. Saved slots are unchanged throughout.
Pending results block PLAY, VERIFY, refinement, save and recall until resolved.
If the oscillator was retuned, its previous profile no longer describes the patch:
rescan before using it again, even if you discarded the newer result.
CAL's `0v note` sets the nominal 0 V note
(default C4) for the displayed 1 V/oct voltage; this is distinct from the
profile-corrected output voltage. The menu hides after five seconds of inactivity and exposes
focus, display mode, A4 reference, and option persistence.
Each boot restores saved instrument settings but starts navigation at the TUNER
page heading, outside edit mode. The menu remains hidden until the encoder press.

After accepting a calibration, the VERIFY target is set to
a whole note near the middle of the measured range. Output remains zero until Run.
VERIFY also displays rolling MEAN
deviation and SPAN (maximum minus minimum) over up to 16 fresh qualified pitches,
at most 500 ms old. The instantaneous deviation remains visible; statistics
never adjust output or calibration data and reset when the target changes.

VERIFY's `mode` selects MANUAL (default) or SCAN. With the calibration patch
unchanged and a calibrated or loaded profile, select SCAN and Run to check all
whole notes and 50-cent midpoints inside its measured range.
SCAN ignores the manual note/cents controls. It waits for fresh, settled samples
at each corrected output
and retains up to four seconds of distinct readings so slow low-frequency
publication can satisfy the eight-reading minimum (manual statistics retain
their half-second window). The per-target timeout remains five seconds.
It then shows the tested/total count, worst signed mean
error and its target, and maximum within-target pitch span. These are measured
results, not an automatic pass/fail threshold. A two-octave profile typically
has 48–49 targets and takes about a minute, depending on detector windows.
Completion restores zero; Run again, exiting VERIFY, or changing verification
mode also stops output. Missing/unstable input times out after five seconds per
target. Partial results remain visible but are not a complete scan. No scan
result changes or saves the calibration curve. Results are not retained on boot.

VERIFY's POINTS mode instead replays each stored calibration voltage and compares
the new measured pitch with the pitch recorded there. This includes the exact
0 V endpoint and avoids interpolation. It shares SCAN's freshness, stability,
timeout and cancellation rules. Results include worst error and its stored
voltage, plus `P0` and `P1` errors for the first two recorded points. For a
low-end discrepancy, load the existing profile and run POINTS without recalibrating
or moving the oscillator's tuning knob. Disagreement at stored points indicates
acquisition/repeatability/drift somewhere in the measurement/output/oscillator
chain; disagreement only between them points toward interpolation or local
response nonlinearity. Neither test alone identifies which physical component
is responsible. POINTS never changes the saved curve.

SCAN also repeats measurements at the worst target and its two surrounding
stored points. The result includes local refinement advice on-screen and over
serial. REFINE reacquires those measurements, proposes one interior point, and
compares the candidate with the original at independent pitches. ACCEPT changes
RAM only; DISCARD retains the original, and saving is always separate. A full
121-point profile refuses refinement rather than removing original anchors.
Advice and local comparison are not a full-range accuracy certificate: verify
the accepted profile again before saving. Recalibrate rather than fitting
corrections to a shifted or unstable oscillator response.

## Corrected pitch-CV playback

PLAY now includes `quantize`: OFF (default) or CHROMATIC. CHROMATIC is the first
single-channel quantizer integration, temporarily hosted in PLAY rather than a
separate quantizer page. It rounds incoming pitch to the nearest semitone before
applying the same measured calibration curve. Midpoint ties round upward; once
a note is selected, it is retained until pitch moves more than 55 cents from it
(five cents beyond the usual boundary). Large changes jump directly to the
nearest note. Stop/restart clears that history. Changing quantization mode during
playback stops output and requires RUN again. Unreachable selected notes hold
the last valid output and resume automatically on reentry; before the first valid
note output remains disabled. Notes are never clamped to the profile edge.
Fresh out-of-range samples renew the held command, while stale measurements,
input rails, output faults and explicit stop retain the zero-output safety path.
The oscillator may remain patched to the loaded profile's audio input for pitch
checking. Frequency is shown while settling; cents error requires the entire
measurement window to follow the last target change plus a settling margin.
This check observes audio; it does not retune the output or alter the profile.
During PLAY, the shared audio verifier stays on the loaded profile's audio input
instead of rotating through all four inputs. Rapid target changes can still
prevent a qualified, settled reading; CV quantization does not depend on this
optional audio check.
There is no trigger,
scale selection, polyphonic quantization or automatic output arming yet.
The planned standalone quantizer must support multiple independent CV channels
without requiring tuner operation or a calibration profile. Applying an oscillator
profile is an optional correction stage, not a prerequisite for quantization.

Load a profile, keep its oscillator tuning unchanged, then select PLAY (after
HELP in the page list). PLAY/input selects the pitch-CV source; the output comes
from the loaded profile and cannot be silently rerouted. Oscillator audio can
remain patched to its tuner input. Supply 1 V/oct pitch CV, where 0 V means the
profile's saved zero-note setting (normally C4). RUN explicitly starts/stops.
Leaving PLAY or changing its input stops output. Loading a profile never starts
playback. The original calibration and all saved profiles remain unchanged.

PLAY uses a separate DC-preserving 64-sample snapshot and a 1-kHz interrupt
service, not the audio DC estimator or 50-Hz display loop. A requested pitch
outside the measured curve holds the last valid output until it reenters range,
without clamping or extrapolating the calibration curve.
Stale CV, input rails, output faults/ack timeouts, excessive computation time
or scheduling gaps latch a stop requiring another explicit RUN. Unplugged CV
can resemble valid zero and is not detectable as a disconnected cable.
Nominal stopped output is zero; that is not an audio mute or universally safe
pitch. With quantize OFF this playback path is continuous and does
not promise audio-rate FM. Serial reports input/output microvolts, update count,
peak computation cycles and peak service gap for hardware qualification.

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

## Detector

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

Four independent measurement lanes populate a retained four-entry bank through
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
