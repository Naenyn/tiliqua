use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};
use tiliqua_hal::dma_framebuffer::Rotate;
use tiliqua_lib::palette::ColorPalette;

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Sonoro,
    Spectrum,
    Histo,
    Display,
    Menu,
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
pub enum Quality3d {
    // Retain the old serialized discriminant so saved High values remain
    // compatible, but omit Low from the encoder's EnumIter choices.
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
            Self::Low => 1,
            Self::Medium => 1,
            Self::High => 2,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum DisplayMode {
    #[default]
    Spectrum,
    Spectrograph,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum SpectrumStyle {
    #[default]
    Bars,
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
pub enum SpectrumHighlight {
    #[default]
    Off,
    #[strum(serialize = "on")]
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
    #[strum(serialize = "grad-rev")]
    GradientReverse,
    Freq,
    #[strum(serialize = "freq-rev")]
    FreqReverse,
}

impl SpectrumFill {
    pub fn hw_index(self) -> u8 {
        match self {
            Self::Off => 0,
            Self::Solid => 1,
            Self::Gradient => 2,
            Self::Amplitude => 3,
            Self::GradientReverse => 4,
            Self::Freq => 5,
            Self::FreqReverse => 6,
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
    #[strum(serialize = "longer")]
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

int_params!(GainParams<u8>   { step: 1, min: 0, max: 12 });
int_params!(HueParams<u8>    { step: 1, min: 0, max: 15 });
int_params!(AngleParams<i8>  { step: 15, min: -90, max: 90 });
int_params!(ScrollParams<u8> { step: 1, min: 0, max: 125 });
int_params!(HideParams<u8>   { step: 1, min: 2, max: 16, format: IntFormat::Scaled { divisor: 2, precision: 1, suffix: "s" } });
button_params!(OneShotButtonParams {
    mode: ButtonMode::OneShot
});

#[derive(OptionPage, Clone)]
pub struct SonoroOpts {
    #[option]
    pub input: EnumOption<InputChannel>,
    #[option]
    pub mode: EnumOption<DisplayMode>,
    #[option(0)]
    pub gain: IntOption<GainParams>,
    #[option]
    pub range: EnumOption<FrequencyRange>,
    #[option]
    pub rate: EnumOption<ScrollRate>,
}

#[derive(OptionPage, Clone)]
pub struct SpectrumOpts {
    #[option]
    #[option_name("style")]
    pub spectrum_style: EnumOption<SpectrumStyle>,
    #[option]
    pub scale: EnumOption<SpectrumScale>,
    #[option]
    #[option_name("harmonics")]
    pub highlight: EnumOption<SpectrumHighlight>,
    #[option]
    pub bands: EnumOption<SpectrumBands>,
    #[option]
    pub fill: EnumOption<SpectrumFill>,
    #[option]
    pub peaks: EnumOption<SpectrumPeaks>,
}

#[derive(OptionPage, Clone)]
pub struct HistoOpts {
    #[option]
    pub view: EnumOption<ViewMode>,
    #[option]
    #[option_if(self.view.value == ViewMode::TwoD)]
    pub style: EnumOption<RenderStyle>,
    #[option]
    #[option_if(self.view.value == ViewMode::TwoD && self.style.value == RenderStyle::Phosphor)]
    pub persist: EnumOption<Persistence>,
    #[option]
    #[option_if(self.view.value == ViewMode::ThreeD)]
    pub quality: EnumOption<Quality3d>,
    #[option(-15)]
    #[option_if(self.view.value == ViewMode::ThreeD)]
    pub rot_x: IntOption<AngleParams>,
    #[option(15)]
    #[option_if(self.view.value == ViewMode::ThreeD)]
    pub rot_y: IntOption<AngleParams>,
    #[option(0)]
    #[option_if(self.view.value == ViewMode::ThreeD)]
    pub rot_z: IntOption<AngleParams>,
}

#[derive(OptionPage, Clone)]
pub struct DisplayOpts {
    #[option]
    pub axes: EnumOption<OnOff>,
    // The options framework evaluates conditional visibility within a page.
    // Keep a hidden mirror of the top-level mode so the spectrum-only grid
    // control can live immediately below axes on the DISPLAY page.
    #[option]
    #[option_if(false)]
    pub spectrum_mode: EnumOption<DisplayMode>,
    #[option]
    #[option_if(self.spectrum_mode.value == DisplayMode::Spectrum)]
    pub grid: EnumOption<OnOff>,
    #[option(0)]
    pub hue: IntOption<HueParams>,
    #[option(ColorPalette::Inferno)]
    pub palette: EnumOption<ColorPalette>,
    #[option]
    #[option_name("noise floor")]
    pub noise_floor: EnumOption<DisplayNoiseFloor>,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum EditHide {
    Off,
    #[default]
    On,
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
    #[page(Page::Sonoro)]
    pub sonoro: SonoroOpts,
    #[page(Page::Spectrum)]
    pub spectrum: SpectrumOpts,
    #[page(Page::Histo)]
    pub histo: HistoOpts,
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
