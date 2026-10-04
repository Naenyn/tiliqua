//! Bounded character-cell helpers; independent of PAC registers and instruments.

pub const COLUMNS: usize = 45;
pub const ROWS: usize = 45;

/// Tracks occupied cells without retaining a second copy of every glyph.
/// One instance per hardware text bank; 256 bytes per bank on all targets.
pub struct Occupied {
    bits: [u32; (COLUMNS * ROWS + 31) / 32],
}

impl Occupied {
    pub const fn new() -> Self {
        Self {
            bits: [0; (COLUMNS * ROWS + 31) / 32],
        }
    }

    pub fn record(&mut self, address: u16, value: u32) {
        let address = address as usize;
        if address >= COLUMNS * ROWS {
            return;
        }
        let bit = 1 << (address % 32);
        if value & 127 != 0 {
            self.bits[address / 32] |= bit;
        } else {
            self.bits[address / 32] &= !bit;
        }
    }

    pub fn clear(&mut self, mut emit: impl FnMut(u16, u32)) {
        for (index, word) in self.bits.iter_mut().enumerate() {
            while *word != 0 {
                let bit = word.trailing_zeros() as usize;
                emit((index * 32 + bit) as u16, 0);
                *word &= *word - 1;
            }
        }
    }
}

#[derive(Clone, Copy)]
pub struct Style {
    pub color: u8,
    pub bold: bool,
}

pub const DEFAULT: Style = Style {
    color: 0xD9,
    bold: false,
};

#[derive(Clone, Copy)]
pub enum Align {
    Left,
    Center,
    Right,
}

// Replace a complete bounded field in one pass, including trailing blanks.
// Shorter values cannot leave stale characters in either back buffer.
pub fn field(
    column: usize,
    row: usize,
    width: usize,
    value: &str,
    style: Style,
    align: Align,
    mut emit: impl FnMut(u16, u32),
) {
    field_emit(column,row,width,value,style,align,&mut emit);
}
// One shared glyph loop avoids duplicating the renderer for each caller's
// emission closure. The bounded drawing behavior stays identical.
#[inline(never)]
fn field_emit(column:usize,row:usize,width:usize,value:&str,style:Style,align:Align,
    emit:&mut dyn FnMut(u16,u32)) {
    if column >= COLUMNS || row >= ROWS {
        return;
    }
    let width = width.min(COLUMNS - column);
    let count = value.chars().take(width).count();
    let padding = match align {
        Align::Left => 0,
        // Pixel offsets below finish centering between the character cells.
        Align::Center => (width - count) / 2,
        Align::Right => width - count,
    };
    let shift = if matches!(align, Align::Center) { center_shift(width, count) } else { 0 };
    let mut characters = value.chars().take(count);
    for offset in 0..width {
        let character = if offset >= padding && offset < padding + count {
            characters.next().unwrap_or(' ')
        } else {
            ' '
        };
        emit(
            (row * COLUMNS + column + offset) as u16,
            cell(character, style) | (shift << 16),
        );
    }
}

/// Two extra cell bits select 0, 2, or 8 pixels of horizontal offset.
/// A 9px glyph in a 12px cell has a 3px unused tail. Round its ideal
/// half-pixel center consistently, including odd numbers of spare cells.
pub const fn center_shift(width: usize, count: usize) -> u32 {
    if (width - count) % 2 == 0 { 1 } else { 2 }
}

/// Glyph/style occupy the low 16 bits; centered fields add offset bits 16..17.
pub fn cell(character: char, style: Style) -> u32 {
    let glyph = if (' '..='~').contains(&character) {
        character as u32 - 32
    } else {
        // One replacement per Unicode character, not per UTF-8 byte.
        b'?' as u32 - 32
    };
    glyph | ((style.bold as u32) << 7) | ((style.color as u32) << 8)
}

pub fn text(column: usize, row: usize, value: &str, style: Style, mut emit: impl FnMut(u16, u32)) {
    if column >= COLUMNS || row >= ROWS {
        return;
    }
    for (offset, character) in value.chars().take(COLUMNS - column).enumerate() {
        emit(
            (row * COLUMNS + column + offset) as u16,
            cell(character, style),
        );
    }
}

