use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default,
         Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Tuner,
    Calibrate,
    Verify,
    Profiles,
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
    Linear,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default,
         Serialize, Deserialize)]
pub enum VerifyMode {
    #[default]
    #[strum(serialize="MANUAL")]
    Manual,
    #[strum(serialize="SCAN")]
    Scan,
    #[strum(serialize="POINTS")]
    Points,
}

int_params!(InputParams<u8> { step: 1, min: 0, max: 3 });
int_params!(NoteParams<u8> { step: 1, min: 12, max: 108 });
int_params!(CentsParams<i16> { step: 1, min: -50, max: 50 });
int_params!(ReferenceParams<u16> {
    step: 1, min: 400, max: 480,
    format: IntFormat::Scaled { divisor: 1, precision: 0, suffix: "Hz" }
});
int_params!(ScrollParams<u8> { step: 1, min: 0, max: 60 });
int_params!(ProfileSlotParams<u8> { step: 1, min: 1, max: 4 });
int_params!(NamePositionParams<u8> { step: 1, min: 1, max: 24 });
int_params!(NameCharacterParams<u8> { step: 1, min: 32, max: 126 });

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
pub struct CalibrateOpts {
    #[option(0)]
    pub input: IntOption<InputParams>,
    #[option(1)]
    pub output: IntOption<InputParams>,
    #[option(60)]
    pub zero_note: IntOption<NoteParams>,
    #[option(false)]
    pub run: ButtonOption<OneShotButtonParams>,
}

#[derive(OptionPage, Clone)]
pub struct HelpOpts {
    #[option(0)]
    pub scroll: IntOption<ScrollParams>,
}

#[derive(OptionPage, Clone)]
pub struct VerifyOpts {
    #[option(60)]
    pub note: IntOption<NoteParams>,
    #[option(0)]
    pub cents: IntOption<CentsParams>,
    #[option]
    pub mode: EnumOption<VerifyMode>,
    #[option(false)]
    pub run: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub refine: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub accept: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub discard: ButtonOption<OneShotButtonParams>,
}

#[derive(OptionPage, Clone)]
pub struct ProfileOpts {
    #[option(1)]
    pub slot: IntOption<ProfileSlotParams>,
    #[option(1)]
    pub position: IntOption<NamePositionParams>,
    #[option(79)]
    pub character: IntOption<NameCharacterParams>,
    #[option(false)]
    pub save: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub load: ButtonOption<OneShotButtonParams>,
}

#[derive(Options, Clone)]
pub struct Opts {
    pub tracker: ScreenTracker<Page>,
    #[page(Page::Tuner)]
    pub tuner: TunerOpts,
    #[page(Page::Calibrate)]
    pub calibrate: CalibrateOpts,
    #[page(Page::Verify)]
    pub verify: VerifyOpts,
    #[page(Page::Profiles)]
    pub profiles: ProfileOpts,
    #[page(Page::Settings)]
    pub settings: SettingsOpts,
    #[page(Page::Help)]
    pub help: HelpOpts,
}
