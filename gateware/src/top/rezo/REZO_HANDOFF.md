# REZO development handoff

This file is the starting context for the next Codex task working on REZO. Read
it together with [`BUILD_PERFORMANCE.md`](BUILD_PERFORMANCE.md) and
[`Rezo_Feature_Ideas_By_Complexity.md`](Rezo_Feature_Ideas_By_Complexity.md)
before changing the design.

## 2026-08-05 UI polish pass

The hardware review led to a consistency and legibility pass:

- BANK PRESET, BANDS PRESET, and FILTER TYPE now share one selector geometry;
  their labels are vertically aligned and each value is centered by its own
  visible width.
- BANK and FEEDBACK use `FREQ:` instead of the abbreviated `FRQ`.
- FEEDBACK navigation now follows the screen from top to bottom: page, ten
  band toggles, then KNEE, CEIL, and DAMP.
- ADVANCED is now OPTIONS. PALETTE and SAVE DEFAULT share a right-aligned label
  column, equal button spacing, and centered button text.
- Disabled BANK bands retain a dim empty frame on BANK and FEEDBACK, plus dim
  top/bottom ghost rails at all four GROUPS assignments, instead of
  disappearing completely.
  FILTER still exposes all ten resonators, and the BANDS page retains its
  explicit enable buttons.
- BANK/FILTER changes now slew the existing ten shared band gains toward the
  new mode's targets. A full-scale transition takes about 1.33 ms at 192 kHz,
  avoiding an instantaneous gain-vector change without adding an output
  multiplier or transition counter.

All 35 targeted tests pass. The exact commit-stamped native-Yosys W160 design
uses 24,090 packed cells (198 free), 169 fewer cells than the prior flashed
build. Seed 7 passes all four clocks at 403.55 MHz DVI5X, 72.91 MHz AUDIO,
66.67 MHz SYNC, and 74.95 MHz DVI. Seeds 6 and 8 fail only DVI; seed 8 is short
by 0.12 MHz.

The first polish archive was
`gateware/build/rezo-r5/rezo-49783e4b-r5.tar.gz`. Its seed-7 `top.bit` and the
archived copy both have SHA-256
`d402cf78143865bfed8ec99385d7b1b2bba747232723c550c2aac4bfeeacf715`;
the archive SHA-256 is
`4b39ae438b017ecd87ed183afe3e0e05ff620e8bf9f65a3554a55841341e6624`.
It was flashed successfully to slot 4 on 2026-08-05. Bitstream and manifest
programming plus FPGA refresh completed without error, and option storage was
preserved. It was superseded later the same day by the GROUPS-ghost build below.

Forty full rectangular GROUPS ghosts exceeded capacity by 149 packed cells.
The final renderer shares one row-edge test across the complete 10x4 grid and
draws dim top/bottom rails instead. Exact commit `b2812acc` uses 24,223 packed
cells (65 free), with seed 6 passing at 387.00 MHz DVI5X, 72.22 MHz AUDIO,
62.50 MHz SYNC, and 79.25 MHz DVI. The final validation archive is
`gateware/build/rezo-r5/rezo-b2812acc-r5.tar.gz`. Its seed-6 `top.bit` and the
archived copy both have SHA-256
`c374120f425c1fca752294a1625611dacb64317732f43c069d4f592cadffae3e`;
the archive SHA-256 is
`97f1d5a2fca4bf0fcba4780d3ddf8d94fa329f520c3dc3214f89a3880cc1b21e`.
It was flashed successfully to slot 4 on 2026-08-05, with option storage
preserved.

## 2026-08-04 BANDS UI update

The journal optimization first increased free space from 504 to 1,082 packed
cells. That room now carries a complete editable BANDS page:

- LEGACY: `29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000 Hz`
- OCTAVE: `31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000 Hz`
- PERCEPT: `50, 150, 300, 500, 770, 1150, 1700, 2700, 5300, 12000 Hz`
- USER: the editable current working layout
- A separate enable/disable toggle for each of the ten bands

