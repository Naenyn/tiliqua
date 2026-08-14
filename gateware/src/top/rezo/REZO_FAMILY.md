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
