# INTONO

INTONO was previously built and documented as TUNER. Historical test names,
hardware interfaces (`TUNER_PERIPH`/`TUNER_DISPLAY`), and older experiment logs
retain that term; it also names the tuning mode within INTONO. New builds and
diagnostics use the INTONO instrument name.
Diagnostic build variables now use `TILIQUA_INTONO_*`; the old
`TILIQUA_TUNER_*` forms remain accepted as fallback aliases for archived
commands. If both are set, the INTONO value wins.

The current [oscillator compatibility qualification](OSCILLATOR_QUALIFICATION.md)
records physical tuning/calibration coverage and its limits, including the
Generate3 CORE/FUNDAMENTAL comparison on the latest detector build.

## Current interface — September 30, 2026

See [automatic calibration](AUTO_CALIBRATION.md) and [routing](CONCURRENCY.md)
for the current interface. CAL performs measurement, verification and guarded
refinement automatically, followed by explicit review/accept/save. It supports
121 initial positions, up to eight additional refinement points and eight
oscillator profile slots. PROFILES and its optional read-only CHECK sit under
CAL. SCALES edits scales; ROUTES is the only playback RUN page and combines
optional quantization with optional oscillator correction per output. A route
needs at least one stage enabled. NOTES sits under SCALES; SETUPS sits under ROUTES. Child-page
headers return to the parent. INTONO (the tuner view), SETTINGS and HELP remain
top-level pages.

The [USB storage investigation](USB_STORAGE.md) covers upstream read/write
support and the remaining integration/resource work; thumb-drive support is
not enabled yet. Automatic calibration has host-test coverage and has completed
a Generate3 FUNDAMENTAL hardware run with automatic verification. See the
dated results in AUTO_CALIBRATION.md for the tested range and remaining checks.

The selected NSDF detector is now unconditional on this branch: an ordinary
INTONO build uses it without an experimental build flag. The old crossing
detector and period verifier have been deleted, including their CSRs and
firmware paths, so there is no selectable or accidental fallback. The shared
`TunerPeripheral` now provides level/DC measurement plus calibrated CV output;
NSDF owns every pitch result. Both
tuner views, calibration, verification and playback audio checks use the shared
NSDF detector. Calibration hardware trials have passed; the original detector
and verifier are not synthesized in this configuration. See the [pause checkpoint](CHECKPOINT.md)
for current feature status, qualification, remaining work and build instructions, and the [detector decision](DETECTOR_DECISION.md)
for evidence, resource tradeoffs and the boundary between those consumers.

INTONO intentionally uses the native signed 16-bit ASQ representation
(4 counts/mV, nominal -8.192 to +8.19175 V). Its CV command protocol and NSDF
frontend are both signed 16-bit interfaces. The top level rejects widened-ASQ
builds so a copied build flag cannot silently change physical output gain or
truncate detector input samples. Profiles remain stored in microvolts and are
therefore independent of this internal representation.

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

Controls are always visible on their owning page. Turn the encoder to move the
bright selection/caret; click a value to edit it, turn to change it, then click
again to finish. Action buttons act on one click. Select the page header, click,
and turn to switch among TUNER, CAL, SCALES, ROUTES, OPTIONS and HELP; click to
finish choosing a page. The four main tabs and OPTIONS/HELP access are visible.
Supporting pages are entered through parent-page buttons; selecting and clicking
their header returns to the parent. The active primary tab stays bright and bracketed while controls are selected;
actions are bracketed and control captions use consistent uppercase lettering.
The screen controls do not time out. Boot
restores saved settings but starts at TUNER, with no output armed.

CAL contains input, output, policy, graph, scan/stop, accept, discard and profiles. SCAN
performs the automatic procedure described in [AUTO_CALIBRATION.md](AUTO_CALIBRATION.md).
Initial measurement runs upward with nominal semitone voltage spacing over
-5..+8 V; valid edge limits can yield a smaller range. The voltage span does not
guarantee the same number of measurable octaves. AUTO is the default policy.
FAST uses fewer acquisition estimates for known well-behaved oscillators,
with the same independent final checks; it may miss brief acquisition variation
or need more correction afterwards. Broader hardware qualification is still pending.
The CAL 0V NOTE readout shows the nearest qualified measured note at zero;
`--` means no measured reference is available. It is not an editable scan target.
ARC separates the spiral and all four pitch markers on the left from the focused
input's note, cents, frequency and Vrms/Vpp readouts on the right. Both retained
background drawing paths and every marker share the smaller spiral geometry.
The 11-octave guide still covers the detector range. LINEAR retains four lanes.

