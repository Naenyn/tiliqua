use tiliqua_hal::dma_framebuffer::DMAFramebuffer;
use serde_derive::{Serialize, Deserialize};

use strum_macros::{EnumIter, IntoStaticStr};

// TODO: take this dynamically from DMAFramebuffer configuration.
pub const PX_HUE_MAX: usize = 16;
pub const PX_INTENSITY_MAX: usize = 16;
const PALETTE_LEN: usize = PX_INTENSITY_MAX * PX_HUE_MAX;

#[derive(Default, Clone, Copy, PartialEq, EnumIter, IntoStaticStr, Serialize, Deserialize)]
#[strum(serialize_all = "kebab-case")]
pub enum ColorPalette {
    Exp,
    #[default]
    Linear,
    Dim,
    Gray,
    InvGray,
    Inferno,
    Hueswap,
    Magma,
    Plasma,
    Viridis,
}

const fn hue2rgb(p: f64, q: f64, mut t: f64) -> f64 {
    if t < 0.0 { t += 1.0; }
    if t > 1.0 { t -= 1.0; }
    if t < 1.0 / 6.0 {
        return p + (q - p) * 6.0 * t;
    }
    if t < 0.5 {
        return q;
    }
    if t < 2.0 / 3.0 {
        return p + (q - p) * (2.0 / 3.0 - t) * 6.0;
    }
    p
}

/// Converts an HSL color to RGB. Conversion formula
/// adapted from http://en.wikipedia.org/wiki/HSL_color_space.
/// Assumes h, s, and l are contained in the set [0, 1] and
/// returns RGB in the set [0, 255].
const fn hsl2rgb(h: f64, s: f64, l: f64) -> (u8, u8, u8) {
    if s == 0.0 {
        let gray = (l * 255.0) as u8;
        return (gray, gray, gray);
    }
    let q = if l < 0.5 { l * (1.0 + s) } else { l + s - l * s };
    let p = 2.0 * l - q;
    (
        (hue2rgb(p, q, h + 1.0 / 3.0) * 255.0) as u8,
        (hue2rgb(p, q, h) * 255.0) as u8,
        (hue2rgb(p, q, h - 1.0 / 3.0) * 255.0) as u8,
    )
}

/// could not find a const version of powf :(
const fn const_powf(base: f64, exp: i32) -> f64 {
    let mut result = 1.0;
    let mut i = 0;
    let (b, n) = if exp < 0 { (1.0 / base, -exp) } else { (base, exp) };
    while i < n {
        result *= b;
        i += 1;
    }
    result
}

// COLOR PALETTES
// All computed statically, so we can rapidly swap between them.

const fn gen_exp() -> [(u8, u8, u8); PALETTE_LEN] {
    let mut lut = [(0u8, 0u8, 0u8); PALETTE_LEN];
    let fac = 1.35;
    let fac_n = const_powf(fac, PX_INTENSITY_MAX as i32);
    let mut i = 0;
    while i < PX_INTENSITY_MAX {
        let intensity = const_powf(fac, i as i32 + 1) / fac_n;
        let mut h = 0;
        while h < PX_HUE_MAX {
            let hue = h as f64 / PX_HUE_MAX as f64;
            lut[i * PX_HUE_MAX + h] = hsl2rgb(hue, 0.9, intensity);
            h += 1;
        }
        i += 1;
    }
    lut
}

const fn gen_linear() -> [(u8, u8, u8); PALETTE_LEN] {
    let mut lut = [(0u8, 0u8, 0u8); PALETTE_LEN];
    let mut i = 0;
    while i < PX_INTENSITY_MAX {
        let mut h = 0;
        while h < PX_HUE_MAX {
            lut[i * PX_HUE_MAX + h] = hsl2rgb(
                h as f64 / PX_HUE_MAX as f64, 0.9,
                i as f64 / PX_HUE_MAX as f64);
            h += 1;
        }
        i += 1;
    }
    lut
}

const fn gen_dim() -> [(u8, u8, u8); PALETTE_LEN] {
    let mut lut = [(0u8, 0u8, 0u8); PALETTE_LEN];
    let mut i = 0;
    while i < PX_INTENSITY_MAX {
        let mut h = 0;
        while h < PX_HUE_MAX {
            let (r, g, b) = hsl2rgb(
                h as f64 / PX_HUE_MAX as f64, 0.9,
                i as f64 / PX_HUE_MAX as f64);
            lut[i * PX_HUE_MAX + h] = (r / 2, g / 2, b / 2);
            h += 1;
        }
        i += 1;
    }
    lut
}

