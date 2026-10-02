//! MIDI edits are relative to a learned octave, independent of route pitch.
#[derive(Debug, PartialEq, Eq)]
pub enum Event { Base(u8), Edit { key: u8, enabled: bool } }
pub struct HeldNotes { held: [u64; 2], pub base: u8, pending: bool, channel: Option<u8> }
impl Default for HeldNotes {
    fn default() -> Self { Self { held: [0; 2], base: 48, pending: false, channel: None } }
}
impl HeldNotes {
    pub fn clear(&mut self) { self.held = [0; 2]; self.pending = false; self.channel=None; }
    pub fn learn_base(&mut self) { self.clear(); self.pending = true; }
    #[inline(never)]
    pub fn process(&mut self, masks: &mut [u16], span: usize, word: u32) -> Option<Event> {
        let status = word as u8;
        let note = (word >> 8) as u8;
        let velocity = (word >> 16) as u8;
        if note >= 128 || velocity >= 128 { return None; }
        let on = match status & 0xf0 {
            0x90 => velocity != 0, 0x80 => false, _ => return None,
        };
        let channel=status&15;
        if self.channel.is_some_and(|c|c!=channel) {return None;}
        if on && self.channel.is_none() {self.channel=Some(channel);}
        let held = &mut self.held[note as usize / 64];
        let bit = 1u64 << (note % 64);
        if !on { *held &= !bit; return None; }
        if *held & bit != 0 { return None; }
        *held |= bit;
        if self.pending {
            self.base = note / 12 * 12;
            self.pending = false;
            return Some(Event::Base(self.base));
        }
        let key = note.checked_sub(self.base)?;
        let octave = key as usize / 12;
        if octave >= span.min(masks.len()) { return None; }
        let bit = 1u16 << (key % 12);
        masks[octave] ^= bit;
        Some(Event::Edit { key, enabled: masks[octave] & bit != 0 })
    }
}
/// MIDI follows the played octave; encoder navigation still uses explicit VIEW.
pub fn reveal(view: u8, span: u8, key: u8) -> u8 {
    let octave = key / 12;
    let view = if octave < view { octave } else if octave >= view + 2 { octave - 1 } else { view };
    view.min(span.saturating_sub(2))
}
#[cfg(test)]
mod tests {
    use super::*;
    fn on(note:u8)->u32 { 0x400090 | (note as u32)<<8 }
    #[test]
    fn any_note_learns_its_octave_without_editing_or_repeating() {
        let mut h=HeldNotes::default();let mut m=[0;8];h.learn_base();
        assert_eq!(h.process(&mut m,8,on(67)),Some(Event::Base(60)));
        assert_eq!(m,[0;8]);assert_eq!(h.process(&mut m,8,on(67)),None);
        h.process(&mut m,8,0x4380);
        assert_eq!(h.process(&mut m,8,on(67)),Some(Event::Edit{key:7,enabled:true}));
        assert_eq!(m[0],128);
    }
    #[test]
    fn absolute_octaves_and_bounds_preserve_pattern_positions() {
        let mut h=HeldNotes::default();let mut m=[0;8];
        assert_eq!(h.process(&mut m,3,on(47)),None);
        assert_eq!(h.process(&mut m,3,on(84)),None);
        assert_eq!(h.process(&mut m,3,on(74)),Some(Event::Edit{key:26,enabled:true}));
        assert_eq!(m,[0,0,4,0,0,0,0,0]);
        assert_eq!(h.process(&mut m,3,on(74)),None);
        h.process(&mut m,3,74<<8|0x90);
        assert_eq!(h.process(&mut m,3,on(74)),Some(Event::Edit{key:26,enabled:false}));
    }
    #[test]
    fn disarm_cancels_pending_but_keeps_base() {
        let mut h=HeldNotes::default();let mut m=[0;8];h.learn_base();
        h.process(&mut m,8,on(5));h.learn_base();h.clear();
        assert_eq!(h.base,0);assert_eq!(h.process(&mut m,8,on(12)),Some(Event::Edit{key:12,enabled:true}));
        assert_eq!(h.process(&mut m,8,0x4045b0),None);
    }
    #[test]
    fn another_channel_cannot_release_or_retoggle_a_held_key() {
        let mut h=HeldNotes::default();let mut m=[0;8];h.learn_base();
        assert_eq!(h.process(&mut m,8,on(60)|1),Some(Event::Base(60)));
        h.process(&mut m,8,60<<8|0x80);
        assert_eq!(h.process(&mut m,8,on(60)|1),None);
        assert_eq!(h.process(&mut m,8,on(61)),None);
        h.process(&mut m,8,60<<8|0x81);
        assert_eq!(h.process(&mut m,8,on(60)|1),Some(Event::Edit {key:0,enabled:true}));
    }
    #[test]
    fn midi_reveals_near_and_far_octaves() {
        assert_eq!(reveal(0,8,95),6);assert_eq!(reveal(6,8,12),1);
        assert_eq!(reveal(2,8,36),2);assert_eq!(reveal(0,1,11),0);
    }
}
