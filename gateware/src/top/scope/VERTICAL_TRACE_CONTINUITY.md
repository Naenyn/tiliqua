# SCOPE vertical trace gaps and flicker

This note documents why steep edges (saw resets, square fronts) can appear as
dashed vertical lines or flicker on the Tiliqua SCOPE bitstream, what has already
been tried, and what could be done next.

Related gateware:

- Capture: `tiliqua/raster/scope_capture.py` (`ColumnCapture`)
- Render: `tiliqua/raster/scope_render.py` (`ColumnRenderer`)
- Reference line plotter: `tiliqua/raster/trace.py`
- Plot upsampling: `tiliqua/dsp/resample.py` (`LinearResample` in `top/scope/top.py`)

Build at **192 kHz** (`pdm run scope build --fs-192khz`) so `n_upsample = 8` and
the scope sample rate matches the intended plot density.

---

## Symptoms

At faster timebases (e.g. 1 ms/div), a saw or square wave may show:

1. **Spatial gaps** — the near-vertical segment looks dashed or dotted rather
   than a solid stroke.
2. **Temporal flicker** — the vertical (and sometimes the whole trace) shimmer
   between sweeps or while the trace is painting left-to-right.

These are related but not the same problem. Peak **overshoot / wiggle** at the
saw reset (where the vertical meets the ramp) was a separate issue; see
[Peak overshoot at discontinuities](#peak-overshoot-at-discontinuities) below.

---

## Architecture: column envelopes, not line segments

SCOPE does **not** plot consecutive `(x, y)` sample pairs as connected segments
(like `trace.py`). Instead:

1. **Capture** walks the horizontal ramp and, for each screen column `x`, stores
   only **ymin** and **ymax** — the vertical span of all samples that landed in
   that column during the sweep.
2. A compact back buffer holds the entire completed sweep.
3. **Render** reads the frozen sweep and draws each **vertical bar** from ymin
   to ymax at that `x` (via the line plotter as a 1-pixel-wide strip).

A steep edge is really a **segment** between two points. The envelope model
stores independent min/max boxes per column. If column *N* only sees the bottom
of the edge and column *N+1* only sees the top, and neither box spans the full
height between them, the display shows **two short bars with empty pixels
between** — the dashed vertical line.

---

## Root causes

### 1. Information lost at column boundaries

When `in_x` advances to a new column, capture **flushes** the previous column’s
envelope to the renderer. Before the steep-edge bridge (commit `e808670`), the
flushed envelope for the **old** column reflected only samples that landed **in
that column**. The sample that crossed into the **new** column carried the other
end of the vertical jump, but that Y value was **not** included in the old
column’s flush.

### 2. Erase-then-draw

The renderer updates columns left to right after a complete sweep:

1. Read what was previously shown for this column (`shown_mem`).
2. **Erase** the old vertical span (black segment).
3. **Draw** the new vertical span.

Compact completed-sweep buffering prevents partially acquired traces from
reaching the renderer. Some short-lived pixel flicker can remain because:

- During the render pass, columns are still updated sequentially.
- On each new triggered sweep, changed columns are erased and redrawn again.
- If the envelope shifts by even one pixel between sweeps, erase removes pixels
  before draw replaces them.

This is separate from the **spatial** dashed-gap problem but contributes to the
overall “flickering” feel.

### 3. Horizontal quantization and speed

At some timebases the ramp may advance more than one column per audio sample, or
a very fast vertical edge may span only one or two columns per sample. A column
can receive **no samples** — a true hole in the trace. This is worse at very
fast timebases.

### 4. Same-column jumps

Large `|Δy|` **within** a single column is already handled by expanding
`col_ymin` / `col_ymax` while samples accumulate. The main gap case is at
**column transitions**, not within one column.

### 5. What the current bridge does not fix

- Adjacent columns where both have partial envelopes but the bridge threshold
  (`VERTICAL_DY_THRESH = 2`) is not met.
- **Sweep-to-sweep** erase/redraw flicker inside the completed render pass.
- **Skipped columns** when X advances faster than one column per sample.
- Diagonal continuity between columns (envelopes are vertical bars only, not
  sloped segments).

---

## Peak overshoot at discontinuities

Overshoot or “wiggle” at the saw peak (where the vertical meets the ramp) was
observed when the plot path used the **band-limited FIR resampler**
(`dsp.Resample`). A hard discontinuity plus a low-pass filter produces Gibbs
overshoot — this is not necessarily AK4619 codec ringing.

**Mitigation (commit `ab785f1`):** replace FIR upsampling on the SCOPE plot path
with **`LinearResample`**, which stays within the two source samples and cannot
overshoot a saw reset. Still build at 192 kHz.

---

## Current mitigation: steep column envelope bridge

**Commit `e808670`** — when a sample step **crosses a column boundary** with
`|Δy| ≥ VERTICAL_DY_THRESH` (2 px), extend the **flushed** min/max envelope to
cover **both** the previous and current sample Y before the renderer sees it.
Same idea as `steep_step` in `trace.py`.

Implementation: `scope_capture.py` — `flush_ymin` / `flush_ymax` derived from
`col_ymin` / `col_ymax` with bridge logic on `col_changing`.

---

## Possible improvements (smallest change → largest shift)

| Approach | Effect | Cost |
|----------|--------|------|
| **Lower `VERTICAL_DY_THRESH`** (e.g. 1, or bridge on any column change with Δy≠0) | More aggressive envelope extension; fewer spatial gaps | Slightly fatter vertical strokes on shallow slopes |
| **Bridge on every column change** | Always include previous sample Y in flush | May over-draw on gentle slopes |
| **Inflate steep envelopes ±1 px** | Guarantees overlap with neighbors | Slight thickening |
| **Write bridge span into both columns** | Extend old column flush *and* seed new column ymin/ymax from bridged range | Moderate gateware change |
| **Same-column `vertical_jump`** (like `trace.py`) | Connect when large Δy without column change | Mostly covered by min/max already |
| **Segment mode for steep steps** | On steep boundary, emit a **line segment** (x0,y0)→(x1,y1) instead of a column bar | Renderer path similar to `trace.py` / `LineStripCmd` |
| **Sample-to-sample line plotter** | Plot consecutive (x,y) with line strips; no column envelope | Best continuity; abandons column-envelope capture |
| **Full-sweep buffer, draw once** | Implemented by `CompletedSweepBuffer`; capture all columns, then render | Removes partial-sweep painting; adds one acquire/render cycle of latency |
| **Union erase** (draw new without erasing old first, or erase union of old+new) | Reduces flicker when envelope jitters | Earlier experiments caused layering/partial-waveform regressions — needs careful design |

---

## Recommended next steps

If spatial gaps remain after `e808670`:

1. **Tune the bridge** — try `VERTICAL_DY_THRESH = 1` or bridge whenever
   `col_changing` and `visible` and `|Δy| > 0`.
2. **Dual-column seeding** — on a steep step, initialize the **new** column’s
   ymin/ymax from the bridged range, not only extend the old column’s flush.
3. **Steep → segment fallback** — if `|Δy|/|Δx|` exceeds a threshold, push one
   diagonal `LineStripCmd` through the existing per-channel line plotter (as
   `trace.py` does for continuous diagonals and verticals).

If residual **flicker** (temporal) dominates over **gaps** (spatial):

- Revisit the per-column erase/draw policy (e.g. only erase when disjoint from new
  envelope, or defer erase until draw completes).
- Avoid naive “union erase” or per-sweep full clears without regression tests —
  those paths previously caused partial waveforms and layering.

---

## Summary

- **Dashed vertical lines** are primarily a **representation** issue: independent
  column bars plus Y values lost at column boundaries — not trigger lock or
  sample rate.
- Compact completed-sweep buffering removes live partial-sweep painting; the
  remaining flicker is the framebuffer's per-column erase/draw interval.
- **Peak wiggle** at saw resets was addressed by **linear** plot upsampling
  instead of FIR (`ab785f1`).
- **Boundary gaps** are partially addressed by the **steep envelope bridge**
  (`e808670`); fully solid fast edges may still need **dual-column seeding** or
  **segment drawing**.
