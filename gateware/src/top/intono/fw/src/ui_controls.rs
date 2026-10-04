//! Geometry for visible controls on the native-text 720-pixel canvas.
//! Option indices remain stable so storage and action dispatch are unchanged.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Surface { Tuner, Calibration, Profiles, Check, Scales, Notes, Setups, Routes, Settings, Help, Midi }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Field { pub column: u8, pub row: u8, pub width: u8, pub action: bool }
/// A centered field's complete glyph footprint must remain in the round panel.
pub fn center_width(row: u8, requested: usize) -> usize {
    let limit=match row { 0=>0,1=>14,2=>20,3=>24,4=>26,5=>28,
        6..=16=>30,17=>28,18=>26,19=>22,20=>18,21=>10,_=>0 };
    requested.min(limit)
}
pub fn field(surface: Surface, index: usize) -> Option<Field> {
    let (column, row, width, action) = match surface {
        Surface::Calibration => match index {
            0 => (4, 5, 6, false), 1 => (11, 5, 6, false),
            2 => return None, // measured reference, not an editable scan target
            3 => (9, 6, 14, false), 4 => (18, 5, 12, false),
            5 => (3, 16, 7, true), 6 => (11, 16, 8, true),
            7 => (20, 16, 8, true), 8 => (8, 18, 14, true), _ => return None,
        },
        Surface::Tuner => match index {
            0 => (8, 4, 15, false), 1 => (10, 18, 10, false), _ => return None,
        },
        Surface::Scales => match index {
            0 => (4,5,10,false), 1 => (16,5,14,false),
            2 => return None, // keyboard focus; no separate root editor
            3 => return None, // transpose belongs to the route
            4 => return None, // mapping is a route property
            5 => (16,16,12,true),
            9 => (4,16,10,false), 8 => (29,10,3,false),
            10 => (4,18,10,false), 11 => (16,18,6,true),
            12 => (24,18,6,true), _ => return None,
        },
        Surface::Notes => match index {
            8 => (4,5,10,false), 9 => (16,5,10,false), 10 => (29,10,3,false), // keys themselves own the hidden toggle action
            1 | 2 => return None,
            0 => (4,16,10,false), // octave target for Clear/Fill
            3 => (4,17,10,true), 4 => (16,17,10,true),
            6 => (4,18,7,true), 7 => (12,18,7,true),
            5 => (16,16,10,true), _ => return None,
        },
        Surface::Routes => match index {
            0 => (4,5,10,false), 1 => (16,5,10,false),
            3 => (4,7,11,false), 2 => (16,7,10,false),
            4 => (4,9,11,true), 5 => (16,9,10,false),
            6 => (4,16,10,true), 7 => (16,16,10,true),
            8 => (10,18,10,true),
            9 => (4,6,12,false), 10 => (18,6,10,false),
            11 => (4,8,13,false), 12 => (18,8,10,false),
            13 => (4,17,10,false),14 => (16,17,10,true),
            15 => (8,10,14,false), _ => return None,
        },
        Surface::Midi => match index {
            0=>(4,5,10,false),1=>(16,5,10,false),
            2=>(4,7,10,false),3=>(16,7,10,true),4=>(10,9,10,false),_=>return None,
        },
        Surface::Setups => match index {
            0 => (8,5,14,false), 1 => (4,16,10,true),
            2 => (16,16,10,true),3 => (7,17,16,true),4 => (10,19,10,true), _ => return None,
        },
        Surface::Profiles => match index {
            0 => (10,5,10,false),
            1 => (4,10,10,false), 2 => (16,10,10,false),
            3 => (4,14,10,true), 4 => (16,14,10,true),
            5 => (4,16,10,true), 6 => (16,16,10,true), _ => return None,
        },
        Surface::Check => match index {
            0 => (4,16,10,true), 1 => (16,16,10,true),
            2 => (4,18,10,true), 3 => (16,18,10,true),
            4 => (11,19,8,true), _ => return None,
        },
        Surface::Help => match index {0 => (10,17,10,false), _ => return None},
        Surface::Settings => match index {
            0 => (4,5,10,false),1 => (16,5,10,true),2 => (4,7,10,true),
            _ => return None,
        },
    };
    Some(Field { column, row, width, action })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn all_controls_fit_large_text_canvas_and_round_viewport() {
        for surface in [Surface::Tuner, Surface::Calibration, Surface::Profiles,
            Surface::Check, Surface::Scales, Surface::Notes, Surface::Setups,
            Surface::Routes, Surface::Settings, Surface::Help, Surface::Midi] {
            for index in 0..16 {
                let Some(f) = field(surface, index) else { continue };
                assert!(f.column + f.width <= 32 && f.row + 1 < 22);
                for x in [120 + f.column as i32 * 16, 120 + (f.column + f.width) as i32 * 16 - 1] {
                    for y in [f.row as i32 * 32, (f.row as i32 + if f.action { 1 } else { 2 }) * 32 - 3] {
                        assert!((x-360).pow(2) + (y-360).pow(2) <= 360*360, "{surface:?} {index}");
                    }
                }
            }
        }
    }
    #[test]
    fn calibration_reference_cannot_be_selected_as_a_control() {
        assert_eq!(field(Surface::Calibration, 2), None);
        assert!(field(Surface::Routes, 2).is_some());
    }
    #[test]
    fn status_and_name_fields_fit_the_round_panel_even_at_bottom_rows() {
        for row in 1..22 {
            let width=center_width(row,30) as i32;
            let left=120+((30-width)/2)*16;
            for x in [left,left+width*16-1] {
                for y in [row as i32*32,row as i32*32+29] {
                    assert!((x-360).pow(2)+(y-360).pow(2)<=360*360,"row {row}");
                }
            }
        }
    }
}
