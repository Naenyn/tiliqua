# TUNER pause checkpoint — September 13, 2026


## Single-input / multiple-output route groups (October 2)

ROUTE now selects a logical group, OUTPUT selects the per-output editor, and
ADD OUT / REMOVE OUT manages exclusive membership. Four groups each have one
input and a four-bit output mask; stopped groups may be empty. Per-output
profiles/scales/keys remain independent. START/STOP operates on the group;
claim conflicts and arm failures leave no partially active group. A member fault
stops the other members and releases the group's claim in the next UI service.
Running-group input/membership are locked; stopped outputs may transfer between
groups. Independent groups no longer share claimed inputs. Free/assigned jack
pickers preserve passive tuner observation.

TQS4 setup records are 116 bytes; old TQS1–3 records migrate fan-out by input.
Shared checked App borrowing and glyph rendering reduce duplicate code, giving
about 20 KiB firmware headroom while preserving the slot limit and stack guard.
SRAM static end is 6664 bytes, leaving 26104 bytes for stack; inspected run
closure frame is 9376 bytes (48 bytes above prior review), main remains 1216.
No calibration algorithm/timing-log changes. Group controls add only compact
layout/options; eight-octave pattern storage remains unchanged.

Tests: 51 scale/UI/setup, 19 options/navigation, 251 calibration/live fixtures,
6 ownership checks, and 24 hardware/layout simulations pass. Hardware fan-out,
concurrent calibration exclusions, setup recall and stack watermark still need
rack validation after flashing. Build/flash evidence is appended below.

Full seed-19 R5 build and flash completed: `intono-ux-groups-20261002-r5.tar.gz`.
Firmware 307536/327680 bytes (20144 remain); all four timing domains pass:
395.73/371.33 MHz serializer, 89.45/74.25 pixel, 67.59/49.15 audio,
65.84/60 CPU. Tiliqua #1 serial E46534A193222B21, slot 1, Refresh DONE.
Evidence: `groups-validation.json`, `groups-firmware.elf` in the build folder.
Rack functional/stack-watermark validation is pending user launch/testing.

## Free / assigned jack selectors (October 2)

Historical checkpoint; grouped route work above supersedes its future-work notes.

Calibration input/output and route input editing now skip jacks claimed by
other operations, in both encoder directions, with a bounded four-choice
search. A focused jack selector displays FREE / ASSIGNED and four jack choices;
assigned numbers and unavailable selector values are dimmed. Active operations
keep their jacks locked; calibration SCAN text is dimmed if either selected jack
is assigned, and claim() still prevents a conflicting start. No automatic
repatching or stopping. No-free selections remain unchanged and unavailable.

Route/output configuration navigation is labeled ROUTE rather than OUTPUT;
it remains accessible to stop running operations. Tuner FOCUS is passive and
continues observing every input. User clarified the intended grouped route model:
one input, one or more outputs, never multiple inputs. Existing backend CV
fan-out remains supported by claim(), while the input picker excludes assigned
sources for new selections. Explicit grouped route/multiple-output editing is
still future UI work; current route editor remains per-output.

5 ownership, 48 scale/UI, and 251 calibration/scale/watermark checks passed.
Deduplicated availability/rendering and removed obsolete unrendered pitch text;
firmware fits the unchanged slot limit: 327632/327680 bytes (48 bytes remain).
The next UI expansion requires code-size reduction before adding features.
No new static reservation table or buffer was introduced. All four seed-19
timing checks pass; flashed Tiliqua #1 slot 1. Retained archive
intono-ux-jacks-20261002-r5.tar.gz, jacks-validation.json and jacks-firmware.elf.
Hardware free/assigned feedback and selector skipping remain for the user to test.


## Saved scales on Routes (October 2)

Replace the redundant lower SCALES page shortcut with LOAD SCALE. SAVED (1–8)
selects the record to recall directly into the selected route. Keep the existing
preset/custom selector for factory intervals and edited notes; loaded records
become a CUSTOM snapshot. Preserve route input, output, profile, zero reference,
key, transpose, mapping and output state. Never start automatically. Failed or
empty reads leave the previous scale intact. Flash recall still requires all
outputs stopped. Reuse the old scales action index; append saved slot index 12.
Menu snapshot already supports 13 controls. Widened/adjacent controls pass the
round-display layout and exact hardware/firmware geometry tests.

48 scale/UI and 24 Python geometry/import/four-route checks passed. Firmware
325344/327680 bytes. All four seed-19 timing checks passed; flashed Tiliqua #1
slot 1. Archive intono-ux-route-scale-20261002-r5.tar.gz, qualification
route-scale-validation.json, and matching route-scale-firmware.elf retained.
Successful route recalls also synchronize the editor slot and load feedback.
251 calibration/scale/watermark regression checks passed. Hardware saved-slot
recall remains for the user to verify.


## Direct scale save/load controls (October 2)

SCALES now exposes SLOT (1–8), SAVE, and LOAD below the keyboards. The tools
page retains compatible shortcuts and shares the same selected slot. Saving
captures the displayed preset intervals or custom masks and the 1–8 octave
span, excluding the route key and transpose. Loading selects CUSTOM, restores
the octave span, and resets the view to the first octave. Empty-slot and flash
feedback appears directly on SCALES. Output playback must be stopped for flash
access. Quarter-tone 24 EDO cannot be encoded in the piano-note slot format and
is explicitly rejected instead of approximated. Existing saved records and
option indices remain compatible; new options are appended.

Removed the obsolete lower ROUTES outline from hardware geometry as well.
Menu snapshots now include all 13 scale controls. Tests: 48 scale/UI, 251
calibration/scale/watermark, and 24 Python geometry/import/four-route checks.
Firmware 324552/327680 bytes; static SRAM 6600 bytes, leaving 26168 bytes for
stack (linker minimum remains 24 KiB). All four seed-19 timing checks passed; flashed Tiliqua #1 slot 1. Archive
intono-ux-scale-save-20261002-r5.tar.gz, qualification scale-save-validation.json,
and matching scale-save-firmware.elf retained in the build directory. Hardware
save/edit/load verification remains for the user.

## Scales duplicate navigation cleanup (October 2)

Remove lower ROUTES action from Scales control geometry and keyboard focus order;
keep top ROUTES tab. Stored option indices remain unchanged. ScaleUI46tests pass;
firmware322568/327680,qualifiedseed19clockchecksPASS. Archiveintono-ux-scales-
nav-20261002-r5.tar.gz;qualification scales-nav-validation.json.

## Compact scale RAM and stack watermark (October 2, flashed)

User chose to keep1–8octaves,default1. See RAM_REVIEW.md for ownership/layout
review and remaining checks. Pattern now stores96u8 semitone indices instead
of96i32 pitches; imported/microtonal scales keep exacti32 tables. No record
format changes or quantization approximations. MULTI_QUANT6388→5236bytes,
static SRAM7716→6552including heartbeat removal; stackregion26216bytes.
Run closure remains9328bytes. Main frame1216bytes; constructor7072+new304.

Watermark painted before startup/interrupt registration; STACK UNUSED_BYTES
reports estimated untouched margin through existing bounded capture. Remove
only temporary ISR stage heartbeat, retain original calibration timing logs.
251calibration/scale/watermark +46scaleUI +22import/four-route checks pass.
Memory-budget assertions pass without threshold increases.

Firmware322560/327680;5120headroom. Qualified seed19timingallPASS; flashed
#1slot1 normal1280x720,RefreshDONE. Savedarchiveintono-ux-ram-review-20261002-
r5.tar.gz;matchingram-review-firmware.elf;ram-review-validation.json.
Read-only capture session31882 writes/tmp/intono-ram-review-live.log and appends
prior sharedcapturelog. User ran AUTO without first trying scales. AUTO completed:
63profilepoints,46/46verified,REVIEW - USABLE GRADED RESULT,CHARACTERgrade.
Acquisition171679ms,checks174807ms. Lowest reported stackunused7120bytes;
VIDEO BUFFER_GAPS0 BACKGROUND_ERRORS0 throughout. Scaleeditor/MIDI/profile
save-load/multi-output hardware margin checks remain pending.

## Memory audit and comparison (October 2)

Stack-fix retry completed: ACTIVE=false,63points,45/45verified,REVIEW -
GRID/LOCAL DISAGREE. Acquisition158859ms,checks190488ms. No freeze or fatal
report in capture. User-visible confirmation remains separate. This supports
stack pressure; no measured stack high-water mark or exact overwrite address
yet proves root cause or identifies the specific triggering UI edit.

Local cached release ELF comparison (not freshly rebuilt identical revisions):
OSCIO16KiB SRAM,8static bytes,main5616 + loop3536bytes; SONORO16KiB,
32static,main5120 + loop3024; CASCADO16KiB,32static,main4960 + loop3328.
Intono32KiB,7716static,main1200 + run80 + loop16384before/9328after.
These are retained compiled frames, not total stack peaks. REZO-family local
ELFs use separate2KiB data/stack region and main frames1056–1184bytes; much
smaller control firmware, not a comparable calibration workload.

Intono static MULTI_QUANT alone6388bytes,APP1216bytes. Eight-octave Pattern
grew degrees[i32;24] to[i32;96]:+288bytes per engine,+1152acrossfour, plus
compiler temporaries. Playback memory-budget fixture failures are real budget
growth signals, not automatically obsolete assertions. Compact conventional
note representation should be considered before changing thresholds.

PSRAM Live state7048bytes,loop frame savings7056. Compiled initializer frame
7072bytes plus Live::new304bytes, released before scan; interrupts are enabled
during initialization, so interrupt stack must still be included. Foreground
exclusive state is CPU-only; no DMA cache-coherency requirement for this object.
Link section NOLOAD deliberately gets initialized via storage.write; bootloader
does not need to initialize it. Explicit address bounds protect firmware/data
load and framebuffer caches. SRAM remains used for shared playback ISR state.

