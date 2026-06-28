pub const UI_NAME: &str = "SCOPE";
pub const UI_TAG: &str = "eef6d9a-";
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
Four-channel digital oscilloscope with crisp vector traces.

All four analog inputs are plotted simultaneously with adjustable timebase,
trigger, and per-channel vertical position.  Audio is passed straight through
to the outputs (no USB or delay lines).

The following options are tweakable in the menu.  TRS MIDI CCs mirror the
scope and display pages:

    .. code-block:: text

        Page    Parameter     CC  Description
        ────    ─────────     ──  ───────────
        HELP    scroll         -  scroll help text up/down

        DISPLAY ui-hue        42  menu and grid overlay hue
        DISPLAY palette       43  color palette
        DISPLAY grid          44  grid overlay style
        DISPLAY grid-i        45  grid overlay intensity

        MISC    rotation      52  screen rotation
        MISC    help           -  show/hide help page
        MISC    save-opts      -  save all options to flash
        MISC    wipe-opts      -  reset all options to defaults

        SCOPE1  ypos0         60  channel 0 vertical position
        SCOPE1  ypos1         61  channel 1 vertical position
        SCOPE1  ypos2         62  channel 2 vertical position
        SCOPE1  ypos3         63  channel 3 vertical position
        SCOPE1  yscale0       70  channel 0 volts/div (CC mirror)
        SCOPE1  vis0-3         -  per-channel visibility

        SCOPE2  timebase      71  horizontal time/div
        SCOPE2  trig-mode     73  trigger mode
        SCOPE2  trig-lvl      74  trigger level
        SCOPE2  intensity     75  trace intensity
        SCOPE2  hue           76  trace color
"###;
pub const OVERLAY_UI_SCRATCH_BASE: usize = 0x20f00000;
pub const OVERLAY_UI_MEM_BASE: usize = 0xc1000000;
pub const OVERLAY_UI_MENU_W: usize = 250;
pub const OVERLAY_UI_MENU_H: usize = 160;
pub const OVERLAY_UI_MENU_WORDS: usize = 1250;
