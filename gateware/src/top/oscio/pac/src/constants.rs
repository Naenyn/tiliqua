pub const UI_NAME: &str = "OSCIO";
pub const UI_TAG: &str = "1043a93e";
pub const HW_REV_MAJOR: u32 = 5;
pub const USE_EXTERNAL_PLL: bool = true;
pub const CLOCK_SYNC_HZ: u32 = 60000000;
pub const CLOCK_AUDIO_HZ: u32 = 49152000;
pub const CLOCK_DVI_HZ: u32 = 74250000;
pub const FIXED_MODELINE: Option<(u16, u16)> = None;
pub const PSRAM_BASE: usize = 0x20000000;
pub const PSRAM_SZ_BYTES: usize = 0x1000000;
pub const PSRAM_SZ_WORDS: usize = PSRAM_SZ_BYTES / 4;
pub const SPIFLASH_BASE: usize = 0x10000000;
pub const SPIFLASH_SZ_BYTES: usize = 0x1000000;
pub const PSRAM_FB_BASE: usize = 0x20000000;
pub const N_BITSTREAMS: usize = 8;
pub const BOOTINFO_BASE: usize = 0x20fff000;
pub const TOUCH_SENSOR_ORDER: [u8; 8] = [5, 7, 8, 9, 10, 11, 12, 13];
pub const PMOD_DEFAULT_CAL: [f32; 4] = [-1.248, -0.03, 0.9, 0.0];
pub const BLIT_MEM_BASE: usize = 0xc0000000;
pub const AUDIO_FS: u32 = 192000;
// Extra constants specified by an SoC subclass:
pub const MODULE_DOCSTRING: &str = r###"
OSCIO is a four-channel digital oscilloscope for Eurorack signals.

All four analog inputs are displayed together. A voltage-monitor view presents
each input in its own history lane with level, low/high, peak-to-peak, period,
and frequency measurements. Each input is also passed straight through to the
matching output with no USB or delay-line processing.

    .. code-block:: text

        in1 ───────────────────────► out1
        in2 ───────────────────────► out2
        in3 ───────────────────────► out3
        in4 ───────────────────────► out4

        trigger source: selectable from in1, in2, in3, or in4

Turn the encoder to move through the menu. Press it to select a page or
parameter, then turn to edit. The menu hides automatically; turning resumes
the current edit, while pressing reopens it in navigation mode.

On the HELP page, turn the encoder to scroll. Select the HELP page title to
return to the preceding menu pages.

OSCIO is the first menu page, with mode as its first option. In scope mode it
also provides time/div and acquire. CHANNEL 1-2 and CHANNEL 3-4 then set each
trace's vertical offset, volts per division, and visibility. The SCOPE page's
Trigger section contains trigger type, source, level, and filter. These channel
and trigger pages are omitted from menu navigation in monitor mode.

In monitor mode the OSCIO page provides time/div and max freq. On a 720x720
display it also provides channels, which switches between CH 1-2 and CH 3-4;
rectangular displays show all four and omit that option. The MONITOR page's
Ranges section gives every channel an independent full-window voltage range:
-5..+5 V, -10..+10 V, 0..+10 V, or 0..+5 V.

Monitor is intended for CV, gates, envelopes, and LFOs. Its max freq defaults
to 20 Hz and may be set from 0.25 Hz through 20 Hz. Monitor runs continuously
without waiting for a trigger, clips each trace to its selected lane range, and
measures the calibrated input before display
interpolation or cleanup. Faster repeating signals are identified in the
statistics panel and replaced by an indicator in the history lanes, while
their voltage and frequency statistics remain visible. A trace must stay below
max freq for three seconds before it appears. Once visible, it tolerates brief
excursions above max freq, but is hidden after one second above the limit or
immediately at 1.5 times the limit (30 Hz when max freq is 20 Hz).
Frequency and period appear only after OSCIO observes a repeatable rising cycle;
static, very small, or irregular signals display -- instead of a false reading.

Rising and falling are strict trigger modes: each sweep waits for the selected
channel to cross trig lvl in the chosen direction. If no crossing arrives, the
completed display is held. Auto rise and auto fall prefer the same locked edge,
but start an untriggered refresh after 50 ms if the edge is lost. Free starts a
new sweep immediately and does not lock to the signal.

Trig filter low-passes trigger detection without filtering any displayed trace.
Start with off or 5kHz and use the highest cutoff that gives stable lock. Lower
cutoffs (1.2kHz, 300Hz, and 75Hz) reject progressively more harmonics, but may
attenuate the trigger waveform or make its crossing arrive later.

Use acquire clean for normal viewing. It is the recommended default and makes
square, saw, and other sharp-edged waves look more like their intended shape.
Use acquire raw when diagnosing the input itself and you want OSCIO to show the
calibrated samples without edge cleanup. Raw may make sharp transitions look
rougher or spikier, so it is usually less useful as the everyday display mode.

DISPLAY sets trace intensity, trace hue, and graph palette. Scope mode also
shows grid style and grid intensity; those unused controls are omitted in
monitor mode. SYSTEM contains overlay hue, automatic hide behavior, rotation,
and settings save/reset actions. HELP is the final menu page.
"###;
pub const OVERLAY_UI_SCRATCH_BASE: usize = 0x20f00000;
pub const OVERLAY_UI_MEM_BASE: usize = 0xc1000000;
pub const OVERLAY_UI_MENU_W: usize = 250;
pub const OVERLAY_UI_MENU_H: usize = 160;
pub const OVERLAY_UI_MENU_WORDS: usize = 1250;
pub const HELP_SCROLL_MAX: u8 = 42;