Current guard reserves24KiB of stack space, but does not establish worst-case
call-chain usage. Future work: target stack watermark/low-water measurement,
compiled call-path budget including interrupts, compact pattern state, and
restore all memory-budget checks with justified budgets. Firmware slot headroom
is independently only4368bytes; firmware size/timing PASS do not verify RAM.

## Calibration state / stack margin fix candidate (October 2, flashed)

User confirms LED follows CAL control focus; not proof of output routing change.
On heartbeat build user reports screen/encoder completely frozen. Capture ends
at idle NOW20380,laststageD; reconnect did not yield further bytes. No PANIC/TRAP.
Cannot infer exact foreground location solely from this incomplete capture.

Compiled stack inspection found only25,052bytes between .data/.bss end0x1e24
and SRAM stacktop0x8000. Perpetual run closure frame16,384bytes; main1,200,
run80; nested tick_automatic2,448 + tick_sweep3,248 + poll208 before other
helpers/interrupt frame. Stack pressure is a strong candidate, not confirmed.

Moved7,048byte Live state into explicit foreground-only NOLOAD section at
PSRAM0x20500000; isolated constructor in inline-never init_calibration_state.
Main-loop frame falls from16,384 to9,328bytes. Link asserts firmware/data load
ends before runtime storage, runtime ends before caches0x20800000. Single
initialization/caller; interrupts never access this state. Initializer stack
released before scanning. Calibration algorithm unchanged; heartbeat retained
until physical verification. Matching symbols scan-stack-firmware.elf.

Firmware323312/327680,4,368bytes headroom. Flashed #1slot1,R5 normal1280x720,
qualified seed19hardware allPASS,Refresh DONE. Archive intono-ux-scan-stack-
20261002-r5.tar.gz; qualification scan-stack-validation.json.

Retry capture now advances through the negative-voltage search, collects107
measurements, and proceeds into sampled-pitch checks and region recovery.
At NOW285574ms foreground publication age62ms; timer heartbeat continues;
VIDEO BUFFER_GAPS=0 BACKGROUND_ERRORS=0. Supports stack-pressure diagnosis,
but user screen confirmation and complete scan result remain pending.
Current read-only capture session15736 appends to
/tmp/intono-scan-fault-live-20261002.log. Do not flash during this active scan.

Added link-time static-data guard reserving at least24KiB between _ebss and
stacktop. Firmware-only build passes; guard is not yet flashed (no runtime
behavior change). Still inspect compiled nested stack use after future changes.

## Foreground-stage heartbeat diagnostic (October 2, flashed)

Routing diagnostic initial scan: CMD0044b1e0 = OUT0,-5V,enable,token2;
hardware ACK00000102 = active,token2. At now20293ms foreground publication
age35ms,frame0,PREPfalse,READYfalse. User reported frozen. No subsequent normal
serial reports arrived while watching. A previous run internally advanced
through +7.916V; this alone does not prove the newer reproduction is UI-only.

Added temporary nonblocking one-byte timer heartbeat every2000interrupts.
Stage map A loop-clock,B renewoutput,C NSDF,D capture,E UI snapshot,F MIDI/
persistence,G plotrevision,H backgroundwork,I scanstart,J measurements,K cal
state machine,L postcal/publication,M controls,N commitcomplete. Timer UART
writes check ready once; no waiting/allocation. Probe output may interleave
normal reports. Remove probe after root cause is found. Root cause pending.

Firmware324224/327680,3456bytes headroom. Slot1 R5 normal1280x720,qualified
seed19hardware PASS,Refresh DONE. Archive intono-ux-scan-stage-20261002-r5.tar.gz,
qualification scan-stage-validation.json,matching scan-stage-firmware.elf.
Host calibration fixture:247passed,2failed. Failures are older small
memory-budget assertions in playback.rs:669/673 after eight-octave masks enlarged
Scale/QuantEngine. No calibration behavior regression failed. Log
/tmp/intono-calibration-regressions.log. Do not report full suite passed.

Read-only capture active execsession49566, same /tmp/intono-scan-fault-live.py
and appendedlog. User asked to launch/reproduce and leave frozen for capture.

## Scan routing / display diagnostic (October 2, flashed)

Serial was not permanently silent: the reproduced scan advanced internally
from -5 V through +7.916 V over 76 s while the user reported a frozen screen.
IN0 detected Waveplane ~34 Hz before scanning. No fatal PANIC/TRAP recorded.
User clarified moving the cable from physical OUT0 to physical OUT1, with
OUTPUT: 0 still selected, advanced one point and then lit the second output.
This is not a menu numbering misunderstanding. Root cause remains unconfirmed.

Added bounded status report fields: SCAN IO CMD/ACK/NOW and VIDEO FRAME/AGE/
PREP/READY. No calibration algorithm change. Firmware323840/327680,3840bytes
headroom. Flashed slot1 R5 normal1280x720 with qualified seed19hardware, all
clocks PASS, Refresh DONE. Archive intono-ux-scan-io-20261002-r5.tar.gz,
qualification scan-io-validation.json in build/intono-ux-midibase-r5.
Read-only capture /tmp/intono-scan-fault-live.py appends the existing log;
active execsession73304. Reproduction requested with OUTPUT0 / physical OUT0.
Current idle reports show frame commits continue (publication age35ms), correct
34 Hz IN0 detection and zero calibration command/ACK. Await first scan report.

## Immediate scan freeze / direct fatal diagnostics (October 2, flashed)

User photo shows CAL IN0/OUT0 AUTO, initial -5.00V,0PTS. User confirms starting
scan freezes immediately; long-press reboot still works, first physical output
LED solid red (software OUT0). This does not establish wrong I/O. Existing
read-only serial captures are empty even with established DTRtrue/RTSfalse.
Found panic/exception handlers relied on synchronous logger intentionally not
installed at startup. Replaced fatal reporting only with direct bounded UART:
PANIC reports file + line (8 hex digits); TRAP reports PC,CAUSE,VALUE,RA (hex).
Writer waits at most12000 polls/byte and returns on backpressure; no runtime
logging changes. Root cause still unconfirmed; reproduction requested.

Flashed diagnostic #1 slot1 R5 normal1280x720, firmware322752/327680,4928bytes
headroom. Includes SEARCHING FOR TONE wording. Firmware-only build reuses fully
qualified seed19hardware, all four clocks PASS; expectedserial/lock/manifest/size
checks and Refresh DONE. Archive `intono-ux-scan-fault-20261002-r5.tar.gz`; SHA `3fe9fadf7091b0e19f088ed4f28a0febb217a16fd8dd2f7a2d7af8773e7a8a36`.
Qualification `gateware/build/intono-ux-midibase-r5/scan-fault-validation.json`;
matching symbols `scan-fault-firmware.elf` in that builddirectory.
Logs `/tmp/intono-scan-fault-{build,flash}.log` and live
`/tmp/intono-scan-fault-live-20261002.log`, captured by
`/tmp/intono-scan-fault-live.py` for600s; active execsession34856.
User asked to launch/retry AUTO after flash. No profiles accepted or saved.


## Searching for tone wording / silent live scan diagnostics (October 1)

User suspects a stalled calibration or wrong I/O. Attached read-only to debug
adapter E46534A193222B21, /dev/cu.usbmodem83102 at115200. Initially DTR false
produced no data; reopened using established DTR true/RTS false capture config.
Still no serial bytes. No resets, output commands, or flashes issued during
investigation. Asked user for CAL input/output, voltage, point count, oscillator,
and whether encoder still responds. Those observations are pending.
Capture `/tmp/intono-scan-live-20261001.log`; reader `/tmp/intono-scan-live.py`
uses bounded180s capture; port identity verified with serial.tools.list_ports.
Source now shows SEARCHING FOR TONE. Firmware-only build succeeded at326928bytes,
using existing verifiedhardware; not flashed to preserve running scan evidence.
Prepared archive `intono-ux-search-tone-20261001-r5.tar.gz`, qualification
`gateware/build/intono-ux-midibase-r5/search-tone-validation.json` flashedfalse.
Build log `/tmp/intono-search-tone-build.log`. Last flashed image remains monitor.


## Output monitor and tuner feedback (October 1, flashed)

User tested MIDI Learn Base successfully. Next UX pass removes the duplicate
scale/key/transpose summary from Routes, using row10 OUTPUT MONITOR, row11
applied profile, row12 output pitch/stopped, row13 live IN/OUT voltages. Route
title row4 is QUANTIZER. Existing route selectors/status/actions are retained.
ARC tuner displays NO SIGNAL and shows green/bold cents within ±2 cents.
Removed obsolete centered cents/frequency/level strings computed then discarded
before ARC rendering; LINEAR readouts are rendered independently and unchanged.
No calibration logs or engine thresholds changed. Help content still deferred.

Firmware-only build reuses the fully verified seed19 hardware image (geometry
unchanged). Firmware326928/327680,752bytes headroom. Flashed #1 slot1 R5 normal
1280x720, same serial/lock/size/manifest checks, Refresh DONE.
Archive `intono-ux-monitor-20261001-r5.tar.gz`, SHA256 `4ebe739d091730dde0ad9e039fb2626bc4b75c2bbd7d766e7f601f91b31a921a`.
Qualification `gateware/build/intono-ux-midibase-r5/monitor-validation.json`.
45 native scale/UI/codec tests passed; diff whitespace clean. Logs
`/tmp/intono-monitor-{build,fixture,flash}.log`. Visual review is pending user.


## MIDI Learn Base (October 1, flashed)

