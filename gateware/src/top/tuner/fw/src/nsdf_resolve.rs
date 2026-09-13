//! Conservative diagnostic bank arbitration; never averages or octave-folds.
#[derive(Clone,Copy)]
pub struct Candidate {pub mhz:u32,pub age:u32,pub qualified:bool}
#[derive(Clone,Copy,Debug,PartialEq)]
pub struct Resolved {pub mhz:u32,pub source:u8}
/// Live display policy: the shorter native window is primary wherever it
/// qualifies. The asynchronous low-rate window is not a veto on moving pitch.
/// This does not relax either bank's confidence, energy, or freshness gates.
pub fn resolve_display(native:Candidate,low:Candidate)->Resolved {
    if native.qualified && native.age<=250 && (600000..=20000000).contains(&native.mhz) {
        Resolved {mhz:native.mhz,source:2}
    } else if low.qualified && low.age<=250 && (20000..=1500000).contains(&low.mhz) {
        Resolved {mhz:low.mhz,source:1}
    } else {Resolved {mhz:0,source:0}}
}
// source: 0 unavailable, 1 low, 2 native, 3 conflicting qualified candidates.
pub fn resolve(native:Candidate,low:Candidate)->Resolved {
    let n=native.qualified && native.age<=250 && (600000..=20000000).contains(&native.mhz);
    let l=low.qualified && low.age<=250 && (20000..=1500000).contains(&low.mhz);
    match (n,l) {
        (false,false)=>Resolved {mhz:0,source:0},
        (true,false)=>Resolved {mhz:native.mhz,source:2},
        (false,true)=>Resolved {mhz:low.mhz,source:1},
        (true,true)=>{
            let min=native.mhz.min(low.mhz);let max=native.mhz.max(low.mhz);
            // 2% agreement tolerance (~34 cents) is NOT claimed pitch accuracy.
            // Inputs are range-checked above; this multiplication fits u32.
            if (max-min)*50>min {return Resolved {mhz:0,source:3};}
            // In the overlap, prefer the longer low-rate window up to 1 kHz;
            // above that use native sampling. No blending of asynchronous data.
            if low.mhz<=1000000 {Resolved {mhz:low.mhz,source:1}}
            else {Resolved {mhz:native.mhz,source:2}}
        }
    }
}
