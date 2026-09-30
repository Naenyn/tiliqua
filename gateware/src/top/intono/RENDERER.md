# Instrument renderer migration

## Hardware testing instruction

The user authorized automatically flashing successfully qualified **non-circular
1280x720 INTONO builds to slot 1** after building, until they revoke this
instruction (2026-09-08). Check for other active flashing work and acquire
`/tmp/tiliqua-flash.lock` for the complete flash sequence. Do not automatically
flash circular builds, other slots, or timing-failed artifacts. Preserve option
storage unless the user requests otherwise.

The earlier instruction to keep the bootloader name **TUNER** regardless of the
feature set (2026-09-08) was superseded when the instrument became **INTONO**.
Normal builds now use INTONO; historical TUNER archive names and measurements
below are retained as evidence of the builds that produced them.

## Contract

### Calibration dashboard (2026-09-27)

The CAL view now uses the retained framebuffer for a bounded response plot,
with text overlaid for patch routing, profile range/quality, and the existing
scan/review actions. The horizontal axis is actual applied V/oct voltage, with
integer-volt ticks. During acquisition it spans the characterized voltage
limits from `calibration::bipolar`; after a quality-acceptable candidate is
found it zooms to that measured range with 5% padding. An unsafe candidate
retains the full sweep view. The dashed rising diagonal denotes the ideal
1 V/oct pitch rise in the default **PITCH** graph. Here the Y-axis is literal
detected pitch in cents (A4 = 6900c), so the vertical distance between a dot
and the diagonal is the tracking error; small errors can be subpixel at a
many-octave span. A narrow strip below the PITCH plot marks each qualified
adjacent interval by its *local* departure from 1 V/oct: cyan below 50,
yellow from 50 to 200, and red at or above 200 cents per volt. Unmeasured
intervals remain dim rather than being interpolated. This is raw oscillator
tracking, not the residual error after applying a correction profile.
The CAL menu's **GRAPH** option switches to **ERROR**, where
the same measurements have a linear, symmetric cents-error Y-axis and a
horizontal dashed 0c ideal line. Its scale expands through readable steps
from ±20c to fit the measured curve with headroom, so broad slope errors do
not masquerade as a flat +20c plateau. Both views anchor the ideal response to the first qualified
measurement, so arbitrary oscillator tuning offset does not count as
tracking error.
The measured polyline crosses only adjacent dots at most 125 mV apart, leaving
unmeasured intervals blank. The ERROR view clips only beyond the largest
supported axis span. A graph toggle redraws
both cached banks, including the active provisional trace, from the same
stored points; neither acquisition nor profile storage changes.
The live sweep keeps fixed bounds so new points do not rescale older pixels.
The polyline uses only stored points, with no implied extrapolation or
fabricated correction series. Profile changes invalidate the
cached plot in both background banks; the previously published CAL background
stays visible while its replacement is prepared. PLAY and QUANTIZER retain their text
views for now. This is a visual first pass, not a change to
calibration acquisition, acceptance, or flash storage.

The initial hardware photo exposed a text/plot overlap: the actual overlay
uses a 12-pixel column pitch, not the generic 16-pixel canvas cell assumption.
The plot now ends before sidebar column 31, with a bounded-layout test. The CAL
text layout remains stable while the plot is rebuilt, and PROFILES prewarms the
retained calibration scene after a profile is loaded so returning to CAL need
not show the legacy text layout as an intermediate screen.

A later hardware photo still showed the old text view briefly: a stale
tracking-failure record selected its renderer whenever the background was
rebuilding. That renderer is now removed. CAL keeps the graphical layout,
presents a live point-count progress bar and compact failure diagnostics. The
progress bar reflects acquisition count; qualified sweep anchors also appear
on the live plot as they arrive.

The intended navigation is four primary utility surfaces: TUNER, CAL, QUANT,
and ROUTES. CAL owns scan, automatic check/improve, review, and quality display.
Its profile browser should become a contextual library panel rather than a
separate operating screen. QUANT similarly owns scale editing and its scale
browser. ROUTES configures input/output pairing and optional calibration and
quantization; it is not a generic “presets” page. Existing VERIFY, PROFILES,
note, and setup menu pages remain functional as an intermediate implementation.
The CAL, PROFILES, and VERIFY menu pages now share one graphical display with
different contextual status lines; their actions remain separate while the
menu design is being revised. Do not remove storage or advanced controls until
replacement navigation is tested. Live points require incremental redraw without stalling acquisition
or showing a previous profile as the current run; the first implementation is
described below.

### Provisional response trace (2026-09-27, awaiting hardware check)

During a new characterization sweep, CAL now displays the empty calibration
grid instead of a previously accepted profile. Accepted *provisional* sweep
points extend the response line in the unused framebuffer bank, and only that
bank is swapped into view. The scan uses fixed -5..+8 V axes anchored to the
first qualified pitch, avoiding a curve that stretches with every new point.
Each bank tracks its own drawn prefix; a discovery restart, reduced point
count, or changed starting point invalidates the provisional image before it
can be mistaken for a continuous calibrated curve. The completed candidate
returns to the normal profile renderer and its quality grade. This changes
only visualization, not the measured data, acceptance policy, or flash format.
It requires a hardware scan to check redraw cadence and tearing; none was
flashed while the rack was off.

The first hardware check found an empty CAL page whose grid and circular edge
appeared only after entering a scan. Preparing the empty CAL background in the
unused bank at startup was insufficient: the tuner idle path immediately
replaced it with the linear tuner background. The idle path now preserves CAL
on that bank while Spiral is visible, so the first CAL transition can swap a
complete frame. A profile redraw retains the previous visible background
instead of blanking it. Hardware confirmed that the empty graph and outer
circle now appear immediately.

The next hardware run failed before collecting a low-voltage pitch sample.
Serial reported `DAC FAULT STATUS_RAW=0x203` at -4.91675 V. That encoded
voltage is inside the gateware's -5..+8 V guard. History review shows the
repository rename changed labels and build-environment names but not the DAC
command path; the live-trace commit added an unnecessary two-bank graph
invalidation at the start of an empty scan. Avoid that redraw when there are
no old pixels, and renew the existing output command before optional serial
and graphics work. Retain the 100 ms hardware watchdog and the explicit
failure diagnostic. A follow-up hardware run must confirm acquisition.

