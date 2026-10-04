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

### UX phase requirements (2026-09-30)

The calibration/quantizer baseline is checkpointed. Resume interface work with
four primary pages: TUNER, CAL (calibration profile generator), SCALES (scale
generator), and ROUTES (assign input/output, profile and scale, then run; name
may change). The concept image supplies visual direction, not a requirement
for a separate PRESETS/profile page. Profiles belong in CAL and scale storage
in SCALES; saved route setups belong with ROUTES.

Replace the XBEAM/OSCIO-style global pop-up navigation with REZO-style visible
controls: turn to focus, click to edit/activate, turn to change values, click
to finish. Page navigation must be visible and selectable. Contextual pop-ups
may remain for choices such as saved scales/profiles. Move existing menu
functionality onto its owning page, trim repetitive explanatory text, and keep
status/action feedback. Reserve access/layout for Settings and Help; add full
help last before the release candidate. Preserve the oscillator setup guidance
in README.md when writing that help.

TUNER offers only ARC and LINEAR; VISUALIZER is removed. Previously saved
VISUALIZER display settings deserialize as ARC.

Legibility is a primary constraint. The user reports unreadable menus and some
page text on a small 720p monitor. Seb at apf.audio recommended font height
**greater than 15 pixels** for the circular display, according to the user.
This initial target was superseded by the user's September 30 hardware feedback
that both doubled-font trials were oversized. Use native 9x15 for the next trial
and assess it on both monitors. Confirm small-screen legibility before deciding
on a final font. Circular display qualification remains pending because the
user does not own that panel.

### Font and transition follow-up (2026-09-30)

Hardware feedback: doubled 9x15 text was oversized on the user's 1080p monitor;
CAL/tuner and ARC/LINEAR transitions had noticeable delays and stale backgrounds.
The user selected a 14x20 trial. Production now uses the exact 7x10 capital cell
of embedded-graphics 7x13 (18-pixel capital ink height) at 2x, retaining 20x32 cells and memory/field geometry.
Lowercase glyphs alias capitals; the original bold face stays within the seven-pixel box.
The compact bitmap occupies the qualified decoder's padded 9x15 glyph slots;
its visible size is 14x20. This keeps the previous pixel decoder geometry
instead of changing it for a smaller ink box. Legacy compatibility fixtures
retain their original 9x15 atlas. No new glyph
read port, smoothing or font resampling is introduced.

The previous two scanout banks also served as the complete scene cache. An idle
warmer could replace a tuner guide with CAL; requesting the tuner again then
cleared 230400 words and rasterized the border and 2112 spiral strokes in small
5 ms batches. This imposed seconds of scheduling delay even before CPU drawing
cost. Three immutable CPU-only cache slots at PSRAM +8, +9 and +10 MiB now store
ARC, LINEAR and the circle template, initialized/flushed before scanout starts.
Transitions copy 4096 words per UI tick into the unused scanout bank. CAL then
redraws only segments 2048 onward; mutable profiles/traces remain governed by the
existing revision/invalidation and per-bank live-prefix logic. Frame publication
still requires an explicit flush and acknowledged bank ownership. Pending page
changes blank the previous background so stale graphs do not persist. Publish
one holding foreground during preparation, then suppress redundant foreground
commits until ready: ordinary commits also hold the exchange busy until a video
boundary and otherwise inflate the nominal 5 ms work cadence to frame cadence.
Hidden-background panels retain normal foreground updates; suppression applies
only to TUNER/CAL transitions. It is after calibration/action polling, which keeps its normal
20 ms cadence; encoder/output interrupts and watchdog renewal continue.

At 1280x720, the copy needs 57 chunks plus flush/ready; a CAL rebuild adds 37
small graph batches. The nominal scheduling component is roughly 0.3 s for a
cold tuner copy and under 0.5 s for CAL; transfer, CPU and frame-boundary time must
be measured on hardware. A resident view can still swap without copying.
Firmware links against a generated PSRAM region bounded below +8 MiB, preventing
future executable growth from overlapping cache reservations; the flash region
and physical RAM size remain unchanged. No interrupt masking is added to copies.

Standalone scene tests cover exact copy coverage, chunk bounds, graph-only CAL
preparation, cancellation/restart and refusal to publish unfinished work. Raster
tests check compact font pixels, bank/row stride and rotated placement.
Qualified and successfully flashed #1 slot 1 under the shared flash lock;
refresh DONE, saved storage retained. Final normal build uses the already
installed native nextpnr 0.11-1-g62e659ed on the standard emitted synthesis,
with seed 18 and unchanged targets. Final clocks: sync 69.37/60 MHz,
pixel 90.34/74.25 MHz, serializer 443.85/371.33 MHz, audio 69.52/49.15 MHz.
The native router completed in 50.69 s after restoring the qualified decoder
geometry. Preliminary smaller-decoder routing attempts were superseded and
cancelled before qualification; none was deployed. The local default toolchain
configuration remains unchanged. Native invocation for this build:
`pdm run env NEXTPNR_ECP5=/Users/naenyn/dev/oss-cad-suite/bin/nextpnr-ecp5 python src/top/intono/top.py build --hw r5 --artifact-name intono-ux-stable --spread-spectrum 0.0`
(the actual launcher set the same variable after PDM loaded its environment).

Validation: 12 retained-scene/publication tests, five final compact font/raster
checks covering normal/bold and both orientations, and 36 display/frame,
renderer and calibration regression tests. Latest full firmware compilation
passes. Archive:
`gateware/build/intono-ux-stable-r5/intono-ux-compact-transitions-20260930-r5.tar.gz`
SHA256 `14f4b9cf28a346681a4ff53455efa516994393781544afb5621edae4f5946cb2`.
Flash log: `/tmp/intono-ux-stable-flash.log`; build log:
`/tmp/intono-ux-stable-build.log`. The sole flasher was DirtyJTAG
E46534A193222B21; preflash serial confirmed inactive CAL, MV=0 and a qualified
33.983 Hz input. Hardware font/readability and actual transition latency still
require user feedback; the 0.3/0.5 s figures are scheduling estimates, not measured
screen timings. Changes remain uncommitted on `codex/intono-ux`.

### First visible-controls implementation (2026-09-30)

Production text is now doubled 9x15 (18x30 pixels) on a 30-column, 22-row
logical layout with 20x32 cell pitch. TextPlane supports explicit memory row
and bank strides, preserving the 45-cell row/2048-cell bank ABI and the single
glyph ROM fetch. Existing small-text raster fixtures remain supported through
an explicit compatibility configuration; production selects large text.
Firmware does not enable the old menu panel. The visible caret and bold/color
selection identify the focused field; NAV, EDIT and PAGE states remain visible.

Header navigation follows TUNER, CAL, SCALES, ROUTES, OPTIONS, HELP. Supporting
profile/check/note/setup panels retain their parent tab and expose their existing
controls on screen. Profile/check panels remain under CAL, note editing under
SCALES, and saved route setups now under ROUTES. CAL's stored zero-note option
remains for record compatibility but is skipped by navigation and replaced by
a qualified measurement readout. Calibration and quantization still require
explicit actions. Display formatting/CSR writes stay outside playback critical
sections. Existing state/slot feedback and serial diagnostics are preserved.

The CAL graph is shorter to make space for readable routing/policy controls,
its pitch/error axis label, quality/reference summary, scan/review actions and
profile access. The conventional note editor shows all 24 A/B note cells; active
notes are bright. Presets show included conventional notes, while 24 EDO is
identified explicitly as 24 steps of 50 cents. The current editor remains tied
to an output's configuration; independently reusable named scales, graphical
keyboard controls and richer library dialogs are still pending. HELP currently
shows interaction instructions, not the planned complete help content.

