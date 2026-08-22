# REZO family development handoff

This file is the starting context for the next Codex task working on the
unified REZO, REZOMO, and STREZO family. Read it together with
[`BUILD_PERFORMANCE.md`](BUILD_PERFORMANCE.md) and
[`Rezo_Feature_Ideas_By_Complexity.md`](Rezo_Feature_Ideas_By_Complexity.md)
before changing the design. The current operator guides are
[`REZO_USER_GUIDE.md`](REZO_USER_GUIDE.md),
[`REZOMO_USER_GUIDE.md`](REZOMO_USER_GUIDE.md), and
[`STREZO_USER_GUIDE.md`](STREZO_USER_GUIDE.md).

## 2026-08-21 chip geometry and routing-overlay fixes

The reported standard-display inconsistencies are fixed across the family:

- REZO and STREZO MAIN PRESET selection outlines now use the shared header
  bounds at y=180..218 in both edit and navigation states.
- REZO's dynamic OUTPUT writer now writes `DRY` at column 32, matching the
  shared static label and centering it over the fifth column. In FILTER mode,
  the fifth column's cell, fill, selection, and header geometry are all
  suppressed rather than merely removed from navigation.
- REZOMO FEEDBACK, KNEE, and CEILING navigation outlines now use the same
  native track endpoints and row bounds as their faders.
- `native_value_chip_x0()` is the family contract for one 16-pixel text-cell
  inset. The audit applied it to OPTIONS, DAMPING, REZO/STREZO PRESET,
  REZO FILTER TYPE, and STREZO CROSS LAYOUT, CROSS CURVE, motion values, and
  OUTPUT side chips. STREZO `LINEAR` therefore begins one full cell inside its
  CROSS CURVE chip instead of at the chip edge.

The apparent shared-page discrepancies came from the split architecture:
static labels and several geometry helpers are shared, but each product keeps
its dense dynamic text writer and selection/cell overlay renderer local to
preserve packing and timing. REZO's local writer overlaid the shared `DRY`
label one column left, while REZOMO did not. Conversely, REZOMO retained
legacy local FEEDBACK selection rectangles even though the shared labels and
track helper were already correct. The regressions now cover these local
overlays explicitly.

Focused display coverage passes `66 passed`; the complete family regression
passes `202 passed, 79 warnings in 815.99s`. Only standard `1280x720p60`
targets were built. The final routes all clear the 1.25% timing-margin gate:

| Target | Seed | LUT4 / COMB | DVI5X / AUDIO / SYNC / DVI MHz | Archive | Slot | Archive SHA-256 |
|---|---:|---|---|---|---:|---|
| REZO | 9 | 20,527 / 24,123 | 379.08 / 71.07 / 60.99 / 77.78 | `rezo-d5dc1eda-r5.tar.gz` | 2 | `e04fa671eb592c9d4dd6a47072d895ecafca9b4eab2b03d52d7a86fd580cacb7` |
| REZOMO | 9 | 20,595 / 23,863 | 420.34 / 63.23 / 65.84 / 75.92 | `rezomo-84646703-r5.tar.gz` | 3 | `0ece66281d16ae7af29a11d90c05157dde253ad1b12f5481eba5981274aac16b` |
| STREZO | 8 | 20,066 / 23,330 | 395.73 / 70.85 / 63.98 / 75.49 | `strezo-001b4d3e-r5.tar.gz` | 4 | `bab0d478815e606243551e21ed3e7e000e81d6fa664bae457f0a02a68896b26c` |

All three archives' embedded `top.bit` payloads match their qualified routed
files and flashed successfully to slots 2/3/4. REZOMO seed 8 and STREZO seed
11 missed DVI5X; alternate routes were evaluated against fixed synthesized
JSON. The checked-in standard defaults are now REZO 9, REZOMO 9, and STREZO
8. No circular target was built or flashed.

## 2026-08-21 native page-heading alignment

All standard-display REZO-family page-content headings now use native text row
12. Their 16-pixel cells draw through y=205, leaving a consistent 12-pixel
gutter before the shared shaded content panel begins at y=218. BANK, FILTER,
BANDS, and STREZO CROSS pages also carry interactive PRESET, MODE, TYPE, or
LAYOUT controls in that strip, so their value text, chips, and selection
outlines move together. Header chips occupy y=184..216 and selection outlines
end exactly where the content panel begins; no text or selection geometry
overlaps the field.

`ui_common.py` is the single source for the heading row, header-chip geometry,
and common support-page headings. Product-only BANK/FILTER/CLOCK/CROSS headings
use the same helper and constants. The complete family regression passes `196
passed, 79 warnings in 800.14s`; the extra case is the new shared heading-band
contract.

Only standard `1280x720p60` targets were built. REZO seed 8 missed sync timing
and STREZO seed 8 missed DVI5X; the qualified standard defaults are therefore
now REZO seed 9, REZOMO seed 8, and STREZO seed 11. All final routes clear the
project's 1.25% timing-margin gate:

- REZO: 20,595 LUT4, 6,907 DFF, 22 DP16KD; DVI5X 414.08, AUDIO
  77.20, SYNC 63.26, DVI 81.55 MHz.
- REZOMO: 20,387 LUT4, 7,105 DFF, 22 DP16KD; DVI5X 421.23, AUDIO
  75.64, SYNC 62.64, DVI 76.21 MHz.
- STREZO: 20,108 LUT4, 6,926 DFF, 21 DP16KD; DVI5X 446.03, AUDIO
  74.42, SYNC 65.28, DVI 75.95 MHz.

Commit `98f79f86` archives were built with those qualified seeds and flashed
successfully to the requested slots:

- slot 2: `build/rezo-r5/rezo-98f79f86-r5.tar.gz`, SHA-256
  `1def708ee9d5ac6262a5e9fec36111b76db043ffb88a032dee0ed95c39ec8562`.
- slot 3: `build/rezomo-r5/rezomo-98f79f86-r5.tar.gz`, SHA-256
  `da738252986886e49974df8f54e69684f12decd19779b407138a4c4ee76a902d`.
- slot 4: `build/strezo-r5/strezo-98f79f86-r5.tar.gz`, SHA-256
  `651610c70b041d76ad92562d4b76733feded010c8f790770483de8faecf6e0f2`.

No circular target was built or flashed.

## 2026-08-21 production-helper audit and consolidation stop point

The follow-up production audit tested the safest remaining exact helper: the
three journal `_header_prefix_byte` methods were temporarily moved into a
shared `JournalHeaderMixin` in `persistence_common.py`. This was a pure
elaboration-time refactor with no intended RTL change.

The experiment passed the 29 persistence tests and the complete family suite
(`195 passed, 79 warnings in 795.37s`). Standard-only seed-8 builds also passed
all clocks. Nevertheless, REZOMO synthesis increased from the qualified
20,466 LUT4 to 20,600 LUT4, a cost of 134 LUT4, and DVI5X fell from 439.75 MHz
to 376.36 MHz—only about 1.35% above its 371.33 MHz requirement. The helper
extraction was therefore rejected and all four product/common source files
were restored byte-for-byte to commit `2a8c1525`.

The experimental dirty-source archives named with the prior HEAD tag
(`rezo-2a8c1525-r5.tar.gz`, `rezomo-2a8c1525-r5.tar.gz`, and
`strezo-2a8c1525-r5.tar.gz`) are not qualified release artifacts and were not
flashed. No circular target was built.

This establishes the practical stopping point for source consolidation. The
remaining exact helpers (`gray_decode`, `clamp_add`, `apply_preset`, and small
display geometry/text methods) save only tens of source lines while directly
or pervasively constructing packing-sensitive RTL. Do not extract them merely
for deduplication. Revisit production consolidation only when it supports a
specific functional change or measurable capacity optimization; otherwise
prioritize features, hardware fixes, and targeted REZOMO optimization.

## 2026-08-21 exact UI/display contract consolidation

This checkpoint completes the exact-body test consolidation audit. It changes
only test and documentation sources; no product RTL, firmware, target
configuration, or generated bitstream changed, so nothing was built or
flashed.

- Added `test_rezo_family_ui_contract.py` as the single source for six shared
  UI behaviors. Four apply to REZO and REZOMO, while BANDS transactional
  editing and the fine-frequency grid apply to all three products. The 14
  parameterized cases replace their copied product-local bodies.
- Added `test_rezo_family_display_contract.py` as the single source for eight
  shared display behaviors, producing 16 parameterized cases across the
  applicable product pairs. Static glyphs, band geometry, BANDS controls,
  five-digit frequencies, disabled-band ghosts, DRIVE shading, OUTPUT
  selection bars, and semantic palette mapping now each have one definition.
- Extended `rezo_display_support.py` with common settled video/panel pixel
  sampling. Native REZOMO and STREZO sampling now uses the same primitive.
- Moved the identical REZO/REZOMO version-1 compatibility vector into
  `test_rezo_persistence_contract.py`; later product-specific migrations stay
  local. The now-empty `test_rezo_standard_persistence.py` was deleted.
- Removed about 1,220 copied lines and added about 525 shared/adaptor lines, a
  net test-source reduction of roughly 695 lines. Collection remains exactly
  195 cases.
- A normalized AST fingerprint audit now reports no exact duplicate test
  functions across `test_rezo*.py` and `test_strezo*.py`.
