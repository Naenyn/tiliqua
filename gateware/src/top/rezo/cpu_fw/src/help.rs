//! Runtime-only HELP navigation. No sound or saved-state fields are touched.
pub struct HelpView {
    pub topic: usize,
    pub scroll: u32,
}

impl HelpView {
    pub const fn new() -> Self {
        Self {
            topic: 0,
            scroll: 0,
        }
    }

    pub fn change_topic(&mut self, delta: i32, count: usize) {
        self.topic = (self.topic as i32 + delta).rem_euclid(count as i32) as usize;
        self.scroll = 0;
    }

    pub fn scroll(&mut self, delta: i32, limit: u32) {
        self.scroll = (self.scroll as i64 + delta as i64).clamp(0, limit as i64) as u32;
    }

    /// Firmware owns row lookup. The display needs only an absolute offset
    /// and a topic-header index, avoiding a hardware topic-offset multiplexer.
    pub fn packed(&self, offsets: &[u32], row_bits: u32) -> u32 {
        ((self.topic as u32) << row_bits) | (offsets[self.topic] + self.scroll)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn topic_wrap_resets_scroll() {
        let mut view = HelpView::new();
        view.scroll = 7;
        view.change_topic(-1, 9);
        assert_eq!((view.topic, view.scroll), (8, 0));
        view.change_topic(1, 9);
        assert_eq!((view.topic, view.scroll), (0, 0));
    }

    #[test]
    fn scroll_clamps_at_both_ends() {
        let mut view = HelpView::new();
        view.scroll(-1, 18);
        assert_eq!(view.scroll, 0);
        view.scroll(127, 18);
        assert_eq!(view.scroll, 18);
        view.scroll(-127, 18);
        assert_eq!(view.scroll, 0);
    }

    #[test]
    fn packed_view_keeps_topic_and_row_separate() {
        let view = HelpView {
            topic: 8,
            scroll: 13,
        };
        let packed = view.packed(&[0, 24, 57, 92, 129, 154, 189, 228, 266], 9);
        assert_eq!(packed >> 9, 8);
        assert_eq!(packed & 511, 279);
    }
}
