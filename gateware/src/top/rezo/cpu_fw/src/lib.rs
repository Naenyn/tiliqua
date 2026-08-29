#![no_std]

use core::ptr::{read_volatile, write_volatile};

pub const ENCODER_STEP: usize = 0xF000_0600;
pub const ENCODER_BUTTON: usize = 0xF000_0601;
pub const FLASH_SLOT: usize = 0xF000_1208;

const UI_COMMAND: usize = 0xF000_1000;
const FLASH_COMMAND: usize = 0xF000_1200;
const FLASH_STATUS: usize = FLASH_COMMAND + 4;
const FLASH_READ: u32 = 1;
const FLASH_PROGRAM: u32 = 2;
const FLASH_ERASE: u32 = 3;
const FLASH_READ_TIMEOUT_POLLS: u32 = 1_000_000;
const FLASH_WRITE_TIMEOUT_POLLS: u32 = 12_000_000;

unsafe fn write32(address: usize, value: u32) {
    write_volatile(address as *mut u32, value);
}

pub unsafe fn read8(address: usize) -> u8 {
    read_volatile(address as *const u8)
}

pub unsafe fn read32(address: usize) -> u32 {
    read_volatile(address as *const u32)
}

pub const fn ui_command_word<const INDEX_BITS: u32>(kind: u32, index: usize, value: u32) -> u32 {
    kind | ((index as u32) << INDEX_BITS) | ((value & 0xffff) << (INDEX_BITS + 5))
}

pub unsafe fn write_ui_command<const INDEX_BITS: u32>(kind: u32, index: usize, value: u32) {
    write32(
        UI_COMMAND,
        ui_command_word::<INDEX_BITS>(kind, index, value),
    );
}

pub const fn flash_command_word(operation: u32, sector: u8, offset: u16, data: u8) -> u32 {
    operation
        | (((sector as u32) & 1) << 2)
        | (((offset as u32) & 0x0fff) << 3)
        | ((data as u32) << 15)
}

unsafe fn flash_operation(operation: u32, sector: u8, offset: u16, data: u8) -> Option<u8> {
    write32(
        FLASH_COMMAND,
        flash_command_word(operation, sector, offset, data),
    );
    let timeout = if operation == FLASH_READ {
        FLASH_READ_TIMEOUT_POLLS
    } else {
        FLASH_WRITE_TIMEOUT_POLLS
    };
    for _ in 0..timeout {
        let status = read32(FLASH_STATUS);
        if status & 1 == 0 && status & 2 != 0 {
            return if status & 4 == 0 {
                Some(((status >> 3) & 0xff) as u8)
            } else {
                None
            };
        }
    }
    None
}

pub unsafe fn flash_read(sector: u8, offset: u16) -> Option<u8> {
    flash_operation(FLASH_READ, sector, offset, 0)
}

pub unsafe fn flash_program(sector: u8, offset: u16, data: u8) -> bool {
    flash_operation(FLASH_PROGRAM, sector, offset, data).is_some()
}

pub unsafe fn flash_erase(sector: u8) -> bool {
    flash_operation(FLASH_ERASE, sector, 0, 0).is_some()
}

/// Binary positions corresponding to the CPU-less UI's initial Gray masks.
pub const GROUP_INDEX_DEFAULTS: [u32; 10] = [1, 1, 1, 3, 3, 3, 7, 7, 7, 15];

pub const fn gray_encode(index: u32) -> u32 {
    index ^ (index >> 1)
}

pub fn step_group_index(index: u32, delta: i32) -> u32 {
    (index as i32 + delta).rem_euclid(16) as u32
}

/// Move through one circular navigation list in encoder direction order.
pub fn step_target(current: u8, targets: &[u8], direction: i8) -> u8 {
    let position = targets
        .iter()
        .position(|target| *target == current)
        .unwrap_or(0);
    let next = if direction > 0 {
        (position + 1) % targets.len()
    } else if position == 0 {
        targets.len() - 1
    } else {
        position - 1
    };
    targets[next]
}

/// Apply one or more coarse 1/256 UI steps to a 16-bit control value.
pub fn clamp_control(value: u32, delta: i32, lo: u32, hi: u32) -> u32 {
    (value as i32 + delta * 256).clamp(lo as i32, hi as i32) as u32
}

pub fn add(value: u32, delta: i32, lo: u32, hi: u32) -> u32 {
    (value as i32 + delta).clamp(lo as i32, hi as i32) as u32
}

pub fn adds(value: i32, delta: i32, lo: i32, hi: i32) -> i32 {
    (value + delta).clamp(lo, hi)
}

