# REZO family continuation handoff

Updated 2026-09-17. This is an operational handoff, not a project diary.
Historical work remains available in git and `BUILD_PERFORMANCE.md`.

## Current continuation checkpoint — 2026-09-17

### Reviewed REZO / STREZO mixed-case HELP qualified and flashed — 2026-09-17

Qualified source/tag `23b82022` imports the user's edited REZO/STREZO review
prose verbatim from `build/rezo-family-help-f56e772e`. Both products now use
the accepted REZOMO mixed-case font and basic punctuation for HELP. Header
and menu glyph codes, six-bit native tile storage, STREZO unity ticks and
the synchronous glyph pipeline remain unchanged. Only HELP needs seven-bit
indices. Native unsupported punctuation is explicitly excluded from ordinary
tile initialization so appended HELP codes cannot truncate into menu digits;
this guard also fixes REZOMO source for its next build. No DSP, CPU, working
RAM, program-allocation, saved-schema, option-layout or first-use policy change.

REZO slot 2 and STREZO slot 4 were flashed successfully with debugger
E46534A193222B21: both exited 0 with Refresh: DONE. Profiles are standard
R5 720p / 192 kHz / spread_spectrum=0.0. Both designs pass all four clocks
with the unchanged 3% gate and exactly matching synthesized/routed PLL
parameters. Archive bytes, CRC, size, tag/profile, option exclusion and
conservative erase-block nonoverlap passed checks. Saved settings not erased.

REZO unanchored seed 9: serializer 401.77 MHz, audio 72.06, system 66.54,
pixel 79.08, minimum margin 6.51%. Resources: 23238/24288 logic (1050 free),
43/56 BRAM, 7/28 DSP, firmware 16716/20480 bytes.
STREZO unanchored seed 8, heap weight 30: serializer 398.41 MHz, audio 73.14,
system 64.13, pixel 87.28, minimum margin 6.88%. Resources: 24124/24288
logic (164 free), 41/56 BRAM, 20/28 DSP, firmware 15008/20480 bytes.
Both products add one BRAM overall; the font itself still fits in one BRAM.
HELP ROMs are REZO 372 rows/11904 seven-bit characters and STREZO
354 rows/11328 characters. Firmware sizes are unchanged.

Final HELP/font/control/render tests: 64 passed (all glyph pixels and both
rotations), native/interface/target selection: 87 passed, 5 deselected,
HDMI serializer: 2 passed, shared Rust host library: 16 passed. STREZO's
first completed seed-4 route had only 0.82% serializer margin and was rejected.
Placement probes were guarded or stopped once the unanchored route qualified;
no hooks, rejected images or incomplete routes were adopted/programmed.

Archives, source prose snapshots, complete qualification/hashes/reports/test
and flash logs are in
`/Users/naenyn/git/tiliqua/build/rezo-family-mixed-help-23b82022`.
REZO archive SHA-256:
`23bd06b95183e87ded044c619f95801a7b3660ef264735684407fbbfc4dbafa3`.
STREZO archive SHA-256:
`1b735a573bdd19dd693a0bc4f128bde3fd287a7f25ebfcbc0e97ed69701a2b97`.

REZOMO's mixed-case HELP was visually accepted by the user before these ports;
its accepted `0def97b1` slot-3 image was left untouched. REZO/STREZO physical
review is pending. No circular build or production merge yet. Main SONORO/
CASCADO sources stay untouched; work remains on codex/strezo-built-in-help.
Next: user review, then merge back and generate the requested release builds.

### REZOMO mixed-case HELP trial qualified and flashed — 2026-09-17

Qualified source/tag `0def97b1` imports the user's edited REZOMO review prose
verbatim and preserves mixed-case body text, with existing menu/control codes
unchanged. Twenty-six lowercase glyphs and twelve basic punctuation glyphs are
appended for REZOMO only. HELP uses seven-bit indices, ordinary native tiles
remain six-bit, and the existing synchronous font pipeline/cell geometry is
unchanged. REZO and STREZO retain their qualified uppercase alphabets/content;
their ports and circular hardware builds wait for user approval of this trial.