Frequency editing uses a 116-position logarithmic grid: the exact 29-value
union of the factory frequencies plus three subdivisions following each
center. Click a band frequency, rotate, then click to apply. Slow turns advance
one position for precision; rapid turns advance eight. Any edit selects USER
automatically. USER is the current working vector rather than a separate hidden
snapshot, and SAVE DEFAULT persists and restores the active frequencies and
enables exactly.

The hardware photo of the first implementation exposed an ambiguous tall-fader
metaphor and overlapping text. The polished page now has a labeled PRESET
selector, a row of ten ENABLE buttons, and a separate row of ten SET FREQ
buttons. It removes redundant band numbers and shows the selected value as an
exact five-digit Hz readout. When no band target is selected, the readout is
blank.

The BANDS page is BANK-only and is skipped entirely in FILTER navigation.
Disabling a band blanks its BANK column and its BANK group/feedback control.
The blank target can still be traversed for one encoder detent, but clicking it
cannot enter edit mode or change the hidden value. A full automatic navigation
skip overflowed the FPGA. FILTER ignores the enable mask and continues to use
all ten resonators.

Final measured resources (`BANDS-FINE-COMMIT-S6`, commit `04dc8771`):

- LUT4: 20,577
- Packed cells: 24,259 / 24,288
- Free packed cells: **29**
- FF: 6,510
- BRAM: 19 / 56
- DVI5X: 442.48 MHz (required 371.33)
- AUDIO: 72.68 MHz (required 49.15)
- SYNC: 63.84 MHz (required 60.00)
- DVI: 76.78 MHz (required 74.25)

This candidate requires native Yosys 0.66+152 and the staged mapping recipe in
`RezoBeamTop.script_after_synth`: an initial density-oriented `abc`, followed by
`abc9 -W 160`, then ECP5 cell mapping. The project's pinned YoWASP Yosys 0.52
maps the fresh source over capacity. The cutoff table is a synchronous
block ROM; the next band is explicitly prefetched after the current band's two
SVF passes, preserving the known-good DSP vector without an illegal asynchronous
block-RAM port.

The previously flashed `rezo-69904c1e-r5.tar.gz` contains the initial UI seen in
the hardware photo, but it was packaged after `--skip-build` reused an older
generated RTL/bitstream. Its source provenance is therefore not exact, and it
does not contain the polished page or guaranteed synchronous-prefetch fix. Do
not treat it as the validation candidate. The rack was powered down before this
pass, so the corrected build must not be flashed until the user is present.

The corrected validation archive is
`gateware/build/rezo-r5/rezo-9fe65f4e-r5.tar.gz`. Its embedded `top.bit` matches
the locally packed seed-1 bitstream at SHA-256
`0d6b46064211777831d31c7d49e38ffb162147ff435a1bda718cdea9a38f2e43`.
It was flashed successfully to slot 4 on 2026-08-04; bitstream and manifest
programming plus FPGA refresh completed without error, and option storage was
preserved. Physical UI/audio/save validation is pending.

The new BANK-only/fine-frequency validation archive is
`gateware/build/rezo-r5/rezo-04dc8771-r5.tar.gz`. Its seed-6 `top.bit` and the
archived copy both have SHA-256
`da757347f33706ac317b8559313927b6a136a713a04943d5b418776348c5397e`.
It was flashed successfully to slot 4 on 2026-08-04. Bitstream and manifest
programming plus FPGA refresh completed without error; option storage was
preserved. Physical UI/audio/save validation is pending.

The clocked sample-and-hold, shift-register, rotate, and random-walk family is
now assigned to a separate alternate bitstream. Do not attempt to squeeze those
features into the 29 cells remaining here. They should share one clocked,
control-rate transformation engine built from the optimized pre-BANDS commit.

## Repository state

