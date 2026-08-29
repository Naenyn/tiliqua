# REZO user guide

REZO is a ten-band resonant filterbank with two ways to use the same resonator
core:

- **BANK** gives direct control over the level of every band.
- **FILTER** combines the ten bands into low-pass, high-pass, band-pass, or
  notch responses.

This guide describes BANK completely first, then explains what changes in
FILTER.

## Hardware and connections

REZO uses all four Eurorack inputs and outputs:

- **IN0..IN3** are independently assigned to AUDIO or CV on the INPUT page.
- AUDIO-role inputs are gain-controlled and mixed to the shared mono resonator
  input.
- CV-role inputs modulate continuous parameters or, in FILTER mode, feed the
  modulation matrix.
- **OUT0..OUT3** are independent mixes of G1 through G4 plus the dry mono input.

HDMI video is required for editing. Audio continues to run independently once
the bitstream has started, but the display is the only complete view of page,
selection, routing, and save status.

## Basic controls

REZO uses the encoder for both navigation and editing.

1. Turn the encoder to move the selection outline.
2. Click the encoder to enter **EDIT**.
3. Turn to change the selected value.
4. Click again to apply the value and return to **NAV**.

Continuous numeric controls use progressive acceleration: a slow turn changes
one step at a time, while sustained fast turns in one direction ramp smoothly
through larger steps. Direction changes and discrete choices always begin with
a single step.

Enable switches, feedback-source switches, and **SAVE DEFAULT** act
immediately when clicked. They do not require a separate edit step.

To change pages, select the page-name chip beside **PAGE**, click, and turn. On
the main page, navigation proceeds PAGE, then PRESET, then MODE. Select MODE to
switch between BANK and FILTER.

### Display versions

REZO is supplied for two displays:

- **Standard:** `1280x720p60`, with the native 720x720 interface centered in
  the widescreen raster.
- **Circular:** `720x720p60r2`, with the same interface rotated for the
  official panel mount.

Controls, audio behavior, and saved state are identical. Use the build intended
for the connected display; the circular build is not a scaled widescreen mode.

## Startup and saved state

At startup REZO checks the active bitstream slot for the newest valid saved
record. Audio remains muted until that record—or the compiled factory state—has
been applied completely. A missing or invalid record therefore returns to safe
defaults rather than partially restoring a patch.

**SAVE DEFAULT** is explicit and slot-local. Editing a control does not write
flash automatically, and moving the bitstream to another slot does not move its
saved record with it.

## Understanding the bands

The ten bands are ten parallel band-pass resonators. The frequency assigned to
a band is its **center frequency**, not the beginning or end of a rigid
frequency range. Each resonator also responds to frequencies around its center.
The bands overlap, and the global resonance setting affects how broad or narrow
their responses are.

Disabling a band removes that resonator from the BANK mix. Its frequency area
is not reassigned: neighboring bands do not become wider to fill the gap.
Disabled bands are shown as dim empty frames or ghost rails on other BANK
pages.

## BANK mode

BANK is the direct filterbank mode. Audio-role inputs are mixed to mono, sent
through all enabled resonators, divided into groups, and then mixed to the four
outputs.

```text
AUDIO inputs -> resonator bands -> groups -> output sends -> OUT0..OUT3
                         |
                         +-> selected bands feed the feedback loop
```

### BANK main page

#### PRESET

The shape presets set the ten band levels. They do not change band frequencies,
group assignments, or routing.

| Preset | Result |
|---|---|
| ALL | Raises every band |
| ODD | Raises alternating odd-position bands |
| EVEN | Raises alternating even-position bands |
| LOW | Raises the lowest four bands |
| MID | Raises the middle four bands |
| HI | Raises the highest four bands |
| ZERO | Returns every band level to zero |

Select **PRESET**, click, turn to a name, then click to apply it.

#### Band levels

Each vertical control is bipolar. The center line is zero; values above and
below it use opposite polarity. Opposite-polarity bands can cancel or reinforce
each other in useful ways because the resonators overlap.

Selecting a band displays its center frequency beside **FREQ:**. A disabled
band keeps a dim frame but cannot be adjusted from this page.

