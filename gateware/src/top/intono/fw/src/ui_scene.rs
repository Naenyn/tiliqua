//! Small retained-background preparation state, independent of hardware.
//! The caller may step only while the exchange is idle, on its back buffer.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Scene {
    Spiral,
    Linear,
    Calibration,
}

// C0 through C11 encloses the entire 20 Hz–20 kHz detector range. Share
// geometry between both background drawing paths and every live marker.
pub const SPIRAL_OCTAVES: usize = 11;
pub const SPIRAL_STEPS: usize = 192;
pub const CAL_GRID_SEGMENTS: usize = 16;
// The profile holds 121 acquisition anchors plus 8 refinement anchors.
pub const CAL_CURVE_SEGMENTS: usize = 129;
pub const VIEWPORT_CENTER: (i32, i32) = (360, 360);
pub const SPIRAL_CENTER: (i32, i32) = (300, 360);
pub const SPIRAL_SPOKE_RADIUS: f32 = 160.0;
pub const SPIRAL_SPACING: f32 = 110.0 / SPIRAL_OCTAVES as f32;
pub fn spiral_radius(semitones: f32) -> f32 {
    40.0 + SPIRAL_SPACING
        * ((semitones - 12.0) / 12.0)
            .max(0.0)
            .min(SPIRAL_OCTAVES as f32)
}

