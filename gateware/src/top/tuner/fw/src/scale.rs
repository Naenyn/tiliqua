//! Allocation-free scale math, independent of storage, MIDI, and DAC mapping.
//! Intervals are thousandths of a cent relative to a separately supplied root.
//! Degree zero is implicit in imported Scala files, but explicit in this table.
pub const MAX_DEGREES: usize = 128;

/// Immutable presets shared by every channel. IDs are not a storage format.
pub fn preset(id: u8) -> Option<Scale<'static>> {
    let (degrees, period): (&[i32], i32) = match id {
        0 => (&[0,100000,200000,300000,400000,500000,600000,700000,800000,900000,1000000,1100000],1200000),
        1 => (&[0,200000,400000,500000,700000,900000,1100000],1200000),
        2 => (&[0,200000,300000,500000,700000,800000,1000000],1200000),
        3 => (&[0,200000,400000,700000,900000],1200000),
        4 => (&[0,300000,500000,700000,1000000],1200000),
        5 => (&[0,50000,100000,150000,200000,250000,300000,350000,400000,450000,500000,550000,
            600000,650000,700000,750000,800000,850000,900000,950000,1000000,1050000,1100000,1150000],1200000),
        _ => return None,
    };
    Some(Scale { degrees, period })
}

#[derive(Debug, PartialEq)]
pub enum Error { Empty, TooManyDegrees, InvalidPeriod, InvalidDegrees, Overflow, InvalidFile }

/// Offline import envelope: magic TSC1, u16 count, u16 reserved=0, i32 period,
/// count i32 degrees, then IEEE CRC32 over the preceding bytes; little endian.
/// Validate everything before touching staging storage. Call only while stopped,
/// outside the real-time loop. Persistence and transport deliberately live elsewhere.
pub fn decode<'a>(bytes: &[u8], storage: &'a mut [i32; MAX_DEGREES]) -> Result<Scale<'a>, Error> {
    if bytes.len()<20 || &bytes[..4]!=b"TSC1" || bytes[6..8]!=[0,0] {return Err(Error::InvalidFile);}
    let count=u16::from_le_bytes([bytes[4],bytes[5]]) as usize;
    if !(1..=MAX_DEGREES).contains(&count) || bytes.len()!=16+count*4 {return Err(Error::InvalidFile);}
    let read=|offset| i32::from_le_bytes(bytes[offset..offset+4].try_into().unwrap());
    let mut crc=0xffff_ffffu32;
    for byte in &bytes[..bytes.len()-4] {
        crc^=*byte as u32;
        for _ in 0..8 {crc=(crc>>1) ^ (0xedb8_8320u32.wrapping_mul(crc&1));}
    }
    if !crc!=read(bytes.len()-4) as u32 {return Err(Error::InvalidFile);}
    let period=read(8);
    if period<=0 {return Err(Error::InvalidPeriod);}
    let mut previous=-1;
    for i in 0..count {
        let degree=read(12+i*4);
        if (i==0 && degree!=0) || degree<=previous || degree>=period {return Err(Error::InvalidDegrees);}
        previous=degree;
    }
    for (i,degree) in storage[..count].iter_mut().enumerate() {*degree=read(12+i*4);}
    Ok(Scale{degrees:&storage[..count],period})
}

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
    fn presets_are_valid_and_represent_expected_intervals() {
        for id in 0..=5 {
            let scale=preset(id).unwrap();
            assert!(Scale::new(scale.degrees,scale.period).is_ok());
            for root in [-1_200_000,0,300_000,6_000_000] {
                for degree in scale.degrees {
                    assert_eq!(scale.quantize(root+degree,root,None),Ok(root+degree));
                }
            }
        }
        assert!(preset(6).is_none());
        assert_eq!(preset(1).unwrap().degrees,&[0,200000,400000,500000,700000,900000,1100000]);
        assert_eq!(preset(2).unwrap().degrees,&[0,200000,300000,500000,700000,800000,1000000]);
        assert_eq!(preset(5).unwrap().degrees.len(),24);
    }
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
