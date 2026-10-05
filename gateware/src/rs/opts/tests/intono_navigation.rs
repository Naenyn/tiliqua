//! Use the actual instrument options/navigation, including persisted enum IDs.
#[path = "../../../top/intono/fw/src/ui_help.rs"] mod ui_help;
#[path = "../../../top/intono/fw/src/options.rs"]
mod options;
#[path = "../../../top/intono/fw/src/route_group.rs"] mod route_group;
#[path = "../../../top/intono/fw/src/route_ui.rs"] mod route_ui;
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
fn route_cards_open_nodes_without_triggering_option_actions() {
    let mut o=Opts::default();o.tracker.page.value=Page::Play;
    let mut v=route_ui::View::new();v.layout=route_group::Layout{inputs:[0,1,2,3],outputs:[1,2,4,8]};let r=ownership::Reservations::new();
    assert!(v.ticks(&mut o,3,&r));assert_eq!(o.play.output.value,2);
    assert!(v.click(&mut o,&r));assert_eq!(v.screen,route_ui::Screen::Flow);
    assert_eq!(o.tracker.selected,Some(0));
    v.ticks(&mut o,2,&r);v.click(&mut o,&r);
    assert_eq!(v.pending,Some((route_ui::Stage::Scale,2)));
    assert!(!o.play.run.poll() && !o.play.assign.poll() && !o.play.bind.poll());
    v.open_pending(&mut o);assert_eq!(o.tracker.selected,Some(5));
    v.ticks(&mut o,7,&r);assert_eq!(o.tracker.selected,Some(route_ui::DONE));
    v.click(&mut o,&r);assert_eq!(v.screen,route_ui::Screen::Flow);
    assert_eq!(o.tracker.selected,Some(2));assert!(!o.tracker.modify);
}

#[test]
fn route_pager_changes_only_the_visible_outputs_and_add_skips_claims() {
    let mut o=Opts::default();o.tracker.page.value=Page::Play;o.play.output.value=0;o.tracker.selected=Some(10);
    let mut v=route_ui::View::new();v.layout=route_group::Layout{inputs:[0,1,2,3],outputs:[1,2,4,8]};v.layout.outputs=[15,0,0,0];v.screen=route_ui::Screen::Flow;
    let mut r=ownership::Reservations::new();
    assert_eq!(v.outputs(0),[Some(0),Some(1)]);
    v.click(&mut o,&r);v.ticks(&mut o,1,&r);
    assert_eq!(v.outputs(0),[Some(2),Some(3)]);v.click(&mut o,&r);
    v.ticks(&mut o,-1,&r);assert_eq!(o.tracker.selected,Some(8));
    v.click(&mut o,&r);assert_eq!(v.pending,Some((route_ui::Stage::Destination,3)));
    v.pending=None;v.layout=route_group::Layout{inputs:[0,1,2,3],outputs:[1,2,4,8]};v.layout.outputs[2]=0;o.tracker.selected=Some(11);
    assert!(r.claim(ownership::Owner::Calibration,1,2));
    v.click(&mut o,&r);assert_eq!(v.pending,Some((route_ui::Stage::Add,2)));
}

#[test]
fn active_route_fields_lock_but_midi_and_stop_remain_available() {
    let mut o=Opts::default();o.tracker.page.value=Page::Play;o.play.output.value=0;
    let mut v=route_ui::View::new();v.layout=route_group::Layout{inputs:[0,1,2,3],outputs:[1,2,4,8]};let mut r=ownership::Reservations::new();
    assert!(r.claim(ownership::Owner::Quant(0),1,1));
    v.screen=route_ui::Screen::Editor(route_ui::Stage::Scale);o.tracker.selected=Some(9);
    v.click(&mut o,&r);assert!(!o.tracker.modify);
    v.screen=route_ui::Screen::Flow;o.tracker.selected=Some(12);v.click(&mut o,&r);
    assert!(o.play.run.poll());
    o.tracker.selected=Some(1);v.click(&mut o,&r);v.open_pending(&mut o);
    assert!(o.tracker.page.value==Page::RouteMidi);
    v.click(&mut o,&r);v.ticks(&mut o,1,&r);v.click(&mut o,&r);
    assert_eq!(o.route_midi.channel.value,1);
    v.ticks(&mut o,5,&r);assert_eq!(o.tracker.selected,Some(route_ui::DONE));
    v.click(&mut o,&r);assert!(v.finish_midi);assert!(o.tracker.page.value==Page::Play);
}

