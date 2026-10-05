# Profile Library qualification — 2026-10-04

Source: `acb11d55` plus the synchronized receiver change on
`codex/intono-profile-manager`.
Utility instructions: [Profile Library](../../../../web/intono/README.md).

## Build and flash

R5, 1280×720p60, seed 22, spread spectrum disabled. Archive:
`build/intono-profile-rx-sync22-r5/intono-profile-rx-sync22-acb11d-d-r5.tar.gz`.
SHA256: `142229c9ed2f35fa6bb3541cda706236d0768e6061f15b65b406109983a14627`.
Archive firmware/bitstream were compared with the build files before flashing.
Slot 1 flash completed with `Refresh: DONE` on device E46534A193222B21.
Option storage remains 24,576 bytes; the flasher preserves its existing contents.

| Resource | New image | Reference CV baseline |
| --- | ---: | ---: |
| Firmware bytes / 327,680 | 327,008 | 327,056 |
| LUTs / 24,288 | 21,859 | 21,992 |
| Flip-flops / 24,288 | 12,258 | 12,246 |
| Block RAM / 56 | 51 | 51 |
| Multipliers / 28 | 14 | 14 |

Final timing: system 67.67 MHz / 60 required; audio 70.75 / 49.15;
video 83.30 / 74.25; serializer 435.92 / 371.33. All passed.
The linker reports `_ebss=0x1fac`, `_stack_start=0x8000`: unchanged 24,660-byte
static-to-stack margin. Transfer state occupies 1,200 bytes in foreground-only
PSRAM. The receive FIFO uses distributed memory and adds no block RAM.

## Automated and browser checks

- Six Node tests: record CRCs and migrations, every octave mask, calibration
  rename preservation, packet resynchronization, full-size transfer/read-back,
  and busy/error handling without retrying COMMIT.
- Four firmware exchange tests plus 41 existing journal tests: bounded
  transfers, malformed packets, timeouts, rejection before persistence, legacy
  codecs and journal interruption/garbage collection.
- 51 navigation and 62 route-render regression tests passed.
- Seven UART simulations passed, including a complete 64-byte receive burst,
  repeated FIFO wraparound, and simultaneous serial reception/32-bit Wishbone
  reads at three foreground polling rates.
- Opt-in continuous and continuous-pair diagnostic configurations compile.
- Browser demo: calibration rename, interval toggles, eight-octave editing,
  preservation of hidden octave intervals, offline write blocking, and phone
  width without horizontal overflow. No browser console errors observed.

## Hardware transfer checks

The original image had a receive-path fault. Browser connection returned
HELLO successfully, but reading profiles timed out. Native serial tests also
show intermittent corruption before bytes reach the profile parser. A temporary
raw capture confirmed one exact 32-byte packet and valid reply, followed by
other packets with incorrect received bytes. For example, the normal HELLO
`4950010100010000000000000000000000000000000000000000000000000065`
was captured as
`4950010100010000000000000004040808101020204040808000000000000065`.
This is evidence of a receive-path fault, independent of profile storage.
Those initial diagnostic tests did not write saved profiles.

The receiver used the logical UART pin interface without a clock-domain
synchronizer; unlike the platform-pins constructor, this interface does not
insert one automatically. A two-stage synchronizer has now been added. Seed 21
was stopped after prolonged routing congestion; seed 22 completed with the
passing timing results above. Temporary raw capture code is removed.

The synchronized image passed native serial hardware checks:

- Read and backed up all sixteen slots. Four calibration profiles and two scales
  were present; one scale uses the legacy 12-byte format.
- Rejected an invalid scale at COMMIT; its saved slot remained unchanged.
- Re-saved existing scale slot 1 byte-for-byte through the actual flash journal,
  then verified its complete contents by reading it back.
- Re-read all sixteen slots and compared exact bytes with the backup; all were
  unchanged, including empty slots.

Backup: `/tmp/intono-device-library-before.json`.
Browser-to-device reading of all sixteen slots passed twice. Re-saving the
existing Waveplane calibration through the browser also passed complete
byte-for-byte read-back verification; its name and measured points were not
edited. The browser
permission picker should select Tiliqua R5 apfbug, not a display adapter. Native
tests and the browser must not hold the serial port at the same time.