### Complete retained graphics fixtures (2026-09-09)

`ui_canvas::grid_segment` and `trace_segment` expose bounded units of retained
drawing work. Each call emits at most one on-canvas line (720 pixels maximum),
and invalid rectangles, ranges, sample counts or segment indices emit nothing.
Trace points are uniformly spaced observations mapped onto a supplied vertical
axis, not an oscillator-calibration interpolation algorithm. The original grid
helper delegates to the segmented implementation.

The Rust fixture `tests/tuner_scene_fixture.rs` uses those production helpers
to generate synthetic four-lane tuner, calibration-error graph, and quantizer
octave-grid backgrounds. The integration tests feed these CPU-produced pixels
through the real `TunerOverlay`, including compact colored text and the actual
menu panel open/closed. Consecutive scanline samples check output pixels and
coordinate latency against an independent text-composition reference. Separate
host tests verify line bounds, grid segmentation equivalence, invalid inputs
and trace endpoints. Circular-safe geometry is asserted by the fixture; these
scene integrations use non-circular scanout, while the existing tests retain
coverage of rotated text/sprites/panel transforms.

Nine canvas tests and six production-scene integrations pass. Retained drawing
emits 3,384 / 6,490 / 10,454 pixels respectively. Counts exclude framebuffer
clearing, text writes, cache flushing and scanout; they are not wall-clock or
frame-rate measurements. Efficient live graph editing still needs a policy for
erasing/replacing old traces and CPU-time measurement on hardware.

No synthetic scenes are exposed to the user or treated as instrument features.
The production firmware build succeeds and is byte-identical to the installed
firmware (SHA256 `24f523f69b6c24f685c16dceec6c07059d6f319f712167deac89785b2f9f6771`);
the unused helpers are stripped. FPGA is unchanged, so no flash is needed for
this validation milestone. Calibration/profile persistence, quantizer behavior
and four-channel acquisition remain separate work, not implemented by fixtures.

### Menu label padding (2026-09-09)

The eight-character SETTINGS heading began at x=455 while the two-pixel panel
border occupied x=454–455. Extend the panel left edge to 448 and width to 256;
the right edge remains 704, text remains at 455, and the divider remains at 533
(relative rule offset now 85). This gives five empty columns between the border
and first glyph without moving any menu text. Production raster checks verify
the bold S, the clear gap and border in both display orientations.

Four focused raster checks pass. Full build timing passes: CPU 66.76/60 MHz,
pixel 91.60/74.25, serializer 394.01/371.33, audio 69.19/12.29. Logic is
13,437 cells; FF/EBR/DSP remain 6,838/24/6. Flashed non-circular slot 1 with
settings preserved. Archive SHA256:
`e259e0953e09a5a9972575d482c3f5197c68cd48ef0fe681e92334ddedb82ab7`.

### Channel handoff correctness before multi-input acquisition (2026-09-09)

Review of the selected-channel acquisition path found two pre-existing issues
that must not be carried into the multi-channel interface. Input selection only
reset part of the pitch state, with later crossing assignments able to override
that reset, and did not reset the RMS window at all. The detector now gives
selection changes priority over sample processing, clears both published
snapshots and both accumulation windows, and advances their sequence numbers.
This invalidation also happens with a paused audio stream. A sample coincident
with the handoff is discarded; a new level reading requires a complete new
window, and pitch remains invalid until a new observation completes.

Firmware now rejects an inconsistent snapshot after its fourth attempt rather
than consuming the final torn values. Selection is checked before and after
the reads to avoid assigning data to an input changed by the encoder ISR.
No detector replication, extra renderer, or algorithmic accuracy claim is made.

Seven gateware tests pass, including active/paused stream switches coincident
with crossings/window completion, clean first RMS windows, fresh pitch after
switching, existing sine/DC-offset behavior, and reference oscillator behavior.
Three firmware host tests cover stable reads, sequence rollover, bounded retry,
and rejection after exhaustion. These tests do not qualify four-channel pitch
estimation; only one channel is still measured at a time.

Full non-circular r5 build passes: CPU 69.68/60 MHz, pixel 93.69/74.25,
serializer 403.88/371.33, audio 67.11/12.29. Resources: 13,180 logic cells
(-114), 6,838 FF, 24 EBR, 6 DSP (unchanged except logic). Firmware 96,608
bytes (+40). Archive SHA256:
`48e238102e20131f81445df4dab0a288ee1a91733d481475e410e252d0ed8141`.
The intended hardware check is switching inputs with different frequencies and
amplitudes, looking for a clean invalidation/reacquisition rather than retained
pitch or a mixed voltage window. Overall UI appearance is unchanged.

### Firmware marker publication and linear layout (2026-09-09)

`ui_markers` now owns validated logical marker descriptors and four-slot frame
packing. Firmware replaces all slots on each publication; absent channels are
explicitly disabled, preventing stale markers when future channel/view modes
change. Slot zero uses the same descriptor with its backward-compatible atlas
register encoding. The current selected-channel client disables slots 1–3.

The live linear cursor now uses fractional cents before the text label rounds,
with nearest-pixel positioning on the shared 416-pixel ruler (~0.24 cents per
pixel). This changes display quantization, not detection accuracy. Non-finite
coordinates are rejected by the helper. `ui_canvas` also defines four retained
ruler lanes at y=224/328/432/536, using exactly the single-lane geometry and
bounded line rasterizer. Those lanes are tested but not exposed as a live view
until there is actual multi-channel acquisition; cached measurements must not
be presented as simultaneous readings.

Eight canvas and two marker host tests pass, plus three production CSR/raster
integration checks. The firmware-only r5 1280x720 build retains qualified FPGA
CRC 3248250310 and its timing/resource results below. Firmware is 96,568 bytes
(+200); no FPGA resources added. Archive SHA256:
`142e05b9112217a2fb9143a4bbb58f97982bee9656eb8ec7c0a20a46093f0dac`.

### Four-marker production interface (2026-09-09)

The production compositor now uses four shared-atlas sprite slots. Slot zero
retains its firmware ABI; three additional write-only descriptors live at display
CSR offsets 0x10, 0x14, and 0x18. Each packs logical x[9:0], y[19:10],
orientation[24:20], hue[28:25], and valid[29]. They stage and publish with the
same acknowledged frame snapshot as text, menu and slot zero. Writes while busy
are ignored; reset leaves the additional slots disabled. Coordinates outside
the logical 720x720 canvas disable those slots. Later opaque slots win overlaps.

