#![no_std]
#![no_main]

use panic_halt as _;
use rezo_cpu_fw::{
    add, adds, clamp_control, edit_feedback_ceiling, edit_feedback_knee, flash_erase,
    flash_program, flash_read, gray_encode, normalize_feedback_limits, pack_bits,
    progressive_edit_level, read32, read8, read_u16, read_u32, record_crc, step_coarse_byte,
    step_group_index, step_target, unpack_bits, write_u16, write_u32, write_ui_command,
    ENCODER_BUTTON, ENCODER_STEP, FLASH_SLOT, GROUP_INDEX_DEFAULTS,
};
use riscv_rt::entry;

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
const SAME_FEEDBACK_STATE: u32 = 18;
const CROSS_FEEDBACK_STATE: u32 = 19;
const DAMP_STATE: u32 = 20;
const KNEE_STATE: u32 = 21;
const CEILING_STATE: u32 = 22;
const CROSS_CURVE_STATE: u32 = 23;
const CROSS_LAYOUT_STATE: u32 = 24;
const CROSS_LAYOUT_PREVIEW_STATE: u32 = 25;
const LAYOUT_STATE: u32 = 26;
const LAYOUT_PREVIEW_STATE: u32 = 27;
const FREQUENCY_PREVIEW_STATE: u32 = 28;
const LEVEL_STATE: u32 = 29;
const SAVE_STATE: u32 = 30;
const STARTUP_STATE: u32 = 31;
const MOTION_SOURCE_STATE: u32 = 32;
const MOTION_RATE_STATE: u32 = 33;
const MOTION_PHASE_STATE: u32 = 34;
const MOTION_DEPTH_STATE: u32 = 35;
const OUTPUT_SIDE: u32 = 36;
const CROSS_MATRIX: u32 = 37;

const BOOT_SLOT_TIMEOUT_POLLS: u32 = 1_000_000;
const STATE_WORDS: usize = 39;
const V5_STATE_WORDS: usize = 38;
const LEGACY_STATE_WORDS: usize = 36;
const HEADER_BYTES: usize = 16;
const RECORD_BYTES: usize = HEADER_BYTES + STATE_WORDS * 2;
const MAGIC: u32 = 0x5a525453;
const VERSION: u16 = 6;

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
const CROSS_LAYOUT: u8 = 60;
const MOTION_SOURCE: u8 = 61;
const MOTION_RATE: u8 = 62;
const MOTION_PHASE: u8 = 63;
const MOTION_DEPTH: u8 = PRESET;
const CROSS_CELL: u8 = 64;
const FEEDBACK_ENABLE: u8 = 80;
const PALETTE: u8 = 90;
const SAVE: u8 = 91;
const LAYOUT: u8 = 92;
const ENABLE: u8 = 93;
const FREQUENCY: u8 = 103;
const CROSS_FEEDBACK: u8 = 113;
const OUTPUT_SIDE_TARGET: u8 = 114;
const CROSS_ROW: u8 = 118;
const CROSS_COL: u8 = 122;
const OUTPUT_DRY_COL: u8 = CROSS_LAYOUT;
const SAME_FEEDBACK: u8 = 126;
const CROSS_CURVE: u8 = MOTION_DEPTH;