#[test]
fn grouped_flow_visits_only_visible_groups_and_exposes_manual_shift() {
    let mut o=Opts::default();o.tracker.page.value=Page::Play;o.play.output.value=0;
    let mut v=route_ui::View::new();v.layout=route_group::Layout{inputs:[0,1,2,3],outputs:[1,2,4,8]};v.screen=route_ui::Screen::Flow;
    v.layout.outputs=[3,0,4,8];let r=ownership::Reservations::new();
    for index in [0,1,2,4,6,8,11,12,13,14] {
        v.ticks(&mut o,1,&r);assert_eq!(o.tracker.selected,Some(index));
    }
    assert!(route_ui::View::fields(route_ui::Stage::Scale).contains(&11));
    assert_eq!(route_ui::View::fields(route_ui::Stage::Destination),&[3,4,2,13,14,route_ui::DONE]);
    o.tracker.selected=Some(6);v.click(&mut o,&r);v.open_pending(&mut o);
    // Mode, preset, key, mapping, then manual shift within the pitch editor.
    v.ticks(&mut o,4,&r);assert_eq!(o.tracker.selected,Some(11));
    v.click(&mut o,&r);v.ticks(&mut o,1,&r);v.click(&mut o,&r);
    assert_eq!(o.play.transpose.value,1);
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
    assert_eq!(opts.tracker.selected,Some(4));
    visible_ticks(&mut opts,-1);
    assert_eq!(opts.tracker.selected,Some(1));
    assert_eq!(opts.calibrate.zero_note.value,60);
}
#[test]
fn page_selection_stops_at_ends_without_starting_outputs_or_calibration() {
    let mut opts=Opts::default(); opts.toggle_modify();
    for page in [Page::Calibrate,Page::Quantizer,Page::Play,Page::Settings,Page::Help,Page::Help] {
        visible_ticks(&mut opts,1);
        assert!(opts.tracker.page.value==page);
        assert!(!opts.calibrate.run.poll() && !opts.play.run.poll());
    }
    visible_ticks(&mut opts,127);assert!(opts.tracker.page.value==Page::Help);
    visible_ticks(&mut opts,-127);assert!(opts.tracker.page.value==Page::Tuner);
    assert!(!opts.calibrate.run.poll() && !opts.play.run.poll());
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
    for index in [0,1] {visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(index));}
    visible_ticks(&mut opts,12);assert_eq!(opts.tracker.selected,Some(2));
    for index in [8,9] {visible_ticks(&mut opts,1);assert_eq!(opts.tracker.selected,Some(index));}
    opts.toggle_modify();visible_ticks(&mut opts,2);opts.toggle_modify();
    assert_eq!(opts.quantizer.octaves.value,3);
    visible_ticks(&mut opts,-26);assert_eq!(opts.tracker.selected,Some(1));
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
    visible_ticks(&mut opts,-1);assert_eq!(opts.tracker.selected,Some(1));
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

