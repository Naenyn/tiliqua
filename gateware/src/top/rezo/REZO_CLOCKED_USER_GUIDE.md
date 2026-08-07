# REZO CLOCKED MVP user guide

This alternate REZO bitstream keeps the ten-band **BANK** filterbank and adds
a clock-driven **CLOCK** mode. FILTER is not present in this bitstream.

## Selecting BANK or CLOCK

On the main page, turn the encoder from the REZO page selector to the mode box
at the upper right. Click, turn between **BANK** and **CLOCK**, then click to
finish.

BANK levels and the CLOCK modulation state are separate. Returning to BANK
restores the unmodulated BANK shape. Returning to CLOCK resumes its transient
state until it is cleared or refilled according to the selected algorithm.

The CLOCK main page intentionally matches BANK: it has the same preset picker,
ten band controls, DRIVE, RES, and FB. The next page in CLOCK mode is a compact
CLOCK settings page with shared controls in the left column and
algorithm-specific controls in the right. Every mode keeps DIRECTION, SOURCE,
BPM, and DEPTH in the same four rows. DIRECTION is editable in SHIFT, ROTATE,
and TURING. WALK moves randomly in both directions, so it displays read-only
RANDOM and skips that row during navigation. SHIFT also shows DATA; TURING
shows CHANGE, BANDS, LENGTH, and optional START.

## Clock source

SOURCE offers three choices:

- **AUTO** uses the jack assigned to CLK whenever that physical jack is
  patched, and otherwise runs from the internal clock. The value is displayed
  as `AUTO EXT` while external or `AUTO INT` while internal.
- **INTERNAL** always runs from the internal clock, even if CLK is patched.
- **EXTERNAL** always waits for the external CLK input.

This decision uses the audio board's physical jack detector, not a pulse
timeout. A stopped or extremely slow patched clock therefore remains external.
On a source change, REZO waits for a complete internal interval or for the
external signal to return low and rise again. Plugging or unplugging a cable
cannot itself create a clock pulse.

BPM sets the internal clock to any whole-number tempo from 15 to 300 beats per
minute. Slow encoder turns change it by 1 BPM; quick turns accelerate through
the range. It remains visible while using an external clock so the fallback
tempo can be prepared before unplugging the cable.

DEPTH scales the modulation produced by every CLOCK algorithm from 0 to 100
percent in seventeen steps. It does not alter the captured or generated
pattern, so depth can be reduced and later returned to 100 percent without
losing detail.

## SHIFT data source

DATA chooses what SHIFT captures on each accepted clock edge:

- **CV** samples the jack assigned to DAT. This is the default and preserves
  the original external sample-and-hold behavior.
- **RANDOM** samples an independent internal bipolar pseudo-random source. The
  generator runs continuously at the audio sample rate, so clock timing
  selects a new point from the noise stream.
- **AUTO CV/AUTO RAND** are the effective AUTO states: AUTO samples DAT while
  its assigned physical jack is patched and uses internal random data
  otherwise.

The shared CLOCK DEPTH control scales either source. ROTATE and WALK do not
consume DATA, and TURING retains its own independent random loop generator.

## Default patch

- Patch audio to **IN0**.
- Patch a reset gate to **IN1**.
- Patch the bipolar CV to sample to **IN2**, or select DATA RANDOM/AUTO to use
  the internal source.
- Optionally patch a clock to **IN3**. With SOURCE set to AUTO, REZO uses its
  internal 120 BPM clock until that jack is patched.

To reassign a role, open the INPUT page, set the desired jack to **CV**, and
choose **DAT**, **CLK**, **RST**, or **LCK** as its target. Discrete role jacks
should normally use distinct jacks. A role jack is excluded from ordinary
audio and CV routing while CLOCK is active, preventing clock and reset pulses from
entering the filterbank mix. DEPTH does not affect these discrete roles.

**LCK** is the active-high gate target used by TURING. A practical TURING patch
assigns IN1 to LCK instead of RST, leaves IN2 available for ordinary modulation,
and keeps CLOCK on IN3. TURING generates changing values internally and
intentionally ignores RESET.

## SHIFT mode

On every accepted rising clock edge, REZO samples the selected DATA source.
The full bipolar input or internal random range maps to the bipolar band-level
range. Captured changes pass through the existing short parameter slew rather
than stepping the resonator gains instantaneously.

The sampled value is added to the band's saved BANK level. The CLOCK display
shows the BANK position as the base marker and the captured difference as
modulation shading.

### SHIFT direction

- **FORWARD** inserts the new sample at band 0 and shifts older values toward band
  9.
- **REVERSE** inserts at band 9 and shifts toward band 0.
- **RANDOM** chooses forward or reverse independently from a deterministic
  pseudo-random sequence on each pulse.

