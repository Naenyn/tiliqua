#![no_std]
#![no_main]

use core::ptr::{read_volatile, write_volatile};
use panic_halt as _;
use rezo_cpu_fw::{
    clamp_control, crc32_bzip2_update, gray_encode, pack_bits, progressive_edit_level,
    step_coarse_byte, step_group_index, step_target, unpack_bits, GROUP_INDEX_DEFAULTS,
};
use riscv_rt::entry;

const ENCODER_STEP: usize = 0xF000_0600;
const ENCODER_BUTTON: usize = 0xF000_0601;
const UI_COMMAND: usize = 0xF000_1000;
const FLASH_COMMAND: usize = 0xF000_1200;
const FLASH_STATUS: usize = FLASH_COMMAND + 0x04;
const FLASH_SLOT: usize = FLASH_COMMAND + 0x08;
const BAND_ENABLE: u32 = 0;
const BAND_FREQUENCY: u32 = 1;
const INPUT_GAIN: u32 = 2;
const INPUT_MODE: u32 = 3;
const CV_TARGET: u32 = 4;
const CV_DEPTH: u32 = 5;
const BANK_GROUP: u32 = 6;
const FEEDBACK_SEND: u32 = 7;
const OUTPUT_SEND: u32 = 9;
const PAGE_STATE: u32 = 10;
const SELECTED_STATE: u32 = 11;
const PRESET_STATE: u32 = 12;
const PALETTE_STATE: u32 = 13;
const EDITING_STATE: u32 = 14;
const DRIVE_STATE: u32 = 15;
const RESONANCE_STATE: u32 = 16;
const FEEDBACK_STATE: u32 = 17;
const CLOCK_MODE_STATE: u32 = 18;
const CLOCK_ALGORITHM_STATE: u32 = 19;
const DAMP_STATE: u32 = 20;
const KNEE_STATE: u32 = 21;
const CEILING_STATE: u32 = 22;
const SHIFT_DIRECTION_STATE: u32 = 23;
const TURING_LENGTH_STATE: u32 = 24;
const TURING_CHANGE_STATE: u32 = 25;
const LAYOUT_STATE: u32 = 26;
const LAYOUT_PREVIEW_STATE: u32 = 27;
const FREQUENCY_PREVIEW_STATE: u32 = 28;
const LEVEL_STATE: u32 = 29;
const SAVE_STATE: u32 = 30;
const STARTUP_STATE: u32 = 31;
const CLOCK_SOURCE_STATE: u32 = 32;
const DATA_SOURCE_STATE: u32 = 33;
const CLOCK_RATE_STATE: u32 = 34;
const CLOCK_DEPTH_STATE: u32 = 35;
const WALK_STEP_STATE: u32 = 36;
const WALK_STYLE_STATE: u32 = 37;
const WALK_DRUNK_STATE: u32 = 38;
const WALK_CHANCE_STATE: u32 = 39;
const TURING_TARGET_STATE: u32 = 40;
const TURING_START_STATE: u32 = 41;

const FLASH_READ: u32 = 1;
const FLASH_PROGRAM: u32 = 2;
const FLASH_ERASE: u32 = 3;
// Persistence is optional at runtime: a missing slot identity or a wedged SPI
// transaction must never hold the UI and codec mute in their reset state.
// Read commands normally complete in microseconds; this bound leaves ample
// margin while keeping a failed boot scan short. Sector erase needs a much
// larger allowance for the flash chip's internal erase cycle.
const BOOT_SLOT_TIMEOUT_POLLS: u32 = 1_000_000;
const FLASH_READ_TIMEOUT_POLLS: u32 = 1_000_000;
const FLASH_WRITE_TIMEOUT_POLLS: u32 = 12_000_000;
const STATE_WORDS: usize = 46;
const LEGACY_STATE_WORDS: usize = 42;
const HEADER_BYTES: usize = 16;
const RECORD_BYTES: usize = HEADER_BYTES + STATE_WORDS * 2;
const MAGIC: u32 = 0x4f5a4552;
// The CPU and CPU-less implementations share REZOMO's exact V3 schema.
const VERSION: u16 = 3;

const PAGE: u8 = 0;
const PRESET: u8 = 1;
const BAND: u8 = 2;
const DRIVE: u8 = 12;
const RESONANCE: u8 = 13;
const FEEDBACK: u8 = 14;
const KNEE: u8 = 15;
const CEILING: u8 = 16;
const DAMP: u8 = 17;
const INPUT: u8 = 18;
const GROUP: u8 = 30;
const OUTPUT: u8 = 40;
const MODE: u8 = 60;
const SHIFT_DIRECTION: u8 = 61;
const CLOCK_ALGORITHM: u8 = 62;
const TURING_LENGTH: u8 = 63;
const TURING_CHANGE: u8 = 64;
const CLOCK_SOURCE: u8 = 65;
const CLOCK_RATE: u8 = 66;
const CLOCK_DEPTH: u8 = 67;
const TURING_TARGET: u8 = 68;
const TURING_START: u8 = 69;
const DATA_SOURCE: u8 = 70;
const FEEDBACK_ENABLE: u8 = 80;
const PALETTE: u8 = 90;
const SAVE: u8 = 91;
const LAYOUT: u8 = 92;
const ENABLE: u8 = 93;
const FREQUENCY: u8 = 103;

const MAIN_BANK: &[u8] = &[0, 1, 60, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];
const FEEDBACK_PAGE: &[u8] = &[0, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 14, 15, 16, 17];
const GROUP_PAGE: &[u8] = &[0, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39];
const OUTPUT_BANK: &[u8] = &[
    0, 117, 118, 119, 120, 121, 113, 40, 41, 42, 43, 44, 114, 45, 46, 47, 48, 49, 115, 50, 51, 52,
    53, 54, 116, 55, 56, 57, 58, 59,
];
const OPTIONS_PAGE: &[u8] = &[0, 90, 91];
const BANDS_PAGE: &[u8] = &[
    0, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111,
    112,
];
const CLOCK_SHIFT_PAGE: &[u8] = &[0, 62, 61, 65, 66, 67, 70];
const CLOCK_ROTATE_PAGE: &[u8] = &[0, 62, 61, 65, 66, 67];
const CLOCK_TURING_ALL_PAGE: &[u8] = &[0, 62, 61, 65, 66, 67, 64, 68, 63];
const CLOCK_TURING_RANGE_PAGE: &[u8] = &[0, 62, 61, 65, 66, 67, 64, 68, 69, 63];
const CLOCK_WALK_PAGE: &[u8] = &[0, 62, 65, 66, 67, 68, 63, 64];
const LEGACY_FREQUENCIES: [u32; 10] = [0, 12, 20, 32, 44, 56, 68, 84, 92, 104];
const OCTAVE_FREQUENCIES: [u32; 10] = [4, 16, 24, 36, 48, 60, 76, 88, 100, 112];
const PERCEPT_FREQUENCIES: [u32; 10] = [8, 28, 40, 48, 52, 64, 72, 80, 96, 108];

