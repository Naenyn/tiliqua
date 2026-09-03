use opts::Options;
use tiliqua_hal::embedded_graphics::{
    mono_font::{ascii::FONT_9X15, ascii::FONT_9X15_BOLD, MonoTextStyle},
    prelude::*,
    primitives::{Line, PrimitiveStyleBuilder, Rectangle},
    text::{Alignment, Text},
};
use tiliqua_lib::color::HI8;

use crate::options::{Opts, Page, ViewMode};

const VSPACE: i32 = 18;
const BORDER: i32 = 1;
/// Match the shared Tiliqua menu geometry used by SONORO and XBEAM.
const CONTENT_Y0: i32 = 18;
// Balance the title gutter and option columns within the fixed 250px bitmap.
// This leaves room for the seven-character DISPLAY title without wasting the
// former wide margin to the right of option values.
const SEP_X: i32 = 79;
const PAGE_X: i32 = 72;
const ITEM_X: i32 = 87;
const VALUE_X: i32 = 232;
const MARKER_X: i32 = 234;

enum MenuRow {
    Header(&'static str),
    Opt(usize, &'static str),
    Spacer,
}

const CHAN12_ROWS: &[MenuRow] = &[
    MenuRow::Header("Channel 1"),
    MenuRow::Opt(0, "offset"),
    MenuRow::Opt(1, "scale"),
    MenuRow::Opt(2, "enabled"),
    MenuRow::Spacer,
    MenuRow::Header("Channel 2"),
    MenuRow::Opt(3, "offset"),
    MenuRow::Opt(4, "scale"),
    MenuRow::Opt(5, "enabled"),
];

const CHAN34_ROWS: &[MenuRow] = &[
    MenuRow::Header("Channel 3"),
    MenuRow::Opt(0, "offset"),
    MenuRow::Opt(1, "scale"),
    MenuRow::Opt(2, "enabled"),
    MenuRow::Spacer,
    MenuRow::Header("Channel 4"),
    MenuRow::Opt(3, "offset"),
    MenuRow::Opt(4, "scale"),
    MenuRow::Opt(5, "enabled"),
];

const SCOPE_HOME_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "mode"),
    MenuRow::Opt(1, "time/div"),
    MenuRow::Opt(2, "acquire"),
];

const MONITOR_HOME_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "mode"),
    MenuRow::Opt(3, "time/div"),
    MenuRow::Opt(4, "max freq"),
];

const MONITOR_CIRCULAR_HOME_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "mode"),
    MenuRow::Opt(3, "time/div"),
    MenuRow::Opt(4, "max freq"),
    MenuRow::Opt(5, "channels"),
];

const SCOPE_ROWS: &[MenuRow] = &[
    MenuRow::Header("Trigger"),
    MenuRow::Opt(0, "type"),
    MenuRow::Opt(1, "source"),
    MenuRow::Opt(2, "level"),
    MenuRow::Opt(3, "filter"),
];

const MONITOR_ROWS: &[MenuRow] = &[
    MenuRow::Header("Ranges"),
    MenuRow::Opt(0, "CH1"),
    MenuRow::Opt(1, "CH2"),
    MenuRow::Opt(2, "CH3"),
    MenuRow::Opt(3, "CH4"),
];

const DISPLAY_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "grid"),
    MenuRow::Opt(1, "grid int"),
    MenuRow::Opt(2, "intensity"),
    MenuRow::Opt(3, "hue"),
    MenuRow::Opt(4, "palette"),
];

const MONITOR_DISPLAY_ROWS: &[MenuRow] = &[
    MenuRow::Opt(2, "intensity"),
    MenuRow::Opt(3, "hue"),
    MenuRow::Opt(4, "palette"),
];

const SYSTEM_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "ui hue"),
    MenuRow::Opt(1, "hide ui"),
    MenuRow::Opt(2, "edit hide"),
    MenuRow::Opt(3, "rotation"),
    MenuRow::Opt(4, "save"),
    MenuRow::Opt(5, "reset"),
];

const HELP_ROWS: &[MenuRow] = &[MenuRow::Opt(0, "scroll")];

