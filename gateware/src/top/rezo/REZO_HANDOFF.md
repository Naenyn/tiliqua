# REZO development handoff

This file is the starting context for the next Codex task working on REZO. Read
it together with [`BUILD_PERFORMANCE.md`](BUILD_PERFORMANCE.md) and
[`Rezo_Feature_Ideas_By_Complexity.md`](Rezo_Feature_Ideas_By_Complexity.md)
before changing the design. [`REZO_USER_GUIDE.md`](REZO_USER_GUIDE.md) is the
simplified operator documentation for the release candidate.

## Display target invariant (read before changing the renderer)

REZO has one current display layout, authored for the official Tiliqua
display. That display is a circular 720x720 panel. Its largest wholly visible
axis-aligned square is 508x508, centered at upright logical coordinates
`x=106..613`, `y=106..613`. All interactive content, page headers, labels,
controls, selection outlines, and content-panel backgrounds must remain inside
that square. The `REZO` identity is the sole intentional exception: it may use
the top circular arc above the square.

The two output modes differ only in panel placement and mount correction:

| Output | Compact 508x508 layout | Rotation | Scaling/enlargement |
|---|---|---|---|
| Official `720x720p60r2` circular display | yes | 90-degree mount correction | none |
| Standard `1280x720p60` development monitor | yes | none | none |

The standard monitor is a pixel-for-pixel preview of the same compact UI. Its
720-wide logical panel is centered in the 1280-pixel raster, so the compact UI
looks physically smaller than the former full-size 720p design. That is
intentional. Do not rotate the standard output, scale the compact UI up to fill
it, or restore the legacy full-size layout for that output. The old polished
720p renderer is the design source currently being reflowed—not a second active
layout target.

In `RezoBeamTop`, `compact_layout` must therefore remain enabled for both
modelines, while `rotate_left` is enabled only when both active dimensions are
720. In `RezoTileDisplay`, `text_x/text_y` are upright native pixel coordinates;
the official target applies rotation before rendering, and the standard target
only subtracts its horizontal centering offset.

## 2026-08-12 compact MAIN geometry

BANK and FILTER share one lower-control grid. Following hardware review, its
final geometry uses alternate native text rows `(28, 30, 32, 34, 36)` and
logical fader starts `(486, 532, 578, 623, 669)`; BANK occupies the first three
and FILTER all five. The final row retains the established bottom anchor while
the preceding rows expand upward into the otherwise empty band/control gutter.
Do not move the bottom row or alter the band field when tuning this spacing.

The compact band field spans logical y=218..474 with zero at y=346. BANK's
signed magnitude is 0..128 and maps one logical pixel per step, so the default
64-level bands are half-height. FILTER's 0..32 response maps eight pixels per
step, reaching—but never crossing—the 256-pixel field. Keep the explicit
upper-edge fill clip if the response calculation changes. This division lets
the bands use the full shaded region with modest top padding while preserving
the lower controls and their bottom gutter.

The passing standard-monitor candidate is the seed-6 W130 route recorded as
`ROUND7-MAIN-EXPANDED-W130-S6` in `BUILD_PERFORMANCE.md`. Its archive manifest
is `1280x720p60` (unrotated, unscaled). It programmed the bitstream and
manifest to slot 4 and refreshed successfully; option storage was preserved.

## 2026-08-12 compact INPUT geometry

The four INPUT groups use native text-row triples `(14, 16, 18)`, `(20, 22,
24)`, `(26, 28, 30)`, and `(32, 34, 36)`. Compact vertical geometry is now
decoded from native `text_y`, not the 720-to-508 logical lookup coordinate.
Group bases are `221 + input*96` native pixels, exactly three pixels above the
MODE text-cell top. Each group occupies exactly six 16px character rows. Do
not convert these vertical bounds through the logical viewport lookup: the old
136-logical-pixel cadence became 95.96 physical pixels, and independently
rounded text and rectangles accumulated the apparent group-dependent drift.

MODE, VALUE, and DEPTH are plain labels. Only editable values are shaded:
MODE uses a small value chip, CV VALUE uses a small destination chip, AUD
VALUE uses the gain-fader lane, and CV DEPTH uses the bipolar depth-fader
lane. Relative to each native group base, the MODE, VALUE, and DEPTH boxes
begin at y=0, 32, and 64 and are 20 physical pixels high. Their visible
14-scanline glyphs begin at y=3, 35, and 67 respectively, giving each glyph
and its box the exact same vertical center. Selection outlines use local
y=0..24, 28..56, and 60..88. Keep these bounds derived from the shared lane
constants instead of applying per-row correction offsets.
MODE begins at native x=14 while VALUE and DEPTH begin at x=13, giving all
three labels the same exclusive right edge at native column 18. Every dynamic
parameter begins at native column 19. The MODE and CV target chips, AUD VALUE
fader, and CV DEPTH fader all begin at logical x=272; small text chips extend
to x=376 so three-character values have consistent padding. AUD VALUE retains
its unity marker and
one-pixel post-VALUE monitor. The raw bipolar CV monitor is conditionally
drawn on DEPTH instead of VALUE. In AUD mode DEPTH is wholly absent and
navigation skips it; do not render a disabled box for that lane.

