# OSCIO development handoff

Updated: 2026-09-02

This document describes the implemented OSCIO scope and CV/LFO design,
its verification state, and the main constraints to preserve during future
development.

## Working conventions

- Repository: `/Users/naenyn/git/tiliqua`
- Source `~/.zshrc` before building or flashing.
- OSCIO is normally flashed to slot **7**.
- The user's fork is `git@github.com:Naenyn/tiliqua.git` (`origin`); the official
  repository is `https://github.com/apfaudio/tiliqua.git` (`upstream`).
- Preserve the existing VexiiRiscv CPU choice unless the user requests a CPU
  change.
- Do not include generated build directories, `.DS_Store`, experimental REZO
  files, or unrelated generated CPU netlists in OSCIO commits.

## Implemented views

OSCIO provides two runtime-selectable views in one bitstream. The low-frequency
voltage view is labeled `CV/LFO` in the user interface; implementation names
continue to use `Monitor` internally.

### Scope

The normal four-channel oscilloscope supports:

- independent channel enable, vertical offset, and volts/division;
- a shared timebase;
- rising, falling, auto-rising, auto-falling, and free-running acquisition;
- selectable trigger channel, level, and low-pass filter;
- clean and raw acquisition modes;
- atomic fast-sweep rendering and progressive slow-sweep rendering;
- edge-aware interpolation for sharp waveforms; and
- grid, palette, hue, intensity, rotation, and persistent settings.

### CV/LFO

The CV/LFO view is intended for control voltages, gates, envelopes, and LFOs.
It provides:

- one history lane per calibrated analog input;
- level, low, high, peak-to-peak, frequency, and period statistics;
- a shared monitor timebase independent of the scope timebase;
- per-channel full-window voltage ranges of `-5..+5 V`, `-10..+10 V`,
  `0..+10 V`, and `0..+5 V`;
- selectable maximum frequency from 0.25 Hz through 20 Hz, defaulting to 20 Hz;
- three-second admission below the frequency limit;
- one-second exit grace above the limit, with immediate removal at 1.5 times
  the selected limit; and
- clipped traces whose plot bounds begin to the right of the statistics column,
  so history is never rendered behind the text.

Statistics are drawn into PSRAM-backed 1bpp scratch panels and diffed against
their previous contents. This updates changed glyph pixels without visibly
blanking the whole statistics area.

Trace capture is invalidated after all new view geometry has been published to
hardware. This ordering prevents a one-time vertical connector from old scope
coordinates when entering monitor mode. Progressive capture also rearms at the
current sweep position after invalidation instead of waiting for an entire
offscreen pass.

## Display layouts

Runtime video dimensions select the CV/LFO layout; separate artifacts are not
required.

- Rectangular displays show all four lanes across the active display.
- A 720x720 display uses a centered circular-safe frame and paginates the monitor
  into CH 1-2 and CH 3-4.
- The channel-pair selector appears only on the circular display.

The normal menu is right-aligned on rectangular video modes and centered inside
the safe region on 720x720 video.

## Menu organization

The menu is mode-aware and begins on the `OSCIO` page with `mode` as the first
item.

Scope navigation:

1. `OSCIO`: mode, time/div, acquire
2. `CH 1-2`: offset, scale, and enable for channels 1 and 2
3. `CH 3-4`: offset, scale, and enable for channels 3 and 4
4. `TRIGGER`: type, source, level, and filter
5. `DISPLAY`: grid, grid intensity, trace intensity, hue, and palette
6. `SYSTEM`: UI hue, hide behavior, rotation, save, and reset
7. `HELP`

CV/LFO navigation:

1. `OSCIO`: mode, time/div, max freq, plus channels on 720x720
2. `RANGES`: CH1 through CH4
3. `DISPLAY`: trace intensity, hue, and palette
4. `SYSTEM`
5. `HELP`

Scope-only channel, trigger, and grid controls are omitted in CV/LFO mode.
Likewise, the circular pagination control is omitted when it has no effect.

## Native-rate frequency detector

Frequency classification is implemented in FPGA logic by
`src/tiliqua/raster/frequency_detector.py`. It observes the calibrated 192 kHz
native input stream rather than the slower firmware statistics poller or the
display-resampled stream.

The detector:

- registers each native sample bundle immediately;
- tracks a slowly released min/max envelope per channel;
- derives offset-independent midpoint and Schmitt thresholds;
- counts 24-bit native-sample periods between accepted rising crossings;
- invalidates stale or insufficient-amplitude measurements;
- independently detects multiple crossings in a short activity window; and
- snapshots all four periods and status bits coherently through scope CSRs.

Firmware performs frequency/period formatting and combines the detector result
with the slower voltage statistics. The reported value is a threshold-crossing
rate, which is appropriate for clean LFOs and out-of-band classification but is
not intended as musical fundamental estimation for arbitrary complex audio.

## Important implementation files

- `src/top/oscio/top.py`: SoC integration and on-device help source
- `src/top/oscio/fw/src/main.rs`: runtime integration and view transitions
- `src/top/oscio/fw/src/options.rs`: options, page lists, and mode-aware navigation
- `src/top/oscio/fw/src/menu_draw.rs`: compact menu layout
- `src/top/oscio/fw/src/monitor.rs`: monitor layout, statistics, and gating
- `src/tiliqua/raster/frequency_detector.py`: native-rate detector
- `src/tiliqua/raster/digital_scope.py`: detector and capture CSR integration
- `src/tiliqua/raster/scope_capture.py`: capture and invalidation behavior
- `src/tiliqua/raster/scope_overlay.py`: progressive trace rendering
- `tests/test_frequency_detector.py`, `tests/test_raster.py`, and
  `tests/test_dsp.py`: relevant regression coverage

Generated PAC sources and `fw/memory.x` are committed alongside their source
definitions when the build changes them.

## Timing and resource state

The earlier default route missed the 60 MHz sync target. The retained seed-3
route closes all domains; the relevant report is
`build/oscio-r5/top-seed3-rangefix.tim`:

```text
dvi5x  386.85 MHz required 371.33 MHz
dvi     78.91 MHz required  74.25 MHz
audio   58.60 MHz required  49.15 MHz
sync    62.67 MHz required  60.00 MHz
```

The timing-clean `top.bit` SHA-256 is:

```text
d2140a28d1bae2aa7a513eda5dca596b5127083d5256229914a1cd1bac413554
```

Firmware-only builds should preserve that bitstream unless gateware changes
require a new full place-and-route run. For new gateware, keep wide arithmetic
registered or serialized, avoid FPGA division, and verify every clock domain.

## Build and verification

Run from `/Users/naenyn/git/tiliqua/gateware`:

```zsh
source ~/.zshrc
pdm run pytest tests/test_dsp.py tests/test_raster.py tests/test_frequency_detector.py

TILIQUA_ASQ_I_BITS=2 TILIQUA_ASQ_WIDTH=18 \
  pdm run oscio build --fs-192khz

pdm flash archive build/oscio-r5/<archive>.tar.gz --slot 7 --noconfirm
```

For firmware-only changes, add `--fw-only`. Always run `git diff --check` and
verify that a firmware-only archive still contains the intended `top.bit`.

The Rust firmware can be checked with:

```zsh
cd src/top/oscio/fw
cargo fmt --check
cargo check --target riscv32im-unknown-none-elf
```

Host-side `cargo test` is not currently a valid verification path because the
firmware dependency graph includes `riscv-rt` target-specific sections.