The musical override remains on ROUTES.

PROFILES groups the storage slot, SAVE AS name and cursor/character controls above
SAVE/LOAD and CHECK/BACK. The caret identifies the edited character, including
trailing spaces. CURRENT identifies the accepted RAM profile, not a preview of
the selected saved slot. Saving still requires stopped outputs and resolved review.
CHECK shows current/candidate identity, measured pitch coverage and 0 V note,
progress, worst signed error, maximum measurement spread and missing checks.
A grade appears only after the check completes. CHECK/IMPROVE, ACCEPT/DISCARD
and BACK retain their existing validation and actions.

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

CHECK's worst-error headline includes completed local repeat measurements;
serial also reports the grid-only worst separately. Operation completion is
not an accuracy pass: the final accuracy label also requires repeatability.
Automatic serial reports include per-phase active milliseconds for acquisition,
initial checking, refinement, and rechecking; these freeze at review.
Low-note verification may finish after eight independent windows only when all
observed post-settle readings stay within one cent. A larger excursion disables
that shortcut for the target; the existing sixteen-window estimator remains
the fallback. Initial profile acquisition and output settling are unchanged.

The former manual note/POINTS/refinement controls are retained only in internal
measurement helpers/tests, not exposed in the normal interface. Serial
diagnostics remain available. Refinement is now part of CAL, with independent
local tests followed by rechecking the same sampled pitches and rollback on
regression. Automatic calibration checks at most 50 pitches spanning the range,
including endpoints, the zero-volt reference when available, and probes near
measured bends. This is explicitly a sampled check, not certification of every
pitch: narrow errors between probes can escape it. CHECK retains the exhaustive
50-cent grid. Automatic acceptance includes local absolute repeat errors, not
just the initial scan result. There is no overall time limit; RUN again reviews
the last fully checked curve, and RUN from review continues improvement when
available. Individual measurements and correction attempts remain bounded.

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
is introduced by this conventional multi-octave editor.

The NOTES page can also edit independent pattern octaves from the dedicated
TRS MIDI input. Press LEARN BASE and play any note to establish its octave as
the first pattern octave, then tap notes to toggle them on or off. Repeated Note Ons while a key remains
held do not retrigger the toggle. Use CLEAR first to start an empty pattern.
Learning toggles off with another press or on leaving NOTES, never changes a
running output, and never saves automatically. MIDI input is not yet a USB-C
host or an imported microtonal-scale editor.


SCALES shows the interval pattern relative to C, without applying a route's
musical key or semitone transpose. Set OCTAVES (1–8, default 1), then turn through the controls to focus the
keyboard keys, then click a highlighted key to toggle membership. Editing a
preset selects Custom; **SCALE TOOLS** opens slot/save/load and MIDI facilities.
ROUTES selects Scale, Key, and Transpose independently for each output. The standard scales use a piano-key preview: included keys are filled
cyan, with dark note labels. Excluded natural keys are dim and excluded sharps
are dark. Key fills and labels change together at a video-frame boundary. The
key outlines are cached, so switching pages does not require drawing them again.
Custom patterns retain their exact degrees and explicit octave span, including
empty octaves. Up to two keyboards are visible together; VIEW selects the first
visible octave. Key navigation stays within that visible pair; use VIEW to
choose another pair before editing it. A single keyboard is centered vertically. 24 EDO also displays the notes 50 cents above the
ordinary semitones, marked `+`. Mapping changes how input voltages choose these
notes, not which notes belong to the scale. Custom NOTES remains a C-based
interval pattern; the selected key and transpose are applied by the route.
TOOLS OCT selects the numbered octave for CLEAR OCT and FILL OCT.
LEARN BASE arms MIDI editing: press any note to set the base to the C of its
MIDI octave. That press only sets the base. Subsequent fresh presses toggle
notes in their corresponding pattern octave and reveal it automatically.
Notes below the base or beyond OCTAVES are ignored. STOP MIDI ends editing; LEARN BASE starts a new learning session. The base defaults to MIDI note 48 (C3), remains
until reboot, and affects editing only; route Key, Transpose, and oscillator
calibration stay independent. Save the pattern to retain note edits. Dimmed controls and the
LOCKED footer identify edits unavailable while that output is running.

