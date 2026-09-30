//! Allocation-free retained drawing on the common 720x720 logical canvas.
//! These helpers emit pixels; they do not allocate, flush caches or publish frames.

pub const SIZE: i32 = 720;
pub const CAL_ERROR_SPAN_MC: i32 = 20_000;
const CAL_ERROR_SPANS_MC: [i32; 10] = [
    20_000, 50_000, 100_000, 200_000, 500_000, 1_000_000,
    2_000_000, 5_000_000, 10_000_000, 20_000_000,
];

/// Select a readable symmetric error axis with room beyond the worst point.
pub fn calibration_error_span_mc(worst_abs_mc: i64) -> i32 {
    let required = worst_abs_mc.saturating_mul(5) / 4;
    CAL_ERROR_SPANS_MC.iter().copied()
        .find(|span| *span as i64 >= required)
        .unwrap_or(*CAL_ERROR_SPANS_MC.last().unwrap())
}
pub const CALIBRATION_PLOT: Rect = Rect {
    x: 154,
    y: 190,
    width: 276,
    height: 230,
};
pub const CAL_TRACKING_Y: i32 = CALIBRATION_PLOT.y + CALIBRATION_PLOT.height as i32 + 2;
pub const CAL_TRACKING_HEIGHT: i32 = 7;

/// Color one measured interval by its local departure from 1 V/oct, in
/// cents per volt. Missing or nonadjacent samples leave a gap in the strip.
pub fn calibration_tracking_color(
    first_uv: i32, first_mc: i32, last_uv: i32, last_mc: i32,
) -> Option<u8> {
    let delta_uv = last_uv as i64 - first_uv as i64;
    if !(1..=125_000).contains(&delta_uv) { return None; }
    let error_mc = (last_mc as i64 - first_mc as i64)
        - delta_uv * 1_200_000 / 1_000_000;
    let slope_mc_per_volt = error_mc.abs().saturating_mul(1_000_000) / delta_uv;
    Some(if slope_mc_per_volt < 50_000 { 0xD9 }
        else if slope_mc_per_volt < 200_000 { 0xD2 }
        else { 0xD0 })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Point {
    pub x: i32,
    pub y: i32,
}

impl Point {
    pub fn inside(self) -> bool {
        (0..SIZE).contains(&self.x) && (0..SIZE).contains(&self.y)
    }
}

#[derive(Clone, Copy)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub width: u16,
    pub height: u16,
}

impl Rect {
    pub fn corners(self) -> Option<(Point, Point)> {
        if self.width == 0 || self.height == 0 {
            return None;
        }
        let first = Point {
            x: self.x,
            y: self.y,
        };
        let last = Point {
            x: self.x.checked_add(self.width as i32 - 1)?,
            y: self.y.checked_add(self.height as i32 - 1)?,
        };
        if first.inside() && last.inside() {
            Some((first, last))
        } else {
            None
        }
    }

    pub fn fits_circle(self, radius: u16) -> bool {
        if radius > 360 {
            return false;
        }
        let Some((a, b)) = self.corners() else {
            return false;
        };
        [a.x, b.x].iter().all(|x| {
            [a.y, b.y].iter().all(|y| {
                let dx = x - 360;
                let dy = y - 360;
                dx * dx + dy * dy <= (radius as i32) * (radius as i32)
            })
        })
    }
}

pub fn physical(point: Point, width: u16, height: u16, rotate_left: bool) -> Option<usize> {
    if !point.inside() {
        return None;
    }
    let (x, y) = if rotate_left {
        (719 - point.y, point.x)
    } else {
        (point.x + (width as i32 - SIZE).max(0) / 2, point.y)
    };
    if x >= width as i32 || y >= height as i32 {
        return None;
    }
    Some(y as usize * width as usize + x as usize)
}

// Endpoints must be on-canvas: rejecting invalid geometry avoids invisible,
// potentially enormous walks. Every accepted line emits at most 720 pixels.
pub fn line(mut a: Point, b: Point, color: u8, mut emit: impl FnMut(Point, u8)) -> bool {
    if !a.inside() || !b.inside() {
        return false;
    }
    let dx = (b.x - a.x).abs();
    let sx = if a.x < b.x { 1 } else { -1 };
    let dy = -(b.y - a.y).abs();
    let sy = if a.y < b.y { 1 } else { -1 };
    let mut error = dx + dy;
    loop {
        emit(a, color);
        if a == b {
            return true;
        }
        let twice = error * 2;
        if twice >= dy {
            error += dy;
            a.x += sx;
        }
        if twice <= dx {
            error += dx;
            a.y += sy;
        }
    }
}