Standard R5 720p / 192 kHz / SS 0.0 qualifies with seed 3, heap weight 30,
no hooks, all clocks above the unchanged 3% gate: serializer 394.48 MHz,
audio 76.40, system 68.83, pixel 76.76 (3.38% minimum). Both physical PLL
parameter sets match the synthesized input. No clock, CPU, working-RAM, DSP,
audio/control, V4 record or first-use acknowledgement changes were made.
Usage is 23383/24288 logic cells (905 free), 44/56 BRAMs, 7/28 DSPs, 8626 FF;
firmware remains 18436/20480 bytes. Font ROM is still one BRAM; updated HELP
is 375 rows / 12000 seven-bit characters / 10500 raw bytes in five BRAMs,
one additional BRAM overall. Whole-design synthesis remapping contributes to
the logic delta; it is not the isolated font cost.

HELP/control/render/font tests: 60 passed, including every new glyph's ink
and background pixels and indices above 63 in both standard and rotated
simulation. Native/HDMI selection: 32 passed; shared Rust library: 16 passed.
Fresh packing, archive tag/profile/CRC/byte checks and protected-option-layout
checks passed. Option storage is still at 5111808, size 8192, excluded from
programming and nonoverlapping conservative erase blocks.

Five completed routes used two distinct seeds. Four seed-9 attempts were
rejected for serializer or existing output-meter pixel timing; none was
packaged/flashed. The carry-member BEL attempt did not constrain the actual
macro and was rejected, not adopted. The single alternate to the product's
default seed 3 qualified without anchors. Do not reuse rejected hooks.

The archive and complete qualification/hashes/logs are in
`/Users/naenyn/git/tiliqua/build/rezomo-mixed-help-0def97b1`.
Archive `rezomo-help-mixed-0def97b1-r5.tar.gz` SHA-256 is
`034734662fb855de3243b0143aae93b9f14487722687e703fd597c8c39b88bde`.
At the user's subsequent request, REZOMO slot 3 was flashed successfully on
2026-09-17 using R5 debugger E46534A193222B21: exit 0, Refresh: DONE.
Only bitstream and manifest were programmed; saved option storage was not
erased or written. Flash log is `rezomo-flash.log` in that artifact folder.
Physical display/audio approval remains pending. Production `rezo` and main SONORO/CASCADO sources
remain untouched; feature stays isolated on `codex/strezo-built-in-help`.
Next: physical font/help review, then the sibling font ports when requested.

### Family topic HELP qualified and flashed — 2026-09-16

Current qualified source/tag is `f56e772e`. REZO and REZOMO now have the
same fixed PAGE, TOPIC and SCROLL menu as STREZO, with product-specific
per-page guides. All topics have separate scroll limits and 21 visible rows.
Shared formatter, renderer (for the two new ports), Cargo generator and Rust
navigation keep content/navigation consistent. STREZO retains its tested
renderer; its BANDS prose now correctly names the native PRESET control.
REZO/REZOMO FEEDBACK prose and guides use the actual FEEDBACK/CEILING labels.

All three 720p / SS 0.0 builds passed the unchanged 3% headroom gate and were
flashed successfully: REZO slot 2, REZOMO slot 3, STREZO slot 4. Each programmer
completed exit 0 with Refresh: DONE. Option addresses/layouts, exclusion from
programming and conservative erase-block nonoverlap were verified. Saved
settings were not erased. Final visual/listening approval is pending.

REZO's program ROM needed 332 bytes beyond its old 16 KiB allocation. The
family now consistently uses 20 KiB, adding two BRAMs only to REZO. CPU
configuration, working RAM, data/CSR addresses and DSP are unchanged.
Both program ports were tested above 16 KiB. Record schemas remain V3/V4/V7.
First-use HELP remains enabled by default; initialized saved slots start
normally and HELP remains navigable after OPTIONS. The acknowledgement writes
only the reserved four-byte footer, with no implicit patch save or erase.

