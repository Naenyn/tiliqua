# ASQ sample formats: 16-bit, 18-bit, and local widening

This note records how Tiliqua's audio sample format (`ASQ`) is represented,
when a 16-bit or 18-bit path is appropriate, and the current format decisions
for OSCIO, SONORO, CASCADO, the REZO family, and TUNER.

The central distinction is between the **converter-facing sample format** and
the **internal precision used by an algorithm**. A bitstream can use native
16-bit samples at its ADC and DAC boundaries while using much wider filter
state, products, feedback paths, and accumulators internally. REZO is an
important example of this design.

This is a snapshot of the repository and synthesized artifacts as inspected on
2026-09-20. Where a format is not enforced in source, a later build command can
still change it.

## What `ASQ` means

`tiliqua.dsp.ASQ` is a signed fixed-point type selected at gateware elaboration
time:

```python
_ASQ_WIDTH = int(os.environ.get("TILIQUA_ASQ_WIDTH", "16"))
_ASQ_I_BITS = int(os.environ.get("TILIQUA_ASQ_I_BITS", "1"))
ASQ = fixed.SQ(_ASQ_I_BITS, _ASQ_WIDTH - _ASQ_I_BITS)
```

The default is therefore 16-bit Q1.15. Builds can override both the total width
and the number of integer/sign bits through environment variables.

The two formats discussed here are:

| Format | Fixed-point shape | Numeric range | Nominal calibrated step | Counts per millivolt |
| --- | --- | --- | --- | --- |
| Native 16-bit | Q1.15 | -1.0 to just below +1.0 | 0.25 mV | 4 |
| Widened 18-bit | Q2.16 | -2.0 to just below +2.0 | 0.125 mV | 8 |

For native Q1.15, -1.0 to +1.0 corresponds nominally to -8.192 V to
+8.19175 V. In Q2.16, the physical converter range still does not become
larger or more accurate. The ordinary converter signal occupies the equivalent
of the -1.0 to +1.0 region while the wider representation provides an
additional integer/guard bit and an additional fractional bit for internal
processing.

Consequently, an 18-bit ASQ build adds two different properties at once:

1. **One guard/range bit.** Intermediate values can grow beyond native
   full-scale without immediately wrapping or saturating.
2. **One fractional bit.** Intermediate rounding has twice the granularity.

It does **not** turn Tiliqua's ADC or DAC into an 18-bit converter, recover
information that was not captured by the ADC, or extend the analog output
voltage range.

## When native 16-bit is appropriate

Native Q1.15 is generally the right converter-facing format when a design is
mostly limited by physical I/O precision or performs little repeated
arithmetic. Typical examples include:

- oscilloscope and waveform display input;
- audio or CV passthrough and routing;
- tuner acquisition;
- pitch quantizer input and output;
- calibration-voltage generation;
- switching, modest gain, and other shallow processing;
- designs where RAM, multiplier width, routing, or timing margin is scarce.

At 1 V/oct, a 0.25 mV code step is approximately 0.3 cents. This is already
finer than the millivolt-scale absolute accuracy of the analog path and finer
than the useful stability of most analog oscillators. A tuner normally obtains
frequency precision from period timing, correlation, and interpolation rather
than from an additional amplitude bit.

Using 16-bit samples at the boundary does not require all internal arithmetic
to remain 16-bit. Products, recursive state, sums, and feedback should be
widened where their numeric ranges require it.

## When an 18-bit path is appropriate

A wider representation is useful when meaningful intermediate values are
created after conversion and must travel between several processing blocks.
Examples include:

- summing several signals;
- feedback effects;
- resonant or recursive filters;
- long cascades of filters and gain stages;
- repeated interpolation or resampling;
- spectral processing with several quantization stages;
- synthesis engines combining multiple voices;
- algorithms that otherwise repeatedly saturate or discard fractional results.

The guard bit can prevent intermediate overflow. The fractional bit can reduce
the accumulation of rounding error. These benefits can be real even when the
original ADC sample was 16-bit, because multiplication, calibration, filtering,
and feedback create meaningful intermediate values between and beyond the
original sample codes.

However, globally widening ASQ is a blunt way to obtain those benefits. It also
widens streams, FIFOs, memories, comparisons, and arithmetic that may not need
it. It can increase LUT, BRAM, DSP, and routing pressure, reduce timing margin,
and silently change the interpretation of constants written for Q1.15.

The preferred architecture is usually:

1. retain native Q1.15 at the ADC/DAC boundary;
2. widen products, state, feedback, and accumulators locally;
3. keep enough integer bits to prevent overflow and enough fractional bits to
   control rounding noise;
4. explicitly round or saturate when narrowing back to the output format.

If an algorithm needs only headroom, adding a local integer guard bit without
also widening every fractional path is more efficient. If it needs only lower
rounding error, a local fractional extension can be used instead. The choice
does not have to be a global 16-versus-18 switch.

## Current bitstream status

### OSCIO

**Current observed build:** 18-bit Q2.16.

OSCIO originated from XBEAM, and its 18-bit format appears to have followed
that lineage and its build procedure. The OSCIO source consumes the generic
`ASQ` shape; it does not presently express an independent source-level
requirement for Q2.16.

