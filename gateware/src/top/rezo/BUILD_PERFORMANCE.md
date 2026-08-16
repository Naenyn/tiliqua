# REZO / REZOMO build performance log

This log tracks resource use and final post-route timing for significant REZO
builds. Keep failed experiments: placement seed sensitivity is material at
720p60, and a failed result can prevent repeating an unproductive build.

## Method

- Target: Tiliqua R5 / SoldierCrab R3 (`LFE5U-25F`)
- Audio rate: 192 kHz
- Video mode: 1280x720p60
- Build command: `pdm run rezo build --fs-192khz` or, for the clocked variant,
  `pdm run rezomo build --fs-192khz`
- Seed override: `TILIQUA_REZO_SEED=<n>`
- Resource figures and frequencies come from the final `top.tim` report.
- Required clocks: DVI5X 371.33 MHz, AUDIO 49.15 MHz, SYNC 60.00 MHz,
  DVI 74.25 MHz.
- The official circular target uses `720x720p60r2`, requiring DVI5X 195.35
  MHz, AUDIO 49.15 MHz, SYNC 60.00 MHz, and DVI 39.07 MHz.

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
| CLOCK-HEAD-DUPLICATE-S2 | Dirty `c8706835`; HEAD style and DRUNK 1--4 with a second dynamic modulation write path | 2 | 21,093 | 24,429 | -141 | 6,463 | 16 | — | — | — | — | FAIL capacity |
| CLOCK-HEAD-SHARED-S2 | Dirty `c8706835`; ALL/HEAD share one dynamic modulation read/write/reflect path | 2 | 20,572 | 23,896 | 392 | 6,463 | 16 | 423.19 | 74.79 | 60.27 | 73.98 | FAIL DVI by 0.27 MHz |
| **CLOCK-HEAD-SHARED-S8** | **Exact CLOCK-HEAD-SHARED JSON; reflected wandering head, disabled-band skip, random 1--DRUNK stride** | **8** | **20,572** | **23,896** | **392** | **6,463** | **16** | **406.17** | **73.65** | **60.44** | **74.37** | **PASS; flashed slot 4** |
| CLOCK-HEAD-BURST-WIDE | Dirty `c8706835`; measured external interval plus separate period/countdown counters | 8 | 20,777 | 24,129 | 159 | 6,530 | 16 | — | — | — | — | Routing aborted; excessive congestion |
| CLOCK-HEAD-BURST-S8 | Dirty `c8706835`; shared upward clock/interval counter, 16-sample burst timing, CHANCE control | 8 | 20,724 | 24,068 | 220 | 6,485 | 16 | 422.12 | 74.42 | 59.18 | 76.78 | FAIL SYNC by 0.82 MHz |
| **CLOCK-HEAD-BURST-S6** | **Exact optimized burst JSON; DRUNK 1--4 temporal landings and 0--100% CHANCE** | **6** | **20,724** | **24,068** | **220** | **6,485** | **16** | **400.64** | **75.68** | **61.50** | **75.00** | **PASS; hardware candidate** |
| **CLOCK-UI-BPM-S5** | **Two-column CLOCK editor, readable labels, WALK BAND name, ordered TURING controls, exact 15--300 BPM with accelerated editing** | **5** | **20,783** | **24,103** | **185** | **6,541** | **18** | **449.03** | **73.96** | **60.19** | **75.50** | **PASS; flashed slot 4** |
| **CLOCK-FIXED-DIRECTION-S8** | **Fixed shared rows; DIRECTION remains visible while WALK reports read-only RANDOM; mode-dependent direction sets retained** | **8** | **20,874** | **24,206** | **82** | **6,529** | **18** | **381.53** | **78.21** | **60.15** | **74.68** | **PASS; flashed slot 4** |
| **CLOCK-DEPTH-SLIDER-S8** | **Full-width 17-step DEPTH slider; numeric depth text table and three writer slots removed** | **8** | **20,845** | **24,201** | **87** | **6,519** | **18** | **382.70** | **74.10** | **60.37** | **77.86** | **PASS; later flashed slot 4** |
| **CLOCK-UI-ALIGN-S9** | **One shared MODE box, narrower two-column controls, left labels inset one cell; optimized DEPTH slider retained** | **9** | **20,737** | **24,081** | **207** | **6,519** | **18** | **389.11** | **76.61** | **61.24** | **79.29** | **PASS; flashed slot 4** |
| **REZOMO-RENAME-S9** | **Clocked variant renamed in both renderers and manifest; `rezomo` build alias; no DSP or layout change** | **9** | **20,737** | **24,081** | **207** | **6,519** | **18** | **418.24** | **77.02** | **60.10** | **76.07** | **PASS; pre-commit release candidate, not flashed** |
| **REZOMO-BACKPORT-S8** | **STREZO input meters, eight-bit display telemetry, 1/8 continuous-control acceleration, and serialized OUTPUT row/column edits** | **8** | **20,851** | **24,113** | **175** | **6,931** | **19** | **384.91** | **74.34** | **61.78** | **78.03** | **PASS; flashed slot 4 for validation** |
| REZOMO-NATIVE-STANDARD-S8 | Native 720 coordinate renderer; centered, unscaled 1280x720 preview | 8 | 20,784 | 24,076 | 212 | 6,983 | 20 | 331.46 | 75.25 | 58.22 | 69.53 | FAIL DVI5X, SYNC, and DVI |
| **REZOMO-NATIVE-STANDARD-S9** | **Same native renderer; centered, unscaled 1280x720 preview** | **9** | **20,784** | **24,076** | **212** | **6,983** | **20** | **437.25** | **71.66** | **63.76** | **74.65** | **PASS; retained standard route** |
| REZOMO-NATIVE-ROUND-S9 | Native renderer; 720x720p60r2 with panel-mount rotation | 9 | 20,784 | 24,076 | 212 | 6,983 | 20 | 432.71 | 70.99 | 59.72 | 77.39 | FAIL SYNC by 0.28 MHz |
| REZOMO-NATIVE-ROUND-S5 | Same official-screen target | 5 | 20,784 | 24,076 | 212 | 6,983 | 20 | — | — | 59.98 | — | FAIL SYNC by 0.02 MHz |
| **REZOMO-NATIVE-ROUND-S6** | **Same official-screen target** | **6** | **20,784** | **24,076** | **212** | **6,983** | **20** | **335.23** | **72.78** | **61.41** | **80.85** | **PASS; retained official-screen route** |
| REZOMO-UI-POLISH-S9 | `1fe69409`; centered value chips, shared enable-button geometry, bounded INPUT gain fader | 9 | 20,699 | 23,971 | 317 | 6,983 | 20 | — | — | — | 69.50 | FAIL DVI |
| REZOMO-UI-POLISH-S6 | Exact committed UI-polish RTL | 6 | 20,699 | 23,971 | 317 | 6,983 | 20 | 337.27 | — | — | — | FAIL DVI5X |
| REZOMO-UI-POLISH-S8 | Exact committed UI-polish RTL | 8 | 20,699 | 23,971 | 317 | 6,983 | 20 | — | — | 54.53 | — | FAIL SYNC |
| **REZOMO-UI-POLISH-S4** | **`1fe69409`; exact committed UI-polish RTL** | **4** | **20,699** | **23,971** | **317** | **6,983** | **20** | **391.08** | **72.01** | **60.98** | **77.83** | **PASS; standard archive flashed slot 4** |
| **REZOMO-CLOCK-LAYOUT-S4** | **`edbc20d9`; one-column CLOCK layout, heading, and uniform row geometry** | **4** | **20,753** | **24,041** | **247** | **6,983** | **20** | **397.14** | **70.67** | **63.77** | **76.45** | **PASS; standard archive flashed slot 4** |
| **REZOMO-CLOCK-FIELDS-S4** | **Dirty `e6e5d25b`; bounded BANK mode chip, content-width CLOCK value chips, and corrected DEPTH geometry** | **4** | **20,837** | **24,113** | **175** | **6,983** | **20** | **400.32** | **73.27** | **62.25** | **78.99** | **PASS; standard archive flashed slot 4** |
| **REZOMO-CHIP-ALIGN-S4** | **Dirty `e6e5d25b`; centered BANK/INPUT chips, row-derived INPUT label alignment, per-field CLOCK widths, and full-width DEPTH** | **4** | **20,675** | **23,983** | **305** | **6,983** | **20** | **391.85** | **70.92** | **61.01** | **79.82** | **PASS; standard archive flashed to slot 4** |
| REZOMO-GLYPH-NUDGE-S4 | Dirty `e6e5d25b`; exact per-value pixel-coordinate centering | 4 | 21,126 | 24,486 | -198 | 6,979 | 20 | — | — | — | — | FAIL capacity before placement |
| REZOMO-HALF-CELL-S4 | Dirty `e6e5d25b`; replace pixel subtractor with dynamic half-cell phase | 4 | — | 24,387 | -99 | 6,977 | 20 | — | — | — | — | FAIL capacity before placement |
| REZOMO-HALF-CELL-NARROW-S4 | Dirty `e6e5d25b`; restrict half-cell phase to photographed fields | 4 | — | 24,452 | -164 | 6,977 | 20 | — | — | — | — | FAIL capacity before placement |
| **REZOMO-OPTICAL-GEOMETRY-S4** | **Dirty `e6e5d25b`; parity-balanced fixed chips, exact vertical centers, and mode-specific CLOCK widths** | **4** | **20,902** | **24,252** | **36** | **6,976** | **20** | **439.37** | **74.60** | **61.46** | **79.57** | **PASS; standard archive flashed to slot 4** |
| REZOMO-MODE-DYNAMIC-S9 | Dirty `e6e5d25b`; BANK/CLOCK mode-dependent chip endpoint | 9 | — | — | — | 6,983 | 20 | — | — | — | — | FAIL placement at utilisation limit |
| REZOMO-BANK-NAV-S9 | Dirty `e6e5d25b`; fixed mode-chip bias and PRESET-before-MODE navigation, pre-simplification | 9 | — | — | — | 6,983 | 20 | 352.49 | 76.79 | 56.20 | 71.02 | FAIL DVI5X, SYNC, and DVI |
| REZOMO-BANK-NAV-S4-A | Same pre-simplification netlist | 4 | — | — | — | 6,983 | 20 | — | — | — | 72.88 | FAIL DVI by 1.37 MHz |
| **REZOMO-BANK-NAV-S4** | **Dirty `e6e5d25b`; PAGE/PRESET/MODE order, simplified reverse path, and CLOCK-biased fixed mode chip** | **4** | **20,817** | **24,169** | **119** | **6,976** | **20** | **424.27** | **72.49** | **60.42** | **75.02** | **PASS; standard archive flashed to slot 4** |
| REZOMO-EVEN-S1 | Dirty `e6e5d25b`; EVN renamed EVEN in both renderers and guides | 1 | 20,835 | 24,193 | 95 | 6,976 | 20 | 349.28 | 76.09 | 59.40 | 79.60 | FAIL DVI5X and SYNC |
| REZOMO-EVEN-S2 | Exact REZOMO-EVEN JSON | 2 | 20,835 | 24,193 | 95 | 6,976 | 20 | 427.17 | 72.91 | 60.93 | 72.40 | FAIL DVI |
| **REZOMO-EVEN-S3** | **Exact REZOMO-EVEN JSON** | **3** | **20,835** | **24,193** | **95** | **6,976** | **20** | **426.44** | **74.16** | **62.42** | **78.85** | **PASS; standard archive flashed to slot 4** |
| REZOMO-EVEN-S4 | Exact REZOMO-EVEN JSON | 4 | 20,835 | 24,193 | 95 | 6,976 | 20 | 368.46 | 73.54 | 59.53 | 73.30 | FAIL DVI5X, SYNC, and DVI |
| REZOMO-EVEN-S5 | Exact REZOMO-EVEN JSON | 5 | 20,835 | 24,193 | 95 | 6,976 | 20 | 397.14 | 71.47 | 58.28 | 75.32 | FAIL SYNC |
| REZOMO-EVEN-S7 | Exact REZOMO-EVEN JSON | 7 | 20,835 | 24,193 | 95 | 6,976 | 20 | 373.97 | 75.59 | 59.85 | 70.90 | FAIL SYNC and DVI |
| REZOMO-EVEN-S8 | Exact REZOMO-EVEN JSON | 8 | 20,835 | 24,193 | 95 | 6,976 | 20 | 339.21 | 74.18 | 60.98 | 75.11 | FAIL DVI5X |
| REZOMO-FINAL-ROUND-S6 | `483f5680`; accepted UI on official 720x720p60r2 target | 6 | 20,835 | 24,261 | 27 | 6,976 | 20 | 396.98 | 77.08 | 57.19 | 79.89 | FAIL SYNC |
| REZOMO-FINAL-ROUND-S1 | Exact circular JSON reroute | 1 | 20,835 | 24,261 | 27 | 6,976 | 20 | 361.93 | 74.24 | 53.02 | 72.48 | FAIL SYNC |
| **REZOMO-FINAL-ROUND-S3** | **Exact committed circular JSON; accepted shared UI and CLOCK alignment** | **3** | **20,835** | **24,261** | **27** | **6,976** | **20** | **378.36** | **78.65** | **61.65** | **72.40** | **PASS; tester archive, not flashed** |
| REZOMO-EVENT-ALL-S3 | Dirty `41008f9c`; raw-send local-coordinate renderer and all-algorithm event stage | 3 | — | 23,881 | 407 | — | 21 | 363.64 | 71.80 | 61.77 | 75.94 | FAIL DVI5X; all-algorithm retiming rejected |
| REZOMO-EVENT-ALL-S1 | Same all-algorithm event netlist | 1 | — | 23,881 | 407 | — | 21 | 346.38 | 73.88 | 62.89 | 74.71 | FAIL DVI5X; final seed trial |
| REZOMO-DVI-RESET-LOCAL-S3 | Dirty `41008f9c`; separate local DVI5X reset deassertion pipeline | 3 | — | 24,239 | 49 | — | 21 | 247.34 | 76.44 | 56.58 | 69.40 | FAIL DVI5X, SYNC, and DVI; rejected packing regression |
| REZOMO-SHIFT-WALK-S3 | Dirty `41008f9c`; retime only SHIFT/WALK with local-coordinate OUTPUT fill | 3 | — | 23,995 | 293 | — | 21 | 382.12 | 73.65 | 62.71 | 68.43 | FAIL DVI; INPUT row selector still follows BRAM directly |
| REZOMO-INPUT-INDEX-S3 | Dirty `41008f9c`; add two-bit INPUT row-index pipeline | 3 | 20,717 | 23,993 | 295 | 7,005 | 21 | 384.47 | 73.36 | 63.22 | 75.51 | PASS 1.25% gate; superseded by exact commit build |
| **REZOMO-CAPACITY-COMMIT-S3** | **`cbd49d7c`; narrow SHIFT/WALK, INPUT-index, and local OUTPUT-coordinate pipelines** | **3** | **20,698** | **23,978** | **310** | **7,005** | **21** | **377.36** | **72.50** | **60.89** | **77.29** | **PASS 1.25% gate; flashed slot 4** |
| **STREZO-NATIVE-STANDARD-S9** | **`6348b81`; native 508x508 safe square, centered family UI, pipelined GROUPS/OUTPUT lookups** | **9** | **20,515** | **23,975** | **313** | **6,893** | **19** | **384.17** | **70.01** | **63.85** | **84.18** | **PASS 1.25% gate; flashed slot 4** |
| **STREZO-NATIVE-ROUND-S1** | **`6348b81`; same upright UI with final panel-mount rotation at 720x720p60r2** | **1** | **20,551** | **24,015** | **273** | **6,893** | **19** | **328.95** | **76.06** | **72.25** | **81.23** | **PASS 1.25% gate; circular archive not flashed** |
| STREZO-CURVE-SCAN-S4 | Dirty `06608b0d`; configurable linear/logarithmic CROSS plus shared ten-band display scaler | 4 | 19,661 | 22,857 | 1,431 | 6,875 | 21 | 347.46 | 72.00 | 54.19 | 81.52 | FAIL DVI5X and SYNC; no flash |
| **STREZO-CURVE-SCAN-S16** | **`2ec93a17`; one BRAM replaces ten parallel display scalers** | **16** | **19,661** | **22,857** | **1,431** | **6,875** | **21** | **387.00** | **73.36** | **67.81** | **77.64** | **PASS 1.25% gate; standard archive flashed slot 4** |
| STREZO-CURVE-UI-S16 | `04c6e663`; corrected dynamic curve value and split OPTIONS panels | 16 | — | 22,937 | 1,351 | 6,875 | 21 | 373.13 | 75.74 | 66.13 | 71.96 | FAIL DVI and DVI5X margin; no flash |
| **STREZO-CURVE-UI-S9** | **`04c6e663`; centered CROSS layout and dynamic LINEAR/LOG ADVANCED control** | **9** | **—** | **22,937** | **1,351** | **6,875** | **21** | **422.30** | **73.58** | **63.20** | **81.59** | **PASS 1.25% gate; standard archive flashed slot 4** |
| **STREZO-UI-POLISH-S9** | **`72445513`; padded LAYOUT chip and top-to-bottom OPTIONS navigation** | **9** | **—** | **22,952** | **1,336** | **6,875** | **21** | **437.45** | **73.23** | **63.25** | **82.12** | **PASS 1.25% gate; standard archive flashed slot 4** |

