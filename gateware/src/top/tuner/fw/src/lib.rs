#![no_std]
#![no_main]

pub use tiliqua_pac as pac;
pub use tiliqua_hal as hal;

tiliqua_hal::impl_serial! { Serial0: tiliqua_pac::UART0, }
tiliqua_hal::impl_timer! { Timer0: tiliqua_pac::TIMER0, }
tiliqua_hal::impl_i2c! { I2c0: tiliqua_pac::I2C0, }
tiliqua_hal::impl_i2c! { I2c1: tiliqua_pac::I2C1, }
tiliqua_hal::impl_encoder! { Encoder0: tiliqua_pac::ENCODER0, }
tiliqua_hal::impl_eurorack_pmod! { EurorackPmod0: tiliqua_pac::PMOD0_PERIPH, }
tiliqua_hal::impl_lean_dma_framebuffer! {
    DMAFramebuffer0: tiliqua_pac::FRAMEBUFFER_PERIPH,
    Palette0: tiliqua_pac::PALETTE_PERIPH,
}
tiliqua_hal::impl_spiflash! { SPIFlash0: tiliqua_pac::SPIFLASH_CTRL, }

pub mod handlers;
pub mod options;
