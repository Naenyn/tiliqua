# REZO family build and consolidation guide

The `codex/rezo-family` branch is the single development home for REZO, REZOMO,
and STREZO. Product and display selection are explicit build-time choices; they
no longer depend on which historical branch is checked out.

## Build matrix

Run commands from `gateware/`:

| Product | Display | Command | Build/archive prefix |
|---|---|---|---|
| REZO | standard 1280x720 | `pdm run rezo build --fs-192khz` | `rezo-r5/`, `rezo-*` |
| REZO | circular 720x720 | `pdm run rezo_round build --fs-192khz` | `rezo-round-r5/`, `rezo-round-*` |
| REZOMO | standard 1280x720 | `pdm run rezomo build --fs-192khz` | `rezomo-r5/`, `rezomo-*` |
| REZOMO | circular 720x720 | `pdm run rezomo_round build --fs-192khz` | `rezomo-round-r5/`, `rezomo-round-*` |
| STREZO | standard 1280x720 | `pdm run strezo build --fs-192khz` | `strezo-r5/`, `strezo-*` |
| STREZO | circular 720x720 | `pdm run strezo_round build --fs-192khz` | `strezo-round-r5/`, `strezo-round-*` |

Every target has a distinct artifact name and therefore a distinct build
directory and archive filename. Standard and circular builds retain the same
product name in their manifests and on screen, so output isolation does not
consume extra FPGA resources. A circular `top.bit` cannot be repackaged
accidentally as a standard artifact through `--skip-build`.

`TILIQUA_REZO_FAMILY_SEED=<n>` overrides a target's qualified default placement
seed. The older `TILIQUA_REZO_SEED=<n>` override remains compatible when the
family-specific variable is unset.
The qualified defaults are seed 8 for REZO standard, seed 2 for REZO circular,
seed 9 for REZOMO standard, seed 4 for REZOMO circular, seed 7 for STREZO
standard, and seed 1 for STREZO circular.

REZO circular also selects the native `yosys` executable because its documented
staged mapping recipe is placement-hostile under the PDM environment's pinned
YoWASP mapper. Set `TILIQUA_REZO_FAMILY_YOSYS=/path/to/yosys` if the native
executable is not on `PATH`; the other three targets retain the project-default
mapper.

## Source layout

- `targets.py` is the authoritative product/display matrix.
- `rezo_variant.py` and `rezo_persistence.py` preserve the accepted non-clocked
  REZO source from branch `rezo` at `222b6caa`.
- `top.py` and `persistence.py` preserve the accepted clocked REZOMO source from
  branch `rezomo` at `483f5680`. REZOMO remains at its historical Python module
  path because generated naming changes can perturb packing on the nearly full
  FPGA; `rezomo_variant.py` is only a compatibility import.
- `strezo_variant.py` and `strezo_persistence.py` preserve the accepted linked-
  stereo source from historical branch `strezo` at `e2b23789`. They remain
  isolated while its renderer is migrated to the native safe-square contract.
- `rezo.py`, `rezo_round.py`, `rezomo.py`, `rezomo_round.py`, `strezo.py`, and
  `strezo_round.py` are deliberately thin build entry points.
- `round.py` is a compatibility shim for the older circular-build script.
- `display_common.py` owns the one family font, character sets, and semantic
  palettes used by every active tile renderer. `ui_common.py` owns shared page
  metadata, geometry, static labels, and navigation contracts.

Variant selection occurs before Amaranth elaboration, so no image carries either
REZOMO-only clock logic or STREZO-only linked-stereo DSP. The historical `rezo`,
`rezomo`, `rezoclocked`, and `strezo` branches remain recovery and provenance
references while consolidation proceeds.
Each variant script is executed with its historical `__main__` module identity;
this preserves generated naming and packing for the near-capacity designs.

## Extraction policy

The coexistence checkpoint is intentionally behavior-preserving. Shared code
should be extracted in small, independently tested steps:

1. value-chip geometry and native display mapping;
2. shared BANK, INPUT, and OPTIONS rendering;
3. common navigation transitions and control constants;
4. common filterbank DSP and telemetry;
5. persistence transport primitives, retaining variant-specific record schemas;
6. REZOMO-only clock algorithms and state in a clocked feature module.