- Focused results: UI `30 passed`, display `82 passed`, and persistence `29
  passed`. The complete family regression passes `195 passed, 79 warnings in
  796.11s`; the warnings are existing dependency deprecations.

The remaining similarities are not exact contracts: STREZO navigation,
stereo/cross-feedback DSP, display geometry, native scene setup, and journal
migrations differ materially. Dense product RTL also remains local because
prior structurally neutral extractions changed packing/timing on near-capacity
images.

## 2026-08-21 DSP/UI/display test consolidation

This checkpoint continues consolidation strictly in test code. No product RTL,
firmware, build configuration, or generated bitstream changed, so no target was
built or flashed.

- Added `test_rezo_family_compare_contract.py` as the single parameterized
  source for four identical DSP contracts exercised by REZO, REZOMO, and
  STREZO: input telemetry, zero-bank wet/dry routing, the known-good band-5
  drive vector, and resonator guard-bit continuity. The identical REZO and
  REZOMO 192 kHz cycle-budget check also lives there; STREZO retains its
  distinct local budget test.
- Added `rezo_ui_support.py` as the common encoder detent, click/hold, and
  shortened-debounce simulation driver used by all three UI suites and the
  cross-family acceleration contract.
- Added `rezo_display_support.py` as the common native-canvas coordinate
  mapping and settled RGB sampling helper for REZOMO and STREZO. Their signal
  setup and scene expectations remain product-owned because they differ.
- Removed about 687 copied lines from the product test files and replaced them
  with shared contracts plus small import adapters, a net reduction of more
  than 400 test lines. Test collection is unchanged at 195 cases.
- Focused compare/UI coverage passes 44 tests, focused native-display coverage
  passes 34 tests, and the complete family regression passes `195 passed, 79
  warnings in 803.22s`. The warnings are existing dependency deprecations.
- This audit does not justify parameterizing merely similar display/UI tests.
  Shared behavior should move into a family contract only when its setup and
  expected result are truly identical; variant semantics should remain local.

## 2026-08-21 pure-contract and persistence-test consolidation

This checkpoint continues the low-risk consolidation audit. Only standard
`1280x720p60` targets were built; no circular target was invoked, and nothing
was flashed.

- Added `core_common.py` as the single source of the shared filterbank numeric
  contract: band/input/drive limits, CV target bases, frequency layouts and
  fine-frequency grid, frequency lookup, and cutoff coefficient. REZO and
  STREZO inherit this signal-free mixin.
- REZOMO deliberately retains its local copy. Applying the same pure mixin to
  REZOMO changed generated structure from 23,792 to 23,836 cells and seed 9
  failed DVI5X at 335.68 MHz. A further REZOMO-only CLOCK constants module also
  produced a larger bitstream and failed DVI at 66.34 MHz. Both experiments
  were rejected; no CLOCK signal or RTL assignment moved out of `top.py`.
- Consolidated the three copied persistence test harnesses into
  `rezo_persistence_support.py` and one parameterized
  `test_rezo_persistence_contract.py`. Common flash, corruption, slot, save,
  and page-boundary behavior is authored once and exercised against all three
  journals. Only product migration tests remain local. This removes about 690
  duplicated test lines.
- The final retained family regression passes: `195 passed, 79 warnings in
  805.01s`. The reduction from 199 tests is intentional: four duplicate
  transport executions now run once. The warnings are existing dependency
  deprecations.
- Final standard routes all pass the 1.25% timing margin gate:
  - REZO seed 8: 24,035 cells (253 free), 6,900 FF, 22 DP16KD; DVI5X
    394.17, AUDIO 70.39, SYNC 63.61, DVI 79.83 MHz. Its bitstream is
    byte-identical to the prior qualified image.
  - REZOMO seed 8: 23,770 cells (518 free), 7,098 FF, 22 DP16KD; DVI5X
    439.75, AUDIO 75.80, SYNC 61.44, DVI 77.71 MHz. Seed 9 failed DVI5X at
    355.11 MHz on this exact synthesized JSON, so seed 8 is the new standard
    default.
  - STREZO seed 8: 23,332 cells (956 free), 6,919 FF, 21 DP16KD; DVI5X
    384.91, AUDIO 72.03, SYNC 64.82, DVI 84.64 MHz.
- Commit `17936729` archives were packaged from those exact routed bitstreams;
  each archived `top.bit` matches its build-directory file:
  - `build/rezo-r5/rezo-17936729-r5.tar.gz`, SHA-256
    `a0526c5c2449215e254547249e7b2152be64d9c734f8f97e4c96f7b4eeb881bc`.
  - `build/rezomo-r5/rezomo-17936729-r5.tar.gz`, SHA-256
    `044ebdba129db71f21dcbf638565d4645b793ef19ffb859836b83ab181c2899b`.
  - `build/strezo-r5/strezo-17936729-r5.tar.gz`, SHA-256
    `a070dc2403ea1fb89e9dd6aeaac7f1b12a4a1b73ca36e18416c36bafa7b5f6ef`.
- The next safe consolidation work is test/contract oriented. REZOMO core and
  CLOCK definitions, all dense renderer RTL, and product journal FSMs should
  remain local unless a future capacity change creates room for controlled
  structural experiments.

## 2026-08-21 shared-code audit and persistence extraction

This checkpoint completes the recommended follow-up audit. Only standard
`1280x720p60` targets were built; no circular target was invoked, and nothing
was flashed.

- Deleted the three obsolete `RezoPeripheral`/`RezoSoc` implementations and
  their unused CSR/SoC imports. All active family targets instantiate the
  framebuffer-free top-level classes, so these copies were dead source rather
  than alternate implementations.
- Added `persistence_common.py` as the single source of the bit-exact BZIP2 CRC
  step/table and `SPIFlashTransfer` transport engine. Each product retains its
  own `RezoStateJournal`: record fields, magic/version handling, migration
  policy, and journal FSM remain product-owned and were not generalized.
- The complete family regression passes: `199 passed, 79 warnings in 807.33s`.
  The focused target suite passes `5 passed`; the three persistence suites pass
  `33 passed, 44 warnings`. The warnings are existing dependency deprecations.
- Final standard routes from the exact audited source all pass the 1.25% timing
  margin gate:
  - REZO seed 8: 24,035 cells (253 free), 6,900 FF, 22 DP16KD; DVI5X
    394.17, AUDIO 70.39, SYNC 63.61, DVI 79.83 MHz.
  - REZOMO seed 9: 23,792 cells (496 free), 7,098 FF, 22 DP16KD; DVI5X
    406.01, AUDIO 71.62, SYNC 64.55, DVI 78.03 MHz.
  - STREZO seed 8: 23,387 cells (901 free), 6,919 FF, 21 DP16KD; DVI5X
    392.46, AUDIO 71.98, SYNC 61.34, DVI 77.86 MHz.
- Commit `90fce999` archives were packaged from those exact routed bitstreams;
  each archived `top.bit` matches its build-directory file:
  - `build/rezo-r5/rezo-90fce999-r5.tar.gz`, SHA-256
    `5490a87b83533b726f3a10c0102b40ece9ead6930cb79e1c8a463aa8f7fcaf0a`.
  - `build/rezomo-r5/rezomo-90fce999-r5.tar.gz`, SHA-256
    `e07e2cd78356965f94975ae7093f0f78034c5764e151294f969521c32a865ce0`.
  - `build/strezo-r5/strezo-90fce999-r5.tar.gz`, SHA-256
    `86b2350537ba16583154a1029cfdab681b05a641d937f3ea97ba7aea50aeb006`.
- STREZO seed 7 was rejected because its final DVI5X result was 355.87 MHz.
  Seed 8 was rerouted from the identical synthesized JSON and is now the
  standard default. REZO remains seed 8 and REZOMO remains seed 9.
- The remaining large similarities are deliberately local: product journal
  schemas/migrations, product-specific pages and DSP, and dense renderer RTL
  whose generated naming and packing affect these near-full ECP5 images. Future
  consolidation should begin with small pure contracts or exact byte-for-byte
  helpers and must repeat full synthesis/timing qualification.

## 2026-08-21 display consolidation and REZOMO optimization

This checkpoint supersedes the build defaults and capacity figures in the
fixed-left checkpoint below. Only standard `1280x720p60` targets were built;
no circular target was invoked and nothing was flashed.

- Added `display_common.py` as the single source of the 5x7 font, tile
  character sets, semantic palette roles, and RGB themes. Removed all three
  unused legacy `RezoBeamDisplay` implementations; the active designs had only
  referenced their copied font dictionaries. Together with shared page
  metadata extraction, this removes about 1,400 duplicated/dead source lines.
- `ui_common.py` now also owns the common page-title sequence, navigation/CV
  target strings, layout/palette/damping/save spellings, and compact frequency
  formatter. Product-specific CLOCK, FILTER/MATRIX, and CROSS/stereo/motion
  pages remain local. Dense dynamic pixel equations also remain local because
  equivalent structural rewrites have repeatedly changed ECP5 packing.
- Expanded REZOMO's existing synchronous CLOCK character ROM from 1Kx6 to
  2Kx6 and moved its remaining constant value-name muxes into unused space.
  It still maps to one DP16KD. Final REZOMO packing is 23,815 cells (473 free),
  450 fewer cells than the prior 24,265-cell image, with 22 DP16KD total.
