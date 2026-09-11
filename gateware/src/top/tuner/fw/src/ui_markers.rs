//! Bounded CPU descriptors for the shared four-slot renderer.
//! Coordinates are logical canvas coordinates; scanout owns rotation.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Marker {
    pub x: u16,
    pub y: u16,
    pub hue: u8,
    pub orientation: u8,
}

impl Marker {
    pub fn packed(self) -> u32 {
        if self.x >= 720 || self.y >= 720 || self.hue >= 16 || self.orientation >= 32 {
            return 0;
        }
        self.x as u32 | ((self.y as u32) << 10) |
            ((self.orientation as u32) << 20) | ((self.hue as u32) << 25) | (1 << 29)
    }

    pub fn lens_base(self) -> u16 { (self.orientation as u16 % 11) * 1089 }
    pub fn lens_bank(self) -> u8 { self.orientation / 11 }
}

/// Every publication replaces all four slots, including absent channels.
/// Never retain stale marker descriptors when channels or views change.
#[derive(Clone, Copy, Default)]
pub struct Markers(pub [Option<Marker>; 4]);

impl Markers {
    pub fn packed(self, slot: usize) -> u32 {
        self.0.get(slot).copied().flatten().map_or(0, Marker::packed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn packing_preserves_all_fields_and_legacy_atlas_mapping() {
        for orientation in 0..32 {
            for hue in 0..16 {
                for (x,y) in [(0,0),(719,719),(360,208)] {
                    let marker = Marker {x,y,hue,orientation};
                    let word = marker.packed();
                    assert_eq!(word & 1023, x as u32);
                    assert_eq!((word >> 10) & 1023, y as u32);
                    assert_eq!((word >> 20) & 31, orientation as u32);
                    assert_eq!((word >> 25) & 15, hue as u32);
                    assert_eq!(word >> 29, 1);
                    assert_eq!(marker.lens_bank() as u16 * 11 + marker.lens_base()/1089,
                               orientation as u16);
                }
            }
        }
    }

    #[test]
    fn invalid_and_missing_slots_disable_instead_of_wrapping() {
        let valid = Marker {x:360,y:360,hue:3,orientation:16};
        for marker in [Marker{x:720,..valid}, Marker{y:u16::MAX,..valid},
                       Marker{hue:16,..valid}, Marker{orientation:32,..valid}] {
            assert_eq!(marker.packed(), 0);
        }
        let frame = Markers([Some(valid),None,Some(valid),None]);
        assert_ne!(frame.packed(0),0);
        assert_ne!(frame.packed(2),0);
        for slot in [1,3,4,usize::MAX] { assert_eq!(frame.packed(slot),0); }
        for slot in 0..4 { assert_eq!(Markers::default().packed(slot),0); }
    }
}