// Inclusive outline/grid. Bounded to 32 divisions in either direction.
pub fn grid(rect: Rect, columns: u8, rows: u8, color: u8, mut emit: impl FnMut(Point, u8)) -> bool {
    if rect.corners().is_none() || !(1..=32).contains(&columns) || !(1..=32).contains(&rows) {
        return false;
    }
    for segment in 0..columns as usize + rows as usize + 2 {
        grid_segment(rect, columns, rows, segment, color, &mut emit);
    }
    true
}

/// One grid line per call, so callers can yield between long retained draws.
pub fn grid_segment(
    rect: Rect,
    columns: u8,
    rows: u8,
    segment: usize,
    color: u8,
    mut emit: impl FnMut(Point, u8),
) -> bool {
    let Some((a, b)) = rect.corners() else {
        return false;
    };
    if !(1..=32).contains(&columns) || !(1..=32).contains(&rows) {
        return false;
    }
    if segment <= columns as usize {
        let x = a.x + (b.x - a.x) * segment as i32 / columns as i32;
        line(Point { x, y: a.y }, Point { x, y: b.y }, color, &mut emit);
    } else if segment < columns as usize + rows as usize + 2 {
        let n = segment - columns as usize - 1;
        let y = a.y + (b.y - a.y) * n as i32 / rows as i32;
        line(Point { x: a.x, y }, Point { x: b.x, y }, color, &mut emit);
    } else {
        return false;
    }
    true
}

/// Join one pair of uniformly spaced observations in a bounded plot.
/// Values clamp to the vertical axis; invalid geometry/ranges emit nothing.
/// This is drawing only, not interpolation of calibration measurements.
pub fn trace_segment(
    rect: Rect,
    values: &[i32],
    low: i32,
    high: i32,
    segment: usize,
    color: u8,
    emit: impl FnMut(Point, u8),
) -> bool {
    let Some((a, b)) = rect.corners() else {
        return false;
    };
    if low >= high || values.len() < 2 || values.len() > 1024 || segment >= values.len() - 1 {
        return false;
    }
    let point = |index: usize| Point {
        x: axis(
            index as i32,
            0,
            values.len() as i32 - 1,
            a.x as u16,
            b.x as u16,
        )
        .unwrap(),
        y: axis(values[index], low, high, b.y as u16, a.y as u16).unwrap(),
    };
    line(point(segment), point(segment + 1), color, emit)
}

pub fn rectangle(rect: Rect, color: u8, emit: impl FnMut(Point, u8)) -> bool {
    grid(rect, 1, 1, color, emit)
}

/// Difference from ideal 1 V/oct, anchored at the first measured point.
/// Pitch is in millicents. The origin is relative, not A440.
pub fn calibration_error_mc(
    voltage_uv: i32, pitch_mc: i32, anchor_uv: i32, anchor_mc: i32,
) -> i64 {
    pitch_mc as i64 - anchor_mc as i64
        - (voltage_uv as i64 - anchor_uv as i64) * 1_200_000 / 1_000_000
}

pub fn calibration_ideal_mc(voltage_uv: i32, anchor_uv: i32, anchor_mc: i32) -> i32 {
    (anchor_mc as i64 + (voltage_uv as i64 - anchor_uv as i64) * 1_200_000 / 1_000_000)
        .clamp(i32::MIN as i64, i32::MAX as i64) as i32
}

pub fn calibration_pitch_bounds(
    anchor_uv: i32, anchor_mc: i32, low_uv: i32, high_uv: i32,
) -> Option<(i32, i32)> {
    if low_uv >= high_uv { return None; }
    let low = calibration_ideal_mc(low_uv, anchor_uv, anchor_mc) as i64;
    let high = calibration_ideal_mc(high_uv, anchor_uv, anchor_mc) as i64;
    let pad = ((high - low) / 32).max(100_000);
    let bounds = ((low - pad).clamp(i32::MIN as i64, i32::MAX as i64) as i32,
        (high + pad).clamp(i32::MIN as i64, i32::MAX as i64) as i32);
    (bounds.0 < bounds.1).then_some(bounds)
}

