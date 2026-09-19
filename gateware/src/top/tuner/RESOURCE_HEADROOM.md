# Resource headroom audit: tuner, calibrator, quantizer

**Current September 19 build `1e586139`:** the combined instrument with bounded
low-bank refinement uses 19347 LUT4, 45/56 EBR and 14/28 DSP. All final routed
clocks pass (system 66.12/60 MHz). CPU RAM remains 32 KiB. The added lag range
costs one EBR, not an additional detector. Live CPU/cadence validation of this
build awaits bootloader selection; do not reuse old measured CPU budgets as
proof of this build's runtime. See [calibration evidence](AUTO_CALIBRATION.md).
The allocation model below is historical, not the current netlist count.

Analysis checkpoint, September 11, 2026. Production firmware is unchanged.
Actual netlist counts are distinguished from planned allocations and schedule
models. This is not a combined bitstream fit/timing result.

## Current measured allocation

`tests/tuner_resource_audit.py` reads the retained TUNER `top.json` directly:

| Consumer | Memory blocks (EBR) |
|---|---:|
| CPU working RAM, 32 KiB | 16 |
| CPU instruction cache | 1 |
| Framebuffer FIFO | 1 |
| Palette | 3 |
| Shared text/menu/sprite display | 10 |
| Existing pitch verifier | 2 |
| **Total** | **33 / 56** |

The display's 10 blocks are four tile, one menu, two font, and three sprite
blocks. The background framebuffer is external memory, not a hidden full-frame
EBR allocation. Do not cut display functionality or CPU working RAM simply to
make a detector fit.

Ten DSP blocks: CPU four, codec calibration one, four level-measurement lanes
one each, verifier one. Replacing the verifier could reclaim two EBR and one
DSP, not all five signal-measurement DSPs: level metering is still required.
No reclamation is credited until firmware no longer needs the old verifier or
its diagnostic capture buffer and replacement behavior is validated.

## Candidate allocations, not whole-design synthesis

| Stage | Planned EBR | Unallocated EBR |
|---|---:|---:|
| Naive NSDF addition, duplicate histories, old verifier retained | 50 | 6 |
| Reuse native filter history for high-bank snapshots | 46 | 10 |
| Then retire old verifier and its private history | 44 | 12 |

The 44-block case is 33 existing + 2 NSDF score engine + 1 filter coefficient
ROM + 4 shared native histories + 4 low-rate histories + 2 score handoff banks
- 2 retired verifier blocks. DSP estimate is 10 + 3 + 1 - 1 = 13 / 28.
The earlier 50-block layout is a useful conservative control case, **not the
recommended final allocation**. Keep the default isolated score engine; do not
assume a memory-port rewrite saves another EBR.

Target at least this twelve-block unallocated margin before further optional
visual features. It is a planning guardrail, not a guarantee that every future
feature fits. Track LUT usage, CPU load and full routing too; EBR is only one
constraint. An extra FFT/spectrum display is not presently justified by this
budget and is not required by NSDF.

## Shared-history safety model

`nsdf_shared_history_probe.py` models one write and one read port shared across
four 1024-word channel rings. Four native samples arrive in four consecutive
cycles every 312/313 cycles at 60 MHz (192 kHz per channel). Each /32 boundary
requests four FIR jobs of 769 reads. Four detector requests each use two passes
of 674 reads from the same frozen head: mean calculation then centered copy.
Jobs are non-preemptible; FIR has priority at dispatch. Every read checks a
sequence-number tag, detecting an overwritten or mixed-generation sample.

83 request-phase cases over a /32 interval, including sample/filter boundaries:

- Maximum snapshot request-to-completion: 8468 cycles, 141.13 us.
- Maximum FIR request-to-completion: 4422 cycles, 73.70 us, below 166.67-us deadline.
- Oldest sample read: 779 samples behind the current head, within 1024 capacity.
- No overwrite mismatches or missed filter deadlines in these cases.

A negative test uses only 769 words/channel and does fail from overwrite.
The extra ring capacity is essential, not gratuitous padding. Four 1024x16
rings still fit the previously allocated four 18-kbit memory blocks.

This is **not** synthesized arbitration: arithmetic pipeline drain, bus bridges,
write/read collision behavior, coefficient reads and full clock-domain handling
still need RTL tests. Snapshot copying must be bounded hardware work. Unbounded
CPU/PSRAM stalls invalidate this model; abort and retry a late snapshot rather
than processing overwritten data. The native history must continue accepting
samples while filtering and snapshots run. Low-rate histories remain separate.

## Failed score-memory optimization retained as evidence