impl Scene {
    pub const fn segments(self) -> usize {
        match self {
            Self::Spiral => 2048 + 12 + SPIRAL_OCTAVES * SPIRAL_STEPS,
            Self::Linear => 2048 + 4 * 22 + 3,
            Self::Calibration => 2048 + CAL_GRID_SEGMENTS + 1 + CAL_CURVE_SEGMENTS,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Work {
    Clear {
        first: usize,
        end: usize,
    },
    Draw {
        scene: Scene,
        first: usize,
        end: usize,
    },
    /// Copy an immutable tuner image, or the circle-only CAL template.
    Copy { source: Option<Scene>, first: usize, end: usize },
    Flush,
    Ready,
}

/// Publish one holding view during preparation, then leave the exchange idle.
/// Routine foreground commits otherwise hold it busy until every video frame,
/// stretching a 5 ms background batch to 20 ms. Operation polling continues.
/// Latch only after an actual commit; a busy exchange is not a publication.
pub struct PublicationHold<Key> {
    held: Option<Key>,
}
impl<Key: Copy + PartialEq> PublicationHold<Key> {
    pub const fn new() -> Self { Self { held: None } }
    pub fn allow(&self, key: Key, preparing: bool, ready: bool) -> bool {
        !preparing || ready || self.held != Some(key)
    }
    pub fn published(&mut self, key: Key, preparing: bool, ready: bool) {
        self.held = if preparing && !ready { Some(key) } else { None };
    }
}

pub const CLEAR_WORDS_PER_TICK: usize = 1024;
// A bounded sequential transfer replaces thousands of software trig calls.
pub const COPY_WORDS_PER_TICK: usize = 4096;
pub const CACHE_OFFSET: usize = 0x800000;
pub const CACHE_STRIDE: usize = 0x100000;
pub const KEYBOARD_CACHE: usize = CACHE_OFFSET + 3 * CACHE_STRIDE;
pub const SINGLE_KEYBOARD_CACHE: usize = CACHE_OFFSET + 4 * CACHE_STRIDE;
pub const CACHE_END: usize = CACHE_OFFSET + 5 * CACHE_STRIDE;
pub const fn cache_offset(source: Option<Scene>) -> usize {
    CACHE_OFFSET + CACHE_STRIDE * match source {
        Some(Scene::Spiral) => 0, Some(Scene::Linear) => 1,
        None => 2, Some(Scene::Calibration) => panic!("CAL is mutable"),
    }
}

/// Tracks provisional graph strokes independently for the two framebuffer
/// banks. Only the back bank is extended before publication. A restarted
/// discovery segment must first clear both old traces.
pub struct LiveTrace {
    active: bool,
    first: Option<(i32, i32)>,
    last: Option<(i32, i32)>,
    count: usize,
    drawn: [usize; 2],
}

impl LiveTrace {
    pub const fn new() -> Self {
        Self { active: false, first: None, last: None, count: 0, drawn: [0; 2] }
    }

    /// Returns true only when previously drawn provisional pixels must be
    /// erased. Entering a fresh empty sweep must not invalidate both CAL
    /// backgrounds while the output watchdog is running.
    pub fn observe(
        &mut self,
        active: bool,
        first: Option<(i32, i32)>,
        last: Option<(i32, i32)>,
        count: usize,
    ) -> bool {
        if !active {
            let needs_clear = self.drawn.iter().any(|&drawn| drawn > 0);
            self.active = false;
            self.first = None;
            self.last = None;
            self.count = 0;
            self.drawn = [0; 2];
            return needs_clear;
        }
        let restart = !self.active
            || (self.first.is_some() && self.first != first)
            || count < self.count
            || (count == self.count && self.last != last);
        let needs_clear = restart && self.drawn.iter().any(|&drawn| drawn > 0);
        if restart {
            self.drawn = [0; 2];
        }
        self.active = true;
        self.first = first;
        self.last = last;
        self.count = count;
        needs_clear
    }

    pub fn reset_bank(&mut self, bank: usize) {
        self.drawn[bank] = 0;
    }

    pub fn pending(&self, bank: usize) -> core::ops::Range<usize> {
        self.drawn[bank]..self.count
    }

    pub fn mark_drawn(&mut self, bank: usize) {
        self.drawn[bank] = self.count;
    }
}

pub struct Backgrounds {
    resident: [Option<Scene>; 2],
    preparing: Option<(usize, Scene, usize)>,
    cached_tuners: bool,
}

impl Backgrounds {
    pub fn with_prepared_calibration() -> Self {
        Self {
            resident: [Some(Scene::Spiral), Some(Scene::Calibration)],
            preparing: None,
            cached_tuners: false,
        }
    }

    pub fn with_cached_tuners() -> Self {
        let mut result = Self::with_prepared_calibration();
        result.cached_tuners = true;
        result
    }

    pub fn new() -> Self {
        Self {
            resident: [Some(Scene::Spiral), None],
            preparing: None,
            cached_tuners: false,
        }
    }

    /// A newly accepted or loaded profile changes the retained calibration
    /// plot, even though its scene identity has not changed.
    pub fn invalidate_calibration(&mut self) {
        for resident in &mut self.resident {
            if *resident == Some(Scene::Calibration) {
                *resident = None;
            }
        }
        if self.preparing.is_some_and(|(_, scene, _)| scene == Scene::Calibration) {
            self.preparing = None;
        }
    }

    // Every returned range must be completed before the next step. Flush is
    // repeated until explicitly acknowledged; incomplete drawing is not ready.
    pub fn step(&mut self, bank: usize, scene: Scene, words: usize) -> Work {
        assert!(bank < 2);
        if self.resident[bank] == Some(scene) {
            return Work::Ready;
        }
        let offset = match self.preparing {
            Some((b, s, offset)) if b == bank && s == scene => offset,
            _ => 0,
        };
        self.resident[bank] = None;
        if offset < words {
            let end = offset.saturating_add(if self.cached_tuners {
                COPY_WORDS_PER_TICK
            } else { CLEAR_WORDS_PER_TICK }).min(words);
            self.preparing = Some((bank, scene, end));
            if self.cached_tuners {
                // Static tuner images are complete after the copy. CAL keeps
                // the border but regenerates only its changing graph strokes.
                if end == words {
                    let drawn = if scene == Scene::Calibration { 2048 } else { scene.segments() };
                    self.preparing = Some((bank, scene, words + drawn));
                }
                Work::Copy { source: if scene == Scene::Calibration { None } else { Some(scene) },
                    first: offset, end }
            } else { Work::Clear { first: offset, end } }
        } else if offset - words < scene.segments() {
            let first = offset - words;
            // Border segments are at most a few pixels. Longer guide lines
            // receive a smaller batch; never cross that boundary in one call.
            let end = if first < 2048 {
                (first + 32).min(2048)
            } else {
                (first + 4).min(scene.segments())
            };
            self.preparing = Some((bank, scene, words + end));
            Work::Draw { scene, first, end }
        } else {
            Work::Flush
        }
    }

    pub fn flushed(&mut self, bank: usize, scene: Scene, words: usize) -> bool {
        if self.preparing != Some((bank, scene, words + scene.segments())) {
            return false;
        }
        self.preparing = None;
        self.resident[bank] = Some(scene);
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn empty_calibration_dashboard_is_ready_before_first_scan() {
        let mut backgrounds = Backgrounds::with_prepared_calibration();
        assert_eq!(backgrounds.step(0, Scene::Spiral, 720 * 720 / 4), Work::Ready);
        assert_eq!(backgrounds.step(1, Scene::Calibration, 720 * 720 / 4), Work::Ready);
        backgrounds.invalidate_calibration();
        assert!(matches!(
            backgrounds.step(1, Scene::Calibration, 720 * 720 / 4),
            Work::Clear { first: 0, .. }
        ));
    }
    #[test]
    fn spiral_covers_high_notes_without_collapsing_octaves() {
        assert_eq!(spiral_radius(12.0), 40.0); // C0
        assert_eq!(spiral_radius(144.0), 150.0); // C11
                                                 // B8 and B9 have equal angles but must differ by a full ring.
        assert_eq!(spiral_radius(131.0) - spiral_radius(119.0), SPIRAL_SPACING);
        // 20 kHz is below E10; even E10 remains inside the guide.
        assert!(spiral_radius(136.0) < 150.0);
        for step in 0..=SPIRAL_OCTAVES * SPIRAL_STEPS {
            let turns = 1.0 + step as f32 / SPIRAL_STEPS as f32;
            let expected = 40.0 + SPIRAL_SPACING * step as f32 / SPIRAL_STEPS as f32;
            assert!((spiral_radius(turns * 12.0) - expected).abs() < 0.0001);
        }
    }
    #[test]
    fn bounded_preparation_then_cached_repeated_switches() {
        for words in [1280 * 720 / 4, 720 * 720 / 4] {
            let mut backgrounds = Backgrounds::new();
            let mut cleared = 0;
            let mut drawn = 0;
            loop {
                match backgrounds.step(1, Scene::Linear, words) {
                    Work::Clear { first, end } => {
                        assert_eq!(first, cleared);
                        assert!(end - first <= CLEAR_WORDS_PER_TICK);
                        cleared = end;
                    }
                    Work::Draw {
                        scene: Scene::Linear,
                        first,
                        end,
                    } => {
                        assert_eq!(first, drawn);
                        assert!(end - first <= if first < 2048 { 32 } else { 4 });
                        drawn = end;
                    }
                    Work::Flush => {
                        assert_eq!(drawn, Scene::Linear.segments());
                        assert_eq!(backgrounds.step(1, Scene::Linear, words), Work::Flush);
                        assert!(backgrounds.flushed(1, Scene::Linear, words));
                        break;
                    }
                    other => panic!("unexpected work: {:?}", other),
                }
            }
            assert_eq!(cleared, words);
            for _ in 0..100 {
                assert_eq!(backgrounds.step(0, Scene::Spiral, words), Work::Ready);
                assert_eq!(backgrounds.step(1, Scene::Linear, words), Work::Ready);
            }
        }
    }
    #[test]
    fn interrupted_preparation_never_presents_partial_scene_as_ready() {
        let mut backgrounds = Backgrounds::new();
        backgrounds.step(1, Scene::Linear, 2048);
        assert!(!backgrounds.flushed(1, Scene::Linear, 2048));
        assert_eq!(
            backgrounds.step(1, Scene::Spiral, 2048),
            Work::Clear {
                first: 0,
                end: 1024
            }
        );
        assert_eq!(
            backgrounds.step(1, Scene::Linear, 2048),
            Work::Clear {
                first: 0,
                end: 1024
            }
        );
    }

    #[test]
    fn every_segment_is_covered_once_and_flush_is_explicit_for_both_scenes() {
        for scene in [Scene::Spiral, Scene::Linear, Scene::Calibration] {
            let mut backgrounds = Backgrounds::new();
            let mut segments = Vec::new();
            let words = 2048;
            loop {
                match backgrounds.step(1, scene, words) {
                    Work::Clear { .. } => {}
                    Work::Draw {
                        scene: actual,
                        first,
                        end,
                    } => {
                        assert_eq!(actual, scene);
                        assert!(end - first <= if first < 2048 { 32 } else { 4 });
                        assert!(!backgrounds.flushed(0, scene, words));
                        segments.extend(first..end);
                    }
                    Work::Flush => break,
                    Work::Ready => panic!("published before flush"),
                    Work::Copy { .. } => panic!("legacy raster path copied"),
                }
            }
            assert_eq!(segments, (0..scene.segments()).collect::<Vec<_>>());
            for _ in 0..10 {
                assert_eq!(backgrounds.step(1, scene, words), Work::Flush);
            }
            assert!(backgrounds.flushed(1, scene, words));
            assert_eq!(backgrounds.step(1, scene, words), Work::Ready);
        }
    }

    #[test]
    fn changing_scene_during_drawing_restarts_clear() {
        let mut backgrounds = Backgrounds::new();
        backgrounds.step(1, Scene::Linear, 1024);
        assert!(matches!(
            backgrounds.step(1, Scene::Linear, 1024),
            Work::Draw { .. }
        ));
        assert_eq!(
            backgrounds.step(1, Scene::Spiral, 1024),
            Work::Clear {
                first: 0,
                end: 1024
            }
        );
        assert!(!backgrounds.flushed(1, Scene::Linear, 1024));
    }

    #[test]
    fn calibration_invalidation_rebuilds_both_cached_banks() {
        let mut backgrounds = Backgrounds::new();
        let words = 1024;
        for bank in 0..2 {
            loop {
                match backgrounds.step(bank, Scene::Calibration, words) {
                    Work::Clear { .. } | Work::Copy { .. } | Work::Draw { .. } => {}
                    Work::Flush => {
                        assert!(backgrounds.flushed(bank, Scene::Calibration, words));
                        break;
                    }
                    Work::Ready => panic!("calibration was not prepared"),
                }
            }
            assert_eq!(backgrounds.step(bank, Scene::Calibration, words), Work::Ready);
        }
        backgrounds.invalidate_calibration();
        for bank in 0..2 {
            assert_eq!(backgrounds.step(bank, Scene::Calibration, words),
                Work::Clear { first: 0, end: words });
        }
    }

    #[test]
    fn pending_background_gets_one_holding_commit_not_one_per_video_frame() {
        let mut hold = PublicationHold::new();
        let key = (Scene::Spiral, 0);
        assert!(hold.allow(key, true, false));
        // An attempted but busy publication must not latch the holding view.
        assert!(hold.allow(key, true, false));
        hold.published(key, true, false);
        for _ in 0..96 { assert!(!hold.allow(key, true, false)); }
        assert!(hold.allow((Scene::Linear, 0), true, false));
        assert!(hold.allow((Scene::Spiral, 1), true, false)); // changed page
        assert!(hold.allow(key, true, true));
        hold.published(key, true, true);
        assert!(hold.allow(key, true, false)); // fresh graph revision
        assert!(hold.allow(key, false, false)); // normal live updates
    }

    #[test]
    fn cached_tuners_copy_exactly_once_without_rasterizing() {
        for words in [1280 * 720 / 4, 720 * 720 / 4] {
            for scene in [Scene::Spiral, Scene::Linear] {
                let mut backgrounds = Backgrounds::with_cached_tuners();
                let mut copied = 0;
                loop {
                    match backgrounds.step(1, scene, words) {
                        Work::Copy { source, first, end } => {
                            assert_eq!(source, Some(scene));
                            assert_eq!(first, copied);
                            assert!(end - first <= COPY_WORDS_PER_TICK);
                            copied = end;
                        }
                        Work::Flush => {
                            assert_eq!(copied, words);
                            assert!(backgrounds.flushed(1, scene, words));
                            break;
                        }
                        other => panic!("unexpected work: {:?}", other),
                    }
                }
                assert_eq!(backgrounds.step(1, scene, words), Work::Ready);
            }
        }
    }

    #[test]
    fn cached_calibration_copies_border_and_draws_only_graph() {
        let words = 1280 * 720 / 4;
        let mut backgrounds = Backgrounds::with_cached_tuners();
        backgrounds.invalidate_calibration();
        let mut copied = 0;
        let mut drawn = 2048;
        let mut ticks = 0;
        loop {
            ticks += 1;
            match backgrounds.step(1, Scene::Calibration, words) {
                Work::Copy { source, first, end } => {
                    assert_eq!(source, None);
                    assert_eq!(first, copied);
                    copied = end;
                }
                Work::Draw { scene, first, end } => {
                    assert_eq!(scene, Scene::Calibration);
                    assert_eq!(copied, words);
                    assert_eq!(first, drawn);
                    drawn = end;
                }
                Work::Flush => {
                    assert_eq!(drawn, Scene::Calibration.segments());
                    assert!(backgrounds.flushed(1, Scene::Calibration, words));
                    break;
                }
                other => panic!("unexpected work: {:?}", other),
            }
        }
        assert!(ticks <= 96); // <=480 ms scheduling time, formerly ~1.7 s.
    }

    #[test]
    fn cancelled_copy_restarts_and_never_publishes_partial_pixels() {
        let mut backgrounds = Backgrounds::with_cached_tuners();
        let words = 8192;
        assert_eq!(backgrounds.step(1, Scene::Linear, words),
            Work::Copy { source: Some(Scene::Linear), first: 0, end: 4096 });
        assert!(!backgrounds.flushed(1, Scene::Linear, words));
        assert_eq!(backgrounds.step(1, Scene::Spiral, words),
            Work::Copy { source: Some(Scene::Spiral), first: 0, end: 4096 });
        assert_eq!(backgrounds.step(0, Scene::Linear, words),
            Work::Copy { source: Some(Scene::Linear), first: 0, end: 4096 });
    }

    #[test]
    fn live_trace_advances_each_bank_and_restarts_on_discontinuity() {
        let mut trace = LiveTrace::new();
        assert!(!trace.observe(true, None, None, 0));
        assert!(trace.pending(0).is_empty());
        assert!(!trace.observe(true, Some((-5, 100)), Some((-4, 200)), 2));
        assert_eq!(trace.pending(0), 0..2);
        trace.mark_drawn(0);
        assert!(trace.pending(0).is_empty());
        assert_eq!(trace.pending(1), 0..2);
        assert!(!trace.observe(true, Some((-5, 100)), Some((-3, 300)), 3));
        assert_eq!(trace.pending(0), 2..3);
        assert_eq!(trace.pending(1), 0..3);
        assert!(trace.observe(true, Some((0, 800)), Some((1, 900)), 2));
        assert_eq!(trace.pending(0), 0..2);
        trace.mark_drawn(0);
        trace.reset_bank(0);
        assert_eq!(trace.pending(0), 0..2);
        assert!(!trace.observe(false, None, None, 0));
        assert!(!trace.observe(true, None, None, 0));
        assert!(!trace.observe(true, Some((0, 800)), Some((1, 900)), 2));
        trace.mark_drawn(1);
        assert!(trace.observe(false, None, None, 0));
    }
}
