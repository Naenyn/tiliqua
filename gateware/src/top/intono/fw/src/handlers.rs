use crate::pac;
use crate::Timer0;

use amaranth_soc_isr::return_as_is;
use core::panic::PanicInfo;
use irq::scoped_interrupts;

scoped_interrupts! {
    #[allow(non_camel_case_types)]
    pub enum Interrupt { TIMER0, }
    use #[return_as_is];
}

// Bounded fatal diagnostics remain available without a runtime logger.
// A disconnected debug cable must not turn fault reporting into another hang.
struct FaultWriter;
impl core::fmt::Write for FaultWriter {
    fn write_str(&mut self, text: &str) -> core::fmt::Result {
        let uart=unsafe {pac::UART0::steal()};
        for byte in text.bytes() {
            let mut ready=false;
            for _ in 0..12000 {
                if uart.tx_ready().read().txe().bit() {ready=true;break;}
            }
            if !ready {return Err(core::fmt::Error);}
            uart.tx_data().write(|w|unsafe {w.data().bits(byte)});
        }
        Ok(())
    }
}

fn fault_word(value: usize) {
    use core::fmt::Write;
    let mut bytes=[b'0';8];
    for (i,b) in bytes.iter_mut().enumerate() {*b=b"0123456789abcdef"[(value>>(28-i*4))&15];}
    FaultWriter.write_str(unsafe {core::str::from_utf8_unchecked(&bytes)}).ok();
}
#[cfg(not(test))]
#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    use core::fmt::Write;
    FaultWriter.write_str("\nINTONO PANIC ").ok();
    if let Some(location)=info.location() {
        FaultWriter.write_str(location.file()).ok();
        FaultWriter.write_str(":").ok();fault_word(location.line() as usize);
    }
    FaultWriter.write_str("\n").ok();
    loop {}
}
#[export_name = "ExceptionHandler"]
fn exception_handler(trap_frame: &riscv_rt::TrapFrame) -> ! {
    use core::fmt::Write;
    for (label,value) in [("\nINTONO TRAP PC=",riscv::register::mepc::read()),
        (" CAUSE=",riscv::register::mcause::read().bits()),
        (" VALUE=",riscv::register::mtval::read()),(" RA=",trap_frame.ra)] {
        FaultWriter.write_str(label).ok();fault_word(value);
    }
    FaultWriter.write_str("\n").ok();
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
