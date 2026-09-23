# OSCIO transfer review — 2026-09-14

Reviewed OSCIO through `b04dad57`, including the September 13–14 correctness,
continuity, native measurement, and resource changes, plus earlier shared
renderer and help improvements. Targets are SONORO on `codex/sonoro-no-3d`
and CASCADO on `codex/waterfall-split`.

## Integrated in both targets

- Ported OSCIO's sprite row-base addressing optimization from `1043a93e`.
  Compute the source row's byte address at command start, then add the row
  stride at each row boundary. This removes the multiplication from the
  per-pixel bitmap lookup path while preserving transparency, clipping
  downstream, output backpressure, and each target's framebuffer selection.
  It is a timing/logic optimization, not a claimed increase in terrain FPS.
- Ported OSCIO's content-derived help scroll bound from `e5b5fcd5`.
  Generate HELP_SCROLL_MAX from the module documentation and the shared
  renderer's 28 visible lines. Clamp persisted scroll positions after loading.
  Both targets previously allowed scrolling to 125, well beyond their text.
- Included the preceding jack-label review: menus, bootloader metadata and
  on-device documentation use physical input/output numbering 0–3. Enum
  ordering, serialized variant names and hardware indices are unchanged.

## Additional numerical correction in SONORO

SONORO's older exponent/mantissa logarithm tables rounded the two terms
independently. Near a power-of-two boundary this could make an increasing
magnitude decrease by one display level. CASCADO already fixed this in
`aeb4b82e`. Ported its fractional table contributions and single final
rounding to SONORO. The input calibration, Hann coherent-gain correction,
CORDIC compensation, 0–63 display range and saturation remain the same.
Hardware regression tests exercise both sides of exponent transitions and
compare with the calibrated floating-point reference (at most one level error).

## Reviewed but not transferred

- OSCIO's native extrema and Schmitt-crossing frequency detector feed its
  CV/LFO measurement view. Neither analyzer instantiates those components.
- Its signed DC averaging remainder fixes a voltage tracker absent here.
  The analyzers' display-level smoother uses unsigned distances, symmetric
  rise/fall handling and upward-rounded step magnitudes, so it does not have
  that signed right-shift deadband.
- OSCIO's discontinuity cleanup, edge-aware interpolation and sweep capture
  fix a waveform display path. The analyzers use band-limited decimation and
  an iterative FFT. Adding that nonlinear cleanup would change the spectrum.
- The analyzers already retain rounded FIR products, pipelined FFT/DC-block
  arithmetic, and a 64-sample buffer for FFT stalls. OSCIO's 16-entry FIFO is
  sized for a different burst source and does not justify shrinking this one.
- OSCIO's native-rate activity windows and compact CV/LFO pagination are not
  instantiated here. Analyzer decimation is already derived from native fs:
  48/24/12/6 kHz analysis for the 24/12/6/3 kHz ranges.
- OSCIO's framebuffer bitmap-difference updates assume a retained image.
  CASCADO clears and swaps framebuffers; drawing only changed glyphs would
  omit text on a freshly cleared buffer. SONORO's persistence also requires
  refreshing unchanged UI pixels. These paths were preserved.
- CASCADO already omits the unused persistence DMA. SONORO uses persistence;
  importing OSCIO's optional-peripheral configuration wholesale would remove
  active functionality or overwrite later target-specific arbitration work.

## Verification and build policy

Added exact bitmap-output tests with multiple spritesheet strides, nonzero
source offsets, successive subrectangle commands and stalled consumers.
Run each target's numerical/rendering regressions and compile its firmware
during full FPGA builds. Test archives use 192 kHz native sampling and
`spread_spectrum=0.0`; final routed timing must pass in all clock domains.
No hardware flashing is part of this review. Hardware validation remains
necessary for text rendering, help navigation and analyzer/terrain behavior.
