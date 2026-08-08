# REZOMO development handoff

This file is the starting context for the next Codex task working on REZOMO.
Read
it together with [`BUILD_PERFORMANCE.md`](BUILD_PERFORMANCE.md) and
[`Rezo_Feature_Ideas_By_Complexity.md`](Rezo_Feature_Ideas_By_Complexity.md)
before changing the design. [`REZOMO_USER_GUIDE.md`](REZOMO_USER_GUIDE.md) is
the complete operator documentation for this clocked variant;
[`REZO_USER_GUIDE.md`](REZO_USER_GUIDE.md) documents the original BANK/FILTER
bitstream.

## 2026-08-07 REZOMO release candidate

The clocked variant now has its own operator-facing identity: **REZOMO**. The
tile header, legacy beam header, bitstream manifest, and help text all use the
new name. `pdm run rezomo` is the preferred build alias; `pdm run rezo` remains
available as a source-compatible alias and also defaults to the REZOMO manifest
name. Internal `Rezo*` class names and the persisted `REZO` record magic remain
unchanged deliberately, avoiding an unnecessary logic and save-format
migration.

[`REZOMO_USER_GUIDE.md`](REZOMO_USER_GUIDE.md) is the complete operator guide.
It documents BANK from signal flow through every supporting page, then CLOCK,
the shared controls, input roles, all four algorithms, persistence, and patch
examples. The old partial clocked guide was removed; the original
[`REZO_USER_GUIDE.md`](REZO_USER_GUIDE.md) remains the guide for the separate
BANK/FILTER bitstream.

All 39 comparison, display, UI, and persistence tests pass. The pre-commit
seed-9 REZOMO build uses 20,737 LUT4, 24,081 packed cells (207 free), 6,519 FF,
and 18 BRAM. Final timing passes at 418.24 MHz DVI5X, 77.02 MHz AUDIO, 60.10 MHz
SYNC, and 76.07 MHz DVI. The archive is
`gateware/build/rezomo-r5/rezomo-16da16f7-r5.tar.gz`; it has not been flashed.
The `top.bit` SHA-256 is
`672f7fac86ff5b6e0ad57a9b6cd0797535d4e5181e1ef787ab9be3887088275e` and the
archive SHA-256 is
`25bbd63b5a434420c4a9aa19b74990b25b6233fab1cf6740f7551bf9f19f2614`.

## 2026-08-07 CLOCK alignment polish candidate

The current working tree corrects the two remaining CLOCK settings-page
alignment issues found during hardware testing. All four algorithm names now
share one 136-pixel MODE box centered between the character-grid positions of
odd- and even-length names. This holds every name within four pixels of the
same center without adding a mode-dependent pixel shifter. The two parameter
columns use 160-pixel value boxes instead of 176-pixel boxes. DIRECTION,
SOURCE, and BPM move one 16-pixel character cell inside the content panel;
their existing value text becomes naturally centered in the narrower boxes.
The full-width power-of-two DEPTH slider and its resource savings are retained.

The fixed comparator-friendly MODE rectangle also improves synthesis. Relative
to CLOCK-DEPTH-SLIDER-S8, this candidate saves another 108 LUT4 and 120 packed
cells with no FF or BRAM increase. All 27 REZO tests pass. The exact seed-9
route uses 20,737 LUT4, 24,081 packed cells (207 free), 6,519 FF, and 18 BRAM.
It passes at 389.11 MHz DVI5X, 76.61 MHz AUDIO, 61.24 MHz SYNC, and 79.29 MHz
DVI. Seeds 1--6 and 8 were rejected for timing; seed 7 was stopped as a
congestion outlier. The archive is
`gateware/build/rezo-r5/rezo-16da16f7-r5.tar.gz`. The `top.bit` SHA-256 is
`fea0900e3b6c30868d58593334874751d3a786f5dfd31d8e41930365673abc23` and the
archive SHA-256 is
`b44cef4757ab3eb067649451cacc58aad2a8d156943b492c9ae809993542ddfb`.

## 2026-08-07 full-width CLOCK DEPTH and optimization candidate

The current working tree replaces CLOCK's numeric DEPTH value box with a
full-width slider spanning both settings columns. It retains the saved 0--16
parameter and therefore the same seventeen steps from 0 through 100 percent.
The 512-pixel interior maps each step to exactly 32 pixels, allowing the fill
endpoint to use a five-bit shift. The obsolete three-character numeric table,
its synchronizer, and three text-writer scan slots are removed. The operator
guide and display regression test describe and verify the new control.

This change is also the retained result of the post-UI optimization pass.
Relative to the previously flashed CLOCK-FIXED-DIRECTION-S8 candidate it saves
29 LUT4, 5 packed cells, and 10 FF. Two more aggressive experiments were
measured and reverted. A shared 60-bit CLOCK-name ROM passed focused tests but
made routing impractically slow. Fixing WALK's hidden legacy step in the source
unexpectedly increased the mapped design to 24,289 packed cells, one beyond
capacity. Removing WALK's now-unread display crossing similarly changed ECP5
packing to 24,342 cells. The benign crossing is retained because its exact
structure produces the smaller, timing-clean route; it does not affect the
display or user-visible behavior.

All 27 REZO tests pass. The exact seed-8 route uses 20,845 LUT4, 24,201 packed
cells (87 free), 6,519 FF, and 18 BRAM. It passes at 382.70 MHz DVI5X, 74.10
MHz AUDIO, 60.37 MHz SYNC, and 77.86 MHz DVI. The archive is
`gateware/build/rezo-r5/rezo-16da16f7-r5.tar.gz`. It was deliberately not
flashed because the rack was powered down. The `top.bit` SHA-256 is
`ad9d997be98007c1a97761df22eb0da75d2a6fc8180112d62c78e4301450ef62` and
the archive SHA-256 is
`232884b1e41183fe62c77ae86eeb0c16a66810fe2e20eb865892b84309c8d4f6`.

## 2026-08-07 CLOCK UI and continuous-BPM candidate

