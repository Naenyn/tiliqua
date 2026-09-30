#![no_std]
#![no_main]

mod calibration_live;
mod capture_trace;
#[cfg(tuner_nsdf_wave_diag)]
mod cv_probe;
mod feedback;
mod measurement_snapshot;
mod midi_learn;
mod note_pattern;
mod nsdf_guard;
mod nsdf_select;
mod nsdf_trace;
#[path = "calibration.rs"]
mod oscillator_calibration;
mod ownership;
mod pitch_math;
mod quantizer_setup;
mod scale;
mod serial_report;
mod ui_canvas;
mod ui_markers;
mod ui_scene;
mod ui_text;
use ownership::{Owner, Reservations};
#[path = "calibration/bipolar.rs"]
mod bipolar;
#[path = "calibration/bipolar_sweep.rs"]
mod bipolar_sweep;
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

use options::{CalibrationGraph, DisplayMode, Opts, Page};
use opts::persistence::*;
use opts::{OptionString, Options as _};
use pac::constants::*;
use runtime::{ChannelMeasurement, MeasurementBank, RuntimeControls};
use tiliqua_fw::*;
use tiliqua_pac as pac;

const TIMER0_ISR_PERIOD_MS: u32 = 5;
const PLAYBACK_PERIOD_MS: u32 = 1;
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
    quant_channels: [quantizer_setup::Channel; 4],
    quant_selected: u8,
    tuner_focus: u8,
}

fn quant_settings(
    opts: &options::QuantizerOpts,
    masks: [u16; 2],
    current: quantizer_setup::Channel,
) -> quantizer_setup::Channel {
    quantizer_setup::Channel {
        input: current.input,
        zero: current.zero,
        scale: opts.scale.value as u8,
        root: opts.root.value as u8,
        transpose: opts.transpose.value,
        equal: opts.mapping.value == options::Distribution::Equal,
        masks,
        quantize: current.quantize,
        correction: current.correction,
    }
}
fn show_quant_settings(opts: &mut options::QuantizerOpts, c: quantizer_setup::Channel) {
    use strum::IntoEnumIterator;
    opts.transpose.value = c.transpose;
    opts.scale.value = options::ScalePreset::iter()
        .nth(c.scale as usize)
        .unwrap_or_default();
    opts.root.value = options::ScaleRoot::iter()
        .nth(c.root as usize)
        .unwrap_or_default();
    opts.mapping.value = if c.equal {
        options::Distribution::Equal
    } else {
        options::Distribution::Nearest
    };
}

// The timer interrupt and foreground loop share one long-lived UI object.
// Keeping it static prevents future profile/scale/menu growth from silently
// becoming part of `main()`'s stack frame, which previously corrupted an
// already constrained main RAM after the first interrupt.
static APP: Mutex<RefCell<Option<App>>> = Mutex::new(RefCell::new(None));
static OWNERS: Mutex<RefCell<Reservations>> = Mutex::new(RefCell::new(Reservations::new()));

