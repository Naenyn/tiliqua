#![allow(unused_imports, unused_mut, unused_variables)]

use crate::{hal, pac};
use crate::{Serial0, Timer0};

use amaranth_soc_isr::return_as_is;
use core::cell::RefCell;
use core::panic::PanicInfo;
use irq::scoped_interrupts;
use log::*;
use tiliqua_lib::logger::WriteLogger;

scoped_interrupts! {
    #[allow(non_camel_case_types)]
    pub enum Interrupt { TIMER0, }
    use #[return_as_is];
}

static LOGGER: WriteLogger<Serial0> = WriteLogger {
    writer: RefCell::new(None),
    level: Level::Trace,
};

pub fn logger_init(writer: Serial0) {
    LOGGER.writer.replace(Some(writer));
    unsafe {
        log::set_logger_racy(&LOGGER)
            .map(|()| log::set_max_level_racy(LevelFilter::Trace))
            .expect("logger");
    }
}

#[cfg(not(test))]
#[panic_handler]
fn panic(panic_info: &PanicInfo) -> ! {
    error!("{:?}", panic_info);
    loop {}
}

#[export_name = "ExceptionHandler"]
fn exception_handler(trap_frame: &riscv_rt::TrapFrame) -> ! {
    error!("exception: ra={:x}", trap_frame.ra);
    loop {}
}

#[export_name = "DefaultHandler"]
fn default_isr_handler() {
    let peripherals = unsafe { pac::Peripherals::steal() };
    let timer = Timer0::new(peripherals.TIMER0, pac::clock::sysclk());
    if timer.is_pending() {
        unsafe {
            TIMER0();
        }
        timer.clear_pending();
    }
}
