//! Use the actual instrument options/navigation, including persisted enum IDs.
#[path = "../../../top/intono/fw/src/options.rs"]
mod options;
#[path = "../../../top/intono/fw/src/ui_navigation.rs"]
mod ui_navigation;
#[path = "../../../top/intono/fw/src/ui_keyboard.rs"] mod ui_keyboard;
use options::{Opts,Page,DisplayMode};
use opts::OptionsEncoderInterface;
#[path = "../../../top/intono/fw/src/ownership.rs"] mod ownership;
fn visible_ticks(opts:&mut Opts,ticks:i8) {
    ui_navigation::visible_ticks(opts,ticks,&ownership::Reservations::new());
}

#[test]
fn encoder_moves_between_visible_controls_and_skips_measured_reference() {
    let mut opts=Opts::default();
    visible_ticks(&mut opts,1);
    assert_eq!(opts.tracker.selected,Some(0));
    opts.toggle_modify(); visible_ticks(&mut opts,1);
    assert_eq!(opts.tuner.input.value,1);
    opts.toggle_modify(); visible_ticks(&mut opts,-1);
    assert!(opts.tracker.selected.is_none());
    opts.toggle_modify(); visible_ticks(&mut opts,1);
    assert!(opts.tracker.page.value==Page::Calibrate);
    opts.toggle_modify(); visible_ticks(&mut opts,3);
    assert_eq!(opts.tracker.selected,Some(3));
    visible_ticks(&mut opts,-1);
    assert_eq!(opts.tracker.selected,Some(1));
    assert_eq!(opts.calibrate.zero_note.value,60);
}
#[test]
fn page_selection_wraps_without_starting_outputs_or_calibration() {
    let mut opts=Opts::default(); opts.toggle_modify();
    for page in [Page::Calibrate,Page::Quantizer,Page::Play,Page::Settings,Page::Help,Page::Tuner] {
        visible_ticks(&mut opts,1);
        assert!(opts.tracker.page.value==page);
        assert!(!opts.calibrate.run.poll() && !opts.play.run.poll());
    }
    visible_ticks(&mut opts,-1);
    assert!(opts.tracker.page.value==Page::Help);
}
#[test]
fn action_click_is_one_shot_and_does_not_enter_value_editing() {
    let mut opts=Opts::default(); opts.tracker.page.value=Page::Calibrate;
    opts.tracker.selected=Some(5);opts.toggle_modify();
    assert!(opts.calibrate.run.poll());assert!(!opts.calibrate.run.poll());
    assert!(!opts.tracker.modify);
    assert!(!opts.calibrate.accept.poll() && !opts.calibrate.discard.poll());
}
#[test]
fn saved_linear_mode_retains_its_original_binary_id() {
    use strum::IntoEnumIterator;
    assert!(postcard::from_bytes::<DisplayMode>(&[2]).unwrap()==DisplayMode::Linear);
    assert!(postcard::from_bytes::<DisplayMode>(&[1]).unwrap()==DisplayMode::Visualizer);
    let offered:Vec<_>=DisplayMode::iter().collect();
    assert!(offered==[DisplayMode::Arc,DisplayMode::Linear]);
}
#[test]
fn route_setup_storage_is_reached_from_routes_not_scale_editing() {
    let mut opts=Opts::default();opts.tracker.page.value=Page::Quantizer;
    opts.tracker.selected=Some(5);
    visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(10));
    visible_ticks(&mut opts,-1);assert_eq!(opts.tracker.selected,Some(5));
    opts.tracker.page.value=Page::Play;opts.tracker.selected=Some(8);
    opts.toggle_modify();assert!(opts.play.setups.poll());
    assert!(!opts.play.run.poll());
}

#[test]
fn octave_count_defaults_to_one_and_keyboard_navigation_stays_in_the_selected_view() {
    let mut opts=Opts::default();opts.tracker.page.value=Page::Quantizer;
    assert_eq!(opts.quantizer.octaves.value,1);
    for index in [0,1,9] {visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(index));}
    opts.toggle_modify();visible_ticks(&mut opts,2);opts.toggle_modify();
    assert_eq!(opts.quantizer.octaves.value,3);
    for key in 0..24 {
        visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(2));
        assert_eq!(opts.quant_notes.octave.value*12+opts.quant_notes.note.value as u8,key);
        assert_eq!(opts.quantizer.view_octave.value,0);
    }
    visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(8));
    opts.toggle_modify();visible_ticks(&mut opts,1);opts.toggle_modify();
    assert_eq!(opts.quantizer.view_octave.value,1);
    visible_ticks(&mut opts,-1);assert_eq!(opts.tracker.selected,Some(2));
    assert_eq!(opts.quant_notes.octave.value,2);
    for _ in 0..23 {visible_ticks(&mut opts,-1);assert_eq!(opts.tracker.selected,Some(2));assert_eq!(opts.quantizer.view_octave.value,1);}
    assert_eq!(opts.quant_notes.octave.value,1);
    visible_ticks(&mut opts,-1);assert_eq!(opts.tracker.selected,Some(9));
    // Changing length clamps both focus and the window without wrapping.
    opts.tracker.selected=Some(9);opts.toggle_modify();visible_ticks(&mut opts,-7);opts.toggle_modify();
    assert_eq!(opts.quantizer.octaves.value,1);
    assert_eq!(opts.quant_notes.octave.value,0);assert_eq!(opts.quantizer.view_octave.value,0);
    opts.tracker.page.value=Page::QuantNotes;opts.tracker.selected=None;
    for index in [8,9] {visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(index));}
    visible_ticks(&mut opts,12);assert_eq!(opts.tracker.selected,Some(2));
    visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(10));
    for index in [0,5,3,4,6,7] {visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(index));}
}

