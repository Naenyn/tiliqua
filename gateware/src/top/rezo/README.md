# REZO bitstream family

REZO is a family of three related Tiliqua bitstreams built around a shared
ten-band resonant filterbank:

| Product | Character | Distinctive behavior |
|---|---|---|
| **REZO** | Mono filterbank and shaped-filter processor | Manual BANK mode plus generated LP, HP, BP, and notch FILTER responses |
| **REZOMO** | Clock-oriented mono filterbank | BANK plus SHIFT, ROTATE, WALK, and TURING modulation algorithms |
| **STREZO** | Linked-stereo filterbank | Independent left/right resonator state, frequency motion, SAME/CROSS feedback routing, and wet-path MID/SIDE shaping |

Each product is available for standard `1280x720p60` HDMI and for the official
rotated `720x720p60r2` circular display. Both outputs render the same upright
native 720x720 interface and expose the same controls and saved state. The
standard target centers that canvas without rotation; the circular target
applies the panel's final 90-degree mount correction.

Operator documentation:

- [REZO user guide](REZO_USER_GUIDE.md)
- [REZOMO user guide](REZOMO_USER_GUIDE.md)
- [STREZO user guide](STREZO_USER_GUIDE.md)

## Common interface

The family uses the same signal-flow page order wherever a page applies:

```text
BANK -> INPUT -> BANDS -> [CLOCK] -> GROUPS -> FEEDBACK -> [CROSS]
     -> OUTPUT -> OPTIONS
```

REZO's FILTER mode inserts MATRIX between BANDS and GROUPS. REZOMO inserts
CLOCK only while CLOCK mode is selected, and STREZO inserts CROSS.

All three products provide post-gain input-bus metering in the lower arc and
final-output metering in the outer arcs. Meter headroom and held clip lamps use
the active palette, so they remain distinguishable in every theme. OUTPUT row
headers edit a complete output at once, while column headers edit one source
across all four outputs. The **ROW DRY** option decides whether a row edit also
changes DRY; it does not affect individual cells or column edits.

## Architecture

All six production targets are CPU-backed designs. Gateware owns the audio
sample path, resonators, HDMI timing and renderer, while product-specific Rust
firmware owns encoder navigation, parameter editing, startup restore, and
flash-backed **SAVE DEFAULT** behavior.

The family is organized in layers:

```text
rezo.py / rezomo.py / strezo.py
*_round.py                       six build entry points
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
cpu_fw, rezomo_cpu_fw,
strezo_cpu_fw/src/main.rs        product-owned navigation and state schema
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

Use the repository's
[Tiliqua installation instructions](../../../docs/install.rst), including the
Rust CPU-bitstream prerequisites. Initialize the repository submodules, then
install the Python environment from `gateware/`:

```bash
pdm install
```

The remaining commands below also run from `gateware/`. They build for
Tiliqua hardware revision 5 by default, and the release configuration uses a
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

Add `--spread-spectrum 0.0` to any build command to disable external video-PLL
spread spectrum. The selected value is recorded in the archive manifest; when
the option is omitted, the default remains `0.01`.

The target matrix supplies starting placement seeds from prior qualified
builds. Every new source revision must be qualified again; those seeds are
not a timing guarantee. Set `TILIQUA_REZO_FAMILY_SEED` when testing another
route.

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

## Arithmetic and overload behavior

The group and feedback paths retain the full ten-band sum before limiting.
Output routing retains overlapping group sums and mixed-sign cancellation
until the final audio clamp. STREZO additionally retains the full wet-group
domain through MID/SIDE, with room for its 2x component gains; feedback taps
remain before that transform. Deliberate resonant overload is still possible,
but these sums no longer wrap to the opposite polarity before limiting.

INPUT VALUE fully down is mute, including old saved minimum positions. The
retained fine byte preserves the edit path back to unity. REZOMO SHIFT's
RANDOM and unpatched AUTO sources use the same bipolar modulation range as CV
DATA. SHIFT retains all ten physical band positions, including silent disabled
positions; it does not skip those positions.

When retaining both spread-spectrum profiles, give the zero-spread build its
own artifact name so the standard archive cannot be overwritten. For example:

```bash
pdm run rezo build --fs-192khz --spread-spectrum 0.0 \
  --artifact-name REZO-NOSS
```

Use REZOMO-NOSS/rezomo and STREZO-NOSS/strezo for the other products. Circular
targets already have distinct ROUND artifact names and apply the panel-mount
rotation in the final display output.

## Built-in help prototype

STREZO, the family's most space-constrained bitstream, has a simple HELP page
after OPTIONS. Its fixed PAGE and SCROLL controls remain above a scrollable
text summary contained inside the circular viewport, with the standard
identity/PAGE header and NAV, EDIT or SCROLL status. The existing font
renderer reads a narrow help ROM; no framebuffer or new font is required.

[STREZO_HELP.md](STREZO_HELP.md) is condensed from the user guide. Only the
paragraphs between its HELP markers enter the build. `help_content.py` wraps
them to 32 columns and supplies both the ROM contents and the firmware scroll
limit. Update the summary alongside the guide. This prototype does not yet
add HELP to REZO or REZOMO and does not change saved records or DSP.

Use brief complete sentences with letters, digits, spaces and periods inside
the HELP markers. Unsupported punctuation is rejected rather than silently
rendered as blanks. The formatter also checks the 3,072-character ROM budget
so a wording change cannot quietly grow the memory allocation.

First-use HELP is enabled by default. Build with
`TILIQUA_REZO_HELP_FIRST_BOOT=0` to disable its automatic startup, without
removing HELP from the page list. Cargo tracks this flag as a build input.
With no valid saved default and no acknowledgement, boot opens HELP; leaving
it programs and verifies only the four-byte `HELP` marker at offsets
4092..4095 of option sector zero. This is beyond the 96-byte STREZO journal
record and requires no erase or implicit sound save. Valid saved defaults
count as initialized for backward compatibility. Failed reads conservatively
keep BANK startup, and a failed acknowledgement can show HELP again next boot.
Erasing defaults clears both saved sounds and the first-use marker.

## Verification

Run the family tests before producing release archives:

```bash
pdm run pytest -q tests/test_rezo*.py tests/test_strezo*.py
```

Every routed build must pass all constrained clocks. The release qualification
also requires at least 3 percent headroom in the timing report:

```bash
pdm run python scripts/check_timing_margin.py \
  build/<target>-r5/top.tim --minimum-headroom-percent 3
```

Replace `<target>` with `rezo`, `rezo-round`, `rezomo`, `rezomo-round`,
`strezo`, or `strezo-round`. Keep the six archives together with their SHA-256
hashes and timing summaries when publishing a release candidate.
