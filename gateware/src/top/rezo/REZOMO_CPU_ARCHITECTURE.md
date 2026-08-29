# REZOMO CPU architecture

The `rezomo_cpu.py` target follows REZO's production control-plane split. The
CPU owns stateful UI behavior and persistence; it does not render pixels or
process audio.

## Ownership boundary

Firmware owns encoder navigation and editing, BANK/CLOCK mode and page state,
all parameter values, CLOCK algorithm layouts, startup restore, and SAVE
DEFAULT. Gateware retains the complete REZOMO DSP and CV paths, video timing
and rendering, LED generation, parameter application, and the slot-bounded SPI
flash transaction window.

Firmware sends compact write commands to a write-only hardware UI peripheral.
The renderer and DSP consume that hardware state directly, preserving the
deterministic CPU-less data plane used by the accepted REZOMO implementation.

Dynamic character updates in the renderer use a compact operation ROM rather
than a 205-way address/data mux. Each operation selects one live hardware value
and one character position; the existing three-DVI-clock refresh cadence is
unchanged. This moves static update topology into one DP16KD block while
keeping all character rendering and refresh timing in hardware.

## CPU and memory

The target uses the same lean VexiiRiscv `rezo_control` integration as REZO,
with no general-purpose SoC peripheral set. REZOMO's larger CLOCK behavior
requires a 20 KiB immutable program ROM; mutable data and stack occupy 2 KiB.
The only peripherals are the encoder, the write-only REZOMO UI command port,
and the bounded persistence flash window.

The program ROM has independent instruction and constant-data read ports. The
hardware UI command format uses a 6-bit operation, a 5-bit element index, and
a 16-bit value. In addition to the shared REZO controls, commands cover SHIFT,
ROTATE, TURING, and WALK settings and derive the four output-routing masks from
the twenty persisted send bits.

## Navigation and persistence

Firmware preserves REZOMO's conditional CLOCK navigation:

- SHIFT: algorithm, direction, clock source, rate, depth, and data source;
- ROTATE: algorithm, direction, clock source, rate, and depth;
- TURING: change, target, optional start, and length; and
- WALK: clock source, rate, depth, style, drunk, and chance.

The current V3 record is 46 words. Firmware can also load the legacy V2
46-word and V1 42-word records, supplying defaults for fields absent from the
older schemas. Startup fails open to defaults if slot discovery or flash access
times out, so a persistence fault cannot leave audio and interaction muted.

## DSP safety and release qualification

REZOMO uses the same pre-narrowing LP/HP/BP state clamp as production REZO.
Normal-level DSP behavior is unchanged; overflowing filter state saturates
instead of wrapping into an unrecoverable rail-to-rail orbit.

Only the standard `1280x720p60` target is part of this checkpoint:

```sh
pdm run rezomo_cpu build --fs-192khz
```

The target enforces at least 3 percent post-route headroom on every clock. A
release is qualified only after the archive boots from slot 3 and the hardware
checklist below passes.

The congestion-optimized 2026-08-25 standard route uses seed 7, 22,014 of
24,288 TRELLIS_COMB cells (90%), 8,206 TRELLIS_FF cells (33%), and 32 of 56
DP16KD blocks (57%). It closes DVI5X at 425.71 MHz, AUDIO at 74.62 MHz, SYNC
at 64.20 MHz, and DVI at 79.30 MHz. DVI is the limiting 6.80% margin, so
future changes must continue to pass the release gate. Relative to the prior
corrected route, the operation ROM recovers 645 packed logic cells at the cost
of one block RAM.

## Hardware verification checklist

1. Boot with responsive video, audio, LEDs, and encoder.
2. Exercise BANK and CLOCK mode and every page.
3. Exercise SHIFT, ROTATE, TURING, and WALK, including their conditional rows.
4. Confirm all four groups and every input CV target can be selected.
5. Save a non-default palette and CLOCK configuration, reboot, and confirm
   automatic restore.
6. Stress resonance, feedback, and drive, then reduce them and confirm the
   output recovers.
