//! Display/performance pitch units. Numeric semitone indices are internal only.
use core::fmt::{self, Write};

#[path = "../../../../rs/opts/src/decimal.rs"]
mod decimal;
pub use decimal::Decimal;

pub fn write_note(out: &mut impl Write, note: i32) -> fmt::Result {
    const NAMES: [&str; 12] = [
        "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
    ];
    write!(
        out,
        "{}{}",
        NAMES[note.rem_euclid(12) as usize],
        note.div_euclid(12) - 1
    )
}

pub fn write_pitch(out: &mut impl Write, millicents: i32) -> fmt::Result {
    let note = (millicents + 50000).div_euclid(100000);
    write_note(out, note)?;
    let cents = (millicents - note * 100000) as f32 / 1000.0;
    write!(out, " {:+.1}c", Decimal(cents))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn names_and_octave_boundaries() {
        for (n, expected) in [(48, "C3"), (60, "C4"), (70, "A#4"), (71, "B4"), (72, "C5")] {
            let mut s = String::new();
            write_note(&mut s, n).unwrap();
            assert_eq!(s, expected);
        }
        let mut s = String::new();
        write_pitch(&mut s, 6652500).unwrap();
        assert_eq!(s, "G4 -47.5c");
    }
}
