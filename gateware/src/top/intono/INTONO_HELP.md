# Intono help

This is the editable source for the on-device Help page. Each section is a topic;
paragraphs are wrapped to the display width by `help_content.py`.

<!-- HELP START -->
## START
Turn the encoder to select a control. Click to edit its value, turn to change it, then click to finish. Action buttons work with one click.

PAGE means you are choosing a page. NAV means you are selecting its controls. EDIT means you are changing a value. From a top page selector, turn clockwise to enter its controls. From OPTIONS or HELP at the bottom, turn counterclockwise to enter from below. Turn back toward the page selector to leave.

Hold the encoder to return to the bootloader.

Choose TOPIC here for help on a particular page. Choose SCROLL to read further. Changing topics returns to the beginning.
## TUNER
The tuner measures pitch and signal level on available audio inputs. Patch an oscillator's audio output into an IN jack.

ARC places notes around the spiral and octaves along it. Select the IN numbers to choose the channel whose details appear at the right.

LINEAR shows all four channels together. A centered marker is in tune; left is flat and right is sharp. The scale is in cents, with 100 cents per semitone.

PITCH shows the nearest note and octave, then the cents offset. FREQUENCY is in Hz. Vrms and Vpp describe signal level. NO SIGNAL means there is no usable pitch reading.

VIEW switches between ARC and LINEAR. The A4 reference is set in OPTIONS.

REFERENCE CV supplies one free output with a steady tuning voltage. Select OUTPUT, VOLTAGE and STEP, then ENABLE. STEP offers 1 V or 10 mV adjustments. BACK returns to the tuner while keeping it on; DISABLE or leaving TUNER turns it off and releases the jack.
## CAL
Calibration measures your oscillator's pitch-voltage response so a route can correct its tuning. It does not adjust the oscillator's internal trimmers.

Let an analog oscillator warm up and settle first; allow about 10-20 minutes, or follow its manual. Set audio-rate mode with a steady tone. Roughly 100-500 Hz at zero pitch CV is a useful starting point, not a required note.

Choose a free IN and OUT. Patch that OUT directly to V/oct and a single oscillator audio output directly to that IN. Use normal V/oct sensitivity. Disconnect FM, sync, vibrato and other pitch modulation; disable internal modulation or detune where possible.

Prefer a clean sine or triangle. A steady saw or square can work, but rich waveforms may be harder to measure. Avoid heavy folding, narrow pulses, noise, chords and effects. Check the tuner for a steady note before scanning.

Keep tuning, octave, tracking and modulation settings unchanged during and after calibration. Tune before the scan, not during it. Changing settings that affect pitch response calls for a new profile.

AUTO is the usual starting policy. PRECISION demands tighter results from a stable oscillator. FORGIVING allows more natural variation; it does not fix a bad patch. FAST takes fewer stability samples for a quicker first pass, with less averaging.

SCAN finds the usable range, measures it, then checks and may refine the curve. Allow several minutes: recent rack runs took about 4-7 minutes. Low tones, gaps and unstable readings can take longer; there is no fixed total run time. SEARCHING FOR TONE is expected near the low end. STOP interrupts; RESUME appears when available.

PITCH plots notes against voltage; ERROR shows error in cents. The dashed guide is nominal response. Review the result before ACCEPT. CHECKS DISAGREE means independent checks found different errors; check patch and stability and consider another scan.

ACCEPT keeps the result in RAM. PROFILES lets you name and save it. DISCARD keeps the previous profile. Use a saved profile for the same oscillator and tuning setup; use NONE for nominal CV without correction. A profile cannot correct a range the oscillator could not reliably produce.
## CAL PROFILES
SLOT chooses one of eight saved oscillator profiles. Browsing shows what is stored there without loading it or changing the profile in RAM.

LOAD copies the chosen saved profile into RAM. SAVE writes the current RAM profile to the chosen slot. Saving to an occupied slot replaces that profile.

Use CURSOR and the character control to edit the profile name before saving. Give profiles names that identify the oscillator and its tuning setup. Keep separate profiles for different oscillator settings; recall one only when that setup is restored.

A route's output/profile controls choose the saved correction profile to apply. NONE uses nominal pitch voltage instead.

Calibration profiles, user scales and route configs have separate slots. A profile in RAM is not saved until you use SAVE.
## SCALES
Scales store intervals, not a musical root. Choose the root key and mapping when applying a scale to a route output.

OUTPUT chooses the working scale to edit. PRESET chooses a factory pattern or CUSTOM. Only this preset list wraps from its last item back to its first.

White and black keys show the familiar keyboard layout. Blue keys are included in the scale. The yellow outline marks the key selected for editing. Click that key to include or exclude it.

