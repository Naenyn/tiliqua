# REZO build performance log

This log tracks resource use and final post-route timing for significant REZO
builds. Keep failed experiments: placement seed sensitivity is material at
720p60, and a failed result can prevent repeating an unproductive build.

## Method

- Target: Tiliqua R5 / SoldierCrab R3 (`LFE5U-25F`)
- Audio rate: 192 kHz
- Video mode: 1280x720p60
- Build command: `pdm run rezo build --fs-192khz`
- Seed override: `TILIQUA_REZO_SEED=<n>`
- Resource figures and frequencies come from the final `top.tim` report.
- Required clocks: DVI5X 371.33 MHz, AUDIO 49.15 MHz, SYNC 60.00 MHz,
  DVI 74.25 MHz.

The formal optimization baseline is **OPT-BASE** below. New feature builds
should be compared against its 21,668 packed cells and 2,620 free cells while
also passing every constrained clock.

## Results

| ID | Source/change | Seed | LUT4 | Packed cells | Free | FF | BRAM | DVI5X MHz | AUDIO MHz | SYNC MHz | DVI MHz | Result |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| PRE-OPT | `2038cb9d`, before renderer/control optimization | 8 | — | 24,228 | 60 | 5,898 | 6 | 443.26 | 61.66 | 69.75 | 76.74 | PASS; historical comparison |
| OPT-S8 | Optimized renderer/control paths, final tree | 8 | 18,282 | 21,668 | 2,620 | 5,894 | 10 | 363.11 | 63.88 | 65.75 | 78.84 | FAIL DVI5X |
| **OPT-BASE** | `2b464d50`, optimized renderer/control paths | **4** | **18,282** | **21,668** | **2,620** | **5,894** | **10** | **404.53** | **64.35** | **64.86** | **79.56** | **PASS; baseline** |
| DRIVE-S4 | DRIVE effective-value shading and base marker, direct geometry | 4 | 18,399 | 21,811 | 2,477 | 5,906 | 10 | 359.07 | 58.08 | 62.38 | 79.57 | FAIL DVI5X |
| DRIVE-S8 | DRIVE effective-value shading and base marker, direct geometry | 8 | 18,399 | 21,811 | 2,477 | 5,906 | 10 | 412.88 | 59.50 | 63.11 | 83.10 | PASS; superseded by shared-renderer experiment |
| DRIVE-SHARED | DRIVE shading/marker; shared BANK DRIVE/RES/FB renderer | 8 | 18,288 | 21,648 | 2,640 | 5,921 | 10 | 400.00 | 58.53 | 62.01 | 82.39 | PASS; pre-palette comparison |
| PALETTE-RUNTIME | Five semantic RGB palettes and ADVANCED selector | 8 | 18,378 | 21,778 | 2,510 | 5,984 | 11 | 396.20 | 62.07 | 64.75 | 80.61 | PASS; runtime selection, persistence pending |
| PALETTE-PERSIST | Palette selection plus delayed audio-board EEPROM restore/save | 8 | 18,494 | 21,894 | 2,394 | 5,986 | 11 | 406.34 | 60.59 | 62.11 | 77.39 | PASS; first hardware candidate |
| PALETTE-PERSIST-FIX | REZO-only NVM opt-in, combined read, checked write and commit delay | 8 | 18,499 | 21,907 | 2,381 | 6,012 | 11 | 431.03 | 61.43 | 62.93 | 82.36 | PASS; upper-half address failed hardware persistence |
| NVM-7F-S8 | Move preference into writable lower half, dense address `0x7f` | 8 | 18,549 | 21,963 | 2,325 | 6,012 | 11 | 353.23 | 61.53 | 60.13 | 81.77 | FAIL DVI5X |
| NVM-7F-S4 | Same writable `0x7f` candidate | 4 | 18,549 | 21,963 | 2,325 | 6,012 | 11 | 370.23 | 60.02 | 57.98 | 81.87 | FAIL DVI5X and SYNC |
| NVM-60-S8-DELAY | Sparse writable `0x60`, separate 5 ms commit counter | 8 | 18,514 | 21,922 | 2,366 | 6,012 | 11 | 425.35 | 60.03 | 59.98 | 79.42 | FAIL SYNC by 0.02 MHz |
| NVM-60-S2-DELAY | Same sparse writable candidate | 2 | 18,514 | 21,922 | 2,366 | 6,012 | 11 | 329.49 | 60.32 | 64.65 | 80.23 | FAIL DVI5X |
| PALETTE-NVM-DISCONNECTED | Writable `0x60`, NACK retry, no redundant commit counter | 8 | 18,529 | 21,939 | 2,349 | 5,993 | 11 | 398.57 | 60.98 | 64.75 | 76.90 | PASS; persistence bridge was absent from active top |
| PALETTE-NVM-CONNECTED-S8 | Persistence bridge and 100 ms save timer connected in active `RezoBeamTop` | 8 | 18,611 | 22,033 | 2,255 | 6,047 | 11 | 365.90 | 62.14 | 61.89 | 81.93 | FAIL DVI5X |
| **PALETTE-NVM-CONNECTED-S4** | Same connected persistence design | **4** | **18,611** | **22,033** | **2,255** | **6,047** | **11** | **383.44** | **63.04** | **64.17** | **80.30** | **PASS; hardware candidate** |
| SAVE-DEFAULT-FIXED-DECODE | Full-state dual-sector journal; explicit 42-word UI decoder | 4 | 22,227 | 25,715 | -1,427 | — | 13 | — | — | — | — | FAIL capacity |
| SAVE-DEFAULT-SCAN-INTERMEDIATE | Circular state stream replacing read/write decoders | 4 | 20,298 | 23,734 | 554 | — | 13 | — | — | — | — | Routing stopped; inadequate congestion/headroom |
| **SAVE-DEFAULT-SCAN-S4** | Slot-derived full-state journal; scan stream, coarse UI registers, palette folded into explicit save | **4** | **19,759** | **23,221** | **1,067** | **6,568** | **13** | **384.62** | **73.76** | **62.50** | **79.85** | **PASS; unflashed candidate** |
| SAVE-DEFAULT-CS-GAP-S4 | Four-cycle flash recovery in a shared journal gap state | 4 | 20,145 | 23,617 | 671 | 6,580 | 13 | 401.28 | 73.36 | 66.28 | 71.85 | FAIL DVI |
| SAVE-DEFAULT-CS-INLINE-S4 | Recovery folded into journal wait states | 4 | 20,336 | 23,822 | 466 | 6,578 | 13 | 389.41 | 74.87 | 64.10 | 77.71 | PASS; excessive packing cost |
| SAVE-DEFAULT-CS-BRIDGE-WAIT-S4 | Recovery centralized in SPI bridge with an added wait state | 4 | 20,381 | 23,853 | 435 | 6,578 | 13 | 386.10 | 77.09 | 63.90 | 75.10 | PASS; excessive packing cost |
| SAVE-DEFAULT-CS-COUNTDOWN-S4 | Compact physical-CS recovery countdown, no added FSM state | 4 | 20,104 | 23,566 | 722 | 6,579 | 13 | 319.28 | 72.71 | 64.80 | 78.98 | FAIL DVI5X |
| **SAVE-DEFAULT-CS-COUNTDOWN-S8** | Same compact recovery netlist | **8** | **20,104** | **23,566** | **722** | **6,579** | **13** | **396.67** | **71.66** | **64.50** | **79.87** | **PASS; hardware candidate** |
| SAVE-CONFIRM-CANCEL-S8-A | Encoder turn cancels confirmation and navigates away; first structural form | 8 | 20,239 | 23,717 | 571 | 6,579 | 13 | 356.38 | 73.04 | 63.29 | 77.82 | FAIL DVI5X; superseded before flash |
| SAVE-CONFIRM-CANCEL-S8-B | Shared navigation assignment structural form | 8 | 20,255 | 23,729 | 559 | 6,579 | 13 | 359.84 | 69.96 | 64.52 | 77.50 | FAIL DVI5X; superseded before flash |
| SAVE-CONFIRM-CANCEL-S8-C | Confirmation represented as a transient navigation target | 8 | 20,258 | 23,736 | 552 | 6,579 | 13 | 356.38 | 56.44 | 61.50 | 77.30 | FAIL DVI5X; superseded before flash |
| SAVE-CONFIRM-CANCEL-S8-D | Edit-mode cancellation on an encoder quadrature edge, local parity decode | 8 | 20,402 | 23,878 | 410 | 6,579 | 13 | 352.73 | 75.02 | 64.36 | 80.66 | FAIL DVI5X; superseded before flash |
| SAVE-CONFIRM-CANCEL-S8-E | Dedicated confirmation latch and display synchronization | 8 | 20,323 | 23,801 | 487 | 6,584 | 13 | 386.85 | 69.34 | 63.55 | 76.92 | PASS; superseded before flash due to packing cost |
| **SAVE-ONE-CLICK-S4** | Remove confirmation state; SAVE DEFAULT requests immediately on click | **4** | **20,312** | **23,784** | **504** | **6,579** | **13** | **396.35** | **74.48** | **64.87** | **78.11** | **PASS; hardware candidate** |

