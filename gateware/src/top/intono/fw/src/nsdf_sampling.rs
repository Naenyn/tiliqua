//! Pitch-detector work allocation. Does not claim jacks or write outputs.
//! An operation reads one captured input; the passive tuner can request
//! background observations without becoming a competing operation.
pub struct Sampling {
    input: Option<u8>,
    tuner_visible: bool,
    full_slot: u8,
    focus_bank: u8,
    focus_visits: u8,
    background_slot: u8,
}
impl Sampling {
    pub fn new() -> Self {
        Self {
            input: None,
            tuner_visible: false,
            // Scheduler::new already has bank zero queued.
            full_slot: 1,
            focus_bank: 0,
            focus_visits: 0,
            background_slot: 0,
        }
    }
    /// Reset only on an actual request change, never on every foreground tick.
    /// Invalid inputs restore the passive all-input schedule.
    pub fn configure(&mut self, input: Option<u8>, tuner_visible: bool) -> bool {
        let input = input.filter(|&n| n < 4);
        let tuner_visible = input.is_some() && tuner_visible;
        if self.input == input && self.tuner_visible == tuner_visible {
            return false;
        }
        self.input = input;
        self.tuner_visible = tuner_visible;
        self.full_slot = 0;
        self.focus_bank = 0;
        self.focus_visits = 0;
        self.background_slot = 0;
        true
    }
    pub fn next(&mut self) -> u8 {
        let Some(input) = self.input else {
            let slot = self.full_slot;
            self.full_slot = (slot + 1) & 7;
            return slot;
        };
        // Two operation-bank visits, then one background bank. Each other
        // bank is visited every 18 slots while TUNER is visible, rather than
        // letting stale cached readings masquerade as a live all-input view.
        if self.tuner_visible && self.focus_visits == 2 {
            while self.background_slot >> 1 == input {
                self.background_slot = (self.background_slot + 1) & 7;
            }
            let slot = self.background_slot;
            self.background_slot = (slot + 1) & 7;
            self.focus_visits = 0;
            return slot;
        }
        let slot = (input << 1) | self.focus_bank;
        self.focus_bank ^= 1;
        if self.tuner_visible { self.focus_visits += 1; }
        slot
    }
}
