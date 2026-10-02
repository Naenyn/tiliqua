# Intono review and route MIDI — October 2, 2026

This reviews the current `codex/intono-ux` working tree, including the preceding
single-input/multiple-output route change. The rack is off; this update has not
been flashed or verified on the physical module. Preserve the last working
`intono-ux-groups-20261002-r5.tar.gz` image for comparison.

## Findings corrected

1. **Group fault cleanup depended on foreground progress (P1).**
   `main.rs`, `timer0_handler`/`MultiQuant::stop_group`: a lane could stop in the
   interrupt while other members remained active until foreground cleanup ran.
   The interrupt now stops all outputs of that claimed group and releases its
   claim before committing the staged output batch. Explicit disable commands
   take effect immediately in `tiliqua/dsp/calibration_output.py`; they do not
   wait for the next batch. Other groups keep running. Foreground cleanup remains
   a fallback for whole-engine scheduling/budget stops.
2. **MIDI learning merged held keys across channels (P2).**
   `midi_learn.rs`: a note-off on another channel could release a held key, allowing
   a subsequent repeat to toggle its scale note again. Each learning session now
   follows its first note's MIDI channel. Learn-base/disarm clears held state and
   channel selection; base octave survives disarming. Invalid data bytes are
   rejected. This costs a small channel tag, rather than 16 separate held-key maps.
3. **Range advice retained the old +5 V boundary (P2).**
   `calibration/discovery.rs`: the higher-tuning suggestion now requires the
   actual +8 V boundary. A partial +5 V curve cannot justify that suggestion.
   Endpoint subtraction now widens before subtracting, and an unrepresentable
   slope returns no estimate instead of wrapping. Normal calibration arithmetic
   and acceptance thresholds are unchanged.
4. **Loaded scale snapshots lost their identity (P2, presentation).**
   `quantizer_setup.rs`/`main.rs`: an output now retains its saved scale slot as
   provenance. Loading/successfully saving a scale sets this tag. Changes to its
   preset, intervals, or octave span clear it; key/transposition changes preserve
   it. The overview displays that slot or the preset/custom name. This remains a
   snapshot: overwriting a saved slot does not silently mutate running outputs.

## Added behavior

`ROUTES > ALL ROUTES` shows all four physical outputs together: route group,
input, RUN/OFF/FREE, oscillator profile source, scale source, root key, and manual
transpose. The final count row includes empty groups. Setup load/save remains on
this page. OSC sources are RAM or slot numbers; full profile names remain on the
individual output's editor/monitor.

`ALL ROUTES > MIDI ROUTE` configures each logical route independently:

- MIDI channel OFF or 1–16; OFF is the default.
- ZERO is any MIDI note, default C4 (MIDI 60).
- RELEASE defaults to HOLD; ZERO optionally returns to zero offset when the last
  controlling note is released. Releasing an earlier/different note is ignored.
- RESET clears its current offset. Changing channel/base/release also clears it.

A note sets a semitone offset from ZERO, in addition to the output's manual
transpose. It applies to every output assigned to that route, including corrected
continuous pitch. MIDI does not change jack ownership or automatically start an
output. Channels may be shared intentionally. Scale learning temporarily owns
MIDI input exclusively, so it cannot also transpose routes.

The interrupt drains at most four MIDI messages per millisecond while learning
is off, even with outputs stopped. Offset application occurs at the beginning of
an output batch; the two half-batches share the same MIDI/CV snapshots. Note
hysteresis is invalidated when the offset changes, while an outstanding DAC ACK
is preserved. Physical output limiting still applies.

TQS5 setup records are 132 bytes with a checksum. They persist route membership,
per-output interval snapshots/provenance, and per-route MIDI channel/base/release.
Live MIDI offsets and armed state are deliberately not restored. TQS1–TQS4
records migrate with MIDI OFF, C4/HOLD, and no saved-scale provenance.

## Math and logic review

Reviewed profile monotonic insertion/refinement/binary interpolation, measured
0 V anchoring, signed CV conversions, nominal fallback, output clamping, scale
nearest/equal distribution, negative cycles, roots/transposition, eight-octave
pattern compilation, calibration discovery/acquisition/replay averaging and
freshness, profile/scale/setup serialization, route reservation/lane teardown,
MIDI learning, frame exchange and background cache ownership.

The existing math tests compare binary interpolation and quantization against
linear/exhaustive references, and native arithmetic against wide arithmetic.
Interpolation products fit u64; lookup rejects out-of-range targets. Averaging
uses i64 sums and independent-window checks, reports instability, and does not
hide gross span behind the mean. Snapshot readers reject torn reads after four
attempts. Playback continues enforcing stale-CV, DAC ACK, scheduling and CPU
budget stops. Calibration still has one captured input/output pair and retains
all policy checks and timing logging. No accuracy relaxation was introduced.

Eight octaves remain a reasonable limit: eight 12-bit masks use 16 bytes, and a
compiled conventional pattern stores at most 96 exact u8 semitone indices, not
96 i32 values. One octave remains the default. Imported fractional scales retain
exact i32 degrees. Reducing the UI maximum would not address the earlier large
calibration-stack allocation.

## Resource review

