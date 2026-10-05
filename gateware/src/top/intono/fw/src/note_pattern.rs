//! Versioned custom-note record, separate from settings and oscillator profiles.
#[path="scale_name.rs"] mod saved_name;
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
pub const LEN: usize = 25;
const LEGACY_LEN: usize = 12;
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
#[cfg(test)]
pub fn encode(masks: [u16; 2]) -> Option<[u8; LEGACY_LEN]> {
    if masks.iter().any(|m| m & !0xfff != 0) {
        return None;
    }
    let mut bytes = [0; LEGACY_LEN];
    bytes[..4].copy_from_slice(b"TNP1");
    bytes[4..6].copy_from_slice(&masks[0].to_le_bytes());
    bytes[6..8].copy_from_slice(&masks[1].to_le_bytes());
    let sum = crc(&bytes[..8]);
    bytes[8..].copy_from_slice(&sum.to_le_bytes());
    Some(bytes)
}
pub fn decode(bytes: &[u8]) -> Option<[u16; 2]> {
    if bytes.len() != LEGACY_LEN || &bytes[..4] != b"TNP1" {
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
pub fn encode_span(masks:[u16;8],octaves:u8)->Option<[u8;LEN]> {
    if !(1..=8).contains(&octaves) || masks.iter().any(|m|m & !0xfff !=0) {return None;}
    let mut bytes=[0;LEN];bytes[..4].copy_from_slice(b"TNP2");bytes[4]=octaves;
    for n in 0..8 {bytes[5+n*2..7+n*2].copy_from_slice(&masks[n].to_le_bytes());}
    let sum=crc(&bytes[..21]);bytes[21..].copy_from_slice(&sum.to_le_bytes());Some(bytes)
}
pub fn decode_span(bytes:&[u8])->Option<([u16;8],u8)> {
    let bytes=saved_name::payload(bytes)?;
    if bytes.len()==LEGACY_LEN {
        let mut old=decode(bytes)?;
        if old[0]==0 {old=[old[1],0];}
        let mut masks=[0;8];masks[..2].copy_from_slice(&old);
        return Some((masks,if old[1]!=0 {2}else{1}));
    }
    if bytes.len()!=LEN || &bytes[..4]!=b"TNP2" || crc(&bytes[..21])!=u32::from_le_bytes(bytes[21..].try_into().ok()?) {return None;}
    let mut masks=[0;8];for n in 0..8 {masks[n]=u16::from_le_bytes([bytes[5+n*2],bytes[6+n*2]]);}
    encode_span(masks,bytes[4])?;Some((masks,bytes[4]))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn named_saved_masks_roundtrip() {
        let masks=[1,2,4,8,16,32,64,128];let raw=encode_span(masks,8).unwrap();
        let mut bytes=[0;61];bytes[..raw.len()].copy_from_slice(&raw);
        let mut name=saved_name::Name::empty();name.bytes[..5].copy_from_slice(b"Scale");name.len=5;
        let len=name.wrap(&mut bytes,raw.len()).unwrap();assert_eq!(decode_span(&bytes[..len]),Some((masks,8)));
    }
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
            for index in 0..LEGACY_LEN {
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