pub fn calibration_pitch_y(
    rect: Rect, pitch_mc: i32, anchor_uv: i32, anchor_mc: i32,
    low_uv: i32, high_uv: i32,
) -> Option<i32> {
    let (a, b) = rect.corners()?;
    let (low, high) = calibration_pitch_bounds(anchor_uv, anchor_mc, low_uv, high_uv)?;
    axis(pitch_mc, low, high, (b.y - 8) as u16, (a.y + 8) as u16)
}

pub fn calibration_pitch_point(
    rect: Rect, voltage_uv: i32, pitch_mc: i32,
    anchor_uv: i32, anchor_mc: i32, low_uv: i32, high_uv: i32,
) -> Option<Point> {
    let (a, b) = rect.corners()?;
    Some(Point {
        x: axis(voltage_uv, low_uv, high_uv, a.x as u16, b.x as u16)?,
        y: calibration_pitch_y(rect, pitch_mc, anchor_uv, anchor_mc, low_uv, high_uv)?,
    })
}

/// The dashed reference is the ideal 1 V/oct pitch rise across the voltage
/// axis. Cent error is measured vertically from this line at each voltage.
pub fn calibration_ideal_y(rect: Rect, voltage_uv: i32,
    low_uv: i32, high_uv: i32) -> Option<i32> {
    let (a, b) = rect.corners()?;
    axis(voltage_uv, low_uv, high_uv,
        (b.y - 32) as u16, (a.y + 32) as u16)
}

pub fn calibration_error_point(
    rect: Rect,
    voltage_uv: i32,
    pitch_mc: i32,
    anchor_uv: i32,
    anchor_mc: i32,
    low_uv: i32,
    high_uv: i32,
    half_span_mc: i32,
) -> Option<Point> {
    let (a, b) = rect.corners()?;
    if low_uv >= high_uv || half_span_mc <= 0 {
        return None;
    }
    let error = calibration_error_mc(voltage_uv, pitch_mc, anchor_uv, anchor_mc)
        .clamp(-(half_span_mc as i64), half_span_mc as i64) as i32;
    let ideal_y = calibration_ideal_y(rect, voltage_uv, low_uv, high_uv)?;
    let error_pixels = error as i64 * 30 / half_span_mc as i64;
    Some(Point {
        x: axis(voltage_uv, low_uv, high_uv, a.x as u16, b.x as u16)?,
        y: (ideal_y as i64 - error_pixels).clamp(a.y as i64, b.y as i64) as i32,
    })
}

pub fn calibration_error_only_point(
    rect: Rect, voltage_uv: i32, pitch_mc: i32,
    anchor_uv: i32, anchor_mc: i32, low_uv: i32, high_uv: i32,
    half_span_mc: i32,
) -> Option<Point> {
    let (a, b) = rect.corners()?;
    if low_uv >= high_uv || half_span_mc <= 0 { return None; }
    let error = calibration_error_mc(voltage_uv, pitch_mc, anchor_uv, anchor_mc)
        .clamp(-(half_span_mc as i64), half_span_mc as i64) as i32;
    Some(Point {
        x: axis(voltage_uv, low_uv, high_uv, a.x as u16, b.x as u16)?,
        y: axis(error, -half_span_mc, half_span_mc,
            (b.y - 8) as u16, (a.y + 8) as u16)?,
    })
}

/// Fixed sweep axes during acquisition prevent each new point from stretching
/// the previously drawn trace. Out-of-scale errors clip to the detail limit.
pub fn live_calibration_point(
    rect: Rect,
    voltage_uv: i32,
    pitch_mc: i32,
    anchor_uv: i32,
    anchor_mc: i32,
    low_uv: i32,
    high_uv: i32,
) -> Option<Point> {
    calibration_error_point(rect, voltage_uv, pitch_mc,
        anchor_uv, anchor_mc, low_uv, high_uv, CAL_ERROR_SPAN_MC)
}

