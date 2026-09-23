//! Compare offline validators with the actual live firmware codecs.
#![allow(dead_code)]
mod options {
    #[derive(Clone, Copy, Debug, Default, PartialEq)]
    pub enum CalibrationPolicy {
        #[default]
        Auto,
        Precision,
        Forgiving,
    }
}
#[path="../src/top/tuner/fw/src/scale.rs"] mod scale;
#[path="../src/top/tuner/fw/src/calibration.rs"] mod oscillator_calibration;
#[path="../src/top/tuner/fw/src/calibration/bipolar.rs"] mod bipolar;
use std::io::{self,BufRead};
fn main() {
    for line in io::stdin().lock().lines() {
        let line=line.unwrap();
        let bytes:Vec<u8>=line.as_bytes().chunks(2).map(|p|
            u8::from_str_radix(std::str::from_utf8(p).unwrap(),16).unwrap()).collect();
        let valid=if bytes.starts_with(b"TSC1") {
            let mut staging=[-99;scale::MAX_DEGREES];
            let valid=scale::decode(&bytes,&mut staging).is_ok();
            if !valid {assert_eq!(staging,[-99;scale::MAX_DEGREES]);}
            valid
        } else {oscillator_calibration::storage::decode(&bytes).is_ok()};
        println!("{}",valid);
    }
}