SCALES' **output** selector selects independent settings for OUT 0–3:
scale, mapping, octave count, and eight independent note masks. Input, musical Key, Transpose, and
oscillator 0 V note are set on ROUTES for that same selected output. Editing
intervals preserves the route's musical offsets.
Switching output recalls that output's settings in RAM without stopping playback.
NOTES edits/loads only the selected output's pattern. Pattern slots are reusable
copies: editing a channel does not modify a saved pattern or another channel.
ROUTES groups output/input, profile and 0 V note above the applied profile and
scale summary. APPLY PROFILE installs the selected RAM/slot profile; selecting
a new source alone does not apply it. The displayed profile name is explicitly
marked APPLIED, while an unapplied selection shows an apply-first prompt.
START/STOP, SCALES and SETUPS are grouped below the live feedback. Running route
settings are dimmed and identify themselves as LOCKED. Pitch/voltage readouts
are shown only while running; stopped-route fault/action messages remain visible.
SETUPS shows the current four-output configuration, including scale/key/transpose
and correction source, rather than suggesting it previews a saved slot. Loading
a setup leaves outputs off.

ROUTES **START/STOP starts/stops only the selected output**, using its own configuration.
Two outputs are calculated per 1 ms interrupt, giving each output a 500 Hz update
rate. Both batches use the same captured input readings, and all four staged
voltages are committed together at one DAC update boundary. Safety disables
remain immediate rather than waiting for a group commit.
Running settings are locked; channel selection and page navigation do not stop
outputs. An empty custom pattern cannot arm its lane.
Per-lane stale CV, missing ACK, and output faults stop that lane; scheduling
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
five cents, capped to a quarter of each adjacent interval for dense scales). Outside
a measured profile, routes continue using nominal 1 V/oct output after scale
quantization. Beyond the guarded -5..+8 V output range, quantized routes use the
nearest reachable scale note; continuous routes cap the nominal voltage. Clipped
input does not stop a route, and normal processing resumes when it returns.
Stale CV, output faults, and missed processing deadlines still stop the route. STOP commands 0 V, not an audio mute.
The tuner acquisition continues independently. Four output routes support
optional oscillator-profile correction; a trigger input is not implemented.
Routes share the renderer and pitch engine, with one immutable curve snapshot
per corrected output.
The scale math supports non-octave periods and fractional intervals. See
[SCALES.md](SCALES.md) for the offline Scala converter, explicit format limits,
and the remaining device-import/storage work. The converter does not yet
upload files to the module. Numerical table precision is 0.001 cent; nominal
DAC steps are 250 microvolts (0.3 cent at 1 V/oct), so table precision is not a
claim of analog output accuracy or distinguishability of arbitrarily close notes.

## Routing, correction and quantization

See [CONCURRENCY.md](CONCURRENCY.md) for the current assignment model and test plan.
ROUTES selects one of four route groups. A group takes exactly one CV input
and feeds any subset of OUT 0–3. Choose ROUTE and INPUT, then choose OUTPUT and
click ADD OUT or REMOVE OUT. Adding a stopped output transfers it from its
previous group; an active group's membership and input are locked. The summary
shows `IN n -> OUT ...`. Empty groups are allowed but cannot start.

Each member output keeps its own scale, musical key, transpose, 0 V note,
and oscillator profile. OUTPUT selects which member's settings/monitor are
shown; SCALES edits that physical output's intervals. Choose PROFILE NONE for
nominal voltage, RAM or SLOT 1–8 plus APPLY PROFILE for correction. Applying a
profile never starts playback. START/STOP controls the entire selected group.
All jacks are reserved together; failed starts roll back every member. If a
member stops on an output fault, the group stops and releases all its jacks.

TUNER is always read-only: all four inputs remain observable, including inputs
claimed by calibration or CV routes. One calibration/verification operation can
run alongside groups using other jacks. Assigned jacks are dimmed and skipped
in jack selectors. Stopped configurations do not reserve jacks. Independent
groups cannot share an input; fan-out belongs within a single group.
Profile flash access and setup recall require stopped outputs. SETUPS saves all
four groups and per-output settings, with every output stopped after recall.
Older saved setups migrate outputs sharing an input into one group (route number
matches that input), preserving each output's settings. 1–8 octave scales remain
supported, with one octave as the default.