#[test]
fn stopped_routes_reserve_jacks_in_encoder_selectors() {
    let mut o=Opts::default();o.tracker.page.value=Page::Play;o.play.output.value=0;
    let mut v=route_ui::View::new();v.layout=route_group::Layout{inputs:[0,1,2,3],outputs:[1,2,4,8]};let r=ownership::Reservations::new();
    v.screen=route_ui::Screen::Editor(route_ui::Stage::Input);
    o.play.input.value=0;o.tracker.selected=Some(1);o.tracker.modify=true;
    v.ticks(&mut o,1,&r);assert_eq!(o.play.input.value,0);
    v.layout.outputs[1]=0;v.ticks(&mut o,1,&r);assert_eq!(o.play.input.value,1);
    v.screen=route_ui::Screen::Editor(route_ui::Stage::Add);o.tracker.selected=Some(13);o.play.output_edit.value=0;
    v.ticks(&mut o,1,&r);assert_eq!(o.play.output_edit.value,1);
    v.ticks(&mut o,1,&r);assert_eq!(o.play.output_edit.value,1);
}

#[test]
fn new_routes_are_empty_and_load_warning_can_jump_or_cancel() {
    assert_eq!(route_group::Layout::new().outputs,[0;4]);
    let mut o=Opts::default();o.tracker.page.value=Page::QuantSetups;o.tracker.selected=Some(2);
    let mut v=route_ui::View::new();let r=ownership::Reservations::new();
    v.warn(&mut o,route_ui::WarningKind::Running(2));
    assert_eq!(v.screen,route_ui::Screen::Warning);
    v.click(&mut o,&r);assert_eq!(o.play.output.value,2);assert_eq!(v.screen,route_ui::Screen::Flow);
    o.tracker.page.value=Page::QuantSetups;o.tracker.selected=Some(2);
    v.warn(&mut o,route_ui::WarningKind::Running(1));v.ticks(&mut o,1,&r);v.click(&mut o,&r);
    assert!(o.tracker.page.value==Page::QuantSetups);assert_eq!(o.tracker.selected,Some(2));
    v.warn(&mut o,route_ui::WarningKind::Calibration);v.click(&mut o,&r);
    assert!(o.tracker.page.value==Page::QuantSetups);
}

#[test]
fn nominal_profile_has_no_redundant_clear_action_in_navigation() {
    use route_ui::{Stage,View};
    assert_eq!(View::fields_for(Stage::Destination,0),&[3,2,13,14,route_ui::DONE]);
    assert!(View::fields_for(Stage::Destination,1).contains(&4));
    let mut o=Opts::default();o.tracker.page.value=Page::Play;
    let mut v=View::new();v.screen=route_ui::Screen::Editor(Stage::Destination);
    o.tracker.selected=Some(3);v.ticks(&mut o,1,&ownership::Reservations::new());
    assert_eq!(o.tracker.selected,Some(2));
}

#[test]
fn empty_route_opens_on_add_and_skips_hidden_nodes() {
    let mut o=Opts::default();o.tracker.page.value=Page::Play;o.tracker.selected=Some(0);
    let mut v=route_ui::View::new();let r=ownership::Reservations::new();
    v.click(&mut o,&r);assert_eq!(v.screen,route_ui::Screen::Flow);
    assert_eq!(o.tracker.selected,Some(11));
    v.ticks(&mut o,1,&r);assert_eq!(o.tracker.selected,Some(13));
    v.ticks(&mut o,-1,&r);assert_eq!(o.tracker.selected,Some(11));
    // Another stopped route owns the provisional source; choose a free source.
    v.layout.outputs[1]=2;v.layout.inputs[1]=o.play.input.value;
    v.click(&mut o,&r);assert_eq!(v.pending,Some((route_ui::Stage::Add,0)));
    assert_eq!(o.play.input.value,0);
    v.open_pending(&mut o);o.tracker.selected=Some(route_ui::DONE);v.click(&mut o,&r);
    assert_eq!(o.tracker.selected,Some(11));
}