After each extraction, run every affected variant suite and compare synthesized
resource and timing results before deleting duplicated code.

### Shared page-contract checkpoint (2026-08-20)

The common support pages now use `ui_common.py` as their structural source of
truth. REZO, REZOMO, and STREZO share native and legacy page headers, static
INPUT/GROUPS/OUTPUT/FEEDBACK labels, native row and column coordinates, and the
FEEDBACK, INPUT, and GROUPS navigation emitters. Shared tests exercise those
contracts directly, so a label, row, or navigation-order correction is made
once and checked against all three products.

The dense dynamic pixel engines remain variant-local deliberately. REZO and
REZOMO reuse tightly packed BRAM-backed mappings while STREZO has different
product data and endpoint arithmetic; making those expressions textually
identical has previously changed packing on near-full images. Their visible
contracts are instead tied together by common constants and cross-variant
display tests. Product-only BANK, BANDS, CLOCK, CROSS, and FILTER behavior also
remains in its owning variant.

## STREZO coexistence checkpoint (2026-08-14)

STREZO is now an explicit third product in the family matrix. Its accepted
`e2b23789` source and V5 persistence implementation were imported under distinct
module names, so adding STREZO does not alter the elaborated REZO or REZOMO
images. The original standard and circular build aliases now select isolated
`STREZO` and `STREZO-ROUND` artifacts through the same target mechanism as the
other family members.

The imported lineage passes all 54 of its historical DSP, display, persistence,
and UI tests. Together with the five family-target tests, the coexistence gate is
59 passing tests. This is a software baseline only: the historical renderer
still authors controls across most of the 720x720 panel and therefore does not
yet satisfy the required `x=[106,614)`, `y=[106,614)` circular safe square.
The following checkpoint records completion of that migration and fresh
standard/circular qualification.

## STREZO native safe-square qualification (2026-08-14)

Commit `6348b81` replaces STREZO's wide historical renderer with the same
upright native 720x720 coordinate contract used by REZO and REZOMO. Both video
targets author one `x=[106,614)`, `y=[106,614)` safe square; the standard target
adds only its horizontal preview offset, while the circular target applies the
panel-mount rotation after the logical UI is complete. A pixel-equivalence test
verifies representative standard and circular coordinates.

The migration also ports the current family UI conventions: native compact
page geometry, centered fixed-width value chips, `EVEN` preset spelling,
bounded INPUT faders, shared semantic palettes, and consistent PAGE/value
title controls. STREZO's product-specific FEEDBACK, GROUPS, OUTPUT, BANDS, and
CROSS pages retain their existing behavior inside the safe square.

All 64 focused STREZO/family tests pass, including cycle-accurate DSP
comparisons, historical renderer compatibility, persistence, navigation, the
new safe-square boundary checks, and standard/circular pixel equivalence.
Dense GROUPS and OUTPUT block-memory paths are pipelined before their dynamic
lookups; this raised the exact standard build's DVI result to 84.18 MHz without
changing visible cell boundaries.

| Target | Commit / seed | Packed cells | DVI5X / AUDIO / SYNC / DVI MHz | Archive SHA-256 | Status |
|---|---:|---:|---|---|---|
| STREZO standard | `6348b81` / 9 | 23,975 (313 free) | 384.17 / 70.01 / 63.85 / 84.18 | `a95f890736c439cf0d32c4b95e0c7b6a4c9f6aed486dc288ff3e19415e9f5381` | Passes 1.25% margin gate; flashed slot 4 |
| STREZO circular | `6348b81` / 1 | 24,015 (273 free) | 328.95 / 76.06 / 72.25 / 81.23 | `02ba74aa0ada6539916e81ea536b5e6a9d9fa3481341e2ad4e265b046621c622` | Passes 1.25% margin gate; not flashed |

The standard archive is
`build/strezo-r5/strezo-6348b810-r5.tar.gz`; its archived and routed `top.bit`
SHA-256 is
`ee97ab8f38a83d541d16db465b1b1e7812d09dad0d7530724ca8d52690b9b561`.
The circular archive is
`build/strezo-round-r5/strezo-round-6348b810-r5.tar.gz`; its archived and routed
`top.bit` SHA-256 is
`c123270bbffe9bd416486f82d861338a15a2bb3ad771c9d71df2101576c022ef`.

