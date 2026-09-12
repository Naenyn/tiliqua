#![no_std]
#![no_main]

mod ui_text;
mod feedback;
mod ui_canvas;
mod ui_scene;
mod ui_markers;
mod measurement_snapshot;
mod pitch_verification;
mod capture_trace;
#[cfg(tuner_nsdf)]
mod nsdf_trace;
mod serial_report;
mod pitch_math;
#[path = "calibration.rs"]
mod oscillator_calibration;
mod calibration_live;
#[path="calibration/bipolar.rs"] mod bipolar;
#[path="calibration/bipolar_sweep.rs"] mod bipolar_sweep;
use ui_markers::{Marker, Markers};

use core::cell::RefCell;
use core::fmt::Write;

use critical_section::Mutex;
use heapless::String;
use irq::handler;
use log::warn;
use micromath::F32Ext;
use riscv_rt::entry;

use tiliqua_hal::pca9635::Pca9635Driver;
use tiliqua_hal::pmod::EurorackPmod;
use tiliqua_lib::*;

use options::{DisplayMode, Opts, Page};
use opts::persistence::*;
use opts::{OptionString, Options as _};
use pac::constants::*;
use runtime::{ChannelMeasurement, MeasurementBank, RuntimeControls};
use tiliqua_fw::*;
use tiliqua_pac as pac;

const TIMER0_ISR_PERIOD_MS: u32 = 5;
const PLAYBACK_PERIOD_MS:u32=1;
const FRAME_PERIOD_TICKS: u8 = 4; // Publish measurements at up to 50Hz.
const MENU_COLS: u8 = 28;
const MENU_ROWS: u8 = 9;
const MENU_PAGE_COLUMN: u8 = 0;
const MENU_PAGE_WIDTH: u8 = 8;
const MENU_ITEM_COLUMN: u8 = 10;
const MENU_VALUE_RIGHT: u8 = 25;
const MENU_EDIT_COLUMN: u8 = 26;
const NOTE_NAMES: [&str; 12] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
];
const ROUND_DISPLAY: bool = matches!(FIXED_MODELINE, Some((720, 720)));

struct App {
    ui: ui::UI<Encoder0, EurorackPmod0, I2c0, Opts>,
    now_ms: u64,
}

// The timer interrupt and foreground loop share one long-lived UI object.
// Keeping it static prevents future profile/scale/menu growth from silently
// becoming part of `main()`'s stack frame, which previously corrupted an
// already constrained main RAM after the first interrupt.
static APP: Mutex<RefCell<Option<App>>> = Mutex::new(RefCell::new(None));
static PLAYBACK:Mutex<RefCell<oscillator_calibration::playback::Engine>>=
    Mutex::new(RefCell::new(oscillator_calibration::playback::Engine::new()));

impl App {
    #[inline(never)]
    fn new(opts: Opts) -> Self {
        let peripherals = unsafe { pac::Peripherals::steal() };
        let encoder = Encoder0::new(peripherals.ENCODER0);
        let pca9635 = Pca9635Driver::new(I2c0::new(peripherals.I2C0));
        let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
        Self {
            now_ms: 0,
            ui: ui::UI::new_with_fade(
                opts,
                TIMER0_ISR_PERIOD_MS,
                5_000,
                encoder,
                pca9635,
                pmod,
            ),
        }
    }
}

fn with_app<R>(f: impl FnOnce(&mut App) -> R) -> R {
    critical_section::with(|cs| {
        let mut slot = APP.borrow_ref_mut(cs);
        f(slot.as_mut().expect("tuner app not initialized"))
    })
}

fn install_app(opts: Opts) {
    critical_section::with(|cs| {
        *APP.borrow_ref_mut(cs) = Some(App::new(opts));
    });
}

fn playback_cycles()->usize {
    // The CPU does not implement mcycle. Invert the free-running downcounter
    // to retain wrapping cycle arithmetic, including its 32-bit rollover.
    (!unsafe{pac::Peripherals::steal()}.PLAYBACK_TIMER.counter().read().value().bits()) as usize
}

fn timer0_handler() {
    let (now,allowed,input,chromatic)=with_app(|app| {
        // Never perform an unbounded motherboard-I2C transaction in this ISR.
        // Encoder/options and PMOD LEDs are all CSR-backed and deterministic.
        app.now_ms += PLAYBACK_PERIOD_MS as u64;
        if app.now_ms%TIMER0_ISR_PERIOD_MS as u64==0 {app.ui.update_realtime();}
        // Measurement bank selection is owned by the foreground reader, not
        // the encoder ISR. All four acquisition lanes run independently.
        (app.now_ms as u32,app.ui.opts.tracker.page.value==Page::Play,app.ui.opts.play.input.value,
            app.ui.opts.play.quantize.value==options::QuantizeMode::Chromatic)
    });
    critical_section::with(|cs| {
        let mut play=PLAYBACK.borrow_ref_mut(cs);
        if !play.active {return;}
        let start=playback_cycles();
        let tuner=unsafe{pac::Peripherals::steal()}.TUNER_PERIPH;
        if play.last_irq_cycle!=0 {
            let gap=start.wrapping_sub(play.last_irq_cycle);
            play.max_gap_cycles=play.max_gap_cycles.max(gap);
            if gap>pac::clock::sysclk() as usize/200 {
                tuner.cal_command().write(|w|unsafe{w.value().bits(play.stop("STOPPED - SCHEDULING GAP"))});
                return;
            }
        }
        play.last_irq_cycle=start;
        let allowed=allowed && input==play.input && chromatic==play.chromatic;
        if let Some(command)=play.tick(now,tuner.cv_sample().read().value().bits(),
            tuner.cal_status().read().value().bits(),allowed) {
            tuner.cal_command().write(|w|unsafe{w.value().bits(command)});
        }
        let elapsed=playback_cycles().wrapping_sub(start);
        play.max_cycles=play.max_cycles.max(elapsed);
        // Leave at least half the 1-ms period for interrupt/UI overhead and
        // foreground work. A missed compute budget is a fault, not silent jitter.
        if elapsed>pac::clock::sysclk() as usize/2000 {
            tuner.cal_command().write(|w|unsafe{w.value().bits(play.stop("STOPPED - CPU BUDGET"))});
        }
    });
}

#[inline(never)]
fn read_measurement(tuner: &pac::TUNER_PERIPH, counts_per_v: f32,
                    input: u8, verification: &mut pitch_verification::Verification) -> ChannelMeasurement {
    tuner.control().write(|w| unsafe { w.channel().bits(input) });
    // Sequence reads bracket each multi-register snapshot. If gateware publishes
    // while firmware is reading, retry rather than combine two measurements.
    if tuner.control().read().channel().bits() != input {
        return ChannelMeasurement::default();
    }
    let pitch_snapshot = measurement_snapshot::read(|| {
        let before = tuner.pitch_sequence().read().sequence().bits();
        let samples = tuner.period_samples().read().samples().bits();
        let cycles = tuner.period_cycles().read().cycles().bits();
        let age = tuner.pitch_age().read().samples().bits();
        let end = tuner.pitch_end().read().value().bits();
        let after = tuner.pitch_sequence().read().sequence().bits();
        (before, (samples, cycles, age, end, before), after)
    });
    let Some((period_samples, period_cycles, pitch_age, pitch_end, sequence)) = pitch_snapshot else {
        return ChannelMeasurement::default();
    };

    let level_snapshot = measurement_snapshot::read(|| {
        let before = tuner.level_sequence().read().sequence().bits();
        let power = tuner.mean_square().read().value().bits();
        let minimum = tuner.minimum().read().value().bits() as i32;
        let maximum = tuner.maximum().read().value().bits() as i32;
        let end = tuner.level_end().read().value().bits();
        let after = tuner.level_sequence().read().sequence().bits();
        (before, (power, minimum, maximum, end), after)
    });
    let Some((mean_square, minimum, maximum, level_end)) = level_snapshot else {
        return ChannelMeasurement::default();
    };
    // Foreground owns the read bank. Keep a defensive identity check before
    // publishing these separately captured pitch/level windows.
    if tuner.control().read().channel().bits() != input {
        return ChannelMeasurement::default();
    }
    let sample_rate = tuner.info().read().sample_rate().bits();
    let mut frequency_hz = if period_samples != 0 {
        sample_rate as f32 * period_cycles as f32 / period_samples as f32
    } else {
        0.0
    };
    let vrms = (mean_square as f32).sqrt() / counts_per_v;
    let vpp = (maximum - minimum) as f32 / counts_per_v;
    let valid = period_cycles != 0 && pitch_age < sample_rate / 2 && vrms >= 0.005;
    let mut qualified = false;
    if valid {
        let capture_mode=tuner.verify_capture().read().mode().bits();
        let selected=tuner.verify_channel().read().channel().bits() == input;
        // Other lanes retain their last qualified descriptor in its own scale.
        if selected {verification.set_capture_mode(capture_mode);}
        let decimation = pitch_verification::capture_divisor(sample_rate,verification.capture_mode());
        let lag = (period_samples as f32 * 256.0 /
                   (period_cycles as f32 * decimation as f32)).round() as u32;
        let status = tuner.verify_status().read();
        let desired=pitch_verification::capture_mode(period_samples,period_cycles,sample_rate,capture_mode);
        if tuner.verify_channel().read().channel().bits() == input && desired!=capture_mode {
            tuner.verify_capture().write(|w| unsafe {w.mode().bits(desired)});
            verification.clear();
        } else if tuner.verify_channel().read().channel().bits() == input && !status.busy().bit() {
            if status.done().bit() {
                verification.complete(input, tuner.verify_lag().read().lag_q8().bits(),
                                      status.factor().bits());
                verification.record_diagnostic(tuner.verify_lag().read().lag_q8().bits(),
                    tuner.verify_info().read().decimation().bits(),
                    tuner.verify_error().read().value().bits(),tuner.verify_span().read().value().bits());
            } else {
                verification.clear();
            }
            tuner.verify_request().write(|w| unsafe { w.lag_q8().bits(lag.min(0xffffff)) });
        }
        // Do not apply a correction to a different measurement bank if future
        // callers change the read-bank ownership contract.
        if tuner.control().read().channel().bits() != input {
            verification.clear();
            return ChannelMeasurement::default();
        }
        let factor=verification.factor(input, lag);
        verification.record_reading(frequency_hz,factor);
        frequency_hz /= factor as f32;
        qualified = verification.matches(input, lag) && minimum > -32000 && maximum < 32000;
    } else {
        verification.clear();
    }
    let clock = tuner.sample_clock().read().value().bits();
    let pitch_age_samples = clock.wrapping_sub(pitch_end);
    let level_age_samples = clock.wrapping_sub(level_end);
    let start_age = (pitch_age_samples as u64 + period_samples as u64).max(
        level_age_samples as u64 + tuner.level_size().read().value().bits() as u64);
    ChannelMeasurement {
        frequency_hz,
        vrms,
        vpp,
        valid,
        sequence,
        window_age_ms: ((start_age * 1000 / sample_rate as u64) + 2).min(u32::MAX as u64) as u32,
        end_age_ms: ((pitch_age_samples.max(level_age_samples) as u64 * 1000 / sample_rate as u64) + 1) as u32,
        qualified: qualified && valid && level_age_samples < sample_rate / 2,
    }
}

