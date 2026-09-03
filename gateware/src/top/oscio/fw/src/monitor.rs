use core::fmt::Write;

use heapless::String;
use tiliqua_hal::embedded_graphics::{
    mono_font::{ascii::FONT_9X15, ascii::FONT_9X15_BOLD, MonoTextStyle},
    prelude::*,
    primitives::{Line, PrimitiveStyle, Rectangle},
    text::Text,
};
use tiliqua_lib::color::HI8;

pub const COUNTS_PER_VOLT: i32 = 4000;
const LEVEL_FILTER_SHIFT: u32 = 5;
const RELEASE_SHIFT: u32 = 13;
const STATS_UPDATE_TICKS: u8 = 100;
const QUALIFY_FRAMES: u8 = 30;
const EXIT_GRACE_FRAMES: u8 = 10;
const HARD_EXIT_NUMERATOR: u32 = 3;
const HARD_EXIT_DENOMINATOR: u32 = 2;
pub const STATS_BITMAP_WIDTH: u32 = 180;
const STATS_COLUMN_WIDTH: u32 = 190;
const PLOT_MARGIN_X: u32 = 8;
const CIRCULAR_FRAME_WIDTH: u32 = 596;
const CIRCULAR_FRAME_HEIGHT: u32 = 396;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MonitorLayout {
    screen_width: u32,
    screen_height: u32,
    frame_x: u32,
    frame_y: u32,
    frame_width: u32,
    frame_height: u32,
    first_channel: usize,
    channel_count: usize,
}

impl MonitorLayout {
    pub fn new(screen_width: u32, screen_height: u32, pair_first_channel: usize) -> Self {
        let circular = screen_width == 720 && screen_height == 720;
        let (frame_width, frame_height, first_channel, channel_count) = if circular {
            (
                CIRCULAR_FRAME_WIDTH.min(screen_width),
                CIRCULAR_FRAME_HEIGHT.min(screen_height),
                pair_first_channel.min(2),
                2,
            )
        } else {
            (screen_width, screen_height, 0, 4)
        };
        Self {
            screen_width,
            screen_height,
            frame_x: screen_width.saturating_sub(frame_width) / 2,
            frame_y: screen_height.saturating_sub(frame_height) / 2,
            frame_width,
            frame_height,
            first_channel,
            channel_count,
        }
    }

    pub fn is_paginated(self) -> bool {
        self.channel_count == 2
    }

    pub fn first_channel(self) -> usize {
        self.first_channel
    }

    pub fn channel_count(self) -> usize {
        self.channel_count
    }

    pub fn slot_for_channel(self, ch: usize) -> Option<usize> {
        if ch >= self.first_channel && ch < self.first_channel + self.channel_count {
            Some(ch - self.first_channel)
        } else {
            None
        }
    }

    pub fn lane_height(self) -> u32 {
        (self.frame_height / self.channel_count as u32).max(1)
    }

    pub fn stats_origin(self, ch: usize) -> Option<Point> {
        let slot = self.slot_for_channel(ch)?;
        Some(Point::new(
            (self.frame_x + 2) as i32,
            (self.frame_y + slot as u32 * self.lane_height() + 2) as i32,
        ))
    }

    pub fn plot_bounds(self) -> (i16, i16, i16, i16) {
        let half_w = (self.screen_width / 2) as i32;
        let half_h = (self.screen_height / 2) as i32;
        let x_lo = self.frame_x + STATS_COLUMN_WIDTH + PLOT_MARGIN_X;
        let x_hi = self.frame_x + self.frame_width - PLOT_MARGIN_X;
        let y_lo = self.frame_y + 3;
        let y_hi = self.frame_y + self.frame_height - 3;
        (
            (x_lo as i32 - half_w) as i16,
            (x_hi as i32 - half_w) as i16,
            (y_lo as i32 - half_h) as i16,
            (y_hi as i32 - half_h) as i16,
        )
    }

    pub fn stats_region(self, ch: usize) -> Option<Rectangle> {
        let origin = self.stats_origin(ch)?;
        Some(Rectangle::new(
            origin,
            Size::new(
                STATS_COLUMN_WIDTH.saturating_sub(5),
                self.lane_height().saturating_sub(4),
            ),
        ))
    }