## Notes

- The optimization traded four additional block RAMs for 2,560 fewer packed
  logic cells, increasing free packed cells from 60 to 2,620.
- DVI5X timing is dominated by the existing TMDS serializer and is highly
  placement-sensitive. A feature can leave REZO logic timing healthy while a
  particular seed fails the independent serializer path.
- STREZO-CURVE-SCAN trades one additional block RAM for 1,393 packed cells.
  The display scans the ten bands in ten DVI clocks and looks up the exact
  former height/sign mapping; DSP, modulation, and audio coefficients are
  unchanged. An earlier experiment that selected one INPUT row before endpoint
  scaling packed 15 cells worse and was reverted.
- For low-cost capacity work, first run focused tests, then use `--skip-build`
  to extract a fresh build plan without routing or archiving. Run `yosys` on
  the emitted `top.ys`, followed by `nextpnr-ecp5 --pack-only` on `top.json`.
  Only start a full route after pack-only reports the desired free-cell target.
  As of the STREZO-CURVE-SCAN work, `--skip-build` explicitly extracts the
  plan and cannot silently archive a stale `top.bit`. After a separately
  qualified route is packed to `top.bit`, use the explicit `--package-only`
  option to create its commit-stamped archive without rebuilding.
- The native renderer adds two display lookup memories over the backport
  baseline: one maps shared horizontal-fader pixels to parameter values and
  one holds INPUT row geometry. Standard and official-screen builds require
  different measured seeds because their video clocks and rotation paths
  produce different placement solutions. The normal commands now default to
  seed 9 and seed 6 respectively.