All four rows use one atlas port, taking eight preparation clocks within the
existing sixteen-clock blanking allowance. Pixel latency remains nine clocks.
No additional bitmap memory or DSP multipliers are needed. Additional slots
are analytical arcs only; the legacy slot-zero visualizer halo is composited
after sprites and is not yet a multi-channel visualizer composition policy.
Current firmware still measures and displays one selected input; this change
does not implement four-channel pitch estimation.

Full r5 1280x720 build: 13,294/24,288 logic cells (+1,178), 6,838 flip-flops
(+473), 24/56 EBR and 6/28 DSP (both unchanged). Final timing passes: CPU
67.24 MHz against 60, pixel 90.41 against 74.25, serializer 444.84 against
371.33, audio 67.90 against 12.29. The extra slots cost about 4.9 percentage
points of total device logic capacity, not zero; account for that before adding
detectors. Approximately 45% logic remains, but this is not a guarantee that
four expensive estimators plus calibration and quantization will fit.

Validation: 31 existing display/frame/sprite/text/bus checks pass; two new
production four-marker raster checks pass after correcting their fixture to
use the production (already frame-latched) input mode. The raster checks cover
both display transforms, orientations, distinct colors, overlap and disable.
The CPU byte-CSR integration test also covers atomic extra descriptors and
ignoring writes while publication is pending. Non-circular archive SHA256:
`f3fc99233269b7e63b320ac86ebc7a347106c0a9e3ba620549eccb345a8870a2`.

One CPU-owned UI and one scanout/compositor must serve the tuner, oscillator
calibrator, and quantizer. Instrument semantics do not belong in per-pixel
hardware. Additional labels should change character data, not add a hardware
renderer for each label. Graphs and spiral geometry use CPU-authored retained
pixels; frequently moving indicators need a bounded, reusable sprite path.

References reviewed: the `rezo` branch at `27d9ecbf` (`display_common.py`,
`ui_common.py`, `ui_specs.py`, and `RezoTileDisplay`), and the shared
XBEAM/OSCIO/SONORO `draw_options` typography and encoder interaction.
Borrow REZO's semantic colors, consistent layouts and circular-safe content
placement. Preserve the overlay-menu interaction and 9x15 normal/bold font
from the other family. Do not import either complete renderer alongside ours.

## Implemented: shared text path

`renderer.py` provides `TextPlane`, `Panel`, and `TextCompositor`. It has no
pitch, note, scale, profile, encoder, clock-configuration or display-modeline
dependencies. The caller supplies logical coordinates and a background pixel
stream. The renderer supports:

- Arbitrary compile-time plane origins, bounded grids, pitch and glyph scale.
- Printable ASCII normal/bold glyphs, including lower-case profile names.
- Optional per-character hue/intensity for channel identification.
- Opaque panel fill, border and divider; later layers have priority.
- One shared glyph-ROM read port and one glyph bit-selection path.
- An explicit five-clock pixel pipeline, including coordinates and blanking.

Character-cell memories remain caller-owned. A later text cell owns its glyph
box rather than blending underlying text glyphs; an opaque panel also masks
earlier text in the spaces between cells. This matches our modal-menu use.

The first shared-text step retained its firmware register ABI, exact main/menu glyph
assets, selected-input detector, reference oscillator and working marker shape.
The legacy large glyphs fit into unused addresses in the shared normal-font
bank. Two menu-coordinate ROMs and the separate main-font lookup are removed.
Coordinate division is bounded and exact over 0..1023; explicit signed-digit
shift/add expressions avoid inferring audio DSP multipliers.

The complete adapter latency is nine pixel clocks instead of four. This is
pipeline delay, not a reduced frame rate: it still accepts/emits one pixel per
clock. Physical scan timing and logical coordinates are delayed with the pixels.

## Verification

`test_tuner_renderer.py` checks the arithmetic against integer division and
compares continuously changing raster samples against an independent software
reference. Synthetic four-color tuner, mixed-case calibration/profile and
quantizer/scale text screens all use the same compositor, with menus open and
closed. These are text-layout fixtures, not implemented instrument modes or
completed graph/sprite prototypes.

`test_tuner_display.py` checks the real tuner adapter, every legacy glyph in
both orientations, marker continuity, panel composition and pixel alignment.
Build timing must pass every clock; a successful pack/archive alone is not a
qualification. Tuner builds no longer request `--timing-allow-fail`.

## Implemented: atomic frame publication

`FrameExchange` owns a bundled-data request/acknowledgement handshake between
the CPU and pixel clock. The CPU writes only its back character bank and staging
marker registers. Writing `FRAME.commit` last freezes both until the reader
adopts the frame at `(x=0, y=-1, de=0)`: the final blank line before visible
scanout, independent of sync polarity. The returned acknowledgement releases
the former front bank to the CPU. Busy writes/duplicate commits are ignored.
The mailbox payload remains stable throughout the request/acknowledgement
round trip; only the request and acknowledgement toggles need synchronizers.
This protocol assumes the existing common bitstream reset, not independent
runtime reset/reconfiguration of one domain.

The new `FRAME` CSR occupies the formerly unused offset `0x8`; other register
offsets are unchanged. Hardware and firmware must be deployed as a matching
archive: old firmware does not commit frames and cannot drive this version.
Main text uses two padded 2048-entry banks; menu text uses two 256-entry banks.
This adds one EBR (menu banks still fit in one). Immutable fonts and lens assets
are shared, not duplicated. The production adapter no longer samples marker
fields independently. Unbuffered mode exists only for isolated raster tests.

Firmware reads the busy status without waiting, refreshes all owned main-view
fields in the back bank, refreshes menu contents once per dirty bank, then
commits. Measurements, reference-output control and encoder handling continue
even if a display transaction is pending. It does not clone a full framebuffer
or allocate another large CPU-side UI object. Background PSRAM guide pixels
remain immutable in this phase; later changing graphs will need equivalent
publication ownership rather than live front-buffer drawing.

