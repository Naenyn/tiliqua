# REZO family build and consolidation guide

The `codex/rezo-family` branch is the single development home for REZO and
REZOMO. Product and display selection are explicit build-time choices; they no
longer depend on which historical branch is checked out.

## Build matrix

Run commands from `gateware/`:

| Product | Display | Command | Build/archive prefix |
|---|---|---|---|
| REZO | standard 1280x720 | `pdm run rezo build --fs-192khz` | `rezo-r5/`, `rezo-*` |
| REZO | circular 720x720 | `pdm run rezo_round build --fs-192khz` | `rezo-round-r5/`, `rezo-round-*` |
| REZOMO | standard 1280x720 | `pdm run rezomo build --fs-192khz` | `rezomo-r5/`, `rezomo-*` |
| REZOMO | circular 720x720 | `pdm run rezomo_round build --fs-192khz` | `rezomo-round-r5/`, `rezomo-round-*` |

Every target has a distinct artifact name and therefore a distinct build
directory and archive filename. Standard and circular builds retain the same
product name in their manifests and on screen, so output isolation does not
consume extra FPGA resources. A circular `top.bit` cannot be repackaged
accidentally as a standard artifact through `--skip-build`.

`TILIQUA_REZO_FAMILY_SEED=<n>` overrides a target's qualified default placement
seed. The older `TILIQUA_REZO_SEED=<n>` override remains compatible when the
family-specific variable is unset.
The qualified defaults are seed 8 for REZO standard, seed 2 for REZO circular,
seed 6 for REZOMO standard, and seed 4 for REZOMO circular.

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
- `rezo.py`, `rezo_round.py`, `rezomo.py`, and `rezomo_round.py` are deliberately
  thin build entry points.
- `round.py` is a compatibility shim for the older circular-build script.

Variant selection occurs before Amaranth elaboration, so REZO does not carry
REZOMO-only clock logic. The historical `rezo`, `rezomo`, and `rezoclocked`
branches remain recovery and provenance references while consolidation proceeds.
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

After each extraction, run both variant suites and compare synthesized resource
and timing results before deleting duplicated code.

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
