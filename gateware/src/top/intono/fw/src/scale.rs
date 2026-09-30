//! Allocation-free scale math, independent of storage, MIDI, and DAC mapping.
//! Intervals are thousandths of a cent relative to a separately supplied root.
//! Degree zero is implicit in imported Scala files, but explicit in this table.
pub const MAX_DEGREES: usize = 128;

/// Immutable presets shared by every channel. IDs are not a storage format.
pub fn preset(id: u8) -> Option<Scale<'static>> {
    let (degrees, period): (&[i32], i32) = match id {
        0 => (
            &[
                0, 100000, 200000, 300000, 400000, 500000, 600000, 700000, 800000, 900000, 1000000,
                1100000,
            ],
            1200000,
        ),
        1 => (
            &[0, 200000, 400000, 500000, 700000, 900000, 1100000],
            1200000,
        ),
        2 => (
            &[0, 200000, 300000, 500000, 700000, 800000, 1000000],
            1200000,
        ),
        3 => (&[0, 200000, 400000, 700000, 900000], 1200000),
        4 => (&[0, 300000, 500000, 700000, 1000000], 1200000),
        5 => (
            &[
                0, 50000, 100000, 150000, 200000, 250000, 300000, 350000, 400000, 450000, 500000,
                550000, 600000, 650000, 700000, 750000, 800000, 850000, 900000, 950000, 1000000,
                1050000, 1100000, 1150000,
            ],
            1200000,
        ),
        _ => return None,
    };
    Some(Scale { degrees, period })
}

#[derive(Debug, PartialEq)]
pub enum Error {
    Empty,
    TooManyDegrees,
    InvalidPeriod,
    InvalidDegrees,
    Overflow,
    InvalidFile,
}

/// Offline import envelope: magic TSC1, u16 count, u16 reserved=0, i32 period,
/// count i32 degrees, then IEEE CRC32 over the preceding bytes; little endian.
/// Validate everything before touching staging storage. Call only while stopped,
/// outside the real-time loop. Persistence and transport deliberately live elsewhere.
pub fn decode<'a>(bytes: &[u8], storage: &'a mut [i32; MAX_DEGREES]) -> Result<Scale<'a>, Error> {
    if bytes.len() < 20 || &bytes[..4] != b"TSC1" || bytes[6..8] != [0, 0] {
        return Err(Error::InvalidFile);
    }
    let count = u16::from_le_bytes([bytes[4], bytes[5]]) as usize;
    if !(1..=MAX_DEGREES).contains(&count) || bytes.len() != 16 + count * 4 {
        return Err(Error::InvalidFile);
    }
    let read = |offset| i32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap());
    let mut crc = 0xffff_ffffu32;
    for byte in &bytes[..bytes.len() - 4] {
        crc ^= *byte as u32;
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0xedb8_8320u32.wrapping_mul(crc & 1));
        }
    }
    if !crc != read(bytes.len() - 4) as u32 {
        return Err(Error::InvalidFile);
    }
    let period = read(8);
    if period <= 0 {
        return Err(Error::InvalidPeriod);
    }
    let mut previous = -1;
    for i in 0..count {
        let degree = read(12 + i * 4);
        if (i == 0 && degree != 0) || degree <= previous || degree >= period {
            return Err(Error::InvalidDegrees);
        }
        previous = degree;
    }
    for (i, degree) in storage[..count].iter_mut().enumerate() {
        *degree = read(12 + i * 4);
    }
    Ok(Scale {
        degrees: &storage[..count],
        period,
    })
}

/// A validated borrowed table. The importer owns storage; channels can share it.
pub struct Scale<'a> {
    degrees: &'a [i32],
    period: i32,
}

/// The live CV domain fits i32. Use the CPU's native divider there, while
/// retaining a wide fallback for the public API's extreme pitch/root pairs.
fn cycle_phase(pitch: i64, period: i32) -> (i64, i64) {
    if let Ok(narrow) = i32::try_from(pitch) {
        let quotient = narrow.div_euclid(period);
        let phase = narrow.rem_euclid(period);
        (quotient as i64 * period as i64, phase as i64)
    } else {
        (
            pitch.div_euclid(period as i64) * period as i64,
            pitch.rem_euclid(period as i64),
        )
    }
}