The current working tree polishes the CLOCK settings page without beginning
the planned post-UI optimization phase. MODE now uses the same selector
geometry as BANK's PRESET. Shared controls form the left column (DIRECTION,
SOURCE, BPM, DEPTH), while algorithm-specific controls form a right column.
Labels are right-aligned against equal-width value boxes and all values are
centered. Direction and source names are no longer abbreviated: the UI can
show FORWARD, REVERSE, PING PONG, RANDOM, AUTO INT, AUTO EXT, INTERNAL, and
EXTERNAL. SHIFT's AUTO DATA states show AUTO CV and AUTO RAND. WALK's
user-facing HEAD name is now BAND; internal constant names remain unchanged.
The shared label is now DIRECTION, and all four shared rows stay fixed in every
mode. WALK displays read-only RANDOM and navigation skips that row; its hidden
legacy step field is normalized to the fixed default. ROTATE exposes only
FORWARD/REVERSE. TURING exposes
FORWARD/REVERSE/PING PONG, changing direction once per complete loop-length
traversal. The MODE value box is offset per visible name width so each submode
is centered without adding a pixel shifter to the timing-sensitive DVI path.

TURING's right column is ordered CHANGE, BANDS, then its range geometry.
BANDS ALL shows LENGTH in row three. BANDS RANGE shows START in row three and
moves LENGTH to row four. Navigating forward follows the same visual order.
Editing START automatically shortens LENGTH when necessary, so a freshly
selected full-length RANGE is not stuck at START 1.

The internal BPM is now any integer from 15 through 300. A slow encoder detent
changes one BPM and a rapid detent changes eight. Period and three-digit label
tables use block ROMs instead of a runtime divider or wide LUT mux. Exact BPM
uses the former three-bit rate field plus its six trailing padding bits, so the
46-word V3 record does not grow or move later fields. A saved record from the
old eight-rate build is recognized by zero high bits and maps its old index to
15, 30, 45, 60, 90, 120, 180, or 240 BPM. New saves restore their exact BPM.
All other CLOCK parameters remain saved; transient modulation patterns remain
deliberately unsaved.

All 27 REZO tests pass. The exact seed-8 route uses 20,874 LUT4, 24,206 packed
cells (82 free), 6,529 FF, and 18 BRAM. It passes at 381.53 MHz DVI5X, 78.21
MHz AUDIO, 60.15 MHz SYNC, and 74.68 MHz DVI. The archive is
`gateware/build/rezo-r5/rezo-c8706835-r5.tar.gz` and was flashed to slot 4.
The `top.bit` SHA-256 is
`66907a00859a65295e46684a9350ecd5361adebf78e97fb254edbdc341726621` and
the archive SHA-256 is
`a92690006ed7de878052263b267dda95312b90b1c3e8667f62d5513870488bca`.

## 2026-08-06 CLOCK HEAD temporal-stumble candidate

Commit `c8706835` checkpoints the tested and flashed simultaneous WALK. The
current working tree adds a second WALK STYLE plus temporal drunkenness without
widening the global two-bit algorithm selector:

- `ALL` is the checkpointed behavior: all enabled bands independently step on
  every clock;
- `HEAD` moves one spatial cursor randomly up or down and changes only its
  landing band;
- disabled bands are skipped without consuming a cursor step;
- the cursor reflects at physical bands 1 and 10 rather than wrapping; and
- every spatial move is exactly one enabled band, while DRUNK 1--4 sets the
  total number of rapid landings in a possible stumble;
- CHANCE offers 0, 10, 25, 50, 75, and 100 percent stumble probabilities; and
- extra landings occur on quarter-interval subdivisions, giving DRUNK 4 a
  sixteenth-note feel under a quarter-note clock.

Both styles share the existing five WALK step sizes, bipolar value reflection,
CLOCK DEPTH, and RESET. Changing STYLE clears the transient vector and cursor.
The first external pulse measures the beginning of an interval; subsequent
pulses can launch measured stumbles. The internal clock already knows its
period. The CLOCK page reuses TURING-exclusive rows for STYLE, DRUNK, and
CHANCE, avoiding new navigation target IDs. SAVE DEFAULT stores one style bit,
two drunkenness bits, and a three-bit chance index in V3's existing padding;
the record remains 46 words. A save from `c8706835` therefore restores safely
as `ALL / DRUNK 1 / CHANCE 25`.

The first temporal scheduler kept three wide counters and left only 159 packed
cells free, producing pathological routing. The retained form uses the existing
clock counter for both internal timing and external period measurement, and
stores burst thresholds at 16-audio-sample resolution (83 microseconds at 192
kHz). This recovers 61 packed cells and 45 FF without changing musical timing.
All 39 REZO tests pass, including explicit DRUNK-4/CHANCE-100 and
DRUNK-4/CHANCE-0 event-count regressions.

The exact seed-6 route uses 20,724 LUT4, 24,068 packed cells (220 free), 6,485
FF, and 16 BRAM. It passes at 400.64 MHz DVI5X, 75.68 MHz AUDIO, 61.50 MHz
SYNC, and 75.00 MHz DVI. Seed 8 misses only SYNC at 59.18 MHz and seed 1 is
substantially worse. The archive is
`gateware/build/rezo-r5/rezo-c8706835-r5.tar.gz` and was flashed to slot 4.
The seed-6 `top.bit` SHA-256 is
`c978dafabd4424fd7ca54391c5157f80cede40b305ade287464743c2b32615c8` and
the archive SHA-256 is
`3f75378e6a60f3df9df016ac426a6d4582bd41cf611944a98ed30dffd7e21872`.

## 2026-08-06 CLOCK WALK candidate

The current working tree adds WALK as the fourth CLOCK algorithm. Each
accepted clock advances every enabled band independently by one positive or
negative bipolar modulation step. Requested motion reflects before the
half-scale signed rails instead of clipping or wrapping, so values remain
bounded and continue moving at either edge. Disabled bands remain zero, RESET
clears the complete walk, and shared CLOCK DEPTH scales the result without
altering the underlying state.

The CLOCK page reuses the `DIR / STEP` row: SHIFT, ROTATE, and TURING continue
to edit direction there, while WALK offers step values 1, 2, 4, 8, and 16.
SAVE DEFAULT includes the three-bit WALK step index in the existing 46-word V3
record. It consumes three formerly zero padding bits, reducing padding from 15
to 12 bits without moving any established field. A V3 record written by the
immediately preceding build therefore imports safely with WALK step 1; V1/V2
records still receive the normal CLOCK defaults and WALK step 4.

