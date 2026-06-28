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
/// Gap between the border stroke and the vertical separator.
const SEP_GAP: i32 = 4;
/// ``FONT_9X15`` baseline offset — top glyph row sits ``baseline`` px above the draw Y.
const TEXT_BASELINE: i32 = FONT_9X15.baseline as i32;
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
    MenuRow::Opt(2, "Trig Lvl"),
    MenuRow::Opt(3, "Grid"),
    MenuRow::Opt(4, "Grid Int"),
    MenuRow::Opt(5, "Intensity"),
    MenuRow::Opt(6, "Hue"),
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
    MenuRow::Opt(3, "Debug?"),
    MenuRow::Opt(4, "Save"),
    MenuRow::Opt(5, "Reset"),
];

const HELP_ROWS: &[MenuRow] = &[
    MenuRow::Opt(0, "Scroll"),
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

fn inner_top() -> i32 {
    BORDER + 1
}

fn inner_bottom(box_h: i32) -> i32 {
    box_h - BORDER - 2
}

fn separator_y0(box_h: i32) -> i32 {
    inner_top() + SEP_GAP
}

fn separator_y1(box_h: i32) -> i32 {
    inner_bottom(box_h) - SEP_GAP
}

/// First-row baseline: top glyph row aligns with the separator top.
fn content_y0(menu_h: u32) -> i32 {
    separator_y0(menu_h as i32) + TEXT_BASELINE
}

/// Draw the scope menu with a 1px border sized to the page content.
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
    let box_h = menu_h as i32;
    let y0 = content_y0(menu_h);
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
        Line::new(
            Point::new(SEP_X, separator_y0(box_h)),
            Point::new(SEP_X, separator_y1(box_h)),
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