- Repository: `/Users/naenyn/git/tiliqua`
- Branch: `rezo`
- Initial BANDS implementation: `69904c1e rezo: add editable band layouts`
- `Erica Resonant FB Notes.txt` is an untracked, user-owned reference file at
  the repository root. Do not delete, stage, or commit it unless explicitly
  requested.
- The parent commit is the optimized, behavior-preserving version-1 journal
  baseline with 1,082 free packed cells.

## User working preferences and safety rules

- Do not revert to a previous implementation without asking. Diagnose and fix
  forward; this is an exploratory passion project and preserving useful work is
  more important than quickly returning to an older build.
- Flashing REZO is allowed when needed. Use slot 4 unless the user says
  otherwise. Never hardcode slot 4 into persistence logic: persistent state
  must always use the bootloader-validated slot from which REZO is running.
- Do not change the UI as part of an optimization unless the user approves the
  UI change first. Internal implementation changes that preserve the displayed
  pixels and control behavior are encouraged.
- Preserve audio behavior during performance work. Add or extend tests before a
  risky refactor and compare the DSP path bit-for-bit where practical.
- Keep the user informed during long builds; FPGA routing may take a long time.
- Never treat a small source change as a small hardware change. This design is
  congested and placement is highly seed-sensitive.

## Current product state

REZO is a CPU-free, lean 1280x720p60 Tiliqua R5 bitstream running audio at
192 kHz. Its major implemented features are:

- Ten time-multiplexed resonator bands.
- A BANDS page with three factory center-frequency layouts, a USER layout,
  stepped per-band frequency editing, and per-band enable controls.
- BANK mode with editable bipolar band levels, factory shapes/presets,
  resonance, feedback, and resonator drive.
- FILTER mode that uses the ten bandpass resonators to approximate low-pass,
  high-pass, band-pass, and notch responses, with frequency, continuously
  variable slope, width, resonance, and drive.
- BANK input assignment: each physical input can be audio or CV. Audio inputs
  are mixed with individual gain; CV inputs can target resonance, feedback, or
  one of four band groups with attenuverters.
- FILTER modulation matrix: IN1-IN3 can each modulate frequency, resonance,
  width, slope, and drive through signed depths.
- Four band groups and per-band group assignment.
- Four-output routing matrix with independent unipolar send levels for each
  group and dry signal.
- Per-band feedback-send enable controls and feedback safety controls.
- Base/effective modulation visualization: unmodulated values retain a marker
  and modulation is shown using the semantic modulation palette role. This is
  implemented for BANK bands and controls and FILTER controls, including
  drive.
- Five semantic color palettes. The selected palette is now part of the saved
  REZO default state rather than an independently autosaved preference.
- One-click `SAVE DEFAULT` on the OPTIONS page. There is intentionally no
  confirmation state. A successful record restores the complete current REZO
  state when the same bitstream slot is booted again.

The user hardware-tested the pre-optimization save/restore workflow
successfully. That implementation was also flashed to slot 4. The archive
filename
used for the last flash carried the previous commit ID because the persistence
changes were uncommitted at build time; those exact changes are now commit
`6a4a4ab1`.

## Persistence safety and implementation notes

Persistence caused a bootloader scare during development, so changes here
must be treated carefully.

- The journal reserves only the two 4 KiB option sectors belonging to the
  active, bootloader-validated slot.
- No arbitrary software-provided flash address is accepted.
- An invalid or unavailable boot-slot record disables saving safely.
- Records are dual-sector, generation-numbered, versioned, CRC-checked, and
  verified after programming.
- Version 2 saves 46 16-bit state words. Its four-word tail packs ten 5-bit
  coarse frequency indices, ten enable bits, and the selected layout; twenty
  existing padding bits elsewhere in the record carry two fine bits per band.
  Version-1
  42-word records remain readable and migrate to LEGACY with all bands enabled.
  The on-flash format still reserves room for up to 2 KiB of future state.
- State capture/restore uses a circular 46-cycle scan stream to avoid a large
  addressable UI-state mux.
- The snapshot memory must remain inferred as block RAM. Distributed RAM cost
  roughly 700 packed cells in an earlier experiment.