/// Small compiled conventional-note pattern, not the microtonal storage format.
/// An empty half collapses to the other half's pitch classes over one octave.
pub struct Pattern {
    degrees: [i32; 24],
    count: usize,
    period: i32,
}
impl Pattern {
    pub const fn empty() -> Self {
        Self {
            degrees: [0; 24],
            count: 0,
            period: 1_200_000,
        }
    }
    pub fn compile(masks: [u16; 2]) -> Result<Self, Error> {
        if masks.iter().any(|m| m & !0xfff != 0) {
            return Err(Error::InvalidDegrees);
        }
        if masks == [0, 0] {
            return Err(Error::Empty);
        }
        let mut result = Self::empty();
        let masks = if masks[0] == 0 { [masks[1], 0] } else { masks };
        result.period = if masks[1] == 0 { 1_200_000 } else { 2_400_000 };
        for (octave, mask) in masks.iter().enumerate() {
            for note in 0..12 {
                if mask & (1 << note) != 0 {
                    result.degrees[result.count] = (octave as i32 * 12 + note) * 100_000;
                    result.count += 1;
                }
            }
        }
        Ok(result)
    }
    pub fn scale(&self) -> Option<Scale<'_>> {
        if self.count == 0 {
            None
        } else {
            Some(Scale {
                degrees: &self.degrees[..self.count],
                period: self.period,
            })
        }
    }
}

impl<'a> Scale<'a> {
    pub fn new(degrees: &'a [i32], period: i32) -> Result<Self, Error> {
        if degrees.is_empty() {
            return Err(Error::Empty);
        }
        if degrees.len() > MAX_DEGREES {
            return Err(Error::TooManyDegrees);
        }
        if period <= 0 {
            return Err(Error::InvalidPeriod);
        }
        if degrees[0] != 0
            || degrees.iter().any(|&d| d < 0 || d >= period)
            || degrees.windows(2).any(|w| w[0] >= w[1])
        {
            return Err(Error::InvalidDegrees);
        }
        Ok(Self { degrees, period })
    }

