# REZO feature roadmap by implementation complexity

This ranking reflects REZO's current lean implementation rather than a generic
filter-bank design. REZO has ten time-multiplexed resonators, four groups, a
five-by-three filter CV matrix, a semantic eight-role UI palette, and 312 sync
clocks per audio sample at 192 kHz. The current post-route baseline and rolling
results live in [`BUILD_PERFORMANCE.md`](BUILD_PERFORMANCE.md).

The ordering below considers implementation effort, audio and UI risk, FPGA
resources, and timing risk. Features that only transform the existing ten band
levels at control rate are substantially cheaper than features that alter the
audio-rate resonator FSM or its compile-time center-frequency coefficients.

## Foundation: control-rate band transformation engine

Before accumulating several spectral-animation features, add one shared,
time-multiplexed control-rate engine:

    manual/preset levels
        -> shape source
        -> rotate / tilt / morph
        -> motion source (LFO / walk / diffusion)
        -> existing group and CV modulation
        -> smoothing
        -> resonators

The engine should process one band per cycle, publish a completed ten-band
vector atomically, reuse a multiplier where practical, and retain separate base
and effective values for UI modulation shading. This avoids ten parallel copies
of every new transform and keeps most future work out of the audio-rate FSM.

## Capacity checkpoint after the 2026-08-03 optimization pass

The current feature-free optimized design leaves 1,082 packed cells free and
passes every clock from the exact same synthesized netlist at placement seeds
8, 4, and 2. This is 578 cells more headroom than the preceding one-click-save
build, but it is the lower edge of the intended 1,000-1,500-cell feature budget,
not room to accumulate several roadmap items at once.

- Additional factory preset shapes remain the safest near-zero-DSP addition.
  Their UI and selection decode still need a measured build.
- One small control-rate feature such as randomize, tilt, or rotate is a
  reasonable isolated experiment once it uses shared sequential machinery.
- A basic forward-only shift register is now a reasonable next prototype:
  one clock input, one CV source, threshold plus hysteresis, and atomic
  publication of all ten values. Reverse, ping-pong, random, reset, and a
  general clock page should remain separate follow-ups.
- Building the complete general transformation engine, feature-rich clock UI,
  and persistence expansion in one step is still too risky at 95% packed-cell
  use. Add the engine and minimal shift operation incrementally, synthesize
  each boundary, and retain at least one known passing placement seed.
- Do not spend the newly recovered room on unrelated UI ornamentation before
  the clocked-mode prototype is placed and routed.

No roadmap feature was added during this optimization-only checkpoint. The
figures above describe measured headroom before feature implementation, not a
resource estimate for unbuilt features.

## Ranked feature list

### 1. Preset shapes — very low complexity

Add fixed band vectors such as flat, smile, telephone, and vowel/formant-like
curves. This extends the existing ALL/ODD/EVN/LOW/MID/HI/ZERO mechanism and has
negligible DSP cost. A later user-preset implementation can coexist with these
factory shapes.

### 2. Color palettes — very low DSP complexity, low UI complexity

REZO already classifies pixels into eight semantic roles: selected, text,
control, modulation, line, panel, background, and blank. Add a small palette
lookup indexed by palette ID and role; do not duplicate geometry for themes.

Initial complementary palettes:

| Palette | Selected | Text | Control | Modulation | Line | Panel | Background | Blank |
|---|---|---|---|---|---|---|---|---|
| LCD | `FFFFFF` | `EEEEEE` | `B8B8B8` | `787878` | `888888` | `323232` | `141414` | `000000` |
| Amber/Blue | `FFF4CC` | `FFD166` | `C98A20` | `4EA5D9` | `9A6A22` | `35270F` | `171006` | `000000` |
| Cyan/Coral | `F4FFFF` | `C8F7F8` | `55CBCD` | `FF7F6A` | `2A9D9F` | `16383A` | `071718` | `000000` |
| Green/Magenta | `F3FFF6` | `D8F3DC` | `74C69D` | `E56BCE` | `40916C` | `1B4332` | `081C15` | `000000` |
| Violet/Gold | `FFF8DA` | `E7DCF5` | `9D7AD2` | `F2C14E` | `6C4AA3` | `2B1D3A` | `100A18` | `000000` |

Implementation plan:

1. Preserve the current palette as pixel-equivalent LCD.
2. Add a three-bit `palette_id` and an 8-role RGB lookup, preferably inferred
   as one block RAM or an equivalently cheap ROM.
3. Add palette selection to ADVANCED using short names.
4. Add display tests for every role and palette.
5. Decide persistence separately from rendering: the lean no-CPU bitstream
   does not currently own a flash writer, while Tiliqua's SoC option storage is
   slot-local. A global palette shared by unrelated bitstreams requires an
   explicit cross-bitstream storage convention and adoption by those
   bitstreams.
6. Build with the current seed, log resources and all post-route clocks, and
   flash only after every timing constraint passes.

### 3. Randomize — low complexity

Use a small LFSR to generate a new ten-band shape on command. Clamp to the band
range and update the complete vector atomically. UI needs a trigger action and,
optionally, an amount control.

### 4. Tilt — low complexity