- REZOMO-UI-POLISH-S4 keeps the native coordinate renderer unchanged while
  centering the BANK, FEEDBACK, and OPTIONS value chips, making BANDS use the
  FEEDBACK enable-button geometry, and constraining the INPUT audio-gain fill
  to its native bounding box. Seeds 9, 6, and 8 each missed a different video
  domain; seed 4 passes all four constrained clocks and is the retained
  1280x720 route.
- REZOMO-CLOCK-LAYOUT-S4 replaces CLOCK's mixed row pitches with one 32-pixel
  single-column grid. The new CLOCKED SETTINGS heading remains outside the
  panel, while all common and mode-dependent key/value rows remain inside it.
  A native-geometry regression test samples every row, including the fourth
  mode-dependent control. Seed 4 passes every clock and supplies the standard
  1280x720 archive.
- REZOMO-CLOCK-FIELDS-S4 restores the BANK mode chip to the final panel-color
  composition, sizes each CLOCK text chip from that field's longest value,
  and maps DEPTH against its own 160-pixel value column instead of the shared
  300-pixel fader lookup. Two-pixel gaps between CLOCK rows use the existing
  panel height without changing the fixed text grid. Seed 4 passes every
  constrained clock for the standard 1280x720 target.
- REZOMO-CHIP-ALIGN-S4 derives BANK and INPUT text placement from each chip's
  fixed native-coordinate bounds, so labels and values share the same row
  centers. CLOCK keeps independent maximum-content widths for each textual
  field while DEPTH alone consumes the remaining panel width. The standard
  1280x720 seed-4 route passes all four constrained clocks with 305 packed
  cells free.