Implemented any-note octave learning on SCALE TOOLS. LEARN BASE (existing
MIDI action index 5) arms editing and becomes STOP MIDI. First fresh Note On
sets base = MIDI note // 12 * 12, without editing any mask. Later fresh presses
map into independent relative octaves; notes outside the configured span are
ignored. Held repeats do not toggle; Note Off and velocity-zero On release.
Edited MIDI notes reveal their octave and focus the corresponding piano key.
Encoder navigation remains confined to explicit VIEW; route key/transpose and
oscillator zero reference are unaffected. Leaving Tools or STOP MIDI disarms.
Base defaults to 48, is retained until relearn/reboot, and is not persisted.
Save retains note edits. Tools Oct now only targets Clear/Fill. Learn Base and
Tools Oct share row16; MIDI base caption is row6.

Built and flashed Tiliqua #1 slot1, R5 1280x720 normal, seed19. Final firmware
327448 / 327680 bytes (**232 bytes headroom**). Reuse i32 formatting for the
base octave: introducing i16 formatting exceeded the limit. Selected UI and
persistence routines remain out of line to reduce duplication; no calibration
logging was removed. Next feature work will need further size reductions.
Archive: `intono-ux-midibase-20261001-r5.tar.gz`; SHA256 `f4da97f662e10b19a38b3383518392b01a4ad438b21095867d4cd43256e77d11`.
Qualification: `gateware/build/intono-ux-midibase-r5/midibase-validation.json`.
All four final timing checks PASS (427.17/371.33,85.39/74.25,70.93/49.15,
67.08/60 MHz). Flash lock, single matching DirtyJTAG serial E46534A193222B21,
manifest/size checks succeeded; refresh DONE. User launches Intono manually.

Validation: 4 MIDI state tests, 45 native scale/UI/codec tests, 11 actual options
navigation tests, 18 canvas tests; 46 display/background/frame/shape tests,
plus 2 final geometry tests after moving the action. Diff whitespace clean.
Logs `/tmp/intono-midibase-{build,final-fw,flash,tests,shapes,navigation,fixture,canvas}.log`.
Hardware MIDI workflow still requires user testing. Intermittent colored line
flashes remain unresolved from earlier work; this change does not address them.

## Manual octave pages and centered single keyboard (October 1, flashed)

User rejected automatic key-driven viewport scrolling. Keyboard traversal now
stays within VIEW's visible pair (or12keys for span1), then exits to surrounding
controls. VIEW changes only by explicitly editing it; re-entering the keyboard
starts at that page's first/last key according to traversal direction. Reducing
span clamps VIEW, preserving the earlier hidden-mask storage behavior. Both
Scales and Scale Tools use this traversal. Musical/quantizer engine unchanged.

Single-octave keyboard is centered64pixels lower within the two-row keyboard
area. Native note labels and octave caption move two rows with it. A separate
immutable raster atPSRAM0xC00000 (source5) copies the circle and draws only its
own keyboard; cache reservation now ends0xD00000. Source3 still draws two rows.
Single-page pixel erasure was removed so centered key bottoms are intact.
Source5 is selected atomically with text/masks. Existing keyboard_second CSR
field stays compatible but no longer masks pixels. Geometry offset lives in
ui_canvas::SINGLE_KEYBOARD_Y_OFFSET. No per-frame redraw or trig was introduced.

45 native UI/scale/storage tests,10 encoder/options tests,18 canvas tests and
63 display/background/DMA/frame/shape tests passed (10 intentionally skipped
unsupported static-source/uncoordinated combinations). Diff check clean.
Routing seed18 was slow; final qualified bitstream uses seed19. All final
clocks PASS:427.17/371.33 serializer,85.39/74.25 pixel,70.93/49.15 audio,
67.08/60CPU MHz. Normal R5 1280x720, spread0. Final firmware326408bytes,
1272bytes slot headroom. Archive intono-ux-pager-20261001-r5.tar.gz under
build/intono-ux-pager-r5. Qualification pager-validation.json confirms flashed.
SHA256: 117ea718bd16a737b16cf0922a29f6f7f43adb567e404c2b7b35def661340310.
Flashed Tiliqua#1 slot1 using expected DirtyJTAG serialE46534A193222B21 with
exclusive /tmp/tiliqua-flash.lock. /tmp/intono-pager-flash.log Refresh:DONE.
Logs /tmp/intono-pager-{build,route19,final-fw,fixture,navigation,canvas,tests}.log.
User needs to launch Intono and assess the physical UI. Transient colored
streak diagnosis remains unresolved; this change does not claim to fix it.

## Configurable octave span and keyboard viewport (October 1, flashed)

User approved keeping two readable keyboards with a side viewport control.
Implemented OCTAVES1..8 default1, independently stored per selected output.
One octave shows only the upper keyboard. VIEW browses adjacent pairs, and
turning through keys auto-scrolls without changing pattern membership. Entering
key focus from VIEW uses the displayed pair. Reducing span clamps cursor/view
but keeps hidden masks so expanding restores edits. Notes/Scale Tools has the
same controls; Tools Oct targets Clear/Fill/MIDI, numbered1..8. Conventional
presets become copied interval masks when entering Scale Tools or toggling a
key. Musical key/transpose remain route-owned. Quarter-tone piano editing is
still unsupported; absolute MIDI octave learning is still future work.

Pattern capacity96degrees/8octaves; compile_span uses explicit period and
preserves empty octaves. Nearest/equal mapping uses the whole interval pattern,
repeating after the selected span. TNP2(25bytes) and TQS3(108bytes) store all8
masks plus span, with TNP1/TQS1/TQS2 backward decode preserving former empty-half
normalization. Slot keys remain unchanged. Existing calibration/logging stays.
Native UI text canvas43columns, stride45, to render the right-side VIEW control.
Atomic backdrop keyboard_second suppresses the full lower retained keyboard
rectangle with delayed logical coordinates, preserving overlay/text alignment.

45 native scale/UI/codec tests,10 actual options/navigation tests,59 display/
frame/geometry/scale tests plus25 final targeted tests passed. Diff clean.
Normal R5 1280x720, seed18; final clocks PASS:460.62/371.33 serializer,
85.81/74.25 pixel,67.58/49.15 audio,68.27/60CPU MHz. Final firmware326256bytes
(CRC2341787434),1424bytes slot headroom. Bitstream524156(CRC4060981245).
Archive build/intono-ux-octaves-r5/intono-ux-octaves-20261001-r5.tar.gz,
SHA25666b97fce1c9dc572b0ee6d639e337d325855322d15382f7b0063db532dd34568.
Flashed Tiliqua#1 slot1 via expected DirtyJTAG E46534A193222B21 and exclusive
/tmp/tiliqua-flash.lock; /tmp/intono-octaves-flash.log Refresh:DONE.
Qualification build/intono-ux-octaves-r5/octaves-validation.json flashedtrue.
Tests/build logs /tmp/intono-octaves-{fixture,navigation,tests,final-tests,
build,final-fw}.log. User still needs to launch Intono and verify physical UI.
Prior transient colored streak diagnosis remains unresolved; do not claim fixed.

## Route-owned key and transpose (October 1, flashed)

User agreed scales are interval definitions; musical key is chosen per route.
Routes now exposes Scale, Key, and Transpose (new appended option indices9..11).
Selected output owns independent offsets. Scales displays and edits root0/shift0
intervals; it no longer displays transpose and edits preserve route key/shift.
Legacy editor offset fields stay mirrored for saved selected-route settings;
startup recalls them as fallback for older options. Existing TQS2 setups already
persist per-route offsets, no format migration. Notes slots remain interval masks.
Profile application now calls Channel::retune: only measured0V note changes,
never musical key. Feedback PROFILE APPLIED - 0V NOTE SET. Running locks include
new selectors; switching outputs/setup recall refreshes both sets of controls.
Expanded MenuSnapshot12 entries and geometry/navigation for route selectors.

42 native tests passed, including D/A Major pitch differences, interval edits
preserving keys, profile retuning preserving key/shift, setup roundtrip and longest
labels. Display/frame/border suite38 passed. Qualified normal R5 1280x720 seed18:
serializer416.49/371.33, pixel82.79/74.25, audio67.77/49.15, CPU67.60/60 MHz,
all PASS. FW320168 bytes CRC2845553573; bitstream528007 bytes CRC4115256474.
Flashed #1 slot1, saved storage preserved; Refresh: DONE in
/tmp/intono-routekey-flash.log. Latest matching build build/intono-ux-routekey-r5,
archive intono-ux-routekey-20261001-r5.tar.gz, SHA256
099164f86ae9cea7758edd3e744a4a6e992bcaf2f5fa57a20b12ff8e86833667.
Build /tmp/intono-routekey-build.log; tests /tmp/intono-routekey-ui-fixture.log
and /tmp/intono-routekey-tests.log; routekey-validation.json records qualification.
User launches from bootloader. Colored flashes still unresolved, diagnostics kept.
Changes uncommitted on codex/intono-ux, generated Vexii source preserved.

## Main Scales keyboard correction (October 1, flashed)

User clarified direct key editing belongs on the MAIN Scales page; prior
implementation only affected the Notes child. Removed visible Key/root field
and border there. Scales order now Output, Preset, Transpose, all24 keyboard
keys, Mapping, Scale Tools, Routes. Key focus uses hidden index2; yellow key
label and CLICK KEY TO TOGGLE footer identify the action. Click is consumed
immediately in encoder ISR, restores modify=false, and respects running-channel
lock. Preset becomes Custom on edit. Old root baked into custom masks; transpose
preserved, toggled degree corresponds to displayed key. Legacy root option remains
for saved setup compatibility but is not a visible control. 24 EDO quarter-tone
grid is retained, no silent twelve-note conversion. Scale Tools exposes existing
note slot/save/load/MIDI/clear/fill facilities. Parent Notes editor remains usable.