The first WALK implementation used a shared 17-bit add/subtract and two 17-bit
comparisons. It fit with only 293 packed cells free, but seed 2 failed SYNC at
54.38 MHz and was not flashed. Since all WALK values and steps have eight zero
low bits, the final implementation performs identical arithmetic in signed
high-byte units. It also replaces the deep four-algorithm selector mux with a
wrapped two-bit increment/decrement. This recovers 250 LUT4 and 248 packed
cells from the failed attempt.

All 38 REZO tests pass. The exact seed-2 route uses 20,417 LUT4, 23,747 packed
cells (541 free), 6,439 FF, and 16 BRAM. It passes at 443.85 MHz DVI5X,
72.80 MHz AUDIO, 62.68 MHz SYNC, and 77.89 MHz DVI. The archive is
`gateware/build/rezo-r5/rezo-965f4783-r5.tar.gz` and was flashed to slot 4.
The seed-2 `top.bit` SHA-256 is
`68377a1bb2bb55bd47d27c1b4fccd2e508941fe9942c0fbf2321509c5b3b5e98` and
the archive SHA-256 is
`8b058eff7ee0e4bb16e521f43694e0cac74d3b4c9197ebd57e6b664b0483469b`.

## 2026-08-06 CLOCK version-3 persistence checkpoint

The current working tree adds backward-compatible CLOCK persistence on top of
the SHIFT internal-random candidate. SAVE DEFAULT now retains BANK/CLOCK mode,
algorithm, direction, clock source and internal BPM, CLOCK depth, SHIFT DATA
source, TURING length/change/target/start, and all four bits of every INPUT
target. The live SHIFT/ROTATE/TURING modulation pattern remains transient.

The V3 record remains 46 words, equal to V2. It reuses six bytes of FILTER's
removed modulation matrix, so all established BANK fields keep their exact
locations. The journal accepts V1 (42-word) and V2 (46-word) records; during a
legacy import it replaces the repurposed words with safe CLOCK defaults and
supplies the established V2 band tail for V1. A same-length V2 regression
specifically verifies that obsolete FILTER bytes cannot become CLOCK settings.

At this checkpoint, live CLOCK controls were copied to a 33-bit shadow snapshot on SAVE and applied
from that shadow once after LOAD. This keeps the circular state-scan mux out of
the clock sequencer's timing paths. Directly scanning the live controls fit but
missed SYNC across seeds 1, 2, 3, 5, and 7. The retained shadowed seed-2 route
uses 19,887 LUT4, 23,199 packed cells (1,089 free), 6,409 FF, and 16 BRAM. It
passes at 400.00 MHz DVI5X, 74.92 MHz AUDIO, 60.76 MHz SYNC, and 81.78 MHz DVI.
All 36 REZO tests pass. The archive is
`gateware/build/rezo-r5/rezo-965f4783-r5.tar.gz` and was flashed to slot 4.
The seed-2 `top.bit` SHA-256 is
`abb4115d27cc8836bfae3be1fbaa62c263b491e8d83bc36eb3471462eedf318d` and
the archive SHA-256 is
`cb0a0fb94f27eb58eadbebba0207f6d961c9e8af65ff23810a5eff6017a3b77e`.

## 2026-08-06 SHIFT internal random DATA candidate

Commit `965f4783` checkpoints the tested and flashed TURING block-RAM
optimization. The current working tree adds a reusable DATA source selector to
SHIFT:

- `CV` (default) samples the existing INPUT-page DAT assignment;
- `RAND` samples an independent 32-bit maximal-length bipolar generator that
  advances continuously at the accepted 192 kHz audio sample rate; and
- `AUTO` follows physical patch detection for the assigned DAT jack, selecting
  external CV while patched and internal random while unpatched. The display
  reports `A CV` or `A RND` for the effective AUTO choice.

The selector reuses TURING TARGET's y=420 CLOCK-page row because the controls
are algorithm-exclusive. ROTATE ignores DATA, while TURING retains its own
independent mutation generator. Shared CLOCK DEPTH scales CV and random SHIFT
captures identically. The version-3 persistence candidate above saves DATA
source with the other CLOCK settings.

All 34 REZO tests pass. New coverage verifies CV compatibility, RAND ignoring
external voltage, AUTO physical-jack switching, selector navigation/cycling,
and display geometry. The exact seed-2 route uses 19,664 LUT4, 22,980 packed
cells (1,308 free), 6,409 FF, and 16 BRAM. The complete feature costs only 45
LUT4, 45 packed cells, and 46 FF over the TURING-BRAM checkpoint, with no new
BRAM or multiplier. It passes at 436.11 MHz DVI5X, 74.37 MHz AUDIO, 64.77 MHz
SYNC, and 77.10 MHz DVI. Seed 1 was rejected for DVI5X and DVI misses; seeds 6
and 8 were stopped after seed 2 passed.

The archive is `gateware/build/rezo-r5/rezo-965f4783-r5.tar.gz` and was flashed
to slot 4. The seed-2
`top.bit` SHA-256 is
`61c614fcd651d973fc35f68093173d50b576cfa838dc3dbbf97a486091827362` and
the archive SHA-256 is
`126566148eb630751ea1f08efc9133a213be8ee6b37a84608c2261ae40b42dc4`.

## 2026-08-06 TURING block-RAM optimization candidate

Commit `c9be114a` checkpoints the tested and flashed TURING targeting/depth
feature. The current working tree makes a behavior-preserving area trade:

- the private 10-by-16-bit TURING loop now uses one synchronous block RAM
  instead of ten registers behind large dynamic read/write muxes;
- a short sequential clear/read/write/prime worker preserves deterministic
  initial fill, mutation, forward/reverse locked rotation, ALL repetition,
  disabled-band skipping, and RANGE remapping; and
- CLOCK input acceptance pauses while that worker is active, so no partially
  shifted pattern can reach the audio path. A ten-step update remains far
  shorter than one 192 kHz audio sample interval.

