use opts::*;
use serde_derive::{Deserialize, Serialize};
use strum_macros::{EnumIter, IntoStaticStr};
use tiliqua_hal::dma_framebuffer::Rotate;
use tiliqua_lib::palette::ColorPalette;
use tiliqua_pac::constants::HELP_SCROLL_MAX;

/// OSCIO bitstream time/div menu. Kept separate from ``tiliqua_lib::scope::Timebase``
/// so OSCIO can trim or extend its range without affecting other bitstreams.
#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum ScopeTimebase {
    #[strum(serialize = "5s/d")]
    Timebase5s,
    #[strum(serialize = "2s/d")]
    Timebase2s,
    #[strum(serialize = "1s/d")]
    Timebase1s,
    #[strum(serialize = "500ms/d")]
    Timebase500ms,
    #[strum(serialize = "200ms/d")]
    Timebase200ms,
    #[default]
    #[strum(serialize = "100ms/d")]
    Timebase100ms,
    #[strum(serialize = "50ms/d")]
    Timebase50ms,
    #[strum(serialize = "20ms/d")]
    Timebase20ms,
    #[strum(serialize = "10ms/d")]
    Timebase10ms,
    #[strum(serialize = "5ms/d")]
    Timebase5ms,
    #[strum(serialize = "2ms/d")]
    Timebase2ms,
    #[strum(serialize = "1ms/d")]
    Timebase1ms,
    #[strum(serialize = "500us/d")]
    Timebase500us,
    #[strum(serialize = "200us/d")]
    Timebase200us,
    #[strum(serialize = "100us/d")]
    Timebase100us,
}

impl ScopeTimebase {
    pub fn t_div_us(&self) -> u64 {
        match self {
            ScopeTimebase::Timebase5s => 5_000_000,
            ScopeTimebase::Timebase2s => 2_000_000,
            ScopeTimebase::Timebase1s => 1_000_000,
            ScopeTimebase::Timebase500ms => 500_000,
            ScopeTimebase::Timebase200ms => 200_000,
            ScopeTimebase::Timebase100ms => 100_000,
            ScopeTimebase::Timebase50ms => 50_000,
            ScopeTimebase::Timebase20ms => 20_000,
            ScopeTimebase::Timebase10ms => 10_000,
            ScopeTimebase::Timebase5ms => 5_000,
            ScopeTimebase::Timebase2ms => 2_000,
            ScopeTimebase::Timebase1ms => 1_000,
            ScopeTimebase::Timebase500us => 500,
            ScopeTimebase::Timebase200us => 200,
            ScopeTimebase::Timebase100us => 100,
        }
    }
}

/// Slow ranges used by the CV/LFO monitor. At ten horizontal divisions these
/// cover one second through fifty seconds of history, appropriate for signals
/// below the monitor's selectable maximum frequency.
#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum MonitorTimebase {
    #[strum(serialize = "5s/d")]
    Timebase5s,
    #[strum(serialize = "2s/d")]
    Timebase2s,
    #[default]
    #[strum(serialize = "1s/d")]
    Timebase1s,
    #[strum(serialize = "500ms/d")]
    Timebase500ms,
    #[strum(serialize = "200ms/d")]
    Timebase200ms,
    #[strum(serialize = "100ms/d")]
    Timebase100ms,
}

impl MonitorTimebase {
    pub fn t_div_us(&self) -> u64 {
        match self {
            MonitorTimebase::Timebase5s => 5_000_000,
            MonitorTimebase::Timebase2s => 2_000_000,
            MonitorTimebase::Timebase1s => 1_000_000,
            MonitorTimebase::Timebase500ms => 500_000,
            MonitorTimebase::Timebase200ms => 200_000,
            MonitorTimebase::Timebase100ms => 100_000,
        }
    }
}

/// Highest repeating frequency retained in the voltage-monitor history.
#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum MonitorFrequencyLimit {
    #[strum(serialize = "0.25Hz")]
    F0p25Hz,
    #[strum(serialize = "0.5Hz")]
    F0p5Hz,
    #[strum(serialize = "1Hz")]
    F1Hz,
    #[strum(serialize = "2Hz")]
    F2Hz,
    #[strum(serialize = "5Hz")]
    F5Hz,
    #[strum(serialize = "10Hz")]
    F10Hz,
    #[default]
    #[strum(serialize = "20Hz")]
    F20Hz,
}

