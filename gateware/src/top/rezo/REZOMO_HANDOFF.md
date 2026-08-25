# REZOMO development handoff

This is the canonical continuation document for current REZOMO work. Read it
alongside [`BUILD_PERFORMANCE.md`](BUILD_PERFORMANCE.md) before changing,
building, or flashing REZOMO.

The older [`REZO_HANDOFF.md`](REZO_HANDOFF.md) contains useful project history,
including earlier REZOMO notes, but its filename is now ambiguous. Keep it as a
historical reference; use this file for the current state and operating rules.

## 2026-08-15 STREZO curve and capacity checkpoint

The consolidated `codex/rezo-family` branch now includes STREZO. Commit
`06608b0d` checkpoints the configurable CROSS response before the capacity
pass. CROSS CURVE lives on OPTIONS, offers the full names LINEAR and
LOGARITHMIC, and persists in a formerly reserved state bit. The CROSS page
retains the full LAYOUT label and full layout names. LOGARITHMIC is an early
response curve (`log1p(7x) / log(8)`), not the rejected late `x^2` curve; both
curves retain zero and full-scale endpoints, including intentional instability
at maximum.

The retained capacity optimization changes display telemetry only. Ten copies
of the BANK band-height arithmetic are replaced by one dual-port block-ROM
lookup scanned across the ten bands in ten DVI clocks (about 0.14 microseconds).
Audio DSP, CROSS coefficients, feedback topology, motion, and encoder behavior
are unchanged. The native display regression suite passes all 13 tests.

The standard build now uses 19,661 total LUT4, 22,857 packed cells (1,431 free),
6,875 FF, and 21 BRAM. This recovers 1,393 packed cells from the 24,250-cell
pre-optimization candidate. Seed 4 failed DVI5X and SYNC and was not flashed.
Seed 16 passes at 387.00 MHz DVI5X, 73.36 MHz AUDIO, 67.81 MHz SYNC, and
77.64 MHz DVI; every clock passes the repository's 1.25 percent headroom gate.
The standard archive `strezo-2ec93a17-r5.tar.gz` was flashed successfully to
slot 4 on 2026-08-15 (`Refresh: DONE`). Its SHA-256 is
`eff8627058a3b94aece852eaa9589b6dccf9e8f9309deffba113b4282097a396`;
the packaged `top.bit` SHA-256 is
`e186a8d037962f3948f9a444e1d86f24201184acf8e08ce338d444825d9e1915`.

To conserve future model and wall-clock budget, do not begin with seed sweeps.
Run focused tests, extract fresh RTL with `pdm run <target> build --fs-192khz
--skip-build`, synthesize `top.ys`, and run nextpnr with `--pack-only`. Route
once only after the packed design has deliberate headroom. `--skip-build` now
extracts its BuildPlan and exits before archiving, preventing an older
`top.bit` from being mislabeled as a new profile build.
Use `--package-only` after placing a separately qualified route at `top.bit`;
it packages that existing image explicitly without elaboration or routing.

Commit `04c6e663` repairs the STREZO curve control observed on hardware. The
OPTIONS page now separates STATE AND DISPLAY from ADVANCED, renders exactly
one dynamic LINEAR/LOG value, and uses an outline rather than filling the chip
while editing. The CROSS LAYOUT chip now matches its centered eight-character
text lane. All 41 focused UI, DSP, and native-display tests pass; the curve-ROM
test proves that LINEAR and LOG select different effective CROSS coefficients.
The design packs to 22,937 cells (1,351 free). Seed 16 was rejected; seed 9
passes at 422.30 MHz DVI5X, 73.58 MHz AUDIO, 63.20 MHz SYNC, and 81.59 MHz DVI.
Archive `strezo-04c6e663-r5.tar.gz` was flashed successfully to slot 4. Its
SHA-256 is `d3af6d3b93ab7265ddd0840a9fbd5840c25a09d96c9b714d616f5abfa5627d0c`;
the packaged `top.bit` SHA-256 is
`c5f6d4ed0680fc98e90f87d19f82e9fcd1b04f94ca8c92ffc1aed2133c6589cc`.