All 33 REZO tests pass. The exact seed-1 route uses 19,619 LUT4, 22,935 packed
cells (1,353 free), 6,363 FF, and 16 BRAM. Relative to the flashed
CLOCK-TARGET-DEPTH-S7 build, it recovers 886 LUT4, 896 packed cells, and 110 FF
at the cost of one BRAM. It passes at 415.45 MHz DVI5X, 73.06 MHz AUDIO,
61.58 MHz SYNC, and 76.09 MHz DVI. Seeds 2, 6, and 8 were rejected for small
timing misses; longer seed-4 and seed-7 congestion searches were stopped once
seed 1 passed.

The archive is `gateware/build/rezo-r5/rezo-c9be114a-r5.tar.gz` and was flashed
to slot 4. The seed-1
`top.bit` SHA-256 is
`27a40d83c4eefb714c9b138000ec254f46cc377009c5b563c0d2f8f95ba9a957` and
the archive SHA-256 is
`12a3fb6dfc2de15e78c61be14d2dfe64b4fbe47079c8d0bcd78a44f2b141647f`.

## 2026-08-06 TURING target and shared CLOCK depth candidate

The current working tree extends every CLOCK algorithm with a shared DEPTH
control and makes short TURING patterns useful in two distinct ways:

- DEPTH scales SHIFT, ROTATE, and TURING modulation from 0 to 100 percent in
  17 steps without changing the underlying clock pattern;
- TURING TARGET `ALL` repeats a short pattern across every enabled band,
  skipping disabled bands without consuming a pattern step;
- TARGET `RANGE` maps one copy of the pattern onto physical bands starting at
  the one-based START value, leaving bands outside the range unmodulated; and
- RANGE length is clamped at the upper edge while target/start edits remap the
  existing loop rather than regenerating it.

All 33 REZO tests pass. New regressions cover positive and negative shared
depth scaling, disabled-band-aware ALL repetition, RANGE mapping to bands 6--8,
and CLOCK-page navigation/display for DEPTH, TARGET, and START.

The exact seed-7 route uses 20,505 LUT4, 23,831 packed cells (457 free), 6,473
FF, and 15 BRAM. It passes at 389.11 MHz DVI5X, 74.71 MHz AUDIO, 61.17 MHz
SYNC, and 74.81 MHz DVI. Seeds 3 and 4 failed only SYNC; the initial seed-8
build failed DVI5X and DVI. The archive is
`gateware/build/rezo-r5/rezo-7f6819a3-r5.tar.gz` and was flashed to slot 4.
The seed-7 `top.bit` SHA-256 is
`2da8bc3dd36e9da855c334706103c7a13dbea9960c777f824341e4b9fe34583b` and
the archive SHA-256 is
`600b07f57c73d49978c68f708454d3a3640ccc574578a7a3cb0e06c033eededb`.

This route is tight at 98 percent packed utilization. Treat another substantial
feature as an optimization task first rather than assuming the remaining 457
cells are usable routing headroom. CLOCK controls remain transient until a
version-3 persistence record is designed.

## 2026-08-06 internal clock and AUTO source candidate

The current working tree extends the TURING candidate with a shared internal
clock source used by SHIFT, ROTATE, and TURING:

- SOURCE choices are AUTO (default), INT, and EXT;
- AUTO reads the audio board's physical jack detector for whichever INPUT is
  assigned to CLK, rather than inferring presence from pulse activity;
- the display reports `AUTO I` or `AUTO E` for the effective source;
- internal rates are 15, 30, 45, 60, 90, 120, 180, and 240 BPM, defaulting to
  120 BPM; and
- cable/source/rate changes cannot generate a clock: internal operation waits
  a full new interval, while external operation requires a low level followed
  by a fresh rising edge.

All 33 REZO tests pass. They cover source overrides, physical-patch AUTO
selection, insertion while the gate is high, unplug fallback timing, the eight
BPM UI choices, CLOCK-page navigation/display, and every earlier DSP,
persistence, SHIFT, ROTATE, and TURING regression.

The exact seed-8 route uses 19,524 LUT4, 22,760 packed cells (1,528 free),
6,105 FF, and 15 BRAM. It passes at 399.20 MHz DVI5X, 72.70 MHz AUDIO,
63.61 MHz SYNC, and 80.33 MHz DVI. Seed 7 failed only DVI at 71.25 MHz;
seed 6 failed DVI5X and SYNC. The archive is
`gateware/build/rezo-r5/rezo-7f6819a3-r5.tar.gz` and was flashed to slot 4.
The seed-8 `top.bit` SHA-256 is
`461e4a90d7f7e58de1421204581698df09730c6e977bc3ceafbb2c4c8487667e` and
the archive SHA-256 is
`399a368b7b570ccacd65ad8e4035d45a427d5803572feff43e22b59779c2a17a`.

SOURCE and BPM remain transient alongside the other CLOCK settings until a
version-3 state record is designed. A future internal DATA source should reuse
this source-selection model but does not need to change the clock engine.

## 2026-08-06 CLOCK TURING candidate

Commit `7f6819a3` checkpoints the tested SHIFT/ROTATE implementation. The current
working tree adds TURING as a third algorithm:

- a full-resolution internally randomized looping modulation register;
- an active-high `LCK` INPUT target: high repeats the loop exactly, while low
  permits mutation according to CHANGE;
- LENGTH 2..10 over the first enabled bands, skipping disabled bands;
- CHANGE choices of 1, 3, 6, 12, 25, 50, and 100 percent;
- forward and reverse directions, with RESET deliberately ignored; and
- a sequential search/write worker that avoids ten parallel wide value muxes.

The first LENGTH pulses seed the loop even if LCK is already high, so an empty
loop cannot be locked. Changing algorithm or length starts a fresh fill. TURING
uses additive modulation over the untouched BANK levels, like ROTATE.

