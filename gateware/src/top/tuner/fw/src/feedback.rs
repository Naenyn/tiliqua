//! Transient action feedback, retained independently of one-shot UI buttons.

#[derive(Default)]
pub struct Feedback {
    message: &'static str,
    remaining_ms: u16,
}

impl Feedback {
    pub fn show(&mut self, message: &'static str) {
        self.message = message;
        self.remaining_ms = 2000;
    }

    pub fn message(&self) -> &'static str { self.message }

    // Returns true only when visible text changes, so both display banks can
    // be invalidated without rebuilding the menu on every timer wakeup.
    pub fn tick(&mut self, elapsed_ms: u16) -> bool {
        if self.remaining_ms == 0 { return false; }
        self.remaining_ms = self.remaining_ms.saturating_sub(elapsed_ms);
        if self.remaining_ms == 0 {
            self.message = "";
            return true;
        }
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn confirmation_survives_many_polls_and_expires_once() {
        let mut feedback = Feedback::default();
        assert!(!feedback.tick(5));
        feedback.show("saved");
        for _ in 0..399 {
            assert!(!feedback.tick(5));
            assert_eq!(feedback.message(), "saved");
        }
        assert!(feedback.tick(5));
        assert_eq!(feedback.message(), "");
        assert!(!feedback.tick(5));
    }

    #[test]
    fn new_result_replaces_previous_and_restarts_duration() {
        let mut feedback = Feedback::default();
        feedback.show("saved");
        feedback.tick(1995);
        feedback.show("failed");
        assert!(!feedback.tick(5));
        assert_eq!(feedback.message(), "failed");
        feedback.show("no flash");
        assert!(feedback.tick(u16::MAX));
        assert_eq!(feedback.message(), "");
    }
}