## Notes

- The optimization traded four additional block RAMs for 2,560 fewer packed
  logic cells, increasing free packed cells from 60 to 2,620.
- DVI5X timing is dominated by the existing TMDS serializer and is highly
  placement-sensitive. A feature can leave REZO logic timing healthy while a
  particular seed fails the independent serializer path.
- Sharing the BANK DRIVE/RES/FB row renderer more than offset the added DRIVE
  animation geometry: DRIVE-SHARED uses 20 fewer packed cells than OPT-BASE.
- PALETTE-RUNTIME adds one block RAM, 130 packed cells, and 63 flip-flops over
  DRIVE-SHARED. The five themes share one semantic-role lookup and all clocks
  pass at seed 8; LCD remains pixel-equivalent to the previous renderer.
- PALETTE-PERSIST-FIX adds 129 packed cells and 28 flip-flops over the
  runtime-only palette build. It reuses the existing pure-RTL I2C master only
  when REZO opts in, reserves writable EEPROM byte `0x60` after limiting the
  boot-config allocation to `0x40..0x5f`, and coalesces changes for 0.1 seconds.
  EEPROM reads use a repeated START and writes are checked for NACK. The
  100 ms save-coalescing interval exceeds the EEPROM's 5 ms internal write
  cycle, avoiding a separate commit-delay counter.