fn spiral_point(cx: i32, cy: i32, radius: f32, turns: f32) -> (u16, u16) {
    let angle = turns * core::f32::consts::TAU - core::f32::consts::FRAC_PI_2;
    (
        (cx + (radius * angle.cos()) as i32) as u16,
        (cy + (radius * angle.sin()) as i32) as u16,
    )
}

/// Minimal retained-mode background canvas. Static geometry is written once
/// through the CPU before scanout is enabled; live pitch and menu state remain
/// in the small DVI overlay. Keeping those jobs separate avoids storing a full
/// rasterized spiral in scarce FPGA block RAM.
struct BackgroundCanvas {
    base: *mut u8,
    width: i32,
    height: i32,
    rotate_left: bool,
}

impl BackgroundCanvas {
    fn new(base: usize, width: u16, height: u16, rotate_left: bool) -> Self {
        Self {
            base: base as *mut u8,
            width: width as i32,
            height: height as i32,
            rotate_left,
        }
    }

    fn clear(&mut self) {
        let words = (self.width as usize * self.height as usize + 3) / 4;
        self.clear_words(0, words);
    }

    fn clear_words(&mut self, first: usize, end: usize) {
        let ptr = self.base.cast::<u32>();
        for offset in first..end {
            unsafe { ptr.add(offset).write_volatile(0) };
        }
    }

    fn put_panel_pixel(&mut self, x: i32, y: i32, pixel: u8) {
        let Some(offset) = ui_canvas::physical(ui_canvas::Point { x, y },
            self.width as u16, self.height as u16, self.rotate_left) else { return; };
        unsafe { self.base.add(offset).write_volatile(pixel) };
    }

    fn line(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, pixel: u8) {
        ui_canvas::line(ui_canvas::Point { x:x0,y:y0 }, ui_canvas::Point { x:x1,y:y1 },
            pixel, |p,c| self.put_panel_pixel(p.x,p.y,c));
    }

    fn thick_line(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, pixel: u8) {
        for offset in -1..=1 {
            self.line(x0 + offset, y0, x1 + offset, y1, pixel);
            self.line(x0, y0 + offset, x1, y1 + offset, pixel);
        }
    }

    fn draw_border(&mut self) {
        const SUBTLE: u8 = (2 << 4) | 9;
        let cx = 360;
        let cy = 360;

        // Circular viewport edge and twelve chromatic divisions.
        let mut previous = None;
        for step in 0..=2048 {
            let angle = step as f32 * core::f32::consts::TAU / 2048.0;
            let point = (
                cx + (356.0 * angle.cos()).round() as i32,
                cy + (356.0 * angle.sin()).round() as i32,
            );
            if let Some((px, py)) = previous {
                self.line(px, py, point.0, point.1, SUBTLE);
            }
            previous = Some(point);
        }
    }

    fn draw_scene_range(&mut self, scene: ui_scene::Scene, first: usize, end: usize) {
        for segment in first..end.min(scene.segments()) {
            if segment < 2048 {
                let point = |step: usize| {
                    let angle = step as f32 * core::f32::consts::TAU / 2048.0;
                    (360 + (356.0 * angle.cos()).round() as i32,
                     360 + (356.0 * angle.sin()).round() as i32)
                };
                let (x0,y0) = point(segment);
                let (x1,y1) = point(segment + 1);
                self.line(x0,y0,x1,y1,0x29);
            } else if scene == ui_scene::Scene::Linear {
                ui_canvas::four_lane_scale_segment(segment - 2048,
                    |p,c| self.put_panel_pixel(p.x,p.y,c));
            } else if segment < 2060 {
                let angle = -core::f32::consts::FRAC_PI_2
                    + (segment - 2048) as f32 * core::f32::consts::TAU / 12.0;
                self.thick_line(360,360,360+(242.0*angle.cos()).round() as i32,
                    360+(242.0*angle.sin()).round() as i32,0x29);
            } else {
                let point = |step: usize| {
                    let turns = 1.0 + step as f32 / 192.0;
                    spiral_point(360,360,52.0+22.0*(turns-1.0),turns)
                };
                let (x0,y0) = point(segment - 2060);
                let (x1,y1) = point(segment - 2060 + 1);
                self.thick_line(x0 as i32,y0 as i32,x1 as i32,y1 as i32,0x59);
            }
        }
    }

    fn draw_static_tuner(&mut self) {
        const GUIDE: u8 = (5 << 4) | 9;
        const SUBTLE: u8 = (2 << 4) | 9;
        let cx = 360;
        let cy = 360;
        self.draw_border();
        for pitch_class in 0..12 {
            let angle = -core::f32::consts::FRAC_PI_2
                + pitch_class as f32 * core::f32::consts::TAU / 12.0;
            self.thick_line(
                cx,
                cy,
                cx + (242.0 * angle.cos()).round() as i32,
                cy + (242.0 * angle.sin()).round() as i32,
                SUBTLE,
            );
        }

        // One continuous Archimedean spiral, one revolution per octave. This
        // uses the same spiral_point() mapping as the live pitch marker.
        let samples_per_octave = 12 * 16;
        let mut previous = None;
        for step in 0..=(8 * samples_per_octave) {
            let turns = 1.0 + step as f32 / samples_per_octave as f32;
            let radius = 52.0 + 22.0 * (turns - 1.0);
            let (x, y) = spiral_point(cx, cy, radius, turns);
            if let Some((px, py)) = previous {
                self.thick_line(px, py, x as i32, y as i32, GUIDE);
            }
            previous = Some((x as i32, y as i32));
        }
    }

    fn finish(&self) {
        // Vexii's fence.i drains stores and flushes the small write-back data
        // cache, making the CPU-authored image visible to the framebuffer DMA.
        unsafe { core::arch::asm!("fence.i", options(nostack, preserves_flags)) };
    }
}

struct TextWriter<'a> {
    display: &'a pac::TUNER_DISPLAY,
    occupied: &'a mut ui_text::Occupied,
}

impl TextWriter<'_> {
    fn cell(&mut self, address: u16, cell: u16) {
        self.display.tile_write().write(|w| unsafe {
            w.bits(address as u32 | ((cell as u32) << 12))
        });
        self.occupied.record(address, cell);
    }

    fn clear(&mut self, initialize: bool) {
        let display = self.display;
        self.occupied.clear(|address, cell| {
            display.tile_write().write(|w| unsafe {
                w.bits(address as u32 | ((cell as u32) << 12))
            });
        });
        if initialize {
            // Establish known contents once per hardware bank. Subsequent
            // scene changes erase only cells that actually contain glyphs.
            for address in 0..ui_text::COLUMNS * ui_text::ROWS {
                self.cell(address as u16, 0);
            }
        }
    }
}

fn write_text(display: &mut TextWriter<'_>, column: u8, row: u8, text: &str) {
    ui_text::text(column as usize, row as usize, text, ui_text::DEFAULT, |address, cell| {
        display.cell(address, cell);
    });
}

fn write_centered(
    display: &mut TextWriter<'_>,
    row: u8,
    text: &str,
    width: u8,
) {
    // An odd field width shares the 45-column canvas's exact center cell.
    let width = ((width as usize) | 1).min(ui_text::COLUMNS);
    ui_text::field((ui_text::COLUMNS - width) / 2, row as usize, width, text,
                  ui_text::DEFAULT, ui_text::Align::Center, |address, cell| {
        display.cell(address, cell);
    });
}

fn write_static_text(display: &mut TextWriter<'_>, scene: ui_scene::Scene, preparing: bool,
                     changed: bool) {
    if changed {
    if scene == ui_scene::Scene::Linear {
        write_text(display, 19, 5, "LINEAR");
        write_text(display, 5, 8, "-50");
        write_text(display, 22, 8, "0");
        write_text(display, 37, 8, "+50");
    } else {
    for (column, row, label) in [
        (22, 5, "C "),
        (33, 7, "C#"),
        (41, 13, "D "),
        (43, 22, "D#"),
        (41, 30, "E "),
        (33, 34, "F "),
        (22, 35, "F#"),
        (11, 34, "G "),
        (2, 30, "G#"),
        (0, 22, "A "),
        (2, 13, "A#"),
        (11, 7, "B "),
    ] {
        write_text(display, column, row, label);
    }
    }
    write_text(display, 20, 1, "TUNER");
    }
    ui_text::field(9, 42, 27,
        if preparing { "PREPARING VIEW" } else { "ENCODER: MENU" },
        ui_text::DEFAULT, ui_text::Align::Center, |address, cell| {
            display.cell(address, cell);
        });
}

