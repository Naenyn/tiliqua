# STREZO user guide

STREZO is a ten-band linked-stereo resonant filterbank. Its left and right
resonators share controls but retain independent state, preserving stereo
motion through the wet path. Four groups provide flexible output routing, and
the CROSS page routes feedback between the left and right group networks.

STREZO can move from subtle stereo animation to unstable resonant feedback.
Begin with modest RESONANCE, FEEDBACK, and CROSS settings and monitor at a safe
level.

## Hardware and connections

STREZO uses all four Eurorack inputs and outputs:

- **IN0..IN3** are independently assigned to LEFT, RIGHT, or CV.
- LEFT and RIGHT inputs feed separate resonator state while sharing the visible
  band, frequency, motion, and safety controls.
- CV inputs modulate feedback, resonance, drive, or G1 through G4.
- **OUT0..OUT3** each select a left or right source side and independently mix
  G1 through G4 plus that side's dry input.

HDMI video is required for editing the stereo routing and feedback matrices.
Audio continues to run independently after startup.

## Basic controls

1. Turn the encoder to move the selection outline.
2. Click to enter **EDIT**.
3. Turn to change the selected value.
4. Click again to apply the value and return to **NAV**.

Continuous numeric controls use progressive acceleration. Slow turns change
one step at a time; sustained fast turns in one direction ramp smoothly through
larger steps. Direction changes and discrete choices always begin with a single
step, so the encoder feels consistent throughout the REZO family.

Switches and **SAVE DEFAULT** act immediately when clicked. Select the
page-name chip beside **PAGE** to change pages.

Pages follow the sound-design path **BANK, INPUT, BANDS, GROUPS, FEEDBACK,
CROSS, OUTPUT, OPTIONS**.

### Reading the meters

The four curved **OUT** meters show the final signals sent to OUT0 through
OUT3. Their upper segment changes to the palette's selection color as the
signal approaches full scale. A held cap in the modulation/accent color marks
clipping; in the NEON palette that clip color is cyan. The two lower-arc input
meters are described on the INPUT page.

### Display versions

STREZO is supplied for two displays:

- **Standard:** `1280x720p60`, with the native 720x720 interface centered in
  the widescreen raster.
- **Circular:** `720x720p60r2`, with the same interface rotated for the
  official panel mount.

Features, audio behavior, and saved state are identical. Use the build intended
for the connected display; the circular build is not a scaled widescreen mode.

## Startup and saved state

At startup STREZO loads the newest valid saved record from the active bitstream
slot, or uses its compiled factory state when no valid record exists. State is
applied before normal operation so routing never starts from a partial record.

**SAVE DEFAULT** is explicit and slot-local. Ordinary editing does not write
flash automatically. Because CROSS can restore a high-feedback patch, audition
the complete saved setup at a safe monitoring level before committing it.

## Signal flow

IN0 through IN3 may be assigned to the left audio mix, right audio mix, or CV.
The audio mixes excite independent left and right copies of the same ten
resonators.

```text
LEFT inputs  -> ten left resonators  -> G1..G4 -> MID/SIDE -> output routing
RIGHT inputs -> ten right resonators -> G1..G4 -> MID/SIDE -> output routing
                         ^                 |
                         +-- SAME/CROSS ---+
```

The ten user controls, frequency layout, band enables, group memberships, and
motion settings are shared by both sides. CROSS routing determines how group
feedback returns to the same or opposite side.

## BANK page

### PRESET and band levels

The shape presets change the ten natural band levels without changing center
frequencies, enables, groups, feedback sources, or output routing.

| Preset | Result |
|---|---|
| ALL | Raises every band |
| ODD | Raises alternating odd-position bands |
| EVEN | Raises alternating even-position bands |
| LOW | Raises the lowest four bands |
| MID | Raises the middle four bands |
| HI | Raises the highest four bands |
| ZERO | Returns every band level to zero |

Each vertical band control is bipolar. The center line is zero; positions
above and below it use opposite polarity. Selecting a band displays its center
frequency beside **FREQ:**. A disabled band retains a dim frame but cannot be
adjusted here.

### DRIVE, RESONANCE, and FEEDBACK

