use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};
use tiliqua_lib::palette::ColorPalette;
pub use tiliqua_lib::scope::{Timebase, VScale};

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Help,
    Bands1,
    Bands2,
    Shape,
    Scope,
    Beam,
    Misc,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum TriggerMode {
    #[default]
    Always,
    Rising,
}

int_params!(BandGainParams<i16>   { step: 512, min: -16384, max: 16384, format: IntFormat::Scaled { divisor: 8192, precision: 2, suffix: "x" } });
int_params!(GainParams<u16>       { step: 512, min: 0,      max: 32768, format: IntFormat::Scaled { divisor: 8192, precision: 2, suffix: "x" } });
int_params!(FeedbackParams<i16>   { step: 256, min: -8192,  max: 8192,  format: IntFormat::Scaled { divisor: 8192, precision: 2, suffix: "" } });
int_params!(ResonanceParams<u16>  { step: 512, min: 0,      max: 32768, format: IntFormat::Scaled { divisor: 8192, precision: 2, suffix: "" } });
int_params!(IntensityParams<u8>   { step: 1,   min: 0,      max: 15 });
int_params!(HueParams<u8>         { step: 1,   min: 0,      max: 15 });
int_params!(PersistParams<u8>     { step: 1,   min: 1,      max: 80 });
int_params!(TriggerLvlParams<i16> { step: 500, min: -16000, max: 16000, format: IntFormat::Scaled { divisor: 4000, precision: 2, suffix: "V" } });
int_params!(PosParams<i16>        { step: 1,   min: -40,    max: 40, format: IntFormat::Scaled { divisor: 4, precision: 2, suffix: "d" } });
int_params!(ScrollParams<u8>      { step: 1,   min: 0,      max: 125 });

button_params!(OneShotButtonParams { mode: ButtonMode::OneShot });

#[derive(OptionPage, Clone)]
pub struct HelpOpts {
    #[option(0)]
    pub scroll: IntOption<ScrollParams>,
}

#[derive(OptionPage, Clone)]
pub struct BandOpts1 {
    #[option(8192)]
    pub hz29: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz61: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz115: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz218: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz411: IntOption<BandGainParams>,
}

#[derive(OptionPage, Clone)]
pub struct BandOpts2 {
    #[option(8192)]
    pub hz777: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz1k5: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz2k8: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz5k2: IntOption<BandGainParams>,
    #[option(8192)]
    pub hz11k: IntOption<BandGainParams>,
}

#[derive(OptionPage, Clone)]
pub struct ShapeOpts {
    #[option(4096)]
    pub dry: IntOption<GainParams>,
    #[option(8192)]
    pub resonance: IntOption<ResonanceParams>,
    #[option(0)]
    pub feedback: IntOption<FeedbackParams>,
}

#[derive(OptionPage, Clone)]
pub struct ScopeOpts {
    #[option(VScale::Scale4V)]
    pub yscale: EnumOption<VScale>,
    #[option]
    pub timebase: EnumOption<Timebase>,
    #[option]
    pub trig_mode: EnumOption<TriggerMode>,
    #[option(0)]
    pub trig_lvl: IntOption<TriggerLvlParams>,
    #[option(-15)]
    pub ypos0: IntOption<PosParams>,
    #[option(-5)]
    pub ypos1: IntOption<PosParams>,
    #[option(5)]
    pub ypos2: IntOption<PosParams>,
    #[option(15)]
    pub ypos3: IntOption<PosParams>,
}

#[derive(OptionPage, Clone)]
pub struct BeamOpts {
    #[option(15)]
    pub persist: IntOption<PersistParams>,
    #[option(10)]
    pub hue: IntOption<HueParams>,
    #[option(8)]
    pub intensity: IntOption<IntensityParams>,
    #[option]
    pub palette: EnumOption<ColorPalette>,
}

#[derive(OptionPage, Clone)]
pub struct MiscOpts {
    #[option(false)]
    pub save_opts: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub wipe_opts: ButtonOption<OneShotButtonParams>,
}

#[derive(Options, Clone)]
pub struct Opts {
    pub tracker: ScreenTracker<Page>,
    #[page(Page::Help)]
    pub help: HelpOpts,
    #[page(Page::Bands1)]
    pub bands1: BandOpts1,
    #[page(Page::Bands2)]
    pub bands2: BandOpts2,
    #[page(Page::Shape)]
    pub shape: ShapeOpts,
    #[page(Page::Scope)]
    pub scope: ScopeOpts,
    #[page(Page::Beam)]
    pub beam: BeamOpts,
    #[page(Page::Misc)]
    pub misc: MiscOpts,
}