fn clear_menu_text(display: &pac::TUNER_DISPLAY) {
    for row in 0..MENU_ROWS {
        for column in 0..MENU_COLS {
            write_menu_char(display, column, row, b' ', false);
        }
    }
}

fn menu_glyph_index(byte: u8) -> u8 {
    if (b' '..=b'~').contains(&byte) {
        byte - b' '
    } else {
        0
    }
}

fn write_menu_char(
    display: &pac::TUNER_DISPLAY,
    column: u8,
    row: u8,
    byte: u8,
    bold: bool,
) {
    if column >= MENU_COLS || row >= MENU_ROWS {
        return;
    }
    let glyph = menu_glyph_index(byte);
    let address = 0x800
        | ((bold as u16) << 10)
        | (((glyph as u16) & 0x40) << 3)
        | (row as u16 * MENU_COLS as u16 + column as u16);
    display.tile_write().write(|w| unsafe {
        w.address().bits(address);
        w.glyph().bits(glyph & 0x3f)
    });
}

fn write_menu_text(
    display: &pac::TUNER_DISPLAY,
    column: u8,
    row: u8,
    text: &str,
    bold: bool,
) {
    for (offset, byte) in text.bytes().enumerate() {
        write_menu_char(display, column.saturating_add(offset as u8), row, byte, bold);
    }
}

fn write_menu_right_aligned(
    display: &pac::TUNER_DISPLAY,
    right: u8,
    row: u8,
    text: &str,
    bold: bool,
) {
    let length = text.len().min(right as usize + 1) as u8;
    write_menu_text(display, right + 1 - length, row, text, bold);
}

struct MenuEntrySnapshot {
    label: &'static str,
    value: OptionString,
    selected: bool,
    editing: bool,
}

struct MenuSnapshot {
    page_label: &'static str,
    page_bold: bool,
    page_editing: bool,
    // Eight complete 15-pixel glyph rows fit at the existing 18-pixel pitch.
    // The ninth hardware text row would cross the panel's bottom border.
    entries: [Option<MenuEntrySnapshot>; 8],
}

impl MenuSnapshot {
    fn from_options(opts: &Opts) -> Self {
        let page = opts.tracker.page.value;
        let page_label = match page {
            Page::Tuner => "TUNER",
            Page::Calibrate => "CAL",
            Page::Verify => "VERIFY",
            Page::Profiles => "PROFILES",
            Page::Settings => "SETTINGS",
            Page::Help => "HELP",
            Page::Play => "PLAY",
        };
        let page_bold = opts.selected().is_none();
        let options = opts.view().options();
        let entries = core::array::from_fn(|row| {
            let index=row;
            options.get(index).map(|option| {
                let selected = opts.selected() == Some(index);
                let label = match (page, index) {
                    // Keep the persisted option key unchanged; all inputs are
                    // acquired continuously, this selects only tuner focus.
                    (Page::Tuner, 0) => "focus",
                    (Page::Calibrate, 2) => "0v note",
                    (Page::Verify, 0) => "note",
                    (Page::Profiles, 1) => "name pos",
                    (Page::Profiles, 2) => "letter",
                    (Page::Settings, 0) => "a4 ref",
                    (Page::Settings, 1) => "save",
                    (Page::Settings, 2) => "reset",
                    _ => option.name(),
                };
                let value=if (page==Page::Verify && index==0) || (page==Page::Calibrate && index==2) {
                    let mut value=OptionString::new();
                    let note=if page==Page::Verify {opts.verify.note.value} else {opts.calibrate.zero_note.value};
                    pitch_units::write_note(&mut value,note as i32).ok();value
                } else if page==Page::Profiles && index==2 {
                    let mut value=OptionString::new();
                    let ch=opts.profiles.character.value;
                    if ch==32 {value.push_str("space").ok();} else {value.push(ch as char).ok();}
                    value
                } else {option.value()};
                MenuEntrySnapshot {
                    label,
                    value,
                    selected,
                    editing: selected && opts.modify(),
                }
            })
        });
        Self {
            page_label,
            page_bold,
            page_editing: page_bold && opts.modify(),
            entries,
        }
    }
}

#[inline(never)]
fn snapshot_menu(save_feedback: &str) -> MenuSnapshot {
    let mut menu = with_app(|app| MenuSnapshot::from_options(&app.ui.opts));
    if menu.page_label == "SETTINGS" && !save_feedback.is_empty() {
        if let Some(entry) = menu.entries[1].as_mut() {
            entry.value.clear();
            entry.value.push_str(save_feedback).ok();
        }
    }
    menu
}

#[inline(never)]
fn publish_menu(display: &pac::TUNER_DISPLAY, menu: &MenuSnapshot) {
    clear_menu_text(display);
    write_menu_right_aligned(
        display,
        MENU_PAGE_COLUMN + MENU_PAGE_WIDTH - 1,
        0,
        menu.page_label,
        menu.page_bold,
    );
    if menu.page_editing {
        write_menu_char(
            display,
            MENU_PAGE_COLUMN + MENU_PAGE_WIDTH - 1,
            1,
            b'^',
            true,
        );
    }

    for (index, entry) in menu.entries.iter().enumerate() {
        if let Some(entry) = entry {
            write_menu_text(
                display,
                MENU_ITEM_COLUMN,
                index as u8,
                entry.label,
                entry.selected,
            );
            write_menu_right_aligned(
                display,
                MENU_VALUE_RIGHT,
                index as u8,
                &entry.value,
                entry.selected,
            );
            if entry.editing {
                write_menu_char(display, MENU_EDIT_COLUMN, index as u8, b'<', true);
            }
        }
    }
}

#[inline(never)]
fn publish_tuner(
    display: &pac::TUNER_DISPLAY,
    text: &mut TextWriter<'_>,
    measurements: &MeasurementBank,
    reference_hz: f32,
    input: u8,
    display_mode: DisplayMode,
    smoothed_channels: &mut [Option<f32>;4],
    menu_active: bool,
) {
    let measurement = measurements.channel(input);
    let smoothed_midi = &mut smoothed_channels[input as usize];
    let cx = 360;
    let cy = 360;
    let outer_radius = 228;
    let inner_radius = 52;
    let octave_spacing = (outer_radius - inner_radius) as f32 / 8.0;

    let mut note_line: String<32> = String::new();
    let mut cents_line: String<32> = String::new();
    let mut frequency_line: String<48> = String::new();
    let mut voltage_line: String<48> = String::new();

    let mut marker = None;
    if measurement.valid {
        let midi_float = pitch_math::semitones(measurement.frequency_hz,reference_hz);
        let display_midi = match *smoothed_midi {
            Some(previous) if (midi_float - previous).abs() <= 2.0 => {
                previous + (midi_float - previous) * 0.20
            }
            _ => midi_float,
        };
        *smoothed_midi = Some(display_midi);
        let midi_note = midi_float.round().max(0.0).min(127.0) as i32;
        let cents = (100.0 * (midi_float - midi_note as f32)).round() as i32;
        let pitch_class = midi_note.rem_euclid(12) as usize;
        let octave = midi_note / 12 - 1;
        write!(note_line, "{}{}", NOTE_NAMES[pitch_class], octave).ok();
        write!(cents_line, "{:^20}", format_args!("{:+04} CENTS", cents)).ok();
        write!(
            frequency_line,
            "{:^24}",
            format_args!("{:8.2} HZ   IN {}", measurement.frequency_hz, input)
        )
        .ok();
        write!(
            voltage_line,
            "{:^28}",
            format_args!("{:5.3} VRMS  {:5.3} VPP", measurement.vrms, measurement.vpp)
        )
        .ok();

        let octave_turns = ((display_midi - 12.0) / 12.0).max(0.0).min(8.0);
        let marker_radius = inner_radius as f32 + octave_spacing * octave_turns;
        let (x, y) = spiral_point(cx, cy, marker_radius, display_midi / 12.0);
        let marker_hue = CHANNEL_HUES[input as usize];
        // 32 unoriented lens axes cover a half-turn at 5.625-degree steps. The small
        // positive correction follows the Archimedean spiral's outward slope
        // rather than merely touching its corresponding circular ring.
        let tangent_turn = display_midi / 12.0 * 64.0
            + 64.0 * octave_spacing
                / (core::f32::consts::TAU * core::f32::consts::TAU * marker_radius);
        let marker_angle = (tangent_turn.round() as i32).rem_euclid(32) as u32;
        marker = Some(Marker {
            x,
            y,
            hue: marker_hue,
            orientation: marker_angle as u8,
        });
        if display_mode == DisplayMode::Linear {
            // Use the unfiltered estimate before rounding the numeric label,
            // not the spiral's cosmetic smoothing or whole-cent steps.
            marker = Some(Marker {
                x: ui_canvas::cents_position(100.0 * (midi_float - midi_note as f32))
                    .unwrap_or(360),
                y: ui_canvas::LINEAR_LANES[input as usize] as u16,
                hue: marker_hue,
                orientation: 16,
            });
        }
    } else {
        *smoothed_midi = None;
        write!(note_line, "--").ok();
        write!(cents_line, "{:^20}", "WAITING FOR SIGNAL").ok();
        write!(frequency_line, "{:^24}", format_args!("IN {}", input)).ok();
        write!(
            voltage_line,
            "{:^28}",
            format_args!("{:5.3} VRMS  {:5.3} VPP", measurement.vrms, measurement.vpp)
        )
        .ok();
    }

    // The compact menu overlays only the established right-side panel, so the
    // underlying tuner remains complete and live while it is open.
    let linear = display_mode == DisplayMode::Linear;
    if !linear {
        write_centered(text, 20, &note_line, 8);
        write_centered(text, 22, &cents_line, 20);
        write_centered(text, 37, &frequency_line, 24);
        write_centered(text, 39, &voltage_line, 28);
    }
    let mut markers = [marker, None, None, None];
    let mut slot = 1;
    for channel in 0..4usize {
        let value = measurements.channel(channel as u8);
        let style = ui_text::Style { color: 0xC0 | CHANNEL_HUES[channel], bold: input as usize == channel };
        if linear {
            let row = [12,18,25,31][channel];
            let mut label: String<48> = String::new();
            if value.valid {
                let midi = pitch_math::semitones(value.frequency_hz,reference_hz);
                let note = midi.round() as i32;
                write!(label,"{} {}{} {:+04}c {:8.2}Hz",channel,
                       NOTE_NAMES[note.rem_euclid(12) as usize],note.div_euclid(12)-1,
                       (100.0*(midi-note as f32)).round() as i32,value.frequency_hz).ok();
            } else { write!(label,"{} -- NO SIGNAL",channel).ok(); }
            ui_text::field(6,row,33,&label,style,ui_text::Align::Center,|address,cell|text.cell(address,cell));
            let mut volts: String<48> = String::new();
            write!(volts,"{:5.3} Vrms  {:5.3} Vpp",value.vrms,value.vpp).ok();
            ui_text::field(6,[16,22,29,35][channel],33,&volts,style,ui_text::Align::Center,
                           |address,cell|text.cell(address,cell));
        } else {
            let mut label: String<4> = String::new();
            write!(label,"{}{}",if input as usize == channel { ">" } else { " " },channel).ok();
            ui_text::field(15+channel*4,3,2,&label,style,ui_text::Align::Left,|address,cell|text.cell(address,cell));
        }
        if channel != input as usize {
            markers[slot] = other_channel_marker(value,reference_hz,channel,linear,&mut smoothed_channels[channel]);
            slot += 1;
        }
    }
    publish_markers(display, Markers(markers),
                    display_mode == DisplayMode::Visualizer, menu_active);
}

