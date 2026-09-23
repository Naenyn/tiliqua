# OSCIO development handoff

Updated: 2026-09-14

This document describes the implemented OSCIO scope and CV/LFO design,
its verification state, and the main constraints to preserve during future
development.

The frequency-state RAM experiment was also not retained: it saved 98 COMB
and 620 FF, but its strict seed-3 route missed the HDMI serializer target
(369.96/371.33 MHz). Production frequency logic was restored exactly; no
shared video/clock code changed and nothing was flashed. The test-only
prototype, equivalence coverage, and results are documented in
`OSCIO_FREQUENCY_MEMORY_2026-09-14.md`.

The serialized peak-tracker experiment was rejected: preserving ADC bursts
reduced the net saving to only two logic cells. Source and hardware retain the
smoke-tested parallel implementation, with an additional burst regression.
See `OSCIO_SERIALIZED_PEAKS_2026-09-13.md` for the measurements and
`OSCIO_CORRECTNESS_REVIEW_2026-09-13.md` for the retained build.

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

Clean acquisition now uses a local three-sample median only near detected
edges. It preserves monotonic transitions bit-for-bit instead of snapping to
distant window endpoints, which could fabricate backward hooks on rounded
square-wave edges. It may reduce genuine isolated extrema as well as spikes;
raw bypasses this display-only cleanup. Both modes retain display resampling.

Fast-sweep continuity: adjacent column envelopes now meet at the midpoint
between the last sample in the old column and the first in the next. This
removes the former 12-pixel connection threshold without extending both
columns over the entire transition. Pen lifts still break connections.

Column capture now exposes `sample_ready` and holds each four-channel bundle
until its coordinate pipeline is consumed. The scope merges all channels
atomically and propagates stalls upstream. This accepts one bundle every eight
60 MHz clocks (7.5 million bundles/s), above the 1.536 million/s display rate,
while avoiding the old burst-induced X/Y metadata overwrite and sample loss.
The burst and continuity regressions are in `tests/test_scope_continuity.py`;
the full DSP-chain regression also exercises the real scope backpressure.

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

Low/high and peak-to-peak include every native-rate input sample, not just
the 1 kHz firmware polls. Parallel trackers accept even consecutive-clock
bursts from the ADC crossing. Atomic four-channel snapshots partition samples
into non-overlapping windows; a coincident sample belongs to the completed
window. Firmware merges peaks into its existing slowly released peak hold.
The level average remains at 1 kHz. Entering CV/LFO discards scope-mode peaks.
Frequency is the latest rising-crossing interval, not a repeatability test;
the help now states this explicitly and its scroll range is regenerated.

Trace capture is invalidated after all new view geometry has been published to
hardware. This ordering prevents a one-time vertical connector from old scope
coordinates when entering monitor mode. Progressive capture also rearms at the
current sweep position after invalidation instead of waiting for an entire
offscreen pass.

## Display layouts

Runtime video dimensions select the CV/LFO layout; separate artifacts are not
required.

- Rectangular displays at least 688 pixels tall show all four lanes.
- Shorter rectangular displays paginate into CH 0-1 and CH 2-3, using the full
  rectangular frame. This includes 640x480, 800x600, and 1024x600.
- A 720x720 display uses a centered circular-safe frame and paginates the monitor
  into CH 0-1 and CH 2-3.
- The channel-pair selector appears whenever the layout is paginated.
- The threshold reserves 172 pixels per lane for its 168-pixel statistics
  bitmap and separators. It uses current logical dimensions, including rotation.

The normal menu is right-aligned on rectangular video modes and centered inside
the safe region on 720x720 video.

## Menu organization

All user-facing input/output references use the physical jack labels **0-3**:
input 0 passes through to output 0, and likewise for 1, 2, and 3. Trigger
source values and CV/LFO statistics use the same numbering. Legacy Rust
option identifiers (`Ch1` through `Ch4`, `ch1_*` through `ch4_*`, and
`Chan12`/`Chan34`) are retained for saved-setting compatibility; they map in
order to physical jacks 0-3. Hardware indices were already zero-based.

The menu is mode-aware and begins on the `OSCIO` page with `mode` as the first
item.

Scope navigation:

1. `OSCIO`: mode, time/div, acquire
2. `CH 0-1`: offset, scale, and enable for channels 0 and 1
3. `CH 2-3`: offset, scale, and enable for channels 2 and 3
4. `TRIGGER`: type, source, level, and filter
5. `DISPLAY`: grid, grid intensity, trace intensity, hue, and palette
6. `SYSTEM`: UI hue, hide behavior, rotation, save, and reset
7. `HELP`

CV/LFO navigation:

1. `OSCIO`: mode, time/div, max freq, plus channels on paginated displays
2. `RANGES`: CH0 through CH3
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

Latest resource/correctness pass: see `OSCIO_RESOURCE_REVIEW_2026-09-13.md`.
Archive `oscio-2ed89680-resource-spread0-seed3-r5.tar.gz` uses strict timing,
seed 3, 192 kHz, ASQ 2/18, and spread spectrum disabled. All clocks pass,
including sync at 67.25 MHz against 60 MHz. Packed combinational use falls
from 22,672 to 22,521 cells; sample widths and the renderer are unchanged.
This also corrects signed DC-level filtering bias and 48 kHz activity windows.

Latest continuity/backpressure build (2026-09-13):
`oscio-7addc0f9-continuity-spread0-seed3-r5.tar.gz`, strict timing, seed 3,
192 kHz, ASQ 2/18, and `spread_spectrum=0.0`. Final routed maxima are
472.81 MHz dvi5x, 80.61 MHz dvi, 57.63 MHz audio, and 63.01 MHz sync:
all pass their unchanged targets. Bitstream SHA-256:
`61d880ff9e97f68b9a1c8f62f2dc97fb250379b48303a24d671f31ddcb3ffbc6`.
The relevant suite passes 78 tests plus 12 subtests, including burst
equivalence, small/large slope connectivity, pen lift, rotations, lane clipping,
and the DSP chain connected to the actual scope input. The user confirmed the
rendering improvement on hardware, and it was committed as `2ed89680`.
The archive tag is the pre-fix checkpoint. Earlier builds below remain references.

The 2026-09-13 conservative edge-cleanup build uses `--timing-strict --seed 3
--spread-spectrum 0.0 --fs-192khz` and ASQ 2/18. Its final routed clocks all pass:

```text
dvi5x 403.71 MHz required 371.33 MHz
dvi    79.50 MHz required  74.25 MHz
audio  58.88 MHz required  49.15 MHz
sync   61.63 MHz required  60.00 MHz
```

Archive: `oscio-3015209c-edge-clean-spread0-seed3-r5.tar.gz`. Its base commit
tag does not include the uncommitted cleanup and CH0-CH3 labeling changes.
Bitstream SHA-256:
`4c7686d01711cf5f33d041293d441b4a0e05d94ad81af2cc228e305f9554237a`.
The selected DSP/raster/frequency/CDC suite passes 75 tests plus 12 subtests;
the rounded-edge regression fails in six subcases against the old code.
Hardware visual confirmation is still required. The known-working earlier
route below is retained as a reference, not the bitstream in this new archive.

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
  pdm run oscio build --fs-192khz --timing-strict --seed 3 --spread-spectrum 0.0

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