All 32 REZO tests pass, including exact locked repetition, 100% mutation,
forward/reverse movement, disabled-band skipping, length limiting, RESET
immunity, UI navigation, and display coverage. The exact seed-7 route uses
19,135 LUT4, 22,307 packed cells (1,981 free), 6,051 FF, and 15 BRAM. It passes
at 394.94 MHz DVI5X, 74.58 MHz AUDIO, 61.08 MHz SYNC, and 80.28 MHz DVI. The
archive is `gateware/build/rezo-r5/rezo-7f6819a3-r5.tar.gz` and was flashed to
slot 4. The seed-7 `top.bit` SHA-256 is
`dac028b76ea47585a1ae01d40a5f9e27106b3e4cabc0892c7435fe6fe7d8f7bf` and
the archive SHA-256 is
`0f5a865463b67368371b614ca5e6d78dd707850681d473432de5d2f7de12270d`.
Seed 4 failed SYNC at 56.93 MHz; seed 6 failed DVI5X and SYNC.

At this checkpoint, an internal LFO/noise DATA source and future WALK mode
could build on the shared clock engine without changing TURING's self-contained
random generator; both were implemented in the later checkpoints above.

## 2026-08-06 CLOCK SHIFT/ROTATE checkpoint

The first external-clock MVP was implemented and is now incorporated into
[`REZOMO_USER_GUIDE.md`](REZOMO_USER_GUIDE.md):

- BANK/CLOCK mode selector on the main page;
- BANK-equivalent CLOCK main controls plus a separate direction settings page;
- SHIFT and additive BANK-shape ROTATE algorithms with mode-specific directions;
- DATA, CLOCK, and RESET INPUT-page targets, defaulting to IN2, IN3, and IN1;
- ten captured bipolar SHIFT values or circulating BANK-level ROTATE origins,
  overlaid as modulation on the untouched BANK shape;
- rising-edge clock detection with high/low hysteresis;
- SHIFT forward/reverse/random and ROTATE forward/reverse/ping-pong directions;
- reset clearing the vector and restarting ping-pong/random state; and
- automatic exclusion of all CLOCK-role jacks from normal audio/CV routing.

All 31 REZO tests passed at this checkpoint, including exact BANK DSP vectors and CLOCK direction,
hysteresis, reset, INPUT-target routing, navigation, and display coverage. The
latest dirty seed-4 route uses 18,306 LUT4, 21,448 packed cells (2,840 free),
5,953 FF, and 15 BRAM. It passes at 449.24 MHz DVI5X, 72.82 MHz AUDIO,
61.24 MHz SYNC, and 79.00 MHz DVI. Its archive is
`gateware/build/rezo-r5/rezo-176cfc5e-r5.tar.gz` and was flashed to slot 4.

The CLOCK controls and live vector are intentionally absent from persistence
until a version-3 record is designed.

## 2026-08-06 `rezoclocked` BANK-only baseline

Branch `rezoclocked` now has a clean, buildable foundation for replacing
FILTER with a shared clocked band-transformation mode. Commit `8a27f1a7`:

- removes FILTER response generation and modulation from `RezoCore`;
- removes FILTER/MATRIX navigation, controls, display pages, faders, and the
  display-side modulation-matrix RAM;
- makes BANK input mixing, feedback, enable masking, output sends, and DRY
  routing unconditional;
- retains the old FILTER bit positions only as inert version-2 persistence
  placeholders, preserving every later BANK field and the fine-frequency
  padding layout byte-for-byte; and
- removes FILTER-only regressions while retaining the BANK audio-cycle,
  known-good DSP, UI, display, and persistence coverage.

All 27 REZO tests pass. The exact commit-stamped seed-1 build passes every
clock and produces
`gateware/build/rezo-r5/rezo-8a27f1a7-r5.tar.gz`. It was deliberately not
flashed. The bitstream SHA-256 is
`cd4471e3034dba751b3cf568fdfbe5b2d78e67d386d6fbaed434b8a1992db2a8`;
the archive SHA-256 is
`bc9e97dc693a7dec9a6f88d1e5313737f7a9a8a0f77475f781e07c823df191a6`.
Its measured resources are 16,512 LUT4, 19,508 packed cells (4,780 free),
5,578 FF, and 15 BRAM. Final clocks are 443.07 MHz DVI5X, 76.24 MHz AUDIO,
61.16 MHz SYNC, and 80.57 MHz DVI.

Relative to the flashed `b2812acc` release candidate, this recovers 4,715
packed cells, 4,099 LUT4, 773 FF, and four BRAM. This is the formal baseline
for CLOCK work. Do not spend the entire margin at once: preserve enough room
for physical clock conditioning, a ten-value double buffer, new UI text and
geometry, tests, and routing variability.

Recommended first CLOCK increment:

1. Reintroduce the top-right BANK/CLOCK selector and use the former FILTER page
   slot for a compact CLOCK main page.
2. Establish fixed MVP input roles in CLOCK mode: IN0 audio, IN1 sampled value,
   IN2 clock, and IN3 reset. Avoid a routing matrix until hardware behavior is
   proven.
3. Implement one rising-edge conditioner with hysteresis and minimum spacing.
4. Feed one shared ten-band state engine with SHIFT first. Add ROTATE and WALK
   as operations over the same state/indexing only after SHIFT is verified.
5. Publish a completed vector atomically into the existing smoothed band-level
   path; keep BANK levels untouched so returning to BANK restores its shape.
6. Reuse the old persistence positions in a version-3 record only after the
   CLOCK state and controls are settled.

The existing `REZO_USER_GUIDE.md` continues to document the released `rezo`
bitstream. Write a separate clocked guide, or revise it, once CLOCK behavior is
stable enough to test on hardware.

## 2026-08-05 UI polish pass

The hardware review led to a consistency and legibility pass:

- BANK PRESET, BANDS PRESET, and FILTER TYPE now share one selector geometry;
  their labels are vertically aligned and each value is centered by its own
  visible width.
- BANK and FEEDBACK use `FREQ:` instead of the abbreviated `FRQ`.
- FEEDBACK navigation now follows the screen from top to bottom: page, ten
  band toggles, then KNEE, CEIL, and DAMP.
- ADVANCED is now OPTIONS. PALETTE and SAVE DEFAULT share a right-aligned label
  column, equal button spacing, and centered button text.
- Disabled BANK bands retain a dim empty frame on BANK and FEEDBACK, plus dim
  top/bottom ghost rails at all four GROUPS assignments, instead of
  disappearing completely.
  FILTER still exposes all ten resonators, and the BANDS page retains its
  explicit enable buttons.