const CHANNEL_HUES: [u8;4] = [1,5,9,13];
mod pitch_units;

fn publish_profiles(display:&pac::TUNER_DISPLAY,text:&mut TextWriter<'_>,
                    cal:&calibration_live::Live,editor:&oscillator_calibration::name::Editor,
                    slot:u8,position:u8,status:&str,menu_active:bool) {
    write_centered(text,3,"OSCILLATOR PROFILES",28);
    let mut line:String<48>=String::new();
    write!(line,"STORAGE SLOT {} OF 4",slot).ok();write_centered(text,8,&line,30);
    write_centered(text,10,"SAVE REPLACES SELECTED SLOT",32);
    write_centered(text,12,"LOAD NEVER STARTS OUTPUT",30);
    write_centered(text,15,"NAME DRAFT",24);
    write_centered(text,17,editor.name(),26);
    line.clear();write!(line,"EDIT CHARACTER {} OF 24",position).ok();write_centered(text,19,&line,30);
    line.clear();
    match status {
        "PROFILE LOADED - OUTPUT OFF" => {write!(line,"LOADED SLOT {} - OUTPUT OFF",slot).ok();}
        "PROFILE SAVED" => {write!(line,"SAVED SLOT {} - READBACK OK",slot).ok();}
        _ => {line.push_str(status).ok();}
    }
    write_centered(text,34,&line,34);
    if let Some(profile)=cal.profile.as_ref() {
        line.clear();write!(line,"RAM: {}",profile.name()).ok();write_centered(text,36,&line,34);
        let route=cal.profile_route.unwrap();
        line.clear();write!(line,"{} POINTS  IN {} -> OUT {}",profile.points().len(),route.input(),route.output()).ok();
        write_centered(text,38,&line,32);
    } else {write_centered(text,36,"NO ACTIVE CALIBRATION",30);}
    write_centered(text,41,"KEEP OSCILLATOR TUNING FIXED",30);
    publish_markers(display,Markers([None;4]),false,menu_active);
}

fn publish_verification(display:&pac::TUNER_DISPLAY,text:&mut TextWriter<'_>,
                        cal:&calibration_live::Live,controls:RuntimeControls,
                        value:ChannelMeasurement,menu_active:bool) {
    write_centered(text,3,"VERIFY CALIBRATION",28);
    let mut line:String<48>=String::new();
    if let Some(route)=cal.profile_route {
        write!(line,"OUT {} -> V/OCT; AUDIO -> IN {}",route.output(),route.input()).ok();
        write_centered(text,8,&line,34);
    } else {write_centered(text,8,"RUN CALIBRATION FIRST",30);}
    write_centered(text,10,"KEEP THE CALIBRATION PATCH",30);
    write_centered(text,12,"DO NOT RETUNE THE OSCILLATOR",32);
    let target=if cal.verifying {cal.target_millicents} else if controls.verify_scan && cal.scan.is_some() {
        cal.scan.as_ref().unwrap().target
    } else if cal.verifying {cal.target_millicents} else {controls.target_millicents};
    line.clear();write!(line,"TARGET ").ok();
    pitch_units::write_pitch(&mut line,target).ok();
    write!(line,"  {:+.3} V",pitch_units::nominal_volts(target,controls.zero_note)).ok();
    write_centered(text,15,&line,34);
    line.clear();write!(line,"0 V = ").ok();
    pitch_units::write_note(&mut line,controls.zero_note as i32).ok();
    write!(line,"; 1 V/OCT; A4 440").ok();write_centered(text,17,&line,34);
    if let Some(profile)=cal.profile.as_ref() {
        let points=profile.points();
        line.clear();pitch_units::write_pitch(&mut line,points[0].millicents).ok();
        write!(line," TO ").ok();
        pitch_units::write_pitch(&mut line,points[points.len()-1].millicents).ok();
        write_centered(text,19,&line,34);
    }
    write_centered(text,32,if cal.verifying {cal.status}
        else if cal.profile.is_none() {"NO COMPLETED CAL - VERIFY BLOCKED"}
        else if cal.status=="DONE - PROFILE IN RAM" {"READY - RUN IN MENU"}
        else {cal.status},32);
    line.clear();write!(line,"CORRECTED OUT {:.3} V",cal.millivolts as f32/1000.0).ok();
    write_centered(text,34,&line,32);
    if let Some(r)=cal.refinement.as_ref() {
        line.clear();
        if r.check.tested<9 {write!(line,"REFINE MEASURE {} / 9",r.check.tested).ok();}
        else {write!(line,"REFINE COMPARE {} / {}",r.tested,r.total()).ok();}
        write_centered(text,36,&line,32);
        line.clear();
        if r.total()>0 && r.tested==r.total() {
            write!(line,"WORST OLD {:.2}c NEW {:.2}c",r.original_worst,r.candidate_worst).ok();
        } else {write!(line,"COMPARISON NOT YET COMPLETE").ok();}
        write_centered(text,38,&line,34);
        write_centered(text,40,"ORIGINAL PROFILE PRESERVED",32);
        write_centered(text,42,if r.stage==oscillator_calibration::refinement::Stage::Ready {
            "MENU: ACCEPT OR DISCARD"
        } else {r.reason},34);
        publish_markers(display,Markers([None;4]),false,menu_active);return;
    }
    if !controls.verify_scan || cal.scan.is_none() {
        line.clear();
        if cal.verifying && value.valid {write!(line,"MEASURED {:.2} HZ",value.frequency_hz).ok();}
        else if cal.verifying {write!(line,"NO VALID AUDIO PITCH").ok();}
        else {write!(line,"OUTPUT STOPPED").ok();}
        write_centered(text,36,&line,32);
        line.clear();
        if let Some(error)=cal.error_cents {write!(line,"DEVIATION {:+.2} CENTS",error).ok();}
        else if !cal.verifying {write!(line,"DEVIATION: --").ok();}
        else if cal.status!="CORRECTED TARGET ACTIVE" {write!(line,"WAITING FOR OUTPUT / SETTLING").ok();}
        else if !value.valid {write!(line,"CHECK AUDIO INPUT {}",cal.input).ok();}
        else {write!(line,"WAITING FOR QUALIFIED PITCH").ok();}
        write_centered(text,38,&line,34);
        line.clear();
        if let Some(summary)=cal.deviation {
            write!(line,"MEAN {:+.2}c  SPAN {:.2}c",summary.mean,summary.spread).ok();
        } else {write!(line,"MEAN / SPAN: --").ok();}
        write_centered(text,40,&line,32);
    }
    if controls.verify_scan {
        if let Some(scan)=cal.scan.as_ref() {
            line.clear();write!(line,"{} {} / {} TARGETS",if scan.points_mode {"POINTS"} else {"SCAN"},scan.tested,scan.total).ok();
            write_centered(text,36,&line,32);
            line.clear();
            if scan.tested>0 {
                write!(line,"WORST {:+.2}c AT ",scan.worst_error).ok();
                if scan.points_mode {
                    let uv=cal.profile.as_ref().unwrap().points()[scan.worst_index].microvolts;
                    write!(line,"{:.4} V",uv as f32/1000000.0).ok();
                } else {pitch_units::write_pitch(&mut line,scan.worst_pitch).ok();}
            } else {write!(line,"WAITING FOR STABLE SAMPLES").ok();}
            write_centered(text,38,&line,34);
            line.clear();
            if scan.points_mode {
                for (index,error) in scan.first_errors.iter().enumerate() {
                    if let Some(error)=error {write!(line,"P{} {:+.2}c  ",index,error).ok();}
                    else {write!(line,"P{} --  ",index).ok();}
                }
            } else {write!(line,"MAX SPAN {:.2}c",scan.max_spread).ok();}
            write_centered(text,40,&line,32);
        }
        if let Some(check)=cal.scan.as_ref().and_then(|s|s.local.as_ref()) {
            line.clear();
            if check.tested==9 {write!(line,"{}",check.advice()).ok();}
            else {write!(line,"LOCAL CHECK {} / 9",check.tested).ok();}
            write_centered(text,42,&line,30);
        } else {
            write_centered(text,42,if controls.verify_points {"POINTS: STORED CV / PITCH"}
                else {"SCAN: RANGE IN 50-CENT STEPS"},30);
        }
    } else {write_centered(text,42,"EXIT VERIFY STOPS OUTPUT",28);}
    publish_markers(display,Markers([None;4]),false,menu_active);
}

