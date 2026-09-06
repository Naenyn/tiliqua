use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};
use tiliqua_hal::dma_framebuffer::Rotate;
use tiliqua_lib::palette::ColorPalette;

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Waterfall,
    View,
    Display,
    Menu,
    Misc,
    Help,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum Quality3d {
    // Retain the old serialized discriminant so saved values migrate cleanly.
    #[strum(disabled)]
    Low,
    #[default]
    #[strum(serialize = "lower")]
    Medium,
    #[strum(serialize = "higher")]
    High,
}

impl Quality3d {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Low | Self::Medium => 1,
            Self::High => 2,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SurfaceStyle {
    Wire,
    #[default]
    Terrain,
}

impl SurfaceStyle {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Wire => 0,
            Self::Terrain => 1,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum FrequencyScale {
    #[default]
    Log,
    Linear,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum ColorBy {
    #[default]
    Level,
    Frequency,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum InputChannel {
    #[default]
    #[strum(serialize = "IN1")]
    In1,
    #[strum(serialize = "IN2")]
    In2,
    #[strum(serialize = "IN3")]
    In3,
    #[strum(serialize = "IN4")]
    In4,
}

impl InputChannel {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::In1 => 0,
            Self::In2 => 1,
            Self::In3 => 2,
            Self::In4 => 3,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum FrequencyRange {
    #[strum(serialize = "3kHz")]
    Range3k,
    #[strum(serialize = "6kHz")]
    Range6k,
    #[strum(serialize = "12kHz")]
    Range12k,
    #[default]
    #[strum(serialize = "24kHz")]
    Range24k,
}

impl FrequencyRange {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Range24k => 0,
            Self::Range12k => 1,
            Self::Range6k => 2,
            Self::Range3k => 3,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum ScrollRate {
    #[strum(serialize = "fast")]
    Fast,
    #[strum(serialize = "medium")]
    Medium,
    #[default]
    #[strum(serialize = "slow")]
    Slow,
    #[strum(serialize = "very-slow")]
    VerySlow,
}

impl ScrollRate {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Fast => 0,
            Self::Medium => 1,
            Self::Slow => 2,
            Self::VerySlow => 3,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum OnOff {
    Off,
    #[default]
    On,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum DisplayNoiseFloor {
    #[default]
    #[strum(serialize = "off")]
    Off,
    #[strum(serialize = "-72dB")]
    Db72,
    #[strum(serialize = "-66dB")]
    Db66,
    #[strum(serialize = "-60dB")]
    Db60,
}

impl DisplayNoiseFloor {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Off => 0,
            Self::Db72 => 1,
            Self::Db66 => 2,
            Self::Db60 => 3,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum EditHide {
    Off,
    #[default]
    On,
}

int_params!(GainParams<u8>   { step: 1, min: 0, max: 12 });
int_params!(HueParams<u8>    { step: 1, min: 0, max: 15 });
int_params!(AngleParams<i8>  { step: 15, min: -90, max: 90 });
int_params!(ScrollParams<u8> { step: 1, min: 0, max: 125 });
int_params!(HideParams<u8>   { step: 1, min: 2, max: 16, format: IntFormat::Scaled { divisor: 2, precision: 1, suffix: "s" } });
button_params!(OneShotButtonParams {
    mode: ButtonMode::OneShot
});

#[derive(OptionPage, Clone)]
pub struct WaterfallOpts {
    #[option]
    pub input: EnumOption<InputChannel>,
    #[option(0)]
    pub gain: IntOption<GainParams>,
    #[option]
    pub range: EnumOption<FrequencyRange>,
    #[option]
    pub rate: EnumOption<ScrollRate>,
}

#[derive(OptionPage, Clone)]
pub struct ViewOpts {
    #[option]
    pub style: EnumOption<SurfaceStyle>,
    #[option]
    pub scale: EnumOption<FrequencyScale>,
    #[option]
    pub quality: EnumOption<Quality3d>,
    #[option]
    #[option_name("color by")]
    pub color_by: EnumOption<ColorBy>,
    #[option]
    #[option_name("age fade")]
    pub age_fade: EnumOption<OnOff>,
    #[option]
    pub contours: EnumOption<OnOff>,
    #[option(-15)]
    pub rot_x: IntOption<AngleParams>,
    #[option(15)]
    pub rot_y: IntOption<AngleParams>,
    #[option(0)]
    pub rot_z: IntOption<AngleParams>,
}

#[derive(OptionPage, Clone)]
pub struct DisplayOpts {
    #[option]
    pub axes: EnumOption<OnOff>,
    #[option(0)]
    pub hue: IntOption<HueParams>,
    #[option(ColorPalette::Inferno)]
    pub palette: EnumOption<ColorPalette>,
    #[option]
    #[option_name("noise floor")]
    pub noise_floor: EnumOption<DisplayNoiseFloor>,
}

#[derive(OptionPage, Clone)]
pub struct MenuOpts {
    #[option(10)]
    pub ui_hue: IntOption<HueParams>,
    #[option(5)]
    #[option_name("hide UI")]
    pub hide: IntOption<HideParams>,
    #[option]
    #[option_name("edit hide")]
    pub edit_hide: EnumOption<EditHide>,
}

#[derive(OptionPage, Clone)]
pub struct MiscOpts {
    #[option]
    pub rotation: EnumOption<Rotate>,
    #[option(false)]
    pub save_opts: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub wipe_opts: ButtonOption<OneShotButtonParams>,
}

#[derive(OptionPage, Clone)]
pub struct HelpOpts {
    #[option(0)]
    pub scroll: IntOption<ScrollParams>,
}

#[derive(Options, Clone)]
pub struct Opts {
    pub tracker: ScreenTracker<Page>,
    #[page(Page::Waterfall)]
    pub waterfall: WaterfallOpts,
    #[page(Page::View)]
    pub view: ViewOpts,
    #[page(Page::Display)]
    pub display: DisplayOpts,
    #[page(Page::Menu)]
    pub menu: MenuOpts,
    #[page(Page::Misc)]
    pub misc: MiscOpts,
    #[page(Page::Help)]
    pub help: HelpOpts,
}

/// Convert the Hide UI value (0.5-second steps) to milliseconds.
pub fn menu_hide_ms(hide: u8) -> u32 {
    hide as u32 * 500
}