#### DRIVE, RES, and FB

- **DRIVE** controls how strongly the input excites the resonators. More drive
  can make the bank denser and more aggressive.
- **RES** controls resonance. Higher settings emphasize each center frequency
  more strongly and allow longer ringing.
- **FB** controls the amount of the selected band mix returned to the input of
  the resonators. Increase it carefully; high resonance and feedback interact.

The display distinguishes a control's saved/base position from modulation when
CV changes its effective value.

### BANDS page

The BANDS page configures the resonators themselves. It is available in both
BANK and FILTER so their shared center frequencies can be edited without
switching modes.

#### Frequency layouts

| Layout | Center frequencies in Hz |
|---|---|
| LEGACY | 29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000 |
| OCTAVE | 31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000 |
| PERCEPT | 50, 150, 300, 500, 770, 1150, 1700, 2700, 5300, 12000 |
| USER | The current manually edited layout |

Select **PRESET**, click, choose a layout, and click again to load it. Loading a
factory layout replaces all ten current center frequencies.

USER is the current working layout rather than a second hidden copy. Editing
any individual frequency automatically changes the displayed layout to USER.

#### Enabling bands

The **ENABLE** row contains one switch for each band. Click a switch to include
or remove that resonator from BANK audio processing. A disabled band can still
be configured on the BANDS page before it is enabled again.

#### Editing a frequency

Select one of the ten **SET FREQ** buttons, click, turn to the desired value,
then click to apply it. The exact value is displayed in Hz.

The available values form a fine logarithmic grid rather than a continuous
range. Slow encoder turns move one position for precise adjustment; a sequence
of fast turns moves eight positions at a time.

### INPUT page

Each of IN0 through IN3 can be assigned as **AUDIO** or **CV** in BANK mode.

For an AUDIO input:

- **MODE** selects AUDIO.
- **VALUE** sets its input gain.
- The signal joins the mono input mix feeding the resonators.
- The activity line is bounded by the VALUE lane. A bright mark at its right
  edge is held briefly when the input mix reaches full scale, making overloads
  visible without allowing the meter to spill into adjacent UI elements.

For a CV input:

- **MODE** selects CV.
- **VALUE** selects the destination: feedback, resonance, drive, or group
  G1 through G4.
- **DEPTH** is a bipolar attenuverter. The center is no modulation; either side
  applies the CV with opposite polarity.

Group CV changes the effective levels of every band assigned to that group.

### GROUPS page

The GROUPS page assigns each band to G1, G2, G3, G4, or combinations of those
groups. Select a band column, click, and turn through the assignment patterns.
The pattern changes one membership at a time.

Groups serve two purposes:

- A BANK CV input can modulate all bands in one group.
- The OUTPUT page can mix each group independently to each output.

A disabled band is silent and cannot be edited here. Its four possible group
positions remain visible as dim ghost rails.

### OUTPUT page

Each output has independent, unipolar send levels from **GRP1**, **GRP2**,
**GRP3**, **GRP4**, and **DRY**.

- Raise more than one group to mix them at an output.
- Use different combinations to create four related filterbank outputs.
- DRY adds the unfiltered mono AUDIO-input mix.
- A send at zero contributes nothing; its maximum setting is unity gain.

The BANK and FILTER output-send settings are stored separately.

### FEEDBACK page

The ten band switches choose which resonators feed the shared feedback loop.
Click a band to include or exclude it. These switches shape the feedback signal;
the **AMOUNT** control sets its overall level. BANK and FILTER retain
independent amounts, so FILTER begins at zero feedback even when BANK feedback
is already raised.

The three safety controls shape and constrain the returning signal:

- **KNEE** sets the level where soft limiting begins.
- **CEIL** sets the maximum allowed feedback-loop level.
- **DAMP** controls how strongly increasing feedback restrains resonance.
  Higher settings are more conservative.

Start with modest FB and RES settings, especially when several bands feed the
loop. KNEE and CEIL reduce runaway behavior, but they do not make every extreme
setting quiet. With DRIVE, RES, and FB all near maximum—especially with a low
KNEE, high CEIL, and light DAMP—the output can become harsh, digitally clipped,
and noisy. This is an intentional overload region rather than an additional
sound-safety range. Reduce DRIVE, RES, or FB to return to normal operation.