## ROTATE mode

ROTATE leaves every natural BANK level untouched and circulates a copy of the
BANK shape as additive modulation. On the first forward pulse, each enabled
band's natural level moves to the next enabled band. Later pulses continue
moving that modulation ring. Disabled bands are skipped and receive no rotated
modulation.

ROTATE supports **FORWARD** and **REVERSE**. Changing between SHIFT and ROTATE
clears the transient modulation vector so state from one algorithm cannot leak
into the other.

## WALK mode

WALK provides two related STYLE choices. Both use a fixed moderate step;
CLOCK DEPTH scales the complete result without changing the stored walk.

- **ALL** maintains an independent bipolar value for every enabled band. On
  each accepted pulse, every enabled value randomly moves up or down by one
  fixed step.
- **BAND** moves one cursor randomly up or down through the enabled bands and
  changes only the band where it lands. Every move is one enabled band; disabled
  bands are skipped. DRUNK sets the total length of a possible stumble from 1
  to 4 landings, while CHANCE selects a `0`, `10`, `25`, `50`, `75`, or `100`
  percent chance that a clock edge starts one. Extra landings are spaced at
  quarter-clock intervals, so a four-step stumble under a quarter-note clock
  has a sixteenth-note feel. The first external pulse learns the clock period;
  stumbles become available after that interval has been measured. The internal
  clock already knows its period and can stumble immediately.

At either modulation limit, an outward step reverses and moves inward instead
of clipping or wrapping. This reflection keeps the motion continuous and
prevents values from becoming stuck at a rail. BAND also reflects its cursor at
the first and last physical band rather than wrapping around. In ALL, disabled
bands are forced to zero. In BAND they are skipped and remain inaudible. RESET
returns the complete walk and the BAND cursor to their starting state. Changing
STYLE also clears the transient walk so the two behaviors never inherit a
partially developed pattern from one another.

## TURING mode

TURING is a full-resolution random looping modulation register inspired by the
Music Thing Modular Turing Machine. CHANGE is the probability that an unlocked
departing loop value mutates. BANDS controls how the private pattern is
distributed, and LENGTH selects its pattern length from 2 to 10:

- **ALL** repeats the pattern across every enabled band. Disabled bands are
  skipped without consuming a pattern position. A five-step pattern therefore
  appears twice when all ten bands are enabled.
- **RANGE** places one copy on a physical band range. START is numbered 1 to 10
  to match the visible bands; START 6 with LENGTH 3 modulates bands 6, 7, and 8.
  Bands outside the range, and disabled bands inside it, receive no TURING
  modulation. START is clamped so the range never extends above band 10.

The first LENGTH clock pulses fill the loop with internal bipolar pseudo-random
values. This initial fill occurs even while LCK is high, preventing an empty
loop from being locked forever. After filling:

- **LCK high** recirculates every departing value unchanged, producing an exact
  repeating loop.
- **LCK low** permits mutation. On a successful CHANGE trial, the departing
  value is replaced by a new internal bipolar random value; otherwise it is
  recirculated unchanged.

CHANGE offers `1`, `3`, `6`, `12`, `25`, `50`, and `100` percent settings.
TURING supports **FORWARD**, **REVERSE**, and **PING PONG**. PING PONG changes
direction after each complete LENGTH traversal. Its random loop is additive
modulation over the untouched natural BANK levels.

The clock input uses separate high and low thresholds so noise near the edge
cannot create repeated captures. Holding a gate high produces only one shift;
it must return low before another rising edge is accepted.

## Reset

A high RESET IN clears all ten SHIFT/ROTATE/WALK values immediately on the next
audio sample. It also returns PING to its forward phase and restarts RAND's sequence.
RESET does not alter BANK levels, frequency centers, enables, groups, feedback,
or output routing. TURING ignores RESET; changing its algorithm or LENGTH starts
a fresh initial fill.

## Shared BANK pages

The frequency layouts, band enables, resonance, feedback safety, groups,
outputs, palette, and input routing work as in normal REZO. CLOCK
uses those same resonators and routes; its captured vector changes only the ten
band levels.

## MVP limitations

- SAVE DEFAULT now stores BANK/CLOCK mode, algorithm, direction, clock source,
  internal BPM, CLOCK depth, SHIFT DATA source, TURING target, length, start,
  change amount, WALK style/drunkenness/chance, and the complete
  DAT/CLK/RST/LCK input assignments. Version-1 and version-2 REZO saves still
  load with safe CLOCK defaults; saving again writes the version-3 format.
- SHIFT can sample external CV, internal random data, or select between them
  automatically from physical patch detection. An internal LFO remains a
  possible follow-up source.
- The live ten-value modulation register is transient and is not saved.