The first seed-18 full build failed sync timing at 59.76 MHz versus 60 MHz on
history RAM -> NSDF DSP energy multiplication. The score engine now registers
both history operands before multiplication, preserving exact arithmetic and
adding one clock per lag. Bit-exact old/new score comparison covers both RAM
port modes; rails, zero/constant/random/sine inputs, cancellation/reuse and
frontend streaming checks pass. Do not deploy a timing-failed artifact or infer
qualification from pre-routing clock estimates. The subsequent seed-18 full
build passes all final clocks: sync 67.38/60 MHz, pixel 87.25/74.25 MHz,
serializer 436.87/371.33 MHz, audio 69.08/49.15 MHz. Resources: 19935 LUT4
(82%), 11928 DFF (49%), 45/56 EBR, 14/28 DSP. No timing override or seed sweep
was used. The latest matching firmware build passes.

Validation: 249 calibration Rust tests, five actual-option navigation/storage
tests, three round-layout tests, 47 display/renderer/control and REZO tests,
25 detector arithmetic/frontend/streaming tests, and diagnostic peripheral
tests. The latest seven calibration/control Python tests passed after the final
firmware changes. Active scan input/output/policy fields retain the ongoing
scan's values and display LOCKED when focused; graph/view navigation stays usable.

Successfully flashed #1 slot 1 under the shared flash lock; refresh DONE.
Archive: `gateware/build/intono-ux-r5/intono-ux-visible-controls-20260930-r5.tar.gz`,
SHA256 `b4ad1cd0ec6bc28b964a4ea8be766f3e92005c9805e159ebdced58f6462c90d7`.
Pre-flash serial showed calibration inactive and MV=0; the sole flasher was
DirtyJTAG E46534A193222B21. Saved options/profiles are preserved.

Font legibility, focus visibility, page selection, CAL transitions and route
processing under this continuous UI workload require physical confirmation
before expanding the interface further. The user does not have the circular
panel; its hardware qualification remains pending despite rotated raster and
layout tests. Changes remain uncommitted on `codex/intono-ux` for review.

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


### September 30: native text and direct tuner scanout

Hardware feedback found that the 14x20 trial remained oversized: capital ink
changed only from 20 to 18 pixels. Production now uses the original 9x15
normal/bold font at native scale, with 16-pixel horizontal cell pitch and the
same 30-column / 22-row logical controls. Text banks retain their 45-column
storage stride and 2048-cell offset. CAL's plot is moved to x=180, width=236
to leave room for the narrowed text matrix's axis labels.

The remaining CAL-to-TUNER and ARC/LINEAR pauses came from copying an entire
cached image into a mutable scanout bank. SceneExchange now captures an
immutable-source selector in the same transaction as foreground and background
ownership. ARC scans PSRAM+8MiB, LINEAR +9MiB directly; their initialized images
are never modified. CAL retains its two mutable banks and independent draw-bank
ownership while a static image is visible. DMA still captures the selected base
only after old-frame transactions finish; foreground still waits for the DVI
boundary. Idle warming now prepares CAL only.

Validation: 43 display, asynchronous scene exchange and stalled-DMA cases pass
(4 inapplicable legacy-exchange cases skipped), including direct scanout from
both immutable addresses and held selections under staging changes. Three
control geometry tests and 14 canvas tests pass. Production glyph checks also
cover an asserted obsolete popup flag, which must not affect visible controls.

The production UX layout also omits the obsolete popup text plane entirely;
legacy configurations retain it. Initial native-font builds encountered routing
congestion and were cancelled without flashing. Capital aliases did not change
synthesis cost, so the final font retains original lowercase glyphs.


Qualified archive:
`build/intono-ux-clean-r5/intono-ux-native-direct-20260930-r5.tar.gz`
SHA256 `09453acf809e9802202e33a6a1324dc987bfcc9a6bc12ecbec62d6d354ccaeb4`.
Native nextpnr-ecp5 0.11-1-g62e659ed, seed 18; normal strict build, R5,
1280x720p60, 192kHz audio, spread 0.0. Final clocks pass: CPU 67.20/60 MHz,
pixel 85.83/74.25 MHz, serializer 469.48/371.33 MHz, audio 68.94/49.15 MHz.
Logic 20181/24288 (83%), FF 11813/24288 (48%), EBR 44/56, DSP 14/28.
Router time 60.69s. Bitstream 514266 bytes, firmware 291816 bytes. Build log:
`/tmp/intono-ux-clean-build.log`; authoritative timing: `build/intono-ux-clean-r5/top.tim`.
Flashed successfully to #1 slot 1 under the shared lock, verified USB serial
E46534A193222B21, saved options preserved, `Refresh: DONE`. Flash log:
`/tmp/intono-ux-native-direct-flash.log`. Physical readability/transition
feedback is pending. No calibration or quantizer logic/logging was changed.


### September 30: tighter text and scale preview/editor

User confirmed native-font readability and much better view switching. Glyph
pitch is now 12px (9px bitmap width, down from 16px pitch) without changing
font size or control positions. Production has 40 visible text columns; the
firmware maps established 30-column control regions into that denser grid.
RAM stride remains 45 columns, bank stride 2048. Bounded field helpers preserve
centering, clip to 40 visible columns, and never erase unrelated text fields.

SCALES keeps output/preset/key/transpose above a two-row note grid, with mapping,
custom-note editing and ROUTES below. Included notes are bracketed as well as
colored. Preview uses the actual scale quantization math with key/transpose,
keeps the two custom cycles separate, respects single-octave pattern
normalization, and shows the additional +50-cent notes for 24 EDO. Preview is
cached until settings change. Custom NOTES explicitly edits C-based intervals,
with independent A/B grids and CLEAR/FILL labels naming the selected octave.
Focus order follows visible controls without changing persisted option indices.
Running output settings/actions that reject edits appear dim, with LOCKED
feedback. Storage formats, scale math, route activation and timing logging are
unchanged; scale editing remains linked to the selected output in this pass.

Validation: 29 pixel/frame-publication cases, 27 scale-preview/text/control
cases and 6 actual-options navigation cases pass (62 total). Software preview
checked using the
actual native glyph bitmap and 12px pitch (`/tmp/intono-scales-preview.png`).


Qualified archive:
`build/intono-ux-scales-r5/intono-ux-scales-tight-text-20260930-r5.tar.gz`
SHA256 `2f30fcab4684777a5050e25e875ebb4b7c2a25181245eef7468cd7cc76dfd038`.
Native nextpnr-ecp5 0.11-1-g62e659ed, seed 18, R5, 1280x720p60,
192kHz audio, spread 0.0. Strict final clocks pass: CPU 66.15/60 MHz,
pixel 77.20/74.25 MHz, serializer 443.85/371.33 MHz, audio 69.00/49.15 MHz.
Logic 20245/24288 (83%), FF 11823/24288 (48%), EBR 44/56, DSP 14/28.
Router time 54.31s. Bitstream 515468 bytes, final firmware 294648 bytes.
The final firmware-only package reuses this qualified bitstream after completing
label/lock feedback and rounded text-region alignment. Logs:
`/tmp/intono-ux-scales-build.log`, `/tmp/intono-ux-scales-fw-final.log`;
clock evidence: `build/intono-ux-scales-r5/top.tim`.
Flashed successfully to #1 slot 1 under the shared flash lock; verified serial
E46534A193222B21, saved storage preserved, `Refresh: DONE`. Flash log:
`/tmp/intono-ux-scales-flash.log`. Hardware layout/readability feedback pending.


### September 30: route dashboard and setup summary

User confirmed the scale UI and tighter character spacing look good. ROUTES
now groups output/input, profile/0V note, APPLY PROFILE/quantize above the
scale/key/transpose/mapping summary and applied profile name. Unapplied profile
selections show an apply-first prompt; stale curve names are not presented as
applied under a new selection. START/STOP and SCALES are grouped at row 16,
SETUPS at row 18, and the four-output running strip at row 19. Only active
routes show live voltage/pitch feedback. Routine stopped instructions are
suppressed; stopped faults and action errors remain visible. UI feedback uses
APPLY PROFILE terminology while engine status strings and diagnostic logs are
unchanged. Running-route editable settings/actions are dimmed and show LOCKED.

