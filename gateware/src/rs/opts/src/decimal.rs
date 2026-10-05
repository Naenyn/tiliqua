use core::fmt::{self, Write};

/// Bounded display decimals without pulling in general float-to-decimal code.
/// Measurements retain their float math; only presentation uses scaled integers.
pub struct Decimal(pub f32);
impl fmt::Display for Decimal {
    fn fmt(&self,f:&mut fmt::Formatter<'_>)->fmt::Result {
        if !self.0.is_finite() {return f.pad("--");}
        let precision=f.precision().unwrap_or(2).min(3);
        let scale=[1u32,10,100,1000][precision];
        let negative=self.0.is_sign_negative();
        let magnitude=(self.0.abs()*scale as f32+0.5) as u32;
        let whole=magnitude/scale;let fraction=magnitude%scale;
        let mut digits=1;let mut rest=whole;while rest>=10 {rest/=10;digits+=1;}
        let sign=negative||f.sign_plus();
        let width=digits+sign as usize+if precision>0 {precision+1}else{0};
        let padding=f.width().unwrap_or(0).saturating_sub(width);
        for _ in 0..padding {f.write_char(' ')?;}
        if sign {f.write_char(if negative {'-'}else{'+'})?;}
        write!(f,"{}",whole)?;
        if precision>0 {write!(f,".{:0width$}",fraction,width=precision)?;}
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn measurement_formatting_width_sign_rounding_and_invalid_values() {
        assert_eq!(format!("{:+.1}", Decimal(-32.44)), "-32.4");
        assert_eq!(format!("{:8.2}", Decimal(33.97)), "   33.97");
        assert_eq!(format!("{:5.3}", Decimal(0.003)), "0.003");
        assert_eq!(format!("{:+.3}", Decimal(1.2348)), "+1.235");
        assert_eq!(format!("{:.0}", Decimal(440.0)), "440");
        assert_eq!(format!("{:.2}", Decimal(-0.0)), "-0.00");
        assert_eq!(format!("{}", Decimal(f32::NAN)), "--");
        assert_eq!(format!("{}", Decimal(f32::INFINITY)), "--");
    }
}
