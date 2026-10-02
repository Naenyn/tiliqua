#![no_std]
#![no_main]

mod calibration_live;
mod capture_trace;
#[cfg(tuner_nsdf_wave_diag)]
mod cv_probe;
mod feedback;
mod measurement_snapshot;
mod midi_learn;
mod midi_transpose;
mod note_pattern;
mod nsdf_guard;
mod nsdf_select;
mod nsdf_trace;
#[path = "calibration.rs"]
mod oscillator_calibration;
mod ownership;
mod route_group;
mod pitch_math;
mod quantizer_setup;
mod scale;
mod serial_report;
mod stack_monitor;
mod ui_canvas;
mod static_guides { include!(concat!(env!("OUT_DIR"), "/static-guides.rs")); }
mod ui_controls;
mod ui_scale;
mod ui_route;
mod ui_navigation;
mod ui_keyboard;

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
const NOTE_NAMES: [&str; 12] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
];
const ROUND_DISPLAY: bool = matches!(FIXED_MODELINE, Some((720, 720)));

struct App {
    ui: ui::UI<Encoder0, EurorackPmod0, I2c0, Opts>,
    now_ms: u64,
    quant_channels: [quantizer_setup::Channel; 4],
    quant_selected: u8,
    route_selected: u8,
    groups: route_group::Layout,
    midi: [midi_transpose::Config;4],
    midi_selected: u8,
    tuner_focus: u8,
}

fn quant_settings(
    opts: &options::QuantizerOpts,
    masks: [u16; 8],
    current: quantizer_setup::Channel,
) -> quantizer_setup::Channel {
    let mut edited=current;
    edited.edit_scale(opts.scale.value as u8,masks);
    if edited.octaves!=opts.octaves.value {edited.scale_slot=0;}
    edited.octaves=opts.octaves.value;
    edited
}
#[inline(never)]
fn show_quant_settings(opts: &mut options::QuantizerOpts, c: quantizer_setup::Channel) {
    use strum::IntoEnumIterator;
    opts.transpose.value = c.transpose;
    opts.octaves.value=c.octaves;
    opts.view_octave.value=ui_keyboard::window(opts.view_octave.value,c.octaves,None);
    opts.scale.value = options::ScalePreset::iter()
        .nth(c.scale as usize)
        .unwrap_or_default();
    opts.root.value = options::ScaleRoot::iter()
        .nth(c.root as usize)
        .unwrap_or_default();

}

#[inline(never)]
fn show_route_settings(opts: &mut options::PlayOpts,c:quantizer_setup::Channel) {
    use strum::IntoEnumIterator;
    opts.mapping.value=if c.equal {options::Distribution::Equal}else{options::Distribution::Nearest};
    opts.zero_note.value=c.zero;
    opts.scale.value=options::ScalePreset::iter().nth(c.scale as usize).unwrap_or_default();
    opts.key.value=options::ScaleRoot::iter().nth(c.root as usize).unwrap_or_default();
    opts.transpose.value=c.transpose;
    opts.quantize.value=if c.quantize {options::RouteQuantize::Scale}else{options::RouteQuantize::Off};
    opts.correction.value=options::Correction::iter().nth(c.correction as usize).unwrap_or_default();
}

// The timer interrupt and foreground loop share one long-lived UI object.
// Keeping it static prevents future profile/scale/menu growth from silently
// becoming part of `main()`'s stack frame, which previously corrupted an
// already constrained main RAM after the first interrupt.
static APP: Mutex<RefCell<Option<App>>> = Mutex::new(RefCell::new(None));
static OWNERS: Mutex<RefCell<Reservations>> = Mutex::new(RefCell::new(Reservations::new()));

