//! Conservative advice, never a claim about an unmeasured oscillator range.
use super::Profile;
pub fn advice(p:&Profile)->&'static str {
    let points=p.points();
    if points.len()<2 {return "INSUFFICIENT RANGE";}
    let low=points[0];let high=points[points.len()-1];
    // Rounded 20 Hz and 20 kHz positions, with a semitone margin. Only suggest
    // shifting when the missing end actually reached our voltage boundary.
    if low.microvolts<=-4_999_000 && low.millicents>1_650_000
        && high.millicents>=13_400_000 {
        "TRY LOWER TUNING; THEN RESCAN"
    } else if high.microvolts>=4_999_000 && high.millicents<13_400_000
        && low.millicents<=1_650_000 {
        "TRY HIGHER TUNING; THEN RESCAN"
    } else if p.limited_low || p.limited_high {
        "LIMITED RANGE; NO SHIFT ADVISED"
    } else {"FULL CV SWEEP; REVIEW PITCH RANGE"}
}
#[cfg(test)] mod tests {
    use super::*;
    use crate::oscillator_calibration::Point;
    fn profile(lo:i32,hi:i32,lp:i32,hp:i32)->Profile {
        let mut p=Profile::new("test",-5_000_000,5_000_000).unwrap();
        p.push(Point{microvolts:lo,millicents:lp}).unwrap();
        p.push(Point{microvolts:hi,millicents:hp}).unwrap();p
    }
    #[test] fn advice_requires_measured_voltage_boundary_not_just_missing_notes() {
        let p=profile(-5_000_000,4_000_000,2_000_000,13_500_000);
        assert!(advice(&p).starts_with("TRY LOWER"));
        let p=profile(-4_000_000,5_000_000,1_500_000,12_000_000);
        assert!(advice(&p).starts_with("TRY HIGHER"));
        let mut p=profile(-4_000_000,3_000_000,2_000_000,13_500_000);
        p.limited_low=true;
        assert_eq!(advice(&p),"LIMITED RANGE; NO SHIFT ADVISED");
    }
}
