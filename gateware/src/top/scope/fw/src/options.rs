use opts::*;
use strum_macros::{EnumIter, IntoStaticStr};
use tiliqua_lib::palette::ColorPalette;
use tiliqua_hal::dma_framebuffer::Rotate;
use serde_derive::{Serialize, Deserialize};

/// SCOPE bitstream time/div menu.  Kept separate from ``tiliqua_lib::scope::Timebase``
/// so SCOPE can trim or extend its range without affecting other bitstreams.
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
}

impl ScopeTimebase {
    pub fn t_div_us(&self) -> u64 {
        match self {
            ScopeTimebase::Timebase5s    => 5_000_000,
            ScopeTimebase::Timebase2s    => 2_000_000,
            ScopeTimebase::Timebase1s    => 1_000_000,
            ScopeTimebase::Timebase500ms => 500_000,
            ScopeTimebase::Timebase200ms => 200_000,
            ScopeTimebase::Timebase100ms => 100_000,
            ScopeTimebase::Timebase50ms  => 50_000,
            ScopeTimebase::Timebase20ms  => 20_000,
            ScopeTimebase::Timebase10ms  => 10_000,
            ScopeTimebase::Timebase5ms   => 5_000,
            ScopeTimebase::Timebase2ms   => 2_000,
            ScopeTimebase::Timebase1ms   => 1_000,
        }
    }
}

/// SCOPE bitstream volts/div menu.  Kept separate from ``tiliqua_lib::scope::VScale``
/// so SCOPE can use Eurorack-friendly steps without affecting other bitstreams.
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
            ScopeVScale::Scale1V    => 3,
            ScopeVScale::Scale2p5V  => 4,
            ScopeVScale::Scale5V    => 5,
        }
    }
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
pub enum Page {
    #[default]
    #[strum(serialize = "CH 1-2")]
    Chan12,
    #[strum(serialize = "CH 3-4")]
    Chan34,
    #[strum(serialize = "SCOPE")]
    Scope,
    #[strum(serialize = "MENU")]
    Menu,
    #[strum(serialize = "MISC")]
    Misc,
    #[strum(serialize = "HELP")]
    Help,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum TriggerMode {
    Always,
    #[default]
    Rising,
}

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum HelpPage {
    #[default]
    Off,
    On,
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
pub enum CcHighlight {
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
int_params!(ScrollParams<u8>      { step: 1, min: 0, max: 125 });

button_params!(OneShotButtonParams { mode: ButtonMode::OneShot });

#[derive(OptionPage, Clone)]
pub struct HelpOpts {
    #[option(0)]
    pub scroll: IntOption<ScrollParams>,
}

#[derive(OptionPage, Clone)]
pub struct MenuOpts {
    #[option(10)]
    pub ui_hue: IntOption<HueParams>,
    #[option]
    pub palette: EnumOption<ColorPalette>,
    #[option(5)]
    pub hide: IntOption<HideParams>,
}

/// Convert ``Hide`` menu value (0.5 s steps) to milliseconds for the UI fade timer.
pub fn menu_hide_ms(hide: u8) -> u32 {
    hide as u32 * 500
}

#[derive(OptionPage, Clone)]
pub struct MiscOpts {
    #[option]
    pub rotation: EnumOption<Rotate>,
    #[option]
    pub help: EnumOption<HelpPage>,
    #[option]
    pub cc_highlight: EnumOption<CcHighlight>,
    #[option(false)]
    pub save_settings: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub reset_settings: ButtonOption<OneShotButtonParams>,
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
pub struct ScopeOpts {
    #[option]
    pub timebase: EnumOption<ScopeTimebase>,
    #[option]
    pub trigger: EnumOption<TriggerMode>,
    #[option]
    pub trig_lvl: IntOption<TriggerLvlParams>,
    #[option]
    pub grid: EnumOption<GridOverlay>,
    #[option(4)]
    pub grid_i: IntOption<IntensityParams>,
    #[option(8)]
    pub intensity: IntOption<IntensityParams>,
    #[option(10)]
    pub hue: IntOption<HueParams>,
}

#[derive(Options, Clone)]
pub struct Opts {
    pub tracker: ScreenTracker<Page>,
    #[page(Page::Help)]
    pub help: HelpOpts,
    #[page(Page::Chan12)]
    pub chan12: Chan12Opts,
    #[page(Page::Chan34)]
    pub chan34: Chan34Opts,
    #[page(Page::Scope)]
    pub scope: ScopeOpts,
    #[page(Page::Menu)]
    pub menu: MenuOpts,
    #[page(Page::Misc)]
    pub misc: MiscOpts,
}

/// Pages shown when turning the encoder at the page title (no wrap).
pub const MENU_PAGES: [Page; 5] = [
    Page::Chan12,
    Page::Chan34,
    Page::Scope,
    Page::Menu,
    Page::Misc,
];

pub fn scope_consume_ticks(opts: &mut Opts, ticks: i8) {
    if ticks >= 1 {
        for _ in 0..ticks {
            scope_tick_up(opts);
        }
    }
    if ticks <= -1 {
        for _ in 0..(-ticks) {
            scope_tick_down(opts);
        }
    }
}

fn scope_tick_up(opts: &mut Opts) {
    if let Some(n_selected) = opts.selected() {
        if opts.modify() {
            opts.view_mut().options_mut()[n_selected].tick_up();
        } else if n_selected + 1 < opts.view().options().len() {
            opts.set_selected(Some(n_selected + 1));
        }
    } else if opts.modify() {
        scope_page_step(opts, 1);
    } else if !opts.view().options().is_empty() {
        opts.set_selected(Some(0));
    }
}

fn scope_tick_down(opts: &mut Opts) {
    if let Some(n_selected) = opts.selected() {
        if opts.modify() {
            opts.view_mut().options_mut()[n_selected].tick_down();
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
    let mut idx = MENU_PAGES
        .iter()
        .position(|&p| p == current)
        .unwrap_or(0);
    if dir > 0 {
        if idx + 1 < MENU_PAGES.len() {
            idx += 1;
        }
    } else if dir < 0 && idx > 0 {
        idx -= 1;
    }
    opts.tracker.page.value = MENU_PAGES[idx];
}