The shared INPUT content panel spans logical y=160..700. Its top is immediately
above IN0 MODE at y=167 but below the INPUT ROUTING heading; its bottom leaves
an 8px gutter before the centered 508x508 viewport border at y=708. The final
DEPTH control and selection outline must remain above that gutter.

The MODE value field is five native character cells wide. AUDIO is rendered as
`AUDIO`; CV is padded as ` CV  ` so both values are centered in the same fixed
chip. The chip's compact lower edge is trimmed independently of the MODE text
baseline so the glyph is also vertically centered. The writer refresh cycle
uses indices 96..103 for the fourth and fifth MODE characters; noncompact
writer timing remains capped at index 95.

The passing standard-monitor candidate is the native W130 seed-4 route
recorded as `ROUND15-INPUT-NATIVE-Y-W130-S4` in `BUILD_PERFORMANCE.md`. Its archive
manifest is `1280x720p60` (unrotated, unscaled). The archive SHA-256 is
`11de9592f89c60c14b865e9a9ac2d1fe40f88c24590a563a36e36ddecf110dca`;
its embedded `top.bit` SHA-256 is
`3985bc741c953195627e10deda7b77aa1e702e4680140d4b74cae546350fd1d7`.
It programmed the bitstream and manifest to slot 4 and refreshed successfully;
option storage was preserved.

## 2026-08-12 compact FEEDBACK geometry

The compact FEEDBACK page now derives its horizontal alignment from shared
edges instead of independent visual offsets.  The ten source buttons are
translated five logical pixels left after the decoder's one-pixel prefetch,
giving the complete group half-open logical bounds of x=[42,678) and an exact
panel center of x=360.  This translation applies
only to FEEDBACK; the shared band geometry on other pages is unchanged.

Treat that ten-button row as the canonical compact band-button component.
Pages exposing the same ten-band toggle/source control (including BANDS
ENABLE) should reuse its button size, inter-button spacing, and centered
arrangement rather than defining a page-specific approximation. Visual state
may differ, but geometry should not.

The KNEE and CEILING faders share logical bounds x=230..654.  On the standard
unrotated 1280x720 output these map to approximately physical x=268..567,
comfortably inside the compact frame whose right edge is near physical x=594.
Their labels are right-aligned at physical x=261, leaving a consistent 7px
gutter.  DAMPING's value chip shares the physical x=268 left edge, spans
x=268..364, and its dynamic value begins at native column 17 (visible near
x=272).  The compact fader and source translations are gated by FEEDBACK so
BANK and FILTER retain their established layout.

The passing standard-monitor candidate is the native W130 seed-1 route
recorded as `ROUND19-FEEDBACK-ALIGN-W130-S1` in `BUILD_PERFORMANCE.md`. Its
archive manifest is `1280x720p60` (unrotated, unscaled). The archive SHA-256 is
`f7d324bdd97ed5058ba839516cbb2de5708b0e7cbf67a8da0128f4240a2c2e98`;
its embedded `top.bit` SHA-256 is
`675040a62133562b0913e889ebf1994311786d746e207ae1c1bb63e29e71805b`.
It programmed the bitstream and manifest to slot 4 and refreshed successfully;
option storage was preserved.

## 2026-08-13 compact MATRIX geometry

The MATRIX controls and column headings retain their established geometry.
Only the row-label table changed: the five labels now occupy native text rows
`(16, 21, 26, 31, 36)`, an exact 80-logical-pixel cadence matching the five
fader rows at y=`250 + 80*n`. All labels keep a common exclusive right edge at
native column 17, so FREQUENCY and RESONANCE begin at column 8 while WIDTH,
SLOPE, and DRIVE begin at column 12. The visible glyph center carries the
font's documented one-pixel optical offset relative to the 28px fader panel.

Keep the row centers and the exclusive label edge in shared tables. Do not
restore the former `(17, 21, 25, 29, 32)` rows: those produced 64/64/64/48px
spacing and made the apparent error vary down the page. The display regression
checks exact 80px cadence, the common right edge, and the one-pixel optical
offset without moving any fader or column heading.