#[test]
fn route_focus_follows_settings_then_actions_without_starting_outputs() {
    let mut opts=Opts::default();opts.tracker.page.value=Page::Play;
    for index in [0,1,13,14,9,10,3,2,11,12,4,5,15,6,7,8] {
        visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(index));
        assert!(!opts.play.run.poll() && !opts.play.bind.poll());
    }
    visible_ticks(&mut opts,-15);assert_eq!(opts.tracker.selected,Some(0));
    visible_ticks(&mut opts,-1);assert!(opts.tracker.selected.is_none());
}


#[test]
fn learn_base_is_a_one_shot_action_without_changing_route_pitch() {
    let mut opts=Opts::default();opts.tracker.page.value=Page::QuantNotes;
    opts.tracker.selected=Some(5);opts.toggle_modify();
    assert!(opts.quant_notes.learn.poll());
    assert!(!opts.quant_notes.learn.poll());
    assert!(!opts.tracker.modify);
    assert!(!opts.quant_notes.toggle.poll());
    assert_eq!(opts.play.zero_note.value,60);
    assert_eq!(opts.play.transpose.value,0);
}

#[test]
fn grouped_route_jack_editors_skip_other_operations_and_membership_is_an_action() {
    let mut opts=Opts::default();opts.tracker.page.value=Page::Play;
    opts.play.output.value=0;
    let mut claims=ownership::Reservations::new();
    assert!(claims.claim(ownership::Owner::Quant(1),2,6));
    opts.play.input.value=0;opts.tracker.selected=Some(1);opts.tracker.modify=true;
    ui_navigation::visible_ticks(&mut opts,1,&claims);assert_eq!(opts.play.input.value,2);
    opts.play.output_edit.value=0;opts.tracker.selected=Some(13);
    ui_navigation::visible_ticks(&mut opts,1,&claims);assert_eq!(opts.play.output_edit.value,3);
    opts.tracker.modify=false;opts.tracker.selected=Some(14);opts.toggle_modify();
    assert!(opts.play.assign.poll());assert!(!opts.play.assign.poll());
    assert!(!opts.play.run.poll());
    assert!(claims.claim(ownership::Owner::Quant(0),1,9));
    opts.play.input.value=0;opts.tracker.selected=Some(1);opts.tracker.modify=true;
    ui_navigation::visible_ticks(&mut opts,1,&claims);assert_eq!(opts.play.input.value,0);
}

#[test]
fn route_midi_controls_default_off_c4_hold_and_keep_all_values_reachable() {
    let mut o=Opts::default();o.tracker.page.value=Page::RouteMidi;
    assert_eq!(o.route_midi.channel.value,0);assert_eq!(o.route_midi.zero.value,60);
    assert!(o.route_midi.release.value==options::MidiRelease::Hold);
    for index in 0..5 {visible_ticks(&mut o,1);assert_eq!(o.tracker.selected,Some(index));}
    o.toggle_modify();visible_ticks(&mut o,1);assert!(o.route_midi.release.value==options::MidiRelease::Zero);
    o.toggle_modify();o.tracker.selected=Some(3);o.toggle_modify();
    assert!(o.route_midi.reset.poll());assert!(!o.route_midi.reset.poll());assert!(!o.tracker.modify);
}

#[test]
fn route_mapping_is_visible_and_defaults_to_nearest() {
    let mut opts=Opts::default();
    assert_eq!(opts.play.mapping.value as u8,0);
    opts.tracker.page.value=Page::Play;opts.tracker.selected=Some(15);
    opts.toggle_modify();visible_ticks(&mut opts,1);
    assert_eq!(opts.play.mapping.value as u8,1);
}

#[test]
fn factory_scale_labels_fit_route_and_editor_fields_and_keep_legacy_ids() {
    use strum::IntoEnumIterator;
    assert_eq!(options::ScalePreset::Edo24 as u8,5);
    assert_eq!(options::ScalePreset::Custom2 as u8,6);
    for (id,value) in options::ScalePreset::iter().enumerate() {
        assert_eq!(id,value as usize);
        let name:&str=value.into();
        assert!(name.len()<=9,"{name} exceeds compact route selector");
    }
    assert_eq!(options::ScalePreset::iter().count(),14);
}
