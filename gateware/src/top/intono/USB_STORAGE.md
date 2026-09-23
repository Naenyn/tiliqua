# Thumb-drive libraries: investigation and integration plan

September 18, 2026. **Not enabled in the current TUNER build.** No bootloader
change or USB gateware addition is included in the automatic-calibration build.

## Upstream support exists

The [guh Rust documentation](https://github.com/apfaudio/guh/blob/main/rs/README.md)
describes FAT filesystem operations through `rust-fatfs` and USB MSC DMA:
directory access, file creation/allocation, reading and writing are supported.
`FatStream` and `FatStreamWriter` support fixed-file streaming via PSRAM. Normal
filesystem operations block; background streaming does not update FAT metadata.
Thus the library is **not read-only**. TUNER has no integration with it yet.

The [Tiliqua UsbLoad work](https://github.com/apfaudio/tiliqua/pull/177), inspected
at `seb/usbloadcln` commit `7808c1be379c810b32e7b1f06a721d4e39038997`, supplies a
different, lower-resource path: the bootloader reads a named root-directory
8.3 file from FAT32 into PSRAM before launching the user bitstream. Its `wavplay`
example uses `with_usb_load("m.wav", 0x400000, 0x100000)`. This avoids adding USB
hardware to the instrument, but that handoff is load-only and needs a compatible
bootloader. It does not provide runtime browsing or saving from TUNER.

## Recommended implementation boundary

The desired feature is explicit load/save of oscillator curves and scales, not
unbounded streaming or automatic replacement of active routes. Two approaches
need evaluation:

1. Add MSC hosting to TUNER for live import/export. Budget actual routed LUT,
   memory, clocks and PSRAM contention first. Current FPGA utilization is about
   78% LUT/EBR, so feasibility must not be assumed from the small file sizes.
2. Use the bootloader for import and a separate library-management/export mode
   for writes. This can save instrument resources but is less convenient and
   requires a deliberate bootloader/service design. Do not silently substitute
   load-only support for the requested load/save workflow.

File operations should be explicit and restricted to stopped operations for the
first implementation: FAT operations can block the CPU. Unplug, timeout, full
drive, malformed file and interrupted writes must preserve internal profiles,
active bindings and the last valid library. Device writes require a tested
temporary-file/commit/recovery strategy; a FAT rename alone is not a guarantee
of power-loss durability. Never format or erase a user's drive automatically.

Use bounded, versioned, checksummed records: existing TUCP profile encoding and
TSC1 microtonal scale encoding are useful starting points. Validate an entire
import before offering explicit destination/overwrite actions. Loading must
never start a route. Keep oscillator correction curves distinct from scales.

Offline Scala conversion (`tests/tuner_scale_import.py`) and the firmware TSC1
decoder already exist, including non-12-tone intervals. Persistent device scale
libraries and removable-file transport still need implementation. PSRAM can
hold a larger validated library without keeping every curve/scale in CPU RAM;
only selected runtime data should consume scarce CPU memory.

Next: prototype the MSC resource cost in an isolated build, then choose the
live-host or service approach before changing bootloader compatibility or
exposing a USB menu. Test with a disposable FAT32 drive before real libraries.

## Offline file tools and dependency boundary (September 19)

`tests/tuner_library_file.py` now validates existing TUCP oscillator records
(v1 legacy or v2, up to 129 measured/refined points) and TSC1 scales by content,
length, checksum and semantic constraints. It prints an inspectable JSON
representation without changing either file. Calibration profiles retain their
actual variable voltage/pitch curve; they are not interpreted as note scales.
Zero-note labels use note name/octave. Point pitches retain the codec's internal
milli-cent units relative to note zero, not cents relative to the profile's
user-selected zero-voltage note.

From `gateware`:

```sh
python tests/tuner_library_file.py oscillator.tprofile
python tests/tuner_library_file.py custom.tscale
python tests/tuner_library_file.py custom.tscale --export-scala custom.scl --description "My scale"
python tests/tuner_scale_import.py custom.scl roundtrip.tscale
```

Scala export preserves every stored interval at 0.001-cent resolution, including
non-octave periods and up to 128 degrees. It writes decimal cent tokens so
integer-valued cents cannot be misread as ratios. It cannot export an oscillator
profile as a scale, overwrite existing files/symlinks, or create a destination
from a malformed record. Descriptions must be supplied separately: TSC1 stores
intervals, not the original Scala title/comments or pre-rounding ratios.
The converter and file tools pass 37 tests, including systematic corruption and
truncation parity against the **actual live Rust profile/scale decoders**.

These are offline tools, **not device upload/download**. They add no FPGA or
CPU-memory cost and do not imply a USB menu exists. The installed Python build
environment currently contains `guh` commit
`be2b947e5aa9a5ddb396de3be6a831d01b13d0c8`, whose MSC engine is explicitly a
read-only block interface (`READ_10`, no write operation). That installed code
is not the read/write DMA filesystem integration described by the newer upstream
documentation. A live-host prototype must use compatible pinned gateware and
Rust versions together; do not update this shared environment implicitly or
claim current installed read-only support fulfills load/save requirements.

## Resource check and MIDI transport (September 22)

The TUNER build with a small, dedicated TRS MIDI receive FIFO and nine-row
menu routes on R5 at 19,270/24,288 total LUT4s (79%), 45/56 EBRs (80%), and
14/28 DSPs (50%). Its 60-MHz main clock closes at 66.39 MHz. This receiver
reuses the board's
dedicated 31.25-kbaud Type-A TRS MIDI input and existing serial decoder; it
does not claim the USB-C port or source USB VBUS. Its first use is explicit
Note On learning in the conventional two-octave editor, with no changes to
running routes and no automatic flash write.

For a reference point only, the repository's standalone, gateware-only
`usb_host` MIDI-to-CV demo routes at 3,358/24,288 LUT4s (13%) and no EBR.
That number includes its own codec and CV path, is **not** an incremental cost
measurement when combined with TUNER, and says nothing about mass storage or
FAT. Crucially, the demo hardwires VBUS on because it has no SoC Type-C CC
negotiation. It must never be copied into this instrument as a USB host power
policy. USB MIDI and USB MSC also need deliberate port ownership and sharing;
the tiny TRS receiver is not a substitute for either one.

The next USB feasibility experiment should add only the host controller and
safe CC/VBUS ownership to an isolated copy of the TUNER design, synthesize it,
and compare incremental LUT/EBR/clock utilization. Then evaluate MIDI class
and MSC separately. The installed MSC stack is read-only, so even a successful
fit would not yet deliver the requested thumb-drive save path. If the full
write-capable stack cannot route with margin, keep the in-bitstream profile
slots and use an explicit bootloader/service import/export design; do not
silently reduce the requirement to import-only.