- The five focused display suites pass: `82 passed, 36 warnings in 127.09s`.
  The complete REZO/REZOMO/STREZO regression also passes: `199 passed, 79
  warnings in 805.52s`. The warnings are existing dependency deprecations.
- Final standard routes from the exact consolidated source:
  - REZO seed 8: 24,148 cells (140 free), 22 DP16KD; DVI5X 440.14,
    AUDIO 68.66, SYNC 64.31, DVI 75.75 MHz.
  - REZOMO seed 9: 23,815 cells (473 free), 22 DP16KD; DVI5X 401.28,
    AUDIO 76.09, SYNC 61.48, DVI 79.52 MHz.
  - STREZO seed 7: 23,372 cells (916 free), 21 DP16KD; DVI5X 391.54,
    AUDIO 74.23, SYNC 64.67, DVI 78.77 MHz.
- Standard defaults are now REZO seed 8, REZOMO seed 9, and STREZO seed 7.
  REZO seed 7 and STREZO seed 11 were rejected after source-derived net-name
  changes reduced their DVI routes below the spread-spectrum margin gate.

## 2026-08-21 fixed-left value-chip implementation

This checkpoint supersedes the exact-centering investigation immediately
below. Hardware-accurate optical centering was rejected after synthesis showed
that its per-value pixel translation pushed REZOMO beyond capacity. The family
now uses the intentionally cheaper rule the user originally proposed: every
changing value begins at one fixed chip-relative text-cell origin and shorter
values carry trailing blanks to clear the remainder of the slot.

- Applied fixed-left strings and writer origins across REZO, REZOMO, and
  STREZO, including BANK/FILTER mode, INPUT mode/target, damping, OPTIONS,
  BANDS layout/frequency, STREZO stereo/motion values, and every REZOMO CLOCK
  value. Removed the temporary font-ink centering helper, translated lookup,
  offset registry, shifter, and their focused tests.
- REZOMO initially still packed at 24,365 `TRELLIS_COMB` cells, 77 beyond the
  24,288-cell device. Left justification itself did not add a dynamic shifter;
  moving blanks from the beginnings to the ends of many CLOCK spellings changed
  constant-mux truth-table sharing and cost LUTs. CLOCK strings now live in one
  synchronous 6-bit character ROM. The existing three-cycle refresh writer
  absorbs its latency with no new display-pipeline stage. Final REZOMO packing
  is 24,265 cells (23 free), 7,146 FF, and 22 DP16KD.
- Final focused display regression:
  `82 passed, 36 warnings in 123.26s` across `test_rezo_display.py`,
  `test_rezo_standard_display.py`, `test_rezomo_native_display.py`,
  `test_strezo_display.py`, and `test_strezo_native_display.py`. The warnings
  are existing dependency deprecations.
- Only standard `1280x720p60` targets were built. No 720x720 circular target
  was invoked. After the rack was powered back on, the qualified archives were
  flashed successfully: REZO to slot 2, REZOMO to slot 3, and STREZO to slot 4.
- Qualified archives and final post-route clocks:
  - REZO seed 7: 24,148 packed cells (140 free), 6,900 FF, 22 DP16KD;
    DVI5X 388.95, AUDIO 70.12, SYNC 62.24, DVI 74.84 MHz. Archive
    `build/rezo-r5/rezo-0f79dfb9-r5.tar.gz`, SHA-256
    `a4927e86f62ef055f96c2d23963966af8ac064329e63e8d2945b5dbaa884e8d2`.
    This archive was created with `--package-only` after routing the exact
    authoritative JSON; its `top.bit` SHA-256 is
    `6222aecfe69371aa9064a0c119f3baab97ee0556a084762e9c875feb118de08a`.
  - REZOMO seed 9: DVI5X 431.03, AUDIO 69.04, SYNC 65.15, DVI 77.24 MHz.
    Archive `build/rezomo-r5/rezomo-0f79dfb9-r5.tar.gz`, SHA-256
    `cc2c2d7b5722202764303616bfb19b0968db3e9ffac57572a3ade3ce1e733d61`;
    `top.bit` SHA-256
    `18ad8a7ee10fc55e89c9d7f904b4854450ed1ab9d0143f84f29c539cb3270fd6`.
  - STREZO seed 11: 23,392 packed cells (896 free), 6,919 FF, 21 DP16KD;
    DVI5X 448.83, AUDIO 71.82, SYNC 63.76, DVI 78.18 MHz. Archive
    `build/strezo-r5/strezo-0f79dfb9-r5.tar.gz`, SHA-256
    `99f12206cb8661990e62ad8d7557e755f8da686c02fc7685097de00c51127556`;
    `top.bit` SHA-256
    `35016ff6330214bc9b3e52b3ccf982cb754777a615e2dcadb51cbb091224dd8c`.
- Standard target defaults are now REZO seed 7, REZOMO seed 9, and STREZO
  seed 11. The remaining action is hardware visual validation of slots 2, 3,
  and 4. No circular archive was built or flashed in this pass.
- `rezo_variant.py` is only an implementation filename introduced when the
  family targets were consolidated. REZO is still the original product,
  REZOMO the second, and STREZO the third; “variant” does not mean REZO is
  derived from REZOMO.

## 2026-08-21 superseded exact-centering investigation

Historical context only: do not resume this implementation direction unless
the user explicitly reverses the fixed-left decision above.

### 2026-08-21 implementation checkpoint: REZOMO capacity blocker

- Added `text_chip.py` with pure visible-ink bound and even-pixel centering
  helpers derived from `FONT_5X7`, plus focused unit coverage.
- REZO, REZOMO, and STREZO now have a registered translated text lookup and
  left-aligned fixed-width writers for the migrated fields. Shared fields are
  selected from precomputed per-value offsets; STREZO also covers CROSS layout
  and curve. REZOMO's offset constants were moved to block RAM and its field
  decode compressed to character row/column comparisons.
- Focused display result before the final lookup register: 84 passed across
  the six REZO-family display files. After registering the lookup, the focused
  helper/centering/native set passed 23 tests; the complete set should be rerun
  after the capacity architecture is finalized.
- REZO standard seed 9 initially placed but failed sync at 59.65 MHz and DVI at
  61.80 MHz. Registering the translated source lookup then produced a standard
  `1280x720p60` archive with no timing warnings:
  `build/rezo-r5/rezo-0f79dfb9-r5.tar.gz`.
- REZOMO standard seed 9 fails before routing with `Unable to find legal
  placement for all cells`. The direct constant-mux form synthesized to 25,836
  submodules; the first block-RAM offset-table form still synthesized to 25,963
  submodules (22 DP16KD). This is a deterministic capacity problem, not a seed
  miss. Do not flash the REZO archive alone; no slots were changed at this
  checkpoint.
- The remaining architectural task is to make REZOMO's per-value phase
  selection essentially free, likely by folding phase metadata into an
  existing writer/address memory or recovering substantial renderer capacity.
  Once REZOMO places, rerun the full display suite, build STREZO standard only,
  then flash slots 2/3/4 together. No circular build was invoked in this pass.

### Current status and user intent

- Repository: `/Users/naenyn/git/tiliqua`.
- Active branch at this checkpoint: `codex/rezo-family`.
- The user approved implementing accurate horizontal centering for **all text
  value chips in all three REZO-family bitstreams**. Every possible string a
  chip can display must be centered independently; centering only the default
  or longest value is not sufficient.
- This refactor is paused **before implementation**. No centering code has been
  edited, tested, built, flashed, or committed yet.
- Vertical centering of ordinary value chips is mostly acceptable. The page
  navigation header has separate visual issues and is not the focus of this
  refactor. Do not broaden this pass without a concrete reason.
- The three variants share `RezoTileDisplay` in `rezo_variant.py`, with variant
  additions in `rezomo_variant.py` and `strezo_variant.py`. The implementation
  must cover both the shared pages and every variant-specific value chip.
- Do not commit unless the user asks. The user's standing preference is to flash
  completed builds unless they explicitly say not to. The rack was powered on
  at this checkpoint; standard-display slots are REZO 2, REZOMO 3, STREZO 4.
- Preserve the user's unrelated untracked files. At this checkpoint they were
  `Erica Resonant FB Notes.txt`, `build/`, and
  `gateware/src/top/.DS_Store`.

### Hardware-photo evidence and why the previous claim was wrong

The user supplied four REZO photos demonstrating that horizontal centering is
not consistent:

- MAIN: preset `ALL` is visibly left of center; mode `BANK` is much closer.
- INPUT: mode `AUDIO` is right of center; target values such as `DRV` and `RES`
  are also right of center.
- OPTIONS: both `LCD` and `SAVE` are right of center.
- BANDS: preset `PERCEPT` is left of center.

Therefore, do not report that chips use consistent horizontal centering merely
because their writer origins or padded slot widths are consistent. The visible
glyph ink is what must be centered in the fixed chip rectangle.

### Root cause in the current renderer

`RezoTileDisplay` is in `gateware/src/top/rezo/rezo_variant.py`. Relevant facts:

- `CELL_SHIFT = 4`, so each text cell is 16 screen pixels wide/high.
- The current character lookup is effectively:

  ```python
  cell_x.eq(text_x[4:])
  cell_y.eq(text_y[4:])
  glyph_col.eq(text_x[1:4])
  glyph_row.eq(text_y[1:4])
  ```