`test_tuner_frames.py` tests three unrelated clock ratios, held payloads,
duplicate requests, lost-update prevention, bank ownership, invalid busy writes,
the actual CSR byte bridge, and the real banked main/menu glyph output.

### Atomic-frame build

Non-circular R5, seed 14: final pixel Fmax **93.44 MHz / 74.25 MHz required**;
serializer **391.70 / 371.33 MHz**; CPU **67.18 / 60 MHz**. All final clock
checks pass with strict timing enabled. Whole design: **12,281 logic cells**,
**6,366 registers**, **22/56 EBR**, **6/28 DSP**. All **21** focused tests pass.
Only the non-circular target was rebuilt for this step; the earlier circular
archive does not include atomic publication.

Artifact: `gateware/build/tuner-atomic-r5/tuner-atomic-75a8c521-r5.tar.gz`.
SHA-256: `e2cf00531d520db993d120359b9a86319655e007ba7b5554cc3bc7f24a3332c6`.
As before, the filename contains the base commit, not a new commit identifier.
Flashed successfully to slot 1 on 2026-09-08 after the coordination check;
option storage was preserved. The user confirmed that this build looks good.

## Remaining redesign work, before detector expansion

### First-milestone measurements

R5, existing 16-KiB CPU RAM, 1280x720 HDMI; same detector and firmware ABI.
The baseline is commit `75a8c521` seed 13. The revised renderer uses seed 14;
its first seed-13 attempt narrowly missed the unchanged HDMI serializer's
371.33-MHz constraint, so it was not accepted. The alternate placement passes
all four reported clocks, and the final archive was rebuilt with strict timing.

| Measure | Baseline | Shared text |
| --- | ---: | ---: |
| Whole-design logic cells | 12,522 / 24,288 | 12,697 / 24,288 |
| Whole-design registers | 6,109 / 24,288 | 6,403 / 24,288 |
| Whole-design EBR blocks | 23 / 56 | 21 / 56 |
| Display EBR blocks | 9 | 7 |
| Whole-design DSP blocks | 6 / 28 | 6 / 28 |
| Reported final pixel-clock Fmax | 75.01 MHz | 91.80 MHz |
| Required pixel clock | 74.25 MHz | 74.25 MHz |

The memory/timing gain is not a universal size reduction: the registered
coordinate and pixel pipelines add registers and some logic. This is an
intentional measured trade, not a reason to spend the remaining budget freely.

Circular seed 13 also passes final timing (95.23-MHz pixel Fmax versus
39.07 MHz required; CPU 67.92 MHz versus 60 MHz). Its inherited 390.8-MHz
PLL VCO legality notice remains unresolved, so timing closure is not a claim
that the circular clock configuration is fully qualified.

All 17 first-stage renderer/display/detector tests pass. The HDMI archive below
was successfully flashed to slot 1 on 2026-09-08; the user confirmed it looked
as it did previously and authorized continuing.
The circular archive has not been flashed. Builds live separately from the previous tuner:

- `gateware/build/tuner-renderer-r5/tuner-renderer-75a8c521-r5.tar.gz`
  SHA-256 `f8670e289bf527595853f3890e22618ea6b3a7a54002bb6b8eba367c3280e33e`.
- `gateware/build/tuner-renderer-round-r5/tuner-renderer-round-75a8c521-r5.tar.gz`
  SHA-256 `fdf9540bec9832908fd6f81a259ecd6b4113a6ce87202b8d3cbc5e40c839c737`.

The filenames contain the base commit; these archives include the uncommitted
renderer migration. Use the hashes, not the commit suffix alone, to identify
these exact builds.

### Shared retained drawing and text fields

`fw/src/ui_canvas.rs` centralizes logical-to-physical mapping and integer lines;
the tuner background now uses these helpers. It also provides rectangle/grid
outlines, circular-safe rectangle checks and saturating graph-axis mapping.
Helpers allocate no heap or image. Line endpoints must be on-canvas (invalid
geometry is rejected); each line emits at most 720 pixels. Grid divisions are
capped at 32 per axis. Axis normalization uses CPU arithmetic, not FPGA DSP.

Host tests exhaustively check logical pixels on both display transforms for
unique in-bounds addresses, line work bounds, signed measurement extremes, and
candidate four-row tuner/calibration/quantizer footprints inside a radius-336
circle. These are geometry tests, not completed new instrument screens.

`ui_text::field` replaces a field in one pass including blanks, supporting
left/center/right alignment and Unicode-safe truncation. Production centered
fields use this instead of separate erase/draw passes, preserving the exact
45-column center and preventing stale short values. Three text and four canvas
host tests pass. This is not yet a dirty-span optimization.

Retained drawing is for startup/occasional changes, not full plots on every
audio update. Runtime background ownership/publication still needs design and
verification before live calibration plots; these helpers do not by themselves
make framebuffer writes tear-free.

Firmware-only HDMI build reuses the qualified FPGA image (CRC 3630939042), so
FPGA usage/timing is unchanged. Firmware is 93,396 bytes. Current TUNER archive
SHA-256: `43bfb4e6b56be4815bd71b47da43ec04d679893010d10df4aff55fdf5974255c`.
Flashed successfully to slot 1 under the shared lock on 2026-09-08; saved
options preserved. User hardware confirmation pending.

### Next steps

### Coordinated scene acquisition integrated into TUNER

TUNER now opts into `DMAFramebuffer(frame_exchange=...)` using `SceneExchange`.
Other bitstreams retain the unchanged default path. The opt-in reader captures
one base at a reader-owned vsync edge, retains every Wishbone transaction until
ACK (including final words), reserves space for complete bursts, drains the last
three bytes even if the FIFO has no following word, and aligns pixel control
signals with registered coordinates/data.

`SceneExchange` holds the foreground payload and optional background swap until
DMA acquisition, then publishes foreground at the existing last-blank-line
boundary. CPU busy clears only after that visible-domain acknowledgement returns.
Ordinary commits do not swap backgrounds. Frame CSR bit 3 requests a background
swap; read bit 4 identifies its back buffer (0 or 1 MiB offset). Firmware must
initialize and flush that buffer BEFORE requesting swap, never write while busy,
and publish matching text/markers in the same transaction. Current firmware does
not request swaps, so only the initialized original background is displayed.

