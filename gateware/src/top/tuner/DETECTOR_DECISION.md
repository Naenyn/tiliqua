# Detector decision: close the alternative-algorithm experiment

**Migration update:** user chose to trial NSDF for calibration rather than keep
two analysis paths indefinitely. The NSDF build now supplies the measurement
bank for CAL/VERIFY and optional PLAY audio checks as well as the tuner. Hardware
acceptance is pending; the old detector/verifier is retained temporarily for
rollback/diagnostic comparison, not the intended final architecture. No resource
reclamation is credited until removal and a fresh full build are verified.
The original decision below records the preceding checkpoint.

## Decision

Keep the installed **NSDF tuner views plus existing calibration/playback detector**
as the feature-development baseline. Stop comparing alternative detector families
and stop optimizing aggressive FM tracking. Continue on
`codex/tuner-nsdf-integration`; this decision does not merge another branch,
remove the original detector, change profile formats, or require a new flash.
The selected hardware build configuration remains `TILIQUA_TUNER_NSDF=1`;
its default continuous scheduler drives both tuner views. Installed firmware
at this decision is `f1c0f323`.

This is an engineering selection for the intended instrument, **not proof that
NSDF is universally more accurate, faster, or cheaper**. No further hardware
comparison is necessary to resume feature work. Reopen the decision only for a
reproducible normal-use failure or a measured feature-budget problem.

## Evidence and tradeoffs

| Criterion | Original implementation | Integrated NSDF | Decision implication |
|---|---|---|---|
| Basic oscillator tuning | Synthetic and user hardware evidence; already useful | Synthetic/RTL/firmware parity plus quiet, low/high-frequency and four-input hardware trials | Both meet the demonstrated basic use case; no blanket accuracy winner |
| Richer periodic waveforms | Raw crossing estimate failed on recorded narrow pulse and modulated Blade | Offline waveform-period estimates are more convincing on those same captures; live pulse trials also exist | Favor NSDF for general tuner display, while acknowledging capture-window and intended-pitch ambiguity |
| Steady-note absolute accuracy | No independently calibrated frequency-reference campaign | No such campaign either; snapshot agreement is not an external reference | Do not market an absolute-accuracy improvement |
| Moving pitch | Short counting windows but transitional averages are possible | Native-priority fix avoids cross-window veto; long low bank still rejects aggressive FM | Adequate tested knob/sweep behavior, not a modulation tracker guarantee |
| Calibration / corrected CV | Substantial live sweep, verify, refine, save/recall and PLAY validation | Not integrated as the authoritative measurement source for those workflows | Preserve the existing calibrated-output path |
| Resources | Retained pre-NSDF netlist: 33/56 EBR, 10/28 DSP | Qualified combined build: 46/56 EBR, 15/28 DSP, ~21086/24288 LUT4 | NSDF is materially more expensive; do not call it an efficiency win over baseline |

The original system is a hysteretic positive-crossing measurement plus firmware
verification/qualification, not just the raw number in a capture header. The
early spectral/NSDF/YIN comparison ranked candidate references; it did **not**
compare the complete original firmware against complete NSDF on matched live
signals. Neither that comparison nor current display trials prove superiority
for calibration. The rationale here is useful additional waveform coverage plus
demonstrated integration, rather than an invented comprehensive benchmark score.

## Current performance budget

Combined FPGA final routed timing passed all configured clocks (main 65.52/60,
pixel 87.90/74.25, serializer 434.97/371.33, audio 70.25/49.152 MHz).
The installed firmware-only updates reuse that verified FPGA image.
Four-input continuous captures generally measured roughly 11 analyses/second
per bank. Measured selector/guard CPU work was roughly 6–7% on several four-tone
captures, **not total CPU utilization or worst-case execution time**. Acquisition
and serial diagnostics remain bounded; UART stalls do not queue pitch work.

CPU RAM remains 32 KiB, with no heap or CPU score-frame allocation. There is
no measured whole-program stack high-water guarantee. Unallocated FPGA capacity
is 10 EBR, 13 DSP and about 3202 LUT4; mapping and timing can change on rebuild.
This is enough to pursue compact feature work, not a promise that every planned
feature fits. Retiring the old verifier could potentially reclaim resources but
is **not credited** and is not a prerequisite for proceeding.

## Scope of acceptance

- NSDF supplies tuner markers/note/frequency in both four-channel views.
- Existing independent level meters still supply RMS/Vpp.
- CAL/VERIFY and optional PLAY audio checks retain baseline measurements.
- Quantization processes CV, not detected audio pitch; it must remain independent
  of NSDF qualification, cadence, and signal loss.
- No weakened confidence thresholds, extrapolated pitch, or stale-result hold.
- No FFT/spectrum display, more detector banks, larger CPU RAM, or further
  modulation research as prerequisites for the remaining features.

Next feature priority is independent multi-channel quantization, reusing the
existing integer pitch/CV math and renderer. Before enabling four outputs,
explicitly validate output ownership, aggregate real-time cost and live-memory
lifetimes. Preserve the working single-channel calibrated playback path while
developing that capability. Calibration improvements should be requirements-led,
not coupled to another detector migration.

## Reproducible evidence

- [Original accuracy history](ACCURACY.md): dated crossing-counter tests and limits.
- [Candidate comparison](FFT_EXPERIMENT.md): same-recording waveform comparisons,
  including raw-header versus full-system caveats.
- [NSDF arithmetic and bank model](NSDF_HARDWARE_EXPERIMENT.md): synthetic results,
  FFT tradeoffs, known aliasing failures; early budgets are superseded.
- [Integration log](NSDF_INTEGRATION.md): actual target CPU, routed build, source
  guards, four-input cadence, hardware removal/reconnection and motion results.
- [Resource audit](RESOURCE_HEADROOM.md): baseline allocation and future-memory
  constraints; its proposed retirement savings remain conditional.
- `tests/test_nsdf_motion_budget.py`: 440 actual-selector synthetic chirps;
  native/low window limitations, not a physical frequency-reference certificate.

The focused NSDF suite passed 138 tests at the preceding checkpoint. Known
unsupported/aliased waveform cases remain documented; a clean test run does not
erase those limitations. The working original branch remains available as a
fallback; no historical branches were rewritten or removed.
