#![no_std]
#![no_main]

use core::ptr::{read_volatile, write_volatile};
use panic_halt as _;
use rezo_hybrid_probe_fw::{
    clamp_control, gray_encode, step_group_index, GROUP_INDEX_DEFAULTS,
};
use riscv_rt::entry;

const ENCODER_STEP: usize = 0xF000_0600;
const ENCODER_BUTTON: usize = 0xF000_0601;
const REZO_UI: usize = 0xF000_1000;
const NAVIGATION: usize = REZO_UI;
const DRIVE_RESONANCE: usize = REZO_UI + 0x04;
const FEEDBACK_MODE: usize = REZO_UI + 0x08;
const LIMITS: usize = REZO_UI + 0x0C;
const FILTER_SHAPE: usize = REZO_UI + 0x10;
const FILTER_WIDTH_LAYOUT: usize = REZO_UI + 0x14;
const SAVE_STATUS: usize = REZO_UI + 0x18;
const LEVEL0: usize = REZO_UI + 0x20;
const ARRAY_COMMAND: usize = REZO_UI + 0x60;
const BAND_ENABLE: u32 = 0;
const BAND_FREQUENCY: u32 = 1;
const INPUT_GAIN: u32 = 2;
const INPUT_MODE: u32 = 3;
const CV_TARGET: u32 = 4;
const CV_DEPTH: u32 = 5;
const BANK_GROUP: u32 = 6;
const FEEDBACK_SEND: u32 = 7;
const FILTER_CV: u32 = 8;
const OUTPUT_SEND: u32 = 9;

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
const FILTER_TYPE: u8 = 61;
const CUTOFF: u8 = 62;
const SLOPE: u8 = 63;
const WIDTH: u8 = 64;
const FILTER_MATRIX: u8 = 65;
const FEEDBACK_ENABLE: u8 = 80;
const PALETTE: u8 = 90;
const SAVE: u8 = 91;
const LAYOUT: u8 = 92;
const ENABLE: u8 = 93;
const FREQUENCY: u8 = 103;

const MAIN_BANK: &[u8] = &[0, 1, 60, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];
const MAIN_FILTER: &[u8] = &[0, 61, 60, 62, 63, 64, 12, 13];
const FEEDBACK_PAGE: &[u8] = &[0, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 14, 15, 16, 17];
const INPUT_PAGE: &[u8] = &[0, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29];
const GROUP_PAGE: &[u8] = &[0, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39];
const OUTPUT_BANK: &[u8] = &[
    0, 117, 118, 119, 120, 121, 113, 40, 41, 42, 43, 44, 114, 45, 46, 47, 48, 49, 115, 50, 51, 52,
    53, 54, 116, 55, 56, 57, 58, 59,
];
const OUTPUT_FILTER: &[u8] = &[
    0, 117, 118, 119, 120, 113, 40, 41, 42, 43, 114, 45, 46, 47, 48, 115, 50, 51, 52, 53, 116, 55,
    56, 57, 58,
];
const OPTIONS_PAGE: &[u8] = &[0, 90, 91];
const BANDS_PAGE: &[u8] = &[
    0, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111,
    112,
];
const FILTER_CV_PAGE: &[u8] = &[
    0, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
];
const LEGACY_FREQUENCIES: [u32; 10] = [0, 12, 20, 32, 44, 56, 68, 84, 92, 104];
const OCTAVE_FREQUENCIES: [u32; 10] = [4, 16, 24, 36, 48, 60, 76, 88, 100, 112];
const PERCEPT_FREQUENCIES: [u32; 10] = [8, 28, 40, 48, 52, 64, 72, 80, 96, 108];

const OUTPUT_BANK_DEFAULTS: [u32; 20] = [
    16, 16, 16, 16, 0, 16, 0, 16, 0, 0, 0, 16, 0, 16, 0, 0, 0, 0, 0, 16,
];
const OUTPUT_FILTER_DEFAULTS: [u32; 20] = [
    16, 16, 16, 16, 0, 16, 0, 16, 0, 0, 0, 16, 0, 16, 0, 0, 0, 0, 0, 0,
];

