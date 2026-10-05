//! Read-only interval view for imported tunings; no allocation or editing state.
use core::fmt::Write;
use heapless::String;
use crate::{scale,ui_text,ui_canvas};

pub fn page_start(count:u8,page:u8)->usize {(page as usize).min((count as usize).saturating_sub(1)/6)*6}
pub fn turn_page(page:u8,count:u8,ticks:i8)->u8 {(page as i16+ticks as i16).clamp(0,(count.saturating_sub(1)/6) as i16) as u8}
pub const STRIP:ui_canvas::Rect=ui_canvas::Rect{x:156,y:330,width:408,height:36};
fn label(row:usize,value:&str,color:u8,mut emit:impl FnMut(u16,u32)) {
    ui_text::field(3,row,34,value,ui_text::Style{color,bold:false},ui_text::Align::Center,&mut emit);
}
pub fn text(table:&scale::Imported,slot:u8,page:u8,mut emit:impl FnMut(u16,u32)) {
    let (count,period)=table.summary();let mut s=String::<48>::new();
    write!(&mut s,"SCALA / USER SLOT {}",slot).ok();label(7,&s,0xF9,&mut emit);
    s.clear();write!(&mut s,"{} PITCHES / REPEATING PATTERN",count).ok();label(8,&s,0xB9,&mut emit);
    s.clear();write!(&mut s,"PERIOD {}.{:03} CENTS",period/1000,period%1000).ok();label(9,&s,0xB9,&mut emit);
    ui_text::field(3,12,10,"0",ui_text::DEFAULT,ui_text::Align::Left,&mut emit);
    s.clear();write!(&mut s,"{}.{:03}",period/1000,period%1000).ok();
    ui_text::field(27,12,10,&s,ui_text::DEFAULT,ui_text::Align::Right,&mut emit);
    let degrees=table.degrees();
    for (i,pitch) in degrees.iter().skip(page_start(count,page)).take(6).enumerate() {
        s.clear();write!(&mut s,"{}: {}.{:03}c",page_start(count,page)+i+1,pitch/1000,pitch%1000).ok();
        ui_text::field(if i<3 {4}else{23},13+i%3,15,&s,ui_text::Style{color:0xB9,bold:false},ui_text::Align::Left,&mut emit);
    }
    s.clear();write!(&mut s,"{}-{} OF {} / READ ONLY",page_start(count,page)+1,(page_start(count,page)+6).min(count as usize),count).ok();
    ui_text::field(0,16,26,&s,ui_text::Style{color:0x89,bold:false},ui_text::Align::Center,&mut emit);
}
/// Every degree is represented at its real position; nearby markers may merge
/// at screen resolution, but table values and playback keep full precision.
pub fn plot(table:&scale::Imported,mut emit:impl FnMut(ui_canvas::Point,u8)) {
    let (_,period)=table.summary();if period<=0 {return;}
    let left=STRIP.x;let right=left+STRIP.width as i32-1;let y=348;
    ui_canvas::line(ui_canvas::Point{x:left,y},ui_canvas::Point{x:right,y},0x49,&mut emit);
    for pitch in table.degrees().iter().copied().chain(core::iter::once(period)) {
        let x=left+((pitch as u32)*(STRIP.width as u32-1)/period as u32) as i32;
        let color=if pitch==0 || pitch==period {0xF2}else{0xD9};
        for dx in 0..2 {ui_canvas::line(ui_canvas::Point{x:(x+dx).min(right),y:y-14},ui_canvas::Point{x:(x+dx).min(right),y:y+14},color,&mut emit);}
    }
}
