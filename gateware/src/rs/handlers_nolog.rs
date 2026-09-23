#![allow(unused_imports, unused_mut, unused_variables)]

//! Interrupt and exception handlers for firmware without a UART logger.

use crate::{pac, Timer0};

use core::panic::PanicInfo;

use amaranth_soc_isr::return_as_is;
use irq::scoped_interrupts;

scoped_interrupts! {
    #[allow(non_camel_case_types)]
    pub enum Interrupt {
        TIMER0,
    }
    use #[return_as_is];
}

#[cfg(not(test))]
#[panic_handler]
fn panic(_panic_info: &PanicInfo) -> ! {
    loop {}
}

#[export_name = "ExceptionHandler"]
fn exception_handler(_trap_frame: &riscv_rt::TrapFrame) -> ! {
    loop {}
}

#[export_name = "DefaultHandler"]
fn default_isr_handler() {
    let peripherals = unsafe { pac::Peripherals::steal() };
    let sysclk = pac::clock::sysclk();
    let timer = Timer0::new(peripherals.TIMER0, sysclk);
    if timer.is_pending() {
        unsafe {
            TIMER0();
        }
        timer.clear_pending();
    }
}
