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
| OPT-JOURNAL-STREAM-S4 | Stream header validation; share active generation; remove CRC staging; shift-register CS recovery | 4 | 20,258 | 23,720 | 568 | 6,461 | 13 | — | — | — | — | Routing aborted after pathological congestion search |
| OPT-JOURNAL-SPLIT-POLL-S8 | Separate erase/program poll states; remove poll-purpose flags | 8 | 20,256 | 23,730 | 558 | 6,459 | 13 | 429.92 | 71.39 | 65.61 | 79.46 | PASS; structurally clean but negligible area gain |
| OPT-JOURNAL-HEADER-SHIFT-S8 | Hold SPI request in journal and shift generation/CRC header bytes sequentially | 8 | 20,122 | 23,592 | 696 | 6,439 | 13 | — | — | — | — | Routing aborted after pathological congestion search |
| OPT-JOURNAL-FOLDED-STATE-S4 | Reuse active-generation and stored-CRC registers for pending save state | 4 | 19,846 | 23,308 | 980 | 6,375 | 13 | 438.21 | 72.14 | 65.49 | 79.97 | PASS |
| **OPT-JOURNAL-FOLDED-ADDR-S8** | Reuse scan validity/sector/address state for boot selection and inactive save target | **8** | **19,742** | **23,206** | **1,082** | **6,373** | **13** | **411.18** | **75.60** | **65.42** | **77.41** | **PASS; final optimization candidate** |
| OPT-JOURNAL-FOLDED-ADDR-S4 | Exact `top.json` reroute of final candidate | 4 | 19,742 | 23,206 | 1,082 | 6,373 | 13 | 389.71 | 74.59 | 65.31 | 77.57 | PASS |
| OPT-JOURNAL-FOLDED-ADDR-S2 | Exact `top.json` reroute of final candidate | 2 | 19,742 | 23,206 | 1,082 | 6,373 | 13 | 488.28 | 73.17 | 67.74 | 76.60 | PASS |
| BANDS-PINNED-ABC9 | Initial editable BANDS experiment | 8 | 20,918 | 24,498 | -210 | 6,501 | 18 | — | — | — | — | INVALID for current source; stale generated RTL |
| BANDS-SYNC-ROM-S8 | Initial synchronous-cutoff experiment | 8 | 20,705 | 24,231 | 57 | 6,501 | 18 | 436.11 | 72.32 | 68.43 | 81.59 | INVALID for current source; stale generated RTL |
| BANDS-ABC2-S4 | Initial native-Yosys `abc2` experiment | 4 | 20,608 | 24,238 | 50 | 6,501 | 18 | 357.02 | 78.69 | 62.30 | 74.27 | INVALID for current source; stale generated RTL |
| BANDS-INITIAL-ARCHIVE-S8 | Initial BANDS archive observed on hardware | 8 | 20,722 | 24,250 | 38 | 6,501 | 18 | 382.56 | 71.93 | 65.89 | 75.84 | INVALID source provenance; flashed slot 4 |
| BANDS-UI-PINNED-S8 | Polished two-row UI; fresh RTL, pinned Yosys 0.52 | 8 | 20,772 | 24,420 | -132 | 6,505 | 18 | — | — | — | — | FAIL capacity |
| BANDS-UI-W175-S8 | Fresh RTL; staged native Yosys, ABC9 wire weight 175 | 8 | 20,797 | 24,449 | -161 | 6,505 | 18 | — | — | — | — | FAIL capacity |
| BANDS-UI-W200-S8 | Fresh RTL; staged native Yosys, ABC9 wire weight 200 | 8 | 20,725 | 24,385 | -97 | 6,505 | 18 | — | — | — | — | FAIL capacity |
| BANDS-UI-W150-S8 | Fresh RTL; staged native Yosys, ABC9 wire weight 150 | 8 | 20,581 | 24,255 | 33 | 6,505 | 18 | 396.04 | 70.48 | 62.80 | 68.51 | FAIL DVI |
| BANDS-UI-W150-S4 | Exact final synthesized JSON rerouted at seed 4 | 4 | 20,581 | 24,255 | 33 | 6,505 | 18 | 379.79 | 72.45 | 61.82 | 70.06 | FAIL DVI |
| BANDS-UI-W150-S2 | Exact final synthesized JSON rerouted at seed 2 | 2 | 20,581 | 24,255 | 33 | 6,505 | 18 | 441.11 | 72.30 | 57.63 | 73.11 | FAIL SYNC and DVI |
| **BANDS-UI-W150-S1** | Polished two-row UI and synchronous cutoff prefetch | **1** | **20,581** | **24,255** | **33** | **6,505** | **18** | **431.78** | **74.28** | **60.23** | **75.56** | **PASS; flashed slot 4, validation pending** |
| BANDS-FINE-W150-S1 | 116-step frequency grid, BANK-only masking, block-ROM factory loader; no disabled-edit guard | 1 | 20,604 | 24,272 | 16 | 6,514 | 19 | 432.90 | 73.65 | 59.85 | 75.68 | FAIL SYNC by 0.15 MHz |
| BANDS-FINE-INERT-W150-S1 | Add disabled BANK control guard with four-rate acceleration | 1 | 20,621 | 24,297 | -9 | 6,514 | 19 | — | — | — | — | FAIL capacity |
| BANDS-FINE-FAST-W140-S1 | Two-rate acceleration; native ABC9 wire weight 140 | 1 | 20,618 | 24,288 | 0 | 6,510 | 19 | 378.07 | 72.48 | 61.57 | 70.15 | FAIL DVI |
| BANDS-FINE-FAST-W160-PRECOMMIT-S1 | BANK-only page/masking/inert controls; 116-step grid; dirty build identifier | 1 | 20,565 | 24,235 | 53 | 6,510 | 19 | 436.87 | 71.25 | 63.71 | 75.57 | PASS; superseded by commit-stamped netlist |
| BANDS-FINE-FAST-W160-S2 | Exact final synthesized JSON rerouted at seed 2 | 2 | 20,565 | 24,235 | 53 | 6,510 | 19 | 406.83 | 73.59 | 56.97 | 72.93 | FAIL SYNC and DVI |
| BANDS-FINE-FAST-W180-S1 | Exact source mapped with ABC9 wire weight 180 | 1 | 20,588 | 24,267 | 21 | 6,510 | 19 | 451.06 | 70.06 | 63.63 | 78.74 | PASS; larger than W160 |
| BANDS-FINE-COMMIT-S1 | `04dc8771`, exact committed W160 JSON | 1 | 20,577 | 24,259 | 29 | 6,510 | 19 | 382.41 | 74.00 | 58.05 | 77.71 | FAIL SYNC |
| BANDS-FINE-COMMIT-S5 | Exact committed W160 JSON | 5 | 20,577 | 24,259 | 29 | 6,510 | 19 | 372.16 | 74.98 | 61.85 | 69.57 | FAIL DVI |
| **BANDS-FINE-COMMIT-S6** | **Exact committed W160 JSON** | **6** | **20,577** | **24,259** | **29** | **6,510** | **19** | **442.48** | **72.68** | **63.84** | **76.78** | **PASS; flashed slot 4** |
| BANDS-FINE-COMMIT-S7 | Exact committed W160 JSON | 7 | 20,577 | 24,259 | 29 | 6,510 | 19 | 389.11 | 69.57 | 62.68 | 75.73 | PASS |
| POLISH-PRECOMMIT-S6 | Centered selectors, OPTIONS layout, disabled-band frames, ordered FEEDBACK navigation, and shared gain slew across mode changes; dirty build ID | 6 | 20,575 | 24,165 | 123 | 6,510 | 19 | 437.06 | 69.37 | 66.14 | 75.32 | PASS; superseded by commit-stamped netlist |
| POLISH-COMMIT-S6 | `49783e4b`, exact committed W160 JSON | 6 | 20,476 | 24,090 | 198 | 6,350 | 19 | 393.08 | 72.26 | 66.30 | 71.36 | FAIL DVI |
| **POLISH-COMMIT-S7** | **`49783e4b`, exact committed W160 JSON** | **7** | **20,476** | **24,090** | **198** | **6,350** | **19** | **403.55** | **72.91** | **66.67** | **74.95** | **PASS; flashed slot 4** |
| POLISH-COMMIT-S8 | `49783e4b`, exact committed W160 JSON | 8 | 20,476 | 24,090 | 198 | 6,350 | 19 | 393.55 | 70.81 | 63.49 | 74.13 | FAIL DVI by 0.12 MHz |
| GROUP-GHOST-FRAMES | `bc6ebc4b`; four full rectangular GROUPS ghosts for every disabled band | 7 | 20,719 | 24,437 | -149 | 6,351 | 19 | — | — | — | — | FAIL capacity |
| GROUP-GHOST-RAILS-S7 | `b2812acc`; shared top/bottom ghost rails | 7 | 20,611 | 24,223 | 65 | 6,351 | 19 | 404.37 | 72.50 | 62.63 | 72.24 | FAIL DVI |
| **GROUP-GHOST-RAILS-S6** | **`b2812acc`; exact committed W160 JSON** | **6** | **20,611** | **24,223** | **65** | **6,351** | **19** | **387.00** | **72.22** | **62.50** | **79.25** | **PASS; flashed slot 4** |
| **CLOCKED-BANK-BASE-S1** | **`8a27f1a7`; FILTER DSP/UI/pages removed, v2 state positions reserved** | **1** | **16,512** | **19,508** | **4,780** | **5,578** | **15** | **443.07** | **76.24** | **61.16** | **80.57** | **PASS; clocked-feature baseline, not flashed** |
| **CLOCK-SHIFT-MVP-S6** | **Dirty `176cfc5e`; external DATA/CLOCK/RESET, four directions, CLOCK page** | **6** | **17,573** | **20,713** | **3,575** | **5,868** | **15** | **418.06** | **72.86** | **63.31** | **74.99** | **PASS; hardware candidate, not flashed** |
| **CLOCK-ROUTING-UI-S6** | **Dirty `176cfc5e`; BANK-like CLOCK main, direction page, DAT/CLK/RST INPUT targets** | **6** | **17,448** | **20,575** | **3,713** | **5,855** | **15** | **390.17** | **73.37** | **61.77** | **77.48** | **PASS; hardware candidate, not flashed** |
| CLOCK-ROTATE-VALUES-S6 | Dirty `176cfc5e`; sequential exact rotation with ten 16-bit value snapshots | 6 | 18,342 | 21,468 | 2,820 | 6,045 | 15 | 388.80 | 74.09 | 63.79 | 72.85 | FAIL DVI |
| **CLOCK-ROTATE-ORIGINS-S4** | **Dirty `176cfc5e`; SHIFT/ROTATE selector, mode-specific directions, four-bit origin ring, disabled-band skipping** | **4** | **18,306** | **21,448** | **2,840** | **5,953** | **15** | **449.24** | **72.82** | **61.24** | **79.00** | **PASS; flashed slot 4** |
| **CLOCK-TURING-S7** | **Dirty `7f6819a3`; full-resolution looping random register, LCK gate, LENGTH and CHANGE controls** | **7** | **19,135** | **22,307** | **1,981** | **6,051** | **15** | **394.94** | **74.58** | **61.08** | **80.28** | **PASS; packaged/flashed slot 4** |
| **CLOCK-INTERNAL-AUTO-S8** | **Dirty `7f6819a3`; physical-jack AUTO source, INT/EXT overrides, safe handoff, eight internal BPMs** | **8** | **19,524** | **22,760** | **1,528** | **6,105** | **15** | **399.20** | **72.70** | **63.61** | **80.33** | **PASS; flashed slot 4** |
| **CLOCK-TARGET-DEPTH-S7** | **Dirty `7f6819a3`; TURING ALL/RANGE targeting, one-based START, shared 17-step CLOCK depth** | **7** | **20,505** | **23,831** | **457** | **6,473** | **15** | **389.11** | **74.71** | **61.17** | **74.81** | **PASS; flashed slot 4** |
| **CLOCK-TURING-BRAM-S1** | **Dirty `c9be114a`; private TURING loop moved from dynamic register muxes to a sequential block-RAM worker** | **1** | **19,619** | **22,935** | **1,353** | **6,363** | **16** | **415.45** | **73.06** | **61.58** | **76.09** | **PASS; flashed slot 4** |
| **CLOCK-RANDOM-DATA-S2** | **Dirty `965f4783`; SHIFT DATA CV/RAND/AUTO selector and independent continuous 32-bit internal source** | **2** | **19,664** | **22,980** | **1,308** | **6,409** | **16** | **436.11** | **74.37** | **64.77** | **77.10** | **PASS; flashed slot 4** |
| **CLOCK-SAVE-V3-S2** | **Dirty `965f4783`; 46-word V3 save, V1/V2 migration, shadowed CLOCK snapshot/restore** | **2** | **19,887** | **23,199** | **1,089** | **6,409** | **16** | **400.00** | **74.92** | **60.76** | **81.78** | **PASS; flashed slot 4** |
| CLOCK-WALK-WIDE-S2 | Dirty `965f4783`; ten-band reflected random walk using a shared 17-bit add/compare path | 2 | 20,667 | 23,995 | 293 | 6,439 | 16 | 387.45 | 74.60 | 54.38 | 74.25 | FAIL SYNC; DVI at boundary, not flashed |
| **CLOCK-WALK-COMPACT-S2** | **Dirty `965f4783`; identical reflected WALK in high-byte units plus wrapped algorithm selector** | **2** | **20,417** | **23,747** | **541** | **6,439** | **16** | **443.85** | **72.80** | **62.68** | **77.89** | **PASS; flashed slot 4** |

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
- The 2026-08-03 journal optimization preserves the version-1 flash bytes,
  active-slot bounds, dual-sector selection, CRC verification, UI behavior,
  and the measured four-cycle physical CS# recovery. Header constants are
  validated as they stream in instead of being retained in separate magic,
  version, and word-count registers. Generation and CRC fields serialize
  through an existing register rather than two wide dynamic byte muxes.