Oscillator setup guidance for the future module help: at the lowest pitch-CV
voltage you intend to use, within both the oscillator's supported range and
Intono's output range, tune the oscillator to the lowest stable pitch you want
reproduced. For an oscillator that responds only to non-negative pitch CV, this
means setting that pitch at 0 V. Use TUNER to confirm reliable detection; tuning
below the measurable range does not add useful calibrated coverage. This places
the desired low note at the bottom of the available voltage range, but the
oscillator's tracking, upper frequency limit and usable voltage span still limit
the number of octaves. Centered tuning knobs are optional. Fully lowering the
knobs can provide a repeatable physical position, but is useful only if the
resulting pitch is stable, measurable and appropriate for the desired range.
Record coarse/fine/octave positions and keep them fixed after calibration.

A qualified pitch measured at 0 V is stored with each new profile. Applying it
sets that route's 0 V note to the nearest musical note: an oscillator near D3
uses D3 as its voltage reference. The route's musical Key and Transpose remain
as chosen by the user; calibration does not choose a musical key.
The exact measured pitch (including cents) anchors nominal fallback beyond the
curve; it does not offset the already measured correction twice. You may edit
the 0 V note afterward while stopped. Reapplying restores the profile reference.
Older profiles reuse an existing measured 0 V point. If none exists, binding
keeps the configured reference and musical key and reports that the measured reference is absent.
No zero-volt pitch is extrapolated. Updated profile records use TUCP version 5,
with the same size and legacy versions 1–4 still readable.

Curves are immutable per-output snapshots. Setup records save the correction
source and quantization enable, not curve contents; rebind after setup recall
or reboot. Legacy setups remain readable. Keep the oscillator tuning unchanged;
verify residual error if moving a curve to a different physical DAC output.

## Oscillator profiles

PROFILES provides eight saved slots inside INTONO's existing settings storage.
After calibration, select a slot and Save. Set `name pos` (1–24) and `letter`
to edit the name draft; a space removes trailing characters. Save replaces the
selected slot and confirms `SAVED SLOT n - READBACK OK` beneath the menu after
reading back and comparing the stored record. Settings/Save is not
required for profiles. Load validates and restores the curve, name, routing and
nominal 0 V note, confirming `LOADED SLOT n - OUTPUT OFF`; the active RAM profile
name, point count, and routing appear beneath that confirmation. It never starts
output. Empty/invalid slots leave the current
RAM profile untouched. Boot remains on INTONO without automatically loading or
enabling a profile. Settings/Reset preserves saved profiles.

To test persistence, save, reload the bitstream, select the same profile slot
and Load, then test VERIFY. Keep oscillator tuning and patching unchanged and
allow the oscillator to warm up: a saved curve cannot compensate for moving its
tuning knob or arbitrary temperature drift.
For Settings/Save, the save row shows `saved` for about two seconds. A failed write
shows `failed`; missing option storage shows `no flash`. These messages report
the save result, not merely the encoder click.

Display offers ARC and LINEAR. ARC shows four colored pitch markers. LINEAR shows
four simultaneous cents rulers, each with note, frequency and voltage readings.
Channel colors are orange, green, cyan and purple for inputs 0–3. The input
setting (now labeled `focus`) chooses the spiral detail readout,
not which inputs are acquired. Each cursor maps -50..+50 cents onto its ruler;
the center is the nearest note. Immutable ARC, LINEAR and circle-only images are prepared at boot in
three additional PSRAM cache slots. The two scanout buffers retain their existing
ownership; a needed tuner image is copied into the unused buffer in bounded
chunks, and CAL copies the circle template before drawing only its graph.
Pending page/view changes hide the previous background until the complete
replacement is published. ARC and LINEAR scan their immutable images directly,
so switching to either needs no background copy or redraw. Text and cursor
geometry switch with that background. CAL retains its measured response graph and visible controls;
profile/check panels, SCALES, ROUTES, OPTIONS and HELP use an atomic blank
backdrop without overwriting the retained graph or tuner background.

The production view uses the original normal/bold 9x15 font at native scale,
with 12x32 cell spacing, 40 visible columns and 22 rows. Control regions
retain their established positions on the 30-column logical layout; glyphs
are packed more tightly within those regions. This follows hardware
feedback that the doubled 14x20 trial still looked oversized. Lowercase labels are restored. The retained text-memory stride
and double-buffer ABI remain unchanged. Controls and centered status fields are
bounded for the circular viewport; firmware no longer enables the legacy small
pop-up menu. This first UX pass preserves the channel-linked scale editor and
existing slot/name controls; richer contextual library panels and independent
reusable scale editing remain follow-up work. Full help is deferred until before
the release candidate.