- REZOMO-GLYPH-NUDGE-S4 centered every glyph bound exactly with a live pixel
  coordinate offset, but exceeded the device by 198 packed cells. Replacing
  the subtractor with a one-bit half-cell tile phase still exceeded capacity;
  narrowing that phase to only the photographed fields also mapped worse due
  to the design's packing sensitivity. The retained
  REZOMO-OPTICAL-GEOMETRY-S4 candidate leaves the tile-reader path unchanged.
  Fixed chip bounds split the two possible character-parity centers, keeping
  requested values within five native pixels horizontally and exact
  vertically. TURING, WALK, and SHIFT use independent mode-specific chip
  widths. The standard seed-4 route passes all clocks with 36 packed cells
  free; the archive completed at 2026-08-13 19:29:26 EDT after roughly 383 s
  and was flashed successfully to slot 4.
- REZOMO-MODE-DYNAMIC-S9 gave BANK and CLOCK independent exact-content chip
  endpoints, but the live endpoint comparator prevented legal placement.
  REZOMO-BANK-NAV retains a fixed 100-pixel chip instead: measured visible
  glyph bounds place BANK within five native pixels of center and CLOCK within
  three. BANK navigation now advances PAGE, PRESET, MODE, then the first band;
  reverse navigation follows the exact inverse order. Seed 9 misses DVI5X,
  SYNC, and DVI, while the first seed-4 form misses only DVI. Letting PRESET's
  numeric predecessor provide the reverse PAGE transition removes a redundant
  comparison. The resulting seed-4 route has 119 packed cells free and passes
  every clock. Its standard archive completed at 2026-08-13 22:07:32 EDT and
  was flashed successfully to slot 4.
