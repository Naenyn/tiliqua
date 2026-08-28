# REZO family continuation handoff

Updated 2026-08-28. This is an operational handoff, not a project diary.
Historical work remains available in git and `BUILD_PERFORMANCE.md`.

## Current state

- Repository: `/Users/naenyn/git/tiliqua`
- Gateware: `/Users/naenyn/git/tiliqua/gateware`
- Branch: `codex/rezo-circular-chrome`
- Last hardware-qualified commit: `3d7fd783`
  (`rezo: converge CPU family and fix runtime regressions`)
- Standard-display slots: REZO 2, REZOMO 3, STREZO 4.
- Standard development target: `1280x720p60` on the user's 1080p monitor.
- Retain `720x720p60r2` support, but do not build the round target unless asked.
- Runtime-corrected REZO and STREZO images were rebuilt and flashed on
  2026-08-28 to slots 2 and 4. Both flash commands detected Tiliqua R5 serial
  `E46534A193222B21` and exited normally. The user subsequently confirmed that
  both images look and operate correctly; they are hardware-qualified.

The user approved and requested the incremental eight-step convergence plan.
All eight steps, including flashing slots 2/3/4, are complete.

## Runtime regression debug

Post-flash hardware testing invalidated two of the original convergence
archives. REZOMO survived and remains the known-good control.

### REZO freeze

The standardized CPU fabric moved REZO's writable data RAM from `0x4000` to
`0x8000`, but Cargo reused an executable linked against the previous
`memory.x`. The broken ELF had `.data`/`.bss` at `0x4000` and `_stack_start` at
`0x4800`, while the new hardware exposed writable RAM only at `0x8000`.
Firmware therefore stalled on its first stack/data access after boot.

Each CPU firmware crate now has a `build.rs` containing
`cargo:rerun-if-changed=memory.x`. This retains the shared 64 KiB CPU region
and standardized `0x8000` data map while forcing a relink after generated
linker-map changes. The rebuilt REZO ELF has `.data`/`.bss` at `0x8000` and
`_stack_start` at `0x8800`.

Hardware-qualified corrected REZO:

- archive: `build/rezo-r5/rezo-874b6c8d-r5.tar.gz`
- SHA-256: `8d876c9d1fd74e0fed420ad48d4aea41eb318c2bfe9d2f59780e516bb1088913`
- timing: DVI5X 443.66/371.33, DVI 80.44/74.25, sync 64.53/60,
  audio 75.68/49.15 MHz
- flashed to slot 2

### STREZO graphical corruption

The photographed UI retained recognizable geometry but showed severe stable
colour/data striping. STREZO alone among it and the known-good REZOMO used four
independently reset TMDS phase rings. Its routed reset-release path reached
5.42 ns against a roughly 2.69 ns DVI5X period, so the colour and clock lanes
could leave reset on different word phases even though ordinary same-domain
timing passed.

STREZO now uses one shared phase ring with split registered load strobes. This
preserves lane alignment and still closes at the existing seed.

Hardware-qualified corrected STREZO:

- archive: `build/strezo-r5/strezo-874b6c8d-r5.tar.gz`
- SHA-256: `70842da94eafdb5b60c2e67fc21a15d7498b78d2565f4f3dc64c85b8668592c5`
- timing: DVI5X 428.08/371.33, DVI 82.60/74.25, sync 62.53/60,
  audio 71.99/49.15 MHz
- flashed to slot 4

The focused family regression passes **102 tests** after both fixes. Hardware
validation confirmed that REZO remains responsive and that STREZO renders
cleanly while retaining normal operation.

### STREZO OUTPUT column-header alignment

STREZO's compact OUTPUT labels and matrix were shifted upward by three native
rows, but its shared column-header selection bar omitted the matching
`-3 * compact_content_shift` offset. The bar consequently rendered below the
column label instead of above it. STREZO now passes the same offset used by
REZO; the native regression checks both a group column and DRY at the corrected
y=232..235 position and rejects the former y=280..283 position. The focused
family regression remains **102 passed**. The `3d7fd783` archive was
subsequently flashed to slot 4 and the user confirmed that STREZO looks and
sounds correct.

## Post-convergence cleanup (step 3)

The CPU-less control surfaces, gateware persistence journals, encoder helper,
and their tests have been retired. Production has required firmware since the
family convergence, and the deleted implementations remain available in git
history. `SPIFlashTransfer` remains as the small live firmware flash helper.

The unused `compact_layout=False` renderer branches and legacy-only geometry,
navigation, labels, and display tests have also been removed. Standard and
round targets both use the retained native/compact renderer path. Product
target IDs now live in lightweight `ui_specs.py` classes, with tests that
compare the Python renderer contracts directly against the Rust firmware
constants. Obsolete encoder mirror signals in the firmware UI state were also
removed.

Validation after cleanup:

