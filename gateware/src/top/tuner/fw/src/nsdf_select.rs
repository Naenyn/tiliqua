//! Diagnostic-only NSDF key-maxima selector. No heap or score-sized CPU buffer.
//! Reads a stable score frame twice, then at most seven three-neighbor searches.
//! Guarded later-peak fallback is our extension, not the paper's algorithm.

#[derive(Clone, Copy, Debug)]
pub struct Estimate {
    pub hz: f32,
    pub clarity: f32,
    pub qualified: bool,
    pub unrefined_hz: f32,
}

#[derive(Clone, Copy)]
struct Peak { lag: i32, height: i32 } // Q20 samples, Q20 NSDF

pub fn select_frame(read:impl FnMut(usize)->i32,low:bool,energy:u64,scaled:bool,clipped:bool)->Option<Estimate> {
    // Exactly the existing >2-count RMS gate, before expensive score access.
    // Scaling halves samples, so unscale energy by four without multiplying it.
    let samples=if low {604} else {674};
    if clipped || energy<=samples*(if scaled {1} else {4}) {return None;}
    select(read,low)
}

fn peak(k:usize,a:i32,b:i32,c:i32)->Peak {
    let curvature=a-2*b+c;
    let shift=if curvature<0 {
        let difference=a-c;
        let fraction=fraction19(difference.unsigned_abs(),(-curvature) as u32) as i32;
        if difference>0 {-fraction} else {fraction}
    } else {0};
    // At the parabola's vertex, height = b + (c-a)*shift/4.
    // Q20 shift quantization and truncation cost less than two height units.
    let height=b+(((c-a) as i64*shift as i64)/4194304) as i32;
    Peak {lag:((k as i32)<<20)+shift,height}
}

fn fraction19(mut numerator:u32,denominator:u32)->u32 {
    // Exact (numerator << 19) / denominator without software 64-bit division.
    // A local maximum guarantees numerator <= denominator <= 4 * 2^20.
    // Each nine-bit step fits u32, including the maximum denominator.
    let mut result=0;
    for shift in [9,9,1] {
        let scaled=numerator<<shift;
        let quotient=scaled/denominator;
        numerator=scaled-quotient*denominator;
        result=(result<<shift)|quotient;
    }
    result
}

fn peaks(read: &mut impl FnMut(usize)->i32,last:usize,mut visit:impl FnMut(Peak)->bool) {
    let mut a=read(0);
    let mut b=read(1);
    let mut skipped=false;
    let mut best:Option<(usize,i32,i32,i32)>=None;
    for k in 1..last {
        let c=read(k+1);
        if b<=0 {
            skipped=true;
            if let Some((k,a,b,c))=best.take() { if visit(peak(k,a,b,c)) {return;} }
        } else if skipped && b>=a && b>c && best.map_or(true,|(_,_,height,_)|b>height) {
            best=Some((k,a,b,c));
        }
        a=b;b=c;
    }
    if let Some((k,a,b,c))=best { visit(peak(k,a,b,c)); }
}

pub fn select(mut read:impl FnMut(usize)->i32,low:bool)->Option<Estimate> {
    let (fs,last,min,max)=if low {(6000_i64,301,20_i64,1500_i64)} else {(192000_i64,321,600_i64,20000_i64)};
    // Same one-ppm endpoint allowance, evaluated once using exact integers.
    let numerator=fs*1048576*1000000;
    let min_lag=((numerator+max*1000001-1)/(max*1000001)) as i32;
    let max_lag=(numerator/(min*999999)) as i32;
    let in_range=|p:Peak| p.lag>=min_lag && p.lag<=max_lag;
    let mut highest=0;
    peaks(&mut read,last,|p| {if in_range(p) {highest=highest.max(p.height);} false});
    if highest<=0 {return None;}
    let mut chosen=None;
    peaks(&mut read,last,|p| {
        if in_range(p) && p.height*10>=9*highest {chosen=Some(p);true} else {false}
    });
    let mut p=chosen?;
    let original_lag=p.lag;
    let qualified=p.height>=838861; // ceil(0.8 * 2^20)
    if qualified {
        let largest=8.min(((last-2)<<20)/p.lag as usize);
        for multiple in (2..=largest).rev() {
            let center=((p.lag*multiple as i32+524288)>>20) as usize;
            let mut best:Option<(usize,i32,i32,i32)>=None;
            for k in center.saturating_sub(1).max(1)..(center+2).min(last) {
                let a=read(k-1);let b=read(k);let c=read(k+1);
                if b>=a && b>c && best.map_or(true,|(_,_,height,_)|b>height) {
                    best=Some((k,a,b,c));
                }
            }
            if let Some((k,a,b,c))=best {
                let candidate=peak(k,a,b,c);
                let lag=candidate.lag/multiple as i32;
                let old=original_lag as i64;let new=lag as i64;
                // 2^(10/1200), represented to nine decimal places.
                if candidate.height>=838861 && candidate.height*10>=9*p.height
                    && new*max>=fs*1048576 && new*min<=fs*1048576
                    && old*1005792941>=new*1000000000
                    && old*1000000000<=new*1005792941 {
                    p=Peak {lag,height:p.height.min(candidate.height)};
                    break;
                }
            }
        }
    }
    // Convert only the final result for existing diagnostic formatting.
    Some(Estimate {hz:(fs*1048576) as f32/p.lag as f32,
        clarity:p.height as f32/1048576.0,qualified,
        unrefined_hz:(fs*1048576) as f32/original_lag as f32})
}

#[cfg(test)]
mod tests {
    #[test]
    fn fractional_division_matches_wide_reference() {
        for denominator in [1,2,3,7,511,512,513,65535,1048576,2097152,4194304] {
            for numerator in [0,1,denominator/2,denominator-1,denominator] {
                assert_eq!(super::fraction19(numerator,denominator),
                    (((numerator as u64)<<19)/denominator as u64) as u32);
            }
        }
        let mut state=731_u32;
        for _ in 0..100000 {
            state=state.wrapping_mul(1664525).wrapping_add(1013904223);
            let denominator=1+(state&4194303);
            state=state.wrapping_mul(1664525).wrapping_add(1013904223);
            let numerator=state%(denominator+1);
            assert_eq!(super::fraction19(numerator,denominator),
                (((numerator as u64)<<19)/denominator as u64) as u32);
        }
    }
}
