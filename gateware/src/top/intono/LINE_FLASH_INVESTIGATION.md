# Current outcome and cleanup (2026-10-06)

The user reports multiple clean reboots on the ASUS VS239H-P with the qualified
`intono-line-resetguard` image. This supports the serializer reset correction as
the leading explanation; it does not conclusively establish the original flash's
cause. No concurrent UART capture exists for those successful boots.

The production candidate retains circular shifting and Intono's opt-in reset
correction. Framebuffer-enable and PLL-lock reset requests are combined before
one fast-clock ResetSynchronizer. The final register drives all phase-ring and
DDR reset pins; there is no second pixel-domain ResetInserter on this path.
Other bitstreams preserve their existing behavior.

Cleanup removes the experimental serializer environment selector, temporary
pixel fault observers/CSRs, serial telemetry, diagnostic protocol command, and
host capture utility. Existing production video-health reporting is preserved.
Restart tests, full-scanline TMDS decoding, and the corrected serializer
comparison remain as regression coverage. Saved-profile formats are unchanged.

The cleaned image must pass final timing and physical monitor testing: removing
observers changes placement and routing, so the earlier image's timing result
cannot qualify the new one. Digital simulations do not model physical reset
skew or HDMI signal integrity. Related-clock bundled-word capture remains an
independent area for future investigation if artifacts recur.

The historical record below includes superseded experiments and instructions;
they describe past investigation steps, not the current test plan.

---

# Transient line investigation

Branch: `codex/intono-line-flash-debug`, based on `naenyn` at `24f78c4d`.

Reported symptom: one or two brief horizontal colored lines on first visits to
ARC tuner and scale keyboards, usually the right half/third, crossing other UI.
This branch adds observation, not a claimed fix.

## Diagnostic blind spot

The previous `BUFFER_GAPS` flag detects DMA starvation. `BACKGROUND_ERRORS`
checks palette-code legality and drawing beyond the logical 720-pixel panel.
A valid-colored line within the panel passes both checks. Baseline serial capture
on October 5 had both flags zero and 8588 bytes of unused stack.

## Added evidence

Two sticky first-pixel snapshots, cleared by FPGA reset:

- `PIXEL RAW`: PSRAM/DMA input before overlays. Watches logical x >= 560,
  y 160..579 on ready ARC and keyboard surfaces.
- `PIXEL OVERLAY`: completed overlays, logical x >= 656, same vertical range.

These regions should contain only black (00/09) and outer-circle dim color (29).
Coordinates recorded are **physical** scanout coordinates. The narrower overlay
region excludes tuner statistics and the keyboard view pager. Probe logic does
not stall or modify pixels. Snapshot crosses clock domains as frozen data; its
valid bit takes an additional synchronizer stage before CPU reads expose it.

Packed word: pixel bits 0..7, x 8..18, y 19..28, surface 29..30, valid 31.
Surface 0=ARC, 1=SCALES, 2=NOTES/tools. CSRs at display offsets 0x28 and 0x2c.

A raw event implicates background memory/scanout or unexpected background drawing.
An overlay-only event implicates a later UI stage. Both can report the same
background fault. Zero snapshots do **not** rule out a flash: probes exclude the
left/central UI, valid circle-color pixels, other pages and post-palette RGB/TMDS.
A reproduced visual flash with clean snapshots motivates extending those stages.

## Autonomous exercise

`pdm run python tests/exercise_intono_display.py --log /tmp/intono-lines.log`
waits for this diagnostic firmware, then cycles tuner/calibration/scales at
12-second intervals, recording acknowledgements and decoded snapshot locations.
Disconnect librarian first. Firmware rejects requests while calibration, routes,
or Reference CV operate. It neither changes assignments nor writes storage.

Diagnostic-only profile protocol operation 0x70: kind=0, slot=page (0 tuner,
1 scales, 2 calibration); count/offset/total=0. Normal packet CRC applies.
Successful reply releases telemetry immediately. Remove this branch-only command
before merging a production fix. Page changes do not force a stored Scala scale
into keyboard mode; use an ordinary keyboard scale for the keyboard reproduction.

Tests inject a one-cycle valid cyan error, confirm old flags stay clear while
both new snapshots identify it, check permitted background colors/other pages,
and verify packet busy guards and zero profile-store calls.

