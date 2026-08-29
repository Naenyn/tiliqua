# REZOMO user guide

REZOMO is a ten-band resonant filterbank with two closely related operating
modes:

- **BANK** gives direct control over the natural level of every resonator.
- **CLOCK** adds clock-driven modulation to those BANK levels using SHIFT,
  ROTATE, WALK, or TURING algorithms.

REZOMO is the clock-oriented sibling of REZO. It does not include REZO's
FILTER mode.

## Hardware and connections

REZOMO uses all four Eurorack inputs and outputs:

- **IN0..IN3** can be AUDIO, continuous CV, or one of the discrete CLOCK roles.
- AUDIO-role inputs are gain-controlled and mixed to the mono resonator input.
- DAT, CLK, RST, and LCK assignments are made on the INPUT page and may be
  placed on whichever physical jacks suit the patch.
- **OUT0..OUT3** are independent mixes of G1 through G4 plus the dry mono input.

HDMI video is required for editing and for seeing active clock-source status.
The audio and clock engines continue to run without display interaction after
startup.

## Basic controls

REZOMO uses the encoder for navigation and editing.

1. Turn the encoder to move the selection outline.
2. Click to enter **EDIT**.
3. Turn to change the selected value.
4. Click again to apply the value and return to **NAV**.

Continuous numeric controls use progressive acceleration: a slow turn changes
one step at a time, while sustained fast turns in one direction ramp smoothly
through larger steps. Direction changes and discrete choices always begin with
a single step.

Enable switches, feedback-source switches, and **SAVE DEFAULT** act
immediately when clicked.

Select the page-name chip beside **PAGE** to change pages. On the main page,
navigation proceeds PAGE, then PRESET, then MODE. Select MODE to switch between
BANK and CLOCK.

### Display versions

REZOMO is supplied for two displays:

- **Standard:** `1280x720p60`, with the native 720x720 interface centered in
  the widescreen raster.
- **Circular:** `720x720p60r2`, with the same interface rotated for the
  official panel mount.

Controls, clock behavior, and saved state are identical. Use the build intended
for the connected display; the circular build is not a scaled widescreen mode.

## Startup and saved state

At startup REZOMO loads the newest valid record from the active bitstream slot,
or uses its compiled factory state if no valid record exists. Audio is unmuted
only after that state has been applied completely.

**SAVE DEFAULT** stores static controls and CLOCK configuration in the active
slot. The evolving SHIFT, ROTATE, WALK, and TURING contents remain transient,
so rebooting restarts modulation as a live process rather than recalling stale
pattern memory.

## Understanding the bands

The ten bands are parallel band-pass resonators. A band's frequency is its
**center frequency**, not the beginning or end of a rigid frequency range.
Each resonator also responds around its center, so neighboring bands overlap.
The global resonance setting affects how broad or narrow those responses are.

Disabling a band removes that resonator from the audio mix. Neighboring bands
do not widen to fill the gap. Other pages leave a dim frame or ghost rail in
the disabled band's position, and navigation skips controls that would edit a
disabled band.

## BANK mode

BANK is the direct filterbank mode. AUDIO-role inputs are mixed to mono and
sent through every enabled resonator. Bands feed groups, and the groups are
mixed independently to the four outputs.

```text
AUDIO inputs -> resonator bands -> groups -> output sends -> OUT0..OUT3
                         |
                         +-> selected bands feed the feedback loop
```

### BANK main page

#### PRESET

The shape presets change the ten natural band levels. They do not change
frequencies, enables, group assignments, feedback sources, or output routing.

| Preset | Result |
|---|---|
| ALL | Raises every band |
| ODD | Raises alternating odd-position bands |
| EVEN | Raises alternating even-position bands |
| LOW | Raises the lowest four bands |
| MID | Raises the middle four bands |
| HI | Raises the highest four bands |
| ZERO | Returns every band level to zero |

#### Band levels