Added an opt-in `--shared-load-port` variant to the isolated score-engine
synthesis probe. Sharing a loading address with a computation read port did not
reduce inferred memory: two EBR remained. With write-through permission (safe
because that read is disabled while loading), synthesis still used two EBR and
increased LUT4/FF from 537/472 to 560/489. The preceding nontransparent attempt
was 558 LUT4, also two EBR. The default remains the original implementation.
Do not count the hoped-for one-block frame store in any budget.

## CPU RAM is a separate and important cliff

The actual `luna_soc.gateware.core.blockram.Peripheral` requires a power-of-two
size. Current CPU RAM is 32 KiB. A normal resize to 64 KiB costs 16 additional
EBR. Even the proposed 44-block detector design would become **60 / 56**.
An arbitrary 40-KiB resize is rejected by that peripheral; an extra separately
mapped bank would need an explicit memory-map/linker/ownership design.

The target-compiled `tuner_memory_layout_probe.rs` uses the real firmware types:

| Type, RISC-V 32-bit target | Bytes |
|---|---:|
| 121-point Profile | 1004 |
| Existing single-channel playback Engine, including profile storage | 1092 |
| Four such Engines, arithmetic size only | 4368 |

Cloning three more engines would add 3276 bytes over one. That is not proof
that they fit the live stack, nor a recommendation to clone the entire adapter:
its output ownership/control interface is currently single-channel. Firmware
already retains calibration/review state and nested interrupt frames. Explicitly
account for concurrent lifetimes and peak stack; allocated stack space is not
measured unused headroom.

121 points cost 968 bytes of point payload per curve. Four stored flash slots
do not require four new FPGA memories; only active runtime curves need resident
storage. Scales likewise should be compact data, not independent renderers or
full voltage lookup tables for every channel. Prefer immutable active profiles
and explicit staging/ownership to accidental repeated copies. Do not move
time-critical ISR profile access to external memory just to hide RAM pressure.

## Preserve independent real-time work

- Quantization consumes calibrated **CV samples**, not detected audio pitch.
  Its output deadlines must not depend on NSDF qualification or a 20-Hz tuner
  publication cadence. Optional audio checks remain observers.
- Keep one shared detector engine; four copies of it or of the UI are not needed.
- Four-channel NSDF at 20 analyses/channel/second occupies ~46% of its own
  60-MHz engine, **not 46% of the CPU**. CPU selection and CV playback need a
  separately measured budget. NSDF produces ~51,520 score words/second before
  selection; bus/CPU costs must be bounded, not inferred from the word rate.
- Existing profile lookup already uses a bounded binary search (at most seven
  comparisons for 121 points), followed by integer interpolation. Four-channel
  CV processing should reuse that math and existing calibrated DAC transport,
  with new explicit per-output ownership/acknowledgment safeguards.
- Historical single-channel PLAY peak was 6536 cycles (~109 us). Four times
  that observation is ~436 us per millisecond, before additional overhead.
  It is **not** a measured worst-case four-channel bound. The existing aggregate
  half-millisecond compute safeguard would have little margin under that simple
  extrapolation, so benchmark real four-channel worst cases before committing.
- Late pitch jobs should be skipped/marked stale without starving quantized
  output, encoder handling or watchdog service. Calibration must still require
  fresh, settled pitch data; do not silently accept stale estimates.

## Next analysis/integration gates

1. Build and verify the bounded shared-history/filter RTL against the model.
2. Measure CPU peak selection/refinement and four-channel CV processing together.
3. Audit target stack high-water and nested calls with four active profiles.
4. Only then replace the old verifier and run a full resource/timing build.
5. Preserve the unallocated margin; decline optional spectrum work if it erodes
   capacity needed for the calibrator and standalone quantizer.

Reproduction from `gateware`:

```
python tests/tuner_resource_audit.py /path/to/qualified/top.json
python tests/nsdf_shared_history_probe.py
python -m pytest -q tests/test_nsdf_shared_history.py tests/test_nsdf_direct_rtl.py
rustc --edition=2021 --target riscv32im-unknown-none-elf --crate-type lib --emit=llvm-ir tests/tuner_memory_layout_probe.rs -o /tmp/tuner-memory-layout.ll
```

The target LLVM globals `PROFILE_LAYOUT` and `PLAYBACK_LAYOUT` expose type sizes;
these are not whole-call-tree stack measurements. Negative port-optimization
reports are `/tmp/tuner-nsdf-shared-load-synth.log` and
`/tmp/tuner-nsdf-shared-load-transparent-synth.log`.