// Conventional two-octave editor, RAM only; never part of oscillator profiles.
static QUANT_NOTES: Mutex<RefCell<[u16; 2]>> = Mutex::new(RefCell::new([0xfff, 0]));
static NOTE_STATUS: Mutex<RefCell<(u8, &'static str)>> =
    Mutex::new(RefCell::new((1, "DEFAULT NOTES - LOAD OR EDIT")));
static MIDI_LEARN: Mutex<RefCell<bool>> = Mutex::new(RefCell::new(false));
static SETUP_STATUS: Mutex<RefCell<(u8, &'static str)>> =
    Mutex::new(RefCell::new((1, "SAVE OR LOAD A SETUP")));
type QuantEngine = oscillator_calibration::playback::Engine;
struct MultiQuant {
    lanes: [QuantEngine; 4],
    configs: [quantizer_setup::Channel; 4],
    bound: [u8; 4],
    running: bool,
    max_cycles: usize,
    last_cycle: usize,
    max_gap: usize,
    phase: usize,
    samples: [u32; 4],
}
static MULTI_QUANT: Mutex<RefCell<MultiQuant>> = Mutex::new(RefCell::new(MultiQuant {
    lanes: [
        QuantEngine::new(),
        QuantEngine::new(),
        QuantEngine::new(),
        QuantEngine::new(),
    ],
    configs: quantizer_setup::DEFAULT,
    bound: [0; 4],
    running: false,
    max_cycles: 0,
    last_cycle: 0,
    max_gap: 0,
    phase: 0,
    samples: [0; 4],
}));
fn quant_command(t: &pac::TUNER_PERIPH, n: usize, value: u32) {
    match n {
        0 => t
            .quant_command0()
            .write(|w| unsafe { w.value().bits(value) }),
        1 => t
            .quant_command1()
            .write(|w| unsafe { w.value().bits(value) }),
        2 => t
            .quant_command2()
            .write(|w| unsafe { w.value().bits(value) }),
        _ => t
            .quant_command3()
            .write(|w| unsafe { w.value().bits(value) }),
    };
}
fn quant_status(t: &pac::TUNER_PERIPH, n: usize) -> u32 {
    match n {
        0 => t.quant_status0().read().value().bits(),
        1 => t.quant_status1().read().value().bits(),
        2 => t.quant_status2().read().value().bits(),
        _ => t.quant_status3().read().value().bits(),
    }
}
fn quant_cv(t: &pac::TUNER_PERIPH, n: u8) -> u32 {
    match n {
        0 => t.quant_cv0().read().value().bits(),
        1 => t.quant_cv1().read().value().bits(),
        2 => t.quant_cv2().read().value().bits(),
        _ => t.quant_cv3().read().value().bits(),
    }
}
impl MultiQuant {
    fn stop(&mut self, t: &pac::TUNER_PERIPH, reason: &'static str) {
        self.running = false;
        self.phase = 0;
        for (n, lane) in self.lanes.iter_mut().enumerate() {
            quant_command(t, n, lane.stop(reason));
        }
    }
    fn toggle(
        &mut self,
        t: &pac::TUNER_PERIPH,
        n: usize,
        c: quantizer_setup::Channel,
        now: u32,
        counts: i32,
        r: &mut Reservations,
    ) {
        if self.lanes[n].active {
            quant_command(t, n, self.lanes[n].stop("STOPPED BY USER"));
            r.release(Owner::Quant(n as u8));
        } else if !c.quantize && c.correction == 0 {
            self.lanes[n].status = "CHOOSE SCALE OR CORRECTION";
        } else if c.correction != 0 && self.bound[n] != c.correction {
            self.lanes[n].status = "BIND CORRECTION ON ROUTE FIRST";
        } else if !r.claim(Owner::Quant(n as u8), 1 << c.input, 1 << n) {
            self.lanes[n].status = "CHANNEL BUSY - STOP ITS OWNER";
        } else {
            if !self.running {
                self.phase = 0;
                self.last_cycle = 0;
                self.max_cycles = 0;
                self.max_gap = 0;
            }
            self.configs[n] = c;
            let lane = &mut self.lanes[n];
            // Disable has cleared faults, but wait until a later RUN if a prior
            // enabled output has not yet acknowledged shutdown.
            quant_command(t, n, lane.stop("STOPPED"));
            if lane.arm_route(
                c.input,
                n as u8,
                c.zero,
                counts,
                now,
                quant_status(t, n),
                c.correction != 0,
                c.quantize,
            ) {
                lane.scale_id = c.scale;
                lane.root = c.root;
                lane.transpose = c.transpose;
                lane.equal = c.equal;
                if c.quantize && c.scale == 6 {
                    match scale::Pattern::compile(c.masks) {
                        Ok(pattern) => lane.pattern = pattern,
                        Err(_) => {
                            lane.stop("EMPTY PATTERN - ADD NOTES");
                        }
                    }
                }
            }
            if !lane.active {
                r.release(Owner::Quant(n as u8));
            }
        }
        self.running = self.lanes.iter().any(|lane| lane.active);
    }
}

impl App {
    #[inline(never)]
    fn new(opts: Opts) -> Self {
        let quant_selected = opts.quantizer.output.value.min(3);
        let mut quant_channels = quantizer_setup::DEFAULT;
        quant_channels[quant_selected as usize] = quant_settings(
            &opts.quantizer,
            [0xfff, 0],
            quant_channels[quant_selected as usize],
        );
        let peripherals = unsafe { pac::Peripherals::steal() };
        let encoder = Encoder0::new(peripherals.ENCODER0);
        let pca9635 = Pca9635Driver::new(I2c0::new(peripherals.I2C0));
        let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
        Self {
            quant_channels,
            quant_selected,
            tuner_focus: 0,
            now_ms: 0,
            ui: ui::UI::new_with_fade(opts, TIMER0_ISR_PERIOD_MS, 5_000, encoder, pca9635, pmod),
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

fn playback_cycles() -> usize {
    // The CPU does not implement mcycle. Invert the free-running downcounter
    // to retain wrapping cycle arithmetic, including its 32-bit rollover.
    (!unsafe { pac::Peripherals::steal() }
        .PLAYBACK_TIMER
        .counter()
        .read()
        .value()
        .bits()) as usize
}
fn outputs_running() -> bool {
    critical_section::with(|cs| MULTI_QUANT.borrow_ref(cs).running)
}

fn timer0_handler() {
    let now = with_app(|app| {
        // Never perform an unbounded motherboard-I2C transaction in this ISR.
        // Encoder/options and PMOD LEDs are all CSR-backed and deterministic.
        app.now_ms += PLAYBACK_PERIOD_MS as u64;
        if app.now_ms % TIMER0_ISR_PERIOD_MS as u64 == 0 {
            app.ui.update_realtime();
        }
        // Measurement bank selection is owned by the foreground reader, not
        // the encoder ISR. All four acquisition lanes run independently.
        app.now_ms as u32
    });
    // Two outputs per interrupt: every channel runs at 500 Hz without putting
    // four worst-case note transitions in the same 1 ms interrupt budget.
    let output_started = playback_cycles();
    critical_section::with(|cs| {
        let mut quant = MULTI_QUANT.borrow_ref_mut(cs);
        if !quant.running {
            return;
        }
        let tuner = unsafe { pac::Peripherals::steal() }.TUNER_PERIPH;
        // Running routes/settings are immutable. Navigation is not a stop.
        let start = playback_cycles();
        if quant.last_cycle != 0 {
            let gap = start.wrapping_sub(quant.last_cycle);
            quant.max_gap = quant.max_gap.max(gap);
            if gap > pac::clock::sysclk() as usize / 200 {
                quant.stop(&tuner, "STOPPED - SCHEDULING GAP");
                return;
            }
        }
        quant.last_cycle = start;
        // Both batches use the same input snapshot. In particular, outputs
        // sharing one input must not cross its note boundary on different ticks.
        if quant.phase == 0 {
            quant.samples = core::array::from_fn(|n| quant_cv(&tuner, n as u8));
        }
        let samples = quant.samples;
        for n in (quant.phase * 2)..(quant.phase * 2 + 2) {
            let lane = &mut quant.lanes[n];
            if let Some(command) = lane.tick(
                now,
                samples[lane.input as usize],
                quant_status(&tuner, n),
                true,
            ) {
                quant_command(&tuner, n, command);
            }
        }
        let elapsed = playback_cycles().wrapping_sub(start);
        quant.max_cycles = quant.max_cycles.max(elapsed);
        if elapsed > pac::clock::sysclk() as usize / 2000 {
            quant.stop(&tuner, "STOPPED - CPU BUDGET");
        } else {
            if quant.phase == 1 {
                tuner.quant_commit().write(|w| unsafe { w.value().bits(1) });
            }
            quant.phase ^= 1;
            quant.running = quant.lanes.iter().any(|lane| lane.active);
        }
    });
    if playback_cycles().wrapping_sub(output_started) > pac::clock::sysclk() as usize / 2000 {
        critical_section::with(|cs| {
            let tuner = unsafe { pac::Peripherals::steal() }.TUNER_PERIPH;
            MULTI_QUANT
                .borrow_ref_mut(cs)
                .stop(&tuner, "STOPPED - COMBINED CPU BUDGET");
        });
    }
}

#[inline(never)]
fn read_measurement(
    tuner: &pac::TUNER_PERIPH,
    counts_per_v: f32,
    input: u8,
) -> ChannelMeasurement {
    tuner
        .control()
        .write(|w| unsafe { w.channel().bits(input) });
    if tuner.control().read().channel().bits() != input {
        return ChannelMeasurement::default();
    }
    let snapshot = measurement_snapshot::read(|| {
        let before = tuner.level_sequence().read().sequence().bits();
        let power = tuner.mean_square().read().value().bits();
        let minimum = tuner.minimum().read().value().bits() as i32;
        let maximum = tuner.maximum().read().value().bits() as i32;
        let end = tuner.level_end().read().value().bits();
        let after = tuner.level_sequence().read().sequence().bits();
        (before, (power, minimum, maximum, end), after)
    });
    let Some((power, minimum, maximum, end)) = snapshot else {
        return ChannelMeasurement::default();
    };
    let age = tuner.sample_clock().read().value().bits().wrapping_sub(end);
    if tuner.control().read().channel().bits() != input
        || age >= tuner.info().read().sample_rate().bits() / 2
    {
        return ChannelMeasurement::default();
    }
    // NSDF supplies pitch separately. Never request the retired verifier or
    // label its zero-filled compatibility registers as a baseline measurement.
    ChannelMeasurement {
        vrms: (power as f32).sqrt() / counts_per_v,
        vpp: (maximum - minimum) as f32 / counts_per_v,
        ..ChannelMeasurement::default()
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
        let Some(offset) = ui_canvas::physical(
            ui_canvas::Point { x, y },
            self.width as u16,
            self.height as u16,
            self.rotate_left,
        ) else {
            return;
        };
        unsafe { self.base.add(offset).write_volatile(pixel) };
    }

    fn line(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, pixel: u8) {
        ui_canvas::line(
            ui_canvas::Point { x: x0, y: y0 },
            ui_canvas::Point { x: x1, y: y1 },
            pixel,
            |p, c| self.put_panel_pixel(p.x, p.y, c),
        );
    }

    fn thick_line(&mut self, x0: i32, y0: i32, x1: i32, y1: i32, pixel: u8) {
        for offset in -1..=1 {
            self.line(x0 + offset, y0, x1 + offset, y1, pixel);
            self.line(x0, y0 + offset, x1, y1 + offset, pixel);
        }
    }

    fn plot_dot(&mut self, x: i32, y: i32) {
        for dy in -2..=2 {
            for dx in -2..=2 {
                if dx * dx + dy * dy <= 4 {
                    self.put_panel_pixel(x + dx, y + dy, 0xFF);
                }
            }
        }
    }

    fn draw_calibration_tracking_interval(
        &mut self,
        first: oscillator_calibration::Point,
        last: oscillator_calibration::Point,
        range: (i32, i32),
    ) {
        let Some(color) = ui_canvas::calibration_tracking_color(
            first.microvolts, first.millicents,
            last.microvolts, last.millicents,
        ) else { return };
        let plot = ui_canvas::CALIBRATION_PLOT;
        let right = (plot.x + plot.width as i32 - 1) as u16;
        let Some(x0) = ui_canvas::axis(first.microvolts, range.0, range.1,
            plot.x as u16, right) else { return };
        let Some(x1) = ui_canvas::axis(last.microvolts, range.0, range.1,
            plot.x as u16, right) else { return };
        for y in ui_canvas::CAL_TRACKING_Y
            ..ui_canvas::CAL_TRACKING_Y + ui_canvas::CAL_TRACKING_HEIGHT {
            self.line(x0, y, x1, y, color);
        }
    }

    fn draw_live_calibration_segments(
        &mut self,
        points: &[oscillator_calibration::Point],
        next_points: core::ops::Range<usize>,
        graph: CalibrationGraph,
        error_span_mc: i32,
    ) {
        let Some(anchor) = points.first() else { return };
        for index in next_points {
            if index >= points.len() { break; }
            let location = |sample: oscillator_calibration::Point| {
                match graph {
                    CalibrationGraph::Pitch => ui_canvas::calibration_pitch_point(
                        ui_canvas::CALIBRATION_PLOT, sample.microvolts, sample.millicents,
                        anchor.microvolts, anchor.millicents,
                        bipolar::MIN_UV, bipolar::MAX_UV),
                    CalibrationGraph::Error => ui_canvas::calibration_error_only_point(
                        ui_canvas::CALIBRATION_PLOT, sample.microvolts, sample.millicents,
                        anchor.microvolts, anchor.millicents,
                        bipolar::MIN_UV, bipolar::MAX_UV,
                        error_span_mc),
                }
            };
            if index > 0 && points[index].microvolts as i64
                - points[index - 1].microvolts as i64 <= 125_000 {
                if let (Some(a), Some(b)) = (location(points[index - 1]), location(points[index])) {
                    self.line(a.x, a.y, b.x, b.y, 0xDB);
                }
            }
            if graph == CalibrationGraph::Pitch && index > 0 {
                self.draw_calibration_tracking_interval(points[index - 1], points[index],
                    (bipolar::MIN_UV, bipolar::MAX_UV));
            }
            if let Some(p) = location(points[index]) {
                self.plot_dot(p.x, p.y);
            }
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

    fn draw_scene_range(
        &mut self,
        scene: ui_scene::Scene,
        first: usize,
        end: usize,
        profile: Option<&oscillator_calibration::Profile>,
        plot_range: (i32, i32),
        plot_anchor: (i32, i32),
        graph: CalibrationGraph,
        error_span_mc: i32,
    ) {
        for segment in first..end.min(scene.segments()) {
            if segment < 2048 {
                let point = |step: usize| {
                    let angle = step as f32 * core::f32::consts::TAU / 2048.0;
                    (
                        360 + (356.0 * angle.cos()).round() as i32,
                        360 + (356.0 * angle.sin()).round() as i32,
                    )
                };
                let (x0, y0) = point(segment);
                let (x1, y1) = point(segment + 1);
                self.line(x0, y0, x1, y1, 0x29);
            } else if scene == ui_scene::Scene::Linear {
                ui_canvas::four_lane_scale_segment(segment - 2048, |p, c| {
                    self.put_panel_pixel(p.x, p.y, c)
                });
            } else if scene == ui_scene::Scene::Calibration {
                const PLOT: ui_canvas::Rect = ui_canvas::CALIBRATION_PLOT;
                let index = segment - 2048;
                if index < ui_scene::CAL_GRID_SEGMENTS {
                    ui_canvas::grid_segment(PLOT, 7, 7, index, 0x29, |p, c| {
                        self.put_panel_pixel(p.x, p.y, c)
                    });
                    continue;
                }
                if index == ui_scene::CAL_GRID_SEGMENTS {
                    // The pitch view has a literal 1 V/oct diagonal. The error
                    // view's ideal reference is a horizontal zero-cent line.
                    for segment in (0..32).step_by(2) {
                        let x0 = PLOT.x + segment * (PLOT.width as i32 - 1) / 32;
                        let x1 = PLOT.x + (segment + 1) * (PLOT.width as i32 - 1) / 32;
                        let uv0 = plot_range.0 as i64
                            + (plot_range.1 as i64 - plot_range.0 as i64) * segment as i64 / 32;
                        let uv1 = plot_range.0 as i64
                            + (plot_range.1 as i64 - plot_range.0 as i64) * (segment + 1) as i64 / 32;
                        let ideal_y = |uv: i32| match graph {
                            CalibrationGraph::Pitch => ui_canvas::calibration_pitch_y(
                                PLOT, ui_canvas::calibration_ideal_mc(
                                    uv, plot_anchor.0, plot_anchor.1),
                                plot_anchor.0, plot_anchor.1,
                                plot_range.0, plot_range.1),
                            CalibrationGraph::Error => ui_canvas::calibration_error_only_point(
                                PLOT, uv, ui_canvas::calibration_ideal_mc(
                                    uv, plot_anchor.0, plot_anchor.1),
                                plot_anchor.0, plot_anchor.1,
                                plot_range.0, plot_range.1,
                                error_span_mc).map(|point| point.y),
                        };
                        if let (Some(y0), Some(y1)) = (ideal_y(uv0 as i32), ideal_y(uv1 as i32)) {
                            self.line(x0, y0, x1, y1, 0x69);
                        }
                    }
                    for division in 0..=4 {
                        let y = PLOT.y + 8 + division * (PLOT.height as i32 - 17) / 4;
                        self.line(PLOT.x - 6, y, PLOT.x, y, 0x69);
                    }
                    let (low_uv, high_uv) = plot_range;
                    for volt in low_uv.div_euclid(1_000_000)
                        ..=high_uv.div_euclid(1_000_000) {
                        if let Some(x) = ui_canvas::axis(volt * 1_000_000,
                            low_uv, high_uv, PLOT.x as u16,
                            (PLOT.x + PLOT.width as i32 - 1) as u16)
                        {
                            if (low_uv..=high_uv).contains(&(volt * 1_000_000)) {
                                self.line(x, PLOT.y + PLOT.height as i32 - 8,
                                    x, PLOT.y + PLOT.height as i32 - 1, 0x69);
                            }
                        }
                    }
                    if graph == CalibrationGraph::Pitch {
                        self.line(PLOT.x, ui_canvas::CAL_TRACKING_Y + 3,
                            PLOT.x + PLOT.width as i32 - 1,
                            ui_canvas::CAL_TRACKING_Y + 3, 0x29);
                    }
                    continue;
                }
                let Some(profile) = profile else { continue };
                let points = profile.points();
                if points.len() < 2 { continue; }
                let low = points[0];
                let point = |sample: oscillator_calibration::Point| {
                    match graph {
                        CalibrationGraph::Pitch => ui_canvas::calibration_pitch_point(
                            PLOT, sample.microvolts, sample.millicents,
                            low.microvolts, low.millicents,
                            plot_range.0, plot_range.1),
                        CalibrationGraph::Error => ui_canvas::calibration_error_only_point(
                            PLOT, sample.microvolts, sample.millicents,
                            low.microvolts, low.millicents,
                            plot_range.0, plot_range.1,
                            error_span_mc),
                    }
                };
                {
                    let n = index - ui_scene::CAL_GRID_SEGMENTS - 1;
                    if n < points.len() {
                        if n > 0 && points[n].microvolts as i64
                            - points[n - 1].microvolts as i64 <= 125_000 {
                            if let (Some(a), Some(b)) = (point(points[n - 1]), point(points[n])) {
                                self.line(a.x, a.y, b.x, b.y, 0xDB);
                            }
                        }
                        if graph == CalibrationGraph::Pitch && n > 0 {
                            self.draw_calibration_tracking_interval(points[n - 1], points[n],
                                plot_range);
                        }
                        if let Some(p) = point(points[n]) {
                            self.plot_dot(p.x, p.y);
                        }
                    }
                }
            } else if segment < 2060 {
                let angle = -core::f32::consts::FRAC_PI_2
                    + (segment - 2048) as f32 * core::f32::consts::TAU / 12.0;
                self.thick_line(
                    360,
                    360,
                    360 + (242.0 * angle.cos()).round() as i32,
                    360 + (242.0 * angle.sin()).round() as i32,
                    0x29,
                );
            } else {
                let point = |step: usize| {
                    let turns = 1.0 + step as f32 / ui_scene::SPIRAL_STEPS as f32;
                    spiral_point(360, 360, ui_scene::spiral_radius(turns * 12.0), turns)
                };
                let (x0, y0) = point(segment - 2060);
                let (x1, y1) = point(segment - 2060 + 1);
                self.thick_line(x0 as i32, y0 as i32, x1 as i32, y1 as i32, 0x59);
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
            let angle =
                -core::f32::consts::FRAC_PI_2 + pitch_class as f32 * core::f32::consts::TAU / 12.0;
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
        let samples_per_octave = ui_scene::SPIRAL_STEPS;
        let mut previous = None;
        for step in 0..=(ui_scene::SPIRAL_OCTAVES * samples_per_octave) {
            let turns = 1.0 + step as f32 / samples_per_octave as f32;
            let radius = ui_scene::spiral_radius(turns * 12.0);
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
        self.display
            .tile_write()
            .write(|w| unsafe { w.bits(address as u32 | ((cell as u32) << 12)) });
        self.occupied.record(address, cell);
    }

    fn clear(&mut self, initialize: bool) {
        let display = self.display;
        self.occupied.clear(|address, cell| {
            display
                .tile_write()
                .write(|w| unsafe { w.bits(address as u32 | ((cell as u32) << 12)) });
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
    ui_text::text(
        column as usize,
        row as usize,
        text,
        ui_text::DEFAULT,
        |address, cell| {
            display.cell(address, cell);
        },
    );
}

fn write_centered(display: &mut TextWriter<'_>, row: u8, text: &str, width: u8) {
    // An odd field width shares the 45-column canvas's exact center cell.
    let width = ((width as usize) | 1).min(ui_text::COLUMNS);
    ui_text::field(
        (ui_text::COLUMNS - width) / 2,
        row as usize,
        width,
        text,
        ui_text::DEFAULT,
        ui_text::Align::Center,
        |address, cell| {
            display.cell(address, cell);
        },
    );
}

fn write_static_text(
    display: &mut TextWriter<'_>,
    scene: ui_scene::Scene,
    preparing: bool,
    changed: bool,
) {
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
        write_text(display, 20, 1, "INTONO");
    }
    ui_text::field(
        9,
        42,
        27,
        if preparing {
            "PREPARING VIEW"
        } else {
            "ENCODER: MENU"
        },
        ui_text::DEFAULT,
        ui_text::Align::Center,
        |address, cell| {
            display.cell(address, cell);
        },
    );
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

fn write_menu_char(display: &pac::TUNER_DISPLAY, column: u8, row: u8, byte: u8, bold: bool) {
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

fn write_menu_text(display: &pac::TUNER_DISPLAY, column: u8, row: u8, text: &str, bold: bool) {
    for (offset, byte) in text.bytes().enumerate() {
        write_menu_char(
            display,
            column.saturating_add(offset as u8),
            row,
            byte,
            bold,
        );
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
    // Nine 15-pixel glyph rows fit in the expanded panel at 18-pixel pitch.
    // NOTES uses all nine; no option should be hidden below a scroll window.
    entries: [Option<MenuEntrySnapshot>; 9],
}

impl MenuSnapshot {
    fn from_options(opts: &Opts) -> Self {
        let page = opts.tracker.page.value;
        let page_label = match page {
            Page::Tuner => "INTONO",
            Page::Calibrate => "CAL",
            Page::Verify => "CHECK",
            Page::Profiles => "PROFILES",
            Page::Settings => "SETTINGS",
            Page::Help => "HELP",
            Page::Play => "ROUTES",
            Page::Quantizer => "SCALES",
            Page::QuantNotes => "NOTES",
            Page::QuantSetups => "SETUPS",
        };
        let page_bold = opts.selected().is_none();
        let options = opts.view().options();
        let entries = core::array::from_fn(|row| {
            let index = row;
            options.get(index).map(|option| {
                let selected = opts.selected() == Some(index);
                let label = match (page, index) {
                    // Keep the persisted option key unchanged; all inputs are
                    // acquired continuously, this selects only tuner focus.
                    (Page::Tuner, 0) => "focus",
                    (Page::Calibrate, 2) => "0v note",
                    (Page::Play, 2) => "0v note",
                    (Page::Profiles, 1) => "name pos",
                    (Page::Profiles, 2) => "letter",
                    (Page::Settings, 0) => "a4 ref",
                    (Page::Settings, 1) => "save",
                    (Page::Settings, 2) => "reset",
                    _ => option.name(),
                };
                let value = if page == Page::Tuner
                    && index == 0
                    && critical_section::with(|cs| OWNERS.borrow_ref(cs).cv_inputs() == 15)
                {
                    let mut value = OptionString::new();
                    value.push_str("NONE").ok();
                    value
                } else if page == Page::QuantNotes && index == 0 {
                    let mut value = OptionString::new();
                    value
                        .push_str(if opts.quant_notes.octave.value == 0 {
                            "A"
                        } else {
                            "B"
                        })
                        .ok();
                    value
                } else if (page == Page::Calibrate && index == 2)
                    || (page == Page::Play && index == 2)
                {
                    let mut value = OptionString::new();
                    let note = if page == Page::Play {
                        opts.play.zero_note.value
                    } else {
                        opts.calibrate.zero_note.value
                    };
                    pitch_units::write_note(&mut value, note as i32).ok();
                    value
                } else if page == Page::Profiles && index == 2 {
                    let mut value = OptionString::new();
                    let ch = opts.profiles.character.value;
                    if ch == 32 {
                        value.push_str("space").ok();
                    } else {
                        value.push(ch as char).ok();
                    }
                    value
                } else {
                    option.value()
                };
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
    smoothed_channels: &mut [Option<f32>; 4],
    menu_active: bool,
) {
    let reservations = critical_section::with(|cs| *OWNERS.borrow_ref(cs));
    let mut visible = *measurements;
    for n in 0..4 {
        if !reservations.tuner_available(n) {
            let mut value = visible.channel(n);
            value.valid = false;
            value.qualified = false;
            visible.update(n, value);
        }
    }
    let measurements = &visible;
    let measurement = measurements.channel(input);
    let smoothed_midi = &mut smoothed_channels[input as usize];
    let cx = 360;
    let cy = 360;
    let octave_spacing = ui_scene::SPIRAL_SPACING;

    let mut note_line: String<32> = String::new();
    let mut cents_line: String<32> = String::new();
    let mut frequency_line: String<48> = String::new();
    let mut voltage_line: String<48> = String::new();

    let mut marker = None;
    if measurement.valid {
        let midi_float = pitch_math::semitones(measurement.frequency_hz, reference_hz);
        let display_midi = match *smoothed_midi {
            Some(previous) if (midi_float - previous).abs() <= 2.0 => {
                previous + (midi_float - previous) * 0.20
            }
            _ => midi_float,
        };
        *smoothed_midi = Some(display_midi);
        // These are musical semitones, not restricted MIDI message values.
        let midi_note = midi_float.round() as i32;
        let cents = (100.0 * (midi_float - midi_note as f32)).round() as i32;
        let pitch_class = midi_note.rem_euclid(12) as usize;
        let octave = midi_note.div_euclid(12) - 1;
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

        let marker_radius = ui_scene::spiral_radius(display_midi);
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
    if !reservations.tuner_available(input) {
        note_line.clear();
        cents_line.clear();
        frequency_line.clear();
        voltage_line.clear();
    }
    if !linear {
        write_centered(text, 20, &note_line, 8);
        write_centered(text, 22, &cents_line, 20);
        write_centered(text, 37, &frequency_line, 24);
        write_centered(text, 39, &voltage_line, 28);
    }
    let mut markers = [marker, None, None, None];
    let mut slot = 1;
    for channel in 0..4usize {
        if !reservations.tuner_available(channel as u8) {
            if linear {
                for row in [[12, 18, 25, 31][channel], [16, 22, 29, 35][channel]] {
                    ui_text::field(
                        6,
                        row,
                        33,
                        "",
                        ui_text::DEFAULT,
                        ui_text::Align::Center,
                        |address, cell| text.cell(address, cell),
                    );
                }
            } else {
                ui_text::field(
                    15 + channel * 4,
                    3,
                    2,
                    "",
                    ui_text::DEFAULT,
                    ui_text::Align::Left,
                    |address, cell| text.cell(address, cell),
                );
            }
            smoothed_channels[channel] = None;
            continue;
        }
        let value = measurements.channel(channel as u8);
        let style = ui_text::Style {
            color: 0xC0 | CHANNEL_HUES[channel],
            bold: input as usize == channel,
        };
        if linear {
            let row = [12, 18, 25, 31][channel];
            let mut label: String<48> = String::new();
            if value.valid {
                let midi = pitch_math::semitones(value.frequency_hz, reference_hz);
                let note = midi.round() as i32;
                write!(
                    label,
                    "{} {}{} {:+04}c {:8.2}Hz",
                    channel,
                    NOTE_NAMES[note.rem_euclid(12) as usize],
                    note.div_euclid(12) - 1,
                    (100.0 * (midi - note as f32)).round() as i32,
                    value.frequency_hz
                )
                .ok();
            } else {
                write!(
                    label,
                    "{} -- {}",
                    channel,
                    if reservations.tuner_available(channel as u8) {
                        "NO SIGNAL"
                    } else {
                        "RESERVED BY OTHER MODE"
                    }
                )
                .ok();
            }
            ui_text::field(
                6,
                row,
                33,
                &label,
                style,
                ui_text::Align::Center,
                |address, cell| text.cell(address, cell),
            );
            let mut volts: String<48> = String::new();
            write!(volts, "{:5.3} Vrms  {:5.3} Vpp", value.vrms, value.vpp).ok();
            ui_text::field(
                6,
                [16, 22, 29, 35][channel],
                33,
                &volts,
                style,
                ui_text::Align::Center,
                |address, cell| text.cell(address, cell),
            );
        } else {
            let mut label: String<4> = String::new();
            write!(
                label,
                "{}{}",
                if input as usize == channel { ">" } else { " " },
                channel
            )
            .ok();
            ui_text::field(
                15 + channel * 4,
                3,
                2,
                &label,
                style,
                ui_text::Align::Left,
                |address, cell| text.cell(address, cell),
            );
        }
        if channel != input as usize {
            markers[slot] = other_channel_marker(
                value,
                reference_hz,
                channel,
                linear,
                &mut smoothed_channels[channel],
            );
            slot += 1;
        }
    }
    write_centered(
        text,
        42,
        if !reservations.tuner_available(input) {
            "ALL INPUTS ASSIGNED TO CV"
        } else {
            "AUDIO INPUTS ONLY; ENCODER: MENU"
        },
        42,
    );
    publish_markers(
        display,
        Markers(markers),
        false,
        menu_active,
    );
}

const CHANNEL_HUES: [u8; 4] = [1, 5, 9, 13];
mod pitch_units;

fn publish_quantizer(display: &pac::TUNER_DISPLAY, text: &mut TextWriter<'_>, menu: bool) {
    if with_app(|app| app.ui.opts.tracker.page.value == Page::QuantSetups) {
        let (channels, slot) =
            with_app(|app| (app.quant_channels, app.ui.opts.quant_setups.slot.value));
        let mut line = String::<96>::new();
        write_centered(text, 4, "QUANTIZER SETUPS", 38);
        write_centered(text, 7, "FOUR INDEPENDENT CHANNEL SETTINGS", 42);
        for (output, c) in channels.iter().enumerate() {
            write!(
                line,
                "OUT {}: IN {} ROOT {} {:+} {}",
                output,
                c.input,
                NOTE_NAMES[c.root as usize],
                c.transpose,
                if c.equal { "EQUAL" } else { "NEAREST" }
            )
            .ok();
            write_centered(text, 12 + output as u8 * 4, &line, 42);
            line.clear();
        }
        write_centered(text, 29, "SAVE INCLUDES ALL FOUR NOTE PATTERNS", 42);
        write_centered(text, 32, "LOAD DOES NOT START OUTPUT", 38);
        write_centered(text, 35, "RUN OUTPUTS IN ROUTES; HEADER BACK", 42);
        let (status_slot, status) = critical_section::with(|cs| *SETUP_STATUS.borrow_ref(cs));
        write!(
            line,
            "SLOT {}: {}",
            slot,
            if slot == status_slot {
                status
            } else {
                "SAVE OR LOAD A SETUP"
            }
        )
        .ok();
        write_centered(text, 39, &line, 42);
        publish_markers(display, Markers([None; 4]), false, menu);
        return;
    }
    if with_app(|app| app.ui.opts.tracker.page.value == Page::QuantNotes) {
        let masks = critical_section::with(|cs| *QUANT_NOTES.borrow_ref(cs));
        let (octave, note) = with_app(|app| {
            (
                app.ui.opts.quant_notes.octave.value as usize,
                app.ui.opts.quant_notes.note.value as usize,
            )
        });
        let mut line = String::<96>::new();
        let output = with_app(|app| app.quant_selected);
        write!(line, "OUT {} NOTE PATTERN", output).ok();
        write_centered(text, 4, &line, 38);
        line.clear();
        write_centered(text, 7, "RELATIVE TO C; ROOT SHIFTS PATTERN", 40);
        for (index, mask) in masks.iter().enumerate() {
            write!(line, "{}:", if index == 0 { "A" } else { "B" }).ok();
            for n in 0..12 {
                if mask & (1 << n) != 0 {
                    write!(line, " {}", NOTE_NAMES[n]).ok();
                }
            }
            if *mask == 0 {
                line.push_str(" EMPTY").ok();
            }
            write_centered(text, 12 + index as u8 * 4, &line, 42);
            line.clear();
        }
        write!(
            line,
            "EDIT {} {}: {}",
            if octave == 0 { "A" } else { "B" },
            NOTE_NAMES[note],
            if masks[octave] & (1 << note) != 0 {
                "ON"
            } else {
                "OFF"
            }
        )
        .ok();
        write_centered(text, 22, &line, 38);
        write_centered(
            text,
            27,
            if critical_section::with(|cs| *MIDI_LEARN.borrow_ref(cs)) {
                "TRS MIDI ON - TAP KEYS TO TOGGLE"
            } else {
                "TOGGLE/CLEAR/FILL; TRS MIDI TOGGLE"
            },
            40,
        );
        write_centered(text, 31, "CUSTOM 2 IN SCALES; HEADER TO RETURN", 38);
        write_centered(
            text,
            35,
            if masks == [0, 0] {
                "EMPTY PATTERN - CANNOT RUN"
            } else if masks[0] == 0 || masks[1] == 0 {
                "ONE OCTAVE REPEAT"
            } else {
                "TWO OCTAVE REPEAT"
            },
            38,
        );
        let slot = with_app(|app| app.ui.opts.quant_notes.slot.value);
        let (status_slot, status) = critical_section::with(|cs| *NOTE_STATUS.borrow_ref(cs));
        line.clear();
        write!(
            line,
            "SLOT {}: {}",
            slot,
            if slot == status_slot {
                status
            } else {
                "LOAD OR SAVE SELECTED SLOT"
            }
        )
        .ok();
        write_centered(text, 39, &line, 42);
        publish_markers(display, Markers([None; 4]), false, menu);
        return;
    }
    let (input, output, zero) = with_app(|app| {
        let c = app.quant_channels[app.quant_selected as usize];
        (c.input, app.quant_selected, c.zero)
    });
    let (active, status, uv, out, pitch, updates, cycles) = critical_section::with(|cs| {
        let q = MULTI_QUANT.borrow_ref(cs);
        let p = &q.lanes[output as usize];
        (
            p.active,
            p.status,
            p.input_uv,
            p.output_uv,
            p.pitch,
            p.updates,
            q.max_cycles,
        )
    });
    let mut line = String::<96>::new();
    write_centered(text, 4, "OUTPUT ROUTING AND PITCH", 38);
    critical_section::with(|cs| {
        let q = MULTI_QUANT.borrow_ref(cs);
        for n in 0..4 {
            write!(
                line,
                " {}:{}",
                n,
                if q.lanes[n].active { "RUN" } else { "OFF" }
            )
            .ok();
        }
    });
    write_centered(text, 7, &line, 42);
    line.clear();
    write!(line, "PITCH CV IN {} -> V/OCT OUT {}", input, output).ok();
    write_centered(text, 10, &line, 38);
    line.clear();
    let (scale_name, root_name, transpose) = with_app(|app| {
        let name: &'static str = app.ui.opts.quantizer.scale.value.into();
        let root: &'static str = app.ui.opts.quantizer.root.value.into();
        (name, root, app.ui.opts.quantizer.transpose.value)
    });
    let c = with_app(|app| app.quant_channels[output as usize]);
    if c.quantize {
        write!(
            line,
            "{} {}; TRANSPOSE {:+}",
            root_name, scale_name, transpose
        )
        .ok();
    } else {
        write!(line, "CONTINUOUS CV - QUANTIZATION OFF").ok();
    }
    write_centered(text, 14, &line, 38);
    line.clear();
    critical_section::with(|cs| {
        let q = MULTI_QUANT.borrow_ref(cs);
        if c.correction == 0 {
            write!(line, "CORRECTION: NONE (NOMINAL CV)").ok();
        } else if q.bound[output as usize] != c.correction {
            write!(line, "CORRECTION: SELECTED, NEEDS BIND").ok();
        } else {
            write!(
                line,
                "CURVE: {}",
                q.lanes[output as usize].profile_name().unwrap_or("MISSING")
            )
            .ok();
        }
    });
    write_centered(text, 17, &line, 42);
    line.clear();
    write!(line, "0 V = ").ok();
    pitch_units::write_note(&mut line, zero as i32).ok();
    write_centered(text, 21, &line, 32);
    line.clear();
    let equal = with_app(|app| app.ui.opts.quantizer.mapping.value == options::Distribution::Equal);
    write_centered(
        text,
        24,
        if equal {
            "EQUAL BINS; OUT -5 TO +5 V"
        } else {
            "NEAREST; OUT -5 TO +5 V"
        },
        38,
    );
    write_centered(text, 27, "RUN / STOP SELECTED; SETTINGS LOCKED", 42);
    write_centered(text, 30, status, 42);
    write!(
        line,
        "IN {:+.4} V -> OUT {:+.4} V",
        uv as f32 / 1e6,
        out as f32 / 1e6
    )
    .ok();
    write_centered(text, 34, &line, 42);
    line.clear();
    if active && updates > 0 {
        pitch_units::write_pitch(&mut line, pitch).ok();
    } else {
        write!(line, "ROUTE: CONFIGURE / BIND / RUN").ok();
    }
    write_centered(text, 37, &line, 32);
    line.clear();
    write!(line, "UPDATES {} MAX {} CPU CYCLES", updates, cycles).ok();
    write_centered(text, 40, &line, 42);
    publish_markers(display, Markers([None; 4]), false, menu);
}

pub fn playback_visible() -> bool {
    outputs_running()
        || with_app(|app| matches!(app.ui.opts.tracker.page.value, Page::Play | Page::Quantizer))
}
pub fn write_playback_status(
    out: &mut impl core::fmt::Write,
    _value: ChannelMeasurement,
) -> core::fmt::Result {
    if critical_section::with(|cs| MULTI_QUANT.borrow_ref(cs).running)
        || with_app(|app| matches!(app.ui.opts.tracker.page.value, Page::Quantizer | Page::Play))
    {
        let (running, cycles, gap, lanes) = critical_section::with(|cs| {
            let q = MULTI_QUANT.borrow_ref(cs);
            let lanes: [_; 4] = core::array::from_fn(|n| {
                let p = &q.lanes[n];
                (
                    p.active,
                    p.input,
                    p.input_uv,
                    p.output_uv,
                    p.pitch,
                    p.zero_note,
                    p.updates,
                    p.status,
                    q.configs[n],
                    p.profile_zero_pitch(),
                )
            });
            (q.running, q.max_cycles, q.max_gap, lanes)
        });
        writeln!(
            out,
            "QUANT4 ACTIVE={} RATE_HZ=500 MAX_BATCH_CYCLES={} MAX_GAP_CYCLES={}",
            running, cycles, gap
        )?;
        for (n, (active, input, uv, voltage, pitch, engine_zero, updates, status, c, physical_zero)) in lanes.iter().enumerate() {
            if let Some(reference) = physical_zero {
                writeln!(out, "Q{} PHYSICAL_ZERO_MC={}", n, reference)?;
            }
            writeln!(
                out,
                "Q{} ACTIVE={} IN={} UV={} OUT_UV={} TARGET_MC={} ENGINE_ZERO={} UPDATES={} STATUS={}",
                n, active, input, uv, voltage, pitch, engine_zero, updates, status
            )?;
            writeln!(
                out,
                "Q{} ZERO_NOTE={} SCALE={} ROOT={} TRANSPOSE={} EQUAL={} A={:03X} B={:03X} QUANT={} CORR={}",
                n,
                c.zero,
                c.scale,
                c.root,
                c.transpose,
                c.equal as u8,
                c.masks[0],
                c.masks[1],
                c.quantize,
                c.correction
            )?;
        }
    }
    Ok(())
}

fn publish_calibration(
    display: &pac::TUNER_DISPLAY,
    text: &mut TextWriter<'_>,
    cal: &calibration_live::Live,
    controls: RuntimeControls,
    value: ChannelMeasurement,
    menu_active: bool,
    plot_ready: bool,
    profile_slot: u8,
    profile_name: &str,
    profile_status: &str,
) {
    let input = if cal.active() { cal.input } else { controls.calibration_input };
    let output = if cal.active() { cal.output } else { controls.calibration_output };
    let profile = calibration_plot_profile(cal);
    let mut line: String<48> = String::new();
    write_centered(text, 3, "INTONO", 20);
    write_centered(text, 5, "TUNER [CAL] QUANT ROUTES", 27);
    write_centered(text, 7, match controls.mode {
        runtime::OperatingMode::Profiles => "OSCILLATOR PROFILES",
        runtime::OperatingMode::Verify => "CALIBRATION CHECK",
        _ => "OSCILLATOR CALIBRATION",
    }, 32);
    write!(line, "OUT {} -> V/OCT    AUDIO -> IN {}", output, input).ok();
    write_centered(text, 9, &line, 40);
    let (plot_low, plot_high) = calibration_plot_range(cal, profile);
    let plot_anchor = calibration_plot_anchor(cal, profile);
    let error_span_mc = calibration_plot_error_span(cal, profile);
    let voltage_step = if plot_high - plot_low > 8_000_000 { 2 } else { 1 };
    for volt in plot_low.div_euclid(1_000_000)
        ..=plot_high.div_euclid(1_000_000) {
        if volt % voltage_step != 0 { continue }
        let uv = volt * 1_000_000;
        if uv < plot_low || uv > plot_high { continue }
        if let Some(x) = ui_canvas::axis(uv, plot_low, plot_high,
            ui_canvas::CALIBRATION_PLOT.x as u16, 429) {
            line.clear();
            write!(line, "{}", volt).ok();
            let column = ((x - 90) / 12).clamp(0, 40) as u8;
            write_text(text, column, 27, &line);
        }
    }
    match controls.calibration_graph {
        CalibrationGraph::Pitch => {
            write_text(text, 0, 11, "PITCH (c)");
            if let Some((low_mc, high_mc)) = ui_canvas::calibration_pitch_bounds(
                plot_anchor.0, plot_anchor.1, plot_low, plot_high,
            ) {
                for division in 0..=4 {
                    let pitch_mc = low_mc as i64
                        + (high_mc as i64 - low_mc as i64) * division / 4;
                    if let Some(y) = ui_canvas::calibration_pitch_y(
                        ui_canvas::CALIBRATION_PLOT, pitch_mc as i32,
                        plot_anchor.0, plot_anchor.1, plot_low, plot_high,
                    ) {
                        line.clear();
                        write!(line, "{}", pitch_mc / 1000).ok();
                        write_text(text, 0, (y / 16).clamp(0, 44) as u8, &line);
                    }
                }
            }
            write_text(text, 31, 11, "PITCH GRAPH");
            write_text(text, 31, 12, "DASH = 1V/OCT");
            write_text(text, 31, 13, "TRACK c/VOLT");
            write_text(text, 31, 14, "C<50 Y<200 R+");
        }
        CalibrationGraph::Error => {
            write_text(text, 0, 11, "ERROR (c)");
            for division in -2..=2 {
                let error_mc = division * error_span_mc / 2;
                if let Some(y) = ui_canvas::axis(error_mc,
                    -error_span_mc, error_span_mc,
                    (ui_canvas::CALIBRATION_PLOT.y
                        + ui_canvas::CALIBRATION_PLOT.height as i32 - 9) as u16,
                    (ui_canvas::CALIBRATION_PLOT.y + 8) as u16,
                ) {
                    line.clear();
                    if error_mc.abs() >= 1_000_000 {
                        write!(line, "{:+.1}k", error_mc as f32 / 1_000_000.0).ok();
                    } else {
                        write!(line, "{:+}", error_mc / 1000).ok();
                    }
                    write_text(text, 0, (y / 16).clamp(0, 44) as u8, &line);
                }
            }
            write_text(text, 31, 11, "ERROR GRAPH");
            write_text(text, 31, 12, "DASH = 0c");
            line.clear();
            if error_span_mc >= 1_000_000 {
                write!(line, "SCALE +/- {}kc", error_span_mc / 1_000_000).ok();
            } else {
                write!(line, "SCALE +/- {}c", error_span_mc / 1000).ok();
            }
            write_text(text, 31, 13, &line);
        }
    }
    write_text(text, 10, 28, "OUTPUT V/OCT (V)");
    write_text(text, 31, 15, "PROFILE");
    write_text(text, 31, 19, "RANGE");
    write_text(text, 31, 23, "QUALITY");
    if let Some(profile) = profile {
        let points = profile.points();
        write_text(text, 31, 16, &profile.name()[..profile.name().len().min(12)]);
        if let (Some(low), Some(high)) = (points.first(), points.last()) {
            line.clear();
            write!(line, "{:+.1}..{:+.1} V", low.microvolts as f32 / 1e6,
                high.microvolts as f32 / 1e6).ok();
            write_text(text, 31, 20, &line);
        }
        line.clear();
        write!(line, "{} PTS", points.len()).ok();
        write_text(text, 31, 21, &line);
        write_text(text, 31, 24, if cal.pending_profile.is_some() {
            cal.pending_quality.grade.label()
        } else {
            cal.profile_quality.grade.label()
        });
        let quality = if cal.pending_profile.is_some() {
            cal.pending_quality
        } else {
            cal.profile_quality
        };
        if let Some(score) = quality.score_percent() {
            line.clear();
            write!(line, "SCORE {}%", score).ok();
            write_text(text, 31, 25, &line);
            line.clear();
            write!(line, "W{:.0}c S{:.0}c", quality.worst_cents(), quality.stability_cents()).ok();
            write_text(text, 31, 26, &line);
        } else if let Some(scan) = cal.scan.as_ref().filter(|s| s.missing != 0) {
            line.clear();
            write!(line, "{} CHECKS MISSING", scan.missing).ok();
            write_text(text, 31, 25, &line);
        }
    } else {
        write_text(text, 31, 16, if cal.acquiring_points().is_some() {
            "SCANNING"
        } else {
            "NO PROFILE"
        });
        write_text(text, 31, 24, if cal.acquiring_points().is_some() {
            "PROVISIONAL"
        } else {
            "UNMEASURED"
        });
    }
    if !plot_ready {
        write_centered(text, 29, "DRAWING RESPONSE PLOT", 34);
    }
    if cal.can_accept_imperfect() {
        write_centered(text, 18, "OFF TARGET - ACCEPT OR IMPROVE", 39);
    } else if cal.pending_profile.is_some() && !cal.pending_quality.acceptable() && !cal.active() {
        write_centered(text, 18, "INCOMPLETE - DIAGNOSTIC CURVE", 39);
    } else if cal.pending_profile.as_ref().is_some_and(|p| p.limited_low || p.limited_high)
        && !cal.active()
    {
        write_centered(text, 18, "LIMITED RANGE - REVIEW BEFORE ACCEPT", 39);
    }
    if controls.mode == runtime::OperatingMode::Profiles {
        line.clear();
        write!(line, "PROFILE SLOT {} OF 4", profile_slot).ok();
        write_centered(text, 30, &line, 34);
        write_centered(text, 32, profile_name, 30);
        write_centered(text, 35, profile_status, 40);
        write_centered(text, 37, "SAVE / LOAD / RENAME IN MENU", 38);
        write_centered(text, 39, "BACK TO CAL TO MEASURE", 32);
    } else if controls.mode == runtime::OperatingMode::Verify {
        write_centered(text, 30, cal.status, 40);
        line.clear();
        if let Some(scan) = cal.scan.as_ref() {
            if let Some(local) = scan.local.as_ref() {
                write!(line, "GRID {}/{}  LOCAL {}/9", scan.tested, scan.total, local.tested).ok();
            } else {
                write!(line, "CHECK {} / {} TARGETS", scan.tested, scan.total).ok();
            }
        } else {
            write!(line, "TARGET ").ok();
            pitch_units::write_pitch(&mut line, if cal.verifying {
                cal.target_millicents
            } else {
                controls.target_millicents
            }).ok();
        }
        write_centered(text, 32, &line, 38);
        line.clear();
        if let Some(scan) = cal.scan.as_ref().filter(|scan| scan.missing > 0) {
            write!(line, "{} TARGETS UNRESOLVED", scan.missing).ok();
        } else if let Some(scan) = cal.scan.as_ref().filter(|scan| scan.complete) {
            write!(line, "WORST {:+.2}c", scan.worst_error).ok();
        } else if let Some(error) = cal.error_cents {
            write!(line, "ERROR {:+.2}c", error).ok();
        } else if value.valid {
            write!(line, "INPUT {:.2} HZ", value.frequency_hz).ok();
        } else {
            line.push_str("WAITING FOR QUALIFIED PITCH").ok();
        }
        write_centered(text, 35, &line, 36);
        write_centered(text, 37, "ADVANCED CHECK / IMPROVE IN MENU", 40);
        write_centered(text, 39, "KEEP OSCILLATOR TUNING FIXED", 36);
    } else if cal.active() {
        let (phase, completed, total) = if cal.verifying {
            if let Some(scan) = cal.scan.as_ref() {
                ("CHECK", scan.tested as usize, scan.total as usize)
            } else if let Some(refinement) = cal.refinement.as_ref() {
                ("IMPROVE", refinement.tested, refinement.total())
            } else {
                ("CHECK", 0, 0)
            }
        } else {
            ("SCAN", cal.point as usize, cal.point_count as usize)
        };
        line.clear();
        write!(line, "{} {}/{}  {:+.3} V", phase, completed,
            total, cal.millivolts as f32 / 1000.0).ok();
        write_centered(text, 30, &line, 43);
        line.clear();
        if value.valid {
            write!(line, "{:.2} HZ    {:.3} VPP", value.frequency_hz, value.vpp).ok();
        } else {
            write!(line, "WAITING FOR QUALIFIED PITCH").ok();
        }
        write_centered(text, 32, &line, 36);
        let filled = if total == 0 { 0 } else {
            (completed * 20 / total).min(20)
        };
        line.clear();
        line.push('[').ok();
        for index in 0..20 {
            line.push(if index < filled { '=' } else { '.' }).ok();
        }
        line.push(']').ok();
        write_centered(text, 35, &line, 26);
        write_centered(text, 37, if cal.automatic.as_ref().is_some_and(|a| a.best.is_some()) {
            "RUN AGAIN: REVIEW VERIFIED CURVE"
        } else {
            "RUN AGAIN: CANCEL BEFORE FIRST CHECK"
        }, 40);
    } else if cal.pending_profile.is_some() {
        write_centered(text, 30, cal.status, 39);
        write_centered(text, 32, if cal.can_continue_automatic() {
            if cal.pending_quality.acceptable() {
                "RECOMMEND IMPROVE: RUN TO CONTINUE"
            } else {
                "OFF TARGET: RUN TO SEARCH RANGE"
            }
        } else if cal.pending_quality.acceptable() {
            "RECOMMEND ACCEPT: USE RESULT IN RAM"
        } else {
            if cal.can_accept_imperfect() {
                "LOW SCORE: ACCEPT OR RESCAN"
            } else {
                "INCOMPLETE: RESCAN OR DISCARD"
            }
        }, 36);
        write_centered(text, 35, if cal.can_continue_automatic() && cal.pending_quality.acceptable() {
            "ACCEPT CURRENT OR RUN TO IMPROVE"
        } else if cal.can_continue_automatic() {
            if cal.can_accept_imperfect() {
                "ACCEPT AS-IS OR RUN TO IMPROVE"
            } else {
                "RUN TO RECHECK OR DISCARD"
            }
        } else {
            "RUN: ADJUST AND RESCAN"
        }, 36);
        write_centered(text, 37, "DISCARD: KEEP PRIOR PROFILE", 38);
    } else {
        write_centered(text, 30, cal.status, 40);
        write_centered(text, 32, "MEASURE: SCAN / CHECK / IMPROVE", 40);
        if let Some(failure) = cal.tracking_failure {
            line.clear();
            write!(line, "FAILED AT {:+.3} V", failure.rejected.microvolts as f32 / 1e6).ok();
            write_centered(text, 35, &line, 34);
            line.clear();
            if let Some(previous) = failure.neighbour {
                write!(line, "PITCH STEP {:+.1} CENTS",
                    (failure.rejected.millicents as i64 - previous.millicents as i64) as f32 / 1000.0).ok();
            } else {
                line.push_str("CHECK SIGNAL AND PATCH").ok();
            }
            write_centered(text, 37, &line, 36);
        } else {
            write_centered(text, 35, "CV OUT -> OSC -> AUDIO IN", 34);
            write_centered(text, 37, "USE A STABLE WAVEFORM", 34);
        }
    }
    if controls.mode == runtime::OperatingMode::Calibrator {
        write_centered(text, 39, if cal.active() {
            "RUN AGAIN TO CANCEL"
        } else {
            "SAVE / LOAD IN PROFILES"
        }, 30);
    }
    write_centered(text, 41, "ENCODER: MENU", 21);
    publish_markers(display, Markers([None; 4]), false, menu_active);
}

fn calibration_plot_profile(cal: &calibration_live::Live) -> Option<&oscillator_calibration::Profile> {
    if cal.acquiring_points().is_some() {
        None
    } else {
        cal.pending_profile.as_ref().or(cal.profile.as_ref())
    }
}

fn calibration_plot_anchor(
    cal: &calibration_live::Live,
    profile: Option<&oscillator_calibration::Profile>,
) -> (i32, i32) {
    profile.and_then(|profile| profile.points().first())
        .or_else(|| cal.acquiring_points().and_then(|points| points.first()))
        .map(|point| (point.microvolts, point.millicents))
        .unwrap_or((0, 6_000_000)) // C4 reference before any pitch is measured
}

fn calibration_plot_error_span(
    cal: &calibration_live::Live,
    profile: Option<&oscillator_calibration::Profile>,
) -> i32 {
    let points = profile.map(|profile| profile.points())
        .or_else(|| cal.acquiring_points());
    let Some(points) = points else { return ui_canvas::CAL_ERROR_SPAN_MC };
    let Some(anchor) = points.first() else { return ui_canvas::CAL_ERROR_SPAN_MC };
    let worst = points.iter().map(|point| ui_canvas::calibration_error_mc(
        point.microvolts, point.millicents,
        anchor.microvolts, anchor.millicents,
    ).abs()).max().unwrap_or(0);
    ui_canvas::calibration_error_span_mc(worst)
}

fn calibration_plot_range(
    cal: &calibration_live::Live,
    profile: Option<&oscillator_calibration::Profile>,
) -> (i32, i32) {
    const FULL: (i32, i32) = (bipolar::MIN_UV, bipolar::MAX_UV);
    if cal.acquiring_points().is_some()
        || (cal.pending_profile.is_some() && !cal.pending_quality.acceptable()) {
        return FULL;
    }
    let Some(points) = profile.map(|profile| profile.points()) else { return FULL };
    let (Some(first), Some(last)) = (points.first(), points.last()) else { return FULL };
    if first.microvolts >= last.microvolts { return FULL }
    let pad = ((last.microvolts - first.microvolts) / 20).max(100_000);
    ((first.microvolts - pad).max(FULL.0),
        (last.microvolts + pad).min(FULL.1))
}

fn calibration_plot_revision(profile: Option<&oscillator_calibration::Profile>,
    plot_range: (i32, i32), plot_anchor: (i32, i32), graph: CalibrationGraph,
    error_span_mc: i32) -> u64 {
    if profile.is_none() && plot_anchor == (0, 6_000_000)
        && plot_range == (bipolar::MIN_UV, bipolar::MAX_UV)
        && graph == CalibrationGraph::Pitch { return 0; }
    let seed = ((plot_range.0 as u32 as u64) << 32)
        | plot_range.1 as u32 as u64;
    let seed = seed ^ ((plot_anchor.0 as u32 as u64) << 32)
        ^ plot_anchor.1 as u32 as u64
        ^ if graph == CalibrationGraph::Error {
            0x99aabbccdd ^ error_span_mc as u64
        } else { 0 };
    let Some(profile) = profile else { return seed };
    profile.points().iter().fold(seed ^ profile.points().len() as u64, |hash, point| {
        hash.wrapping_mul(0x100000001b3)
            ^ ((point.microvolts as u32 as u64) << 32 | point.millicents as u32 as u64)
    })
}

fn other_channel_marker(
    value: ChannelMeasurement,
    reference: f32,
    channel: usize,
    linear: bool,
    smooth: &mut Option<f32>,
) -> Option<Marker> {
    if !value.valid {
        *smooth = None;
        return None;
    }
    let midi = pitch_math::semitones(value.frequency_hz, reference);
    let drawn = match *smooth {
        Some(previous) if (midi - previous).abs() <= 2.0 => previous + (midi - previous) * 0.20,
        _ => midi,
    };
    *smooth = Some(drawn);
    let hue = CHANNEL_HUES[channel];
    if linear {
        return Some(Marker {
            x: ui_canvas::cents_position(100.0 * (midi - midi.round()))?,
            y: ui_canvas::LINEAR_LANES[channel] as u16,
            hue,
            orientation: 16,
        });
    }
    let radius = ui_scene::spiral_radius(drawn);
    let (x, y) = spiral_point(360, 360, radius, drawn / 12.0);
    let tangent = drawn / 12.0 * 64.0
        + 64.0 * ui_scene::SPIRAL_SPACING
            / (core::f32::consts::TAU * core::f32::consts::TAU * radius);
    Some(Marker {
        x,
        y,
        hue,
        orientation: (tangent.round() as i32).rem_euclid(32) as u8,
    })
}

fn publish_markers(
    display: &pac::TUNER_DISPLAY,
    markers: Markers,
    visualizer: bool,
    menu_active: bool,
) {
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
    display
        .marker1()
        .write(|w| unsafe { w.bits(markers.packed(1)) });
    display
        .marker2()
        .write(|w| unsafe { w.bits(markers.packed(2)) });
    display
        .marker3()
        .write(|w| unsafe { w.bits(markers.packed(3)) });
}

#[derive(Clone, Copy)]
struct UiFrame {
    bind_route: bool,
    save_setup: bool,
    load_setup: bool,
    save_notes: bool,
    load_notes: bool,
    run_play: bool,
    controls: RuntimeControls,
    save: bool,
    wipe: bool,
    menu_active: bool,
    menu_dirty: bool,
    run_calibration: bool,
    accept_scan: bool,
    discard_scan: bool,
    run_verify: bool,
    refine: bool,
    accept_refinement: bool,
    discard_refinement: bool,
    profile_slot: u8,
    name_position: u8,
    name_character: u8,
    save_profile: bool,
    load_profile: bool,
    now_ms: u64,
}

fn poll_ui_frame() -> UiFrame {
    // The output selector also selects its independent configuration. Capture
    // the old editor before loading the new channel. Never automatically arm.
    with_app(|app| {
        critical_section::with(|cs| {
            use strum::IntoEnumIterator;
            let r = OWNERS.borrow_ref(cs);
            if let Some(focus) = r.focus(app.ui.opts.tuner.input.value, app.tuner_focus) {
                app.ui.opts.tuner.input.value = focus;
                app.tuner_focus = focus;
            }
            let old = app.quant_selected as usize;
            let route_page = app.ui.opts.tracker.page.value == Page::Play;
            let selected = if route_page {
                app.ui.opts.play.output.value
            } else {
                app.ui.opts.quantizer.output.value
            }
            .min(3);
            let q = MULTI_QUANT.borrow_ref(cs);
            let mut edited = app.quant_channels[old];
            if q.lanes[old].active {
                edited = q.configs[old];
            } else if route_page {
                edited.input = app.ui.opts.play.input.value;
                edited.zero = app.ui.opts.play.zero_note.value;
                edited.quantize = app.ui.opts.play.quantize.value == options::RouteQuantize::Scale;
                edited.correction = app.ui.opts.play.correction.value as u8;
            } else {
                edited =
                    quant_settings(&app.ui.opts.quantizer, *QUANT_NOTES.borrow_ref(cs), edited);
            }
            if app.quant_channels[old] != edited {
                *SETUP_STATUS.borrow_ref_mut(cs) =
                    (app.ui.opts.quant_setups.slot.value, "EDITED - SAVE SETUP");
            }
            quantizer_setup::select(
                &mut app.quant_channels,
                &mut app.quant_selected,
                edited,
                selected,
            );
            let c = app.quant_channels[selected as usize];
            show_quant_settings(&mut app.ui.opts.quantizer, c);
            app.ui.opts.quantizer.output.value = selected;
            app.ui.opts.play.output.value = selected;
            app.ui.opts.play.input.value = c.input;
            app.ui.opts.play.zero_note.value = c.zero;
            app.ui.opts.play.quantize.value = if c.quantize {
                options::RouteQuantize::Scale
            } else {
                options::RouteQuantize::Off
            };
            app.ui.opts.play.correction.value = options::Correction::iter()
                .nth(c.correction as usize)
                .unwrap_or_default();
            *QUANT_NOTES.borrow_ref_mut(cs) = c.masks;
        })
    });
    with_app(|app| {
        let toggle = app.ui.opts.quant_notes.toggle.poll();
        let clear = app.ui.opts.quant_notes.clear.poll();
        let fill = app.ui.opts.quant_notes.fill.poll();
        let learn = app.ui.opts.quant_notes.learn.poll();
        let on_notes = app.ui.opts.tracker.page.value == Page::QuantNotes;
        critical_section::with(|cs| {
            let mut armed = MIDI_LEARN.borrow_ref_mut(cs);
            if !on_notes {
                *armed = false;
            } else if learn {
                if MULTI_QUANT.borrow_ref(cs).lanes[app.quant_selected as usize].active {
                    *NOTE_STATUS.borrow_ref_mut(cs) = (
                        app.ui.opts.quant_notes.slot.value,
                        "STOP CHANNEL BEFORE MIDI LEARN",
                    );
                    *armed = false;
                } else {
                    *armed = !*armed;
                    *NOTE_STATUS.borrow_ref_mut(cs) = (
                        app.ui.opts.quant_notes.slot.value,
                        if *armed { "MIDI LEARN ON" } else { "MIDI LEARN OFF" },
                    );
                }
            }
        });
        if on_notes && (toggle || clear || fill) {
            let octave = app.ui.opts.quant_notes.octave.value as usize;
            let note = app.ui.opts.quant_notes.note.value as u8;
            critical_section::with(|cs| {
                if MULTI_QUANT.borrow_ref(cs).lanes[app.quant_selected as usize].active {
                    *NOTE_STATUS.borrow_ref_mut(cs) = (
                        app.ui.opts.quant_notes.slot.value,
                        "STOP CHANNEL BEFORE EDITING",
                    );
                    return;
                }
                let mut masks = QUANT_NOTES.borrow_ref_mut(cs);
                if clear {
                    masks[octave] = 0;
                } else if fill {
                    masks[octave] = 0xfff;
                } else if toggle {
                    masks[octave] ^= 1 << note;
                }
                *NOTE_STATUS.borrow_ref_mut(cs) =
                    (app.ui.opts.quant_notes.slot.value, "EDITED - SAVE TO KEEP");
            });
        }
        let save = app.ui.opts.settings.save_opts.poll();
        let wipe = app.ui.opts.settings.wipe_opts.poll();
        // Supporting screens are entered through their parent, not mixed into
        // the top-level page selector. Clicking a child header returns home.
        let page = app.ui.opts.tracker.page.value;
        let parent = match page {
            Page::Verify => Some(Page::Profiles),
            Page::Profiles => Some(Page::Calibrate),
            Page::QuantNotes | Page::QuantSetups => Some(Page::Quantizer),
            _ => None,
        };
        let header_back = app.ui.opts.tracker.selected.is_none() && app.ui.opts.tracker.modify;
        let destination = if app.ui.opts.calibrate.profiles.poll() {
            Some(Page::Profiles)
        } else if app.ui.opts.profiles.check.poll() {
            Some(Page::Verify)
        } else if app.ui.opts.profiles.back.poll() {
            Some(Page::Calibrate)
        } else if app.ui.opts.verify.back.poll() {
            Some(Page::Profiles)
        } else if app.ui.opts.play.scales.poll() {
            Some(Page::Quantizer)
        } else if app.ui.opts.quantizer.notes.poll() {
            Some(Page::QuantNotes)
        } else if app.ui.opts.quantizer.setups.poll() {
            Some(Page::QuantSetups)
        } else if app.ui.opts.quantizer.routes.poll() {
            Some(Page::Play)
        } else if header_back {
            parent
        } else {
            None
        };
        if let Some(page) = destination {
            app.ui.opts.tracker.page.value = page;
            app.ui.opts.tracker.selected = Some(0);
            app.ui.opts.tracker.modify = false;
            app.ui.external_modify();
        }
        let menu_active = app.ui.draw();
        app.ui.set_menu_visible(menu_active);
        UiFrame {
            bind_route: app.ui.opts.play.bind.poll(),
            save_setup: app.ui.opts.quant_setups.save.poll(),
            load_setup: app.ui.opts.quant_setups.load.poll(),
            save_notes: app.ui.opts.quant_notes.save.poll(),
            load_notes: app.ui.opts.quant_notes.load.poll(),
            run_play: app.ui.opts.play.run.poll(),
            run_calibration: app.ui.opts.calibrate.run.poll(),
            accept_scan: app.ui.opts.calibrate.accept.poll(),
            discard_scan: app.ui.opts.calibrate.discard.poll(),
            run_verify: app.ui.opts.verify.run.poll(),
            refine: app.ui.opts.verify.improve.poll(),
            accept_refinement: app.ui.opts.verify.accept.poll(),
            discard_refinement: app.ui.opts.verify.discard.poll(),
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

type IntonoPersistence = FlashOptionsPersistence<SPIFlash0, 1100>;

#[inline(never)]
fn persist_setup(storage: &mut Option<IntonoPersistence>, save: bool) -> &'static str {
    if critical_section::with(|cs| MULTI_QUANT.borrow_ref(cs).running) {
        return "STOP OUTPUT FIRST";
    }
    let slot = with_app(|app| app.ui.opts.quant_setups.slot.value);
    let Some(key) = quantizer_setup::key(slot) else {
        return "INVALID SETUP SLOT";
    };
    if with_app(|app| app.ui.opts.all().any(|o| o.key().value() == key)) {
        return "SETUP KEY CONFLICT";
    }
    let Some(storage) = storage.as_mut() else {
        return "NO FLASH STORAGE";
    };
    let mut check = [0u8; quantizer_setup::LEN + 1];
    if save {
        let channels = with_app(|app| app.quant_channels);
        let Some(bytes) = quantizer_setup::encode(&channels) else {
            return "INVALID SETUP";
        };
        if storage.save_key(key, &bytes).is_err() {
            return "SETUP SAVE FAILED";
        }
        match storage.load_key(key, &mut check) {
            Ok(Some(n)) if n == bytes.len() && check[..n] == bytes => "SETUP SAVED",
            _ => "SETUP READBACK FAILED",
        }
    } else {
        let bytes = match storage.load_key(key, &mut check) {
            Ok(Some(n)) => &check[..n],
            Ok(None) => return "NO SAVED SETUP",
            Err(_) => return "SETUP LOAD FAILED",
        };
        let Some(channels) = quantizer_setup::decode(bytes) else {
            return "INVALID SAVED SETUP";
        };
        with_app(|app| {
            app.quant_channels = channels;
            let current = channels[app.quant_selected as usize];
            show_quant_settings(&mut app.ui.opts.quantizer, current);
            critical_section::with(|cs| {
                MULTI_QUANT.borrow_ref_mut(cs).bound = [0; 4];
                *QUANT_NOTES.borrow_ref_mut(cs) = current.masks;
                *NOTE_STATUS.borrow_ref_mut(cs) =
                    (app.ui.opts.quant_notes.slot.value, "NOTES FROM SETUP");
            });
        });
        "SETUP LOADED - STOPPED"
    }
}

#[inline(never)]
fn persist_notes(storage: &mut Option<IntonoPersistence>, save: bool) -> &'static str {
    if critical_section::with(|cs| MULTI_QUANT.borrow_ref(cs).running) {
        return "STOP OUTPUT FIRST";
    }
    let slot = with_app(|app| app.ui.opts.quant_notes.slot.value);
    let Some(key) = note_pattern::key(slot) else {
        return "INVALID NOTE SLOT";
    };
    if with_app(|app| app.ui.opts.all().any(|o| o.key().value() == key)) {
        return "NOTE KEY CONFLICT";
    }
    let Some(storage) = storage.as_mut() else {
        return "NO FLASH STORAGE";
    };
    let mut check = [0u8; note_pattern::LEN + 1];
    if save {
        let masks = critical_section::with(|cs| *QUANT_NOTES.borrow_ref(cs));
        let Some(bytes) = note_pattern::encode(masks) else {
            return "INVALID NOTES";
        };
        if storage.save_key(key, &bytes).is_err() {
            return "NOTE SAVE FAILED";
        }
        match storage.load_key(key, &mut check) {
            Ok(Some(n)) if n == bytes.len() && check[..n] == bytes => "NOTES SAVED",
            _ => "NOTE READBACK FAILED",
        }
    } else {
        let bytes = match storage.load_key(key, &mut check) {
            Ok(Some(n)) => &check[..n],
            Ok(None) => return "NO SAVED NOTES",
            Err(_) => return "NOTE LOAD FAILED",
        };
        let Some(masks) = note_pattern::decode(bytes) else {
            return "INVALID SAVED NOTES";
        };
        critical_section::with(|cs| *QUANT_NOTES.borrow_ref_mut(cs) = masks);
        "NOTES LOADED"
    }
}

fn expanded_window(storage: &IntonoPersistence) -> core::ops::Range<u32> {
    let base = storage.default_window().start;
    base + 8192..base + 24576
}

fn profile_key(slot: u8) -> Option<u32> {
    let key = oscillator_calibration::storage::key(slot)?;
    if with_app(|app| app.ui.opts.all().any(|o| o.key().value() == key)) {
        None
    } else {
        Some(key)
    }
}

// Flash reads share the journal/cache path with profile recall. Keep them out
// of active output service. RAM binding only copies a bounded immutable curve.
#[inline(never)]
fn bind_route(
    storage: &mut Option<IntonoPersistence>,
    cal: &calibration_live::Live,
    output: usize,
    source: u8,
) -> &'static str {
    if output >= 4 || source > oscillator_calibration::storage::SLOTS + 1 {
        return "INVALID ROUTE";
    }
    if critical_section::with(|cs| MULTI_QUANT.borrow_ref(cs).lanes[output].active) {
        return "STOP THIS OUTPUT BEFORE BINDING";
    }
    // A failed replacement must not arm a stale curve under the new request.
    critical_section::with(|cs| MULTI_QUANT.borrow_ref_mut(cs).bound[output] = 0);
    if source == 0 {
        critical_section::with(|cs| MULTI_QUANT.borrow_ref_mut(cs).bound[output] = 0);
        return "NOMINAL CV - NO CORRECTION";
    }
    if source == 1 {
        let Some(profile) = cal.profile.as_ref() else {
            return "NO ACCEPTED RAM PROFILE";
        };
        return install_route_curve(output, source, profile);
    }
    if cal.active() || outputs_running() {
        return "STOP OUTPUTS BEFORE FLASH READ";
    }
    let Some(key) = profile_key(source - 1) else {
        return "INVALID PROFILE SLOT";
    };
    let Some(storage) = storage.as_mut() else {
        return "NO PROFILE STORAGE";
    };
    let mut bytes = [0; oscillator_calibration::storage::MAX_BYTES + 1];
    let result = match storage.load_key_in(expanded_window(storage), key, &mut bytes) {
        Ok(None) => storage.load_key(key, &mut bytes),
        other => other,
    };
    let len = match result {
        Ok(Some(n)) => n,
        Ok(None) => return "EMPTY PROFILE SLOT",
        Err(_) => return "PROFILE READ FAILED",
    };
    bind_route_record(output, source, &bytes[..len])
}

#[inline(never)]
fn bind_route_record(output: usize, source: u8, bytes: &[u8]) -> &'static str {
    let Ok(record) = oscillator_calibration::storage::decode(bytes) else {
        return "INVALID STORED PROFILE";
    };
    install_route_curve(output, source, &record.profile)
}

#[inline(never)]
fn install_route_curve(
    output: usize,
    source: u8,
    profile: &oscillator_calibration::Profile,
) -> &'static str {
    critical_section::with(|cs| {
        let mut q = MULTI_QUANT.borrow_ref_mut(cs);
        if !q.lanes[output].bind_profile(profile) {
            return "CANNOT BIND PROFILE";
        }
        q.bound[output] = source;
        if let Some(note) = profile.natural_note() {
            // Binding adopts the oscillator's natural musical origin/root.
            // Subsequent stopped-route edits remain explicit user overrides.
            with_app(|app| {
                let c = &mut app.quant_channels[output];
                c.zero = note;
                c.root = note % 12;
                q.configs[output] = *c;
                if app.quant_selected as usize == output {
                    app.ui.opts.play.zero_note.value = note;
                    show_quant_settings(&mut app.ui.opts.quantizer, *c);
                    app.ui.external_modify();
                }
            });
            "BOUND - NATURAL NOTE / ROOT SET"
        } else {
            "BOUND - NO MEASURED 0V REFERENCE"
        }
    })
}

#[inline(never)]
fn save_profile(
    storage: &mut Option<IntonoPersistence>,
    cal: &mut calibration_live::Live,
    slot: u8,
    zero_note: u8,
    name: &str,
) -> &'static str {
    use oscillator_calibration::storage as record;
    if cal.active() || outputs_running() {
        return "BUSY - STOP OUTPUT FIRST";
    }
    if cal.pending_profile.is_some() {
        return "ACCEPT OR DISCARD CAL FIRST";
    }
    if cal
        .refinement
        .as_ref()
        .is_some_and(|r| r.stage == oscillator_calibration::refinement::Stage::Ready)
    {
        return "ACCEPT OR DISCARD FIRST";
    }
    let (Some(profile), Some(route)) = (cal.profile.as_ref(), cal.profile_route) else {
        return "NO CALIBRATION TO SAVE";
    };
    let Some(key) = profile_key(slot) else {
        return "INVALID PROFILE SLOT";
    };
    let Some(storage) = storage.as_mut() else {
        return "NO PROFILE STORAGE";
    };
    let mut bytes = [0; record::MAX_BYTES];
    let Ok(len) = record::encode(
        profile,
        route,
        profile.natural_note().unwrap_or(zero_note),
        cal.profile_quality,
        name,
        &mut bytes,
    ) else {
        return "INVALID NAME / PROFILE";
    };
    if storage
        .save_key_in(expanded_window(storage), key, &bytes[..len])
        .is_err()
    {
        return "SAVE FAILED";
    }
    let mut check = [0; record::MAX_BYTES + 1];
    if !matches!(storage.load_key_in(expanded_window(storage),key,&mut check),Ok(Some(n)) if n==len && check[..n]==bytes[..len])
    {
        return "SAVE READBACK FAILED";
    }
    cal.profile.as_mut().unwrap().rename(name).ok();
    "PROFILE SAVED"
}

#[inline(never)]
fn load_profile(
    storage: &mut Option<IntonoPersistence>,
    cal: &mut calibration_live::Live,
    slot: u8,
    editor: &mut oscillator_calibration::name::Editor,
) -> (&'static str, Option<u8>) {
    use oscillator_calibration::storage as record;
    if cal.active() || outputs_running() {
        return ("BUSY - STOP OUTPUT FIRST", None);
    }
    let Some(key) = profile_key(slot) else {
        return ("INVALID PROFILE SLOT", None);
    };
    let Some(storage) = storage.as_mut() else {
        return ("NO PROFILE STORAGE", None);
    };
    let mut bytes = [0; record::MAX_BYTES + 1];
    // Fall back only when absent, never hide a corrupt/newer record by loading
    // an old calibration. Legacy journal is read-only for profile operations.
    let result = match storage.load_key_in(expanded_window(storage), key, &mut bytes) {
        Ok(None) => storage.load_key(key, &mut bytes),
        other => other,
    };
    let len = match result {
        Ok(Some(n)) => n,
        Ok(None) => return ("EMPTY PROFILE SLOT", None),
        Err(_) => return ("PROFILE READ FAILED", None),
    };
    decode_profile(&bytes[..len], cal, editor)
}

// Decoding moves a complete profile. Keep its temporaries out of the frame
// that calls the flash journal reader, which has its own nested buffers.
#[inline(never)]
fn decode_profile(
    bytes: &[u8],
    cal: &mut calibration_live::Live,
    editor: &mut oscillator_calibration::name::Editor,
) -> (&'static str, Option<u8>) {
    let Ok(record) = oscillator_calibration::storage::decode(bytes) else {
        return ("INVALID STORED PROFILE", None);
    };
    let zero = record.profile.natural_note().unwrap_or(record.zero_note);
    if !cal.recall(record) {
        return ("BUSY - STOP OUTPUT FIRST", None);
    }
    editor.set(cal.profile.as_ref().unwrap().name());
    ("PROFILE LOADED - OUTPUT OFF", Some(zero))
}

struct RuntimeResources {
    uart: pac::UART0,
    hardware_calibration: Option<(i32, i32, u8)>,
    hardware_calibration_bits: u8,
    timer: Timer0,
    tuner: pac::TUNER_PERIPH,
    display: pac::TUNER_DISPLAY,
    persistence: Option<IntonoPersistence>,
    counts_per_v: f32,
    video_size: (u16, u16),
}

// One-byte, nonblocking boot markers for diagnosing startup without risking
// a stalled USB serial reader freezing the real-time firmware.
fn boot_mark(byte: u8) {
    // Steal only this zero-sized register accessor. Stealing `Peripherals`
    // would mark the whole device taken before startup's `take()` call.
    let uart = unsafe { pac::UART0::steal() };
    if uart.tx_ready().read().txe().bit() {
        uart.tx_data().write(|w| unsafe { w.data().bits(byte) });
    }
}

/// Complete all allocation-heavy and deserialization-heavy startup work before
/// enabling interrupts. Its stack frame is released before `run()` begins.
#[inline(never)]
fn startup() -> RuntimeResources {
    let peripherals = pac::Peripherals::take().unwrap();
    let sysclk = pac::clock::sysclk();
    peripherals
        .PLAYBACK_TIMER
        .enable()
        .write(|w| w.enable().bit(false));
    peripherals
        .PLAYBACK_TIMER
        .reload()
        .write(|w| unsafe { w.value().bits(u32::MAX) });
    peripherals
        .PLAYBACK_TIMER
        .mode()
        .write(|w| w.periodic().bit(true));
    peripherals
        .PLAYBACK_TIMER
        .enable()
        .write(|w| w.enable().bit(true));
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
    // Bank 1 is not visible at boot. Build the empty CAL dashboard here so
    // entering CAL can publish its grid and circular edge on the next frame,
    // without waiting for a multi-frame clear/draw pass.
    let mut calibration_background = BackgroundCanvas::new(
        PSRAM_FB_BASE + 0x100000,
        modeline.h_active,
        modeline.v_active,
        ROUND_DISPLAY,
    );
    calibration_background.clear();
    calibration_background.draw_scene_range(
        ui_scene::Scene::Calibration,
        0,
        ui_scene::Scene::Calibration.segments(),
        None,
        (bipolar::MIN_UV, bipolar::MAX_UV),
        (0, 6_000_000),
        CalibrationGraph::Pitch,
        ui_canvas::CAL_ERROR_SPAN_MC,
    );
    calibration_background.finish();
    video.enable();
    boot_mark(b'V');
    let tuner_display = peripherals.TUNER_DISPLAY;

    let mut pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
    let counts_per_v = pmod.counts_per_v() as f32;
    // Preserve load_or_default behavior, but retain read-only diagnostics so
    // a missing EEPROM record cannot masquerade as factory-calibrated zero.
    let hardware_calibration_bits = pmod.f_bits();
    let hardware_calibration = calibration::CalibrationConstants::from_eeprom(&mut I2c1::new(
        peripherals.I2C1,
    ))
    .map(|constants| {
        constants.write_to_pmod(&mut pmod);
        (
            constants.cal.dac_scale[1],
            constants.cal.dac_zero[1],
            constants.cal.fractional_bits,
        )
    });

    let mut opts = Opts::default();
    let persistence = if let Some(window) = bootinfo.manifest.get_option_storage_window() {
        let default = window.start..window.start.saturating_add(8192);
        match IntonoPersistence::with_reserved_buffer(spiflash, default, window) {
            Ok(mut storage) => {
                storage.load_options(&mut opts).ok();
                Some(storage)
            }
            Err(_) => {
                warn!("Invalid option storage window");
                None
            }
        }
    } else {
        warn!("No option storage region; settings will not persist");
        None
    };
    // Recall instrument settings, not the navigation position saved alongside
    // them. Start at the INTONO tuning page heading on every boot, outside edit mode.
    opts.tracker.page.value = Page::Tuner;
    // Name drafts are not profiles and must not restore half-edited characters.
    opts.profiles.position.value = 1;
    opts.profiles.character.value = b'O';
    opts.tracker.selected = None;
    opts.tracker.modify = false;
    install_app(opts);
    boot_mark(b'A');
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
    boot_mark(b'R');
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
    let counts_per_v = *counts_per_v;
    let video_size = *video_size;
    let midi_input = unsafe { pac::Peripherals::steal() }.MIDI_INPUT;
    handler!(timer0 = || timer0_handler());

    irq::scope(|scope| {
        scope.register(handlers::Interrupt::TIMER0, timer0);
        timer.enable_tick_isr(PLAYBACK_PERIOD_MS, pac::Interrupt::TIMER0);
        let sample_rate = tuner.info().read().sample_rate().bits();
        let mut frame_ticks = FRAME_PERIOD_TICKS;
        let mut smoothed_midi = [None; 4];
        let mut midi_held = midi_learn::HeldNotes::default();
        let mut measurements = MeasurementBank::default();
        #[cfg(tuner_nsdf_continuous)]
        let mut nsdf_sequences = [nsdf_trace::Sequence::default(); 4];
        let mut calibration = calibration_live::Live::new();
        let mut calibration_controls: Option<RuntimeControls> = None;
        let mut capture_trace = capture_trace::Trace::with_calibration(
            *hardware_calibration,
            *hardware_calibration_bits,
        );
        #[cfg(tuner_nsdf_wave_diag)]
        let mut cv_probe = cv_probe::Probe::default();
        let mut nsdf_trace = nsdf_trace::Trace::new();
        let mut run_calibration = false;
        let mut run_verify = false;
        let mut refine = false;
        let mut accept_refinement = false;
        let mut discard_refinement = false;
        let mut name_editor = oscillator_calibration::name::Editor::new();
        let mut profile_status = "SAVE / LOAD ONLY WITH OUTPUT OFF";
        let mut profile_status_slot = 1;
        // Each character bank must receive a changed menu once. Closing the
        // menu hides it; it does not destroy the retained contents of either bank.
        let mut menu_dirty_banks = 0b11u8;
        let mut save_feedback = feedback::Feedback::default();
        let mut backgrounds = ui_scene::Backgrounds::with_prepared_calibration();
        let mut scene = ui_scene::Scene::Spiral;
        let mut calibration_revision = 0u64;
        let mut calibration_plot_dirty = false;
        let mut live_trace = ui_scene::LiveTrace::new();
        let mut text_scenes = [None; 2];
        // Compact occupancy only: 512 bytes total, not an 8-KiB text shadow.
        let mut text_occupied = [ui_text::Occupied::new(), ui_text::Occupied::new()];
        let mut last_ui_ms = 0;
        let mut marked_ui = false;
        loop {
            riscv::asm::wfi();
            let now = with_app(|app| app.now_ms);
            #[cfg(tuner_nsdf_wave_diag)]
            cv_probe.tick(
                &tuner,
                uart,
                now,
                !calibration.active()
                    && !playback_visible()
                    && with_app(|app| app.ui.opts.tracker.page.value == options::Page::Tuner),
            );
            // Service the DAC watchdog before any opportunistic serial or
            // framebuffer work. Transitions remain in calibration.tick().
            calibration.renew_output(&tuner);
            // Fast diagnostic is foreground-only, never an ISR job. It gets
            // opportunities between UI frames; UART writes remain bounded.
            #[cfg(tuner_nsdf_continuous)]
            {
                nsdf_trace.set_operation_input(
                    calibration.active().then_some(calibration.input),
                    with_app(|app| app.ui.opts.tracker.page.value == options::Page::Tuner),
                );
                let status_due = capture_trace.status_due(now, calibration.active());
                nsdf_trace.tick_reporting(
                    uart,
                    now,
                    !status_due
                        && env!("TILIQUA_INTONO_NSDF_TRACE") != "continuous-quiet",
                );
                if status_due && nsdf_trace.serial_idle() {
                    // One owner at a time, including under UART backpressure.
                    // Reuse the existing report storage; no new RAM buffer.
                    for _ in 0..32 {
                        capture_trace.tick(
                            &tuner,
                            uart,
                            now,
                            &calibration,
                            measurements.channel(calibration.input),
                            counts_per_v as i32,
                        );
                    }
                }
            }
            #[cfg(not(tuner_nsdf_continuous))]
            if nsdf_trace.fast() {
                nsdf_trace.tick(uart, now);
            }
            let ui_period_ms = TIMER0_ISR_PERIOD_MS as u64;
            // Opt-in transition capture trades idle tuner UI refresh for UART
            // service opportunities. Never throttle calibration, verify or PLAY.
            // Encoder sampling and output processing remain in their ISRs.
            let ui_period_ms = nsdf_trace.ui_period_ms(
                !calibration.active()
                    && with_app(|app| app.ui.opts.tracker.page.value == options::Page::Tuner)
                    && !outputs_running(),
                ui_period_ms,
            );
            let ui_elapsed_ms = now.wrapping_sub(last_ui_ms);
            if ui_elapsed_ms < ui_period_ms {
                continue;
            }
            last_ui_ms = now;
            critical_section::with(|cs| {
                let mut r = OWNERS.borrow_ref_mut(cs);
                let q = MULTI_QUANT.borrow_ref(cs);
                for n in 0..4 {
                    if !q.lanes[n].active {
                        r.release(Owner::Quant(n as u8));
                    }
                }

                if !calibration.active() {
                    r.release(Owner::Calibration);
                }
            });
            // The menu may be browsed freely, but an active operation keeps
            // the route/settings captured when it started.
            if calibration.active() {
                if let Some(c) = calibration_controls {
                    with_app(|app| {
                        app.ui.opts.calibrate.input.value = c.calibration_input;
                        app.ui.opts.calibrate.output.value = c.calibration_output;
                        app.ui.opts.calibrate.zero_note.value = c.zero_note;
                    });
                }
            }
            let ui_frame = poll_ui_frame();
            if !marked_ui {
                boot_mark(b'U');
                marked_ui = true;
            }
            // Consume a bounded burst every UI tick, even when learning is off.
            // Note traffic cannot accumulate and later edit a different scale.
            let (learn, octave, selected, slot) = with_app(|app| {
                (
                    critical_section::with(|cs| *MIDI_LEARN.borrow_ref(cs))
                        && app.ui.opts.tracker.page.value == Page::QuantNotes,
                    app.ui.opts.quant_notes.octave.value as usize,
                    app.quant_selected as usize,
                    app.ui.opts.quant_notes.slot.value,
                )
            });
            if !learn {
                midi_held.clear();
            }
            for _ in 0..8 {
                let word = midi_input.midi_read().read().msg().bits();
                if word == 0 {
                    break;
                }
                if !learn {
                    continue;
                }
                critical_section::with(|cs| {
                    if MULTI_QUANT.borrow_ref(cs).lanes[selected].active {
                        *MIDI_LEARN.borrow_ref_mut(cs) = false;
                        *NOTE_STATUS.borrow_ref_mut(cs) =
                            (slot, "STOP CHANNEL BEFORE MIDI LEARN");
                    } else if let Some(enabled) = midi_held.process(
                        &mut QUANT_NOTES.borrow_ref_mut(cs), octave, word,
                    ) {
                        *NOTE_STATUS.borrow_ref_mut(cs) = (
                            slot,
                            if enabled { "MIDI NOTE ADDED - SAVE TO KEEP" }
                            else { "MIDI NOTE REMOVED - SAVE TO KEEP" },
                        );
                    }
                });
            }
            if ui_frame.bind_route {
                let (n, c) = with_app(|app| {
                    (
                        app.quant_selected as usize,
                        app.quant_channels[app.quant_selected as usize],
                    )
                });
                let status = bind_route(persistence, &calibration, n, c.correction);
                critical_section::with(|cs| {
                    MULTI_QUANT.borrow_ref_mut(cs).lanes[n].status = status
                });
            }
            if ui_frame.run_play {
                critical_section::with(|cs| {
                    let mut q = MULTI_QUANT.borrow_ref_mut(cs);
                    let (n, c) = with_app(|app| {
                        (
                            app.quant_selected as usize,
                            app.quant_channels[app.quant_selected as usize],
                        )
                    });
                    q.toggle(
                        &tuner,
                        n,
                        c,
                        ui_frame.now_ms as u32,
                        counts_per_v as i32,
                        &mut OWNERS.borrow_ref_mut(cs),
                    );
                });
            }
            if !nsdf_trace.fast() {
                nsdf_trace.tick(uart, ui_frame.now_ms);
            }
            run_calibration |= ui_frame.run_calibration;
            if ui_frame.controls.mode == runtime::OperatingMode::Calibrator {
                if ui_frame.discard_scan {
                    calibration.discard_scan();
                } else if ui_frame.accept_scan {
                    calibration.accept_scan(&tuner);
                    if let Some(note) = calibration.profile.as_ref().and_then(oscillator_calibration::Profile::natural_note) {
                        with_app(|app| { app.ui.opts.calibrate.zero_note.value = note; });
                    }
                }
            }
            run_verify |= ui_frame.run_verify;
            refine |= ui_frame.refine;
            accept_refinement |= ui_frame.accept_refinement;
            discard_refinement |= ui_frame.discard_refinement;
            if ui_frame.controls.mode == runtime::OperatingMode::Profiles {
                if ui_frame.profile_slot != profile_status_slot {
                    profile_status_slot = ui_frame.profile_slot;
                    profile_status = "SAVE / LOAD ONLY WITH OUTPUT OFF";
                }
                if let Some(character) =
                    name_editor.update(ui_frame.name_position, ui_frame.name_character)
                {
                    with_app(|app| {
                        app.ui.opts.profiles.character.value = character;
                        app.ui.external_modify();
                    });
                    menu_dirty_banks = 0b11;
                }
                if ui_frame.save_profile {
                    profile_status = save_profile(
                        persistence,
                        &mut calibration,
                        ui_frame.profile_slot,
                        ui_frame.controls.zero_note,
                        name_editor.name(),
                    );
                } else if ui_frame.load_profile {
                    let (status, zero) = load_profile(
                        persistence,
                        &mut calibration,
                        ui_frame.profile_slot,
                        &mut name_editor,
                    );
                    profile_status = status;
                    if let Some(zero) = zero {
                        with_app(|app| {
                            app.ui.opts.calibrate.zero_note.value = zero;
                            app.ui.opts.calibrate.input.value = calibration.input;
                            app.ui.opts.calibrate.output.value = calibration.output;
                            app.ui.opts.profiles.position.value = 1;
                            app.ui.opts.profiles.character.value = name_editor.character();
                            app.ui.external_modify();
                        });
                        menu_dirty_banks = 0b11;
                    }
                }
            }
            let feedback_ms = if ui_period_ms > TIMER0_ISR_PERIOD_MS as u64 {
                ui_elapsed_ms.min(u16::MAX as u64) as u16
            } else {
                TIMER0_ISR_PERIOD_MS as u16
            };
            if save_feedback.tick(feedback_ms) {
                menu_dirty_banks = 0b11;
            }
            if ui_frame.menu_dirty {
                menu_dirty_banks = 0b11;
            }
            if (ui_frame.save_notes || ui_frame.load_notes)
                && !calibration.active()
                && with_app(|app| app.ui.opts.tracker.page.value == Page::QuantNotes)
            {
                let status = persist_notes(persistence, ui_frame.save_notes);
                let slot = with_app(|app| app.ui.opts.quant_notes.slot.value);
                critical_section::with(|cs| *NOTE_STATUS.borrow_ref_mut(cs) = (slot, status));
            }
            if (ui_frame.save_setup || ui_frame.load_setup)
                && !calibration.active()
                && with_app(|app| app.ui.opts.tracker.page.value == Page::QuantSetups)
            {
                let status = persist_setup(persistence, ui_frame.save_setup);
                let slot = with_app(|app| app.ui.opts.quant_setups.slot.value);
                critical_section::with(|cs| *SETUP_STATUS.borrow_ref_mut(cs) = (slot, status));
            }
            if (ui_frame.save || ui_frame.wipe) && (calibration.active() || outputs_running()) {
                save_feedback.show("stop outputs first");
                menu_dirty_banks = 0b11;
            }
            if ui_frame.save && !calibration.active() && !outputs_running() {
                let result = if let Some(storage) = persistence.as_mut() {
                    let opts = snapshot_options_for_save();
                    if storage.save_options(&opts).is_ok() {
                        "saved"
                    } else {
                        "failed"
                    }
                } else {
                    "no flash"
                };
                save_feedback.show(result);
                menu_dirty_banks = 0b11;
            }
            if ui_frame.wipe && !calibration.active() && !outputs_running() {
                save_feedback = feedback::Feedback::default();
                menu_dirty_banks = 0b11;
                if let Some(storage) = persistence.as_mut() {
                    let opts = snapshot_options_for_save();
                    storage.erase_options(&opts).ok();
                }
                reset_options();
                name_editor = oscillator_calibration::name::Editor::new();
            }

            let calibration_view = matches!(
                ui_frame.controls.mode,
                runtime::OperatingMode::Calibrator
                    | runtime::OperatingMode::Verify
                    | runtime::OperatingMode::Profiles
                    | runtime::OperatingMode::Play
                    | runtime::OperatingMode::Quantizer
            );
            let calibration_dashboard = matches!(ui_frame.controls.mode,
                runtime::OperatingMode::Calibrator
                    | runtime::OperatingMode::Profiles
                    | runtime::OperatingMode::Verify);
            let calibration_prepared = matches!(
                ui_frame.controls.mode,
                runtime::OperatingMode::Calibrator
                    | runtime::OperatingMode::Profiles
                    | runtime::OperatingMode::Verify
            );
            let requested_scene = if calibration_prepared {
                ui_scene::Scene::Calibration
            } else if ui_frame.controls.display_mode == DisplayMode::Linear {
                ui_scene::Scene::Linear
            } else {
                ui_scene::Scene::Spiral
            };
            let plot_profile = calibration_plot_profile(&calibration);
            let plot_range = calibration_plot_range(&calibration, plot_profile);
            let plot_anchor = calibration_plot_anchor(&calibration, plot_profile);
            let graph = ui_frame.controls.calibration_graph;
            let error_span_mc = calibration_plot_error_span(&calibration, plot_profile);
            let live_points = calibration.acquiring_points();
            let live_first = live_points.and_then(|points| points.first())
                .map(|point| (point.microvolts, point.millicents));
            let live_last = live_points.and_then(|points| points.last())
                .map(|point| (point.microvolts, point.millicents));
            let stale_live_trace = live_trace.observe(
                live_points.is_some(), live_first, live_last,
                live_points.map_or(0, |points| points.len()),
            );
            let plot_revision = calibration_plot_revision(
                plot_profile, plot_range, plot_anchor, graph, error_span_mc);
            if plot_revision != calibration_revision || stale_live_trace {
                calibration_revision = plot_revision;
                backgrounds.invalidate_calibration();
                calibration_plot_dirty = true;
            }
            let mut swap_background = false;
            let exchange = tuner_display.frame().read();
            if !exchange.busy().bit() {
                // Keep CAL ready on the unused bank while the tuner is shown.
                // Otherwise the idle warmer immediately overwrites the CAL
                // frame prepared at startup with Linear, reintroducing the
                // long blank transition on the first CAL visit.
                let prepare_scene = if requested_scene != scene {
                    requested_scene
                } else if calibration_prepared {
                    ui_scene::Scene::Calibration
                } else if scene == ui_scene::Scene::Spiral {
                    ui_scene::Scene::Calibration
                } else {
                    ui_scene::Scene::Spiral
                };
                let bank = exchange.background_back().bit() as usize;
                let mut canvas = BackgroundCanvas::new(
                    PSRAM_FB_BASE + bank * 0x100000,
                    video_size.0,
                    video_size.1,
                    ROUND_DISPLAY,
                );
                match backgrounds.step(
                    bank,
                    prepare_scene,
                    video_size.0 as usize * video_size.1 as usize / 4,
                ) {
                    ui_scene::Work::Clear { first, end } => canvas.clear_words(first, end),
                    ui_scene::Work::Draw { scene, first, end } => {
                        canvas.draw_scene_range(scene, first, end, plot_profile,
                            plot_range, plot_anchor, graph, error_span_mc);
                    }
                    ui_scene::Work::Flush => {
                        canvas.finish();
                        backgrounds.flushed(
                            bank,
                            prepare_scene,
                            video_size.0 as usize * video_size.1 as usize / 4,
                        );
                        if prepare_scene == ui_scene::Scene::Calibration {
                            live_trace.reset_bank(bank);
                        }
                    }
                    ui_scene::Work::Ready => {
                        let mut live_updated = false;
                        if prepare_scene == ui_scene::Scene::Calibration {
                            if let Some(points) = live_points {
                                let pending = live_trace.pending(bank);
                                if !pending.is_empty() {
                                    canvas.draw_live_calibration_segments(
                                        points, pending, graph, error_span_mc);
                                    canvas.finish();
                                    live_trace.mark_drawn(bank);
                                    live_updated = true;
                                }
                            }
                        }
                        swap_background = requested_scene != scene
                            || (calibration_prepared && calibration_plot_dirty)
                            || (calibration_prepared && live_updated);
                    }
                }
            }

            frame_ticks = frame_ticks.saturating_add(1);
            if frame_ticks >= FRAME_PERIOD_TICKS || swap_background {
                frame_ticks = 0;
                let controls = ui_frame.controls;
                if discard_refinement {
                    calibration.discard_refinement(&tuner);
                    discard_refinement = false;
                    refine = false;
                    accept_refinement = false;
                    run_verify = false;
                }
                if accept_refinement {
                    if controls.mode == runtime::OperatingMode::Verify {
                        calibration.accept_refinement(&tuner);
                    }
                    accept_refinement = false;
                }
                if refine {
                    capture_trace.cancel(&tuner);
                    let can_start = !calibration.active()
                        && calibration.profile_route.is_some_and(|route| {
                            critical_section::with(|cs| {
                                OWNERS.borrow_ref_mut(cs).claim(
                                    Owner::Calibration,
                                    1 << route.input(),
                                    1 << route.output(),
                                )
                            })
                        });
                    if can_start {
                        calibration_controls = Some(controls);
                        calibration.start_refinement(&tuner, controls, ui_frame.now_ms);
                    } else {
                        calibration.status = "BUSY - STOP OWNER BEFORE REFINE";
                    }
                    refine = false;
                }
                if run_verify {
                    capture_trace.cancel(&tuner);
                    run_verify = false;
                    let can_start = calibration.verifying
                        || (!calibration.active()
                            && calibration.profile_route.is_some_and(|route| {
                                critical_section::with(|cs| {
                                    OWNERS.borrow_ref_mut(cs).claim(
                                        Owner::Calibration,
                                        1 << route.input(),
                                        1 << route.output(),
                                    )
                                })
                            }));
                    if can_start {
                        calibration_controls = Some(controls);
                        calibration.toggle_verify(&tuner, controls, ui_frame.now_ms);
                    } else {
                        calibration.status = "NO PROFILE OR CHANNEL BUSY";
                    }
                }
                if run_calibration {
                    capture_trace.cancel(&tuner);
                    run_calibration = false;
                    if controls.mode == runtime::OperatingMode::Calibrator {
                        let resume = calibration.can_continue_automatic();
                        let input = if resume { calibration.input } else { controls.calibration_input };
                        let output = if resume { calibration.output } else { controls.calibration_output };
                        let can_start = calibration.active()
                            || critical_section::with(|cs| {
                                OWNERS.borrow_ref_mut(cs).claim(
                                    Owner::Calibration,
                                    1 << input,
                                    1 << output,
                                )
                            });
                        if can_start {
                            if !resume {
                                calibration_controls = Some(controls);
                            }
                            calibration.toggle_automatic(&tuner, controls, ui_frame.now_ms);
                        } else {
                            calibration.status = "CHANNEL BUSY - STOP ITS OWNER";
                        }
                    }
                }
                for input in 0..4u8 {
                    let measurement = read_measurement(
                        &tuner,
                        counts_per_v,
                        input,
                    );
                    #[cfg(tuner_nsdf_continuous)]
                    nsdf_trace.observe_baseline(
                        input,
                        measurement.frequency_hz,
                        measurement.valid && measurement.qualified,
                        measurement.end_age_ms,
                        ui_frame.now_ms,
                    );
                    #[cfg(tuner_nsdf_continuous)]
                    let measurement = {
                        let (hz, qualified, sequence, window_age_ms, end_age_ms) =
                            if calibration.active() && input == calibration.input {
                                nsdf_trace.calibration_measurement(
                                    input,
                                    ui_frame.now_ms,
                                    &mut nsdf_sequences[input as usize],
                                )
                            } else {
                                nsdf_trace.measurement(
                                    input,
                                    ui_frame.now_ms,
                                    &mut nsdf_sequences[input as usize],
                                )
                            };
                        ChannelMeasurement {
                            frequency_hz: hz,
                            valid: qualified,
                            qualified,
                            sequence,
                            window_age_ms,
                            end_age_ms,
                            ..measurement
                        }
                    };
                    measurements.update(input, measurement);
                }
                let active_controls = calibration_live::background_controls(
                    calibration_controls.unwrap_or(controls),
                    controls,
                    calibration.verifying,
                );
                if calibration.active() {
                    calibration_controls = Some(active_controls);
                }
                let previous_unstable_count = calibration.scan_warnings.unstable;
                calibration.tick(
                    &tuner,
                    measurements.channel(calibration.input),
                    active_controls,
                    ui_frame.now_ms,
                );
                // Record the first unstable point in the serial status report.
                if calibration.scan_warnings.unstable > previous_unstable_count {
                    capture_trace.note_unstable();
                }
                calibration.take_suggested_note();
                let reference_hz = controls.reference_hz as f32;
                // Never wait for video in the real-time loop. If scanout is
                // stopped or still owns a pending frame, keep servicing the
                // reference output and UI and try a fresh snapshot next time.
                let frame = tuner_display.frame().read();
                if frame.busy().bit() {
                    continue;
                }
                if swap_background {
                    scene = requested_scene;
                    if calibration_prepared {
                        calibration_plot_dirty = false;
                    }
                }
                let text_bank = frame.back_bank().bit() as usize;
                let displayed_scene = if calibration_view {
                    ui_scene::Scene::Calibration
                } else {
                    scene
                };
                let changed = text_scenes[text_bank] != Some(displayed_scene);
                let mut text = TextWriter {
                    display: &tuner_display,
                    occupied: &mut text_occupied[text_bank],
                };
                if changed {
                    text.clear(text_scenes[text_bank].is_none());
                    text_scenes[text_bank] = Some(displayed_scene);
                }
                // Static labels are retained independently in both banks.
                // Dynamic fields still replace their full bounded footprint.
                if calibration_view {
                    text.clear(false);
                    if matches!(
                        controls.mode,
                        runtime::OperatingMode::Quantizer | runtime::OperatingMode::Play
                    ) {
                        publish_quantizer(&tuner_display, &mut text, ui_frame.menu_active);
                    } else {
                        publish_calibration(
                            &tuner_display,
                            &mut text,
                            &calibration,
                            controls,
                            measurements.channel(if calibration.active() {
                                calibration.input
                            } else {
                                controls.calibration_input
                            }),
                            ui_frame.menu_active,
                            scene == ui_scene::Scene::Calibration && !calibration_plot_dirty,
                            ui_frame.profile_slot,
                            name_editor.name(),
                            profile_status,
                        );
                    }
                } else {
                    write_static_text(&mut text, scene, requested_scene != scene, changed);
                    publish_tuner(
                        &tuner_display,
                        &mut text,
                        &measurements,
                        reference_hz,
                        controls.tuner_input,
                        if scene == ui_scene::Scene::Linear {
                            DisplayMode::Linear
                        } else {
                            DisplayMode::Arc
                        },
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
                tuner_display
                    .backdrop()
                    .write(|w| w.blank().bit(calibration_view
                        && (!calibration_dashboard || scene != ui_scene::Scene::Calibration)));
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
    boot_mark(b'M');
    run(&mut startup())
}
