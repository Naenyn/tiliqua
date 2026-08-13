# REZO build performance log

This log tracks resource use and final post-route timing for significant REZO
builds. Keep failed experiments: placement seed sensitivity is material at
720p60, and a failed result can prevent repeating an unproductive build.

## Method

- Target: Tiliqua R5 / SoldierCrab R3 (`LFE5U-25F`)
- Audio rate: 192 kHz
- Video mode: 1280x720p60
- Build command: `pdm run rezo build --fs-192khz --modeline 1280x720p60`
- Seed override: `TILIQUA_REZO_SEED=<n>`
- Resource figures and frequencies come from the final `top.tim` report.
- Required clocks: DVI5X 371.33 MHz, AUDIO 49.15 MHz, SYNC 60.00 MHz,
  DVI 74.25 MHz.

The formal optimization baseline is **OPT-BASE** below. New feature builds
should be compared against its 21,668 packed cells and 2,620 free cells while
also passing every constrained clock.

### 2026-08-11 through 2026-08-12 compact-display target work

These rows use nextpnr's raw `TRELLIS_COMB` utilization rather than the packed
cell metric in the historical table. The standard preview renders the same
native-size 508x508 UI as the circular target, centered in 1280x720 with no
rotation and no enlargement. Only the 720x720 circular target applies the
90-degree panel-mount correction.

