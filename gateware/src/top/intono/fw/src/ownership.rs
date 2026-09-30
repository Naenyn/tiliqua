//! Jack roles: passive audio observers, one exclusive scan, shared CV sources.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Owner {
    Calibration,
    Quant(u8),
}
impl Owner {
    fn index(self) -> Option<usize> {
        match self {
            Self::Calibration => Some(0),
            Self::Quant(n) if n < 4 => Some(1 + n as usize),
            _ => None,
        }
    }
}
#[derive(Clone, Copy)]
pub struct Reservations {
    inputs: [u8; 5],
    outputs: [u8; 5],
}
impl Reservations {
    pub const fn new() -> Self {
        Self {
            inputs: [0; 5],
            outputs: [0; 5],
        }
    }
    pub fn claim(&mut self, owner: Owner, inputs: u8, outputs: u8) -> bool {
        let Some(index) = owner.index() else {
            return false;
        };
        if (inputs | outputs) & !15 != 0 || inputs | outputs == 0 {
            return false;
        }
        if self.inputs[index] | self.outputs[index] != 0 {
            return self.inputs[index] == inputs && self.outputs[index] == outputs;
        }
        for n in 0..5 {
            let shared_cv = index > 0 && n > 0;
            if self.outputs[n] & outputs != 0 || (!shared_cv && self.inputs[n] & inputs != 0) {
                return false;
            }
        }
        self.inputs[index] = inputs;
        self.outputs[index] = outputs;
        true
    }
    pub fn release(&mut self, owner: Owner) {
        if let Some(n) = owner.index() {
            self.inputs[n] = 0;
            self.outputs[n] = 0;
        }
    }
    pub fn held(&self, owner: Owner) -> bool {
        owner
            .index()
            .is_some_and(|n| self.inputs[n] | self.outputs[n] != 0)
    }
    pub fn cv_inputs(&self) -> u8 {
        self.inputs[1..].iter().fold(0, |mask, input| mask | input)
    }
    /// Passive observation does not compete with an operation's jack claims.
    pub fn tuner_available(&self, input: u8) -> bool {
        input < 4
    }
    pub fn focus(&self, requested: u8, previous: u8) -> Option<u8> {
        let backwards = requested < previous;
        (0..4)
            .map(|offset| {
                if backwards {
                    (requested + 4 - offset) % 4
                } else {
                    (requested + offset) % 4
                }
            })
            .find(|input| self.tuner_available(*input))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn passive_tuner_observes_claimed_inputs_without_claiming_them() {
        let mut r = Reservations::new();
        assert!(r.claim(Owner::Calibration, 2, 2));
        assert!(r.tuner_available(1));
        assert!(r.claim(Owner::Quant(2), 4, 4));
        assert!(r.tuner_available(2));
        assert_eq!(r.focus(2, 1), Some(2));
        assert_eq!(r.focus(2, 3), Some(2));
        assert!(!r.claim(Owner::Quant(3), 2, 8));
        assert!(!r.held(Owner::Quant(3)));
        assert!(r.claim(Owner::Quant(3), 4, 8));
        r.release(Owner::Quant(2));
        assert!(r.tuner_available(2));
        r.release(Owner::Quant(3));
        assert!(r.tuner_available(2));
    }
    #[test]
    fn output_exclusion_and_immutable_routes() {
        let mut r = Reservations::new();
        assert!(r.claim(Owner::Quant(0), 1, 1));
        assert!(!r.claim(Owner::Calibration, 2, 1));
        assert!(!r.claim(Owner::Calibration, 1, 2));
        assert!(!r.claim(Owner::Quant(0), 2, 1));
        assert!(r.claim(Owner::Calibration, 2, 2));
        assert!(!r.claim(Owner::Quant(4), 1, 1));
        assert!(!r.claim(Owner::Quant(1), 16, 1));
    }
    #[test]
    fn all_cv_inputs_remain_observable() {
        let mut r = Reservations::new();
        for n in 0..4 {
            assert!(r.claim(Owner::Quant(n), 1 << n, 1 << n));
        }
        assert_eq!(r.focus(0, 0), Some(0));
        r.release(Owner::Quant(2));
        assert_eq!(r.focus(0, 0), Some(0));
    }
}