    // The two degrees bracketing a pitch, including across period boundaries.
    fn bracket(&self, pitch: i64) -> (i64, i64) {
        let period = self.period as i64;
        let (cycle, phase) = cycle_phase(pitch, self.period);
        let mut lo = 0;
        let mut hi = self.degrees.len();
        while lo < hi {
            let mid = (lo + hi) / 2;
            if self.degrees[mid] as i64 <= phase {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        let lower = if lo == 0 {
            cycle - period + self.degrees[self.degrees.len() - 1] as i64
        } else {
            cycle + self.degrees[lo - 1] as i64
        };
        let upper = if lo == self.degrees.len() {
            cycle + period + self.degrees[0] as i64
        } else {
            cycle + self.degrees[lo] as i64
        };
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
            // Find membership and both neighbors together. Two bracket calls
            // would repeat cycle division and search for the same held note.
            let (cycle, phase) = cycle_phase(prev, self.period);
            if let Ok(index) = self.degrees.binary_search(&(phase as i32)) {
                let before = if index == 0 {
                    cycle - self.period as i64 + self.degrees[self.degrees.len() - 1] as i64
                } else {
                    cycle + self.degrees[index - 1] as i64
                };
                let next = if index + 1 == self.degrees.len() {
                    cycle + self.period as i64 + self.degrees[0] as i64
                } else {
                    cycle + self.degrees[index + 1] as i64
                };
                let down = prev - before;
                let up = next - prev;
                // Doubled arithmetic preserves half-millicent midpoints.
                if 2 * relative >= before + prev - 2 * (down / 4).min(5_000)
                    && 2 * relative <= prev + next + 2 * (up / 4).min(5_000)
                {
                    return Ok(previous);
                }
            }
        }
        let (lower, upper) = self.bracket(relative);
        let target = if relative - lower < upper - relative {
            lower
        } else {
            upper
        };
        i32::try_from(target + root as i64).map_err(|_| Error::Overflow)
    }

    /// Nearest scale degree inside an inclusive output pitch interval.
    /// Search only the two neighbors of the bounded target, never all octaves.
    /// Hysteresis is intentionally omitted when enforcing physical limits.
    pub fn quantize_bounded(
        &self,
        pitch: i32,
        root: i32,
        minimum: i32,
        maximum: i32,
    ) -> Result<i32, Error> {
        if minimum > maximum {
            return Err(Error::InvalidDegrees);
        }
        let bounded = pitch.clamp(minimum, maximum) as i64 - root as i64;
        let (lower, upper) = self.bracket(bounded);
        let lower = lower + root as i64;
        let upper = upper + root as i64;
        let valid = |p: i64| p >= minimum as i64 && p <= maximum as i64;
        let target = match (valid(lower), valid(upper)) {
            (true, true) => {
                if pitch as i64 - lower < upper - pitch as i64 {
                    lower
                } else {
                    upper
                }
            }
            (true, false) => lower,
            (false, true) => upper,
            (false, false) => return Err(Error::InvalidDegrees),
        };
        i32::try_from(target).map_err(|_| Error::Overflow)
    }

    /// Equal input bins over the entire repeat span. Output intervals remain
    /// musical intervals; this is not equal temperament. Bin zero starts at root.
    pub fn distribute(&self, pitch: i32, root: i32, previous: Option<i32>) -> Result<i32, Error> {
        let relative = pitch as i64 - root as i64;
        let period = self.period as i64;
        let count = self.degrees.len() as i64;
        if let Some(previous) = previous {
            let prev = previous as i64 - root as i64;
            let (cycle, phase) = cycle_phase(prev, self.period);
            if let Ok(index) = self.degrees.binary_search(&(phase as i32)) {
                let margin = 5_000.min(self.period / (self.degrees.len() as i32 * 4)) as i64;
                let position = (relative - cycle) * count;
                if position >= index as i64 * period - margin * count
                    && position < (index as i64 + 1) * period + margin * count
                {
                    return Ok(previous);
                }
            }
        }
        let (cycle, phase) = cycle_phase(relative, self.period);
        let index = if let Some(product) = (phase as u32).checked_mul(count as u32) {
            (product / self.period as u32) as usize
        } else {
            (phase * count / period) as usize
        };
        i32::try_from(cycle + self.degrees[index] as i64 + root as i64).map_err(|_| Error::Overflow)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounded_scale_matches_exhaustive_nearest_degree() {
        let degrees = [0, 17, 43];
        let scale = Scale::new(&degrees, 71).unwrap();
        for root in [-89, 0, 83] {
            for (minimum, maximum) in [(-201, 190), (-50, -21), (0, 2), (12, 13)] {
                let candidates: std::vec::Vec<i32> = (-10..=10)
                    .flat_map(|cycle| {
                        degrees
                            .into_iter()
                            .map(move |degree| root + cycle * 71 + degree)
                    })
                    .filter(|pitch| *pitch >= minimum && *pitch <= maximum)
                    .collect();
                for pitch in -250..=250 {
                    let expected = candidates
                        .iter()
                        .copied()
                        .min_by_key(|&p| ((pitch as i64 - p as i64).abs(), -(p as i64)))
                        .ok_or(Error::InvalidDegrees);
                    assert_eq!(
                        scale.quantize_bounded(pitch, root, minimum, maximum),
                        expected
                    );
                }
            }
        }
    }

    #[test]
    fn shared_neighbor_lookup_matches_previous_bracket_algorithm() {
        for masks in [
            [1, 0],
            [0xaaa, 0x555],
            [0xfdb, 0],
            [0x800, 1],
            [0xfff, 0xfff],
        ] {
            let pattern = Pattern::compile(masks).unwrap();
            let s = pattern.scale().unwrap();
            for root in [-12345, 0, 7654321] {
                for prev in (-3_000_000..=3_000_000).step_by(100_000) {
                    for offset in [
                        -200001, -155001, -155000, -55001, -55000, -1, 0, 1, 55000, 55001, 155000,
                        155001, 200001,
                    ] {
                        let pitch = prev + offset;
                        let (degree, next) = s.bracket(prev as i64);
                        let (before, _) = s.bracket(prev as i64 - 1);
                        let hold = degree == prev as i64
                            && 2 * pitch as i64
                                >= before + prev as i64
                                    - 2 * ((prev as i64 - before) / 4).min(5000)
                            && 2 * pitch as i64
                                <= prev as i64 + next + 2 * ((next - prev as i64) / 4).min(5000);
                        let expected = if hold {
                            Ok(prev + root)
                        } else {
                            s.quantize(pitch + root, root, None)
                        };
                        assert_eq!(s.quantize(pitch + root, root, Some(prev + root)), expected);
                    }
                }
            }
        }
    }
    #[test]
    fn native_cycle_math_matches_wide_reference() {
        for period in [1, 3, 100_000, 1_200_000, 2_400_000, i32::MAX] {
            for pitch in [
                -4_294_967_295i64,
                i32::MIN as i64 - 1,
                i32::MIN as i64,
                -2_400_001,
                -1,
                0,
                1,
                2_400_001,
                i32::MAX as i64,
                i32::MAX as i64 + 1,
                4_294_967_295,
            ] {
                assert_eq!(
                    cycle_phase(pitch, period),
                    (
                        pitch.div_euclid(period as i64) * period as i64,
                        pitch.rem_euclid(period as i64)
                    )
                );
            }
        }
        let s = Scale::new(&[0, 1_000_000_000], i32::MAX).unwrap();
        for pitch in [i32::MIN, -1, 0, 1, i32::MAX] {
            for root in [i32::MIN, 0, i32::MAX] {
                let relative = pitch as i64 - root as i64;
                let cycle = relative.div_euclid(i32::MAX as i64) * i32::MAX as i64;
                let index = (relative.rem_euclid(i32::MAX as i64) * 2 / i32::MAX as i64) as usize;
                let expected = i32::try_from(cycle + s.degrees[index] as i64 + root as i64)
                    .map_err(|_| Error::Overflow);
                assert_eq!(s.distribute(pitch, root, None), expected);
            }
        }
    }
    #[test]
    fn two_octave_patterns_cross_boundaries_and_collapse_empty_halves() {
        let pattern = Pattern::compile([1 << 11, 1]).unwrap();
        let scale = pattern.scale().unwrap();
        assert_eq!(scale.period, 2_400_000);
        assert_eq!(scale.quantize(1_150_000, 0, None), Ok(1_200_000));
        assert_eq!(scale.quantize(-1_250_000, 0, None), Ok(-1_200_000));
        // No unison in the first octave: bracket before first enabled note.
        assert_eq!(scale.quantize(0, 0, None), Ok(1_100_000));
        for masks in [[1 << 7, 0], [0, 1 << 7]] {
            let p = Pattern::compile(masks).unwrap();
            let s = p.scale().unwrap();
            assert_eq!(s.period, 1_200_000);
            assert_eq!(s.degrees, &[700_000]);
            assert_eq!(s.quantize(0, 0, None), Ok(-500_000));
            assert_eq!(s.distribute(0, 0, None), Ok(700_000));
        }
        assert!(Pattern::compile([0, 0]).is_err());
        assert!(Pattern::compile([0x1000, 0]).is_err());
    }
    #[test]
    fn equal_bins_share_whole_span_not_each_octave_separately() {
        let p = Pattern::compile([1, (1 << 0) | (1 << 4) | (1 << 7)]).unwrap();
        let s = p.scale().unwrap();
        // Four equal 600-cent input bins across a 2400-cent repeat.
        for cycle in -4..=4 {
            for (bin, note) in [0, 1_200_000, 1_600_000, 1_900_000].iter().enumerate() {
                for offset in [0, 1, 299_999, 599_999] {
                    assert_eq!(
                        s.distribute(cycle * 2_400_000 + bin as i32 * 600_000 + offset, 0, None),
                        Ok(cycle * 2_400_000 + note)
                    );
                }
            }
        }
        assert_eq!(s.distribute(604_999, 0, Some(0)), Ok(0));
        assert_eq!(s.distribute(605_000, 0, Some(0)), Ok(1_200_000));
        assert_eq!(s.distribute(600_000, 0, Some(123)), Ok(1_200_000));
        assert_eq!(s.distribute(100_000, 100_000, None), Ok(100_000));
        assert_eq!(s.distribute(i32::MAX, i32::MAX, None), Ok(i32::MAX));
    }
    #[test]
    fn sparse_patterns_match_exhaustive_nearest_search() {
        // Include every possible one-octave mask and varied second halves.
        for mask in 1u16..=0xfff {
            let p = Pattern::compile([mask, (!mask) & 0xfff]).unwrap();
            let s = p.scale().unwrap();
            for pitch in [
                -2_450_000, -500_001, -1, 0, 55_555, 1_150_000, 2_399_999, 3_000_000,
            ] {
                let expected = (-4..=4)
                    .flat_map(|cycle| s.degrees.iter().map(move |d| cycle * s.period + d))
                    .min_by_key(|target| ((target - pitch).abs(), -target))
                    .unwrap();
                assert_eq!(s.quantize(pitch, 0, None), Ok(expected));
            }
        }
    }
    #[test]
    fn presets_are_valid_and_represent_expected_intervals() {
        for id in 0..=5 {
            let scale = preset(id).unwrap();
            assert!(Scale::new(scale.degrees, scale.period).is_ok());
            for root in [-1_200_000, 0, 300_000, 6_000_000] {
                for degree in scale.degrees {
                    assert_eq!(scale.quantize(root + degree, root, None), Ok(root + degree));
                }
            }
        }
        assert!(preset(6).is_none());
        assert_eq!(
            preset(1).unwrap().degrees,
            &[0, 200000, 400000, 500000, 700000, 900000, 1100000]
        );
        assert_eq!(
            preset(2).unwrap().degrees,
            &[0, 200000, 300000, 500000, 700000, 800000, 1000000]
        );
        assert_eq!(preset(5).unwrap().degrees.len(), 24);
    }
    #[test]
    fn rejects_invalid_tables() {
        for (degrees, period) in [
            (&[][..], 1200),
            (&[1][..], 1200),
            (&[0, 0][..], 1200),
            (&[0, 1200][..], 1200),
            (&[0, -1][..], 1200),
            (&[0][..], 0),
        ] {
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
            let expected = (-6..=6)
                .flat_map(|cycle| {
                    degrees
                        .iter()
                        .map(move |degree| cycle * 1_001 + degree + 29)
                })
                .min_by_key(|&target| ((target - pitch).abs(), -target))
                .unwrap();
            assert_eq!(scale.quantize(pitch, 29, None), Ok(expected));
        }
    }
}
