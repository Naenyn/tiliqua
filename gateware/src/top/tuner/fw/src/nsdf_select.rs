//! NSDF key-maxima selector. No heap or score-sized CPU buffer.
//! Reads a stable score frame twice, then at most seven three-neighbor searches.
//! Guarded later-peak fallback is our extension, not the paper's algorithm.

#[derive(Clone, Copy, Debug)]
pub struct Estimate {
    pub hz: f32,
    pub clarity: f32,
    pub qualified: bool,
    pub unrefined_hz: f32,
}

#[derive(Clone, Copy)]
struct Peak {
    lag: i32,
    height: i32,
} // Q20 samples, Q20 NSDF

pub fn select_frame(
    read: impl FnMut(usize) -> i32,
    low: bool,
    energy: u64,
    scaled: bool,
    clipped: bool,
) -> Option<Estimate> {
    // Exactly the existing >2-count RMS gate, before expensive score access.
    // Scaling halves samples, so unscale energy by four without multiplying it.
    let samples = 674;
    // A low-rate decimator can report internal saturation on a hot modular
    // signal even when its emitted, scaled waveform remains periodic and
    // bounded. Let the normal score/confidence policy judge that waveform.
    // Native clipping still means the ADC-side evidence is untrustworthy.
    if (!low && clipped) || energy <= samples * (if scaled { 1 } else { 4 }) {
        return None;
    }
    select(read, low)
}

fn peak(k: usize, a: i32, b: i32, c: i32) -> Peak {
    let curvature = a - 2 * b + c;
    let shift = if curvature < 0 {
        let difference = a - c;
        let fraction = fraction19(difference.unsigned_abs(), (-curvature) as u32) as i32;
        if difference > 0 {
            -fraction
        } else {
            fraction
        }
    } else {
        0
    };
    // At the parabola's vertex, height = b + (c-a)*shift/4.
    // Q20 shift quantization and truncation cost less than two height units.
    let correction = (c - a) as i64 * shift as i64;
    // A local maximum makes this product nonnegative. Explicit shifting keeps
    // the size-optimized RV32 build from calling __divdi3 for division by 2^22.
    debug_assert!(correction >= 0);
    let height = b + (correction >> 22) as i32;
    Peak {
        lag: ((k as i32) << 20) + shift,
        height,
    }
}

fn fraction19(mut numerator: u32, denominator: u32) -> u32 {
    // Exact (numerator << 19) / denominator without software 64-bit division.
    // A local maximum guarantees numerator <= denominator <= 4 * 2^20.
    // Each nine-bit step fits u32, including the maximum denominator.
    let mut result = 0;
    for shift in [9, 9, 1] {
        let scaled = numerator << shift;
        let quotient = scaled / denominator;
        numerator = scaled - quotient * denominator;
        result = (result << shift) | quotient;
    }
    result
}

fn peaks(read: &mut impl FnMut(usize) -> i32, last: usize, mut visit: impl FnMut(Peak) -> bool) {
    let mut a = read(0);
    let mut b = read(1);
    let mut skipped = false;
    let mut best: Option<(usize, i32, i32, i32)> = None;
    for k in 1..last {
        let c = read(k + 1);
        if b <= 0 {
            skipped = true;
            if let Some((k, a, b, c)) = best.take() {
                if visit(peak(k, a, b, c)) {
                    return;
                }
            }
        } else if skipped && b >= a && b > c && best.map_or(true, |(_, _, height, _)| b > height) {
            best = Some((k, a, b, c));
        }
        a = b;
        b = c;
    }
    if let Some((k, a, b, c)) = best {
        visit(peak(k, a, b, c));
    }
}

pub fn select(read: impl FnMut(usize) -> i32, low: bool) -> Option<Estimate> {
    select_with_limit(read, low, 621)
}

