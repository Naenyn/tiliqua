#![no_std]
#![no_main]

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

use options::{DisplayMode, Opts, Page, ReferenceTone};
use opts::persistence::*;
use opts::Options as _;
use pac::constants::*;
use tiliqua_fw::*;
use tiliqua_pac as pac;

const TIMER0_ISR_PERIOD_MS: u32 = 5;
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
}

impl App {
    fn new(opts: Opts) -> Self {
        let peripherals = unsafe { pac::Peripherals::steal() };
        let encoder = Encoder0::new(peripherals.ENCODER0);
        let pca9635 = Pca9635Driver::new(I2c0::new(peripherals.I2C0));
        let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
        Self {
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

fn timer0_handler(app: &Mutex<RefCell<App>>) {
    critical_section::with(|cs| {
        let mut app = app.borrow_ref_mut(cs);
        // Never perform an unbounded motherboard-I2C transaction in this ISR.
        // Encoder/options and PMOD LEDs are all CSR-backed and deterministic.
        app.ui.update_realtime();
        let peripherals = unsafe { pac::Peripherals::steal() };
        peripherals
            .TUNER_PERIPH
            .control()
            .write(|w| unsafe { w.channel().bits(app.ui.opts.tuner.input.value) });
    });
}

#[derive(Clone, Copy, Default)]
struct Measurement {
    frequency_hz: f32,
    vrms: f32,
    vpp: f32,
    valid: bool,
}

fn read_measurement(tuner: &pac::TUNER_PERIPH, counts_per_v: f32) -> Measurement {
    // Sequence reads bracket each multi-register snapshot. If gateware publishes
    // while firmware is reading, retry rather than combine two measurements.
    let mut pitch_snapshot = (0, 0, 0, 0);
    for _ in 0..4 {
        let before = tuner.pitch_sequence().read().sequence().bits();
        let samples = tuner.period_samples().read().samples().bits();
        let cycles = tuner.period_cycles().read().cycles().bits();
        let age = tuner.pitch_age().read().samples().bits();
        let after = tuner.pitch_sequence().read().sequence().bits();
        pitch_snapshot = (after, samples, cycles, age);
        if before == after {
            break;
        }
    }
    let (_pitch_sequence, period_samples, period_cycles, pitch_age) = pitch_snapshot;

    let mut level_snapshot = (0, 0, 0, 0);
    for _ in 0..4 {
        let before = tuner.level_sequence().read().sequence().bits();
        let power = tuner.mean_square().read().value().bits();
        let minimum = tuner.minimum().read().value().bits() as i32;
        let maximum = tuner.maximum().read().value().bits() as i32;
        let after = tuner.level_sequence().read().sequence().bits();
        level_snapshot = (after, power, minimum, maximum);
        if before == after {
            break;
        }
    }
    let (_level_sequence, mean_square, minimum, maximum) = level_snapshot;
    let sample_rate = tuner.info().read().sample_rate().bits();
    let frequency_hz = if period_samples != 0 {
        sample_rate as f32 * period_cycles as f32 / period_samples as f32
    } else {
        0.0
    };
    let vrms = (mean_square as f32).sqrt() / counts_per_v;
    let vpp = (maximum - minimum) as f32 / counts_per_v;
    Measurement {
        frequency_hz,
        vrms,
        vpp,
        valid: period_cycles != 0 && pitch_age < sample_rate / 2 && vrms >= 0.005,
    }
}

fn reference_frequency(
    measurement: Measurement,
    reference_hz: f32,
    mode: ReferenceTone,
) -> Option<f32> {
    match mode {
        ReferenceTone::Off => None,
        ReferenceTone::A4 => Some(reference_hz),
        ReferenceTone::Nearest if measurement.valid => {
            let midi = (69.0 + 12.0 * (measurement.frequency_hz / reference_hz).log2()).round();
            Some(reference_hz * (2.0_f32).powf((midi - 69.0) / 12.0))
        }
        ReferenceTone::Nearest => None,
    }
}

fn configure_reference(tuner: &pac::TUNER_PERIPH, frequency: Option<f32>, sample_rate: u32) {
    let increment = frequency.map_or(0, |hz| {
        (hz * 4_294_967_296.0_f32 / sample_rate as f32).round() as u32
    });
    tuner
        .reference_increment()
        .write(|w| unsafe { w.value().bits(increment) });
    tuner
        .reference_control()
        .write(|w| w.enable().bit(frequency.is_some()));
}

#[derive(Clone, Copy)]
struct Marker {
    x: u16,
    y: u16,
    hue: u8,
    lens_base: u16,
    lens_bank: u8,
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
    x_offset: i32,
    rotate_left: bool,
}

impl BackgroundCanvas {
    fn new(base: usize, width: u16, height: u16, rotate_left: bool) -> Self {
        Self {
            base: base as *mut u8,
            width: width as i32,
            height: height as i32,
            x_offset: if rotate_left { 0 } else { (width as i32 - 720).max(0) / 2 },
            rotate_left,
        }
    }

    fn clear(&mut self) {
        let words = (self.width as usize * self.height as usize + 3) / 4;
        let ptr = self.base.cast::<u32>();
        for offset in 0..words {
            unsafe { ptr.add(offset).write_volatile(0) };
        }
    }

    fn put_panel_pixel(&mut self, x: i32, y: i32, pixel: u8) {
        if !(0..720).contains(&x) || !(0..720).contains(&y) {
            return;
        }
        let (screen_x, screen_y) = if self.rotate_left {
            (719 - y, x)
        } else {
            (x + self.x_offset, y)
        };
        if screen_x < 0 || screen_x >= self.width || screen_y < 0 || screen_y >= self.height {
            return;
        }
        let offset = screen_y as usize * self.width as usize + screen_x as usize;
        unsafe { self.base.add(offset).write_volatile(pixel) };
    }

    fn line(&mut self, mut x0: i32, mut y0: i32, x1: i32, y1: i32, pixel: u8) {
        let dx = (x1 - x0).abs();
        let sx = if x0 < x1 { 1 } else { -1 };
        let dy = -(y1 - y0).abs();
        let sy = if y0 < y1 { 1 } else { -1 };
        let mut error = dx + dy;
        loop {
            self.put_panel_pixel(x0, y0, pixel);
            if x0 == x1 && y0 == y1 { break; }
            let twice = error * 2;
            if twice >= dy { error += dy; x0 += sx; }
            if twice <= dx { error += dx; y0 += sy; }
        }
    }

    fn thick_line(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, pixel: u8) {
        for offset in -1..=1 {
            self.line(x0 + offset, y0, x1 + offset, y1, pixel);
            self.line(x0, y0 + offset, x1, y1 + offset, pixel);
        }
    }

    fn draw_static_tuner(&mut self) {
        const GUIDE: u8 = (5 << 4) | 9;
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

fn glyph_index(byte: u8) -> u8 {
    match byte {
        b' ' => 0,
        b'#' => 1,
        b'+' => 2,
        b'-' => 3,
        b'.' => 4,
        b'/' => 5,
        b':' => 6,
        b'0'..=b'9' => 7 + byte - b'0',
        b'A'..=b'Z' => 17 + byte - b'A',
        b'a'..=b'z' => 17 + byte - b'a',
        b'<' => 43,
        b'^' => 44,
        _ => 0,
    }
}

fn write_text(display: &pac::TUNER_DISPLAY, column: u8, row: u8, text: &str) {
    for (offset, byte) in text.bytes().enumerate() {
        let x = column as usize + offset;
        if x >= 45 || row >= 45 {
            break;
        }
        display.tile_write().write(|w| unsafe {
            w.address().bits(row as u16 * 45 + x as u16);
            w.glyph().bits(glyph_index(byte))
        });
    }
}

fn write_centered<const N: usize>(
    display: &pac::TUNER_DISPLAY,
    row: u8,
    text: &String<N>,
    width: u8,
) {
    // Always erase the complete field before drawing its new value. In
    // particular, note names vary between two and three characters (B1/A#1),
    // and a shorter name must not leave the old final tile behind.
    let field_column = (45 - width) / 2;
    for offset in 0..width {
        display.tile_write().write(|w| unsafe {
            w.address()
                .bits(row as u16 * 45 + field_column as u16 + offset as u16);
            w.glyph().bits(glyph_index(b' '))
        });
    }
    let column = (45usize.saturating_sub(text.len())) / 2;
    write_text(display, column as u8, row, text);
}

fn write_static_text(display: &pac::TUNER_DISPLAY) {
    for (column, row, label) in [
        (22, 5, "C "),
        (31, 7, "C#"),
        (37, 13, "D "),
        (39, 22, "D#"),
        (37, 30, "E "),
        (31, 34, "F "),
        (22, 35, "F#"),
        (14, 34, "G "),
        (7, 30, "G#"),
        (5, 22, "A "),
        (7, 13, "A#"),
        (14, 7, "B "),
    ] {
        write_text(display, column, row, label);
    }
    write_text(display, 20, 1, "TUNER");
    write_text(display, 11, 42, "PRESS ENCODER FOR MENU");
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

fn publish_menu(display: &pac::TUNER_DISPLAY, opts: &Opts) {
    clear_menu_text(display);
    let page = opts.tracker.page.value;
    let page_label = match page {
        Page::Tuner => "TUNER",
        Page::Settings => "SETTINGS",
        Page::Help => "HELP",
    };
    let page_bold = opts.selected().is_none();
    write_menu_right_aligned(
        display,
        MENU_PAGE_COLUMN + MENU_PAGE_WIDTH - 1,
        0,
        page_label,
        page_bold,
    );
    if page_bold && opts.modify() {
        write_menu_char(
            display,
            MENU_PAGE_COLUMN + MENU_PAGE_WIDTH - 1,
            1,
            b'^',
            true,
        );
    }

    let options = opts.view().options();
    for index in 0..3 {
        if let Some(option) = options.get(index) {
            let selected = opts.selected() == Some(index);
            let label = match (page, index) {
                (Page::Tuner, 2) => "ref tone",
                (Page::Settings, 0) => "a4 ref",
                (Page::Settings, 1) => "save",
                (Page::Settings, 2) => "reset",
                _ => option.name(),
            };
            write_menu_text(display, MENU_ITEM_COLUMN, index as u8, label, selected);
            write_menu_right_aligned(
                display,
                MENU_VALUE_RIGHT,
                index as u8,
                &option.value(),
                selected,
            );
            if selected && opts.modify() {
                write_menu_char(display, MENU_EDIT_COLUMN, index as u8, b'<', true);
            }
        }
    }
}

fn publish_tuner(
    display: &pac::TUNER_DISPLAY,
    measurement: Measurement,
    reference_hz: f32,
    input: u8,
    display_mode: DisplayMode,
    reference_mode: ReferenceTone,
    reference_output_hz: Option<f32>,
    smoothed_midi: &mut Option<f32>,
    menu_active: bool,
) {
    let cx = 360;
    let cy = 360;
    let outer_radius = 228;
    let inner_radius = 52;
    let octave_spacing = (outer_radius - inner_radius) as f32 / 8.0;

    let mut note_line: String<32> = String::new();
    let mut cents_line: String<32> = String::new();
    let mut frequency_line: String<48> = String::new();
    let mut voltage_line: String<48> = String::new();
    let mut reference_line: String<48> = String::new();

    let mut marker = None;
    if measurement.valid {
        let midi_float = 69.0 + 12.0 * (measurement.frequency_hz / reference_hz).log2();
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
            format_args!("{:8.2} HZ   IN {}", measurement.frequency_hz, input + 1)
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
        let marker_hue = if cents.abs() <= 5 { 5 } else { 2 };
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
            lens_base: ((marker_angle % 11) * 33 * 33) as u16,
            lens_bank: (marker_angle / 11) as u8,
        });
    } else {
        *smoothed_midi = None;
        write!(note_line, "--").ok();
        write!(cents_line, "{:^20}", "WAITING FOR SIGNAL").ok();
        write!(frequency_line, "{:^24}", format_args!("IN {}", input + 1)).ok();
        write!(
            voltage_line,
            "{:^28}",
            format_args!("{:5.3} VRMS  {:5.3} VPP", measurement.vrms, measurement.vpp)
        )
        .ok();
    }

    match reference_output_hz {
        Some(hz) => {
            let label = if reference_mode == ReferenceTone::A4 {
                "A4"
            } else {
                "NOTE"
            };
            write!(reference_line, "REF1 {:7.2} HZ {}", hz, label).ok();
        }
        None => {
            write!(reference_line, "REF1 OFF").ok();
        }
    };

    // The compact menu overlays only the established right-side panel, so the
    // underlying tuner remains complete and live while it is open.
    write_centered(display, 20, &note_line, 8);
    write_centered(display, 22, &cents_line, 20);
    write_centered(display, 37, &frequency_line, 24);
    write_centered(display, 39, &voltage_line, 28);
    write_centered(display, 41, &reference_line, 24);
    display.marker().write(|w| unsafe {
        if let Some(marker) = marker {
            w.x().bits(marker.x);
            w.y().bits(marker.y);
            w.hue().bits(marker.hue);
            w.valid().bit(true);
            w.visualizer().bit(display_mode == DisplayMode::Visualizer);
            w.menu_active().bit(menu_active)
        } else {
            w.x().bits(0);
            w.y().bits(0);
            w.hue().bits(0);
            w.valid().bit(false);
            w.visualizer().bit(display_mode == DisplayMode::Visualizer);
            w.menu_active().bit(menu_active)
        }
    });
    display.marker_shape().write(|w| unsafe {
        w.base().bits(marker.map_or(0, |value| value.lens_base));
        w.bank().bits(marker.map_or(0, |value| value.lens_bank))
    });
}

#[entry]
fn main() -> ! {
    let peripherals = pac::Peripherals::take().unwrap();
    let sysclk = pac::clock::sysclk();
    let mut timer = Timer0::new(peripherals.TIMER0, sysclk);
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
    // Scanout timing still comes from the standard video peripheral, but the
    // tuner overlay replaces every active pixel. There is no framebuffer draw
    // or initialization phase: the initialized tile RAM is visible immediately.
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
    write_static_text(&tuner_display);

    let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
    let counts_per_v = pmod.counts_per_v() as f32;
    // The PMOD peripheral already powers up with safe default calibration.
    // Do not risk wedging application startup on the current unbounded I2C
    // EEPROM driver. Loading stored calibration will return once that driver
    // supports a finite timeout and recovery.

    let mut opts = Opts::default();
    let mut flash_persist = if let Some(window) = bootinfo.manifest.get_option_storage_window() {
        let mut storage = FlashOptionsPersistence::new(spiflash, window);
        storage.load_options(&mut opts).ok();
        Some(storage)
    } else {
        warn!("No option storage region; settings will not persist");
        None
    };
    let app = Mutex::new(RefCell::new(App::new(opts)));
    critical_section::with(|cs| {
        let mut app = app.borrow_ref_mut(cs);
        app.ui.clear_draw();
        app.ui.set_menu_visible(false);
    });
    handler!(timer0 = || timer0_handler(&app));

    irq::scope(|scope| {
        scope.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(TIMER0_ISR_PERIOD_MS, pac::Interrupt::TIMER0);
        let tuner = peripherals.TUNER_PERIPH;
        let sample_rate = tuner.info().read().sample_rate().bits();
        let mut frame_ticks = FRAME_PERIOD_TICKS;
        let mut smoothed_midi = None;
        let mut menu_was_active = false;
        let mut menu_dirty_pending = false;
        loop {
            riscv::asm::wfi();
            let (opts, save, wipe, menu_active, menu_dirty) = critical_section::with(|cs| {
                let mut app = app.borrow_ref_mut(cs);
                let save = app.ui.opts.settings.save_opts.poll();
                let wipe = app.ui.opts.settings.wipe_opts.poll();
                let menu_active = app.ui.draw();
                app.ui.set_menu_visible(menu_active);
                let menu_dirty = app.ui.take_menu_dirty();
                (app.ui.opts.clone(), save, wipe, menu_active, menu_dirty)
            });
            menu_dirty_pending |= menu_dirty;
            if save {
                if let Some(storage) = flash_persist.as_mut() {
                    storage.save_options(&opts).ok();
                }
            }
            if wipe {
                critical_section::with(|cs| {
                    let mut app = app.borrow_ref_mut(cs);
                    app.ui.opts = Opts::default();
                    app.ui.external_modify();
                });
                if let Some(storage) = flash_persist.as_mut() {
                    storage.erase_all().ok();
                }
            }

            frame_ticks = frame_ticks.saturating_add(1);
            if frame_ticks >= FRAME_PERIOD_TICKS {
                frame_ticks = 0;
                let menu_transition = menu_active != menu_was_active;
                if menu_transition {
                    clear_menu_text(&tuner_display);
                    menu_was_active = menu_active;
                }
                let measurement = read_measurement(&tuner, counts_per_v);
                let reference_hz = opts.settings.reference.value as f32;
                let reference_output_hz =
                    reference_frequency(measurement, reference_hz, opts.tuner.reference_tone.value);
                configure_reference(&tuner, reference_output_hz, sample_rate);
                publish_tuner(
                    &tuner_display,
                    measurement,
                    reference_hz,
                    opts.tuner.input.value,
                    opts.tuner.display.value,
                    opts.tuner.reference_tone.value,
                    reference_output_hz,
                    &mut smoothed_midi,
                    menu_active,
                );
                if menu_active && (menu_dirty_pending || menu_transition) {
                    publish_menu(&tuner_display, &opts);
                }
                menu_dirty_pending = false;
            }
        }
    })
}
