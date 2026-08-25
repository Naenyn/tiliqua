use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default,
         Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Tuner,
    Settings,
    Help,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default,
         Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum DisplayMode {
    #[default]
    Arc,
    Visualizer,
}

int_params!(InputParams<u8> { step: 1, min: 0, max: 3 });
int_params!(ReferenceParams<u16> {
    step: 1, min: 400, max: 480,
    format: IntFormat::Scaled { divisor: 1, precision: 0, suffix: "Hz" }
});
int_params!(ScrollParams<u8> { step: 1, min: 0, max: 60 });

button_params!(OneShotButtonParams { mode: ButtonMode::OneShot });

#[derive(OptionPage, Clone)]
pub struct TunerOpts {
    #[option(0)]
    pub input: IntOption<InputParams>,
    #[option]
    pub display: EnumOption<DisplayMode>,
}

#[derive(OptionPage, Clone)]
pub struct SettingsOpts {
    #[option(440)]
    pub reference: IntOption<ReferenceParams>,
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
    #[page(Page::Tuner)]
    pub tuner: TunerOpts,
    #[page(Page::Settings)]
    pub settings: SettingsOpts,
    #[page(Page::Help)]
    pub help: HelpOpts,
}