An oscilloscope is normally a good candidate for native 16-bit input because it
primarily displays converter data. A wider path may help calibrated scaling,
interpolation, or low-level trigger calculations, but it cannot expose analog
detail the converter did not capture. OSCIO therefore needs a controlled
16-versus-18 comparison before its inherited format is treated as a deliberate
requirement. Low-level triggering, trace stability, resource usage, and timing
should be compared. After that decision, the selected format should be asserted
or otherwise encoded in the target rather than left in a shell command.

### SONORO

**Current observed build:** 16-bit Q1.15.

SONORO was renamed from SPECTO in commit `96fe3b1d`. The rename did not change
the sample format in source. The last inspected SPECTO artifact immediately
before the rename was built at 18-bit, while the current SONORO artifact is
16-bit. Because ASQ width was controlled by build-time environment variables,
the transition appears to have occurred when later SONORO builds no longer
supplied SPECTO's 18-bit overrides. It was not recorded as an intentional DSP
design change.

SONORO is the strongest candidate among these display-oriented bitstreams for
a measured 18-bit benefit. Its path includes windowing, filtering, an FFT,
magnitude processing, and resampling. On the other hand, the FFT and related
DSP blocks already widen important intermediate values, and the source is
largely shape-generic. The current 16-bit build is internally consistent and
has been timing-qualified; an 18-bit build should only replace it if an A/B
comparison demonstrates a useful improvement in low-level spectral behavior
that justifies the resource and timing cost.

Until that comparison is performed, SONORO's 16-bit format should be described
as the current stable build format, not as a historically established design
requirement.

### CASCADO

**Current observed build:** 16-bit Q1.15.

CASCADO shares the spectral-analysis family of processing with SONORO and uses
the generic ASQ shape through its filters, FFT analyzer, magnitude conversion,
and resampling path. Its present 16-bit format comes from the default build
configuration rather than an explicit format assertion.

Because CASCADO converts spectral results into display levels, a globally
wider path may have little visible value after the analyzer's own widened
arithmetic and display quantization. It should nevertheless be included in the
same controlled spectral A/B testing as SONORO. Unless that testing shows a
materially better noise floor or weak-component display, native 16-bit is the
more conservative resource and timing choice. The final decision should then
be encoded in the target.

### REZO family

**Required format:** native 16-bit Q1.15 at the ASQ boundary.

REZO, STREZO, and REZOMO are resonant-filter designs, but they are not
"16-bit filters" internally. Their implementation follows the preferred
native-boundary/local-widening architecture. The family explicitly rejects a
global ASQ format other than Q1.15 because its user-interface coefficients,
limiter rails, gains, and feedback tuning are deliberately expressed in native
Q1.15 units.

Important internal widths include:

- 18-bit Q3.15 multiplier operands;
- 20-bit Q3.17 state-variable-filter state, including two fractional guard
  bits;
- an 18-bit input-plus-feedback path;
- 22-bit ten-band mix and feedback accumulators;
- 24-bit output-routing accumulators;
- explicit saturation before narrowing to the 16-bit output stream.

Those wider paths are where resonance, feedback energy, band summation, and
cancellation require headroom. Globally rebuilding REZO at Q2.16 would not be
a free precision improvement: it would change the numeric meaning of constants
and shifts that were designed and hardware-qualified for Q1.15.

The REZO family should remain Q1.15 at its boundary and continue widening only
the internal operations that require it.

### TUNER

**Required format in the current development tree:** native 16-bit Q1.15.

TUNER's CV command protocol and production NSDF detector frontend are signed
16-bit interfaces. An accidental Q2.16 build changed the physical interpretation
of firmware CV commands and fed an 18-bit stream into a fixed signed-16 detector
boundary. The result included incorrect output voltage and possible truncation
of loud detector inputs.

The current TUNER development tree rejects a widened-ASQ build. Its calibration
profiles remain stored in microvolts, so the stored profile representation is
independent of the internal sample format.

Native 16-bit is appropriate here because:

- the detector's frequency accuracy comes primarily from timing and NSDF
  interpolation, not additional amplitude codes;
- Q1.15 already provides approximately 0.3-cent CV code spacing at 1 V/oct;
- four-channel detector buffers and arithmetic have a meaningful resource
  cost;
- the firmware/hardware CV interface has a single, unambiguous scale.

Any detector calculation that later needs wider products or accumulators should
widen those calculations locally rather than changing the global converter
format.

## Build and maintenance rules

Sample format must not remain undocumented state in a developer's shell. For
each bitstream:

- assert a required format in source when constants or interfaces depend on
  it;
- otherwise, make the selected format an explicit target/build option;
- record width and integer/fractional-bit counts in artifact metadata;
- test any supported alternative formats;
- keep firmware scaling derived from hardware-reported fractional bits where
  practical;
- explicitly rescale, round, and saturate at every narrowing boundary;
- never assume that a wider top-level ASQ automatically improves effective
  analog resolution.

The decision should be driven by the widest meaningful intermediate value,
acceptable rounding error, measured output quality, FPGA resource use, and
timing closure—not by ancestry or the intuition that a larger bit count is
always better.
