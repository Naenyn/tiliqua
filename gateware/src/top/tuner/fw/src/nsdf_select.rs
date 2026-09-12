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
struct Peak { lag: f32, height: f32 }

pub fn select_frame(read:impl FnMut(usize)->i32,low:bool,energy:u64,scaled:bool,clipped:bool)->Option<Estimate> {
    // Exactly the existing >2-count RMS gate, before expensive score access.
    // Scaling halves samples, so unscale energy by four without multiplying it.
    let samples=if low {604} else {674};
    if clipped || energy<=samples*(if scaled {1} else {4}) {return None;}
    select(read,low)
}

fn interpolate(k: usize, a: f32, b: f32, c: f32) -> Peak {
    let curvature=a-2.0*b+c;
    let shift=if curvature<0.0 { (0.5*(a-c)/curvature).clamp(-0.5,0.5) } else { 0.0 };
    Peak { lag:k as f32+shift, height:b+0.5*(c-a)*shift+0.5*curvature*shift*shift }
}

fn peak(k:usize,a:i32,b:i32,c:i32)->Peak {
    interpolate(k,a as f32/1048576.0,b as f32/1048576.0,c as f32/1048576.0)
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
    let (fs,last,min,max)=if low {(6000.0,301,20.0,1500.0)} else {(192000.0,321,600.0,20000.0)};
    // Compare lags instead of dividing every candidate on a soft-float CPU.
    let min_lag=fs/(max*(1.0+1e-6));
    let max_lag=fs/(min*(1.0-1e-6));
    let in_range=|p:Peak| p.lag>=min_lag && p.lag<=max_lag;
    let mut highest=0.0_f32;
    peaks(&mut read,last,|p| {if in_range(p) {highest=highest.max(p.height);} false});
    if highest<=0.0 {return None;}
    let mut chosen=None;
    peaks(&mut read,last,|p| {
        if in_range(p) && p.height>=0.9*highest {chosen=Some(p);true} else {false}
    });
    let mut p=chosen?;
    let original=fs/p.lag;
    let qualified=p.height>=0.8;
    if qualified {
        let largest=8.min(((last-2) as f32/p.lag) as usize);
        for multiple in (2..=largest).rev() {
            let center=(p.lag*multiple as f32+0.5) as usize;
            let mut best:Option<(usize,i32,i32,i32)>=None;
            for k in center.saturating_sub(1).max(1)..(center+2).min(last) {
                let a=read(k-1);let b=read(k);let c=read(k+1);
                if b>=a && b>c && best.map_or(true,|(_,_,height,_)|b>height) {
                    best=Some((k,a,b,c));
                }
            }
            if let Some((k,a,b,c))=best {
                let candidate=peak(k,a,b,c);
                let lag=candidate.lag/multiple as f32;
                let hz=fs/lag;
                // 2^(10/1200): same ten-cent guard, no runtime log or power.
                let ratio=hz/original;
                if candidate.height>=0.8_f32.max(0.9*p.height) && hz>=min && hz<=max
                    && ratio>=1.0/1.005792941 && ratio<=1.005792941 {
                    p=Peak {lag,height:p.height.min(candidate.height)};
                    break;
                }
            }
        }
    }
    Some(Estimate {hz:fs/p.lag,clarity:p.height,qualified,unrefined_hz:original})
}
