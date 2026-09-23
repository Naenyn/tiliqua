//! Shared precision pitch conversion for tuning, acquisition and verification.
//! No platform-dependent math trait calls: host tests execute this same code.

fn log2_positive(mut x: f32) -> f32 {
    if !x.is_finite() || x <= 0.0 {
        return f32::NAN;
    }
    let mut adjustment = 0;
    if x < f32::MIN_POSITIVE {
        x *= 8388608.0;
        adjustment = -23;
    }
    let bits = x.to_bits();
    let mut exponent = ((bits >> 23) & 255) as i32 - 127 + adjustment;
    let mut mantissa = f32::from_bits((bits & 0x7fffff) | 0x3f800000);
    // Center around one, so |z| <= 0.171573. Five atanh terms
    // leave < 1.1e-9 absolute log2 truncation error; f32 dominates.
    if mantissa > core::f32::consts::SQRT_2 {
        mantissa *= 0.5;
        exponent += 1;
    }
    let z = (mantissa - 1.0) / (mantissa + 1.0);
    let z2 = z * z;
    let series = z * (1.0 + z2 * (1.0 / 3.0 + z2 * (1.0 / 5.0 + z2 * (1.0 / 7.0 + z2 / 9.0))));
    exponent as f32 + 2.0 * core::f32::consts::LOG2_E * series
}

/// Internal equal-tempered semitone coordinate; A4 is index 69.
pub fn semitones(hz: f32, reference_hz: f32) -> f32 {
    if !hz.is_finite() || !reference_hz.is_finite() || hz <= 0.0 || reference_hz <= 0.0 {
        return f32::NAN;
    }
    69.0 + 12.0 * log2_positive(hz / reference_hz)
}

pub fn millicents(hz: f32, reference_hz: f32) -> i32 {
    let scaled = semitones(hz, reference_hz) * 100000.0;
    (scaled + if scaled >= 0.0 { 0.5 } else { -0.5 }) as i32
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn dense_frequency_and_reference_sweep() {
        let mut worst = 0.0f64;
        for reference in (400..=480).step_by(5) {
            for n in 0..=100000 {
                let hz = (10.0 * 2400.0f64.powf(n as f64 / 100000.0)) as f32;
                let expected = 69.0 + 12.0 * (hz as f64 / reference as f64).log2();
                let error = (semitones(hz, reference as f32) as f64 - expected).abs() * 100.0;
                worst = worst.max(error);
                assert!(error < 0.002, "{hz} Hz ref {reference}: {error} cents");
                assert!(
                    (millicents(hz, reference as f32) as f64 / 1000.0 - expected * 100.0).abs()
                        < 0.003
                );
            }
        }
        println!("Worst pitch-conversion error: {worst:.6} cents");
    }
    #[test]
    fn reported_problem_and_octave_boundaries() {
        for hz in [
            329.62756, 349.22824, 357.8, 369.99442, 391.99544, 415.3047, 439.999, 440.0, 440.001,
            466.16376, 523.2511,
        ] {
            let expected = 69.0 + 12.0 * (hz as f64 / 440.0).log2();
            assert!((semitones(hz, 440.0) as f64 - expected).abs() * 100.0 < 0.002);
        }
        assert!((semitones(357.8, 440.0) - 65.4198).abs() < 0.00002);
        for octave in -5..=5 {
            let hz = 440.0 * 2.0f32.powi(octave);
            assert_eq!(semitones(hz, 440.0), 69.0 + 12.0 * octave as f32);
        }
    }
    #[test]
    fn invalid_values_and_subnormal_logarithms() {
        for bad in [0.0, -1.0, f32::NAN, f32::INFINITY] {
            assert!(semitones(bad, 440.0).is_nan());
            assert!(semitones(440.0, bad).is_nan());
        }
        assert_eq!(log2_positive(f32::from_bits(1)), -149.0);
    }
}
