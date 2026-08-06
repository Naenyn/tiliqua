# REZO CLOCKED MVP user guide

This alternate REZO bitstream keeps the ten-band **BANK** filterbank and adds
an external-clock **CLOCK** mode. FILTER is not present in this bitstream.

## Selecting BANK or CLOCK

On the main page, turn the encoder from the REZO page selector to the mode box
at the upper right. Click, turn between **BANK** and **CLOCK**, then click to
finish.

BANK levels and the CLOCK shift register are separate. Returning to BANK
restores the unmodulated BANK shape. Returning to CLOCK resumes the captured
shift-register values until RESET or power cycling clears them.

The CLOCK main page intentionally matches BANK: it has the same preset picker,
ten band controls, DRIVE, RES, and FB. The next page in CLOCK mode is a compact
CLOCK settings page containing MODE and DIRECTION.

## Default patch

- Patch audio to **IN0**.
- Patch a reset gate to **IN1**.
- Patch the bipolar CV to sample to **IN2**.
- Patch a clock to **IN3**.

To reassign a role, open the INPUT page, set the desired jack to **CV**, and
choose **DAT**, **CLK**, or **RST** as its target. The three roles should
normally use distinct jacks. A role jack is excluded from ordinary audio and
CV routing while CLOCK is active, preventing clock and reset pulses from
entering the filterbank mix. DEPTH does not affect these three discrete roles.

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

The clock input uses separate high and low thresholds so noise near the edge
cannot create repeated captures. Holding a gate high produces only one shift;
it must return low before another rising edge is accepted.

## Reset

A high RESET IN clears all ten captured values immediately on the next audio
sample. It also returns PING to its forward phase and restarts RAND's sequence.
RESET does not alter BANK levels, frequency centers, enables, groups, feedback,
or output routing.

## Shared BANK pages

The frequency layouts, band enables, resonance, feedback safety, groups,
outputs, palette, and input routing work as in normal REZO. CLOCK
uses those same resonators and routes; its captured vector changes only the ten
band levels.

## MVP limitations

- CLOCK requires an external clock and external sample source. Internal clock,
  noise, and LFO sources are planned follow-ups.
- Mode and direction return to BANK/FWD after a reboot. The new DAT/CLK/RST
  target values are intentionally not written into the version-2 REZO state
  record yet, avoiding accidental interpretation of saves made by the released
  FILTER bitstream. The normal BANK state still saves and restores; after a
  saved version-2 input configuration is restored, assign CLOCK roles again on
  the INPUT page.
- The live ten-value shift register is transient and is not saved.
- WALK is not part of this MVP.