/// Step the editable high byte of a 16-bit value without disturbing its
/// precision byte. REZO input gain keeps 0xCC in that byte so exact unity and
/// the CPU-less endpoint behavior survive every encoder edit.
pub fn step_coarse_byte(value: u32, delta: i32) -> u32 {
    let coarse = ((value >> 8) as i32 + delta).clamp(0, 255) as u32;
    (coarse << 8) | (value & 0xff)
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

pub fn read_u16(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([bytes[offset], bytes[offset + 1]])
}

pub fn read_u32(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([
        bytes[offset],
        bytes[offset + 1],
        bytes[offset + 2],
        bytes[offset + 3],
    ])
}

pub fn write_u16(bytes: &mut [u8], offset: usize, value: u16) {
    bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}

pub fn write_u32(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

/// Calculate the CRC for a REZO-family journal record. All product records
/// share a 16-byte header whose CRC field occupies bytes 12..16.
pub fn record_crc(record: &[u8], words: usize) -> u32 {
    let mut crc = 0xffff_ffff;
    for byte in &record[..12] {
        crc = crc32_bzip2_update(crc, *byte);
    }
    for byte in &record[16..16 + words * 2] {
        crc = crc32_bzip2_update(crc, *byte);
    }
    crc ^ 0xffff_ffff
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
    fn navigation_wraps_and_recovers_from_an_invisible_target() {
        let targets = [0, 4, 7, 9];
        assert_eq!(step_target(0, &targets, 1), 4);
        assert_eq!(step_target(9, &targets, 1), 0);
        assert_eq!(step_target(0, &targets, -1), 9);
        assert_eq!(step_target(4, &targets, -1), 0);
        assert_eq!(step_target(99, &targets, 1), 4);
        assert_eq!(step_target(99, &targets, -1), 9);
    }

    #[test]
    fn scalar_steps_match_cpu_less_coarse_ranges() {
        assert_eq!(add(3, 2, 0, 4), 4);
        assert_eq!(add(3, -5, 0, 4), 0);
        assert_eq!(adds(-3, 2, -4, 4), -1);
        assert_eq!(adds(3, 5, -4, 4), 4);

        assert_eq!(clamp_control(0x2000, 1, 0, 0x8000), 0x2100);
        assert_eq!(clamp_control(0x2000, -1, 0, 0x8000), 0x1f00);
        assert_eq!(clamp_control(0x8000, 1, 0, 0x8000), 0x8000);
        assert_eq!(clamp_control(0, -1, 0, 0x8000), 0);

        assert_eq!(clamp_control(0x2000, -64, 0x1000, 0x8000), 0x1000);
        assert_eq!(clamp_control(0x7000, 32, 0x1000, 0x8000), 0x8000);
        assert_eq!(clamp_control(0x2000, 128, 0, 0x5fff), 0x5fff);

        assert_eq!(step_coarse_byte(0xcccc, 1), 0xcdcc);
        assert_eq!(step_coarse_byte(0xcccc, -1), 0xcbcc);
        assert_eq!(step_coarse_byte(0xffcc, 1), 0xffcc);
        assert_eq!(step_coarse_byte(0x00cc, -1), 0x00cc);
        assert_eq!(step_coarse_byte(0x0000, 255), 0xff00);
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

    #[test]
    fn little_endian_fields_and_record_crc_share_one_contract() {
        let mut record = [0u8; 22];
        write_u16(&mut record, 0, 0x1234);
        write_u32(&mut record, 4, 0x89ab_cdef);
        write_u16(&mut record, 16, 0x5678);
        write_u32(&mut record, 18, 0x0123_4567);
        assert_eq!(read_u16(&record, 0), 0x1234);
        assert_eq!(read_u32(&record, 4), 0x89ab_cdef);
        assert_eq!(read_u16(&record, 16), 0x5678);
        assert_eq!(read_u32(&record, 18), 0x0123_4567);

        let crc = record_crc(&record, 3);
        write_u32(&mut record, 12, crc);
        assert_eq!(record_crc(&record, 3), read_u32(&record, 12));
    }

    #[test]
    fn command_words_preserve_product_index_width_and_flash_layout() {
        assert_eq!(
            ui_command_word::<5>(3, 17, 0xabcd),
            3 | (17 << 5) | (0xabcd << 10)
        );
        assert_eq!(
            ui_command_word::<6>(3, 17, 0xabcd),
            3 | (17 << 6) | (0xabcd << 11)
        );
        assert_eq!(
            flash_command_word(2, 1, 0x0abc, 0x5a),
            2 | 4 | (0xabc << 3) | (0x5a << 15)
        );
    }
}