- The font is 5x7. Rendering reads `bit 4 - glyph_col` and gates on
  `glyph_col < 5`. Screen bit 0 is ignored, so each font column occupies two
  screen pixels.
- A nominal glyph can occupy at most 10 of a cell's 16 horizontal pixels,
  leaving six trailing pixels. Individual glyphs have different actual ink
  bounds, so their optical/geometric ink centers also differ.
- Text RAM is 45x45 characters per page. Dynamic strings are refreshed at
  roughly 15 Hz.

Manual leading/trailing spaces and character-count centering cannot produce
accurate visible centering because a text cell's center is not the rendered
ink's center, and actual ink bounds vary by glyph and string.

### Approved implementation direction

Keep each chip at a fixed geometry, sized slightly larger than its largest
allowed value. Center each possible value by its **actual rendered ink bounds**:

1. At Python elaboration time, use the same `RezoBeamDisplay.FONT_5X7` data as
   the hardware renderer to calculate every glyph/string's leftmost and
   rightmost ink pixels.
2. Add pure helpers for string ink bounds and for the per-value x correction
   needed to align the text ink center with the chip center.
3. For chip bounds `x0..x1`, align the text's ink center to
   `Cchip = (x0 + x1) / 2`. Use one documented floor/rounding rule. Prefer even
   screen-pixel offsets so doubled font columns stay aligned; an unavoidable
   one-pixel parity difference is acceptable if handled consistently.
4. Precompute all corrections as constants. Runtime hardware should only select
   constants already implied by the value selector. Do not add runtime division,
   multiplication, a second font renderer, or a metadata RAM.
5. Apply shifts only inside explicitly registered value-chip rectangles. Labels
   and ordinary page text must remain unchanged.
6. If visual shift is `S`, renderer source lookup should use `text_x - S` (or an
   equivalent formulation). Clip both the chip field and source validity so
   neighboring text-RAM cells cannot bleed into a shifted field. Pipeline that
   validity alongside the existing glyph memory/column pipeline.
7. Remove or replace manual space padding where it fights the geometric
   correction, while still clearing the entire fixed-width text-RAM slot when a
   shorter value replaces a longer one.

The most maintainable architecture is a data-driven registry describing, for
each value chip: page, chip bounds, writer origin/slot width, allowed strings,
and precomputed offsets. Use the same registry for writer formatting and
renderer shifting where practical. Static and dynamic chips both count.

Before editing, inspect the exact current renderer pipeline. It has historically
included `cell_x_pre_q`, `text_active_pre_q`, glyph memory/read-port signals,
`glyph_col_q`, and `text_active_q`; correction validity must stay aligned with
the glyph data through those stages.

### Known value writers and tables to inventory

The following locations are clues, not a substitute for a fresh exhaustive
inventory with `rg` through all three variant files:

- Active navigation value: column 33, row 8, width 4.
- MAIN preset: column 16, row 11, width 4.
- Selected compact band frequency: page 0, column 29, row 14, width 3.
- INPUT modes: page 2, column 20 at the native input mode rows, width 5.
- INPUT values: page 2, column 20 at the value rows, width 3.
- FILTER type: page 7, column 14, row 11, width 4.
- OUTPUT dry value: page 4, column 31, row 18, width 4.
- FEEDBACK frequency: page 1, column 29, row 16, width 3.
- OPTIONS palette: page 5, column 22, row 17, width 6.
- OPTIONS save state: page 5, column 22, row 21, width 7.
- STREZO layout: page 6, column 16, row 11, width 7.
- STREZO BANDS selected frequency: page 6, column 20, row 22, width 5.
- Feedback damping value: page 1 at the native damping writer, width 5.
- Static values also require coverage, including BANK/FILTER mode values and all
  REZOMO CLOCK and STREZO-specific pages.

Known manually padded tables include:

```python
preset_names = ("ALL ", "ODD ", "EVEN", "LOW ", "MID ", "HIGH", "ZERO")
target_names = ("FB ", "RES", "DRV", "G1 ", "G2 ", "G3 ", "G4 ")
nav_names = ("NAV ", "EDIT")
damp_names = (" OFF ", "LIGHT", " MED ", "HEAVY", " MAX ")
layout_names = (" LEGACY", " OCTAVE", "PERCEPT", "  USER ")
filter_type_names = (" LP ", " HP ", " BP ", "NOT ")
palette_names = ("  LCD ", " AMBER", " CYAN ", " GREEN", "VIOLET")
save_names = (" SAVE  ", "SAVING ", " SAVED ", " ERROR ", "NO SLOT")
```

Also audit INPUT mode (`"AUDIO"` versus padded `CV`), OUTPUT dry, compact
frequency strings, and all variant tables. Manual padding must not survive as
an unexamined second centering system.

Known compact chip geometry includes:

- Palette: x=344..456, y=260..300; writer x=352.
- Save: x=328..456, y=324..364; writer x=352.
- Layout: x=256..384, y=168..200; writer x=256.
- MAIN mode: x=464..584, y=168..200.
- FILTER type: x=216..288, y=168..200.
- INPUT mode: x=304..402 (98 pixels wide); writer x=320.
- INPUT value: x=304..370 (66 pixels wide); writer x=320.

The INPUT writer origin is a concrete example of why `AUDIO`, `DRV`, and `RES`
appear right-shifted. Recheck all precise bounds in current code rather than
assuming this list is complete or current.

### Verification requirements

- Add pure unit tests for font ink-bound and offset helpers.
- Add or extend display pixel tests so every allowed value in every registered
  chip is exhaustively checked for centered visible bounds and containment.
- Representative regressions must include `ALL`/`BANK`, `AUDIO`/`CV`,
  `DRV`/`RES`/`FB`, all palettes (`LCD`, `AMBER`, `CYAN`, etc.), every SAVE
  state, `PERCEPT` and all layouts, FILTER types, damping modes, REZOMO CLOCK
  choices, and STREZO-specific values.
- Allow at most the unavoidable one-screen-pixel parity difference after the
  documented rounding rule. Verify that text remains inside intended padding.
- Relevant tests include:
  - `gateware/tests/test_rezo_display.py`
  - `gateware/tests/test_rezo_standard_display.py`
  - `gateware/tests/test_rezomo_native_display.py`
  - `gateware/tests/test_strezo_native_display.py`
  - any additional variant display tests found by `rg`.
- Run `git diff --check`, focused pytest, and Python compilation where relevant.
- After tests pass, build all three **standard, non-circular** variants. Reuse
  recorded qualified/default seed metadata rather than blindly chasing random
  seeds. If all three builds pass and the rack is still available, flash REZO
  to slot 2, REZOMO to slot 3, and STREZO to slot 4.

Recent commits useful for build/geometry context include:

- `0f79dfb9 Record qualified REZO family standard seeds`
- `3cf5fe57 Pipeline STREZO motion depth endpoint`
- `2517dc8d Pipeline STREZO motion indicator endpoint`
- `1d58670e Pipeline STREZO feedback display endpoints`
- `9ddf2a9f Standardize REZO family control geometry`
- `a235999a Record qualified STREZO standard seed`

Recheck actual HEAD and current build metadata before building. The older
standard-display hardware checkpoint later in this document is historical and
must not be mistaken for the current branch tip.

### Recommended resume order

1. Inspect the current shared text writer/renderer and both variant subclasses.
2. Inventory every fixed text-value chip, its bounds, its writer slot, and all
   possible strings.
3. Implement the pure font-metric/centering helper and its unit tests.
4. Introduce the chip registry and the clipped correction pipeline.
5. Remove conflicting manual padding while preserving slot clearing.
6. Run exhaustive pixel and existing regression tests.
7. Build the three standard variants and flash slots 2/3/4 if permitted.
8. Update this section with exact test results, archives/seeds, flash results,
   and any remaining exceptions.

## 2026-08-13 native circular-display migration

The REZO renderer at commit `3924b67e` has now been validated successfully on
the official Tiliqua circular display. Its display contract is therefore the
authoritative target for REZOMO as well:

- upright native canvas: 720x720 pixels;
- wholly visible safe square: half-open `x=[106,614)`, `y=[106,614)`, exactly
  508x508 pixels;
- standard `1280x720p60`: center the native canvas horizontally, with no
  rotation and no scaling;
- official `720x720p60r2`: apply the 90-degree panel-mount correction, with no
  scaling;
- the REZOMO identity may occupy the top circular arc, but every interactive
  page element must remain inside the safe square;
- all active geometry is authored directly in final native pixel coordinates.
  Do not reintroduce the historical 720-to-508 coordinate lookup or scale text
  and rectangles independently.

The migration is intentionally renderer-only. CLOCK DSP, navigation target
IDs, telemetry, persistence layout, and saved-state migration must remain
unchanged. Seven shared pages (BANK, FEEDBACK, INPUT, GROUPS, OUTPUT, OPTIONS,
and BANDS) follow the proven REZO native geometry. CLOCK receives its own
native slot layout while retaining every algorithm-dependent control.

Build aliases are `pdm run rezomo build --fs-192khz` for the standard preview
and `pdm run rezomo_round build --fs-192khz` for the official screen. Neither
artifact is to be flashed during this unattended migration. Final archives
must be qualified by display mode in their filenames and both routes must be
recorded in `BUILD_PERFORMANCE.md`.