unsafe fn write32(address: usize, value: u32) {
    write_volatile(address as *mut u32, value);
}
unsafe fn read8(address: usize) -> u8 {
    read_volatile(address as *const u8)
}
unsafe fn array_write(kind: u32, index: usize, value: u32) {
    write32(
        ARRAY_COMMAND,
        kind | ((index as u32) << 4) | ((value & 0xFFFF) << 9),
    );
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
    filter_drive: u32,
    resonance: u32,
    bank_feedback: u32,
    filter_feedback: u32,
    filter_mode: bool,
    filter_type: u32,
    damp: u32,
    knee: u32,
    ceiling: u32,
    cutoff: u32,
    slope: u32,
    width: u32,
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
    filter_cv: [i32; 15],
    bank_output_sends: [u32; 20],
    filter_output_sends: [u32; 20],
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
            filter_drive: 0x2000,
            resonance: 0x2000,
            bank_feedback: 0,
            filter_feedback: 0,
            filter_mode: false,
            filter_type: 0,
            damp: 3,
            knee: 0x2000,
            ceiling: 0x7000,
            cutoff: 0x4000,
            slope: 0x4000,
            width: 0x3000,
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
            filter_cv: [0; 15],
            bank_output_sends: OUTPUT_BANK_DEFAULTS,
            filter_output_sends: OUTPUT_FILTER_DEFAULTS,
        }
    }

    fn drive(&self) -> u32 {
        if self.filter_mode {
            self.filter_drive
        } else {
            self.bank_drive
        }
    }

    fn feedback(&self) -> u32 {
        if self.filter_mode {
            self.filter_feedback
        } else {
            self.bank_feedback
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
        let sends = if self.filter_mode {
            &mut self.filter_output_sends
        } else {
            &mut self.bank_output_sends
        };
        let columns = if self.filter_mode { 4 } else { 5 };
        for column in 0..columns {
            let n = row * 5 + column;
            sends[n] = add(sends[n], delta, 0, 16);
        }
    }

    fn edit_output_column(&mut self, column: usize, delta: i32) {
        let sends = if self.filter_mode {
            &mut self.filter_output_sends
        } else {
            &mut self.bank_output_sends
        };
        for row in 0..4 {
            let n = row * 5 + column;
            sends[n] = add(sends[n], delta, 0, 16);
        }
    }

    fn targets(&self) -> &'static [u8] {
        match self.page {
            0 if self.filter_mode => MAIN_FILTER,
            0 => MAIN_BANK,
            1 => FEEDBACK_PAGE,
            2 => INPUT_PAGE,
            3 => GROUP_PAGE,
            4 if self.filter_mode => OUTPUT_FILTER,
            4 => OUTPUT_BANK,
            5 => OPTIONS_PAGE,
            6 => BANDS_PAGE,
            7 => FILTER_CV_PAGE,
            _ => OPTIONS_PAGE,
        }
    }

    fn navigate(&mut self, direction: i8) {
        let targets = self.targets();
        let p = targets
            .iter()
            .position(|x| *x == self.selected)
            .unwrap_or(0);
        let p = if direction > 0 {
            (p + 1) % targets.len()
        } else if p == 0 {
            targets.len() - 1
        } else {
            p - 1
        };
        self.selected = targets[p];
    }

    fn change_page(&mut self, direction: i8) {
        const BANK: &[u8] = &[0, 6, 2, 3, 4, 1, 5];
        const FILTER: &[u8] = &[0, 6, 2, 7, 3, 4, 1, 5];
        let order = if self.filter_mode { FILTER } else { BANK };
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

    unsafe fn click(&mut self) {
        if (FEEDBACK_ENABLE..FEEDBACK_ENABLE + 10).contains(&self.selected) {
            let n = (self.selected - FEEDBACK_ENABLE) as usize;
            if self.enables[n] != 0 {
                self.feedback_sends[n] ^= 1;
            }
        } else if (ENABLE..ENABLE + 10).contains(&self.selected) {
            let n = (self.selected - ENABLE) as usize;
            self.enables[n] ^= 1;
        } else if self.selected == SAVE {
            // Flash persistence follows as a separately testable milestone.
            write32(SAVE_STATUS, (1 << 1) | (2 << 5));
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
            if (BAND..BAND + 10).contains(&self.selected)
                && self.enables[(self.selected - BAND) as usize] == 0
            {
                return;
            }
            if self.selected == LAYOUT {
                self.layout_preview = self.layout;
            } else if (FREQUENCY..FREQUENCY + 10).contains(&self.selected) {
                self.frequency_preview = self.frequencies[(self.selected - FREQUENCY) as usize];
            }
            self.editing = true;
        }
    }

    unsafe fn edit(&mut self, direction: i8) {
        let d = direction as i32;
        match self.selected {
            PAGE => self.change_page(direction),
            PRESET => self.preset = (self.preset as i32 + d).rem_euclid(7) as u8,
            DRIVE if self.filter_mode => {
                self.filter_drive = clamp_control(self.filter_drive, d, 0, 0x5FFF)
            }
            DRIVE => self.bank_drive = clamp_control(self.bank_drive, d, 0, 0x5FFF),
            RESONANCE => self.resonance = clamp_control(self.resonance, d, 0, 0x8000),
            FEEDBACK if self.filter_mode => {
                self.filter_feedback = clamp_control(self.filter_feedback, d, 0, 0x8000)
            }
            FEEDBACK => self.bank_feedback = clamp_control(self.bank_feedback, d, 0, 0x8000),
            KNEE => self.knee = clamp_control(self.knee, d, 0x1000, 0x8000),
            CEILING => self.ceiling = clamp_control(self.ceiling, d, 0x1000, 0x8000),
            DAMP => self.damp = (self.damp as i32 + d).clamp(0, 4) as u32,
            MODE => {
                self.filter_mode = !self.filter_mode;
                if self.page == 7 && !self.filter_mode {
                    self.page = 2;
                }
            }
            FILTER_TYPE => self.filter_type = (self.filter_type as i32 + d).rem_euclid(4) as u32,
            CUTOFF => self.cutoff = add(self.cutoff, d * 256, 0, 0x8000),
            SLOPE => self.slope = add(self.slope, d * 256, 0, 0x8000),
            WIDTH => self.width = add(self.width, d * 256, 0, 0x8000),
            PALETTE => self.palette = (self.palette as i32 + d).rem_euclid(5) as u8,
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
                        self.input_gains[n] = add(self.input_gains[n], d * 256, 0, 0xFFFF);
                    }
                    1 => {
                        self.cv_targets[n] = (self.cv_targets[n] as i32 + d).rem_euclid(7) as u32;
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
            t if (FILTER_MATRIX..FILTER_MATRIX + 15).contains(&t) => {
                let n = (t - FILTER_MATRIX) as usize;
                self.filter_cv[n] = adds(self.filter_cv[n], d, -128, 127);
            }
            t if (OUTPUT..OUTPUT + 20).contains(&t) => {
                let n = (t - OUTPUT) as usize;
                let sends = if self.filter_mode {
                    &mut self.filter_output_sends
                } else {
                    &mut self.bank_output_sends
                };
                sends[n] = add(sends[n], d, 0, 16);
            }
            t if (113..117).contains(&t) => self.edit_output_row((t - 113) as usize, d),
            t if (117..121).contains(&t) => self.edit_output_column((t - 117) as usize, d),
            121 if !self.filter_mode => self.edit_output_column(4, d),
            _ => {}
        }
    }

    unsafe fn write_scalars(&self) {
        let nav = self.page as u32
            | ((self.selected as u32) << 3)
            | ((self.preset as u32) << 10)
            | ((self.palette as u32) << 13)
            | ((self.editing as u32) << 16);
        write32(NAVIGATION, nav);
        write32(DRIVE_RESONANCE, self.drive() | (self.resonance << 16));
        write32(
            FEEDBACK_MODE,
            self.feedback()
                | ((self.filter_mode as u32) << 16)
                | (self.filter_type << 17)
                | (self.damp << 19),
        );
        write32(LIMITS, self.knee | (self.ceiling << 16));
        write32(FILTER_SHAPE, self.cutoff | (self.slope << 16));
        write32(
            FILTER_WIDTH_LAYOUT,
            self.width
                | (self.layout << 16)
                | (self.layout_preview << 18)
                | (self.frequency_preview << 20),
        );
        for n in 0..10 {
            write32(LEVEL0 + 4 * n, self.levels[n] as u32);
        }
    }

    unsafe fn write_packed(&self) {
        for n in 0..10 {
            array_write(BAND_ENABLE, n, self.enables[n]);
            array_write(BAND_FREQUENCY, n, self.frequencies[n]);
            let index = self.group_indices[n];
            array_write(BANK_GROUP, n, gray_encode(index));
            array_write(FEEDBACK_SEND, n, self.feedback_sends[n]);
        }
        for n in 0..4 {
            array_write(INPUT_GAIN, n, self.input_gains[n]);
            array_write(INPUT_MODE, n, self.input_modes[n]);
            array_write(CV_TARGET, n, self.cv_targets[n]);
            array_write(CV_DEPTH, n, self.cv_depths[n] as u32);
        }
        for n in 0..15 {
            array_write(FILTER_CV, n, self.filter_cv[n] as u32);
        }
        for n in 0..20 {
            array_write(
                OUTPUT_SEND,
                n,
                if self.filter_mode {
                    self.filter_output_sends[n]
                } else {
                    self.bank_output_sends[n]
                },
            );
        }
    }
}