SETUPS shows CURRENT ROUTE SETTINGS for all four outputs, including input,
scale/key/transpose and correction source. It does not preview selected slot
contents. Slot selection stays above the summary; SAVE/LOAD are together below
it, with explicit outputs-off feedback for loading. Encoder route focus follows
the new visible order without changing stored option indices. Route activation,
profile application, storage formats, scale math and ownership guards are
unchanged.

Validation: 28 real Rust scale/text/control/feedback cases and 7 actual-options
navigation cases pass. Expanded geometry checks cover ROUTES and SETUPS at
native 12px pitch. Stopped fault/error text remains visible. Software route
preview checked (`/tmp/intono-routes-preview.png`). This is firmware only,
reusing the qualified 40-column/12px hardware image from the preceding pass.
Archive: `build/intono-ux-scales-r5/intono-ux-routes-dashboard-20260930-r5.tar.gz`
SHA256 `c8fddb6fb4e375fb727e9e622a2ba85097f2e76fdcc881e8274c3eed5b41a8a4`.
Final firmware 297536 bytes; FPGA bitstream 515468 bytes, byte-for-byte verified
against the preceding qualified scale UI archive. The same strict clock results
apply: CPU 66.15/60 MHz, pixel 77.20/74.25 MHz, serializer 443.85/371.33 MHz,
audio 69.00/49.15 MHz. Final firmware build log:
`/tmp/intono-ux-routes-fw-final.log`. Flashed successfully to #1 slot 1 under
the shared lock, verified serial E46534A193222B21, saved storage preserved,
`Refresh: DONE`. Flash log: `/tmp/intono-ux-routes-flash.log`.
Hardware route/setup-layout feedback pending.


### September 30: profile naming and check results

PROFILES now has a fixed 24-character name origin with a visible caret, separate
cursor/character editing, grouped SAVE/LOAD and CHECK/BACK, and CURRENT accepted
RAM profile details. The selected storage slot does not imply a saved-record
preview. CHECK separates profile identity/coverage/zero reference, progress,
worst signed error, maximum measurement spread and completed grade/missing count
from the action controls. No calibration, storage or verification policy changed.
Native font and 12px character pitch are unchanged. Full Help remains deferred.

The 28 scale/text/status/geometry fixture checks and seven actual-options
navigation checks pass. Geometry coverage now includes PROFILES and CHECK.
Native-font software previews were inspected for overlap and round-panel fit.
Firmware-only build succeeded; firmware 300288 bytes. Archive bitstream matches
the qualified scale image byte for byte, retaining timing passes at CPU 66.15/60,
pixel 77.20/74.25, serializer 443.85/371.33 and audio 69.00/49.15 MHz.

Archive: `build/intono-ux-scales-r5/intono-ux-profile-check-20260930-r5.tar.gz`
SHA256 `ffc2db0db820444b0cc46d491d6d41157e43c56927a5de5a02752f15cc85113d`.
Build log: `/tmp/intono-ux-profiles-fw-final.log`.
Flash log: `/tmp/intono-ux-profiles-flash.log`.
USB scan verified #1 serial `E46534A193222B21`; the shared flash lock was held
through slot-1 programming. Flash succeeded with `Refresh: DONE`; saved option
storage was preserved. Physical feedback on this pass remains pending.


### September 30: concept-guided tuner and control hierarchy

Revisited the user's original four-panel concept alongside the six current rack
photos. ARC uses a left spiral and right readout sidebar with a retained divider.
The center is (300,360), radii 40..150 across C0..C11; the full detector range
remains distinct. Both retained drawing paths and all four live markers use the
shared geometry; note labels no longer compete with focused numeric readouts.
LINEAR geometry and independent channel measurement behavior are unchanged.
Frequency stays at two displayed decimals below 10 kHz, one above it to fit.

The active primary page stays bracketed/bright/bold even while a control is
focused. Action controls are bracketed; captions consistently use uppercase.
The MIDI LEARN field was widened to retain its full label and focus marker.
CAL translates READY - RUN IN MENU to SELECT SCAN TO START for display only;
engine statuses and logging are untouched. Full Help and graphical scale keys
remain future UI work. The font remains native 9x15 with 12px character pitch.

All 47 targeted checks pass (28 scale/text/status/geometry, 12 scene preparation,
seven actual-options navigation). A native-font tuner preview was visually
inspected. Firmware-only build succeeded, firmware 300872 bytes. Bitstream is
byte-identical to the qualified scale image; all four prior timing passes hold.
Archive: `build/intono-ux-scales-r5/intono-ux-concept-tuner-20260930-r5.tar.gz`
SHA256 `9ba612da58721e4b74e61e68648ef621eb51e2e1e04111fe5782aee7f49188d2`.
Build log: `/tmp/intono-ux-visual-fw-final.log`.
Flash log: `/tmp/intono-ux-visual-flash.log`.
USB scan verified #1 serial `E46534A193222B21`; shared lock held throughout
slot-1 flash. Programming and `Refresh: DONE` succeeded; saved storage retained.
Physical assessment of the sidebar/compact spiral remains pending.


### September 30: viewport border and header alignment correction

The compact ARC pass accidentally reused SPIRAL_CENTER in draw_border. At
(300,360), the 356px viewport radius extended outside the 720px logical panel
and its left arc was clipped. Restore the fixed VIEWPORT_CENTER (360,360) for
the border; keep SPIRAL_CENTER (300,360) for spiral geometry and live markers.
Both boot-time tuner and circle-only caches now use the correct viewport edge.
The segmented calibration edge already used (360,360) and is unchanged.

The header uses four equal nine-cell slots at native columns 2,11,20,29, spanning
36 cells centered in the 40-cell plane. Native-font preview inspected; 12 scene
preparation checks pass. Firmware-only build succeeds (300864 bytes), reusing
the byte-identical qualified FPGA image and its four timing passes.
Archive: `build/intono-ux-scales-r5/intono-ux-centered-border-20260930-r5.tar.gz`
SHA256 `2f62af84b4857d993b7f2971037cd7bc4c0ffa274e585f64879d43baeaf80818`.
Build log: `/tmp/intono-ux-centering-fw-final.log`.
Flash log: `/tmp/intono-ux-centering-flash.log`.
Verified USB #1 serial `E46534A193222B21`, held the shared flash lock, and flashed
slot 1 successfully (`Refresh: DONE`). Saved storage preserved; rack feedback
on the corrected circle and alignment remains pending.


### October 1: cached scale keyboard

Standard scales (CHROMATIC, MAJOR, MINOR, MAJ PENTA, MIN PENTA) use an outlined
one-octave piano preview at x164..556/y344..479. Included natural notes are bright,
bold and bracketed; included sharps use bright labels plus asterisks. Membership
still comes from the actual quantizer scale preview after key/transpose. Custom
patterns and 24 EDO retain exact grids, preserving independent cycles and +50c
notes without implying an ordinary keyboard can represent all of them.

A new immutable keyboard image occupies PSRAM +11 MiB; the circle-only template
remains +10 MiB. Reserve caches through +12 MiB below the physical 16 MiB limit.
SceneExchange source 3 selects the keyboard, holding it with the same transaction
as its text/markers. Existing CAL banks and tuner sources are unchanged. The
keyboard is initialized and flushed before video enable; page switching uses
cached scanout without redrawing key outlines. No new drawing engine or font ROM.

The delayed-memory DMA tests now cover source 3; the asynchronous ownership test
also switches into/out of it and verifies the held source cannot be changed by
later CPU writes. Pixel/frame suite: 45 passed, six intentional uncoordinated
static-source combinations skipped. Geometry/canvas checks: 15 passed, including
chromatic key order and every label inside its key. Existing scale preview/text/
control checks: 28 passed; actual-options navigation: seven passed. Native-font
D-major preview visually inspected. Build/flash evidence follows after timing.