    pub fn plot_region(self, ch: usize) -> Option<Rectangle> {
        let slot = self.slot_for_channel(ch)?;
        Some(Rectangle::new(
            Point::new(
                (self.frame_x + STATS_COLUMN_WIDTH + 1) as i32,
                (self.frame_y + slot as u32 * self.lane_height() + 1) as i32,
            ),
            Size::new(
                self.frame_width.saturating_sub(STATS_COLUMN_WIDTH + 1),
                self.lane_height().saturating_sub(2),
            ),
        ))
    }

    pub fn lane_center_px(self, ch: usize) -> Option<i16> {
        let slot = self.slot_for_channel(ch)?;
        let center = self.frame_y + slot as u32 * self.lane_height() + self.lane_height() / 2;
        Some((center as i32 - self.screen_height as i32 / 2) as i16)
    }
}

#[derive(Clone, Copy, Default)]
pub struct ChannelMeasurement {
    pub level: i32,
    pub low: i32,
    pub high: i32,
    pub period_ticks: u32,
    pub period_valid: bool,
    pub rapid_activity: bool,
}

#[derive(Clone, Copy, Default)]
pub struct MeasurementFrame {
    pub epoch: u32,
    pub fs: u32,
    pub channels: [ChannelMeasurement; 4],
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum LaneState {
    #[default]
    Checking,
    Visible,
    AboveBand,
}

/// Qualifies monitor traces before allowing them into the display overlay.
///
/// A hidden trace must remain below the selected cutoff for three seconds
/// before it is shown. Once visible, it may exceed the cutoff for up to one
/// second; reaching 1.5x the cutoff hides it immediately. This wide, asymmetric
/// boundary prevents marginal estimates from repeatedly exposing and hiding a
/// lane while still rejecting clearly out-of-band signals promptly.
pub struct MonitorGate {
    states: [LaneState; 4],
    qualify_frames: [u8; 4],
    above_frames: [u8; 4],
    last_epoch: u32,
    last_minimum_period_ms: u32,
}

impl MonitorGate {
    pub fn new() -> Self {
        Self {
            states: [LaneState::Checking; 4],
            qualify_frames: [0; 4],
            above_frames: [0; 4],
            last_epoch: 0,
            last_minimum_period_ms: 0,
        }
    }

    pub fn reset(&mut self, minimum_period_ms: u32) {
        self.states = [LaneState::Checking; 4];
        self.qualify_frames = [0; 4];
        self.above_frames = [0; 4];
        self.last_epoch = 0;
        self.last_minimum_period_ms = minimum_period_ms;
    }

    pub fn update(&mut self, frame: &MeasurementFrame, minimum_period_ms: u32) {
        if minimum_period_ms != self.last_minimum_period_ms {
            self.reset(minimum_period_ms);
        }
        if frame.epoch == 0 || frame.epoch == self.last_epoch {
            return;
        }
        self.last_epoch = frame.epoch;

        for ch in 0..4 {
            let measurement = frame.channels[ch];
            if self.states[ch] == LaneState::Visible {
                if is_above_hard_limit(measurement, minimum_period_ms, frame.fs) {
                    self.states[ch] = LaneState::AboveBand;
                    self.qualify_frames[ch] = 0;
                    self.above_frames[ch] = 0;
                } else if is_above_monitor_band(measurement, minimum_period_ms, frame.fs) {
                    self.above_frames[ch] = self.above_frames[ch].saturating_add(1);
                    if self.above_frames[ch] >= EXIT_GRACE_FRAMES {
                        self.states[ch] = LaneState::AboveBand;
                        self.qualify_frames[ch] = 0;
                        self.above_frames[ch] = 0;
                    }
                } else {
                    self.above_frames[ch] = 0;
                }
                continue;
            }

            let safely_below = !is_above_monitor_band(measurement, minimum_period_ms, frame.fs);
            self.states[ch] = LaneState::Checking;
            if safely_below {
                self.qualify_frames[ch] = self.qualify_frames[ch].saturating_add(1);
                if self.qualify_frames[ch] >= QUALIFY_FRAMES {
                    self.states[ch] = LaneState::Visible;
                }
            } else {
                self.qualify_frames[ch] = 0;
                self.states[ch] = LaneState::AboveBand;
            }
        }
    }

