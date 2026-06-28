#[macro_export]
macro_rules! impl_scope {
    ($( $SCOPEX:ident: $PACSCOPEX:ty, )+) => { $(
        pub struct $SCOPEX {
            registers: $PACSCOPEX,
            xscale: u8,
            px_div_x: u32,
            px_div_y: u32,
            fs_up: u32,
        }

        impl $SCOPEX {
            pub fn new(registers: $PACSCOPEX, xscale: u8) -> Self {
                let ppv = registers.pixels_per_volt().read().pixels_per_volt().bits() as u32;
                let fs_up = registers.fs().read().fs().bits();
                let px_div_x = ppv >> xscale;
                let px_div_y = ppv >> tiliqua_lib::scope::VScale::Scale1V.to_scale_bits();
                registers.xscale().write(|w| unsafe { w.xscale().bits(xscale) });
                Self { registers, xscale, px_div_x, px_div_y, fs_up }
            }

            pub fn pixels_per_div(&self) -> (u32, u32) {
                (self.px_div_x, self.px_div_y)
            }

            pub fn set_timebase_us(&mut self, t_div_us: u64) {
                let numer: u64 = (self.px_div_x as u64) * (1u64 << (15 + self.xscale as u32));
                let raw = (numer * 1_000_000 / (self.fs_up as u64 * t_div_us)) as u32;
                self.registers.timebase().write(|w| unsafe { w.timebase().bits(raw) });
            }

            pub fn set_timebase(&mut self, tb: tiliqua_lib::scope::Timebase) {
                self.set_timebase_us(tb.t_div_us());
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

            pub fn set_enabled(&mut self, enabled: bool, trigger_always: bool) {
                self.registers.flags().write(|w| {
                    w.enable().bit(enabled);
                    w.trigger_always().bit(trigger_always)
                });
            }

            pub fn set_plot_region(&mut self, x_lo: i16, x_hi: i16, y_lo: i16, y_hi: i16) {
                self.registers.plot_x_lo().write(|w| unsafe { w.value().bits(x_lo as u16) });
                self.registers.plot_x_hi().write(|w| unsafe { w.value().bits(x_hi as u16) });
                self.registers.plot_y_lo().write(|w| unsafe { w.value().bits(y_lo as u16) });
                self.registers.plot_y_hi().write(|w| unsafe { w.value().bits(y_hi as u16) });
            }

            pub fn debug_status(&self) -> u32 {
                u32::from(self.registers.debug_status().read().bits())
            }

            pub fn debug_counts(&self) -> u32 {
                self.registers.debug_count().read().bits()
            }

            pub fn debug_probe(&self) -> (i16, i16) {
                let r = self.registers.debug_probe().read();
                (r.in_x().bits() as i16, r.in_y0().bits() as i16)
            }

            pub fn debug_ncols(&self) -> u32 {
                u32::from(self.registers.debug_ncols().read().ncols().bits())
            }

            pub fn debug_timebase(&self) -> u32 {
                self.registers.debug_timebase().read().td().bits()
            }

            pub fn trigger_test_render(&mut self) {
                self.registers.debug_ctl().write(|w| w.test_render().bit(true));
            }
        }
    )+ };
}
