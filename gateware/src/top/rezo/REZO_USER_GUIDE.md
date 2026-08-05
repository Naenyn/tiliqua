# REZO user guide

REZO is a ten-band resonant filterbank with two ways to use the same resonator
core:

- **BANK** gives direct control over the level of every band.
- **FILTER** combines the ten bands into low-pass, high-pass, band-pass, or
  notch responses.

This guide describes BANK completely first, then explains what changes in
FILTER.

## Basic controls

REZO uses the encoder for both navigation and editing.

1. Turn the encoder to move the selection outline.
2. Click the encoder to enter **EDIT**.
3. Turn to change the selected value.
4. Click again to apply the value and return to **NAV**.

Enable switches, feedback-source switches, and **SAVE DEFAULT** act
immediately when clicked. They do not require a separate edit step.

To change pages, select the **REZO** box at the upper left, click, and turn.
To switch between BANK and FILTER, select the mode box at the upper right,
click, turn once, and click again.

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
| EVN | Raises alternating even-position bands |
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

The BANDS page configures the resonators themselves. It appears only in BANK
mode.

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

The ten band switches choose which enabled bands feed the shared feedback loop.
Click a band to include or exclude it. These switches shape the feedback signal;
the main page's **FB** control sets its overall amount.

The three safety controls shape and constrain the returning signal:

- **KNEE** sets the level where soft limiting begins.
- **CEIL** sets the maximum allowed feedback-loop level.
- **DAMP** controls how strongly increasing feedback restrains resonance.
  Higher settings are more conservative.

Start with modest FB and RES settings, especially when several bands feed the
loop. KNEE and CEIL reduce runaway behavior, but they do not make every extreme
setting quiet.

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

- The ten center frequencies are the frequencies configured on the BANK BANDS
  page. FILTER uses them even though the BANDS page is hidden.
- Resonance is shared.
- Band-to-group assignments are shared.
- Display palette and saved state are shared.

FILTER ignores the BANK band-enable switches: all ten resonators remain
available to construct the filter response. It also ignores the manual BANK
level shape and disables the BANK feedback loop.

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

FILTER treats **IN0** as its audio input. Keep IN0 configured as AUDIO and use
its saved input gain to set the incoming level.

IN1, IN2, and IN3 become the three CV sources on the **MATRIX** page. Each can
modulate any of five destinations with a bipolar depth:

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
remain available, but DRY is omitted: FILTER outputs contain only grouped
resonator signals.

### Pages with BANK-only behavior

- **BANDS** is hidden in FILTER. Return to BANK to change frequency layouts,
  individual center frequencies, or enable switches.
- The feedback loop is disabled in FILTER. FEEDBACK settings are retained for
  BANK and resume when BANK is selected.
- OPTIONS and SAVE DEFAULT work identically in both modes.

### A practical first patch

1. Connect audio to IN0 and begin in BANK mode.
2. Load the OCTAVE layout and the ALL shape preset.
3. Lower several band levels, then raise RES until the bands become distinct.
4. Assign low, middle, and high bands to different groups.
5. Mix those groups differently across OUT0 through OUT3.
6. Add a CV input, target a group, and set a small bipolar depth.
7. Switch to FILTER, choose LP, and adjust FREQ and SLOPE.
8. Use IN1 on the MATRIX page to modulate FREQ.
9. When the complete setup is worth keeping, use OPTIONS > SAVE DEFAULT.
