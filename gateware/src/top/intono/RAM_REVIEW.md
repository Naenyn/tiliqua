# Intono RAM review — October 2, 2026

The scan freeze is consistent with stack pressure. Moving calibration state to
PSRAM allowed an AUTO retry to finish acquisition and all 45 verification targets.
It ended at the existing checks-disagree review result. We have not captured an
exact overflowing stack address or isolated the individual triggering UI edit.

## Current memory allocation

Measured from the release ELF flashed as `intono-ux-ram-review-20261002-r5.tar.gz`:

| Allocation | Bytes | Location |
| --- | ---: | --- |
| All initialized/static CPU state | 6,552 | Internal 32 KiB SRAM |
| Four playback engines and configuration (`MULTI_QUANT`, included above) | 5,236 | Internal SRAM |
| UI/application object (`APP`, included above) | 1,216 | Internal SRAM |
| Available stack region after static state | 26,216 | Internal SRAM |
| Foreground calibration state (`Live`) | 7,048 | PSRAM at `0x20500000` |
| Main frame | 1,216 | Stack |
| Run wrapper frame | 80 | Stack |
| Perpetual run closure frame | 9,328 | Stack |
| Calibration constructor frame, temporary | 7,072 | Stack |
| Constructor's `Live::new` frame, nested | 304 | Stack |
| AUTO tick frame | 2,432 | Stack |
| Sweep tick frame, nested in AUTO | 3,232 | Stack |
| Sweep poll frame, nested in sweep | 192 | Stack |

Frames are compiled function allocations, not a complete peak-stack bound.
Additional helper/trap/interrupt frames must be included. Startup has a separate
12,064-byte frame, released before run starts. Calibration construction runs with
interrupts enabled and retains the run frame while its temporary exists.

The previous diagnostic build retained 7,716 static bytes and a 16,384-byte run
closure. Moving Live to PSRAM saved 7,056 bytes of retained stack. Compact patterns
then saved 1,152 static bytes; removing the temporary heartbeat removed another
12 bytes including layout padding. The run closure still occupies 9,328 bytes:
other state and compiler temporaries determine its current peak frame.

## Representation and ownership findings

- Eight-octave keyboard patterns used 96 i32 millicent values (384 bytes of array
  storage). They now use 96 u8 semitone indices (96 bytes). Pattern is at most
  104 bytes, including its count and period. Conversion to exact millicents occurs
  during lookup; no floating point or approximation is introduced.
- Imported/microtonal scales continue borrowing exact i32 degrees. Presets share
  immutable tables; no per-route preset table is allocated.
- Four playback profiles dominate static SRAM. Independent routes need independent
  curves. These stay in SRAM because the 1 ms playback interrupt reads them; moving
  them into contended external memory would require a separate latency review.
- Calibration's current and pending profiles intentionally preserve review/accept/
  discard behavior. Its large state is foreground-only and now resides in PSRAM.
  The one-time unsafe initializer must remain its only owner; do not expose this
  reference to interrupts or call the initializer again.
- No dynamic heap allocator is used here. Heapless strings/arrays have fixed inline
  capacity and consume their full capacity even when empty. In particular, the
  existing 2,048-byte diagnostic report remains on the run stack. Keep required
  timing evidence, but avoid adding duplicate diagnostic buffers.
- Large rendering caches already live in PSRAM. Static guide coordinates live in
  executable/readonly storage, not in the runtime stack. More screen graphics do
  not automatically imply more SRAM; retained firmware objects and copies do.

## Address safety and measurement

The linker bounds firmware/data loading below the calibration storage at +5 MiB,
then calibration storage below caches at +8 MiB. Caches finish at +13 MiB, below
16 MiB PSRAM's final boot-information page. The calibration section is NOLOAD and
is initialized explicitly before use. Only the CPU uses that object, so it does
not need DMA cache flushing. Existing framebuffer ownership/flushing remains
separate.

The linker reserves at least 24 KiB for stack after static state. This prevents
static growth from silently consuming the reserve; it cannot prove dynamic stack
usage. A new watermark paints unused stack before startup/interrupt registration
and reports `STACK UNUSED_BYTES` through the existing bounded UART path. This is
an estimate of untouched margin since boot, including startup and interrupts;
it is not an overflow trap, and unwritten frame slots or coincidental marker
values can make it optimistic. Pair it with compiled call-path inspection.

Remaining validation: observe watermark during AUTO, profile save/load, all page
transitions, MIDI learning, and multi-output quantization. Run-fixture budget
assertions now pass without raising their thresholds. Keep these checks mandatory
when changing retained types. Do not infer runtime RAM safety from firmware size
or FPGA timing alone.