Full native nextpnr build (0.11-1-g62e659ed, seed 18) passed at normal R5
1280x720p60/192kHz clocks, spread spectrum 0.0: CPU 68.93/60 MHz, pixel
87.77/74.25 MHz, serializer 416.15/371.33 MHz, audio 68.72/49.15 MHz.
Routing took 48.40s. Resources: 20446/24288 logic cells (84%), 11824/24288
FF (48%), EBR 44/56, DSP 14/28. Final firmware-only packaging after label
placement changes reused this newly qualified hardware; firmware 303736 bytes,
bitstream 515115 bytes. All 95 targeted checks pass as detailed above.

Archive: `build/intono-ux-keyboard-r5/intono-ux-keyboard-preview-20261001-r5.tar.gz`
SHA256 `d14169cc54e6035a72b763cb28dc6e7184f6fd6ae4941fe68ed69c0a7c2ac296`.
Build logs: `/tmp/intono-ux-keyboard-build.log`,
`/tmp/intono-ux-keyboard-fw-final.log`; pixel log `/tmp/intono-keyboard-pixels.log`.
Flash log: `/tmp/intono-ux-keyboard-flash.log`. USB scan verified #1 serial
`E46534A193222B21`; shared lock held throughout slot-1 programming. Flash and
`Refresh: DONE` succeeded; saved profiles/settings retained. Physical keyboard
UI assessment remains pending. This qualified hardware supersedes the scale
image for subsequent firmware-only builds; do not reuse the older image with
source-3 keyboard firmware.


### October 1: atomic primitive key fills

Replace standard-scale bracket/asterisk indicators with filled rectangle interiors:
included keys are cyan (palette 0xA9), excluded naturals dim (0x39), excluded
sharps dark (0x09). Selected text uses dark ink (0x19) above the fill; note labels
are plain. Custom/24 EDO grids are unchanged. Key borders remain cached and
black-key rectangles cover the upper joins of natural keys. The retained raster tags key interiors E0..EB for C..B; the overlay converts
those tags to colors from the published mask. This avoids twelve runtime
rectangle comparisons per pixel. The four-cycle fill/color delay matches the existing sprite pipeline; text remains in front.
No framebuffer repaint and no change to overlay latency or frame ownership.

Append keyboard_mask (12 bits) and keyboard_enable to the existing BACKDROP
register at 0x1c, keeping CSR offsets and bus width unchanged. Both join the
staged frame payload; busy writes are ignored and the same publication boundary
adopts fills, labels, source and markers. Firmware returns the cached actual
scale-preview mask to stage those fields immediately before commit. Only
standard-scale piano pages enable the layer; other pages preserve their pixels.

Pixel/frame/DMA suite: 47 passed, six intentional uncoordinated static-source
combinations skipped. The strengthened two keyboard tests also pass in isolation:
all twelve keys with empty/C-only/D-major/chromatic masks, preserved outlines,
black-key priority, outside pixels, disabled overlay, blanking and text above
fill in both landscape and rotated geometry. Transaction tests verify published
mask/enable cannot be overwritten by pending CSR writes. Native-font filled-key
preview visually inspected. Full build and flash evidence follows qualification.

Full native nextpnr build (0.11-1-g62e659ed, seed 18) passed at R5
1280x720p60/192kHz, spread spectrum 0.0: CPU 66.58/60 MHz, pixel 85.62/74.25,
serializer 416.49/371.33, audio 69.42/49.15 MHz. Routing took 55.09s.
Resources: 20307/24288 logic cells (83%), FF 11883/24288 (48%), EBR 44/56,
DSP 14/28. No additional font or block memory. Firmware 303256 bytes, bitstream
515474 bytes. The rectangle-comparison trial was not flashed; only the final
cached-tag implementation below was deployed.

Archive: `build/intono-ux-tagged-keys-r5/intono-ux-filled-keyboard-20261001-r5.tar.gz`
SHA256 `3d0a067d24686f5d408accb105aa78d2ccdb669933469a66f3ad9b8b38eaa8ac`.
Build log: `/tmp/intono-ux-tagged-keys-build.log`.
Pixel log: `/tmp/intono-tagged-keys-pixels.log`.
Flash log: `/tmp/intono-ux-filled-keyboard-flash.log`.
The tagged-keys hardware is the new firmware-only baseline; older keyboard
hardware does not decode tagged interiors or the added BACKDROP fields.
USB scan verified #1 serial `E46534A193222B21`; shared lock held for slot-1
programming. Flash and `Refresh: DONE` succeeded; saved storage preserved.
Physical assessment of key-fill contrast remains pending.


### October 1: rounded controls and keyboard

Standard-scale keys now use retained rounded rectangles (radius 4) with the
existing E0..EB fill tags. Natural keys are drawn before sharps; curved corner
cutouts preserve the underlying key. Custom and 24 EDO note grids are unchanged.
Main tabs, Options/Help and page action buttons use actual scanline-rounded
outlines (radius 6, two-pixel stroke), replacing temporary text brackets.
Labels remain native 9x15 at 12-pixel character spacing.

The border layout ROM agrees with the firmware control table. Surface and focus
join the atomic BACKDROP payload without changing CSR offsets. The border
pipeline retains four-cycle alignment, behind the text layer. Curve insets are
shared per scanline and relative box coordinates are bounded to ten bits.
The first full build missed serializer timing and was not flashed. The optimized renderer passed qualification as recorded below.

Full native nextpnr build (seed 18, R5 1280x720p60/192kHz, spread spectrum
0.0) passed: serializer 393.86/371.33 MHz, pixel 83.39/74.25 MHz, audio
68.92/49.15 MHz, CPU 66.18/60 MHz. Routing took 820.21s. Resources:
21269/24288 logic cells (87%), FF 12010/24288 (49%), EBR 46/56, DSP 14/28.
Firmware 303032 bytes, bitstream 532900 bytes.

Validation: 49 pixel/frame/background/border checks passed, six intentional
static-source combinations skipped; 28 scale/control checks and 16 retained
scene/primitive checks passed. A native-font software preview was inspected.

Archive: `build/intono-ux-rounded-r5/intono-ux-rounded-controls-20261001-r5.tar.gz`
SHA256 `271bbc6efae9deeaa9016d8c074d804376bc5e1bb58497c81753ef8fb65ba055`.
Build log: `/tmp/intono-ux-rounded-build.log`; pixel log:
`/tmp/intono-rounded-pixels.log`; flash log: `/tmp/intono-ux-rounded-flash.log`.
USB scan verified #1 serial `E46534A193222B21`; shared flash lock held for
slot-1 programming. Flash and `Refresh: DONE` succeeded; saved storage preserved.
Use this rounded-controls hardware as the new firmware-only baseline. Physical
assessment of the corner style and button highlights remains pending.


### October 1: label centering and octave keyboard editor

Firmware-only refinement on the qualified rounded-controls hardware. OPTIONS
and HELP now use centered fields; odd spare half-cells round right, balancing
the nine-pixel glyph footprint within its twelve-pixel cell pitch. A geometry
test checks representative tab, footer and action labels against field centers.
The ROUTES quantization field shifts one logical column right, clearing the
profile action outline; action descriptors and gateware are unchanged.

CUSTOM NOTES now uses the retained keyboard cache for the selected A/B octave,
with that octave's raw C-based mask, note count and a warm selected-note label.
The existing OCTAVE control rotates the view; masks, saved format, key/transpose
and quantizer math are unchanged. Full two-cycle applied previews remain on
SCALES; 24 EDO retains its exact half-semitone grids. Frame publication reuses
the qualified source-3/mask atomic path; no repaint or new memory allocation.

