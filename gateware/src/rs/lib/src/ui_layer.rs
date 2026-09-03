use core::convert::Infallible;

use tiliqua_hal::embedded_graphics::draw_target::DrawTarget;
use tiliqua_hal::embedded_graphics::geometry::{OriginDimensions, Point, Size};
use tiliqua_hal::embedded_graphics::Pixel;

use crate::color::HI8;

/// Bitmap storage in PSRAM so the 16 KiB blockram is not exhausted.
pub unsafe fn words_psram<const N: usize>(base: usize) -> &'static mut [u32; N] {
    &mut *(base as *mut [u32; N])
}

/// CSR writer for the gateware UI bitmap BRAM (auto-incrementing word writes).
pub trait UiLayerPort {
    fn set_mem_addr(&self, word: u16);
    fn write_mem_word(&self, data: u32);
}

/// Packed 1bpp layer composited in gateware at DVI read time.
///
/// Bitmap storage lives in caller-provided memory (PSRAM scratch), not blockram.
pub struct UiLayer<const N_WORDS: usize> {
    base_word: usize,
    width: u32,
    height: u32,
    words: &'static mut [u32; N_WORDS],
    dirty: bool,
}

impl<const N_WORDS: usize> UiLayer<N_WORDS> {
    pub fn new_in(
        words: &'static mut [u32; N_WORDS],
        base_word: usize,
        width: u32,
        height: u32,
    ) -> Self {
        Self {
            base_word,
            width,
            height,
            words,
            dirty: false,
        }
    }

    pub fn clear(&mut self) {
        self.words.fill(0);
        self.dirty = true;
    }

    pub fn flush<P: UiLayerPort>(&mut self, port: &P) {
        if !self.dirty {
            return;
        }
        port.set_mem_addr(self.base_word as u16);
        for word in self.words.iter() {
            port.write_mem_word(*word);
        }
        self.dirty = false;
    }

    fn set_bit(&mut self, x: u32, y: u32, set: bool) {
        let bit_i = y * self.width + x;
        let word = (bit_i / 32) as usize;
        let bit = bit_i % 32;
        if word >= N_WORDS {
            return;
        }
        if set {
            self.words[word] |= 1u32 << bit;
        } else {
            self.words[word] &= !(1u32 << bit);
        }
        self.dirty = true;
    }

    /// Draw only bitmap pixels that changed since the previous snapshot.
    ///
    /// This is useful for live framebuffer text: removed glyph pixels are
    /// explicitly written in `off`, added pixels in `on`, and unchanged areas
    /// generate no plot traffic. The previous bitmap is updated in place.
    pub fn draw_diff<D>(
        &self,
        previous: &mut Self,
        target: &mut D,
        origin: Point,
        on: HI8,
        off: HI8,
    ) -> Result<(), D::Error>
    where
        D: DrawTarget<Color = HI8>,
    {
        for word_i in 0..N_WORDS {
            let new_word = self.words[word_i];
            let mut changed = new_word ^ previous.words[word_i];
            while changed != 0 {
                let bit = changed.trailing_zeros() as usize;
                let pixel_i = word_i * 32 + bit;
                let y = pixel_i as u32 / self.width;
                if y < self.height {
                    let x = pixel_i as u32 % self.width;
                    let color = if (new_word & (1u32 << bit)) != 0 {
                        on
                    } else {
                        off
                    };
                    target.draw_iter(core::iter::once(Pixel(
                        Point::new(origin.x + x as i32, origin.y + y as i32),
                        color,
                    )))?;
                }
                changed &= changed - 1;
            }
            previous.words[word_i] = new_word;
        }
        Ok(())
    }
}

impl<const N_WORDS: usize> OriginDimensions for UiLayer<N_WORDS> {
    fn size(&self) -> Size {
        Size::new(self.width, self.height)
    }
}

impl<const N_WORDS: usize> DrawTarget for UiLayer<N_WORDS> {
    type Color = HI8;
    type Error = Infallible;

    fn draw_iter<I>(&mut self, pixels: I) -> Result<(), Self::Error>
    where
        I: IntoIterator<Item = Pixel<Self::Color>>,
    {
        for Pixel(coord, color) in pixels {
            if coord.x < 0 || coord.y < 0 {
                continue;
            }
            let x = coord.x as u32;
            let y = coord.y as u32;
            if x >= self.width || y >= self.height {
                continue;
            }
            self.set_bit(x, y, color.intensity() != 0);
        }
        Ok(())
    }
}