- REZOMO-EVEN replaces the abbreviated EVN preset label with the full four-
  character EVEN spelling in both REZO-family renderers and user guides. A
  native-display regression verifies that all four glyphs remain inside the
  existing preset chip. The additional dynamic glyph changes packing by 24
  cells and makes the route seed-sensitive again: seeds 1, 2, 4, 5, 7, and 8
  each miss at least one clock. Seed 3 passes all four clocks with 95 packed
  cells free. Its standard archive completed at 2026-08-13 22:50:56 EDT and
  was flashed successfully to slot 4.
- REZOMO-FINAL-ROUND builds the hardware-accepted shared-page and CLOCK UI from
  exact source commit `483f5680` for the official rotated `720x720p60r2`
  display. Seeds 6 and 1 fail only the 60 MHz SYNC domain. Seed 3 passes every
  constrained clock with 27 packed cells free and supplies the tester archive;
  seed 4 was stopped after seed 3 passed. The retained archive is
  `rezomo-483f5680-720x720p60r2-r5.tar.gz` with SHA-256
  `91e82b59edca3fd42cc83024f0a66aa437a50fd19ffb7d1112fcb5591b77b274`.
  Its embedded `top.bit` SHA-256 is
  `f520de6e866e353d04c18148bd12a8808abcb56a984af3ee8766db7f01111456`.
  The archive was verified but not flashed.