| ID | Target/change | Seed | TRELLIS_COMB | Raw free | FF | BRAM | DVI5X MHz | AUDIO MHz | SYNC MHz | DVI MHz | Result |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| COMPACT-STD-ACCUM-S9 | 1280x720; independent Bresenham coordinate accumulators | 9 | 24,630 | -342 | — | 22 | — | — | — | — | FAIL placement capacity |
| COMPACT-STD-ROM-S9 | 1280x720; shared block-RAM coordinate map, direct decode from RAM outputs | 9 | 24,135 | 153 | — | 23 | 396.98 | 67.47 | 59.83 | 57.12 | FAIL SYNC and DVI |
| **COMPACT-STD-ROM-PIPE-S4** | **1280x720; shared block-RAM map plus registered renderer boundary** | **4** | **24,149** | **139** | **6,913** | **23** | **385.65** | **70.77** | **61.15** | **80.87** | **PASS; flashed slot 4** |
| ROUND2-IRREG-W140-S4 | Photo-round-2 alignment; irregular FILTER fader geometry, ABC9 W=140 | 4 | 24,383 | -95 | 6,916 | 23 | — | — | — | — | FAIL placement capacity |
| ROUND2-TEXT-W140-S4 | Same UI with FILTER corrections folded into text ROM, ABC9 W=140 | 4 | 24,314 | -26 | 6,913 | 23 | — | — | — | — | FAIL placement capacity |
| ROUND2-TEXT-W130-S4 | Same UI, denser ABC9 W=130 mapping | 4 | 24,151 | 137 | 6,913 | 23 | 350.26 | 73.05 | 59.20 | 82.01 | FAIL DVI5X and SYNC |
| **ROUND2-TEXT-W130-S9** | **Exact W=130 JSON rerouted; second photo-alignment pass** | **9** | **24,151** | **137** | **6,913** | **23** | **401.45** | **71.91** | **63.25** | **77.01** | **PASS; flashed slot 4** |
| ROUND3-INPUT-W130-S9 | Third photo pass; conditional INPUT CV chips/AUD depth text; initial full build | 9 | 24,150 | 138 | 6,913 | 23 | 394.01 | 74.07 | 53.46 | 76.43 | FAIL SYNC |
| **ROUND3-INPUT-W130-S4** | **Exact synthesized JSON rerouted; third photo-alignment pass** | **4** | **24,150** | **138** | **6,913** | **23** | **407.17** | **73.08** | **63.30** | **76.91** | **PASS; flashed slot 4** |
| **ROUND4-MAIN-GRID-W130-S4** | **BANK/FILTER shared five-slot native-row grid; exact label/fader lower-edge alignment** | **4** | **24,017** | **271** | **6,920** | **23** | **392.77** | **75.88** | **62.08** | **78.86** | **PASS; flashed slot 4** |
| ROUND5-MAIN-SPACED-W130-S4 | Roomy alternate-row MAIN grid, shortened bands, wider faders; initial route | 4 | 24,050 | 238 | 6,921 | 23 | 341.18 | 73.23 | 54.30 | 73.90 | FAIL DVI5X, SYNC, and DVI |
| ROUND5-MAIN-SPACED-W130-S9 | Exact synthesized JSON rerouted | 9 | 24,050 | 238 | 6,921 | 23 | 364.56 | 70.24 | 53.47 | 73.97 | FAIL DVI5X, SYNC, and DVI |
| **ROUND5-MAIN-SPACED-W130-S6** | **Exact synthesized JSON rerouted; roomy shared BANK/FILTER grid** | **6** | **24,050** | **238** | **6,921** | **23** | **439.56** | **74.95** | **60.16** | **79.85** | **PASS; flashed slot 4** |
| **ROUND6-MAIN-COMPACT-W130-S6** | **Bottom-anchored 16-pixel control cadence; corrected BANK/FILTER band scaling and clipping** | **6** | **22,985** | **1,303** | **6,842** | **23** | **416.67** | **73.95** | **66.15** | **77.54** | **PASS; flashed slot 4** |
| ROUND7-MAIN-EXPANDED-BUNDLED-S6 | Alternate-row controls expanded upward; bundled Yosys 0.52 route | 6 | 23,138 | 1,150 | 6,845 | 23 | 443.85 | 71.01 | 58.68 | 72.07 | FAIL SYNC and DVI |
| **ROUND7-MAIN-EXPANDED-W130-S6** | **Same geometry; native W130 netlist, last row bottom-anchored** | **6** | **22,978** | **1,310** | **6,845** | **23** | **408.00** | **72.12** | **66.09** | **76.76** | **PASS; flashed slot 4** |
| ROUND8-INPUT-LANES-BUNDLED-S6 | INPUT groups moved upward; unified MODE/VALUE/DEPTH lanes; bundled Yosys 0.52 route | 6 | 23,010 | 1,278 | 6,845 | 23 | 396.51 | 72.17 | 58.70 | 81.14 | FAIL SYNC |
| ROUND8-INPUT-LANES-W130-S6 | Same INPUT geometry; native W130 netlist | 6 | 22,915 | 1,373 | 6,845 | 23 | 412.03 | 74.02 | 61.59 | 73.61 | FAIL DVI by 0.64 MHz |
| ROUND8-INPUT-LANES-W130-S7 | Exact native W130 JSON rerouted | 7 | 22,915 | 1,373 | 6,845 | 23 | 363.90 | 69.99 | 64.22 | 76.62 | FAIL DVI5X |
| **ROUND8-INPUT-LANES-W130-S4** | **Exact native W130 JSON rerouted; STREZO-style INPUT lane alignment** | **4** | **22,915** | **1,373** | **6,845** | **23** | **393.08** | **69.30** | **61.87** | **78.25** | **PASS; flashed slot 4** |
| ROUND9-INPUT-ALIGN-BUNDLED-S4 | Align VALUE/DEPTH backgrounds to native text; restore compact level monitor; bundled Yosys 0.52 | 4 | 23,044 | 1,244 | 6,845 | 23 | — | — | — | — | Routing aborted after pathological final congestion |
| **ROUND9-INPUT-ALIGN-W130-S4** | **Same geometry; native W130 mapping and exact VALUE-target spacing** | **4** | **22,960** | **1,328** | **6,845** | **23** | **399.20** | **74.46** | **62.38** | **76.61** | **PASS; flashed slot 4** |
| ROUND10-INPUT-LANES-BANK-SCALE-BUNDLED-S4 | Taller INPUT lanes and restored half-height BANK default; bundled Yosys 0.52 | 4 | 23,152 | 1,136 | 6,844 | 23 | — | — | — | — | Routing aborted after pathological final congestion |
| **ROUND10-INPUT-LANES-BANK-SCALE-W130-S4** | **Same geometry; native W130 mapping** | **4** | **23,046** | **1,242** | **6,844** | **23** | **422.12** | **70.34** | **66.12** | **74.79** | **PASS; flashed slot 4** |
| ROUND11-INPUT-VALUES-BUNDLED-S4 | INPUT value-only shading, 136px groups, and mode-dependent level-monitor placement; bundled Yosys 0.52 | 4 | 23,288 | 1,000 | 6,845 | 23 | — | — | — | — | Routing aborted after pathological final congestion |
| ROUND11-INPUT-VALUES-W130-S4 | Same geometry; native W130 mapping | 4 | 23,091 | 1,197 | 6,845 | 23 | 368.19 | 77.07 | 62.61 | 81.39 | FAIL DVI5X by 3.14 MHz |
| **ROUND11-INPUT-VALUES-W130-S6** | **Exact native W130 JSON rerouted** | **6** | **23,091** | **1,197** | **6,845** | **23** | **385.95** | **70.71** | **63.88** | **76.14** | **PASS; flashed slot 4** |
| ROUND12-INPUT-BOUNDS-BUNDLED-S4 | Compact VALUE/DEPTH gap, centered value chips, and INPUT content panel extended to y=700; bundled Yosys 0.52 | 4 | 23,352 | 936 | 6,845 | 23 | — | — | — | — | Routing aborted after pathological final congestion |
| ROUND12-INPUT-BOUNDS-W130-S4 | Same geometry; native W130 mapping | 4 | 23,373 | 915 | 6,845 | 23 | — | — | — | — | Routing aborted after pathological final congestion |
| ROUND12-INPUT-BOUNDS-W130-S6 | Exact native W130 JSON rerouted | 6 | 23,373 | 915 | 6,845 | 23 | 355.37 | 74.32 | 63.49 | 69.68 | FAIL DVI5X and DVI |
| ROUND12-INPUT-BOUNDS-W130-S9 | Exact native W130 JSON rerouted | 9 | 23,373 | 915 | 6,845 | 23 | 401.77 | 71.50 | 64.97 | 72.54 | FAIL DVI |
| ROUND12-INPUT-BOUNDS-W130-S8 | Exact native W130 JSON rerouted | 8 | 23,373 | 915 | 6,845 | 23 | 386.25 | 72.87 | 59.97 | 71.24 | FAIL SYNC by 0.03 MHz and DVI |
| **ROUND12-INPUT-BOUNDS-W130-S1** | **Exact native W130 JSON rerouted; compact INPUT bounds correction** | **1** | **23,373** | **915** | **6,845** | **23** | **391.24** | **73.00** | **62.32** | **77.32** | **PASS; flashed slot 4** |
| **ROUND13-INPUT-COLUMNS-BUNDLED-S1** | **INPUT panel begins above IN0; right-aligned labels and one left-aligned parameter/fader column** | **1** | **23,210** | **1,078** | **6,846** | **23** | **414.94** | **71.65** | **61.25** | **78.55** | **PASS; flashed slot 4** |
| ROUND14-INPUT-AUDIO-BUNDLED-S1 | Five-character INPUT MODE fields; bundled Yosys 0.52 route | 1 | 23,218 | 1,070 | 6,846 | 23 | — | — | — | — | Routing aborted after pathological final congestion |
| **ROUND14-INPUT-AUDIO-W130-S1** | **Five-character AUDIO/CV mode chips, centered vertically and horizontally** | **1** | **23,163** | **1,125** | **6,846** | **23** | **434.03** | **74.21** | **66.33** | **75.67** | **PASS; flashed slot 4** |
| ROUND15-INPUT-NATIVE-Y-BUNDLED-S1 | INPUT vertical geometry moved onto the native 16px text raster; bundled Yosys 0.52 route | 1 | 23,173 | 1,115 | 6,845 | 23 | 395.73 | 74.04 | 56.72 | 69.47 | FAIL SYNC and DVI |
| ROUND15-INPUT-NATIVE-Y-W130-S1 | Exact native W130 JSON rerouted | 1 | 23,092 | 1,196 | 6,845 | 23 | 360.36 | 73.94 | 65.68 | 75.34 | FAIL DVI5X by 10.97 MHz |
| **ROUND15-INPUT-NATIVE-Y-W130-S4** | **Native 96px INPUT cadence and mathematically centered MODE/VALUE/DEPTH lanes** | **4** | **23,092** | **1,196** | **6,845** | **23** | **406.17** | **75.53** | **60.45** | **75.48** | **PASS; flashed slot 4** |
| ROUND16-GROUPS-NATIVE-Y-BUNDLED-S1 | GROUPS labels, rails, and markers share four native row centers; bundled Yosys 0.52 route | 1 | 23,337 | 951 | 6,845 | 23 | 456.41 | 74.67 | 57.58 | 65.74 | FAIL SYNC and DVI |
| **ROUND16-GROUPS-NATIVE-Y-W130-S1** | **Exact native W130 route; four 48px GROUPS rows with coincident label/rail/marker centers** | **1** | **23,253** | **1,035** | **6,845** | **23** | **393.24** | **77.31** | **61.63** | **80.62** | **PASS; flashed slot 4** |
| ROUND17-OUTPUT-NATIVE-XY-BUNDLED-S1 | OUTPUT row/column labels and cells share native centers; bundled Yosys 0.52 route | 1 | 23,365 | 923 | 6,860 | 23 | — | — | — | — | Routing aborted after pathological final congestion |
| ROUND17-OUTPUT-NATIVE-XY-W130-S1 | Same OUTPUT geometry; native W130 mapping | 1 | 23,281 | 1,007 | 6,860 | 23 | 371.47 | 77.11 | 64.75 | 72.79 | FAIL DVI by 1.46 MHz |
| **ROUND17-OUTPUT-NATIVE-XY-W130-S2** | **Exact native W130 JSON rerouted; five centered columns and four centered rows** | **2** | **23,281** | **1,007** | **6,860** | **23** | **413.22** | **73.29** | **66.34** | **82.44** | **PASS; flashed slot 4** |
| ROUND18-OUTPUT-EVEN-ROWS-BUNDLED-S2 | OUTPUT centers corrected from 64/48/64px to a uniform 64px cadence; bundled Yosys 0.52 route | 2 | 23,423 | 865 | 6,861 | 23 | 406.17 | 74.11 | 62.94 | 73.57 | FAIL DVI by 0.68 MHz |
| ROUND18-OUTPUT-EVEN-ROWS-W130-S1 | Same geometry; native W130 mapping | 1 | 23,256 | 1,032 | 6,861 | 23 | 337.15 | 74.21 | 62.20 | 69.08 | FAIL DVI5X and DVI |
| ROUND18-OUTPUT-EVEN-ROWS-W130-S4 | Exact native W130 JSON rerouted | 4 | 23,256 | 1,032 | 6,861 | 23 | 364.03 | 72.69 | 64.41 | 79.20 | FAIL DVI5X by 7.30 MHz |
| ROUND18-OUTPUT-EVEN-ROWS-W130-S8 | Exact native W130 JSON rerouted | 8 | 23,256 | 1,032 | 6,861 | 23 | 331.90 | 76.24 | 62.20 | 78.33 | FAIL DVI5X |
| **ROUND18-OUTPUT-EVEN-ROWS-W130-S10** | **Exact native W130 JSON rerouted; four OUTPUT rows on one uniform 64px center cadence** | **10** | **23,256** | **1,032** | **6,861** | **23** | **390.93** | **72.76** | **65.61** | **79.50** | **PASS; flashed slot 4** |
| ROUND19-FEEDBACK-ALIGN-BUNDLED-S1 | FEEDBACK source row centered and safety controls moved onto one shared left edge; bundled Yosys 0.52 | 1 | — | — | 6,868 | 23 | — | — | — | — | Routing stopped after pathological congestion at 107k iterations |
| **ROUND19-FEEDBACK-ALIGN-W130-S1** | **Native W130 mapping; centered ten-source group and aligned KNEE/CEILING/DAMPING controls** | **1** | **23,361** | **927** | **6,868** | **23** | **395.88** | **70.70** | **62.08** | **75.00** | **PASS; flashed slot 4** |
| ROUND20-FEEDBACK-SOURCE-CENTER-BUNDLED-S1 | Correct FEEDBACK source decoder prefetch offset from six to five logical pixels; bundled Yosys 0.52 | 1 | — | — | 6,868 | 23 | — | — | — | — | Routing stopped after pathological congestion beyond 113k iterations |
| **ROUND20-FEEDBACK-SOURCE-CENTER-W130-S1** | **Native W130 mapping; ten-button rendered interval [42,678) centered exactly on x=360** | **1** | **23,443** | **845** | **6,861** | **23** | **390.32** | **71.64** | **64.83** | **79.56** | **PASS; flashed slot 4** |
| ROUND21-MATRIX-ROWS-BUNDLED-S1 | MATRIX labels moved to one exact 80px native cadence; bundled Yosys 0.52 | 1 | — | — | 6,868 | 23 | — | — | — | — | Route stopped after prolonged congestion; not retained |
| ROUND21-MATRIX-ROWS-W130-S1 | Native W130 mapping; exact MATRIX row centers | 1 | 23,374 | 914 | 6,861 | 23 | 389.11 | 68.84 | 61.23 | 70.56 | FAIL DVI |
| **ROUND21-MATRIX-ROWS-W130-S6** | **Exact native W130 JSON rerouted; MATRIX labels share the five fader-row centers** | **6** | **23,374** | **914** | **6,861** | **23** | **346.02** | **72.88** | **63.91** | **76.17** | **DVI5X timing miss; packaged for hardware UI validation** |