// Explicit limit also lets host tests replay historical short captures through
// the CURRENT policy, without retaining another detector in the bitstream.
pub fn select_with_limit(
    mut read: impl FnMut(usize) -> i32,
    low: bool,
    last: usize,
) -> Option<Estimate> {
    let (fs, min, max) = if low {
        (6000_i64, 20_i64, 1500_i64)
    } else {
        (192000_i64, 600_i64, 20000_i64)
    };
    // Same one-ppm endpoint allowance, evaluated once using exact integers.
    let numerator = fs * 1048576 * 1000000;
    let min_lag = ((numerator + max * 1000001 - 1) / (max * 1000001)) as i32;
    let max_lag = (numerator / (min * 999999)) as i32;
    let in_range = |p: Peak| p.lag >= min_lag && p.lag <= max_lag;
    let mut highest = 0;
    // Extra lags only refine an already established period. Letting
    // their short-overlap peaks compete for initial selection can reject
    // otherwise trackable moving tones or choose a spurious subharmonic.
    let primary_last = last.min(if low { 301 } else { 321 });
    // Choose the first strong key maximum BEFORE checking the bank's range.
    // Filtering peaks first can turn a 1520-Hz tone into a qualified 760-Hz
    // low-bank result: its real period is excluded, but its double survives.
    // Reject an out-of-band selection instead of inventing a subharmonic.
    peaks(&mut read, primary_last, |p| {
        highest = highest.max(p.height);
        false
    });
    if highest <= 0 {
        return None;
    }
    let mut chosen = None;
    peaks(&mut read, primary_last, |p| {
        // At only 3–4 low-rate samples/cycle, parabolic peak height can
        // understate a real out-of-band period below the relative 90% cutoff.
        // If it still clears the absolute confidence gate, do not skip it
        // and turn a later multiple into an apparently valid low-bank tone.
        // Reject this ambiguous bank; native selection and the cross-bank
        // disagreement guard remain unchanged. Weak early peaks may still
        // be skipped, and this never accepts a previously rejected pitch.
        if low && p.height >= 838861 && !in_range(p) {
            return true;
        }
        if p.height * 10 >= 9 * highest {
            chosen = Some(p);
            true
        } else {
            false
        }
    });
    let mut p = chosen?;
    if !in_range(p) {
        return None;
    }
    let original_lag = p.lag;
    let qualified = p.height >= 838861; // ceil(0.8 * 2^20)
    if qualified {
        let mut refined: Option<(i32, i32)> = None;
        let largest = 8.min(((last - 2) << 20) / p.lag as usize);
        for multiple in (2..=largest).rev() {
            let center = ((p.lag * multiple as i32 + 524288) >> 20) as usize;
            let mut best: Option<(usize, i32, i32, i32)> = None;
            for k in center.saturating_sub(1).max(1)..(center + 2).min(last) {
                let a = read(k - 1);
                let b = read(k);
                let c = read(k + 1);
                if b >= a && b > c && best.map_or(true, |(_, _, height, _)| b > height) {
                    best = Some((k, a, b, c));
                }
            }
            if let Some((k, a, b, c)) = best {
                let candidate = peak(k, a, b, c);
                let lag = candidate.lag / multiple as i32;
                let old = original_lag as i64;
                let new = lag as i64;
                // 2^(10/1200), represented to nine decimal places.
                if candidate.height >= 838861
                    && candidate.height * 10 >= 9 * p.height
                    && new * max >= fs * 1048576
                    && new * min <= fs * 1048576
                    && old * 1005792941 >= new * 1000000000
                    && old * 1000000000 <= new * 1005792941
                {
                    // Small alternating-cycle components in either bank
                    // can bias odd multiples. Prefer the strongest repeating
                    // interval; equal heights retain the longer interval.
                    if refined.map_or(true, |(_, height)| candidate.height > height) {
                        refined = Some((lag, candidate.height));
                    }
                }
            }
        }
        if let Some((lag, height)) = refined {
            p = Peak {
                lag,
                height: p.height.min(height),
            };
        }
    }
    // Convert only the final result for existing diagnostic formatting.
    Some(Estimate {
        hz: (fs * 1048576) as f32 / p.lag as f32,
        clarity: p.height as f32 / 1048576.0,
        qualified,
        unrefined_hz: (fs * 1048576) as f32 / original_lag as f32,
    })
}