## Consolidation qualification (2026-08-14)

The coexistence checkpoint passed 107 combined REZO/REZOMO tests. All four
artifacts below pass every constrained clock, and each archive's `top.bit`
SHA-256 matches the corresponding routed file. Nothing in this qualification
was flashed.

| Target | Commit / seed | Packed cells | DVI5X / AUDIO / SYNC / DVI MHz | Archive SHA-256 |
|---|---:|---:|---|---|
| REZO standard | `8b39ff81` / 8 | 23,985 (303 free) | 460.62 / 75.12 / 60.14 / 76.44 | `06dbe7a321cf5cc70faca26b80da7c15cff4a0df18c13290564a2418327dbcdb` |
| REZO circular | `7cbdc2c7` / 2 | 23,914 (374 free) | 425.35 / 72.13 / 65.27 / 75.06 | `68f703a66f7bec3c077afc4fadc6eca64117bce1377667e3de1ef5baa91e805b` |
| REZOMO standard | `8b39ff81` / 6 | 24,193 (95 free) | 392.00 / 72.63 / 63.02 / 75.27 | `81bc70e29b4ea4251ec18a27e051d618bed4b965d5325d581e72c43458e4305a` |
| REZOMO circular | `8b39ff81` / 4 | 24,261 (27 free) | 389.56 / 73.94 / 61.87 / 76.02 | `021195d89b8ae34edd3bdfe14e3474e9223a421b278c6298d02085b528b47d36` |

The exact archives are under `build/rezo-r5/`, `build/rezo-round-r5/`,
`build/rezomo-r5/`, and `build/rezomo-round-r5/`. The two commits after
`8b39ff81` only make the REZO circular native-mapper and seed selection part of
the explicit target wrapper; the final REZO circular row verifies that complete
one-command path at the current functional head.

## Post-consolidation optimization pass (2026-08-14)

The first hardware test after the FILTER navigation and INPUT fader fix exposed
an important qualification gap. A seed-12 REZO standard route passed nominal
static timing at 74.54 MHz DVI, but produced no usable HDMI signal on the rack.
The external video clock uses 1% spread spectrum, so a route only 0.39% above
the nominal 74.25 MHz constraint does not have credible hardware margin. Slot 4
was restored to the known-good `rezo-8b39ff81-r5.tar.gz` image before the rack
was powered down. No later archive in this section has been flashed.

Three measured RTL changes were retained:

1. compact REZO audio-gain endpoints use one offset-plus-gain calculation,
   keeping the complete fader inside its lane while removing the extra
   display-domain scale adder;
2. compact REZO INPUT target IDs use a four-entry constant decoder instead of
   `TARGET_INPUT_BASE + 3 * input_index`, removing the block-RAM-to-carry-chain
   DVI critical path;
3. REZO stores scaled OUTPUT send offsets in its existing BRAM, moving the
   multiply-by-three operation to the sync write path. REZOMO deliberately
   retains raw sends: the identical transformation saved 38 packed cells in
   REZO but cost 77 in REZOMO, leaving only 18 free. The rejected shared form
   is recorded by `df3e4de` and its immediate revert `b4504cd`.

The final combined software gate passed 105 tests. Current measured artifacts
are:

| Target | Source / seed | Packed cells | DVI5X / AUDIO / SYNC / DVI MHz | Archive payload SHA-256 | Status |
|---|---:|---:|---|---|---|
| REZO standard | `55df62df` / 8 | 23,879 (409 free) | 405.19 / 72.14 / 65.13 / 75.05 | `1cf12e275855f0e61b8cd7f9cc1eebe95d4c3b49832f9207eb0d151cd92d338a` | Nominal pass; not hardware-qualified because DVI margin is close to the 1% spread peak |
| REZO circular | `902e7c58` / 2 | 23,861 (427 free) | 404.04 / 73.93 / 60.41 / 80.95 | `b4c8cd828ef918f446320592768bfe2eff9a55fe9aac7332a196926210ee9519` | Nominal pass; not hardware-qualified because sync margin is only 0.41 MHz |
| REZOMO standard | `f65f2b3f` / 6 | 24,193 (95 free) | 392.00 / 72.63 / 63.02 / 75.27 | `d5568ce575a54cad1a39e0d679b96ce6acb6b129243fd737644cdcb67b9e1c82` | Final-head rebuild reproduced prior metrics and passes the 1.25% margin gate |
| REZOMO circular | `f65f2b3f` / 4 | 24,261 (27 free) | 389.56 / 73.94 / 61.87 / 76.02 | `5698af89a57dfc487a632d46d2e8a9619d3e49a4cfaca243975f67beae62c03f` | Final-head rebuild reproduced prior metrics and passes the 1.25% margin gate |

