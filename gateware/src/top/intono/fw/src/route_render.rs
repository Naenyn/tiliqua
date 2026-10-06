//! Foreground-only route presentation, using the native text bank and a bounded
//! sparse list of PSRAM outlines. No operation state is modified by rendering.
use super::*;
use route_ui::{Screen, Stage, DONE};
fn aligned(
    text: &mut TextWriter<'_>,
    x: u16,
    row: u8,
    width: u16,
    value: &str,
    color: u8,
    bold: bool,
    align: ui_text::Align,
) {
    let column = ((x as i32 - 120 + 6) / 12).max(0) as usize;
    ui_text::field(
        column,
        row as usize,
        (width / 12) as usize,
        value,
        ui_text::Style { color, bold },
        align,
        |a, c| text.cell(a, c),
    );
}
fn label(
    text: &mut TextWriter<'_>,
    x: u16,
    row: u8,
    width: u16,
    value: &str,
    color: u8,
    bold: bool,
) {
    aligned(
        text,
        x,
        row,
        width,
        value,
        color,
        bold,
        ui_text::Align::Center,
    );
}
fn left(
    text: &mut TextWriter<'_>,
    x: u16,
    row: u8,
    width: u16,
    value: &str,
    color: u8,
    bold: bool,
) {
    aligned(
        text,
        x,
        row,
        width,
        value,
        color,
        bold,
        ui_text::Align::Left,
    );
}
fn control(
    d: &mut ui_route::Drawing,
    text: &mut TextWriter<'_>,
    x: u16,
    row: u8,
    width: u16,
    value: &str,
    focus: bool,
    locked: bool,
    normal:u8,
) {
    debug_assert!(
        value.chars().count() <= width as usize / 12,
        "button label exceeds its bounds: {}",
        value
    );
    let filled = focus && !locked && d.editing;
    if filled {
        d.rounded_fill(x, row as u16 * 32 - 6, width, 28);
    } else if focus && !locked {
        d.outline(x, row as u16 * 32 - 6, width, 28, true);
    }
    label(
        text,
        x,
        row,
        width,
        value,
        if locked {
            0x49
        } else if filled {
            0x09
        } else if focus {
            0xF9
        } else {
            normal
        },
        focus,
    );
}
// Actions use the complementary family; editable values stay neutral white.
fn button(d:&mut ui_route::Drawing,text:&mut TextWriter<'_>,x:u16,row:u8,width:u16,value:&str,focus:bool,locked:bool) {
    control(d,text,x,row,width,value,focus,locked,0xC9);
}
fn value_button(d:&mut ui_route::Drawing,text:&mut TextWriter<'_>,x:u16,row:u8,width:u16,value:&str,focus:bool,locked:bool) {
    control(d,text,x,row,width,value,focus,locked,0xD9);
}
fn history(d: &mut ui_route::Drawing, h: &ui_route::History, out: usize, y: u16) {
    for i in 0..8 {
        if i >= 8 - h.counts[out] as usize {
            let height = h.values[out][i] as u16;
            d.add(504 + i as u16 * 8, y + 20 - height, 5, height, 0xD4, true);
        }
    }
}
#[inline(never)]
pub fn publish(text: &mut TextWriter<'_>, menu: &MenuSnapshot) -> ui_route::Drawing {
    let (channels, groups, route, output, midi, selected, editing) = with_app(|a| {
        (
            a.quant_channels,
            a.groups,
            a.route_selected as usize,
            a.quant_selected as usize,
            a.midi[if a.ui.opts.tracker.page.value == options::Page::RouteMidi {
                a.ui.opts.route_midi.route.value.min(3) as usize
            } else {
                a.route_selected as usize
            }],
            a.ui.opts.tracker.selected,
            a.ui.opts.tracker.modify,
        )
    });
    let view = critical_section::with(|cs| *ROUTE_VIEW.borrow_ref(cs));
    let h = critical_section::with(|cs| *ROUTE_HISTORY.borrow_ref(cs));
    let (active, pitches, bound, status, shift) = critical_section::with(|cs| {
        let q = MULTI_QUANT.borrow_ref(cs);
        (
            q.lanes
                .iter()
                .enumerate()
                .fold(0u8, |m, (n, l)| m | ((l.active as u8) << n)),
            core::array::from_fn::<_, 4, _>(|n| q.lanes[n].pitch),
            q.bound,
            q.lanes[output].status,
            q.shifts[route],
        )
    });
    let running = active & groups.outputs[route] != 0;
    let mut d = ui_route::Drawing::new();
    d.editing = editing && selected.is_some();
    let mut s = String::<64>::new();
    if with_app(|a| a.ui.opts.tracker.page.value) == options::Page::Settings {
        if let Some(entry) = menu.entries[0].as_ref() {
            left(text, 216, 6, 144, "A4 REF", 0x69, false);
            value_button(
                &mut d,
                text,
                360,
                6,
                144,
                &entry.value,
                selected == Some(0),
                false,
            );
        }
        button(
            &mut d,
            text,
            216,
            10,
            288,
            "SAVE PREFERENCES",
            selected == Some(1),
            false,
        );
        button(
            &mut d,
            text,
            216,
            12,
            288,
            "RESET PREFERENCES",
            selected == Some(2),
            false,
        );
        label(text, 144, 14, 432, "PALETTE / A4 / TUNER / CALIBRATION", 0x69, false);
        label(
            text,
            144,
            15,
            432,
            "PROFILES / SCALES / CONFIGS KEPT",
            0x69,
            false,
        );
        if let Some(entry)=menu.entries[3].as_ref() {
            left(text,216,8,144,"PALETTE",0x69,false);
            value_button(&mut d,text,360,8,144,&entry.value,selected==Some(3),false);
        }
        return d;
    }
    if with_app(|a| a.ui.opts.tracker.page.value) == options::Page::QuantSetups {
        label(text, 168, 4, 384, "CONFIGS", 0xF9, true);
        if let Some(entry) = menu.entries[0].as_ref() {
            left(text, 240, 5, 144, "CONFIG SLOT", 0x69, false);
            value_button(
                &mut d,
                text,
                384,
                5,
                96,
                &entry.value,
                selected == Some(0),
                false,
            );
        }
        label(text,120,6,480,&config_slot_name(),0xD9,false);
        label(text, 120, 7, 480, "CURRENT ROUTE ASSIGNMENTS", 0x69, false);
        for route in 0..4 {
            s.clear();
            ui_route::write_assignment(&mut s, groups, route);
            left(text, 120, 8 + route * 2, 480, &s, 0xD9, false);
        }
        button(
            &mut d,
            text,
            192,
            16,
            156,
            "SAVE CONFIG",
            selected == Some(1),
            false,
        );
        button(
            &mut d,
            text,
            372,
            16,
            156,
            "LOAD CONFIG",
            selected == Some(2),
            false,
        );
        button(
            &mut d,
            text,
            252,
            17,
            216,
            "MIDI TRANSPOSE",
            selected == Some(3),
            false,
        );
        let slot = with_app(|a| a.ui.opts.quant_setups.slot.value);
        let (status_slot, status) = critical_section::with(|cs| *SETUP_STATUS.borrow_ref(cs));
        label(
            text,
            168,
            18,
            384,
            if status_slot == slot { status } else { "" },
            0x69,
            false,
        );
        button(
            &mut d,
            text,
            288,
            19,
            144,
            "BACK",
            selected == Some(4),
            false,
        );
        return d;
    }
    if view.screen == Screen::Editor(Stage::Midi) && view.midi_from_configs {
        let route = with_app(|a| a.ui.opts.route_midi.route.value.min(3) as usize);
        let (shift, learning) = critical_section::with(|cs| {
            let q = MULTI_QUANT.borrow_ref(cs);
            (
                q.shifts[route],
                q.midi_base_learn.route == Some(route as u8),
            )
        });
        label(text, 168, 4, 384, "MIDI TRANSPOSE", 0xC9, true);
        label(
            text,
            144,
            6,
            432,
            "CHOOSE A ROUTE TO CONFIGURE",
            0x69,
            false,
        );
        for (index, row, name, action) in [
            (0, 7, "ROUTE", false),
            (1, 8, "CHANNEL", false),
            (2, 9, "BASE NOTE", false),
            (
                5,
                10,
                if learning {
                    "CANCEL LEARN"
                } else {
                    "LEARN BASE NOTE"
                },
                true,
            ),
            (4, 11, "RELEASE", false),
            (3, 12, "RESET TRANSPOSE", true),
            (6, 18, "BACK", true),
        ] {
            let Some(entry) = menu.entries.get(index).and_then(|e| e.as_ref()) else {
                continue;
            };
            let locked = index == 5 && midi.channel == 0;
            if action {
                button(
                    &mut d,
                    text,
                    192,
                    row,
                    336,
                    name,
                    selected == Some(index),
                    locked,
                );
            } else {
                left(text, 192, row, 120, name, 0x69, false);
                value_button(
                    &mut d,
                    text,
                    312,
                    row,
                    216,
                    &entry.value,
                    selected == Some(index),
                    locked,
                );
            }
        }
        write!(s, "ROUTE {} TRANSPOSE: {:+} ST", route + 1, shift).ok();
        label(text, 144, 14, 432, &s, 0xD9, false);
        label(
            text,
            144,
            15,
            432,
            if learning {
                "PLAY NOTE ON SELECTED CHANNEL"
            } else {
                "APPLIES TO ALL ROUTE OUTPUTS"
            },
            0x69,
            false,
        );
        label(text, 168, 16, 384, "SAVED WITH CONFIG", 0x69, false);
        return d;
    }
    match view.screen {
        Screen::Warning => {
            d.outline(156, 218, 408, 306, true);
            label(text, 168, 7, 384, "CAN'T LOAD CONFIG", 0xF9, true);
            if let Some(w) = view.warning {
                match w.kind {
                    route_ui::WarningKind::Running(n) => {
                        s.clear();
                        write!(s, "ROUTE {} IS RUNNING", n + 1).ok();
                        label(text, 168, 9, 384, &s, 0xD9, false);
                        label(text, 168, 11, 384, "STOP IT BEFORE LOADING", 0x69, false);
                        s.clear();
                        write!(s, "GO TO ROUTE {}", n + 1).ok();
                        button(&mut d, text, 180, 14, 216, &s, w.go, false);
                        button(&mut d, text, 408, 14, 132, "CANCEL", !w.go, false);
                    }
                    route_ui::WarningKind::Calibration => {
                        label(text, 168, 9, 384, "CALIBRATION IS RUNNING", 0xD9, false);
                        label(text, 168, 11, 384, "STOP SCAN BEFORE LOADING", 0x69, false);
                        button(&mut d, text, 288, 14, 144, "CANCEL", true, false);
                    }
                    route_ui::WarningKind::SavedConflict(output, jack, a, b) => {
                        s.clear();
                        write!(
                            s,
                            "{} {} ASSIGNED TWICE",
                            if output { "OUTPUT" } else { "INPUT" },
                            jack
                        )
                        .ok();
                        label(text, 168, 9, 384, &s, 0xD9, false);
                        s.clear();
                        write!(s, "SAVED ROUTES {} AND {}", a + 1, b + 1).ok();
                        label(text, 168, 11, 384, &s, 0x69, false);
                        button(&mut d, text, 288, 14, 144, "CANCEL", true, false);
                    }
                    route_ui::WarningKind::InvalidSetup => {
                        label(text, 168, 9, 384, "SAVED CONFIG IS INVALID", 0xD9, false);
                        label(text, 168, 11, 384, "CHECK JACK ASSIGNMENTS", 0x69, false);
                        button(&mut d, text, 288, 14, 144, "CANCEL", true, false);
                    }
                }
                label(text, 168, 15, 384, "CURRENT CONFIG KEPT", 0x69, false);
            }
            return d;
        }
        Screen::Overview => {
            let mut row = 5;
            for n in 0..4 {
                let mask = groups.outputs[n];
                let expanded = n == route;
                let focused = selected == Some(n);
                let rows = 1 + if expanded {
                    2 * mask.count_ones() as u8
                } else {
                    0
                };
                d.outline(144, row as u16 * 32 - 6, 432, rows as u16 * 32 - 4, focused);
                s.clear();
                write!(s, "ROUTE {}", n + 1).ok();
                left(
                    text,
                    156,
                    row,
                    108,
                    &s,
                    if focused { 0xF9 } else { 0xD9 },
                    focused,
                );
                s.clear();
                if mask != 0 {
                    write!(s, "IN{} >", groups.inputs[n]).ok();
                    for out in 0..4 {
                        if mask & (1 << out) != 0 {
                            write!(s, " {}", out).ok();
                        }
                    }
                } else {
                    s.push_str("NOT ASSIGNED").ok();
                }
                left(text, 288, row, 204, &s, 0x69, false);
                label(
                    text,
                    492,
                    row,
                    72,
                    if mask == 0 {
                        "FREE"
                    } else if active & mask != 0 {
                        "RUN"
                    } else {
                        "STOP"
                    },
                    if active & mask != 0 { 0xD4 } else { 0x69 },
                    false,
                );
                if expanded {
                    d.add(156, row as u16 * 32 + 23, 408, 1, 0x49, true);
                    let mut r = row + 1;
                    for out in 0..4 {
                        if mask & (1 << out) != 0 {
                            let c = channels[out];
                            s.clear();
                            write!(s, "OUT{}", out).ok();
                            d.outline(156, r as u16 * 32 - 3, 60, 26, false);
                            label(text, 156, r, 60, &s, 0xD9, true);
                            s.clear();
                            if !c.quantize {
                                s.push_str("BYPASS").ok();
                            } else {
                                if c.scale_slot != 0 {
                                    write_saved_scale(&mut s,out as usize,c.scale_slot);
                                } else {
                                    s.push_str(scale_label(c.scale)).ok();
                                }
                                write!(
                                    s,
                                    " / {} / {}",
                                    NOTE_NAMES[c.root as usize],
                                    if c.equal { "EQUAL" } else { "NEAREST" }
                                )
                                .ok();
                            }
                            left(text, 240, r, 324, &s, 0xD9, false);
                            s.clear();
                            write_profile_source(&mut s, c.correction);
                            write!(s, " / {:+} ST", c.transpose).ok();
                            left(text, 240, r + 1, 252, &s, 0x69, false);
                            if active & (1 << out) != 0 {
                                history(&mut d, &h, out, (r + 1) as u16 * 32);
                            }
                            r += 2;
                        }
                    }
                }
                row += rows;
            }
            if row <= 16 {
                s.clear();
                if midi.channel == 0 {
                    s.push_str("MIDI TRANSPOSE OFF").ok();
                } else {
                    write!(s, "MIDI CH{} / {:+}st", midi.channel, shift).ok();
                }
                label(text, 168, 17, 384, &s, 0x69, false);
            }
            button(
                &mut d,
                text,
                228,
                18,
                108,
                if running { "STOP" } else { "START" },
                selected == Some(4),
                groups.outputs[route] == 0,
            );
            button(
                &mut d,
                text,
                384,
                18,
                108,
                "CONFIGS",
                selected == Some(6),
                false,
            );
        }
        Screen::Flow => {
            s.clear();
            write!(
                s,
                "ROUTE {} / {}",
                route + 1,
                if running { "RUNNING" } else { "STOPPED" }
            )
            .ok();
            label(text, 192, 4, 336, &s, 0xD9, false);
            if groups.outputs[route] == 0 {
                let claims = critical_section::with(|cs| *OWNERS.borrow_ref(cs));
                let available = groups.available(route as u8, true, &claims) != 0
                    && groups.available(route as u8, false, &claims) != 0;
                button(
                    &mut d,
                    text,
                    252,
                    11,
                    216,
                    "ADD OUTPUT",
                    selected == Some(11),
                    !available,
                );
                if !available {
                    label(text, 192, 13, 336, "NO FREE INPUT / OUTPUT", 0x69, false);
                }
                button(
                    &mut d,
                    text,
                    228,
                    18,
                    132,
                    "BACK",
                    selected == Some(13),
                    false,
                );
                button(
                    &mut d,
                    text,
                    384,
                    18,
                    108,
                    "CONFIGS",
                    selected == Some(14),
                    false,
                );
                return d;
            }
            for (node, x, title) in [(0, 168, "CV INPUT"), (1, 384, "MIDI TRANSPOSE")] {
                d.outline(x, 154, 168, 60, selected == Some(node));
                label(text, x, 5, 168, title, if node==1 {0xB9}else{0x69}, false);
                s.clear();
                if node == 0 {
                    write!(s, "IN{}", groups.inputs[route]).ok();
                } else if midi.channel == 0 {
                    s.push_str("OFF").ok();
                } else {
                    write!(s, "CH{} {:+}st", midi.channel, shift).ok();
                }
                label(text, x, 6, 168, &s, if node==1 {0xC9}else{0xD9}, false);
            }
            let outs = view.outputs(route as u8);
            // Musical processing and oscillator/output setup are grouped.
            // A single branch uses the center of the available diagram area.
            let first_row = if outs[1].is_some() { 8 } else { 10 };
            if outs[0].is_some() {
                let last_row = if outs[1].is_some() { 13 } else { first_row };
                d.add(132, 232, 120, 1, 0x49, true);
                d.add(252, 214, 1, 19, 0x49, true);
                d.add(132, 232, 1, last_row as u16 * 32 + 56 - 232, 0x49, true);
                d.add(468, 214, 1, 19, 0x49, true);
                d.add(258, 232, 211, 1, 0x49, true);
                // MIDI has its own port at the top of the pitch group.
                for y in (234..first_row as u16 * 32 - 6).step_by(10) {
                    d.add(258, y, 1, 5, 0x49, true);
                }
                if outs[1].is_some() {
                    for y in (376..410).step_by(10) {
                        d.add(258, y, 1, 5, 0x49, true);
                    }
                }
            }
            for (lane, out) in outs.iter().enumerate() {
                let Some(out) = out else { continue };
                let out = *out as usize;
                let c = channels[out];
                let row = first_row + lane as u8 * 5;
                let center = row as u16 * 32 + 56;
                d.add(132, center, 24, 1, 0x49, true);
                d.outline(
                    156,
                    row as u16 * 32 - 6,
                    204,
                    124,
                    selected == Some(2 + lane * 4),
                );
                d.outline(
                    408,
                    row as u16 * 32 - 6,
                    168,
                    124,
                    selected == Some(4 + lane * 4),
                );
                d.add(360, center, 48, 1, 0x49, true);
                for dx in 0..3 {
                    d.add(393 + dx, center - 2 + dx, 1, 5 - dx * 2, 0x69, true);
                }
                label(text, 168, row, 180, "PITCH", 0x69, false);
                s.clear();
                if !c.quantize {
                    s.push_str("BYPASS").ok();
                } else if c.scale_slot != 0 {
                    write_saved_scale(&mut s,out as usize,c.scale_slot);
                } else {
                    s.push_str(scale_label(c.scale)).ok();
                }
                label(text, 168, row + 1, 180, &s, 0xD9, false);
                s.clear();
                write!(
                    s,
                    "{} / {}",
                    NOTE_NAMES[c.root as usize],
                    if c.equal { "EQUAL" } else { "NEAREST" }
                )
                .ok();
                label(text, 168, row + 2, 180, &s, 0x69, false);
                s.clear();
                write!(s, "{:+}ST MIDI{:+}", c.transpose, shift).ok();
                label(text, 168, row + 3, 180, &s, 0x69, false);
                s.clear();
                write!(s, "OUTPUT {}", out).ok();
                label(text, 420, row, 144, &s, 0x69, false);
                s.clear();
                write_profile_source(&mut s, c.correction);
                label(text, 420, row + 1, 144, &s, 0xD9, false);
                s.clear();
                if c.correction != 0 && c.correction != bound[out] {
                    s.push_str("APPLY!").ok();
                } else {
                    s.push_str("0V ").ok();
                    pitch_units::write_note(&mut s, c.zero as i32).ok();
                }
                label(text, 420, row + 2, 144, &s, 0x69, false);
                s.clear();
                if active & (1 << out) != 0 {
                    pitch_units::write_note(&mut s, pitches[out].div_euclid(100_000)).ok();
                } else {
                    s.push_str("STOPPED").ok();
                }
                label(
                    text,
                    420,
                    row + 3,
                    144,
                    &s,
                    if active & (1 << out) != 0 { 0xD4 } else { 0x69 },
                    false,
                );
            }
            if outs[0].is_none() {
                label(text, 192, 10, 336, "ADD AN OUTPUT TO BEGIN", 0x69, false);
            }
            if groups.outputs[route].count_ones() > 2 {
                s.clear();
                write!(
                    s,
                    "VIEW: {}-{}",
                    view.window * 2 + 1,
                    (view.window * 2 + 2).min(groups.outputs[route].count_ones() as u8)
                )
                .ok();
                button(&mut d, text, 168, 17, 216, &s, selected == Some(10), false);
            }
            button(
                &mut d,
                text,
                408,
                17,
                144,
                "ADD OUTPUT",
                selected == Some(11),
                running
                    || groups.available(
                        route as u8,
                        true,
                        &critical_section::with(|cs| *OWNERS.borrow_ref(cs)),
                    ) & !groups.outputs[route]
                        == 0,
            );
            button(
                &mut d,
                text,
                180,
                18,
                96,
                if running { "STOP" } else { "START" },
                selected == Some(12),
                groups.outputs[route] == 0,
            );
            button(
                &mut d,
                text,
                288,
                18,
                132,
                "BACK",
                selected == Some(13),
                false,
            );
            button(
                &mut d,
                text,
                432,
                18,
                108,
                "CONFIGS",
                selected == Some(14),
                false,
            );
        }
        Screen::Editor(stage) => {
            d.outline(168, 218, 384, 332, true);
            d.add(192, 246, 336, 1, 0x49, true);
            s.clear();
            if matches!(stage, Stage::Input | Stage::Midi) {
                write!(s, "ROUTE {} / ", route + 1).ok();
            } else {
                write!(s, "OUT{} / ", output).ok();
            }
            s.push_str(match stage {
                Stage::Input => "INPUT",
                Stage::Midi => "MIDI",
                Stage::Scale => "PITCH",
                Stage::Add => "ADD OUTPUT",
                Stage::Destination => "OUTPUT / PROFILE",
            })
            .ok();
            label(text, 180, 7, 360, &s, 0xF9, true);
            let fields = route_ui::View::fields_for(stage, channels[output].correction);
            for (n, index) in fields.iter().copied().filter(|i| *i != DONE).enumerate() {
                let Some(entry) = menu.entries.get(index).and_then(|e| e.as_ref()) else {
                    continue;
                };
                let row = 8 + n as u8;
                let locked = (running && stage != Stage::Midi)
                    || (stage == Stage::Midi && index == 5 && midi.channel == 0);
                let label_name = match (stage, index) {
                    (Stage::Scale, 5) => "MODE",
                    (Stage::Scale, 9) => "PRESET",
                    (Stage::Scale, 10) => "KEY",
                    (Stage::Scale, 15) => "MAP",
                    (Stage::Scale, 12) => "USER SLOT",
                    (Stage::Scale, 7) => "LOAD USER SCALE",
                    (Stage::Destination, 3) => "PROFILE",
                    (Stage::Destination, 4) => {
                        if channels[output].correction == 0 {
                            "CLEAR PROFILE"
                        } else {
                            "APPLY PROFILE"
                        }
                    }
                    (Stage::Destination, 2) => "0V NOTE",
                    (Stage::Add | Stage::Destination, 13) => "OUTPUT",
                    (Stage::Add | Stage::Destination, 14) => {
                        if groups.owner(output as u8) == Some(route as u8) {
                            "REMOVE OUTPUT"
                        } else {
                            "ADD OUTPUT"
                        }
                    }
                    (Stage::Midi, 1) => "CHANNEL",
                    (Stage::Midi, 2) => "BASE NOTE",
                    (Stage::Midi, 4) => "RELEASE",
                    (Stage::Midi, 3) => "RESET TRANSPOSE",
                    (Stage::Midi, 5) => {
                        if critical_section::with(|cs| {
                            MULTI_QUANT.borrow_ref(cs).midi_base_learn.route
                        }) == Some(route as u8)
                        {
                            "CANCEL LEARN"
                        } else {
                            "LEARN BASE NOTE"
                        }
                    }
                    (Stage::Input, 1) => "INPUT",
                    _ => "TRANSPOSE",
                };
                let action = matches!(
                    (stage, index),
                    (Stage::Scale, 7)
                        | (Stage::Destination, 4)
                        | (Stage::Add | Stage::Destination, 14)
                        | (Stage::Midi, 3 | 5)
                );
                if action {
                    button(
                        &mut d,
                        text,
                        192,
                        row,
                        336,
                        label_name,
                        selected == Some(index),
                        locked,
                    );
                } else {
                    left(text, 192, row, 120, label_name, 0x69, false);
                    value_button(
                        &mut d,
                        text,
                        312,
                        row,
                        216,
                        &entry.value,
                        selected == Some(index),
                        locked,
                    );
                }
            }
            if matches!(stage, Stage::Input | Stage::Add | Stage::Destination) {
                let claims = critical_section::with(|cs| *OWNERS.borrow_ref(cs));
                let output_jack = stage != Stage::Input;
                let free = groups.available(route as u8, output_jack, &claims);
                let own = if output_jack {
                    groups.outputs[route]
                } else if groups.outputs[route] != 0 {
                    1 << groups.inputs[route]
                } else {
                    0
                };
                for n in 0..4 {
                    s.clear();
                    write!(s, "{}{}", if own & (1 << n) != 0 { "*" } else { " " }, n).ok();
                    label(
                        text,
                        240 + n * 48,
                        if stage == Stage::Destination { 13 } else { 12 },
                        48,
                        &s,
                        if free & (1 << n) != 0 { 0xD9 } else { 0x49 },
                        own & (1 << n) != 0,
                    );
                }
            }
            let jacks = matches!(stage, Stage::Input | Stage::Add | Stage::Destination);
            if jacks {
                label(text, 192, 14, 336, "* ASSIGNED TO THIS ROUTE", 0x69, false);
                label(text, 192, 15, 336, "DIM = ASSIGNED", 0x69, false);
            } else if running && stage != Stage::Midi {
                label(text, 192, 15, 336, "STOP ROUTE TO EDIT", 0x69, false);
            } else if stage == Stage::Midi {
                s.clear();
                write!(s, "TRANSPOSE: {:+} ST", shift).ok();
                label(text, 192, 14, 336, &s, 0xD9, false);
                label(
                    text,
                    192,
                    15,
                    336,
                    if critical_section::with(|cs| MULTI_QUANT.borrow_ref(cs).midi_base_learn.route)
                        == Some(route as u8)
                    {
                        "PLAY NOTE ON SELECTED CHANNEL"
                    } else {
                        "SHARED BY ALL OUTPUTS"
                    },
                    0x69,
                    false,
                );
            }
            button(
                &mut d,
                text,
                288,
                16,
                144,
                "DONE",
                selected == Some(DONE),
                false,
            );
        }
    }
    // Preserve failures and profile/load feedback rather than hiding them in
    // the new diagram. Routine status occupies the navigation hint instead.
    let message = ui_route::route_status_message(status, groups.outputs[route]);
    label(
        text,
        156,
        19,
        408,
        message.unwrap_or(if editing {
            "TURN TO EDIT / CLICK TO FINISH"
        } else {
            "TURN TO SELECT / CLICK TO OPEN"
        }),
        0x69,
        false,
    );
    d
}

