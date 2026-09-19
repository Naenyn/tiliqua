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