## First diagnostic image

Built/flashed to slot 1 on October 6, 2026:
`build/intono-line-probe-r5/intono-line-probe-24f78c-d-r5.tar.gz`.
Firmware: 327168 / 327680 bytes. EBR 50/56, DSP 14/28.
Seed 22 routing was stopped after prolonged congestion; seed 23 used the same
synthesized netlist and passed final timing: CPU 65.69/60 MHz, DVI 84.84/74.25,
DVI5x 439.95/371.33, audio 69.06/49.15. Archive built with the repository's
ArchiveBuilder and independently checked for matching file CRCs and the unchanged
36864-byte option-storage reservation. Flash completed with `Refresh: DONE`.

Validation logs: `/tmp/intono-probe-tests.log` (45 passed),
`/tmp/intono-probe-injection.log` (27 passed, 10 skipped),
`/tmp/intono-line-stages.log` (17 passed),
`/tmp/intono-probe-host.log` (6 passed).
Hardware reproduction remains pending; passing simulations are not a fix.

## Reproduced visual flash, first probes clear

User launched the first diagnostic image and reported a blue line immediately
after the tuner rendered. The retained RAW and OVERLAY words were both zero,
BUFFER_GAPS=0, BACKGROUND_ERRORS=0. Seven subsequent automated page requests all
returned OK and retained the same zero diagnostics. Transcript:
`/tmp/intono-line-probe-reproduced.log`. This does not exonerate indexed scanout:
the original probes excluded y<160/y>=580 and all dim circle-color pixels.

The second diagnostic revision removes the vertical blind spots (all 720 logical
rows), detects >=64 consecutive dim-circle pixels in the right guard region, and
adds a post-palette check. `RGB` is a first-event snapshot in the same packed
format; `RGBVAL` is the actual RGB color as 00RRGGBB. It detects nonblack RGB output
for indices 00 or 09 after UI ready on the watched surfaces, with palette latency
accounted for. It does not cover corruption introduced later by TMDS serialization,
the cable, or the monitor. New CSR offsets are 0x30 (RGB event) and 0x34 (RGB value).

Second image built and flashed to slot 1 (October 6):
`build/intono-line-probe2-r5/intono-line-probe2-24f78c-d-r5.tar.gz`.
Firmware 327024 bytes; seed 23 final clocks all pass: CPU 62.94/60 MHz,
DVI 80.52/74.25, DVI5x 451.26/371.33, audio 69.69/49.15.
Archive CRC/storage checks pass; flash completed with `Refresh: DONE`.
Expanded display suite: 47 passed. Dedicated injected-fault suite: 4 passed.
User launched the second image and reported no flash so far. Seven automated
page requests (tuner/calibration/scales twice, ending on tuner) all returned OK.
RAW, OVERLAY, RGB, BUFFER_GAPS and BACKGROUND_ERRORS remained zero throughout;
reported unused stack margin was 8572 bytes. Transcript:
`/tmp/intono-line-probe2-loaded.log`. Serial capture closed normally afterward.
This is a clean run, not a confirmed fix: neither diagnostic revision deliberately
changes rendering behavior, and a changed FPGA placement can affect reproduction.
The next useful test is another boot and first visits to tuner and scale keyboards.
If a flash appears, read the sticky snapshots before rebooting.

## Second-image reproduction: orange at the cents readout

After reboot, user reported this order: tuner page, spiral, channel markers,
then a flash. Clarification: orange, around the cents readout beneath the focused
note. Immediately captured `/tmp/intono-line-probe2-reproduced.log`: RAW,
OVERLAY, RGB, BUFFER_GAPS and BACKGROUND_ERRORS all zero; stack margin 8572 bytes.
Capture closed normally. This is another confirmed visual reproduction with
clean probes, not evidence of a fix or proof of an HDMI fault.

