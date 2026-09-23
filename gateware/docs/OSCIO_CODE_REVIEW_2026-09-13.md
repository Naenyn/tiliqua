# OSCIO code review — 2026-09-13

Reviewed `oscio` at `3015209c`, including its firmware, capture/scaler,
frequency detector, reconstruction/resampling, trigger/ramp, scope overlay,
clock-domain configuration transfers, and relevant tests. Findings below are
not implemented by this review. The accompanying implementation changes are
limited to jack numbering and explanatory documentation.

Follow-up: the subsequent continuity patch addresses the first P1 finding
with capture backpressure and atomic channel acceptance. Its spaced/burst
equivalence tests are in `tests/test_scope_continuity.py`; the numerical
examples below describe the original implementation, not the corrected one.

## Label changes

User-facing channel numbers now match physical input and output jacks 0-3:
on-device help, bootloader jack diagram, channel menus, trigger source values,
CV/LFO pair selector, range labels, and statistics headings. Updated the
checked-in generated help copy as well as its source. No help lines were added
or removed, so the scroll limit is unchanged.

Legacy option identifiers and enum ordering remain intact to preserve stored
settings. For example, `TriggerChannel::Ch1` still selects hardware index 0,
but its displayed value is now `0`. This also avoids silently migrating a
saved setting to another physical jack.

## Correctness findings

### P1: Capture can associate Y samples with the next bundle's X position

Location: `src/tiliqua/raster/scope_capture.py:229-284`.

`scaling` clears after issuing the fourth channel's multiply, allowing a new
bundle to overwrite `scaled_x`, `scaled_active`, and `scaled_at_end` before
the old bundle reaches the final coordinate stage. That stage then reads the
new metadata alongside the previous bundle's Y values. The comment assuming
39 clocks between bundles uses the average plotting rate; the edge-aware
resampler actually emits bursts, including five-clock phase spacing and
adjacent final outputs. Capture has no ready signal to throttle those bursts.

Reproduction: identical 20-bundle stimuli separated by 20 clocks versus five
clocks produce different column streams. The first spaced envelope appears at
column 75 with Y minima `[-6, -12, -19, -25]`; the burst version attaches those
same values to column 79. The spaced run flushes 19 columns and the burst run
18. These are direct component simulations, not an on-hardware measurement.

Recommendation: pipeline bundle metadata with the corresponding channel
results, and provide an explicit ready/valid or adequately buffered interface
for capture. Simply declining samples while the pipeline drains would discard
data; test the actual resampler-to-capture chain with burst traffic and sweep
endpoints. Preserve the existing staged multiplier to retain its timing benefit.

### P2: CV/LFO level filtering has a persistent negative DC bias

Location: `src/top/oscio/fw/src/monitor.rs:293-294`.

The integer update `(sample - level) >> 5` becomes zero for a positive residual
of 1-31 counts. Negative residuals round downward, so the settling behavior is
asymmetric. A tracker initialized at zero and then fed exactly 4000 Q15 counts
(1 V) for 10,000 updates settles at 3969 counts, displayed as **0.992 V**.
This was reproduced by compiling the tracker and measurement structures
directly from the reviewed Rust source in a small host harness.

Recommendation: retain fractional accumulator bits or an error remainder,
then round when presenting the level. Add positive and negative DC-step tests;
the current static-voltage test initializes directly at its final voltage,
so it cannot detect this error.

### P2: The rapid-activity window changes meaning with native sample rate

Locations: `src/tiliqua/raster/frequency_detector.py:35`,
`src/tiliqua/raster/digital_scope.py` detector construction, and
`src/top/oscio/fw/src/monitor.rs:338-345`.

The detector always uses 4800 native samples per activity window and flags two
rising crossings. That window is 25 ms at 192 kHz but 100 ms at 48 kHz.
Simulation of a valid 20 Hz square wave reports `period=2400, valid=1, rapid=1`
at 48 kHz, versus `period=9600, valid=1, rapid=0` at 192 kHz. Once a lane is
visible, `is_above_hard_limit` unconditionally hides it when rapid is set,
even though its measured period is within the selected 20 Hz limit. Admission
and hard-exit predicates also disagree here, allowing repeated qualification
and hiding. OSCIO supports a 48 kHz build as well as its usual 192 kHz build.

Recommendation: derive activity-window length and hold time from `native_fs`,
and make admission and exit handling consistent. Audit the envelope block and
release constants for sample-rate and Q-format dependence at the same time.

### P2: Four-lane CV/LFO layout overflows shorter supported displays