/// Centered tuning-reference panel; operation state is supplied by the adapter.
#[inline(never)]
pub fn reference(
    text: &mut TextWriter<'_>,
    menu: &MenuSnapshot,
    selected: Option<usize>,
    editing: bool,
    reference: reference_cv::Reference,
) -> ui_route::Drawing {
    let mut d = ui_route::Drawing::new();
    d.editing = editing;
    d.outline(144, 186, 432, 418, true);
    label(text, 168, 6, 384, "REFERENCE CV", 0xF9, true);
    for (index, name, row) in [(0, "OUTPUT", 8), (1, "VOLTAGE", 10), (2, "STEP", 12)] {
        if let Some(entry) = menu.entries[index].as_ref() {
            left(text, 168, row, 132, name, 0x69, false);
            value_button(
                &mut d,
                text,
                312,
                row,
                240,
                &entry.value,
                selected == Some(index),
                index == 0 && reference.phase != 0,
            );
        }
    }
    button(
        &mut d,
        text,
        168,
        14,
        180,
        if reference.enabled() {
            "DISABLE"
        } else {
            "ENABLE"
        },
        selected == Some(3),
        reference.phase == 3 || reference.free == 0,
    );
    button(
        &mut d,
        text,
        372,
        14,
        180,
        "BACK",
        selected == Some(4),
        false,
    );
    label(text, 168, 16, 384, reference.status, 0xD9, false);
    for output in 0..4 {
        let mut number = String::<8>::new();
        write!(&mut number, "OUT{}", output).ok();
        label(
            text,
            168 + output * 96,
            17,
            96,
            &number,
            if reference.free & (1 << output) != 0 {
                0xD9
            } else {
                0x49
            },
            false,
        );
    }
    label(text, 168, 18, 384, "DIM = ASSIGNED", 0x69, false);
    d
}
