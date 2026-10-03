//! Transient diagram navigation. Persisted options and operation polling retain
//! their original indices; virtual nodes never reach the generic click handler.
use crate::{
    options::{Opts, Page},
    ownership::{Owner, Reservations},
    route_group::Layout,
};
use opts::OptionsEncoderInterface;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stage {
    Input,
    Midi,
    Scale,
    Add,
    Destination,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Screen {
    Overview,
    Flow,
    Editor(Stage),
    Warning,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WarningKind {
    Running(u8),
    Calibration,
    InvalidSetup,
    SavedConflict(bool, u8, u8, u8),
}
#[derive(Clone, Copy)]
pub struct Warning {
    pub kind: WarningKind,
    pub page: Page,
    pub focus: Option<usize>,
    pub go: bool,
}
pub const DONE: usize = 16;
#[derive(Clone, Copy)]
pub struct View {
    pub screen: Screen,
    pub window: u8,
    pub return_focus: u8,
    pub midi_from_configs: bool,
    pub pending: Option<(Stage, u8)>,
    pub finish_midi: bool,
    pub layout: Layout,
    pub warning: Option<Warning>,
}
impl View {
    pub const fn new() -> Self {
        Self {
            screen: Screen::Overview,
            window: 0,
            return_focus: 0,
            midi_from_configs: false,
            pending: None,
            finish_midi: false,
            layout: Layout::new(),
            warning: None,
        }
    }
    pub fn warn(&mut self, o: &mut Opts, kind: WarningKind) {
        self.warning = Some(Warning {
            kind,
            page: o.tracker.page.value,
            focus: o.tracker.selected,
            go: matches!(kind, WarningKind::Running(_)),
        });
        self.screen = Screen::Warning;
        o.tracker.page.value = Page::Play;
        o.tracker.modify = false;
    }
    pub fn handles(&self, page: Page) -> bool {
        page == Page::QuantSetups
            || page == Page::Play
            || (page == Page::RouteMidi && self.screen == Screen::Editor(Stage::Midi))
    }
    pub fn fields(stage: Stage) -> &'static [usize] {
        match stage {
            Stage::Input => &[1, DONE],
            Stage::Midi => &[1, 2, 5, 4, 3, DONE],
            Stage::Scale => &[5, 9, 10, 15, 11, 12, 7, DONE],
            Stage::Destination => &[3, 4, 2, 13, 14, DONE],
            Stage::Add => &[13, 14, DONE],
        }
    }
    pub fn fields_for(stage: Stage, profile: u8) -> &'static [usize] {
        match (stage, profile) {
            (Stage::Destination, 0) => &[3, 2, 13, 14, DONE],
            _ => Self::fields(stage),
        }
    }
    pub fn editor_fields(&self, stage: Stage, profile: u8) -> &'static [usize] {
        if stage == Stage::Midi && self.midi_from_configs {
            &[0, 1, 2, 5, 4, 3, 6]
        } else {
            Self::fields_for(stage, profile)
        }
    }
    pub fn outputs(&self, route: u8) -> [Option<u8>; 2] {
        let mask = self.layout.outputs[route.min(3) as usize];
        let mut result = [None; 2];
        let mut index = 0;
        for n in 0..4 {
            if mask & (1 << n) != 0 {
                if index >= self.window as usize * 2 && index < self.window as usize * 2 + 2 {
                    result[index % 2] = Some(n);
                }
                index += 1;
            }
        }
        result
    }
    pub fn clamp_window(&mut self, route: u8) {
        if self.layout.outputs[route.min(3) as usize].count_ones() <= 2 {
            self.window = 0;
        }
    }
    fn flow_order(&self, route: u8) -> ([usize; 15], usize) {
        let mut order = [0; 15];
        let mut len = 0;
        if self.layout.outputs[route as usize] == 0 {
            order[..3].copy_from_slice(&[11, 13, 14]);
            return (order, 3);
        }
        let outputs = self.outputs(route);
        for n in 0..15 {
            let visible = match n {
                2..=9 => outputs[(n - 2) / 4].is_some() && (n - 2) % 2 == 0,
                10 => self.layout.outputs[route as usize].count_ones() > 2,
                _ => true,
            };
            if visible {
                order[len] = n;
                len += 1;
            }
        }
        (order, len)
    }
    pub fn ticks(&mut self, o: &mut Opts, ticks: i8, claims: &Reservations) -> bool {
        if o.tracker.page.value == Page::QuantSetups || !self.handles(o.tracker.page.value) {
            return false;
        }
        if o.tracker.selected.is_none() && o.tracker.modify && self.screen == Screen::Overview {
            return false;
        }
        if self.screen == Screen::Warning {
            if let Some(w) = self.warning.as_mut() {
                w.go = ticks < 0 && matches!(w.kind, WarningKind::Running(_));
            }
            return true;
        }
        if self.pending.is_some() {
            return true;
        }
        self.clamp_window(o.play.output.value);
        for _ in 0..ticks.unsigned_abs() {
            let forward = ticks > 0;
            if let Screen::Editor(stage) = self.screen {
                if o.tracker.modify {
                    if stage == Stage::Midi {
                        o.consume_ticks(if forward { 1 } else { -1 });
                    } else if matches!(o.tracker.selected, Some(1 | 13)) {
                        let output = o.tracker.selected == Some(13);
                        let route = o.play.output.value.min(3);
                        let free = self.layout.available(route, output, claims);
                        let value = if output {
                            &mut o.play.output_edit.value
                        } else {
                            &mut o.play.input.value
                        };
                        if let Some(next) = (1..=4)
                            .map(|n| {
                                if forward {
                                    (*value + n) % 4
                                } else {
                                    (*value + 4 - n) % 4
                                }
                            })
                            .find(|n| free & (1 << n) != 0)
                        {
                            *value = next;
                        }
                    } else {
                        crate::ui_navigation::visible_ticks(
                            o,
                            if forward { 1 } else { -1 },
                            claims,
                        );
                    }
                    continue;
                }
            } else if self.screen == Screen::Flow
                && o.tracker.modify
                && o.tracker.selected == Some(10)
            {
                self.window = if forward { 1 } else { 0 };
                continue;
            }
            if self.screen == Screen::Overview {
                // Actions belong to the highlighted card, before moving to
                // another route. START must not silently target the last card.
                let route = o.play.output.value.min(3) as usize;
                let has_outputs = self.layout.outputs[route] != 0;
                let next = match (o.tracker.selected, forward) {
                    (None, true) => Some(0),
                    (Some(0..=3), true) => Some(if has_outputs { 4 } else { 6 }),
                    (Some(4), true) => Some(6),
                    (Some(6), true) => {
                        if route < 3 {
                            Some(route + 1)
                        } else {
                            Some(6)
                        }
                    }
                    (Some(n @ 0..=3), false) => {
                        if n == 0 {
                            None
                        } else {
                            o.play.output.value = (n - 1) as u8;
                            Some(6)
                        }
                    }
                    (Some(4), false) => Some(route),
                    (Some(6), false) => Some(if has_outputs { 4 } else { route }),
                    _ => None,
                };
                o.tracker.selected = next;
                if let Some(n @ 0..=3) = next {
                    o.play.output.value = n as u8;
                    self.window = 0;
                }
                continue;
            }
            let (flow, len) = if self.screen == Screen::Flow {
                self.flow_order(o.play.output.value.min(3))
            } else {
                ([0; 15], 0)
            };
            let order = match self.screen {
                Screen::Overview => unreachable!("overview navigation handled above"),
                Screen::Flow => &flow[..len],
                Screen::Editor(stage) => self.editor_fields(stage, o.play.correction.value as u8),
                Screen::Warning => &[],
            };
            let current = o
                .tracker
                .selected
                .and_then(|s| order.iter().position(|n| *n == s));
            o.tracker.selected = match (current, forward) {
                (None, true) => Some(order[0]),
                (Some(n), true) => Some(order[(n + 1).min(order.len() - 1)]),
                (Some(0), false) => Some(order[0]),
                (Some(n), false) => Some(order[n - 1]),
                _ => None,
            };
        }
        true
    }
    pub fn click(&mut self, o: &mut Opts, claims: &Reservations) -> bool {
        if o.tracker.page.value == Page::QuantSetups || !self.handles(o.tracker.page.value) {
            return false;
        }
        if self.screen == Screen::Warning {
            if let Some(w) = self.warning.take() {
                if let (true, WarningKind::Running(route)) = (w.go, w.kind) {
                    o.play.output.value = route;
                    self.screen = Screen::Flow;
                    self.window = 0;
                    o.tracker.selected = Some(0);
                } else {
                    o.tracker.page.value = w.page;
                    o.tracker.selected = w.focus;
                    self.screen = Screen::Overview;
                }
                o.tracker.modify = false;
            }
            return true;
        }
        let Some(focus) = o.tracker.selected else {
            return self.screen != Screen::Overview;
        };
        if self.pending.is_some() {
            return true;
        }
        let route = o.play.output.value.min(3);
        let held = claims.held(Owner::Quant(route));
        match self.screen {
            Screen::Warning => {}
            Screen::Overview => match focus {
                0..=3 => {
                    self.screen = Screen::Flow;
                    self.window = 0;
                    o.tracker.selected = Some(if self.layout.outputs[route as usize] == 0 {
                        11
                    } else {
                        0
                    });
                }
                4 => o.play.run.value = true,
                6 => o.play.setups.value = true,
                _ => {}
            },
            Screen::Flow => {
                let node = match focus {
                    0 => Some((Stage::Input, 255)),
                    1 => Some((Stage::Midi, 255)),
                    2 | 4 | 6 | 8 => self.outputs(route)[(focus - 2) / 4].map(|out| {
                        (
                            if (focus - 2) % 4 == 0 {
                                Stage::Scale
                            } else {
                                Stage::Destination
                            },
                            out,
                        )
                    }),
                    11 => Some((Stage::Add, 255)),
                    _ => None,
                };
                if let Some((stage, out)) = node {
                    if stage == Stage::Add && held {
                        return true;
                    }
                    let out = if stage == Stage::Add {
                        // An empty route begins with a usable source; placeholders
                        // from another route's setup must not silently block ADD.
                        if self.layout.outputs[route as usize] == 0 {
                            let sources = self.layout.available(route, false, claims);
                            if sources == 0 {
                                return true;
                            }
                            if sources & (1 << o.play.input.value) == 0 {
                                o.play.input.value = sources.trailing_zeros() as u8;
                            }
                        }
                        // ADD only offers unassigned destinations.
                        let free = self.layout.available(route, true, claims)
                            & !self.layout.outputs[route as usize];
                        if free == 0 {
                            return true;
                        }
                        free.trailing_zeros() as u8
                    } else {
                        out
                    };
                    self.return_focus = focus as u8;
                    self.pending = Some((stage, out));
                    if out < 4 {
                        o.play.output_edit.value = out;
                    }
                } else {
                    match focus {
                        10 => o.tracker.modify = !o.tracker.modify,
                        12 => o.play.run.value = true,
                        13 => {
                            self.screen = Screen::Overview;
                            o.tracker.selected = Some(route as usize);
                        }
                        14 => o.play.setups.value = true,
                        _ => {}
                    }
                }
            }
            Screen::Editor(stage) => {
                if focus == DONE {
                    self.finish_midi = stage == Stage::Midi;
                    self.screen = Screen::Flow;
                    o.tracker.page.value = Page::Play;
                    o.tracker.selected = Some(if self.layout.outputs[route as usize] == 0 {
                        11
                    } else {
                        self.return_focus as usize
                    });
                    o.tracker.modify = false;
                    return true;
                }
                if held && stage != Stage::Midi {
                    o.tracker.modify = false;
                    return true;
                }
                // A field or a real one-shot action belongs to the existing
                // option page. Never index a virtual node in that page.
                if self
                    .editor_fields(stage, o.play.correction.value as u8)
                    .contains(&focus)
                {
                    o.toggle_modify();
                }
            }
        }
        if !matches!(self.screen, Screen::Editor(_)) && focus != 10 {
            o.tracker.modify = false;
        }
        true
    }
    /// Foreground commits the old output editor before opening a different
    /// output. Only then can subsequent encoder input change its fields.
    pub fn open_pending(&mut self, o: &mut Opts) -> Option<Stage> {
        let (stage, _) = self.pending.take()?;
        self.screen = Screen::Editor(stage);
        if stage == Stage::Midi {
            self.midi_from_configs = false;
            o.tracker.page.value = Page::RouteMidi;
        }
        o.tracker.selected = Some(Self::fields(stage)[0]);
        o.tracker.modify = false;
        Some(stage)
    }
}