impl MonitorFrequencyLimit {
    pub fn minimum_period_ms(self) -> u32 {
        match self {
            MonitorFrequencyLimit::F0p25Hz => 4_000,
            MonitorFrequencyLimit::F0p5Hz => 2_000,
            MonitorFrequencyLimit::F1Hz => 1_000,
            MonitorFrequencyLimit::F2Hz => 500,
            MonitorFrequencyLimit::F5Hz => 200,
            MonitorFrequencyLimit::F10Hz => 100,
            MonitorFrequencyLimit::F20Hz => 50,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            MonitorFrequencyLimit::F0p25Hz => "0.25Hz",
            MonitorFrequencyLimit::F0p5Hz => "0.5Hz",
            MonitorFrequencyLimit::F1Hz => "1Hz",
            MonitorFrequencyLimit::F2Hz => "2Hz",
            MonitorFrequencyLimit::F5Hz => "5Hz",
            MonitorFrequencyLimit::F10Hz => "10Hz",
            MonitorFrequencyLimit::F20Hz => "20Hz",
        }
    }

    pub fn spaced_label(self) -> &'static str {
        match self {
            MonitorFrequencyLimit::F0p25Hz => "0.25 Hz",
            MonitorFrequencyLimit::F0p5Hz => "0.5 Hz",
            MonitorFrequencyLimit::F1Hz => "1 Hz",
            MonitorFrequencyLimit::F2Hz => "2 Hz",
            MonitorFrequencyLimit::F5Hz => "5 Hz",
            MonitorFrequencyLimit::F10Hz => "10 Hz",
            MonitorFrequencyLimit::F20Hz => "20 Hz",
        }
    }
}

/// OSCIO bitstream volts/div menu. Kept separate from ``tiliqua_lib::scope::VScale``
/// so OSCIO can use Eurorack-friendly steps without affecting other bitstreams.
#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum ScopeVScale {
    #[strum(serialize = "100mV/d")]
    Scale100mV,
    #[strum(serialize = "250mV/d")]
    Scale250mV,
    #[strum(serialize = "500mV/d")]
    Scale500mV,
    #[default]
    #[strum(serialize = "1V/d")]
    Scale1V,
    #[strum(serialize = "2.5V/d")]
    Scale2p5V,
    #[strum(serialize = "5V/d")]
    Scale5V,
}