Apply a signed linear gain slope across band index. Implement it in the shared
control-rate transform engine using a precomputed per-band distance from the
center. Expose amount and optionally pivot.

### 5. Rotate — low complexity

Maintain a circular band-index offset rather than physically copying data.
This is cheap in state but its variable indexing must be checked for mux cost.
Offer continuous encoder control and CV modulation once the base transform is
stable.

### 6. Spectral gravity — low to moderate complexity

When one band moves, pull neighboring bands toward it using a small fixed
kernel. Reuse the diffusion neighbor datapath and expose strength/radius at
control rate.

### 7. Random walk — low to moderate complexity

At a clocked control interval, add a small signed random delta to each band and
reflect or clamp at the limits. Controls: rate, step size, and optional lock
probability.

### 8. Diffusion — low to moderate complexity

Average each band with its immediate neighbors on a clock. Double-buffer the
ten values so a whole iteration uses the previous state. Controls: rate and
amount; end handling may clamp or wrap.

### 9. Cellular automata — moderate complexity

Treat bands as cells and evolve a selected elementary rule. The binary state
and rule calculation are cheap; making it musically useful needs level mapping,
clocking, direction, and UI work. It should share the motion clock introduced
for random walk and diffusion.

### 10. One-LFO phase spread — moderate complexity

Generate one control-rate oscillator and derive ten phase-shifted values from a
small waveform table or accumulator offsets. Controls: rate, depth, phase
spread, shape, and destination/mix behavior. Keep it control-rate and feed the
existing effective-value visualization.

### 11. Morph between two states — moderate complexity

Store two ten-band vectors and interpolate with one shared multiplier in the
transform engine. A/B capture and morph amount are inexpensive; deciding what
else belongs in each state and presenting capture safely are the larger design
questions.

### 12. Shift register — moderate complexity

Clock CV into one end of the band vector and shift existing values. Add forward,
reverse, ping-pong, and random modes only after the basic version. This needs a
clock-input convention, threshold/hysteresis, and probably a shared clock page.

### 13. Ping / modal resonator — moderate to high complexity

Excite the resonator bank from an internal impulse or detected external edge.
The impulse generator is cheap, but reliable trigger conditioning, decay
behavior, protection, and interaction with feedback require audio testing.

### 14. Spectral sequencer — moderate to high complexity

Store a full band vector for each step and recall it atomically. BRAM cost is
manageable; editing steps, clock/reset behavior, interpolation, and persistence
make this primarily a state-management and UI feature.

### 15. Harmonic frequency mode — high complexity

Derive center frequencies from a root and harmonic series. Current resonator
coefficients are compile-time constants, so this first requires safe runtime
coefficient updates, coefficient generation or lookup, bounds checking, and
state-transition smoothing to avoid noise.

### 16. Frequency-layout stretch / morph — high complexity

Interpolate between logarithmic, perceptual, harmonic, or user layouts. This
has the same runtime-coefficient prerequisites as harmonic mode plus per-band
interpolation and a more demanding frequency-editing UI.

### 17. Audio follower / spectral transfer — high complexity

Estimate the energy of a second signal in each band and use it to control the
main bank. The existing resonators may be reusable for analysis, but this adds
envelope followers, attack/release controls, normalization, routing, and
substantial audio-rate validation.

### 18. Spectral feedback matrix — very high complexity

Allow individual bands to feed other bands. Start, if pursued, with a four-by-
four group feedback matrix; it maps naturally to existing groups and is much
cheaper to operate and edit. A full ten-by-ten matrix requires 100 gains,
accumulation and stability protection, extensive UI, and careful scheduling in
the audio FSM.

## Recommended implementation sequence

1. Color palettes
2. Preset shapes
3. Shared control-rate transformation engine
4. Tilt
5. Rotate
6. Randomize
7. Spectral gravity
8. Two-state morph
9. Shared clock/trigger infrastructure
10. Random walk
11. Diffusion
12. Cellular automata
13. One-LFO phase spread
14. Shift register
15. Ping/modal resonator
16. Spectral sequencer
17. Harmonic frequency mode
18. Frequency-layout stretch/morph
19. Audio follower/spectral transfer
20. Group feedback matrix, then reassess a full band matrix

This sequence deliberately establishes shared machinery before features that
depend on it. Each step should add functional tests, run the REZO regression
suite, receive a post-route build, and append both passing and failed seed
results to `BUILD_PERFORMANCE.md`.

## Notes

- Rotate wraps the final band back to the beginning. A shift register discards
  the oldest value and inserts a new one.
- User presets are not just another factory shape: they require state capture,
  recall, versioning, and persistence. Begin with three whole-state REZO slots
  only after the storage policy is settled; page-local presets can be added
  later if users need mix-and-match recall.
- Dynamically disabling a band is cheap if it means forcing its level and
  feedback send to zero. Dynamically removing resonators from the audio FSM
  saves little in a fixed bitstream and complicates scheduling, so keep ten
  instantiated logical bands and treat enable as a control-state mask.
- All animated UI should consume already-computed base/effective state. Avoid
  doing transform arithmetic in the pixel renderer.