Resources (logic/BRAM/DSP, firmware bytes) are REZO 23210/42/7, 16716;
REZOMO 22871/43/7, 18436; STREZO 24146/40/20, 15008. HELP ROM rows/raw bytes
are 347/8328, 358/8592 and 328/7872. Every product remains within its budgets;
STREZO has only 142 logic cells free.

REZO qualified on default seed 9 with 11.93% minimum margin; REZOMO also
qualified on default seed 9 with 3.46% minimum. STREZO qualified on seed 4,
heap weight 30 and checked CPU-clear, complete motion-bank and CPU-commit
placement anchors, with 6.65% minimum. Both physical PLL configurations match
their synthesized inputs. No timing normalization, clock change, CPU/DSP
change or gate relaxation was used. Revalidate hooks for changed netlists.

Rejected timing and congestion attempts were not flashed. REZOMO's fixed
serializer-cell attempts became congested or missed serializer timing; one
deliberate seed-9 alternate based on REZO's successful mono serializer
qualified without hooks. STREZO required localizing all motion bits, then
balancing the remaining CPU response-to-register-file detour. A merely
frequency-passing 0.72% system-margin intermediate was rejected.

HELP/control/font/render tests, native family/HDMI checks, ROM/linker/ABI
checks and all 16 Rust host-library tests passed. The final corrected HELP
suite passed 54 tests. Standard and rotated rendering were simulated, but
circular hardware builds remain deferred until the final view/text is approved.

Archives, complete per-topic review text, final timing/synthesis reports,
test logs, exact hooks, hashes and flash logs are in
`/Users/naenyn/git/tiliqua/build/rezo-family-help-f56e772e`; see its
`QUALIFICATION.md` and `HELP_REVIEW.md`. The feature stays isolated on
`codex/strezo-built-in-help` in `/private/tmp/tiliqua-rezo-review-20260914`.
Production `rezo` and main SONORO/CASCADO sources were not changed.
Next: user review/edit requests, then final profile builds and merge when asked.

### STREZO page/topic HELP qualified and flashed — 2026-09-16

Qualified source/tag `145d1945` adds START plus eight operating-page guides
from `STREZO_HELP.md`. Fixed PAGE, TOPIC and SCROLL controls retain the family
header. Changing TOPIC resets SCROLL; each topic has a separate end stop and
21 visible rows. Firmware owns topic-offset lookup and packs topic/absolute
row into the existing command 40, widened to 13 bits. HELP input guards keep
the reused target numbers from editing or being blocked by disabled bands.

The text uses 328 rows / 10,496 six-bit characters / 7,872 raw bytes and four
BRAMs. Final usage is 24,124 / 24,288 logic cells (164 free), 40 / 56 BRAMs,
20 / 28 DSPs; firmware is 15,008 bytes in the unchanged 20 KiB allocation.
DSP, audio math, clock frequencies, V7 sound records and first-use
acknowledgement behavior are unchanged. 55 focused gateware and all 16 shared
Rust host library tests passed, including every topic's start/end rendering
in standard and rotated simulation, 13-bit CSR transfer and navigation bounds.

The fresh 720p/SS 0.0 netlist qualified on the first routing attempt using
seed 4, timing weight 30 and the three revalidated CPU clear-path LUT anchors.
Routing took 267.22 seconds. All clocks pass the unchanged 3% gate:
serializer 7.55%, audio 52.80%, system 7.95%, pixel 10.40%. Both routed PLL
divider/feedback configurations match the synthesized input. Do not assume
this brittle synthesized-cell floorplan qualifies changed sources/profiles.

Archive `strezo-help-topics-145d1945-r5.tar.gz` was flashed to STREZO slot 4
successfully, exit 0 with `Refresh: DONE`. Option storage address/layout was
checked and excluded from programming; saved options were not erased.
REZO/REZOMO were not flashed. Artifacts, guides, tests, exact hook, timing,
hashes and flash log are in `/Users/naenyn/git/tiliqua/build/strezo-help-145d1945`.
See its `QUALIFICATION.md`. User visual/listening approval is pending.

