# REZO bitstream family

REZO is a family of three related Tiliqua bitstreams built around a shared
ten-band resonant filterbank:

| Product | Character | Distinctive behavior |
|---|---|---|
| **REZO** | Mono filterbank and shaped-filter processor | Manual BANK mode plus generated LP, HP, BP, and notch FILTER responses |
| **REZOMO** | Clock-oriented mono filterbank | BANK plus SHIFT, ROTATE, WALK, and TURING modulation algorithms |
| **STREZO** | Linked-stereo filterbank | Independent left/right resonator state, frequency motion, and SAME/CROSS feedback routing |

Each product is available for standard `1280x720p60` HDMI and for the official
rotated `720x720p60r2` circular display. Both outputs render the same upright
native 720x720 interface and expose the same controls and saved state. The
standard target centers that canvas without rotation; the circular target
applies the panel's final 90-degree mount correction.

Operator documentation:

- [REZO user guide](REZO_USER_GUIDE.md)
- [REZOMO user guide](REZOMO_USER_GUIDE.md)
- [STREZO user guide](STREZO_USER_GUIDE.md)

## Architecture

All six production targets are CPU-backed designs. Gateware owns the audio
sample path, resonators, HDMI timing and renderer, while product-specific Rust
firmware owns encoder navigation, parameter editing, startup restore, and
flash-backed **SAVE DEFAULT** behavior.

The family is organized in layers:

```text
rezo.py / *_round.py             six build entry points
        |
        v
targets.py                       product, display, modeline, seed, artifact name
        |
        v
*_cpu.py + cpu_build.py          SoC construction and Rust firmware image
        |
        +--> rezo_variant.py     REZO DSP and renderer
        +--> top.py              REZOMO DSP and renderer
        +--> strezo_variant.py   STREZO DSP and renderer
        |
        v
cpu_control.py + ui_specs.py     shared MMIO and declarative UI contracts
*_cpu_fw/src/main.rs             product-owned navigation and state schema
```

Shared modules hold behavior that is genuinely common: target construction,
CPU build plumbing, core fixed-point helpers, display palettes and geometry,
UI target numbering, flash transport, and persistence record primitives.
Product DSP, state schemas, page behavior, and distinct controls remain local
so consolidation does not erase functional differences.

Saved defaults use two alternating records in the active bitstream slot. At
startup firmware selects the newest valid record, applies the complete state,
and then unmutes audio. If no valid record exists, the product starts from its
compiled defaults.

For deeper implementation and qualification history, see
[REZO_FAMILY.md](REZO_FAMILY.md), the three `*_CPU_ARCHITECTURE.md` documents,
and [BUILD_PERFORMANCE.md](BUILD_PERFORMANCE.md).

## Build prerequisites

Use the repository's documented Tiliqua toolchain and install the `gateware`
PDM environment. Commands below run from the `gateware` directory and build for
Tiliqua hardware revision 5 by default. The release configuration uses the
192 kHz audio sample rate.

Before a release build, start from a committed, clean source tree. Archive
names include the source commit, so building from uncommitted changes produces
an archive identifier that cannot fully describe its contents.

## Build matrix

From `gateware/`:

| Product | Standard 1280x720 | Circular 720x720 |
|---|---|---|
| REZO | `pdm run rezo build --fs-192khz` | `pdm run rezo_round build --fs-192khz` |
| REZOMO | `pdm run rezomo build --fs-192khz` | `pdm run rezomo_round build --fs-192khz` |
| STREZO | `pdm run strezo build --fs-192khz` | `pdm run strezo_round build --fs-192khz` |

The target matrix supplies the qualified default placement seed for each
product and display. Set `TILIQUA_REZO_FAMILY_SEED` only when deliberately
testing another route.

Successful builds create these artifact directories:

```text
build/rezo-r5/           build/rezo-round-r5/
build/rezomo-r5/         build/rezomo-round-r5/
build/strezo-r5/         build/strezo-round-r5/
```

Each directory contains the compiled firmware, FPGA intermediates, timing
report, bitstream, manifest, and a commit-stamped `.tar.gz` archive suitable
for the normal Tiliqua archive flashing workflow. Standard and circular
artifacts have distinct names and cannot silently overwrite one another.

## Verification

Run the family tests before producing release archives:

```bash
pdm run pytest -q tests/test_rezo*.py tests/test_rezomo*.py tests/test_strezo*.py
```

Every routed build must pass all constrained clocks. The release qualification
also requires at least 1.25 percent headroom in the timing report:

```bash
pdm run python scripts/check_timing_margin.py \
  build/<target>-r5/top.tim --minimum-headroom-percent 1.25
```

Replace `<target>` with `rezo`, `rezo-round`, `rezomo`, `rezomo-round`,
`strezo`, or `strezo-round`. Keep the six archives together with their SHA-256
hashes and timing summaries when publishing a release candidate.