Commit `72445513` adds symmetric horizontal padding to the CROSS LAYOUT chip
and changes OPTIONS navigation to PAGE -> PALETTE -> SAVE -> CURVE. Its seed-9
route leaves 1,336 cells free and passes at 437.45 MHz DVI5X, 73.23 MHz AUDIO,
63.25 MHz SYNC, and 82.12 MHz DVI. Archive `strezo-72445513-r5.tar.gz` was
flashed to slot 4 (`Refresh: DONE`), SHA-256
`b60e2eb20ec8ab376a238d5577f1aa65677fa7aac61e877470cdc726754bbca7`.

## 2026-08-24 CPU control-plane checkpoint

The active branch is converting REZOMO to the same lean CPU control-plane
architecture already hardware-accepted in REZO. See
[`REZOMO_CPU_ARCHITECTURE.md`](REZOMO_CPU_ARCHITECTURE.md) for the ownership
boundary and verification checklist.

The new `rezomo_cpu` target builds only the standard `1280x720p60` display. A
20 KiB VexiiRiscv program ROM runs encoder navigation, BANK/CLOCK state,
conditional SHIFT/ROTATE/TURING/WALK editing, and V1/V2/V3 persistence. The
audio DSP, CV paths, video renderer, LEDs, and bounded flash transaction engine
remain in gateware. The state-variable-filter update now also carries REZO's
pre-narrowing saturation fix so extreme resonance/feedback/drive can recover
after controls are reduced.

Focused CPU, DSP, display, and family-parity tests pass. Seed 1 was rejected at
59.45 MHz SYNC. Seed 2 passes the 3% release gate at 451.06 MHz DVI5X,
74.43 MHz AUDIO, 62.57 MHz SYNC, and 76.55 MHz DVI. It uses 22,334 TRELLIS_COMB
cells (91%), 8,131 TRELLIS_FF cells (33%), and 31 DP16KD blocks (55%). Record
the final clean archive, SHA-256, and slot-3 flash result here after packaging;
do not use either dirty archive.

Implementation commit `fef63fa8` supplies the qualified standard archive
`rezomo-cpu-fef63fa8-r5.tar.gz`. Its SHA-256 is
`93c8dfa15090f78ec3eccb36c731403dada97f313430d8742129036c92ba5067`;
the packaged `top.bit` SHA-256 is
`11813b91e199f178f67e96ae86e30fc49a5d5b0cf5cff1333986af0d265932c2`.
It was flashed successfully to slot 3 on 2026-08-24 (`Refresh: DONE`) and now
awaits the hardware verification checklist in `REZOMO_CPU_ARCHITECTURE.md`.

The first hardware pass exposed aliased names in the shared character ROM:
CV targets, DAMPING, PALETTE, and potentially CLOCK tables used bitwise-OR
addressing with unaligned table bases. The 2026-08-25 fix gives every table a
power-of-two-aligned span within the same 2K ROM and tests all 1,552 populated
character addresses for uniqueness. Seed 2 then missed the DVI release margin;
seed 3 passes every clock with the utilization and timing recorded in
`REZOMO_CPU_ARCHITECTURE.md`. Commit `646f6c6a` supplies the clean replacement
archive `rezomo-cpu-646f6c6a-r5.tar.gz`. Its SHA-256 is
`ffaeabe196eeb5767342d13d9bf96c4d1a3cb892762e8197a0d60543b231a300`;
the packaged `top.bit` SHA-256 is
`4c7aeec0b259b0e1b4663ef1719905b136a1bc2364e73c014cfb078fea738d50`.
The packaged bitstream exactly matches the qualified seed-3 route. It was
flashed successfully to slot 3 on 2026-08-25 (`Refresh: DONE`) and awaits
hardware verification of all CV target, DAMPING, PALETTE, and CLOCK names.

## 2026-08-25 CPU renderer congestion checkpoint