    pub fn states(&self) -> [LaneState; 4] {
        self.states
    }
}

/// Low-rate voltage statistics tracker fed from calibrated input CSRs at 1 kHz.
/// Native-rate period and activity results are supplied separately by FPGA
/// hardware and merged into each snapshot by the main loop.
pub struct MonitorTracker {
    frame: MeasurementFrame,
    f_bits: u8,
    initialized: bool,
    update_ticks: u8,
}

impl MonitorTracker {
    pub fn new(f_bits: u8) -> Self {
        Self {
            frame: MeasurementFrame::default(),
            f_bits,
            initialized: false,
            update_ticks: 0,
        }
    }

    pub fn reset(&mut self) {
        let f_bits = self.f_bits;
        *self = Self::new(f_bits);
    }

    fn q15(&self, raw: i32) -> i32 {
        if self.f_bits >= 15 {
            raw >> (self.f_bits - 15)
        } else {
            raw.saturating_mul(1i32 << (15 - self.f_bits))
        }
    }

    pub fn update(&mut self, raw: [i32; 4]) {
        for ch in 0..4 {
            let sample = self.q15(raw[ch]);
            let measurement = &mut self.frame.channels[ch];
            if !self.initialized {
                measurement.level = sample;
                measurement.low = sample;
                measurement.high = sample;
                continue;
            }

            // About a 32 ms DC/level average at the 1 kHz update rate.
            measurement.level += (sample - measurement.level) >> LEVEL_FILTER_SHIFT;

            // Extrema attack immediately and release over roughly ten seconds.
            // This retains the peaks of slow LFOs without making a changed
            // patch remain stuck at its lifetime minimum and maximum.
            if sample < measurement.low {
                measurement.low = sample;
            } else {
                let delta = sample - measurement.low;
                measurement.low += (delta + ((1 << RELEASE_SHIFT) - 1)) >> RELEASE_SHIFT;
            }
            if sample > measurement.high {
                measurement.high = sample;
            } else {
                let delta = measurement.high - sample;
                measurement.high -= (delta + ((1 << RELEASE_SHIFT) - 1)) >> RELEASE_SHIFT;
            }
        }

        self.initialized = true;
        self.update_ticks += 1;
        if self.update_ticks >= STATS_UPDATE_TICKS {
            self.update_ticks = 0;
            self.frame.epoch = self.frame.epoch.wrapping_add(1);
        }
    }

