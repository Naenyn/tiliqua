use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};
use tiliqua_hal::dma_framebuffer::Rotate;
use tiliqua_lib::palette::ColorPalette;

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Spectro,
    Display,
    Misc,
    Help,
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
#[strum(serialize_all = "kebab-case")]
pub enum RenderStyle {
    Analytical,
    #[default]
    Phosphor,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum FrequencyRange {
    #[strum(serialize = "3kHz")]
    Range3k,
    #[strum(serialize = "6kHz")]
    Range6k,
    #[default]
    #[strum(serialize = "12kHz")]
    Range12k,
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
    #[default]
    #[strum(serialize = "medium")]
    Medium,
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
pub enum Persistence {
    Short,
    Medium,
    #[default]
    Long,
    #[strum(serialize = "long+")]
    VeryLong,
}

impl Persistence {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Short => 0,
            Self::Medium => 1,
            Self::Long => 2,
            Self::VeryLong => 3,
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

int_params!(GainParams<u8>   { step: 1, min: 0, max: 12 });
int_params!(HueParams<u8>    { step: 1, min: 0, max: 15 });
int_params!(ScrollParams<u8> { step: 1, min: 0, max: 125 });
button_params!(OneShotButtonParams {
    mode: ButtonMode::OneShot
});

#[derive(OptionPage, Clone)]
pub struct SpectroOpts {
    #[option]
    pub input: EnumOption<InputChannel>,
    #[option]
    pub style: EnumOption<RenderStyle>,
    #[option]
    #[option_if(self.style.value == RenderStyle::Phosphor)]
    pub persist: EnumOption<Persistence>,
    #[option(0)]
    pub gain: IntOption<GainParams>,
    #[option]
    pub range: EnumOption<FrequencyRange>,
    #[option]
    pub rate: EnumOption<ScrollRate>,
}

#[derive(OptionPage, Clone)]
pub struct DisplayOpts {
    #[option]
    pub axes: EnumOption<OnOff>,
    #[option(0)]
    pub hue: IntOption<HueParams>,
    #[option(10)]
    pub ui_hue: IntOption<HueParams>,
    #[option(ColorPalette::Inferno)]
    pub palette: EnumOption<ColorPalette>,
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
    #[page(Page::Spectro)]
    pub spectro: SpectroOpts,
    #[page(Page::Display)]
    pub display: DisplayOpts,
    #[page(Page::Misc)]
    pub misc: MiscOpts,
    #[page(Page::Help)]
    pub help: HelpOpts,
}
