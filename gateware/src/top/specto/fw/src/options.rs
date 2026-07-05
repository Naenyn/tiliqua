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
    #[strum(serialize = "3D")]
    View3d,
    Display,
    Misc,
    Help,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum ViewMode {
    #[default]
    #[strum(serialize = "2D")]
    TwoD,
    #[strum(serialize = "3D")]
    ThreeD,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum DisplayMode {
    Spectrum,
    #[default]
    Spectrograph,
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

    pub fn framebuffer_value(self) -> u8 {
        match self {
            Self::Short => 20,
            Self::Medium => 28,
            Self::Long => 36,
            Self::VeryLong => 48,
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
int_params!(AngleParams<i8>  { step: 15, min: -90, max: 90 });
int_params!(ScrollParams<u8> { step: 1, min: 0, max: 125 });
button_params!(OneShotButtonParams {
    mode: ButtonMode::OneShot
});

#[derive(OptionPage, Clone)]
pub struct SpectroOpts {
    #[option]
    pub input: EnumOption<InputChannel>,
    #[option]
    pub mode: EnumOption<DisplayMode>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrograph)]
    pub view: EnumOption<ViewMode>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrograph && self.view.value == ViewMode::TwoD)]
    pub style: EnumOption<RenderStyle>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrograph && self.view.value == ViewMode::TwoD && self.style.value == RenderStyle::Phosphor)]
    pub persist: EnumOption<Persistence>,
    #[option(0)]
    pub gain: IntOption<GainParams>,
    #[option]
    pub range: EnumOption<FrequencyRange>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrograph)]
    pub rate: EnumOption<ScrollRate>,
}

#[derive(OptionPage, Clone)]
pub struct View3dOpts {
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
    #[page(Page::View3d)]
    pub view_3d: View3dOpts,
    #[page(Page::Display)]
    pub display: DisplayOpts,
    #[page(Page::Misc)]
    pub misc: MiscOpts,
    #[page(Page::Help)]
    pub help: HelpOpts,
}