The dynamic character refresh writer is now ROM-driven instead of synthesizing
a 205-way address/data mux. All live text sources and the established
three-DVI-clock write cadence remain unchanged. The focused CPU/native-display
suite passes (`20 passed`), and the broader CPU/display/family contract suite
passes (`61 passed`).

Pack-only comparison against the corrected CPU build drops utilization from
22,659 to 22,014 TRELLIS_COMB cells, recovering 645 cells, while FF usage drops
from 8,212 to 8,206 and DP16KD usage rises from 31 to 32. Seed 7 is the retained
standard-display route: 425.71 MHz DVI5X, 74.62 MHz AUDIO, 64.20 MHz SYNC, and
79.30 MHz DVI. Every clock clears the 3% release gate; DVI is limiting at
6.80%. Seeds 4 and 5 passed nominal timing but missed the release margin. Seed
6 cleared the gate before the implementation commit, but the clean committed
build reached only 2.58% SYNC margin, so it was rejected.

Only the standard `1280x720p60` target was considered.
Implementation commit `5ea78921` supplies the exact qualified archive
`rezomo-cpu-5ea78921-r5.tar.gz`. Its SHA-256 is
`ca18a8b1ad17caf23ed72a773aaa879ed6f983965a70984bccedc9f115b17296`;
the packaged `top.bit` SHA-256 is
`9a044daef97305efd3d9b22b44c65af12b19583bedaf2b01c10462423253b9e3`.
The archive was flashed to slot 3 on 2026-08-25 (`Refresh: DONE`). The user
confirmed that the resulting video, interaction, and audio look good and
accepted REZOMO as complete. No circular build was made or flashed.

## Current status and next objective

REZO and REZOMO now have hardware-accepted CPU control-plane implementations.
There are no known remaining REZOMO implementation gaps outside the deferred
circular-viewport redesign. Further REZOMO changes should be driven by new
hardware findings rather than speculative cleanup.

The next objective is to convert STREZO to the same lean CPU architecture while
preserving its accepted DSP, renderer, navigation, persistence semantics, and
linked-stereo features. Start from the current
`codex/rezo-cpu-framebuffer-prototype` branch, whose accepted checkpoint is the
documentation commit following implementation commit `5ea78921`. A new session
may create `codex/strezo-cpu-control-plane` from that clean checkpoint if a
separate experimental branch is desired.

Use REZO and REZOMO as the CPU architecture references. STREZO's own accepted
CPU-less implementation remains authoritative for product behavior and visual
geometry; do not replace its unique CROSS, MOTION, linked-stereo routing, or
OPTIONS behavior with REZO/REZOMO semantics.

## Display and coordinate-space contract

The native design space is the official Tiliqua display, not the development
monitor:

- The official display is a circular `720x720` panel.
- All interactive page content is authored directly in the centered `508x508`
  safe square that fits completely inside that circle.
- In native `720x720` coordinates, the half-open safe-square bounds are
  `x = [106, 614)` and `y = [106, 614)`.
- The bitstream identity may occupy the otherwise unused top arc. Page frames,
  controls, labels, and other interactive content must remain inside the safe
  square.
- Geometry is expressed in final native pixels. Do not reintroduce a
  `720 -> 508` coordinate-compression lookup and do not scale text, rectangles,
  or controls independently.

There are two display targets:

### Standard development target: `1280x720`

- This is the display currently used for visual iteration and hardware testing.
- Render the native `720x720` canvas centered horizontally in the `1280x720`
  output; the native origin therefore receives a `+280` pixel X offset.
- Do not rotate.
- Do not scale.
- The UI is expected to look physically smaller on the standard monitor. That
  is intentional until a separate scaling feature is designed.

### Official circular target: `720x720p60r2`

- Keep the same native `720x720` canvas and centered `508x508` safe square.
- Apply the required 90-degree panel correction only in the final framebuffer
  address mapping.
- Do not scale the UI.
- Do not rotate or rewrite individual page geometry.

In short: author one native layout, preview it upright and unscaled on the
standard monitor, and rotate only the final circular-panel build.

## Proven reference state

REZO's native-coordinate conversion was tested on the official circular Tiliqua
screen and reported to fit correctly. Treat that result as proof of the display
contract above.