Fixture38 passed, including main-page forward/reverse traversal and displayed
key toggle checks across all roots/transposes; display/frame/border suite38
passed. Qualified normal R5 1280x720 seed18, all timing PASS: serializer434.97/
371.33, pixel82.01/74.25, audio68.35/49.15, CPU65.45/60 MHz. FW319360 bytes
CRC2374873786; bitstream529114 bytes CRC3507042698. Flashed #1 slot1,
saved storage preserved; Refresh: DONE in /tmp/intono-mainkeys-flash.log.
Latest matching build build/intono-ux-mainkeys-r5, archive
intono-ux-mainkeys-20261001-r5.tar.gz, SHA256
bf3cb097c2930cb4ae9530525d577642f6c3bbfd95a4b69e3c2504c1bdfe654a.
Build /tmp/intono-mainkeys-build.log; tests /tmp/intono-mainkeys-fixture.log
and /tmp/intono-mainkeys-tests.log; mainkeys-validation.json records qualification.
User launches from bootloader to test. Colored flashes unresolved, diagnostics
retained. No commit requested; working tree stays uncommitted.

## Direct keyboard editing (October 1, flashed)

User requested selecting/toggling the actual keys instead of Note and Toggle
controls. Notes editor enters at A/C, visits 24 keys in chromatic order across
A and B, click toggles focused key immediately (no edit mode). Reverse rotation
returns to Slot and parent header; forward rotation continues to octave tools,
Clear/Fill, Save/Load, and MIDI Learn. Focus lettering yellow only on keyboard.
Note/Toggle controls hidden, stored option indices unchanged. Tools Oct selector
allows Clear/Fill/MIDI Learn to target either octave after keyboard traversal.
Tools row16, Clear/Fill row17, Save/Load/Learn row18; feedback row19. Solid fills
and other prior UX improvements retained. Running-channel lock applies to clicks.
Click consumes the existing one-shot in encoder ISR before later ticks can change
focus; bounded mask/feedback update only. Quantization/storage semantics unchanged.

Native fixture36 passed, including forward/reverse full-key traversal and controls;
display/frame/border suite38 passed, final updated shape agreement2 passed.
Qualified normal R5 1280x720 seed18: serializer434.97/371.33, pixel82.01/74.25,
audio68.35/49.15, CPU65.45/60 MHz, all PASS. FW318232 bytes CRC4021146580,
bitstream529114 bytes CRC2312789563. Flashed #1 slot1, saved storage preserved;
Refresh: DONE in /tmp/intono-directkeys-flash.log. Latest matching build
build/intono-ux-directkeys-r5, archive intono-ux-directkeys-20261001-r5.tar.gz,
SHA256 c09035d38abdcd75e9e7197095a049389472bc6c236562390429dd3fc12b2088.
Build /tmp/intono-directkeys-build.log; tests /tmp/intono-directkeys-fixture.log,
/tmp/intono-directkeys-tests.log and /tmp/intono-directkeys-shapes-final.log.
directkeys-validation.json records qualification. User launches from bootloader.
Intermittent colored streaks remain unresolved, diagnostics retained.

## Solid keyboard fills and octave counts (October 1, flashed)

User tested keypolish and approved other enhancements but rejected split natural
key shading. Restored solid selected naturals A9 / accidentals79 and excluded
naturals39 / accidentals09; selected labels dark19, excluded labelsD9, focus
labels yellow. Kept prior route layout, live pitch, inline controls, branding,
and diagnostic trace. Scale overview octave headings now include each keyboard's
note count, consistent with custom-note editor; masks/quantization/storage
unchanged. No claim to fix the intermittent colored horizontal flashes.

Native scale/navigation fixture34 passed; display/frame/border suite38 passed,
including solid top/body agreement, masks/text/occlusion and both rotations.
R5 1280x720 normal clocks seed18, all final timing PASS: serializer416.49/371.33,
pixel82.79/74.25, audio67.77/49.15, CPU67.60/60 MHz. FW317808 bytes
CRC2038677513, bitstream528007 bytes CRC2702195070. Flashed #1 slot1,
storage preserved; Refresh: DONE in /tmp/intono-solidkeys-flash.log.
Latest artifact build/intono-ux-solidkeys-r5, archive
intono-ux-solidkeys-20261001-r5.tar.gz, SHA256
44ef2d3c20b318f192119f3b58763a9fb44d4ca1886212603ef0681c564c346f.
Build /tmp/intono-solidkeys-build.log; tests /tmp/intono-solidkeys-tests.log
and /tmp/intono-solidkeys-fixture.log; solidkeys-validation.json records manifest
and timing. User launches from bootloader for appearance test.

## Concept-guided keyboard and route polish (October 1, flashed)

User authorized resuming UI/UX enhancements while colored-streak cause remains
unresolved. Diagnostic flags and trace logging remain in place. Keyboard naturals
now have a bright selected32px cap and darker body, selected accidentals bright,
excluded keys dim. Natural labels use light ink on dark bodies; accidental
labels keep dark ink on selected bright fills. Two simultaneous octaves stay
independent; 24-degree quantization/storage behavior unchanged.

Routes profile selector fits one row, including PROFILE: SLOT 8, gets a matching
rounded outline. Profile action width11 and Mode col16/width10 provide a gap
between neighbors. Removed decorative edit-prefix asterisk; existing focus
outline and EDIT footer convey state. Four output RUN/OFF readouts have distinct
columns and channel hues when active, bold for selected output. Active route
pitch emphasized; input/output voltages align in separate columns. Scale view
shows selected output live pitch while running, editor label when stopped.
Header INTONO now cyan/bold like the concept. Native font size/pitch unchanged.
Native fixture34 passed; full display/frame/border suite38 passed. Final
keyboard cap/body checks passed in both rotations. Qualified R5 1280x720 image,
normal clocks seed18: serializer436.87/371.33, pixel87.68/74.25,
audio69.33/49.15, CPU68.03/60 MHz, all PASS. FW317720 bytes CRC509043080,
bitstream528825 bytes CRC3969115396. Flashed #1 slot1, saved storage preserved;
Refresh: DONE in /tmp/intono-keypolish-flash.log.
Archive intono-ux-keypolish-20261001-r5.tar.gz, SHA256
3e359c9e3c1469150cd5e52ddd794b2993a9dc94cdab2e5517347c6bf778fe98.
Use build/intono-ux-keypolish-r5 for matching firmware-only changes.
Build /tmp/intono-keypolish-build.log; tests /tmp/intono-keypolish-tests.log,
/tmp/intono-keypolish-keyboard-final.log and /tmp/intono-ux-route-fixture.log.
Existing debugger remains attached in /tmp/intono-outputdiag-live-20261001.log.
Physical UI appearance awaits user test; colored streak cause remains unresolved.

## Separate red/green lines — palette review (October 1)

User saw blue on initial Tuner without paging, and separate red and green lines
extending right near the top of the upper keyboard when entering quantization.
Output diagnostic capture /tmp/intono-outputdiag-live-20261001.log still reports
BUFFER_GAPS=0 BACKGROUND_ERRORS=0. This excludes detected raw palette/margin and
final overlay margin violations, not every interior wrong pixel or downstream
RGB/serializer/link fault. Asked whether lines reach the physical right edge;
answer pending. Do not call the keyboard geometry a confirmed cause.

Reviewed color stage and tried an explicit DVI-clocked block-RAM palette read.
Both old and experimental paths passed all256 colors before/after CPU updates,
one-pixel timing alignment and actual DMA first/repeat transitions. Synthesis
revealed the OLD palette already merges its RGB output registers into clocked
DP16KD read ports (outputdiag top.rpt lines17712-17714 and17783-17785).
Therefore a missing palette register was not established. Experiment build
/tmp/intono-clockedpalette-build.log stopped before qualification, never flashed;
its palette/SoC/top changes withdrawn. No new hardware flash this turn. Keep
intono-ux-outputdiag-r5 as the latest qualified/flashed image. Added palette and
end-to-end DMA RGB/timing tests for the existing path; final test log
/tmp/intono-palette-review-tests-final.log. Hardware cause still unresolved.

## First-visit flashes — output diagnostic (October 1, flashed)

User reports blue streak on first Tuner -> CAL, then red/green on CAL ->
quantization, settling until reboot. Live capture
/tmp/intono-flashdiag-live-20261001.log records BUFFER_GAPS=0 and
BACKGROUND_ERRORS=0 through these observations. Startup COUNT=121 is the planned
scan count, not evidence of a loaded oscillator profile. Default empty CAL plot
revision is already zero; do not add a redundant revision-initialization fix.

Added actual DMA/FIFO first and repeat page-visit tests at 60MHz CPU / 74.25MHz
pixel clocks, with two memory-latency cases, distinct source bytes and per-pixel
metadata assertions. Both pass. This does not reproduce the hardware artifact.

Candidate output diagnostic keeps the existing VIDEO_HEALTH layout and serial
format. BACKGROUND_ERRORS is now a bitmask: bit0 unexpected incoming palette or
margin pixel, bit1 nonzero final overlay pixel outside the 720x720 UI panel.
Both flags are sticky until reset; 3 means both checks observed an error.
Output is unchanged. Injected misplaced text plane checks bit1 independently
with an entirely clean incoming background. Palette/serializer/monitor faults
remain outside the coverage. Qualified simplified build and flashed #1 slot1, saved storage preserved.
All final clocks PASS: serializer416.49/371.33, pixel82.79/74.25,
audio67.77/49.15, CPU67.60/60 MHz. Full suite53 passed, eight skipped;
three diagnostic injection checks passed again after simplification.
Initial duplicate-coordinate-comparison candidate stopped for routing congestion;
it was never flashed. Final design delays the existing panel-valid predicate by
nine pixel clocks instead. Final build /tmp/intono-outputdiag-build-final.log,
tests /tmp/intono-outputdiag-tests.log and
/tmp/intono-outputdiag-injection-final.log. Refresh: DONE in
/tmp/intono-outputdiag-flash.log. Archive intono-ux-outputdiag-20261001-r5.tar.gz,
SHA256 2a8a603164424ed4305066c992539a07c4744f5c4f60476f238fb56e36b7f2ef.
FW317016 bytes CRC3980772549; bitstream528007 bytes CRC2271977079.
Use build/intono-ux-outputdiag-r5 for subsequent firmware-only builds.
Physical cause remains unresolved; this is diagnostic coverage, not a claimed fix.