The retained hardware-validation candidate is the native W130 seed-6 route
recorded as `ROUND21-MATRIX-ROWS-W130-S6` in `BUILD_PERFORMANCE.md`. Its archive
manifest is `1280x720p60` (unrotated, unscaled). The archive SHA-256 is
`c4297940060f637ccd7683afe4c1ba0941b5666efbf3f1395a60f7d1f822c44a`;
its embedded `top.bit` SHA-256 is
`dd62cf9bba095e858b1d6100b95ee9591f2e8528341b596bb14ef3d94a4b1664`.
Primary DVI, SYNC, and AUDIO timing pass, but DVI5X reaches only 346.02 MHz
against 371.33 MHz, so this artifact is for UI validation rather than a clean
release timing baseline. It programmed the bitstream and manifest to slot 4
and refreshed successfully; option storage was preserved.

The final source-row centering correction accounts explicitly for the shared
decoder's one-pixel ROM prefetch. FEEDBACK now samples five logical pixels
ahead, so the aggregate rendered button interval is exactly x=[42,678) and
its center is x=360. The passing standard-monitor candidate is the native
W130 seed-1 route recorded as `ROUND20-FEEDBACK-SOURCE-CENTER-W130-S1` in
`BUILD_PERFORMANCE.md`. Its archive manifest is `1280x720p60` (unrotated,
unscaled). The archive SHA-256 is
`863f4965e2e39c9e7481becb735b25ddd2eff84887eeca6fbc6d60c1689e4d28`;
its embedded `top.bit` SHA-256 is
`ed8fff27b8b1ee33d4f40658669b94d67b467ed25ea122fc58bd85b35c6cbe50`.
It programmed the bitstream and manifest to slot 4 and refreshed successfully;
option storage was preserved.

## 2026-08-12 compact OUTPUT geometry

OUTPUT uses the same native-center rule as GROUPS. Its row labels occupy native
text rows `(21, 25, 29, 33)`, whose visible centers are logical y `(342.5,
406.5, 470.5, 534.5)`. Their uniform 64px cadence avoids the former
64/48/64px row gaps. Each 28px send cell is placed symmetrically around the
same half-pixel center, so OUT0 through OUT3 cannot accumulate vertical drift.

The five column centers are logical x `(270.5, 334.5, 398.5, 462.5, 534.5)`.
G1 through G4 retain their native text starts at columns `(16, 20, 24, 28)`;
the dynamic DRY writer starts one cell earlier so its three visible glyphs
center on the fifth value column. Compact send cells are 56px wide on the
64px G-column cadence, with a 48px interior and three pixels per 0..16 fill
step. Noncompact OUTPUT geometry is unchanged.

Keep headings, row labels, and cell bounds derived from the shared center
tables. Do not restore the former scaled logical positions independently: the
text raster remains native while scaled rectangles round differently, which
causes both progressive row drift and the visibly displaced DRY heading. The
display regression samples every row and column center and both cell edges.

The passing standard-monitor candidate is the native W130 seed-10 route
recorded as `ROUND18-OUTPUT-EVEN-ROWS-W130-S10` in `BUILD_PERFORMANCE.md`. Its
archive manifest is `1280x720p60` (unrotated, unscaled). The archive SHA-256 is
`30e6747434d65cd4c2328c5645247e1dde75ca10ae5450341a2f1f5caa10340c`;
its embedded `top.bit` SHA-256 is
`d0249cd27b41df2ee985e4c91dfeb6e02026fccb9965754de2627a12a4523293`.
It programmed the bitstream and manifest to slot 4 and refreshed successfully;
option storage was preserved.

## 2026-08-12 compact GROUPS geometry

GROUPS vertical geometry is native, like INPUT. The four labels occupy native
text rows `(20, 23, 26, 29)`, a uniform 48px cadence. Because the font has 14
visible scanlines followed by two blank scanlines, each glyph's visual center
is at `row*16 + 6.5`. The corresponding rail occupies native y=`row*16+6..7`,
so its two-pixel center is the same half-pixel. Each 20px assignment marker is
symmetrical around that center, spanning y=`center-9..center+10`; its disabled
ghost edges are the first and final two pixels.

Do not restore the old `305 + group*64` logical rails or `294 + group*64`
logical markers. The compact lookup turns that 64-logical-pixel cadence into
45.16 physical pixels while labels remain constrained to a 16px native text
grid, making progressive row misalignment unavoidable. Keep the label rows,
rail centers, marker bounds, and the GROUPS geometry regression test derived
from the shared native center table.

The passing standard-monitor candidate is the native W130 seed-1 route
recorded as `ROUND16-GROUPS-NATIVE-Y-W130-S1` in `BUILD_PERFORMANCE.md`. Its
archive manifest is `1280x720p60` (unrotated, unscaled). The archive SHA-256 is
`98087b13b23f541b50bf7835b151ab57bf06ba2d01e9580cf368bec1be9e1536`;
its embedded `top.bit` SHA-256 is
`db69e9ee34534655a32a98cae0ef3c4e0fd47f375f87ec6e88ac5ce2684ccb5e`.
It programmed the bitstream and manifest to slot 4 and refreshed successfully;
option storage was preserved.

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