The migration is implemented as of the 2026-08-13 candidate. The native
renderer owns the 720x720 coordinate system and transforms only its final
pixel address: standard output adds a 280-pixel horizontal canvas offset,
while the official target applies the 90-degree panel correction. Neither
path scales geometry. The native CLOCK page is stacked to keep all controls
inside the safe square; its values, target IDs, and clock algorithms are
unchanged. Shared BANK, INPUT, GROUPS, OUTPUT, FEEDBACK, OPTIONS, and BANDS
pages use the same final-pixel layout rules proven on REZO.

Display regressions cover the safe-square border, blank pixels beyond the
safe square, native CLOCK row placement, and pixel equivalence between the
standard preview and the rotated official target. The complete REZO/REZOMO
regression set passes. The first retained dirty routes are standard seed 9
(437.25 MHz DVI5X, 71.66 MHz AUDIO, 63.76 MHz SYNC, 74.65 MHz DVI) and round
seed 6 (335.23 MHz DVI5X, 72.78 MHz AUDIO, 61.41 MHz SYNC, 80.85 MHz DVI).
Seed defaults are target-specific and encoded in their entry points; an
explicit `TILIQUA_REZO_SEED` still overrides either for experiments.

## 2026-08-07 REZOMO release candidate

The clocked variant now has its own operator-facing identity: **REZOMO**. The
tile header, legacy beam header, bitstream manifest, and help text all use the
new name. `pdm run rezomo` is the preferred build alias; `pdm run rezo` remains
available as a source-compatible alias and also defaults to the REZOMO manifest
name. Internal `Rezo*` class names and the persisted `REZO` record magic remain
unchanged deliberately, avoiding an unnecessary logic and save-format
migration.

[`REZOMO_USER_GUIDE.md`](REZOMO_USER_GUIDE.md) is the complete operator guide.
It documents BANK from signal flow through every supporting page, then CLOCK,
the shared controls, input roles, all four algorithms, persistence, and patch
examples. The old partial clocked guide was removed; the original
[`REZO_USER_GUIDE.md`](REZO_USER_GUIDE.md) remains the guide for the separate
BANK/FILTER bitstream.

All 39 comparison, display, UI, and persistence tests pass. The pre-commit
seed-9 REZOMO build uses 20,737 LUT4, 24,081 packed cells (207 free), 6,519 FF,
and 18 BRAM. Final timing passes at 418.24 MHz DVI5X, 77.02 MHz AUDIO, 60.10 MHz
SYNC, and 76.07 MHz DVI. The archive is
`gateware/build/rezomo-r5/rezomo-16da16f7-r5.tar.gz`; it has not been flashed.
The `top.bit` SHA-256 is
`672f7fac86ff5b6e0ad57a9b6cd0797535d4e5181e1ef787ab9be3887088275e` and the
archive SHA-256 is
`25bbd63b5a434420c4a9aa19b74990b25b6233fab1cf6740f7551bf9f19f2614`.

## 2026-08-07 CLOCK alignment polish candidate

The current working tree corrects the two remaining CLOCK settings-page
alignment issues found during hardware testing. All four algorithm names now
share one 136-pixel MODE box centered between the character-grid positions of
odd- and even-length names. This holds every name within four pixels of the
same center without adding a mode-dependent pixel shifter. The two parameter
columns use 160-pixel value boxes instead of 176-pixel boxes. DIRECTION,
SOURCE, and BPM move one 16-pixel character cell inside the content panel;
their existing value text becomes naturally centered in the narrower boxes.
The full-width power-of-two DEPTH slider and its resource savings are retained.

The fixed comparator-friendly MODE rectangle also improves synthesis. Relative
to CLOCK-DEPTH-SLIDER-S8, this candidate saves another 108 LUT4 and 120 packed
cells with no FF or BRAM increase. All 27 REZO tests pass. The exact seed-9
route uses 20,737 LUT4, 24,081 packed cells (207 free), 6,519 FF, and 18 BRAM.
It passes at 389.11 MHz DVI5X, 76.61 MHz AUDIO, 61.24 MHz SYNC, and 79.29 MHz
DVI. Seeds 1--6 and 8 were rejected for timing; seed 7 was stopped as a
congestion outlier. The archive is
`gateware/build/rezo-r5/rezo-16da16f7-r5.tar.gz`. The `top.bit` SHA-256 is
`fea0900e3b6c30868d58593334874751d3a786f5dfd31d8e41930365673abc23` and the
archive SHA-256 is
`b44cef4757ab3eb067649451cacc58aad2a8d156943b492c9ae809993542ddfb`.

## 2026-08-07 full-width CLOCK DEPTH and optimization candidate

The current working tree replaces CLOCK's numeric DEPTH value box with a
full-width slider spanning both settings columns. It retains the saved 0--16
parameter and therefore the same seventeen steps from 0 through 100 percent.
The 512-pixel interior maps each step to exactly 32 pixels, allowing the fill
endpoint to use a five-bit shift. The obsolete three-character numeric table,
its synchronizer, and three text-writer scan slots are removed. The operator
guide and display regression test describe and verify the new control.

This change is also the retained result of the post-UI optimization pass.
Relative to the previously flashed CLOCK-FIXED-DIRECTION-S8 candidate it saves
29 LUT4, 5 packed cells, and 10 FF. Two more aggressive experiments were
measured and reverted. A shared 60-bit CLOCK-name ROM passed focused tests but
made routing impractically slow. Fixing WALK's hidden legacy step in the source
unexpectedly increased the mapped design to 24,289 packed cells, one beyond
capacity. Removing WALK's now-unread display crossing similarly changed ECP5
packing to 24,342 cells. The benign crossing is retained because its exact
structure produces the smaller, timing-clean route; it does not affect the
display or user-visible behavior.

All 27 REZO tests pass. The exact seed-8 route uses 20,845 LUT4, 24,201 packed
cells (87 free), 6,519 FF, and 18 BRAM. It passes at 382.70 MHz DVI5X, 74.10
MHz AUDIO, 60.37 MHz SYNC, and 77.86 MHz DVI. The archive is
`gateware/build/rezo-r5/rezo-16da16f7-r5.tar.gz`. It was deliberately not
flashed because the rack was powered down. The `top.bit` SHA-256 is
`ad9d997be98007c1a97761df22eb0da75d2a6fc8180112d62c78e4301450ef62` and
the archive SHA-256 is
`232884b1e41183fe62c77ae86eeb0c16a66810fe2e20eb865892b84309c8d4f6`.

## 2026-08-07 CLOCK UI and continuous-BPM candidate

The current working tree polishes the CLOCK settings page without beginning
the planned post-UI optimization phase. MODE now uses the same selector
geometry as BANK's PRESET. Shared controls form the left column (DIRECTION,
SOURCE, BPM, DEPTH), while algorithm-specific controls form a right column.
Labels are right-aligned against equal-width value boxes and all values are
centered. Direction and source names are no longer abbreviated: the UI can
show FORWARD, REVERSE, PING PONG, RANDOM, AUTO INT, AUTO EXT, INTERNAL, and
EXTERNAL. SHIFT's AUTO DATA states show AUTO CV and AUTO RAND. WALK's
user-facing HEAD name is now BAND; internal constant names remain unchanged.
The shared label is now DIRECTION, and all four shared rows stay fixed in every
mode. WALK displays read-only RANDOM and navigation skips that row; its hidden
legacy step field is normalized to the fixed default. ROTATE exposes only
FORWARD/REVERSE. TURING exposes
FORWARD/REVERSE/PING PONG, changing direction once per complete loop-length
traversal. The MODE value box is offset per visible name width so each submode
is centered without adding a pixel shifter to the timing-sensitive DVI path.

TURING's right column is ordered CHANGE, BANDS, then its range geometry.
BANDS ALL shows LENGTH in row three. BANDS RANGE shows START in row three and
moves LENGTH to row four. Navigating forward follows the same visual order.
Editing START automatically shortens LENGTH when necessary, so a freshly
selected full-length RANGE is not stuck at START 1.

The internal BPM is now any integer from 15 through 300. A slow encoder detent
changes one BPM and a rapid detent changes eight. Period and three-digit label
tables use block ROMs instead of a runtime divider or wide LUT mux. Exact BPM
uses the former three-bit rate field plus its six trailing padding bits, so the
46-word V3 record does not grow or move later fields. A saved record from the
old eight-rate build is recognized by zero high bits and maps its old index to
15, 30, 45, 60, 90, 120, 180, or 240 BPM. New saves restore their exact BPM.
All other CLOCK parameters remain saved; transient modulation patterns remain
deliberately unsaved.

All 27 REZO tests pass. The exact seed-8 route uses 20,874 LUT4, 24,206 packed
cells (82 free), 6,529 FF, and 18 BRAM. It passes at 381.53 MHz DVI5X, 78.21
MHz AUDIO, 60.15 MHz SYNC, and 74.68 MHz DVI. The archive is
`gateware/build/rezo-r5/rezo-c8706835-r5.tar.gz` and was flashed to slot 4.
The `top.bit` SHA-256 is
`66907a00859a65295e46684a9350ecd5361adebf78e97fb254edbdc341726621` and
the archive SHA-256 is
`a92690006ed7de878052263b267dda95312b90b1c3e8667f62d5513870488bca`.

