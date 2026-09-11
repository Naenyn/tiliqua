//! Future expanded-profile codec. Legacy bytes remain readable; writes use v2.
//! Not yet linked into live persistence or exposed to users.
use crate::{bipolar,bipolar_sweep::Curve};
use crate::oscillator_calibration::{Point,Route};
pub const MAX_BYTES:usize=40+8*bipolar::MAX_POINTS;
pub struct Record {pub curve:Curve,pub route:Route,pub zero_note:u8,name:[u8;24],name_len:usize}
impl Record {pub fn name(&self)->&str {core::str::from_utf8(&self.name[..self.name_len]).unwrap()}}
fn valid_name(name:&str)->bool {
    (1..=24).contains(&name.len()) && !name.trim().is_empty()
        && name.bytes().all(|b|(32..=126).contains(&b))
}
fn crc(bytes:&[u8])->u32 {
    let mut c=!0u32;
    for b in bytes {c^=*b as u32;for _ in 0..8 {c=(c>>1)^if c&1!=0 {0xedb88320} else {0};}}
    !c
}
pub fn encode(curve:&Curve,route:Route,zero:u8,name:&str,out:&mut [u8;MAX_BYTES])->Option<usize> {
    if !valid_name(name) || !(12..=108).contains(&zero) || curve.points().len()<2 {return None;}
    out.fill(0);out[..4].copy_from_slice(b"TUCP");out[4]=2;
    out[5]=route.input();out[6]=route.output();out[7]=zero;
    out[8]=name.len() as u8;out[9]=curve.points().len() as u8;
    out[10]=u8::from(curve.limited_low)|(u8::from(curve.limited_high)<<1);
    out[12..12+name.len()].copy_from_slice(name.as_bytes());
    for (i,p) in curve.points().iter().enumerate() {
        let at=36+i*8;out[at..at+4].copy_from_slice(&p.microvolts.to_le_bytes());
        out[at+4..at+8].copy_from_slice(&p.millicents.to_le_bytes());
    }
    let end=36+curve.points().len()*8;let checksum=crc(&out[..end]);
    out[end..end+4].copy_from_slice(&checksum.to_le_bytes());Some(end+4)
}
pub fn decode(data:&[u8])->Option<Record> {
    if data.len()<56 || data.len()>MAX_BYTES || &data[..4]!=b"TUCP" {return None;}
    let version=data[4];
    if version!=1 && version!=2 {return None;}
    let count=data[9] as usize;let name_len=data[8] as usize;
    if !(2..=if version==1 {32} else {bipolar::MAX_POINTS}).contains(&count)
        || data.len()!=40+8*count || !(1..=24).contains(&name_len)
        || !(12..=108).contains(&data[7]) || data[11]!=0
        || data[10]>if version==1 {0} else {3}
        || data[12+name_len..36].iter().any(|b|*b!=0) {return None;}
    let end=data.len()-4;
    if crc(&data[..end])!=u32::from_le_bytes(data[end..].try_into().ok()?) {return None;}
    let name_str=core::str::from_utf8(&data[12..12+name_len]).ok()?;
    if !valid_name(name_str) {return None;}
    let route=Route::new(data[5],data[6]).ok()?;
    let mut curve=Curve::new();
    curve.limited_low=data[10]&1!=0;curve.limited_high=data[10]&2!=0;
    for i in 0..count {
        let at=36+i*8;
        let p=Point{microvolts:i32::from_le_bytes(data[at..at+4].try_into().ok()?),
            millicents:i32::from_le_bytes(data[at+4..at+8].try_into().ok()?)};
        if version==1 && !(0..=2000000).contains(&p.microvolts) {return None;}
        // Do not sort or silently repair corrupted serialized data.
        if curve.points().last().is_some_and(|last|last.microvolts>=p.microvolts) || !curve.add(p) {return None;}
    }
    let mut name=[0;24];name[..name_len].copy_from_slice(name_str.as_bytes());
    Some(Record{curve,route,zero_note:data[7],name,name_len})
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn full_bipolar_curve_roundtrips_and_reads_legacy_without_modifying_it() {
        let mut c=Curve::new();
        for i in (1..=60).rev() {
            let uv=bipolar::voltage(bipolar::Density::Semitone,bipolar::Direction::Down,i).unwrap();
            assert!(c.add(Point{microvolts:uv,millicents:6000000+(uv as i64*6/5) as i32}));
        }
        for i in 0..=60 {
            let uv=bipolar::voltage(bipolar::Density::Semitone,bipolar::Direction::Up,i).unwrap();
            assert!(c.add(Point{microvolts:uv,millicents:6000000+(uv as i64*6/5) as i32}));
        }
        let mut bytes=[0;MAX_BYTES];let n=encode(&c,Route::new(3,1).unwrap(),60,"Full range",&mut bytes).unwrap();
        assert_eq!(n,1008);let restored=decode(&bytes[..n]).unwrap();
        assert_eq!(restored.curve.points(),c.points());assert_eq!(restored.name(),"Full range");
        assert_eq!(restored.route,Route::new(3,1).unwrap());assert_eq!(restored.zero_note,60);
        for i in 0..n {bytes[i]^=1;assert!(decode(&bytes[..n]).is_none());bytes[i]^=1;}
        use crate::oscillator_calibration::{Profile,storage};
        let mut p=Profile::new("Legacy",0,2000000).unwrap();
        p.push(Point{microvolts:0,millicents:6000000}).unwrap();
        p.push(Point{microvolts:2000000,millicents:8400000}).unwrap();
        let mut old=[0;storage::MAX_BYTES];let n=storage::encode(&p,Route::new(1,2).unwrap(),48,"Legacy",&mut old).unwrap();
        let snapshot=old;let restored=decode(&old[..n]).unwrap();
        assert_eq!(old,snapshot);assert_eq!(restored.curve.points(),p.points());
        assert_eq!(restored.name(),"Legacy");assert_eq!(restored.zero_note,48);
    }
    #[test] fn rejects_semantically_invalid_records_even_with_valid_crc() {
        let mut c=Curve::new();
        c.add(Point{microvolts:-5000000,millicents:0});
        c.add(Point{microvolts:5000000,millicents:12000000});
        c.limited_low=true;
        let mut bytes=[0;MAX_BYTES];let n=encode(&c,Route::new(0,1).unwrap(),60,"test",&mut bytes).unwrap();
        assert!(decode(&bytes[..n]).unwrap().curve.limited_low);
        for mode in 0..6 {
            let mut invalid=bytes;
            match mode {
                0=>invalid[36..40].copy_from_slice(&(-5000001i32).to_le_bytes()),
                1=>invalid[44..48].copy_from_slice(&(-5000000i32).to_le_bytes()),
                2=>invalid[48..52].copy_from_slice(&0i32.to_le_bytes()),
                3=>invalid[10]=4,
                4=>invalid[5]=4,
                _=>invalid[4]=1,
            }
            let checksum=crc(&invalid[..n-4]);invalid[n-4..n].copy_from_slice(&checksum.to_le_bytes());
            assert!(decode(&invalid[..n]).is_none());
        }
        for len in 0..n {assert!(decode(&bytes[..len]).is_none());}
    }
}