Release ELF for this update: `_ebss = 0x1a90`, stack top `0x8000`.

| Item | Bytes |
| --- | ---: |
| Total initialized/static SRAM | 6,800 |
| Available stack region | 25,968 |
| MULTI_QUANT (included above) | 5,268 |
| APP (included above) | 1,432 |
| Main frame | 1,216 |
| Retained run closure frame | 9,472 |
| Startup frame, released before run | 12,528 |
| Interrupt callback frame, excluding callees/trap | 320 |

These are compiled allocations, **not a proof of maximum combined stack use**.
The linker still requires at least 24 KiB for the stack. Calibration Live remains
in explicitly initialized NOLOAD PSRAM at +5 MiB, below caches at +8 MiB. Five
1 MiB cache reservations finish at +13 MiB, within 16 MiB PSRAM and below boot
information. DMA/cache flushing and scene publication retain their existing
ownership protocol. No heap, expanded SRAM, relaxed firmware-slot size, or extra
profile copy was introduced for this feature.

## Remaining checks and limitations

- Measure stack watermark and worst interrupt cycles on the rack with four
  changing outputs, MIDI traffic, scale editing, and calibration. Host tests do
  not establish physical interrupt latency or total stack high-water use.
- MIDI FIFO depth is eight. Transpose service is now interrupt-driven, but scale
  learning still drains in the foreground. Dense MIDI during unusually slow
  foreground work can drop events; no overflow counter currently exposes that.
- RELEASE ZERO follows the last note; it does not implement a held-note priority
  stack, sustain pedal, pitch bend, or MIDI clock. HOLD is the default requested
  behavior. MIDI offsets are intentionally lost on reboot/setup reload.
- The prior transient colored horizontal flashes are not proven resolved.
  Frame/background/palette simulations pass, but those do not reproduce every
  real HDMI/PSRAM timing condition. Keep the video health and boot/timing logging.
- Overview labels show saved source slots, not mutable links. Profile availability
  still requires APPLY before starting after a setup recall. Saved scale slots
  have no user-defined names yet.

## Validation

- 254 calibration/live/playback host tests pass, including new MIDI composition,
  ACK preservation, continuous-pitch offset, output limiting, and range advice.
- 55 scale/UI/setup host tests pass, including TQS5 roundtrip, every-byte corruption,
  legacy migration, channel matching, note bounds and optional release behavior.
- 20 real option/encoder navigation tests pass, including MIDI controls/defaults.
- 5 MIDI learning tests pass, including cross-channel note release.
- 52 FPGA/UI/background/frame/palette/scale/output simulations pass; 10 existing
  unsupported static-source combinations are skipped.
- `git diff --check` passes. Full FPGA timing and artifact details are recorded
  below after build completion. Hardware testing is pending.

## Qualified build

Artifact: `build/intono-ux-midibase-r5/intono-ux-review-midi-20261002-r5.tar.gz` (not flashed).
SHA-256: `6201fe6d1a04c9735413602f6a1ecfee2c00cfd3020c3b8ede8c9989cfb5e48a`. Firmware is 315,584 / 327,680 bytes;
12,096 bytes remain. The previous grouped-route image was 307,536
bytes, so this update adds 8,048 bytes. Static SRAM grows by 136 bytes from the
preceding 6,664-byte allocation. Keep monitoring ROM growth as UI work continues.

Final seed-19 timing: serializer 434.97 / 371.33 MHz, pixel 86.30 / 74.25 MHz,
audio 67.30 / 49.15 MHz, CPU 67.35 / 60.00 MHz: all PASS. The FPGA uses 46 / 56
DP16KD blocks and 19,969 / 24,288 LUT4s (82% each). Final timing qualification,
archive hash and test counts are saved in `review-midi-validation.json`; the
matching release ELF is saved as `review-midi-firmware.elf` beside the archive.

### Morning test order

1. Flash the qualified archive to Tiliqua #1 slot 1, then capture boot/video health
   and the stack watermark. No flash was attempted while the rack was off.
2. Check ALL ROUTES against the physical patch, including a group with two outputs
   and an empty group. Verify assigned-jack exclusion during calibration selection.
3. Enable a route MIDI channel. With zero C4, play C4/C5/C3: offsets should be
   0/+12/-12 semitones on every group member. Release should hold. Try another MIDI
   channel, a different zero note, RESET, and optional RELEASE ZERO.
4. Test scale learning independently; its first note sets both octave and channel.
   Learning should edit intervals without transposing running routes.
5. Save/recall a setup with custom scale slots and MIDI settings. Settings restore;
   outputs stay off and MIDI offset resets. APPLY the selected oscillator profiles
   before starting. Test a previously saved TQS4 setup too.
6. Run AUTO with the existing Waveplane patch, preserving timing logging. Capture
   minimum stack margin and interrupt cycle maximum with all desired routes active
   outside calibration, and repeat HDMI page transitions to assess line flashes.


## Morning flash status

After the rack was powered up, the qualified archive was flashed successfully
to Tiliqua #1 slot 1 on October 2. Erase, write and FPGA refresh completed.
The offline-review statements above describe the overnight state; physical
feature, stack-margin and interrupt-latency verification remains pending.