Important REZOMO migration commits on the current branch include:

- `324c3e55` — migrate the REZOMO UI to native display geometry
- `1fe69409` — polish shared UI controls
- `edbc20d9` — align the CLOCK settings layout
- `e6e5d25b` — record the CLOCK layout build

At the time this handoff was created, the branch was `rezomo`, with HEAD at
`e6e5d25b`. Always inspect the actual branch, HEAD, and worktree before resuming;
the identifiers above are landmarks, not instructions to reset.

## Accepted standard-target state

The standard `1280x720` UI pass is hardware-accepted. It includes deterministic
per-field chip widths and optical centering on BANK, INPUT, OPTIONS, and every
CLOCK algorithm; PAGE/PRESET/MODE BANK navigation; and the full `EVEN` preset
name. The final standard archive passed every constrained clock and was flashed
successfully to slot 4 with option storage preserved. The focused REZOMO
navigation and native-display suite passed all 24 tests on 2026-08-13 before
this state was committed.

An updated official-screen archive was subsequently built from exact source
commit `483f5680`. Seed 3 passes every circular-target clock and supplies
`rezomo-483f5680-720x720p60r2-r5.tar.gz`; its manifest explicitly records
`720x720p60r2`. The archive was prepared for external testing and was not
flashed to the standard rack display.

Untracked files and generated build output may still be present. They belong to
the user or the existing workflow; do not remove or rewrite them as cleanup.

The post-consolidation capacity pass produced standard-target commit
`cbd49d7c`. It leaves 310 packed cells free, up from 95 in the prior qualified
image, and passes the enforced 1.25% timing-headroom gate on all four clocks.
The exact archive `rezomo-cbd49d7c-r5.tar.gz` was flashed successfully to slot 4
on 2026-08-14 and is awaiting the user's hardware pass. The optimization keeps
the DVI PHY and persistence format unchanged; it retimes only SHIFT/WALK event
starts and two renderer lookup paths. The focused 39-test REZO-family suite
passes. See `REZO_FAMILY.md` and `BUILD_PERFORMANCE.md` for exact measurements
and hashes.

## Work completed so far

The following areas have already received native-coordinate and layout work:

- shared BANK/FILTER rendering and lower fader block
- INPUT ROUTING grouping and native geometry
- GROUPS row alignment
- OUTPUT ROUTING grid alignment and equal row spacing
- FEEDBACK control alignment and reusable band-enable-button presentation
- BANDS enable-button presentation
- OPTIONS value fields
- CLOCK page conversion to a single-column `CLOCKED SETTINGS` layout
- target-specific final address mapping for upright standard output and rotated
  circular output

The standard `1280x720` build is the active visual-development target. Do not
produce the circular build for every iteration; build it once the standard view
has been accepted.

## Completed chip-alignment pass

The deterministic chip-sizing and visual-centering iteration is complete and
accepted on the standard display:

- BANK MODE uses a fixed parity-balanced field that centers both BANK and CLOCK.
- INPUT ROUTING MODE and VALUE fields use semantic widths and centered glyphs.
- CLOCK / TURING CHANGE and LENGTH use independent content widths.
- CLOCK / WALK STYLE, DRUNK, and CHANCE use independent content widths.
- CLOCK / SHIFT DATA is sized for its own longest value.
- OPTIONS PALETTE is centered using the same fixed-field convention.

Focused pixel tests cover chip endpoints, stable semantic widths, glyph bounds,
row centers, navigation order, and safe-square bounds.

## Value-chip alignment contract

For a field whose possible values are, for example, `FOO`, `FOOBAR`, and
`SOMETHINGELSE`:

1. Determine the chip width from the longest possible value for that specific
   field, plus fixed left and right padding.
2. Keep that chip width fixed while the value changes; do not resize the chip to
   the current value.
3. Center the rendered glyph bounds horizontally within the chip.
4. Center the rendered glyph bounds vertically within the chip.
5. Treat odd leftover pixels deliberately so the optical result does not drift
   consistently toward the top or left.