- Pending save generation and CRC now reuse the active-generation and
  stored-CRC registers. If a verification fails and the user retries during
  the same boot, the next record may skip a generation number; ordering,
  sector safety, and power-loss recovery do not require generations to be
  contiguous.
- Boot-sector-A validity reuses `have_active`, and the scan sector/address
  also carries the inactive save target. This final fold produced 1,082 free
  cells, a gain of 578 over SAVE-ONE-CLICK-S4, and routed successfully from
  the exact same synthesized netlist at seeds 8, 4, and 2.
- OPT-JOURNAL-STREAM-S4 and OPT-JOURNAL-HEADER-SHIFT-S8 were stopped only
  after their detailed routers entered prolonged congestion searches. Their
  pre-route placement clock estimates are deliberately omitted from the
  table; they are not final timing results.
- BANDS implements ten enable toggles and exact stepped editing across a
  29-frequency union. Factory layouts are LEGACY, OCTAVE, and PERCEPT; editing
  or selecting USER snapshots the currently active vector, so USER never
  recalls a stale hidden shape. Version 2 expands the record from 42 to 46
  words and restores frequencies, enables, and the selected layout exactly;
  version-1 records migrate to LEGACY with every band enabled.
- Several source-level reductions were counterproductive after mapping:
  shortened layout labels, compact target IDs, small/wide label ROM variants,
  and removal of apparently redundant bounds all increased packed-cell use.
  Current-vector implementations using parallel preset muxes, sequential
  selectors, and a block-ROM loader ranged from 24,524 to 24,620 packed cells.
  The retained UI renders one frequency label and one shared selection outline.