// Map a bounded measurement onto a plot axis; descending pixel axes support
// graph Y coordinates. Arithmetic stays wide until after normalization.
pub fn axis(value: i32, low: i32, high: i32, first: u16, last: u16) -> Option<i32> {
    if low >= high || first >= 720 || last >= 720 {
        return None;
    }
    let numerator = value.clamp(low, high) as i64 - low as i64;
    Some(
        first as i32
            + (numerator * (last as i64 - first as i64) / (high as i64 - low as i64)) as i32,
    )
}

/// Circular-safe linear cents ruler, shared by the retained view and tests.
pub const LINEAR_LEFT: u16 = 152;
pub const LINEAR_RIGHT: u16 = 568;
pub const LINEAR_LANES: [i32; 4] = [224, 328, 432, 536];

/// One-pixel cursor resolution without quantizing to the whole-cent label.
/// Reject non-finite input before casting; never turn a bad estimate into a
/// plausible zero-cent indication. Only the drawing is clamped to the ruler.
pub fn cents_position(cents: f32) -> Option<u16> {
    if !cents.is_finite() {
        return None;
    }
    let clamped = cents.max(-50.0).min(50.0);
    Some(
        (LINEAR_LEFT as f32 + (clamped + 50.0) * (LINEAR_RIGHT - LINEAR_LEFT) as f32 / 100.0 + 0.5)
            as u16,
    )
}

pub fn linear_scale(mut emit: impl FnMut(Point, u8)) {
    for segment in 0..22 {
        linear_scale_segment(segment, &mut emit);
    }
}

pub fn linear_scale_segment(segment: usize, mut emit: impl FnMut(Point, u8)) {
    scale_segment(segment, 360, &mut emit);
}

/// Four retained lanes, still using the same line rasterizer and framebuffer.
/// Kept separate from measurement acquisition; callers must label absent data.
pub fn four_lane_scale_segment(segment: usize, mut emit: impl FnMut(Point, u8)) {
    if segment >= 4 * 22 {
        return;
    }
    scale_segment(segment % 22, LINEAR_LANES[segment / 22], &mut emit);
}