#[test]
fn midi_base_learn_is_reachable_as_a_one_shot_action() {
    let mut o=Opts::default();o.tracker.page.value=Page::RouteMidi;
    let mut v=route_ui::View::new();v.screen=route_ui::Screen::Editor(route_ui::Stage::Midi);
    let claims=ownership::Reservations::new();o.tracker.selected=Some(2);
    v.ticks(&mut o,1,&claims);assert_eq!(o.tracker.selected,Some(5));
    v.click(&mut o,&claims);assert!(o.route_midi.learn.poll());assert!(!o.route_midi.learn.poll());
    assert!(!o.tracker.modify);
}

#[test]
fn overview_visits_cards_consecutively_then_shared_actions() {
    let mut o=Opts::default();o.tracker.page.value=Page::Play;
    let mut v=route_ui::View::new();v.layout=route_group::Layout{inputs:[0,1,2,3],outputs:[1,2,4,8]};let r=ownership::Reservations::new();
    for route in 0..4 {
        v.ticks(&mut o,1,&r);assert_eq!(o.tracker.selected,Some(route));assert_eq!(o.play.output.value,route as u8);
    }
    v.ticks(&mut o,1,&r);assert_eq!(o.tracker.selected,Some(4));assert_eq!(o.play.output.value,3);
    v.click(&mut o,&r);assert!(o.play.run.poll());
    v.ticks(&mut o,1,&r);assert_eq!(o.tracker.selected,Some(6));
    for index in [Some(4),Some(3),Some(2),Some(1),Some(0),None] {
        v.ticks(&mut o,-1,&r);assert_eq!(o.tracker.selected,index);
    }
    // Empty last route skips Start/Stop in both directions.
    v.layout.outputs[3]=0;v.ticks(&mut o,4,&r);assert_eq!(o.tracker.selected,Some(3));
    v.ticks(&mut o,1,&r);assert_eq!(o.tracker.selected,Some(6));
    v.ticks(&mut o,-1,&r);assert_eq!(o.tracker.selected,Some(3));
}
#[test]
fn config_midi_has_route_selection_learn_and_explicit_back() {
    let mut o=Opts::default();o.tracker.page.value=Page::RouteMidi;
    let mut v=route_ui::View::new();v.screen=route_ui::Screen::Editor(route_ui::Stage::Midi);v.midi_from_configs=true;
    let r=ownership::Reservations::new();
    for index in [0,1,2,5,4,3,6] {v.ticks(&mut o,1,&r);assert_eq!(o.tracker.selected,Some(index));}
    v.click(&mut o,&r);assert!(o.route_midi.back.poll());assert!(!o.tracker.modify);
    o.tracker.page.value=Page::QuantSetups;o.tracker.selected=Some(4);o.toggle_modify();assert!(o.quant_setups.back.poll());
}

#[path = "../../../top/intono/fw/src/preferences.rs"]
mod preferences;

#[test]
fn preferences_use_generic_navigation_and_one_shot_actions() {
    let mut o=Opts::default();o.tracker.page.value=Page::Settings;
    let mut v=route_ui::View::new();let claims=ownership::Reservations::new();
    assert!(v.handles(Page::Settings));
    for index in 0..3 {
        assert!(!v.ticks(&mut o,1,&claims));visible_ticks(&mut o,1);
        assert_eq!(o.tracker.selected,Some(index));
    }
    assert!(!v.click(&mut o,&claims));o.toggle_modify();assert!(o.settings.wipe_opts.poll());
    o.tracker.selected=Some(1);o.toggle_modify();assert!(o.settings.save_opts.poll());
}

#[test]
fn calibration_navigation_follows_visual_order_in_both_directions() {
    let mut o=Opts::default();o.tracker.page.value=Page::Calibrate;
    for index in [0,1,4,3,5,6,7,8] {
        visible_ticks(&mut o,1);assert_eq!(o.tracker.selected,Some(index));
    }
    for index in [7,6,5,3,4,1,0] {
        visible_ticks(&mut o,-1);assert_eq!(o.tracker.selected,Some(index));
    }
    visible_ticks(&mut o,-1);assert_eq!(o.tracker.selected,None);
}
#[test]
fn linear_tuner_skips_focus_and_restores_it_in_arc() {
    let mut o=Opts::default();o.tuner.display.value=DisplayMode::Linear;
    visible_ticks(&mut o,1);assert_eq!(o.tracker.selected,Some(1));
    visible_ticks(&mut o,-1);assert_eq!(o.tracker.selected,None);
    o.tuner.display.value=DisplayMode::Arc;
    visible_ticks(&mut o,1);assert_eq!(o.tracker.selected,Some(0));
    visible_ticks(&mut o,1);assert_eq!(o.tracker.selected,Some(1));
}