Each vertical band control is bipolar. The center line is zero; positions
above and below it use opposite polarity. Opposite-polarity resonators can
cancel or reinforce one another because their responses overlap.

Selecting a band displays its center frequency beside **FREQ:**. A disabled
band retains a dim frame but cannot be adjusted here.

#### DRIVE, RES, and FB

- **DRIVE** controls how strongly the input excites the resonators.
- **RES** controls resonance and ringing around each center frequency.
- **FB** returns the selected feedback-band mix to the resonator input.

High RES and FB settings interact strongly. Begin with modest values and raise
them carefully. The display distinguishes a control's saved position from its
CV-modulated effective value.

### BANDS page

The BANDS page configures the resonators themselves.

#### Frequency layouts

| Layout | Center frequencies in Hz |
|---|---|
| LEGACY | 29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000 |
| OCTAVE | 31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000 |
| PERCEPT | 50, 150, 300, 500, 770, 1150, 1700, 2700, 5300, 12000 |
| USER | The current manually edited layout |

Selecting a factory layout replaces all ten current center frequencies.
Editing any individual frequency automatically changes the displayed layout
to USER. USER is the current working layout, not a separate hidden copy.

#### Enabling bands

The **ENABLE** row contains one switch per resonator. Click a switch to include
or remove that band from BANK and CLOCK processing. A disabled band's
frequency can still be edited on this page before it is enabled again.

#### Editing a frequency

Select a **SET FREQ** button, click, turn to the desired value, then click to
apply it. The available frequencies form a fine logarithmic grid. Slow turns
move one position; repeated fast turns accelerate through the range.

### INPUT page

Each of IN0 through IN3 can be assigned as **AUDIO** or **CV**.

For an AUDIO input:

- **MODE** selects AUDIO.
- **VALUE** sets its input gain.
- The signal joins the mono input mix feeding the resonators.

For an ordinary CV input:

- **MODE** selects CV.
- **VALUE** selects FB, RES, DRV, or group G1 through G4.
- **DEPTH** is a bipolar attenuverter. Its center is zero modulation; the two
  directions apply opposite CV polarity.

Group CV changes the effective levels of every enabled band assigned to that
group.

The same page also assigns the discrete CLOCK roles **DAT**, **CLK**, **RST**,
and **LCK**. Those roles are described under CLOCK mode.

### GROUPS page

The GROUPS page assigns each enabled band to G1, G2, G3, G4, or combinations
of those groups. Select a band, click, and turn through its membership
patterns.

Groups serve two purposes:

- Group CV can modulate several band levels together.
- The OUTPUT page can mix each group independently to every output.

A disabled band's four group positions remain visible as dim ghost rails, but
the band cannot be edited from this page.

### OUTPUT page

Each output has independent unipolar sends from **GRP1**, **GRP2**, **GRP3**,
**GRP4**, and **DRY**.

- Raise multiple group sends to mix them at one output.
- Use different group combinations for four related filterbank outputs.
- DRY adds the unfiltered mono AUDIO-input mix.
- A maximum send is unity gain; a zero send contributes nothing.

BANK and CLOCK use the same group and output routing.

### FEEDBACK page

The ten band switches select which enabled resonators feed the shared feedback
loop. The main page's FB control sets the overall return amount.

- **KNEE** sets where soft limiting begins. Below it, the return is unchanged;
  above it, progressively stronger compression bends the signal toward CEIL.
- **CEIL** sets the hard maximum feedback-loop level. Its fader colors the
  span from KNEE to CEIL to show the active soft-limiting region.
- **DAMP** makes increasing feedback restrain resonance. Higher values are
  more conservative.

KNEE and CEIL may meet for hard limiting with no soft region. Raising KNEE
past CEIL raises CEIL too; lowering CEIL past KNEE lowers KNEE too. This keeps
the pair valid while allowing either control to lead an edit.

These controls reduce runaway behavior but do not make every extreme RES/FB
combination quiet.

### OPTIONS page

#### PALETTE

Choose LCD, AMBER, CYAN, GREEN, or VIOLET.

