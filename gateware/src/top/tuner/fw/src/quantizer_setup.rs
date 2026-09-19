//! Small per-output settings, separate from detector state and measured curves.
//! No armed state is persisted. Pattern masks are snapshots, not mutable links.
pub const SLOTS:u8=8;
pub const LEN:usize=56;
pub fn key(slot:u8)->Option<u32> {
    if (1..=SLOTS).contains(&slot) {Some(0x54515331+slot as u32-1)} else {None}
}
#[derive(Clone,Copy,Debug,PartialEq)]
pub struct Channel {
    pub input:u8, pub zero:u8, pub scale:u8, pub root:u8,
    pub transpose:i8, pub equal:bool, pub masks:[u16;2],
    pub quantize:bool, pub correction:u8, // 0:none, 1:RAM snapshot, 2..5:slot 1..4
}
impl Channel {
    pub const fn new(input:u8)->Self {
        Self{input,zero:60,scale:0,root:0,transpose:0,equal:false,masks:[0xfff,0],quantize:true,correction:0}
    }
    fn valid(&self)->bool {
        self.input<4 && (12..=108).contains(&self.zero) && self.scale<=6 && self.correction<=5
            && self.root<12 && (-12..=12).contains(&self.transpose)
            && self.masks.iter().all(|m|m&!0xfff==0)
    }
}
pub const DEFAULT:[Channel;4]=[Channel::new(0),Channel::new(1),Channel::new(2),Channel::new(3)];
/// Commit the current editor and return the newly selected editor, if changed.
/// Navigation never arms or stops hardware; active settings must be locked by the caller.
pub fn select(channels:&mut [Channel;4],selected:&mut u8,edited:Channel,next:u8)->Option<Channel> {
    if *selected>=4 || next>=4 || !edited.valid() {return None;}
    channels[*selected as usize]=edited;
    if next==*selected {return None;}
    *selected=next;Some(channels[next as usize])
}
fn crc(bytes:&[u8])->u32 {
    let mut value=0xffff_ffffu32;
    for byte in bytes {value^=*byte as u32;for _ in 0..8 {value=(value>>1)^0xedb8_8320u32.wrapping_mul(value&1);}}
    !value
}
pub fn encode(channels:&[Channel;4])->Option<[u8;LEN]> {
    if !channels.iter().all(Channel::valid) {return None;}
    let mut bytes=[0;LEN];bytes[..4].copy_from_slice(b"TQS2");
    for (i,c) in channels.iter().enumerate() {
        let b=&mut bytes[4+i*12..16+i*12];
        b[..6].copy_from_slice(&[c.input,c.zero,c.scale,c.root,c.transpose as u8,c.equal as u8]);
        b[6..8].copy_from_slice(&c.masks[0].to_le_bytes());b[8..10].copy_from_slice(&c.masks[1].to_le_bytes());
        b[10]=c.quantize as u8;b[11]=c.correction;
    }
    let sum=crc(&bytes[..52]);bytes[52..].copy_from_slice(&sum.to_le_bytes());Some(bytes)
}
pub fn decode(bytes:&[u8])->Option<[Channel;4]> {
    let width=match (bytes.len(),bytes.get(..4)?) {(48,b"TQS1")=>10,(56,b"TQS2")=>12,_=>return None};
    let end=bytes.len()-4;
    if crc(&bytes[..end])!=u32::from_le_bytes(bytes[end..].try_into().ok()?) {return None;}
    let mut channels=DEFAULT;
    for (i,c) in channels.iter_mut().enumerate() {
        let b=&bytes[4+i*width..4+(i+1)*width];if b[5]>1 || (width==12 && b[10]>1) {return None;}
        *c=Channel{input:b[0],zero:b[1],scale:b[2],root:b[3],transpose:b[4] as i8,equal:b[5]!=0,
            masks:[u16::from_le_bytes([b[6],b[7]]),u16::from_le_bytes([b[8],b[9]])],
            quantize:width==10 || b[10]!=0,correction:if width==12 {b[11]} else {0}};
        if !c.valid() {return None;}
    }
    Some(channels)
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn legacy_setups_migrate_and_new_stages_roundtrip() {
        let mut legacy=[0u8;48];legacy[..4].copy_from_slice(b"TQS1");
        for i in 0..4 {legacy[4+i*10..10+i*10].copy_from_slice(&[i as u8,60,0,0,0,0]);}
        let sum=crc(&legacy[..44]);legacy[44..].copy_from_slice(&sum.to_le_bytes());
        let mut channels=decode(&legacy).unwrap();
        for c in &channels {assert!(c.quantize);assert_eq!(c.correction,0);}
        for (n,c) in channels.iter_mut().enumerate() {c.quantize=n%2==0;c.correction=n as u8+1;}
        assert_eq!(decode(&encode(&channels).unwrap()),Some(channels));
        channels[0].correction=6;assert!(encode(&channels).is_none());
    }
    #[test] fn switching_retains_each_editor_without_linking_masks() {
        let mut channels=DEFAULT;let mut selected=1;
        let mut edited=channels[1];edited.input=0;edited.scale=6;edited.masks=[0xfdb,0];edited.equal=true;
        assert_eq!(select(&mut channels,&mut selected,edited,2),Some(DEFAULT[2]));
        let mut second=channels[2];second.root=5;second.masks=[1,16];second.transpose=-12;
        assert_eq!(select(&mut channels,&mut selected,second,1),Some(edited));
        assert_eq!(channels[2],second);assert_eq!(channels[0],DEFAULT[0]);assert_eq!(channels[3],DEFAULT[3]);
        let saved=channels;
        assert_eq!(select(&mut channels,&mut selected,edited,4),None);assert_eq!(channels,saved);
        assert_eq!(select(&mut channels,&mut selected,edited,1),None);
    }
    #[test] fn independent_channels_roundtrip_and_reject_corruption() {
        let mut channels=DEFAULT;
        for (i,c) in channels.iter_mut().enumerate() {
            c.scale=i as u8;c.root=i as u8;c.transpose=i as i8-2;c.equal=i%2==0;c.masks=[1<<i,1<<(11-i)];
        }
        let bytes=encode(&channels).unwrap();assert_eq!(decode(&bytes),Some(channels));
        for i in 0..LEN {let mut bad=bytes;bad[i]^=1;assert_eq!(decode(&bad),None);assert_eq!(decode(&bytes[..i]),None);}
        for (field,value) in [(0,4),(1,11),(2,7),(3,12),(4,13),(5,2),(7,0x10)] {
            let mut bad=bytes;bad[4+field]=value;let sum=crc(&bad[..52]);bad[52..].copy_from_slice(&sum.to_le_bytes());assert_eq!(decode(&bad),None);
        }
        assert_eq!(key(0),None);assert_eq!(key(9),None);
        for i in 1..=8 {assert_eq!(key(i),Some(0x54515330+i as u32));}
        assert!(core::mem::size_of::<[Channel;4]>()<=56);
    }
}
