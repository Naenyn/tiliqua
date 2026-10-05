//! Bounded help phrase decoding, without heap allocation or a full text buffer.
#[path = "help_text.rs"]
mod content;
pub const VISIBLE_ROWS: usize = 9;
fn entry(index: u8) -> (&'static str, &'static [u8], u8) {
    content::TOPICS[index.min(9) as usize]
}
pub fn topic(index: u8) -> (&'static str, &'static [u8]) {
    let e = entry(index);
    (e.0, e.1)
}
pub fn line_count(index: u8) -> usize {
    entry(index).2 as usize
}
pub fn max_scroll(index: u8) -> u8 {
    line_count(index).saturating_sub(VISIBLE_ROWS) as u8
}
pub fn lines(index: u8, scroll: u8) -> impl Iterator<Item = heapless::String<36>> {
    let mut source = entry(index).1.iter().copied();
    let mut phrase = [].iter().copied();
    let bytes = core::iter::from_fn(move || {
        if let Some(v) = phrase.next() {
            return Some(v);
        }
        let v = source.next()?;
        let token = if v >= 128 {
            Some((v - 128) as usize)
        } else if v < 10 {
            Some(127 + v as usize)
        } else if v > 10 && v < 32 {
            Some(126 + v as usize)
        } else if v == 127 {
            Some(158)
        } else {
            None
        };
        if let Some(token) = token {
            phrase = content::DICTIONARY
                [content::OFFSETS[token] as usize..content::OFFSETS[token + 1] as usize]
                .iter()
                .copied();
            phrase.next()
        } else {
            Some(v)
        }
    });
    let mut bytes = bytes.peekable();
    core::iter::from_fn(move || {
        bytes.peek()?;
        let mut line = heapless::String::<36>::new();
        for byte in bytes.by_ref() {
            if byte == 10 {
                break;
            }
            line.push(byte as char).ok();
        }
        Some(line)
    })
    .skip(scroll.min(max_scroll(index)) as usize)
    .take(VISIBLE_ROWS)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn every_topic_fits_and_has_a_reachable_last_line() {
        for index in 0..10 {
            assert!(topic(index).0.len() + 7 <= 32);
            assert!(max_scroll(index) <= 120);
            for scroll in 0..=max_scroll(index) {
                let actual: std::vec::Vec<_> = lines(index, scroll).collect();
                let expected: std::vec::Vec<_> = content::RAW[index as usize]
                    .lines()
                    .skip(scroll as usize)
                    .take(VISIBLE_ROWS)
                    .collect();
                assert_eq!(
                    actual
                        .iter()
                        .map(|s| s.as_str())
                        .collect::<std::vec::Vec<_>>(),
                    expected
                );
            }
            let last = lines(index, max_scroll(index)).last().unwrap();
            assert_eq!(lines(index, 255).last().unwrap(), last);
            assert_eq!(
                lines(index, 255).count(),
                VISIBLE_ROWS.min(line_count(index))
            );
        }
        assert_eq!(topic(255), topic(9));
    }
}