## Intermittent colored line — diagnostic follow-up (October 1)

User still sees a blue line at initial load, and red/green streaks crossing the
outer circle while entering Scales. The axis-image serial capture reports
BUFFER_GAPS=0 throughout the observed session. No FIFO starvation evidence;
this does not establish a physical cause. Do not call the prior blanking fix a
confirmed remedy. Cached-image ownership, sprite bounds and text/border validity
were reviewed without finding a matching full-width drawing error.

New diagnostic observes raw retained pixels before overlays, without changing
visible output. It latches evidence of colors outside the canvas palette or
nonzero pixels outside the logical 720x720 panel. Allowed pixels include cyan
hue 9, zero, white loading dots FF, cream traces DB, red/yellow tracking D0/D2,
and keyboard tags E0..EB/F0..FB. This is an instrument-specific palette contract,
not a general renderer restriction; update it if retained drawing gains colors.
Evidence is a sticky single-bit flag, synchronized into an 8-bit field,
reported as BACKGROUND_ERRORS
alongside BUFFER_GAPS. VIDEO_HEALTH at 0x24 now divides its low 16 bits into gaps8
and background_errors8; matching firmware/gateware required. A nonzero result
would implicate incoming background data/geometry. Zero cannot rule out a bad
sample that happens to match a legal color and location, nor a later overlay,
palette, serialization or monitor fault. There is no diagnostic masking.
The new simulation injects bad colors and margin pixels, ignores blanking,
checks output preservation and persistence until reset. The first counter-based
build was stopped for routing congestion and was not flashed.
Qualified normal-clock R5 image passes all timing checks: serializer410.00/371.33,
pixel86.71/74.25, audio67.31/49.15, CPU65.46/60 MHz. All 37 display/frame/border
checks pass; both sticky-flag injection cases pass. Firmware 317016 bytes,
CRC 3980772549; bitstream 527158 bytes, CRC 2358114563.
Flashed to #1 slot 1 with saved storage preserved; /tmp/intono-flashdiag-flash.log
confirms Refresh: DONE. Matching archive: intono-ux-flashdiag-20261001-r5.tar.gz.
SHA256 ee7c8616e1bf2033811ffbabb3fd171eb5db261cf85a06e50295972403eeffbf.
Use intono-ux-flashdiag-r5 for future firmware-only builds; VIDEO_HEALTH field
layout differs from circle-r5. Build log /tmp/intono-flashdiag-build-final.log;
tests /tmp/intono-flashdiag-tests-final.log. Debugger reattached, capture
/tmp/intono-flashdiag-live-20261001.log. Physical cause remains unconfirmed;
this image adds evidence, not a claimed fix.

## Latest UI — centered voltage ticks and clearer results (October 1)

X-axis labels are centered under the low, midpoint and high ticks, with native
12px text-grid rounding. End labels now extend equally to either side of the
plot edges. Compact label/value selectors use the same centered alignment as
buttons. Calibration review spells out WORST and SPREAD instead of W/S, retaining
the measured values and grade. Musical processing, calibration decisions and
saved formats are unchanged. The native UI/scale fixture passes all 33 checks.
Firmware-only build uses the matching qualified intono-ux-circle-r5 gateware;
flash completed successfully to #1 slot 1 with saved storage preserved.
Archive: intono-ux-circle-20261001-axis-r5.tar.gz, firmware 316992 bytes,
CRC 3096737726. Matching bitstream unchanged (CRC 478174243), all qualified
clocks still pass. SHA256: 199d538b62429c501522bb4752bbbeb8fab2d7f1b4d67c466a3399014a2fe693.
Logs: /tmp/intono-axis-build.log and /tmp/intono-axis-flash.log (Refresh: DONE).

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

## Latest UI — transient pixel gap handling and piano contrast (October 1)

User confirmed the complete loading view and reported a brief blue horizontal
line after boot. A forced scanout-memory gap demonstrates a matching stale-pixel
streak failure mode. Coordinated scanout now blanks unavailable background pixels
while keeping the timing and overlay alignment. This does not prevent memory
starvation; physical confirmation of the reported line's cause is still pending.
Selected sharp keys now use darker cyan than natural keys, retaining clear piano
geometry even for chromatic scales. 52 display/frame/background/border tests pass,
with six unsupported static-source combinations skipped. No musical engine,
calibration, storage or firmware changes in this step.

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


## Latest UI — simultaneous octaves and compact fields (October 1)

User requested simultaneous smaller keyboards instead of the preview toggle,
and inline label/value configuration. Implemented and flashed successfully to
#1 slot 1, preserving saved storage. Both SCALES and CUSTOM NOTES show two
stacked keyboards with independent masks; EDIT OCT selects which octave the
existing editing/MIDI actions target. Standard scales repeat in the second
keyboard; custom cycles remain distinct, including an empty cycle after
transposition. 24 EDO keeps exact grids. Short controls now use one row,
including input/output, policy/graph, key/transpose, map, tuner focus/view and
slot selectors; long values fall back to two rows and profile names keep two.
Font size/spacing unchanged. Preview toggle's stored key remains but it is hidden.

New KEYBOARD_B CSR 0x20 stages the second 12-bit mask atomically; prior offsets
unchanged. New firmware requires the matching stacked gateware. Use
build/intono-ux-stacked-r5 for future firmware-only builds, not the older rounded
image. Full normal-clock FPGA build passed; 49 pixel/frame/background checks,
17 scene/primitive, 33 scale/text/layout and eight navigation checks passed
(six intentional pixel-suite skips). Final firmware 304616 bytes. Archive:
build/intono-ux-stacked-r5/intono-ux-stacked-octaves-20261001-r5.tar.gz
SHA256 95e08d15dd18ed51a9c1588e24b8d1aff7b63f453e454524c05ed331acdc5b5b.
Flash log /tmp/intono-stacked-flash.log confirms Refresh: DONE. Physical feedback
pending; see RENDERER.md for qualification and saved preview paths. Calibration,
quantizer behavior, diagnostics and profile/scale storage formats are unchanged.


## Overnight UI work — October 1 (flashed after rack power-up)

The user powered the rack back up and authorized flashing to resume. The
overnight archive below is now flashed to #1 slot 1, preserving saved storage.
USB serial E46534A193222B21 verified; Refresh: DONE. Flash evidence:
/tmp/intono-ux-night-flash.log. Physical assessment is pending.

The flashed development is ready for morning testing:
- SCALES now uses the full keyboard for CUSTOM patterns. VIEW OCTAVE switches
  between the two applied cycles after key/transpose; repeating patterns show
  REPEATING. This is a read-only view, available while an output runs.
- 24 EDO keeps its exact semitone/half-semitone grids.
- SETUPS now gives each current output two readable rows; CURRENT SETUP makes
  clear these are current settings, not a preview of the selected flash slot.
- Display name CUSTOM replaces CUSTOM 2; persisted enum IDs are unchanged.
- Existing action indices remain stable; view_octave is appended at index 8.

31 scale/text/layout checks, eight actual-option navigation tests, and two
border/layout checks pass. Firmware-only build passed using the already
qualified rounded-controls FPGA (same bitstream CRC 3917047491). Firmware
305648 bytes. Archive: build/intono-ux-rounded-r5/intono-ux-night-20261001-r5.tar.gz
SHA256 6c620c2cfcc99eb8aeb5032b84178132f018b883b4d34b6728e2649ad48e63d3.
Local previews and night-validation.json are saved in that build directory.

Morning checks: switch a custom pattern's A/B preview; change key/transpose and
verify each cycle stays distinct; inspect a single-octave repeating pattern;
confirm view changes work while running without changing output; inspect all
four setup summaries including C# -12 / NEAREST and slot 8. Calibration math,
quantizer behavior, profile/scale storage formats and diagnostics are unchanged.


