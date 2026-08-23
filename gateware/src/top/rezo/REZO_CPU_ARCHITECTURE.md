# REZO CPU architecture

This document describes the production-oriented REZO CPU target implemented by
`rezo_cpu.py`. It is deliberately a control-plane CPU, not a framebuffer or
audio processor.

## Ownership boundary

Firmware owns the stateful work that is easier to maintain as software:

- encoder navigation, editing, acceleration, and page selection;
- all user-visible parameter state;
- startup restore and SAVE DEFAULT persistence;
- migration of the legacy 42-word record to the current 46-word record; and
- dispatch of compact write commands to the hardware UI state.

Gateware remains responsible for the latency- and throughput-sensitive paths:

- audio I/O and the complete REZO DSP pipeline;
- CV sampling and modulation;
- video timing, text, shapes, meters, and LEDs;
- parameter application at audio rate; and
- a slot-bounded SPI flash transaction window.

The renderer therefore remains deterministic and responsive even if firmware
is busy. The CPU selects and edits elements; it does not draw pixels.

## CPU and memory

The target uses the existing VexiiRiscv integration with the `rezo_control`
variant. It has no general SoC peripheral set. Its useful address space is:

| Address | Size | Purpose |
|---|---:|---|
| `0x0000_0000` | 16 KiB | immutable firmware ROM, dual-read-port BRAM |
| `0x0000_4000` | 2 KiB | mutable data and stack BRAM |
| `0xF000_0600` | small CSR | encoder |
| `0xF000_1000` | small CSR | write-only REZO UI command port |
| `0xF000_1200` | small CSR | bounded persistence flash window |

Instruction fetch has a direct ROM port. Constant reads use the ROM's second
port, avoiding the instruction/data arbitration path that caused early timing
and boot failures. The UI peripheral is write-only and command based so a wide
readback mux is not placed on the congested CPU-to-renderer boundary.

## Startup and persistence

Firmware waits until the hardware has resolved the active boot slot. It then
scans only that slot's option sectors, validates record headers and CRCs, and
loads the newest valid record. If slot discovery or flash access times out,
startup fails open with defaults so audio and interaction cannot remain muted.

SAVE DEFAULT erases and programs through the same bounded window. The UI shows
`SAVING`, then `SAVED` or the failure state. The record format intentionally
matches CPU-less REZO so settings can survive movement between architectures
when both builds use the current schema.

## DSP and display safety

Audio mixing already saturates at the ASQ full-scale boundary. The display
clamps its input activity meter to the value lane and holds a visible clip mark
for roughly three quarters of a second.

The state-variable filter clamps each widened LP, HP, and BP update before it
is narrowed into persistent state. This is important: narrowing first can wrap
an overflowing state even if a later expression appears to saturate it, which
can create a rail-to-rail orbit that does not recover when resonance, feedback,
or drive is reduced.

Hardware validation confirms that maximum DRIVE, RES, and FB with the loosest
safety settings can still create intentionally harsh digital clipping and
noise. That overload is acceptable because reducing the controls now reliably
returns the module to normal operation. Recoverability—not making every extreme
combination clean—is the release safety boundary and is covered by the DSP
stress-and-retreat regression.

## Release build

Only the standard rectangular target is part of this CPU checkpoint:

```sh
pdm run rezo_cpu build --fs-192khz
```

The target defaults to route seed 1 and enforces at least 3 percent post-route
headroom on every clock before packaging. A release is not qualified until UI,
persistence, DSP stress, and standard-display regressions pass and the archive
has been exercised on hardware. No circular build is implied by this target.

## Hardware verification checklist

1. Boot with responsive audio, LEDs, video, and encoder.
2. Confirm BANK and FILTER page navigation and every conditional edit target.
3. Save a non-default palette, reboot, and confirm automatic restore.
4. Drive an AUDIO input past full scale and confirm the held clip mark remains
   inside the VALUE lane.
5. Exercise high resonance, feedback, and drive, then reduce all three and
   confirm the output returns from overload rather than remaining in noise.

The 2026-08-23 standard route uses 21,878 of 24,288 TRELLIS_COMB cells (90%),
8,119 TRELLIS_FF cells (33%), and 36 of 56 DP16KD blocks (64%). Seed 1 closes
DVI5X at 423.37 MHz, AUDIO at 71.75 MHz, DVI at 77.83 MHz, and SYNC at
61.84 MHz. SYNC is the limiting 3.07% margin, so future changes must continue
to pass the release gate rather than treating this route as generous capacity.
