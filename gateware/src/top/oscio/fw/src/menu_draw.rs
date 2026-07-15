use tiliqua_hal::embedded_graphics::{
    mono_font::{ascii::FONT_9X15, ascii::FONT_9X15_BOLD, MonoTextStyle},
    primitives::{Line, PrimitiveStyleBuilder, Rectangle},
    text::{Alignment, Text},
    prelude::*,
};
use tiliqua_lib::color::HI8;
use opts::Options;

use crate::options::Page;

const VSPACE: i32 = 15;
const BORDER: i32 = 1;
/// Align the first row with XBEAM/SPECTO's menu baseline at screen center.
const CONTENT_Y0: i32 = 18;
/// Left column wide enough for the longest page title (``CH 1-2``).
const GUTTER_W: i32 = 64;
const SEP_X: i32 = GUTTER_W - 3;
const PAGE_X: i32 = GUTTER_W - 6;
const ITEM_X: i32 = GUTTER_W + 5;
const RIGHT_MARGIN: i32 = 8;
const MARKER_GAP: i32 = 72;

enum MenuRow {
    Header(&'static str),
    Opt(usize, &'static str),
    Spacer,
}

const CHAN12_ROWS: &[MenuRow] = &[
    MenuRow::Header("Channel 1"),
    MenuRow::Opt(0, "Offset"),
    MenuRow::Opt(1, "Scale"),
    MenuRow::Opt(2, "Enabled"),
    MenuRow::Spacer,
    MenuRow::Header("Channel 2"),
    MenuRow::Opt(3, "Offset"),
    MenuRow::Opt(4, "Scale"),
    MenuRow::Opt(5, "Enabled"),
];

const CHAN34_ROWS: &[MenuRow] = &[
    MenuRow::Header("Channel 3"),
    MenuRow::Opt(0, "Offset"),
    MenuRow::Opt(1, "Scale"),
    MenuRow::Opt(2, "Enabled"),
    MenuRow::Spacer,
    MenuRow::Header("Channel 4"),
    MenuRow::Opt(3, "Offset"),
    MenuRow::Opt(4, "Scale"),
    MenuRow::Opt(5, "Enabled"),
];

const SCOPE_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "Timebase"),
    MenuRow::Opt(1, "Trigger"),
    MenuRow::Opt(2, "Trigger CH"),
    MenuRow::Opt(3, "Trig Lvl"),
    MenuRow::Opt(4, "Grid"),
    MenuRow::Opt(5, "Grid Int"),
    MenuRow::Opt(6, "Intensity"),
    MenuRow::Opt(7, "Hue"),
];

const MENU_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "UI Hue"),
    MenuRow::Opt(1, "Palette"),
    MenuRow::Opt(2, "Hide UI"),
];

const MISC_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "Rotation"),
    MenuRow::Opt(1, "Help"),
    MenuRow::Opt(2, "CC Highlt"),
    MenuRow::Opt(3, "Save"),
    MenuRow::Opt(4, "Reset"),
];

const HELP_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "Scroll"),
    MenuRow::Opt(1, "Back"),
];

fn rows_for_page(page: Page) -> &'static [MenuRow] {
    match page {
        Page::Chan12 => CHAN12_ROWS,
        Page::Chan34 => CHAN34_ROWS,
        Page::Scope => SCOPE_ROWS,
        Page::Menu => MENU_ROWS,
        Page::Misc => MISC_ROWS,
        Page::Help => HELP_ROWS,
    }
}

/// Draw the scope menu with an opaque bordered panel and a row-sized separator.
pub fn draw_scope_menu<D, O>(
    d: &mut D,
    opts: &O,
    page: Page,
    hue: u8,
    menu_w: u32,
    menu_h: u32,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
    O: Options,
{
    let font_white = MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(hue, 15));
    let font_grey = MonoTextStyle::new(&FONT_9X15, HI8::new(hue, 10));
    let font_header = MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(hue, 12));

    let stroke = PrimitiveStyleBuilder::new()
        .stroke_color(HI8::new(hue, 10))
        .stroke_width(1)
        .build();

    let rows = rows_for_page(page);
    let y0 = CONTENT_Y0;
    let value_x = menu_w as i32 - RIGHT_MARGIN;
    let marker_x = value_x - MARKER_GAP;
    let page_hl = matches!((opts.selected(), opts.modify()), (None, _));
    let opts_view = opts.view().options();

    Rectangle::new(
        Point::new(BORDER, BORDER),
        Size::new(menu_w - (BORDER * 2) as u32, menu_h - (BORDER * 2) as u32),
    )
    .into_styled(stroke)
    .draw(d)?;

    if !rows.is_empty() {
        // Match draw_options(): the separator begins just above the first
        // baseline and ends at the last visible row instead of spanning the
        // fixed-size backing bitmap.
        Line::new(
            Point::new(SEP_X, y0 - 10),
            Point::new(SEP_X, y0 - 13 + VSPACE * rows.len() as i32),
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
        Text::with_alignment("^", Point::new(PAGE_X, y0 + VSPACE), font_white, Alignment::Right)
            .draw(d)?;
    }

    let mut row_y = y0;
    for row in rows {
        match row {
            MenuRow::Spacer => {
                row_y += VSPACE;
            }
            MenuRow::Header(label) => {
                Text::with_alignment(*label, Point::new(ITEM_X, row_y), font_header, Alignment::Left)
                    .draw(d)?;
                row_y += VSPACE;
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
                    Point::new(value_x, row_y),
                    font,
                    Alignment::Right,
                )
                .draw(d)?;
                if show_marker {
                    Text::with_alignment("<", Point::new(marker_x, row_y), font, Alignment::Left)
                        .draw(d)?;
                }
                row_y += VSPACE;
            }
        }
    }

    Ok(())
}
