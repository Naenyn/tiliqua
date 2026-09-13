//! Consumer-facing diagnostic pitch descriptor. No fabricated audio levels.
#[path="nsdf_resolve.rs"]
mod resolve;
#[derive(Clone,Copy)]
pub struct Frame {
    pub mhz:u32,pub count:u32,pub completed:u64,pub request_ms:u32,pub qualified:bool,
}
#[derive(Clone,Copy,Debug,PartialEq)]
pub struct Pitch {
    pub mhz:u32,pub source:u8,pub generation:u32,
    pub end_age_ms:u32,pub window_age_ms:u32,
}
impl Pitch {
    pub const NONE:Self=Self {mhz:0,source:0,generation:0,end_age_ms:u32::MAX,window_age_ms:u32::MAX};
}
pub fn publish(native:Frame,low:Frame,now:u64)->Pitch {
    publish_with(native,low,now,false)
}
pub fn display(native:Frame,low:Frame,now:u64)->Pitch {
    publish_with(native,low,now,true)
}
fn publish_with(native:Frame,low:Frame,now:u64,live:bool)->Pitch {
    let candidate=|f:Frame| {
        // Reject a future timestamp instead of saturating it into apparent youth.
        let age=now.checked_sub(f.completed).unwrap_or(u64::MAX)
            .saturating_add(f.request_ms as u64).min(u32::MAX as u64) as u32;
        resolve::Candidate {mhz:f.mhz,age,qualified:f.qualified && f.count>0}
    };
    let n=candidate(native);let l=candidate(low);
    let r=if live {resolve::resolve_display(n,l)} else {resolve::resolve(n,l)};
    if r.source!=1 && r.source!=2 {return Pitch {source:r.source,..Pitch::NONE};}
    let (f,age)=if r.source==1 {(low,l.age)} else {(native,n.age)};
    // Conservative request-time age, not completion age. Two ms allow tick
    // rounding/foreground observation. Include the older comparison candidate
    // if both banks participated, not just the chosen pitch's window.
    let end_age_ms=age.saturating_add(2);
    let both=!live && n.qualified && l.qualified && n.age<=250 && l.age<=250
        && (600000..=20000000).contains(&n.mhz) && (20000..=1500000).contains(&l.mhz);
    let support_age=if both {n.age.max(l.age)}else{age};
    // Source energy spans 20480/192000 s (107 ms rounded up), and its
    // published endpoint may precede the frame by 512 samples (another 3 ms).
    Pitch {mhz:r.mhz,source:r.source,generation:f.count,
        end_age_ms,window_age_ms:support_age.saturating_add(112)}
}