fn publish_playback(display:&pac::TUNER_DISPLAY,text:&mut TextWriter<'_>,
                    cal:&calibration_live::Live,controls:RuntimeControls,value:ChannelMeasurement,menu:bool) {
    let now=with_app(|app|app.now_ms as u32);
    let (active,status,input,output,uv,out,pitch,updates,cycles,settled)=critical_section::with(|cs| {
        let p=PLAYBACK.borrow_ref(cs);
        (p.active,p.status,p.input,p.output,p.input_uv,p.output_uv,p.pitch,p.updates,p.max_cycles,
            p.feedback_ready(now,value.window_age_ms,value.end_age_ms))
    });
    let mut line=String::<96>::new();
    write_centered(text,4,"CALIBRATED CV PLAYBACK",28);
    write_centered(text,10,"PITCH CV -> SELECTED INPUT",30);
    if let Some(route)=cal.profile_route {
        write!(line,"OUT {} -> OSCILLATOR V/OCT",route.output()).ok();
        write_centered(text,13,&line,32);line.clear();
    }
    write!(line,"OSC AUDIO -> IN {} (PITCH CHECK)",cal.input).ok();
    write_centered(text,16,&line,34);line.clear();
    write_centered(text,19,"RUN STARTS / STOPS; EXIT STOPS",34);
    write!(line,"0 V = {}{}; 1 V/OCT",NOTE_NAMES[(controls.zero_note%12) as usize],
        controls.zero_note as i32/12-1).ok();
    write_centered(text,23,&line,32);line.clear();
    let chromatic=with_app(|app|app.ui.opts.play.quantize.value==options::QuantizeMode::Chromatic);
    write_centered(text,26,if chromatic {"CHROMATIC - 5c HYSTERESIS"} else {"CONTINUOUS - NO QUANTIZATION"},34);
    write_centered(text,29,status,38);
    write!(line,"IN {} {:+.4} V -> OUT {} {:+.4} V",input,uv as f32/1e6,output,out as f32/1e6).ok();
    write_centered(text,33,&line,42);line.clear();
    if active && updates>0 {pitch_units::write_pitch(&mut line,pitch).ok();write_centered(text,36,&line,30);line.clear();}
    if active && value.valid && value.qualified {
        if settled {
            write!(line,"AUDIO {:.2} Hz ERROR {:+.2}c",value.frequency_hz,
                (pitch_math::millicents(value.frequency_hz,440.0) as i64-pitch as i64) as f32/1000.0).ok();
        } else {write!(line,"AUDIO {:.2} Hz - SETTLING",value.frequency_hz).ok();}
        write_centered(text,38,&line,42);line.clear();
    } else {write_centered(text,38,"AUDIO CHECK: NO QUALIFIED PITCH",42);}
    write!(line,"UPDATES {} MAX {} CPU CYCLES",updates,cycles).ok();
    write_centered(text,40,&line,42);
    publish_markers(display,Markers([None;4]),false,menu);
}

pub fn playback_visible()->bool {with_app(|app|app.ui.opts.tracker.page.value==Page::Play)}
pub fn write_playback_status(out:&mut impl core::fmt::Write,value:ChannelMeasurement)->core::fmt::Result {
    let now=with_app(|app|app.now_ms as u32);
    let (active,status,input,output,uv,voltage,updates,cycles,gap,pitch,chromatic,settled)=critical_section::with(|cs| {
        let p=PLAYBACK.borrow_ref(cs);
        (p.active,p.status,p.input,p.output,p.input_uv,p.output_uv,p.updates,p.max_cycles,p.max_gap_cycles,p.pitch,p.chromatic,
            p.feedback_ready(now,value.window_age_ms,value.end_age_ms))
    });
    writeln!(out,"PLAY ACTIVE={} STATUS={} IN={} OUT={} INPUT_UV={} OUTPUT_UV={} UPDATES={} MAX_CYCLES={} MAX_GAP_CYCLES={}",
        active,status,input,output,uv,voltage,updates,cycles,gap)?;
    writeln!(out,"PLAY QUANTIZE={}",if chromatic {"CHROMATIC"} else {"OFF"})?;
    if active && value.valid && value.qualified {
        if settled {
            writeln!(out,"PLAY AUDIO_HZ={:.3} TARGET_MC={} ERROR_C={:+.2}",value.frequency_hz,pitch,
                (pitch_math::millicents(value.frequency_hz,440.0) as i64-pitch as i64) as f32/1000.0)?;
        } else {writeln!(out,"PLAY AUDIO_HZ={:.3} TARGET_MC={} CHECK=SETTLING",value.frequency_hz,pitch)?;}
    }
    Ok(())
}

fn publish_calibration(display:&pac::TUNER_DISPLAY,text:&mut TextWriter<'_>,
                       cal:&calibration_live::Live,controls:RuntimeControls,
                       value:ChannelMeasurement,menu_active:bool) {
    let input=if cal.active() {cal.input} else {controls.calibration_input};
    let output=if cal.active() {cal.output} else {controls.calibration_output};
    write_centered(text,3,"OSCILLATOR CALIBRATION",28);
    let mut line:String<48>=String::new();
    write!(line,"OUT {} -> OSC V/OCT",output).ok(); write_centered(text,8,&line,30);
    line.clear();write!(line,"OSC AUDIO -> IN {}",input).ok();write_centered(text,10,&line,30);
    write_centered(text,12,"USE SINE; VCO MID RANGE",30);
    write_centered(text,14,"UPWARD -5 TO +5V; 121 PTS",30);
    write_centered(text,16,"RUN AGAIN TO CANCEL",30);
    write_centered(text,18,"EXIT CAL ALSO CANCELS",30);
    if let Some(profile)=cal.pending_profile.as_ref() {
        let points=profile.points();let low=points[0];let high=points[points.len()-1];
        write_centered(text,12,"SCAN COMPLETE - OUTPUT ZERO",30);
        write_centered(text,14,"ACCEPT: USE RESULT IN RAM",30);
        write_centered(text,16,"RUN: ADJUST AND RESCAN",30);
        write_centered(text,18,"DISCARD: KEEP PRIOR PROFILE",30);
        line.clear();write!(line,"{} POINTS; {:.2} OCTAVES",points.len(),
            (high.millicents-low.millicents) as f32/1_200_000.0).ok();
        write_centered(text,20,&line,32);
        line.clear();write!(line,"CV {:+.3} TO {:+.3} V",low.microvolts as f32/1e6,high.microvolts as f32/1e6).ok();
        write_centered(text,22,&line,32);
        line.clear();pitch_units::write_pitch(&mut line,low.millicents).ok();
        write!(line," TO ").ok();pitch_units::write_pitch(&mut line,high.millicents).ok();
        write_centered(text,24,&line,32);
        write_centered(text,26,oscillator_calibration::discovery::advice(profile),32);
        write_centered(text,28,"ADVICE IS NOT A RANGE GUARANTEE",32);
        write_centered(text,30,"RETUNING REQUIRES A NEW SCAN",32);
        write_centered(text,32,cal.status,32);
        write_centered(text,34,"SAVED SLOTS ARE UNCHANGED",32);
        write_centered(text,36,"ACCEPT DOES NOT SAVE TO FLASH",32);
        write_centered(text,38,"SAVE SEPARATELY IN PROFILES",32);
        write_centered(text,41,"ENCODER: MENU",24);
        publish_markers(display,Markers([None;4]),false,menu_active);
        return;
    }
    for row in [22,24,26,28] {write_centered(text,row,"",32);}
    if let Some(failure)=cal.tracking_failure {
        if let Some(previous)=failure.neighbour {
            line.clear();write!(line,"PREV {:+.4}V ",previous.microvolts as f32/1e6).ok();
            pitch_units::write_pitch(&mut line,previous.millicents).ok();
            write_centered(text,22,&line,32);
            line.clear();write!(line,"PITCH STEP {:+.2} CENTS",
                (failure.rejected.millicents as i64-previous.millicents as i64) as f32/1000.0).ok();
            write_centered(text,26,&line,32);
        }
        line.clear();write!(line,"FAIL {:+.4}V ",failure.rejected.microvolts as f32/1e6).ok();
        pitch_units::write_pitch(&mut line,failure.rejected.millicents).ok();
        write_centered(text,24,&line,32);
        if let Some((raw,factor))=cal.rejected_detector {
            line.clear();write!(line,"RAW {:.2}Hz /{}",raw,factor).ok();
            write_centered(text,28,&line,32);
        }
    }
    line.clear();
    if let Some(error)=cal.zero_error_cents {
        write!(line,"ZERO CHECK {:+.2}c (LIMIT 3c)",error).ok();
    } else if let Some(diagnostic)=cal.rejected_verifier {
        if diagnostic.span!=0 {
            write!(line,"1X MISMATCH {:.2}%",
                diagnostic.error as f32*100.0/(256.0*diagnostic.span as f32)).ok();
        }
    }
    write_centered(text,30,&line,32);
    line.clear();
    if let Some(diagnostic)=cal.rejected_verifier {
        write!(line,"LAG {:.3} SAMPLES; DIV {}",
            diagnostic.lag_q8 as f32/256.0,diagnostic.divisor).ok();
    }
    write_centered(text,20,&line,32);
    write_centered(text,32,cal.status,32);
    line.clear();write!(line,"POINT {}/{}   OUT {:.3} V",cal.point,cal.point_count,cal.millivolts as f32/1000.0).ok();
    write_centered(text,34,&line,32);
    line.clear();
    if value.valid {write!(line,"{:.2} Hz  {:.3} Vpp",value.frequency_hz,value.vpp).ok();}
    else {write!(line,"NO SIGNAL").ok();}
    write_centered(text,36,&line,32);
    if let Some(profile)=cal.profile.as_ref() {
        let points=profile.points();
        line.clear();write!(line,"RAM: {} PTS, {:.1} CENTS",points.len(),
            (points.last().unwrap().millicents-points[0].millicents) as f32/1000.0).ok();
        write_centered(text,38,&line,32);
    } else {write_centered(text,38,"NO COMPLETED CALIBRATION PROFILE",32);}
    write_centered(text,41,"ENCODER: MENU",24);
    publish_markers(display,Markers([None;4]),false,menu_active);
}