- The first BANDS archive was accidentally packaged with an older generated
  `top.il`: `--skip-build` archives an existing `top.bit` and does not regenerate
  RTL. Its UI was visible on hardware, but its reported resources cannot be
  attributed to the then-current source. The four initial BANDS rows remain as
  invalidated diagnostics so they are not mistaken for reproducible builds.
- The polished BANDS page replaces the ambiguous tall controls with separate
  ENABLE and SET FREQ button rows, moves and labels the PRESET selector, removes
  redundant band numbers, and shows the selected frequency as an exact
  five-digit Hz value. The label table still occupies one shared block RAM.
- The project's pinned YoWASP Yosys 0.52 maps the fresh polished source 132
  cells over capacity. The final candidate uses native Yosys 0.66+152 and a
  staged `abc`/`abc9 -W 150` flow. The build CLI now forwards a fragment's
  `script_after_synth`, so generated `top.ys` records that recipe. Weights 175
  and 200 were both larger; seed 1 is the only retained all-clock passing route.
- The cutoff table is a synchronous block ROM with an explicit next-band
  prefetch after both current-band SVF passes. This avoids both the illegal
  asynchronous block-RAM mapping and the earlier one-band lag, and passes the
  known-good DSP vector.
- BANDS plus the UI polish consumes 1,049 of the 1,082 cells recovered by the
  preceding journal optimization. The final design has only 33 packed cells
  free; clocked sample
  and hold, shift, rotate, and random-walk features are therefore assigned to
  a separate alternate bitstream rather than this one.
