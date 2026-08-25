# STREZO CPU architecture

The `strezo_cpu.py` target applies the proven REZO-family control-plane split
to STREZO. Firmware owns stateful interaction and persistence; gateware retains
all audio, CV, video, LED, and bounded flash-transaction paths.

## Ownership boundary

Firmware owns encoder navigation and editing, all user-visible parameter
state, startup restore, SAVE DEFAULT, V4-to-V5 migration, BANDS motion state,
stereo output-side selection, and the complete CROSS interaction model.
Gateware retains the linked-stereo resonator DSP, CROSS coefficient and motion
processing, CV application, scanline renderer, telemetry, LEDs, and final
display address mapping.

The CPU sends compact commands to a write-only STREZO UI peripheral. The DSP
and renderer consume that hardware state directly. CROSS factory layouts remain
immutable until a matrix edit copies the selected factory into USER state;
cell, row, and column edits then update that retained matrix. GLOBAL continues
to bypass matrix editing and use the accepted same-side/cross-feedback path.

## CPU and persistence

The target uses the lean VexiiRiscv `rezo_control` integration with a 20 KiB
dual-read-port program ROM and 2 KiB data RAM. Its only peripherals are the
encoder, write-only UI command port, and slot-bounded persistence flash window.

The firmware record is bit-compatible with CPU-less STREZO V5: 38 16-bit
words under STREZO's `STRZ` journal magic. V4 36-word records load with the
established motion defaults appended. Startup fails open to defaults if boot
slot discovery or flash access times out.

## Display targets

The current qualification build is the upright, unscaled `1280x720p60`
development-monitor artifact:

```sh
pdm run strezo_cpu build --fs-192khz
```

This is not a standard-only design. STREZO still authors one native `720x720`
canvas with interactive content inside the centered `508x508` safe square.
The existing `720x720p60r2` path applies the official panel's 90-degree
correction only in the final framebuffer address mapping. A circular CPU entry
point can therefore reuse this same top-level and firmware when display
polishing is complete. No circular artifact is built or flashed as part of the
current checkpoint.

The standard target enforces at least 3 percent post-route headroom on every
clock. A release is qualified only after the exact archive boots from slot 4
and the checklist below passes.

## Hardware verification checklist

1. Boot with responsive video, stereo audio, LEDs, and encoder.
2. Exercise every page and both navigation directions.
3. Verify BANDS layout, enables, frequencies, and OFF/TRIANGLE/RANDOM motion.
4. Verify each output row, column, cell, and left/right side selector.
5. Verify all CROSS factory layouts, factory-to-USER copying, matrix cell/row/
   column edits, same-side feedback, cross feedback, and LINEAR/LOG curve.
6. Save a non-default palette, motion configuration, output side, and USER
   matrix; reboot and confirm automatic restore.
7. Stress resonance, feedback, cross feedback, and drive, then reduce them and
   confirm normal output recovers.