- BANK/FILTER changes now slew the existing ten shared band gains toward the
  new mode's targets. A full-scale transition takes about 1.33 ms at 192 kHz,
  avoiding an instantaneous gain-vector change without adding an output
  multiplier or transition counter.

All 35 targeted tests pass. The exact commit-stamped native-Yosys W160 design
uses 24,090 packed cells (198 free), 169 fewer cells than the prior flashed
build. Seed 7 passes all four clocks at 403.55 MHz DVI5X, 72.91 MHz AUDIO,
66.67 MHz SYNC, and 74.95 MHz DVI. Seeds 6 and 8 fail only DVI; seed 8 is short
by 0.12 MHz.

The first polish archive was
`gateware/build/rezo-r5/rezo-49783e4b-r5.tar.gz`. Its seed-7 `top.bit` and the
archived copy both have SHA-256
`d402cf78143865bfed8ec99385d7b1b2bba747232723c550c2aac4bfeeacf715`;
the archive SHA-256 is
`4b39ae438b017ecd87ed183afe3e0e05ff620e8bf9f65a3554a55841341e6624`.
It was flashed successfully to slot 4 on 2026-08-05. Bitstream and manifest
programming plus FPGA refresh completed without error, and option storage was
preserved. It was superseded later the same day by the GROUPS-ghost build below.

Forty full rectangular GROUPS ghosts exceeded capacity by 149 packed cells.
The final renderer shares one row-edge test across the complete 10x4 grid and
draws dim top/bottom rails instead. Exact commit `b2812acc` uses 24,223 packed
cells (65 free), with seed 6 passing at 387.00 MHz DVI5X, 72.22 MHz AUDIO,
62.50 MHz SYNC, and 79.25 MHz DVI. The final validation archive is
`gateware/build/rezo-r5/rezo-b2812acc-r5.tar.gz`. Its seed-6 `top.bit` and the
archived copy both have SHA-256
`c374120f425c1fca752294a1625611dacb64317732f43c069d4f592cadffae3e`;
the archive SHA-256 is
`97f1d5a2fca4bf0fcba4780d3ddf8d94fa329f520c3dc3214f89a3880cc1b21e`.
It was flashed successfully to slot 4 on 2026-08-05, with option storage
preserved.

## 2026-08-04 BANDS UI update

The journal optimization first increased free space from 504 to 1,082 packed
cells. That room now carries a complete editable BANDS page:

- LEGACY: `29, 61, 115, 218, 411, 777, 1500, 2800, 5200, 11000 Hz`
- OCTAVE: `31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000 Hz`
- PERCEPT: `50, 150, 300, 500, 770, 1150, 1700, 2700, 5300, 12000 Hz`
- USER: the editable current working layout
- A separate enable/disable toggle for each of the ten bands

Frequency editing uses a 116-position logarithmic grid: the exact 29-value
union of the factory frequencies plus three subdivisions following each
center. Click a band frequency, rotate, then click to apply. Slow turns advance
one position for precision; rapid turns advance eight. Any edit selects USER
automatically. USER is the current working vector rather than a separate hidden
snapshot, and SAVE DEFAULT persists and restores the active frequencies and
enables exactly.

The hardware photo of the first implementation exposed an ambiguous tall-fader
metaphor and overlapping text. The polished page now has a labeled PRESET
selector, a row of ten ENABLE buttons, and a separate row of ten SET FREQ
buttons. It removes redundant band numbers and shows the selected value as an
exact five-digit Hz readout. When no band target is selected, the readout is
blank.

The BANDS page is BANK-only and is skipped entirely in FILTER navigation.
Disabling a band blanks its BANK column and its BANK group/feedback control.
The blank target can still be traversed for one encoder detent, but clicking it
cannot enter edit mode or change the hidden value. A full automatic navigation
skip overflowed the FPGA. FILTER ignores the enable mask and continues to use
all ten resonators.

Final measured resources (`BANDS-FINE-COMMIT-S6`, commit `04dc8771`):

- LUT4: 20,577
- Packed cells: 24,259 / 24,288
- Free packed cells: **29**
- FF: 6,510
- BRAM: 19 / 56
- DVI5X: 442.48 MHz (required 371.33)
- AUDIO: 72.68 MHz (required 49.15)
- SYNC: 63.84 MHz (required 60.00)
- DVI: 76.78 MHz (required 74.25)

This candidate requires native Yosys 0.66+152 and the staged mapping recipe in
`RezoBeamTop.script_after_synth`: an initial density-oriented `abc`, followed by
`abc9 -W 160`, then ECP5 cell mapping. The project's pinned YoWASP Yosys 0.52
maps the fresh source over capacity. The cutoff table is a synchronous
block ROM; the next band is explicitly prefetched after the current band's two
SVF passes, preserving the known-good DSP vector without an illegal asynchronous
block-RAM port.

The previously flashed `rezo-69904c1e-r5.tar.gz` contains the initial UI seen in
the hardware photo, but it was packaged after `--skip-build` reused an older
generated RTL/bitstream. Its source provenance is therefore not exact, and it
does not contain the polished page or guaranteed synchronous-prefetch fix. Do
not treat it as the validation candidate. The rack was powered down before this
pass, so the corrected build must not be flashed until the user is present.

The corrected validation archive is
`gateware/build/rezo-r5/rezo-9fe65f4e-r5.tar.gz`. Its embedded `top.bit` matches
the locally packed seed-1 bitstream at SHA-256
`0d6b46064211777831d31c7d49e38ffb162147ff435a1bda718cdea9a38f2e43`.
It was flashed successfully to slot 4 on 2026-08-04; bitstream and manifest
programming plus FPGA refresh completed without error, and option storage was
preserved. Physical UI/audio/save validation is pending.

The new BANK-only/fine-frequency validation archive is
`gateware/build/rezo-r5/rezo-04dc8771-r5.tar.gz`. Its seed-6 `top.bit` and the
archived copy both have SHA-256
`da757347f33706ac317b8559313927b6a136a713a04943d5b418776348c5397e`.
It was flashed successfully to slot 4 on 2026-08-04. Bitstream and manifest
programming plus FPGA refresh completed without error; option storage was
preserved. Physical UI/audio/save validation is pending.

