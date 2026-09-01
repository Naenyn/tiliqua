#[doc(hidden)]
pub fn timebase_increment(
    px_div_x: u32,
    xscale: u8,
    fs_up: u32,
    t_div_us: u64,
    frac_bits: u8,
) -> u32 {
    let exponent = frac_bits.saturating_sub(9) as u32 + xscale as u32;
    let numer = (px_div_x as u64) * (1u64 << exponent) * 1_000_000;
    let denom = (fs_up as u64) * t_div_us;
    // Round to the nearest representable ramp increment. Flooring biases every
    // timebase slow and produces a 1.59% error at OSCIO's 2 s/div setting.
    ((numer + denom / 2) / denom) as u32
}

#[doc(hidden)]
pub fn capture_viewport(x_lo: i16, x_hi: i16, xscale: u8) -> (i16, i16) {
    let ramp_start_px = -(1i32 << (15u32.saturating_sub(xscale as u32)));
    let x_offset = x_lo as i32 - ramp_start_px;
    let ramp_end_px = x_hi as i32 - x_offset;
    let ramp_shift = xscale.saturating_sub(2) as u32;
    let ramp_end_raw = (ramp_end_px << ramp_shift)
        .clamp(i16::MIN as i32, i16::MAX as i32) as i16;
    (
        x_offset.clamp(i16::MIN as i32, i16::MAX as i32) as i16,
        ramp_end_raw,
    )
}

