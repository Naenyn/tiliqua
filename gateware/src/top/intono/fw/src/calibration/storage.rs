//! Versioned profile records sharing the options journal; no direct flash writes.
use super::{CalibrationGrade, CalibrationQuality, Point, Profile, Route, MAX_POINTS};
pub const SLOTS: u8 = 8;
pub const MAX_BYTES: usize = 52 + 8 * MAX_POINTS;
pub fn key(slot: u8) -> Option<u32> {
    if (1..=SLOTS).contains(&slot) {
        Some(0x54555030 + slot as u32)
    } else {
        None
    }
}

#[derive(Debug, PartialEq)]
pub enum Error {
    Invalid,
    Version,
    Checksum,
}
pub struct Recalled {
    pub profile: Profile,
    pub route: Route,
    pub zero_note: u8,
    pub quality: CalibrationQuality,
}

fn crc(bytes: &[u8]) -> u32 {
    let mut c = !0u32;
    for b in bytes {
        c ^= *b as u32;
        for _ in 0..8 {
            c = (c >> 1) ^ if c & 1 != 0 { 0xedb88320 } else { 0 };
        }
    }
    !c
}

pub fn encode(
    profile: &Profile,
    route: Route,
    zero_note: u8,
    quality: CalibrationQuality,
    name: &str,
    out: &mut [u8; MAX_BYTES],
) -> Result<usize, Error> {
    if !(12..=108).contains(&zero_note) || profile.points().len() < 2 {
        return Err(Error::Invalid);
    }
    let mut validated = Profile::new(name, -5000000, 8000000).map_err(|_| Error::Invalid)?;
    for p in profile.points() {
        validated.push(*p).map_err(|_| Error::Invalid)?;
    }
    out.fill(0);
    out[..4].copy_from_slice(b"TUCP");
    out[4] = 4;
    out[10] = u8::from(profile.limited_low) | (u8::from(profile.limited_high) << 1);
    out[5] = route.input();
    out[6] = route.output();
    out[7] = zero_note;
    out[8] = name.len() as u8;
    out[9] = profile.points().len() as u8;
    out[11] = quality.grade as u8;
    out[12..12 + name.len()].copy_from_slice(name.as_bytes());
    out[36..40].copy_from_slice(&quality.worst_millicents.to_le_bytes());
    out[40..44].copy_from_slice(&quality.stability_millicents.to_le_bytes());
    for (i, p) in profile.points().iter().enumerate() {
        let start = 48 + i * 8;
        out[start..start + 4].copy_from_slice(&p.microvolts.to_le_bytes());
        out[start + 4..start + 8].copy_from_slice(&p.millicents.to_le_bytes());
    }
    let end = 48 + profile.points().len() * 8;
    let checksum = crc(&out[..end]);
    out[end..end + 4].copy_from_slice(&checksum.to_le_bytes());
    Ok(end + 4)
}

