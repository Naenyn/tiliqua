pub const UI_NAME: &str = "OSCIO";
pub const UI_TAG: &str = "959cd08-";
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

All four analog inputs are displayed together. Each input is also passed
straight through to the matching output with no USB or delay-line processing.

    .. code-block:: text

        in1 ───────────────────────► out1
        in2 ───────────────────────► out2
        in3 ───────────────────────► out3
        in4 ───────────────────────► out4

        trigger source: selectable from in1, in2, in3, or in4

Turn the encoder to move through the menu. Press it to select a page or
parameter, then turn to edit. The menu hides automatically; turning resumes
the current edit, while pressing reopens it in navigation mode.

CHANNEL 1-2 and CHANNEL 3-4 set each trace's vertical offset, volts per
division, and visibility.

OSCIO sets time per division, trigger mode, trigger source, trigger level,
grid style, trace intensity, and trace hue. Rising and falling modes lock the
sweep to the selected trigger channel. Free mode continuously retriggers.

MENU changes the overlay hue, palette, and automatic hide delay. MISC contains
screen rotation, this help page, MIDI highlighting, diagnostics, and settings
save/reset actions.

On this page, turn the encoder to scroll. Press once to leave scroll editing,
select Back, and press again to return to the oscilloscope.
"###;
pub const OVERLAY_UI_SCRATCH_BASE: usize = 0x20f00000;
pub const OVERLAY_UI_MEM_BASE: usize = 0xc1000000;
pub const OVERLAY_UI_MENU_W: usize = 250;
pub const OVERLAY_UI_MENU_H: usize = 160;
pub const OVERLAY_UI_MENU_WORDS: usize = 1250;