29 scale/text/control checks and both border/layout checks passed; native-font
software preview inspected. Firmware-only build succeeded (303200 bytes), with
the same qualified 532900-byte FPGA bitstream. Archive:
`build/intono-ux-rounded-r5/intono-ux-octave-editor-20261001-r5.tar.gz`
SHA256 `1a8826edc5f82475106553fec3c1e21b8f6627633a18e5d75c9e64ec9fe9e084`.
Build log `/tmp/intono-ux-octave-build.log`; tests
`/tmp/intono-octave-ui-tests.log`, `/tmp/intono-octave-shapes.log`;
flash log `/tmp/intono-ux-octave-flash.log`. Physical feedback remains pending.
USB scan verified #1 serial `E46534A193222B21`; shared flash lock held throughout
slot-1 programming. Flash and `Refresh: DONE` succeeded; saved storage preserved.


### October 1 overnight: applied octave preview and setup summaries (not flashed)

Rack shut down by user; development/build only. SCALES CUSTOM now shows the
full retained keyboard for the selected applied cycle. Appended view_octave
option (index 8) is a UI preview only; all previous action/option indices remain
stable. Encoder focus follows the visible order and omits the view for ordinary
presets. The view remains available while running and never changes key,
transpose, pattern masks, arm state or calibration. Single-octave patterns
normalize to a repeating preview; 24 EDO retains exact half-semitone grids.
The empty-cycle test covers transposition moving both notes into the other
cycle; no octave merging is permitted. Custom's display name is now CUSTOM;
its binary enum ID remains 6.

SETUPS replaces four potentially truncated lines with two rows per current
output: I/O and scale, then profile source and key/transpose/mapping (or nominal
zero note when quantization is off). CURRENT SETUP distinguishes the view from
a flash-slot preview. Longest labels fit without truncation and stay inside the
circular boundary. Save/load action geometry and load-leaves-outputs-off
behavior are unchanged. Software previews inspected for both screens.

31 scale/text/control/layout checks, eight actual-option navigation tests and
two border/layout checks passed. Logs: /tmp/intono-night-ui-tests.log,
/tmp/intono-night-navigation.log, /tmp/intono-night-shapes.log. Firmware-only
build /tmp/intono-night-build.log passed: firmware 305648 bytes, same qualified
532900-byte bitstream (CRC 3917047491); no gateware changes in this pass.
Archive: `build/intono-ux-rounded-r5/intono-ux-night-20261001-r5.tar.gz`
SHA256 `6c620c2cfcc99eb8aeb5032b84178132f018b883b4d34b6728e2649ad48e63d3`.
Previews: night-scales-preview.png, night-setups-preview.png in that directory.
**Not flashed.** Physical testing deferred until the rack is powered again.


October 1 rack power-up: user authorized flashing to resume. Verified the
overnight archive SHA256 and manifest against night-validation.json, retained
the same qualified FPGA timing, checked for competing flash operations, and
held /tmp/tiliqua-flash.lock throughout programming. USB scan identified #1
serial E46534A193222B21 as the sole DirtyJTAG. Slot-1 flash and Refresh: DONE
succeeded; saved option/profile storage preserved. Flash log:
/tmp/intono-ux-night-flash.log. The overnight image is now the latest flashed
UI build; the preceding not-flashed note records its original overnight state.


### October 1: simultaneous stacked octaves and compact controls

User requested both octaves visible and label/value configuration pairs on
one row. Both SCALES and CUSTOM NOTES now use the same immutable source-3
keyboard cache containing two rounded 72px natural/40px sharp keyboards, at
logical y=280 and 408. Note labels retain the native font and 12px pitch.
A uses E0..EB raster tags, B uses F0..FB. Independent mask fields select each
cycle; no framebuffer repaint or extra cached image. Quarter-tone scales
retain exact note grids. The editor's octave selector is now EDIT OCT and
selects the target for existing actions/MIDI rather than hiding a cycle.

The existing BACKDROP CSR and all prior offsets remain unchanged. Append
KEYBOARD_B at 0x20; grow peripheral CSR address width from five to six bits.
Its 12-bit mask joins the same staged frame payload, with busy writes ignored.
Firmware stages both masks before commit. The extra mask is decoded before
the unchanged four-cycle tagged-fill pipeline, behind text and borders. New
firmware requires the matching stacked-octave gateware. Do not reuse the older
rounded-controls image for firmware-only builds of this version.

Short fields use bounded inline label/value text with a colon. The helper emits
nothing if the full pair cannot fit, allowing the existing two-row fallback.
Long route profile names always retain two rows. CAL policy/graph and SCALES
key/transpose move to row 6. SCALES preset/transpose have wider fields for their
longest values. MAP and VIEW captions stay short. No font changes or changes
to action IDs, storage formats, calibration or quantizer math. Retain the
retired preview option's saved key but omit it from navigation/rendering.

Validation/build/flash evidence follows qualification below.

49 pixel/frame/background/border checks passed (six intentional static-source
combinations skipped), including independent empty/full/different octave masks
in both display orientations and pending-write rejection for KEYBOARD_B.
17 retained-scene/primitive tests, 33 scale/text/control/layout checks and eight
actual-option navigation tests passed. Native-font previews inspected and saved
as stacked-scales-preview.png and stacked-notes-preview.png in the build folder.

Full normal-clock R5 1280x720p60/192kHz build passed (native nextpnr, seed 18,
spread spectrum 0.0): serializer 393.55/371.33 MHz, pixel 83.38/74.25 MHz,
audio 69.08/49.15 MHz, CPU 67.34/60 MHz. Routing took 64.26s. Resources:
20776/24288 logic (85%), 12047 FF (49%), EBR 46/56. Final firmware-only build
includes the tested inline helper: firmware 304616 bytes, bitstream 525180 bytes,
bitstream CRC 1607979219. Full build log /tmp/intono-stacked-build.log;
final firmware /tmp/intono-stacked-fw-final.log; tests /tmp/intono-stacked-pixels.log,
/tmp/intono-stacked-scene-tests.log, /tmp/intono-stacked-ui-tests.log,
/tmp/intono-stacked-navigation.log. No additional font or cache memory.

Archive: `build/intono-ux-stacked-r5/intono-ux-stacked-octaves-20261001-r5.tar.gz`
SHA256 `95e08d15dd18ed51a9c1588e24b8d1aff7b63f453e454524c05ed331acdc5b5b`.
Flash log: /tmp/intono-stacked-flash.log. Verified sole DirtyJTAG #1 serial
E46534A193222B21, shared flash lock held throughout slot-1 programming.
Flash and Refresh: DONE succeeded, saved storage preserved. This stacked image
is the latest qualified firmware-only baseline; physical feedback is pending.


## Latest UI — larger calibration plot (October 1)

Flashed to #1 slot 1 successfully; saved storage preserved. Plot now 280x204
at (180,256), up from 236x140 at (180,320), sharing the enlarged bounds across
pitch/error grids, measured traces and tracking strip. Axis labels moved to
rows 8/11/14 and sidebar to logical column 23, keeping a 32px gap. Font and
calibration/quantizer behavior unchanged. Standard scale preview caption now
OCTAVE 2 - SAME SCALE. User clarified multi-octave intent as Instruō dàil;
README documents primary manual findings and the current engine's limitations.

17 scene/primitive and 33 scale/text/layout checks passed; firmware-only build
passed against the qualified stacked FPGA (CRC 1607979219), firmware 304616
bytes. Archive build/intono-ux-stacked-r5/intono-ux-larger-cal-20261001-r5.tar.gz,
SHA256 a8bbfbb087dc5f7ed0a065d44c878930c3875b0ac035a18544983469e07ec3b8.
Flash log /tmp/intono-larger-graph-flash.log confirms Refresh: DONE. Local layout
preview /tmp/intono-larger-graph-preview.png; hardware visual assessment pending.

## Latest UI — early video and precomputed guides (October 1)