// Conventional octave-pattern editor; never part of oscillator profiles.
static QUANT_NOTES: Mutex<RefCell<[u16; 8]>> = Mutex::new(RefCell::new([0xfff,0,0,0,0,0,0,0]));
static NOTE_STATUS: Mutex<RefCell<(u8, &'static str)>> =
    Mutex::new(RefCell::new((1, "DEFAULT NOTES - LOAD OR EDIT")));
static MIDI_BASE_REQUEST: Mutex<RefCell<bool>> = Mutex::new(RefCell::new(false));
static MIDI_BASE: Mutex<RefCell<u8>> = Mutex::new(RefCell::new(48));
static MIDI_LEARN: Mutex<RefCell<bool>> = Mutex::new(RefCell::new(false));
static SETUP_STATUS: Mutex<RefCell<(u8, &'static str)>> =
    Mutex::new(RefCell::new((1, "SAVE OR LOAD A SETUP")));
type QuantEngine = oscillator_calibration::playback::Engine;
struct MultiQuant {
    groups: route_group::Layout,
    midi: [midi_transpose::Config;4],
    shifts: [i8;4],
    midi_last: [Option<u8>;4],
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
    groups: route_group::Layout::new(),
    midi: [midi_transpose::Config::new();4],
    shifts: [0;4],
    midi_last: [None;4],
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
#[inline(never)]
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
#[inline(never)]
fn quant_status(t: &pac::TUNER_PERIPH, n: usize) -> u32 {
    match n {
        0 => t.quant_status0().read().value().bits(),
        1 => t.quant_status1().read().value().bits(),
        2 => t.quant_status2().read().value().bits(),
        _ => t.quant_status3().read().value().bits(),
    }
}
#[inline(never)]
fn quant_cv(t: &pac::TUNER_PERIPH, n: u8) -> u32 {
    match n {
        0 => t.quant_cv0().read().value().bits(),
        1 => t.quant_cv1().read().value().bits(),
        2 => t.quant_cv2().read().value().bits(),
        _ => t.quant_cv3().read().value().bits(),
    }
}
impl MultiQuant {
    fn transpose_route(&mut self,route:usize,offset:i8) {
        self.shifts[route]=offset;
    }
    fn apply_midi(&mut self) {
        for route in 0..4 {for n in 0..4 {if self.groups.outputs[route]&(1<<n)!=0 {self.lanes[n].set_midi_transpose(self.shifts[route]);}}}
    }
    fn midi_word(&mut self,word:u32) {
        for route in 0..4 {
            if let Some(offset)=self.midi[route].offset(word) {
                self.midi_last[route]=Some((word>>8) as u8);self.transpose_route(route,offset);
            } else if self.midi[route].released(word,self.midi_last[route]) {
                self.midi_last[route]=None;self.transpose_route(route,0);
            }
        }
    }

    fn stop(&mut self, t: &pac::TUNER_PERIPH, reason: &'static str) {
        self.running = false;
        self.phase = 0;
        for (n, lane) in self.lanes.iter_mut().enumerate() {
            quant_command(t, n, lane.stop(reason));
        }
    }
    fn stop_group(&mut self,t:&pac::TUNER_PERIPH,route:usize,reason:&'static str,r:&mut Reservations) {
        for n in 0..4 {
            if self.groups.outputs[route]&(1<<n)!=0 {quant_command(t,n,self.lanes[n].stop(reason));}
        }
        r.release(Owner::Quant(route as u8));
        self.running=self.lanes.iter().any(|lane|lane.active);
    }
    fn toggle(&mut self,t:&pac::TUNER_PERIPH,route:usize,channels:[quantizer_setup::Channel;4],now:u32,counts:i32,r:&mut Reservations) {
        let owner=Owner::Quant(route as u8);
        if r.held(owner) {self.stop_group(t,route,"STOPPED BY USER",r);return;}
        let mask=self.groups.outputs[route];
        let input=self.groups.inputs[route];
        let mut reason=if mask==0 {Some("ADD AN OUTPUT FIRST")}else{None};
        for n in 0..4 {
            if mask&(1<<n)==0 {continue;}
            let c=channels[n];
            if !c.quantize && c.correction==0 {reason=Some("CHOOSE SCALE OR CORRECTION");}
            if c.correction!=0 && self.bound[n]!=c.correction {reason=Some("BIND CORRECTION ON ROUTE FIRST");}
        }
        if reason.is_none() && !r.claim(owner,1<<input,mask) {reason=Some("JACK ASSIGNED - STOP ROUTE");}
        if let Some(reason)=reason {
            for n in 0..4 {if mask&(1<<n)!=0 || (mask==0 && !self.lanes[n].active) {self.lanes[n].status=reason;}}
            return;
        }
        if !self.running {self.phase=0;self.last_cycle=0;self.max_cycles=0;self.max_gap=0;}
        for n in 0..4 {
            if mask&(1<<n)==0 {continue;}
            let mut c=channels[n];c.input=input;self.configs[n]=c;
            let lane=&mut self.lanes[n];
            quant_command(t,n,lane.stop("STOPPED"));
            if lane.arm_route(input,n as u8,c.zero,counts,now,quant_status(t,n),c.correction!=0,c.quantize) {
                lane.scale_id=c.scale;lane.root=c.root;lane.transpose=c.transpose;lane.equal=c.equal;
                lane.set_midi_transpose(self.shifts[route]);
                if c.quantize && c.scale==6 {
                    match scale::Pattern::compile_span(&c.masks,c.octaves) {
                        Ok(pattern)=>lane.pattern=pattern,
                        Err(_)=>{lane.stop("EMPTY PATTERN - ADD NOTES");}
                    }
                }
            }
            if !lane.active {
                let reason=lane.status;self.stop_group(t,route,reason,r);return;
            }
        }
        self.running=true;
    }
}

impl App {
    #[inline(never)]
    fn new(mut opts: Opts) -> Self {
        if opts.tuner.display.value == DisplayMode::Visualizer {
            opts.tuner.display.value = DisplayMode::Arc;
        }
        let quant_selected = opts.quantizer.output.value.min(3);
        let mut quant_channels = quantizer_setup::DEFAULT;
        // Existing selected-route offsets were saved in the old editor fields.
        let selected=&mut quant_channels[quant_selected as usize];
        selected.root=if opts.play.key.value!=options::ScaleRoot::C {opts.play.key.value as u8}
            else {opts.quantizer.root.value as u8};
        selected.equal=opts.play.mapping.value==options::Distribution::Equal;
        selected.transpose=if opts.play.transpose.value!=0 {opts.play.transpose.value}
            else {opts.quantizer.transpose.value};
        use strum::IntoEnumIterator;
        opts.play.key.value=options::ScaleRoot::iter().nth(selected.root as usize).unwrap_or_default();
        opts.play.transpose.value=selected.transpose;
        opts.play.scale.value=opts.quantizer.scale.value;
        quant_channels[quant_selected as usize] = quant_settings(
            &opts.quantizer,
            [0xfff,0,0,0,0,0,0,0],
            quant_channels[quant_selected as usize],
        );
        let peripherals = unsafe { pac::Peripherals::steal() };
        let encoder = Encoder0::new(peripherals.ENCODER0);
        let pca9635 = Pca9635Driver::new(I2c0::new(peripherals.I2C0));
        let pmod = EurorackPmod0::new(peripherals.PMOD0_PERIPH);
        Self {
            quant_channels,
            quant_selected,
            route_selected: quant_selected,
            groups: route_group::Layout::new(),
            midi: [midi_transpose::Config::new();4],
            midi_selected: 1,
            tuner_focus: 0,
            now_ms: 0,
            ui: ui::UI::new_with_fade(opts, TIMER0_ISR_PERIOD_MS, 5_000, encoder, pca9635, pmod),
        }
    }
}

fn visible_ticks(opts: &mut Opts, ticks: i8) {
    let claims = critical_section::with(|cs| *OWNERS.borrow_ref(cs));
    ui_navigation::visible_ticks(opts, ticks, &claims);
}

#[inline(never)]
fn borrow_app(cs:critical_section::CriticalSection<'_>)->core::cell::RefMut<'_,App> {
    core::cell::RefMut::map(APP.borrow_ref_mut(cs),|slot|slot.as_mut().expect("tuner app not initialized"))
}
fn with_app<R>(f: impl FnOnce(&mut App) -> R) -> R {
    critical_section::with(|cs| {
        let mut slot = borrow_app(cs);
        f(&mut slot)
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
            app.ui.update_encoder_realtime(visible_ticks);
            // The retired root selector index now represents piano-key focus.
            // A click reaches the generic edit flag; consume it as a key action.
            if app.ui.opts.tracker.page.value==Page::Quantizer
                && app.ui.opts.tracker.selected==Some(ui_keyboard::KEYBOARD)
                && app.ui.opts.tracker.modify {
                app.ui.opts.tracker.modify=false;
                let key=app.ui.opts.quant_notes.octave.value*12+app.ui.opts.quant_notes.note.value as u8;
                critical_section::with(|cs| {
                    let current_masks=*QUANT_NOTES.borrow_ref(cs);
                    let status=if MULTI_QUANT.borrow_ref(cs).lanes[app.quant_selected as usize].active {
                        "STOP CHANNEL BEFORE EDITING"
                    } else if let Some(masks)=ui_scale::toggle_span(
                        app.ui.opts.quantizer.scale.value as u8,current_masks,app.ui.opts.quantizer.octaves.value,key) {
                        *QUANT_NOTES.borrow_ref_mut(cs)=masks;
                        app.ui.opts.quantizer.scale.value=options::ScalePreset::Custom2;
                        "EDITED - SAVE TO KEEP"
                    } else {"24 EDO NEEDS QUARTER-TONE EDITOR"};
                    *NOTE_STATUS.borrow_ref_mut(cs)=(app.ui.opts.quant_notes.slot.value,status);
                });
            }
            // Resolve a key click now, before later encoder ticks can move its
            // focus while the foreground prepares a display frame.
            if app.ui.opts.tracker.page.value==Page::QuantNotes && app.ui.opts.quant_notes.toggle.poll() {
                let octave=app.ui.opts.quant_notes.octave.value as usize;
                let note=app.ui.opts.quant_notes.note.value as u8;
                critical_section::with(|cs| {
                    let status=if MULTI_QUANT.borrow_ref(cs).lanes[app.quant_selected as usize].active {
                        "STOP CHANNEL BEFORE EDITING"
                    } else {
                        QUANT_NOTES.borrow_ref_mut(cs)[octave]^=1<<note;
                        "EDITED - SAVE TO KEEP"
                    };
                    *NOTE_STATUS.borrow_ref_mut(cs)=(app.ui.opts.quant_notes.slot.value,status);
                });
            }
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
        // Route MIDI stays responsive during foreground rendering. Scale learn
        // owns the FIFO exclusively while armed; offsets never edit its pattern.
        if !*MIDI_LEARN.borrow_ref(cs) {
            let midi=unsafe {pac::Peripherals::steal()}.MIDI_INPUT;
            for _ in 0..4 {let word=midi.midi_read().read().msg().bits();if word==0 {break;}quant.midi_word(word);}
        }
        // Both half-batches use one MIDI offset snapshot, just like CV input.
        if !quant.running || quant.phase==0 {quant.apply_midi();}
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
        // A member fault stops its whole claimed route before the output commit.
        { let mut owners=OWNERS.borrow_ref_mut(cs);
          for route in 0..4 {if owners.held(Owner::Quant(route as u8)) {
            if let Some(n)=(0..4).find(|n|quant.groups.outputs[route]&(1<<n)!=0 && !quant.lanes[*n].active) {
                let reason=quant.lanes[n].status;quant.stop_group(&tuner,route,reason,&mut owners);
            }
          }}
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

    fn copy_words(&mut self, source: usize, first: usize, end: usize) {
        let src = source as *const u32;
        let dst = self.base.cast::<u32>();
        for offset in first..end {
            unsafe { dst.add(offset).write_volatile(src.add(offset).read_volatile()) };
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
        // Circular viewport edge; coordinates are computed at build time.
        for index in 0..static_guides::BORDER.len()-1 {
            let a = static_guides::BORDER.point(index);
            let b = static_guides::BORDER.point(index+1);
            self.line(a.0 as i32, a.1 as i32, b.0 as i32, b.1 as i32, SUBTLE);
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
                let (x0,y0) = static_guides::BORDER.point(segment);
                let (x1,y1) = static_guides::BORDER.point(segment+1);
                self.line(x0 as i32, y0 as i32, x1 as i32, y1 as i32, 0x29);
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
                if segment==2048 {self.line(484,184,484,516,0x29);}
                let angle = -core::f32::consts::FRAC_PI_2
                    + (segment - 2048) as f32 * core::f32::consts::TAU / 12.0;
                self.thick_line(
                    ui_scene::SPIRAL_CENTER.0,
                    ui_scene::SPIRAL_CENTER.1,
                    ui_scene::SPIRAL_CENTER.0 + (ui_scene::SPIRAL_SPOKE_RADIUS * angle.cos()).round() as i32,
                    ui_scene::SPIRAL_CENTER.1 + (ui_scene::SPIRAL_SPOKE_RADIUS * angle.sin()).round() as i32,
                    0x29,
                );
            } else {
                let point = |step: usize| static_guides::SPIRAL.point(step);
                let (x0, y0) = point(segment - 2060);
                let (x1, y1) = point(segment - 2060 + 1);
                self.thick_line(x0 as i32, y0 as i32, x1 as i32, y1 as i32, 0x59);
            }
        }
    }

    fn draw_static_tuner(&mut self) {
        const GUIDE: u8 = (5 << 4) | 9;
        const SUBTLE: u8 = (2 << 4) | 9;
        let (cx, cy) = ui_scene::SPIRAL_CENTER;
        self.draw_border();
        self.line(484,184,484,516,0x29);
        for pitch_class in 0..12 {
            let angle =
                -core::f32::consts::FRAC_PI_2 + pitch_class as f32 * core::f32::consts::TAU / 12.0;
            self.thick_line(
                cx,
                cy,
                cx + (ui_scene::SPIRAL_SPOKE_RADIUS * angle.cos()).round() as i32,
                cy + (ui_scene::SPIRAL_SPOKE_RADIUS * angle.sin()).round() as i32,
                SUBTLE,
            );
        }

        // Same coordinates as segmented rendering, without startup soft-float trig.
        for index in 0..static_guides::SPIRAL.len()-1 {
            let a = static_guides::SPIRAL.point(index);
            let b = static_guides::SPIRAL.point(index+1);
            self.thick_line(a.0 as i32, a.1 as i32, b.0 as i32, b.1 as i32, GUIDE);
        }
    }

    fn draw_scale_keyboard(&mut self, single:bool) {
        self.draw_border();
        // Each octave has independent tags; black keys cover natural-key joins.
        for octave in 0..if single {1}else{2} {
            for black_pass in [false,true] {
                for note in 0..12 {
                    let (mut key,black)=ui_canvas::octave_key(note,octave).unwrap();
                    if single {key.y+=ui_canvas::SINGLE_KEYBOARD_Y_OFFSET;}
                    if black!=black_pass {continue;}
                    ui_canvas::rounded_rectangle(key,4,if black {0x69}else{0x49},
                        0xE0+octave as u8*16+note as u8,
                        |p,c|self.put_panel_pixel(p.x,p.y,c));
                }
            }
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
    #[inline(never)]
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

#[inline(never)]
fn write_text(display: &mut TextWriter<'_>, column: u8, row: u8, text: &str) {
    ui_text::ux_text(
        column as usize,
        row as usize,
        text,
        ui_text::DEFAULT,
        |address, cell| {
            display.cell(address, cell);
        },
    );
}

#[inline(never)]
fn write_centered(display: &mut TextWriter<'_>, row: u8, text: &str, width: u8) {
    let width = ui_controls::center_width(row,width as usize);
    ui_text::ux_field(
        (30 - width) / 2,
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

#[inline(never)]
fn write_static_text(text: &mut TextWriter<'_>, scene: ui_scene::Scene, preparing: bool, _changed: bool) {
    if scene == ui_scene::Scene::Spiral {
        for (column, row, label) in [(11,5,"C"),(17,6,"C#"),(20,8,"D"),
            (21,11,"D#"),(20,14,"E"),(17,16,"F"),(11,17,"F#"),
            (6,16,"G"),(2,14,"G#"),(0,11,"A"),(2,8,"A#"),(6,6,"B")] {
            write_text(text, column, row, label);
        }
    } else {
        write_text(text, 4, 4, "-50");
        write_text(text, 14, 4, "0");
        write_text(text, 23, 4, "+50");
    }
    if preparing { write_centered(text, 16, "PREPARING VIEW", 24); }
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
    // All controls are displayed on the page; retain stable option indices.
    entries: [Option<MenuEntrySnapshot>; 16],
}

impl MenuSnapshot {
    #[inline(never)]
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
            Page::QuantSetups => "ALL ROUTES",
            Page::RouteMidi => "ROUTE MIDI",
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
                    (Page::Tuner, 1) => "view",
                    (Page::QuantNotes, 0) => "tools oct",
                    (Page::Play, 5) => "mode",
                    (Page::Play, 12) => "saved",
                    (Page::Calibrate, 2) => "0v note",
                    (Page::Play, 2) => "0v note",
                    (Page::Play, 3) => "profile",
                    (Page::Profiles, 1) => "name pos",
                    (Page::Profiles, 2) => "letter",
                    (Page::Play, 0) => "route",
                    (Page::Quantizer,0)|(Page::Play,13) => "output",
                    (Page::Quantizer, 1) => "preset",
                    (Page::Quantizer, 2) => "key",
                    (Page::Quantizer,8)|(Page::QuantNotes,10)=>"view",
                    (Page::Play, 15) => "map",
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
                } else if page==Page::RouteMidi && index==1 {
                    let mut value=OptionString::new();if opts.route_midi.channel.value==0 {value.push_str("OFF").ok();}else{write!(value,"{}",opts.route_midi.channel.value).ok();}value
                } else if page==Page::RouteMidi && index==2 {
                    let mut value=OptionString::new();pitch_units::write_note(&mut value,opts.route_midi.zero.value as i32).ok();value
                } else if matches!((page,index),(Page::Quantizer,3)|(Page::Play,11)) {
                    let mut value=OptionString::new();
                    write!(value,"{:+} st",if page==Page::Play {opts.play.transpose.value}else{opts.quantizer.transpose.value}).ok();
                    value
                } else if matches!((page,index),(Page::Quantizer,8)|(Page::QuantNotes,10)) {
                    let mut value=OptionString::new();
                    let (view,span)=if page==Page::QuantNotes {(opts.quant_notes.view.value,opts.quant_notes.octaves.value)}else{(opts.quantizer.view_octave.value,opts.quantizer.octaves.value)};
                    if span==1 {write!(value,"1").ok();}else{write!(value,"{}-{}",view+1,view+2).ok();}
                    value
                } else if page == Page::QuantNotes && index == 0 {
                    let mut value=OptionString::new();write!(value,"{}",opts.quant_notes.octave.value+1).ok();value
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
fn surface(page: Page) -> ui_controls::Surface {
    use ui_controls::Surface as S;
    match page {
        Page::Tuner => S::Tuner, Page::Calibrate => S::Calibration,
        Page::Profiles => S::Profiles, Page::Verify => S::Check,
        Page::Quantizer => S::Scales, Page::QuantNotes => S::Notes,
        Page::QuantSetups => S::Setups, Page::Play => S::Routes,
        Page::Settings => S::Settings, Page::Help => S::Help, Page::RouteMidi=>S::Midi,
    }
}
#[inline(never)]
fn publish_controls(text: &mut TextWriter<'_>, menu: &MenuSnapshot, cal: &calibration_live::Live) {
    let page = with_app(|app| app.ui.opts.tracker.page.value);
    ui_text::ux_field(11,1,8,"INTONO",ui_text::Style {color:0xB9,bold:true},
        ui_text::Align::Center,|a,c|text.cell(a,c));
    for (column, width, label, active) in [(2,9,"TUNER",matches!(page,Page::Tuner)),
        (11,9,"CAL",matches!(page,Page::Calibrate|Page::Profiles|Page::Verify)),
        (20,9,"SCALES",matches!(page,Page::Quantizer|Page::QuantNotes)),
        (29,9,"ROUTES",matches!(page,Page::Play|Page::QuantSetups|Page::RouteMidi))] {
        let mut tab=String::<12>::new();
        tab.push_str(label).ok();
        ui_text::field(column,3,width,&tab,ui_text::Style {
            color: if active { 0xF9 } else { 0x69 }, bold: active,
        },ui_text::Align::Center,|a,c|text.cell(a,c));
    }
    if matches!(page,Page::Settings|Page::Help|Page::Profiles|Page::Verify|Page::QuantNotes|Page::QuantSetups) {
        write_centered(text, 4, menu.page_label, 18);
    }
    for (column,label,active) in [(8,"OPTIONS",page==Page::Settings),(17,"HELP",page==Page::Help)] {
        ui_text::ux_field(column,20,label.len(),label,ui_text::Style {
            color: if active {0xF9}else{0x69}, bold: active && menu.page_bold,
        },ui_text::Align::Center,|a,c|text.cell(a,c));
    }
    let selected_output=with_app(|app|app.quant_selected as usize);
    let output_active=critical_section::with(|cs|
        MULTI_QUANT.borrow_ref(cs).lanes[selected_output].active);
    let claims=critical_section::with(|cs|*OWNERS.borrow_ref(cs));
    let (selected,cal_input,cal_output,route_input)=with_app(|app|(
        app.ui.opts.tracker.selected,app.ui.opts.calibrate.input.value,
        app.ui.opts.calibrate.output.value,app.ui.opts.play.input.value));
    let cal_inputs=claims.free_mask(Owner::Calibration,false);
    let cal_outputs=claims.free_mask(Owner::Calibration,true);
    let (route,groups)=with_app(|app|(app.route_selected,app.groups));
    let route_active=claims.held(Owner::Quant(route));
    let route_inputs=claims.free_mask(Owner::Quant(route),false);
    let route_outputs=claims.free_mask(Owner::Quant(route),true);
    let jack_choice=match (page,selected) {
        (Page::Calibrate,Some(0))=>Some((Owner::Calibration,cal_inputs,cal_input)),
        (Page::Calibrate,Some(1))=>Some((Owner::Calibration,cal_outputs,cal_output)),
        (Page::Play,Some(1))=>Some((Owner::Quant(route),route_inputs,route_input)),
        (Page::Play,Some(13))=>Some((Owner::Quant(route),route_outputs,selected_output as u8)),
        _=>None,
    };
    let cal_free=cal_inputs&(1<<cal_input)!=0 && cal_outputs&(1<<cal_output)!=0;
    let quant_locked = |index| (page==Page::Play &&
        ((route_active && matches!(index,1|14)) || ((output_active || groups.owner(selected_output as u8)!=Some(route)) && matches!(index,2|3|4|5|7|9|10|11|15)))) || output_active &&
        (
         (page==Page::Quantizer && matches!(index,1|2|3|4|9)) ||
         (page==Page::QuantNotes && matches!(index,2|3|4|5|7|9)));
    let scale_locked=with_app(|app|app.ui.opts.tracker.selected.is_some_and(quant_locked));
    let cal_locked=cal.active() && page==Page::Calibrate &&
        with_app(|app|matches!(app.ui.opts.tracker.selected,Some(0|1|3)));
    write_centered(text, 21, if cal_locked || scale_locked { "LOCKED" } else if menu.page_editing { "PAGE EDIT" }
        else if menu.entries.iter().flatten().any(|entry|entry.editing) { "EDIT" }
        else if menu.page_bold { "PAGE" } else { "NAV" }, 10);
    for (index, entry) in menu.entries.iter().enumerate() {
        let Some(entry) = entry else { continue };
        let Some(field) = ui_controls::field(surface(page),index) else { continue };
        let label = match (page,index) {
            (Page::Calibrate,5) => if cal.active() { "STOP" } else if cal.can_continue_automatic() { "RESUME" } else { "SCAN" }, (Page::Calibrate,8) => "PROFILES",
            (Page::Verify,0) => "CHECK",
            (Page::Profiles,1) => "CURSOR",
            (Page::Play,6) => if route_active {"STOP"} else {"START"},
            (Page::Play,7) => "LOAD SCALE",
            (Page::Play,8) => "ALL ROUTES",
            (Page::QuantSetups,3) => "MIDI ROUTE",
            (Page::RouteMidi,2) => "ZERO",
            (Page::Play,14) => if groups.owner(selected_output as u8)==Some(route) {"REMOVE OUT"}else{"ADD OUT"},
            (Page::Play,4) => if with_app(|app|app.quant_channels[selected_output].correction)==0 {"CLEAR PROFILE"} else {"APPLY PROFILE"}, (Page::Quantizer,5) => "SCALE TOOLS",
            (Page::Quantizer,6) => "SETUPS",
            (Page::QuantNotes,3) => "CLEAR OCT",
            (Page::QuantNotes,4) => "FILL OCT",
            (Page::QuantNotes,5) => if critical_section::with(|cs|*MIDI_LEARN.borrow_ref(cs)) {"STOP MIDI"}else{"LEARN BASE"},
            _ => entry.label,
        };
        let assigned=match (page,index) {
            (Page::Calibrate,0)=>cal_inputs&(1<<cal_input)==0,
            (Page::Calibrate,1)=>cal_outputs&(1<<cal_output)==0,
            (Page::Play,1)=>route_inputs&(1<<route_input)==0,
            (Page::Play,13|14)=>route_outputs&(1<<selected_output)==0,
            _=>false,
        };
        let locked=(cal.active() && page==Page::Calibrate && matches!(index,0|1|3)) || quant_locked(index)
            || assigned || (page==Page::Calibrate && index==5 && !cal.active() && !cal_free);
        let style = ui_text::Style { color: if locked {0x69} else if entry.selected { 0xF9 } else { 0xB9 }, bold:entry.selected };
        let mut label_text = String::<32>::new();
        // Focus outline and EDIT footer already distinguish selection/editing.
        // Avoid an extra prefix that shifts or wraps compact selector labels.
        for c in label.chars() { label_text.push(c.to_ascii_uppercase()).ok(); }
        if !field.action {
            if ui_text::inline_field(field.column as usize,field.row as usize,field.width as usize,
                &label_text,&entry.value,style,|a,c|text.cell(a,c)) {continue;}
        }
        ui_text::ux_field(field.column as usize, field.row as usize, field.width as usize,
            &label_text,style,if field.action {ui_text::Align::Center}else{ui_text::Align::Left},|a,c|text.cell(a,c));
        if !field.action {
            ui_text::ux_field(field.column as usize, field.row as usize+1, field.width as usize,
                &entry.value,style,ui_text::Align::Left,|a,c|text.cell(a,c));
        }
    }
    if let Some((owner,free,current))=jack_choice {
        ui_text::ux_field(3,19,27,"",ui_text::DEFAULT,ui_text::Align::Left,|a,c|text.cell(a,c));
        ui_text::ux_text(4,19,"FREE",ui_text::DEFAULT,|a,c|text.cell(a,c));
        ui_text::ux_text(8,19," / ASSIGNED",ui_text::Style {color:0x49,bold:false},|a,c|text.cell(a,c));
        for jack in 0..4 {
            let value=["0","1","2","3"][jack as usize];
            let available=free&(1<<jack)!=0;
            ui_text::ux_field(21+jack as usize*2,19,2,value,ui_text::Style {
                color:if !available {0x49}else if jack==current {0xF9}else{0xB9},
                bold:available && jack==current,
            },ui_text::Align::Center,|a,c|text.cell(a,c));
        }
        if claims.held(owner) && selected!=Some(13) {
            write_centered(text,19,"ASSIGNED",28);
        }
        if free==0 || (claims.held(owner) && selected!=Some(13)) {
            write_centered(text,21,"ASSIGNED",12);
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
    let (cx, cy) = ui_scene::SPIRAL_CENTER;
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
        let pitch_class = midi_note.rem_euclid(12) as usize;
        let octave = midi_note.div_euclid(12) - 1;
        write!(note_line, "{}{}", NOTE_NAMES[pitch_class], octave).ok();
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

    }

    // ARC reserves the right column for readouts; all markers and the retained
    // spiral share the same geometry. LINEAR keeps its four existing lanes.
    let linear = display_mode == DisplayMode::Linear;
    if !reservations.tuner_available(input) {
        note_line.clear();
        cents_line.clear();
        frequency_line.clear();
        voltage_line.clear();
    }
    if !linear {
        write_text(text,23,6,"PITCH");
        ui_text::ux_field(23,7,7,&note_line,ui_text::Style {color:0xF9,bold:true},
            ui_text::Align::Left,|a,c|text.cell(a,c));
        if measurement.valid && reservations.tuner_available(input) {
            cents_line.clear();
            let midi=pitch_math::semitones(measurement.frequency_hz,reference_hz);
            let cents=100.0*(midi-midi.round());
            write!(cents_line,"{:+.1}c",cents).ok();
            ui_text::ux_field(23,8,7,&cents_line,ui_text::Style {
                color:if cents.abs()<=2.0 {0xF5}else{0xB9},bold:cents.abs()<=2.0,
            },ui_text::Align::Left,|a,c|text.cell(a,c));
            frequency_line.clear();write!(frequency_line,"{:.*}Hz",if measurement.frequency_hz>=10000.0 {1}else{2},measurement.frequency_hz).ok();
            write_text(text,23,11,&frequency_line);
            voltage_line.clear();write!(voltage_line,"{:.2}Vrms",measurement.vrms).ok();
            write_text(text,23,14,&voltage_line);
            voltage_line.clear();write!(voltage_line,"{:.2}Vpp",measurement.vpp).ok();
            write_text(text,23,15,&voltage_line);
        }
        else if reservations.tuner_available(input) {write_text(text,23,8,"NO SIGNAL");}
        write_text(text,23,10,"FREQUENCY");
        write_text(text,23,13,"LEVEL");
    }
    let mut markers = [marker, None, None, None];
    let mut slot = 1;
    for channel in 0..4usize {
        if !reservations.tuner_available(channel as u8) {
            if linear {
                for row in [[6, 9, 12, 15][channel], [8, 11, 14, 17][channel]] {
                    ui_text::ux_field(
                        1,
                        row,
                        28,
                        "",
                        ui_text::DEFAULT,
                        ui_text::Align::Center,
                        |address, cell| text.cell(address, cell),
                    );
                }
            } else {
                ui_text::ux_field(
                    8 + channel * 4,
                    4,
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
            let row = [6, 9, 12, 15][channel];
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
            ui_text::ux_field(
                1,
                row,
                28,
                &label,
                style,
                ui_text::Align::Center,
                |address, cell| text.cell(address, cell),
            );
            let mut volts: String<48> = String::new();
            write!(volts, "{:5.3} Vrms  {:5.3} Vpp", value.vrms, value.vpp).ok();
            ui_text::ux_field(
                1,
                [8, 11, 14, 17][channel],
                28,
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
            ui_text::ux_field(
                8 + channel * 4,
                4,
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
    publish_markers(display, Markers(markers), false, menu_active);
}

const CHANNEL_HUES: [u8; 4] = [1, 5, 9, 13];
mod pitch_units;

/// Six notes per row; brackets identify included notes without relying on color.
fn publish_note_grid(text: &mut TextWriter<'_>, mask: u16, row: usize,
    quarter: bool, selected: Option<usize>) {
    for note in 0..12 {
        let included=mask&(1<<note)!=0;
        let focused=selected==Some(note);
        let mut label=String::<8>::new();
        if focused { label.push('>').ok(); }
        if included { label.push('[').ok(); }
        label.push_str(NOTE_NAMES[note]).ok();
        if quarter { label.push('+').ok(); }
        if included {label.push(']').ok();}
        ui_text::ux_field(3+(note%6)*4,row+note/6,4,&label,
            ui_text::Style {color:if focused {0xF5} else if included {0xF9} else {0x49},bold:included||focused},
            ui_text::Align::Center,|a,c|text.cell(a,c));
    }
}

#[inline(never)]
fn publish_piano_notes(text: &mut TextWriter<'_>,mask:u16,octave:usize,single:bool,focused:Option<usize>) {
    for note in 0..12 {
        let selected=mask&(1<<note)!=0;
        let (column,mut row,width)=ui_canvas::octave_label(note,octave).unwrap();
        if single {row+=ui_canvas::SINGLE_KEYBOARD_Y_OFFSET as usize/32;}
        let mut label=String::<6>::new();
        label.push_str(NOTE_NAMES[note]).ok();
        let style=ui_text::Style {color:if focused==Some(note) {0xF5} else if selected {0x19}else{0xD9},
            bold:selected||focused==Some(note)};
        ui_text::field(column,row,width,&label,style,ui_text::Align::Center,|a,c|text.cell(a,c));
    }
}

fn scale_label(id:u8) -> &'static str {
    use strum::IntoEnumIterator;
    options::ScalePreset::iter().nth(id as usize).map(Into::into).unwrap_or("INVALID SCALE")
}
fn write_profile_source(line: &mut impl core::fmt::Write, source:u8) {
    match source {0=>{write!(line,"NOMINAL").ok();},1=>{write!(line,"RAM").ok();},
        n=>{write!(line,"SLOT {}",n-1).ok();}}
}

#[inline(never)]
fn publish_quantizer(display: &pac::TUNER_DISPLAY, text: &mut TextWriter<'_>, menu: bool, preview: &mut ui_scale::Cache) -> u32 {
    let mut keyboard_mask=0;
    let (page,output,c) = with_app(|app|(app.ui.opts.tracker.page.value,app.quant_selected,
        app.quant_channels[app.quant_selected as usize]));
    let mut line = String::<64>::new();
    if page == Page::QuantNotes {
        let masks = critical_section::with(|cs|*QUANT_NOTES.borrow_ref(cs));
        let (selected_octave, selected_note, key_focused)=with_app(|app|(
            app.ui.opts.quant_notes.octave.value,app.ui.opts.quant_notes.note.value as usize,
            app.ui.opts.tracker.selected==Some(ui_keyboard::KEYBOARD)));
        let base=critical_section::with(|cs|*MIDI_BASE.borrow_ref(cs));
        write!(line,"MIDI BASE: C{}",base as i32/12-1).ok();
        write_centered(text,6,&line,28);
        write_centered(text,7,"TURN: KEY / CLICK: TOGGLE",28);
        let view=with_app(|app|app.ui.opts.quant_notes.view.value as usize);
        for row in 0..(c.octaves as usize).min(2) {
            let octave=view+row;
            line.clear();write!(line,"OCTAVE {} / {} NOTES",octave+1,masks[octave].count_ones()).ok();
            write_centered(text,8+row as u8*4+if c.octaves==1 {2}else{0},&line,28);
            publish_piano_notes(text,masks[octave],row,c.octaves==1,
                if key_focused && selected_octave as usize==octave {Some(selected_note)}else{None});
            keyboard_mask|=(masks[octave] as u32)<<(row*12);
        }
        let slot=with_app(|app|app.ui.opts.quant_notes.slot.value);
        let (status_slot,status) = critical_section::with(|cs|*NOTE_STATUS.borrow_ref(cs));
        let status=if slot == status_slot {status}else{"SELECTED SCALE SLOT"};
        write_centered(text,19,status,26);
    } else if page == Page::RouteMidi {
        let route=with_app(|app|app.midi_selected as usize);
        let offset=critical_section::with(|cs|MULTI_QUANT.borrow_ref(cs).shifts[route]);
        write!(line,"TRANSPOSE: {:+} st",offset).ok();write_centered(text,10,&line,28);
        write_centered(text,12,"NOTE ON SETS TRANSPOSE",28);
        let hold=with_app(|app|app.midi[route].hold);
        write_centered(text,13,if hold {"RELEASE HOLDS LAST NOTE"}else{"RELEASE RETURNS TO ZERO"},28);
        write_centered(text,15,"SAVED WITH ROUTE SETUP",28);
        write_centered(text,18,"SCALE LEARN PAUSES MIDI",26);
    } else if page == Page::QuantSetups {
        let slot=with_app(|app|app.ui.opts.quant_setups.slot.value);
        let (status_slot,status) = critical_section::with(|cs|*SETUP_STATUS.borrow_ref(cs));
        let status=if slot == status_slot {status}else{"SELECTED SETUP SLOT"};
        let (channels,groups)=with_app(|app|(app.quant_channels,app.groups));
        for (n,c) in channels.iter().enumerate() {
            let row=7+n*2;
            line.clear();
            if let Some(route)=groups.owner(n as u8) {
                let active=critical_section::with(|cs|MULTI_QUANT.borrow_ref(cs).lanes[n].active);
                write!(line,"R{} IN{} > OUT{} {}",route,groups.inputs[route as usize],n,if active {"RUN"}else{"OFF"}).ok();
            } else {write!(line,"OUT{} FREE",n).ok();}
            write_centered(text,row as u8,&line,30);line.clear();
            write_profile_source(&mut line,c.correction);
            line.push_str(" / ").ok();
            if !c.quantize {line.push_str("NO SCALE").ok();}
            else {
                if c.scale_slot!=0 {write!(line,"S{}",c.scale_slot).ok();}else{line.push_str(scale_label(c.scale)).ok();}
                write!(line," {} {:+}",NOTE_NAMES[c.root as usize],c.transpose).ok();
            }
            write_centered(text,(row+1) as u8,&line,30);
        }
        // All four route groups remain visible, including groups with no outputs.
        line.clear();for route in 0..4 {write!(line,"{}:{} ",route,groups.outputs[route].count_ones()).ok();}
        write_centered(text,15,&line,28);
        write_centered(text,18,status,26);
        write_centered(text,19,"LOAD LEAVES OUTPUTS OFF",26);
    } else if page == Page::Quantizer {
        let (masks,quartertones,count)=preview.get_span(c.scale,c.masks,c.octaves);
        write!(line,"{} NOTES / {} OCTAVE{}",count,c.octaves,if c.octaves>1 {"S"}else{""}).ok();
        write_centered(text,7,&line,28);line.clear();
        let (key_focused,focused_octave,focused_note,view)=with_app(|app|(
            app.ui.opts.tracker.selected==Some(ui_keyboard::KEYBOARD),
            app.ui.opts.quant_notes.octave.value as usize,app.ui.opts.quant_notes.note.value as usize,
            app.ui.opts.quantizer.view_octave.value as usize));
        if !quartertones {
            for row in 0..(c.octaves as usize).min(2) {
                let octave=view+row;
                line.clear();let count=masks[octave].count_ones();
                write!(line,"OCTAVE {} / {} NOTE{}",octave+1,count,if count==1 {""}else{"S"}).ok();
                write_centered(text,8+row as u8*4+if c.octaves==1 {2}else{0},&line,28);
                publish_piano_notes(text,masks[octave],row,c.octaves==1,
                    if key_focused && focused_octave==octave {Some(focused_note)}else{None});
                keyboard_mask|=(masks[octave] as u32)<<(row*12);
            }
        } else {
            publish_note_grid(text,masks[0],9,false,None);
            write_centered(text,11,"+ = 50 CENTS ABOVE NOTE",28);
            publish_note_grid(text,0xfff,13,true,None);
        }
        let slot=with_app(|app|app.ui.opts.quantizer.slot.value);
        let (status_slot,status)=critical_section::with(|cs|*NOTE_STATUS.borrow_ref(cs));
        write_centered(text,19,if slot==status_slot {status}else{"SELECT SLOT / LOAD OR SAVE"},28);
    } else {
        let (status, input_uv, output_uv, active, pitch, running, bound, name) = critical_section::with(|cs| {
            let q=MULTI_QUANT.borrow_ref(cs); let lane=&q.lanes[output as usize];
            let mut name=String::<32>::new();
            if q.bound[output as usize]==c.correction && c.correction!=0 {
                if let Some(s)=lane.profile_name() {name.push_str(s).ok();}
            }
            (lane.status,lane.input_uv,lane.output_uv,lane.active,lane.pitch,
                core::array::from_fn::<_,4,_>(|n|q.lanes[n].active),q.bound[output as usize],name)
        });
        let (route,groups)=with_app(|app|(app.route_selected,app.groups));
        write_centered(text,4,"QUANTIZER",26);
        write!(line,"IN {} -> OUT",groups.inputs[route as usize]).ok();
        for n in 0..4 {if groups.outputs[route as usize]&(1<<n)!=0 {write!(line," {}",n).ok();}}
        if groups.outputs[route as usize]==0 {line.push_str(" NONE").ok();}
        write_centered(text,14,&line,30);line.clear();

        if c.correction==0 {line.push_str("NOMINAL CV / NO PROFILE").ok();}
        else if c.correction!=bound {line.push_str("PROFILE SELECTED - APPLY FIRST").ok();}
        else {
            line.push_str("APPLIED: ").ok();
            line.push_str(if name.is_empty() {"UNNAMED PROFILE"} else {name.as_str()}).ok();
        }
        write_centered(text,11,&line,30);line.clear();
        if active { pitch_units::write_pitch(&mut line,pitch).ok(); }
        else {line.push_str("STOPPED").ok();}
        ui_text::ux_field(3,12,24,&line,ui_text::Style {
            color:if active {0xF9}else{0x89},bold:active,
        },ui_text::Align::Center,|a,c|text.cell(a,c));line.clear();
        if active {
            for (column,label,uv) in [(6,"IN",input_uv),(20,"OUT",output_uv)] {
                line.clear();write!(line,"{} {:+.3}V",label,uv as f32/1e6).ok();
                ui_text::field(column,13,14,&line,ui_text::DEFAULT,
                    ui_text::Align::Center,|a,c|text.cell(a,c));
            }
        }
        line.clear();
        if let Some(status)=ui_route::status_message(status) {write_centered(text,15,status,30);}
        for n in 0..4 {
            line.clear();write!(line,"{}:{}",n,if running[n] {"RUN"}else{"OFF"}).ok();
            ui_text::field(6+n*7,19,7,&line,ui_text::Style {
                color:if running[n] {0xC0|CHANNEL_HUES[n]}else{0x69},
                bold:n==output as usize,
            },ui_text::Align::Center,|a,c|text.cell(a,c));
        }
    }
    publish_markers(display,Markers([None;4]),false,menu);
    keyboard_mask
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

#[inline(never)]
fn publish_calibration(
    display: &pac::TUNER_DISPLAY, text: &mut TextWriter<'_>,
    cal: &calibration_live::Live, controls: RuntimeControls, value: ChannelMeasurement,
    menu_active: bool, plot_ready: bool, _profile_slot: u8, name_position: u8, profile_name: &str, profile_status: &str,
) {
    let mut line=String::<64>::new();
    let profile=calibration_plot_profile(cal);
    if controls.mode==runtime::OperatingMode::Calibrator {
        write_centered(text,4,profile.map_or("CALIBRATION",|p|p.name()),26);
    }
    if controls.mode==runtime::OperatingMode::Profiles {
        write_centered(text,7,"SAVE AS",24);
        // Fixed native-cell name origin keeps the cursor over the character,
        // including the trailing spaces used to extend a short name.
        ui_text::field(8,8,24,profile_name,ui_text::DEFAULT,ui_text::Align::Left,|a,c|text.cell(a,c));
        ui_text::field(8+name_position.saturating_sub(1).min(23) as usize,9,1,"^",
            ui_text::Style {color:0xF9,bold:true},ui_text::Align::Left,|a,c|text.cell(a,c));
        if let Some(p)=cal.profile.as_ref() {
            write!(line,"CURRENT: {}",p.name()).ok();
            write_centered(text,12,&line,28); line.clear();
            write!(line,"{} POINTS / {}",p.points().len(),cal.profile_quality.grade.label()).ok();
            write_centered(text,13,&line,28); line.clear();
        } else { write_centered(text,12,"NO ACCEPTED PROFILE",28); }
        write_centered(text,18,profile_status,26);
    } else if controls.mode==runtime::OperatingMode::Verify {
        write_centered(text,5,profile.map_or("NO PROFILE",|p|p.name()),26);
        if let Some(p)=profile {
            write!(line,"{} / {} POINTS",if cal.pending_profile.is_some(){"CANDIDATE"}else{"CURRENT"},p.points().len()).ok();
            write_centered(text,6,&line,28); line.clear();
            if let (Some(low),Some(high))=(p.points().first(),p.points().last()) {
                pitch_units::write_note(&mut line,(low.millicents+50_000)/100_000).ok();
                line.push_str(" .. ").ok();
                pitch_units::write_note(&mut line,(high.millicents+50_000)/100_000).ok();
                write_centered(text,7,&line,28); line.clear();
            }
            if let Some(reference)=p.zero_pitch() {
                line.push_str("0V: ").ok();
                pitch_units::write_note(&mut line,(reference+50_000)/100_000).ok();
                write_centered(text,8,&line,28); line.clear();
            }
        }
        if let Some(scan)=cal.scan.as_ref() {
            write!(line,"CHECK {}/{}{}",scan.tested,scan.total,if scan.complete {" COMPLETE"}else{""}).ok();
            write_centered(text,10,&line,28); line.clear();
            if scan.tested>0 {
                write!(line,"WORST: {:+.2}c",scan.worst_error).ok();
                write_centered(text,11,&line,28); line.clear();
                write!(line,"SPREAD: {:.2}c",scan.max_spread).ok();
                write_centered(text,12,&line,28); line.clear();
            }
            if scan.complete {
                write!(line,"{} / {} MISSING",scan.quality().grade.label(),scan.missing).ok();
                write_centered(text,13,&line,28); line.clear();
            }
        } else { write_centered(text,10,if profile.is_some(){"READY TO CHECK"}else{"LOAD OR SCAN A PROFILE"},28); }
        write_centered(text,14,cal.status,28);
    } else {
        let reference = profile.and_then(|p|p.zero_pitch());
        write_text(text,23,8,"0V NOTE");
        if let Some(pitch)=reference {
            pitch_units::write_note(&mut line,(pitch+50_000)/100_000).ok();
        } else { line.push_str("--").ok(); }
        write_text(text,23,9,&line); line.clear();
        if let Some(profile)=profile {
            let quality=if cal.pending_profile.is_some(){cal.pending_quality}else{cal.profile_quality};
            write_text(text,23,10,quality.grade.label());
            write_text(text,23,11,"WORST");
            write!(line,"{:.1}c",quality.worst_cents()).ok();
            write_text(text,23,12,&line);line.clear();
            write_text(text,23,13,"SPREAD");
            write!(line,"{:.1}c",quality.stability_cents()).ok();
            write_text(text,23,14,&line);line.clear();
        } else if value.valid {
            write!(line,"{:.1}Hz",value.frequency_hz).ok();
            write_text(text,23,11,&line);line.clear();
        }
        let (low,high)=calibration_plot_range(cal,profile);
        let anchor=calibration_plot_anchor(cal,profile);
        if controls.calibration_graph==CalibrationGraph::Pitch {
            write_text(text,4,7,"PITCH");
            if let Some((low_mc,high_mc))=ui_canvas::calibration_pitch_bounds(anchor.0,anchor.1,low,high) {
                for (row,pitch) in [(8,high_mc),(11,low_mc+(high_mc-low_mc)/2),(14,low_mc)] {
                    line.clear(); pitch_units::write_note(&mut line,(pitch+50_000)/100_000).ok();
                    ui_text::ux_field(0,row,4,&line,ui_text::DEFAULT,ui_text::Align::Left,|a,c|text.cell(a,c));
                }
            }
        } else {
            write_text(text,4,7,"ERROR c");
            let span=calibration_plot_error_span(cal,profile);
            for (row,amount) in [(8,span),(11,0),(14,-span)] {
                line.clear();
                if amount.abs()>=1_000_000 {write!(line,"{}k",amount/1_000_000).ok();}
                else {write!(line,"{}",amount/1000).ok();}
                ui_text::ux_field(0,row,4,&line,ui_text::DEFAULT,ui_text::Align::Left,|a,c|text.cell(a,c));
            }
        }
        line.clear();
        // Center each label's field on its tick, including the two endpoints.
        // The native 12px text grid places their ink within half a cell.
        let plot=ui_canvas::CALIBRATION_PLOT;
        let width=7;
        for (x,voltage) in [
            (plot.x,low),
            (plot.x+plot.width as i32/2,((low as i64+high as i64)/2) as i32),
            (plot.x+plot.width as i32,high),
        ] {
            let column=((x-120)/12) as usize-width/2;
            line.clear();write!(line,"{:+.1}V",voltage as f32/1e6).ok();
            ui_text::field(column,15,width,&line,ui_text::DEFAULT,ui_text::Align::Center,|a,c|text.cell(a,c));
        }
        line.clear();
        if cal.active() {
            if let Some(scan)=cal.scan.as_ref().filter(|_|cal.verifying) {
                write!(line,"CHECK {}/{}",scan.tested,scan.total).ok();
            } else { write!(line,"SCAN {:+.2}V / {} PTS",cal.millivolts as f32/1000.0,cal.point).ok(); }
        } else if let Some(profile)=profile { write!(line,"{} POINTS",profile.points().len()).ok(); }
        else { line.push_str(if plot_ready {"READY TO SCAN"}else{"DRAWING GRAPH"}).ok(); }
        write_centered(text,19,&line,24);
        write_centered(text,17,if cal.active() && cal.waiting_for_tone() {"SEARCHING FOR TONE"}else if cal.status=="READY - RUN IN MENU" {"SELECT SCAN TO START"}else if cal.status=="REVIEW - GRID/LOCAL DISAGREE" {"REVIEW - CHECKS DISAGREE"}else{cal.status},28);
    }
    publish_markers(display,Markers([None;4]),false,menu_active);
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
    let (x, y) = spiral_point(ui_scene::SPIRAL_CENTER.0, ui_scene::SPIRAL_CENTER.1, radius, drawn / 12.0);
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

#[inline(never)]
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
    load_route_scale: bool,
    save_setup: bool,
    load_setup: bool,
    save_notes: bool,
    load_notes: bool,
    run_play: bool,
    controls: RuntimeControls,
    save: bool,
    wipe: bool,
    menu_active: bool,
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

#[inline(never)]
fn poll_ui_frame(cal: &calibration_live::Live, scan_controls: Option<RuntimeControls>) -> UiFrame {
    // The output selector also selects its independent configuration. Capture
    // the old editor before loading the new channel. Never automatically arm.
    with_app(|app| {
        if app.ui.opts.tracker.page.value==Page::RouteMidi {
            let old=app.midi_selected as usize;
            let config=midi_transpose::Config {channel:app.ui.opts.route_midi.channel.value,base:app.ui.opts.route_midi.zero.value,hold:app.ui.opts.route_midi.release.value==options::MidiRelease::Hold};
            let reset=app.ui.opts.route_midi.reset.poll();
            critical_section::with(|cs| {let mut q=MULTI_QUANT.borrow_ref_mut(cs);
                if config!=app.midi[old] || reset {q.transpose_route(old,0);q.midi_last[old]=None;}
                app.midi[old]=config;q.midi=app.midi;
            });
            let next=app.ui.opts.route_midi.route.value.min(3);
            if next!=app.midi_selected {app.midi_selected=next;let c=app.midi[next as usize];app.ui.opts.route_midi.channel.value=c.channel;app.ui.opts.route_midi.zero.value=c.base;
                app.ui.opts.route_midi.release.value=if c.hold {options::MidiRelease::Hold}else{options::MidiRelease::Zero};}
        }
        if cal.active() {
            app.ui.opts.calibrate.input.value=cal.input;
            app.ui.opts.calibrate.output.value=cal.output;
            if let Some(controls)=scan_controls {
                app.ui.opts.calibrate.policy.value=controls.calibration_policy;
            }
            if app.ui.opts.tracker.page.value==Page::Calibrate
                && matches!(app.ui.opts.tracker.selected,Some(0|1|3)) {
                app.ui.opts.tracker.modify=false;
            }
        }
        critical_section::with(|cs| {
            use strum::IntoEnumIterator;
            let r = OWNERS.borrow_ref(cs);
            if let Some(focus) = r.focus(app.ui.opts.tuner.input.value, app.tuner_focus) {
                app.ui.opts.tuner.input.value = focus;
                app.tuner_focus = focus;
            }
            let old = app.quant_selected as usize;
            let route_page = app.ui.opts.tracker.page.value == Page::Play;
            let old_route=app.route_selected;
            let route=app.ui.opts.play.output.value.min(3);
            let selected=if route_page {
                if route!=old_route {app.groups.first(route).unwrap_or(app.quant_selected)}
                else {app.ui.opts.play.output_edit.value.min(3)}
            } else {app.ui.opts.quantizer.output.value.min(3)};
            let assign=app.ui.opts.play.assign.poll();
            if route_page && !r.held(Owner::Quant(old_route)) {
                let input=app.ui.opts.play.input.value.min(3);
                if r.free_mask(Owner::Quant(old_route),false)&(1<<input)!=0 {
                    app.groups.inputs[old_route as usize]=input;
                    for n in 0..4 {if app.groups.outputs[old_route as usize]&(1<<n)!=0 {app.quant_channels[n].input=input;}}
                }
                if assign {
                    let previous=app.groups.owner(selected);
                    if previous.is_none_or(|group|!r.held(Owner::Quant(group)))
                        && r.free_mask(Owner::Quant(old_route),true)&(1<<selected)!=0 {
                        app.groups.assign(old_route,selected,previous!=Some(old_route));
                        *SETUP_STATUS.borrow_ref_mut(cs)=(app.ui.opts.quant_setups.slot.value,"EDITED - SAVE SETUP");
                        app.quant_channels[selected as usize].input=input;
                    }
                }
            }
            app.route_selected=route;

            let mut q = MULTI_QUANT.borrow_ref_mut(cs);
            q.groups=app.groups;
            let mut edited = app.quant_channels[old];
            if q.lanes[old].active {
                edited = q.configs[old];
            } else if route_page && app.groups.owner(old as u8)==Some(old_route) {
                edited.input = app.groups.inputs[old_route as usize];
                edited.zero = app.ui.opts.play.zero_note.value;
                edited.quantize = app.ui.opts.play.quantize.value == options::RouteQuantize::Scale;
                edited.correction = app.ui.opts.play.correction.value as u8;
                if edited.scale!=app.ui.opts.play.scale.value as u8 {edited.scale_slot=0;}
                edited.scale=app.ui.opts.play.scale.value as u8;
                edited.root=app.ui.opts.play.key.value as u8;
                edited.transpose=app.ui.opts.play.transpose.value;
                edited.equal=app.ui.opts.play.mapping.value==options::Distribution::Equal;
            } else if !route_page {
                edited =
                    quant_settings(&app.ui.opts.quantizer, *QUANT_NOTES.borrow_ref(cs), edited);
                if app.ui.opts.tracker.page.value==Page::QuantNotes {
                    if edited.octaves!=app.ui.opts.quant_notes.octaves.value {edited.scale_slot=0;}
                    edited.octaves=app.ui.opts.quant_notes.octaves.value;
                }
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
            app.ui.opts.quant_notes.octaves.value=c.octaves;
            app.ui.opts.quant_notes.octave.value=app.ui.opts.quant_notes.octave.value.min(c.octaves-1);
            app.ui.opts.quant_notes.view.value=ui_keyboard::window(app.ui.opts.quant_notes.view.value,c.octaves,None);
            app.ui.opts.quantizer.output.value = selected;
            app.ui.opts.play.output.value = route;
            app.ui.opts.play.output_edit.value=selected;
            show_route_settings(&mut app.ui.opts.play,c);
            app.ui.opts.play.input.value=app.groups.inputs[route as usize];
            *QUANT_NOTES.borrow_ref_mut(cs) = c.masks;
        })
    });
    with_app(|app| {
        let clear = app.ui.opts.quant_notes.clear.poll();
        let fill = app.ui.opts.quant_notes.fill.poll();
        let learn = app.ui.opts.quant_notes.learn.poll();
        let on_notes = app.ui.opts.tracker.page.value == Page::QuantNotes;
        if on_notes {
            app.ui.opts.quantizer.slot.value = app.ui.opts.quant_notes.slot.value;
        } else {
            app.ui.opts.quant_notes.slot.value = app.ui.opts.quantizer.slot.value;
        }
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
                    *MIDI_BASE_REQUEST.borrow_ref_mut(cs) = *armed;
                    *NOTE_STATUS.borrow_ref_mut(cs) = (
                        app.ui.opts.quant_notes.slot.value,
                        if *armed { "PLAY NOTE TO SET BASE" } else { "MIDI LEARN OFF" },
                    );
                }
            }
        });
        if on_notes && (clear || fill) {
            let octave = app.ui.opts.quant_notes.octave.value as usize;
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
            Page::QuantNotes => Some(Page::Quantizer),
            Page::QuantSetups => Some(Page::Play),
            Page::RouteMidi => Some(Page::QuantSetups),
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
        } else if app.ui.opts.quantizer.notes.poll() {
            Some(Page::QuantNotes)
        } else if app.ui.opts.play.setups.poll() || app.ui.opts.quantizer.setups.poll() {
            Some(Page::QuantSetups)
        } else if app.ui.opts.quant_setups.midi.poll() {
            Some(Page::RouteMidi)
        } else if app.ui.opts.quantizer.routes.poll() {
            Some(Page::Play)
        } else if header_back {
            parent
        } else {
            None
        };
        if let Some(page) = destination {
            app.ui.opts.tracker.page.value = page;
            app.ui.opts.tracker.selected = Some(if page==Page::QuantNotes {ui_keyboard::KEYBOARD}else{0});
            if page==Page::RouteMidi {
                app.midi_selected=app.route_selected;
                app.ui.opts.route_midi.route.value=app.route_selected;
                let c=app.midi[app.route_selected as usize];
                app.ui.opts.route_midi.channel.value=c.channel;app.ui.opts.route_midi.zero.value=c.base;
                app.ui.opts.route_midi.release.value=if c.hold {options::MidiRelease::Hold}else{options::MidiRelease::Zero};
            }
            if page==Page::QuantNotes {
                critical_section::with(|cs| {
                    if !MULTI_QUANT.borrow_ref(cs).lanes[app.quant_selected as usize].active
                        && scale::has_piano_keys(app.ui.opts.quantizer.scale.value as u8) {
                        let masks=ui_scale::preview_span(app.ui.opts.quantizer.scale.value as u8,
                            *QUANT_NOTES.borrow_ref(cs),app.ui.opts.quantizer.octaves.value).0;
                        *QUANT_NOTES.borrow_ref_mut(cs)=masks;
                        app.ui.opts.quantizer.scale.value=options::ScalePreset::Custom2;
                    }
                });
                app.ui.opts.quant_notes.view.value=0;
                app.ui.opts.quant_notes.octave.value=0;
                app.ui.opts.quant_notes.note.value=options::ScaleRoot::C;
            }
            app.ui.opts.tracker.modify = false;
            app.ui.external_modify();
        }
        let menu_active = false; // Controls are always visible on their owning page.
        app.ui.set_menu_visible(true);
        UiFrame {
            bind_route: app.ui.opts.play.bind.poll() && app.groups.owner(app.quant_selected)==Some(app.route_selected),
            load_route_scale: app.ui.opts.play.scales.poll() && app.groups.owner(app.quant_selected)==Some(app.route_selected),
            save_setup: app.ui.opts.quant_setups.save.poll(),
            load_setup: app.ui.opts.quant_setups.load.poll(),
            save_notes: app.ui.opts.quant_notes.save.poll() | app.ui.opts.quantizer.save.poll(),
            load_notes: app.ui.opts.quant_notes.load.poll() | app.ui.opts.quantizer.load.poll(),
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
        }
    })
}

/// Saving is deliberately isolated from the real-time loop. `Opts` is cloned
/// only for an explicit save request, never on every 5-ms wakeup.
#[inline(never)]
fn snapshot_options_for_save() -> Opts {
    with_app(|app| app.ui.opts.clone())
}

#[inline(never)]
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
    let mut check = [0u8; quantizer_setup::FULL_LEN + 1];
    if save {
        let (channels,groups,midi) = with_app(|app| (app.quant_channels,app.groups,app.midi));
        let Some(bytes) = quantizer_setup::encode_full(&channels,groups,midi) else {
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
        let Some((channels,groups,midi)) = quantizer_setup::decode_full(bytes) else {
            return "INVALID SAVED SETUP";
        };
        with_app(|app| {
            app.quant_channels = channels;
            app.groups=groups;app.midi=midi;
            app.ui.opts.play.input.value=groups.inputs[app.route_selected as usize];
            let current = channels[app.quant_selected as usize];
            show_quant_settings(&mut app.ui.opts.quantizer, current);
                app.ui.opts.quant_notes.octaves.value=current.octaves;
            show_route_settings(&mut app.ui.opts.play,current);
            critical_section::with(|cs| {
                let mut q=MULTI_QUANT.borrow_ref_mut(cs);q.bound=[0;4];q.groups=groups;q.midi=midi;for route in 0..4 {q.transpose_route(route,0);q.midi_last[route]=None;}
                *QUANT_NOTES.borrow_ref_mut(cs) = current.masks;
                *NOTE_STATUS.borrow_ref_mut(cs) =
                    (app.ui.opts.quant_notes.slot.value, "NOTES FROM SETUP");
            });
        });
        "SETUP LOADED - STOPPED"
    }
}

#[inline(never)]
fn persist_notes(storage: &mut Option<IntonoPersistence>, save: bool, slot: u8) -> &'static str {
    if critical_section::with(|cs| MULTI_QUANT.borrow_ref(cs).running) {
        return "STOP OUTPUT FIRST";
    }
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
        let c = with_app(|app| app.quant_channels[app.quant_selected as usize]);
        let (masks, quartertones, _) = ui_scale::preview_span(c.scale, c.masks, c.octaves);
        if quartertones { return "24 EDO CANNOT SAVE AS NOTES"; }
        let Some(bytes) = note_pattern::encode_span(masks, c.octaves) else {
            return "INVALID NOTES";
        };
        if storage.save_key(key, &bytes).is_err() {
            return "NOTE SAVE FAILED";
        }
        match storage.load_key(key, &mut check) {
            Ok(Some(n)) if n == bytes.len() && check[..n] == bytes => {with_app(|app|app.quant_channels[app.quant_selected as usize].scale_slot=slot);"NOTES SAVED"},
            _ => "NOTE READBACK FAILED",
        }
    } else {
        let bytes = match storage.load_key(key, &mut check) {
            Ok(Some(n)) => &check[..n],
            Ok(None) => return "NO SAVED NOTES",
            Err(_) => return "NOTE LOAD FAILED",
        };
        let Some((masks,octaves)) = note_pattern::decode_span(bytes) else {
            return "INVALID SAVED NOTES";
        };
        critical_section::with(|cs| *QUANT_NOTES.borrow_ref_mut(cs) = masks);
        with_app(|app| {
            let c = &mut app.quant_channels[app.quant_selected as usize];
            c.scale = options::ScalePreset::Custom2 as u8;
            c.masks = masks;
            c.octaves = octaves;
            c.scale_slot=slot;
            app.ui.opts.quantizer.scale.value = options::ScalePreset::Custom2;
            app.ui.opts.quantizer.slot.value = slot;
            app.ui.opts.quant_notes.slot.value = slot;
            show_route_settings(&mut app.ui.opts.play, *c);
            app.ui.external_modify();
            app.ui.opts.quantizer.octaves.value=octaves;app.ui.opts.quant_notes.octaves.value=octaves;app.ui.opts.quant_notes.octave.value=0;app.ui.opts.quantizer.view_octave.value=0;app.ui.opts.quant_notes.view.value=0;});
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

fn bind_route_record(output: usize, source: u8, bytes: &[u8]) -> &'static str {
    let Ok(record) = oscillator_calibration::storage::decode(bytes) else {
        return "INVALID STORED PROFILE";
    };
    install_route_curve(output, source, &record.profile)
}

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
            // Calibration updates voltage-to-pitch origin, not the route key.
            with_app(|app| {
                let c = &mut app.quant_channels[output];
                c.retune(note);
                q.configs[output] = *c;
                if app.quant_selected as usize == output {
                    app.ui.opts.play.zero_note.value = note;
                    show_quant_settings(&mut app.ui.opts.quantizer, *c);
                    app.ui.external_modify();
                }
            });
            "BOUND - NATURAL NOTE SET"
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
    boot_ms: [u32;8],
}

// One-byte, nonblocking boot markers for diagnosing startup without risking
// a stalled USB serial reader freezing the real-time firmware.
fn boot_mark(byte: u8) {
    // Steal only this zero-sized register accessor. Stealing `Peripherals`
    // would mark the whole device taken before startup's `take()` call.
    #[cfg(intono_verbose_diagnostics)]
    {
    let uart = unsafe { pac::UART0::steal() };
    if uart.tx_ready().read().txe().bit() {
        uart.tx_data().write(|w| unsafe { w.data().bits(byte) });
    }
    }
    #[cfg(not(intono_verbose_diagnostics))]
    let _ = byte;
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
    let started = playback_cycles();
    let elapsed = || playback_cycles().wrapping_sub(started) as u32 / (sysclk / 1000);
    let mut boot_ms = [0;8];
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
    background.draw_border();
    // A small retained loading indicator is visible even before text-bank adoption.
    for x in [342,354,366] {
        ui_canvas::rounded_rectangle(ui_canvas::Rect {x,y:400,width:6,height:6},3,
            0x69,0x69,|p,c|background.put_panel_pixel(p.x,p.y,c));
    }
    background.finish();
    let tuner_display = peripherals.TUNER_DISPLAY;
    let mut occupied = ui_text::Occupied::new();
    let mut text = TextWriter { display: &tuner_display, occupied: &mut occupied };
    text.clear(true);
    write_centered(&mut text,8,"INTONO",12);
    write_centered(&mut text,11,"STARTING",20);
    tuner_display.backdrop().write(|w| {
        w.ui_ready().bit(false);
        unsafe {w.ui_surface().bits(15);w.ui_focus().bits(31);} w
    });
    tuner_display.frame().write(|w| w.commit().set_bit());
    video.enable();
    boot_ms[0] = elapsed();
    boot_mark(b'V');
    // Never draw into the startup buffer after scanout is enabled.
    let mut cached = BackgroundCanvas::new(
        PSRAM_FB_BASE + ui_scene::cache_offset(Some(ui_scene::Scene::Spiral)),
        modeline.h_active, modeline.v_active, ROUND_DISPLAY);
    cached.clear();cached.draw_static_tuner();cached.finish();
    boot_ms[1] = elapsed();
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
    boot_ms[2] = elapsed();
    // Cache immutable guides beyond the framebuffer and firmware regions.
    // memory.x bounds firmware below this reservation (enforced by build.rs).
    assert!(ui_scene::CACHE_END <= PSRAM_SZ_BYTES - 4096);
    let words = modeline.h_active as usize * modeline.v_active as usize / 4;
    let circle_base = PSRAM_FB_BASE + ui_scene::cache_offset(None);
    let mut circle = BackgroundCanvas::new(circle_base,
        modeline.h_active, modeline.v_active, ROUND_DISPLAY);
    circle.clear();
    circle.draw_border();
    circle.finish();
    boot_ms[3] = elapsed();
    let mut linear = BackgroundCanvas::new(
        PSRAM_FB_BASE + ui_scene::cache_offset(Some(ui_scene::Scene::Linear)),
        modeline.h_active, modeline.v_active, ROUND_DISPLAY);
    linear.copy_words(circle_base, 0, words);
    linear.draw_scene_range(ui_scene::Scene::Linear, 2048,
        ui_scene::Scene::Linear.segments(), None,
        (bipolar::MIN_UV, bipolar::MAX_UV), (0, 6_000_000),
        CalibrationGraph::Pitch, ui_canvas::CAL_ERROR_SPAN_MC);
    linear.finish();
    boot_ms[4] = elapsed();
    let mut keyboard=BackgroundCanvas::new(PSRAM_FB_BASE+ui_scene::KEYBOARD_CACHE,
        modeline.h_active,modeline.v_active,ROUND_DISPLAY);
    keyboard.clear();keyboard.draw_scale_keyboard(false);keyboard.finish();
    let mut single=BackgroundCanvas::new(PSRAM_FB_BASE+ui_scene::SINGLE_KEYBOARD_CACHE,
        modeline.h_active,modeline.v_active,ROUND_DISPLAY);
    single.copy_words(circle_base,0,words);single.draw_scale_keyboard(true);single.finish();
    boot_ms[5] = elapsed();

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

    boot_ms[6] = elapsed();
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

    boot_ms[7] = elapsed();
    RuntimeResources {
        boot_ms,
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

// Foreground-only calibration storage. Keep the large retained state out of
// both the scarce 32 KiB SRAM and the perpetual main-loop stack.
#[link_section = ".intono_runtime"]
static mut CALIBRATION_STATE: core::mem::MaybeUninit<calibration_live::Live> = core::mem::MaybeUninit::uninit();

// Called exactly once by run. Isolate constructor temporaries from the
// perpetual loop; moving storage alone can leave its return slot on the stack.
#[inline(never)]
unsafe fn init_calibration_state() -> &'static mut calibration_live::Live {
    let storage = core::ptr::addr_of_mut!(CALIBRATION_STATE).cast::<calibration_live::Live>();
    storage.write(calibration_live::Live::new());
    &mut *storage
}


/// The perpetual real-time phase retains no large calibration state on its stack.
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
        boot_ms,
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
        let mut calibration = unsafe { init_calibration_state() };
        let mut calibration_controls: Option<RuntimeControls> = None;
        let mut capture_trace = capture_trace::Trace::with_calibration(
            *hardware_calibration,
            *hardware_calibration_bits,
        );
        capture_trace.with_boot_timings(boot_ms);
        #[cfg(tuner_nsdf_wave_diag)]
        let mut cv_probe = cv_probe::Probe::default();
        let mut nsdf_trace = nsdf_trace::Trace::new();
        let mut run_calibration = false;
        let mut run_verify = false;
        let mut refine = false;
        let mut accept_refinement = false;
        let mut discard_refinement = false;
        let mut name_editor = oscillator_calibration::name::Editor::new();
        let mut profile_status = "SAVE / LOAD: OUTPUT MUST BE OFF";
        let mut profile_status_slot = 1;
        // Each character bank must receive a changed menu once. Closing the
        // menu hides it; it does not destroy the retained contents of either bank.
        let mut save_feedback = feedback::Feedback::default();
        let mut backgrounds = ui_scene::Backgrounds::with_cached_tuners();
        let mut publication_hold = ui_scene::PublicationHold::new();
        let mut scale_preview = ui_scale::Cache::new();
        let mut scene = ui_scene::Scene::Spiral;
        let mut calibration_revision = 0u64;
        let mut calibration_plot_dirty = false;
        let mut live_trace = ui_scene::LiveTrace::new();
        let mut text_scenes = [None; 2];
        // Compact occupancy only: 512 bytes total, not an 8-KiB text shadow.
        let mut text_occupied = [ui_text::Occupied::new(), ui_text::Occupied::new()];
        let mut last_ui_ms = 0;
        let mut marked_ui = false;
        let mut last_published_ms = 0;
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
                    let video_health=tuner_display.video_health().read();
                    capture_trace.video_health(video_health.gaps().bits(),video_health.background_errors().bits());
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
                let mut q = MULTI_QUANT.borrow_ref_mut(cs);
                for route in 0..4 {
                    if r.held(Owner::Quant(route as u8)) {
                        if let Some(n)=(0..4).find(|n|q.groups.outputs[route]&(1<<n)!=0 && !q.lanes[*n].active) {
                            let reason=q.lanes[n].status;q.stop_group(&tuner,route,reason,&mut r);
                        }
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

            let ui_frame = poll_ui_frame(&calibration,calibration_controls);

            if !marked_ui {
                boot_mark(b'U');
                marked_ui = true;
            }
            // Consume a bounded burst every UI tick, even when learning is off.
            // Note traffic cannot accumulate and later edit a different scale.
            let (learn, span, selected, slot) = with_app(|app| {
                (
                    critical_section::with(|cs| *MIDI_LEARN.borrow_ref(cs))
                        && app.ui.opts.tracker.page.value == Page::QuantNotes,
                    app.ui.opts.quant_notes.octaves.value as usize,
                    app.quant_selected as usize,
                    app.ui.opts.quant_notes.slot.value,
                )
            });
            let base_request=critical_section::with(|cs| {
                let mut request=MIDI_BASE_REQUEST.borrow_ref_mut(cs);
                let pending=*request;*request=false;pending
            });
            if !learn { midi_held.clear(); }
            else if base_request { midi_held.learn_base(); }
            for _ in 0..if learn {8}else{0} {
                let word = midi_input.midi_read().read().msg().bits();
                if word == 0 {
                    break;
                }
                if !learn {
                    continue;
                }
                let event=critical_section::with(|cs| {
                    if MULTI_QUANT.borrow_ref(cs).lanes[selected].active {
                        *MIDI_LEARN.borrow_ref_mut(cs) = false;
                        *NOTE_STATUS.borrow_ref_mut(cs) = (slot, "STOP CHANNEL BEFORE MIDI LEARN");
                        return None;
                    }
                    let event=midi_held.process(&mut QUANT_NOTES.borrow_ref_mut(cs)[..],span,word);
                    if let Some(ref event)=event {
                        *NOTE_STATUS.borrow_ref_mut(cs)=(slot,match event {
                            midi_learn::Event::Base(base)=> {
                                *MIDI_BASE.borrow_ref_mut(cs)=*base;
                                "BASE SET - PLAY NOTES"
                            },
                            midi_learn::Event::Edit{enabled,..}=>if *enabled {"MIDI NOTE ADDED - SAVE TO KEEP"}else{"MIDI NOTE REMOVED - SAVE TO KEEP"},
                        });
                    }
                    event
                });
                if let Some(midi_learn::Event::Edit{key,..})=event {
                    use strum::IntoEnumIterator;
                    with_app(|app| {
                        app.ui.opts.quant_notes.octave.value=key/12;
                        app.ui.opts.quant_notes.note.value=options::ScaleRoot::iter().nth((key%12) as usize).unwrap();
                        let view=midi_learn::reveal(app.ui.opts.quant_notes.view.value,span as u8,key);
                        app.ui.opts.quant_notes.view.value=view;
                        app.ui.opts.quantizer.view_octave.value=view;
                        app.ui.opts.tracker.selected=Some(ui_keyboard::KEYBOARD);
                        app.ui.opts.tracker.modify=false;
                    });
                }
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
            if ui_frame.load_route_scale && !calibration.active() {
                let slot = with_app(|app| app.ui.opts.play.scale_slot.value);
                let status = persist_notes(persistence, false, slot);
                critical_section::with(|cs| {
                    let n=with_app(|app|app.quant_selected as usize);
                    MULTI_QUANT.borrow_ref_mut(cs).lanes[n].status=status;
                    if status == "NOTES LOADED" {
                        *NOTE_STATUS.borrow_ref_mut(cs) = (slot, status);
                    }
                });
            }
            if ui_frame.run_play {
                critical_section::with(|cs| {
                    let mut q = MULTI_QUANT.borrow_ref_mut(cs);
                    let (n, c) = with_app(|app| {
                        (
                            app.route_selected as usize,
                            app.quant_channels,
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
                    profile_status = "SAVE / LOAD: OUTPUT MUST BE OFF";
                }
                if let Some(character) =
                    name_editor.update(ui_frame.name_position, ui_frame.name_character)
                {
                    with_app(|app| {
                        app.ui.opts.profiles.character.value = character;
                        app.ui.external_modify();
                    });
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
                        }
                }
            }
            let feedback_ms = if ui_period_ms > TIMER0_ISR_PERIOD_MS as u64 {
                ui_elapsed_ms.min(u16::MAX as u64) as u16
            } else {
                TIMER0_ISR_PERIOD_MS as u16
            };
            if save_feedback.tick(feedback_ms) {
            }
            if (ui_frame.save_notes || ui_frame.load_notes)
                && !calibration.active()
                && with_app(|app| matches!(app.ui.opts.tracker.page.value, Page::QuantNotes | Page::Quantizer))
            {
                let slot = with_app(|app| app.ui.opts.quant_notes.slot.value);
                let status = persist_notes(persistence, ui_frame.save_notes, slot);
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
            }
            if ui_frame.wipe && !calibration.active() && !outputs_running() {
                save_feedback = feedback::Feedback::default();
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
                // Tuner guides are immutable and scanned directly. Only CAL
                // needs preparation in the mutable back bank.
                let prepare_scene = ui_scene::Scene::Calibration;
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
                    ui_scene::Work::Copy { source, first, end } => canvas.copy_words(
                        PSRAM_FB_BASE + ui_scene::cache_offset(source), first, end),
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
                        swap_background = (calibration_prepared && requested_scene != scene)
                            || (calibration_prepared && calibration_plot_dirty)
                            || (calibration_prepared && live_updated);
                    }
                }
            }

            let direct_tuner = requested_scene != ui_scene::Scene::Calibration;
            let change_tuner = direct_tuner && requested_scene != scene;
            frame_ticks = frame_ticks.saturating_add(1);
            if frame_ticks >= FRAME_PERIOD_TICKS || swap_background || change_tuner {
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
                            calibration.status = "JACK ASSIGNED - STOP ROUTE";
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
                let page=with_app(|app|app.ui.opts.tracker.page.value);
                let preparing_background = matches!(page, Page::Tuner | Page::Calibrate)
                    && ((!direct_tuner && requested_scene != scene)
                        || (calibration_prepared && calibration_plot_dirty));
                let holding_key = (requested_scene, page);
                capture_trace.display_state(tuner_display.frame().read().bits() as u32,
                    last_published_ms, preparing_background, swap_background);
                if !publication_hold.allow(holding_key, preparing_background, swap_background) {
                    // All operation polling above still runs at its normal
                    // cadence; only redundant foreground commits are paused.
                    continue;
                }
                let frame = tuner_display.frame().read();
                if frame.busy().bit() {
                    continue;
                }
                if swap_background || change_tuner {
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
                {
                    text.clear(text_scenes[text_bank].is_none());
                    text_scenes[text_bank] = Some(displayed_scene);
                }
                let mut keyboard_mask=0;
                // Static labels are retained independently in both banks.
                // Dynamic fields still replace their full bounded footprint.
                if calibration_view {
                    text.clear(false);
                    if matches!(
                        controls.mode,
                        runtime::OperatingMode::Quantizer | runtime::OperatingMode::Play
                    ) {
                        keyboard_mask=publish_quantizer(&tuner_display, &mut text, ui_frame.menu_active, &mut scale_preview);
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
                            ui_frame.name_position,
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
                if page==Page::Settings {
                    text.clear(false);
                    publish_markers(&tuner_display,Markers([None;4]),false,false);
                    write_centered(&mut text,14,save_feedback.message(),24);
                } else if page==Page::Help {
                    text.clear(false);
                    publish_markers(&tuner_display,Markers([None;4]),false,false);
                    write_centered(&mut text,7,"TURN TO SELECT",24);
                    write_centered(&mut text,9,"CLICK TO EDIT / APPLY",26);
                    write_centered(&mut text,12,"HELP CONTENT TO FOLLOW",26);
                }

                let menu = snapshot_menu(save_feedback.message());
                publish_controls(&mut text,&menu,&calibration);
                // Commit LAST: characters, marker geometry/color and menu
                // visibility are immutable until the hardware acknowledges them.
                let piano_view=page==Page::QuantNotes || (page==Page::Quantizer && with_app(|app|
                    scale::has_piano_keys(app.quant_channels[app.quant_selected as usize].scale)));
                // Text-only pages and a preparing instrument retain the common
                // outer circle without exposing any old guide or graph pixels.
                let circle_view = !piano_view && ((calibration_view
                    && (!calibration_dashboard || scene != ui_scene::Scene::Calibration))
                    || !matches!(page,Page::Tuner|Page::Calibrate)
                    || requested_scene != scene);
                tuner_display
                    .backdrop()
                    .write(|w| {w.blank().bit(false);
                        w.keyboard_enable().bit(piano_view);
                        w.keyboard_second().bit(with_app(|app|app.quant_channels[app.quant_selected as usize].octaves>1));
                        w.ui_ready().bit(true);
                        unsafe {w.keyboard_mask().bits((keyboard_mask&0xfff) as u16);
                            w.ui_surface().bits(surface(page) as u8);
                            w.ui_focus().bits(menu.entries.iter().position(|e|e.as_ref().is_some_and(|e|e.selected)).unwrap_or(31) as u8);
                        } w});
                tuner_display.keyboard_b().write(|w| unsafe {w.mask().bits((keyboard_mask>>12) as u16)});
                tuner_display.frame().write(|w| {
                    unsafe { w.background_source().bits(if circle_view {4} else if piano_view {if with_app(|app|app.quant_channels[app.quant_selected as usize].octaves)==1 {5}else{3}} else {match scene {
                        ui_scene::Scene::Spiral => 1,
                        ui_scene::Scene::Linear => 2,
                        ui_scene::Scene::Calibration => 0,
                    }}); }
                    w.swap_background().bit(swap_background);
                    w.commit().set_bit()
                });

                last_published_ms = ui_frame.now_ms;
                publication_hold.published(holding_key, preparing_background, swap_background);
            }
        }
    })
}

#[entry]
fn main() -> ! {
    unsafe { stack_monitor::paint(); }
    boot_mark(b'M');
    run(&mut startup())
}
