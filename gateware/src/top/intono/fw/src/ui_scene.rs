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
pub const CAL_CURVE_SEGMENTS: usize = 128;
pub const SPIRAL_SPACING: f32 = 176.0 / SPIRAL_OCTAVES as f32;
pub fn spiral_radius(semitones: f32) -> f32 {
    52.0 + SPIRAL_SPACING
        * ((semitones - 12.0) / 12.0)
            .max(0.0)
            .min(SPIRAL_OCTAVES as f32)
}

impl Scene {
    pub const fn segments(self) -> usize {
        match self {
            Self::Spiral => 2048 + 12 + SPIRAL_OCTAVES * SPIRAL_STEPS,
            Self::Linear => 2048 + 4 * 22,
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
    Flush,
    Ready,
}

pub const CLEAR_WORDS_PER_TICK: usize = 1024;

pub struct Backgrounds {
    resident: [Option<Scene>; 2],
    preparing: Option<(usize, Scene, usize)>,
}

impl Backgrounds {
    pub fn new() -> Self {
        Self {
            resident: [Some(Scene::Spiral), None],
            preparing: None,
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
            let end = offset.saturating_add(CLEAR_WORDS_PER_TICK).min(words);
            self.preparing = Some((bank, scene, end));
            Work::Clear { first: offset, end }
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
    fn spiral_covers_high_notes_without_collapsing_octaves() {
        assert_eq!(spiral_radius(12.0), 52.0); // C0
        assert_eq!(spiral_radius(144.0), 228.0); // C11
                                                 // B8 and B9 have equal angles but must differ by a full ring.
        assert_eq!(spiral_radius(131.0) - spiral_radius(119.0), SPIRAL_SPACING);
        // 20 kHz is below E10; even E10 remains inside the guide.
        assert!(spiral_radius(136.0) < 228.0);
        for step in 0..=SPIRAL_OCTAVES * SPIRAL_STEPS {
            let turns = 1.0 + step as f32 / SPIRAL_STEPS as f32;
            let expected = 52.0 + SPIRAL_SPACING * step as f32 / SPIRAL_STEPS as f32;
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
                    Work::Clear { .. } | Work::Draw { .. } => {}
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
}