ROUND21 also explored native seeds 2, 3, 4, 5, 7, 8, 9, 10, and 11.
Seeds 2 and 3 entered prolonged final-router congestion; seeds 4, 5, 7, 8,
9, 10, and 11 had materially worse pre-route timing than seed 6 and their
detailed routes were stopped once that was clear. Seed 6 is the retained
artifact because its primary DVI, SYNC, and AUDIO clocks all pass and it has
the best aggregate timing of the completed candidates, though its DVI5X
serializer clock remains 25.31 MHz short. This is an explicit exception to
the normal all-clocks rule for the requested hardware UI validation; do not
use this row as a release-quality timing baseline.

The ROUND21 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`c4297940060f637ccd7683afe4c1ba0941b5666efbf3f1395a60f7d1f822c44a`.
Its embedded `top.bit` SHA-256 is
`dd62cf9bba095e858b1d6100b95ee9591f2e8528341b596bb14ef3d94a4b1664`.
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. It was flashed successfully to slot 4 on 2026-08-13; option storage
was preserved.

The ROUND20 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`863f4965e2e39c9e7481becb735b25ddd2eff84887eeca6fbc6d60c1689e4d28`.
Its embedded `top.bit` SHA-256 is
`ed8fff27b8b1ee33d4f40658669b94d67b467ed25ea122fc58bd85b35c6cbe50`.
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. It was flashed successfully to slot 4 on 2026-08-12; option storage
was preserved.