#[macro_export]
macro_rules! impl_scope {
    ($( $SCOPEX:ident: $PACSCOPEX:ty, )+) => { $(
        pub struct $SCOPEX {
            registers: $PACSCOPEX,
            xscale: u8,
            px_div_x: u32,
            px_div_y: u32,
            fs_up: u32,
            timebase_frac_bits: u8,
        }

        impl $SCOPEX {
            pub fn new(registers: $PACSCOPEX, xscale: u8) -> Self {
                let ppv = registers.pixels_per_volt().read().pixels_per_volt().bits() as u32;
                let fs_up = registers.fs().read().fs().bits();
                let px_div_x = ppv >> xscale;
                let px_div_y = ppv >> tiliqua_lib::scope::VScale::Scale1V.to_scale_bits();
                registers.xscale().write(|w| unsafe { w.xscale().bits(xscale) });
                Self {
                    registers, xscale, px_div_x, px_div_y, fs_up,
                    timebase_frac_bits: 24,
                }
            }

            pub fn set_timebase_frac_bits(&mut self, frac_bits: u8) {
                self.timebase_frac_bits = frac_bits;
            }

            pub fn pixels_per_div(&self) -> (u32, u32) {
                (self.px_div_x, self.px_div_y)
            }

            pub fn set_timebase_us(&mut self, t_div_us: u64) {
                let raw = $crate::scope::timebase_increment(
                    self.px_div_x, self.xscale, self.fs_up, t_div_us,
                    self.timebase_frac_bits);
                self.registers.timebase().write(|w| unsafe { w.timebase().bits(raw) });
            }

            pub fn set_timebase(&mut self, tb: tiliqua_lib::scope::Timebase) {
                self.set_timebase_us(tb.t_div_us());
            }

            pub fn set_display_mode(&mut self, progressive: bool, clean: bool) {
                self.registers.display_mode().write(|w| {
                    w.progressive().bit(progressive);
                    w.clean().bit(clean)
                });
            }

            pub fn set_progressive(&mut self, progressive: bool) {
                self.set_display_mode(progressive, true);
            }

            pub fn set_yscale_ch(&mut self, ch: usize, vs: tiliqua_lib::scope::VScale) {
                let bits = vs.to_scale_bits();
                match ch {
                    0 => self.registers.yscale0().write(|w| unsafe { w.yscale().bits(bits) }),
                    1 => self.registers.yscale1().write(|w| unsafe { w.yscale().bits(bits) }),
                    2 => self.registers.yscale2().write(|w| unsafe { w.yscale().bits(bits) }),
                    3 => self.registers.yscale3().write(|w| unsafe { w.yscale().bits(bits) }),
                    _ => return,
                };
            }

            /// Eurorack-friendly V/div LUT index (SCOPE ``DigitalScope`` capture path only).
            pub fn set_yscale_index(&mut self, ch: usize, index: u8) {
                match ch {
                    0 => self.registers.yscale0().write(|w| unsafe { w.yscale().bits(index) }),
                    1 => self.registers.yscale1().write(|w| unsafe { w.yscale().bits(index) }),
                    2 => self.registers.yscale2().write(|w| unsafe { w.yscale().bits(index) }),
                    3 => self.registers.yscale3().write(|w| unsafe { w.yscale().bits(index) }),
                    _ => return,
                };
            }

            pub fn set_channel_mask(&mut self, visible: [bool; 4]) {
                self.registers.channel_en().write(|w| {
                    w.ch0().bit(visible[0]);
                    w.ch1().bit(visible[1]);
                    w.ch2().bit(visible[2]);
                    w.ch3().bit(visible[3])
                });
            }

            pub fn set_hue(&mut self, hue: u8) {
                self.registers.hue().write(|w| unsafe { w.hue().bits(hue) });
            }

            pub fn set_intensity(&mut self, intensity: u8) {
                self.registers.intensity().write(|w| unsafe { w.intensity().bits(intensity) });
            }

            pub fn set_trigger_level(&mut self, lvl: i16) {
                self.registers.trigger_lvl().write(|w| unsafe { w.trigger_level().bits(lvl as u16) });
            }

            pub fn set_ypos_px(&mut self, ch: usize, pos: i16) {
                match ch {
                    0 => self.registers.ypos0().write(|w| unsafe { w.ypos().bits(pos as u16) }),
                    1 => self.registers.ypos1().write(|w| unsafe { w.ypos().bits(pos as u16) }),
                    2 => self.registers.ypos2().write(|w| unsafe { w.ypos().bits(pos as u16) }),
                    3 => self.registers.ypos3().write(|w| unsafe { w.ypos().bits(pos as u16) }),
                    _ => return,
                };
            }

            pub fn set_xscale(&mut self, scale: u8) {
                self.xscale = scale;
                let ppv = self.registers.pixels_per_volt().read().pixels_per_volt().bits() as u32;
                self.px_div_x = ppv >> scale;
                self.registers.xscale().write(|w| unsafe { w.xscale().bits(scale) });
            }

            pub fn set_xpos_px(&mut self, pos: i16) {
                self.registers.xpos().write(|w| unsafe { w.xpos().bits(pos as u16) });
            }

            pub fn set_trigger(
                &mut self,
                enabled: bool,
                trigger_free: bool,
                trigger_auto: bool,
                falling: bool,
                ch: u8,
                filter: u8,
            ) {
                self.registers.flags().write(|w| {
                    w.enable().bit(enabled);
                    w.trigger_always().bit(trigger_free);
                    w.trigger_auto().bit(trigger_auto);
                    w.trigger_falling().bit(falling);
                    unsafe { w.trigger_ch().bits(ch.min(3)) };
                    unsafe { w.trigger_filter().bits(filter.min(4)) };
                    w
                });
            }

            pub fn set_plot_region(&mut self, x_lo: i16, x_hi: i16, y_lo: i16, y_hi: i16) {
                self.registers.plot_x_lo().write(|w| unsafe { w.value().bits(x_lo as u16) });
                self.registers.plot_x_hi().write(|w| unsafe { w.value().bits(x_hi as u16) });
                self.registers.plot_y_lo().write(|w| unsafe { w.value().bits(y_lo as u16) });
                self.registers.plot_y_hi().write(|w| unsafe { w.value().bits(y_hi as u16) });

                // Align ramp -1 with the left edge and stop at the exclusive
                // right edge. This removes the invisible tail that previously
                // delayed the next slow sweep by several divisions.
                let (x_offset, ramp_end_raw) =
                    $crate::scope::capture_viewport(x_lo, x_hi, self.xscale);
                self.set_xpos_px(x_offset);
                self.registers.ramp_end().write(|w| unsafe {
                    w.value().bits(ramp_end_raw as u16)
                });
            }

        }
    )+ };
}

#[cfg(test)]
mod tests {
    use super::{capture_viewport, timebase_increment};

    #[test]
    fn timebase_increment_rounds_to_nearest() {
        // OSCIO at 192 kHz, 8x interpolation, xscale 5 and 125 px/div.
        assert_eq!(timebase_increment(125, 5, 1_536_000, 2_000_000, 24), 43);
        assert_eq!(timebase_increment(125, 5, 1_536_000, 500_000, 24), 171);
        assert_eq!(timebase_increment(125, 5, 1_536_000, 100, 24), 853_333);

        assert_eq!(timebase_increment(125, 5, 1_536_000, 2_000_000, 28), 683);
        assert_eq!(timebase_increment(125, 5, 1_536_000, 500_000, 28), 2731);
    }


    #[test]
    fn capture_viewport_uses_the_full_visible_width_without_a_tail() {
        // 1280x720 landscape: -1 lands at x=-632 and the programmable
        // endpoint lands at the exclusive x=632 bound.
        assert_eq!(capture_viewport(-632, 632, 5), (392, 1920));
        // 720-wide portrait: same invariant with xscale 6.
        assert_eq!(capture_viewport(-352, 352, 6), (160, 3072));
    }
}