## 2026-08-06 CLOCK HEAD temporal-stumble candidate

Commit `c8706835` checkpoints the tested and flashed simultaneous WALK. The
current working tree adds a second WALK STYLE plus temporal drunkenness without
widening the global two-bit algorithm selector:

- `ALL` is the checkpointed behavior: all enabled bands independently step on
  every clock;
- `HEAD` moves one spatial cursor randomly up or down and changes only its
  landing band;
- disabled bands are skipped without consuming a cursor step;
- the cursor reflects at physical bands 1 and 10 rather than wrapping; and
- every spatial move is exactly one enabled band, while DRUNK 1--4 sets the
  total number of rapid landings in a possible stumble;
- CHANCE offers 0, 10, 25, 50, 75, and 100 percent stumble probabilities; and
- extra landings occur on quarter-interval subdivisions, giving DRUNK 4 a
  sixteenth-note feel under a quarter-note clock.

Both styles share the existing five WALK step sizes, bipolar value reflection,
CLOCK DEPTH, and RESET. Changing STYLE clears the transient vector and cursor.
The first external pulse measures the beginning of an interval; subsequent
pulses can launch measured stumbles. The internal clock already knows its
period. The CLOCK page reuses TURING-exclusive rows for STYLE, DRUNK, and
CHANCE, avoiding new navigation target IDs. SAVE DEFAULT stores one style bit,
two drunkenness bits, and a three-bit chance index in V3's existing padding;
the record remains 46 words. A save from `c8706835` therefore restores safely
as `ALL / DRUNK 1 / CHANCE 25`.

The first temporal scheduler kept three wide counters and left only 159 packed
cells free, producing pathological routing. The retained form uses the existing
clock counter for both internal timing and external period measurement, and
stores burst thresholds at 16-audio-sample resolution (83 microseconds at 192
kHz). This recovers 61 packed cells and 45 FF without changing musical timing.
All 39 REZO tests pass, including explicit DRUNK-4/CHANCE-100 and
DRUNK-4/CHANCE-0 event-count regressions.

The exact seed-6 route uses 20,724 LUT4, 24,068 packed cells (220 free), 6,485
FF, and 16 BRAM. It passes at 400.64 MHz DVI5X, 75.68 MHz AUDIO, 61.50 MHz
SYNC, and 75.00 MHz DVI. Seed 8 misses only SYNC at 59.18 MHz and seed 1 is
substantially worse. The archive is
`gateware/build/rezo-r5/rezo-c8706835-r5.tar.gz` and was flashed to slot 4.
The seed-6 `top.bit` SHA-256 is
`c978dafabd4424fd7ca54391c5157f80cede40b305ade287464743c2b32615c8` and
the archive SHA-256 is
`3f75378e6a60f3df9df016ac426a6d4582bd41cf611944a98ed30dffd7e21872`.

## 2026-08-06 CLOCK WALK candidate

The current working tree adds WALK as the fourth CLOCK algorithm. Each
accepted clock advances every enabled band independently by one positive or
negative bipolar modulation step. Requested motion reflects before the
half-scale signed rails instead of clipping or wrapping, so values remain
bounded and continue moving at either edge. Disabled bands remain zero, RESET
clears the complete walk, and shared CLOCK DEPTH scales the result without
altering the underlying state.

The CLOCK page reuses the `DIR / STEP` row: SHIFT, ROTATE, and TURING continue
to edit direction there, while WALK offers step values 1, 2, 4, 8, and 16.
SAVE DEFAULT includes the three-bit WALK step index in the existing 46-word V3
record. It consumes three formerly zero padding bits, reducing padding from 15
to 12 bits without moving any established field. A V3 record written by the
immediately preceding build therefore imports safely with WALK step 1; V1/V2
records still receive the normal CLOCK defaults and WALK step 4.

The first WALK implementation used a shared 17-bit add/subtract and two 17-bit
comparisons. It fit with only 293 packed cells free, but seed 2 failed SYNC at
54.38 MHz and was not flashed. Since all WALK values and steps have eight zero
low bits, the final implementation performs identical arithmetic in signed
high-byte units. It also replaces the deep four-algorithm selector mux with a
wrapped two-bit increment/decrement. This recovers 250 LUT4 and 248 packed
cells from the failed attempt.

All 38 REZO tests pass. The exact seed-2 route uses 20,417 LUT4, 23,747 packed
cells (541 free), 6,439 FF, and 16 BRAM. It passes at 443.85 MHz DVI5X,
72.80 MHz AUDIO, 62.68 MHz SYNC, and 77.89 MHz DVI. The archive is
`gateware/build/rezo-r5/rezo-965f4783-r5.tar.gz` and was flashed to slot 4.
The seed-2 `top.bit` SHA-256 is
`68377a1bb2bb55bd47d27c1b4fccd2e508941fe9942c0fbf2321509c5b3b5e98` and
the archive SHA-256 is
`8b058eff7ee0e4bb16e521f43694e0cac74d3b4c9197ebd57e6b664b0483469b`.

## 2026-08-06 CLOCK version-3 persistence checkpoint

The current working tree adds backward-compatible CLOCK persistence on top of
the SHIFT internal-random candidate. SAVE DEFAULT now retains BANK/CLOCK mode,
algorithm, direction, clock source and internal BPM, CLOCK depth, SHIFT DATA
source, TURING length/change/target/start, and all four bits of every INPUT
target. The live SHIFT/ROTATE/TURING modulation pattern remains transient.

The V3 record remains 46 words, equal to V2. It reuses six bytes of FILTER's
removed modulation matrix, so all established BANK fields keep their exact
locations. The journal accepts V1 (42-word) and V2 (46-word) records; during a
legacy import it replaces the repurposed words with safe CLOCK defaults and
supplies the established V2 band tail for V1. A same-length V2 regression
specifically verifies that obsolete FILTER bytes cannot become CLOCK settings.

At this checkpoint, live CLOCK controls were copied to a 33-bit shadow snapshot on SAVE and applied
from that shadow once after LOAD. This keeps the circular state-scan mux out of
the clock sequencer's timing paths. Directly scanning the live controls fit but
missed SYNC across seeds 1, 2, 3, 5, and 7. The retained shadowed seed-2 route
uses 19,887 LUT4, 23,199 packed cells (1,089 free), 6,409 FF, and 16 BRAM. It
passes at 400.00 MHz DVI5X, 74.92 MHz AUDIO, 60.76 MHz SYNC, and 81.78 MHz DVI.
All 36 REZO tests pass. The archive is
`gateware/build/rezo-r5/rezo-965f4783-r5.tar.gz` and was flashed to slot 4.
The seed-2 `top.bit` SHA-256 is
`abb4115d27cc8836bfae3be1fbaa62c263b491e8d83bc36eb3471462eedf318d` and
the archive SHA-256 is
`cb0a0fb94f27eb58eadbebba0207f6d961c9e8af65ff23810a5eff6017a3b77e`.

## 2026-08-06 SHIFT internal random DATA candidate

Commit `965f4783` checkpoints the tested and flashed TURING block-RAM
optimization. The current working tree adds a reusable DATA source selector to
SHIFT:

- `CV` (default) samples the existing INPUT-page DAT assignment;
- `RAND` samples an independent 32-bit maximal-length bipolar generator that
  advances continuously at the accepted 192 kHz audio sample rate; and
- `AUTO` follows physical patch detection for the assigned DAT jack, selecting
  external CV while patched and internal random while unpatched. The display
  reports `A CV` or `A RND` for the effective AUTO choice.

The selector reuses TURING TARGET's y=420 CLOCK-page row because the controls
are algorithm-exclusive. ROTATE ignores DATA, while TURING retains its own
independent mutation generator. Shared CLOCK DEPTH scales CV and random SHIFT
captures identically. The version-3 persistence candidate above saves DATA
source with the other CLOCK settings.

All 34 REZO tests pass. New coverage verifies CV compatibility, RAND ignoring
external voltage, AUTO physical-jack switching, selector navigation/cycling,
and display geometry. The exact seed-2 route uses 19,664 LUT4, 22,980 packed
cells (1,308 free), 6,409 FF, and 16 BRAM. The complete feature costs only 45
LUT4, 45 packed cells, and 46 FF over the TURING-BRAM checkpoint, with no new
BRAM or multiplier. It passes at 436.11 MHz DVI5X, 74.37 MHz AUDIO, 64.77 MHz
SYNC, and 77.10 MHz DVI. Seed 1 was rejected for DVI5X and DVI misses; seeds 6
and 8 were stopped after seed 2 passed.

The archive is `gateware/build/rezo-r5/rezo-965f4783-r5.tar.gz` and was flashed
to slot 4. The seed-2
`top.bit` SHA-256 is
`61c614fcd651d973fc35f68093173d50b576cfa838dc3dbbf97a486091827362` and
the archive SHA-256 is
`126566148eb630751ea1f08efc9133a213be8ee6b37a84608c2261ae40b42dc4`.

## 2026-08-06 TURING block-RAM optimization candidate

Commit `c9be114a` checkpoints the tested and flashed TURING targeting/depth
feature. The current working tree makes a behavior-preserving area trade:

- the private 10-by-16-bit TURING loop now uses one synchronous block RAM
  instead of ten registers behind large dynamic read/write muxes;