fn rows_for_page(page: Page, mode: ViewMode, circular_display: bool) -> &'static [MenuRow] {
    match page {
        Page::Mode => match (mode, circular_display) {
            (ViewMode::Scope, _) => SCOPE_HOME_ROWS,
            (ViewMode::Monitor, false) => MONITOR_HOME_ROWS,
            (ViewMode::Monitor, true) => MONITOR_CIRCULAR_HOME_ROWS,
        },
        Page::Chan12 => CHAN12_ROWS,
        Page::Chan34 => CHAN34_ROWS,
        Page::Scope => SCOPE_ROWS,
        Page::Monitor => MONITOR_ROWS,
        Page::Display => match mode {
            ViewMode::Scope => DISPLAY_ROWS,
            ViewMode::Monitor => MONITOR_DISPLAY_ROWS,
        },
        Page::System => SYSTEM_ROWS,
        Page::Help => HELP_ROWS,
    }
}

fn row_spacing(page: Page) -> i32 {
    match page {
        // Nine rows, including the visual group separator, fit the fixed
        // 160px hardware overlay at this pitch.
        Page::Chan12 | Page::Chan34 => 16,
        _ => VSPACE,
    }
}

/// Draw the scope menu with an opaque bordered panel and a row-sized separator.
pub fn draw_scope_menu<D>(
    d: &mut D,
    opts: &Opts,
    page: Page,
    circular_display: bool,
    hue: u8,
    menu_w: u32,
    menu_h: u32,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    let font_white = MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(hue, 15));
    let font_grey = MonoTextStyle::new(&FONT_9X15, HI8::new(hue, 10));
    let font_header = MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(hue, 12));

    let stroke = PrimitiveStyleBuilder::new()
        .stroke_color(HI8::new(hue, 10))
        .stroke_width(1)
        .build();

    let rows = rows_for_page(page, opts.mode.view.value, circular_display);
    let row_spacing = row_spacing(page);
    let y0 = CONTENT_Y0;
    let page_hl = matches!((opts.selected(), opts.modify()), (None, _));
    let opts_view = opts.view().options();

    if page != Page::Help {
        Rectangle::new(
            Point::new(BORDER, BORDER),
            Size::new(menu_w - (BORDER * 2) as u32, menu_h - (BORDER * 2) as u32),
        )
        .into_styled(stroke)
        .draw(d)?;
    }

    if !rows.is_empty() {
        // Match draw_options(): the separator begins just above the first
        // baseline and ends at the last visible row instead of spanning the
        // fixed-size backing bitmap.
        Line::new(
            Point::new(SEP_X, y0 - 10),
            Point::new(SEP_X, y0 - 13 + row_spacing * rows.len() as i32),
        )
        .into_styled(stroke)
        .draw(d)?;
    }

    Text::with_alignment(
        &opts.page().value(),
        Point::new(PAGE_X, y0),
        if page_hl { font_white } else { font_grey },
        Alignment::Right,
    )
    .draw(d)?;

    if page_hl && opts.modify() {
        Text::with_alignment(
            "^",
            Point::new(PAGE_X, y0 + row_spacing),
            font_white,
            Alignment::Right,
        )
        .draw(d)?;
    }

    let mut row_y = y0;
    for row in rows {
        match row {
            MenuRow::Spacer => {
                row_y += row_spacing;
            }
            MenuRow::Header(label) => {
                Text::with_alignment(
                    *label,
                    Point::new(ITEM_X, row_y),
                    font_header,
                    Alignment::Left,
                )
                .draw(d)?;
                row_y += row_spacing;
            }
            MenuRow::Opt(idx, label) => {
                let mut font = font_grey;
                let mut show_marker = false;
                if let Some(n_selected) = opts.selected() {
                    if n_selected == *idx {
                        font = font_white;
                        show_marker = opts.modify();
                    }
                }
                Text::with_alignment(*label, Point::new(ITEM_X, row_y), font, Alignment::Left)
                    .draw(d)?;
                Text::with_alignment(
                    &opts_view[*idx].value(),
                    Point::new(VALUE_X, row_y),
                    font,
                    Alignment::Right,
                )
                .draw(d)?;
                if show_marker {
                    Text::with_alignment("<", Point::new(MARKER_X, row_y), font, Alignment::Left)
                        .draw(d)?;
                }
                row_y += row_spacing;
            }
        }
    }

    Ok(())
}