User observed 10–11 seconds with no Intono video, long enough for HDMI loss.
Startup previously disabled scanout until ARC, CAL, circle, LINEAR and keyboard
caches were prepared. Repeated software trig and whole-frame memory work were
on that critical path. Firmware now clears/flushed the initial buffer, publishes
INTONO / STARTING text, and enables video before preparing other caches. It never
modifies the visible startup buffer afterward. ARC is authored directly in its
immutable cache, eliminating the old full-screen copy from bank 0. Runtime direct
cache scanout and warm CAL/LINEAR/keyboard behavior remain intact.

build.rs precomputes circle/spiral points with explicit micromath f32 operations
and shared ui_scene constants. All 4162 coordinates match the previous software
path in a host comparison; 17 scene/primitive and 33 scale/text/layout checks pass.
Firmware-only build passed against qualified stacked FPGA CRC 1607979219.
Firmware 321480 bytes (6200 bytes remain in slot's firmware allocation).
Nonblocking CAL diagnostics now include cumulative BOOT ELAPSED_MS stages:
VIDEO, ARC, CAL, CIRCLE, LINEAR, KEYBOARD, EEPROM, READY. These measure firmware
startup only, excluding FPGA configuration/bootloader/firmware loading and monitor
lock time. Existing calibration timing reports remain enabled.

Flashed successfully to #1 slot 1, preserving saved storage. Archive:
build/intono-ux-stacked-r5/intono-ux-early-video-20261001-r5.tar.gz
SHA256 574433b1bfa606c0506246b66e99946273afb674601bd689f45232005d5ce0dc.
/tmp/intono-early-video-flash.log confirms Refresh: DONE. Module initially returned
to bootloader; asked user to launch Intono for /tmp/intono-boot-serial.log capture.
Physical timing and HDMI assessment pending. Do not claim a measured speedup yet.

## Packed immutable guides — October 1

Fixed circle/spiral coordinates now use one origin per 16 points plus two signed
byte offsets for each point. Lookup uses two table reads and integer addition,
with no trig, incremental state or full-table decompression. build.rs rejects
coordinates or offsets that cannot be represented. All 4162 recovered points
match the former micromath path. New host fixture intono_guide_fixture.rs covers
that comparison and includes 12 existing retained-scene tests (14 checks pass).
Firmware-only build passed: 314744 bytes, down 6736 from the first early-video
version; 12936 bytes remain in the slot firmware allocation. Matching stacked
FPGA and its timing qualification unchanged. Early initialized startup display
and nonblocking BOOT ELAPSED_MS diagnostics remain intact.

Archive build/intono-ux-stacked-r5/intono-ux-packed-guides-20261001-r5.tar.gz.
Flashed successfully to #1 slot 1 with saved storage preserved. SHA256 cab7720e358c3157c9fbc80af51f96132b2639397f2369f01f1f34e760ccaf1d. /tmp/intono-packed-guides-flash.log confirms Refresh: DONE. Live startup timing still pending user launch. Startup currently returns to bootloader after refresh and requires
user launch of Intono. Do not infer measured startup improvement from host tests.

## Latest UI — complete startup view and selector outlines (October 1)

User confirmed faster boot but saw button outlines before content. Production
frame reset now keeps outlines hidden with UI_READY=0. Boot publishes a reserved
surface (15), INTONO / STARTING text, outer circle and three loading dots, before
enabling video. All caches are still prepared off-screen; the first complete
runtime page commits UI_READY=1 with its text, markers, backdrop and static source.
UI_READY is bit 22 of existing BACKDROP CSR 0x1c and part of the atomic snapshot;
older offsets remain unchanged. Gate affects control borders only, preserving
loading text. No animation or busy wait was added. Matching firmware/gateware
are required. Use build/intono-ux-selectors-r5 for future firmware-only builds.

Editable compact fields now have rounded outlines matching action controls:
tuner focus/view; CAL input/output/policy/graph; scale output/preset/key/transpose/
map; note octave/note/slot; route input/output/reference/mode; saved-slot selectors
and settings. Long route profile names keep their two-row readout. Focus uses
outline color and bold text, removing the old > prefix; * still marks editing.
Keyboard headings now simply OCTAVE 1 / OCTAVE 2 for ordinary presets, A / B
for custom patterns. Fonts, musical mapping and storage IDs are unchanged.

51 pixel/frame/background/border checks pass (six intentional unsupported static
combinations skipped): initial 48 passed, then corrected layout check plus two
new loading-view rotation checks pass; the atomic-frame check was rerun. 33
scale/text/layout and eight actual-option navigation checks pass. Guide/scene
checks remain unchanged from previous qualification. Local reviewed previews:
build/intono-ux-selectors-r5/scales-preview.png and notes-preview.png.

Full normal-clock R5 seed 18 build passes: serializer 422.12/371.33 MHz, pixel
87.40/74.25, audio 65.07/49.15, CPU 66.26/60. Routing 45.65s. Bitstream CRC
3398614390, 528889 bytes. Final firmware-only build 315312 bytes. Logs:
/tmp/intono-selectors-build.log, /tmp/intono-selectors-fw-final.log,
/tmp/intono-selectors-tests.log, /tmp/intono-startup-layout-tests.log.
Archive build/intono-ux-selectors-r5/intono-ux-selectors-20261001-r5.tar.gz.
Flashed successfully to #1 slot 1, preserving saved storage. SHA256 b132a6cf21bebce083a5ef25a15d7eb7ba6b0c3b64eab55c23430dbe94913f28. /tmp/intono-selectors-flash.log confirms Refresh: DONE. Physical startup/selector feedback pending.

### Transient background streak and keyboard contrast (October 1)

A forced memory stall reproduces the display reader stretching its last bright
pixel across a horizontal gap. Coordinated Intono scanout now delays a sample-valid
flag with the pixel and substitutes palette index 0 when no background sample is
available. HDMI timing, overlay coordinates and the buffered word's remaining bytes
are preserved. This prevents stale-pixel streaks; it does not prevent starvation or
restore missing samples. The reported one-time startup line still needs hardware
confirmation, since its actual trigger has not been captured. The uncoordinated
reader used by other bitstreams is unchanged.

Selected sharp keys now use a darker cyan (0x79) than natural keys (0xA9), keeping
the piano shape legible even with the chromatic scale. Both octave masks, key
outlines and overlaid note labels retain their previous behavior.

52 display/frame/background/border checks pass, with six intentionally unsupported
static-source combinations skipped. Includes a deliberate active-scan memory gap
and independent octave masks in both display orientations. Logs:
/tmp/intono-gap-tests.log and /tmp/intono-gap-frame-tests.log.

Full normal-clock R5 seed 18 build passes all timing checks: serializer
408.16/371.33 MHz, pixel 84.54/74.25, audio 67.49/49.15, CPU 69.21/60.
Firmware remains 315312 bytes (CRC 3424959533); bitstream 525997 bytes,
CRC 4009510865. Flashed to module #1 slot 1 with saved storage preserved;
/tmp/intono-gap-flash.log confirms Refresh: DONE. Archive:
build/intono-ux-gap-r5/intono-ux-gap-20261001-streak-r5.tar.gz
SHA256 52dc768d31ce712af7773125930f26be6b7828372c3d3c720819557cdeffb235.
Build log /tmp/intono-gap-build.log; qualification metadata and reviewed layout
previews live in build/intono-ux-gap-r5. Use this qualified hardware for future
firmware-only builds. Physical retest of the occasional startup line is pending.

### Waveplane UI test and circle-only pages (October 1, in progress)

User again saw a brief horizontal blue line, including a page transition; it
appeared outside the circular UI and reached the display's right edge. The prior
missing-sample blanking did not eliminate it. Keep the physical cause unresolved.
The new candidate adds a Gray-coded 8-bit saturating gap-episode counter in scanout, crossed
to sync and exposed at TUNER_DISPLAY VIDEO_HEALTH 0x24. Existing bounded serial
reports include VIDEO BUFFER_GAPS. Counting begins after the first available
background pixel, excluding the initially empty startup reader; it saturates at
255 episodes and is exposed as a 16-bit register field. No forced stalls/resets
are introduced on hardware.

Routes/settings/help and other text-only views now select immutable source 4,
the existing circle-only cache at PSRAM +0xA00000. FRAME.background_source expands
from 2 to 3 bits in the existing register (no other field/CSR offset changes).
CAL buffer ownership is unchanged. Production no longer hides the whole raster
for text-only pages. CAL progress now shows signed output voltage and collected
points, and WAITING FOR TONE when the sweep has no qualified sample yet. This is
read-only presentation; acquisition deadlines and safety behavior are unchanged.

User requested debug attachment during an apparent negative-voltage scan hang.
Attached read-only serial /dev/cu.usbmodem83102; it advanced normally once audible
pitch was detected. Final AUTO review: GRID/LOCAL DISAGREE; 56 points, 1.166750 to
5.750000 V, E0 -31.7c to D#5 -32.0c. CHARACTER grade, worst 8.493c, stability
7.338c; ACCEPTABLE=true is the broad review threshold, NOT the 2c target.
Acquisition 219096 ms, checks 200633 ms, total 419729 ms; 85 measured points
39943 ms and 88 missing waits 179126 ms. Three upper-region recoveries; no profile
accepted/saved by the agent. Serial archive:
build/intono-ux-gap-r5/waveplane-auto-20261001-serial.log.
BOOT timings measured in same log: VIDEO107, ARC712, CAL857, CIRCLE973, LINEAR1564,
KEYBOARD1887, EEPROM1913, READY2200 ms (cumulative firmware time).

54 display/frame/background/border tests pass, eight unsupported static-source
combinations skipped, including new circle-source acquisition and gap counter.
Log /tmp/intono-circle-tests.log. Full build intono-ux-circle-r5 is in progress;
not yet flashed. Preserve the user's pending on-module review result.

## Latest UI — common circle, voltage axis and scan feedback (October 1)

Qualified and flashed to #1 slot 1, preserving saved storage. The finished Waveplane
review was captured before flash; its unsaved RAM candidate was cleared by refresh.
Text-only pages (routes/settings/help/saved lists) select source 4, the existing
circle-only cache; FRAME source width is 3 bits, all CSR offsets unchanged. X-axis
labels now show low, midpoint and high voltage at their corresponding positions.
CAL footer shows signed output voltage and collected points during acquisition;
WAITING FOR TONE distinguishes absent qualified evidence. On-screen GRID/LOCAL
DISAGREE becomes CHECKS DISAGREE; the original serial reason and engine decisions
remain unchanged. For this scan the grid's worst error was -8.493c and later same-CV
local mean -3.80c, a ~4.7c mismatch above the AUTO 3c consistency threshold.

An 8-bit saturating Gray-coded scanout gap counter crosses safely to sync and
appears as a 16-bit VIDEO_HEALTH read at 0x24, plus VIDEO BUFFER_GAPS in existing
bounded status reports. It starts after the first available background sample and
saturates at 255; it excludes the initially empty reader. The line's physical
cause remains unresolved: user still saw it after the previous missing-sample
blanking, outside or crossing the circle toward the right display edge. Use the
new diagnostic evidence before changing scanout recovery or arbitration.

54 display/frame/background/border checks pass (8 unsupported combinations
skipped). After simplifying the counter, all 13 DMA cases pass again (8 skipped),
including deliberate starvation and counter observation. Firmware compilation
checks the new axis/status paths. Logs /tmp/intono-circle-tests.log and
/tmp/intono-circle-gap-tests.log. The first 16-bit-counter route was abandoned
for congestion; it was not qualified or flashed. Revised normal-clock R5 seed 18
build passes: serializer427.17/371.33 MHz, pixel89.02/74.25, audio66.82/49.15,
CPU67.29/60. Firmware317240 bytes CRC2318122058; bitstream530017 bytes CRC478174243.
Build /tmp/intono-circle-build-final.log; flash /tmp/intono-circle-flash.log confirms
Refresh: DONE. Archive build/intono-ux-circle-r5/intono-ux-circle-20261001-circle-r5.tar.gz.
SHA256 c08f5b83e741d622df6c3ada75e2da992df43ac4fcc3d0d79fd7e2222f30c1a3. Use intono-ux-circle-r5 for future firmware-only builds.
Serial scan archive build/intono-ux-circle-r5/waveplane-auto-prior-image-20261001-serial.log.

### Intermittent colored-line diagnostics (October 1)

The user still sees a blue flash at load and red/green flashes crossing the
circle on Scales entry. BUFFER_GAPS remained zero. No matching full-width
composition failure has been reproduced. A new sticky BACKGROUND_ERRORS flag
observes unexpected retained-image colors or nonzero pixels in the 720-panel
margins before overlays. Allowed raw colors/tags match BackgroundCanvas. The
flag never masks or changes a pixel and crosses to sync with FFSynchronizer.
VIDEO_HEALTH 0x24 now has gaps8 and background_errors8; the latter is 0/1 until
DVI reset. Update the instrument-specific whitelist when adding retained colors.
A zero flag does not exclude incorrect samples that match allowed colors and
locations, or later overlay/palette/serializer/monitor faults. See CHECKPOINT
for qualification and the successfully flashed archive. The first counter-based
build was abandoned for routing congestion; it was never flashed. Latest build
uses a smaller sticky flag, passes all clocks and 37 display tests. Physical
cause still requires evidence from a reported event.

### First-visit output diagnostic (October 1)

Hardware reports both previous checks zero during first-visit blue and red/green
flashes. Actual DMA tests now exercise first and repeat immutable/mutable page
transitions at the production 60/74.25MHz clock ratio and two memory latencies;
no pixel/metadata mismatch reproduces. The output diagnostic extends the same
8-bit BACKGROUND_ERRORS field: bit0 retains the raw-background check, bit1
latches any nonzero final overlay pixel outside the logical 720-square.
The existing panel-valid predicate is delayed through the complete nine-clock
overlay latency, avoiding duplicate wide coordinate comparisons. No clipping or output masking is added. A deliberately misplaced text
plane with a zero incoming image tests output-only evidence (value2). Incoming
nonzero margin data triggers both checks (value3). Bits persist until reset.
Zero does not exclude downstream palette, TMDS, physical link or monitor faults.
Full display/frame/border/DMA suite: 53 passed, eight unsupported combinations
skipped (/tmp/intono-outputdiag-tests.log). Simplified image qualified at all four clocks and flashed #1 slot1; see CHECKPOINT for archive/hash/logs. Physical cause is still unresolved.

### Separate colored streaks: palette review (October 1)

Blue again appeared on initial Tuner without paging; separate red and green
streaks near upper keyboard on quantization. Raw and completed-overlay flags
remain zero in /tmp/intono-outputdiag-live-20261001.log. No cause reproduced.
An explicit clocked palette alternative passed simulation but synthesis review
showed the old palette already merges RGB registers into block RAM read ports.
The experiment was withdrawn and its unqualified build stopped, never flashed.
Existing palette path now has all256-color/CPU update/one-pixel timing coverage,
and first/repeat DMA page-transition tests check palette RGB and timing on every
pixel at60/74.25MHz with two memory latency cases. Keep outputdiag-r5 as the
latest flashed hardware; no renderer change is being presented as a streak fix.

### Concept-guided keyboard and route polish (October 1)

Selected natural keys use a bright32px upper cap and subdued body; selected
accidentals bright, excluded keys dim. Fill decoding stays four-cycle aligned
and clipped by the same retained E/F tags; no new mutable framebuffer drawing.
Firmware changes label ink for selected naturals vs accidentals. Shapes/notes
remain two simultaneous, independently masked octaves, same native font/pitch.

Routes profile selector becomes inline with its own rounded outline, width11;
profile action width11 and Mode col16 width10 maintain separation. Editing
prefix removed: focus outline and EDIT footer remain. Four independently colored
output states replace the single compressed status string. Active pitch and
separate IN/OUT voltage columns aid performance feedback. Scale page footer
shows running target pitch. Branding cyan/bold. R5 qualification
passed all clocks; flashed #1 slot1 with storage preserved. See CHECKPOINT for
archive/hash and /tmp/intono-keypolish-build.log. Physical appearance awaits user
test; this does not claim to fix the intermittent colored streaks.

### Solid keyboard fills and octave counts (October 1)

User rejected the cap/body shading after hardware testing: natural keys appeared
half accidental. Restored solid selected naturals A9 and accidentals79, excluded
naturals39 and accidentals09. Selected labels use dark19 ink, excluded labelsD9;
yellow focused labels remain. No additional fill boundary within a natural key.
Mask/tag pipeline, key outlines, and two independent octaves remain unchanged.
Display tests exercise top/body agreement, occlusion, text, independent masks,
and both rotations. Scale overview now shows note count beside each octave
heading, matching the custom-note editor. Earlier route layout, live pitch,
inline controls, and branding improvements remain. Rendering diagnostics stay
in place; this is not a claimed fix for intermittent horizontal flashes.

Qualified and flashed normal R5 1280x720 image to #1 slot1 with saved storage
preserved. See CHECKPOINT for solidkeys archive, hash, timing, and test logs.

### Direct keyboard navigation (October 1)

Custom-note editing enters the keyboard at A/C. Encoder ticks visit the 24 keys
in chromatic order across A and B, then the octave tools, Clear/Fill, Save/Load,
and MIDI Learn controls. Reverse traversal returns through the keys to Slot and
the parent-page header. Focused key lettering is yellow only while keyboard
focus is active; other key fills remain solid and membership-controlled.
Separate Note and Toggle fields/outlines are hidden. Their stored option keys
remain stable: toggle index2 represents keyboard focus, while the existing
octave/note values identify its key. Octave tools target stays selectable for
Clear/Fill/MIDI Learn; those controls sit below the second keyboard.

Clicks on the keyboard are consumed immediately after encoder polling, before
future ticks can move focus during foreground frame preparation. This bounded
interrupt action changes one mask bit and feedback; running-channel lock checks
remain in force. No storage format or quantization semantics change.

Directkeys passed native navigation/scale tests and display/shape checks, then
normal R5 hardware timing. Flashed #1 slot1 with saved storage preserved;
CHECKPOINT records archive/hash and logs.

### Main Scales keyboards are editable (October 1)

Correction to directkeys: user intended the main Scales page, not just the
separate Notes editor. Root/Key index2 now has no visible field or border on
Scales; that index represents keyboard focus there. Navigation order is Output,
Preset, Transpose, all24 keys, Mapping, Scale Tools, Routes. Focused key lettering
is yellow. Generic root-edit click is consumed immediately as a keyboard action
and exits modify state before another tick. Running-channel lock still applies.

Clicking a piano key bakes the old preset/root into custom masks and toggles the
corresponding untransposed degree; root resets to C and transpose is preserved.
Tests compare before/after displayed memberships for every key, root, and
transpose value. Preset becomes Custom. Legacy root storage remains readable,
but no root selector is displayed. Quarter-tone 24 EDO grids are unchanged and
do not silently convert to twelve-note patterns; piano edit is unavailable for
that preset. Scale Tools retains the existing slot/save/load/MIDI controls.

Mainkeys passed38 native and38 display checks, normal R5 timing, and flashed
#1 slot1 with saved storage preserved. CHECKPOINT records qualification/logs.

### Route-owned musical offsets (October 1)

Routes adds Scale, Key, and Transpose selectors at appended option indices9..11.
Existing option indices/keys and TQS2 setup format are preserved. Route selector
changes commit to the selected channel; channel switches and setup recall refresh
both route and scale controls. Running-channel edits remain locked.

Scales no longer displays transpose; keyboards and direct key edits operate at
root0/transpose0 as interval definitions. Editing or choosing a scale preserves
the channel's key and transpose. Existing scale root/transpose fields are mirrored
for legacy selected-route option persistence, not edited from this page. Notes
slots remain interval masks. Saved setups already persist separate per-route
root/transpose, so the same preset can serve D and A routes independently.
Profile application retunes only the measured0V reference, preserving musical
key/transpose. Feedback now says PROFILE APPLIED - 0V NOTE SET. Expanded menu
snapshot to12 entries and border geometry/navigation to include new controls.

Routekey passed42 native and38 display tests, all final normal R5 timing,
and flashed #1 slot1 with saved storage preserved. CHECKPOINT records qualification.

## Octave viewport (October 1, revised to manual paging)

OCTAVES defaults to1 and supports8 independent masks. VIEW selects the first
visible octave of an adjacent pair. Key navigation visits only the visible
keys, then moves to the surrounding controls; it never changes VIEW. Both
Scales and Scale Tools use the same bounded traversal. The native text plane
includes columns0..42 (storage stride45), rendering the right-side VIEW control.

Two cached keyboard layouts are immutable: source3 at PSRAM0xB00000 has two
rows, and source5 at0xC00000 has a single centered row. The latter moves keys,
note labels and octave caption down64pixels (two native text rows). Firmware
chooses the source with the atomic text/mask/frame commit; no drawing is needed
when switching layouts. Cache reservation now ends at0xD00000. The centered
cache copies the circle template and draws only its own E-tagged keys, so there
is no hidden lower keyboard or conditional pixel erasure. keyboard_second is
retained as a compatible staging field but no longer masks the raster. Static
source5 participates in the same frame ownership/scanout tests as other caches.
Scale previews remain cached; no new per-frame geometry or trigonometry.

MIDI Learn Base uses any fresh Note On to choose its octave without toggling
a degree. Later MIDI edits reveal and focus the corresponding pattern key.
This explicit MIDI follow behavior does not change encoder VIEW paging. The
Learn Base / Stop MIDI action shares row 16 with Tools Oct; the base appears above the
keyboard instructions. It is an editing reference retained until reboot.

### Calibration state and stack budget (October 2)

The CPU has 32 KiB SRAM for static data and stack combined. Successful linking
alone does not validate the deepest calibration call stack. Calibration's
7,048-byte retained Live state now lives in a foreground-only NOLOAD section at
PSRAM +5 MiB. A separate non-inlined initializer releases its construction
temporary before operation. The current main-loop frame falls from 16,384 to
9,328 bytes. The firmware linker reserves at least 24 KiB SRAM for stack and
rejects executable/data overlap with runtime storage or runtime overlap with
framebuffer caches at +8 MiB. Inspect compiled frames when growing UI/operation
state; static-data guards do not account for nested calls or interrupt frames.

### Pixel-centered controls (2026-10-04)

The UX text plane now uses 18-bit cells. Glyph, bold, and color remain bits
0..15; bits 16..17 select offsets 0, 2, or 8 pixels (codes 0, 1, 2).
The existing TileWrite CSR carries these at bits 28..29, leaving addresses
and earlier registers unchanged. Centered firmware fields use floor cell
padding plus the pixel offset; blank cells always use zero offset.

A second character read handles the five pixels that can carry from an
8-pixel-offset glyph into the next cell, with a guard against row/bank wrap.
Both reads use the same acknowledged front bank. Offset and bank selection
are registered before the font ROM, preserving timing: the native compositor
is six clocks and the production overlay ten. Non-offset planes retain the
five-clock compositor. No CPU framebuffer or occupancy allocation was added;
the additional read uses four FPGA BRAM blocks (51/56 total).

The qualified baseline is `build/intono-ui-text-center-pipe-r5`, hardware
`67179044`, final firmware `8e8a807b`. Do not pair this firmware with earlier
16-bit text hardware or the failed unpipelined text-center build. See the
checkpoint for archive hash, final clock results, and verified flash.
