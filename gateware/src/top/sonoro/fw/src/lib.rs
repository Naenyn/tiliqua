#![no_std]
#![no_main]

pub use tiliqua_hal as hal;
pub use tiliqua_pac as pac;

hal::impl_tiliqua_soc_pac!();

pub mod handlers;
pub mod options;
