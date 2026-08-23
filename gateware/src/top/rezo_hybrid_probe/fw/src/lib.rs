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

pub const ACCEL_WINDOW_LOOPS: u8 = 60;
pub const MAX_ACCEL_LEVEL: u8 = 3;

/// Mirror the CPU-less UI's progressive 1x..4x edit acceleration.
pub fn progressive_edit_level(
    idle_loops: u8,
    current_level: u8,
    continuous: bool,
    same_direction: bool,
) -> u8 {
    if continuous && same_direction && idle_loops < ACCEL_WINDOW_LOOPS {
        current_level.saturating_add(1).min(MAX_ACCEL_LEVEL)
    } else {
        0
    }
}

pub fn pack_bits(words: &mut [u16], bit: &mut usize, value: u32, width: usize) {
    for n in 0..width {
        if value & (1 << n) != 0 {
            words[*bit >> 4] |= 1 << (*bit & 15);
        }
        *bit += 1;
    }
}

pub fn unpack_bits(words: &[u16], bit: &mut usize, width: usize) -> u32 {
    let mut value = 0;
    for n in 0..width {
        value |= (((words[*bit >> 4] >> (*bit & 15)) & 1) as u32) << n;
        *bit += 1;
    }
    value
}

pub fn crc32_bzip2_update(mut crc: u32, byte: u8) -> u32 {
    crc ^= (byte as u32) << 24;
    for _ in 0..8 {
        crc = if crc & 0x8000_0000 != 0 {
            (crc << 1) ^ 0x04c1_1db7
        } else {
            crc << 1
        };
    }
    crc
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

    #[test]
    fn acceleration_is_precise_then_progressive_and_bounded() {
        assert_eq!(progressive_edit_level(u8::MAX, 3, true, true), 0);
        assert_eq!(progressive_edit_level(0, 0, true, true), 1);
        assert_eq!(progressive_edit_level(0, 1, true, true), 2);
        assert_eq!(progressive_edit_level(0, 2, true, true), 3);
        assert_eq!(progressive_edit_level(0, 3, true, true), 3);
        assert_eq!(progressive_edit_level(0, 3, false, true), 0);
        assert_eq!(progressive_edit_level(0, 3, true, false), 0);
    }

    #[test]
    fn packed_fields_cross_word_boundaries() {
        let mut words = [0u16; 3];
        let mut bit = 0;
        pack_bits(&mut words, &mut bit, 0x15, 5);
        pack_bits(&mut words, &mut bit, 0xabc, 12);
        pack_bits(&mut words, &mut bit, 0x5a, 8);
        assert_eq!(bit, 25);
        bit = 0;
        assert_eq!(unpack_bits(&words, &mut bit, 5), 0x15);
        assert_eq!(unpack_bits(&words, &mut bit, 12), 0xabc);
        assert_eq!(unpack_bits(&words, &mut bit, 8), 0x5a);
    }

    #[test]
    fn crc_matches_rezo_journal_contract() {
        let mut crc = 0xffff_ffff;
        for byte in b"123456789" {
            crc = crc32_bzip2_update(crc, *byte);
        }
        assert_eq!(crc ^ 0xffff_ffff, 0xfc89_1918);
    }
}