impl ScopeVScale {
    /// Hardware LUT index written to ``yscaleN`` CSRs (see ``scope_capture.YSCALE_LUT``).
    pub fn to_hw_index(self) -> u8 {
        match self {
            ScopeVScale::Scale100mV => 0,
            ScopeVScale::Scale250mV => 1,
            ScopeVScale::Scale500mV => 2,
            ScopeVScale::Scale1V => 3,
            ScopeVScale::Scale2p5V => 4,
            ScopeVScale::Scale5V => 5,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum ViewMode {
    #[default]
    Scope,
    Monitor,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum MonitorPair {
    #[default]
    #[strum(serialize = "CH 1-2")]
    Chan12,
    #[strum(serialize = "CH 3-4")]
    Chan34,
}

impl MonitorPair {
    pub fn first_channel(self) -> usize {
        match self {
            MonitorPair::Chan12 => 0,
            MonitorPair::Chan34 => 2,
        }
    }
}

/// Full vertical voltage window used by one monitor history lane.
#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum MonitorRange {
    #[strum(serialize = "-5..+5V")]
    Bipolar5V,
    #[default]
    #[strum(serialize = "-10..+10V")]
    Bipolar10V,
    #[strum(serialize = "0..+10V")]
    Unipolar10V,
    #[strum(serialize = "0..+5V")]
    Unipolar5V,
}

impl MonitorRange {
    /// Hardware LUT index written to the per-channel y-scale CSR.
    pub fn scale_index(self) -> u8 {
        match self {
            MonitorRange::Bipolar5V => 6,
            MonitorRange::Bipolar10V => 7,
            MonitorRange::Unipolar10V => 8,
            MonitorRange::Unipolar5V => 9,
        }
    }

    /// The unipolar zero line is the bottom of the 160-pixel range window.
    pub fn center_offset_px(self) -> i16 {
        match self {
            MonitorRange::Bipolar5V | MonitorRange::Bipolar10V => 0,
            MonitorRange::Unipolar10V | MonitorRange::Unipolar5V => 80,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum Page {
    #[default]
    #[strum(serialize = "OSCIO")]
    Mode,
    #[strum(serialize = "CH 1-2")]
    Chan12,
    #[strum(serialize = "CH 3-4")]
    Chan34,
    #[strum(serialize = "SCOPE")]
    Scope,
    #[strum(serialize = "MONITOR")]
    Monitor,
    #[strum(serialize = "DISPLAY")]
    Display,
    #[strum(serialize = "SYSTEM")]
    System,
    #[strum(serialize = "HELP")]
    Help,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum TriggerMode {
    #[default]
    Rising,
    Falling,
    #[strum(serialize = "free")]
    Free,
    #[strum(serialize = "auto rise")]
    AutoRising,
    #[strum(serialize = "auto fall")]
    AutoFalling,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum TriggerChannel {
    #[default]
    #[strum(serialize = "1")]
    Ch1,
    #[strum(serialize = "2")]
    Ch2,
    #[strum(serialize = "3")]
    Ch3,
    #[strum(serialize = "4")]
    Ch4,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum TriggerFilter {
    #[default]
    #[strum(serialize = "off")]
    Off,
    #[strum(serialize = "5kHz")]
    F5kHz,
    #[strum(serialize = "1.2kHz")]
    F1p2kHz,
    #[strum(serialize = "300Hz")]
    F300Hz,
    #[strum(serialize = "75Hz")]
    F75Hz,
}

impl TriggerFilter {
    pub fn hw_index(self) -> u8 {
        match self {
            TriggerFilter::Off => 0,
            TriggerFilter::F5kHz => 1,
            TriggerFilter::F1p2kHz => 2,
            TriggerFilter::F300Hz => 3,
            TriggerFilter::F75Hz => 4,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum AcquisitionMode {
    #[default]
    #[strum(serialize = "clean")]
    Clean,
    #[strum(serialize = "raw")]
    Raw,
}

impl TriggerChannel {
    pub fn hw_index(self) -> u8 {
        match self {
            TriggerChannel::Ch1 => 0,
            TriggerChannel::Ch2 => 1,
            TriggerChannel::Ch3 => 2,
            TriggerChannel::Ch4 => 3,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum GridOverlay {
    Off,
    Grid,
    #[default]
    Cross,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum EditHide {
    Off,
    #[default]
    On,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum ChannelVis {
    #[default]
    #[strum(serialize = "Yes")]
    On,
    #[strum(serialize = "No")]
    Off,
}

int_params!(IntensityParams<u8>   { step: 1, min: 0, max: 15 });
int_params!(HueParams<u8>         { step: 1, min: 0, max: 15 });
int_params!(HideParams<u8>        { step: 1, min: 2, max: 16, format: IntFormat::Scaled { divisor: 2, precision: 1, suffix: "s" } });
int_params!(TriggerLvlParams<i16> { step: 500, min: -16000, max: 16000, format: IntFormat::Scaled { divisor: 4000, precision: 2, suffix: "V" } });
int_params!(PosParams<i16>       { step: 1, min: -40, max: 40, format: IntFormat::Scaled { divisor: 4, precision: 2, suffix: "d" } });
// Generated from MODULE_DOCSTRING's line count so help edits cannot leave an
// obsolete range or allow scrolling into an empty viewport.
int_params!(ScrollParams<u8>      { step: 1, min: 0, max: HELP_SCROLL_MAX });

button_params!(OneShotButtonParams {
    mode: ButtonMode::OneShot
});

#[derive(OptionPage, Clone)]
pub struct HelpOpts {
    #[option(0)]
    pub scroll: IntOption<ScrollParams>,
}

#[derive(OptionPage, Clone)]
pub struct SystemOpts {
    #[option(10)]
    pub ui_hue: IntOption<HueParams>,
    #[option(5)]
    pub hide: IntOption<HideParams>,
    #[option]
    pub edit_hide: EnumOption<EditHide>,
    #[option]
    pub rotation: EnumOption<Rotate>,
    #[option(false)]
    pub save_settings: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub reset_settings: ButtonOption<OneShotButtonParams>,
}

#[derive(OptionPage, Clone)]
pub struct DisplayOpts {
    #[option]
    pub grid: EnumOption<GridOverlay>,
    #[option(4)]
    pub grid_i: IntOption<IntensityParams>,
    #[option(8)]
    pub intensity: IntOption<IntensityParams>,
    #[option(10)]
    pub hue: IntOption<HueParams>,
    #[option]
    pub palette: EnumOption<ColorPalette>,
}

/// Convert ``Hide`` menu value (0.5 s steps) to milliseconds for the UI fade timer.
pub fn menu_hide_ms(hide: u8) -> u32 {
    hide as u32 * 500
}

#[derive(OptionPage, Clone)]
pub struct Chan12Opts {
    #[option(0)]
    pub ch1_y_offset: IntOption<PosParams>,
    #[option(ScopeVScale::Scale1V)]
    pub ch1_scale: EnumOption<ScopeVScale>,
    #[option]
    pub ch1_enabled: EnumOption<ChannelVis>,
    #[option(0)]
    pub ch2_y_offset: IntOption<PosParams>,
    #[option(ScopeVScale::Scale1V)]
    pub ch2_scale: EnumOption<ScopeVScale>,
    #[option]
    pub ch2_enabled: EnumOption<ChannelVis>,
}

#[derive(OptionPage, Clone)]
pub struct Chan34Opts {
    #[option(0)]
    pub ch3_y_offset: IntOption<PosParams>,
    #[option(ScopeVScale::Scale1V)]
    pub ch3_scale: EnumOption<ScopeVScale>,
    #[option]
    pub ch3_enabled: EnumOption<ChannelVis>,
    #[option(0)]
    pub ch4_y_offset: IntOption<PosParams>,
    #[option(ScopeVScale::Scale1V)]
    pub ch4_scale: EnumOption<ScopeVScale>,
    #[option]
    pub ch4_enabled: EnumOption<ChannelVis>,
}

#[derive(OptionPage, Clone)]
pub struct ModeOpts {
    #[option]
    pub view: EnumOption<ViewMode>,
    #[option]
    pub scope_timebase: EnumOption<ScopeTimebase>,
    #[option]
    pub scope_acquisition: EnumOption<AcquisitionMode>,
    #[option]
    pub monitor_timebase: EnumOption<MonitorTimebase>,
    #[option]
    pub monitor_frequency: EnumOption<MonitorFrequencyLimit>,
    #[option]
    pub monitor_pair: EnumOption<MonitorPair>,
}

#[derive(OptionPage, Clone)]
pub struct ScopeOpts {
    #[option]
    pub trigger: EnumOption<TriggerMode>,
    #[option]
    pub trigger_ch: EnumOption<TriggerChannel>,
    #[option]
    pub trig_lvl: IntOption<TriggerLvlParams>,
    #[option]
    pub trig_filter: EnumOption<TriggerFilter>,
}

#[derive(OptionPage, Clone)]
pub struct MonitorOpts {
    #[option]
    pub ch1_range: EnumOption<MonitorRange>,
    #[option]
    pub ch2_range: EnumOption<MonitorRange>,
    #[option]
    pub ch3_range: EnumOption<MonitorRange>,
    #[option]
    pub ch4_range: EnumOption<MonitorRange>,
}

#[derive(Options, Clone)]
pub struct Opts {
    pub tracker: ScreenTracker<Page>,
    #[page(Page::Mode)]
    pub mode: ModeOpts,
    #[page(Page::Help)]
    pub help: HelpOpts,
    #[page(Page::Chan12)]
    pub chan12: Chan12Opts,
    #[page(Page::Chan34)]
    pub chan34: Chan34Opts,
    #[page(Page::Scope)]
    pub scope: ScopeOpts,
    #[page(Page::Monitor)]
    pub monitor: MonitorOpts,
    #[page(Page::Display)]
    pub display: DisplayOpts,
    #[page(Page::System)]
    pub system: SystemOpts,
}

/// Mode-specific pages shown when turning the encoder at the page title. The
/// mode selector is always first and Help is always last.
pub const SCOPE_MENU_PAGES: [Page; 7] = [
    Page::Mode,
    Page::Chan12,
    Page::Chan34,
    Page::Scope,
    Page::Display,
    Page::System,
    Page::Help,
];

pub const MONITOR_MENU_PAGES: [Page; 5] = [
    Page::Mode,
    Page::Monitor,
    Page::Display,
    Page::System,
    Page::Help,
];

const SCOPE_HOME_OPTIONS: &[usize] = &[0, 1, 2];
const MONITOR_HOME_OPTIONS: &[usize] = &[0, 3, 4];
const MONITOR_CIRCULAR_HOME_OPTIONS: &[usize] = &[0, 3, 4, 5];
const MONITOR_DISPLAY_OPTIONS: &[usize] = &[2, 3, 4];

fn visible_option_indices(opts: &Opts, circular_display: bool) -> Option<&'static [usize]> {
    match (opts.tracker.page.value, opts.mode.view.value) {
        (Page::Mode, ViewMode::Scope) => Some(SCOPE_HOME_OPTIONS),
        (Page::Mode, ViewMode::Monitor) if circular_display => Some(MONITOR_CIRCULAR_HOME_OPTIONS),
        (Page::Mode, ViewMode::Monitor) => Some(MONITOR_HOME_OPTIONS),
        (Page::Display, ViewMode::Monitor) => Some(MONITOR_DISPLAY_OPTIONS),
        _ => None,
    }
}

pub fn scope_consume_ticks(opts: &mut Opts, ticks: i8, circular_display: bool) {
    if ticks >= 1 {
        for _ in 0..ticks {
            scope_tick_up(opts, circular_display);
        }
    }
    if ticks <= -1 {
        for _ in 0..(-ticks) {
            scope_tick_down(opts, circular_display);
        }
    }
}

fn scope_tick_up(opts: &mut Opts, circular_display: bool) {
    if let Some(n_selected) = opts.selected() {
        if opts.modify() {
            opts.view_mut().options_mut()[n_selected].tick_up();
        } else if let Some(indices) = visible_option_indices(opts, circular_display) {
            if let Some(position) = indices.iter().position(|&index| index == n_selected) {
                if position + 1 < indices.len() {
                    opts.set_selected(Some(indices[position + 1]));
                }
            }
        } else if n_selected + 1 < opts.view().options().len() {
            opts.set_selected(Some(n_selected + 1));
        }
    } else if opts.modify() {
        scope_page_step(opts, 1);
    } else if !opts.view().options().is_empty() {
        let first = visible_option_indices(opts, circular_display)
            .and_then(|indices| indices.first().copied())
            .unwrap_or(0);
        opts.set_selected(Some(first));
    }
}

fn scope_tick_down(opts: &mut Opts, circular_display: bool) {
    if let Some(n_selected) = opts.selected() {
        if opts.modify() {
            opts.view_mut().options_mut()[n_selected].tick_down();
        } else if let Some(indices) = visible_option_indices(opts, circular_display) {
            if let Some(position) = indices.iter().position(|&index| index == n_selected) {
                if position == 0 {
                    opts.set_selected(None);
                } else {
                    opts.set_selected(Some(indices[position - 1]));
                }
            }
        } else if n_selected != 0 {
            opts.set_selected(Some(n_selected - 1));
        } else {
            opts.set_selected(None);
        }
    } else if opts.modify() {
        scope_page_step(opts, -1);
    }
}

fn scope_page_step(opts: &mut Opts, dir: i8) {
    let current = opts.tracker.page.value;
    let pages: &[Page] = match opts.mode.view.value {
        ViewMode::Scope => &SCOPE_MENU_PAGES,
        ViewMode::Monitor => &MONITOR_MENU_PAGES,
    };
    let mut idx = pages.iter().position(|&p| p == current).unwrap_or(0);
    if dir > 0 {
        if idx + 1 < pages.len() {
            idx += 1;
        }
    } else if dir < 0 && idx > 0 {
        idx -= 1;
    }
    opts.tracker.page.value = pages[idx];
}
