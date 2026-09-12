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

fn interpolate(k: usize, a: f32, b: f32, c: f32) -> Peak {
    let curvature=a-2.0*b+c;
    let shift=if curvature<0.0 { (0.5*(a-c)/curvature).clamp(-0.5,0.5) } else { 0.0 };
    Peak { lag:k as f32+shift, height:b+0.5*(c-a)*shift+0.5*curvature*shift*shift }
}

fn value(read: &mut impl FnMut(usize)->i32, index: usize)->f32 {
    read(index) as f32 / 1048576.0
}

fn peaks(read: &mut impl FnMut(usize)->i32,last:usize,mut visit:impl FnMut(Peak)->bool) {
    let mut a=value(read,0);
    let mut b=value(read,1);
    let mut skipped=false;
    let mut best:Option<(f32,Peak)>=None;
    for k in 1..last {
        let c=value(read,k+1);
        if b<=0.0 {
            skipped=true;
            if let Some((_,p))=best.take() { if visit(p) {return;} }
        } else if skipped && b>=a && b>c && best.map_or(true,|(height,_)|b>height) {
            best=Some((b,interpolate(k,a,b,c)));
        }
        a=b;b=c;
    }
    if let Some((_,p))=best { visit(p); }
}

pub fn select(mut read:impl FnMut(usize)->i32,low:bool)->Option<Estimate> {
    let (fs,last,min,max)=if low {(6000.0,301,20.0,1500.0)} else {(192000.0,321,600.0,20000.0)};
    let in_range=|p:Peak| {let hz=fs/p.lag;hz>=min*(1.0-1e-6) && hz<=max*(1.0+1e-6)};
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
            let mut best:Option<(f32,Peak)>=None;
            for k in center.saturating_sub(1).max(1)..(center+2).min(last) {
                let a=value(&mut read,k-1);let b=value(&mut read,k);let c=value(&mut read,k+1);
                if b>=a && b>c && best.map_or(true,|(height,_)|b>height) {
                    best=Some((b,interpolate(k,a,b,c)));
                }
            }
            if let Some((_,candidate))=best {
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