const MAIN_PAGE: &[u8] = &[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];
const FEEDBACK_PAGE: &[u8] = &[0, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 14, 15, 16, 17];
const GROUP_PAGE: &[u8] = &[0, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39];
const OPTIONS_PAGE: &[u8] = &[0, 90, 91, 1];
const OUTPUT_PAGE: &[u8] = &[
    0, 122, 123, 124, 125, 60, 118, 114, 40, 41, 42, 43, 44, 119, 115, 45, 46, 47, 48, 49, 120,
    116, 50, 51, 52, 53, 54, 121, 117, 55, 56, 57, 58, 59,
];
const BANDS_TRIANGLE: &[u8] = &[
    0, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111,
    112, 61, 62, 63, 1,
];
const BANDS_RANDOM: &[u8] = &[
    0, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111,
    112, 61, 62, 1,
];
const CROSS_GLOBAL_PAGE: &[u8] = &[0, 60, 126, 113];
const CROSS_MATRIX_PAGE: &[u8] = &[
    0, 60, 122, 123, 124, 125, 118, 64, 65, 66, 67, 119, 68, 69, 70, 71, 120, 72, 73, 74, 75, 121,
    76, 77, 78, 79, 126, 113,
];
const LEGACY_FREQUENCIES: [u32; 10] = [0, 12, 20, 32, 44, 56, 68, 84, 92, 104];
const OCTAVE_FREQUENCIES: [u32; 10] = [4, 16, 24, 36, 48, 60, 76, 88, 100, 112];
const PERCEPT_FREQUENCIES: [u32; 10] = [8, 28, 40, 48, 52, 64, 72, 80, 96, 108];
const OUTPUT_DEFAULTS: [u32; 20] = [
    16, 16, 16, 16, 0, 16, 16, 16, 16, 0, 16, 0, 16, 0, 0, 16, 0, 16, 0, 0,
];

unsafe fn ui_write(kind: u32, index: usize, value: u32) {
    write_ui_command::<6>(kind, index, value);
}

fn cross_factory(layout: u32, source: usize, destination: usize) -> u32 {
    match layout {
        1 if source == destination => 16,
        2 if destination == (source + 1) & 3 => 16,
        3 if destination == 3 - source => 16,
        4 => 4,
        _ => 0,
    }
}

struct State {
    page: u8,
    selected: u8,
    preset: u8,
    palette: u8,
    editing: bool,
    drive: u32,
    resonance: u32,
    feedback: u32,
    same_reduction: u32,
    cross_feedback: u32,
    cross_curve: u32,
    cross_layout: u32,
    cross_layout_preview: u32,
    knee: u32,
    ceiling: u32,
    damp: u32,
    motion_source: u32,
    motion_rate: u32,
    motion_phase: u32,
    motion_depth: u32,
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
    output_sends: [u32; 20],
    output_sides: [u32; 4],
    cross_matrix: [u32; 16],
}

impl State {
    const fn new() -> Self {
        Self {
            page: 0,
            selected: 0,
            preset: 0,
            palette: 0,
            editing: false,
            drive: 0x2000,
            resonance: 0x2000,
            feedback: 0,
            same_reduction: 0,
            cross_feedback: 0,
            cross_curve: 0,
            cross_layout: 0,
            cross_layout_preview: 0,
            knee: 0x2000,
            ceiling: 0x7000,
            damp: 3,
            motion_source: 0,
            motion_rate: 12,
            motion_phase: 28,
            motion_depth: 32,
            layout: 1,
            layout_preview: 1,
            frequency_preview: 0,
            levels: [0x2000; 10],
            enables: [1; 10],
            frequencies: OCTAVE_FREQUENCIES,
            input_gains: [0xCCCC, 0xCCCC, 0, 0],
            input_modes: [0, 1, 2, 2],
            cv_targets: [1, 1, 2, 0],
            cv_depths: [0; 4],
            group_indices: GROUP_INDEX_DEFAULTS,
            feedback_sends: [1; 10],
            output_sends: OUTPUT_DEFAULTS,
            output_sides: [0, 1, 0, 1],
            cross_matrix: [16, 0, 0, 0, 0, 16, 0, 0, 0, 0, 16, 0, 0, 0, 0, 16],
        }
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
        let table = match self.layout_preview {
            0 => Some(&LEGACY_FREQUENCIES),
            1 => Some(&OCTAVE_FREQUENCIES),
            2 => Some(&PERCEPT_FREQUENCIES),
            _ => None,
        };
        if let Some(table) = table {
            self.frequencies.copy_from_slice(table);
        }
        self.layout = self.layout_preview;
    }

