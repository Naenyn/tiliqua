#[path="../src/top/intono/fw/src/route_group.rs"] mod route_group;
#[path="../src/top/intono/fw/src/quantizer_setup.rs"] mod quantizer_setup;
#[path="../src/top/intono/fw/src/ui_keyboard.rs"] mod ui_keyboard;
#[path="../src/top/intono/fw/src/scale.rs"] mod scale;
#[path="../src/top/intono/fw/src/ui_scale.rs"] mod ui_scale;
#[path="../src/top/intono/fw/src/ui_route.rs"] mod ui_route;
#[path="../src/top/intono/fw/src/ui_text.rs"] mod ui_text;
#[path="../src/top/intono/fw/src/ui_controls.rs"] mod ui_controls;
#[test]
fn scale_editor_fields_fit_the_actual_dense_text_plane_and_round_panel() {
    for surface in [ui_controls::Surface::Scales,ui_controls::Surface::Notes,ui_controls::Surface::Routes,ui_controls::Surface::Setups,ui_controls::Surface::Profiles,ui_controls::Surface::Check] {
        for index in 0..13 {
            let Some(f)=ui_controls::field(surface,index) else {continue};
            for row in [f.row,f.row+u8::from(!f.action)] {
                ui_text::ux_field(f.column as usize,row as usize,f.width as usize,
                    "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",ui_text::DEFAULT,
                    ui_text::Align::Left,|address,_| {
                        let column=address as i32%45;let row=address as i32/45;
                        assert!(column<43);
                        for x in [120+column*12,120+column*12+8] {
                            for y in [row*32,row*32+14] {
                                assert!((x-360).pow(2)+(y-360).pow(2)<=360*360);
                            }
                        }
                    });
            }
        }
    }
}

#[test]
fn setup_summaries_fit_longest_route_labels_without_truncation() {
    for row in [8,10,12,14] {
        for (column,r,width,label) in [(4,row,10,"OUT 3 <- IN 3"),
            (16,row,14,"MIN PENTA"),(4,row+1,10,"SLOT 8"),
            (16,row+1,14,"C# -12 / NEAREST")] {
            let mut shown=0;
            ui_text::ux_field(column,r,width,label,ui_text::DEFAULT,
                ui_text::Align::Left,|a,c| {
                    if c&127!=0 {shown+=1;}
                    let x=120+(a as i32%45)*12;let y=(a as i32/45)*32;
                    for px in [x,x+8] {for py in [y,y+14] {
                        assert!((px-360).pow(2)+(py-360).pow(2)<=360*360);
                    }}
                });
            assert_eq!(shown,label.chars().filter(|c|*c!=' ').count());
        }
    }
}

#[test]
fn compact_scale_controls_fit_longest_values_above_both_keyboards() {
    for (index,label,value) in [(0,">OUTPUT","3"),(1,">PRESET","CHROMATIC")] {
        let f=ui_controls::field(ui_controls::Surface::Scales,index).unwrap();
        assert!(ui_text::inline_field(f.column as usize,f.row as usize,f.width as usize,
            label,value,ui_text::DEFAULT,|a,_|assert_eq!(a as usize/45,f.row as usize)));
    }
    assert!(ui_controls::field(ui_controls::Surface::Scales,8).is_some());
    assert!(ui_controls::field(ui_controls::Surface::Scales,2).is_none());
    assert!(ui_controls::field(ui_controls::Surface::Scales,3).is_none());
    assert!(ui_controls::field(ui_controls::Surface::Scales,4).is_none());
}

#[test]
fn route_profile_and_mode_fit_one_row_including_longest_slot() {
    for (index,label,value) in [(3,"PROFILE","SLOT 8"),(5,"MODE","SCALE"),
        (2,"0V NOTE","C#8"),(9,"SCALE","CHROMATIC"),(10,"KEY","C#"),(11,"TRANSPOSE","-12 st"),(12,"SAVED","8"),(15,"MAP","NEAREST")] {
        let f=ui_controls::field(ui_controls::Surface::Routes,index).unwrap();
        assert!(ui_text::inline_field(f.column as usize,f.row as usize,f.width as usize,
            label,value,ui_text::DEFAULT,|a,_|assert_eq!(a as usize/45,f.row as usize)));
    }
}

#[test]
fn route_keys_survive_interval_edits_profile_retuning_and_setup_reload() {
    let mut routes=quantizer_setup::DEFAULT;
    routes[0].root=2;routes[1].root=9;routes[1].transpose=-12;routes[1].equal=true;
    for route in &mut routes[..2] {route.edit_scale(1,[0xfff,0]);}
    assert_eq!(routes[0].root,2);assert_eq!(routes[1].root,9);
    let major=scale::preset(1).unwrap();
    assert_eq!(major.quantize(700_000,routes[0].root as i32*100_000,None),Ok(700_000));
    assert_eq!(major.quantize(700_000,routes[1].root as i32*100_000,None),Ok(800_000));
    routes[0].edit_scale(6,[0x891,0x124]);
    assert_eq!(routes[0].root,2);assert_eq!(routes[1].scale,1);
    routes[0].retune(37);routes[1].retune(69);
    assert_eq!(routes[0].root,2);assert_eq!(routes[1].root,9);
    assert_eq!(routes[1].transpose,-12);
    assert!(routes[1].equal); // interval edits never overwrite route mapping
    let bytes=quantizer_setup::encode(&routes).unwrap();
    assert_eq!(quantizer_setup::decode(&bytes),Some(routes));
}