- a short sequential clear/read/write/prime worker preserves deterministic
  initial fill, mutation, forward/reverse locked rotation, ALL repetition,
  disabled-band skipping, and RANGE remapping; and
- CLOCK input acceptance pauses while that worker is active, so no partially
  shifted pattern can reach the audio path. A ten-step update remains far
  shorter than one 192 kHz audio sample interval.

All 33 REZO tests pass. The exact seed-1 route uses 19,619 LUT4, 22,935 packed
cells (1,353 free), 6,363 FF, and 16 BRAM. Relative to the flashed
CLOCK-TARGET-DEPTH-S7 build, it recovers 886 LUT4, 896 packed cells, and 110 FF
at the cost of one BRAM. It passes at 415.45 MHz DVI5X, 73.06 MHz AUDIO,
61.58 MHz SYNC, and 76.09 MHz DVI. Seeds 2, 6, and 8 were rejected for small
timing misses; longer seed-4 and seed-7 congestion searches were stopped once
seed 1 passed.

The archive is `gateware/build/rezo-r5/rezo-c9be114a-r5.tar.gz` and was flashed
to slot 4. The seed-1
`top.bit` SHA-256 is
`27a40d83c4eefb714c9b138000ec254f46cc377009c5b563c0d2f8f95ba9a957` and
the archive SHA-256 is
`12a3fb6dfc2de15e78c61be14d2dfe64b4fbe47079c8d0bcd78a44f2b141647f`.

## 2026-08-06 TURING target and shared CLOCK depth candidate

The current working tree extends every CLOCK algorithm with a shared DEPTH
control and makes short TURING patterns useful in two distinct ways:

- DEPTH scales SHIFT, ROTATE, and TURING modulation from 0 to 100 percent in
  17 steps without changing the underlying clock pattern;
- TURING TARGET `ALL` repeats a short pattern across every enabled band,
  skipping disabled bands without consuming a pattern step;
- TARGET `RANGE` maps one copy of the pattern onto physical bands starting at
  the one-based START value, leaving bands outside the range unmodulated; and
- RANGE length is clamped at the upper edge while target/start edits remap the
  existing loop rather than regenerating it.

All 33 REZO tests pass. New regressions cover positive and negative shared
depth scaling, disabled-band-aware ALL repetition, RANGE mapping to bands 6--8,
and CLOCK-page navigation/display for DEPTH, TARGET, and START.

The exact seed-7 route uses 20,505 LUT4, 23,831 packed cells (457 free), 6,473
FF, and 15 BRAM. It passes at 389.11 MHz DVI5X, 74.71 MHz AUDIO, 61.17 MHz
SYNC, and 74.81 MHz DVI. Seeds 3 and 4 failed only SYNC; the initial seed-8
build failed DVI5X and DVI. The archive is
`gateware/build/rezo-r5/rezo-7f6819a3-r5.tar.gz` and was flashed to slot 4.
The seed-7 `top.bit` SHA-256 is
`2da8bc3dd36e9da855c334706103c7a13dbea9960c777f824341e4b9fe34583b` and
the archive SHA-256 is
`600b07f57c73d49978c68f708454d3a3640ccc574578a7a3cb0e06c033eededb`.

This route is tight at 98 percent packed utilization. Treat another substantial
feature as an optimization task first rather than assuming the remaining 457
cells are usable routing headroom. CLOCK controls remain transient until a
version-3 persistence record is designed.

## 2026-08-06 internal clock and AUTO source candidate

The current working tree extends the TURING candidate with a shared internal
clock source used by SHIFT, ROTATE, and TURING:

- SOURCE choices are AUTO (default), INT, and EXT;
- AUTO reads the audio board's physical jack detector for whichever INPUT is
  assigned to CLK, rather than inferring presence from pulse activity;
- the display reports `AUTO I` or `AUTO E` for the effective source;
- internal rates are 15, 30, 45, 60, 90, 120, 180, and 240 BPM, defaulting to
  120 BPM; and
- cable/source/rate changes cannot generate a clock: internal operation waits
  a full new interval, while external operation requires a low level followed
  by a fresh rising edge.

All 33 REZO tests pass. They cover source overrides, physical-patch AUTO
selection, insertion while the gate is high, unplug fallback timing, the eight
BPM UI choices, CLOCK-page navigation/display, and every earlier DSP,
persistence, SHIFT, ROTATE, and TURING regression.

The exact seed-8 route uses 19,524 LUT4, 22,760 packed cells (1,528 free),
6,105 FF, and 15 BRAM. It passes at 399.20 MHz DVI5X, 72.70 MHz AUDIO,
63.61 MHz SYNC, and 80.33 MHz DVI. Seed 7 failed only DVI at 71.25 MHz;
seed 6 failed DVI5X and SYNC. The archive is
`gateware/build/rezo-r5/rezo-7f6819a3-r5.tar.gz` and was flashed to slot 4.
The seed-8 `top.bit` SHA-256 is
`461e4a90d7f7e58de1421204581698df09730c6e977bc3ceafbb2c4c8487667e` and
the archive SHA-256 is
`399a368b7b570ccacd65ad8e4035d45a427d5803572feff43e22b59779c2a17a`.

SOURCE and BPM remain transient alongside the other CLOCK settings until a
version-3 state record is designed. A future internal DATA source should reuse
this source-selection model but does not need to change the clock engine.

## 2026-08-06 CLOCK TURING candidate

Commit `7f6819a3` checkpoints the tested SHIFT/ROTATE implementation. The current
working tree adds TURING as a third algorithm:

- a full-resolution internally randomized looping modulation register;
- an active-high `LCK` INPUT target: high repeats the loop exactly, while low
  permits mutation according to CHANGE;
- LENGTH 2..10 over the first enabled bands, skipping disabled bands;
- CHANGE choices of 1, 3, 6, 12, 25, 50, and 100 percent;
- forward and reverse directions, with RESET deliberately ignored; and
- a sequential search/write worker that avoids ten parallel wide value muxes.

The first LENGTH pulses seed the loop even if LCK is already high, so an empty
loop cannot be locked. Changing algorithm or length starts a fresh fill. TURING
uses additive modulation over the untouched BANK levels, like ROTATE.

All 32 REZO tests pass, including exact locked repetition, 100% mutation,
forward/reverse movement, disabled-band skipping, length limiting, RESET
immunity, UI navigation, and display coverage. The exact seed-7 route uses
19,135 LUT4, 22,307 packed cells (1,981 free), 6,051 FF, and 15 BRAM. It passes
at 394.94 MHz DVI5X, 74.58 MHz AUDIO, 61.08 MHz SYNC, and 80.28 MHz DVI. The
archive is `gateware/build/rezo-r5/rezo-7f6819a3-r5.tar.gz` and was flashed to
slot 4. The seed-7 `top.bit` SHA-256 is
`dac028b76ea47585a1ae01d40a5f9e27106b3e4cabc0892c7435fe6fe7d8f7bf` and
the archive SHA-256 is
`0f5a865463b67368371b614ca5e6d78dd707850681d473432de5d2f7de12270d`.
Seed 4 failed SYNC at 56.93 MHz; seed 6 failed DVI5X and SYNC.

At this checkpoint, an internal LFO/noise DATA source and future WALK mode
could build on the shared clock engine without changing TURING's self-contained
random generator; both were implemented in the later checkpoints above.

## 2026-08-06 CLOCK SHIFT/ROTATE checkpoint

The first external-clock MVP was implemented and is now incorporated into
[`REZOMO_USER_GUIDE.md`](REZOMO_USER_GUIDE.md):

- BANK/CLOCK mode selector on the main page;
- BANK-equivalent CLOCK main controls plus a separate direction settings page;
- SHIFT and additive BANK-shape ROTATE algorithms with mode-specific directions;
- DATA, CLOCK, and RESET INPUT-page targets, defaulting to IN2, IN3, and IN1;
- ten captured bipolar SHIFT values or circulating BANK-level ROTATE origins,
  overlaid as modulation on the untouched BANK shape;
- rising-edge clock detection with high/low hysteresis;
- SHIFT forward/reverse/random and ROTATE forward/reverse/ping-pong directions;
- reset clearing the vector and restarting ping-pong/random state; and
- automatic exclusion of all CLOCK-role jacks from normal audio/CV routing.

All 31 REZO tests passed at this checkpoint, including exact BANK DSP vectors and CLOCK direction,
hysteresis, reset, INPUT-target routing, navigation, and display coverage. The
latest dirty seed-4 route uses 18,306 LUT4, 21,448 packed cells (2,840 free),
5,953 FF, and 15 BRAM. It passes at 449.24 MHz DVI5X, 72.82 MHz AUDIO,
61.24 MHz SYNC, and 79.00 MHz DVI. Its archive is
`gateware/build/rezo-r5/rezo-176cfc5e-r5.tar.gz` and was flashed to slot 4.

The CLOCK controls and live vector are intentionally absent from persistence
until a version-3 record is designed.

## 2026-08-06 `rezoclocked` BANK-only baseline

Branch `rezoclocked` now has a clean, buildable foundation for replacing
FILTER with a shared clocked band-transformation mode. Commit `8a27f1a7`:

- removes FILTER response generation and modulation from `RezoCore`;
- removes FILTER/MATRIX navigation, controls, display pages, faders, and the
  display-side modulation-matrix RAM;
