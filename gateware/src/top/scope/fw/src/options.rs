use opts::*;
use strum_macros::{EnumIter, IntoStaticStr};
use tiliqua_lib::palette::ColorPalette;
pub use tiliqua_lib::scope::{Timebase, VScale};
use tiliqua_hal::dma_framebuffer::Rotate;
use serde_derive::{Serialize, Deserialize};

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "SCREAMING-KEBAB-CASE")]
pub enum Page {
    #[default]
    Scope1,
    Scope2,
    Display,
    Misc,
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
#[strum(serialize_all = "kebab-case")]
pub enum ChannelVis {
    #[default]
    On,
    Off,
}

int_params!(IntensityParams<u8>   { step: 1, min: 0, max: 15 });
int_params!(HueParams<u8>         { step: 1, min: 0, max: 15 });
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
pub struct DisplayOpts {
    #[option(10)]
    pub ui_hue: IntOption<HueParams>,
    #[option]
    pub palette: EnumOption<ColorPalette>,
    #[option]
    pub grid: EnumOption<GridOverlay>,
    #[option(4)]
    pub grid_i: IntOption<IntensityParams>,
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
    pub save_opts: ButtonOption<OneShotButtonParams>,
    #[option(false)]
    pub wipe_opts: ButtonOption<OneShotButtonParams>,
}

#[derive(OptionPage, Clone)]
pub struct ScopeOpts1 {
    #[option(-14)]
    pub ypos0: IntOption<PosParams>,
    #[option(-5)]
    pub ypos1: IntOption<PosParams>,
    #[option(5)]
    pub ypos2: IntOption<PosParams>,
    #[option(14)]
    pub ypos3: IntOption<PosParams>,
    #[option(VScale::Scale4V)]
    pub yscale0: EnumOption<VScale>,
    #[option(VScale::Scale4V)]
    pub yscale1: EnumOption<VScale>,
    #[option(VScale::Scale4V)]
    pub yscale2: EnumOption<VScale>,
    #[option(VScale::Scale4V)]
    pub yscale3: EnumOption<VScale>,
    #[option]
    pub vis0: EnumOption<ChannelVis>,
    #[option]
    pub vis1: EnumOption<ChannelVis>,
    #[option]
    pub vis2: EnumOption<ChannelVis>,
    #[option]
    pub vis3: EnumOption<ChannelVis>,
}

#[derive(OptionPage, Clone)]
pub struct ScopeOpts2 {
    #[option]
    pub timebase: EnumOption<Timebase>,
    #[option]
    pub trig_mode: EnumOption<TriggerMode>,
    #[option]
    pub trig_lvl: IntOption<TriggerLvlParams>,
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
    #[page(Page::Display)]
    pub display: DisplayOpts,
    #[page(Page::Misc)]
    pub misc: MiscOpts,
    #[page(Page::Scope1)]
    pub scope1: ScopeOpts1,
    #[page(Page::Scope2)]
    pub scope2: ScopeOpts2,
}

/// Pages shown when turning the encoder at the page title (no wrap).
pub const MENU_PAGES: [Page; 4] = [
    Page::Scope1,
    Page::Scope2,
    Page::Display,
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