/// Keep the established 30-column control geometry while packing glyphs
/// into 40 native cells (12px pitch rather than 16px). Storage stays 45-wide.
pub const UX_COLUMNS: usize = 43;
pub const fn ux_column(column: usize) -> usize { (column * 4 + 1) / 3 }
pub fn ux_field(column: usize, row: usize, width: usize, value: &str,
    style: Style, align: Align, emit: impl FnMut(u16,u32)) {
    if column >= 32 || row >= 22 { return; }
    let start = ux_column(column);
    let end = ux_column((column + width).min(32));
    field(start,row,end-start,value,style,align,emit);
}
/// A label/value pair occupies exactly one row, or emits nothing if it cannot fit.
#[inline(never)]
pub fn inline_field(column:usize,row:usize,width:usize,label:&str,value:&str,
    style:Style,mut emit:impl FnMut(u16,u32)) -> bool {
    if column>=32 || row>=22 {return false;}
    let start=ux_column(column);let end=ux_column((column+width).min(32));
    let count=label.chars().count()+2+value.chars().count();
    if count>end-start {return false;}
    let padding=(end-start-count)/2;
    let shift=center_shift(end-start,count);
    let mut chars=label.chars().chain(": ".chars()).chain(value.chars());
    for offset in 0..end-start {
        let character=if offset>=padding && offset<padding+count {
            chars.next().unwrap_or(' ')
        } else {' '};
        emit((row*COLUMNS+start+offset) as u16,cell(character,style) | (shift<<16));
    }
    true
}
pub fn ux_text(column: usize, row: usize, value: &str, style: Style,
    emit: impl FnMut(u16,u32)) {
    if column >= 32 || row >= 22 { return; }
    let start=ux_column(column);
    let mut emit=emit;
    for (offset,character) in value.chars().take(UX_COLUMNS-start).enumerate() {
        emit((row*COLUMNS+start+offset) as u16,cell(character,style));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn compact_character_pitch_preserves_control_regions_and_centering() {
        let mut cells=Vec::new();
        ux_field(11,5,8,"INTONO",DEFAULT,Align::Center,|a,c|cells.push((a,c)));
        assert_eq!(cells.first().unwrap().0,5*45+15);
        assert_eq!(cells.last().unwrap().0,5*45+24);
        let ink:Vec<_>=cells.iter().filter(|(_,c)|c&127!=0).collect();
        assert_eq!(ink.first().unwrap().0,5*45+17);
        assert_eq!(ink.last().unwrap().0,5*45+22);
        assert_eq!(ux_column(32),UX_COLUMNS);
        ux_text(32,0,"X",DEFAULT,|_,_|panic!("outside viewport"));
        ux_field(29,21,99,"LONG",DEFAULT,Align::Left,|a,_|assert!(a%45<43));
    }

    #[test]
    fn centered_labels_balance_native_glyph_footprints() {
        for (column,width,label) in [(2,9,"TUNER"),(11,9,"CAL"),(20,9,"SCALES"),
            (29,9,"ROUTES"),(11,9,"OPTIONS"),(23,5,"HELP"),(5,16,"CLEAR PROFILE")] {
            let mut ink=Vec::new();
            let mut offset=0;
            field(column,3,width,label,DEFAULT,Align::Center,|a,c| {
                offset=match c>>16 {1=>2,2=>8,_=>0};
                if c&127!=0 {ink.push(a as i32%45);}
            });
            let text_center_twice=ink[0]*12+(ink.last().unwrap()*12+9)+offset*2;
            let field_center_twice=(column*24+width*12) as i32;
            assert!((text_center_twice-field_center_twice).abs()<=1,"{label}");
        }
    }

    #[test]
    fn inline_fields_keep_whole_values_on_one_row_or_emit_nothing() {
        let mut cells=Vec::new();
        assert!(inline_field(16,6,14,">TRANSPOSE","-12 st",DEFAULT,|a,c|cells.push((a,c))));
        assert!(cells.iter().all(|(a,_)|a/45==6));
        let label:String=cells.iter().map(|(_,c)|((c&127) as u8+32) as char).collect();
        assert_eq!(label.trim(),">TRANSPOSE: -12 st");
        assert!(!inline_field(4,5,10,"PROFILE","TWENTY-FOUR LETTER NAME",DEFAULT,|_,_|panic!()));
        assert!(!inline_field(30,5,10,"X","Y",DEFAULT,|_,_|panic!()));
        assert!(!inline_field(4,22,10,"X","Y",DEFAULT,|_,_|panic!()));
    }
    #[test]
    fn sparse_clear_preserves_bank_independence_and_shorter_fields() {
        assert_eq!(core::mem::size_of::<Occupied>(), 256);
        let mut banks = [Occupied::new(), Occupied::new()];
        let mut hardware = [[0u32; COLUMNS * ROWS]; 2];
        for bank in 0..2 {
            for value in ["A#1", "B1"] {
                field(20, 22, 5, value, DEFAULT, Align::Center, |a, c| {
                    banks[bank].record(a, c);
                    hardware[bank][a as usize] = c;
                });
            }
        }
        let mut writes = 0;
        banks[0].clear(|a, c| {
            hardware[0][a as usize] = c;
            writes += 1;
        });
        assert_eq!(writes, 2);
        assert!(hardware[0].iter().all(|c| c & 127 == 0));
        assert_eq!(hardware[1].iter().filter(|c| **c & 127 != 0).count(), 2);
        banks[0].clear(|_, _| panic!("already empty"));
        banks[1].clear(|a, c| hardware[1][a as usize] = c);
        assert!(hardware[1].iter().all(|c| c & 127 == 0));
    }

    #[test]
    fn sparse_clear_handles_full_plane_styles_and_invalid_addresses() {
        let mut occupied = Occupied::new();
        for a in 0..COLUMNS * ROWS {
            occupied.record(a as u16, cell('X', DEFAULT));
        }
        occupied.record(u16::MAX, 1);
        let mut count = 0;
        occupied.clear(|a, c| {
            assert_eq!(a as usize, count);
            assert_eq!(c, 0);
            count += 1;
        });
        assert_eq!(count, COLUMNS * ROWS);
        occupied.record(
            10,
            cell(
                ' ',
                Style {
                    color: 255,
                    bold: true,
                },
            ),
        );
        occupied.clear(|_, _| panic!("styled blank is still empty"));
    }

    #[test]
    fn alternating_scenes_and_banks_leave_no_previous_labels() {
        let mut occupied = [Occupied::new(), Occupied::new()];
        let mut hardware = [[0u32; COLUMNS * ROWS]; 2];
        for frame in 0..200 {
            let bank = frame % 2;
            let linear = (frame / 2) % 2 == 1;
            let mut erased = 0;
            occupied[bank].clear(|a, c| {
                hardware[bank][a as usize] = c;
                erased += 1;
            });
            assert!(erased <= 120);
            let mut expected = [0u32; COLUMNS * ROWS];
            for (row, width, value) in [
                (
                    if linear { 13 } else { 20 },
                    9,
                    if frame % 3 == 0 { "A#1" } else { "B1" },
                ),
                (if linear { 16 } else { 22 }, 21, "-003 CENTS"),
                (if linear { 29 } else { 37 }, 25, "440.00 HZ IN 1"),
                (if linear { 31 } else { 39 }, 29, "3.500 VRMS 9.900 VPP"),
                (if linear { 33 } else { 41 }, 25, "REF1 OFF"),
            ] {
                field(
                    (45 - width) / 2,
                    row,
                    width,
                    value,
                    DEFAULT,
                    Align::Center,
                    |a, c| {
                        occupied[bank].record(a, c);
                        hardware[bank][a as usize] = c;
                        expected[a as usize] = c;
                    },
                );
            }
            for (actual, expected) in hardware[bank].iter().zip(expected) {
                // Blank glyph colors need not match: they are transparent.
                if expected & 127 == 0 {
                    assert_eq!(actual & 127, 0);
                } else {
                    assert_eq!(*actual, expected);
                }
            }
        }
    }

    #[test]
    fn fields_replace_shorter_values_once_per_cell() {
        for align in [Align::Left, Align::Center, Align::Right] {
            let mut cells = [cell('X', DEFAULT); 5];
            for value in ["A#1", "B1", "", "aélong string"] {
                let mut writes = 0;
                field(20, 22, 5, value, DEFAULT, align, |address, value| {
                    assert_eq!(address as usize, 22 * 45 + 20 + writes);
                    cells[writes] = value;
                    writes += 1;
                });
                assert_eq!(writes, 5);
                let count = value.chars().take(5).count();
                assert_eq!(cells.iter().filter(|c| (**c & 127) != 0).count(), count);
            }
        }
        let mut writes = 0;
        field(44, 44, usize::MAX, "ABC", DEFAULT, Align::Right, |a, _| {
            assert_eq!(a, 2024);
            writes += 1;
        });
        assert_eq!(writes, 1);
        field(0, 45, 5, "", DEFAULT, Align::Left, |_, _| panic!());
    }

    #[test]
    fn ascii_bold_and_color_are_independent() {
        for character in ' '..='~' {
            for color in [0, 0xD9, 0xF1, 0xF5, 0xFA, 0xFE] {
                for bold in [false, true] {
                    let encoded = cell(character, Style { color, bold });
                    assert_eq!(encoded & 127, character as u32 - 32);
                    assert_eq!((encoded >> 7) & 1, bold as u32);
                    assert_eq!(encoded >> 8, color as u32);
                }
            }
        }
    }

    #[test]
    fn clipping_and_unicode_do_not_spill_into_other_rows() {
        let mut cells = Vec::new();
        text(43, 44, "aéZ", DEFAULT, |address, value| {
            cells.push((address, value))
        });
        assert_eq!(
            cells,
            vec![(2023, cell('a', DEFAULT)), (2024, cell('?', DEFAULT))]
        );
        text(45, 0, "bad", DEFAULT, |_, _| panic!("outside columns"));
        text(0, 45, "bad", DEFAULT, |_, _| panic!("outside rows"));
        text(usize::MAX, 0, "bad", DEFAULT, |_, _| panic!("overflow"));
    }
}