const OUTPUT_BANK_DEFAULTS: [u32; 20] = [
    16, 16, 16, 16, 0, 16, 0, 16, 0, 0, 0, 16, 0, 16, 0, 0, 0, 0, 0, 16,
];
const LEGACY_OUTPUT_DEFAULTS: [u32; 20] = [
    16, 16, 16, 16, 0, 16, 0, 16, 0, 0, 0, 16, 0, 16, 0, 0, 0, 0, 0, 0,
];

unsafe fn write32(address: usize, value: u32) {
    write_volatile(address as *mut u32, value);
}
unsafe fn read8(address: usize) -> u8 {
    read_volatile(address as *const u8)
}
unsafe fn read32(address: usize) -> u32 {
    read_volatile(address as *const u32)
}
unsafe fn ui_write(kind: u32, index: usize, value: u32) {
    write32(
        UI_COMMAND,
        kind | ((index as u32) << 6) | ((value & 0xFFFF) << 11),
    );
}

unsafe fn flash_operation(operation: u32, sector: u8, offset: u16, data: u8) -> Option<u8> {
    let command = operation
        | (((sector as u32) & 1) << 2)
        | (((offset as u32) & 0x0fff) << 3)
        | ((data as u32) << 15);
    write32(FLASH_COMMAND, command);
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

unsafe fn flash_read(sector: u8, offset: u16) -> Option<u8> {
    flash_operation(FLASH_READ, sector, offset, 0)
}

unsafe fn flash_program(sector: u8, offset: u16, data: u8) -> bool {
    flash_operation(FLASH_PROGRAM, sector, offset, data).is_some()
}

unsafe fn flash_erase(sector: u8) -> bool {
    flash_operation(FLASH_ERASE, sector, 0, 0).is_some()
}

fn record_crc(record: &[u8; RECORD_BYTES], words: usize) -> u32 {
    let mut crc = 0xffff_ffff;
    for byte in &record[..12] {
        crc = crc32_bzip2_update(crc, *byte);
    }
    for byte in &record[HEADER_BYTES..HEADER_BYTES + words * 2] {
        crc = crc32_bzip2_update(crc, *byte);
    }
    crc ^ 0xffff_ffff
}

fn read_u16(bytes: &[u8], offset: usize) -> u16 {
    u16::from_le_bytes([bytes[offset], bytes[offset + 1]])
}

fn read_u32(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([
        bytes[offset],
        bytes[offset + 1],
        bytes[offset + 2],
        bytes[offset + 3],
    ])
}

fn write_u16(bytes: &mut [u8], offset: usize, value: u16) {
    bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}

fn write_u32(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn legacy_band_config_words() -> [u16; 4] {
    let mut words = [0u16; 4];
    let mut bit = 0;
    for frequency in LEGACY_FREQUENCIES {
        pack_bits(&mut words, &mut bit, frequency >> 2, 5);
    }
    for _ in 0..10 {
        pack_bits(&mut words, &mut bit, 1, 1);
    }
    pack_bits(&mut words, &mut bit, 0, 2);
    words
}

fn legacy_clock_config_words() -> [u16; 3] {
    let mut words = [0u16; 3];
    let mut bit = 0;
    for (value, width) in [
        (0, 1),
        (0, 2),
        (0, 2),
        (10, 4),
        (3, 3),
        (0, 2),
        (5, 3),
        (128, 8),
        (0, 1),
        (0, 4),
        (0, 2),
        (0, 4),
        (2, 3),
        (0, 1),
        (0, 2),
        (2, 3),
    ] {
        pack_bits(&mut words, &mut bit, value, width);
    }
    debug_assert_eq!(bit, 45);
    words
}

unsafe fn scan_sector(
    sector: u8,
    record: &mut [u8; RECORD_BYTES],
    words: &mut [u16; STATE_WORDS],
) -> Option<u32> {
    for (offset, byte) in record[..HEADER_BYTES].iter_mut().enumerate() {
        *byte = flash_read(sector, offset as u16)?;
    }
    if read_u32(record, 0) != MAGIC {
        return None;
    }
    let version = read_u16(record, 4);
    let declared_words = read_u16(record, 6) as usize;
    let accepted = ((version == VERSION || version == 2) && declared_words == STATE_WORDS)
        || (version == 1 && declared_words == LEGACY_STATE_WORDS);
    if !accepted {
        return None;
    }
    for offset in HEADER_BYTES..HEADER_BYTES + declared_words * 2 {
        record[offset] = flash_read(sector, offset as u16)?;
    }
    if record_crc(record, declared_words) != read_u32(record, 12) {
        return None;
    }
    words.fill(0);
    for (n, word) in words[..declared_words].iter_mut().enumerate() {
        *word = read_u16(record, HEADER_BYTES + 2 * n);
    }
    if declared_words == LEGACY_STATE_WORDS {
        words[LEGACY_STATE_WORDS..].copy_from_slice(&legacy_band_config_words());
    }
    if version < VERSION {
        let defaults = legacy_clock_config_words();
        words[10..13].copy_from_slice(&defaults);
    }
    Some(read_u32(record, 8))
}

unsafe fn save_sector(
    sector: u8,
    generation: u32,
    words: &[u16; STATE_WORDS],
    record: &mut [u8; RECORD_BYTES],
) -> bool {
    record.fill(0);
    write_u32(record, 0, MAGIC);
    write_u16(record, 4, VERSION);
    write_u16(record, 6, STATE_WORDS as u16);
    write_u32(record, 8, generation);
    for (n, word) in words.iter().enumerate() {
        write_u16(record, HEADER_BYTES + 2 * n, *word);
    }
    let crc = record_crc(record, STATE_WORDS);
    write_u32(record, 12, crc);
    if !flash_erase(sector) {
        return false;
    }
    for (offset, byte) in record.iter().enumerate() {
        if !flash_program(sector, offset as u16, *byte) {
            return false;
        }
    }
    true
}
fn add(value: u32, delta: i32, lo: u32, hi: u32) -> u32 {
    (value as i32 + delta).clamp(lo as i32, hi as i32) as u32
}
fn adds(value: i32, delta: i32, lo: i32, hi: i32) -> i32 {
    (value + delta).clamp(lo, hi)
}
struct State {
    page: u8,
    selected: u8,
    preset: u8,
    palette: u8,
    editing: bool,
    bank_drive: u32,
    resonance: u32,
    bank_feedback: u32,
    damp: u32,
    knee: u32,
    ceiling: u32,
    clock_mode: bool,
    clock_algorithm: u32,
    shift_direction: u32,
    turing_length: u32,
    turing_change_index: u32,
    clock_source: u32,
    data_source: u32,
    internal_clock_rate: u32,
    clock_depth: u32,
    walk_step_index: u32,
    walk_style: u32,
    walk_drunk: u32,
    walk_chance_index: u32,
    turing_target: u32,
    turing_start: u32,
    clock_roles_initialized: bool,
    layout: u32,
    layout_preview: u32,
    frequency_preview: u32,
    levels: [i32; 10],
    enables: [u32; 10],
    frequencies: [u32; 10],
    input_gains: [u32; 4],
    input_modes: [u32; 4],
    cv_targets: [u32; 4],
    cv_depths: [i32; 4],
    group_indices: [u32; 10],
    feedback_sends: [u32; 10],
    bank_output_sends: [u32; 20],
    legacy_output_sends: [u32; 20],
}

impl State {
    const fn new() -> Self {
        Self {
            page: 0,
            selected: 0,
            preset: 0,
            palette: 0,
            editing: false,
            bank_drive: 0x2000,
            resonance: 0x2000,
            bank_feedback: 0,
            damp: 3,
            knee: 0x2000,
            ceiling: 0x7000,
            clock_mode: false,
            clock_algorithm: 0,
            shift_direction: 0,
            turing_length: 10,
            turing_change_index: 3,
            clock_source: 0,
            data_source: 0,
            internal_clock_rate: 120,
            clock_depth: 128,
            walk_step_index: 2,
            walk_style: 0,
            walk_drunk: 0,
            walk_chance_index: 2,
            turing_target: 0,
            turing_start: 0,
            clock_roles_initialized: false,
            layout: 1,
            layout_preview: 1,
            frequency_preview: 0,
            levels: [0x2000; 10],
            enables: [1; 10],
            frequencies: OCTAVE_FREQUENCIES,
            input_gains: [0xCCCC, 0, 0, 0],
            input_modes: [0, 1, 1, 1],
            cv_targets: [1, 1, 2, 0],
            cv_depths: [0; 4],
            // The hardware UI walks a four-bit binary index and presents its
            // Gray-coded value as the group mask.  Keep the same internal
            // representation here so all sixteen group combinations remain
            // reachable in the same order.
            group_indices: GROUP_INDEX_DEFAULTS,
            feedback_sends: [1; 10],
            bank_output_sends: OUTPUT_BANK_DEFAULTS,
            legacy_output_sends: LEGACY_OUTPUT_DEFAULTS,
        }
    }

    fn drive(&self) -> u32 {
        self.bank_drive
    }

    fn feedback(&self) -> u32 {
        self.bank_feedback
    }

    fn apply_preset(&mut self) {
        for n in 0..10 {
            self.levels[n] = match self.preset {
                0 => 0x2000,
                1 if n & 1 != 0 => 0x2000,
                2 if n & 1 == 0 => 0x2000,
                3 if n < 4 => 0x2000,
                4 if (3..=6).contains(&n) => 0x2000,
                5 if n >= 6 => 0x2000,
                _ => 0,
            };
        }
    }

    fn apply_layout(&mut self) {
        let frequencies = match self.layout_preview {
            0 => Some(&LEGACY_FREQUENCIES),
            1 => Some(&OCTAVE_FREQUENCIES),
            2 => Some(&PERCEPT_FREQUENCIES),
            _ => None,
        };
        if let Some(frequencies) = frequencies {
            self.frequencies.copy_from_slice(frequencies);
        }
        self.layout = self.layout_preview;
    }

    fn edit_output_row(&mut self, row: usize, delta: i32) {
        for column in 0..5 {
            let n = row * 5 + column;
            self.bank_output_sends[n] = add(self.bank_output_sends[n], delta, 0, 16);
        }
    }

    fn edit_output_column(&mut self, column: usize, delta: i32) {
        for row in 0..4 {
            let n = row * 5 + column;
            self.bank_output_sends[n] = add(self.bank_output_sends[n], delta, 0, 16);
        }
    }

    fn targets(&self) -> &'static [u8] {
        match self.page {
            0 => MAIN_BANK,
            1 => FEEDBACK_PAGE,
            3 => GROUP_PAGE,
            4 => OUTPUT_BANK,
            5 => OPTIONS_PAGE,
            6 => BANDS_PAGE,
            7 if self.clock_algorithm == 0 => CLOCK_SHIFT_PAGE,
            7 if self.clock_algorithm == 1 => CLOCK_ROTATE_PAGE,
            7 if self.clock_algorithm == 2 && self.turing_target != 0 => CLOCK_TURING_RANGE_PAGE,
            7 if self.clock_algorithm == 2 => CLOCK_TURING_ALL_PAGE,
            7 => CLOCK_WALK_PAGE,
            _ => OPTIONS_PAGE,
        }
    }

    fn navigate(&mut self, direction: i8) {
        if self.page == 2 {
            // AUDIO lanes expose MODE and GAIN. CV lanes expose MODE, TARGET,
            // and DEPTH. Match the CPU-less conditional navigation exactly.
            let mut input_targets = [0u8; 13];
            let mut len = 1;
            for lane in 0..4 {
                let target = INPUT + lane * 3;
                input_targets[len] = target;
                input_targets[len + 1] = target + 1;
                len += 2;
                if self.input_modes[lane as usize] != 0 {
                    input_targets[len] = target + 2;
                    len += 1;
                }
            }
            self.selected = step_target(self.selected, &input_targets[..len], direction);
            return;
        }
        let targets = self.targets();
        self.selected = step_target(self.selected, targets, direction);
    }

    fn change_page(&mut self, direction: i8) {
        const BANK: &[u8] = &[0, 6, 2, 3, 4, 1, 5];
        const CLOCK: &[u8] = &[0, 7, 6, 2, 3, 4, 1, 5];
        let order = if self.clock_mode { CLOCK } else { BANK };
        let p = order.iter().position(|x| *x == self.page).unwrap_or(0);
        let p = if direction > 0 {
            (p + 1) % order.len()
        } else if p == 0 {
            order.len() - 1
        } else {
            p - 1
        };
        self.page = order[p];
    }

    fn click(&mut self) -> bool {
        if (FEEDBACK_ENABLE..FEEDBACK_ENABLE + 10).contains(&self.selected) {
            let n = (self.selected - FEEDBACK_ENABLE) as usize;
            if self.enables[n] != 0 {
                self.feedback_sends[n] ^= 1;
            }
        } else if (ENABLE..ENABLE + 10).contains(&self.selected) {
            let n = (self.selected - ENABLE) as usize;
            self.enables[n] ^= 1;
        } else if self.selected == SAVE {
            return true;
        } else if self.editing {
            match self.selected {
                PRESET => self.apply_preset(),
                LAYOUT => self.apply_layout(),
                t if (FREQUENCY..FREQUENCY + 10).contains(&t) => {
                    let n = (t - FREQUENCY) as usize;
                    self.frequencies[n] = self.frequency_preview;
                    self.layout = 3;
                    self.layout_preview = 3;
                }
                _ => {}
            }
            self.editing = false;
        } else {
            let disabled_bank_band = if (BAND..BAND + 10).contains(&self.selected) {
                self.enables[(self.selected - BAND) as usize] == 0
            } else if (GROUP..GROUP + 10).contains(&self.selected) {
                self.enables[(self.selected - GROUP) as usize] == 0
            } else {
                false
            };
            if disabled_bank_band {
                return false;
            }
            if self.selected == LAYOUT {
                self.layout_preview = self.layout;
            } else if (FREQUENCY..FREQUENCY + 10).contains(&self.selected) {
                self.frequency_preview = self.frequencies[(self.selected - FREQUENCY) as usize];
            }
            self.editing = true;
        }
        false
    }

    fn edit(&mut self, direction: i8) {
        let d = direction as i32;
        match self.selected {
            PAGE => self.change_page(direction),
            PRESET => self.preset = (self.preset as i32 + d).rem_euclid(7) as u8,
            DRIVE => self.bank_drive = clamp_control(self.bank_drive, d, 0, 0x5FFF),
            RESONANCE => self.resonance = clamp_control(self.resonance, d, 0, 0x8000),
            FEEDBACK => self.bank_feedback = clamp_control(self.bank_feedback, d, 0, 0x8000),
            KNEE => self.knee = clamp_control(self.knee, d, 0x1000, 0x8000),
            CEILING => self.ceiling = clamp_control(self.ceiling, d, 0x1000, 0x8000),
            DAMP => self.damp = (self.damp as i32 + d).clamp(0, 4) as u32,
            MODE => {
                self.clock_mode = !self.clock_mode;
                if self.clock_mode && !self.clock_roles_initialized {
                    self.clock_roles_initialized = true;
                    if !self.cv_targets.iter().any(|target| *target >= 7) {
                        self.input_modes[1..].fill(1);
                        self.cv_targets[1] = 8;
                        self.cv_targets[2] = 9;
                        self.cv_targets[3] = 7;
                    }
                }
            }
            CLOCK_ALGORITHM => {
                self.clock_algorithm = (self.clock_algorithm as i32 + d).rem_euclid(4) as u32;
                self.shift_direction = 0;
                self.walk_step_index = 2;
            }
            SHIFT_DIRECTION => {
                let values: &[u32] = match self.clock_algorithm {
                    0 => &[0, 1, 3],
                    1 => &[0, 1],
                    2 => &[0, 1, 2],
                    _ => &[0],
                };
                let position = values
                    .iter()
                    .position(|value| *value == self.shift_direction)
                    .unwrap_or(0) as i32;
                self.shift_direction =
                    values[(position + d).rem_euclid(values.len() as i32) as usize];
            }
            CLOCK_SOURCE => self.clock_source = (self.clock_source as i32 + d).rem_euclid(3) as u32,
            DATA_SOURCE => self.data_source = (self.data_source as i32 + d).rem_euclid(3) as u32,
            CLOCK_RATE => self.internal_clock_rate = add(self.internal_clock_rate, d, 15, 300),
            CLOCK_DEPTH => self.clock_depth = add(self.clock_depth, d, 0, 128),
            TURING_CHANGE if self.clock_algorithm == 3 => {
                self.walk_chance_index = (self.walk_chance_index as i32 + d).rem_euclid(6) as u32
            }
            TURING_CHANGE => {
                self.turing_change_index =
                    (self.turing_change_index as i32 + d).rem_euclid(7) as u32
            }
            TURING_TARGET if self.clock_algorithm == 3 => self.walk_style ^= 1,
            TURING_TARGET => self.turing_target ^= 1,
            TURING_LENGTH if self.clock_algorithm == 3 => {
                self.walk_drunk = (self.walk_drunk as i32 + d).rem_euclid(4) as u32
            }
            TURING_LENGTH => {
                self.turing_length = (self.turing_length as i32 - 2 + d).rem_euclid(9) as u32 + 2;
                if self.turing_start + self.turing_length > 10 {
                    self.turing_start = 10 - self.turing_length;
                }
            }
            TURING_START => {
                if d > 0 {
                    if self.turing_start >= 8 {
                        self.turing_start = 0;
                    } else {
                        if self.turing_start + self.turing_length >= 10 {
                            self.turing_length = 9 - self.turing_start;
                        }
                        self.turing_start += 1;
                    }
                } else if self.turing_start == 0 {
                    self.turing_start = 8;
                    self.turing_length = 2;
                } else {
                    self.turing_start -= 1;
                }
            }
            PALETTE => self.palette = (self.palette as i32 + d).rem_euclid(8) as u8,
            LAYOUT => self.layout_preview = (self.layout_preview as i32 + d).rem_euclid(4) as u32,
            t if (BAND..BAND + 10).contains(&t) => {
                let n = (t - BAND) as usize;
                self.levels[n] = adds(self.levels[n], d * 256, -0x4000, 0x3FFF);
            }
            t if (FREQUENCY..FREQUENCY + 10).contains(&t) => {
                self.frequency_preview = add(self.frequency_preview, d, 0, 115);
            }
            t if (INPUT..INPUT + 12).contains(&t) => {
                let field = (t - INPUT) as usize;
                let n = field / 3;
                match field % 3 {
                    0 => {
                        self.input_modes[n] ^= 1;
                    }
                    1 if self.input_modes[n] == 0 => {
                        self.input_gains[n] = step_coarse_byte(self.input_gains[n], d);
                    }
                    1 => {
                        self.cv_targets[n] = (self.cv_targets[n] as i32 + d).rem_euclid(11) as u32;
                    }
                    _ => {
                        self.cv_depths[n] = adds(self.cv_depths[n], d * 256, -0x8000, 0x7F00);
                    }
                }
            }
            t if (GROUP..GROUP + 10).contains(&t) => {
                let n = (t - GROUP) as usize;
                self.group_indices[n] = step_group_index(self.group_indices[n], d);
            }
            t if (OUTPUT..OUTPUT + 20).contains(&t) => {
                let n = (t - OUTPUT) as usize;
                self.bank_output_sends[n] = add(self.bank_output_sends[n], d, 0, 16);
            }
            t if (113..117).contains(&t) => self.edit_output_row((t - 113) as usize, d),
            t if (117..121).contains(&t) => self.edit_output_column((t - 117) as usize, d),
            121 => self.edit_output_column(4, d),
            _ => {}
        }
    }

    fn pack_words(&self) -> [u16; STATE_WORDS] {
        let mut words = [0u16; STATE_WORDS];
        let mut bit = 0;
        for level in self.levels {
            let coarse = if level == 0x3fff {
                64
            } else {
                (level >> 8) as u8 as u32
            };
            pack_bits(&mut words, &mut bit, coarse, 8);
        }
        let bank_drive = if self.bank_drive == 0x5fff {
            96
        } else {
            self.bank_drive >> 8
        };
        pack_bits(&mut words, &mut bit, bank_drive, 8);
        pack_bits(&mut words, &mut bit, 32, 8); // reserved legacy drive
        pack_bits(&mut words, &mut bit, self.resonance >> 8, 8);
        pack_bits(&mut words, &mut bit, self.bank_feedback >> 8, 8);
        pack_bits(&mut words, &mut bit, 64, 8); // reserved cutoff
        pack_bits(&mut words, &mut bit, 64, 8); // reserved slope
        pack_bits(&mut words, &mut bit, 48, 8); // reserved width
        pack_bits(&mut words, &mut bit, self.knee >> 8, 8);
        pack_bits(&mut words, &mut bit, self.ceiling >> 8, 8);
        pack_bits(&mut words, &mut bit, self.damp, 3);
        pack_bits(&mut words, &mut bit, 0, 1); // reserved legacy mode
        pack_bits(&mut words, &mut bit, 0, 2); // reserved legacy type
        pack_bits(&mut words, &mut bit, self.frequencies[0] & 3, 2);
        pack_bits(&mut words, &mut bit, self.clock_mode as u32, 1);
        pack_bits(&mut words, &mut bit, self.clock_algorithm, 2);
        pack_bits(&mut words, &mut bit, self.shift_direction, 2);
        pack_bits(&mut words, &mut bit, self.turing_length, 4);
        pack_bits(&mut words, &mut bit, self.turing_change_index, 3);
        pack_bits(&mut words, &mut bit, self.clock_source, 2);
        pack_bits(&mut words, &mut bit, self.internal_clock_rate & 7, 3);
        pack_bits(&mut words, &mut bit, self.clock_depth, 8);
        pack_bits(&mut words, &mut bit, self.turing_target, 1);
        pack_bits(&mut words, &mut bit, self.turing_start, 4);
        pack_bits(&mut words, &mut bit, self.data_source, 2);
        for target in self.cv_targets {
            pack_bits(&mut words, &mut bit, target >> 3, 1);
        }
        pack_bits(&mut words, &mut bit, self.walk_step_index, 3);
        pack_bits(&mut words, &mut bit, self.walk_style, 1);
        pack_bits(&mut words, &mut bit, self.walk_drunk, 2);
        pack_bits(&mut words, &mut bit, self.walk_chance_index, 3);
        pack_bits(&mut words, &mut bit, self.internal_clock_rate >> 3, 6);
        pack_bits(&mut words, &mut bit, 0, 5 + 64);
        for n in 1..5 {
            pack_bits(&mut words, &mut bit, self.frequencies[n] & 3, 2);
        }
        for value in self.input_gains {
            pack_bits(&mut words, &mut bit, value, 16);
        }
        for value in self.cv_depths {
            pack_bits(&mut words, &mut bit, (value >> 8) as u8 as u32, 8);
        }
        for value in self.input_modes {
            pack_bits(&mut words, &mut bit, value, 1);
        }
        for value in self.cv_targets {
            pack_bits(&mut words, &mut bit, value, 3);
        }
        for value in self.group_indices {
            pack_bits(&mut words, &mut bit, value, 4);
        }
        for n in 5..9 {
            pack_bits(&mut words, &mut bit, self.frequencies[n] & 3, 2);
        }
        for value in self.feedback_sends {
            pack_bits(&mut words, &mut bit, value, 1);
        }
        pack_bits(&mut words, &mut bit, self.preset as u32, 3);
        pack_bits(&mut words, &mut bit, self.palette as u32, 3);
        for value in self.bank_output_sends {
            pack_bits(&mut words, &mut bit, value, 5);
        }
        for value in self.legacy_output_sends {
            pack_bits(&mut words, &mut bit, value, 5);
        }
        pack_bits(&mut words, &mut bit, 0, 8);
        for frequency in self.frequencies {
            pack_bits(&mut words, &mut bit, frequency >> 2, 5);
        }
        for value in self.enables {
            pack_bits(&mut words, &mut bit, value, 1);
        }
        pack_bits(&mut words, &mut bit, self.layout, 2);
        pack_bits(&mut words, &mut bit, self.frequencies[9] & 3, 2);
        debug_assert_eq!(bit, STATE_WORDS * 16);
        words
    }

    fn load_words(&mut self, words: &[u16; STATE_WORDS]) {
        let mut bit = 0;
        for level in &mut self.levels {
            let coarse = unpack_bits(words, &mut bit, 8) as u8;
            *level = if coarse == 64 {
                0x3fff
            } else {
                (coarse as i8 as i32) << 8
            };
        }
        let bank_drive = unpack_bits(words, &mut bit, 8);
        let _legacy_drive = unpack_bits(words, &mut bit, 8);
        self.bank_drive = if bank_drive == 96 {
            0x5fff
        } else {
            bank_drive << 8
        };
        self.resonance = unpack_bits(words, &mut bit, 8) << 8;
        self.bank_feedback = unpack_bits(words, &mut bit, 8) << 8;
        let _legacy_cutoff = unpack_bits(words, &mut bit, 8);
        let _legacy_slope = unpack_bits(words, &mut bit, 8);
        let _legacy_width = unpack_bits(words, &mut bit, 8);
        self.knee = unpack_bits(words, &mut bit, 8) << 8;
        self.ceiling = unpack_bits(words, &mut bit, 8) << 8;
        self.damp = unpack_bits(words, &mut bit, 3);
        let _legacy_mode = unpack_bits(words, &mut bit, 1);
        let _legacy_type = unpack_bits(words, &mut bit, 2);
        self.frequencies.fill(0);
        self.frequencies[0] = unpack_bits(words, &mut bit, 2);
        self.clock_mode = unpack_bits(words, &mut bit, 1) != 0;
        self.clock_algorithm = unpack_bits(words, &mut bit, 2);
        self.shift_direction = unpack_bits(words, &mut bit, 2);
        self.turing_length = unpack_bits(words, &mut bit, 4);
        self.turing_change_index = unpack_bits(words, &mut bit, 3);
        self.clock_source = unpack_bits(words, &mut bit, 2);
        let rate_low = unpack_bits(words, &mut bit, 3);
        self.clock_depth = unpack_bits(words, &mut bit, 8);
        self.turing_target = unpack_bits(words, &mut bit, 1);
        self.turing_start = unpack_bits(words, &mut bit, 4);
        self.data_source = unpack_bits(words, &mut bit, 2);
        let mut target_highs = [0u32; 4];
        for value in &mut target_highs {
            *value = unpack_bits(words, &mut bit, 1);
        }
        self.walk_step_index = unpack_bits(words, &mut bit, 3);
        self.walk_style = unpack_bits(words, &mut bit, 1);
        self.walk_drunk = unpack_bits(words, &mut bit, 2);
        self.walk_chance_index = unpack_bits(words, &mut bit, 3);
        let rate_high = unpack_bits(words, &mut bit, 6);
        self.internal_clock_rate = if rate_high == 0 {
            [15, 30, 45, 60, 90, 120, 180, 240][rate_low as usize]
        } else {
            rate_low | (rate_high << 3)
        };
        let _reserved = unpack_bits(words, &mut bit, 5 + 64);
        for n in 1..5 {
            self.frequencies[n] = unpack_bits(words, &mut bit, 2);
        }
        for value in &mut self.input_gains {
            *value = unpack_bits(words, &mut bit, 16);
        }
        for value in &mut self.cv_depths {
            *value = (unpack_bits(words, &mut bit, 8) as u8 as i8 as i32) << 8;
        }
        for value in &mut self.input_modes {
            *value = unpack_bits(words, &mut bit, 1);
        }
        for value in &mut self.cv_targets {
            *value = unpack_bits(words, &mut bit, 3);
        }
        for (value, high) in self.cv_targets.iter_mut().zip(target_highs) {
            *value |= high << 3;
        }
        for value in &mut self.group_indices {
            *value = unpack_bits(words, &mut bit, 4);
        }
        for n in 5..9 {
            self.frequencies[n] = unpack_bits(words, &mut bit, 2);
        }
        for value in &mut self.feedback_sends {
            *value = unpack_bits(words, &mut bit, 1);
        }
        self.preset = unpack_bits(words, &mut bit, 3) as u8;
        self.palette = unpack_bits(words, &mut bit, 3) as u8;
        for value in &mut self.bank_output_sends {
            *value = unpack_bits(words, &mut bit, 5);
        }
        for value in &mut self.legacy_output_sends {
            *value = unpack_bits(words, &mut bit, 5);
        }
        let _legacy_feedback = unpack_bits(words, &mut bit, 8);
        for frequency in &mut self.frequencies {
            *frequency |= unpack_bits(words, &mut bit, 5) << 2;
        }
        for value in &mut self.enables {
            *value = unpack_bits(words, &mut bit, 1);
        }
        self.layout = unpack_bits(words, &mut bit, 2);
        self.frequencies[9] |= unpack_bits(words, &mut bit, 2);
        // Older V2 records could retain a dormant USER vector while naming a
        // factory layout. The CPU-less UI materializes that factory vector on
        // restore; do the same here for exact cross-implementation behavior.
        if self.layout != 3 {
            self.layout_preview = self.layout;
            self.apply_layout();
        }
        self.layout_preview = self.layout;
        self.frequency_preview = self.frequencies[0];
        self.editing = false;
        self.clock_roles_initialized = self.cv_targets.iter().any(|target| *target >= 7);
        if self.clock_algorithm == 3 {
            self.walk_step_index = 2;
        }
        if (self.clock_algorithm == 0 && self.shift_direction == 2)
            || (self.clock_algorithm == 1 && self.shift_direction > 1)
            || (self.clock_algorithm == 2 && self.shift_direction == 3)
        {
            self.shift_direction = 0;
        }
        debug_assert_eq!(bit, STATE_WORDS * 16);
    }

    fn continuous_accel_target(&self) -> bool {
        let input_field = self.selected.wrapping_sub(INPUT);
        (BAND..BAND + 10).contains(&self.selected)
            || matches!(
                self.selected,
                DRIVE | RESONANCE | FEEDBACK | KNEE | CEILING | CLOCK_RATE
            )
            || ((INPUT..INPUT + 12).contains(&self.selected)
                && (input_field % 3 == 2
                    || (input_field % 3 == 1 && self.input_modes[(input_field / 3) as usize] == 0)))
    }

    unsafe fn write_output(&self, index: usize) {
        ui_write(OUTPUT_SEND, index, self.bank_output_sends[index]);
    }

    unsafe fn write_edit_target(&self, target: u8) {
        match target {
            PAGE => ui_write(PAGE_STATE, 0, self.page as u32),
            PRESET => ui_write(PRESET_STATE, 0, self.preset as u32),
            DRIVE => ui_write(DRIVE_STATE, 0, self.drive()),
            RESONANCE => ui_write(RESONANCE_STATE, 0, self.resonance),
            FEEDBACK => ui_write(FEEDBACK_STATE, 0, self.feedback()),
            KNEE => ui_write(KNEE_STATE, 0, self.knee),
            CEILING => ui_write(CEILING_STATE, 0, self.ceiling),
            DAMP => ui_write(DAMP_STATE, 0, self.damp),
            MODE => {
                ui_write(CLOCK_MODE_STATE, 0, self.clock_mode as u32);
                for n in 0..4 {
                    ui_write(INPUT_MODE, n, self.input_modes[n]);
                    ui_write(CV_TARGET, n, self.cv_targets[n]);
                }
            }
            CLOCK_ALGORITHM => {
                ui_write(CLOCK_ALGORITHM_STATE, 0, self.clock_algorithm);
                ui_write(SHIFT_DIRECTION_STATE, 0, self.shift_direction);
                ui_write(WALK_STEP_STATE, 0, self.walk_step_index);
            }
            SHIFT_DIRECTION => ui_write(SHIFT_DIRECTION_STATE, 0, self.shift_direction),
            CLOCK_SOURCE => ui_write(CLOCK_SOURCE_STATE, 0, self.clock_source),
            DATA_SOURCE => ui_write(DATA_SOURCE_STATE, 0, self.data_source),
            CLOCK_RATE => ui_write(CLOCK_RATE_STATE, 0, self.internal_clock_rate),
            CLOCK_DEPTH => ui_write(CLOCK_DEPTH_STATE, 0, self.clock_depth),
            TURING_CHANGE => ui_write(
                if self.clock_algorithm == 3 {
                    WALK_CHANCE_STATE
                } else {
                    TURING_CHANGE_STATE
                },
                0,
                if self.clock_algorithm == 3 {
                    self.walk_chance_index
                } else {
                    self.turing_change_index
                },
            ),
            TURING_TARGET => ui_write(
                if self.clock_algorithm == 3 {
                    WALK_STYLE_STATE
                } else {
                    TURING_TARGET_STATE
                },
                0,
                if self.clock_algorithm == 3 {
                    self.walk_style
                } else {
                    self.turing_target
                },
            ),
            TURING_LENGTH => ui_write(
                if self.clock_algorithm == 3 {
                    WALK_DRUNK_STATE
                } else {
                    TURING_LENGTH_STATE
                },
                0,
                if self.clock_algorithm == 3 {
                    self.walk_drunk
                } else {
                    self.turing_length
                },
            ),
            TURING_START => {
                ui_write(TURING_START_STATE, 0, self.turing_start);
                ui_write(TURING_LENGTH_STATE, 0, self.turing_length);
            }
            PALETTE => ui_write(PALETTE_STATE, 0, self.palette as u32),
            LAYOUT => ui_write(LAYOUT_PREVIEW_STATE, 0, self.layout_preview),
            t if (BAND..BAND + 10).contains(&t) => {
                let n = (t - BAND) as usize;
                ui_write(LEVEL_STATE, n, self.levels[n] as u32);
            }
            t if (FREQUENCY..FREQUENCY + 10).contains(&t) => {
                ui_write(FREQUENCY_PREVIEW_STATE, 0, self.frequency_preview);
            }
            t if (INPUT..INPUT + 12).contains(&t) => {
                let field = (t - INPUT) as usize;
                let n = field / 3;
                match field % 3 {
                    0 => ui_write(INPUT_MODE, n, self.input_modes[n]),
                    1 if self.input_modes[n] == 0 => ui_write(INPUT_GAIN, n, self.input_gains[n]),
                    1 => ui_write(CV_TARGET, n, self.cv_targets[n]),
                    _ => ui_write(CV_DEPTH, n, self.cv_depths[n] as u32),
                }
            }
            t if (GROUP..GROUP + 10).contains(&t) => {
                let n = (t - GROUP) as usize;
                ui_write(BANK_GROUP, n, gray_encode(self.group_indices[n]));
            }
            t if (OUTPUT..OUTPUT + 20).contains(&t) => {
                self.write_output((t - OUTPUT) as usize);
            }
            t if (113..117).contains(&t) => {
                let row = (t - 113) as usize;
                for column in 0..5 {
                    self.write_output(row * 5 + column);
                }
            }
            t if (117..121).contains(&t) => {
                let column = (t - 117) as usize;
                for row in 0..4 {
                    self.write_output(row * 5 + column);
                }
            }
            121 => {
                for row in 0..4 {
                    self.write_output(row * 5 + 4);
                }
            }
            _ => {}
        }
    }

    unsafe fn write_click_result(&self, target: u8, was_editing: bool) {
        ui_write(EDITING_STATE, 0, self.editing as u32);
        if (FEEDBACK_ENABLE..FEEDBACK_ENABLE + 10).contains(&target) {
            let n = (target - FEEDBACK_ENABLE) as usize;
            ui_write(FEEDBACK_SEND, n, self.feedback_sends[n]);
        } else if (ENABLE..ENABLE + 10).contains(&target) {
            let n = (target - ENABLE) as usize;
            ui_write(BAND_ENABLE, n, self.enables[n]);
        } else if was_editing {
            if target == PRESET {
                for n in 0..10 {
                    ui_write(LEVEL_STATE, n, self.levels[n] as u32);
                }
            } else if target == LAYOUT {
                ui_write(LAYOUT_STATE, 0, self.layout);
                for n in 0..10 {
                    ui_write(BAND_FREQUENCY, n, self.frequencies[n]);
                }
            } else if (FREQUENCY..FREQUENCY + 10).contains(&target) {
                let n = (target - FREQUENCY) as usize;
                ui_write(BAND_FREQUENCY, n, self.frequencies[n]);
                ui_write(LAYOUT_STATE, 0, self.layout);
                ui_write(LAYOUT_PREVIEW_STATE, 0, self.layout_preview);
            }
        } else if target == LAYOUT {
            ui_write(LAYOUT_PREVIEW_STATE, 0, self.layout_preview);
        } else if (FREQUENCY..FREQUENCY + 10).contains(&target) {
            ui_write(FREQUENCY_PREVIEW_STATE, 0, self.frequency_preview);
        }
    }

    unsafe fn write_scalars(&self) {
        ui_write(PAGE_STATE, 0, self.page as u32);
        ui_write(SELECTED_STATE, 0, self.selected as u32);
        ui_write(PRESET_STATE, 0, self.preset as u32);
        ui_write(PALETTE_STATE, 0, self.palette as u32);
        ui_write(EDITING_STATE, 0, self.editing as u32);
        ui_write(DRIVE_STATE, 0, self.drive());
        ui_write(RESONANCE_STATE, 0, self.resonance);
        ui_write(FEEDBACK_STATE, 0, self.feedback());
        ui_write(CLOCK_MODE_STATE, 0, self.clock_mode as u32);
        ui_write(CLOCK_ALGORITHM_STATE, 0, self.clock_algorithm);
        ui_write(DAMP_STATE, 0, self.damp);
        ui_write(KNEE_STATE, 0, self.knee);
        ui_write(CEILING_STATE, 0, self.ceiling);
        ui_write(SHIFT_DIRECTION_STATE, 0, self.shift_direction);
        ui_write(TURING_LENGTH_STATE, 0, self.turing_length);
        ui_write(TURING_CHANGE_STATE, 0, self.turing_change_index);
        ui_write(CLOCK_SOURCE_STATE, 0, self.clock_source);
        ui_write(DATA_SOURCE_STATE, 0, self.data_source);
        ui_write(CLOCK_RATE_STATE, 0, self.internal_clock_rate);
        ui_write(CLOCK_DEPTH_STATE, 0, self.clock_depth);
        ui_write(WALK_STEP_STATE, 0, self.walk_step_index);
        ui_write(WALK_STYLE_STATE, 0, self.walk_style);
        ui_write(WALK_DRUNK_STATE, 0, self.walk_drunk);
        ui_write(WALK_CHANCE_STATE, 0, self.walk_chance_index);
        ui_write(TURING_TARGET_STATE, 0, self.turing_target);
        ui_write(TURING_START_STATE, 0, self.turing_start);
        ui_write(LAYOUT_STATE, 0, self.layout);
        ui_write(LAYOUT_PREVIEW_STATE, 0, self.layout_preview);
        ui_write(FREQUENCY_PREVIEW_STATE, 0, self.frequency_preview);
        for n in 0..10 {
            ui_write(LEVEL_STATE, n, self.levels[n] as u32);
        }
    }

    unsafe fn write_packed(&self) {
        for n in 0..10 {
            ui_write(BAND_ENABLE, n, self.enables[n]);
            ui_write(BAND_FREQUENCY, n, self.frequencies[n]);
            let index = self.group_indices[n];
            ui_write(BANK_GROUP, n, gray_encode(index));
            ui_write(FEEDBACK_SEND, n, self.feedback_sends[n]);
        }
        for n in 0..4 {
            ui_write(INPUT_GAIN, n, self.input_gains[n]);
            ui_write(INPUT_MODE, n, self.input_modes[n]);
            ui_write(CV_TARGET, n, self.cv_targets[n]);
            ui_write(CV_DEPTH, n, self.cv_depths[n] as u32);
        }
        for n in 0..20 {
            ui_write(OUTPUT_SEND, n, self.bank_output_sends[n]);
        }
    }
}

#[entry]
fn main() -> ! {
    let mut state = State::new();
    let mut record = [0u8; RECORD_BYTES];
    let mut words = [0u16; STATE_WORDS];
    let mut candidate = [0u16; STATE_WORDS];
    let flash_available;
    let mut have_active = false;
    let mut active_sector = 0u8;
    let mut active_generation = 0u32;
    let mut previous_button = false;
    let mut button_press_pending = false;
    let mut click_lockout = 0u8;
    let mut encoder_remainder = 0i16;
    let mut detent_idle = u8::MAX;
    let mut accel_level = 0u8;
    let mut last_edit_direction = 0i8;
    unsafe {
        // Wait until the bootloader's slot detector has either supplied a
        // validated slot or explicitly reported that no safe slot exists.
        // The flash peripheral itself independently enforces this decision.
        flash_available = (0..BOOT_SLOT_TIMEOUT_POLLS)
            .find_map(|_| {
                let slot = read32(FLASH_SLOT);
                if slot & 1 != 0 {
                    Some(slot & 2 != 0)
                } else {
                    None
                }
            })
            .unwrap_or(false);
        if flash_available {
            if let Some(generation) = scan_sector(0, &mut record, &mut words) {
                state.load_words(&words);
                have_active = true;
                active_generation = generation;
            }
            if let Some(generation) = scan_sector(1, &mut record, &mut candidate) {
                if !have_active || generation > active_generation {
                    state.load_words(&candidate);
                    have_active = true;
                    active_sector = 1;
                    active_generation = generation;
                }
            }
        }
        state.write_scalars();
        state.write_packed();
        ui_write(SAVE_STATE, 0, flash_available as u32);
        // Audio remains muted until the complete restored/default state has
        // reached the hardware control registers.
        ui_write(STARTUP_STATE, 0, 1);
    }
    loop {
        detent_idle = detent_idle.saturating_add(1);
        encoder_remainder += unsafe { read8(ENCODER_STEP) as i8 } as i16;
        let button = unsafe { read8(ENCODER_BUTTON) & 1 != 0 };
        click_lockout = click_lockout.saturating_sub(1);
        if button && !previous_button && click_lockout == 0 {
            button_press_pending = true;
        } else if !button && previous_button && button_press_pending {
            let target = state.selected;
            let was_editing = state.editing;
            let save_requested = state.click();
            unsafe { state.write_click_result(target, was_editing) };
            if !was_editing && state.editing {
                // Navigation speed before entering a control must never make
                // its first edit imprecise.
                detent_idle = u8::MAX;
                accel_level = 0;
            }
            if save_requested && flash_available {
                unsafe {
                    // The inactive sector is erased and written first, then
                    // reread and CRC-checked before it becomes active. A
                    // power loss therefore leaves the previous record valid.
                    ui_write(SAVE_STATE, 0, 1 | (1 << 1) | (1 << 2));
                    words = state.pack_words();
                    let target_sector = if have_active { active_sector ^ 1 } else { 0 };
                    let generation = if have_active {
                        active_generation.wrapping_add(1)
                    } else {
                        1
                    };
                    let saved = save_sector(target_sector, generation, &words, &mut record)
                        && scan_sector(target_sector, &mut record, &mut candidate)
                            == Some(generation)
                        && candidate == words;
                    if saved {
                        have_active = true;
                        active_sector = target_sector;
                        active_generation = generation;
                        ui_write(SAVE_STATE, 0, 1 | (2 << 2));
                    } else {
                        ui_write(SAVE_STATE, 0, 1 | (3 << 2));
                    }
                }
            }
            button_press_pending = false;
            // The loop period is roughly a fraction of a millisecond. Ignore
            // switch bounce for the following few tens of milliseconds.
            click_lockout = 80;
        }
        previous_button = button;
        let mut edited_target = None;
        let mut navigated = false;
        while encoder_remainder > 1 {
            if state.editing {
                let direction = 1;
                accel_level = progressive_edit_level(
                    detent_idle,
                    accel_level,
                    state.continuous_accel_target(),
                    last_edit_direction == direction,
                );
                let amount = accel_level + 1;
                last_edit_direction = direction;
                detent_idle = 0;
                state.edit(amount as i8);
                edited_target = Some(state.selected);
            } else {
                state.navigate(1);
                navigated = true;
                accel_level = 0;
            }
            encoder_remainder -= 2;
        }
        while encoder_remainder < -1 {
            if state.editing {
                let direction = -1;
                accel_level = progressive_edit_level(
                    detent_idle,
                    accel_level,
                    state.continuous_accel_target(),
                    last_edit_direction == direction,
                );
                let amount = accel_level + 1;
                last_edit_direction = direction;
                detent_idle = 0;
                state.edit(-(amount as i8));
                edited_target = Some(state.selected);
            } else {
                state.navigate(-1);
                navigated = true;
                accel_level = 0;
            }
            encoder_remainder += 2;
        }
        unsafe {
            if let Some(target) = edited_target {
                state.write_edit_target(target);
            } else if navigated {
                ui_write(SELECTED_STATE, 0, state.selected as u32);
            }
        }
        riscv::asm::delay(20_000);
    }
}
