# SONORO / CASCADO target-only numerical and efficiency review

Date: 2026-09-14. Baselines: SONORO 92c604bc; CASCADO 2ed25e04.

Scope: target spectrogram gateware, target integration, firmware display math,
and configuration. No shared/core Tiliqua source is changed by this review.
This is a source/simulation review, not a substitute for the next hardware test.

## Corrected

CASCADO firmware projected axis annotations by shifting each of three products
before adding. Terrain gateware adds all products before shifting. Separate
arithmetic shifts can bias annotations by up to two pixels, especially for
negative terms under rotation. Firmware now matches the gateware dot product.

Camera helpers live in a target-local, independently testable Rust module.
Tests cover signed Q8 rounding, the default camera, five-degree increments,
all 50,653 combinations of the supported angle grid, signed 10-bit coefficient
bounds, signed 24-bit accumulator bounds at representative extreme coordinates,
and exact dot-product results. Axis annotation matrices are cached by camera
angle, avoiding repeated matrix construction on every completed surface.
This reduces CPU work when ticks/labels are enabled; it is not a claimed FPS gain.

## Checks with no new defect established

- Both targets use fractional logarithm contributions and a single final
  rounding, with zero handling and full-scale saturation. Existing tests check
  exponent boundaries; CASCADO exhaustively checks all nonzero 16-bit raw codes.
  Error is bounded by one six-bit display code, not one dB.
- Six-bit levels represent -96..0 dBFS: each step is about 1.524 dB.
  Gain is a saturating display-code offset, not an analog voltage multiplier.
  The display-floor soft knee deliberately changes displayed heights near the
  threshold. It must not be interpreted as calibrated measurement there.
- 512-point analysis at 48/24/12/6 kHz gives 93.75/46.875/23.4375/11.71875 Hz
  bins. Positive bins stop at 255, just below Nyquist; range labels are limits,
  not a claim that the last FFT bin equals the endpoint.
- CASCADO log buckets cover bins 1..255; duplicated low-frequency bins are
  expected at finite FFT resolution. Low/high geometry spans the entire axis.
- Four-corner terrain shading uses an eight-bit sum (maximum 252); adding two
  before dividing by four remains safe and yields a result no larger than 63.
- Projection products and sums have adequate width for supported camera values.
  Frequency-color brightness saturates rather than wrapping at the top.
- CASCADO captures complete history columns before acknowledging them and fences
  rendered writes before buffer swaps. SONORO retains its delayed final-bin
  handoff and scan/read alignment regression coverage.

## Remaining limitations / opportunities

1. CASCADO visibility ordering is a fixed oldest-to-newest painter order, not
   a depth buffer. Large camera rotations can violate that ordering. The single
   optional historical ridge is deliberately a final overlay. General
   hidden-surface correctness needs a separate design decision; changing it
   casually risks returning the holes/perforation seen in earlier builds.
2. CASCADO history is capture/render-cadence dependent. Its depth is sixteen
   spectra, not a fixed number of seconds. Rate affects admission, and render
   cost affects elapsed history time; the current new/old labels are honest.
3. The largest likely terrain performance opportunity is less framebuffer
   traffic: conservative occlusion/coverage rejection before emitting facets,
   or clearing only proven dirty bounds. These require overlap, clipping,
   rotation, and UI-erasure tests before implementation. More triangles or
   finer blocks alone are not an optimization.
4. Camera annotation projection caching is safe and implemented. Caching all
   projected tick endpoints could save more CPU work, but should be measured
   before adding complexity. Menus still need repainting after fresh-buffer
   swaps; blindly skipping unchanged text is incorrect.
5. SONORO's disabled beam-raced text fallback may be removed for maintainability,
   but it is already disabled at elaboration and removing source alone does
   not recover FPGA resources. Its history stores 256 x 256 x 6 = 393,216 bits
   (48 KiB logical payload); CASCADO stores 16 x 256 x 6 = 24,576 bits (3 KiB),
   excluding buffers and physical RAM packing.
6. Configuration is synchronized field-by-field. During range/camera edits,
   transient frames can combine old analysis/history with new display settings.
   Atomic frame-boundary configuration and explicit history invalidation are
   worthwhile future polish, but are broader behavioral changes, not justified
   as an overnight arithmetic fix.
7. The compact logarithm table is validated for the production ASQ format.
   Supporting substantially wider fractional formats should include low-end
   saturation tests because exponent contributions are clamped before adding
   mantissa corrections. Do not assume arbitrary-format accuracy.

## Build decision

SONORO has no new executable change: retain its existing 92c604bc test artifact.
CASCADO needs a new artifact for the annotation correction and cache.
Build with spread_spectrum=0.0 and the existing 192 kHz audio configuration.
Do not flash; hardware validation is deferred to morning.