Four end-to-end DMA/FIFO tests use nonuniform pixels, delayed ACKs (including all
terminal transfers), both sync polarities and unrelated clocks. They verify all
words are fetched in order, all visible pixels match their bank, and synthetic
foreground scene metadata changes with its matching background. Startup is black
before the first DMA vsync. A separate test checks repeated foreground-only and
background-changing commits, early boundaries and illegal resubmission. Together
with existing suites, 32 focused tests pass (31 full-suite plus the subsequently
added scene-only test, also run with its four ownership/layout peers).

The tests do not yet exercise actual multi-view firmware, PSRAM cache coherency
on hardware during swaps, or independent clock resets. Acquisition-to-publication
must fit the supported display blanking interval; sustained memory starvation
or runtime clock changes need recovery policy before being supported. The round
FPGA image is not newly qualified merely because both sync polarities pass tests.

Full HDMI build qualified on 2026-09-08: logic 12,762/24,288, FF 6,359/24,288,
EBR 24/56, DSP 6/28. Compared with the preceding qualified renderer, this adds
122 logic cells, removes 57 FFs, and uses no additional EBRs or DSPs. Final clocks
pass: pixel 94.37 MHz (74.25 required), serializer 465.98 MHz (371.33),
CPU 64.37 MHz (60), audio 68.02 MHz (12.29).

Archive `build/tuner-r5/tuner-75a8c521-r5.tar.gz`, visible name TUNER,
1280x720p60, firmware 93,396 bytes. SHA-256:
`7134d0879d22c2bc1390bd2e3e1c6b33095a6cae02176138a8196f686603e127`.
Flashed successfully to slot 1 on 2026-09-08 under the shared flash lock after
checking other sessions and active flasher processes. Saved options preserved.
Hardware confirmation pending; current firmware still does not request a
background swap, so this is not hardware validation of live scene switching.

### First real scene-switching client: linear tuner

Firmware now offers LINEAR alongside ARC/VISUALIZER, using the existing selected
channel detector. This exercises actual background selection, complete text-bank
replacement, marker placement and the common overlay menu. It does not implement
four-channel measurement, calibration plotting, or quantizer tables yet.

The spare background is warmed during idle exchange opportunities after startup.
Clears are bounded to 1,024 words (4 KiB) per preparation step: 225 clear steps for
HDMI, 127 for the panel. The border and ruler are drawn once after clearing and
the cache is flushed before marking the scene publishable. The current view stays
live; an early selection shows PREPARING VIEW. Both backgrounds then remain cached
at 0 and 1 MiB offsets, with no per-switch background writes. The border/ruler draw
and cache flush are not yet time-sliced or wall-clock profiled on hardware.

Each text bank is fully cleared (2,025 cell writes) on its first use for a new
scene, then receives complete current labels/fields. Ordinary updates keep the
existing bounded field writes. The linear ruler emits fewer than 1,000 pixels;
its cursor uses the same -50..+50 axis mapping as its ticks, without the spiral's
cosmetic pitch smoothing. Instrument accuracy is otherwise unchanged.

Validation: 13 DMA/ownership/frame-publication simulation tests pass, plus 12
host tests across background preparation, canvas geometry, text and save feedback.
Preparation tests cover both sizes, interrupted requests and 100 cached round trips.
These are not a substitute for hardware cache-coherency and switch-latency checks.

Qualified firmware-only HDMI build on 2026-09-08: 94,816 bytes (+1,420); bitstream
CRC 2527963884 is unchanged, so all FPGA resource counts and passing timing remain
those of the preceding full build. No new detector, DSP or block RAM is added.
Archive SHA-256:
`59e49a4368c7d477619a9d3a062a5b0a7c035a3f841ea3ccd1d4ac44872546b7`.
Visible artifact name remains TUNER. Circular hardware was not rebuilt.
Flashed successfully to slot 1 under the shared lock on 2026-09-08 after checking
other sessions and active flasher processes; saved options preserved. Hardware
confirmation of LINEAR/ARC switching and menu behavior is pending.

### Sparse text invalidation

The user confirmed LINEAR works. Firmware now tracks occupied glyph cells with
one 256-byte bitmap per text bank. Each bank is fully initialized once; later
scene changes erase only its occupied cells. Static labels are retained until
that bank changes scene. Dynamic fields still replace their complete footprint,
so short note names and signal-loss messages cannot leave stale glyphs. Menu
publication and background ownership are unchanged. This is sparse clearing,
not a full dirty-cell diff: unchanged dynamic fields still generate writes.

The current spiral footprint is at most 165 cells, versus 2,025 formerly cleared
on every scene change; initial bank clears remain full-size. Retained static
labels avoid 29 writes per ordinary spiral update and 18 per linear update.
The added occupancy state is 512 bytes total, not an 8-KiB full text shadow.
Compiled function prologues reserve 1,808 bytes for the foreground closure,
128 for run and 336 for publish_tuner; these are individual frames, not a complete
worst-case call-chain or interrupt high-water measurement.

Six host text tests pass, including bank isolation, full-plane clearing, blank
styles, shorter fields and 200 alternating scene/bank updates. Firmware-only
HDMI build: 95,120 bytes (+304), unchanged top.bit CRC 2527963884; no FPGA resource
or timing change. Archive SHA-256:
`6207c79d49096f740f3b3f13aaa9a5564692bba3055a9e846024acde6524e634`.
Flashed successfully to slot 1 on 2026-09-08 under the shared lock, after checking
other tasks and active flasher processes. Saved options preserved; hardware
confirmation pending. Visible output and typography are intended to be unchanged.

Typography follow-up: the main plane places 9-pixel glyphs in 16-pixel horizontal
cells. The user finds that spacing too wide. Tighten the cell pitch together
with logical layout and circular-boundary checks, not by changing the font alone.
The menu has its own established pitch/style and should remain compatible.

### Compact main-view typography

The production ASCII plane now has x origin 90 and horizontal pitch 12, retaining
45 columns, 45 rows, 16-pixel vertical pitch and the same 9x15 font. Centered
fields keep their logical center; peripheral note labels and linear endpoints
are repositioned. The legacy test plane and OSCIO/SONORO overlay menu are unchanged.
There is no extra glyph ROM, text bank, or font-size mode. Firmware and gateware
must be deployed together because the text placement contract changed.