The ROUND19 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`f7d324bdd97ed5058ba839516cbb2de5708b0e7cbf67a8da0128f4240a2c2e98`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-1 route (SHA-256
`675040a62133562b0913e889ebf1994311786d746e207ae1c1bb63e29e71805b`).
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. It was flashed successfully to slot 4 on 2026-08-12; option storage
was preserved.

The ROUND18 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`30e6747434d65cd4c2328c5645247e1dde75ca10ae5450341a2f1f5caa10340c`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-10 route (SHA-256
`d0249cd27b41df2ee985e4c91dfeb6e02026fccb9965754de2627a12a4523293`).
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. It was flashed successfully to slot 4 on 2026-08-12; option storage
was preserved.

The ROUND17 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`7bafc4508a64b7fb35fa993a30cbd40c62f55a3aa5ed442387e85d76ff46e794`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-2 route (SHA-256
`f85f2714d35441db069a5a3ac015810118371d5fa2e52782972eeec0ddc8ccea`).
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. It was flashed successfully to slot 4 on 2026-08-12; option storage
was preserved.

The ROUND16 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`98087b13b23f541b50bf7835b151ab57bf06ba2d01e9580cf368bec1be9e1536`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-1 route (SHA-256
`db69e9ee34534655a32a98cae0ef3c4e0fd47f375f87ec6e88ac5ce2684ccb5e`).
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. It was flashed successfully to slot 4 on 2026-08-12; option storage
was preserved.