- **DRIVE** controls how strongly the inputs excite the resonators.
- **RESONANCE** emphasizes and lengthens ringing at each center frequency.
- **FEEDBACK** controls the overall level returned by the bands selected on
  the FEEDBACK page.

The display distinguishes saved positions from CV-modulated effective values.

## FEEDBACK page

The ten switches select which enabled resonators contribute to the feedback
tap. The BANK page's FEEDBACK control sets its overall amount.

- **KNEE** sets the level where soft limiting begins. Below it, the return is
  unchanged; above it, progressively stronger compression bends the signal
  toward CEILING.
- **CEILING** sets the hard final feedback-loop limit. Its fader colors the
  span from KNEE to CEILING to show the active soft-limiting region.
- **DAMPING** selects OFF, LIGHT, MED, HEAVY, or MAX resonance restraint as
  feedback increases.

KNEE and CEILING may meet for hard limiting with no soft region. Raising KNEE
past CEILING raises CEILING too; lowering CEILING past KNEE lowers KNEE too.

These controls make feedback easier to manage, but they intentionally do not
remove the possibility of instability at extreme settings.

## INPUT page

Each jack can be assigned as **LEFT**, **RIGHT**, or **CV**.

For a LEFT or RIGHT audio input, **VALUE** sets its gain and the signal joins
the corresponding stereo-side input mix. The activity line on VALUE shows that
jack after its gain.

The curved **L IN R** meters in the bottom arc show those completed left and
right input mixes after all VALUE gains and summing, immediately before DRIVE
and feedback enter the filter banks. Each meter grows outward from the center.
The fixed marker is nominal 0 dB (5 V peak); the short outer section is ADC
headroom up to 8.192 V peak. A clip lamp at the outer tip indicates that the
unclamped sum exceeded the input bus, even though the signal sent onward was
safely clamped. Clip lamps use the palette's modulation/accent color (cyan in
NEON).

For a CV input:

- **VALUE** selects FB, RES, DRV, or group G1 through G4.
- **DEPTH** is a bipolar attenuverter. Its center is zero modulation; the two
  directions apply opposite CV polarity.

Group CV changes the effective levels of every enabled band assigned to that
group. The line under each depth control is a live bipolar input indicator.

## GROUPS page

The GROUPS page assigns each enabled band to G1, G2, G3, G4, or combinations
of those groups. Select a band column, click, and turn through its membership
patterns. A disabled band leaves dim ghost rails and cannot be edited here.

Groups are used by three parts of STREZO:

- group CV modulation;
- the four-output routing matrix;
- the SAME/CROSS feedback matrix.

## OUTPUT page

Each output row has independent unipolar sends from **G1**, **G2**, **G3**,
**G4**, and **DRY**. A zero send contributes nothing and the maximum setting is
unity gain. Raise several sends to mix groups at one output, or build four
different views of the stereo filterbank.

The **L** or **R** chip on each output row selects which stereo side supplies
all five sends on that row. DRY adds the corresponding unfiltered input path.

Selecting an OUT row header adjusts all four wet group sends together;
**OPTIONS > ROW DRY** chooses whether DRY follows that row edit. Selecting a
G1-G4 or DRY column header adjusts that source across all four outputs. ROW DRY
does not change column-header behavior.

The shared **MID** and **SIDE** controls below the matrix reshape only the wet
G1-G4 signals after the feedback taps and before output routing. DRY bypasses
this stage, so the original stereo input can always be mixed back unchanged.
Both controls run from 0 to 128, with 64 as exact unity. The fixed tick on
each fader marks that 1.0x position:

- **MID** changes the common center component. Raise it to make the newly
  shared stereo center more pronounced; lower it to leave more difference
  information.
- **SIDE** changes the left/right difference. Lower it to narrow the wet image;
  raise it to widen the wet image.

MID 64 / SIDE 0 produces centered mono wet output. MID 0 / SIDE 64 removes
common center content. Values above 64 provide up to 2x gain in the selected
component and may reach the output limit sooner.

## BANDS page

### Frequency layouts

| Layout | Center frequencies in Hz |
|---|---|
| LEGACY | 29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000 |
| OCTAVE | 31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000 |
| PERCEPT | 50, 150, 300, 500, 770, 1150, 1700, 2700, 5300, 12000 |
| USER | The current manually edited layout |