- The follow-up BANK-only pass hides the BANDS page in FILTER mode, blanks
  disabled BANK columns and group/feedback controls, and makes those controls
  inert while disabled. Navigation may still traverse a blank disabled target
  for one detent; a full combinational skip search exceeded capacity. FILTER
  continues to use and expose all ten resonators.
- Manual frequency editing now uses 116 logarithmically spaced positions: the
  exact 29-value factory union plus three subdivisions after every center.
  Slow turns move one position and rapid turns move eight. The original five
  coarse bits per band remain byte-compatible in version 2; twenty formerly
  zero padding bits store the two fine bits per band, so old saves restore the
  same exact centers. Factory loading uses one additional block ROM rather
  than ten parallel layout muxes.
- The four-rate 1/2/4/8 acceleration guard overflowed capacity. A two-rate
  1/8 implementation retains precise/fast editing and maps materially better.
  The final staged native recipe uses `abc9 -W 160`. Changing the displayed
  identifier from the dirty tree to commit `04dc8771` perturbed packing from
  24,235 to 24,259 cells. Seeds 6 and 7 pass every clock with 29 cells free;
  seed 6 has the best retained margins and supplies the archive. Seeds 1 and 5
  fail one clock each, seed 2 was measured on the precommit JSON and fails SYNC
  and DVI, and seeds 3 and 4 were stopped after prolonged congestion searches.