    pub fn snapshot(&self) -> MeasurementFrame {
        self.frame
    }
}

pub fn is_above_monitor_band(
    measurement: ChannelMeasurement,
    minimum_period_ms: u32,
    fs: u32,
) -> bool {
    if measurement.period_valid && measurement.period_ticks != 0 && fs != 0 {
        (measurement.period_ticks as u64) * 1000 < (minimum_period_ms as u64) * (fs as u64)
    } else {
        measurement.rapid_activity
    }
}

pub fn is_above_hard_limit(
    measurement: ChannelMeasurement,
    minimum_period_ms: u32,
    fs: u32,
) -> bool {
    if measurement.rapid_activity {
        return true;
    }
    measurement.period_valid
        && measurement.period_ticks != 0
        && fs != 0
        && (measurement.period_ticks as u64) * (HARD_EXIT_NUMERATOR as u64) * 1000
            <= (minimum_period_ms as u64) * (fs as u64) * (HARD_EXIT_DENOMINATOR as u64)
}

fn voltage_text(value: i32) -> String<16> {
    let mut text = String::new();
    let millivolts = value / (COUNTS_PER_VOLT / 1000);
    let sign = if millivolts < 0 { '-' } else { '+' };
    let magnitude = millivolts.saturating_abs();
    write!(
        text,
        "{}{}.{:03}V",
        sign,
        magnitude / 1000,
        magnitude % 1000
    )
    .ok();
    text
}

fn magnitude_voltage_text(value: i32) -> String<16> {
    let mut text = String::new();
    let millivolts = value.saturating_abs() / (COUNTS_PER_VOLT / 1000);
    write!(text, "{}.{:03}V", millivolts / 1000, millivolts % 1000).ok();
    text
}

fn rate_text(measurement: ChannelMeasurement, fs: u32) -> (String<24>, String<24>) {
    let mut frequency = String::new();
    let mut period = String::new();
    if !measurement.period_valid || measurement.period_ticks == 0 || fs == 0 {
        write!(frequency, "freq --").ok();
        write!(period, "period --").ok();
        return (frequency, period);
    }

    let ticks = measurement.period_ticks as u64;
    let milli_hz = ((fs as u64 * 1000) + ticks / 2) / ticks;
    let period_ms = (ticks * 1000 + fs as u64 / 2) / fs as u64;
    write!(
        frequency,
        "freq {}.{:03}Hz",
        milli_hz / 1000,
        milli_hz % 1000
    )
    .ok();
    if period_ms < 1000 {
        write!(period, "period {}ms", period_ms).ok();
    } else {
        write!(
            period,
            "period {}.{:03}s",
            period_ms / 1000,
            period_ms % 1000
        )
        .ok();
    }
    (frequency, period)
}

pub fn draw_lane_plot<D>(
    display: &mut D,
    layout: MonitorLayout,
    ui_hue: u8,
    base_hue: u8,
    ch: usize,
    lane_state: LaneState,
    limit_label: &str,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    let Some(slot) = layout.slot_for_channel(ch) else {
        return Ok(());
    };
    let stats = (layout.frame_x + STATS_COLUMN_WIDTH) as i32;
    let lane_h = layout.lane_height() as i32;
    let center_y = layout.frame_y as i32 + slot as i32 * lane_h + lane_h / 2;
    let plot_right = (layout.frame_x + layout.frame_width - PLOT_MARGIN_X) as i32;
    let dim = PrimitiveStyle::with_stroke(HI8::new(ui_hue, 4), 1);
    let mut x = stats + PLOT_MARGIN_X as i32;
    while x < plot_right {
        Line::new(
            Point::new(x, center_y),
            Point::new((x + 7).min(plot_right), center_y),
        )
        .into_styled(dim)
        .draw(display)?;
        x += 16;
    }

    if lane_state != LaneState::Visible {
        let mut label: String<24> = String::new();
        match lane_state {
            LaneState::AboveBand => write!(label, "SIGNAL > {}", limit_label).ok(),
            LaneState::Checking => write!(label, "CHECKING SIGNAL").ok(),
            LaneState::Visible => None,
        };
        let hue = base_hue.wrapping_add((ch * 3) as u8) & 0x0f;
        let style = MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(hue, 13));
        let plot_center = stats + (plot_right - stats) / 2;
        let text_x = plot_center - (label.len() as i32 * 9) / 2;
        Text::new(&label, Point::new(text_x, center_y + 5), style).draw(display)?;
    }
    Ok(())
}

pub fn draw_frame<D>(display: &mut D, layout: MonitorLayout, hue: u8) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    let bright = PrimitiveStyle::with_stroke(HI8::new(hue, 8), 1);
    let stats = (layout.frame_x + STATS_COLUMN_WIDTH) as i32;
    let lane_h = layout.lane_height() as i32;
    let frame_bottom = (layout.frame_y + layout.frame_height - 1) as i32;
    let frame_right = (layout.frame_x + layout.frame_width - 1) as i32;

    Line::new(
        Point::new(stats, layout.frame_y as i32),
        Point::new(stats, frame_bottom),
    )
    .into_styled(bright)
    .draw(display)?;
    for slot in 1..layout.channel_count {
        let y = layout.frame_y as i32 + slot as i32 * lane_h;
        Line::new(
            Point::new(layout.frame_x as i32, y),
            Point::new(frame_right, y),
        )
        .into_styled(bright)
        .draw(display)?;
    }
    Ok(())
}