#[entry]
fn main() -> ! {
    let mut state = State::new();
    let mut previous_button = false;
    let mut button_press_pending = false;
    let mut click_lockout = 0u8;
    let mut encoder_remainder = 0i16;
    unsafe {
        state.write_scalars();
        state.write_packed();
        write32(SAVE_STATUS, 1 << 1);
    }
    loop {
        let mut dirty = false;
        encoder_remainder += unsafe { read8(ENCODER_STEP) as i8 } as i16;
        let button = unsafe { read8(ENCODER_BUTTON) & 1 != 0 };
        click_lockout = click_lockout.saturating_sub(1);
        if button && !previous_button && click_lockout == 0 {
            button_press_pending = true;
        } else if !button && previous_button && button_press_pending {
            unsafe { state.click() };
            dirty = true;
            button_press_pending = false;
            // The loop period is roughly a fraction of a millisecond. Ignore
            // switch bounce for the following few tens of milliseconds.
            click_lockout = 80;
        }
        previous_button = button;
        while encoder_remainder > 1 {
            if state.editing {
                unsafe { state.edit(1) };
            } else {
                state.navigate(1);
            }
            encoder_remainder -= 2;
            dirty = true;
        }
        while encoder_remainder < -1 {
            if state.editing {
                unsafe { state.edit(-1) };
            } else {
                state.navigate(-1);
            }
            encoder_remainder += 2;
            dirty = true;
        }
        if dirty {
            unsafe {
                state.write_scalars();
                state.write_packed();
            }
        }
        riscv::asm::delay(20_000);
    }
}
