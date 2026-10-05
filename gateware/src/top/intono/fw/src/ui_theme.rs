//! REZO semantic colors mapped to Intono's existing blue UI hue.
// Channel marker hues, keyboard black/white, and the yellow cursor stay fixed.
pub const COLORS: [[u32;8];8] = [[16777215, 15658734, 12105912, 7895160, 8947848, 3289650, 657930, 1315860], [16774348, 16765286, 13208096, 5154265, 10119714, 3483407, 788483, 1511430], [16056319, 13170680, 5622733, 16744298, 2792863, 1456186, 265228, 464664], [15990774, 14218204, 7653021, 15035342, 4231532, 1786674, 265739, 531477], [16775386, 15195381, 10320594, 15909198, 7096995, 2825530, 525580, 1051160], [16773569, 16765286, 15087942, 16747586, 11085618, 4658458, 1049605, 2296333], [16773375, 15324671, 10182117, 58879, 7158967, 2758471, 525327, 1313316], [16118271, 13227775, 4415982, 16196997, 3820216, 1514834, 263703, 724781]];
pub fn color(theme:u8,intensity:u8)->Option<(u8,u8,u8)> {
 if theme==0 {return None;}
 if intensity==0 {return Some((0,0,0));}
 let role=match intensity {1..=3=>5,4..=8=>4,9..=13=>2,14=>1,_=>0};
 let rgb=COLORS[(theme-1).min(7) as usize][role];
 Some(((rgb>>16)as u8,(rgb>>8)as u8,rgb as u8))
}
#[cfg(test)] mod tests {
 use super::*;
 #[test]fn themes_keep_blank_black_and_selection_bright(){
  assert_eq!(color(0,15),None);
  for t in 1..=8 {assert_eq!(color(t,0),Some((0,0,0)));let (r,g,b)=color(t,15).unwrap();assert!(r>230&&g>230&&b>190);assert_ne!(color(t,15),color(t,4));}
 }
}