#### SAVE DEFAULT

Click **SAVE DEFAULT** to store the complete static REZOMO setup for the
current bitstream slot. The button reports SAVING, SAVED, ERROR, or NO SLOT.
Changes are not saved automatically.

The save includes natural band levels, frequencies, enables, groups, feedback,
input assignments and depths, output sends, palette, the selected BANK/CLOCK
mode, and every CLOCK parameter. Dynamic CLOCK-generated band modulation is
intentionally not saved.

## CLOCK mode

CLOCK keeps the complete BANK signal path and adds a transient bipolar
modulation value to each enabled band's natural BANK level. The natural level
marker remains visible while modulation moves around it.

The CLOCK main page intentionally matches BANK: PRESET, the ten band controls,
DRIVE, RES, and FB all edit the underlying BANK sound. Disabled bands are
skipped by the clock algorithms.

The following CLOCK page selects the clock algorithm and its settings.

### Shared CLOCK controls

#### MODE

- **SHIFT** samples DATA and shifts captured values through the enabled bands.
- **ROTATE** circulates a copy of the natural BANK shape as modulation.
- **WALK** produces reflected random walks.
- **TURING** evolves or locks a repeating internal random loop.

Changing algorithm clears incompatible transient modulation so one algorithm
does not inherit a partially developed pattern from another.

#### DIRECTION

The available choices depend on MODE:

- SHIFT: FORWARD, REVERSE, or RANDOM.
- ROTATE: FORWARD or REVERSE.
- WALK: read-only RANDOM; navigation skips this row.
- TURING: FORWARD, REVERSE, or PING PONG.

#### SOURCE and BPM

SOURCE chooses the clock:

- **AUTO** uses the assigned CLK jack while its physical jack detector reports
  a patch, otherwise it uses the internal clock. The display reports AUTO EXT
  or AUTO INT to show the active source.
- **INTERNAL** always uses the internal clock.
- **EXTERNAL** always waits for the assigned CLK input.

AUTO uses physical patch detection rather than a pulse timeout. A patched but
stopped clock therefore remains external. Source handoff waits for a safe edge;
plugging or unplugging a cable does not itself create a pulse.

BPM sets the internal clock to any whole-number tempo from 15 through 300.
Slow turns change one BPM; fast turns accelerate. BPM remains editable while
an external clock is active so the fallback tempo can be prepared in advance.

#### DEPTH

The full-width slider scales every CLOCK algorithm from 0 to 100
percent in seventeen steps. It scales the output modulation without destroying
the captured or generated pattern.

### Discrete CLOCK input roles

On the INPUT page, set a jack to CV and assign one of these targets:

- **CLK** accepts the external clock.
- **DAT** supplies the bipolar sample captured by SHIFT.
- **RST** clears SHIFT, ROTATE, and WALK transient state.
- **LCK** is TURING's active-high loop-lock gate.

A discrete-role jack is excluded from ordinary audio and continuous CV routing
while CLOCK is active. Assign different physical jacks to roles that need to be
used simultaneously.

The first transition into CLOCK supplies these defaults if no clock roles have
already been assigned:

- IN1: RST
- IN2: DAT
- IN3: CLK

IN0 remains available for audio.

### SHIFT

On each accepted rising clock edge, SHIFT samples DATA. The full bipolar input
range maps to the bipolar band-modulation range and passes through the normal
short parameter slew.

DATA offers:

- **CV**: always sample the assigned DAT input.
- **RANDOM**: sample an independent internal bipolar pseudo-random source.
- **AUTO**: use DAT while its physical jack is patched, otherwise use internal
  random. The display reports AUTO CV or AUTO RAND.

FORWARD inserts the new sample at the lowest enabled band and shifts older
values upward. REVERSE inserts at the highest enabled band. RANDOM chooses one
of those two directions on every pulse. Disabled bands are skipped.

### ROTATE