    fn targets(&self) -> &'static [u8] {
        match self.page {
            0 => MAIN_PAGE,
            1 => FEEDBACK_PAGE,
            3 => GROUP_PAGE,
            4 => OUTPUT_PAGE,
            5 => OPTIONS_PAGE,
            6 if self.motion_source == 2 => BANDS_RANDOM,
            6 => BANDS_TRIANGLE,
            7 if self.cross_layout == 0 => CROSS_GLOBAL_PAGE,
            7 => CROSS_MATRIX_PAGE,
            _ => OPTIONS_PAGE,
        }
    }

    fn navigate(&mut self, direction: i8) {
        if self.page == 2 {
            let mut targets = [0u8; 13];
            let mut len = 1;
            for lane in 0..4 {
                let target = INPUT + lane * 3;
                targets[len] = target;
                targets[len + 1] = target + 1;
                len += 2;
                if self.input_modes[lane as usize] == 2 {
                    targets[len] = target + 2;
                    len += 1;
                }
            }
            self.selected = step_target(self.selected, &targets[..len], direction);
        } else {
            self.selected = step_target(self.selected, self.targets(), direction);
        }
    }

    fn change_page(&mut self, direction: i8) {
        const ORDER: &[u8] = &[0, 6, 2, 3, 4, 1, 7, 5];
        let p = ORDER.iter().position(|x| *x == self.page).unwrap_or(0);
        let p = if direction > 0 {
            (p + 1) % ORDER.len()
        } else if p == 0 {
            ORDER.len() - 1
        } else {
            p - 1
        };
        self.page = ORDER[p];
    }

    fn matrix_edit_target(&self) -> bool {
        (CROSS_CELL..CROSS_CELL + 16).contains(&self.selected)
            || (CROSS_ROW..CROSS_ROW + 4).contains(&self.selected)
            || (CROSS_COL..CROSS_COL + 4).contains(&self.selected)
    }

    fn click(&mut self) -> bool {
        if (FEEDBACK_ENABLE..FEEDBACK_ENABLE + 10).contains(&self.selected) {
            let n = (self.selected - FEEDBACK_ENABLE) as usize;
            if self.enables[n] != 0 {
                self.feedback_sends[n] ^= 1;
            }
        } else if (ENABLE..ENABLE + 10).contains(&self.selected) {
            self.enables[(self.selected - ENABLE) as usize] ^= 1;
        } else if (OUTPUT_SIDE_TARGET..OUTPUT_SIDE_TARGET + 4).contains(&self.selected) {
            self.output_sides[(self.selected - OUTPUT_SIDE_TARGET) as usize] ^= 1;
        } else if self.selected == SAVE {
            return true;
        } else if self.editing {
            if self.page == 0 && self.selected == PRESET {
                self.apply_preset();
            } else if self.selected == LAYOUT {
                self.apply_layout();
            } else if self.page == 7 && self.selected == CROSS_LAYOUT {
                self.cross_layout = self.cross_layout_preview;
            } else if (FREQUENCY..FREQUENCY + 10).contains(&self.selected) {
                self.frequencies[(self.selected - FREQUENCY) as usize] = self.frequency_preview;
                self.layout = 3;
                self.layout_preview = 3;
            }
            self.editing = false;
        } else {
            if self.selected == LAYOUT {
                self.layout_preview = self.layout;
            } else if self.page == 7 && self.selected == CROSS_LAYOUT {
                self.cross_layout_preview = self.cross_layout;
            } else if (FREQUENCY..FREQUENCY + 10).contains(&self.selected) {
                self.frequency_preview = self.frequencies[(self.selected - FREQUENCY) as usize];
            }
            if self.matrix_edit_target() {
                if self.cross_layout == 0 {
                    return false;
                }
                if self.cross_layout != 5 {
                    for source in 0..4 {
                        for destination in 0..4 {
                            self.cross_matrix[source * 4 + destination] =
                                cross_factory(self.cross_layout, source, destination);
                        }
                    }
                    self.cross_layout = 5;
                }
            }
            let disabled = if (BAND..BAND + 10).contains(&self.selected) {
                self.enables[(self.selected - BAND) as usize] == 0
            } else if (FEEDBACK_ENABLE..FEEDBACK_ENABLE + 10).contains(&self.selected) {
                self.enables[(self.selected - FEEDBACK_ENABLE) as usize] == 0
            } else if (GROUP..GROUP + 10).contains(&self.selected) {
                self.enables[(self.selected - GROUP) as usize] == 0
            } else {
                false
            };
            self.editing = !disabled;
        }
        false
    }

    fn edit_output_row(&mut self, row: usize, d: i32) {
        for col in 0..5 {
            let n = row * 5 + col;
            self.output_sends[n] = add(self.output_sends[n], d, 0, 16);
        }
    }
    fn edit_output_col(&mut self, col: usize, d: i32) {
        for row in 0..4 {
            let n = row * 5 + col;
            self.output_sends[n] = add(self.output_sends[n], d, 0, 16);
        }
    }
    fn edit_cross_row(&mut self, row: usize, d: i32) {
        for col in 0..4 {
            let n = row * 4 + col;
            self.cross_matrix[n] = add(self.cross_matrix[n], d, 0, 16);
        }
    }
    fn edit_cross_col(&mut self, col: usize, d: i32) {
        for row in 0..4 {
            let n = row * 4 + col;
            self.cross_matrix[n] = add(self.cross_matrix[n], d, 0, 16);
        }
    }

    fn edit(&mut self, direction: i8) {
        let d = direction as i32;
        match self.selected {
            PAGE => self.change_page(direction),
            PRESET if self.page == 0 => self.preset = (self.preset as i32 + d).rem_euclid(7) as u8,
            CROSS_CURVE if self.page == 5 => self.cross_curve ^= 1,
            MOTION_DEPTH if self.page == 6 => self.motion_depth = add(self.motion_depth, d, 0, 128),
            DRIVE => self.drive = clamp_control(self.drive, d, 0, 0x5fff),
            RESONANCE => self.resonance = clamp_control(self.resonance, d, 0, 0x8000),
            FEEDBACK => self.feedback = clamp_control(self.feedback, d, 0, 0x8000),
            KNEE => self.knee = edit_feedback_knee(self.knee, self.ceiling, d),
            CEILING => self.ceiling = edit_feedback_ceiling(self.ceiling, self.knee, d),
            DAMP => self.damp = (self.damp as i32 + d).clamp(0, 4) as u32,
            CROSS_FEEDBACK => self.cross_feedback = add(self.cross_feedback, d, 0, 128),
            SAME_FEEDBACK => self.same_reduction = add(self.same_reduction, -d, 0, 128),
            CROSS_LAYOUT if self.page == 7 => {
                self.cross_layout_preview =
                    (self.cross_layout_preview as i32 + d).rem_euclid(6) as u32
            }
            PALETTE => self.palette = (self.palette as i32 + d).rem_euclid(8) as u8,
            LAYOUT => self.layout_preview = (self.layout_preview as i32 + d).rem_euclid(4) as u32,
            MOTION_SOURCE => {
                self.motion_source = (self.motion_source as i32 + d).rem_euclid(3) as u32
            }
            MOTION_RATE => self.motion_rate = add(self.motion_rate, d, 1, 200),
            MOTION_PHASE => self.motion_phase = add(self.motion_phase, d, 0, 255),
            t if (BAND..BAND + 10).contains(&t) => {
                let n = (t - BAND) as usize;
                self.levels[n] = adds(self.levels[n], d * 256, -0x4000, 0x3fff);
            }
            t if (FREQUENCY..FREQUENCY + 10).contains(&t) => {
                self.frequency_preview = add(self.frequency_preview, d, 0, 115)
            }
            t if (INPUT..INPUT + 12).contains(&t) => {
                let field = (t - INPUT) as usize;
                let n = field / 3;
                match field % 3 {
                    0 => {
                        self.input_modes[n] = (self.input_modes[n] as i32 + d).rem_euclid(3) as u32
                    }
                    1 if self.input_modes[n] != 2 => {
                        self.input_gains[n] = step_coarse_byte(self.input_gains[n], d)
                    }
                    1 => self.cv_targets[n] = (self.cv_targets[n] as i32 + d).rem_euclid(7) as u32,
                    _ => self.cv_depths[n] = adds(self.cv_depths[n], d * 256, -0x8000, 0x7f00),
                }
            }
            t if (GROUP..GROUP + 10).contains(&t) => {
                let n = (t - GROUP) as usize;
                self.group_indices[n] = step_group_index(self.group_indices[n], d);
            }
            t if (OUTPUT..OUTPUT + 20).contains(&t) => {
                let n = (t - OUTPUT) as usize;
                self.output_sends[n] = add(self.output_sends[n], d, 0, 16);
            }
            t if (CROSS_ROW..CROSS_ROW + 4).contains(&t) && self.page == 4 => {
                self.edit_output_row((t - CROSS_ROW) as usize, d)
            }
            t if (CROSS_COL..CROSS_COL + 4).contains(&t) && self.page == 4 => {
                self.edit_output_col((t - CROSS_COL) as usize, d)
            }
            OUTPUT_DRY_COL if self.page == 4 => self.edit_output_col(4, d),
            t if (CROSS_CELL..CROSS_CELL + 16).contains(&t) => {
                let n = (t - CROSS_CELL) as usize;
                self.cross_matrix[n] = add(self.cross_matrix[n], d, 0, 16);
            }
            t if (CROSS_ROW..CROSS_ROW + 4).contains(&t) => {
                self.edit_cross_row((t - CROSS_ROW) as usize, d)
            }
            t if (CROSS_COL..CROSS_COL + 4).contains(&t) => {
                self.edit_cross_col((t - CROSS_COL) as usize, d)
            }
            _ => {}
        }
    }

    fn continuous_accel_target(&self) -> bool {
        matches!(
            self.selected,
            DRIVE | RESONANCE | FEEDBACK | KNEE | CEILING | MOTION_RATE | MOTION_PHASE
        ) || (BAND..BAND + 10).contains(&self.selected)
            || (FREQUENCY..FREQUENCY + 10).contains(&self.selected)
            || ((INPUT..INPUT + 12).contains(&self.selected) && {
                let field = (self.selected - INPUT) as usize;
                field % 3 == 2 || (field % 3 == 1 && self.input_modes[field / 3] != 2)
            })
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
        pack_bits(
            &mut words,
            &mut bit,
            if self.drive == 0x5fff {
                96
            } else {
                self.drive >> 8
            },
            8,
        );
        pack_bits(&mut words, &mut bit, self.resonance >> 8, 8);
        pack_bits(&mut words, &mut bit, self.feedback >> 8, 8);
        pack_bits(&mut words, &mut bit, self.knee >> 8, 8);
        pack_bits(&mut words, &mut bit, self.ceiling >> 8, 8);
        pack_bits(&mut words, &mut bit, self.damp, 3);
        for v in self.input_gains {
            pack_bits(&mut words, &mut bit, v, 16);
        }
        for v in self.cv_depths {
            pack_bits(&mut words, &mut bit, (v >> 8) as u8 as u32, 8);
        }
        for v in self.input_modes {
            pack_bits(&mut words, &mut bit, v, 2);
        }
        for v in self.cv_targets {
            pack_bits(&mut words, &mut bit, v, 3);
        }
        for v in self.group_indices {
            pack_bits(&mut words, &mut bit, v, 4);
        }
        for v in self.feedback_sends {
            pack_bits(&mut words, &mut bit, v, 1);
        }
        pack_bits(&mut words, &mut bit, self.preset as u32, 3);
        pack_bits(&mut words, &mut bit, self.palette as u32, 3);
        for v in self.output_sends {
            pack_bits(&mut words, &mut bit, v, 5);
        }
        for v in self.output_sides {
            pack_bits(&mut words, &mut bit, v, 1);
        }
        for v in self.frequencies {
            pack_bits(&mut words, &mut bit, v, 7);
        }
        for v in self.enables {
            pack_bits(&mut words, &mut bit, v, 1);
        }
        pack_bits(&mut words, &mut bit, self.layout, 2);
        pack_bits(&mut words, &mut bit, self.cross_layout, 3);
        for v in self.cross_matrix {
            pack_bits(&mut words, &mut bit, v, 5);
        }
        pack_bits(&mut words, &mut bit, self.same_reduction & 31, 5);
        pack_bits(&mut words, &mut bit, self.cross_feedback & 31, 5);
        pack_bits(&mut words, &mut bit, self.cross_curve, 1);
        pack_bits(&mut words, &mut bit, 0, 1);
        pack_bits(&mut words, &mut bit, self.motion_source, 2);
        pack_bits(&mut words, &mut bit, self.motion_rate, 8);
        pack_bits(&mut words, &mut bit, self.motion_phase, 8);
        pack_bits(&mut words, &mut bit, self.motion_depth, 8);
        pack_bits(&mut words, &mut bit, self.same_reduction >> 5, 3);
        pack_bits(&mut words, &mut bit, self.cross_feedback >> 5, 3);
        for value in [
            self.drive,
            self.resonance,
            self.feedback,
            self.knee,
            self.ceiling,
        ] {
            pack_bits(&mut words, &mut bit, (value >> 6) & 3, 2);
        }
        pack_bits(&mut words, &mut bit, 0, 6);
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
        let drive = unpack_bits(words, &mut bit, 8);
        self.drive = if drive == 96 { 0x5fff } else { drive << 8 };
        self.resonance = unpack_bits(words, &mut bit, 8) << 8;
        self.feedback = unpack_bits(words, &mut bit, 8) << 8;
        self.knee = unpack_bits(words, &mut bit, 8) << 8;
        self.ceiling = unpack_bits(words, &mut bit, 8) << 8;
        self.damp = unpack_bits(words, &mut bit, 3);
        for v in &mut self.input_gains {
            *v = unpack_bits(words, &mut bit, 16);
        }
        for v in &mut self.cv_depths {
            *v = (unpack_bits(words, &mut bit, 8) as u8 as i8 as i32) << 8;
        }
        for v in &mut self.input_modes {
            *v = unpack_bits(words, &mut bit, 2);
        }
        for v in &mut self.cv_targets {
            *v = unpack_bits(words, &mut bit, 3);
        }
        for v in &mut self.group_indices {
            *v = unpack_bits(words, &mut bit, 4);
        }
        for v in &mut self.feedback_sends {
            *v = unpack_bits(words, &mut bit, 1);
        }
        self.preset = unpack_bits(words, &mut bit, 3) as u8;
        self.palette = unpack_bits(words, &mut bit, 3) as u8;
        for v in &mut self.output_sends {
            *v = unpack_bits(words, &mut bit, 5);
        }
        for v in &mut self.output_sides {
            *v = unpack_bits(words, &mut bit, 1);
        }
        for v in &mut self.frequencies {
            *v = unpack_bits(words, &mut bit, 7);
        }
        for v in &mut self.enables {
            *v = unpack_bits(words, &mut bit, 1);
        }
        self.layout = unpack_bits(words, &mut bit, 2);
        self.layout_preview = self.layout;
        self.cross_layout = unpack_bits(words, &mut bit, 3);
        self.cross_layout_preview = self.cross_layout;
        for v in &mut self.cross_matrix {
            *v = unpack_bits(words, &mut bit, 5);
        }
        self.same_reduction = unpack_bits(words, &mut bit, 5);
        self.cross_feedback = unpack_bits(words, &mut bit, 5);
        self.cross_curve = unpack_bits(words, &mut bit, 1);
        let _ = unpack_bits(words, &mut bit, 1);
        self.motion_source = unpack_bits(words, &mut bit, 2);
        self.motion_rate = unpack_bits(words, &mut bit, 8);
        self.motion_phase = unpack_bits(words, &mut bit, 8);
        self.motion_depth = unpack_bits(words, &mut bit, 8);
        self.same_reduction |= unpack_bits(words, &mut bit, 3) << 5;
        self.cross_feedback |= unpack_bits(words, &mut bit, 3) << 5;
        self.drive |= unpack_bits(words, &mut bit, 2) << 6;
        self.resonance |= unpack_bits(words, &mut bit, 2) << 6;
        self.feedback |= unpack_bits(words, &mut bit, 2) << 6;
        self.knee |= unpack_bits(words, &mut bit, 2) << 6;
        self.ceiling |= unpack_bits(words, &mut bit, 2) << 6;
        let _reserved = unpack_bits(words, &mut bit, 6);
        (self.knee, self.ceiling) = normalize_feedback_limits(self.knee, self.ceiling);
        debug_assert_eq!(bit, STATE_WORDS * 16);
    }

    unsafe fn publish(
        &self,
        save_available: bool,
        save_busy: bool,
        save_status: u32,
        startup: bool,
    ) {
        for n in 0..10 {
            ui_write(LEVEL_STATE, n, self.levels[n] as u32);
            ui_write(BAND_ENABLE, n, self.enables[n]);
            ui_write(BAND_FREQUENCY, n, self.frequencies[n]);
            ui_write(BANK_GROUP, n, gray_encode(self.group_indices[n]));
            ui_write(FEEDBACK_SEND, n, self.feedback_sends[n]);
        }
        for n in 0..4 {
            ui_write(INPUT_GAIN, n, self.input_gains[n]);
            ui_write(INPUT_MODE, n, self.input_modes[n]);
            ui_write(CV_TARGET, n, self.cv_targets[n]);
            ui_write(CV_DEPTH, n, self.cv_depths[n] as u32);
            ui_write(OUTPUT_SIDE, n, self.output_sides[n]);
        }
        for n in 0..20 {
            ui_write(OUTPUT_SEND, n, self.output_sends[n]);
        }
        for n in 0..16 {
            ui_write(CROSS_MATRIX, n, self.cross_matrix[n]);
        }
        for (kind, value) in [
            (PAGE_STATE, self.page as u32),
            (SELECTED_STATE, self.selected as u32),
            (PRESET_STATE, self.preset as u32),
            (PALETTE_STATE, self.palette as u32),
            (EDITING_STATE, self.editing as u32),
            (DRIVE_STATE, self.drive),
            (RESONANCE_STATE, self.resonance),
            (FEEDBACK_STATE, self.feedback),
            (SAME_FEEDBACK_STATE, 128 - self.same_reduction),
            (CROSS_FEEDBACK_STATE, self.cross_feedback),
            (DAMP_STATE, self.damp),
            (KNEE_STATE, self.knee),
            (CEILING_STATE, self.ceiling),
            (CROSS_CURVE_STATE, self.cross_curve),
            (CROSS_LAYOUT_STATE, self.cross_layout),
            (CROSS_LAYOUT_PREVIEW_STATE, self.cross_layout_preview),
            (LAYOUT_STATE, self.layout),
            (LAYOUT_PREVIEW_STATE, self.layout_preview),
            (FREQUENCY_PREVIEW_STATE, self.frequency_preview),
            (MOTION_SOURCE_STATE, self.motion_source),
            (MOTION_RATE_STATE, self.motion_rate),
            (MOTION_PHASE_STATE, self.motion_phase),
            (MOTION_DEPTH_STATE, self.motion_depth),
        ] {
            ui_write(kind, 0, value);
        }
        ui_write(
            SAVE_STATE,
            0,
            save_available as u32 | ((save_busy as u32) << 1) | (save_status << 2),
        );
        ui_write(STARTUP_STATE, 0, startup as u32);
    }
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
    let declared = read_u16(record, 6) as usize;
    if !((version == VERSION && declared == STATE_WORDS)
        || (version == 5 && declared == V5_STATE_WORDS)
        || (version == 4 && declared == LEGACY_STATE_WORDS))
    {
        return None;
    }
    for offset in HEADER_BYTES..HEADER_BYTES + declared * 2 {
        record[offset] = flash_read(sector, offset as u16)?;
    }
    if record_crc(record, declared) != read_u32(record, 12) {
        return None;
    }
    words.fill(0);
    for (n, word) in words[..declared].iter_mut().enumerate() {
        *word = read_u16(record, HEADER_BYTES + 2 * n);
    }
    if declared == LEGACY_STATE_WORDS {
        words[36] = 0x7030;
        words[37] = 0x0080;
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
    let mut button_pending = false;
    let mut click_lockout = 0u8;
    let mut encoder_remainder = 0i16;
    let mut detent_idle = u8::MAX;
    let mut accel_level = 0u8;
    let mut last_direction = 0i8;
    let mut save_status = 0u32;
    unsafe {
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
        state.publish(flash_available, false, save_status, true);
    }
    loop {
        detent_idle = detent_idle.saturating_add(1);
        encoder_remainder += unsafe { read8(ENCODER_STEP) as i8 } as i16;
        let button = unsafe { read8(ENCODER_BUTTON) & 1 != 0 };
        click_lockout = click_lockout.saturating_sub(1);
        if button && !previous_button && click_lockout == 0 {
            button_pending = true;
        } else if !button && previous_button && button_pending {
            let save_requested = state.click();
            if !state.editing {
                accel_level = 0;
                detent_idle = u8::MAX;
            }
            unsafe {
                state.publish(flash_available, false, save_status, true);
            }
            if save_requested && flash_available {
                unsafe {
                    state.publish(true, true, 1, true);
                    words = state.pack_words();
                    let target = if have_active { active_sector ^ 1 } else { 0 };
                    let generation = if have_active {
                        active_generation.wrapping_add(1)
                    } else {
                        1
                    };
                    let saved = save_sector(target, generation, &words, &mut record)
                        && scan_sector(target, &mut record, &mut candidate) == Some(generation)
                        && candidate == words;
                    if saved {
                        have_active = true;
                        active_sector = target;
                        active_generation = generation;
                    }
                    save_status = if saved { 2 } else { 3 };
                    state.publish(true, false, save_status, true);
                }
            }
            button_pending = false;
            click_lockout = 80;
        }
        previous_button = button;
        let mut changed = false;
        while encoder_remainder > 1 {
            if state.editing {
                accel_level = progressive_edit_level(
                    detent_idle,
                    accel_level,
                    state.continuous_accel_target(),
                    last_direction == 1,
                );
                state.edit((accel_level + 1) as i8);
                last_direction = 1;
                detent_idle = 0;
            } else {
                state.navigate(1);
                accel_level = 0;
            }
            encoder_remainder -= 2;
            changed = true;
        }
        while encoder_remainder < -1 {
            if state.editing {
                accel_level = progressive_edit_level(
                    detent_idle,
                    accel_level,
                    state.continuous_accel_target(),
                    last_direction == -1,
                );
                state.edit(-((accel_level + 1) as i8));
                last_direction = -1;
                detent_idle = 0;
            } else {
                state.navigate(-1);
                accel_level = 0;
            }
            encoder_remainder += 2;
            changed = true;
        }
        if changed {
            unsafe {
                state.publish(flash_available, false, save_status, true);
            }
        }
        riscv::asm::delay(20_000);
    }
}