## Original detector (historical; code removed)

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
PYTHONPATH=src pdm intono build --hw r5
PYTHONPATH=src pdm intono_round build --hw r5
```

`intono` is the fixed, unrotated 1280x720 HDMI development target.
`intono_round` produces a separate `INTONO-ROUND` artifact for the fixed 720x720
production-panel target and compensates for the display's physical 90-degree
mounting. Keeping these as explicit artifacts prevents mutable bootloader video
state from selecting the wrong UI transform.

Both INTONO targets default to 192 kHz codec sampling for the 20 Hz–20 kHz
measurement target. This default is local to INTONO, not other bitstreams.
Building does not flash the archive; flashing is a separate operation.

The non-circular R5 build defaults to routing seed 18. After a gateware change,
run a full build and check both the 60 MHz CPU and 5× DVI clock timing reports,
then verify HDMI lock on hardware. `--fw-only` reuses the existing `top.bit` in
the build directory; use it only after that exact bitstream has been qualified.
A passing timing report alone does not establish HDMI lock, and a rebuild with
the same seed can produce a different bitstream, so keep the hardware-verified
archive when preparing a release.

The interface uses rounded outline tabs and action buttons, with a brighter
outline for the active page or focused action. Standard-scale piano keys have
subtly rounded corners; included notes retain their cyan fill. Native font size
and character spacing are unchanged.

SCALES and SCALE TOOLS display up to two stacked piano keyboards. One-octave
patterns show only one keyboard. Turn to focus a key (yellow lettering), click
to toggle it. OCTAVES sets the repeat length independently of note membership;
VIEW browses adjacent octaves; keyboard focus stops at the visible page edges. On
SCALE TOOLS, TOOLS OCT chooses the Clear/Fill target. Opening Scale Tools
from a conventional preset copies its intervals into a Custom pattern.
SCALES shows untransposed intervals. 24 EDO retains its separate half-semitone
grids and does not support twelve-key piano editing.

Short configuration fields use one row, such as INPUT: 1 and POLICY: AUTO.
Long values fall back to two rows, and profile names retain that layout. Font
size and spacing remain unchanged.

SETUPS shows the current configuration in two rows per output, with I/O and
scale above profile source and key/transpose/mapping. These summaries describe
current settings; select LOAD to read the chosen saved slot, with outputs off.


### Multi-octave intent clarified (October 1, 2026)

The user intends dàil-style multi-octave scale/chord/arpeggio programming, not
just a duplicated keyboard preview. Primary reference: [Instruō dàil manual](https://www.instruomodular.com/wp-content/uploads/2024/08/dail-Manual.pdf),
pages 3, 12 and 17. It describes programming notes spanning multiple octaves
via MIDI, natural distribution respecting pitch distances, and equal
distribution dividing the defined octave span evenly among selected notes.
The manual does not explicitly resolve pattern repetition or out-of-pattern
boundary behavior; do not infer exact parity from those descriptions alone.

Intono now stores one to eight independent octave masks and an explicit span,
defaulting to one. Custom patterns repeat every selected span, anchored to
C-relative interval zero before the route's key/transpose. Empty leading,
trailing and internal octaves retain their placement. Nearest/EQUAL mapping
operates on the complete pattern; EQUAL divides the entire span among degrees.
This specifies Intono's boundary/repetition behavior without claiming exact
dàil parity. MIDI Learn uses an absolute octave base established by any note through
LEARN BASE. Subsequent presses map into the independent pattern octaves.

TNP2 note records and TQS3 route setups store the span and all eight masks,
including hidden edits beyond a reduced span. TNP1 and TQS1/2 loads normalize
legacy empty halves exactly as the previous engine did, then infer span 1/2.
Keys/slots stay unchanged and oscillator profiles remain separate.

### Startup and selectors (October 1)

The startup view holds an outer circle, loading dots and INTONO / STARTING text
until the first complete page snapshot. Control outlines remain disabled until
that snapshot; selectors now use the same rounded borders as action buttons.
The current qualified image is `intono-ux-selectors-r5`; future firmware-only
builds must use this hardware rather than the previous stacked image.

### Background gaps and piano contrast (October 1)

Coordinated scanout clears unavailable background samples instead of holding the
last pixel across a memory gap. A deliberate-stall simulation verifies this case;
the reported occasional startup line still needs a physical retest. Selected
sharp keys use darker cyan than natural keys so chromatic keyboards remain legible.

Current qualified hardware: `intono-ux-gap-r5`, successfully flashed to #1 slot 1.

### Common circle and calibration feedback (October 1)

Routes, options, help and saved-item pages now retain the common circular edge
using the existing immutable circle image. CAL voltage labels span its horizontal
axis with endpoint/midpoint values. During acquisition its footer shows the current
voltage and number of collected points; SEARCHING FOR TONE identifies the quiet
part of a sweep. CHECKS DISAGREE means the broad check and later repetitions at
the same target voltage did not agree enough to trust automatic improvement.

Current qualified/flashed image: `intono-ux-circle-r5`. VIDEO BUFFER_GAPS in debug
status will help distinguish missing background samples from the still-unresolved
brief horizontal line. The diagnostic saturates at 255 episodes after the reader
has received its first sample; it does not change acquisition or output timing.

### Output monitor and tuner feedback (October 1, 2026)

ROUTES groups the applied profile, current output pitch, and live input/output
voltages below OUTPUT MONITOR. Scale, key, and transpose remain in their
editable controls above, avoiding a second summary of the same settings.
ARC tuner shows NO SIGNAL when the focused input has no valid pitch; its
cents readout turns green and bold within ±2 cents. This is a visual tuning
cue and does not change detection, calibration, or quantization tolerances.

### Route overview and MIDI transposition

Open **ROUTES → ALL ROUTES** to see each physical output's group, input, profile,
scale/key, and run state together. This also contains setup SAVE/LOAD.
**MIDI ROUTE** selects a logical route's MIDI channel (OFF by default), zero note
(C4 by default), and release behavior (HOLD by default, optionally ZERO). Notes
transpose every output in that group relative to the zero note; RESET clears the
current transpose. Save a setup to retain these settings. Current MIDI offsets
and running state are not saved. Scale MIDI learning temporarily pauses route
transposition. See [October 2 code review](CODE_REVIEW_2026-10-02.md) for validation
and remaining hardware checks.

### Serial diagnostics

Normal builds retain calibration pass timing/progress, stack watermark and video
health reports. Detailed raw CV snapshots, scan command/acknowledgement dumps,
frame ages, tuner/verification evidence, EEPROM/boot reports and boot markers are
opt-in: set `TILIQUA_INTONO_VERBOSE_DIAGNOSTICS=1` when building firmware. The
normal default is unset or `0`. Both modes drain serial output without blocking.
This flag is independent of `TILIQUA_INTONO_NSDF_TRACE`; retain its default
`continuous-quiet` for production pitch acquisition. Wave/pair experiments and
repeat diagnostics remain independently opt-in. Output watchdogs and acquisition
scheduling are always active.

### Mapping belongs to the output route

Choose `MAP: NEAREST` or `MAP: EQUAL` on Routes for the selected output.
Nearest is the default. Mapping is saved with route setups, alongside the key
and transpose, and remains unchanged when editing or loading a scale. The
Scales page now defines only intervals and octave span. Saved scale records
already contain only masks and span, so their format is unchanged. The hidden
legacy editor mapping option remains solely to preserve serialized option keys;
it is no longer used by runtime playback or scale editing.

### Factory scale collection

Twelve common factory interval patterns are available: Chromatic, Major,
Natural Minor, Major Pentatonic, Minor Pentatonic, Dorian, Mixolydian, Phrygian,
Lydian, Harmonic Minor, Melodic Minor and Blues. Melodic Minor uses the fixed
ascending/jazz form in both input directions; Blues is the six-note minor blues
pattern. Display labels abbreviate longer names to fit one-row route controls.
The existing 24 EDO option is retained as an additional microtonal option.
All old preset IDs (0..6, including Custom) remain unchanged; new presets append
IDs 7..13. Eight user scale slots remain separate, with interval snapshots
loaded using the existing saved-scale selector. Editing a factory keyboard
creates a custom interval pattern without changing the factory table.

Reference: [Seaside Modular Proteus manual](https://seaside.digital/manuals/ProteusManual.pdf),
scale selection on page 9. This is a practical common set, not a measured popularity
ranking. Proteus supplies the core set; Lydian, melodic minor and blues extend it.