- The first UI-polish route unexpectedly maps 94 fewer packed cells than the
  preceding commit even though it adds disabled-band frames and mode-change
  gain slewing. It also renames ADVANCED to OPTIONS, centers variable-width
  selector labels with fixed padding, and fixes FEEDBACK navigation order.
  This row carries a dirty identifier; the exact commit-stamped result must be
  routed and recorded separately before packaging.
- The exact `49783e4b` identifier maps another 75 cells smaller than the dirty
  candidate: 24,090 packed cells, leaving 198 free. That is 169 more free cells
  than `BANDS-FINE-COMMIT-S6`. Seed 7 passes all clocks and supplies the flashed
  archive. Seed 6 fails DVI, seed 8 misses DVI by only 0.12 MHz, and seed 1 was
  stopped after seed 7 completed rather than retained as a partial route.
- Extending disabled-band ghosts to GROUPS with forty full rectangular frames
  costs 347 packed cells over `49783e4b` and exceeds capacity by 149. The
  retained renderer shares the existing band/row decoder and draws only the
  top and bottom rails of each absent assignment. It costs 133 packed cells,
  fits with 65 free, and preserves an unambiguous inactive location. Seed 7
  fails only DVI; seed 6 passes every clock and supplies the flashed archive.
  Seed 8 was stopped once seed 6 passed rather than retained as a partial route.
- The `rezoclocked` branch begins at `CLOCKED-BANK-BASE-S1`. Removing FILTER's
  generated response engine, modulation scan, dedicated controls, hidden
  FILTER/MATRIX text pages, matrix display memory, and mode-dependent routing
  recovers 4,715 packed cells relative to the flashed release candidate. LUT4
  demand falls by 4,099, flip-flops by 773, and block RAM by four. The existing
  46-word version-2 state positions formerly occupied by FILTER remain as inert
  reserved bits, so established BANK fields and saved frequency fine bits keep
  their exact on-flash positions. The first configured seed passes all four
  clocks and is the formal capacity baseline for the shared clock/shift engine.
- ROTATE first stored ten parallel 16-bit level snapshots. Converting the
  circulating state to ten four-bit source-band origins removes 92 FF and 20
  packed cells from the sequential-value candidate, while retaining exact
  disabled-band skipping. Each destination reads the current natural BANK
  level of its circulating origin, so editing the BANK shape updates the
  rotating modulation source without reseeding the ring. Seed 4 passes every
  clock and supplies the flashed archive; seed 7 also passed a preceding
  equivalent synthesis but the final regenerated netlist routed best at 4.
- Version 3 persistence retains the 46-word V2 payload size by reusing six
  bytes from FILTER's removed modulation matrix for CLOCK configuration and
  the fourth bit of each input target. V1/V2 imports replace those repurposed
  words with safe CLOCK defaults, while every established BANK field retains
  its address. A shadow snapshot keeps the circular journal mux off the live
  sequencer paths; directly scanning the live CLOCK controls missed SYNC at
  seeds 1, 2, 3, 5, and 7. The retained seed-2 shadow route adds 219 packed
  cells over CLOCK-RANDOM-DATA-S2, keeps FF/BRAM counts unchanged, and leaves
  1,089 packed cells for follow-up modes.
- WALK advances all ten enabled bands independently on every accepted clock,
  choosing a positive or negative step per band and reflecting before either
  signed modulation rail. Its first direct implementation used a shared
  17-bit add/subtract and two 17-bit comparisons. It fit, but congestion left
  only 293 cells and seed 2 failed SYNC. Because every supported step is a
  multiple of 256, the retained implementation performs the exact same walk
  in signed high-byte units and restores the zero low byte on writeback. It
  recovers 250 LUT4 and 248 packed cells from the wide attempt. Replacing the
  four-way algorithm-selection mux tree with wrapped two-bit arithmetic also
  shortens the UI path that dominated the failed route. Seed 2 passes every
  clock with 541 cells free and supplies the flashed archive.
