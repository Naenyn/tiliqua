# Scale architecture

Primary development branch: `codex/tuner`. TUNER is a working product name.
The prior `codex/tuner-nsdf-integration` branch is retained as a checkpoint.

## Implemented scale engine and preset integration

`fw/src/scale.rs` implements allocation-free nearest-degree quantization over
validated, borrowed interval tables. Values are signed millicents (0.001 cent),
not MIDI note numbers or a twelve-bit mask. Tables begin at zero, are strictly
increasing, and exclude the positive repeat interval itself. Non-octave periods
and negative input pitches are supported. Root is separate from the table.
At most 128 degrees are accepted; this is an explicit initial implementation
limit, not a claim to support every Scala file. No silent truncation is allowed.

Binary search bounds per-sample work. Multiple channels can borrow one immutable
table rather than duplicate it. Five-cent midpoint hysteresis is capped at one
quarter of each neighboring interval, preserving access to dense tunings.
Integer overflow is an error, not a wrapped pitch. The caller retains existing
DAC limits, range holding, stale-CV checks, and explicit output arming.

Host tests cover chromatic compatibility, irregular and fractional intervals,
non-octave repetition, negative pitches, root offsets, dense-scale hysteresis,
invalid tables, maximum size, overflow, and comparison with an exhaustive oracle.
The new firmware connects this engine to standalone QUANT for chromatic,
major, natural minor, major/minor pentatonic, and 24-EDO presets. Root is a pitch
class anchored in the octave of the 0 V note; transpose is a separate post-
quantization semitone shift. Changing either, scale, or routing stops playback
and requires RUN. Corrected PLAY retains its existing chromatic behavior.
Hardware testing of this build is pending; the rack was powered down.

## Two-octave editor and input distribution

CUSTOM 2 compiles two 12-bit masks once at RUN into a 24-entry maximum pattern.
This adapter does not replace the general microtonal format. NOTES editing
stops output; imported microtonal tables remain a separate path. Explicit SAVE
and LOAD preserve the two conventional masks in one of eight selected slots
(keys TNP1 through TNP8; legacy saves remain in slot 1)
in the original settings journal. The expanded oscillator-profile journal is
untouched. Writes are read back and compared; invalid loads don't replace edits.
Nothing is automatically armed or loaded. Settings reset does not erase this
separate storage. These are conventional note-pattern slots, not yet imported
microtonal-scale slots. Eight separate SETUPS slots now retain the four output
configurations and independent mask snapshots in 48-byte CRC-protected TQS1
records. No running state is stored. QUANT RUN now starts all four outputs at
500 Hz per channel. Calculations are staggered two per 1 ms interrupt using a
shared input snapshot; all four voltages commit at one DAC update boundary.
Safety disables remain immediate. Selecting output selects its
settings and stops the group. Hardware timing/resource qualification and live
four-channel testing are required for this adapter change.
Both populated halves repeat every 2400 cents. One empty half collapses to the
other mask's pitch classes over 1200 cents, discarding which half they occupied.
Both empty refuses to arm. Patterns may omit unison, so nearest lookup handles
both wrap boundaries without inventing a C note. Exhaustive-reference tests
cover all 4095 nonempty first-half masks with complementary second halves.

EQUAL is available for presets and CUSTOM 2. It gives each degree one equal
input bin across the **entire** period, not a separately divided bin allocation
per octave. Bins are left-inclusive/right-exclusive before hysteresis. Degree
zero's bin begins at root even when the first selected pitch lies above root.
Negative voltages repeat using floor/Euclidean division. Hysteresis is in input
space, capped at five cents or one quarter of bin width. Output stays on actual
selected degrees; transpose and output limits apply afterwards. This is a
defined behavior to audition, not a claim to reproduce Instruo dail's behavior.

## Offline Scala import