### OPTIONS page

#### PALETTE

Choose among LCD, AMBER, CYAN, GREEN, and VIOLET display palettes.

#### SAVE DEFAULT

Click **SAVE DEFAULT** once to store the complete REZO state for the current
bitstream slot. The button reports SAVING, SAVED, ERROR, or NO SLOT.

Saving includes both modes, band frequencies and enables, input assignments,
group membership, feedback settings, output sends, filter modulation, and the
palette. Changes are not saved automatically.

## FILTER mode

FILTER uses the same ten resonators but generates their gains from a familiar
filter shape instead of using the ten manual BANK levels.

The transition between BANK and FILTER is briefly smoothed to reduce clicks.

### What remains shared with BANK

- The ten center frequencies are configured on the shared BANDS page.
- Resonance is shared.
- Band-to-group assignments are shared.
- Display palette and saved state are shared.

FILTER ignores the BANK band-enable switches: all ten resonators remain
available to construct the filter response. It also ignores the manual BANK
level shape. The feedback-source switches and safety controls are shared, while
FILTER has an independent feedback amount that defaults to zero.

### FILTER main page

#### TYPE

- **LP** passes the lower bands and reduces the higher bands.
- **HP** passes the higher bands and reduces the lower bands.
- **BP** passes a region around the selected frequency.
- **NOT** reduces a region around the selected frequency while passing the
  bands outside it.

#### Filter controls

- **FREQ** moves the transition or center through the ten resonators.
- **SLOPE** changes how gradually or sharply the generated gain shape moves
  between passing and reduced bands.
- **WIDTH** sets the size of the BP or NOT region. It is shown only for those
  two types.
- **DRIVE** is a FILTER-specific drive setting; BANK retains its own drive.
- **RES** is the shared resonance setting.

The ten columns visualize the generated gains. They are not the manually saved
BANK band levels.

### FILTER inputs and MOD MATRIX

The INPUT page works in FILTER as it does in BANK: each jack can independently
be AUDIO or CV. Every AUDIO-role input joins the mono mix feeding the
resonators, with its own gain. IN1, IN2, and IN3 used as CV become the three
sources on the MATRIX page; switching one back to AUDIO removes its CV signal
from the matrix without erasing the stored matrix depths.

Each CV source can modulate any of five destinations with a bipolar depth:

- Frequency
- Resonance
- Width
- Slope
- Drive

Select a matrix cell, click, and turn. The center is zero modulation; the two
directions invert CV polarity. Multiple inputs may modulate the same
destination, and one input may modulate several destinations.

### FILTER groups and outputs

The GROUPS page still determines which resonators feed G1 through G4. Because
FILTER ignores the BANK enable mask, all ten band columns are available here.
Group changes are shared with BANK.

FILTER has its own OUTPUT send levels, separate from BANK. The four group sends
and the unfiltered DRY input mix are all available.

### Shared and mode-specific behavior

- BANDS frequencies, group membership, feedback-source switches, safety
  controls, and OPTIONS are shared.
- BANK alone uses manual band levels and the band-enable mask.
- BANK and FILTER retain separate drive, feedback amount, and output sends.
- SAVE DEFAULT stores the complete state of both modes.

### A practical first patch

1. Connect audio to IN0 and begin in BANK mode.
2. Load the OCTAVE layout and the ALL shape preset.
3. Lower several band levels, then raise RES until the bands become distinct.
4. Assign low, middle, and high bands to different groups.
5. Mix those groups differently across OUT0 through OUT3.
6. Add a CV input, target a group, and set a small bipolar depth.
7. Switch to FILTER, choose LP, and adjust FREQ and SLOPE.
8. Set IN1 to CV, then use it on the MATRIX page to modulate FREQ.
9. When the complete setup is worth keeping, use OPTIONS > SAVE DEFAULT.

When first exploring feedback, monitor at a conservative level and raise RES,
FB, and DRIVE one at a time. The limiter controls contain the feedback path,
but intentionally do not remove REZO's abrasive overload range.