Loading a factory layout replaces all ten center frequencies. Editing an
individual **SET FREQ** value automatically changes the displayed layout to
USER. The frequency choices use a fine logarithmic grid.

The **ENABLE** row includes or removes each resonator from audio processing.
Disabled bands may still have their frequencies configured before being
enabled again.

### MOTION

MOTION adds shared modulation to the band frequencies.

- **LFO SHAPE** selects OFF, TRIANGLE, or RANDOM.
- **RATE HZ** sets the motion rate from 0.0 through 20.0 Hz.
- **PHASE** offsets the periodic source in degrees. It is dimmed, blank, and
  skipped by navigation for RANDOM because random motion has no useful phase.
- **DEPTH** sets the modulation amount.

The bipolar line directly beneath DEPTH shows the post-depth modulation. It is
blank at zero depth and, at full depth, can travel from the center to either
end of the full fader range.

## CROSS page

The CROSS page controls feedback between the four groups and the two stereo
sides. Treat its faders as feedback coefficients, not as an ordinary output
crossfader.

### LAYOUT

| Layout | Routing |
|---|---|
| GLOBAL | Uses the global SAME and CROSS paths without an editable matrix |
| DIAGONAL | Each group feeds the matching group |
| ROTATE | Each group feeds the next group |
| MIRROR | G1 feeds G4, G2 feeds G3, and vice versa |
| ALL | Every source feeds every destination at a reduced level |
| USER | Uses the editable 4-by-4 matrix |

Selecting a factory layout loads its routing pattern. Editing an individual
matrix cell changes the layout to USER. Matrix cells range from no send to full
send and fill their frames completely at maximum.

The **FROM** row headers adjust all four destinations for one source group.
The **TO** column headers adjust one destination from all four source groups.
Either whole-row or whole-column edit changes the layout to USER.

### SAME and CROSS

- **SAME** controls the feedback returned to the same stereo side.
- **CROSS** controls the feedback sent to the opposite stereo side.

CROSS closes a two-channel round trip, so its audible buildup depends strongly
on the input, band levels, matrix, RESONANCE, FEEDBACK, and SAME. The upper end
is intentionally capable of unstable and abrasive results.

## OPTIONS page

Navigation follows the visible top-to-bottom order: PAGE, PALETTE, ROW DRY,
SAVE DEFAULT, then CROSS CURVE.

### STATE AND DISPLAY

- **PALETTE** selects LCD, AMBER, CYAN, GREEN, VIOLET, EMBER, NEON, or AZURE.
- **ROW DRY** chooses whether an OUTPUT row edit changes DRY along with G1-G4.
  INCLUDE adjusts all five sends; EXCLUDE adjusts only the four wet group
  sends and leaves DRY untouched.
- **SAVE DEFAULT** stores the complete STREZO state in the current bitstream
  slot. The button reports SAVING, SAVED, ERROR, or NO SLOT.

### ADVANCED: CROSS CURVE

- **LINEAR** maps the CROSS fader directly to the feedback coefficient.
- **FINE** rises later, expanding the stable low and middle range while keeping
  the strongest cross-coupling in the final part of the fader. Both curves
  retain exact zero and maximum endpoints.

The curve changes only the response of the CROSS control. It does not change
SAME or rewrite the saved CROSS position.

## Saving and startup

SAVE DEFAULT stores band levels, frequencies, enables, groups, input roles and
depths, output sends, feedback safety settings, CROSS layout and matrix, SAME
and CROSS positions, CROSS curve, MID/SIDE gains, motion settings, palette, the
ROW DRY preference, and the selected page state needed to restore the patch.
Changes are not saved automatically.

## A practical first patch

1. Patch a source to IN0 and assign it LEFT; assign another source to RIGHT if
   desired.
2. Load OCTAVE and ALL, then lower DRIVE, RESONANCE, and FEEDBACK.
3. Assign low and high bands to different groups and route those groups to
   different outputs.
4. On CROSS, begin with GLOBAL, SAME at maximum, and CROSS at zero.
5. Raise FEEDBACK modestly, then increase CROSS slowly while monitoring level.
6. Compare LINEAR and FINE under OPTIONS > ADVANCED.
7. Add TRIANGLE motion at low DEPTH.
8. Save the complete setup only after it behaves safely with the intended
   inputs and monitoring level.
