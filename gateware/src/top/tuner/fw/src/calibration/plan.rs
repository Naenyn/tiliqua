//! Bounded positive-only sweep plans, quantized once to exact DAC counts.
pub const CAPACITY:usize=25;
pub fn plan(dense:bool)->([i32;CAPACITY],usize) {
    let intervals=if dense {24} else {8};
    let mut points=[0;CAPACITY];
    for i in 0..=intervals {
        points[i]=((i*8000+intervals/2)/intervals) as i32*250;
    }
    (points,intervals+1)
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn exact_counts_monotonic_and_bounded() {
        for dense in [false,true] {
            let (p,n)=plan(dense);
            assert_eq!(n,if dense {25} else {9});
            assert_eq!(p[0],0);assert_eq!(p[n-1],2000000);
            for pair in p[..n].windows(2) {
                assert!(pair[1]>pair[0]);assert_eq!(pair[1]%250,0);
            }
        }
        assert_eq!(plan(true).0[1],83250);
        assert_eq!(plan(true).0[2],166750);
    }
}