#[test]
fn tuner_input_list_stops_at_ends_and_can_observe_assigned_inputs() {
    let mut o=Opts::default();o.tracker.selected=Some(0);o.toggle_modify();
    let mut claims=ownership::Reservations::new();
    assert!(claims.claim(ownership::Owner::Calibration,2,1));
    ui_navigation::visible_ticks(&mut o,1,&claims);assert_eq!(o.tuner.input.value,1);
    ui_navigation::visible_ticks(&mut o,-1,&claims);assert_eq!(o.tuner.input.value,0);
    ui_navigation::visible_ticks(&mut o,-1,&claims);assert_eq!(o.tuner.input.value,0);
    ui_navigation::visible_ticks(&mut o,127,&claims);assert_eq!(o.tuner.input.value,3);
}

#[test]
fn scale_preset_navigation_places_custom_last_and_wraps_both_directions() {
    use options::ScalePreset;
    use strum::IntoEnumIterator;
    for page in [Page::Quantizer, Page::Play] {
        let mut o=Opts::default();o.tracker.page.value=page;
        o.tracker.selected=Some(if page==Page::Quantizer {1}else{9});
        o.tracker.modify=true;
        let current=|o:&Opts| if page==Page::Quantizer {o.quantizer.scale.value}else{o.play.scale.value};
        visible_ticks(&mut o,-1);assert!(current(&o)==ScalePreset::Custom2);
        visible_ticks(&mut o,1);assert!(current(&o)==ScalePreset::Chromatic);
        let mut seen=0u16;
        for _ in 0..14 {
            seen|=1<<current(&o) as u8;
            visible_ticks(&mut o,1);
        }
        assert_eq!(seen,0x3fff);assert!(current(&o)==ScalePreset::Chromatic);
        visible_ticks(&mut o,-2);assert!(current(&o)==ScalePreset::Blues);
        visible_ticks(&mut o,1);assert!(current(&o)==ScalePreset::Custom2);
        visible_ticks(&mut o,-13);assert!(current(&o)==ScalePreset::Chromatic);
        for preset in ScalePreset::iter() {
            assert!(preset.stepped(true).stepped(false)==preset);
        }
    }
}

#[test]
fn help_topics_reset_scroll_and_navigation_follows_visible_controls() {
    let mut o=Opts::default();o.tracker.page.value=Page::Help;
    visible_ticks(&mut o,1);assert_eq!(o.tracker.selected,Some(1));
    visible_ticks(&mut o,1);assert_eq!(o.tracker.selected,Some(0));
    visible_ticks(&mut o,-1);assert_eq!(o.tracker.selected,Some(1));
    visible_ticks(&mut o,-1);assert_eq!(o.tracker.selected,None);
    o.tracker.selected=Some(1);o.tracker.modify=true;o.help.scroll.value=10;
    visible_ticks(&mut o,1);assert_eq!(o.help.topic.value,1);assert_eq!(o.help.scroll.value,0);
    visible_ticks(&mut o,-10);assert_eq!(o.help.topic.value,0);
    visible_ticks(&mut o,100);assert_eq!(o.help.topic.value,9);
    o.tracker.selected=Some(0);
    visible_ticks(&mut o,100);assert_eq!(o.help.scroll.value,ui_help::max_scroll(9));
    visible_ticks(&mut o,-100);assert_eq!(o.help.scroll.value,0);
}
