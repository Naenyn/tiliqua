//! Diagnostic source-energy veto, not a pitch estimator or output owner.
//! Integer-only; no heap, frame buffer, floating point or 128-bit arithmetic.
pub struct Source {
    pub end:u32, pub samples:u32, pub sum:i32, pub squares:u64, pub status:u32,
}

pub fn passes(source:Source, channel:u8, low:bool, sequence:u32, frame_end:u32,
              energy:u64, scaled:bool, clipped:bool)->bool {
    const N:u64=20480;
    if channel>3 || source.samples!=N as u32 || source.status!=(1|((channel as u32)<<2)) {
        return false;
    }
    let offset=frame_end.wrapping_sub(source.end) as i32;
    if low {
        if !(-512..=512).contains(&offset) {return false;}
    } else if frame_end!=sequence || !(0..=512).contains(&offset) {return false;}
    let sum=(source.sum as i64).unsigned_abs();
    if sum>N*32768 || source.squares>N*(1_u64<<30) {return false;}
    let qn=source.squares*N;
    let ss=sum*sum;
    if ss>qn {return false;}
    let samples=674_u64;
    if clipped || energy>samples*(1_u64<<30) {return false;}
    let energy=energy*if scaled {4} else {1};
    if energy<=4*samples {return false;}
    // Round source mean-square UP: never accept a frame rejected by the exact
    // 10% native / 5% low RMS gate. The low bank must not treat faint remnants
    // of out-of-band tones as independent qualified subharmonics. This is a
    // relative gate, not a higher absolute input-level floor. Additional
    // conservative margin is <0.01 count^2 native, <0.0025 count^2 low.
    // All products fit u64 by bounds above.
    let source_power=(qn-ss+N*N-1)/(N*N);
    energy*(if low {400} else {100})>source_power*samples
}
