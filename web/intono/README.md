# INTONO Profile Library

A static, local web utility for Intono's eight calibration slots and eight user
scale slots. No server runs on the instrument, and no cloud service receives
profile data. This needs the profile-transfer Intono firmware and gateware;
earlier images do not implement the protocol or its receive queue.

From the repository root:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory web/intono
```

Open http://localhost:8765 in desktop Chrome or Edge (Web Serial required).
Connect Tiliqua's **USB debug serial port**, select it with **Connect device**,
and launch INTONO from the factory bootloader. Close competing serial monitors.
The instrument's USB-C musical MIDI limitation is unchanged: musical MIDI uses
its 3.5 mm MIDI input. The debug USB connection is used only for profile data.

1. Stop calibration, all running routes, and Reference CV.
2. **Read from device** creates a consistent local snapshot of all sixteen slots.
   It does not activate anything on the instrument. If any read fails, the old
   local snapshot is retained.
3. Calibration profiles can be inspected, renamed, exported, or imported.
   Renaming preserves every measured point and quality field. Scales can be
   edited across 1–8 octaves; choices are intervals, not root notes. Scale names
   are not stored in the existing device format, so slots are labeled User scale.
4. **Write this slot to device** asks before replacing that saved slot, then
   reads it back and compares every byte. Active RAM profiles/routes stay as
   they were. Reload the saved profile on the instrument to apply changes.
5. **Export library** backs up the local snapshot. **Import library** changes
   only the local snapshot; write desired slots individually. Empty slots in an
   imported file do not erase device profiles. Reading again replaces local
   edits after confirmation.

**Try a demo** works without hardware. No edits persist across a browser reload;
export a file or write a slot to keep them. Export a current device snapshot
before replacing profiles. Files contain the exact versioned records and CRCs,
so old calibration versions and legacy two-octave scale records can round-trip.

## Transport and limits

`protocol.mjs` and firmware `profile_transfer.rs` implement the same v1 protocol:
32-byte frames, 16-byte chunks, CRC8/ATM per packet, and one request/reply in
flight. HELLO describes the version and bank sizes; READ enumerates known slots
and transfers records. BEGIN / WRITE / COMMIT stage a single upload; ABORT or a
10-second idle expiry discards it. No write occurs until the complete record is
validated by the existing firmware codec. Stored records retain their CRC32.
The browser does not retry COMMIT automatically after a lost acknowledgement;
read the slot before retrying because the write may have succeeded.

The device exposes only kind 0 (calibration), kind 1 (scale), and slots 1–8.
There is no arbitrary key, address, erase, or route-config operation. All flash
access uses the existing journal and calibration's legacy fallback window.
Transfers are rejected while any output operation is active. The transfer state
lives in foreground-only PSRAM, with no new static SRAM allocation. A 64-byte
register RX queue complements the existing 16-byte TX queue; no new block RAM
is needed. Diagnostic serial output pauses during a transfer lease while pitch
acquisition continues.

## Tests

```sh
node --test web/intono/tests.mjs
cd gateware/src/rs/opts
cargo test --target aarch64-apple-darwin --test intono_profile_transfer --test profile_journal
cd ../../../..
```

Gateware: `gateware/.venv/bin/python -m pytest gateware/tests/test_tuner_buffered_uart.py`
with the gateware package on the Python import path (normally run from gateware).
Browser tests cover demo editing, invalid imports, offline write blocking, and
responsive layout. Device qualification is recorded separately with the build.