- The SPI bridge enforces four full 60 MHz cycles of physical CS#-high recovery
  between flash transactions. The original one-cycle gap produced SAVE ERROR
  and no committed record. Do not weaken this timing without hardware-level
  evidence and tests.
- The earlier boot failure was never conclusively explained. The present
  bounded addressing and hardware-tested journal work, but any persistence
  refactor should first prove all erase/program addresses remain inside the
  current slot's option window.

Key files:

- `gateware/src/top/rezo/persistence.py`
- `gateware/src/top/rezo/top.py`
- `gateware/src/tiliqua/periph/eurorack_pmod.py`
- `gateware/tests/test_rezo_persistence.py`
- `gateware/tests/test_i2c.py`

## Build-performance discipline

`BUILD_PERFORMANCE.md` is a required rolling engineering log, not optional
documentation. For every materially different synthesized/routed design:

1. Record the source change or experiment ID.
2. Record the placement seed.
3. Record LUT4, packed cells, free cells, FF, and BRAM.
4. Record every final post-route clock result: DVI5X, AUDIO, SYNC, and DVI.
5. Keep failed experiments and aborted/pathological routes in the notes so the
   same dead end is not repeated.
6. Do not compare pre-route timing estimates as though they were final timing.
7. Run more than one seed for an important candidate when time permits.

Formal historical optimization baseline (`OPT-BASE`, commit `2b464d50`, seed
4):

- LUT4: 18,282
- Packed cells: 21,668 / 24,288
- Free packed cells: 2,620
- FF: 5,894
- BRAM: 10 / 56
- DVI5X: 404.53 MHz (required 371.33)
- AUDIO: 64.35 MHz (required 49.15)
- SYNC: 64.86 MHz (required 60.00)
- DVI: 79.56 MHz (required 74.25)

Previous one-click-save build (`SAVE-ONE-CLICK-S4`, seed 4):

- LUT4: 20,312
- Packed cells: 23,784 / 24,288
- Free packed cells: **504** (about 2.1%)
- FF: 6,579
- BRAM: 13 / 56
- DVI5X: 396.35 MHz (pass)
- AUDIO: 74.48 MHz (pass)
- SYNC: 64.87 MHz (pass)
- DVI: 78.11 MHz (pass)

The pre-BANDS optimized build passes at seeds 8, 4, and 2 with 1,082 free
cells. BANDS plus the BANK-only/fine-frequency pass uses 1,053 of those cells
and the final commit-stamped seed-6 candidate leaves 29.
Packed-cell use is not monotonic with source-code size: shortening labels and
several apparently simpler lookup structures mapped substantially worse.
DVI5X is largely the existing TMDS serializer and is highly seed-sensitive,
but overall packing congestion is also a real constraint.

## Test baseline

The complete targeted regression set contains 35 tests, including exact USER
working-vector semantics, all ten persisted frequencies/enables, version-1
migration, the known-good DSP vector, two-row BANDS geometry, a five-digit
frequency readout, mode-change gain slew, disabled-band frames, and programming
across a 256-byte flash page:

```sh
pdm run pytest \
  tests/test_rezo_ui.py \
  tests/test_rezo_display.py \
  tests/test_rezo_persistence.py \
  tests/test_rezo_compare_path.py \
  tests/test_i2c.py
```

Run from `gateware/` if the repository's PDM command expects that directory.
Also run `git diff --check` before builds and commits.

Normal build command:

```sh
TILIQUA_REZO_SEED=<seed> pdm run rezo build --fs-192khz
```

That command uses the pinned Yosys and currently exceeds capacity, but it does
generate a fresh `top.il` and a `top.ys` containing the staged recipe. Run that
script with the native OSS CAD Suite Yosys, then route the resulting JSON:

