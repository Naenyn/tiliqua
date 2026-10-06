//! Seven semantic theme colors: three primary, three complementary, highlight.
//! REZO control/modulation pairings; black/white and musical status colors are shared.
pub const BLACK:u8=0x09;
pub const WHITE:u8=0xF9;
pub const PRIMARY_DIM:u8=0x29;
pub const PRIMARY:u8=0x49;
pub const PRIMARY_BRIGHT:u8=0x69;
pub const COMPLEMENT_DIM:u8=0x89;
pub const COMPLEMENT:u8=0xB9;
pub const COMPLEMENT_BRIGHT:u8=0xC9;
pub const HIGHLIGHT:u8=0xF2;
pub const COLORS:[[u32;7];9]=[
    [0x183541,0x367A94,0x55BFE8,0x995600,0xFF9000,0xFFAC40,0xFFE58A], // Blue
    [0x343434,0x767676,0xB8B8B8,0x484848,0x787878,0x9A9A9A,0xFFFFFF], // LCD
    [0x382709,0x815814,0xC98A20,0x2F6382,0x4EA5D9,0x7ABCE2,0xFFF4CC], // Amber
    [0x183939,0x368283,0x55CBCD,0x994C40,0xFF7F6A,0xFF9F8F,0xF4FFFF], // Cyan
    [0x20372C,0x4A7F64,0x74C69D,0x89407C,0xE56BCE,0xEC90DA,0xF3FFF6], // Green
    [0x2C223B,0x644E86,0x9D7AD2,0x91742F,0xF2C14E,0xF5D07A,0xFFF8DA], // Violet
    [0x401014,0x93242D,0xE63946,0x995428,0xFF8C42,0xFFA971,0xFFF1C1], // Ember
    [0x2B1A40,0x633C93,0x9B5DE5,0x008999,0x00E5FF,0x40ECFF,0xFFF0FF], // Neon
    [0x131B43,0x2B3E98,0x4361EE,0x941650,0xF72585,0xF95CA4,0xF5F1FF], // Azure
 ];
pub fn rgb(color:u32)->(u8,u8,u8) {((color>>16)as u8,(color>>8)as u8,color as u8)}
pub fn highlight(theme:u8)->(u8,u8,u8) {rgb(COLORS[theme.min(8) as usize][6])}
pub fn color(theme:u8,intensity:u8)->(u8,u8,u8) {
    let role=match intensity {0=>return (0,0,0),1..=3=>0,4..=5=>1,6..=7|10=>2,
        8..=9=>3,11=>4,12=>5,14=>6,_=>return (245,248,255)};
    rgb(COLORS[theme.min(8) as usize][role])
}
#[cfg(test)] mod tests {
    use super::*;
    #[test]fn seven_roles_remain_distinct_and_black_white_are_shared() {
        for theme in 0..=8 {
            assert_eq!(color(theme,0),(0,0,0));assert_eq!(color(theme,13),(245,248,255));
            assert_eq!(color(theme,15),(245,248,255));assert_eq!(color(theme,14),highlight(theme));
            for role in 0..7 {for other in role+1..7 {assert_ne!(COLORS[theme as usize][role],COLORS[theme as usize][other]);}}
        }
    }
    #[test]fn rezo_pairings_and_keyboard_membership_are_preserved() {
        assert_eq!(color(3,6),rgb(0x55CBCD));assert_eq!(color(3,11),rgb(0xFF7F6A));
        assert_eq!(color(7,6),rgb(0x9B5DE5));assert_eq!(color(7,11),rgb(0x00E5FF));
        for theme in 0..=8 {assert_eq!(color(theme,10),color(theme,6));}
    }
}