#[path="../src/top/intono/fw/src/note_pattern.rs"] mod note_pattern;
#[test]
fn explicit_span_preserves_empty_octaves_and_pages_every_key() {
    let masks=[1,0,4,0,0,0,0,0];
    let pattern=scale::Pattern::compile_span(&masks,3).unwrap();
    let scale=pattern.scale().unwrap();
    assert_eq!(scale.quantize(1_200_000,0,None),Ok(0));
    assert_eq!(scale.quantize(3_600_000,0,None),Ok(3_600_000));
    assert_eq!(note_pattern::decode_span(&note_pattern::encode_span(masks,3).unwrap()),Some((masks,3)));
    let legacy=note_pattern::encode([0,4]).unwrap();
    assert_eq!(note_pattern::decode_span(&legacy).unwrap(),([4,0,0,0,0,0,0,0],1));
    for span in 1u8..=8 {for view in 0..=span.saturating_sub(2) {
        let mut state=(Some(9),view*12);
        let first=view*12;let end=(first+24).min(span*12);
        for key in first..end {
            state=ui_keyboard::next_span(state.0,state.1,true,span,view,false);
            assert_eq!(state,(Some(ui_keyboard::KEYBOARD),key));
            assert_eq!(ui_keyboard::window(view,span,Some(key)),view);
        }
        state=ui_keyboard::next_span(state.0,state.1,true,span,view,false);
        assert_eq!(state.0,Some(8));
        for key in (first..end).rev() {
            state=ui_keyboard::next_span(state.0,state.1,false,span,view,false);
            assert_eq!(state,(Some(ui_keyboard::KEYBOARD),key));
        }
        assert_eq!(ui_keyboard::next_span(state.0,state.1,false,span,view,false).0,Some(9));
    }}
    let mut routes=quantizer_setup::DEFAULT;
    routes[0].octaves=8;routes[0].masks=[1,2,4,8,16,32,64,128];
    assert_eq!(quantizer_setup::decode(&quantizer_setup::encode(&routes).unwrap()),Some(routes));
}

#[test]
fn octave_records_preview_and_key_edits_match_the_full_pattern() {
    let mut cache=ui_scale::Cache::new();
    for span in 1..=8 {
        for id in 0..=4 {
            let (masks,quartertones,count)=cache.get_span(id,[0;8],span);
            assert!(!quartertones);assert_eq!(count,masks[0].count_ones() as u8*span);
            let edited=ui_scale::toggle_span(id,[0;8],span,span*12-1).unwrap();
            assert_eq!(edited[(span-1) as usize],masks[(span-1) as usize]^(1<<11));
        }
        let masks=[1,0,4,8,16,0,64,128];
        let record=note_pattern::encode_span(masks,span).unwrap();
        for byte in 0..record.len() {
            let mut bad=record;bad[byte]^=1;
            assert!(note_pattern::decode_span(&bad).is_none());
            assert!(note_pattern::decode_span(&record[..byte]).is_none());
        }
        assert_eq!(note_pattern::decode_span(&record),Some((masks,span)));
    }
    assert!(note_pattern::encode_span([0;8],0).is_none());
    assert!(note_pattern::encode_span([0;8],9).is_none());
    let mut ink=String::new();
    ui_text::ux_field(29,10,3,"VIEW",ui_text::DEFAULT,ui_text::Align::Left,|_,c| {
        if c&127!=0 {ink.push(((c&127) as u8+32) as char);}
    });assert_eq!(ink,"VIEW");
}


#[test]
fn saved_preset_recalls_displayed_intervals_and_span_instead_of_old_custom_notes() {
    let old_custom = [1;8];
    for preset in 0..5 {
        for octaves in 1..=8 {
            let (shown,quartertones,_) = ui_scale::preview_span(preset,old_custom,octaves);
            assert!(!quartertones);
            let record=note_pattern::encode_span(shown,octaves).unwrap();
            let (loaded,span)=note_pattern::decode_span(&record).unwrap();
            assert_eq!(span,octaves);
            assert_eq!(&loaded[..span as usize],&shown[..span as usize]);
            assert_eq!(ui_scale::preview_span(6,loaded,span).0,loaded);
        }
    }
}

#[test]
fn expanded_factory_presets_preview_edit_and_reload_without_losing_route_mapping() {
    for id in scale::COMMON_PRESETS {
        let (masks,quartertones,count)=ui_scale::preview_span(id,[0;8],3);
        assert!(!quartertones);assert_eq!(count,masks[..3].iter().map(|m|m.count_ones() as u8).sum::<u8>());
        assert!(masks[..3].iter().all(|m|*m==masks[0]));
        let changed=ui_scale::toggle_span(id,[0;8],3,0).unwrap();
        assert_eq!(changed[0],masks[0]^1);
        let mut channels=quantizer_setup::DEFAULT;
        channels[0].scale=id;channels[0].equal=true;
        let bytes=quantizer_setup::encode(&channels).unwrap();
        assert_eq!(quantizer_setup::decode(&bytes),Some(channels));
        let record=note_pattern::encode_span(masks,3).unwrap();
        assert_eq!(note_pattern::decode_span(&record),Some((masks,3)));
    }
}
