//! Optional named envelope around unchanged legacy scale records.
//! Plain ASCII names fit the instrument's font; old unnamed records remain valid.
pub const MAX:usize=24;
pub const OVERHEAD:usize=36;
fn crc(bytes:&[u8])->u32 {let mut c=0xffff_ffffu32;for b in bytes {c^=*b as u32;for _ in 0..8 {c=(c>>1)^0xedb8_8320u32.wrapping_mul(c&1);}}!c}
pub fn payload(bytes:&[u8])->Option<&[u8]> {
    if !bytes.starts_with(b"TSN1") && !bytes.starts_with(b"TCN1") {return Some(bytes);}
    if bytes.len()<OVERHEAD+12 || bytes[4]==0 || bytes[4] as usize>MAX || bytes[5..8]!=[0;3] {return None;}
    let end=8+bytes[4] as usize;
    if bytes[8..end].iter().any(|b|!(32..=126).contains(b)) || bytes[8..end].iter().all(|b|*b==32) || bytes[end..32].iter().any(|b|*b!=0) || crc(&bytes[..bytes.len()-4])!=u32::from_le_bytes(bytes[bytes.len()-4..].try_into().ok()?) {return None;}
    let inner=&bytes[32..bytes.len()-4];
    let valid=if bytes.starts_with(b"TCN1") {matches!(inner.get(..4),Some(b"TQS1"|b"TQS2"|b"TQS3"|b"TQS4"|b"TQS5"|b"TQS6"))}else{matches!(inner.get(..4),Some(b"TNP1"|b"TNP2"|b"TSC1"))};
    if !valid {return None;}
    Some(inner)
}
pub fn name(bytes:&[u8])->Option<&str> {payload(bytes)?;if bytes.starts_with(b"TSN1") || bytes.starts_with(b"TCN1") {core::str::from_utf8(&bytes[8..8+bytes[4] as usize]).ok()}else{None}}
#[derive(Clone,Copy)]pub struct Name {pub bytes:[u8;MAX],pub len:u8}
impl Name {
    pub const fn empty()->Self {Self{bytes:[0;MAX],len:0}}
    pub fn read(bytes:&[u8])->Self {let mut n=Self::empty();if let Some(s)=name(bytes) {n.bytes[..s.len()].copy_from_slice(s.as_bytes());n.len=s.len() as u8;}n}
    pub fn text(&self)->&str {core::str::from_utf8(&self.bytes[..self.len as usize]).unwrap_or("")}
    pub fn wrap_config(&self,bytes:&mut [u8],len:usize)->Option<usize> {
        self.wrap_record(bytes,len,b'C')
    }
    pub fn wrap(&self,bytes:&mut [u8],len:usize)->Option<usize> {
        self.wrap_record(bytes,len,b'S')
    }
    fn wrap_record(&self,bytes:&mut [u8],len:usize,kind:u8)->Option<usize> {
        if self.len==0 {return Some(len);}
        let size=len.checked_add(OVERHEAD)?;if size>bytes.len() {return None;}
        bytes.copy_within(0..len,32);bytes[..32].fill(0);bytes[..4].copy_from_slice(b"TSN1");bytes[1]=kind;bytes[4]=self.len;bytes[8..8+self.len as usize].copy_from_slice(&self.bytes[..self.len as usize]);
        let sum=crc(&bytes[..size-4]);bytes[size-4..size].copy_from_slice(&sum.to_le_bytes());Some(size)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn envelopes_preserve_payload_and_reject_every_corrupted_byte() {
        for len in [25,528] {
            let mut bytes=[0u8;564];bytes[..4].copy_from_slice(if len==25 {b"TNP2"}else{b"TSC1"});
            for i in 4..len {bytes[i]=i as u8;}
            let original=bytes;let mut n=Name::empty();n.bytes.copy_from_slice(b"123456789012345678901234");n.len=24;
            let size=n.wrap(&mut bytes,len).unwrap();assert_eq!(size,len+36);
            assert_eq!(payload(&bytes[..size]),Some(&original[..len]));assert_eq!(name(&bytes[..size]),Some(n.text()));
            let read=Name::read(&bytes[..size]);assert_eq!(read.text(),n.text());
            for i in 0..size {let mut bad=bytes;bad[i]^=1;if i<4 {assert!(name(&bad[..size]).is_none());}else {assert!(payload(&bad[..size]).is_none());}}
            assert!(n.wrap(&mut [0;24],25).is_none());
        }
    }
    #[test]
    fn unnamed_and_invalid_headers() {
        assert_eq!(payload(b"TNP2"),Some(&b"TNP2"[..]));assert_eq!(name(b"TNP2"),None);
        let mut bytes=[0;61];bytes[..4].copy_from_slice(b"TNP2");let mut n=Name::empty();n.bytes[0]=b'A';n.len=1;n.wrap(&mut bytes,25).unwrap();
        for invalid in [0,25] {let mut bad=bytes;bad[4]=invalid;assert!(payload(&bad).is_none());}
        let mut bad=bytes;bad[8]=b' ';let sum=crc(&bad[..57]);bad[57..].copy_from_slice(&sum.to_le_bytes());assert!(payload(&bad).is_none());
    }
}