Locations: `src/top/oscio/fw/src/monitor.rs:39-49`, its statistics text Y
positions, and `src/tiliqua/raster/scope_capture.py:244-247`.

Every rectangular display gets four lanes, but each lane retains a fixed
160-pixel voltage window and statistics text extends to baseline 145 inside a
168-pixel bitmap. At 640x480, lanes are only 120 pixels high: waveforms cross
lane separators and lower statistics extend into the next lane (or beyond the
screen for the last lane). At 800x600 and 1024x600, the 150-pixel lanes are still
shorter than the voltage window. These modelines are supported by the video
configuration. The usual 1280x720 layout and paginated 720x720 layout have
enough height.

Recommendation: choose pagination from available lane height, or derive both
voltage mapping and text layout from lane geometry. Update menu visibility so
the channel-pair selector appears for any newly paginated modeline.

### P2: Period validity does not establish repeatability

Location: `src/tiliqua/raster/frequency_detector.py:243-246` and the on-device
help's claim that irregular signals show `--`.

After two Schmitt rising crossings, the latest interval is marked valid if it
fits in 24 bits. No comparison to preceding intervals is performed. Irregular
events can therefore produce a numerical frequency rather than `--`; the
three-second lane qualification checks frequency limits, not cycle consistency.

Recommendation: either qualify interval consistency over multiple cycles,
with a documented tolerance and response time, or describe the measurement as
the reciprocal of the latest crossing interval instead of a repeatability test.
Keep step and static-CV visualization independent of frequency validity.

## Optimization opportunities and measurement limits

- **Avoid rewriting unchanged scope configuration in every main-loop pass.**
  `main.rs:762-909` repeatedly writes hue, intensity, level, scale, positions,
  masks, plot bounds, and trigger settings. It also rereads pixels-per-volt and
  recalculates the timebase using 64-bit division on RV32IM. Cache applied
  settings and update only changed groups, with explicit initialization and
  reset handling. Keep the existing configuration-before-trace-reset ordering.
  Expected benefit is reduced CPU/bus traffic; no cycle benchmark was taken.
- **Take the native frequency snapshot when it will be consumed.** The main
  loop currently snapshots all four periods on every CV/LFO iteration, but
  statistics and gate state advance at the 100 ms measurement epoch. Align
  reads and formatting with that epoch unless a separate faster reaction path
  is deliberately required.
- **Measure extrema at the native rate if audio statistics need accuracy.**
  Low/high/peak-to-peak are based on 1 kHz firmware polling, while frequency is
  native-rate. Narrow gates and audio waveforms can be missed or aliased by the
  voltage tracker, even while a convincing frequency is displayed. Native
  min/max accumulation with a low-rate snapshot would improve peak coverage
  and reduce per-sample CPU work, at an FPGA resource cost. This is a design
  limitation rather than a claim that low-frequency CV measurement is unusable.
- **Clarify raw acquisition.** `clean_o` bypasses discontinuity reconstruction,
  but the edge-aware resampler remains active in both modes. Raw therefore
  still uses hard-edge holding and interpolation between retained samples;
  it is not an unprocessed sample-only display.
- **Do not promise a fixed ten-division CV/LFO history.** The current mapping
  retains time per division, but the visible lane width varies: 1280x720 gives
  1074/125 = 8.592 divisions, while the circular lane gives 390/31 ≈ 12.58.
  The code comment promising one to fifty seconds of history is approximate
  and is inaccurate for these layouts. A seconds-per-screen control would be
  clearer if users need a fixed visible history length.

## Verification

- `pytest tests/test_dsp.py tests/test_raster.py tests/test_frequency_detector.py
  tests/test_config_cdc.py -q`: **73 passed**, nine existing Amaranth
  `reset=` deprecation warnings; run with `TILIQUA_ASQ_I_BITS=2` and
  `TILIQUA_ASQ_WIDTH=18` against this worktree's `src`.
- `cargo check --locked --target riscv32im-unknown-none-elf`: passed for OSCIO
  firmware after the label edits.
- `docs/oscio_review_probes.py` retains the capture-burst and native-frequency
  reproductions. Run from `gateware` with `PYTHONPATH=src`, the same ASQ
  environment, and an interpreter containing the project's Amaranth dependencies.
- Existing passing tests do not exercise these burst, 48 kHz, DC-step, and
  short-display cases. Add regressions when implementing fixes.
- No new FPGA route or hardware test was performed. These findings do not
  establish the cause of the earlier HDMI lock failures. Static clock-domain
  timing results alone do not prove all clock-domain crossings and external
  interfaces correct.
