//! Compile for the real target; ELF symbol sizes expose layouts without running.
#![no_std]
#![allow(dead_code)]
#[path="../src/top/intono/fw/src/calibration.rs"] mod oscillator_calibration;
#[path="../src/top/intono/fw/src/calibration/bipolar.rs"] mod bipolar;

#[no_mangle]
pub static PROFILE_LAYOUT: [u8; core::mem::size_of::<oscillator_calibration::Profile>()] =
    [0; core::mem::size_of::<oscillator_calibration::Profile>()];
#[no_mangle]
pub static PLAYBACK_LAYOUT: [u8; core::mem::size_of::<oscillator_calibration::playback::Engine>()] =
    [0; core::mem::size_of::<oscillator_calibration::playback::Engine>()];