const fn gen_gray() -> [(u8, u8, u8); PALETTE_LEN] {
    let mut lut = [(0u8, 0u8, 0u8); PALETTE_LEN];
    let mut i = 0;
    while i < PX_INTENSITY_MAX {
        let gray = (i * 16) as u8;
        let mut h = 0;
        while h < PX_HUE_MAX {
            lut[i * PX_HUE_MAX + h] = (gray, gray, gray);
            h += 1;
        }
        i += 1;
    }
    lut
}

const fn gen_inv_gray() -> [(u8, u8, u8); PALETTE_LEN] {
    let mut lut = [(0u8, 0u8, 0u8); PALETTE_LEN];
    let mut i = 0;
    while i < PX_INTENSITY_MAX {
        let gray = 255 - (i * 16) as u8;
        let mut h = 0;
        while h < PX_HUE_MAX {
            lut[i * PX_HUE_MAX + h] = (gray, gray, gray);
            h += 1;
        }
        i += 1;
    }
    lut
}

const INFERNO_16: [(u8, u8, u8); 16] = [
    (0, 0, 4), (10, 7, 34), (32, 12, 74), (60, 9, 101),
    (87, 16, 110), (114, 25, 110), (140, 41, 99), (165, 62, 79),
    (187, 86, 57), (206, 114, 36), (222, 143, 17), (234, 176, 5),
    (242, 210, 37), (248, 238, 85), (252, 252, 139), (252, 255, 164),
];

const MAGMA_16: [(u8, u8, u8); 16] = [
    (0, 0, 4), (11, 8, 30), (28, 16, 68), (51, 16, 96),
    (75, 19, 109), (101, 21, 110), (126, 30, 108), (151, 43, 101),
    (176, 58, 91), (199, 75, 81), (218, 95, 73), (234, 120, 75),
    (246, 150, 92), (252, 183, 119), (254, 218, 157), (252, 253, 191),
];

const PLASMA_16: [(u8, u8, u8); 16] = [
    (13, 8, 135), (47, 5, 150), (76, 2, 161), (103, 0, 167),
    (130, 5, 167), (156, 23, 158), (181, 42, 145), (204, 62, 129),
    (222, 81, 110), (237, 100, 90), (247, 123, 67), (252, 149, 48),
    (252, 177, 36), (245, 207, 58), (227, 235, 86), (240, 249, 33),
];

const VIRIDIS_16: [(u8, u8, u8); 16] = [
    (68, 1, 84), (72, 24, 106), (72, 44, 122), (65, 63, 131),
    (56, 82, 139), (48, 100, 141), (42, 118, 142), (35, 136, 142),
    (31, 153, 138), (34, 168, 132), (53, 183, 121), (84, 197, 104),
    (122, 209, 81), (165, 219, 54), (210, 226, 27), (253, 231, 37),
];

const fn gen_heatmap(colors: [(u8, u8, u8); 16])
        -> [(u8, u8, u8); PALETTE_LEN] {
    let mut lut = [(0u8, 0u8, 0u8); PALETTE_LEN];
    let mut i = 0;
    while i < PX_INTENSITY_MAX {
        let mut h = 0;
        while h < PX_HUE_MAX {
            lut[i * PX_HUE_MAX + h] = colors[i];
            h += 1;
        }
        i += 1;
    }
    lut
}

const fn gen_hueswap() -> [(u8, u8, u8); PALETTE_LEN] {
    let mut lut = [(0u8, 0u8, 0u8); PALETTE_LEN];
    let mut i = 0;
    while i < PX_INTENSITY_MAX {
        let mut h = 0;
        while h < PX_HUE_MAX {
            lut[i * PX_HUE_MAX + h] = if i == 0 {
                (0, 0, 0)
            } else {
                hsl2rgb(
                    i as f64 / PX_INTENSITY_MAX as f64, 0.9,
                    h as f64 / PX_HUE_MAX as f64)
            };
            h += 1;
        }
        i += 1;
    }
    lut
}

