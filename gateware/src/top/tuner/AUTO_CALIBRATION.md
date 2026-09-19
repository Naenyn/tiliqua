# Automatic calibration — September 18, 2026

This is the current UI/workflow specification. It supersedes the manual
VERIFY/REFINE instructions in older investigation documents. Hardware testing
of this automatic controller is pending; its state machine is host-tested.

## Simple workflow

- TUNER observes audio inputs, with spiral and linear views.
- CAL selects the audio input, CV output and nominal 0 V note. RUN starts an
  upward -5..+5 V measurement, automatically checks the resulting curve, then
  attempts guarded improvements when appropriate. RUN again cancels.
- PROFILES is reached from CAL. It offers eight oscillator slots and a
  read-only CHECK of an accepted/loaded profile. CHECK still drives the
  oscillator; "read-only" means it never changes the curve.
- SCALES edits the selected output's scale, notes, root, transpose and mapping.
  NOTES and SETUPS are child pages, not separate top-level modes.
- ROUTES selects input/output, optional quantization and optional correction.
  BIND snapshots the selected correction profile. RUN is available here only,
  and requires at least one processing stage. Quantization precedes correction.

Child-page headers return to the parent; all menus fit the existing eight-row
box. Navigation does not stop running operations. CAL reserves its input/output
through the entire automatic sequence, including transitions between stages.
Other nonconflicting routes may continue running.

## What automatic means

1. Measure an initial curve and discover its usable range.
2. Check corrected pitches on a 50-cent grid within that range, including the
   existing local repeatability measurements at the worst location.
3. If error exceeds 2 cents and the local response is suitable, measure one
   additional interior point and independently check the local candidate.
4. Recheck the full range. Retain the insertion only if worst absolute error
   improves by at least 0.5 cents. Otherwise undo it and retain the last fully
   checked candidate. Repeat only while useful and within the limits below.
5. Return output to commanded calibrated zero and present a review. ACCEPT
   replaces RAM only; SAVE in PROFILES is separate. Neither starts playback.

The 2-cent target is best effort, not a guaranteed specification. A 50-cent
verification grid samples the response; it cannot certify every intermediate
pitch. Noise, drift, range boundaries or a nonrepeatable response can prevent
refinement. The result explains why it stopped. Retuning requires a new scan.

The accepted profile and saved slots remain untouched during work. Cancellation
keeps them. A timeout/fault cannot offer a candidate that never completed its
first check; after a successful check, a failed tentative improvement is rolled
back. An operation is bounded to eight improvement attempts and 15 minutes
total, not eight unbounded rescans. No flash writes happen inside the loop.

## Point count and storage budget

The initial 121 positions provide semitone voltage spacing across ten volts.
That is a sensible baseline for a smooth oscillator response, not proof of
sufficient precision for every oscillator. We measure interpolation error and
place extra points where needed rather than increasing every scan's density.

There are eight additional point slots: at most 129 stored points. A limited
initial range may contain fewer than 121 anchors; the eight-attempt limit still
applies. Original anchors are never discarded to make room. If the bounded
refinement cannot meet the target, present the measured result rather than
silently claiming success or looping forever.

Eight oscillator profiles fit the existing 16-KiB profile journal alongside the
unchanged separate settings allocation. Each maximum TUCP v2 payload is 1,072
bytes: eight total 8,576 bytes before journal overhead. Repeated save/garbage
collection and interrupted collection of eight full records are tested. More
slots would require a fresh journal-capacity/recovery budget, not just a larger
menu number. Runtime playback still holds only four bound curves, not all eight
stored profiles. CPU RAM remains 32 KiB.

Existing profile keys and flash reservation are unchanged. Older v1/v2 profiles
remain readable. Firmware predating this change cannot read a 129-point record
or select slots 5–8; do not assume backward compatibility after downgrading.

## Validation and next hardware check

Host coverage includes complete automatic operation, navigation during work,
successful refinement, rejection of full-range regressions, cancellation,
deadline and output-fault rollback, profile serialization, journal recovery and
actual menu labels/navigation. The broader 176-test regression suite passes.

On hardware, run CAL once with the existing calibration patch and stable sine.
Confirm that measuring, checking and any justified improvement proceed without
manual VERIFY/REFINE selections, ending at review with output zero. Accept and
save only after reviewing it. A curve already within 2 cents should finish
without an improvement pass. Then test concurrency with unrelated routes.

See [USB storage](USB_STORAGE.md) for removable-library work that is not yet
enabled in this build.