**Latest UX update, October 1:** calibration baseline commits `1ae3a683` and
`21db3864` were fast-forward merged into local `naenyn`; UX work remains on
`codex/intono-ux`, uncommitted. User confirmed native 9x15 text looks good and
direct tuner scanout greatly improves performance. The latest pass tightens
character pitch from 16 to 12px while preserving control positions, improves
SCALES previews (key/transpose, separate custom cycles, 24 EDO) and reorganizes
the custom-note editor with visible focus order and running-output lock feedback.
The subsequent route pass reorganizes ROUTES around applied-profile details,
scale summary, live feedback and explicit START/STOP. SETUPS shows the current
four-route settings; running-route edits are visibly locked. Route focus follows
visible order. All 35 targeted route/text/navigation checks pass, and the final
firmware-only archive reuses the preceding timing-qualified hardware image.
See [RENDERER.md](RENDERER.md) for archive/hash/timing evidence. Flashed
successfully to #1 slot 1 with saved storage preserved; the user approved the route pass.
The next pass gives PROFILES a fixed name cursor and accepted-profile summary,
and CHECK a coverage/progress/error/results layout. All 35 targeted checks pass;
firmware is 300288 bytes using the unchanged qualified FPGA image. Flash evidence
is recorded in RENDERER.md. The following concept-guided pass moves ARC readouts
into a right sidebar, compacts and aligns the spiral/markers, brackets active
tabs/actions, standardizes captions and replaces obsolete RUN IN MENU wording
on CAL. Its 47 targeted checks pass with the same qualified gateware. The next
correction restores the viewport border center (360,360), independent of the
left-shifted spiral, and uses equal centered header slots. Scene checks and
firmware build pass; see RENDERER.md for flash evidence. The October 1 pass adds
a cached piano-key preview for standard scales, retaining exact custom/24 EDO
grids. Source 3 now scans the +11 MiB keyboard cache (reserve caches through
+12 MiB). All 95 targeted checks and the full normal-clock FPGA build pass;
flashed to #1 slot 1 preserving storage. The latest qualified hardware is now
build/intono-ux-tagged-keys-r5 after the following filled-key pass: standard
keyboard keys now use cyan/dim/dark primitive fills and plain labels. A published
12-bit mask colors tagged cached interiors; 47 pixel/frame/DMA checks and full
normal-clock FPGA timing pass. Firmware 303256 bytes; flash evidence in RENDERER.md.
The rounded-controls pass supersedes that hardware: build/intono-ux-rounded-r5.
Tabs, footer links and action buttons now have actual rounded outlines and
centered plain labels; piano keys have subtle radius-4 corners. Surface/focus
are staged atomically. All 49 pixel/frame/background/border checks (six intentional
skips), 28 scale/control and 16 scene/primitive checks pass. Full normal-clock
FPGA timing passed; flashed to #1 slot 1 preserving saved storage. Firmware
303032 bytes. See RENDERER.md for archive, timing and flash evidence; physical
feedback remains pending. The following firmware-only pass centers footer
labels and balances odd character counts, fixes profile-action/quantize crowding
on ROUTES, and shows one selected A/B octave at a time as a full keyboard in
CUSTOM NOTES. Focused notes are yellow; both pattern masks remain unchanged.
29 scale/text/control and two border/layout checks passed; firmware 303200 bytes
flashed successfully to #1 slot 1 preserving saved storage. See the octave-editor
archive/flash evidence in RENDERER.md. Use the rounded-controls hardware for further
firmware-only builds. Full help,
richer libraries and independently reusable scale
editing remain pending. Keep calibration/quantizer math and diagnostics intact;
do not resume historical calibration-speed or pause instructions below.

**September 30 checkpoint:** the user considers the calibration foundation,
basic quantization and tuning ready to checkpoint and resume UI work. The R5
natural-origin build is flashed to #1 slot 1; the user reports a successful
quantizer test with about five usable octaves. AUTO took 5m27.670s with a
63-point CHARACTER profile (worst 8.474c, stability 8.600c). This is a working
development baseline, not a release claim or full oscillator qualification.
See [SPEED_WORK_HANDOFF.md](SPEED_WORK_HANDOFF.md) for current calibration,
validation and flash details; its current records supersede the historical
pause and older ranges below. Keep granular timing diagnostics in place.

Resume the interface contract in [RENDERER.md](RENDERER.md): TUNER, CAL, QUANT,
and ROUTES are the four primary surfaces. CAL's profile library and QUANT's
scale library should become contextual panels. Preserve existing storage,
advanced controls, explicit run/stop behavior and measured-data visibility
while replacing the intermediate menu navigation. Further scan-speed work
is deferred; the missing-reading discovery cost remains recorded for later.

**Latest September 19 update:** `e3b1e805` is built and flashed to slot 1.
Generate3 FUNDAMENTAL automatic calibration completed with 92 anchors from
-2.58325 to +5 V and 181/181 corrected targets checked. Worst error was +2.23
cents; one no-gain refinement attempt safely kept the verified original curve.
The previous +4.25-V detector conflict is resolved on this run. See
[AUTO_CALIBRATION.md](AUTO_CALIBRATION.md) for the filter/native-refinement
changes, limits, resource costs and evidence. This is internal verification,
not absolute accuracy or full 20-kHz qualification. Mixed CAL/ROUTES operation
remains to be physically tested; USB storage integration remains pending.
Saved profiles were not changed. The historical pause snapshot below is not
the current build or workflow.

**September 18 update:** development resumed; passive tuner plus unified
per-output routing (optional quantization then optional correction) supersedes
the first mode-owned implementation. One scan may coexist with other outputs.
CAL now runs a bounded automatic measure/check/improve workflow; eight profile
slots support up to 129 points (121 initial positions plus eight refinements).
See [AUTO_CALIBRATION.md](AUTO_CALIBRATION.md) for the simplified UI and pending
hardware test, and [USB_STORAGE.md](USB_STORAGE.md) for the upstream thumb-drive
integration investigation (not yet enabled).
See [CONCURRENCY.md](CONCURRENCY.md) for the
new behavior, build evidence and pending hardware test. The pause snapshot below
is historical; its page-change/setting-change stop behavior is superseded.

Work is paused at the user's request. This file supersedes earlier "next step"
and pending-trial statements in the dated investigation documents. Active branch
is `codex/tuner`; latest implementation commit is `26d3891e`. No remote push is
implied. TUNER remains a working instrument name.

## Working features

- Shared renderer and four-input NSDF tuner, spiral and linear views; independent
  level meters. Selected build is 192 kHz; legacy pitch hardware is omitted.
- Oscillator calibration: upward -5..+5 V sweep, up to 121 semitone-spaced points,
  usable-range discovery, review/accept/discard and tuning advice. ACCEPT is RAM
  only; four PROFILES slots are saved separately. VERIFY and guarded local
  refinement work; corrected PLAY is a separate single-channel path.
- Standalone four-output nominal quantization, independent input routing (one
  input may feed several outputs), scales, root, transpose, 0 V note and mapping.
  Default routing is IN n to OUT n. No audio pitch detection or profile required.
- Nearest and Equal mapping; presets including 24 EDO; editable two-octave note
  patterns. One empty octave collapses to one-octave operation. Eight NOTES
  pattern slots and eight SETUPS slots; each setup contains all four channels.
  Settings edits/recall stop outputs; RUN is explicit. Out-of-range CV holds the
  last valid result; faults/stale data retain their separate safety behavior.
- Scala conversion/validated binary decoding exists offline, but device import,
  persistent imported microtonal scales, MIDI learning and USB hosting do not.

## Four-output synchronization and test evidence

`77baf571` introduced four lanes at 500 Hz each, calculating two per 1 ms
interrupt. The user heard possible stagger. `26d3891e` retained that CPU schedule
but shares input readings between batches and stages all four output voltages
until one common commit. Explicit safety disables remain immediate. The codec
path carries four values together through its FIFO; physical jack timing is
not established solely by the simulation or register ACKs.

- 174 regression tests passed, including staged-output behavior, DAC
  backpressure, ACKs, fault isolation and CAL priority.
- Live serial on the synchronized build: all four active; observed maximum
  batch 21629 cycles (~360.5 us at 60 MHz), below the 500 us guard. Observed
  maximum interrupt gap 121127 cycles (~2.019 ms), below the 5 ms guard.
  These are observed maxima, not a worst-case execution-time proof.
- First audio recording used different scales/mappings, which legitimately
  change notes at different CV thresholds. Second recording used matching
  reported settings. Four spectral tracks across 14 successive transitions
  showed no consistent sequential order; estimated transition spread was
  about 1–4 ms. The 1024-sample spectral window and individual oscillator
  responses mean those estimates do NOT measure DAC skew or prove zero skew.
- Next optional timing test: connect OUT0–3 to another Tiliqua running OSCIO,
  use identical quantizer settings and one LFO, trigger on a CV step, inspect
  all four edges near 1 ms/div if supported. Check scope sample/display
  resolution before making sub-millisecond claims; raw capture is preferable.

Local evidence (not repository fixtures): `/tmp/tuner-sync-regression.log`,
`/tmp/tuner-sync-build.log`, `/tmp/tuner-sync-matched-check.serial.log` and
`/tmp/tuner-sync-audio-check.serial.log`; these temporary files can expire.
User recordings: `New 2 2026-09-13 1709.wav` and `New 2 2026-09-13 1717.wav`.

## Qualified hardware and release build

Full synthesis/routing of the synchronized hardware passed:

| Resource/clock | Result |
|---|---:|
| LUT4 | 19312 / 24288 (79%) |
| EBR | 44 / 56 (78%) |
| DSP | 14 / 28 (50%) |
| Main clock | 65.85 MHz achieved / 60 MHz required |
| HDMI serializer | 406.17 / 371.33 MHz |
| Pixel clock | 87.72 / 74.25 MHz |
| Audio clock | 69.74 / 49.15 MHz |

CPU working RAM remains 32 KiB. Do not assume the remaining FPGA resources can
support every optional feature; retain CPU, memory and routed timing checks.
No spectrum renderer is planned as a prerequisite for feature completion.

Qualified `top.bit` SHA-256:
`48e9bd78f32593d57549807b9f8b8be57b51070f8220ceadc388c6fcf4049fcf`.
The documentation checkpoint build reuses this hardware with a newly tagged
firmware/archive. Normal release is R5, 1280x720p60 (unrotated), 192 kHz,
`spread_spectrum=0.0`. Circular display qualification is not claimed here.

From `gateware`, with the project's Python environment and FPGA/Rust tools on
PATH, build with `PYTHONPATH=src TILIQUA_TUNER_SEED=17
python src/top/intono/top.py build --hw r5`. Add `--fw-only` only when reusing
qualified, unchanged hardware. Never use it to qualify a gateware change.
Archives are under `gateware/build/tuner-r5/`. Preserve option storage; archives
contain bitstream, firmware and manifest, not a replacement options payload.
Bitstream slot 1 is distinct from calibration-profile slot 1.

## Resume priorities

1. Resolve physical CV timing only if needed; do not mistake differing scale
   thresholds or oscillator response for channel scheduling delay.
2. Consolidate multi-channel safety/storage regression coverage and UI clarity.
   QUANT's output selector selects a channel's settings; RUN controls the group.
3. Add validated user-controlled scale import/storage and computer-side authoring.
   Keep scale files independent of oscillator profiles and stopped during import.
4. Evaluate optional per-channel profile correction, MIDI learning/transposition,
   and USB support separately against resource limits. No commitment to fit all.
5. Revisit the wider interface after feature behavior is settled. Preserve the
   single renderer, panel numbering, explicit run/stop and save feedback.