## Octave support

Keep one octave by default and a maximum of eight, as agreed with the user.
The two-keyboard pager limits visible complexity. Eight octaves cost only 16 bytes
of persisted masks and at most 104 bytes of compiled pattern per engine; reducing
the user-facing maximum is no longer necessary to recover RAM. Changing the maximum
would be a UX decision and would need a policy for existing saved eight-octave
patterns. This change preserves saved record formats, MIDI learning, independent
notes per octave, hysteresis, equal distribution and hardware-boundary mapping.

## Build and validation

- Host calibration/scale/watermark fixture: 251 passed, none failed.
- Scale UI fixture: 46 passed, none failed.
- Scale import and four-quantizer tests: 22 passed, none failed.
- Compact vs exact table comparison covers spans 1–8, sparse/silent octaves,
  negative pitches, roots, hysteresis, equal distribution and bounded output.
- Firmware: 322,560 / 327,680 bytes; 5,120 bytes of slot headroom.
- Firmware-only build uses the previously qualified seed19 FPGA image; all four
  routed clock timing checks pass. Flash to Tiliqua #1 slot1 completed Refresh DONE.
- Matching ELF: `build/intono-ux-midibase-r5/ram-review-firmware.elf`.
- Qualification: `build/intono-ux-midibase-r5/ram-review-validation.json`.
- Hardware AUTO completed without freezing: 63 profile points, 46/46 verification
  targets, REVIEW - USABLE GRADED RESULT (CHARACTER grade). Acquisition 171,679 ms,
  checks 174,807 ms. Lowest reported untouched stack margin: 7,120 bytes. No video
  buffer gaps or background errors reported. Watermark is an estimate, not proof
  that every possible call path fits.
- User ran calibration without first visiting the scale editor. Scale editing,
  MIDI learning, profile save/load and multi-output hardware checks remain pending.
- Read-only capture session31882: `/tmp/intono-ram-review-live.log`.

## October 2 grouped routes

A route layout is eight bytes (four input numbers and four output masks), held
in App and the playback controller. The existing four per-output engines and
profiles remain unchanged. Group START uses the single shared input and all
member output bits in one reservation; the ISR still services the same bounded
four outputs. Failure cleanup stops the group before releasing its claim.

The inspected grouped build has `_ebss=0x1a08` (6664 static bytes), leaving 26104
bytes of SRAM stack. Its run closure is 9376 bytes (48 more than the reviewed
9328-byte frame); main remains 1216 and the constructor remains 7072. This is
compiled evidence, not a new measured peak-stack result. Recheck the existing
watermark during calibration plus group playback and setup recall on the rack.

Sharing checked App access and the glyph-emission loop reduced duplicated
firmware code enough to leave about 20 KiB in the unchanged 327680-byte slot.
No memory limits, scale octave limits, accuracy checks or diagnostic logs were
removed to make room. The eight-octave scale representation is unchanged.


## Overnight route MIDI follow-up

The unflashed October 2 review/MIDI image retains 6,800 static SRAM bytes and
25,968 stack bytes. APP is 1,432 bytes; MULTI_QUANT is 5,268 bytes. The run closure
is 9,472 bytes, main 1,216, startup 12,528 (released before run), and interrupt
callback 320 excluding callees/trap. The 24 KiB linker stack reserve still passes.
These allocations do not replace rack watermark measurements. Eight-octave
compact patterns remain unchanged. See CODE_REVIEW_2026-10-02.md and the matching
review-midi-firmware.elf for current allocations and remaining verification.

### Diagnostic cleanup, 2026-10-02

Detailed telemetry is now compiled only with
`TILIQUA_INTONO_VERBOSE_DIAGNOSTICS=1`. Normal capture storage drops from a 2048
byte report plus 128/192 byte EEPROM/boot strings to one 1536 byte report.
The old no-op capture cancellation API was removed. Timing remains first in the
normal report; the maximal 24-pass timing history test proves it uses <1024
bytes, leaving >512 bytes for scan progress and health. Normal firmware is
288440 bytes (39240 bytes free), down 27144 bytes from the review/MIDI build.
Static SRAM remains 6800 bytes; compiler-disassembled retained run closure is
7968 bytes versus 9472 previously, saving 1504 bytes of stack frame. This is a
frame comparison, not a measurement of total runtime high-water usage.
Both normal and verbose firmware builds pass; 254 host calibration/playback tests
pass. FPGA unchanged, reusing the qualified seed-19 bitstream. Calibration timing,
stack/video health, pitch scheduling and output protections remain enabled.