/// Render one statistics panel into a local 1bpp scratch bitmap. The caller
/// diffs this against the previous bitmap so removed glyph pixels are written
/// black without visibly blanking the whole panel.
pub fn draw_channel_stats<D>(
    display: &mut D,
    ch: usize,
    measurement: ChannelMeasurement,
    fs: u32,
    ready: bool,
) -> Result<(), D::Error>
where
    D: DrawTarget<Color = HI8>,
{
    let bold = MonoTextStyle::new(&FONT_9X15_BOLD, HI8::new(0, 15));
    let normal = MonoTextStyle::new(&FONT_9X15, HI8::new(0, 11));
    let mut line: String<48> = String::new();

    if ready {
        write!(line, "CH{}  {}", ch + 1, voltage_text(measurement.level)).ok();
    } else {
        write!(line, "CH{}  --", ch + 1).ok();
    }
    Text::new(&line, Point::new(8, 23), bold).draw(display)?;

    line.clear();
    if ready {
        write!(line, "lo {}", voltage_text(measurement.low)).ok();
    } else {
        write!(line, "lo --").ok();
    }
    Text::new(&line, Point::new(8, 45), normal).draw(display)?;

    line.clear();
    if ready {
        write!(line, "hi {}", voltage_text(measurement.high)).ok();
    } else {
        write!(line, "hi --").ok();
    }
    Text::new(&line, Point::new(8, 70), normal).draw(display)?;

    line.clear();
    if ready {
        let peak_to_peak = measurement.high.saturating_sub(measurement.low);
        write!(line, "p-p {}", magnitude_voltage_text(peak_to_peak)).ok();
    } else {
        write!(line, "p-p --").ok();
    }
    Text::new(&line, Point::new(8, 95), normal).draw(display)?;

    let (frequency, period) = if ready {
        rate_text(measurement, fs)
    } else {
        rate_text(ChannelMeasurement::default(), 0)
    };
    line.clear();
    write!(line, "{}", frequency).ok();
    Text::new(&line, Point::new(8, 120), normal).draw(display)?;
    line.clear();
    write!(line, "{}", period).ok();
    Text::new(&line, Point::new(8, 145), normal).draw(display)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        is_above_monitor_band, ChannelMeasurement, LaneState, MeasurementFrame, MonitorGate,
        MonitorLayout, MonitorTracker, STATS_UPDATE_TICKS,
    };

    #[test]
    fn monitor_rejects_rates_above_two_hz() {
        let fast = ChannelMeasurement {
            period_ticks: 95_999,
            period_valid: true,
            ..Default::default()
        };
        let edge = ChannelMeasurement {
            period_ticks: 96_000,
            period_valid: true,
            ..Default::default()
        };
        assert!(is_above_monitor_band(fast, 500, 192_000));
        assert!(!is_above_monitor_band(edge, 500, 192_000));

        let one_hz_fast = ChannelMeasurement {
            period_ticks: 191_999,
            period_valid: true,
            ..Default::default()
        };
        let one_hz_edge = ChannelMeasurement {
            period_ticks: 192_000,
            period_valid: true,
            ..Default::default()
        };
        assert!(is_above_monitor_band(one_hz_fast, 1000, 192_000));
        assert!(!is_above_monitor_band(one_hz_edge, 1000, 192_000));

        let twenty_hz_fast = ChannelMeasurement {
            period_ticks: 9_599,
            period_valid: true,
            ..Default::default()
        };
        let twenty_hz_edge = ChannelMeasurement {
            period_ticks: 9_600,
            period_valid: true,
            ..Default::default()
        };
        assert!(is_above_monitor_band(twenty_hz_fast, 50, 192_000));
        assert!(!is_above_monitor_band(twenty_hz_edge, 50, 192_000));
    }

    #[test]
    fn one_slow_step_does_not_hide_the_trace() {
        let mut tracker = MonitorTracker::new(15);
        tracker.update([0; 4]);
        tracker.update([5000; 4]);
        for _ in 2..20 {
            tracker.update([5000; 4]);
        }
        assert!(!is_above_monitor_band(
            tracker.snapshot().channels[0],
            1000,
            192_000,
        ));
    }

    #[test]
    fn landscape_layout_displays_all_four_channels() {
        let layout = MonitorLayout::new(1280, 720, 2);
        assert!(!layout.is_paginated());
        assert_eq!(layout.first_channel(), 0);
        assert_eq!(layout.channel_count(), 4);
        assert_eq!(layout.lane_center_px(0), Some(-270));
        assert_eq!(layout.lane_center_px(1), Some(-90));
        assert_eq!(layout.lane_center_px(2), Some(90));
        assert_eq!(layout.lane_center_px(3), Some(270));
    }

    #[test]
    fn circular_layout_displays_selected_pair_inside_safe_frame() {
        let first = MonitorLayout::new(720, 720, 0);
        assert!(first.is_paginated());
        assert_eq!(first.first_channel(), 0);
        assert_eq!(first.channel_count(), 2);
        assert_eq!(first.lane_center_px(0), Some(-99));
        assert_eq!(first.lane_center_px(1), Some(99));
        assert_eq!(first.lane_center_px(2), None);
        assert_eq!(first.plot_bounds(), (-100, 290, -195, 195));

        let second = MonitorLayout::new(720, 720, 2);
        assert_eq!(second.lane_center_px(0), None);
        assert_eq!(second.lane_center_px(2), Some(-99));
        assert_eq!(second.lane_center_px(3), Some(99));
    }

    #[test]
    fn tracker_retains_voltage_extrema() {
        let mut tracker = MonitorTracker::new(15);
        let cycle = [3000, 3000, 5000, 5000];
        for tick in 0..24 {
            let value = cycle[tick % cycle.len()];
            tracker.update([value; 4]);
        }
        let frame = tracker.snapshot();
        assert!(!frame.channels[0].period_valid);
        assert!(frame.channels[0].low >= 3000);
        assert!(frame.channels[0].high <= 5000);
    }

    #[test]
    fn tracker_rejects_static_voltage() {
        let mut tracker = MonitorTracker::new(15);
        for _ in 0..40 {
            tracker.update([4000; 4]);
        }
        let frame = tracker.snapshot();
        assert!(!frame.channels[0].period_valid);
        assert_eq!(frame.channels[0].level, 4000);
    }

    #[test]
    fn tracker_generation_does_not_wrap_at_the_old_eight_bit_boundary() {
        let mut tracker = MonitorTracker::new(15);
        tracker.frame.epoch = u8::MAX as u32;
        for _ in 0..STATS_UPDATE_TICKS {
            tracker.update([0; 4]);
        }
        assert_eq!(tracker.snapshot().epoch, 256);
    }

    #[test]
    fn monitor_gate_requires_three_stable_seconds_before_showing() {
        let mut gate = MonitorGate::new();
        gate.reset(500);
        let mut frame = MeasurementFrame {
            fs: 1000,
            channels: [ChannelMeasurement {
                period_ticks: 600,
                period_valid: true,
                ..Default::default()
            }; 4],
            ..Default::default()
        };
        for epoch in 1..30 {
            frame.epoch = epoch;
            gate.update(&frame, 500);
            assert_eq!(gate.states()[0], LaneState::Checking);
        }
        frame.epoch = 30;
        gate.update(&frame, 500);
        assert_eq!(gate.states()[0], LaneState::Visible);
    }

    #[test]
    fn monitor_gate_tolerates_one_second_above_cutoff_then_requalifies() {
        let mut gate = MonitorGate::new();
        gate.reset(500);
        let mut frame = MeasurementFrame {
            fs: 1000,
            channels: [ChannelMeasurement {
                period_ticks: 600,
                period_valid: true,
                ..Default::default()
            }; 4],
            ..Default::default()
        };
        for epoch in 1..=30 {
            frame.epoch = epoch;
            gate.update(&frame, 500);
        }
        assert_eq!(gate.states()[0], LaneState::Visible);

        frame.channels[0].period_ticks = 400;
        for epoch in 31..40 {
            frame.epoch = epoch;
            gate.update(&frame, 500);
            assert_eq!(gate.states()[0], LaneState::Visible);
        }
        frame.epoch = 40;
        gate.update(&frame, 500);
        assert_eq!(gate.states()[0], LaneState::AboveBand);

        frame.channels[0].period_ticks = 500;
        for epoch in 41..70 {
            frame.epoch = epoch;
            gate.update(&frame, 500);
            assert_eq!(gate.states()[0], LaneState::Checking);
        }
        frame.epoch = 70;
        gate.update(&frame, 500);
        assert_eq!(gate.states()[0], LaneState::Visible);
    }

    #[test]
    fn monitor_gate_hides_at_one_and_a_half_times_cutoff_immediately() {
        let mut gate = MonitorGate::new();
        gate.reset(50);
        let mut frame = MeasurementFrame {
            fs: 1000,
            channels: [ChannelMeasurement {
                period_ticks: 50,
                period_valid: true,
                ..Default::default()
            }; 4],
            ..Default::default()
        };
        for epoch in 1..=30 {
            frame.epoch = epoch;
            gate.update(&frame, 50);
        }
        assert_eq!(gate.states()[0], LaneState::Visible);

        frame.epoch = 31;
        frame.channels[0].period_ticks = 33;
        gate.update(&frame, 50);
        assert_eq!(gate.states()[0], LaneState::AboveBand);
    }
}
