//! Small per-output settings, separate from detector state and measured curves.
//! No armed state is persisted. Pattern masks are snapshots, not mutable links.
// Standalone host tests also compile the route reservation dependency.
#[cfg(test)]
#[path="ownership.rs"]
pub mod ownership;
#[cfg(test)]
#[path="route_group.rs"]
pub mod route_group;
pub const SLOTS: u8 = 8;
pub const LEN: usize = 108;
pub fn key(slot: u8) -> Option<u32> {
    if (1..=SLOTS).contains(&slot) {
        Some(0x54515331 + slot as u32 - 1)
    } else {
        None
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Channel {
    pub input: u8,
    pub zero: u8,
    pub scale: u8,
    pub root: u8,
    pub transpose: i8,
    pub equal: bool,
    pub masks: [u16; 8],
    pub octaves: u8,
    pub quantize: bool,
    pub scale_slot: u8, // saved interval snapshot provenance, 0 means edited/preset
    pub correction: u8, // 0:none, 1:RAM snapshot, 2..9:slot 1..8
}
impl Channel {
    pub const fn new(input: u8) -> Self {
        Self {
            input,
            zero: 60,
            scale: 0,
            root: 0,
            transpose: 0,
            equal: false,
            masks: [0xfff, 0, 0, 0, 0, 0, 0, 0],
            octaves: 1,
            quantize: true,
            correction: 0,
            scale_slot: 0,
        }
    }
    /// Scale definitions contain intervals; musical offsets belong to the route.
    pub fn edit_scale<const N:usize>(&mut self,scale:u8,masks:[u16;N]) {
        if self.scale!=scale || self.masks[..N]!=masks {self.scale_slot=0;}
        self.scale=scale;self.masks=[0;8];self.masks[..N].copy_from_slice(&masks);
    }
    pub fn retune(&mut self,note:u8) {self.zero=note;}
    fn valid(&self) -> bool {
        self.input < 4
            && (12..=108).contains(&self.zero)
            && self.scale <= 13
            && self.scale_slot <= 8
            && self.correction <= 9
            && (1..=8).contains(&self.octaves)
            && self.root < 12
            && (-12..=12).contains(&self.transpose)
            && self.masks.iter().all(|m| m & !0xfff == 0)
    }
}
pub const DEFAULT: [Channel; 4] = [
    Channel::new(0),
    Channel::new(1),
    Channel::new(2),
    Channel::new(3),
];
/// Commit the current editor and return the newly selected editor, if changed.
/// Navigation never arms or stops hardware; active settings must be locked by the caller.
pub fn select(
    channels: &mut [Channel; 4],
    selected: &mut u8,
    edited: Channel,
    next: u8,
) -> Option<Channel> {
    if *selected >= 4 || next >= 4 || !edited.valid() {
        return None;
    }
    channels[*selected as usize] = edited;
    if next == *selected {
        return None;
    }
    *selected = next;
    Some(channels[next as usize])
}
#[cfg(not(test))] use crate::route_group;
pub const GROUP_LEN: usize = LEN + 8;
pub fn legacy_groups(channels:&[Channel;4])->route_group::Layout {
    let mut groups=route_group::Layout {inputs:[0,1,2,3],outputs:[0;4]};
    for (output,c) in channels.iter().enumerate() {groups.outputs[c.input as usize]|=1<<output;}
    groups
}
pub fn encode_group(channels:&[Channel;4],groups:route_group::Layout)->Option<[u8;GROUP_LEN]> {
    if !groups.valid() {return None;}
    for (output,c) in channels.iter().enumerate() {
        if let Some(route)=groups.owner(output as u8) {
            if c.input!=groups.inputs[route as usize] {return None;}
        }
    }
    let old=encode(channels)?;
    let mut bytes=[0;GROUP_LEN];bytes[..LEN-4].copy_from_slice(&old[..LEN-4]);
    bytes[..4].copy_from_slice(b"TQS4");
    bytes[LEN-4..LEN].copy_from_slice(&groups.inputs);
    bytes[LEN..LEN+4].copy_from_slice(&groups.outputs);
    let sum=crc(&bytes[..GROUP_LEN-4]);bytes[GROUP_LEN-4..].copy_from_slice(&sum.to_le_bytes());Some(bytes)
}
pub fn decode_group(bytes:&[u8])->Option<([Channel;4],route_group::Layout)> {
    let channels=decode(bytes)?;
    let groups=if bytes.len()==GROUP_LEN {
        route_group::Layout {inputs:bytes[LEN-4..LEN].try_into().ok()?,outputs:bytes[LEN..LEN+4].try_into().ok()?}
    } else {legacy_groups(&channels)};
    encode_group(&channels,groups)?;Some((channels,groups))
}
fn crc(bytes: &[u8]) -> u32 {
    let mut value = 0xffff_ffffu32;
    for byte in bytes {
        value ^= *byte as u32;
        for _ in 0..8 {
            value = (value >> 1) ^ 0xedb8_8320u32.wrapping_mul(value & 1);
        }
    }
    !value
}
pub fn encode(channels: &[Channel; 4]) -> Option<[u8; LEN]> {
    if !channels.iter().all(Channel::valid) {return None;}
    let mut bytes=[0;LEN];bytes[..4].copy_from_slice(b"TQS3");
    for (i,c) in channels.iter().enumerate() {
        let b=&mut bytes[4+i*25..4+(i+1)*25];
        b[..9].copy_from_slice(&[c.input,c.zero,c.scale,c.root,c.transpose as u8,
            c.equal as u8,c.quantize as u8,c.correction,c.octaves]);
        for n in 0..8 {b[9+n*2..11+n*2].copy_from_slice(&c.masks[n].to_le_bytes());}
    }
    let sum=crc(&bytes[..LEN-4]);bytes[LEN-4..].copy_from_slice(&sum.to_le_bytes());Some(bytes)
}
pub fn decode(bytes: &[u8]) -> Option<[Channel; 4]> {
    let width=match (bytes.len(),bytes.get(..4)?) {
        (48,b"TQS1")=>10,(56,b"TQS2")=>12,(LEN,b"TQS3")=>25,(GROUP_LEN,b"TQS4")=>25,_=>return None,
    };
    let end=bytes.len()-4;
    if crc(&bytes[..end])!=u32::from_le_bytes(bytes[end..].try_into().ok()?) {return None;}
    let mut channels=DEFAULT;
    for (i,c) in channels.iter_mut().enumerate() {
        let b=&bytes[4+i*width..4+(i+1)*width];
        if b[5]>1 || (width==12 && b[10]>1) || (width==25 && b[6]>1) {return None;}
        c.input=b[0];c.zero=b[1];c.scale=b[2];c.root=b[3];c.transpose=b[4] as i8;c.equal=b[5]!=0;
        if width==25 {
            c.quantize=b[6]!=0;c.correction=b[7];c.octaves=b[8];
            for n in 0..8 {c.masks[n]=u16::from_le_bytes([b[9+n*2],b[10+n*2]]);}
        } else {
            c.masks[0]=u16::from_le_bytes([b[6],b[7]]);
            c.masks[1]=u16::from_le_bytes([b[8],b[9]]);
            if c.masks[0]==0 {c.masks[0]=c.masks[1];c.masks[1]=0;}
            c.octaves=if c.masks[1]!=0 {2}else{1};
            c.quantize=width==10 || b[10]!=0;c.correction=if width==12 {b[11]}else{0};
        }
        if !c.valid() {return None;}
    }
    Some(channels)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn grouped_setups_roundtrip_and_legacy_fanout_migrates() {
        let mut channels=DEFAULT;channels[1].input=0;
        let groups=legacy_groups(&channels);
        assert_eq!(groups.outputs,[3,0,4,8]);
        let bytes=encode_group(&channels,groups).unwrap();
        assert_eq!(decode_group(&bytes),Some((channels,groups)));
        assert_eq!(decode_group(&encode(&channels).unwrap()),Some((channels,groups)));
        let mut bad=groups;bad.outputs[2]|=1;
        assert!(encode_group(&channels,bad).is_none());
        bad=groups;bad.inputs[0]=1;assert!(encode_group(&channels,bad).is_none());
        let mut corrupted=bytes;corrupted[108]^=1;
        assert!(decode_group(&corrupted).is_none());
        // A valid checksum does not make duplicate ownership or input mismatch valid.
        corrupted=bytes;corrupted[110]|=1;
        let sum=crc(&corrupted[..GROUP_LEN-4]);corrupted[GROUP_LEN-4..].copy_from_slice(&sum.to_le_bytes());
        assert!(decode_group(&corrupted).is_none());
        corrupted=bytes;corrupted[104]=1;
        let sum=crc(&corrupted[..GROUP_LEN-4]);corrupted[GROUP_LEN-4..].copy_from_slice(&sum.to_le_bytes());
        assert!(decode_group(&corrupted).is_none());
    }
    #[test]
    fn legacy_setups_migrate_and_new_stages_roundtrip() {
        let mut legacy = [0u8; 48];
        legacy[..4].copy_from_slice(b"TQS1");
        for i in 0..4 {
            legacy[4 + i * 10..10 + i * 10].copy_from_slice(&[i as u8, 60, 0, 0, 0, 0]);
        }
        let sum = crc(&legacy[..44]);
        legacy[44..].copy_from_slice(&sum.to_le_bytes());
        let mut channels = decode(&legacy).unwrap();
        for c in &channels {
            assert!(c.quantize);
            assert_eq!(c.correction, 0);
        }
        for (n, c) in channels.iter_mut().enumerate() {
            c.quantize = n % 2 == 0;
            c.correction = n as u8 + 1;
        }
        assert_eq!(decode(&encode(&channels).unwrap()), Some(channels));
        channels[0].correction = 9;
        assert!(encode(&channels).is_some());
        channels[0].correction = 10;
        assert!(encode(&channels).is_none());
    }
    #[test]
    fn switching_retains_each_editor_without_linking_masks() {
        let mut channels = DEFAULT;
        let mut selected = 1;
        let mut edited = channels[1];
        edited.input = 0;
        edited.scale = 6;
        edited.masks = [0xfdb, 0,0,0,0,0,0,0];
        edited.equal = true;
        assert_eq!(
            select(&mut channels, &mut selected, edited, 2),
            Some(DEFAULT[2])
        );
        let mut second = channels[2];
        second.root = 5;
        second.masks = [1,16,0,0,0,0,0,0];
        second.transpose = -12;
        assert_eq!(
            select(&mut channels, &mut selected, second, 1),
            Some(edited)
        );
        assert_eq!(channels[2], second);
        assert_eq!(channels[0], DEFAULT[0]);
        assert_eq!(channels[3], DEFAULT[3]);
        let saved = channels;
        assert_eq!(select(&mut channels, &mut selected, edited, 4), None);
        assert_eq!(channels, saved);
        assert_eq!(select(&mut channels, &mut selected, edited, 1), None);
    }
    #[test]
    fn independent_channels_roundtrip_and_reject_corruption() {
        let mut channels = DEFAULT;
        for (i, c) in channels.iter_mut().enumerate() {
            c.scale = i as u8;
            c.root = i as u8;
            c.transpose = i as i8 - 2;
            c.equal = i % 2 == 0;
            c.masks = [1 << i,1 << (11-i),0,0,0,0,0,0];
        }
        let bytes = encode(&channels).unwrap();
        assert_eq!(decode(&bytes), Some(channels));
        for i in 0..LEN {
            let mut bad = bytes;
            bad[i] ^= 1;
            assert_eq!(decode(&bad), None);
            assert_eq!(decode(&bytes[..i]), None);
        }
        for (field, value) in [(0, 4), (1, 11), (2, 14), (3, 12), (4, 13), (5, 2), (10, 0x10)] {
            let mut bad = bytes;
            bad[4 + field] = value;
            let sum = crc(&bad[..LEN-4]);
            bad[LEN-4..].copy_from_slice(&sum.to_le_bytes());
            assert_eq!(decode(&bad), None);
        }
        assert_eq!(key(0), None);
        assert_eq!(key(9), None);
        for i in 1..=8 {
            assert_eq!(key(i), Some(0x54515330 + i as u32));
        }
        assert!(core::mem::size_of::<[Channel; 4]>() <= 112);
    }
}

#[cfg(test)] #[path="midi_transpose.rs"] pub mod midi_transpose;
#[cfg(not(test))] use crate::midi_transpose;
pub const FULL_LEN:usize=132;
pub fn encode_full(channels:&[Channel;4],groups:route_group::Layout,midi:[midi_transpose::Config;4])->Option<[u8;FULL_LEN]> {
    if !midi.iter().all(|c|c.valid()) {return None;}
    let old=encode_group(channels,groups)?;
    let mut bytes=[0;FULL_LEN];bytes[..112].copy_from_slice(&old[..112]);bytes[..4].copy_from_slice(b"TQS5");
    for n in 0..4 {bytes[112+n*3]=midi[n].channel;bytes[113+n*3]=midi[n].base;bytes[114+n*3]=midi[n].hold as u8;bytes[124+n]=channels[n].scale_slot;}
    let sum=crc(&bytes[..128]);bytes[128..].copy_from_slice(&sum.to_le_bytes());Some(bytes)
}
/// Diagnose assignments only after authenticating the saved format and CRC.
pub fn saved_assignment_conflict(bytes:&[u8])->Option<(bool,u8,u8,u8)> {
    let end=match (bytes.len(),bytes.get(..4)?) {
        (FULL_LEN,b"TQS5")=>128,(GROUP_LEN,b"TQS4")=>GROUP_LEN-4,_=>return None,
    };
    if crc(&bytes[..end])!=u32::from_le_bytes(bytes[end..end+4].try_into().ok()?) {return None;}
    let g=route_group::Layout {inputs:bytes[LEN-4..LEN].try_into().ok()?,outputs:bytes[LEN..LEN+4].try_into().ok()?};
    if g.inputs.iter().any(|i|*i>3)||g.outputs.iter().any(|m|m&!15!=0) {return None;}
    g.conflict()
}
pub fn decode_full(bytes:&[u8])->Option<([Channel;4],route_group::Layout,[midi_transpose::Config;4])> {
    let mut midi=[midi_transpose::Config::new();4];
    if bytes.len()!=FULL_LEN {let (c,g)=decode_group(bytes)?;return Some((c,g,midi));}
    if bytes.get(..4)?!=b"TQS5" || crc(&bytes[..128])!=u32::from_le_bytes(bytes[128..].try_into().ok()?) {return None;}
    let mut legacy=[0;GROUP_LEN];legacy[..112].copy_from_slice(&bytes[..112]);legacy[..4].copy_from_slice(b"TQS4");
    let sum=crc(&legacy[..112]);legacy[112..].copy_from_slice(&sum.to_le_bytes());
    let (mut channels,groups)=decode_group(&legacy)?;
    for n in 0..4 {midi[n]=midi_transpose::Config {channel:bytes[112+n*3],base:bytes[113+n*3],hold:bytes[114+n*3]!=0};if bytes[114+n*3]>1 {return None;}channels[n].scale_slot=bytes[124+n];}
    if !midi.iter().all(|c|c.valid()) || !channels.iter().all(Channel::valid) {return None;}
    Some((channels,groups,midi))
}
#[cfg(test)] mod full_tests {
    use super::*;
    #[test] fn saved_conflict_identifies_jack_and_routes_before_atomic_rejection() {
        let g=route_group::Layout {inputs:[0,1,2,3],outputs:[1,2,4,8]};
        let mut bytes=encode_full(&DEFAULT,g,[midi_transpose::Config::new();4]).unwrap();
        bytes[LEN-3]=0;
        assert_eq!(saved_assignment_conflict(&bytes),None); // bad CRC is not trusted
        let sum=crc(&bytes[..128]);bytes[128..].copy_from_slice(&sum.to_le_bytes());
        assert_eq!(saved_assignment_conflict(&bytes),Some((false,0,0,1)));
        assert!(decode_full(&bytes).is_none());
        bytes[LEN-3]=1;bytes[LEN+1]=1;
        let sum=crc(&bytes[..128]);bytes[128..].copy_from_slice(&sum.to_le_bytes());
        assert_eq!(saved_assignment_conflict(&bytes),Some((true,0,0,1)));
        assert!(decode_full(&bytes).is_none());
    }
    #[test] fn full_config_roundtrip_and_old_defaults() {
        let mut c=DEFAULT;c[0].scale_slot=8;let g=route_group::Layout::new();
        let mut m=[midi_transpose::Config::new();4];m[2]=midi_transpose::Config {channel:16,base:127,hold:true};
        let bytes=encode_full(&c,g,m).unwrap();assert_eq!(decode_full(&bytes),Some((c,g,m)));
        for n in 0..FULL_LEN {let mut bad=bytes;bad[n]^=1;assert!(decode_full(&bad).is_none());}
        let old=decode_full(&encode_group(&DEFAULT,g).unwrap()).unwrap();assert_eq!(old.2,[midi_transpose::Config::new();4]);
        m[0].channel=17;assert!(encode_full(&c,g,m).is_none());
    }
}