static PALETTE_EXP:      [(u8, u8, u8); PALETTE_LEN] = gen_exp();
static PALETTE_LINEAR:   [(u8, u8, u8); PALETTE_LEN] = gen_linear();
static PALETTE_DIM:      [(u8, u8, u8); PALETTE_LEN] = gen_dim();
static PALETTE_GRAY:     [(u8, u8, u8); PALETTE_LEN] = gen_gray();
static PALETTE_INV_GRAY: [(u8, u8, u8); PALETTE_LEN] = gen_inv_gray();
static PALETTE_INFERNO:  [(u8, u8, u8); PALETTE_LEN] = gen_heatmap(INFERNO_16);
static PALETTE_HUESWAP:  [(u8, u8, u8); PALETTE_LEN] = gen_hueswap();
static PALETTE_MAGMA:    [(u8, u8, u8); PALETTE_LEN] = gen_heatmap(MAGMA_16);
static PALETTE_PLASMA:   [(u8, u8, u8); PALETTE_LEN] = gen_heatmap(PLASMA_16);
static PALETTE_VIRIDIS:  [(u8, u8, u8); PALETTE_LEN] = gen_heatmap(VIRIDIS_16);

impl ColorPalette {
    fn lut(&self) -> &'static [(u8, u8, u8); PALETTE_LEN] {
        match self {
            ColorPalette::Exp      => &PALETTE_EXP,
            ColorPalette::Linear   => &PALETTE_LINEAR,
            ColorPalette::Dim      => &PALETTE_DIM,
            ColorPalette::Gray     => &PALETTE_GRAY,
            ColorPalette::InvGray  => &PALETTE_INV_GRAY,
            ColorPalette::Inferno  => &PALETTE_INFERNO,
            ColorPalette::Hueswap  => &PALETTE_HUESWAP,
            ColorPalette::Magma    => &PALETTE_MAGMA,
            ColorPalette::Plasma   => &PALETTE_PLASMA,
            ColorPalette::Viridis  => &PALETTE_VIRIDIS,
        }
    }

    /// Return the scalar heat-map color for one four-bit intensity. SPECTO
    /// uses this to populate hue-rotated columns while ordinary users can
    /// continue programming the palette through `write_to_hardware`.
    pub fn heatmap_color(&self, intensity: u8) -> Option<(u8, u8, u8)> {
        let index = (intensity & 0x0f) as usize;
        match self {
            ColorPalette::Inferno => Some(INFERNO_16[index]),
            ColorPalette::Magma => Some(MAGMA_16[index]),
            ColorPalette::Plasma => Some(PLASMA_16[index]),
            ColorPalette::Viridis => Some(VIRIDIS_16[index]),
            _ => None,
        }
    }

    pub fn write_to_hardware(&self, video: &mut impl DMAFramebuffer) {
        let lut = self.lut();
        for i in 0..PX_INTENSITY_MAX {
            for h in 0..PX_HUE_MAX {
                let (r, g, b) = lut[i * PX_HUE_MAX + h];
                video.set_palette_rgb(i as u8, h as u8, r, g, b);
            }
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use image::{ImageBuffer, RgbImage, Rgb};
    use strum::IntoEnumIterator;

    const BLOCK_SIZE: u32 = 8;

    /// Test to draw every pallette to an image file for previewing.
    #[test]
    fn test_plot_all_palettes() {
        let width = PX_HUE_MAX as u32 * BLOCK_SIZE;
        let height = PX_INTENSITY_MAX as u32 * BLOCK_SIZE;
        for palette in ColorPalette::iter() {
            let mut img: RgbImage = ImageBuffer::new(width, height);
            for h in 0..PX_HUE_MAX {
                for i in 0..PX_INTENSITY_MAX {
                    let (r, g, b) = palette.lut()[i * PX_HUE_MAX + h];
                    let pixel = Rgb([r, g, b]);
                    let x_start = h as u32 * BLOCK_SIZE;
                    let y_start = (PX_INTENSITY_MAX as u32 - 1 - i as u32) * BLOCK_SIZE;
                    for dy in 0..BLOCK_SIZE {
                        for dx in 0..BLOCK_SIZE {
                            img.put_pixel(x_start + dx, y_start + dy, pixel);
                        }
                    }
                }
            }

            let palette_name: &'static str = palette.into();
            let filename = format!("palette_{}.png", palette_name);
            img.save(&filename).unwrap();
        }
    }
}