Open HELP after OPTIONS on this initialized slot. Circular builds remain
deferred until the final view is approved. REZO/REZOMO HELP ports and merge
remain pending. Keep the feature isolated on `codex/strezo-built-in-help`;
production `rezo` and the main SONORO checkout were not changed.

### STREZO HELP English qualified and flashed — 2026-09-16

Qualified source/tag is now `f848a6de` (a424ad46's English/glyph fixes plus a
handoff-only commit). The corrected HELP build was flashed successfully to
STREZO slot 4 on R5 serial E46534A193222B21, exit 0 with `Refresh: DONE`.
Saved options were checked against the prototype and excluded from programming.
REZO/REZOMO slots were not touched. User visual/listening approval is pending.

The unchanged synthesized netlist qualified with seed 4, heap timing weight 30
and three explicit CPU clear-path LUT anchors balanced between response and
program-counter inputs. No RTL, DSP, bus handshake, memory or clock-speed
changes were necessary. The initial anchors reached only 2.12% system margin;
the balanced anchors pass every final clock at the unchanged 3% requirement:
serializer 6.65%, audio 48.52%, system 5.63%, pixel 9.70%. Routing took 48.32
seconds. Resources remain 23,999 / 24,288 logic cells, 37 BRAMs, 20 DSPs.
Both physical PLL divider/feedback configurations match the synthesized input.

33 focused gateware checks and all 13 shared Rust host library tests passed
again. The archive, raw timing report, exact anchor script, tests and flash log
are in `/Users/naenyn/git/tiliqua/build/strezo-help-f848a6de`; see its
`QUALIFICATION.md` for the reproducible command and netlist/archive hashes.
The ordinary seed-8 source default is NOT the qualified floorplan for this
revision. Requalify changed netlists and other display profiles; do not blindly
reuse the current synthesized-cell anchors. Router2 congestion and broader
region-placement experiments were abandoned; none was packaged or flashed.

HELP still uses 77 body rows, scroll maximum 56 and the same 3072-character
ROM allocation. Open HELP after OPTIONS on this initialized slot. Circular
builds remain deferred until the final view is approved. REZO/REZOMO HELP ports
and production merge remain pending; keep this STREZO-only feature isolated
on `codex/strezo-built-in-help` while main is occupied by SONORO work.

### STREZO HELP English / glyph review — 2026-09-16

Source `a424ad46` rewrites all HELP sections as brief complete sentences. The
old colon/comma/semicolon/slash/hyphen punctuation was unsupported and silently
rendered as spaces, compounding the label-plus-instruction shorthand. The
formatter now rejects unsupported characters; tests also verify the ROM
alphabet against the actual font. A 3072-character budget guard prevents
accidental growth. The body remains 77 rows, scroll maximum 56, 21 visible
rows, with no font, header, renderer, DSP, clock or saved-format changes.

33 focused gateware checks and all 13 Rust host library checks passed.
Synthesis uses 23,999 / 24,288 logic cells, 37 BRAMs and 20 DSPs. This source
has NOT yet qualified or been flashed. Seed 4 with timing weights 20 and 30
completed but system headroom was only 0.45% and 1.35%, below the unchanged
3% requirement. A 63 MHz system placement-training constraint with weight 30
produced the same 60.81 MHz result and was rejected, with no PLL changes or
normalized timing report. Seed 8/weight 20 and seed 9/weight 30 were stopped
for prolonged routing congestion. No placement jobs remain running and no
new archive was packaged. Reports, tests and copy are in
`/Users/naenyn/git/tiliqua/build/strezo-help-a424ad46/QUALIFICATION.md`.

The rack still has qualified `5c85873c` in slot 4 and saved options were not
changed. Keep the improved text and guards; the remaining task is a qualified
720p/SS 0.0 build before flashing. Do not lower the timing gate, reuse the old
bitstream under a new tag, or change DSP/clocks just to land copy edits.
Circular builds remain deferred until the final view is approved. HELP remains
STREZO-only on the isolated feature branch, not merged into production `rezo`.