- focused display/contract suite: **102 passed**
- complete surviving `test_rezo*.py`/`test_strezo*.py` suite: **169 passed**
- Python compilation and `git diff --check`: pass
- REZO fully elaborated and routed, but the timing gate correctly rejected its
  archive because DVI5X achieved only 358.55/371.33 MHz. This is the existing
  phase/load-route weakness addressed by follow-on step 4, not a simulation or
  firmware regression.

## Superseded pre-runtime-check builds

All three canonical CPU images built with their existing single target seed.
No seed sweep was used, but REZO and STREZO later failed runtime testing for
the reasons above. The timing/resource data remains useful historical context;
these archive identities are not a hardware qualification.

The corrected builds reused and overwrote the same HEAD-derived archive
filenames. Use the SHA-256 values in the runtime-debug section, not filenames
alone, to distinguish the current candidates from the broken payloads.

| Product | Archive | DVI achieved / required | Sync achieved / required | DP16KD | LUT4 | FF |
|---|---|---:|---:|---:|---:|---:|
| REZO | `build/rezo-r5/rezo-874b6c8d-r5.tar.gz` | 80.44 / 74.25 MHz | 64.53 / 60 MHz | 36 | 10,592 | 8,315 |
| REZOMO | `build/rezomo-r5/rezomo-874b6c8d-r5.tar.gz` | 78.96 / 74.25 MHz | 62.66 / 60 MHz | 38 | 11,877 | 8,417 |
| STREZO | `build/strezo-r5/strezo-874b6c8d-r5.tar.gz` | 79.26 / 74.25 MHz | 64.00 / 60 MHz | 35 | 10,939 | 8,456 |

The archives have normal product identities (`REZO`, `REZOMO`, `STREZO`), not
temporary `-CPU` suffixes. CPU-backed images are now the canonical production
targets.

Focused family regression command:

```sh
cd /Users/naenyn/git/tiliqua/gateware
pdm run pytest -q \
  tests/test_rezo_standard_display.py \
  tests/test_rezomo_native_display.py \
  tests/test_strezo_native_display.py \
  tests/test_strezo_display.py \
  tests/test_rezo_family_targets.py
```

Result: **102 passed**. The warnings are existing Amaranth/LUNA deprecations.

## What changed

### CPU and production targets

- `RezoFamilyCpuControlPlane` centralizes the CPU construction and common
  address contract.
- All three resolve to the exact same generated Vexii netlist:
  `VexiiRiscv_77bc371dea005dbd0c073a5f7cc676e8.v`.
- All expose a 64 KiB CPU-visible main-RAM region and data at `0x8000` with
  size `0x0800`.
- Physical firmware code storage remains product-sized: REZO `0x4000`,
  REZOMO/STREZO `0x5000`. This does not change CPU identity.
- Canonical and round entry points dispatch to CPU-backed implementations.
  Missing firmware is an error; there is no silent CPU-less production image.
- The old implementation remains recoverable from git history, as requested.

### Shared renderer policy

- All renderers register the UI selection in the DVI domain before geometry
  and text decisions.
- INPUT uses the same two-stage pipeline everywhere: synchronous row lookup,
  one selected-lane register, then endpoint/meter arithmetic. This avoids four
  parallel endpoint paths and preserves the established one-pixel prefetch.
- INPUT, GROUPS, and five-column OUTPUT use shared native geometry generators
  from `ui_common.py`. STREZO's four-column CROSS page remains local because it
  is a genuine product feature.
- STREZO's INPUT audio meter uses the same capped/scaled endpoint behavior as
  REZO and REZOMO.
- REZOMO CLOCK row geometry is decoded by one compact row lookup instead of
  repeated rectangles; the selected-row data is registered.
- Text storage uses the same efficient policy everywhere: packed 45x45 pages,
  with page/row base computed one pixel early and registered before the text
  BRAM. The live BRAM path performs only the small cell-x addition.
- The shared packed text pipeline reduced REZO text/resource use from 42 to 36
  DP16KDs and removed REZOMO's former live `cell_y * 45` timing path.
- Footer version text and its now-dead constructor plumbing were removed from
  all three products, as requested.

### Why the final text design matters

A sparse 64x64-per-page experiment removed address arithmetic, but cost six
extra DP16KDs in REZOMO and made routing take more than eleven minutes without
converging. That experiment was stopped and is not in the final tree.

The packed-and-pipelined design gives the same timing benefit while keeping
the smaller memory footprint. At the same REZOMO seed it routed normally and
passed DVI at 78.96 MHz. This is the preferred family implementation.

## Genuine product differences

Do not erase these in the name of sharing:

- REZO has FILTER and modulation-matrix behavior and nine text pages.
- REZOMO has CLOCK-specific UI and clock DSP/control behavior.
- STREZO has MOTION and CROSS pages and linked-stereo DSP/control behavior.
- Product firmware CSR schemas and physical firmware code sizes may differ.