fn other_channel_marker(value: ChannelMeasurement, reference: f32, channel: usize,
                        linear: bool, smooth: &mut Option<f32>) -> Option<Marker> {
    if !value.valid { *smooth = None; return None; }
    let midi = pitch_math::semitones(value.frequency_hz,reference);
    let drawn = match *smooth {
        Some(previous) if (midi-previous).abs() <= 2.0 => previous+(midi-previous)*0.20,
        _ => midi,
    };
    *smooth = Some(drawn);
    let hue = CHANNEL_HUES[channel];
    if linear {
        return Some(Marker { x:ui_canvas::cents_position(100.0*(midi-midi.round()))?,
            y:ui_canvas::LINEAR_LANES[channel] as u16,hue,orientation:16 });
    }
    let radius = 52.0+22.0*((drawn-12.0)/12.0).max(0.0).min(8.0);
    let (x,y) = spiral_point(360,360,radius,drawn/12.0);
    let tangent = drawn/12.0*64.0 + 64.0*22.0/(core::f32::consts::TAU*core::f32::consts::TAU*radius);
    Some(Marker {x,y,hue,orientation:(tangent.round() as i32).rem_euclid(32) as u8})
}

fn publish_markers(display: &pac::TUNER_DISPLAY, markers: Markers,
                   visualizer: bool, menu_active: bool) {
    let marker = markers.0[0].filter(|value| value.packed() != 0);
    display.marker().write(|w| unsafe {
        if let Some(marker) = marker {
            w.x().bits(marker.x);
            w.y().bits(marker.y);
            w.hue().bits(marker.hue);
            w.valid().bit(true);
            w.visualizer().bit(visualizer);
            w.menu_active().bit(menu_active)
        } else {
            w.x().bits(0);
            w.y().bits(0);
            w.hue().bits(0);
            w.valid().bit(false);
            w.visualizer().bit(visualizer);
            w.menu_active().bit(menu_active)
        }
    });
    display.marker_shape().write(|w| unsafe {
        w.base().bits(marker.map_or(0, Marker::lens_base));
        w.bank().bits(marker.map_or(0, Marker::lens_bank))
    });
    display.marker1().write(|w| unsafe { w.bits(markers.packed(1)) });
    display.marker2().write(|w| unsafe { w.bits(markers.packed(2)) });
    display.marker3().write(|w| unsafe { w.bits(markers.packed(3)) });
}

#[derive(Clone, Copy)]
struct UiFrame {
    run_play:bool,
    controls: RuntimeControls,
    save: bool,
    wipe: bool,
    menu_active: bool,
    menu_dirty: bool,
    run_calibration: bool,
    accept_scan:bool,
    discard_scan:bool,
    run_verify: bool,
    refine:bool,
    accept_refinement:bool,
    discard_refinement:bool,
    profile_slot:u8,
    name_position:u8,
    name_character:u8,
    save_profile:bool,
    load_profile:bool,
    now_ms: u64,
}

fn poll_ui_frame() -> UiFrame {
    with_app(|app| {
        let save = app.ui.opts.settings.save_opts.poll();
        let wipe = app.ui.opts.settings.wipe_opts.poll();
        let menu_active = app.ui.draw();
        app.ui.set_menu_visible(menu_active);
        UiFrame {
            run_play:app.ui.opts.play.run.poll(),
            run_calibration: app.ui.opts.calibrate.run.poll(),
            accept_scan:app.ui.opts.calibrate.accept.poll(),
            discard_scan:app.ui.opts.calibrate.discard.poll(),
            run_verify: app.ui.opts.verify.run.poll(),
            refine:app.ui.opts.verify.refine.poll(),
            accept_refinement:app.ui.opts.verify.accept.poll(),
            discard_refinement:app.ui.opts.verify.discard.poll(),
            profile_slot: app.ui.opts.profiles.slot.value,
            name_position: app.ui.opts.profiles.position.value,
            name_character: app.ui.opts.profiles.character.value,
            save_profile: app.ui.opts.profiles.save.poll(),
            load_profile: app.ui.opts.profiles.load.poll(),
            now_ms: app.now_ms,
            controls: RuntimeControls::from_options(&app.ui.opts),
            save,
            wipe,
            menu_active,
            menu_dirty: app.ui.take_menu_dirty(),
        }
    })
}

/// Saving is deliberately isolated from the real-time loop. `Opts` is cloned
/// only for an explicit save request, never on every 5-ms wakeup.
#[inline(never)]
fn snapshot_options_for_save() -> Opts {
    with_app(|app| app.ui.opts.clone())
}

fn reset_options() {
    with_app(|app| {
        app.ui.opts = Opts::default();
        app.ui.external_modify();
    });
}

type TunerPersistence = FlashOptionsPersistence<SPIFlash0,1100>;

fn expanded_window(storage:&TunerPersistence)->core::ops::Range<u32> {
    let base=storage.default_window().start;
    base+8192..base+24576
}

fn profile_key(slot:u8)->Option<u32> {
    let key=oscillator_calibration::storage::key(slot)?;
    if with_app(|app| app.ui.opts.all().any(|o|o.key().value()==key)) {None} else {Some(key)}
}

#[inline(never)]
fn save_profile(storage:&mut Option<TunerPersistence>,cal:&mut calibration_live::Live,
                slot:u8,zero_note:u8,name:&str)->&'static str {
    use oscillator_calibration::storage as record;
    if cal.active() {return "BUSY - STOP OUTPUT FIRST";}
    if cal.pending_profile.is_some() {return "ACCEPT OR DISCARD CAL FIRST";}
    if cal.refinement.as_ref().is_some_and(|r|r.stage==oscillator_calibration::refinement::Stage::Ready) {
        return "ACCEPT OR DISCARD FIRST";
    }
    let (Some(profile),Some(route))=(cal.profile.as_ref(),cal.profile_route) else {return "NO CALIBRATION TO SAVE";};
    let Some(key)=profile_key(slot) else {return "INVALID PROFILE SLOT";};
    let Some(storage)=storage.as_mut() else {return "NO PROFILE STORAGE";};
    let mut bytes=[0;record::MAX_BYTES];
    let Ok(len)=record::encode(profile,route,zero_note,name,&mut bytes) else {return "INVALID NAME / PROFILE";};
    if storage.save_key_in(expanded_window(storage),key,&bytes[..len]).is_err() {return "SAVE FAILED";}
    let mut check=[0;record::MAX_BYTES+1];
    if !matches!(storage.load_key_in(expanded_window(storage),key,&mut check),Ok(Some(n)) if n==len && check[..n]==bytes[..len]) {
        return "SAVE READBACK FAILED";
    }
    cal.profile.as_mut().unwrap().rename(name).ok();
    "PROFILE SAVED"
}

#[inline(never)]
fn load_profile(storage:&mut Option<TunerPersistence>,cal:&mut calibration_live::Live,
                slot:u8,editor:&mut oscillator_calibration::name::Editor)->(&'static str,Option<u8>) {
    use oscillator_calibration::storage as record;
    if cal.active() {return ("BUSY - STOP OUTPUT FIRST",None);}
    let Some(key)=profile_key(slot) else {return ("INVALID PROFILE SLOT",None);};
    let Some(storage)=storage.as_mut() else {return ("NO PROFILE STORAGE",None);};
    let mut bytes=[0;record::MAX_BYTES+1];
    // Fall back only when absent, never hide a corrupt/newer record by loading
    // an old calibration. Legacy journal is read-only for profile operations.
    let result=match storage.load_key_in(expanded_window(storage),key,&mut bytes) {
        Ok(None)=>storage.load_key(key,&mut bytes),other=>other,
    };
    let len=match result {
        Ok(Some(n))=>n,Ok(None)=>return ("EMPTY PROFILE SLOT",None),Err(_)=>return ("PROFILE READ FAILED",None),
    };
    decode_profile(&bytes[..len],cal,editor)
}

// Decoding moves a complete profile. Keep its temporaries out of the frame
// that calls the flash journal reader, which has its own nested buffers.
#[inline(never)]
fn decode_profile(bytes:&[u8],cal:&mut calibration_live::Live,
                  editor:&mut oscillator_calibration::name::Editor)->(&'static str,Option<u8>) {
    let Ok(record)=oscillator_calibration::storage::decode(bytes) else {return ("INVALID STORED PROFILE",None);};
    let zero=record.zero_note;
    if !cal.recall(record) {return ("BUSY - STOP OUTPUT FIRST",None);}
    editor.set(cal.profile.as_ref().unwrap().name());
    ("PROFILE LOADED - OUTPUT OFF",Some(zero))
}

struct RuntimeResources {
    uart: pac::UART0,
    hardware_calibration:Option<(i32,i32,u8)>,
    hardware_calibration_bits:u8,
    timer: Timer0,
    tuner: pac::TUNER_PERIPH,
    display: pac::TUNER_DISPLAY,
    persistence: Option<TunerPersistence>,
    counts_per_v: f32,
    video_size: (u16, u16),
}

