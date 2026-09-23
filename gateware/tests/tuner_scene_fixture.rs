//! Synthetic graphics only: no calibration/quantization or audio acquisition.
#[path = "../src/top/intono/fw/src/ui_canvas.rs"]
mod ui_canvas;
use std::io::{self, Write};
use ui_canvas::{Rect, Point};

fn main() {
    let scene = std::env::args().nth(1).expect("scene name");
    let mut pixels = vec![0u8; 720*720];
    let mut writes = 0;
    let mut emit = |p:Point, color| {
        assert!(p.inside());
        assert!((p.x-360).pow(2)+(p.y-360).pow(2)<336*336);
        writes += 1;
        pixels[p.y as usize*720+p.x as usize] = color;
    };
    match scene.as_str() {
        "tuner" => {
            for segment in 0..88 { ui_canvas::four_lane_scale_segment(segment,&mut emit); }
        },
        "calibrator" => {
            let rect = Rect{x:152,y:256,width:417,height:257};
            for segment in 0..18 {
                assert!(ui_canvas::grid_segment(rect,8,8,segment,0x29,&mut emit));
            }
            let residuals = [-30,-18,-8,0,8,14,18,24,40];
            for segment in 0..residuals.len()-1 {
                assert!(ui_canvas::trace_segment(rect,&residuals,-50,50,segment,0xF5,&mut emit));
            }
        },
        "quantizer" => {
            let rect = Rect{x:152,y:256,width:417,height:257};
            for segment in 0..22 {
                assert!(ui_canvas::grid_segment(rect,12,8,segment,0x29,&mut emit));
            }
            for octave in 0..8 {
                for note in [0,2,4,7,9] {
                    let cell = Rect{x:157+note*416/12,y:262+octave*32,width:23,height:19};
                    assert!(ui_canvas::rectangle(cell,0xA9,&mut emit));
                }
            }
        },
        _ => panic!("unknown scene"),
    }
    assert!(writes < 12_000, "retained scene work unexpectedly grew: {writes}");
    eprintln!("{scene}: {writes} retained pixel writes");
    io::stdout().write_all(&pixels).unwrap();
}