The generated CPU, address contract, common page geometry, input pipeline,
text addressing policy, target construction, and build qualification rules
should not diverge.

## Latest optimization review

No source changes were made as part of this review. The family currently uses
about 89-90% of available COMB cells, while flip-flop use is about 34% and BRAM
use is about 62-67%. Placement/routing and combinational timing remain the real
constraints. Extra pipeline registers are comparatively inexpensive.

### Recommended source simplifications

These reduce code size and divergence but should not materially change the
bitstreams because the branches are already eliminated at Python elaboration
time:

1. Remove the remaining CPU-less production branches from `rezo_variant.py`,
   `top.py`, and `strezo_variant.py`. Production firmware is mandatory and the
   old implementation remains in git history.
2. Extract the still-live `SPIFlashTransfer` helper from the three persistence
   modules, then remove the obsolete gateware state-journal implementations and
   their CPU-less tests.
3. Retire the legacy `compact_layout=False` renderer branches. Every current
   standard and round production target passes `compact_layout=True`; round
   720x720 support does not depend on the legacy branches. This is the largest
   remaining renderer-maintenance cleanup.
4. Remove the unused `yosys`, `nextpnr_ecp5`, and `ecppack` fields from
   `targets.py`; all current family targets set them to `None`.
5. Consolidate duplicated firmware-build/CLI plumbing in `rezo_cpu.py`,
   `rezomo_cpu.py`, and `strezo_cpu.py`. Decide whether the redundant `*_cpu`
   console entry points remain documented compatibility aliases or are removed
   now that CPU images are canonical.
6. Extract the duplicated Rust persistence, arithmetic, input, navigation, and
   edit-loop primitives into the shared firmware crate behind a product spec or
   trait. This is the most valuable follow-on for preventing firmware drift,
   but it needs firmware-size checks after each step.

`RezoHardwareUI` classes cannot simply be deleted yet: renderer code and tests
still use their constants and target/navigation contracts. First move that
declarative product specification into lightweight modules; then remove the
obsolete hardware state-machine portions.

### Recommended hardware optimizations

Do these individually and compare timing/resource reports after each change:

1. **First choice:** share STREZO's registered OUTPUT-send BRAM pattern with
   REZO and REZOMO. REZOMO's current DVI critical path starts at
   `display.output_send_mem`, passes through scaling and endpoint comparison,
   and is a good candidate for one cheap register stage.
2. Predecode STREZO's selected page/target into small registered flags or a
   compact lookup. Its current DVI critical path passes through a large
   page-selection/outline decode.
3. Pipeline or time-multiplex REZO's band-display height/top arithmetic. That
   is its current DVI critical region.

All three currently pass timing, so these are headroom and maintainability
improvements rather than emergency fixes. The DSP is the largest identifiable
COMB consumer in each image, followed by display logic; the shared CPU accounts
for roughly 2.5k named combinational cells per product.

Do not prioritize indiscriminate BRAM-table merging: many small tables are read
concurrently, and adding address/data multiplexers may consume more COMB and
hurt timing. Do not change the accepted shared Vexii CPU configuration unless a
measured problem specifically points there.

## Dirty files

Expected modified files are:

- `gateware/src/top/rezo/REZO_HANDOFF.md`
- `gateware/src/top/rezo/cpu_control.py`
- `gateware/src/top/rezo/cpu_fw/memory.x`
- `gateware/src/top/rezo/cpu_fw/build.rs`
- `gateware/src/top/rezo/rezo_cpu.py`
- `gateware/src/top/rezo/rezo_variant.py`
- `gateware/src/top/rezo/rezomo_cpu.py`
- `gateware/src/top/rezo/rezomo_cpu_fw/build.rs`
- `gateware/src/top/rezo/strezo_cpu.py`
- `gateware/src/top/rezo/strezo_cpu_fw/build.rs`
- `gateware/src/top/rezo/strezo_variant.py`
- `gateware/src/top/rezo/targets.py`
- `gateware/src/top/rezo/top.py`
- `gateware/src/top/rezo/ui_common.py`
- `gateware/tests/test_rezo_family_targets.py`
- `gateware/tests/test_rezo_standard_display.py`
- `gateware/tests/test_strezo_native_display.py`

Preserve unrelated user changes if the branch is merged again. Do not use a
broad restore/reset.

## Next actions

1. Review `git diff --check`, syntax checks, and the final dirty-file list.
2. Commit the completed convergence and runtime-regression fixes when
   requested/appropriate.
3. Discuss and choose the next cleanup/optimization tranche before changing or
   rebuilding anything. The safest starting tranche is removal of dead CPU-less
   source and legacy persistence code; the first measured hardware candidate is
   the shared registered OUTPUT-send path.

Do not substitute a seed sweep for path analysis. For any future timing miss,
inspect the exact reported path, improve the shared structure when applicable,
then validate with one deliberate target seed.
