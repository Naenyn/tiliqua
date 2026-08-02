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
| DRIVE-SHARED | DRIVE shading/marker; shared BANK DRIVE/RES/FB renderer | 8 | 18,288 | 21,648 | 2,640 | 5,921 | 10 | 400.00 | 58.53 | 62.01 | 82.39 | PASS; current candidate |

## Notes

- The optimization traded four additional block RAMs for 2,560 fewer packed
  logic cells, increasing free packed cells from 60 to 2,620.
- DVI5X timing is dominated by the existing TMDS serializer and is highly
  placement-sensitive. A feature can leave REZO logic timing healthy while a
  particular seed fails the independent serializer path.
- Sharing the BANK DRIVE/RES/FB row renderer more than offset the added DRIVE
  animation geometry: DRIVE-SHARED uses 20 fewer packed cells than OPT-BASE.
- Timing comparisons are only meaningful after routing. Pre-route estimates
  are not recorded in the table.
- UI/DSP functional regressions are checked separately by
  `tests/test_rezo_compare_path.py`, `tests/test_rezo_display.py`, and
  `tests/test_rezo_ui.py`.
