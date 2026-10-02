//! Compare compressed build-time guides with the former software raster path.
//! Compile after a firmware build, setting INTONO_GUIDE_TABLE to its generated file
//! and passing the host micromath rlib via --extern.
mod generated { include!(env!("INTONO_GUIDE_TABLE")); }
#[allow(dead_code)]
#[path="../src/top/intono/fw/src/ui_scene.rs"] mod ui_scene;

#[test]
fn every_circle_point_survives_signed_offset_packing() {
    assert_eq!(generated::BORDER.len(),2049);
    for step in 0..generated::BORDER.len() {
        let angle=step as f32*core::f32::consts::TAU/2048.0;
        let expected=((360+micromath::F32Ext::round(356.0*micromath::F32Ext::cos(angle)) as i32) as u16,
                      (360+micromath::F32Ext::round(356.0*micromath::F32Ext::sin(angle)) as i32) as u16);
        assert_eq!(generated::BORDER.point(step),expected,"circle point {step}");
    }
}

#[test]
fn every_spiral_point_survives_signed_offset_packing() {
    assert_eq!(generated::SPIRAL.len(),ui_scene::SPIRAL_OCTAVES*ui_scene::SPIRAL_STEPS+1);
    for step in 0..generated::SPIRAL.len() {
        let turns=1.0+step as f32/ui_scene::SPIRAL_STEPS as f32;
        let radius=ui_scene::spiral_radius(turns*12.0);
        let angle=turns*core::f32::consts::TAU-core::f32::consts::FRAC_PI_2;
        let expected=((ui_scene::SPIRAL_CENTER.0+(radius*micromath::F32Ext::cos(angle)) as i32) as u16,
                      (ui_scene::SPIRAL_CENTER.1+(radius*micromath::F32Ext::sin(angle)) as i32) as u16);
        assert_eq!(generated::SPIRAL.point(step),expected,"spiral point {step}");
    }
}
