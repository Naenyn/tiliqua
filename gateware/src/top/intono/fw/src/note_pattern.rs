//! Versioned custom-note record, separate from settings and oscillator profiles.
pub const KEY: u32 = 0x544e5031;
pub const SLOTS: u8 = 8;
/// Slot 1 retains the original key, so existing saved notes need no migration.
pub fn key(slot: u8) -> Option<u32> {
    if (1..=SLOTS).contains(&slot) {
        Some(KEY + slot as u32 - 1)
    } else {
        None
    }
}
pub const LEN: usize = 12;
fn crc(bytes: &[u8]) -> u32 {
    let mut crc = 0xffff_ffffu32;
    for byte in bytes {
        crc ^= *byte as u32;
        for _ in 0..8 {
            crc = (crc >> 1) ^ 0xedb8_8320u32.wrapping_mul(crc & 1);
        }
    }
    !crc
}
pub fn encode(masks: [u16; 2]) -> Option<[u8; LEN]> {
    if masks.iter().any(|m| m & !0xfff != 0) {
        return None;
    }
    let mut bytes = [0; LEN];
    bytes[..4].copy_from_slice(b"TNP1");
    bytes[4..6].copy_from_slice(&masks[0].to_le_bytes());
    bytes[6..8].copy_from_slice(&masks[1].to_le_bytes());
    let sum = crc(&bytes[..8]);
    bytes[8..].copy_from_slice(&sum.to_le_bytes());
    Some(bytes)
}
pub fn decode(bytes: &[u8]) -> Option<[u16; 2]> {
    if bytes.len() != LEN || &bytes[..4] != b"TNP1" {
        return None;
    }
    if crc(&bytes[..8]) != u32::from_le_bytes(bytes[8..].try_into().ok()?) {
        return None;
    }
    let masks = [
        u16::from_le_bytes(bytes[4..6].try_into().ok()?),
        u16::from_le_bytes(bytes[6..8].try_into().ok()?),
    ];
    if masks.iter().any(|m| m & !0xfff != 0) {
        None
    } else {
        Some(masks)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn roundtrip_and_corruption() {
        assert_eq!(key(1), Some(KEY));
        assert_eq!(key(0), None);
        assert_eq!(key(9), None);
        for slot in 1..=SLOTS {
            assert_eq!(key(slot), Some(KEY + slot as u32 - 1));
        }
        for mask in 0..=0xfff {
            let masks = [mask, 0xfff ^ mask];
            let record = encode(masks).unwrap();
            assert_eq!(decode(&record), Some(masks));
            for index in 0..LEN {
                let mut bad = record;
                bad[index] ^= 1;
                assert_eq!(decode(&bad), None);
                assert_eq!(decode(&record[..index]), None);
            }
        }
        assert_eq!(decode(&encode([0, 0]).unwrap()), Some([0, 0]));
        assert!(encode([0x1000, 0]).is_none());
        assert!(!(0x54555031..=0x54555034).contains(&KEY));
    }
}
