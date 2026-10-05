//! Instrument preferences only. Route configs, scales and profiles have their
//! own records. Always save defaults too, so an old value cannot reappear.
use crate::options::{CalibrationGraph, CalibrationPolicy, DisplayMode, Opts, UiPalette};
use opts::{persistence::OptionsPersistence, OptionTrait};

pub const KEY: u32 = 0x49504631;
const LEN: usize = 20;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Preferences {
    reference: u16,
    tuner_input: u8,
    display: u8,
    cal_input: u8,
    cal_output: u8,
    cal_zero: u8,
    policy: u8,
    graph: u8,
    palette: u8,
}
impl Default for Preferences {
    fn default() -> Self {
        Self {
            reference: 440,
            tuner_input: 0,
            display: 0,
            cal_input: 0,
            cal_output: 0,
            cal_zero: 60,
            policy: 0,
            graph: 0,
            palette: 0,
        }
    }
}
impl Preferences {
    pub fn capture(o: &Opts) -> Self {
        Self {
            reference: o.settings.reference.value,
            tuner_input: o.tuner.input.value,
            display: o.tuner.display.value as u8,
            cal_input: o.calibrate.input.value,
            cal_output: o.calibrate.output.value,
            cal_zero: o.calibrate.zero_note.value,
            policy: o.calibrate.policy.value as u8,
            graph: o.calibrate.graph.value as u8,
            palette: o.settings.palette.value as u8,
        }
    }
    fn valid(self) -> bool {
        (400..=480).contains(&self.reference)
            && self.tuner_input < 4
            && matches!(self.display, 0 | 2)
            && self.cal_input < 4
            && self.cal_output < 4
            && (12..=108).contains(&self.cal_zero)
            && self.policy < 4
            && self.graph < 2
            && self.palette < 9
    }
    pub fn apply(self, o: &mut Opts) {
        o.settings.reference.value = self.reference;
        use strum::IntoEnumIterator;
        o.settings.palette.value=UiPalette::iter().nth(self.palette as usize).unwrap_or_default();
        o.tuner.input.value = self.tuner_input;
        o.tuner.display.value = if self.display == 2 {
            DisplayMode::Linear
        } else {
            DisplayMode::Arc
        };
        o.calibrate.input.value = self.cal_input;
        o.calibrate.output.value = self.cal_output;
        o.calibrate.zero_note.value = self.cal_zero;
        o.calibrate.policy.value = match self.policy {
            1 => CalibrationPolicy::Precision,
            2 => CalibrationPolicy::Forgiving,
            3 => CalibrationPolicy::Fast,
            _ => CalibrationPolicy::Auto,
        };
        o.calibrate.graph.value = if self.graph == 1 {
            CalibrationGraph::Error
        } else {
            CalibrationGraph::Pitch
        };
    }
    pub fn encode(self) -> [u8; LEN] {
        let mut b = [0; LEN];
        b[..4].copy_from_slice(b"IPF1");
        b[4..6].copy_from_slice(&self.reference.to_le_bytes());
        b[6..13].copy_from_slice(&[
            self.tuner_input,
            self.display,
            self.cal_input,
            self.cal_output,
            self.cal_zero,
            self.policy,
            self.graph,
        ]);
        b[13]=self.palette;
        let sum = crc(&b[..16]);
        b[16..].copy_from_slice(&sum.to_le_bytes());
        b
    }
    fn decode(b: &[u8]) -> Option<Self> {
        if b.len() != LEN
            || &b[..4] != b"IPF1"
            || b[14..16] != [0; 2]
            || crc(&b[..16]) != u32::from_le_bytes(b[16..].try_into().ok()?)
        {
            return None;
        }
        let p = Self {
            reference: u16::from_le_bytes(b[4..6].try_into().ok()?),
            tuner_input: b[6],
            display: b[7],
            cal_input: b[8],
            cal_output: b[9],
            cal_zero: b[10],
            policy: b[11],
            graph: b[12],
            palette: b[13],
        };
        p.valid().then_some(p)
    }
}
fn crc(bytes: &[u8]) -> u32 {
    let mut c = !0u32;
    for b in bytes {
        c ^= *b as u32;
        for _ in 0..8 {
            c = (c >> 1) ^ 0xedb88320u32.wrapping_mul(c & 1);
        }
    }
    !c
}
pub fn save<P: OptionsPersistence>(storage: &mut P, p: Preferences) -> Result<(), P::Error> {
    storage.save_key_retries(KEY, &p.encode(), 2)
}
pub fn load<P: OptionsPersistence>(storage: &mut P, o: &mut Opts) -> Result<(), P::Error> {
    let mut b = [0; 32];
    if let Some(len) = storage.load_key(KEY, &mut b)? {
        // A damaged new record must not resurrect obsolete legacy values.
        if let Some(p) = Preferences::decode(&b[..len]) {
            p.apply(o);
        }
        return Ok(());
    }
    // Migrate only the preference fields from the old generic Options journal.
    // Ignore editor fields, slot selectors, saved page and one-shot actions.
    let migration = (|| {
        let fields: [&mut dyn OptionTrait; 8] = [
            &mut o.settings.reference,
            &mut o.tuner.input,
            &mut o.tuner.display,
            &mut o.calibrate.input,
            &mut o.calibrate.output,
            &mut o.calibrate.zero_note,
            &mut o.calibrate.policy,
            &mut o.calibrate.graph,
        ];
        for f in fields {
            if let Some(len) = storage.load_key(f.key().value(), &mut b)? {
                f.decode(&b[..len]);
            }
        }
        Ok(())
    })();
    if let Err(error) = migration {
        Preferences::default().apply(o);
        return Err(error);
    }
    let mut p = Preferences::capture(o);
    if p.display == 1 {
        p.display = 0;
    } // Removed Visualizer preference becomes Arc.
    if !p.valid() {
        p = Preferences::default();
    }
    p.apply(o);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use opts::{persistence::OptionsPersistence, Options};
    use std::collections::BTreeMap;
    #[derive(Default)]
    struct Store {
        records: BTreeMap<u32, std::vec::Vec<u8>>,
        writes: std::vec::Vec<u32>,
    }
    impl OptionsPersistence for Store {
        type Error = ();
        fn save_key(&mut self, k: u32, b: &[u8]) -> Result<(), ()> {
            self.writes.push(k);
            self.records.insert(k, b.to_vec());
            Ok(())
        }
        fn save_key_retries(&mut self, k: u32, b: &[u8], _: usize) -> Result<(), ()> {
            self.save_key(k, b)
        }
        fn load_key(&mut self, k: u32, b: &mut [u8]) -> Result<Option<usize>, ()> {
            let Some(v) = self.records.get(&k) else {
                return Ok(None);
            };
            if v.len() > b.len() {
                return Err(());
            }
            b[..v.len()].copy_from_slice(v);
            Ok(Some(v.len()))
        }
        fn erase_all(&mut self) -> Result<(), ()> {
            panic!("must not erase profiles/scales/configs")
        }
        fn load_options<O: Options>(&mut self, _: &mut O) -> Result<(), ()> {
            panic!("must not load editor selections")
        }
        fn save_options<O: Options>(&mut self, _: &O) -> Result<(), ()> {
            panic!("must not save editor selections")
        }
    }
    #[test]
    fn save_roundtrip_defaults_and_reset_leave_other_records_and_editors_alone() {
        let mut store = Store::default();
        store.records.insert(0x1234, vec![1, 2, 3]);
        let mut o = Opts::default();
        o.settings.reference.value = 442;
        o.tuner.input.value = 3;
        o.tuner.display.value = DisplayMode::Linear;
        o.calibrate.input.value = 2;
        o.calibrate.output.value = 1;
        o.calibrate.zero_note.value = 24;
        o.calibrate.policy.value = CalibrationPolicy::Precision;
        o.calibrate.graph.value = CalibrationGraph::Error;
        o.play.transpose.value = 7;
        o.quant_setups.slot.value = 8;
        save(&mut store, Preferences::capture(&o)).unwrap();
        assert_eq!(store.writes, vec![KEY]);
        let mut loaded = Opts::default();
        load(&mut store, &mut loaded).unwrap();
        assert_eq!(Preferences::capture(&loaded), Preferences::capture(&o));
        assert_eq!(loaded.play.transpose.value, 0);
        assert_eq!(loaded.quant_setups.slot.value, 1);
        Preferences::default().apply(&mut o);
        assert_eq!(o.play.transpose.value, 7);
        assert_eq!(o.quant_setups.slot.value, 8);
        save(&mut store, Preferences::default()).unwrap();
        load(&mut store, &mut loaded).unwrap();
        assert_eq!(Preferences::capture(&loaded), Preferences::default());
        assert_eq!(store.records.get(&0x1234).unwrap(), &vec![1, 2, 3]);
    }
    #[test]
    fn legacy_migration_reads_only_preferences_and_not_page_or_route_fields() {
        let mut old = Opts::default();
        old.settings.reference.value = 432;
        old.tuner.input.value = 2;
        old.play.transpose.value = 9;
        old.quant_setups.slot.value = 6;
        old.route_midi.channel.value = 5;
        let mut store = Store::default();
        let mut b = [0; 32];
        for f in old.all() {
            if let Some(n) = f.encode(&mut b) {
                store.records.insert(f.key().value(), b[..n].to_vec());
            }
        }
        store.records.insert(0xdeadbeef, vec![6]);
        let mut loaded = Opts::default();
        load(&mut store, &mut loaded).unwrap();
        assert_eq!(loaded.settings.reference.value, 432);
        assert_eq!(loaded.tuner.input.value, 2);
        assert_eq!(loaded.play.transpose.value, 0);
        assert_eq!(loaded.quant_setups.slot.value, 1);
        assert_eq!(loaded.route_midi.channel.value, 0);
        assert!(loaded.tracker.page.value == crate::options::Page::Tuner);
        assert!(store.writes.is_empty());
        assert!(loaded.all().all(|f| f.key().value() != KEY));
    }
    #[test]
    fn corruption_or_invalid_fields_cannot_partially_apply_or_restore_legacy_values() {
        let good = Preferences::default().encode();
        for i in 0..LEN {
            let mut bad = good;
            bad[i] ^= 1;
            assert!(Preferences::decode(&bad).is_none());
        }
        for (index, value) in [(6, 4), (7, 1), (8, 4), (9, 4), (10, 0), (11, 4), (12, 2), (13,9)] {
            let mut b = good;
            b[index] = value;
            let sum = crc(&b[..16]);
            b[16..].copy_from_slice(&sum.to_le_bytes());
            assert!(Preferences::decode(&b).is_none());
        }
        let mut store = Store::default();
        store.records.insert(KEY, vec![0; LEN]);
        let mut old = Opts::default();
        old.settings.reference.value = 432;
        let mut b = [0; 32];
        let f = &old.settings.reference;
        let n = f.encode(&mut b).unwrap();
        store.records.insert(f.key().value(), b[..n].to_vec());
        let mut loaded = Opts::default();
        load(&mut store, &mut loaded).unwrap();
        assert_eq!(loaded.settings.reference.value, 440);
    }
}

#[cfg(test)] mod palette_tests {
 use super::*;
 #[test]fn palettes_roundtrip_and_legacy_blue_defaults(){
  for value in 0..9 {let mut p=Preferences::default();p.palette=value;assert_eq!(Preferences::decode(&p.encode()),Some(p));let mut o=Opts::default();p.apply(&mut o);assert_eq!(o.settings.palette.value as u8,value);}
  assert_eq!(Preferences::default().encode()[13],0);
 }
}