The ROUND15 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`11de9592f89c60c14b865e9a9ac2d1fe40f88c24590a563a36e36ddecf110dca`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-4 route (SHA-256
`3985bc741c953195627e10deda7b77aa1e702e4680140d4b74cae546350fd1d7`).
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. It was flashed successfully to slot 4 on 2026-08-12; option storage
was preserved.

The ROUND14 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`e3eb7c4abb4dfa5e0bda224094f0d4508ac5a50ef788563391e623ef8aa574ac`.
Its embedded `top.bit` is byte-identical to the separately generated passing
seed-1 route (SHA-256
`7210dbe78e24db4c628a71d6f087044612bd752b99a86001c1594ee3a72ea3c6`).
The manifest records the standard, unrotated `1280x720p60` target. It was
flashed successfully to slot 4 on 2026-08-12; option storage was preserved.

The ROUND13 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`2acab5802a39aa6759038636c5e5f09d958625500e4cb2ddfdcf2134aed2c1f6`.
Its embedded `top.bit` is byte-identical to the separately generated passing
seed-1 route (SHA-256
`8d66a88a842377ef816bf46b46d884cbdfb0989871e04826f8070889b9f4af1c`).
The manifest records the standard, unrotated `1280x720p60` target.
It was flashed successfully to slot 4 on 2026-08-12; option storage was
preserved.