ROTATE copies the natural BANK levels into an additive modulation ring without
changing the natural values themselves. Each pulse moves that ring to the next
enabled band in the selected direction. The value leaving one end returns at
the other end. ROTATE supports FORWARD and REVERSE.

### WALK

WALK always chooses its spatial direction randomly and reflects at its limits
instead of clipping or wrapping.

- **ALL** maintains an independent bipolar walk for every enabled band. Every
  clock pulse moves each value up or down by one fixed step.
- **BAND** moves one cursor randomly through the enabled bands and changes only
  the band where it lands. Disabled bands are skipped.

For BAND, **DRUNK** chooses a possible stumble length from one to four
landings. **CHANCE** chooses a 0, 10, 25, 50, 75, or 100 percent chance that a
clock pulse starts the stumble. Extra landings occur at quarter-clock
intervals, so a four-landing stumble under a quarter-note clock has a
sixteenth-note feel. The first external interval must be measured before
stumbles are available; the internal clock already knows its period.

### TURING

TURING is a full-resolution looping random modulation register inspired by the
Music Thing Modular Turing Machine.

**LENGTH** selects two through ten loop steps. **CHANGE** sets a 1, 3, 6, 12,
25, 50, or 100 percent probability that an unlocked departing value is
replaced by a new internal random value.

**BANDS** controls distribution:

- **ALL** repeats the pattern across every enabled band. Disabled bands do not
  consume pattern positions. A five-step pattern therefore repeats twice
  across ten enabled bands.
- **RANGE** places one copy on a physical range. START is numbered 1 through
  10. START 6 and LENGTH 3 target bands 6, 7, and 8. Other bands receive no
  TURING modulation.

The first LENGTH pulses fill the loop even if LCK is high. After filling:

- LCK high recirculates the loop unchanged.
- LCK low permits mutations according to CHANGE.

PING PONG changes direction after each complete LENGTH traversal. TURING
intentionally ignores RST; changing MODE or LENGTH starts a fresh fill.

### Reset behavior

A high RST input clears SHIFT, ROTATE, and WALK transient modulation on the
next audio sample. It restores directional phase and restarts the deterministic
random sequence. It does not alter natural band levels, frequencies, enables,
groups, feedback, routing, or saved settings.

### Clock input behavior

The external clock uses separate high and low thresholds. Holding a gate high
produces one accepted edge; it must return low before another edge can occur.
This hysteresis prevents noise near the threshold from producing repeated
captures.

Clock and reset inputs are interpreted after their assigned jack roles. If an
expected clock produces no motion, verify the jack is set to CV, assigned CLK,
and selected by SOURCE before changing the audio routing.

## Practical starting patches

### Clocked sample and hold

1. Patch audio to IN0.
2. Patch a bipolar CV to IN2/DAT.
3. Patch a clock to IN3/CLK, or leave it unpatched for AUTO INT.
4. Select CLOCK, SHIFT, FORWARD, and DATA CV.
5. Start with DEPTH near 25 percent, then increase it to taste.

### Self-running pattern

1. Leave CLK and DAT unpatched.
2. Select SOURCE AUTO INT and set BPM.
3. Select SHIFT with DATA AUTO RAND, or select WALK.
4. Raise RES moderately and distribute groups across the outputs.

### Locked evolving loop

1. Assign IN1 to LCK and IN3 to CLK.
2. Select TURING, choose LENGTH and CHANGE, and let the initial loop fill.
3. Hold LCK high to freeze the loop.
4. Lower LCK briefly whenever the pattern should evolve again.

## Saved and transient state

SAVE DEFAULT stores every static parameter needed to recreate the patch,
including CLOCK MODE, DIRECTION, SOURCE, BPM, DEPTH, SHIFT DATA, TURING
settings, WALK settings, and DAT/CLK/RST/LCK assignments.

The evolving SHIFT register, rotated modulation ring, WALK positions, TURING
loop contents, cursor, and clock phase remain transient by design. Modulation
should resume as a live process rather than reappear as stale saved values.