The cents text uses index B9 (Blue theme complement #FF9000) at logical y=256.
The general raw guard begins at x=560, and completed-overlay guard at x=656.
These omit much of this text area. Third revision adds a targeted Arc window
x=492..655, y=248..287: any nonblack retained-background pixel is suspicious;
completed text must not contain 16 consecutive nonblack pixels (ordinary glyphs
are at most 9 pixels wide with gaps). It reuses the existing RAW/OVERLAY snapshots
and requires no additional telemetry fields. Tests scan the actual cents font
and then inject an orange streak wholly left of the earlier guard thresholds.
Five dedicated probe tests pass. Root cause remains unconfirmed.

Third-revision regression suite: 49 passed
(`/tmp/intono-line-probe3-tests.log`). During review, the serializer comparison
test was found to instantiate its "old" PHY with the default, which now enables
circular shifting. Explicitly selecting `circular_shift=False` restores the
intended comparison against zero-fill shifting. Corrected comparison and TMDS
tests: 3 passed (`/tmp/intono-line-probe3-serializer-tests.log`). This test repair
does not change the built hardware or establish the cause of the visible flash.

Third image built and flashed to slot 1:
`build/intono-line-probe3-r5/intono-line-probe3-24f78c-d-r5.tar.gz`.
Firmware 327024 bytes (656 spare); all final clocks pass: CPU 65.99/60 MHz,
DVI 82.18/74.25, DVI5x 449.64/371.33, audio 67.15/49.15. Archive and unchanged
36864-byte saved-data reservation verified. Flash exited successfully with
`Refresh: DONE` (`/tmp/intono-line-probe3-flash.log`). Awaiting user launch and
reproduction; no root cause or rendering fix claimed.

## Third-image reproduction: two flashes, probes still clear

User reported blue/purple lower on the tuner before FREQUENCY/LEVEL appeared,
then orange higher up afterward. `/tmp/intono-line-probe3-reproduced.log` again
shows zero RAW/OVERLAY/RGB and old health flags. Before treating that as evidence
against these stages, revision 4 adds a live self-test of the measurement path.

CSR 0x38 reports fixed gateware revision 4 in bits 31:24 and synchronized live
ready[0], diagnostic mode[2:1], and UI surface[6:3]. CSR 0x3c selects mode 0=arm,
1=inject, 2=clear. Injection changes ONLY diagnostic capture inputs; no video,
audio, or stored data is modified. All three probes should return a synthetic
first event at x=0x123, y=0x145, pixel=0xAB, surface=3, plus RGB 0x112233.
The same clock crossings and CPU fault registers used for real events are read.

Branch-only operation 0x70 additionally accepts slot 3=inject, 4=clear, 5=arm.
The existing active-operation guard applies. `exercise_intono_display.py
--probe-self-test --cycles 0 --log ...` first records existing evidence, verifies
revision 4, then clears/injects/clears/rearms, checking telemetry after each step.
It deliberately clears retained evidence only in this explicit self-test mode.
Normal capture never clears. Six probe tests pass, including actual byte-wide
CSR access, injection isolation from video, and capture of a real event after
rearming. Six protocol tests verify these diagnostic commands do not access
profile storage and refuse active operations.

Revision 4 initial build (`intono-line-probe4`) was NOT flashed: final pixel-clock
timing was 71.09 MHz against required 74.25 MHz. The critical path was palette
RAM -> diagnostic RGB comparison -> sticky-event capture enable. Added a
diagnostic-only pipeline register for the comparison and matching event payload;
the video path is unchanged. All six probe tests still pass, including injected
transient coordinates/RGB and actual CSR readback. Rebuild uses artifact name
`intono-line-probe4p` so the failed timing report remains available separately.
Full pre-pipeline display/frame suite: 54 passed. Firmware size: 327144 bytes.

Pipelined revision 4 build completed and flashed successfully to slot 1:
`build/intono-line-probe4p-r5/intono-line-probe4p-24f78c-d-r5.tar.gz`.
All final timings pass: CPU 66.67/60 MHz, DVI 85.12/74.25,
DVI5x 432.90/371.33, audio 68.30/49.15. Firmware remains 327144 bytes
(536 spare); archive CRCs and 36864-byte storage reservation verified.
`/tmp/intono-line-probe4p-flash.log` ends with `Refresh: DONE`, exit 0.
Awaiting user launch to run the live self-test; no fault origin established yet.

## Live self-test passed

User launched revision 4 and reported no flashes this boot. Executed
`exercise_intono_display.py --probe-self-test --cycles 0` with transcript
`/tmp/intono-line-probe4p-self-test.log`. Initial PROBE=04000001 confirms revision
4, UI ready, armed mode, Arc surface. Initial fault/health words were zero.
All three fault registers returned exactly EA2923AB for injection (surface 3,
x=291, y=325, pixel AB), with RGBVAL=00112233. Clearing returned all four words
to zero; rearming returned PROBE=04000001. Every command acknowledged OK.
This validates the physical device's event latch, CDC, CPU-register readback,
and UART reporting path. Injection bypasses the real fault predicates, whose
coverage still has limits; it does not prove that a visually observed line must
trigger those predicates, nor verify the TMDS/monitor path. No actual flash was
captured during this boot. Probes left armed on tuner; no profiles changed.

## Revision 4 reproduction after self-test validation

User rebooted and observed three tuner flashes: blue lower down before content
rendered, then two yellow flashes higher near the cents readout, separated in
time and height. `/tmp/intono-line-probe4p-reproduced.log` shows all fault/health
words zero and PROBE=04000001 (revision 4, ready, armed, Arc) on every report.
The capture did not clear anything and closed normally after requesting tuner.

Startup review confirms a remaining temporal blind spot: firmware explicitly
publishes ui_ready=false and surface=15 for the loading screen; current probes
require ui_ready and surfaces 0/4/5. Thus the pre-content blue flash may precede
probe coverage. This does not explain the later flashes. The RGB probe only
checks indexed black pixels, and the spatial predicates do not cover all legal
text/marker regions. Clean captures still do not establish a serializer or
monitor fault. Obtain a whole-screen boot video to locate the transient pixels
and their timing relative to loading and first complete foreground frames before
selecting another spatial predicate. No new image flashed after this capture.

## ASUS VS239H-P comparison and phone video (2026-10-06)

User reports five clean reboots through an AVerMedia capture card, also no
reproduction on a small 720p display, then immediate reproduction on returning
to the ASUS VS239H-P. Whether cables/adapters stayed identical is unknown.
This is useful evidence of a sink/link dependency, not proof of a monitor defect.

Inspected all 30-fps frames around seven seconds in
`/Users/naenyn/Downloads/8381B567-8CBE-43C0-97CC-8B1FF911BC0D.MP4`.
Frame 224 (approximately 7.467 s) clearly contains the blue line; neighboring
frames do not. It starts immediately to the right of the enlarged `--` pitch
readout, crosses the circle, and reaches the right edge of the active display.
It occurs during the initial reveal of the tuner, with NO SIGNAL and no moving
pitch markers. It is NOT confined to the spiral or logical UI panel. The phone's
30-fps sampling does not establish its exact duration in 60-Hz display frames.
Extracted review images: `/tmp/intono-boot-video/full-01.png` through `full-03.png`;
`full-02.png` is the affected frame. No simultaneous serial recording of this
particular video boot has been established, so do not claim exact correlation
with an earlier all-zero diagnostic capture.

Checked `DVITimingGen` and fixed 1280x720p60 modeline: 1650 total pixels,
750 total lines, 74.25 MHz, positive sync; 45 kHz horizontal / 60 Hz vertical.
These rates match the ASUS manual's HDMI 720p60 entry. No timing change justified
by the manual. Official source:
https://dlcdnet.asus.com/pub/ASUS/LCD%20Monitors/ASUS_VS229VS239_UserGuide_English.pdf
(supported timings on printed page 3-8; image settings on 3-2 and 3-3).
Standard SPLENDID mode disables ASCR dynamic contrast. The manual's Clock/Phase
noise adjustments apply ONLY to VGA and are irrelevant to this HDMI test.

Added `tests/test_intono_tmds_scanlines.py`: independently decodes emitted TMDS
symbols, checks byte recovery, bounded disparity and all four blanking control
symbols through 260 full-width scanlines (332,800 active pixels). Covers every
constant byte value, a sparse bright-text-to-black transition, palette-like
transitions, all byte values and deterministic random pixels. Together with
existing encoder, serializer comparison and pixel-probe tests: 10 passed in
13.99 s, log `/tmp/intono-monitor-path-tests.log`. This checks digital logic,
NOT physical signal integrity, actual clock phase margins or sink decoding.
The reported 8.93-ns DVI-to-DVI5x cross-domain critical path in revision 4p's
timing report is a reset/enable path, not evidence of an 8.93-ns pixel transfer.

No confirmed root cause, production change, new bitstream or flash tonight.
Avoid a speculative timing/palette change that would obscure the comparison.
Keep revision 4p installed and its validated diagnostics for the next test:

1. Reproduce on ASUS with current settings and record them (including displayed
   resolution/refresh). Keep the same cable and port for the next comparison.
2. Switch only SPLENDID to Standard (ASCR disabled), repeat several boots and
   first visits to tuner/scales. If the line disappears, restore the original
   mode to check that reproduction returns. Do not factory-reset the monitor.
3. If unchanged, test another cable with the original monitor settings. An
   HDMI-to-DVI connection on the same ASUS is a further useful isolation test
   if the user already has an adapter; not necessary to purchase one yet.
4. Capture diagnostics concurrently with a reproduced video. If we return to
   gateware instrumentation, cover startup and observe the final PHY input/
   output instead of adding more spiral/keyboard bounds checks. The existing
   startup gate remains a real limitation of our negative evidence.

## Factory-path comparison and zero-fill experiment

User confirmed the ASUS is already in Standard mode and other bitstreams work
on this same monitor/cable. Do not continue treating monitor settings or cable
replacement as prerequisites. An Intono-specific difference is the leading
working hypothesis, with sink sensitivity still possible.

Source comparison: ordinary `Framebuffer` users construct `DVIPHY` with
`circular_shift=False`. Intono alone sets the framebuffer override True.
`top/rezo/top.py` also explicitly uses False; REZO variants have additional
floorplanned split load strobes, and beamrace uses the PHY default, so these
are not all identical implementations. Intono additionally opts into the
palette output register, frame exchange/DMA, overlay and zero spread spectrum.
The shared PHY encoder, PLL implementation and 720p modeline are not separate
Intono implementations. Dense placement itself remains a possible variable.

Added branch-only build selector `TILIQUA_INTONO_SERIALIZER=circular|zero-fill`;
default remains circular, invalid values fail. Test build `intono-line-zerofill`
uses zero-fill with seed 23, spread spectrum 0, same firmware and diagnostic
revision 4. This deliberately changes the serializer netlist, and therefore
placement can change too; improvement would implicate this implementation or
placement, not prove recirculation's logical behavior wrong. Digital serializer
equivalence, full scanline decoding, PHY elaboration and probe tests: 10 passed
(`/tmp/intono-zerofill-tests.log`). No claim of root cause yet.

Read-only pre-test capture `/tmp/intono-before-zerofill.serial.log` confirms
revision 4 ready on Arc, all pixel faults, buffer gaps and background errors zero,
calibration inactive, 8572 bytes stack unused. It did not clear evidence or send
page commands. Build log: `/tmp/intono-line-zerofill-build.log`.

Zero-fill image completed and qualified: DVI5x 409.17/371.33 MHz,
DVI 79.62/74.25, audio 69.31/49.15, CPU 69.08/60; all pass. Firmware is
byte-for-byte identical to revision 4p (327144 bytes, 536 spare). Archive
integrity and 36864-byte option reservation verified in
`build/intono-line-zerofill-r5/diagnostic-qualification.json`.
Diagnostic rearm command returned OK, confirming all output operations idle.
Flashed slot 1, exit 0; `/tmp/intono-line-zerofill-flash.log` confirms Refresh DONE.
Await user boot and ASUS reproduction; this is a comparison image, not a
confirmed fix. Default build selector remains circular for now.

### Zero-fill hardware result: rejected

User reports no HDMI lock / monitor goes dark with `intono-line-zerofill`.
Do not flash this artifact again as a candidate fix. Its same-domain timing
passes and digital-equivalence tests did not ensure physical HDMI operation.
This result does not prove the intermittent line has the same cause, nor that
zero-fill is intrinsically wrong: changing it also changed placement/routing.
Restore the exact previously working `intono-line-probe4p` archive to slot 1.
Investigate serializer load/word alignment and related-clock timing constraints
before another physical output change; do not just cycle implementation seeds
and treat a timing PASS as sufficient hardware qualification.

Restoration completed: flash exit 0 and Refresh DONE in
`/tmp/intono-line-restore4p-flash.log`. User must launch Intono from bootloader;
restored HDMI behavior remains awaiting confirmation.

## Local serializer reset-release investigation

The rejected zero-fill build's firmware is byte-identical to revision 4p.
Changing shift mode changes synthesis (especially the constant clock lane)
and placement; all four final same-domain clocks passed. That is not proof
of reset-release safety or related-clock word-transfer timing.

Found a structural hazard: the five-bit serializer phase ring is reset from
a pixel-clock-domain signal, both at PLL lock and framebuffer enable. Reset
release can reach the five fast-clock flops at different times. An invalid
ring can produce an invalid transmitted clock. This is a hypothesis consistent
with the no-lock report, not a confirmed cause of that report or the original
transient lines. The original video shows a line extending beyond the UI circle
next to the pitch readout during initial reveal, with no moving tuner points.

Candidate intono-line-localreset retains circular shifting and identical
firmware. Intono alone opts into asynchronous assertion / fast-clock
synchronized deassertion for both serializer reset sources. Other bitstreams
retain their current behavior. Restart tests check the actual serializer DDR
clock pairs at five reset phases, three restarts each, while varying live RGB;
all pass together with the existing serializer tests (8 passed). This validates
digital restart behavior, not physical timing or monitor behavior. Build and
exact rejected-route timing extraction are in progress.

Exact failed-image routing was regenerated with the original yowasp tool
and seed 23. The regenerated configuration SHA-256 matches top.config exactly
(615e1571398dbb2099e6824b71647da1bb6f5559fcb031171fc4a8bd054b499f).
Reports: build/intono-line-zerofill-r5/failed-detailed.{tim,json,sdf};
failed-routed.json. The pixel-clock-to-phase-ring reset critical path is
9.753 ns including clock-to-Q, logic, routing and setup. Endpoint propagation
values differ by 0.614 ns across phase bits (8.716..9.329 ns max). The fast
clock period is about 2.69 ns. This demonstrates a poorly controlled reset
crossing; reset edge alignment is not known, so it does not prove a sampled
wrong ring occurred on the user's boot. Pixel-data crossings need separate
analysis: the quoted 9.753 ns is NOT a pixel-data path.

The first local-reset candidate was rejected before flashing: final DVI5x
268.96/371.33 MHz. Its critical path combined two independently synchronized
resets through a LUT and long routing to phase reset. Revised implementation
combines PLL/enable requests BEFORE a single ResetSynchronizer and removes
redundant framebuffer serializer ResetInserter. Revised restart/serializer
tests: 6 passed; /tmp/intono-combined-reset-tests.log. New candidate
intono-line-combinedreset is building with the same circular mode and seed23.

Remaining independent hypothesis: serializer load phase relative to the pixel
word update is not explicitly established by the free-running phase ring.
Same-domain timing PASS does not establish the bundled 10-bit word's capture
margin across the related clocks. Some final pixel-data route segments in the
failed image approach a fast-clock period before clock-to-Q/setup are included;
that alone is NOT a violation because the actual load phase is not known.
A future controlled comparison can derive the word-load boundary from a pixel
clock toggle synchronized into the fast domain, allowing several fast cycles
for the bundled word to settle. Do not mix this architectural change into the
reset experiment or assert that either hypothesis explains the original video.

The combined-reset candidate passed serializer timing (403.39/371.33 MHz),
but failed pixel timing (68.22/74.25 MHz); NOT FLASHED. The critical path is
the diagnostic raw-region arithmetic into FirstPixelFault's hold enable.
Added an observer-only event register for bad flag, ScanPixel, surface and
control before the sticky latch; rendered streams are unchanged. Twelve
probe/restart/serializer tests pass (/tmp/intono-reset-observer-tests.log).
intono-line-combinedresetp builds with that correction; still seed23, circular
serializer mode, same firmware. Rejecting timing-failed candidates is required.

Qualification lesson: digital equivalence and the four same-domain frequency
checks were insufficient evidence for a physical serializer substitution.
Reset-release and bundled-word crossing timing must be reviewed explicitly,
and the physical sink result remains part of qualification. Existing pixel
fault logs observe upstream of TMDS/physical output; their startup gate also
limits negative evidence. They cannot rule out a post-observer link failure.

Current reset/observer candidate firmware is byte-identical to revision4p:
327144 bytes, SHA-256 b6d59aa50378d327c948d67dad5b14216cd89ae995ce2596e7b9c2fb48decb01.
Synthesized block RAM50 and DSP14 are unchanged. Netlist confirms all five
phase-ring reset pins directly share the final fast-clock synchronizer flop
(no intervening LUT). Read-only preflash UART capture returned zero bytes
(/tmp/intono-before-combinedresetp.serial.log); no commands were sent and
this alone is not confirmation of restored monitor operation.

intono-line-combinedresetp routing was stopped after over20 minutes cycling
through congestion (not flashed, no final timing result). Simplified only
observer coordinate predicates: physical x>=threshold+offset instead of
(x-offset)>=threshold, and rotated constant y bounds converted to physical
x bounds. This removes carry chains before the same comparisons; pipeline
event fields remain aligned. New comparison candidate: intono-line-resetguard.

## Qualified reset/guard candidate flashed

intono-line-resetguard completed: DVI5x424.99/371.33MHz, DVI81.27/74.25,
audio70.81/49.15, CPU64.90/60; all final clocks pass. Clock reset critical
path is now a fast-clock register directly to the DDR output reset, 2.35ns;
all five phase reset pins directly share that same-clock synchronizer output.
Archive/CRC and option reservation36864 verified. Firmware identical to4p.
Guard simplification removes634 LUT4s versus the congested candidate.
Thirteen tests pass including normal/rotated exact guard-boundary captures.

Flashed slot1 with exit0, RefreshDONE; /tmp/intono-line-resetguard-flash.log.
Qualification: build/intono-line-resetguard-r5/diagnostic-qualification.json.
Asked user to launch from factory bootloader and confirm HDMI lock. Capture
/tmp/intono-line-resetguard.serial.log is waiting for telemetry; then one
TUNER/SCALES/CAL navigation cycle without modifying profiles/starting outputs.
Physical no-lock regression and original transient-line resolution are both
unconfirmed pending that launch/test. No root-cause claim for the original
line and no merge to naenyn.

Launch capture timed out after120 seconds with no diagnostic telemetry; no
page/probe commands were sent. /tmp/intono-line-resetguard-capture.log.
Serial port closed normally by the script. The qualified image is flashed,
but manual launch and monitor feedback remain required.

## Clean production candidate qualification

Removed temporary observers, diagnostic CSR extensions/UART commands, the host
capture tool, and the experimental serializer selector. Kept production health
reporting and circular shifting. Seven serializer/reset/scanline tests and 42
production display/frame/TMDS tests pass (49 total).

First cleaned candidate, `intono-reset-clean` seed23, was NOT flashed: final
pixel-clock timing72.70/74.25MHz failed, while serializer406.50/371.33,
audio66.97/49.15 and CPU67.85/60 passed. Pixel critical path is FIFO first-word
resynchronization/read-pointer logic (3.29ns logic,10.47ns routing), not the
serializer reset. Firmware326752 bytes (928 spare); saved-profile formats and
36864-byte option reservation unchanged. Netlist confirms all five phase reset
pins directly share the final fast-clock synchronizer register.

Retry uses normal Intono placement seed18 with the same circuit, tests and
firmware. No claim that placement alone proves physical HDMI safety; strict
final timing, direct-reset netlist check, archive validation and hardware test
are still required before this is ready to merge.

Seed18 cleaned candidate completed and qualified: serializer416.49/371.33MHz,
pixel81.93/74.25, audio67.95/49.15, CPU64.35/60 (all PASS). Archive files match
disk and manifest CRCs, options reservation36864 verified, firmware326752 bytes.
Direct same-clock reset connectivity verified for all five phase registers.
Qualification: build/intono-reset-clean18-r5/qualification.json.
Flashed slot1 successfully; /tmp/intono-reset-clean18-flash.log, Refresh DONE.
User must launch Intono from the factory bootloader and repeat first visits to
TUNER/SCALES and several reboots before committing/merging this cleaned image.
The branch remains uncommitted; naenyn is unchanged.

## Cleaned build hardware acceptance

The user confirms the flashed seed18 cleaned build looks good and authorizes
merging into naenyn. This is the accepted production candidate. The earlier
resetguard image also passed multiple user reboots without reproducing the
artifact. Reset synchronization remains the leading explanation, rather than
a conclusively observed cause of the original transient lines.