fn scale_segment(segment: usize, y: i32, mut emit: impl FnMut(Point, u8)) {
    if segment == 0 {
        line(
            Point {
                x: LINEAR_LEFT as i32,
                y,
            },
            Point {
                x: LINEAR_RIGHT as i32,
                y,
            },
            0x29,
            &mut emit,
        );
    } else if segment <= 21 {
        let tick = segment as i32 - 1;
        let x = axis(tick, 0, 20, LINEAR_LEFT, LINEAR_RIGHT).unwrap();
        let half_height = if tick == 10 {
            24
        } else if tick % 2 == 0 {
            12
        } else {
            6
        };
        line(
            Point {
                x,
                y: y - half_height,
            },
            Point {
                x,
                y: y + half_height,
            },
            if tick == 10 { 0x99 } else { 0x59 },
            &mut emit,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn segmented_grids_and_traces_are_bounded_and_reject_invalid_work() {
        let rect = Rect {
            x: 152,
            y: 256,
            width: 417,
            height: 257,
        };
        let mut complete = Vec::new();
        grid(rect, 12, 8, 9, |p, c| complete.push((p, c)));
        let mut segmented = Vec::new();
        for segment in 0..22 {
            let before = segmented.len();
            assert!(grid_segment(rect, 12, 8, segment, 9, |p, c| segmented.push((p, c))));
            assert!(segmented.len() - before <= 417);
        }
        assert_eq!(complete, segmented);
        assert!(!grid_segment(rect, 12, 8, usize::MAX, 9, |_, _| panic!()));
        assert!(!grid_segment(rect, 0, 8, 0, 9, |_, _| panic!()));
        let values = [i32::MIN, 0, i32::MAX];
        let mut trace = Vec::new();
        for segment in 0..2 {
            assert!(trace_segment(
                rect,
                &values,
                -100,
                100,
                segment,
                5,
                |p, _| trace.push(p)
            ));
        }
        assert_eq!(trace[0], Point { x: 152, y: 512 });
        assert!(trace.contains(&Point { x: 360, y: 384 }));
        assert_eq!(*trace.last().unwrap(), Point { x: 568, y: 256 });
        assert!(trace.len() <= 2 * 720);
        for values in [&[][..], &[1][..], &[0; 1025][..]] {
            assert!(!trace_segment(rect, values, 0, 1, 0, 5, |_, _| panic!()));
        }
        assert!(!trace_segment(
            rect,
            &[0, 1],
            0,
            1,
            usize::MAX,
            5,
            |_, _| panic!()
        ));
        assert!(!trace_segment(rect, &[0, 1], 1, 1, 0, 5, |_, _| panic!()));
    }
    #[test]
    fn fractional_cursor_is_monotonic_symmetric_and_bounded() {
        assert_eq!(cents_position(f32::NAN), None);
        assert_eq!(cents_position(f32::INFINITY), None);
        assert_eq!(cents_position(f32::NEG_INFINITY), None);
        assert_eq!(cents_position(-100.0), Some(LINEAR_LEFT));
        assert_eq!(cents_position(100.0), Some(LINEAR_RIGHT));
        assert_eq!(cents_position(0.0), Some(360));
        assert_eq!(cents_position(0.25), Some(361));
        assert_eq!(cents_position(-0.25), Some(359));
        let mut previous = LINEAR_LEFT;
        for hundredths in -5000..=5000 {
            let value = cents_position(hundredths as f32 / 100.0).unwrap();
            assert!(value >= previous && value <= previous + 1);
            assert!((LINEAR_LEFT..=LINEAR_RIGHT).contains(&value));
            previous = value;
        }
    }

    #[test]
    fn four_lanes_are_circular_safe_and_match_single_lane_geometry() {
        let mut single = Vec::new();
        linear_scale(|p, c| single.push((p, c)));
        for (lane, y) in LINEAR_LANES.iter().enumerate() {
            let mut actual = Vec::new();
            for segment in lane * 22..(lane + 1) * 22 {
                four_lane_scale_segment(segment, |p, c| {
                    assert!((p.x - 360).pow(2) + (p.y - 360).pow(2) < 336 * 336);
                    actual.push((
                        Point {
                            x: p.x,
                            y: p.y - y + 360,
                        },
                        c,
                    ));
                });
            }
            assert_eq!(actual, single);
            // Full 33x33 marker footprint fits at both ruler extremes.
            for x in [LINEAR_LEFT, LINEAR_RIGHT] {
                assert!(Rect {
                    x: x as i32 - 16,
                    y: y - 16,
                    width: 33,
                    height: 33
                }
                .fits_circle(336));
            }
        }
        four_lane_scale_segment(usize::MAX, |_, _| panic!("invalid segment"));
    }

    #[test]
    fn chunked_linear_scale_matches_complete_raster_exactly() {
        let mut complete = Vec::new();
        linear_scale(|p, c| complete.push((p, c)));
        let mut chunked = Vec::new();
        for start in (0..22).step_by(4) {
            let before = chunked.len();
            for segment in start..(start + 4).min(22) {
                linear_scale_segment(segment, |p, c| chunked.push((p, c)));
            }
            assert!(chunked.len() - before <= 600);
        }
        assert_eq!(chunked, complete);
        linear_scale_segment(usize::MAX, |_, _| panic!("invalid segment"));
    }
    #[test]
    fn linear_view_is_small_circular_safe_and_matches_cursor_mapping() {
        let mut count = 0;
        linear_scale(|p, _| {
            assert!((p.x - 360).pow(2) + (p.y - 360).pow(2) < 336 * 336);
            count += 1;
        });
        assert!(count < 1000);
        assert_eq!(axis(-50, -50, 50, 152, 568), Some(152));
        assert_eq!(axis(0, -50, 50, 152, 568), Some(360));
        assert_eq!(axis(50, -50, 50, 152, 568), Some(568));
    }
    #[test]
    fn transforms_cover_both_targets_without_aliases() {
        for (width, rotate) in [(1280, false), (720, true)] {
            let mut used = vec![false; width as usize * 720];
            for y in 0..720 {
                for x in 0..720 {
                    let address = physical(Point { x, y }, width, 720, rotate).unwrap();
                    assert!(!used[address]);
                    used[address] = true;
                }
            }
        }
        assert_eq!(physical(Point { x: 0, y: 0 }, 1280, 720, false), Some(280));
        assert_eq!(physical(Point { x: 0, y: 0 }, 720, 720, true), Some(719));
        assert!(physical(Point { x: -1, y: 0 }, 720, 720, false).is_none());
    }
    #[test]
    fn lines_are_bounded_in_every_direction() {
        let center = Point { x: 360, y: 360 };
        for target in [
            Point { x: 0, y: 0 },
            Point { x: 719, y: 719 },
            Point { x: 0, y: 719 },
            Point { x: 719, y: 0 },
            center,
        ] {
            for (a, b) in [(center, target), (target, center)] {
                let mut points = Vec::new();
                assert!(line(a, b, 9, |p, c| {
                    assert!(p.inside());
                    assert_eq!(c, 9);
                    points.push(p);
                }));
                assert_eq!(points[0], a);
                assert_eq!(*points.last().unwrap(), b);
                assert!(points.len() <= 720);
            }
        }
        assert!(!line(
            center,
            Point { x: i32::MAX, y: 0 },
            9,
            |_, _| panic!()
        ));
    }
    #[test]
    fn reusable_instrument_layouts_fit_circle_and_have_bounded_grids() {
        // Four linear tuning lanes, calibration plot, quantizer octave table.
        for rect in [
            Rect {
                x: 152,
                y: 168,
                width: 416,
                height: 80,
            },
            Rect {
                x: 152,
                y: 272,
                width: 416,
                height: 80,
            },
            Rect {
                x: 152,
                y: 376,
                width: 416,
                height: 80,
            },
            Rect {
                x: 152,
                y: 480,
                width: 416,
                height: 80,
            },
            Rect {
                x: 152,
                y: 168,
                width: 416,
                height: 384,
            },
        ] {
            assert!(rect.fits_circle(336));
            let mut count = 0;
            assert!(grid(rect, 12, 8, 9, |p, _| {
                assert!(p.inside());
                count += 1;
            }));
            assert!(count <= 66 * 720);
            assert!(rectangle(rect, 9, |_, _| {}));
        }
        assert!(!Rect {
            x: 0,
            y: 0,
            width: 720,
            height: 720
        }
        .fits_circle(336));
    }
    #[test]
    fn graph_mapping_saturates_and_handles_extreme_measurements() {
        assert_eq!(axis(i32::MIN, i32::MIN, i32::MAX, 100, 600), Some(100));
        assert_eq!(axis(i32::MAX, i32::MIN, i32::MAX, 100, 600), Some(600));
        assert_eq!(axis(0, -50, 50, 600, 100), Some(350));
        assert_eq!(axis(100, -50, 50, 100, 600), Some(600));
        assert_eq!(axis(0, 1, 1, 100, 600), None);
    }

    #[test]
    fn calibration_error_makes_small_deviations_visible_and_clamps_safely() {
        let rect = CALIBRATION_PLOT;
        assert!(rect.fits_circle(336));
        // Production text starts at x=90 with a 12-pixel cell pitch. The
        // sidebar begins at column 31 and must not touch the plot border.
        let sidebar = Rect { x: 90 + 31 * 12, y: 176, width: 168, height: 224 };
        assert!(sidebar.fits_circle(336));
        assert!(rect.x + rect.width as i32 + 24 < sidebar.x);
        let first = calibration_error_point(rect, -5_000_000, 0,
            -5_000_000, 0, -5_000_000, 5_000_000, 20_000).unwrap();
        let ideal = calibration_error_point(rect, 5_000_000, 12_000_000,
            -5_000_000, 0, -5_000_000, 5_000_000, 20_000).unwrap();
        let sharp = calibration_error_point(rect, 5_000_000, 12_005_000,
            -5_000_000, 0, -5_000_000, 5_000_000, 20_000).unwrap();
        assert_eq!(first.x, 154);
        assert_eq!(ideal.x, 429);
        assert!(first.y > ideal.y);
        assert!(sharp.y < ideal.y);
        let flat = calibration_error_point(rect, 5_000_000, 11_995_000,
            -5_000_000, 0, -5_000_000, 5_000_000, 20_000).unwrap();
        assert!(flat.y > ideal.y);
        assert_eq!(calibration_ideal_y(rect, -5_000_000, -5_000_000, 5_000_000),
            Some(first.y));
        assert_eq!(calibration_error_mc(1_000_000, 1_198_000, 0, 0), -2_000);
        assert!(calibration_error_point(rect, 0, 0, 0, 0, 0, 0, 0).is_none());
    }

    #[test]
    fn provisional_calibration_trace_keeps_fixed_voltage_axis() {
        let rect = CALIBRATION_PLOT;
        let first = live_calibration_point(rect, -3_000_000, 1_000_000, -3_000_000, 1_000_000,
            -5_000_000, 8_000_000)
            .unwrap();
        let next = live_calibration_point(rect, -2_000_000, 2_205_000, -3_000_000, 1_000_000,
            -5_000_000, 8_000_000)
            .unwrap();
        let later = live_calibration_point(rect, 1_000_000, 5_798_000, -3_000_000, 1_000_000,
            -5_000_000, 8_000_000)
            .unwrap();
        assert!(rect.x < first.x && first.x < next.x && next.x < later.x);
        assert_eq!(first.y, calibration_ideal_y(rect, -3_000_000,
            -5_000_000, 8_000_000).unwrap());
        assert!(next.y < calibration_ideal_y(rect, -2_000_000,
            -5_000_000, 8_000_000).unwrap());
        assert!(later.y > calibration_ideal_y(rect, 1_000_000,
            -5_000_000, 8_000_000).unwrap());
        assert_eq!(first, live_calibration_point(rect, -3_000_000, 1_000_000,
            -3_000_000, 1_000_000, -5_000_000, 8_000_000).unwrap());
        assert_eq!(live_calibration_point(rect, i32::MAX, i32::MAX,
            -3_000_000, 1_000_000, -5_000_000, 8_000_000).unwrap(),
            Point { x: 429, y: 252 });
    }

    #[test]
    fn pitch_and_error_views_use_the_same_measurements_without_faking_pitch() {
        let rect = CALIBRATION_PLOT;
        let anchor = (0, 6_000_000); // C4 at 0 V
        let ideal = calibration_pitch_point(rect, 1_000_000, 7_200_000,
            anchor.0, anchor.1, -5_000_000, 8_000_000).unwrap();
        let sharp = calibration_pitch_point(rect, 1_000_000, 7_205_000,
            anchor.0, anchor.1, -5_000_000, 8_000_000).unwrap();
        assert_eq!(ideal.x, sharp.x);
        assert!(sharp.y <= ideal.y);
        assert_eq!(ideal.y, calibration_pitch_y(rect,
            calibration_ideal_mc(1_000_000, anchor.0, anchor.1),
            anchor.0, anchor.1, -5_000_000, 8_000_000).unwrap());

        let error_ideal = calibration_error_only_point(rect, 1_000_000, 7_200_000,
            anchor.0, anchor.1, -5_000_000, 8_000_000, 20_000).unwrap();
        let error_sharp = calibration_error_only_point(rect, 1_000_000, 7_205_000,
            anchor.0, anchor.1, -5_000_000, 8_000_000, 20_000).unwrap();
        assert_eq!(error_ideal.x, ideal.x);
        assert_eq!(error_sharp.x, ideal.x);
        assert!(error_sharp.y < error_ideal.y);
    }

    #[test]
    fn error_axis_expands_before_clipping_real_tracking_deviation() {
        assert_eq!(calibration_error_span_mc(0), 20_000);
        assert_eq!(calibration_error_span_mc(20_000), 50_000);
        assert_eq!(calibration_error_span_mc(80_000), 100_000);
        assert_eq!(calibration_error_span_mc(300_000), 500_000);
        assert_eq!(calibration_error_span_mc(i64::MAX), 20_000_000);
    }

    #[test]
    fn tracking_strip_shows_local_slope_and_leaves_missing_intervals_blank() {
        assert_eq!(calibration_tracking_color(0, 0, 100_000, 120_000), Some(0xD9));
        assert_eq!(calibration_tracking_color(0, 0, 100_000, 130_000), Some(0xD2));
        assert_eq!(calibration_tracking_color(0, 0, 100_000, 150_000), Some(0xD0));
        assert_eq!(calibration_tracking_color(0, 0, 126_000, 151_200), None);
        assert_eq!(calibration_tracking_color(0, 0, 0, 0), None);
        assert_eq!(calibration_tracking_color(100_000, 120_000, 0, 0), None);
    }
}