The clocked sample-and-hold, shift-register, rotate, and random-walk family is
now assigned to a separate alternate bitstream. Do not attempt to squeeze those
features into the 29 cells remaining here. They should share one clocked,
control-rate transformation engine built from the optimized pre-BANDS commit.

## Repository state

- Repository: `/Users/naenyn/git/tiliqua`
- Branch: `rezo`
- Initial BANDS implementation: `69904c1e rezo: add editable band layouts`
- `Erica Resonant FB Notes.txt` is an untracked, user-owned reference file at
  the repository root. Do not delete, stage, or commit it unless explicitly
  requested.
- The parent commit is the optimized, behavior-preserving version-1 journal
  baseline with 1,082 free packed cells.

## User working preferences and safety rules

- Do not revert to a previous implementation without asking. Diagnose and fix
  forward; this is an exploratory passion project and preserving useful work is
  more important than quickly returning to an older build.
- Flashing REZO is allowed when needed. Use slot 4 unless the user says
  otherwise. Never hardcode slot 4 into persistence logic: persistent state
  must always use the bootloader-validated slot from which REZO is running.
- Do not change the UI as part of an optimization unless the user approves the
  UI change first. Internal implementation changes that preserve the displayed
  pixels and control behavior are encouraged.
- Preserve audio behavior during performance work. Add or extend tests before a
  risky refactor and compare the DSP path bit-for-bit where practical.
- Keep the user informed during long builds; FPGA routing may take a long time.
- Never treat a small source change as a small hardware change. This design is
  congested and placement is highly seed-sensitive.

## Current product state

REZO is a CPU-free, lean 1280x720p60 Tiliqua R5 bitstream running audio at
192 kHz. Its major implemented features are:

- Ten time-multiplexed resonator bands.
- A BANDS page with three factory center-frequency layouts, a USER layout,
  stepped per-band frequency editing, and per-band enable controls.
- BANK mode with editable bipolar band levels, factory shapes/presets,
  resonance, feedback, and resonator drive.
- FILTER mode that uses the ten bandpass resonators to approximate low-pass,
  high-pass, band-pass, and notch responses, with frequency, continuously
  variable slope, width, resonance, and drive.
- BANK input assignment: each physical input can be audio or CV. Audio inputs
  are mixed with individual gain; CV inputs can target resonance, feedback, or
  one of four band groups with attenuverters.
- FILTER modulation matrix: IN1-IN3 can each modulate frequency, resonance,
  width, slope, and drive through signed depths.
- Four band groups and per-band group assignment.
- Four-output routing matrix with independent unipolar send levels for each
  group and dry signal.
- Per-band feedback-send enable controls and feedback safety controls.
- Base/effective modulation visualization: unmodulated values retain a marker
  and modulation is shown using the semantic modulation palette role. This is
  implemented for BANK bands and controls and FILTER controls, including
  drive.
- Five semantic color palettes. The selected palette is now part of the saved
  REZO default state rather than an independently autosaved preference.
- One-click `SAVE DEFAULT` on the OPTIONS page. There is intentionally no
  confirmation state. A successful record restores the complete current REZO
  state when the same bitstream slot is booted again.

The user hardware-tested the pre-optimization save/restore workflow
successfully. That implementation was also flashed to slot 4. The archive
filename
used for the last flash carried the previous commit ID because the persistence
changes were uncommitted at build time; those exact changes are now commit
`6a4a4ab1`.

## Persistence safety and implementation notes

Persistence caused a bootloader scare during development, so changes here
must be treated carefully.

- The journal reserves only the two 4 KiB option sectors belonging to the
  active, bootloader-validated slot.
- No arbitrary software-provided flash address is accepted.
- An invalid or unavailable boot-slot record disables saving safely.
- Records are dual-sector, generation-numbered, versioned, CRC-checked, and
  verified after programming.
- Version 2 saves 46 16-bit state words. Its four-word tail packs ten 5-bit
  coarse frequency indices, ten enable bits, and the selected layout; twenty
  existing padding bits elsewhere in the record carry two fine bits per band.
  Version-1
  42-word records remain readable and migrate to LEGACY with all bands enabled.
  The on-flash format still reserves room for up to 2 KiB of future state.
- State capture/restore uses a circular 46-cycle scan stream to avoid a large
  addressable UI-state mux.
- The snapshot memory must remain inferred as block RAM. Distributed RAM cost
  roughly 700 packed cells in an earlier experiment.
- The SPI bridge enforces four full 60 MHz cycles of physical CS#-high recovery
  between flash transactions. The original one-cycle gap produced SAVE ERROR
  and no committed record. Do not weaken this timing without hardware-level
  evidence and tests.
- The earlier boot failure was never conclusively explained. The present
  bounded addressing and hardware-tested journal work, but any persistence
  refactor should first prove all erase/program addresses remain inside the
  current slot's option window.

Key files:

- `gateware/src/top/rezo/persistence.py`
- `gateware/src/top/rezo/top.py`
- `gateware/src/tiliqua/periph/eurorack_pmod.py`
- `gateware/tests/test_rezo_persistence.py`
- `gateware/tests/test_i2c.py`

## Build-performance discipline

`BUILD_PERFORMANCE.md` is a required rolling engineering log, not optional
documentation. For every materially different synthesized/routed design:

1. Record the source change or experiment ID.
2. Record the placement seed.
3. Record LUT4, packed cells, free cells, FF, and BRAM.
4. Record every final post-route clock result: DVI5X, AUDIO, SYNC, and DVI.
5. Keep failed experiments and aborted/pathological routes in the notes so the
   same dead end is not repeated.
6. Do not compare pre-route timing estimates as though they were final timing.
7. Run more than one seed for an important candidate when time permits.

Formal historical optimization baseline (`OPT-BASE`, commit `2b464d50`, seed
4):

- LUT4: 18,282
- Packed cells: 21,668 / 24,288
- Free packed cells: 2,620
- FF: 5,894
- BRAM: 10 / 56
- DVI5X: 404.53 MHz (required 371.33)
- AUDIO: 64.35 MHz (required 49.15)
- SYNC: 64.86 MHz (required 60.00)
- DVI: 79.56 MHz (required 74.25)

