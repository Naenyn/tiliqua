# REZOMO development handoff

This is the canonical continuation document for current REZOMO work. Read it
alongside [`BUILD_PERFORMANCE.md`](BUILD_PERFORMANCE.md) before changing,
building, or flashing REZOMO.

The older [`REZO_HANDOFF.md`](REZO_HANDOFF.md) contains useful project history,
including earlier REZOMO notes, but its filename is now ambiguous. Keep it as a
historical reference; use this file for the current state and operating rules.

## Current objective

REZOMO is being caught up to the native-display architecture and UI conventions
already completed and hardware-validated in REZO. The work is primarily a UI
geometry and consistency migration. Do not change DSP behavior, navigation,
persistence, control meaning, or clock algorithms unless a separate request
explicitly calls for it.

REZO is the authoritative visual reference for shared pages and controls. REZOMO
also has its unique CLOCK page, whose layout must follow the same geometry,
alignment, and value-chip rules.

Do not borrow UI code or conventions from SPECTO/SONORO, OSCIO, or unrelated
bitstreams. The applicable references are REZO and, where explicitly useful,
the established REZOMO behavior.

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
- `gateware/src/top/rezo/fw/src/main.rs` — firmware UI renderer and behavior
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
pdm run rezomo build --fs-192khz
```

Do not assume that a successful firmware-only build proves FPGA fit. For a
hardware-test handoff, complete the full build and identify the exact newly
created archive.

Flash only the standard build, only when requested and the rack is available:

```sh
cd gateware
source ~/.zshrc
pdm flash archive build/rezomo-r5/<exact-new-archive>.tar.gz \
  --slot 4 --noconfirm
```

Never flash a circular-display build to the standard development display.

Once the standard layout is accepted, build the official circular artifact:

```sh
cd gateware
source ~/.zshrc
unset TILIQUA_ASQ_I_BITS TILIQUA_ASQ_WIDTH
pdm run rezomo_round build --fs-192khz
```

Keep artifacts distinguishable by target in their filenames or release names.
The circular artifact must be identifiable as the `720x720` rotated-panel build;
the standard artifact must be identifiable as the upright `1280x720` build.

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

1. Read this file and `BUILD_PERFORMANCE.md`.
2. Inspect branch, HEAD, and worktree before changing anything.
3. Treat the accepted standard UI and focused pixel tests as the shared-page
   reference unless new hardware feedback supersedes them.
4. Build and clearly name an updated official circular artifact from the
   accepted source when requested; do not flash it to the standard rack display.
5. Begin consolidating shared REZO/REZOMO page rendering and navigation behind
   common helpers rather than continuing to port equivalent edits by hand.