The ROUND12 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`5af320b5e424854f5df38ce71ec09f0a563dbe2bb4e0f5b85cce0ad59f944b04`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-1 route (SHA-256
`c10f501e943ba357a1e05964d136b5e9ef754b63cca272e7ae22f07dff79e02e`).
The manifest records the standard, unrotated `1280x720p60` target. Seed 7 and
the native seed-4 route were stopped after prolonged final congestion; seed 2
was likewise stopped after its placement timing and final congestion were both
substantially worse. Seed 10 was stopped once seed 1 passed all clocks.
The archive was flashed successfully to slot 4 on 2026-08-12; option storage
was preserved.

The ROUND11 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`69459d31308aab0a2f2565183faaf252cd5ab4f76dda4eca11d739e62e3e21b9`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-6 route (SHA-256
`70706ef5729dab959cce0039a3f9393202b4acc1bf5947ab8dc4eadbdb7fcb05`).
The manifest records the standard, unrotated `1280x720p60` target. It was
flashed successfully to slot 4 on 2026-08-12; option storage was preserved.

The ROUND10 archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`26bf4237d916b5350e0a6a2885cc2b1798ed77138db9b8704a22a45ef1a93a70`.
Its embedded `top.bit` is byte-identical to the separately packed passing
seed-4 route (SHA-256
`819ad9f92ca82460c0b9f3cd0aa0830f77fbb64f78cf99a79865ec493ab075db`).
The manifest records the standard, unrotated `1280x720p60` target. It was
flashed successfully to slot 4 on 2026-08-12; option storage was preserved.

The final archive is `rezo-6f8596b7-r5.tar.gz` with SHA-256
`34067684bf421d8f7fd72e0f55227c154a079806e771863d633d00f4a71d41d0`.
Its manifest records `1280x720p60`; this distinguishes it from the earlier
720x720 circular-panel archive that used the same dirty source identifier.
The archive was flashed successfully to slot 4 on 2026-08-11.

The second photo-alignment archive is `rezo-6f8596b7-r5.tar.gz` with SHA-256
`cc46772587c3a24de3f474821f938ad2adaad248697ccbf3fbf53cc8449aeccd`.
It uses ABC9 wire weight 130 and the all-clock passing seed-9 reroute of the
exact synthesized JSON. Its manifest also records `1280x720p60`.
The archive was flashed successfully to slot 4 on 2026-08-11.

The third photo-alignment archive is `rezo-6f8596b7-r5.tar.gz` with SHA-256
`d1408d8cc4efa04953b4f89ccad8c18bd830a710108bdf3aa475be1b3301af5c`.
It contains the all-clock passing seed-4 reroute of the exact W=130 JSON; the
archive's `top.bit` is byte-identical to the separately packed passing route.
Its manifest records the standard, unrotated `1280x720p60` target. The archive
was flashed successfully to slot 4 on 2026-08-12.

