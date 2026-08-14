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
The qualified defaults are seed 8 for both REZO targets, seed 6 for REZOMO
standard, and seed 4 for REZOMO circular.

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
