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
    #[strum(serialize = "2D")]
    TwoD,
    #[default]
    #[strum(serialize = "3D")]
    ThreeD,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum Source3d {
    #[default]
    Live,
    Static,
}

impl Source3d {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Live => 0,
            Self::Static => 1,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum Quality3d {
    // Retain the old serialized discriminant so saved High values remain
    // compatible, but omit Low from the encoder's EnumIter choices.
    #[strum(disabled)]
    Low,
    #[default]
    Medium,
    High,
}

impl Quality3d {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Low => 1,
            Self::Medium => 1,
            Self::High => 2,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum DisplayMode {
    Spectrum,
    #[default]
    Spectrograph,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumStyle {
    Bars,
    #[default]
    Curve,
}

impl SpectrumStyle {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Bars => 0,
            Self::Curve => 1,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumScale {
    Linear,
    #[default]
    Log,
}

impl SpectrumScale {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Linear => 0,
            Self::Log => 1,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumTilt {
    #[default]
    Flat,
    #[strum(serialize = "+3db/oct")]
    Gentle,
    #[strum(serialize = "+6db/oct")]
    Strong,
}

impl SpectrumTilt {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Flat => 0,
            Self::Gentle => 1,
            Self::Strong => 2,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumHighlight {
    #[default]
    Off,
    Peaks,
}

impl SpectrumHighlight {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Off => 0,
            Self::Peaks => 1,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumSmoothing {
    #[default]
    Off,
    Light,
    Strong,
}

impl SpectrumSmoothing {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Off => 0,
            Self::Light => 1,
            Self::Strong => 2,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum SpectrumBands {
    #[strum(serialize = "32")]
    Bands32,
    #[default]
    #[strum(serialize = "64")]
    Bands64,
    #[strum(serialize = "128")]
    Bands128,
    #[strum(serialize = "256")]
    Bands256,
}

impl SpectrumBands {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Bands32 => 0,
            Self::Bands64 => 1,
            Self::Bands128 => 2,
            Self::Bands256 => 3,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumFill {
    Off,
    Solid,
    Gradient,
    #[default]
    Amplitude,
}

impl SpectrumFill {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Off => 0,
            Self::Solid => 1,
            Self::Gradient => 2,
            Self::Amplitude => 3,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumPeaks {
    Off,
    Fast,
    Medium,
    Slow,
    #[strum(serialize = "very-slow")]
    VerySlow,
    #[default]
    Sustain,
}

impl SpectrumPeaks {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Off => 0,
            Self::Fast => 1,
            Self::Medium => 2,
            Self::Slow => 3,
            Self::VerySlow => 4,
            Self::Sustain => 5,
        }
    }
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
    #[option_name("style")]
    #[option_if(self.mode.value == DisplayMode::Spectrum)]
    pub spectrum_style: EnumOption<SpectrumStyle>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrum && self.spectrum_style.value == SpectrumStyle::Curve)]
    pub scale: EnumOption<SpectrumScale>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrum)]
    pub tilt: EnumOption<SpectrumTilt>,
    #[option]
    #[option_name("hi-lite")]
    #[option_if(self.mode.value == DisplayMode::Spectrum)]
    pub highlight: EnumOption<SpectrumHighlight>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrum && self.spectrum_style.value == SpectrumStyle::Curve)]
    pub smoothing: EnumOption<SpectrumSmoothing>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrum && self.spectrum_style.value == SpectrumStyle::Bars)]
    pub bands: EnumOption<SpectrumBands>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrum)]
    pub fill: EnumOption<SpectrumFill>,
    #[option]
    #[option_if(self.mode.value == DisplayMode::Spectrum)]
    pub peaks: EnumOption<SpectrumPeaks>,
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
    pub rate: EnumOption<ScrollRate>,
}

#[derive(OptionPage, Clone)]
pub struct View3dOpts {
    #[option]
    pub source: EnumOption<Source3d>,
    #[option]
    pub quality: EnumOption<Quality3d>,
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