### STREZO HELP header / first-use revision — 2026-09-16

The isolated worktree remains on `codex/strezo-built-in-help`; qualified
feature source is now `5c85873c`. HELP remains after OPTIONS. It has the usual
STREZO identity, PAGE/HELP chip and NAV/EDIT/SCROLL status, a fixed SCROLL
control, and 21 visible body rows inside the circular viewport. Fixed header
rows are shared; only the status row has three variants. Content still comes
from the condensed `STREZO_HELP.md`, with one formatter feeding ROM and Cargo.

`TILIQUA_REZO_HELP_FIRST_BOOT` defaults to 1; 0 disables automatic startup
without removing HELP navigation. An uninitialized slot with available flash,
no valid defaults, and no acknowledged HELP starts on HELP. Existing valid
defaults retain BANK startup. Leaving automatic HELP programs and verifies
only the four-byte HELP acknowledgement at sector-zero offsets 4092..4095,
without an erase or implicit patch save. Read failures conservatively start
BANK; a failed acknowledgement may show HELP again. The saved format remains
V7, 40 words, 96 bytes. Saved options were not erased to exercise first use.

The 720p/SS 0.0 build qualified with seed 8: 23,979 / 24,288 logic cells,
37 BRAMs, 20 DSPs; margins are serializer 17.04%, audio 54.12%, system 6.78%,
pixel 8.57%. Routing took 150.74 seconds. The archive was flashed successfully
to STREZO slot 4, exiting normally with Refresh: DONE. The archive's option
region layout was checked against the previous prototype and excluded from
programming; saved settings were preserved. Artifacts, tests and qualification:
`/Users/naenyn/git/tiliqua/build/strezo-help-5c85873c`.

25 focused gateware checks and 13 Rust host checks passed. Meter rendering was
restructured to pre-scale geometry and shorten existing pixel paths, with no
extra pixel latency or DSP/audio changes. A serializer placement experiment
was physically rejected and withdrawn in `84d9b1b8`; the proven split-load
layout and single shared phase ring are retained. Do not restore that option.

The original prototype built quickly, but the expanded header exposed marginal
placement/routing on the nearly-full device. Sharing header rows recovered one
BRAM and the revised build passed the unchanged 3% timing gate. Never flash
the rejected 649d1882/64d0b510/310087d0/84d9b1b8 standard attempts.

Circular builds are deferred until the user approves the final view. A circular
649d1882 build had already qualified before that instruction and was not
flashed; do not rebuild circular profiles during iteration. REZO and REZOMO
do not yet have HELP. Production remains `e89a32fe`, and the main checkout is
occupied by SONORO. Keep this feature separate until the new view is tested.
For this user's initialized slot, manually open HELP after OPTIONS to test it.

### Earlier STREZO HELP prototype — 2026-09-16

The isolated worktree is on `codex/strezo-built-in-help`. Feature source
`57cfef1c` adds a plain scrollable HELP page after OPTIONS, with fixed PAGE
and SCROLL controls. `STREZO_HELP.md` is condensed from the user guide;
`help_content.py` supplies both the ROM and Cargo-generated scroll limit.
The shared font's previously missing J glyph is completed. DSP and saved
records are unchanged. REZO and REZOMO do not yet have HELP.

Both profiles are qualified: standard 720p/SS 0.0, seed 8, minimum margin
5.44%, 23,865 logic cells; circular rotated/default SS 0.01, seed 4, minimum
margin 4.15%, 23,735 logic cells. Both use 37 BRAMs and 20 DSPs. Archives,
guides and timing reports are saved in
`/Users/naenyn/git/tiliqua/build/strezo-help-57cfef1c`.
The standard zero-spread HELP archive was flashed to slot 4 after the
debugger reconnected; the command exited successfully with Refresh: DONE.
Saved options were preserved. Test navigation/scrolling before merging into
`rezo`. Production remains `e89a32fe`; the main checkout remains SONORO.

### Completed arithmetic release