#[cfg(test)]
mod tests {
    #[test]
    fn low_rate_clipping_does_not_veto_a_strong_period() {
        let mut scores = [0_i32; 622];
        scores[22] = 1026392; // Captured hot C&P2-like low-bank confidence.
        let accepted = super::select_frame(|k| scores[k], true, 674 * 1000, true, true).unwrap();
        assert!(accepted.qualified);
        assert!((accepted.hz - 272.7273).abs() < 0.01);
        assert!(super::select_frame(|k| scores[k], false, 674 * 1000, true, true).is_none());
    }

    #[test]
    fn strong_out_of_band_peak_is_not_replaced_by_its_multiple() {
        for (low, first) in [(true, 3), (false, 8)] {
            let mut scores = [0_i32; 622];
            scores[first] = 1048576;
            scores[2 * first] = 1048576;
            assert!(super::select(|k| scores[k], low).is_none());
            // Weak early maxima still do not veto a stronger, valid period.
            scores[first] = 524288;
            let accepted = super::select(|k| scores[k], low).unwrap();
            assert!(accepted.qualified);
            assert_eq!(accepted.hz, if low { 1000.0 } else { 12000.0 });
        }
    }

    #[test]
    fn qualified_outside_peak_below_relative_cutoff_still_vetoes_low_bank() {
        let mut scores = [0_i32; 622];
        scores[3] = 838861; // Absolute confidence passes, relative 90% does not.
        scores[6] = 1048576;
        assert!(super::select(|k| scores[k], true).is_none());
        scores[3] = 838860; // A weak early peak is not an out-of-band veto.
        assert!(super::select(|k| scores[k], true).unwrap().qualified);
        // Native-bank policy keeps its existing relative peak cutoff.
        scores = [0; 622];
        scores[8] = 838861;
        scores[16] = 1048576;
        assert!(super::select(|k| scores[k], false).unwrap().qualified);
    }

    #[test]
    fn fractional_division_matches_wide_reference() {
        for denominator in [1, 2, 3, 7, 511, 512, 513, 65535, 1048576, 2097152, 4194304] {
            for numerator in [0, 1, denominator / 2, denominator - 1, denominator] {
                assert_eq!(
                    super::fraction19(numerator, denominator),
                    (((numerator as u64) << 19) / denominator as u64) as u32
                );
            }
        }
        let mut state = 731_u32;
        for _ in 0..100000 {
            state = state.wrapping_mul(1664525).wrapping_add(1013904223);
            let denominator = 1 + (state & 4194303);
            state = state.wrapping_mul(1664525).wrapping_add(1013904223);
            let numerator = state % (denominator + 1);
            assert_eq!(
                super::fraction19(numerator, denominator),
                (((numerator as u64) << 19) / denominator as u64) as u32
            );
        }
    }

    #[test]
    fn integer_peak_matches_wide_reference() {
        let mut state = 917_u32;
        for _ in 0..10000 {
            state = state.wrapping_mul(1664525).wrapping_add(1013904223);
            let b = (state & 1048575) as i32;
            state = state.wrapping_mul(1664525).wrapping_add(1013904223);
            let a = (state % (b as u32 + 1048577)) as i32 - 1048576;
            state = state.wrapping_mul(1664525).wrapping_add(1013904223);
            let c = (state % (b as u32 + 1048576)) as i32 - 1048576;
            let shift = (((a - c) as i64 * 524288) / (a - 2 * b + c) as i64) as i32;
            let expected = b + (((c - a) as i64 * shift as i64) / 4194304) as i32;
            let p = super::peak(10, a, b, c);
            assert_eq!(p.lag, (10 << 20) + shift);
            assert_eq!(p.height, expected);
        }
    }
}