Eighteen display/compositor tests pass, including new normal/bold production-font
pixel tests across the entire 720-wide scanline in both coordinate transforms.
They explicitly check the 90-pixel margins and three blank columns between glyph
cells. Software layout previews using the actual normal font were visually checked;
all rendered sample text pixels fit inside the 356-pixel-radius boundary. Those
previews are layout checks, not screenshots of hardware or exact PSRAM rasterization.

Full HDMI build: logic 12,849 (+87), FF 6,369 (+10), EBR 24/56, DSP 6/28.
Final clocks pass: pixel 91.33 MHz / 74.25 required, serializer 419.29 / 371.33,
audio 70.50 / 12.29, CPU 60.12 / 60. The CPU margin is only about 0.2%; investigate
that critical path and improve margin before expanding workloads. This is a
physical timing margin, not a measurement of CPU software utilization.
Firmware 95,144 bytes. HDMI archive SHA-256:
`062acbc0e4fbc5b12d9d0b60110b4b2fdc69144309ba37146c8178bc7b61d311`.
Bitstream CRC 467253894. Visible name remains TUNER; no circular hardware rebuild.
Flashed successfully to slot 1 on 2026-09-08 under the shared lock, after checking
other tasks and active flasher processes. Saved options preserved. Hardware
confirmation of the typography update is pending.

### CPU memory/peripheral routing separation

The compact-text build's 16.63 ns CPU critical path started at the PSRAM response,
crossed the shared response selection, and ended at a CPU cache write enable.
12.51 ns was routing, versus 4.12 ns logic. It was not pitch-estimator arithmetic
or glyph drawing. A naive registered response with a paused downstream strobe
is unsafe: the current PSRAM GO state streams burst words without honoring
per-beat STB pauses. No such response pipeline was added.

TUNER now opts into `isolate_cpu_peripherals`: instruction/data cache buses
retain their arbiter and a memory-only decoder (main RAM, flash, PSRAM), while
the cacheless peripheral bus gets its own CSR decoder. Memory burst semantics
and CPU clock are unchanged. The original unified decoder map remains for SVD
and linker introspection, but only the two split decoders are elaborated in this
mode. The checked-in CPU PMA maps the actual memory regions cacheable and CSR
uncached. The option rejects raster-engine and extra-region configurations;
other bitstreams default to the original topology. It does not enable access
to the historical, absent sprite-memory window.

Nineteen bus/ownership/DMA/frame tests pass. New tests exercise simultaneous CSR
reads and 16-word memory read/write bursts to each memory region, address/CTI/
byte-select/data forwarding, error isolation, and the preserved software map.
The older frame-publication test's glyph sample was updated to use MAIN_TEXT_X,
matching the new typography origin. These simulations do not execute the black-box
CPU or prove application-level cache/interrupt behavior on hardware.

Full HDMI build: logic 12,116 (-733), FF 6,365 (-4), EBR 24/56, DSP 6/28.
Final clocks: CPU 68.28 MHz (60 required), pixel 89.37 (74.25), serializer
435.92 (371.33), audio 67.35 (12.29). CPU frequency headroom rises from about
0.2% to 13.8% in this routed build; this is not a software speedup claim or a
multi-seed qualification. Firmware remains identical: 95,144 bytes, CRC 2681226908.
Bitstream CRC 3142759542. Archive SHA-256:
`531971bbc3a6024be7e7a0f4827563cca1affcd224fc6cc226365e44fa1c617e`.
Visible name remains TUNER, non-circular 1280x720p60; circular hardware not rebuilt.
Flashed successfully to slot 1 on 2026-09-08 under the shared lock after checking
other tasks and active flasher processes. Saved options preserved. Hardware
confirmation of CPU/peripheral functionality is pending.

### Incremental runtime background drawing

The user confirmed the split-bus build works. Runtime scene preparation now
draws bounded ranges after clearing: up to 32 short border segments or four
longer guide/ruler segments per idle opportunity. No batch crosses that boundary.
The linear ruler's four-segment batches emit at most 600 pixels. Cached scene
switches are unchanged. The initial startup spiral remains the existing one-pass
draw before interrupts; this change targets runtime preparation, not boot time.

Preparation has an explicit Flush phase which repeats until the caller completes
the CPU cache flush and acknowledges it. Draw completion alone no longer marks
a scene resident. Cancelling while drawing restarts the inactive buffer's clear.
There is still one final cache-flush instruction; its worst-case hardware latency
has not been measured or made preemptible. Segment budgets bound work counts,
not a proven wall-clock deadline. More slices can increase first-view warmup time
while reducing uninterrupted foreground work; no faster scanout claim is intended.

Ten host tests pass across scene scheduling and canvas geometry, including both
display sizes, complete segment coverage for both scenes, cancellation during
drawing, explicit flush acknowledgement, and exact equality of chunked versus
whole linear-ruler pixel output. FPGA is unchanged (CRC 3142759542), retaining
the preceding resource use and timing qualification. Firmware: 96,368 bytes
(+1,224). Archive SHA-256:
`4618f7173b7c49c39710b3c3adb9ba1a8a286f35405921bc7b2782abc4f996ab`.
Non-circular HDMI TUNER only; circular hardware not rebuilt.
Flashed successfully to slot 1 on 2026-09-09 under the shared lock, after checking
other tasks and active flasher processes. Saved options preserved; hardware
confirmation of incremental preparation is pending.

### Earlier background ownership groundwork (before integration)

`background.py` adds a sync-domain `BackgroundExchange`, tested independently
from the DMA reader. CPU writes only while writable, flushes the completed back
buffer, then submits. The reader samples `next_base` and pulses `acquire` exactly
once before a new frame's first memory request, after completing old requests.
Only this event releases the old PSRAM buffer. It is an acquisition acknowledgement,
not an acknowledgement that the image is already visible on the monitor.

Four tests cover 720/1280-wide layouts, invalid overlap/alignment, stalled
acquisition, duplicate submits, and coincident submit/acquire. Storage uses byte
offsets 0 and 0x100000 (DMA word bases 0 and 0x40000); a 1280x720 frame occupies
921,600 bytes, so both buffers fit before firmware at byte offset 0x200000.
These constants must be checked against the actual allocated firmware window
when integrated; do not silently assume this layout for other bitstreams.

