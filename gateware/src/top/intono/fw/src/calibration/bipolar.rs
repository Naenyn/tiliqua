//! Signed voltage planning and encoding for the live bipolar adapter.
//!
//! Visit zero first, explore downwards, return to zero, then explore upwards.
//! Each direction may terminate independently when pitch is no longer usable.
//! Storage must sort accepted measurements by voltage before making a Profile.

pub const MIN_UV: i32 = -5_000_000;
/// Normal bipolar acquisition boundary.  Positive-only inputs may use the
/// wider hardware-safe ceiling below after that behavior is measured.
pub const BIPOLAR_MAX_UV: i32 = 5_000_000;
pub const MAX_UV: i32 = 8_000_000;
pub const UV_PER_COUNT: i32 = 250;
pub const MAX_POINTS: usize = 121;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Density {
    QuarterVolt,
    Semitone,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Direction {
    Down,
    Up,
}

/// Number of intervals from zero to either edge; no retained voltage array.
pub fn intervals(density: Density) -> usize {
    match density {
        Density::QuarterVolt => 20,
        Density::Semitone => 60,
    }
}

/// Intervals in an automatically selected 0..+8 V plan.  Both densities keep
/// their nominal spacing; semitone acquisition therefore needs only 97 points.
pub fn positive_intervals(density: Density) -> usize {
    match density {
        Density::QuarterVolt => 32,
        Density::Semitone => 96,
    }
}

/// Number of intervals in the hardware-safe -5 V .. +8 V characterization
/// pass.  Characterization always visits the complete range; deciding which
/// contiguous part is suitable for a calibration profile happens afterwards.
pub fn full_intervals(density: Density) -> usize {
    intervals(density) + positive_intervals(density)
}

pub fn full_voltage(density: Density, index: usize) -> Option<i32> {
    let negative = intervals(density);
    if index <= negative {
        voltage(density, Direction::Down, negative - index)
    } else {
        positive_voltage(density, index - negative)
    }
}

/// Nominal 1 V/oct spacing, rounded symmetrically to representable DAC counts.
/// This describes voltage spacing, not a promise about oscillator tracking.
pub fn voltage(density: Density, direction: Direction, index: usize) -> Option<i32> {
    let n = intervals(density);
    if index > n {
        return None;
    }
    let counts = ((index * 20_000 + n / 2) / n) as i32;
    Some(counts * UV_PER_COUNT * if direction == Direction::Down { -1 } else { 1 })
}

pub fn positive_voltage(density: Density, index: usize) -> Option<i32> {
    let n = positive_intervals(density);
    if index > n {
        return None;
    }
    let counts = ((index * 32_000 + n / 2) / n) as i32;
    Some(counts * UV_PER_COUNT)
}

/// Signed two's-complement payload for a bipolar output command.
/// Quantize to nearest count, ties away from zero; reject rather than clamp.
pub fn encode_voltage(uv: i32) -> Option<u16> {
    if !(MIN_UV..=BIPOLAR_MAX_UV).contains(&uv) {
        return None;
    }
    encode_hardware_voltage(uv)
}

/// Wider guarded INTONO output range, used by profiles and route playback.
/// Acquisition/verification and nominal route fallback share these limits;
/// `encode_voltage` retains the conservative +/-5 V helper for other callers.
pub fn encode_profile_voltage(uv: i32) -> Option<u16> {
    if !(MIN_UV..=MAX_UV).contains(&uv) {
        return None;
    }
    encode_hardware_voltage(uv)
}

fn encode_hardware_voltage(uv: i32) -> Option<u16> {
    let magnitude = (uv.abs() + UV_PER_COUNT / 2) / UV_PER_COUNT;
    let counts = if uv < 0 { -magnitude } else { magnitude };
    Some(counts as i16 as u16)
}

/// Decode and validate exactly the same bounds intended for the hardware guard.
pub fn decode_voltage(bits: u16) -> Option<i32> {
    let uv = bits as i16 as i32 * UV_PER_COUNT;
    if (MIN_UV..=MAX_UV).contains(&uv) {
        Some(uv)
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn plans_have_unique_sorted_union_and_exact_symmetric_endpoints() {
        for density in [Density::QuarterVolt, Density::Semitone] {
            let n = intervals(density);
            assert_eq!(
                2 * n + 1,
                if density == Density::Semitone {
                    MAX_POINTS
                } else {
                    41
                }
            );
            assert_eq!(voltage(density, Direction::Down, n), Some(MIN_UV));
            assert_eq!(voltage(density, Direction::Up, n), Some(BIPOLAR_MAX_UV));
            assert_eq!(voltage(density, Direction::Up, n + 1), None);
            let mut previous = 0;
            for i in 0..=n {
                let up = voltage(density, Direction::Up, i).unwrap();
                assert_eq!(voltage(density, Direction::Down, i), Some(-up));
                assert_eq!(up % UV_PER_COUNT, 0);
                if i > 0 {
                    assert!(up > previous);
                }
                assert_eq!(decode_voltage(encode_voltage(up).unwrap()), Some(up));
                assert_eq!(decode_voltage(encode_voltage(-up).unwrap()), Some(-up));
                previous = up;
            }
        }
    }
    #[test]
    fn positive_only_plan_reaches_eight_volts_at_the_same_density() {
        for density in [Density::QuarterVolt, Density::Semitone] {
            let n = positive_intervals(density);
            assert_eq!(n + 1, if density == Density::Semitone { 97 } else { 33 });
            assert_eq!(positive_voltage(density, 0), Some(0));
            assert_eq!(positive_voltage(density, n), Some(MAX_UV));
            assert_eq!(positive_voltage(density, n + 1), None);
            let mut previous = -1;
            for i in 0..=n {
                let uv = positive_voltage(density, i).unwrap();
                assert!(uv > previous);
                assert_eq!(uv % UV_PER_COUNT, 0);
                assert_eq!(
                    decode_voltage(encode_profile_voltage(uv).unwrap()),
                    Some(uv)
                );
                previous = uv;
            }
        }
    }
    #[test]
    fn characterization_plan_covers_the_complete_safe_range_upward() {
        for density in [Density::QuarterVolt, Density::Semitone] {
            let n = full_intervals(density);
            assert_eq!(full_voltage(density, 0), Some(MIN_UV));
            assert_eq!(full_voltage(density, n), Some(MAX_UV));
            assert_eq!(full_voltage(density, n + 1), None);
            let mut previous = MIN_UV - 1;
            for index in 0..=n {
                let uv = full_voltage(density, index).unwrap();
                assert!(uv > previous);
                previous = uv;
            }
        }
    }
    #[test]
    fn all_signed_payloads_obey_output_bounds() {
        for bits in 0..=u16::MAX {
            let counts = bits as i16 as i32;
            assert_eq!(
                decode_voltage(bits).is_some(),
                (-20_000..=32_000).contains(&counts)
            );
            if let Some(uv) = decode_voltage(bits) {
                assert_eq!(encode_profile_voltage(uv), Some(bits));
            }
        }
        for uv in [i32::MIN, MIN_UV - 1, MAX_UV + 1, i32::MAX] {
            assert_eq!(encode_voltage(uv), None);
        }
    }
    #[test]
    fn rounding_is_symmetric_and_bounded_near_every_dac_count() {
        for count in -20_000..=32_000 {
            for offset in [-126, -125, -124, -1, 0, 1, 124, 125, 126] {
                let uv = count * UV_PER_COUNT + offset;
                if !(MIN_UV..=MAX_UV).contains(&uv) {
                    continue;
                }
                let decoded = decode_voltage(encode_profile_voltage(uv).unwrap()).unwrap();
                assert!((decoded - uv).abs() <= 125);
                if (MIN_UV..=MAX_UV).contains(&-uv) {
                    assert_eq!(
                        decode_voltage(encode_profile_voltage(-uv).unwrap()),
                        Some(-decoded)
                    );
                }
            }
        }
    }
}