```sh
source ~/.zshrc
yosys -l top-native.rpt top.ys
nextpnr-ecp5 --timing-allow-fail --seed 1 --25k --package CABGA256 --speed 6 \
  --json top.json --lpf top.lpf --textcfg top.config --log top.tim
ecppack --freq 38.8 --compress --bootaddr 0x0 \
  --input top.config --bit top.bit --svf top.svf
```

Normal flash command from `gateware/`:

```sh
pdm flash archive build/rezo-r5/<archive>.tar.gz --slot 4 --noconfirm
```

Only flash a routed build after every required clock passes. When evaluating
seeds of an unchanged synthesized design, reuse the exact `top.json` for direct
nextpnr routing so synthesis variation is not confused with placement
variation.

## Immediate next task: hardware validation

1. Confirm boot, audio, all pages, palette rendering, and modulation display.
   Check selector alignment, OPTIONS spacing, disabled-band frames, and the
   corrected FEEDBACK navigation order against the hardware photos.
2. Exercise BANK/FILTER changes with sustained and transient-rich input. The
   new shared-gain slew removes the direct band-gain discontinuity; if a pop
   remains, the next candidate should fade the complete four-output mix so
   mode-specific routing and dry sends also transition smoothly.
3. Confirm a previous version-1 default restores as LEGACY/all-enabled while
   preserving every pre-BANDS setting.
4. Exercise every layout, frequency editing, enable toggles, and FILTER mode.
5. SAVE DEFAULT, reboot slot 4, and confirm the complete version-2 state restores.
6. Develop clocked modes only as a separately measured alternate bitstream.

## Desired next functionality

The next major desired feature is a clocked shift-register mode. The roadmap
ranks it as moderate complexity. The likely foundation is a shared,
time-multiplexed control-rate band transformation engine:

```text
manual/preset levels
    -> shape source
    -> rotate / tilt / morph
    -> motion or clocked source
    -> existing group and CV modulation
    -> smoothing
    -> ten time-multiplexed resonators
```

For shift-register mode, plan for:

- A physical input configured as clock, with threshold and hysteresis.
- A source value (probably another CV input initially) shifted into one end of
  the ten-band vector.
- Atomic publication of a completed ten-band state so the audio engine never
  sees a partially shifted vector.
- Forward direction first; reverse, ping-pong, random, and reset are later
  enhancements.
- Existing base/effective modulation visualization should consume the computed
  state rather than adding arithmetic to the pixel renderer.
- State fields must be versioned and included in SAVE DEFAULT only after the
  basic mode is stable.

Before implementing it, settle the minimal first-version interaction with the
user. A new mode/page or altered input page is a UI change and requires
approval. The performance pass is now complete; hardware-validate it before
spending the recovered cells.

Lower-risk features that may fit before or alongside that foundation are more
factory preset shapes and a simple band-enable mask. Tilt, rotate, randomize,
random walk, diffusion, LFO phase spreading, and more advanced spectral modes
should still be isolated from the first shift-register build so their measured
costs do not become entangled.

## Longer-term direction

The full ranked roadmap is in `Rezo_Feature_Ideas_By_Complexity.md`. Important
product goals discussed with the user include:

- Continue supporting BANK and FILTER modes rather than copying the Erica
  module exactly.
- Preserve resonance as a primary, immediately accessible control.
- More characterful but controlled resonance/feedback/drive behavior.
- Potentially configurable band frequencies and frequency-layout presets.
- Additional motion features such as tilt, rotation, LFO phase spread, random
  walk, diffusion, and shift-register operation.
- Future user presets or multiple saved states, after the single default-state
  journal is proven and resource headroom exists.
- Potential stereo or multiple-audio-input workflows, assignable CV, and
  richer output routing; these are substantially larger than simple
  control-rate transformations.
- A CLOCK or SHIFT REGISTER mode is currently more important than scopes or a
  spectrum analyzer. Visual analysis features remain low priority.

The guiding constraint is to keep REZO musically interesting and visually
coherent while maintaining 720p60 HDMI timing and substantial modulation
capacity. Optimize shared machinery before adding parallel copies of feature
logic.