- REZOMO-CAPACITY-COMMIT-S3 is the exact standard-target build from commit
  `cbd49d7c`. OUTPUT sends remain raw in block memory; registering local pixel
  coordinates removes the post-RAM offset chain. SHIFT and WALK alone capture
  accepted events before their wide updates, while a two-bit INPUT row-index
  stage removes the DVI BRAM-to-endpoint-mux path. The exact route recovers 215
  packed cells over REZOMO-EVEN-S3 and passes the 1.25% margin gate on every
  clock. The 39-test focused family suite passes. Archive SHA-256 is
  `ee8eaa227c35ebe8c7af307af756f984b9df217d8ff05e2be98fdf1aa93cb90e`;
  `top.bit` SHA-256 is
  `e67ea8eb4a95ace972fe7e9ed4776964006f01508da6fc9ddbfa84839ed28295`.
  Flashing to slot 4 completed successfully on 2026-08-14; hardware validation
  is pending.
- CLOCK-DEPTH-SLIDER-S8 removes the dynamic three-character numeric DEPTH
  label and its text-writer scan slots. The replacement geometry uses the
  existing 0--16 value as a five-bit left shift, yielding a 512-pixel interior
  with exactly 32 pixels per step. Relative to CLOCK-FIXED-DIRECTION-S8 this
  saves 29 LUT4, 5 packed cells, and 10 FF. Two broader experiments were
  rejected: sharing CLOCK selector names through a wide ROM made routing
  impractically slow, while fixing WALK's hidden legacy step increased packing
  to 24,289 cells and failed capacity. Removing the now-unread WALK display
  crossing also changed ECP5 packing unfavorably (24,342 cells), so the benign
  crossing remains to preserve the measured timing-clean result.