- Hardware testing exposed that the initial `0x80` location is in the
  24AA025UID's write-protected upper half. The final design formally reserves
  lower-half byte `0x60`; boot configuration retains `0x40..0x5f` (32 bytes,
  versus only a few bytes currently serialized). A protocol-level I2C test
  verifies the exact repeated-START read and palette write transactions.
- Hardware testing then exposed an integration error: the persistence control
  had been placed in the obsolete `RezoSoc`, while builds use the lean
  `RezoBeamTop`. Earlier persistence resource reports therefore measured only
  the I2C peripheral; the unconnected controller was optimized away. The
  connected design adds 94 packed cells and 54 flip-flops over that report and
  is covered by a bridge-level restore/write-request simulation.
- Seed 10 of the `NVM-60-S8-DELAY` netlist also failed DVI5X at 361.93 MHz;
  the other passing-clock figures were not retained before the next run.
- Timing comparisons are only meaningful after routing. Pre-route estimates
  are not recorded in the table.
- SAVE-DEFAULT reserves two 4 KiB sectors in the option window belonging to
  the slot validated from the bootloader EEPROM record. No slot number is
  hardcoded and an invalid record disables saving. The version-1 payload uses
  84 bytes while reserving format capacity for 2 KiB of future state.
- The first full-state implementation exceeded capacity because its wide
  addressable read and restore decoders synthesized to 25,715 packed cells.
  A 42-cycle circular scan stream removed those muxes. The final candidate
  also retains encoder-quantized controls at their meaningful precision and
  expands them to the same 16-bit DSP values, and stores palette in the
  explicit default record instead of auto-writing the audio-board EEPROM.
- The snapshot memory must carry `ram_style=block`: at its current 42-word
  logical depth, unconstrained inference selects distributed LUT RAM and costs
  roughly 700 packed cells. The on-flash 2 KiB growth reservation does not
  require synthesizing unused RAM addresses.
- The first hardware save attempt reached `ERROR`; a read-only JTAG dump of
  the active slot-4 option window contained no `REZO` record, showing that the
  page-program command had not committed rather than merely failing CRC
  validation. The CPU-free flash sequencer had only one 60 MHz cycle of CS#
  recovery between write-side transactions. The final bridge detects the
  journal's existing deselect edge, holds physical CS# inactive for four full
  cycles, and stalls transfer launch until recovery completes. A PHY-level
  simulation measures this interval and rejects any early data launch.
- Several correct recovery implementations were retained above because their
  logically small structural differences produced large packing changes in
  this congested design. The final countdown version has 287 more LUT4s and
  345 more packed cells than the pre-recovery SAVE-DEFAULT-SCAN-S4 result,
  leaving 722 packed cells. Seed 8 is required for the recorded passing
  placement; seed 4 fails only the independent DVI5X serializer path.
- Confirmation-state experiments are retained in the table because small
  control-flow changes caused disproportionate packing and routing effects.
  The final UI follows other Tiliqua bitstreams: SAVE DEFAULT is an explicit
  one-click operation with no confirmation mode. Seed 8 entered a pathological
  placement search for this netlist and was stopped; rerouting the exact same
  synthesized JSON with seed 4 passed every constrained clock.
- UI/DSP functional regressions are checked separately by
  `tests/test_rezo_compare_path.py`, `tests/test_rezo_display.py`, and
  `tests/test_rezo_ui.py`.
