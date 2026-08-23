#![no_std]

/// Binary positions corresponding to the CPU-less UI's initial Gray masks.
pub const GROUP_INDEX_DEFAULTS: [u32; 10] = [1, 1, 1, 3, 3, 3, 7, 7, 7, 15];

pub const fn gray_encode(index: u32) -> u32 {
    index ^ (index >> 1)
}

pub fn step_group_index(index: u32, delta: i32) -> u32 {
    (index as i32 + delta).rem_euclid(16) as u32
}

/// Apply one or more coarse 1/256 UI steps to a 16-bit control value.
pub fn clamp_control(value: u32, delta: i32, lo: u32, hi: u32) -> u32 {
    (value as i32 + delta * 256).clamp(lo as i32, hi as i32) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn group_defaults_match_cpu_less_masks() {
        let masks = GROUP_INDEX_DEFAULTS.map(gray_encode);
        assert_eq!(masks, [1, 1, 1, 2, 2, 2, 4, 4, 4, 8]);
    }

    #[test]
    fn group_cycle_visits_every_mask_and_wraps() {
        let mut index = 0;
        let mut seen = 0u16;
        for _ in 0..16 {
            seen |= 1 << gray_encode(index);
            index = step_group_index(index, 1);
        }
        assert_eq!(seen, u16::MAX);
        assert_eq!(index, 0);
        assert_eq!(step_group_index(0, -1), 15);
    }

    #[test]
    fn scalar_steps_match_cpu_less_coarse_ranges() {
        assert_eq!(clamp_control(0x2000, 1, 0, 0x8000), 0x2100);
        assert_eq!(clamp_control(0x2000, -1, 0, 0x8000), 0x1f00);
        assert_eq!(clamp_control(0x8000, 1, 0, 0x8000), 0x8000);
        assert_eq!(clamp_control(0, -1, 0, 0x8000), 0);

        assert_eq!(clamp_control(0x2000, -64, 0x1000, 0x8000), 0x1000);
        assert_eq!(clamp_control(0x7000, 32, 0x1000, 0x8000), 0x8000);
        assert_eq!(clamp_control(0x2000, 128, 0, 0x5fff), 0x5fff);

    }
}
