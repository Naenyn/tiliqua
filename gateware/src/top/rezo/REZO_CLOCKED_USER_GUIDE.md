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
CLOCK settings page containing MODE, DIRECTION, SOURCE, BPM, and DEPTH. TURING
also reveals TARGET, LENGTH, optional START, and CHANGE controls on this page.

## Clock source

SOURCE offers three choices:

- **AUTO** uses the jack assigned to CLK whenever that physical jack is
  patched, and otherwise runs from the internal clock. The value is displayed
  as `AUTO E` while external or `AUTO I` while internal.
- **INT** always runs from the internal clock, even if the CLK jack is patched.
- **EXT** always waits for the external CLK input.

This decision uses the audio board's physical jack detector, not a pulse
timeout. A stopped or extremely slow patched clock therefore remains external.
On a source change, REZO waits for a complete internal interval or for the
external signal to return low and rise again. Plugging or unplugging a cable
cannot itself create a clock pulse.

BPM sets the internal clock to `15`, `30`, `45`, `60`, `90`, `120`, `180`, or
`240` beats per minute. It remains visible while using an external clock so the
fallback tempo can be prepared before unplugging the cable.

DEPTH scales the modulation produced by every CLOCK algorithm from 0 to 100
percent in seventeen steps. It does not alter the captured or generated
pattern, so depth can be reduced and later returned to 100 percent without
losing detail.

## Default patch

- Patch audio to **IN0**.
- Patch a reset gate to **IN1**.
- Patch the bipolar CV to sample to **IN2**.
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

On every accepted rising clock edge, REZO samples DATA IN. The full bipolar
input range maps to the bipolar band-level range. Captured changes pass through
the existing short parameter slew rather than stepping the resonator gains
instantaneously.

The sampled value is added to the band's saved BANK level. The CLOCK display
shows the BANK position as the base marker and the captured difference as
modulation shading.

### SHIFT direction

- **FWD** inserts the new sample at band 0 and shifts older values toward band
  9.
- **REV** inserts at band 9 and shifts toward band 0.
- **RAND** chooses forward or reverse independently from a deterministic
  pseudo-random sequence on each pulse.

## ROTATE mode

ROTATE leaves every natural BANK level untouched and circulates a copy of the
BANK shape as additive modulation. On the first forward pulse, each enabled
band's natural level moves to the next enabled band. Later pulses continue
moving that modulation ring. Disabled bands are skipped and receive no rotated
modulation.

ROTATE supports **FWD**, **REV**, and **PING**. PING begins forward and reverses
after a number of pulses equal to the number of enabled bands, then repeats in
the other direction. Changing between SHIFT and ROTATE clears the transient
modulation vector so state from one algorithm cannot leak into the other.

## TURING mode

TURING is a full-resolution random looping modulation register inspired by the
Music Thing Modular Turing Machine. LENGTH selects its pattern length from 2 to
10. TARGET controls how that private pattern is distributed:

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
TURING supports **FWD** and **REV**. Its random loop is additive modulation over
the untouched natural BANK levels.

The clock input uses separate high and low thresholds so noise near the edge
cannot create repeated captures. Holding a gate high produces only one shift;
it must return low before another rising edge is accepted.

## Reset

A high RESET IN clears all ten SHIFT/ROTATE values immediately on the next audio
sample. It also returns PING to its forward phase and restarts RAND's sequence.
RESET does not alter BANK levels, frequency centers, enables, groups, feedback,
or output routing. TURING ignores RESET; changing its algorithm or LENGTH starts
a fresh initial fill.

## Shared BANK pages

The frequency layouts, band enables, resonance, feedback safety, groups,
outputs, palette, and input routing work as in normal REZO. CLOCK
uses those same resonators and routes; its captured vector changes only the ten
band levels.

## MVP limitations

- SHIFT still requires external DATA; TURING has its own internal random
  source. Internal LFO and noise DATA sources are planned follow-ups.
- Mode, algorithm, direction, source, internal BPM, CLOCK depth, TURING target,
  length, start, and change amount return to their defaults after a reboot. The
  new DAT/CLK/RST/LCK
  target values are intentionally not written into the version-2 REZO state
  record yet, avoiding accidental interpretation of saves made by the released
  FILTER bitstream. The normal BANK state still saves and restores; after a
  saved version-2 input configuration is restored, assign CLOCK roles again on
  the INPUT page.
- The live ten-value modulation register is transient and is not saved.
- WALK is not part of this MVP.
