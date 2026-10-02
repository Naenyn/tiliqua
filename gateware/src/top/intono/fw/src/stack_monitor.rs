//! Stack watermark, painted once before startup and interrupt registration.
//! Untouched words estimate the remaining margin; this is not an overflow trap.
const MARKER: u32 = 0xc35a_69b4;

fn untouched_words(words: usize, mut read: impl FnMut(usize) -> u32) -> usize {
    (0..words).take_while(|&index| read(index) == MARKER).count()
}

#[cfg(not(test))]
fn bounds() -> (usize, usize) {
    extern "C" { static _ebss: u8; static _sstack: u8; }
    ((core::ptr::addr_of!(_ebss) as usize + 3) & !3,
     core::ptr::addr_of!(_sstack) as usize)
}

/// Call exactly once from main before startup enables any interrupts.
#[cfg(not(test))]
#[inline(never)]
pub unsafe fn paint() {
    let (start, _) = bounds();
    let sp: usize;
    core::arch::asm!("mv {}, sp", out(reg) sp, options(nomem, nostack, preserves_flags));
    // Exclude this function's active frame and a conservative scratch margin.
    let end = sp.saturating_sub(64) & !3;
    for address in (start..end).step_by(4) {
        core::ptr::write_volatile(address as *mut u32, MARKER);
    }
}

#[cfg(not(test))]
pub fn free_bytes() -> usize {
    let (start, end) = bounds();
    untouched_words((end - start) / 4, |index| unsafe {
        core::ptr::read_volatile((start + index * 4) as *const u32)
    }) * 4
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reports_only_the_contiguous_unused_margin() {
        for used in 0..=16 {
            let mut words = [MARKER; 16];
            words[16-used..].fill(0);
            assert_eq!(untouched_words(16, |index| words[index]), 16-used);
        }
        assert_eq!(untouched_words(0, |_| panic!("outside stack")), 0);
        assert_eq!(untouched_words(4, |index| if index == 1 {0} else {MARKER}), 1);
    }
}