This pass confirms that source consolidation and FPGA optimization are related
but distinct. Pure Python constants and tests should continue to be shared.
Nearly-full elaborated RTL must be synthesized for both variants before it is
made common: mathematically equivalent structures can pack very differently.
The next hardware candidate should target at least 1% video-clock headroom plus
additional guard margin, then be tested on the rack before its seed becomes a
new qualified default.

Run the margin gate after every build and before packaging or flashing a new
route:

```sh
pdm run python scripts/check_timing_margin.py \
  build/<target>-r5/top.tim --minimum-headroom-percent 1.25
```

This is intentionally stricter than nextpnr's nominal PASS/FAIL flag. The
default covers the configured 1% spread peak plus a small guard margin; release
candidates may use a higher threshold.

## REZOMO capacity recovery (2026-08-14)

REZOMO standard commit `cbd49d7c`, seed 3, is the first hardware candidate from
the dedicated post-consolidation capacity pass. It uses 23,978 packed cells
(310 free), versus 24,193 packed cells (95 free) for the prior qualified
standard image. This recovers 215 cells and increases free packed capacity by
more than three times without changing the shared DVI PHY or persistence
format.

The retained changes are deliberately narrow:

1. OUTPUT ROUTING decodes repeated output columns from block memory and keeps
   raw send values in block memory, but registers pixel position relative to
   the cell before comparing against the send width. This removes a post-RAM
   coordinate carry chain without the packing penalty of storing absolute
   endpoints.
2. SHIFT and WALK capture accepted clock events and begin their wide pattern
   updates one 60 MHz cycle later. ROTATE and TURING remain on their direct
   paths. All clock-algorithm simulations preserve the prior results.
3. INPUT ROUTING registers only its two-bit repeated-row selector before the
   endpoint muxes. The selector settles in the blank left edge before any INPUT
   control is drawn, removing the block-RAM clock-to-output delay from the DVI
   critical path without moving visible geometry.

The exact commit build passed the 1.25% margin gate at DVI5X 377.36 MHz
(1.62%), AUDIO 72.50 MHz (47.51%), DVI 77.29 MHz (4.09%), and SYNC 60.89 MHz
(1.48%). The 39-test focused REZO-family suite passed. Archive
`rezomo-cbd49d7c-r5.tar.gz` has SHA-256
`ee8eaa227c35ebe8c7af307af756f984b9df217d8ff05e2be98fdf1aa93cb90e`;
its `top.bit` SHA-256 is
`e67ea8eb4a95ace972fe7e9ed4776964006f01508da6fc9ddbfa84839ed28295`.
It was flashed successfully to slot 4 for hardware validation.

The circular REZOMO target has not yet been rebuilt from this optimization
commit. Its older seed-4 qualification remains the current reference until an
exact circular build passes the same margin gate.

## Shared page-contract qualification (2026-08-20)

Commit `a40c6a83` centralizes the common page headers, support-page labels,
coordinates, and FEEDBACK/INPUT/GROUPS navigation contracts described above.
All 198 family DSP, display, persistence, target, and UI tests pass. Standard
routes were built from that exact functional commit and accepted by the 1.25%
timing-margin gate:

| Target | Seed | Combinational cells | DVI5X / AUDIO / SYNC / DVI MHz |
|---|---:|---:|---|
| REZO standard | 9 | 24,062 (226 free) | 399.84 / 72.45 / 67.70 / 79.21 |
| REZOMO standard | 9 | 23,999 (289 free) | 389.71 / 69.58 / 62.75 / 79.90 |
| STREZO standard | 7 | 23,207 (1,081 free) | 391.85 / 74.95 / 63.17 / 78.31 |

STREZO's prior default seed 4 was rejected because DVI5X reached only
352.49 MHz. Seed 7 was selected from the recorded route history rather than a
random search and is now the qualified standard default.