pub fn decode(data: &[u8]) -> Result<Recalled, Error> {
    if data.len() < 56 || data.len() > MAX_BYTES || &data[..4] != b"TUCP" {
        return Err(Error::Invalid);
    }
    let version = data[4];
    if version != 1 && version != 2 && version != 3 && version != 4 {
        return Err(Error::Version);
    }
    let (name_len, count) = (data[8] as usize, data[9] as usize);
    if !(1..=24).contains(&name_len)
        || !(2..=if version == 1 { 32 } else { MAX_POINTS }).contains(&count)
        || data.len() != if version == 4 { 52 + count * 8 } else { 40 + count * 8 }
        || !(12..=108).contains(&data[7])
        || data[10] > if version == 1 { 0 } else { 3 }
        || (version < 4 && data[11] != 0)
        || (version == 4 && CalibrationGrade::from_u8(data[11]).is_none())
        || data[12 + name_len..36].iter().any(|b| *b != 0)
        || (version == 4
            && (u32::from_le_bytes(data[36..40].try_into().unwrap()) > 100_000
                || u32::from_le_bytes(data[40..44].try_into().unwrap()) > 100_000))
        || (version == 4 && data[44..48].iter().any(|b| *b != 0))
    {
        return Err(Error::Invalid);
    }
    let end = data.len() - 4;
    if crc(&data[..end]) != u32::from_le_bytes(data[end..].try_into().unwrap()) {
        return Err(Error::Checksum);
    }
    let name = core::str::from_utf8(&data[12..12 + name_len]).map_err(|_| Error::Invalid)?;
    let route = Route::new(data[5], data[6]).map_err(|_| Error::Invalid)?;
    let mut profile = Profile::new(
        name,
        if version == 1 { 0 } else { -5000000 },
        match version {
            1 => 2000000,
            2 => 5000000,
            _ => 8000000,
        },
    )
    .map_err(|_| Error::Invalid)?;
    profile.limited_low = data[10] & 1 != 0;
    profile.limited_high = data[10] & 2 != 0;
    let points_start = if version == 4 { 48 } else { 36 };
    for i in 0..count {
        let start = points_start + i * 8;
        profile
            .push(Point {
                microvolts: i32::from_le_bytes(data[start..start + 4].try_into().unwrap()),
                millicents: i32::from_le_bytes(data[start + 4..start + 8].try_into().unwrap()),
            })
            .map_err(|_| Error::Invalid)?;
    }
    Ok(Recalled {
        profile,
        route,
        zero_note: data[7],
        quality: if version == 4 {
            CalibrationQuality {
                grade: CalibrationGrade::from_u8(data[11]).ok_or(Error::Invalid)?,
                worst_millicents: u32::from_le_bytes(data[36..40].try_into().unwrap()),
                stability_millicents: u32::from_le_bytes(data[40..44].try_into().unwrap()),
            }
        } else {
            CalibrationQuality::default()
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn record() -> ([u8; MAX_BYTES], usize) {
        let mut p = Profile::new("Generate 3", 0, 2000000).unwrap();
        for i in 0..25 {
            p.push(Point {
                microvolts: i * 83000,
                millicents: 6500000 + i * 99600,
            })
            .unwrap();
        }
        let mut bytes = [0; MAX_BYTES];
        let n = encode(&p, Route::new(2, 3).unwrap(), 48, CalibrationQuality::default(), "Generate 3", &mut bytes).unwrap();
        (bytes, n)
    }
    fn legacy_record(version: u8) -> ([u8; MAX_BYTES], usize) {
        let (mut bytes, _) = record();
        let count = bytes[9] as usize;
        bytes.copy_within(48..48 + count * 8, 36);
        bytes[4] = version;
        bytes[11] = 0;
        let end = 36 + count * 8;
        let checksum = crc(&bytes[..end]);
        bytes[end..end + 4].copy_from_slice(&checksum.to_le_bytes());
        bytes[end + 4..].fill(0);
        (bytes, end + 4)
    }
    #[test]
    fn round_trip_preserves_name_route_origin_and_curve() {
        let (bytes, n) = record();
        let r = decode(&bytes[..n]).unwrap();
        assert_eq!(r.profile.name(), "Generate 3");
        assert_eq!(r.route, Route::new(2, 3).unwrap());
        assert_eq!(r.zero_note, 48);
        assert_eq!(r.profile.points().len(), 25);
        assert_eq!(r.profile.voltage_for_pitch(6599600), Ok(83000));
        assert_eq!(key(0), None);
        assert_eq!(key(SLOTS + 1), None);
    }
    #[test]
    fn version_three_roundtrips_positive_only_eight_volt_profile_and_reads_v2() {
        let mut p = Profile::new("Positive", 0, 8000000).unwrap();
        p.limited_low = true;
        for n in 0..=96 {
            p.push(Point {
                microvolts: n * 83333,
                millicents: 2_400_000 + n * 100_000,
            })
            .unwrap();
        }
        let mut bytes = [0; MAX_BYTES];
        let quality = CalibrationQuality { grade: CalibrationGrade::Musical, worst_millicents: 4200, stability_millicents: 1800 };
        let n = encode(&p, Route::new(0, 0).unwrap(), 48, quality, "Positive", &mut bytes).unwrap();
        assert_eq!(bytes[4], 4);
        let r = decode(&bytes[..n]).unwrap();
        assert_eq!(r.profile.points(), p.points());
        assert!(r.profile.limited_low);
        assert_eq!(r.profile.points().last().unwrap().microvolts, 7_999_968);
        assert_eq!(r.quality, quality);

        let (v2, n) = legacy_record(2);
        assert_eq!(decode(&v2[..n]).unwrap().profile.points().len(), 25);
        assert_eq!(decode(&v2[..n]).unwrap().quality.grade, CalibrationGrade::Unverified);
    }
    #[test]
    fn reads_legacy_and_roundtrips_all_121_signed_points() {
        let (legacy, n) = legacy_record(1);
        let before = legacy;
        let restored = decode(&legacy[..n]).unwrap();
        assert_eq!(restored.profile.points().len(), 25);
        assert_eq!(restored.profile.name(), "Generate 3");
        assert_eq!(before, legacy);
        let mut p = Profile::new("Bipolar", -5000000, 5000000).unwrap();
        p.limited_low = true;
        for i in 0..121i32 {
            let uv = -5000000 + ((i * 40000 + 60) / 120) * 250;
            p.push(Point {
                microvolts: uv,
                millicents: 6000000 + (uv as i64 * 6 / 5) as i32,
            })
            .unwrap();
        }
        let mut bytes = [0; MAX_BYTES];
        let n = encode(&p, Route::new(0, 1).unwrap(), 60, CalibrationQuality::default(), "Bipolar", &mut bytes).unwrap();
        assert_eq!(n, 1020);
        let r = decode(&bytes[..n]).unwrap();
        assert_eq!(r.profile.points(), p.points());
        assert!(r.profile.limited_low);
        assert!(!r.profile.limited_high);
        bytes[4] = 1;
        let c = crc(&bytes[..n - 4]);
        bytes[n - 4..n].copy_from_slice(&c.to_le_bytes());
        assert!(decode(&bytes[..n]).is_err());
    }
    #[test]
    fn rejects_truncated_and_bit_corrupted_records() {
        let (bytes, n) = record();
        for end in 0..n {
            assert!(decode(&bytes[..end]).is_err());
        }
        for i in 0..n {
            for bit in 0..8 {
                let mut b = bytes;
                b[i] ^= 1 << bit;
                assert!(decode(&b[..n]).is_err(), "byte {i} bit {bit}");
            }
        }
    }
    #[test]
    fn refinement_capacity_roundtrips_without_changing_old_record_layout() {
        let mut p = Profile::new("129 points", -5000000, 5000000).unwrap();
        for n in 0..MAX_POINTS as i32 {
            p.push(Point {
                microvolts: -5000000 + n * 77000,
                millicents: n * 92400,
            })
            .unwrap();
        }
        let mut bytes = [0; MAX_BYTES];
        let len = encode(&p, Route::new(0, 1).unwrap(), 60, CalibrationQuality::default(), "129 points", &mut bytes).unwrap();
        assert_eq!(len, 1084);
        assert!(MAX_BYTES + 4 <= 1100);
        assert_eq!(decode(&bytes[..len]).unwrap().profile.points(), p.points());
        for slot in 1..=8 {
            assert_eq!(key(slot), Some(0x54555030 + slot as u32));
        }
    }
    #[test]
    fn checks_semantics_even_with_valid_checksum() {
        let (bytes, n) = record();
        for i in [5, 6, 7, 8, 9, 10, 12, 39, 47] {
            let mut b = bytes;
            b[i] = 255;
            let c = crc(&b[..n - 4]);
            b[n - 4..n].copy_from_slice(&c.to_le_bytes());
            assert!(decode(&b[..n]).is_err(), "byte {i}");
        }
    }
}