/// Complete all allocation-heavy and deserialization-heavy startup work before
/// enabling interrupts. Its stack frame is released before `run()` begins.
#[inline(never)]
fn startup() -> RuntimeResources {
    let peripherals = pac::Peripherals::take().unwrap();
    let sysclk = pac::clock::sysclk();
    peripherals.PLAYBACK_TIMER.enable().write(|w|w.enable().bit(false));
    peripherals.PLAYBACK_TIMER.reload().write(|w|unsafe{w.value().bits(u32::MAX)});
    peripherals.PLAYBACK_TIMER.mode().write(|w|w.periodic().bit(true));
    peripherals.PLAYBACK_TIMER.enable().write(|w|w.enable().bit(true));
    let timer = Timer0::new(peripherals.TIMER0, sysclk);
    let spiflash = SPIFlash0::new(peripherals.SPIFLASH_CTRL, SPIFLASH_BASE, SPIFLASH_SZ_BYTES);

    // Do not install the synchronous UART logger in the real-time tuner.
    // Calibration and option loading both log from inside peripheral access
    // paths; if the USB/UART consumer is absent or backpressured, Serial0's
    // blocking fmt::Write implementation can wedge startup before the timer
    // interrupt (and therefore the encoder, LEDs and measurements) is enabled.
    // Runtime diagnostics here must use a bounded/non-blocking transport.

    let bootinfo = unsafe { bootinfo::BootInfo::from_addr(BOOTINFO_BASE) }.unwrap();
    let modeline = bootinfo
        .modeline
        .maybe_override_fixed(FIXED_MODELINE, CLOCK_DVI_HZ);
    let mut video = DMAFramebuffer0::new(
        peripherals.FRAMEBUFFER_PERIPH,
        peripherals.PALETTE_PERIPH,
        PSRAM_FB_BASE,
        modeline.clone(),
    );
    // Static guide pixels are CPU-authored once; live text and marker state
    // are published together through the double-buffered overlay below.
    palette::ColorPalette::default().write_to_hardware(&mut video);
    let mut background = BackgroundCanvas::new(
        PSRAM_FB_BASE,
        modeline.h_active,
        modeline.v_active,
        ROUND_DISPLAY,
    );
    background.clear();
    background.draw_static_tuner();
    background.finish();
    video.enable();
    let tuner_display = peripherals.TUNER_DISPLAY;

    let mut pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
    let counts_per_v = pmod.counts_per_v() as f32;
    // Preserve load_or_default behavior, but retain read-only diagnostics so
    // a missing EEPROM record cannot masquerade as factory-calibrated zero.
    let hardware_calibration_bits=pmod.f_bits();
    let hardware_calibration=calibration::CalibrationConstants::from_eeprom(
        &mut I2c1::new(peripherals.I2C1)).map(|constants| {
            constants.write_to_pmod(&mut pmod);
            (constants.cal.dac_scale[1],constants.cal.dac_zero[1],constants.cal.fractional_bits)
        });

    let mut opts = Opts::default();
    let persistence = if let Some(window) = bootinfo.manifest.get_option_storage_window() {
        let default=window.start..window.start.saturating_add(8192);
        match TunerPersistence::with_reserved_buffer(spiflash,default,window) {
            Ok(mut storage)=>{storage.load_options(&mut opts).ok();Some(storage)}
            Err(_)=>{warn!("Invalid option storage window");None}
        }
    } else {
        warn!("No option storage region; settings will not persist");
        None
    };
    // Recall instrument settings, not the navigation position saved alongside
    // them. Start at the TUNER page heading on every boot, outside edit mode.
    opts.tracker.page.value = Page::Tuner;
    // Name drafts are not profiles and must not restore half-edited characters.
    opts.profiles.position.value=1;opts.profiles.character.value=b'O';
    opts.tracker.selected = None;
    opts.tracker.modify = false;
    install_app(opts);
    with_app(|app| {
        app.ui.clear_draw();
        app.ui.set_menu_visible(false);
    });

    RuntimeResources {
        timer,
        tuner: peripherals.TUNER_PERIPH,
        display: tuner_display,
        persistence,
        counts_per_v,
        video_size: (modeline.h_active, modeline.v_active),
        uart: peripherals.UART0,
        hardware_calibration,
        hardware_calibration_bits,
    }
}