6. Center the corresponding label vertically on the same row. Labels are
   normally right-aligned to the shared label/value boundary.

Do not infer visual centering from string padding alone when the font renderer's
baseline or glyph bounds make that insufficient. Derive row text coordinates
from the chip rectangle and the font metrics used by the renderer. Reuse one
helper so the rule is identical on BANK, INPUT, CLOCK, OPTIONS, FEEDBACK, and
future pages.

Fields may have different chip widths because they have different semantic
value sets. Values within the same field must share one stable width.

## Layout rules learned during the REZO conversion

- Define row or column centers once, then derive both labels and controls from
  those centers. Do not maintain unrelated arrays of guessed text coordinates.
- Center row labels on the actual control centerline, accounting for font
  baseline and glyph height.
- Center column headings above the actual control rectangles, including columns
  with longer headings such as `DRY`.
- Use equal arithmetic row spacing where rows are intended to be uniform.
- Keep shaded section backgrounds large enough to enclose every child with
  deliberate padding.
- Keep labels outside bright value chips. The chip represents the changing
  value, not the label.
- Where a repeated UI element exists, such as ten band-enable buttons, use the
  same dimensions, spacing, and rendering on every applicable page.
- For faders, derive the label center from the fader rectangle rather than
  nudging each label independently.
- Preserve the REZO convention that AUDIO inputs hide or skip the inapplicable
  DEPTH control.

## Relevant files

- `gateware/src/top/rezo/top.py` — REZO/REZOMO gateware target and display-mode
  mapping
- `gateware/src/top/rezo/cpu_control.py` — proven REZO/REZOMO minimal CPU and
  write-only hardware-control peripherals
- `gateware/src/top/rezo/cpu_fw/` — accepted REZO control firmware
- `gateware/src/top/rezo/rezomo_cpu_fw/` — accepted REZOMO control firmware
- `gateware/src/top/rezo/strezo_variant.py` — authoritative STREZO CPU-less DSP,
  UI, navigation, renderer, and top-level integration
- `gateware/src/top/rezo/strezo_persistence.py` — authoritative STREZO journal
- `gateware/src/top/rezo/REZO_CPU_ARCHITECTURE.md` and
  `REZOMO_CPU_ARCHITECTURE.md` — ownership boundary and lessons from both CPU
  conversions
- `gateware/tests/test_rezomo_native_display.py` — focused native-display and
  geometry tests
- `gateware/src/top/rezo/BUILD_PERFORMANCE.md` — build timing, utilization, and
  artifact history
- `gateware/src/top/rezo/REZO_HANDOFF.md` — older project and REZOMO history

Confirm the actual implementation location in the current diff before editing;
the renderer may be embedded/generated through `top.py` rather than changed only
in the Rust source.

## Verification workflow

From the repository root, begin with:

```sh
git status --short --branch
git diff --check
git diff -- gateware/src/top/rezo/top.py \
  gateware/tests/test_rezomo_native_display.py \
  gateware/src/top/rezo/BUILD_PERFORMANCE.md
```

Run the focused display tests:

```sh
cd gateware
source ~/.zshrc
pdm run pytest tests/test_rezomo_native_display.py
```

Build the standard, upright, unscaled target using the normal Q1.15 arithmetic
configuration:

```sh
cd gateware
source ~/.zshrc
unset TILIQUA_ASQ_I_BITS TILIQUA_ASQ_WIDTH
pdm run rezomo_cpu build --fs-192khz
```

Do not assume that a successful firmware-only build proves FPGA fit. For a
hardware-test handoff, complete the full build and identify the exact newly
created archive.

Flash only the standard build, only when requested and the rack is available:

```sh
cd gateware
source ~/.zshrc
pdm flash archive build/rezomo-cpu-r5/<exact-new-archive>.tar.gz \
  --slot 3 --noconfirm
```

Never flash a circular-display build to the standard development display.

The CPU checkpoint currently has no circular target. Keep CPU conversion builds
on the standard upright `1280x720` development display until the user explicitly
resumes circular-display work.