Run `python gateware/tests/tuner_scale_import.py input.scl output.tscale`.
This implements a documented subset of the
[Scala format](https://www.huygens-fokker.org/scala/scl_format.html): comments,
description (including empty description), count, positive ascending ratios or
decimal cents, and trailing pitch annotations. Integer pitch tokens are ratios,
not cents. The last interval supplies the repeat period; implicit unison is
inserted into the table. Ratio components through 2147483647 are supported.

Explicit limits: 1..128 degrees, 1 MiB file input, 256-character pitch tokens,
positive strictly increasing intervals representable as signed millicents.
Zero-degree scales, descending/negative intervals, and intervals that collapse
at 0.001-cent resolution are rejected, even if permitted by the broader Scala
format. No sorting, truncation, or silent coalescing. Keyboard mappings are not
implemented. UTF-8 (including BOM) and Latin-1 descriptions are supported.

The output envelope is `TSC1`, little-endian u16 degree count, u16 reserved zero,
i32 period, count i32 degrees, and IEEE CRC32 of all preceding bytes. Maximum
size is 528 bytes. No root, routing, keyboard mapping, or oscillator profile is
embedded. This is a versioned staging format, not a flash slot layout.
The converter refuses to overwrite any existing output file. Firmware decoding
validates the entire envelope and table before changing caller-owned staging
storage. Cross-language tests check conversion, corruption, truncation, and
failed-import atomicity. CRC detects corruption; it is not authentication.

There is **no device upload or persistent custom-scale slot yet**. The decoder
is ready for transport integration but is not reachable from the UI or serial
port. No thumb-drive support is implied. Users can author `.scl` files on a
computer without using the encoder, but cannot load them into this build yet.

## Next integration

1. Preserve the working presets, two-octave patterns, Nearest/Equal mapping,
   independent routing and eight setup slots. User tests have exercised these;
   expand edge-case coverage without treating that as exhaustive qualification.
2. Complete direct CV timing qualification of the synchronized four-output
   implementation. Optional per-output calibration-profile correction remains
   future work; nominal QUANT must never require an oscillator profile.
3. Connect the implemented Scala importer/decoder to a user-controlled transport
   and add a friendly computer-side editor. Keep conversion outside playback.
   Keyboard mapping (`.kbm`) is a separate feature.
4. Define versioned scale storage independently from oscillator profiles. Import
   into staging storage, validate completely, then publish while outputs are
   stopped. A failed import must leave the previous scale and profiles intact.
5. TRS MIDI note toggling is wired into the conventional two-octave editor:
   open NOTES, choose A or B, press LEARN, and tap keys to turn their pitch
   classes on or off. A fresh positive-velocity Note On toggles its note
   modulo 12 in the chosen octave. Repeated Note Ons while a key is held do
   nothing; Note Off or zero-velocity Note On releases it for the next tap.
   LEARN toggles off on a second press or on leaving NOTES. CLEAR is optional.
   A running selected output cannot be edited. The result remains in RAM until
   the user explicitly saves it in a NOTES slot. This does not decode USB MIDI,
   transpose routes, or alter imported microtonal scales. TRS MIDI
   transposition remains future work.
6. Evaluate USB MIDI hosting and future upstream USB mass-storage support
   separately for resource use, compatibility, and safe port/power ownership.
   Keep file transport separate from parsing and playback. Encoder editing is
   a convenience, not the only long-term authoring/import mechanism.

## Four-channel interface implemented

Current gateware retains the selected CV/command path for CAL/PLAY and adds
four continuous CV snapshots, four independent command/ACK/watchdog owners,
and a shared commit register for QUANT. CAL/PLAY has hard priority.

Firmware calculates two lanes per interrupt from a shared set of input readings
and commits the four results together. The nominal lanes do not embed oscillator
profiles. Bounds, immediate disables, fault isolation and watchdogs remain.
Simulation, routed timing and live CPU budgets pass; see [checkpoint](CHECKPOINT.md)
for the outstanding physical CV timing check and current resource counts.

## Hardware checklist after power-up

- Flash normal 1280x720 TUNER slot 1 only after user confirms rack is on.
- Slow CV/LFO IN1, OUT1 to V/oct: test C major, D minor, both pentatonics.
- Chromatic +12 transpose must move output up 1 V; 24 EDO gives 1/24 V steps.
- Changing scale/root/transpose stops safely and requires RUN again.
- Check range holding/reentry, then inspect serial cycle/gap maxima and faults.
- Confirm tuner/calibration menus still work. Profiles and spread spectrum=0.0
  remain unchanged. No calibration run is needed merely to use QUANT.