Current DMA code updates `scan_base` throughout the synchronized vsync level,
including while prefetch can be active. Its existing base CSR has no ownership
acknowledgement. Do not wire `acquire` to vsync directly. Integration must latch
the address once at the reader's frame-start event and preserve outstanding
Wishbone transactions. Background adoption must also coordinate with the existing
text/sprite frame transaction; otherwise scene backgrounds and labels could be
one frame apart. FIFO prefetch, delayed bus acknowledgements, cache flushes,
reset, and startup initialization need end-to-end tests before this path is enabled.

No production wiring, firmware, shared DMA implementation, or flashed image was
changed for this groundwork. The four tests are ownership-unit tests, not claims
of complete DMA/scene-transition correctness or measured resource savings.

Shared sprite component:
`sprites.py` implements `ScanlineSprites` with one synchronous bitmap ROM read
port and up to four cached rows. Four slots require eight preparation clocks
during horizontal blanking, then sustain one pixel per clock with two clocks
of pipeline latency. Each slot has position, bitmap index, enable and color;
later opaque pixels win, while holes reveal earlier slots. Preparation captures
all descriptors and rejects duplicate requests while busy. Stale rows and
blanking cannot display cached sprite pixels.

`test_tuner_sprites.py` compares one- and four-slot output with a software
reference over changing rows, clipping, invalid bitmap indices, transparent
overlap, input mutation during preparation, and consecutive pixel/sync values.
The combined display, text, frame-exchange and sprite suite passes: 21 tests
(2026-09-08). The final shift/add address change also passes all three sprite
tests independently.
This is functional simulation, not a full-design resource or timing result.
The production adapter now uses this component for its one analytical marker.
It prepares the current physical row at x=-16 in horizontal blanking, after
atomic frame publication on the preceding blank line. Both positions and atlas
samples are transformed for the rotated panel; text and marker output retain
the existing nine-clock total latency. The visualizer halo is unchanged.
The legacy bank/base CSR values are decoded without division, preserving the
firmware ABI. All 32 orientations, the 31->0 wrap, changing positions and
consecutive pixels pass reference comparisons on both display transforms.
Four-slot behavior is tested in the generic component but only one slot is
instantiated in the current tuner; four-channel acquisition and its CSR/firmware
interface are not yet implemented.
The row-wide ROM's EBR packing must be measured rather than assumed to match
the old one-bit-wide atlas.

Integrated non-circular R5 build, seed 14 (2026-09-08): 12,725/24,288 logic
cells, 6,402 registers, 22/56 EBR and 6/28 DSP. Compared with atomic publication,
this is +444 logic cells, +36 registers, unchanged EBR/DSP. Final timing passes:
pixel 92.94 MHz (required 74.25), serializer 429.74 MHz (371.33), CPU 65.19 MHz
(60), audio 68.36 MHz (12.29). This qualifies the one-slot integration, not the
eventual complete four-channel instrument. All 23 focused tests pass, including
both display transforms; only the non-circular FPGA target was rebuilt.

Archive: `gateware/build/tuner-r5/tuner-75a8c521-r5.tar.gz`, bootloader name TUNER.
SHA-256: `11943e55df2165ee051726e934fdc52ca4a315be2e808d1589998825a8e8fc26`.
The filename still identifies the base commit; this contains uncommitted work.
Flashed successfully to slot 1 under the shared flash lock on 2026-09-08;
saved options preserved. The user confirmed that this build looks fine.

### Firmware-facing text cells

The production main text plane now uses the shared normal/bold 9x15 ASCII font
at the existing 16-pixel cell pitch. Its two banks contain 16-bit cells:
bits 0..6 = printable ASCII index (character minus 32), bit 7 = bold, bits
8..15 = palette pixel (low nibble hue, high nibble intensity). The menu retains
its existing geometry, font, and packed-address encoding. The legacy 5x7 font
adapter remains only for compatibility regression tests, not production use.

`tile_write` keeps address bits 0..11; main-cell payload now occupies bits
12..27. This changes the main-text ABI: deploy matching firmware and gateware.
All writes still target the back bank and are rejected while a frame is pending.
The production CSR test publishes lower/upper-case, punctuation, bold and four
distinct colors across successive banks and verifies rendered pixels.

Firmware `ui_text.rs` provides allocation-free, bounded cell emission with
explicit style, shared dimensions, right-edge clipping and one `?` replacement
per unsupported Unicode character. It does not own instrument state or touch
hardware directly. Host tests cover every printable ASCII character, colors,
bold, clipping, and invalid coordinates. Centered numeric fields still erase
their entire old field before replacement. Menu rendering is unchanged.

Qualified R5 HDMI build, seed 14: 12,640 logic cells, 6,416 registers, 24/56 EBR,
6/28 DSP. Styled cells cost two additional EBR blocks versus the previous build;
logic decreases by 85 cells. Final clocks pass: pixel 90.30 MHz (74.25 required),
serializer 418.76 MHz (371.33), CPU 65.94 MHz (60), audio 67.10 MHz (12.29).
All 23 rendering tests and two host firmware-helper tests pass. Only HDMI was
rebuilt; this does not qualify a new circular FPGA image.

The current `gateware/build/tuner-r5/tuner-75a8c521-r5.tar.gz` replaces the prior
same-named development artifact. SHA-256:
`c72e1ae3e02b46d7ca91e180b814b84bd1c91323ab994735abe9e9fb9549032c`.
Firmware is 92,436 bytes. Visible bootloader name remains TUNER.
Flashed successfully to slot 1 on 2026-09-08 after coordination and under the
shared flash lock, preserving saved options. Hardware confirmation pending.
The user subsequently confirmed the display and save/recall work.

### Save feedback

XBEAM's `ButtonOption::value()` shows `<>` for only the action poll and one
delayed poll. The tuner's independently paced menu publication can miss that
short pulse. Tuner now retains a separate save-result message for approximately
two seconds of timer wakeups: `saved` only on `save_options` success, `failed`
on an error, and `no flash` without option storage. Showing and expiring the
message invalidate both text banks. Repeated saves restart the duration;
reset clears the old save confirmation. No persistence format or gateware
changes are needed. Host tests cover expiry, replacement, and timer saturation.