- CLOCK-UI-ALIGN-S9 uses one 136-pixel MODE rectangle spanning the two former
  parity-specific positions. Odd- and even-length names sit at most four
  pixels from its center without a DVI pixel shifter. Parameter boxes shrink
  from 176 to 160 pixels around their existing centers, allowing DIRECTION,
  SOURCE, and BPM to move one character cell inside the panel without moving
  value text. Reusing comparator-friendly rectangle boundaries removes the
  previous mode-dependent geometry and saves another 108 LUT4 and 120 packed
  cells over CLOCK-DEPTH-SLIDER-S8. Seeds 1--8 were rejected for timing (seed
  7 was an aborted congestion outlier); seed 9 passes every domain.
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
- HEAD is implemented as a second WALK style rather than a fifth global
  algorithm, preserving the compact two-bit algorithm selector. One cursor
  randomly travels up or down through enabled bands, reflects at the physical
  ends, and modifies only its landing. DRUNK 1--4 chooses the maximum stride;
  each pulse draws an actual distance from one through that ceiling. The first
  RTL version expressed separate dynamic writes for ALL and HEAD and mapped
  141 cells over capacity. Folding both through the existing indexed
  read/write/reflect path recovers 533 packed cells and makes the entire
  feature cost 149 cells over CLOCK-WALK-COMPACT. Seed 2 misses only DVI;
  seed 1 misses only DVI5X; seed 7 misses DVI5X and SYNC; and seed 8 passes all
  clocks with 392 cells free and supplies the flashed archive.

## 2026-08-14 consolidated REZO-family target qualification

The new `codex/rezo-family` target matrix keeps product logic elaborated
independently while selecting standard/circular modelines, isolated artifact
names, qualified seeds, and REZO circular's native mapper explicitly. The
combined regression suite passes 107 tests. Final packed-cell and clock results
are recorded in `REZO_FAMILY.md`; every retained archive passed all four clocks,
its archived bitstream matched the routed `top.bit`, and none was flashed.

## 2026-08-16 unified six-target release

All six release archives below were synthesized from exact source commit
`0defa7645717307599d1d671c9cc60b9c1910bb3` after registering the REZO
FILTER-CV edit request and REZOMO shared level target. Every route passes the
project's 1.25% timing-margin gate. The manifests were checked for source tag,
product name, and modeline. Nothing in this set was flashed.

| Target | Seed | DVI5X / AUDIO / SYNC / DVI MHz | Archive | Archive SHA-256 |
|---|---:|---|---|---|
| REZO standard | 9 | 405.68 / 70.27 / 61.88 / 77.97 | `rezo-0defa764-r5.tar.gz` | `42cc02a15b7ba7e6b73680d88cf33853491dadbdc5bd8f6886382bd29b67c550` |
| REZOMO standard | 4 | 395.26 / 72.16 / 63.64 / 77.99 | `rezomo-0defa764-r5.tar.gz` | `989d2d7cd3281443174366759c7d64e2fec66e287ec2a02d4e87b9b57f1c9592` |
| STREZO standard | 1 | 382.26 / 71.56 / 62.47 / 82.22 | `strezo-0defa764-r5.tar.gz` | `03859d2f8fa0770ef468682962f6d8e09583441dc3290d30b37367b890f54a01` |
| REZO circular | 9 | 352.36 / 74.04 / 63.49 / 74.04 | `rezo-round-0defa764-r5.tar.gz` | `452c5ceac8899e07d0fa52f430f3cb34dd563b727340ea4aa54347fa096a387d` |
| REZOMO circular | 4 | 320.20 / 74.72 / 66.07 / 78.64 | `rezomo-round-0defa764-r5.tar.gz` | `9e0e85d1244cbe1fb562fe1ef851b170fdac1cccb12733e6327e8c6ac1160129` |
| STREZO circular | 1 | 327.55 / 74.39 / 63.28 / 75.94 | `strezo-round-0defa764-r5.tar.gz` | `32ac2a7dbbcd7d195ced8147290c0afb9565ce73b9a8a20d4c74eeccd63c9d86` |

Collected copies live in `build/rezo-family-release-0defa764/`. Retain each
seed with its corresponding synthesized netlist: a seed is reproducible for
the same netlist, toolchain, constraints, and router options, but is not a
portable timing guarantee after RTL or toolchain changes.
