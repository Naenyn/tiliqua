#![no_std]
#![no_main]

pub use tiliqua_hal as hal;
pub use tiliqua_pac as pac;

hal::impl_tiliqua_soc_pac_without_diagnostics!();

hal::impl_scope! {
    Scope0: pac::SCOPE_PERIPH,
}

#[path = "../../../../rs/handlers_nolog.rs"]
pub mod handlers;
pub mod menu_draw;
pub mod monitor;
pub mod options;