Previous one-click-save build (`SAVE-ONE-CLICK-S4`, seed 4):

- LUT4: 20,312
- Packed cells: 23,784 / 24,288
- Free packed cells: **504** (about 2.1%)
- FF: 6,579
- BRAM: 13 / 56
- DVI5X: 396.35 MHz (pass)
- AUDIO: 74.48 MHz (pass)
- SYNC: 64.87 MHz (pass)
- DVI: 78.11 MHz (pass)

The pre-BANDS optimized build passes at seeds 8, 4, and 2 with 1,082 free
cells. BANDS plus the BANK-only/fine-frequency pass uses 1,053 of those cells
and the final commit-stamped seed-6 candidate leaves 29.
Packed-cell use is not monotonic with source-code size: shortening labels and
several apparently simpler lookup structures mapped substantially worse.
DVI5X is largely the existing TMDS serializer and is highly seed-sensitive,
but overall packing congestion is also a real constraint.

## Test baseline

The complete targeted regression set now contains 39 tests, including exact USER
working-vector semantics, all ten persisted frequencies/enables, version-1
migration, the known-good DSP vector, two-row BANDS geometry, a five-digit
frequency readout, mode-change gain slew, disabled-band frames, programming
across a 256-byte flash page, deterministic bounded ALL WALK behavior, and
HEAD cursor/stride/disabled-band behavior:

```sh
pdm run pytest \
  tests/test_rezo_ui.py \
  tests/test_rezo_display.py \
  tests/test_rezo_persistence.py \
  tests/test_rezo_compare_path.py
```

Run from `gateware/` if the repository's PDM command expects that directory.
Also run `git diff --check` before builds and commits.

Normal build command:

```sh
TILIQUA_REZO_SEED=<seed> pdm run rezo build --fs-192khz
```

That command uses the pinned Yosys and currently exceeds capacity, but it does
generate a fresh `top.il` and a `top.ys` containing the staged recipe. Run that
script with the native OSS CAD Suite Yosys, then route the resulting JSON:

```sh
source ~/.zshrc
yosys -l top-native.rpt top.ys
nextpnr-ecp5 --timing-allow-fail --seed 1 --25k --package CABGA256 --speed 6 \
  --json top.json --lpf top.lpf --textcfg top.config --log top.tim
ecppack --freq 38.8 --compress --bootaddr 0x0 \
  --input top.config --bit top.bit --svf top.svf
```

Normal flash command from `gateware/`:

```sh
pdm flash archive build/rezo-r5/<archive>.tar.gz --slot 4 --noconfirm
```

Only flash a routed build after every required clock passes. When evaluating
seeds of an unchanged synthesized design, reuse the exact `top.json` for direct
nextpnr routing so synthesis variation is not confused with placement
variation.

## Immediate next task: hardware validation

1. Confirm boot, audio, all pages, palette rendering, and modulation display.
   Check selector alignment, OPTIONS spacing, disabled-band frames, and the
   corrected FEEDBACK navigation order against the hardware photos.
2. Exercise BANK/FILTER changes with sustained and transient-rich input. The
   new shared-gain slew removes the direct band-gain discontinuity; if a pop
   remains, the next candidate should fade the complete four-output mix so
   mode-specific routing and dry sends also transition smoothly.
3. Confirm a previous version-1 default restores as LEGACY/all-enabled while
   preserving every pre-BANDS setting.
4. Exercise every layout, frequency editing, enable toggles, and FILTER mode.
5. SAVE DEFAULT, reboot slot 4, and confirm the complete version-2 state restores.
6. Develop clocked modes only as a separately measured alternate bitstream.

## Desired next functionality

The next major desired feature is a clocked shift-register mode. The roadmap
ranks it as moderate complexity. The likely foundation is a shared,
time-multiplexed control-rate band transformation engine:

```text
manual/preset levels
    -> shape source
    -> rotate / tilt / morph
    -> motion or clocked source
    -> existing group and CV modulation
    -> smoothing
    -> ten time-multiplexed resonators
```

For shift-register mode, plan for:

- A physical input configured as clock, with threshold and hysteresis.
- A source value (probably another CV input initially) shifted into one end of
  the ten-band vector.
- Atomic publication of a completed ten-band state so the audio engine never
  sees a partially shifted vector.
- Forward direction first; reverse, ping-pong, random, and reset are later
  enhancements.
- Existing base/effective modulation visualization should consume the computed
  state rather than adding arithmetic to the pixel renderer.
- State fields must be versioned and included in SAVE DEFAULT only after the
  basic mode is stable.

Before implementing it, settle the minimal first-version interaction with the
user. A new mode/page or altered input page is a UI change and requires
approval. The performance pass is now complete; hardware-validate it before
spending the recovered cells.

Lower-risk features that may fit before or alongside that foundation are more
factory preset shapes and a simple band-enable mask. Tilt, rotate, randomize,
random walk, diffusion, LFO phase spreading, and more advanced spectral modes
should still be isolated from the first shift-register build so their measured
costs do not become entangled.

## Longer-term direction

The full ranked roadmap is in `Rezo_Feature_Ideas_By_Complexity.md`. Important
product goals discussed with the user include:

- Continue supporting BANK and FILTER modes rather than copying the Erica
  module exactly.
- Preserve resonance as a primary, immediately accessible control.
- More characterful but controlled resonance/feedback/drive behavior.
- Potentially configurable band frequencies and frequency-layout presets.
- Additional motion features such as tilt, rotation, LFO phase spread, random
  walk, diffusion, and shift-register operation.
- Future user presets or multiple saved states, after the single default-state
  journal is proven and resource headroom exists.
- Potential stereo or multiple-audio-input workflows, assignable CV, and
  richer output routing; these are substantially larger than simple
  control-rate transformations.
- A CLOCK or SHIFT REGISTER mode is currently more important than scopes or a
  spectrum analyzer. Visual analysis features remain low priority.

The guiding constraint is to keep REZO musically interesting and visually
coherent while maintaining 720p60 HDMI timing and substantial modulation
capacity. Optimize shared machinery before adding parallel copies of feature
logic.
