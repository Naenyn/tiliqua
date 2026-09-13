//! Allocation-free scale math, independent of storage, MIDI, and DAC mapping.
//! Intervals are thousandths of a cent relative to a separately supplied root.
//! Degree zero is implicit in imported Scala files, but explicit in this table.
pub const MAX_DEGREES: usize = 128;

#[derive(Debug, PartialEq)]
pub enum Error { Empty, TooManyDegrees, InvalidPeriod, InvalidDegrees, Overflow }

/// A validated borrowed table. The importer owns storage; channels can share it.
pub struct Scale<'a> { degrees: &'a [i32], period: i32 }

impl<'a> Scale<'a> {
    pub fn new(degrees: &'a [i32], period: i32) -> Result<Self, Error> {
        if degrees.is_empty() { return Err(Error::Empty); }
        if degrees.len() > MAX_DEGREES { return Err(Error::TooManyDegrees); }
        if period <= 0 { return Err(Error::InvalidPeriod); }
        if degrees[0] != 0 || degrees.iter().any(|&d| d < 0 || d >= period)
            || degrees.windows(2).any(|w| w[0] >= w[1]) {
            return Err(Error::InvalidDegrees);
        }
        Ok(Self { degrees, period })
    }

    // The two degrees bracketing a pitch, including across period boundaries.
    fn bracket(&self, pitch: i64) -> (i64, i64) {
        let period = self.period as i64;
        let cycle = pitch.div_euclid(period) * period;
        let phase = pitch.rem_euclid(period);
        let mut lo = 0;
        let mut hi = self.degrees.len();
        while lo < hi {
            let mid = (lo + hi) / 2;
            if self.degrees[mid] as i64 <= phase { lo = mid + 1; }
            else { hi = mid; }
        }
        let lower = cycle + self.degrees[lo - 1] as i64;
        let upper = if lo == self.degrees.len() { cycle + period }
            else { cycle + self.degrees[lo] as i64 };
        (lower, upper)
    }

    /// Nearest degree, ties upward. Previous output is only retained if it is
    /// in this scale. Hysteresis extends each midpoint by at most five cents,
    /// capped at a quarter of that neighbor gap for dense microtonal scales.
    /// Root changes/scale changes should also clear the caller's history.
    pub fn quantize(&self, pitch: i32, root: i32, previous: Option<i32>) -> Result<i32, Error> {
        let relative = pitch as i64 - root as i64;
        if let Some(previous) = previous {
            let prev = previous as i64 - root as i64;
            let (degree, next) = self.bracket(prev);
            if degree == prev {
                let (before, _) = self.bracket(prev - 1);
                let down = prev - before;
                let up = next - prev;
                // Doubled arithmetic preserves half-millicent midpoints.
                if 2 * relative >= before + prev - 2 * (down / 4).min(5_000)
                    && 2 * relative <= prev + next + 2 * (up / 4).min(5_000) {
                    return Ok(previous);
                }
            }
        }
        let (lower, upper) = self.bracket(relative);
        let target = if relative - lower < upper - relative { lower } else { upper };
        i32::try_from(target + root as i64).map_err(|_| Error::Overflow)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_invalid_tables() {
        for (degrees, period) in [(&[][..], 1200), (&[1][..], 1200),
            (&[0, 0][..], 1200), (&[0, 1200][..], 1200),
            (&[0, -1][..], 1200), (&[0][..], 0)] {
            assert!(Scale::new(degrees, period).is_err());
        }
        assert!(Scale::new(&[0; 129], 1200).is_err());
    }
    #[test]
    fn chromatic_matches_existing_rounding_and_hysteresis() {
        let degrees: [i32; 12] = core::array::from_fn(|i| i as i32 * 100_000);
        let scale = Scale::new(&degrees, 1_200_000).unwrap();
        for pitch in (-12_000_000i32..12_000_000).step_by(137) {
            let expected = (pitch + 50_000).div_euclid(100_000) * 100_000;
            assert_eq!(scale.quantize(pitch, 0, None), Ok(expected));
        }
        assert_eq!(scale.quantize(55_000, 0, Some(0)), Ok(0));
        assert_eq!(scale.quantize(55_001, 0, Some(0)), Ok(100_000));
        assert_eq!(scale.quantize(-55_000, 0, Some(0)), Ok(0));
        assert_eq!(scale.quantize(-55_001, 0, Some(0)), Ok(-100_000));
    }
    #[test]
    fn non_octave_fractional_degrees_negative_pitches_and_root() {
        let scale = Scale::new(&[0, 190_195, 701_955], 1_901_955).unwrap();
        for cycle in -10..=10 {
            for degree in [0, 190_195, 701_955] {
                let target = cycle * 1_901_955 + degree + 23_456;
                assert_eq!(scale.quantize(target + 10, 23_456, None), Ok(target));
            }
        }
    }
    #[test]
    fn dense_degrees_do_not_get_swallowed_by_hysteresis() {
        let scale = Scale::new(&[0, 1_000, 2_000], 3_000).unwrap();
        assert_eq!(scale.quantize(750, 0, Some(0)), Ok(0));
        assert_eq!(scale.quantize(751, 0, Some(0)), Ok(1_000));
        assert_eq!(scale.quantize(1_000, 0, Some(123)), Ok(1_000));
    }
    #[test]
    fn maximum_table_and_integer_edges() {
        let degrees: [i32; 128] = core::array::from_fn(|i| i as i32 * 10_000);
        let scale = Scale::new(&degrees, 1_280_000).unwrap();
        assert_eq!(scale.quantize(1_275_000, 0, None), Ok(1_280_000));
        let scale = Scale::new(&[0], 100_000).unwrap();
        assert_eq!(scale.quantize(i32::MAX, i32::MAX, None), Ok(i32::MAX));
        assert_eq!(scale.quantize(i32::MIN, i32::MIN, None), Ok(i32::MIN));
        assert_eq!(scale.quantize(i32::MAX, 20_000, None), Err(Error::Overflow));
    }
    #[test]
    fn binary_search_matches_exhaustive_irregular_scale() {
        let degrees = [0, 17, 111, 350, 901];
        let scale = Scale::new(&degrees, 1_001).unwrap();
        for pitch in -5_000i32..=5_000 {
            let expected = (-6..=6).flat_map(|cycle|
                degrees.iter().map(move |degree| cycle * 1_001 + degree + 29))
                .min_by_key(|&target| ((target - pitch).abs(), -target)).unwrap();
            assert_eq!(scale.quantize(pitch, 29, None), Ok(expected));
        }
    }
}