- makes BANK input mixing, feedback, enable masking, output sends, and DRY
  routing unconditional;
- retains the old FILTER bit positions only as inert version-2 persistence
  placeholders, preserving every later BANK field and the fine-frequency
  padding layout byte-for-byte; and
- removes FILTER-only regressions while retaining the BANK audio-cycle,
  known-good DSP, UI, display, and persistence coverage.

All 27 REZO tests pass. The exact commit-stamped seed-1 build passes every
clock and produces
`gateware/build/rezo-r5/rezo-8a27f1a7-r5.tar.gz`. It was deliberately not
flashed. The bitstream SHA-256 is
`cd4471e3034dba751b3cf568fdfbe5b2d78e67d386d6fbaed434b8a1992db2a8`;
the archive SHA-256 is
`bc9e97dc693a7dec9a6f88d1e5313737f7a9a8a0f77475f781e07c823df191a6`.
Its measured resources are 16,512 LUT4, 19,508 packed cells (4,780 free),
5,578 FF, and 15 BRAM. Final clocks are 443.07 MHz DVI5X, 76.24 MHz AUDIO,
61.16 MHz SYNC, and 80.57 MHz DVI.

Relative to the flashed `b2812acc` release candidate, this recovers 4,715
packed cells, 4,099 LUT4, 773 FF, and four BRAM. This is the formal baseline
for CLOCK work. Do not spend the entire margin at once: preserve enough room
for physical clock conditioning, a ten-value double buffer, new UI text and
geometry, tests, and routing variability.

Recommended first CLOCK increment:

1. Reintroduce the top-right BANK/CLOCK selector and use the former FILTER page
   slot for a compact CLOCK main page.
2. Establish fixed MVP input roles in CLOCK mode: IN0 audio, IN1 sampled value,
   IN2 clock, and IN3 reset. Avoid a routing matrix until hardware behavior is
   proven.
3. Implement one rising-edge conditioner with hysteresis and minimum spacing.
4. Feed one shared ten-band state engine with SHIFT first. Add ROTATE and WALK
   as operations over the same state/indexing only after SHIFT is verified.
5. Publish a completed vector atomically into the existing smoothed band-level
   path; keep BANK levels untouched so returning to BANK restores its shape.
6. Reuse the old persistence positions in a version-3 record only after the
   CLOCK state and controls are settled.

The existing `REZO_USER_GUIDE.md` continues to document the released `rezo`
bitstream. Write a separate clocked guide, or revise it, once CLOCK behavior is
stable enough to test on hardware.

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

The complete targeted regression set now contains 39 tests, including exact USER
working-vector semantics, all ten persisted frequencies/enables, version-1
migration, the known-good DSP vector, two-row BANDS geometry, a five-digit
frequency readout, mode-change gain slew, disabled-band frames, programming
across a 256-byte flash page, deterministic bounded ALL WALK behavior, and
HEAD cursor/stride/disabled-band behavior:

```sh
pdm run pytest \
  tests/test_rezo_ui.py \
  tests/test_rezo_display.py \
  tests/test_rezo_persistence.py \
  tests/test_rezo_compare_path.py
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

## Standard-display hardware checkpoint (2026-08-20)

Commit `f612bab9` is the hardware checkpoint for the first post-release bug
pass. It fixes STREZO CEILING/KNEE display scaling, OUTPUT DRY selection, and
BANDS preset centering. It also expands REZO FILTER mode with shared editable
band frequencies, per-input AUDIO/CV roles, dry routing, and an independent
feedback amount. The focused regression suites pass.

All three standard 1280x720 builds completed successfully with their target's
checked-in default synthesis and placement recipe, and were flashed and booted
in the following stable slot assignment:

| Target | Default seed | Archive | Slot | Archive SHA-256 | `top.bit` SHA-256 |
|---|---:|---|---:|---|---|
| REZO | 4 | `build/rezo-r5/rezo-f612bab9-r5.tar.gz` | 2 | `f14af9ddb32078a8f99081c7482e4a0ee4ad6502c4aecc5030c551a38c6d9df2` | `2e8464a6fcc253e7624c07733482d232cbbaf8259f3f257b06e9ba958e3db078` |
| REZOMO | 9 | `build/rezomo-r5/rezomo-f612bab9-r5.tar.gz` | 3 | `e69b336bc589e90bfdfb6bf70ec37fd7f3e5089cf0a1f8ded2e16fab8c344d9f` | `b63b54ad828900a6719f34d83afb503eee7f0c31f1c79c4a13f30755820c7717` |
| STREZO | 7 | `build/strezo-r5/strezo-f612bab9-r5.tar.gz` | 4 | `103f9b2d088873ebae8093e35d3f22cd35de085de6d3a6360b23ee073fe2dc22` | `4ad8c30297dfff78d8c72304bf3ed49a8233e194ea45925ed1a79e2f76609de3` |

The timing summaries recorded by the successful routes were:

| Target | DVI5X | AUDIO | SYNC | DVI |
|---|---:|---:|---:|---:|
| REZO | 387.90 MHz | 71.60 MHz | 61.21 MHz | 77.14 MHz |
| REZOMO | 414.42 MHz | 76.28 MHz | 63.15 MHz | 79.77 MHz |
| STREZO | 394.79 MHz | 74.15 MHz | 63.01 MHz | 79.16 MHz |

These are deliberately standard-display builds only. No circular target was
rebuilt for this checkpoint. Continue to use slots 2, 3, and 4 for REZO,
REZOMO, and STREZO respectively unless the user explicitly changes the
assignment.

## Standard-display chip-alignment checkpoint (2026-08-22)

Commit `f7ebab7` normalizes the remaining native value-column alignment:
FEEDBACK DAMPING now follows the KNEE/CEILING column, STREZO CROSS CURVE follows
the OPTIONS value column, and MAIN/BANDS PRESET values share the REZO/STREZO
MAIN left origin across all three products. The full family suite passes 205
tests.

Only the standard `1280x720p60` targets were built. The final archives carry
seed-record commit `775de97b`; no circular target was invoked. Every archived
`top.bit` was checked byte-for-byte against its timing-qualified routed file.

| Target | Seed | COMB / free | LUT4 | FF | BRAM | DVI5X / AUDIO / SYNC / DVI MHz | Archive SHA-256 | `top.bit` SHA-256 | Slot |
|---|---:|---|---:|---:|---:|---|---|---|---:|
| REZO | 2 | 24,083 / 205 | 20,485 | 6,907 | 22 | 380.37 / 73.03 / 62.17 / 79.21 | `c7e6c640d3c0086329b341a914909ad09cf05bb3529596a9d82c709b7944bb94` | `cd2b1965e6d0e5d4d59b8814709e0a573577a9bac2d37c7a20d6635e7cc42260` | 2 |
| REZOMO | 9 | 23,868 / 420 | 20,568 | 7,105 | 22 | 391.08 / 72.71 / 62.90 / 77.78 | `e33e4d9a799a17f0039132ddac8ff24924b9d41810cbcaa70bf9d908d169e52b` | `baa37c2d57536b5199af9559e29244990a0a128bce9917ab2d2421d6576f6a44` | 3 |
| STREZO | 4 | 23,248 / 1,040 | 19,992 | 6,926 | 21 | 434.22 / 74.45 / 62.36 / 75.19 | `97944560f50684c178c40faf0ec51db362082950ecb9ae6ebfcfa4b2d590dc56` | `7a0a450e8f3d4ed87e0f27483c0e455d4403c2c90722cbb8e622e2c7fe2bebc2` | 4 |

The exact archives are `rezo-775de97b-r5.tar.gz`,
`rezomo-775de97b-r5.tar.gz`, and `strezo-775de97b-r5.tar.gz`. All three flash
operations completed successfully on Tiliqua R5 serial `E46534A193222B21`.
REZO's prior default seed 9 missed DVI, and STREZO's prior default seed 8 missed
DVI5X and DVI; the checked-in standard defaults are therefore now seeds 2 and
4 respectively. REZOMO retains seed 9.

## STREZO MOTION alignment correction (2026-08-22)

Commit `7583d9bb` restores the BANDS/MOTION two-column layout. LFO SHAPE,
RATE HZ, PHASE, and DEPTH now share a right edge at native column 16, followed
by a 16-pixel gutter and the value/control column at x=272. The complete DEPTH
track, fill, selection marker, and bipolar monitor moved left from x=280..568
to x=272..560 so they align with the chips above.

The DAMPING chip remains intentionally four pixels inside the FEEDBACK fader
track: its surrounding selection outline begins at x=268, exactly matching the
fader selection outlines, while preserving the family chip's standard text
inset.

The STREZO and shared-family regression sets pass 79 tests. Only standard
`1280x720p60` STREZO was built. Seed 4 passes at 384.32 MHz DVI5X, 72.85 MHz
AUDIO, 66.34 MHz SYNC, and 76.23 MHz DVI. Archive
`strezo-7583d9bb-r5.tar.gz` has SHA-256
`d4ea7785d8a0fad2177e456d58d4c3ffe5df29058b73206cc025f8303547beff`;
its verified `top.bit` SHA-256 is
`584c37d7dbe64ce1d60c5bd348e44205deee05396102102660340fbad7055f81`.
The archive was flashed successfully to slot 4. No circular target was built.