Do not infer a saved profile's oscillator identity from old slot maps: the user
has overwritten test slots during development. Preserve all stored records.

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


## October 2 overnight review and MIDI update — ready, NOT FLASHED

User preference: default C4 zero and hold last MIDI transpose, configurable.
Implemented per-route channel OFF/1–16, any zero note, HOLD/ZERO release and RESET.
MIDI offsets reach all group outputs at batch boundaries; scale learning owns
MIDI exclusively while armed. ROUTES > ALL ROUTES now summarizes all outputs,
profile/scale sources, keys and status. Setup TQS5 (132 bytes) persists MIDI and
saved-scale provenance; TQS1–4 migrate with MIDI off. Full review and morning
checklist: CODE_REVIEW_2026-10-02.md. Corrected group fault cleanup in ISR, MIDI
learn cross-channel held-state issue, stale +5V advice and endpoint slope overflow.
Calibration policies/timing logs and 1–8 octave support retained.

Qualified unflashed artifact: build/intono-ux-midibase-r5/intono-ux-review-midi-20261002-r5.tar.gz.
SHA256 6201fe6d1a04c9735413602f6a1ecfee2c00cfd3020c3b8ede8c9989cfb5e48a. FW 315584/327680; SRAM 6800, stack region 25968.
All final clocks PASS (serializer434.97, pixel86.30, audio67.30, CPU67.35 MHz).
254 live/cal tests +55 scale/UI/setup +20 navigation +5 MIDI learner pass.
52 simulations pass,10 existing unsupported combinations skipped; diff clean.
No debugger attachment or flash attempted because rack was turned off. Previous
groups archive remains the last flashed image; capture stack/IRQ timing on rack.


October 2 morning: user powered the rack and authorized flashing. Verified the
review/MIDI archive SHA256 and flashed Tiliqua #1 (DirtyJTAG E46534A193222B21),
slot 1. Erase/write/refresh completed successfully. Log /tmp/intono-review-flash.log;
qualification build/intono-ux-midibase-r5/review-midi-flash.json. Physical feature,
stack-watermark and interrupt-latency testing remains pending module launch.

### Diagnostic cleanup flashed, 2026-10-02

Tiliqua #1 slot 1 successfully written/refreshed with
`build/intono-ux-midibase-r5/intono-ux-diagnostics-20261002-r5.tar.gz`.
SHA256 `68d6ee59c09b496333ebac9065518ab8fb7a6ce733415371bcba7db1f762871e`.
Normal firmware 288440 bytes; detailed diagnostics opt-in, calibration timing
and stack/video health retained. Both diagnostic modes compile and 254 host
calibration/playback tests pass. Flash completed with Refresh DONE; user runtime
smoke test pending. See RAM_REVIEW.md for memory comparison and README.md for
build setting.

### Route mapping and expanded factory scales, 2026-10-02

Mapping is visible only on Routes, stored per output alongside root/transpose.
Scale interval edits and saved-scale loads preserve it. Legacy hidden scale
mapping fields remain for option-key compatibility; saved note records unchanged.
Twelve common factory presets now available, plus retained 24 EDO and eight user
slots. IDs 0..6 remain stable; new presets append 7..13. Fixed/jazz melodic minor
and six-note minor blues are documented. Proteus manual used as factory-set
reference; no claim of measured popularity ranking.

Qualification: 255 calibration/playback tests, 57 scale/setup/UI tests, 22 actual
options/navigation tests pass; 39/40 initial display/frame tests passed, with the
remaining old packed-register fixture updated for 5-bit focus and then all six
frame/border tests passing. The focus register now distinguishes control 15 from
no-selection 31; generated firmware CSR accessors match this bitstream.
All four final seed-19 timing domains PASS: 444.05/371.33 MHz serializer,
87.96/74.25 pixel, 68.43/49.15 audio, 66.96/60 CPU. Logic cells 21096/24288,
RAM blocks 46/56, multipliers 14/28. Firmware 289096/327680 bytes, SRAM static
6816 bytes, stack region 25952 bytes.
Qualified archive: `build/intono-ux-midibase-r5/intono-ux-route-map-presets-20261002-r5.tar.gz`.
SHA256 `f2b73656cb0705d2d09cb1435c80e30f0f757e23515198563f4aa240342d696a`.

Successfully flashed Tiliqua #1 slot 1; erase/write completed and Refresh DONE.
Runtime smoke test pending.


## Routes flow integration — 2026-10-02

Branch `codex/intono-route-flow` now contains the firmware implementation of the
card overview and route flow, following `ux/route-flow.html`. Selected cards expand;
all four outputs fit in an expanded card. The definition shows two output chains
at a time with an explicit pager. Centered stage editors reuse existing persisted
options, explicit Apply Profile / Load User Scale actions, and active jack locks.
MIDI is shared per route; scale/key/map/shift/profile remain per output. Eight green
bars show approximately one second of actual output-pitch history at 8 Hz.

Sparse rounded outlines reuse the double-buffered background banks. Each bank
receives the common circle once upon entry, then erases/repaints only retained
shapes. Text and background publish together. No additional FPGA block RAM.
A foreground synchronization correction also prevents MIDI/setup pages from
writing stale scale-editor settings back into a stopped output.

Qualified and flashed to Tiliqua #1, slot 1:
`build/intono-ux-midibase-r5/intono-route-flow-20261002-r5.tar.gz`.
SHA256 `db7dbede4a36a156b59c4b282a56aee5c18d77be3f0ed6a7d6c59e8239576b80`.
Matching symbols `route-flow-firmware.elf`; evidence `route-flow-validation.json`
and `route-flow-flash.json`. Firmware 304280 / 327680 bytes; static SRAM 7876;
remaining stack region 24892. Compiled run closure 8128 bytes (160 above prior),
route renderer 976 bytes. These are allocations, not a new runtime stack watermark.

FPGA: COMB 20837/24288, FF 12121/24288, RAM 46/56, MULT 14/28. All final timing
checks pass: serializer 432.90/371.33 MHz, pixel 85.96/74.25 MHz, audio
67.18/49.15 MHz, CPU 65.78/60 MHz. Tests: 26 actual-option/navigation,
78 scale/canvas/history, 255 calibration/playback host, 69 Python display/layout/
calibration regressions. Updated obsolete option/layout assertions to the current
persisted fields and dynamic route shapes.

Physical follow-up: launch Intono, exercise card expansion, each stage editor,
three/four-output paging, MIDI edits, occupied jacks, Start/Stop, saved-scale load,
profile apply, and calibration after leaving Routes. Check legibility and capture
stack/video health during use. Hardware flashing succeeded; screen interaction
has not yet been observed on the rack.


### Route presentation polish — 2026-10-02

Following rack photos, cards now use aligned route/assignment/status columns,
output badges, a header separator, and aligned scale/key/map/profile details.
Flow nodes allocate extra width to scales and profiles, with native-cell padding
so CHROMATIC does not cross its border. A separate dotted MIDI connection feeds
the shift stages. Editors use labels beside independently outlined values.

Flashed slot 1: `intono-route-polish-20261002-r5.tar.gz`, SHA256
`74f80bd2e008f6deb97c5fc28da31ceb51800defd374d744919f8756e5701b4a`.
Firmware-only rebuild against the byte-identical, previously qualified FPGA
bitstream. Matching `route-polish-firmware.elf`, `route-polish-flash.json`,
`route-polish-validation.json`. Static/stack allocations unchanged (7876/24892);
run/presenter compiled frames unchanged (8128/976).

Added actual-presenter host capture test `opts/tests/intono_route_render.rs`:
45 presenter/dependency tests and 26 encoder tests pass. Dense four-output cards,
two-branch flow and editor captures were inspected with native 9x15 glyphs;
shapes fit the circle and leave spare capacity in the bounded 48-shape list.
Raster preview script `/tmp/render-intono-route-capture.py`; captures
`/tmp/intono-route-{overview,flow,editor}.{txt,png}`. These use test state; rack
appearance and interaction remain to be verified by the user.


### Grouped flow — 2026-10-02

Output branches now contain two spacious, clickable groups: Pitch (scale, key,
mapping, manual/MIDI shifts) and Output (jack, profile, 0V reference, live note).
Manual transpose is included in the Pitch editor; profile and jack assignment
share the Output editor. Flow focus skips the removed narrow boxes. A single
visible branch is vertically centered, including the final page of a three-output
route; two branches remain stacked. Wider connections include directional arrows.
CV and MIDI retain separate ports and all existing run/claim locks remain.

Flashed Tiliqua #1 slot 1: `intono-route-groups-20261002-r5.tar.gz`; SHA256
`b9171e32c17b2391323c578f7b6cac958ecf5316a2db659f139557fce9eb4fc2`.
Firmware-only rebuild with verified identical FPGA bitstream. Matching symbols
`route-groups-firmware.elf`, qualification `route-groups-validation.json` and
`route-groups-flash.json`. SRAM/stack region remains 7876/24892 bytes. Tests:
27 navigation and 45 presenter/dependency checks pass. Native-glyph captures
of single/two-output flow and both editors inspected; rack appearance pending.

### 2026-10-02 — reserve configured route jacks immediately

- Route selectors now combine persisted route assignments with runtime claims. A stopped route retains its input/output reservations; removing its last output releases its source reservation. Empty route source selectors are placeholders until an output is assigned.
- Output assignment no longer transfers a destination from another stopped route. Remove it from that route first. Input sharing between nonempty routes is also rejected, including conflicting saved layouts.
- Calibration continues to use runtime claims only: stopped routes' jacks may be borrowed without modifying their configurations. Starting a conflicting route during a scan fails with `JACK IN USE - STOP OPERATION`.
- Editor legends mark this route's assigned jacks with `*`, dim unavailable numbers, and ADD OUTPUT is disabled when no unassigned destination remains.
- Validation: 29 actual navigation tests, 46 actual presenter tests, 86 scale/setup/ownership fixture tests passed. Firmware 305824/327680 bytes; SRAM 7876 bytes and stack reservation 24892 bytes unchanged. FPGA bitstream identical to qualified route-groups build.
- Archive: `build/intono-ux-midibase-r5/intono-route-reservations-20261002-r5.tar.gz`; SHA256 `983e854ac5ed7f05dc2a3d63f771877789c0d4552bfe4a3cd31ae617ae3531bd`. Matching ELF and validation/flash records retained beside archive.

