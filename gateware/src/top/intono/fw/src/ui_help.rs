//! Page-based help, held in read-only firmware storage rather than runtime RAM.
#[path = "help_text.rs"] mod content;
pub const VISIBLE_ROWS: usize = 9;
pub fn topic(index: u8) -> (&'static str, &'static str) {
    content::TOPICS[index.min(content::TOPICS.len() as u8 - 1) as usize]
}
pub fn line_count(index: u8) -> usize { topic(index).1.lines().count() }
pub fn max_scroll(index: u8) -> u8 { line_count(index).saturating_sub(VISIBLE_ROWS) as u8 }
pub fn lines(index: u8, scroll: u8) -> impl Iterator<Item=&'static str> {
    topic(index).1.lines().skip(scroll.min(max_scroll(index)) as usize).take(VISIBLE_ROWS)
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn every_topic_fits_and_has_a_reachable_last_line() {
        for index in 0..10 {
            let (name,body)=topic(index);
            assert!(name.len()+7<=32);
            assert!(body.is_ascii());
            assert!(body.lines().all(|line|line.len()<=36));
            assert!(max_scroll(index)<=60);
            assert_eq!(lines(index,255).last(),body.lines().last());
            assert_eq!(lines(index,255).count(),VISIBLE_ROWS.min(line_count(index)));
        }
        assert_eq!(topic(255),topic(9));
    }
}