The older sections below are historical. Production is on `rezo`; the
arithmetic fixes were developed on `codex/rezo-arithmetic-fixes` at
`50384c31` and merged back with the current documentation at `e89a32fe`.
Use the isolated checkout `/private/tmp/tiliqua-rezo-review-20260914`;
the main checkout is occupied by SONORO work.

All three 50384c31 standard 720p images, with spread spectrum 0.0, passed
the 3% timing-margin gate and were flashed to REZO 2, REZOMO 3, STREZO 4.
This establishes build/flash success, not a new user listening qualification.
The four corrections cover wide accumulation, minimum INPUT mute, STREZO
MID/SIDE headroom, and REZOMO random SHIFT range. All 230 gateware cases passed
across the full/focused runs, and all 10 Rust host tests passed.

The completed release set contains nine archives: three rotated circular at default
spread spectrum (0.01), three standard 720p at default (0.01), and three
standard 720p at 0.0. All nine passed qualification; the latter set was flashed
to slots 2/3/4, with all three refreshes reporting DONE. Preserve saved
options. Use distinct NOSS artifact names for zero-spread builds. The README
and three user guides describe current behavior; do not restore the older
SHIFT skipped-band claims, 1.25% timing gate, CPU maps, or seed assumptions.

Release artifacts and qualification are in
`/Users/naenyn/git/tiliqua/build/rezo-release-e89a32fe`.
The isolated checkout is now on `codex/strezo-built-in-help` for a STREZO-only
HELP prototype. Keep this separate from production until hardware-tested.

At 50384c31, standard REZO qualified with seed 8 (seed 9 missed the video
margin at 2.91%); REZOMO qualified with 3 and STREZO with 8. Requalify every
new source revision. Avoid blind large seed sweeps.

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

## Phase-safe REZO serializer (step 4)

REZO no longer uses four independently reset local TMDS phase rings. Like
STREZO, it now has one shared word-phase ring, but its dense placement requires
two explicitly retained load-strobe registers per lane. The lower strobe is at
Y2 beside bits 0..7 and the upper strobe is at Y5 beside bits 8..9; the ten
shift registers retain their per-lane floorplan near the fixed DVI pins.
Keeping the ECP5 register primitives is necessary because synthesis otherwise
merges the equivalent copies back into a cross-lane high-fanout select.

At the existing REZO seed, the phase-safe route achieves:

- DVI5X 402.74/371.33 MHz
- DVI 81.90/74.25 MHz
- sync 63.30/60 MHz
- audio 73.86/49.15 MHz
- 36 DP16KD, 7 MULT18X18D, 18,879 total LUT4s, 8,308 DFFs

Canonical source commit `424d381b` produced
`build/rezo-r5/rezo-424d381b-r5.tar.gz`, SHA-256
`2240355b8a7e683a48f9056221b45e79e709ab88d5d63674a216a8a1dc07d1c4`.
This image has not been flashed.

## Measured renderer/control timing work (step 5)

Clean pre-change builds were essential. At `be69ccec`, REZO passed, but REZOMO
missed the 3% production gate in sync at 60.79/60 MHz (1.32% headroom), and
STREZO missed it in DVI at 76.02/74.25 MHz (2.38% headroom). STREZO also spent
roughly half an hour resolving final routing congestion.

The accepted fixes are deliberately product-specific:

- REZOMO registers the clamped Turing effective length. The UI length/start
  controls are stable for millions of sync clocks, and the register cuts their
  long combinational cone out of the worker/modulation update path. The build
  now reaches sync 66.49 MHz, DVI 78.68 MHz, DVI5X 436.68 MHz, and audio 75.75
  MHz with 19,013 LUT4s and 8,421 DFFs.
- STREZO decodes the selected OUTPUT target into registered row/source fields
  instead of rebuilding a five-column linear index after the column BRAM. DVI
  rises to 86.61 MHz, sync reaches 63.02 MHz, DVI5X reaches 391.24 MHz, and
  audio reaches 73.37 MHz. The route completes in minutes with 19,070 LUT4s
  and 8,445 DFFs.
