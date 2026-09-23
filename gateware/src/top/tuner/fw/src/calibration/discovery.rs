//! Conservative advice, never a claim about an unmeasured oscillator range.
use super::Profile;

/// Measured control-voltage slope across the accepted profile. This describes
/// the observed oscillator configuration; it does not assume one V/oct.
pub fn millivolts_per_octave(p: &Profile) -> Option<i32> {
    let points = p.points();
    if points.len() < 2 {
        return None;
    }
    let low = points[0];
    let high = points[points.len() - 1];
    let pitch_span = (high.millicents - low.millicents) as i64;
    if pitch_span <= 0 {
        return None;
    }
    let voltage_span = (high.microvolts - low.microvolts) as i64;
    Some(((voltage_span * 1_200_000) / (pitch_span * 1_000)) as i32)
}

/// Tolerate normal analogue error while still naming half/double-rate CV
/// responses instead of silently presenting them as conventional V/oct.
pub fn nonstandard_response(p: &Profile) -> bool {
    millivolts_per_octave(p).is_some_and(|mv| !(800..=1_250).contains(&mv))
}

pub fn advice(p: &Profile) -> &'static str {
    let points = p.points();
    if points.len() < 2 {
        return "INSUFFICIENT RANGE";
    }
    let low = points[0];
    let high = points[points.len() - 1];
    // Rounded 20 Hz and 20 kHz positions, with a semitone margin. Only suggest
    // shifting when the missing end actually reached our voltage boundary.
    if low.microvolts <= -4_999_000 && low.millicents > 1_650_000 && high.millicents >= 13_400_000 {
        "TRY LOWER TUNING; THEN RESCAN"
    } else if high.microvolts >= 4_999_000
        && high.millicents < 13_400_000
        && low.millicents <= 1_650_000
    {
        "TRY HIGHER TUNING; THEN RESCAN"
    } else if p.limited_low && low.microvolts >= 0 {
        // A curve beginning above zero may be a positive-only CV input or an
        // oscillator tuned below our 20-Hz measurement floor. The scan alone
        // cannot distinguish them, so report only the measured behavior.
        "MEASURED RANGE STARTS ABOVE 0V; LOW REQUESTS CLAMP"
    } else if p.limited_low || p.limited_high {
        "LIMITED RANGE; NO SHIFT ADVISED"
    } else {
        "FULL CV SWEEP; REVIEW PITCH RANGE"
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use crate::oscillator_calibration::Point;
    fn profile(lo: i32, hi: i32, lp: i32, hp: i32) -> Profile {
        let mut p = Profile::new("test", -5_000_000, 8_000_000).unwrap();
        p.push(Point {
            microvolts: lo,
            millicents: lp,
        })
        .unwrap();
        p.push(Point {
            microvolts: hi,
            millicents: hp,
        })
        .unwrap();
        p
    }
    #[test]
    fn advice_requires_measured_voltage_boundary_not_just_missing_notes() {
        let p = profile(-5_000_000, 4_000_000, 2_000_000, 13_500_000);
        assert!(advice(&p).starts_with("TRY LOWER"));
        let p = profile(-4_000_000, 5_000_000, 1_500_000, 12_000_000);
        assert!(advice(&p).starts_with("TRY HIGHER"));
        let mut p = profile(-4_000_000, 3_000_000, 2_000_000, 13_500_000);
        p.limited_low = true;
        assert_eq!(advice(&p), "LIMITED RANGE; NO SHIFT ADVISED");
    }
    #[test]
    fn positive_only_cv_input_is_reported_without_retuning_advice() {
        let mut p = profile(83_250, 5_000_000, 2_500_000, 8_500_000);
        p.limited_low = true;
        assert_eq!(
            advice(&p),
            "MEASURED RANGE STARTS ABOVE 0V; LOW REQUESTS CLAMP"
        );
    }
    #[test]
    fn response_slope_is_descriptive_and_flags_only_large_deviations() {
        let p = profile(0, 2_000_000, 3_000_000, 5_400_000);
        assert_eq!(millivolts_per_octave(&p), Some(1000));
        assert!(!nonstandard_response(&p));
        let p = profile(0, 6_000_000, 3_000_000, 6_600_000);
        assert_eq!(millivolts_per_octave(&p), Some(2000));
        assert!(nonstandard_response(&p));
    }
}
