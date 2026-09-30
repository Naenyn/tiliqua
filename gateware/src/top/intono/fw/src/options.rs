use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};

#[derive(Clone, Copy, PartialEq, EnumIter, Default, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Tuner,
    Calibrate,
    #[strum(disabled)]
    Verify,
    #[strum(disabled)]
    Profiles,
    Settings,
    Help,
    Play,
    Quantizer,
    #[strum(disabled)]
    QuantNotes,
    #[strum(disabled)]
    QuantSetups,
}
// EnumIter excludes child screens, but labels must remain valid for every
// screen. Deriving IntoStaticStr with `disabled` would panic for a child.
impl From<Page> for &'static str {
    fn from(page: Page) -> Self {
        match page {
            Page::Tuner => "INTONO",
            Page::Calibrate => "CAL",
            Page::Verify => "CHECK",
            Page::Profiles => "PROFILES",
            Page::Settings => "SETTINGS",
            Page::Help => "HELP",
            Page::Play => "ROUTES",
            Page::Quantizer => "SCALES",
            Page::QuantNotes => "NOTES",
            Page::QuantSetups => "SETUPS",
        }
    }
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum DisplayMode {
    #[default]
    Arc,
    Visualizer,
    Linear,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum VerifyMode {
    #[default]
    #[strum(serialize = "MANUAL")]
    Manual,
    #[strum(serialize = "SCAN")]
    Scan,
    #[strum(serialize = "POINTS")]
    Points,
}

/// User-facing calibration policy.  All modes retain the same hard safety,
/// routing, monotonicity, and detector-ambiguity checks; this only selects how
/// much measured pitch error/repeatability is acceptable for a usable curve.
/// FAST uses AUTO's final checks with fewer acquisition estimates per point.
#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum CalibrationPolicy {
    #[default]
    #[strum(serialize = "AUTO")]
    Auto,
    #[strum(serialize = "PRECISION")]
    Precision,
    #[strum(serialize = "FORGIVING")]
    Forgiving,
    #[strum(serialize = "FAST")]
    Fast,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum CalibrationGraph {
    #[default]
    #[strum(serialize = "PITCH")]
    Pitch,
    #[strum(serialize = "ERROR")]
    Error,
}

int_params!(InputParams<u8> { step: 1, min: 0, max: 3 });
int_params!(TransposeParams<i8> { step: 1, min: -12, max: 12 });

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum ScalePreset {
    #[default]
    #[strum(serialize = "CHROMATIC")]
    Chromatic,
    #[strum(serialize = "MAJOR")]
    Major,
    #[strum(serialize = "MINOR")]
    Minor,
    #[strum(serialize = "MAJ PENTA")]
    MajorPentatonic,
    #[strum(serialize = "MIN PENTA")]
    MinorPentatonic,
    #[strum(serialize = "24 EDO")]
    Edo24,
    #[strum(serialize = "CUSTOM 2")]
    Custom2,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum Distribution {
    #[default]
    #[strum(serialize = "NEAREST")]
    Nearest,
    #[strum(serialize = "EQUAL")]
    Equal,
}
int_params!(OctaveParams<u8> { step: 1, min: 0, max: 1 });
int_params!(PatternSlotParams<u8> { step: 1, min: 1, max: 8 });

#[derive(OptionPage, Clone)]
pub struct QuantSetupOpts {
    #[option(1)]
    pub slot: IntOption<PatternSlotParams>,
    #[option(false)]
    pub save: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub load: ButtonOption<OneShotButtonParams>,
}

#[derive(OptionPage, Clone)]
pub struct QuantNotesOpts {
    #[option(0)]
    pub octave: IntOption<OctaveParams>,
    #[option]
    pub note: EnumOption<ScaleRoot>,
    #[option(false)]
    pub toggle: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub clear: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub fill: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub learn: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub save: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub load: ButtonOption<OneShotButtonParams>,
    #[option(1)]
    pub slot: IntOption<PatternSlotParams>,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum ScaleRoot {
    #[default]
    C,
    #[strum(serialize = "C#")]
    Cs,
    D,
    #[strum(serialize = "D#")]
    Ds,
    E,
    F,
    #[strum(serialize = "F#")]
    Fs,
    G,
    #[strum(serialize = "G#")]
    Gs,
    A,
    #[strum(serialize = "A#")]
    As,
    B,
}
int_params!(NoteParams<u8> { step: 1, min: 12, max: 108 });
int_params!(CentsParams<i16> { step: 1, min: -50, max: 50 });
int_params!(ReferenceParams<u16> {
    step: 1, min: 400, max: 480,
    format: IntFormat::Scaled { divisor: 1, precision: 0, suffix: "Hz" }
});
int_params!(ScrollParams<u8> { step: 1, min: 0, max: 60 });
int_params!(ProfileSlotParams<u8> { step: 1, min: 1, max: 8 });
int_params!(NamePositionParams<u8> { step: 1, min: 1, max: 24 });
int_params!(NameCharacterParams<u8> { step: 1, min: 32, max: 126 });

button_params!(OneShotButtonParams {
    mode: ButtonMode::OneShot
});

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
    #[option(0)]
    pub output: IntOption<InputParams>,
    #[option(60)]
    pub zero_note: IntOption<NoteParams>,
    #[option]
    pub policy: EnumOption<CalibrationPolicy>,
    #[option]
    pub graph: EnumOption<CalibrationGraph>,
    #[option(false)]
    pub run: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub accept: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub discard: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub profiles: ButtonOption<OneShotButtonParams>,
}

#[derive(OptionPage, Clone)]
pub struct HelpOpts {
    #[option(0)]
    pub scroll: IntOption<ScrollParams>,
}

#[derive(OptionPage, Clone)]
pub struct PlayOpts {
    #[option(1)]
    pub output: IntOption<InputParams>,
    #[option(1)]
    pub input: IntOption<InputParams>,
    #[option(60)]
    pub zero_note: IntOption<NoteParams>,
    #[option]
    pub correction: EnumOption<Correction>,
    #[option(false)]
    pub bind: ButtonOption<OneShotButtonParams>,
    #[option]
    pub quantize: EnumOption<RouteQuantize>,
    #[option(false)]
    pub run: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub scales: ButtonOption<OneShotButtonParams>,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum Correction {
    #[default]
    #[strum(serialize = "NONE")]
    None,
    #[strum(serialize = "RAM")]
    Ram,
    #[strum(serialize = "SLOT 1")]
    Slot1,
    #[strum(serialize = "SLOT 2")]
    Slot2,
    #[strum(serialize = "SLOT 3")]
    Slot3,
    #[strum(serialize = "SLOT 4")]
    Slot4,
    #[strum(serialize = "SLOT 5")]
    Slot5,
    #[strum(serialize = "SLOT 6")]
    Slot6,
    #[strum(serialize = "SLOT 7")]
    Slot7,
    #[strum(serialize = "SLOT 8")]
    Slot8,
}
#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
pub enum RouteQuantize {
    #[strum(serialize = "OFF")]
    Off,
    #[default]
    #[strum(serialize = "SCALE")]
    Scale,
}

#[derive(OptionPage, Clone)]
pub struct QuantizerOpts {
    #[option(1)]
    pub output: IntOption<InputParams>,
    #[option]
    pub scale: EnumOption<ScalePreset>,
    #[option]
    pub root: EnumOption<ScaleRoot>,
    #[option(0)]
    pub transpose: IntOption<TransposeParams>,
    #[option]
    pub mapping: EnumOption<Distribution>,
    #[option(false)]
    pub notes: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub setups: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub routes: ButtonOption<OneShotButtonParams>,
}

#[derive(Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Default, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum QuantizeMode {
    #[default]
    Off,
    Chromatic,
}

#[derive(OptionPage, Clone)]
pub struct VerifyOpts {
    #[option(false)]
    pub run: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub improve: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub accept: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub discard: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub back: ButtonOption<OneShotButtonParams>,
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
    #[option(false)]
    pub check: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub back: ButtonOption<OneShotButtonParams>,
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
    #[page(Page::Play)]
    pub play: PlayOpts,
    #[page(Page::Quantizer)]
    pub quantizer: QuantizerOpts,
    #[page(Page::QuantNotes)]
    pub quant_notes: QuantNotesOpts,
    #[page(Page::QuantSetups)]
    pub quant_setups: QuantSetupOpts,
}
