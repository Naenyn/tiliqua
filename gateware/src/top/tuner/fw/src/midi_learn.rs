//! Deliberately narrow TRS MIDI editing for the conventional note pattern.
//! MIDI never drives CV or changes a saved scale implicitly.

#[derive(Default)]
pub struct HeldNotes([u64; 2]);

impl HeldNotes {
    pub fn clear(&mut self) {
        self.0 = [0; 2];
    }

    /// A fresh key press toggles its pitch class in the selected octave.
    /// Note Off (including zero-velocity Note On) releases the key, while
    /// repeated Note Ons before release do not toggle it again. The result
    /// is Some(true) when enabled, Some(false) when disabled, or None when
    /// the message does not edit the pattern.
    pub fn process(&mut self, masks: &mut [u16; 2], octave: usize, word: u32) -> Option<bool> {
        let status = word as u8;
        let note = (word >> 8) as u8;
        let velocity = (word >> 16) as u8;
        if note >= 128 || octave >= masks.len() {
            return None;
        }
        let on = match status & 0xf0 {
            0x90 => velocity != 0,
            0x80 => false,
            _ => return None,
        };
        let held = &mut self.0[note as usize / 64];
        let key = 1u64 << (note % 64);
        if !on {
            *held &= !key;
            return None;
        }
        if *held & key != 0 {
            return None;
        }
        *held |= key;
        let bit = 1u16 << (note % 12);
        masks[octave] ^= bit;
        Some(masks[octave] & bit != 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fresh_presses_toggle_but_repeats_do_not() {
        let mut held = HeldNotes::default();
        let mut masks = [0, 0];
        assert_eq!(held.process(&mut masks, 1, 0x7f3c90), Some(true));
        assert_eq!(held.process(&mut masks, 1, 0x7f3c90), None);
        assert_eq!(masks, [0, 1]);
        assert_eq!(held.process(&mut masks, 1, 0x403c80), None);
        assert_eq!(held.process(&mut masks, 1, 0x403c90), Some(false));
        assert_eq!(masks, [0, 0]);
        assert_eq!(held.process(&mut masks, 1, 0x003c90), None);
        assert_eq!(held.process(&mut masks, 0, 0x403c9f), Some(true));
        assert_eq!(masks, [1, 0]);
    }

    #[test]
    fn disarming_forgets_held_keys_and_ignores_other_messages() {
        let mut held = HeldNotes::default();
        let mut masks = [0, 0];
        assert_eq!(held.process(&mut masks, 0, 0x4045b0), None);
        assert_eq!(held.process(&mut masks, 2, 0x404590), None);
        assert_eq!(held.process(&mut masks, 0, 0x404590), Some(true));
        held.clear();
        assert_eq!(held.process(&mut masks, 0, 0x404590), Some(false));
    }
}