### 2026-10-02 — empty routes and actionable setup load warnings

- New/default route layouts contain no outputs and reserve no sources. Choosing a source is provisional until the first output is added. Saved valid layouts retain their assignments.
- Setup slots store the whole four-route configuration. Loading replaces it atomically after full decoding/validation; stopped assignments in the current setup do not conflict with a replacement. There is no individual-route load action.
- Running-route load attempts show a centered `CAN'T LOAD SETUP` dialog with the route number, `GO TO ROUTE n`, and `CANCEL`. The jump opens that route's flow; cancel restores the setup page/focus. Neither action stops routes or applies the rejected load.
- Calibration blocks setup loading with explicit stop-scan feedback rather than silently ignoring the request. Invalid saved setups retain the current setup. CRC-authenticated duplicate assignments are diagnosed by jack type/number and both saved route numbers; malformed/checksum-invalid data gets a generic invalid-file dialog.
- Regression validation: 30 navigation, 46 presenter, 87 scale/setup/ownership tests pass, including input/output duplicate diagnostics, corrupted CRC, empty defaults, modal jump/cancel and temporary calibration reservations. Actual presenter warning capture inspected.
- Built and flashed Tiliqua #1 slot 1, Refresh DONE. Archive `build/intono-ux-midibase-r5/intono-route-load-dialogs-20261002-r5.tar.gz`; SHA256 `e3e4b2c2ae31a4bf4af8a6dbaf327196d2ab73bf39134012086a1bd1a8343310`. Firmware 308064/327680 bytes, static SRAM 7892 bytes, reserved stack 24876 bytes. FPGA image byte-identical to qualified route-groups build. Matching ELF/validation/flash records retained.

### 2026-10-03 — route editor cleanup and transition latency

- Output/profile and input editors remove the `FREE / DIM: ASSIGNED` heading, move jack numbers up, then show `* ASSIGNED TO THIS ROUTE` and `DIM = ASSIGNED` on separate lines. Pitch editor omits the click/turn tutorial.
- Selecting profile NONE clears the stopped output's bound-profile indicator and uses nominal CV. Redundant CLEAR PROFILE action is absent from both rendering and encoder navigation; selecting a real source retains APPLY PROFILE.
- Routes initializes on Route 1 independently of the scale editor's selected output and previously saved route selector. PlayOpts defaults to route index zero.
- Route background preparation clears the existing back buffer in bounded 32768-word chunks and draws the build-time border coordinates directly, rather than copying the whole circle cache in 4096-word chunks. First complete bank can publish on its final preparation tick. At 1280x720 this reduces 57 preparation steps to eight. No new framebuffer or SRAM. Wall-clock latency needs hardware observation; operation timers remain interruptible and foreground services run between chunks.
- Tests: 31 actual navigation, 46 presenter, 87 scale/setup fixture tests passed. Presenter captures inspected; diff whitespace checks clean. Firmware 308152/327680 bytes; SRAM 7892 bytes and stack 24876 bytes unchanged. FPGA bitstream identical to qualified route-groups build.
- Archive `build/intono-ux-midibase-r5/intono-route-tidy-20261003-r5.tar.gz`, SHA256 `a9f86dd2636b375d328b01299a8ddd467e29cebd9bd29fdccdc2d6cc9ca303fa`. Matching ELF and validation/flash records retained beside archive.

### 2026-10-03 — focused empty-route creation

- Opening an empty route focuses a centered ADD OUTPUT button immediately. CV/MIDI nodes and START remain hidden until an output exists; BACK/SETUPS remain accessible.
- Empty flow encoder order is ADD OUTPUT, BACK, SETUPS; it cannot focus hidden nodes. Cancelling ADD returns to the focused centered button.
- ADD selects a free provisional input if another route/calibration has reserved the old placeholder. A successful output assignment closes the ADD dialog and opens the normal diagram focused on its first pitch group.
- Validation: 32 navigation and 46 real presenter tests pass, including empty-route initial focus, hidden-node skipping and source conflict fallback. Actual empty-route presenter capture inspected. Firmware 308856/327680 bytes; FPGA bitstream identical to qualified route-groups build.
- Archive `build/intono-ux-midibase-r5/intono-route-empty-20261003-r5.tar.gz`, SHA256 `36f159bff6db779da971552af1636e157ffa181058ead3f592ac0c4ba757ee9b`; matching ELF and validation/flash records retained beside archive.

### 2026-10-03 — distinguish route context from encoder focus

- Overview route card border and title emphasis now follow `tracker.selected`, rather than highlighting the remembered route during page-tab navigation. Expanded details retain their route context when focusing action buttons, but only the control under encoder focus is highlighted.
- Actual presenter regression checks all four card borders with page navigation, first-card focus and START-button focus. 32 navigation and 46 presenter tests pass; FPGA unchanged.
- Archive `build/intono-ux-midibase-r5/intono-route-focus-20261003-r5.tar.gz`, SHA256 `29544fc4ada8c76d848b6f7959d880803ceb1dfabc198ac3d2215e80090eafbd`. Firmware 308816 bytes. Matching ELF and validation/flash records retained.

### 2026-10-03 — clear obsolete empty-route warning

- A successful output assignment clears the lane's stale `ADD AN OUTPUT FIRST` status. The route presenter additionally suppresses that specific warning when the route has an output, while retaining profile/load and real output fault feedback.
- Regression validation: 32 navigation and 47 presenter/dependency tests pass; includes obsolete-requirement suppression and preservation of unrelated errors. FPGA unchanged.
- Archive `build/intono-ux-midibase-r5/intono-route-status-20261003-r5.tar.gz`, SHA256 `85ca9ce96cfbb4404f46a717e85d174856a696bcd7f79afa33cb83bac24de12a`. Firmware 308960 bytes. Matching ELF and validation/flash records retained. Flash completion is separate from verifying Intono was relaunched.

### MIDI transpose wording and base-note learn — 2026-10-03
- Route flow uses MIDI TRANSPOSE. Popup renames ZERO to BASE NOTE, release choices to LATCH / RESET ON RELEASE, and reset action to RESET TRANSPOSE; current offset is visible beside these controls.
- LEARN BASE NOTE arms a one-shot capture of the exact next note on the selected route MIDI channel (not its octave). Note-off/zero-velocity and other channels are ignored. Capturing establishes zero transpose; CANCEL LEARN or leaving the popup cancels capture. Channel OFF disables learn. Existing setup persistence stores the learned base through the unchanged MIDI configuration format.
- Interrupt capture uses compact fixed state and hands the learned note to foreground before UI configuration synchronization, avoiding a stale field overwriting it. Other routes continue normal MIDI handling.
- Host validation: 33 navigation and 52 presenter/dependency tests passed, including capture/channel/cancel tests and popup geometry. Firmware 310480 / 327680 bytes; qualified FPGA unchanged.
- Archive: intono-midi-ux-20261003-r5.tar.gz, SHA256 e62b647f907c324bf9b8d3f7a63b8b30c1e11ce00823576bf7b56f093a6766e4. Device execution still requires hardware confirmation after slot reload.

### Configs navigation and route Start — 2026-10-03
- Removed redundant EDIT ROUTE from overview. Encoder order follows each highlighted route with START/STOP and CONFIGS before proceeding to the next card, preserving the chosen route when starting. Empty routes skip the disabled Start action.
- SETUPS renamed CONFIGS in user-facing labels and feedback; binary storage keys/formats unchanged. Configs has an explicit BACK, SAVE CONFIG / LOAD CONFIG, and a readable Current route assignments summary listing all outputs per route with one-based route numbering. Live RUN/OFF and LOAD LEAVES OUTPUTS OFF removed; run state is not persisted.
- Configs / MIDI TRANSPOSE now uses the retained firmware presenter, with a route selector (Route 1–4), channel, exact learned base note, release policy, reset, live offset and explicit BACK. This fixes the old standalone MIDI page's incomplete generic controls. Flow MIDI popup retains DONE. Capture cancels on changing MIDI routes.
- Configs controls are also drawn by the firmware presenter, so the added Back button and wider MIDI action have matching outlines without changing FPGA geometry. Back to overview restores focus to the remembered route.
- Validation: 35 navigation, 53 presenter/dependency, 91 scale/setup/geometry tests passed; real presenter captures inspected for Configs and MIDI with longest release wording. Firmware 312512 / 327680 bytes. FPGA bitstream identical to qualified route-groups image.
- Archive intono-configs-20261003-r5.tar.gz, SHA256 5a79d4ed004ea9a107b98fc828b1748a2546578cb270b274c1bc34fce5787d40. Flash record configs-flash.json; application execution requires user confirmation after reload if refresh does not restart it.


## October 3 overnight cleanup

Committed the accumulated route/config/MIDI UI work as `49675406`, then reviewed
math, reservations, persistence, MIDI state, RAM, and foreground rendering work.
See `CODE_REVIEW_2026-10-03.md` for fixes and validation. Removed unnecessary
calibration graph scans outside CAL and obsolete route UI paths. Static SRAM
remains 7,940 bytes; firmware payload is 312,112 bytes. The qualified morning
archive is `build/intono-ux-midibase-r5/intono-cleanup-20261003-r5.tar.gz`; its
matching ELF and validation JSON sit alongside it. Not flashed overnight.