OCTAVES sets a repeating pattern from one to eight octaves. One is the default. VIEW chooses which octaves are visible; encoder navigation stays within that view.

SLOT chooses one of eight user scale slots. SAVE stores your working intervals there. LOAD replaces the working scale with that slot's saved intervals. Unsaved edits are lost on reboot.

24 EDO divides an octave into 24 equal steps, including pitches between the normal keyboard notes.
## SCALE TOOLS
Tools work on the same intervals shown on SCALES. BACK returns to that page.

TOOLS OCT chooses the octave affected by CLEAR OCT or FILL OCT. Clearing excludes all its notes; filling includes all twelve keyboard intervals.

MIDI is supported through the 3.5 mm MIDI input only, not USB-C.

LEARN BASE waits for any MIDI note. That note's octave becomes the first editing octave. For example, playing E3 sets MIDI BASE to C3. The first note sets the base without changing an interval.

After learning, play a note to toggle its interval. Release it before playing it again to toggle it again. Notes outside the configured octave range are ignored. The view follows the octave being edited.

The first note also selects the MIDI channel for that learning session. STOP MIDI ends learning. SAVE keeps your edited scale in the selected user slot.
## ROUTES
A route takes one CV input to one or more outputs. Each output can have its own scale, key, mapping, transpose and oscillator profile.

Select a route card to see its details. Click to open its flow diagram. An empty route starts with ADD OUTPUT. Click a diagram section to open its settings; DONE returns to the diagram.

Configured jacks are reserved immediately, even while stopped. Dim jacks belong to another route or calibration and cannot be selected. A star marks a jack assigned to this route.

Removing an output releases its jack. Removing the last output also releases the route's input. One input cannot belong to two routes.

In PITCH, NEAREST picks the closest allowed pitch. EQUAL gives each allowed interval an equal share of the input range. KEY selects the root and TRANSPOSE shifts the result.

LOAD USER SCALE applies intervals from a saved user slot. PROFILE chooses oscillator correction; NONE uses nominal CV. 0V NOTE is the pitch represented by zero input volts.

START and STOP control the selected route. The small bars show recent output pitch history. BACK returns to the overview. CONFIGS saves or loads the complete routing arrangement.
## MIDI TRANSPOSE
MIDI uses the 3.5 mm MIDI input only; USB-C MIDI is not supported.

MIDI transpose is shared by all outputs of a route, but configured separately for each route.

CHANNEL enables a MIDI channel from 1 to 16. OFF disables MIDI transpose. Routes with different channels can be transposed independently by one MIDI source.

BASE NOTE is the note that means no transposition. The default is C4. Notes above it transpose up; notes below it transpose down, by their distance in semitones.

LEARN BASE captures the next note on the selected channel as the base note.

LATCH keeps the last transposition after release. RESET ON RELEASE returns to no MIDI transposition when the controlling note is released. RESET TRANSPOSE clears the current MIDI offset immediately.

Scale learning and route transpose can share a MIDI channel. Stop routes while learning a scale if you do not want those notes to transpose them too.
## CONFIGS
Each of eight config slots stores all four routes, their output settings and their MIDI transpose settings.

SLOT chooses the destination or source. SAVE CONFIG replaces that slot with the current arrangement. LOAD CONFIG restores the saved arrangement with outputs stopped. START the routes you want to run.

The summary lists each route's input and outputs. MIDI TRANSPOSE opens settings for the selected route. BACK returns to the route overview.

Conflicting assignments are not silently taken from another route. Read the warning and use its route shortcut to inspect the owner, then change or release the assignment before retrying.

Configs are separate from calibration profile and user scale slots. Saving a config does not save an unsaved calibration scan or scale edit.
## OPTIONS
A4 REF sets the tuning reference, normally 440 Hz.

SAVE PREFERENCES stores the reference, tuner view and selected input, and calibration input, output, 0V note, policy and graph choice.

RESET PREFERENCES restores those settings to their defaults. It does not erase saved oscillator profiles, user scales or route configs.

Stop outputs and calibration before a flash storage operation when prompted. User profiles, scales and configs are saved with their own SAVE controls.
<!-- HELP END -->

## Guidance sources (not shown on the display)

- Warm-up guidance: [Intellijel oscillator calibration guide](https://intellijel.zendesk.com/hc/en-us/articles/115000914288-How-to-calibrate-the-1V-OCT-tracking-of-an-Intellijel-analog-oscillator). Intono does not ask users to adjust internal trimmers.
- Starting frequency and unchanged tuning relationship: `CALIBRATION.md`; waveform behavior: `OSCILLATOR_QUALIFICATION.md`.
- Approximate 4-7 minute examples and no total-run deadline: `AUTO_CALIBRATION.md`. These are observations, not promised completion times.