/// The perpetual real-time phase has a deliberately small, stable stack frame.
/// Large startup temporaries and the retained UI are no longer live here.
#[inline(never)]
fn run(resources: &mut RuntimeResources) -> ! {
    let RuntimeResources {
        uart,
        hardware_calibration,
        hardware_calibration_bits,
        timer,
        tuner,
        display: tuner_display,
        persistence,
        counts_per_v,
        video_size,
    } = resources;
    // Borrow the single flash buffer in main instead of retaining another
    // 1.1 KiB copy in this never-returning frame.
    let counts_per_v=*counts_per_v;
    let video_size=*video_size;
    handler!(timer0 = || timer0_handler());

    irq::scope(|scope| {
        scope.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(PLAYBACK_PERIOD_MS, pac::Interrupt::TIMER0);
        let sample_rate = tuner.info().read().sample_rate().bits();
        let mut frame_ticks = FRAME_PERIOD_TICKS;
        let mut smoothed_midi = [None; 4];
        let mut measurements = MeasurementBank::default();
        let mut verification: [pitch_verification::Verification;4] = core::array::from_fn(|_| Default::default());
        let mut verification_frames = 0u8;
        let mut calibration = calibration_live::Live::new();
        let mut capture_trace=capture_trace::Trace::with_calibration(*hardware_calibration,*hardware_calibration_bits);
        #[cfg(tuner_nsdf)]
        let mut nsdf_trace=nsdf_trace::Trace::new();
        let mut run_calibration = false;
        let mut run_verify = false;
        let mut refine=false;let mut accept_refinement=false;let mut discard_refinement=false;
        let mut name_editor=oscillator_calibration::name::Editor::new();
        let mut profile_status="SAVE / LOAD ONLY WITH OUTPUT OFF";
        let mut profile_status_slot=1;
        // Each character bank must receive a changed menu once. Closing the
        // menu hides it; it does not destroy the retained contents of either bank.
        let mut menu_dirty_banks = 0b11u8;
        let mut save_feedback = feedback::Feedback::default();
        let mut backgrounds = ui_scene::Backgrounds::new();
        let mut scene = ui_scene::Scene::Spiral;
        let mut text_scenes = [None; 2];
        // Compact occupancy only: 512 bytes total, not an 8-KiB text shadow.
        let mut text_occupied = [ui_text::Occupied::new(), ui_text::Occupied::new()];
        let mut last_ui_ms=0;
        loop {
            riscv::asm::wfi();
            let now=with_app(|app|app.now_ms);
            if now.wrapping_sub(last_ui_ms)<TIMER0_ISR_PERIOD_MS as u64 {continue;}
            last_ui_ms=now;
            let ui_frame = poll_ui_frame();
            if ui_frame.run_play && ui_frame.controls.mode==runtime::OperatingMode::Play {
                critical_section::with(|cs| {
                    let mut play=PLAYBACK.borrow_ref_mut(cs);
                    if play.active {
                        tuner.cal_command().write(|w|unsafe{w.value().bits(play.stop("STOPPED BY USER"))});
                    } else if calibration.pending_profile.is_some() {
                        play.status="ACCEPT OR DISCARD CAL FIRST";
                    } else if !calibration.active() {
                        if let (Some(profile),Some(route))=(calibration.profile.as_ref(),calibration.profile_route) {
                            let input=with_app(|app|app.ui.opts.play.input.value);
                            if play.arm(profile,input,route.output(),ui_frame.controls.zero_note,
                                counts_per_v as i32,ui_frame.now_ms as u32,tuner.cal_status().read().value().bits()) {
                                play.chromatic=with_app(|app|app.ui.opts.play.quantize.value==options::QuantizeMode::Chromatic);
                                tuner.cv_channel().write(|w|unsafe{w.channel().bits(input)});
                            }
                        } else {play.status="LOAD OR CALIBRATE A PROFILE";}
                    }
                });
            }
            #[cfg(not(tuner_nsdf))]
            capture_trace.tick(&tuner,uart,ui_frame.now_ms,&calibration,measurements.channel(calibration.input));
            #[cfg(tuner_nsdf)]
            nsdf_trace.tick(uart,ui_frame.now_ms);
            run_calibration |= ui_frame.run_calibration;
            if ui_frame.controls.mode==runtime::OperatingMode::Calibrator {
                if ui_frame.discard_scan {calibration.discard_scan();}
                else if ui_frame.accept_scan {calibration.accept_scan(&tuner);}
            }
            run_verify |= ui_frame.run_verify;
            refine|=ui_frame.refine;accept_refinement|=ui_frame.accept_refinement;
            discard_refinement|=ui_frame.discard_refinement;
            if ui_frame.controls.mode==runtime::OperatingMode::Profiles {
                if ui_frame.profile_slot!=profile_status_slot {
                    profile_status_slot=ui_frame.profile_slot;
                    profile_status="SAVE / LOAD ONLY WITH OUTPUT OFF";
                }
                if let Some(character)=name_editor.update(ui_frame.name_position,ui_frame.name_character) {
                    with_app(|app| {app.ui.opts.profiles.character.value=character;app.ui.external_modify();});
                    menu_dirty_banks=0b11;
                }
                if ui_frame.save_profile {
                    profile_status=save_profile(persistence,&mut calibration,ui_frame.profile_slot,
                        ui_frame.controls.zero_note,name_editor.name());
                } else if ui_frame.load_profile {
                    let (status,zero)=load_profile(persistence,&mut calibration,ui_frame.profile_slot,&mut name_editor);
                    profile_status=status;
                    if let Some(zero)=zero {
                        with_app(|app| {
                            app.ui.opts.calibrate.zero_note.value=zero;
                            app.ui.opts.calibrate.input.value=calibration.input;
                            app.ui.opts.calibrate.output.value=calibration.output;
                            app.ui.opts.profiles.position.value=1;
                            app.ui.opts.profiles.character.value=name_editor.character();
                            app.ui.external_modify();
                        });
                        menu_dirty_banks=0b11;
                    }
                }
            }
            if save_feedback.tick(TIMER0_ISR_PERIOD_MS as u16) {
                menu_dirty_banks = 0b11;
            }
            if ui_frame.menu_dirty {
                menu_dirty_banks = 0b11;
            }
            if ui_frame.save && !calibration.active() {
                let result = if let Some(storage) = persistence.as_mut() {
                    let opts = snapshot_options_for_save();
                    if storage.save_options(&opts).is_ok() { "saved" } else { "failed" }
                } else { "no flash" };
                save_feedback.show(result);
                menu_dirty_banks = 0b11;
            }
            if ui_frame.wipe && !calibration.active() {
                save_feedback = feedback::Feedback::default();
                menu_dirty_banks = 0b11;
                if let Some(storage) = persistence.as_mut() {
                    let opts=snapshot_options_for_save();
                    storage.erase_options(&opts).ok();
                }
                reset_options();
                name_editor=oscillator_calibration::name::Editor::new();
            }

            let calibration_view = matches!(ui_frame.controls.mode,
                runtime::OperatingMode::Calibrator | runtime::OperatingMode::Verify | runtime::OperatingMode::Profiles | runtime::OperatingMode::Play);
            let requested_scene = if ui_frame.controls.display_mode == DisplayMode::Linear {
                ui_scene::Scene::Linear
            } else { ui_scene::Scene::Spiral };
            let mut swap_background = false;
            let exchange = tuner_display.frame().read();
            if !exchange.busy().bit() && !calibration_view {
                // Warm the unused view in idle opportunities, never touching
                // the visible background or adding another startup clear.
                let prepare_scene = if requested_scene != scene { requested_scene }
                    else if scene == ui_scene::Scene::Spiral { ui_scene::Scene::Linear }
                    else { ui_scene::Scene::Spiral };
                let bank = exchange.background_back().bit() as usize;
                let mut canvas = BackgroundCanvas::new(
                    PSRAM_FB_BASE + bank * 0x100000, video_size.0, video_size.1,
                    ROUND_DISPLAY);
                match backgrounds.step(bank, prepare_scene,
                    video_size.0 as usize * video_size.1 as usize / 4) {
                    ui_scene::Work::Clear { first, end } => canvas.clear_words(first, end),
                    ui_scene::Work::Draw { scene, first, end } => {
                        canvas.draw_scene_range(scene, first, end);
                    }
                    ui_scene::Work::Flush => {
                        canvas.finish();
                        backgrounds.flushed(bank, prepare_scene,
                            video_size.0 as usize * video_size.1 as usize / 4);
                    }
                    ui_scene::Work::Ready => swap_background = requested_scene != scene,
                }
            }

            frame_ticks = frame_ticks.saturating_add(1);
            if frame_ticks >= FRAME_PERIOD_TICKS || swap_background {
                frame_ticks = 0;
                let controls = ui_frame.controls;
                if discard_refinement {
                    calibration.discard_refinement(&tuner);discard_refinement=false;
                    refine=false;accept_refinement=false;run_verify=false;
                }
                if accept_refinement {
                    if controls.mode==runtime::OperatingMode::Verify {calibration.accept_refinement(&tuner);}
                    accept_refinement=false;
                }
                if refine {
                    capture_trace.cancel(&tuner);
                    calibration.start_refinement(&tuner,controls,ui_frame.now_ms);
                    verification[calibration.input as usize].clear();refine=false;
                }
                if run_verify {
                    capture_trace.cancel(&tuner);
                    run_verify=false;
                    calibration.toggle_verify(&tuner,controls,ui_frame.now_ms);
                    verification[calibration.input as usize].clear();
                }
                if run_calibration {
                    capture_trace.cancel(&tuner);
                    run_calibration = false;
                    if controls.mode == runtime::OperatingMode::Calibrator {
                        calibration.toggle(&tuner, controls, ui_frame.now_ms);
                        verification[calibration.input as usize].clear();
                    }
                }
                // PLAY checks the loaded oscillator, not all four audio lanes.
                // Pin the shared verifier before reading so note changes don't
                // wait for a round trip through unrelated inputs. Raw four-lane
                // pitch acquisition remains continuous.
                let playback_audio=if controls.mode==runtime::OperatingMode::Play {
                    calibration.profile_route.map(|route|route.input())
                } else {None};
                if let Some(input)=playback_audio {
                    tuner.verify_channel().write(|w|unsafe{w.channel().bits(input)});
                    verification_frames=0;
                }
                let previous_capture_mode=tuner.verify_capture().read().mode().bits();
                for input in 0..4u8 {
                    let measurement = read_measurement(&tuner, counts_per_v, input,
                                                       &mut verification[input as usize]);
                    measurements.update(input, measurement);
                }
                if previous_capture_mode!=tuner.verify_capture().read().mode().bits() {
                    verification_frames=0;
                }
                verification_frames = verification_frames.saturating_add(1);
                let dwell=pitch_verification::dwell_frames(tuner.info().read().sample_rate().bits(),
                    tuner.verify_info().read().decimation().bits().max(1) as u32);
                if calibration.active() {
                    tuner.verify_channel().write(|w| unsafe {w.channel().bits(calibration.input)});
                    verification_frames = 0;
                } else if playback_audio.is_none() && verification_frames >= dwell {
                    verification_frames = 0;
                    let next = (tuner.verify_channel().read().channel().bits()+1) & 3;
                    tuner.verify_channel().write(|w| unsafe { w.channel().bits(next) });
                }
                let previous_rejection=calibration.tracking_failure.map(|f|f.rejected.millicents);
                calibration.tick(&tuner, measurements.channel(calibration.input), controls, ui_frame.now_ms);
                if calibration.tracking_failure.is_none() {
                    capture_trace.cancel(&tuner);
                    calibration.rejected_detector=None;
                    calibration.rejected_verifier=None;
                } else if calibration.rejected_detector.is_none()
                    || previous_rejection!=calibration.tracking_failure.map(|f|f.rejected.millicents) {
                    calibration.rejected_detector=Some(verification[calibration.input as usize].reading());
                    calibration.rejected_verifier=Some(verification[calibration.input as usize].diagnostic());
                }
                if calibration.active() && calibration.tracking_failure.is_some() {
                    let v=&verification[calibration.input as usize];
                    let (raw,factor)=v.reading();
                    capture_trace.arm(&tuner,ui_frame.now_ms,raw,factor,v.diagnostic());
                }
                if let Some(note)=calibration.take_suggested_note() {
                    with_app(|app| {
                        app.ui.opts.verify.note.value=note;
                        app.ui.opts.verify.cents.value=0;
                        app.ui.external_modify();
                    });
                    menu_dirty_banks=0b11;
                }
                let reference_hz = controls.reference_hz as f32;
                // Never wait for video in the real-time loop. If scanout is
                // stopped or still owns a pending frame, keep servicing the
                // reference output and UI and try a fresh snapshot next time.
                let frame = tuner_display.frame().read();
                if frame.busy().bit() {
                    continue;
                }
                if swap_background { scene = requested_scene; }
                let text_bank = frame.back_bank().bit() as usize;
                let displayed_scene = if calibration_view {ui_scene::Scene::Calibration} else {scene};
                let changed = text_scenes[text_bank] != Some(displayed_scene);
                let mut text = TextWriter {
                    display: &tuner_display, occupied: &mut text_occupied[text_bank],
                };
                if changed {
                    text.clear(text_scenes[text_bank].is_none());
                    text_scenes[text_bank] = Some(displayed_scene);
                }
                // Static labels are retained independently in both banks.
                // Dynamic fields still replace their full bounded footprint.
                if calibration_view {
                    text.clear(false);
                    if controls.mode == runtime::OperatingMode::Play {
                        publish_playback(&tuner_display,&mut text,&calibration,controls,
                            measurements.channel(calibration.input),ui_frame.menu_active);
                    } else if controls.mode == runtime::OperatingMode::Profiles {
                        publish_profiles(&tuner_display,&mut text,&calibration,&name_editor,
                            ui_frame.profile_slot,ui_frame.name_position,profile_status,ui_frame.menu_active);
                    } else if controls.mode == runtime::OperatingMode::Verify {
                        publish_verification(&tuner_display,&mut text,&calibration,controls,
                            measurements.channel(calibration.input),ui_frame.menu_active);
                    } else {
                    publish_calibration(&tuner_display, &mut text, &calibration, controls,
                        measurements.channel(if calibration.active() {calibration.input} else {controls.calibration_input}),
                        ui_frame.menu_active);
                    }
                } else {
                write_static_text(&mut text, scene, requested_scene != scene, changed);
                publish_tuner(
                    &tuner_display,
                    &mut text,
                    &measurements,
                    reference_hz,
                    controls.tuner_input,
                    if scene == ui_scene::Scene::Linear { DisplayMode::Linear }
                    else if controls.display_mode == DisplayMode::Visualizer {
                        DisplayMode::Visualizer
                    } else { DisplayMode::Arc },
                    &mut smoothed_midi,
                    ui_frame.menu_active,
                );
                }
                let bank_mask = 1 << (frame.back_bank().bit() as u8);
                if ui_frame.menu_active && (menu_dirty_banks & bank_mask != 0) {
                    let menu = snapshot_menu(save_feedback.message());
                    publish_menu(&tuner_display, &menu);
                    menu_dirty_banks &= !bank_mask;
                }
                // Commit LAST: characters, marker geometry/color and menu
                // visibility are immutable until the hardware acknowledges them.
                tuner_display.backdrop().write(|w| w.blank().bit(calibration_view));
                tuner_display.frame().write(|w| {
                    w.swap_background().bit(swap_background);
                    w.commit().set_bit()
                });
            }
        }
    })
}

#[entry]
fn main() -> ! {
    run(&mut startup())
}
