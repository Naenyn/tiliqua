# INTONO Profile Library

A static web utility for Intono's 24 saved slots: eight calibration
profiles, eight user scales, and eight route configs. No server runs on the instrument, and no cloud service receives
profile data. This needs the profile-transfer Intono firmware and gateware;
earlier images do not implement the protocol or its receive queue.

**[Open the hosted librarian](https://naenyn.github.io/tiliqua/intono/)** in desktop
Chrome or Edge. No installation or local server is required.

To run it locally instead, from the repository root:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory web/intono
```

Open http://localhost:8765 in desktop Chrome or Edge (Web Serial required).
Connect Tiliqua's **USB debug serial port**, choose **Tiliqua R5 apfbug…** with **Connect device**,
and launch INTONO from the factory bootloader. Close competing serial monitors.
The instrument's USB-C musical MIDI limitation is unchanged: musical MIDI uses
its 3.5 mm MIDI input. The debug USB connection is used only for profile data.

1. Stop calibration, all running routes, and Reference CV.
2. **Read from device** creates a complete local snapshot of all 24 slots.
   It does not activate anything on the instrument. If any read fails, the old
   local snapshot is retained.
3. Calibration profiles can be inspected, renamed, exported, or imported.
   Renaming preserves every measured point and quality field. Scales can be
   edited across 1–8 octaves; choices are intervals, not root notes. Scales and
   configs can be named to identify them on the instrument. Invalid name edits
   remain visible when switching slots or tabs; correct them before writing or
   exporting. Names use 1–24 printable ASCII characters.
4. **Write this slot to device** asks before replacing that saved slot, then
   reads it back and compares every byte. Active RAM profiles/routes stay as
   they were. **Write changes to device** reviews and writes changed slots across
   all three tabs, with the same read-back check for every slot. Reload the saved
   profile on the instrument to apply changes.
5. **Export library** backs up the local snapshot. **Import library** changes
   only the local snapshot; use bulk write or write desired slots individually.
   Empty slots in an imported file do not erase device profiles. Reading again replaces local
   edits after confirmation.

**Try a demo** works without hardware. No edits persist across a browser reload;
export a file or write a slot to keep them. Export a current device snapshot
before replacing profiles. Files contain the exact versioned records and CRCs,
so old calibration versions and legacy two-octave scale records can round-trip.

## Scala files

On the Scales tab, **Import JSON / Scala** accepts `.scl` files. The file's
implicit unison and final repeating period become an INTONO interval pattern;
the root key still belongs to the route. Import is local until you confirm an individual or bulk device write. Microtonal tunings require Scala-capable firmware.

### Import limits and rejected files

- Maximum file size: **100,000 bytes**, including comments and descriptions.
- **1–128 listed pitches**, including the final repeating period; starting unison
  (0 cents) is implicit and is not listed separately.
- Pitch values and the repeating period must lie between **0.001 and 9600 cents**
  (eight octaves), and pitches must be strictly ascending after rounding to
  **0.001 cent**. Duplicate or descending pitches are rejected.
- Ratios use positive integer numerators and denominators, each at most
  9,007,199,254,740,991 (JavaScript's exact integer limit).
- `.kbm` mappings, the original description, and original ratio notation are
  not retained. Scala export writes the stored intervals as cents.

Files exceeding these limits are rejected with an error before replacing the
local slot. They are **not truncated** to fit. Import never writes to the device;
saving requires a confirmed **Write this slot to device** or
**Write changes to device** action.

Scala-capable firmware preserves microtonal intervals and non-octave periods in
`TSC1` records: up to 128 degrees, positive ascending pitches, and a repeating
period of at most 9600 cents. Values are rounded to 0.001 cent, not to semitones.
The importer accepts cents, positive integer ratios, comments, and pitch labels.
The final pitch defines the period; unison is implicit. Descriptions and original
ratio notation are not stored. The interval editor shows cents and accepts Scala
text edits; apply them before exporting or writing. Drafts survive slot changes,
but a browser reload still requires exporting/writing first.

Whole-semitone patterns with whole-octave periods use the existing keyboard
format, preserving on-device editing. Other tunings show degree count and period
on INTONO, together with a strip showing every degree across the repeating
period and six interval values per page in cents. Select **PAGE**, click, then
turn the encoder to browse all intervals; click again to finish browsing.
These tunings are read only on the device and are edited
through this utility. Closely spaced strip markers can overlap at screen
resolution; stored values retain their full precision. On a route, **LOAD USER SCALE**
loads the slot; root, NEAREST/EQUAL mapping and transpose remain route properties.
Calibration correction also works with the imported intervals.

A saved config refers to an imported tuning's user slot, whereas keyboard
patterns remain embedded snapshots. Keep that slot unchanged to recall the same
tuning. Replacing it affects subsequent config loads, not an already loaded RAM
table. A missing or invalid Scala record rejects the entire config load.

**Export Scala** exports intervals as cents, including the final period. Scala
always includes unison, so exporting a keyboard pattern with interval zero
disabled is refused instead of silently adding it. `.kbm` keyboard mappings are
not supported. This is scale-file support within the stated limits, not every
feature of the Scala desktop application.

Microtonal transfer requires the new firmware: HELLO capability bit 0 advertises
TSC1 support. The browser blocks those writes to older firmware. Existing
profiles remain readable: settings/legacy records stay in the first 8 KiB,
expanded calibration in the next 16 KiB, and scale writes use a separate new
12 KiB journal with legacy read fallback. No existing saved-data addresses move.

Format reference: [Scala scale file specification](https://www.huygens-fokker.org/scala/scl_format.html).

## Transport and limits

`protocol.mjs` and firmware `profile_transfer.rs` implement the same v1 protocol:
32-byte frames, 16-byte chunks, CRC8/ATM per packet, and one request/reply in
flight. HELLO describes the version and bank sizes; READ enumerates known slots
and transfers records. BEGIN / WRITE / COMMIT stage a single upload; ABORT or a
10-second idle expiry discards it. No write occurs until the complete record is
validated by the existing firmware codec. Stored records retain their CRC32.
The browser does not retry COMMIT automatically after a lost acknowledgement;
read the slot before retrying because the write may have succeeded.

The device exposes kind 0 (calibration), kind 1 (scale), and kind 2 (config),
each with slots 1–8. There is no arbitrary key, address, or erase operation. All flash
access uses the existing journal and calibration's legacy fallback window.
Transfers are rejected while any output operation is active. The transfer state
lives in foreground-only PSRAM, with no new static SRAM allocation. A 64-byte
distributed-memory RX queue complements the existing 16-byte TX queue; no new block RAM
is needed. Diagnostic serial output pauses during a transfer lease while pitch
acquisition continues.

## GitHub Pages hosting

`.github/workflows/intono-pages.yml` runs the Node tests before publishing the
static librarian at `https://naenyn.github.io/tiliqua/intono/`. The site root
redirects there. Pushes to `naenyn` deploy only when this folder or the workflow
changes; pull requests targeting `naenyn` run tests without deploying.

One-time repository setup:

1. Open **Settings → Pages** and choose **GitHub Actions** as the source.
2. If the `github-pages` environment restricts deployment branches, allow `naenyn`.
3. Commit and push the workflow and librarian changes to `naenyn`.

For manual deployment, use **Actions → Intono librarian website → Run workflow**
and select `naenyn`. GitHub shows this manual control only once the workflow also
exists on the repository's default branch (currently `main`). Automatic deployment
from `naenyn` does not require changing the default branch.

GitHub Pages has one deployed site per repository. This workflow publishes the
librarian, not the separate documentation site; it does not combine both sites.
The existing documentation workflow remains unchanged. HTTPS-hosted Web Serial
still requires desktop Chrome or Edge and permission to access the USB debug
serial port. Profile data stays in the browser and on the connected instrument.

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

## Saved scale names

Keyboard scales and imported Scala tunings can be named in the web editor with
1–24 printable ASCII characters. Writing the slot saves the name together with
its intervals. Scala imports initially use the file description (trimmed to 24
characters; unsupported characters become `?`). Rename it before writing if needed.

Intono shows the selected slot's name without loading it, and uses loaded names
on the Scala summary and route cards. Long route labels are shortened to fit.
Unnamed slots remain readable. Scale Tools is hidden for imported tunings,
which are edited in the web library.

Named records use a checksummed `TSN1` envelope around the existing scale record;
this firmware still reads older unnamed records. Older firmware must be updated
before writing named scales. JSON backup/export preserves names. Configs keep
Scala slot references; keyboard configs retain their embedded interval snapshot
and display its slot name only while that slot still matches the snapshot.

## Route config backups

The **Configs** tab reads the eight saved route config slots. It shows all four
routes, their input and outputs, per-output quantization and calibration settings,
and each route's MIDI transpose settings. **Config name** accepts 1–24 printable
ASCII characters. Writing a config stores its name and settings without loading
it into the active routes; load it on Intono to apply it, with outputs stopped.

Export a config individually as JSON or use **Export library** to include all
24 slots: eight calibration profiles, eight scales, and eight route configs.
Importing a library only changes the local snapshot. Use **Write changes to
device** to review and restore all nonempty imported slots, or write individual
slots. Restore referenced calibration and Scala slots to their original
slot numbers too. Keyboard interval patterns are embedded in configs. Unsaved
route edits and temporary RAM calibration profiles are not included.

Named configs use a checksummed `TCN1` envelope around the unchanged `TQS` record.
Firmware advertises config transfer support separately; older firmware can still
transfer profiles and scales. Its library export contains those two banks only.
Older two-bank library backups remain importable and leave the local config bank
untouched. Empty backup slots never delete device records.

The built-in 24 EDO preset is no longer in the selectable preset list. Import a
24 EDO Scala tuning to use quarter tones through the interval display instead.

## Writing changes together

**Write changes to device** reviews changed, nonempty slots across Calibration,
Scales, and Configs. Confirm the slot numbers and names before writing. Stop
calibration, routes, and Reference CV first. Apply pending Scala interval text
edits before starting; the bulk action is unavailable until they are applied.

Transfers run sequentially, with calibration and scales before configs. Each
slot is read back and verified before its local change marker is cleared.
Progress shows the current slot and completed count. An error stops the batch;
failed and unattempted slots retain their local edits for retry. If an
acknowledgement is lost, the failed slot may already have been written; inspect
it before retrying. Empty local slots never delete saved device profiles.
The operation is not an all-or-nothing transaction: verified writes remain saved
if a later slot fails. Active route settings are not changed by saved-slot writes.

## Understanding pending changes

Gold highlights mean **Not written to device**. A banner counts pending slots
across all three tabs; each tab shows its own count, and affected slots have a
gold edge and an explicit label. The selected profile also shows this status.
Indicators appear when editing or importing, including unfinished Scala text
edits. Apply those interval edits before writing or exporting.

Local edits live only in the current browser tab. **Export profile** saves the
selected slot to a file; **Export library** saves the whole local snapshot.
Neither changes INTONO, so exporting does not clear the pending-device markers.
Only a successful, verified device write clears a slot's marker. Importing a
library marks its nonempty slots for writing; empty slots never delete profiles.

Keep the tab open until you write or export anything you want to keep. Refreshing
or closing it loses local edits; the browser warns before leaving with pending
changes. Reading from the device replaces local edits after confirmation.
The librarian edits saved slots, not current working profiles in RAM or live
routes. Load a saved slot on INTONO when you want to apply its new contents.