- REZO registers its scaled OUTPUT-send BRAM data before the fill endpoint
  adder. Exact fill-boundary tests pass; the route reaches DVI5X 426.62 MHz,
  DVI 80.04 MHz, sync 66.49 MHz, and audio 72.55 MHz with 18,864 LUT4s and
  8,315 DFFs.

The first combined test archive exposed a route-dependent STREZO HDMI failure:
audio ran normally, but the receiver detected no connection. The serializer
logic was unchanged from the prior hardware-qualified image, but its shared
phase ring, load strobes, and shift registers were left unconstrained. STREZO
now uses the same proven per-lane serializer floorplan as REZO while retaining
one shared phase ring. The routed candidate reaches DVI5X 482.39 MHz, DVI
80.01 MHz, sync 66.34 MHz, and audio 69.80 MHz. Archive
`build/strezo-r5/strezo-59dc30d1-r5.tar.gz` has SHA-256
`0cd9bfdeb63cf78592d114c6122549786896a3bc1646766f1f9c7668612c443d`;
it was flashed to slot 4 and the user confirmed normal HDMI, UI, and audio.

The same send-data register was tested in REZOMO and rejected. Although it
removed the original OUTPUT BRAM critical path, the altered placement exposed
a band-marker path at only 76.59 MHz DVI (3.15% headroom) and made routing much
slower. REZOMO therefore retains its pre-existing raw-send pipeline.

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
4. ~~Remove the unused `yosys`, `nextpnr_ecp5`, and `ecppack` fields from
   `targets.py`; all current family targets set them to `None`.~~ Completed
   after the hardware-qualified STREZO serializer fix.
5. ~~Consolidate duplicated firmware-build/CLI plumbing in `rezo_cpu.py`,
   `rezomo_cpu.py`, and `strezo_cpu.py`.~~ Completed in `b961597c` through
   `cpu_build.py`; the `*_cpu` console entry points remain compatibility
   aliases. Full standard builds reproduced the preceding timing exactly:
   REZO 426.62/72.55/66.49/80.04 MHz, REZOMO
   436.68/75.75/66.49/78.68 MHz, and STREZO
   482.39/69.80/66.34/80.01 MHz (DVI5X/audio/sync/DVI). Archive SHA-256 values
   are `765bd4c5ef661b2ecad31a0a503c29e034033f5201bc4938492efe323cfcb904`,
   `dbebd964fa7f8546cb42baf27e68203e61fb32b632e7cfefcfe178919477e271`,
   and `3a3e464cdd1d5d8b3b8ed5cde636618fbd517676e5ade1bc33a4403031d01b6d`.
6. Extract the duplicated Rust persistence, arithmetic, input, navigation, and
   edit-loop primitives into the shared firmware crate behind a product spec or
   trait. In progress: endian record access, journal CRC, and clamp-add helpers
   are shared. The encoder/flash MMIO addresses, volatile access, flash command
   transport, and UI command encoding are also shared; the UI index width is an
   explicit product parameter (five bits for REZO, six for REZOMO/STREZO).
   Nine host tests cover the common bit packing, CRC, arithmetic, navigation,
   and both UI command formats. Release text sizes are REZO 14,880 bytes,
   REZOMO 16,952 bytes, and STREZO 13,356 bytes, all within their physical
   firmware regions.

   Full `9d3774fb` standard builds preserve the established timing exactly.
   Archive SHA-256 values are:

   - REZO: `1529a75901dcaf4b0db74fd4becc783ac1738c9c3446d6c67952591f179e3ff3`
   - REZOMO: `78c497e13177826db124ce63db7289b805b7cbb893b22faba2b5ed9f6b4fddbd`
   - STREZO: `f4ed326e0430b27b688e289531b525c4f4632113253daad82226095e09697b3a`

   Continue one equivalent block at a time, with firmware-size and full
   bitstream checks after each checkpoint. The next candidate is shared sector
   scan/save orchestration behind a product-owned record codec; product record
   schemas and page/edit behavior remain intentionally local.

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
