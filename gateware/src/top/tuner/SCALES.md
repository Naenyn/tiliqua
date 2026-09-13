# Scale architecture

Primary development branch: `codex/tuner`. TUNER is a working product name.
The prior `codex/tuner-nsdf-integration` branch is retained as a checkpoint.

## Implemented foundation (not yet connected to live QUANT)

`fw/src/scale.rs` implements allocation-free nearest-degree quantization over
validated, borrowed interval tables. Values are signed millicents (0.001 cent),
not MIDI note numbers or a twelve-bit mask. Tables begin at zero, are strictly
increasing, and exclude the positive repeat interval itself. Non-octave periods
and negative input pitches are supported. Root is separate from the table.
At most 128 degrees are accepted; this is an explicit initial implementation
limit, not a claim to support every Scala file. No silent truncation is allowed.

Binary search bounds per-sample work. Multiple channels can borrow one immutable
table rather than duplicate it. Five-cent midpoint hysteresis is capped at one
quarter of each neighboring interval, preserving access to dense tunings.
Integer overflow is an error, not a wrapped pitch. The caller retains existing
DAC limits, range holding, stale-CV checks, and explicit output arming.

Host tests cover chromatic compatibility, irregular and fractional intervals,
non-octave repetition, negative pitches, root offsets, dense-scale hysteresis,
invalid tables, maximum size, overflow, and comparison with an exhaustive oracle.
The installed firmware still uses its previously qualified chromatic path.

## Next integration

1. Add preset selection and root controls using this representation, then wire
   the shared engine into standalone QUANT. Test output ownership and reset
   quantizer history on tuning changes; do not alter calibrated PLAY implicitly.
2. Add independent channel routing with measured CPU/FPGA budgets. Keep scale
   storage shared where possible and profile correction downstream of scale
   quantization, so nominal operation never requires an oscillator profile.
3. Add computer-side Scala `.scl` import and scale editing. Read the authoritative
   format specification before implementing its parser. Convert ratios/cents
   outside the real-time loop; reject malformed, oversized, or unrepresentable
   scales with useful errors. Keyboard mapping (`.kbm`) is a separate feature.
4. Define versioned scale storage independently from oscillator profiles. Import
   into staging storage, validate completely, then publish while outputs are
   stopped. A failed import must leave the previous scale and profiles intact.
5. Add TRS MIDI note learning/transposition. Conventional MIDI note learning
   supplies twelve-tone intervals; it must not overwrite an imported microtonal
   scale without an explicit user action.
6. Evaluate USB MIDI hosting and future upstream USB mass-storage support
   separately for resource use, compatibility, and safe port/power ownership.
   Keep file transport separate from parsing and playback. Encoder editing is
   a convenience, not the only long-term authoring/import mechanism.

No Scala import, thumb-drive support, USB MIDI, custom-scale persistence, or
multi-channel quantization is claimed implemented by this foundation.