The shared BANK/FILTER grid archive is `rezo-6f8596b7-r5.tar.gz` with SHA-256
`2f08dd1b6712d1a2c8a3e7dde00609144da070d0562522673530946a8c103da2`.
Both modes now derive their lower faders from five native text rows; BANK uses
the first three slots and FILTER uses all five. Its manifest records the
standard, unrotated `1280x720p60` target. The archive was flashed successfully
to slot 4 on 2026-08-12.

The roomy shared-grid archive is `rezo-6f8596b7-r5.tar.gz` with SHA-256
`61f84215fde31ed5aaab6048be6736c564c05f30a457f5a3d69315a76934165b`.
Its five control slots use alternate native rows, its faders extend farther
right, and the compact MAIN band field is shortened symmetrically to preserve
a clear gutter above the controls. BANK uses the first three slots and FILTER
uses all five. The retained seed-6 route passes every clock, and its manifest
records the standard, unrotated `1280x720p60` target. The archive was flashed
successfully to slot 4 on 2026-08-12.

The corrected compact-grid archive is `rezo-6f8596b7-r5.tar.gz` with SHA-256
`ac33e24e6aa5c8a9f2d0f4719a36cdf050fed4edc256b1d03720b09b1a90c9b3`.
Its embedded `top.bit` is byte-identical to the retained passing seed-6 route
at SHA-256
`73dfe3dafa46c7840d6de7e4efe00e2faa835d3f7115db78366713d8b36559d2`.
The horizontal controls retain their bottom anchor but use a 16-physical-pixel
cadence, exactly half the preceding roomy grid's spacing. The compact band
field spans logical y=218..474 around zero y=346: BANK maps its signed 0..128
magnitude one-for-one to each half, while FILTER maps its 0..32 magnitude over
the full 256-pixel height and clips fills to the field. The manifest records
the standard, unrotated `1280x720p60` target. Initial slot-4 attempts found no
debugger and wrote nothing. After reconnecting, the bitstream and manifest
programmed successfully and FPGA refresh completed on 2026-08-12; option
storage was preserved.

The expanded-row archive is `rezo-6f8596b7-r5.tar.gz` with SHA-256
`3b8f9a3556b25de01a1a8ddf37fad4fd196851535acf6fe34376b3baabd41205`.
Its embedded `top.bit` matches the retained native W130 seed-6 route at
SHA-256
`92edffb09a7bf7ae8e6843ec76b451fb8dc420dec180e0d3a77448c3af3e5dba`.
The five shared MAIN rows occupy alternate native text rows `(28, 30, 32, 34,
36)` and logical fader starts `(486, 532, 578, 623, 669)`. Thus the final row
retains the ROUND6 bottom anchor while the preceding rows expand upward into
the band/control gutter. The band field and its scaling are unchanged. The
manifest records the standard, unrotated `1280x720p60` target. The archive was
flashed successfully to slot 4 on 2026-08-12 with option storage preserved.

The compact INPUT-lane archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`ea00a34124f071f1fed3a43d1232399fa7741d01dffa4301d26a15293b905f2d`.
Its embedded `top.bit` is byte-identical to the retained native W130 seed-4
route at SHA-256
`bab77e70e57a058d54c9c8664e1f809facb2213646e86c8e645d2c985cb7a6b0`.
The four INPUT groups use complete shaded lanes that include their labels;
AUD VALUE remains a gain fader with its attached one-pixel level monitor,
while an AUD DEPTH lane is absent and skipped by navigation. The manifest
records the standard, unrotated and unscaled `1280x720p60` target. The archive
was flashed successfully to slot 4 on 2026-08-12 with option storage
preserved.

The aligned INPUT-lane archive is `rezo-4b874e18-r5.tar.gz` with SHA-256
`e8d4dd71f32923761fdc392313c05894eba0c785b4060a5a65a0b6f755ac6ec8`.
Its embedded `top.bit` is byte-identical to the retained native W130 seed-4
route at SHA-256
`0713947852f1194ca116624b201c18ef4dce6831676090d172aca983147d3672`.
VALUE and DEPTH backgrounds now begin on their native text rows, CV target
text has a full-cell gap after VALUE, and two logical monitor scanlines
downsample to a stable one-pixel physical level indicator attached to VALUE.
The manifest records the standard, unrotated and unscaled `1280x720p60`
target. The archive was flashed successfully to slot 4 on 2026-08-12 with
option storage preserved.

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