## Build-performance logging

Every completed full build must be recorded in
`gateware/src/top/rezo/BUILD_PERFORMANCE.md`. Preserve the existing table and
record, when available:

- date/time
- target and display mode
- build/archive identifier
- wall-clock duration
- FPGA utilization and timing result
- whether the build was flashed
- slot number
- any noteworthy failure, retry, or environment issue

Do not replace previous observations. Append a new entry for each meaningful
build attempt.

## Guardrails

- Preserve user changes and unrelated dirty files.
- Do not reset, restore, delete, or broadly reformat the worktree.
- Do not change scaling or rotation policy while fixing page geometry.
- Do not rotate the standard `1280x720` target.
- Do not scale either current target.
- Do not produce circular artifacts on every iteration.
- Do not flash unless explicitly requested.
- Do not modify DSP, clock semantics, navigation, or persistence as part of a
  visual-alignment fix.
- Prefer shared geometric helpers over page-specific pixel nudges.
- Verify the generated pixels/tests and then verify on hardware; photographs are
  the final authority for optical alignment.

## Suggested next-session sequence

1. Read this file, `REZO_CPU_ARCHITECTURE.md`,
   `REZOMO_CPU_ARCHITECTURE.md`, and `BUILD_PERFORMANCE.md`.
2. Confirm branch, HEAD, and a clean worktree. Preserve the accepted REZO and
   REZOMO implementations; create a STREZO child branch if desired.
3. Audit `strezo_variant.py` and `strezo_persistence.py`: enumerate the complete
   state record, navigation graph, save/restore behavior, renderer inputs, and
   STREZO-only controls before writing firmware.
4. Reuse the lean VexiiRiscv core, bounded SPI-flash window, startup fail-open
   behavior, and write-only UI command pattern. Keep audio DSP, CV, video,
   LEDs, and lightweight rendering in hardware.
5. Add a STREZO-specific control plane and firmware rather than forcing its
   CROSS, MOTION, output-source, and OPTIONS controls into REZO semantics.
6. Run firmware/focused behavior tests first. Then synthesize and pack without
   routing to measure fit. Apply REZOMO's ROM-driven dynamic-text technique
   early if STREZO's writer creates a wide mux.
7. Build only standard `1280x720p60` at 192 kHz. Route only after deliberate
   packed headroom exists, log every meaningful attempt, and flash only the
   exact accepted archive to slot 4 when explicitly requested.

## 2026-08-25 STREZO CPU completion checkpoint

The STREZO conversion described above is complete on branch
`codex/strezo-cpu-control-plane`. Implementation commits `ac36e0ee` and
`b89fc0da` move stateful UI/navigation/persistence into firmware while keeping
linked-stereo DSP, CV, rendering, telemetry, LEDs, and bounded flash hardware
in gateware. STREZO-specific CROSS factory-to-USER editing, same/cross
feedback, MOTION, output-side selection, and V4-to-V5 restore semantics are
preserved.

The clean seed-8 standard route passes the 3 percent release gate at 444.64 /
71.26 / 65.62 / 82.88 MHz for DVI5X / AUDIO / SYNC / DVI. Archive
`build/strezo-cpu-r5/strezo-cpu-b89fc0da-r5.tar.gz` has SHA-256
`8fccf1851528dd9bd8da66d2b7c6e794345d0739590be76b97feb16302a6edc5`;
its embedded `top.bit` matches the qualified route at SHA-256
`406284c73c2f894abc455841f4d8cb91d661ecdaeffc4e0b290fb4a837d2770f`.
It was flashed to slot 4 on 2026-08-25 with `Refresh: DONE`.

Software verification is green (62 final affected display/control tests, 19
focused DSP/family-target tests, and firmware format/offline release checks).
The remaining work is user hardware acceptance using the checklist in
`STREZO_CPU_ARCHITECTURE.md`, followed by any requested polishing.

This checkpoint built only standard `1280x720p60` for the development monitor.
It did not remove or replace the native `720x720` canvas or the official
panel's final rotation path, and no circular archive was built or flashed.