Qualified HDMI archive (2026-09-08), same TUNER filename:
SHA-256 `2eae19719278f4266609102e1a59607fdca5dbc8526c73f37d207bff0098f39d`.
Firmware is 92,804 bytes. The FPGA image CRC and all final passing timing values
are identical to the preceding text-interface build. Both feedback host tests
pass; no additional rendering gateware was changed in this update.
Flashed successfully to slot 1 under the shared lock, preserving saved options.
Hardware confirmation of the save message is pending.
The user confirmed the save feedback works.

Startup navigation update: after loading persisted options, force Page::Tuner,
selected=None, modify=false before installing the UI. Saved instrument values
and flash contents are untouched; the menu still starts hidden. A firmware-only
build reuses the unchanged qualified FPGA image (CRC 3630939042). Firmware is
92,820 bytes. Archive SHA-256:
`bedb11eb131444756832d4af85d72e6fe0de0c7f752b416e684fd5c9b64ebc83`.
Flashed successfully to slot 1 under the shared lock on 2026-09-08, preserving
saved options. Hardware confirmation of startup navigation pending.

1. Replace the tuner-specific lens atlas with a bounded sprite interface that
   can show four colored markers without duplicating four rendering engines.
   Test overlap priority, pitch-wrap continuity and worst-case transfer cost.
2. Expose the generic ASCII/color plane to firmware and centralize reusable
   text, graph, line, rectangle and scale-grid layout helpers. Keep large
   retained state out of the real-time stack.
3. Exercise complete spiral/linear tuner, calibration graph/profile editor and
   quantizer scale/octave-grid screens, not just their text. Measure update
   bandwidth, menu responsiveness, memory use and full-design timing.
4. Add startup-selectable display profiles: one logical 720x720 canvas,
   centered/unrotated on 1280x720 HDMI and rotated for the official panel.
   Framebuffer addressing, scanout, UI coordinates, boot metadata and clocks
   must agree. Do not infer panel identity solely from square resolution.

The current production integration still has separate fixed display builds.
Runtime coordinate transforms alone cannot make a fixed-timing build support
both displays. Validate the existing circular-clock legality warning and both
startup paths before enabling a unified artifact. Live hotplug is a separate
feature, not part of this first migration.

Do not expand to four expensive fundamental estimators until these renderer
costs and the complete instrument budget have been checked. A renderer resource
target is subordinate to room for calibration, quantization and detection.

### Four-channel production integration

Both spiral modes now publish all four physical input markers using the existing
four sprite slots. Slot zero follows the focused input, so the optional visualizer
emphasis remains focused while the other inputs retain precise arcs. Palette
intensity 12 preserves channel hue (intensity 15 becomes white). The channel
legend and linear readouts use the same orange/green/cyan/purple identification.

LINEAR now uses the existing four-lane cached background at logical y=224, 328,
432 and 536. Each lane has its own note/cents/frequency and Vrms/Vpp readout;
the menu remains the same shared overlay. No additional renderer, framebuffer,
font atlas or harmonic capture RAM was introduced for this milestone.

### Live calibration milestone

The same scene exchange now supports a circular, text-heavy CAL view with a
cached border-only background, patch instructions, progress and RAM-profile
summary. It uses the existing text/menu plane and hides pitch sprites. The
foreground frame is about 3.7 KiB in the compiled prologue; main RAM remains
16 KiB. Firmware is 110,256 bytes.

The first full build failed the unchanged HDMI serializer's shared synchronous
clear path (329.92 vs 371.33 MHz). TUNER now opts into recirculating the vacated
high bits during serialization instead of clearing them. All five pairs are
consumed before the next parallel load, so these bits cannot affect the current
symbol. A simulation compares the actual legacy/new DDR input pairs over 1,024
RGB/control samples. Other bitstreams retain the default legacy implementation.
No seed sweep or timing override was used.

The rebuilt seed-14 design passes final CPU 70.30/60 MHz, pixel 89.21/74.25 MHz,
serializer 439.75/371.33 MHz and audio 66.52/12.29 MHz. Resources: 17,871 logic
cells (73%), 8,877 registers, 26 EBR and 10 DSP. The added calibration controller
and ADC-window metadata therefore preserve RAM/DSP headroom. 36 detector/output
tests pass, plus the additional routed-output CSR test; 20 serializer/display/
frame tests and 11 background/instrument tests pass. The Rust live-adapter
fixture passes 15 tests (13 profile/controller plus two integration tests), and
four cached-scene host tests pass including the calibration background.

### Text-only backdrop / reference-tone removal

CAL previously required 225 clear batches plus 64 border batches on the HDMI
target, each scheduled no faster than 5 ms and further delayed by pending frame
transfers. A two-background cache also evicted this third scene. The noticeable
transition was background preparation, not pitch acquisition or calibration.

A generic `blank_background` frame field now masks only the framebuffer pixels
before sprites/text. The bit is staged by the backdrop CSR and published with
the same atomic frame payload. Firmware enters CAL without preparing/swapping a
background, and pauses background warming while there. The cached tuner pixels
remain intact. Returning restores them at a frame boundary. CAL's decorative
outer border is omitted. Expected latency is a UI update plus frame handoff,
not seconds; actual hardware perception awaits testing.

Production also disables instantiation of the reference oscillator, removes its
menu option/readout/firmware control, and hardwires non-calibration outputs to
zero. Legacy CSR addresses remain harmless for compatibility. The A4 frequency
used for note interpretation remains configurable. Persistence loads existing
options by their individual keys, ignoring the removed tone option.

22 display/frame/calibration tests and four IO/calibration tests pass. Tests
cover atomic backdrop publication, text over blank pixels, restoration of the
original background, and inability to enable a tone through old CSR writes.
Final seed-14 clocks pass: CPU 68.38/60 MHz, pixel 89.53/74.25 MHz, serializer
448.43/371.33 MHz, audio 72.31/12.29 MHz. Resources: 18,003 logic cells (74%),
8,849 registers, 25 EBR (one freed), 10 DSP. Other bitstreams are unaffected by
the production-only reference setting; the backdrop belongs to TUNER's overlay.
Archive SHA256 `56176357a9280107c6ce7d30934ac4238a703dc01862c66aa3be19bac68a4669`
flashed successfully to standard slot 1 under the shared lock (`Refresh: DONE`,
exit 0), preserving saved options. Hardware verification is pending.
