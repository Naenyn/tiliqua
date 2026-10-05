# Intono help

This is the editable source for the on-device Help page. Each section is a topic;
paragraphs are wrapped to the display width by `help_content.py`.

<!-- HELP START -->
## START
Turn the encoder to select a control. Click to edit its value, turn to change it, then click to finish. Action buttons work with one click.

PAGE means you are choosing a page. NAV means you are selecting its controls. EDIT means you are changing a value. Turn back to the page selector to choose another page.

Hold the encoder to return to the bootloader.

Choose TOPIC here for help on a particular page. Choose SCROLL to read further. Changing topics returns to the beginning.
## TUNER
The tuner measures pitch and signal level on available audio inputs. Patch an oscillator's audio output into an IN jack.

ARC places notes around the spiral and octaves along it. Select the IN numbers to choose the channel whose details appear at the right.

LINEAR shows all four channels together. A centered marker is in tune; left is flat and right is sharp. The scale is in cents, with 100 cents per semitone.

PITCH shows the nearest note and octave, then the cents offset. FREQUENCY is in Hz. Vrms and Vpp describe signal level. NO SIGNAL means there is no usable pitch reading.

VIEW switches between ARC and LINEAR. The A4 reference is set in OPTIONS.
## CAL
Calibration measures how your oscillator responds to pitch voltage so a route can correct its tuning.

Choose a free IN and OUT. Patch that OUT to the oscillator's V/oct input and its audio output directly to that IN. Remove other pitch modulation and leave its tuning controls steady.

SCAN starts the measurement. SEARCHING FOR TONE can take longer at low or negative voltages. STOP interrupts the scan; RESUME is offered when it can continue.

AUTO is the normal policy. PRECISION requires stricter results. FORGIVING tolerates more variation. FAST uses fewer stability samples.

PITCH plots measured notes against output voltage. ERROR shows pitch error in cents. The dashed guide is the nominal response.

Review the result before ACCEPT. CHECKS DISAGREE means the independent checks found different errors; check the patch and oscillator stability and consider another scan.

ACCEPT keeps the result in RAM. Use PROFILES to save it for later. DISCARD rejects the result.
## CAL PROFILES
SLOT chooses one of eight saved oscillator profiles. Browsing shows what is stored there without loading it or changing the profile in RAM.

LOAD copies the chosen saved profile into RAM. SAVE writes the current RAM profile to the chosen slot. Saving to an occupied slot replaces that profile.

Use CURSOR and the character control to edit the profile name before saving. Give profiles names that identify the oscillator and its settings.

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
