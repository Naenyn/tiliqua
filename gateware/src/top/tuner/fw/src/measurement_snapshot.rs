//! Bounded sequence-guarded peripheral reads. Never accept a torn final attempt.
pub fn read<T>(mut sample: impl FnMut() -> (u16, T, u16)) -> Option<T> {
    for _ in 0..4 {
        let (before, value, after) = sample();
        if before == after {
            return Some(value);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stable_reads_stop_immediately() {
        let mut calls = 0;
        assert_eq!(
            read(|| {
                calls += 1;
                (7, (23, 4), 7)
            }),
            Some((23, 4))
        );
        assert_eq!(calls, 1);
    }
    #[test]
    fn rejects_torn_values_including_sequence_wrap() {
        let mut calls = 0;
        assert_eq!(
            read(|| {
                calls += 1;
                if calls == 1 {
                    (u16::MAX, 999, 0)
                } else if calls < 4 {
                    (0, 999, 1)
                } else {
                    (1, 42, 1)
                }
            }),
            Some(42)
        );
        assert_eq!(calls, 4);
    }
    #[test]
    fn exhaustion_returns_no_measurement_and_has_fixed_cost() {
        let mut calls = 0;
        assert_eq!(
            read(|| {
                calls += 1;
                (0, 999, 1)
            }),
            None
        );
        assert_eq!(calls, 4);
    }
}
