//! Encoder navigation for visible instrument controls.
use crate::options::{Opts,Page};

pub fn visible_ticks(opts: &mut Opts, ticks: i8, claims: &crate::ownership::Reservations) {
    use opts::OptionsEncoderInterface;
    const PAGES: [Page; 6] = [Page::Tuner, Page::Calibrate, Page::Quantizer,
        Page::Play, Page::Settings, Page::Help];
    for _ in 0..ticks.unsigned_abs() {
        let step = if ticks > 0 { 1 } else { -1 };
        let calibration_jack = opts.tracker.page.value == Page::Calibrate
            && matches!(opts.tracker.selected,Some(0|1));
        if opts.tracker.page.value==Page::Tuner && opts.tracker.selected==Some(0) && opts.tracker.modify {
            for distance in 1..=4 {
                let next=(opts.tuner.input.value as i32+step*distance).rem_euclid(4) as u8;
                if claims.tuner_available(next) {opts.tuner.input.value=next;break;}
            }
        } else if calibration_jack && opts.tracker.modify {
            let output = opts.tracker.selected == Some(1);
            if !claims.held(crate::ownership::Owner::Calibration) {
                let value = if output { &mut opts.calibrate.output.value } else { &mut opts.calibrate.input.value };
                if let Some(next) = claims.next_free(crate::ownership::Owner::Calibration,output,*value,step>0) { *value=next; }
            }
        } else if opts.tracker.page.value == Page::Play && matches!(opts.tracker.selected,Some(1|13)) && opts.tracker.modify {
            let output=opts.tracker.selected==Some(13);
            let owner=crate::ownership::Owner::Quant(opts.play.output.value);
            if output || !claims.held(owner) {
                let value=if output {&mut opts.play.output_edit.value}else{&mut opts.play.input.value};
                if let Some(next)=claims.next_free(owner,output,*value,step>0) {*value=next;}
            }
        } else if opts.tracker.selected.is_none() && opts.tracker.modify {
            if let Some(index) = PAGES.iter().position(|page| *page == opts.tracker.page.value) {
                opts.tracker.page.value = PAGES[(index as i32 + step).rem_euclid(PAGES.len() as i32) as usize];
            }
        } else if matches!(opts.tracker.page.value,Page::QuantNotes|Page::Quantizer) && !opts.tracker.modify {
            use strum::IntoEnumIterator;
            let tools=opts.tracker.page.value==Page::QuantNotes;
            let (view,span)=if tools {(opts.quant_notes.view.value,opts.quant_notes.octaves.value)}else{(opts.quantizer.view_octave.value,opts.quantizer.octaves.value)};
            let key=opts.quant_notes.octave.value*12+opts.quant_notes.note.value as u8;
            let (selected,key)=crate::ui_keyboard::next_span(opts.tracker.selected,key,step>0,span,view,tools);
            opts.tracker.selected=selected;
            opts.quant_notes.octave.value=key/12;
            opts.quant_notes.note.value=crate::options::ScaleRoot::iter().nth((key%12) as usize).unwrap();
        } else if matches!(opts.tracker.page.value,Page::Play|Page::Calibrate|Page::Tuner) && !opts.tracker.modify {
            // Follow the on-screen order without changing persisted option indices.
            let order: &[usize] = match opts.tracker.page.value {
                Page::Calibrate => &[0,1,4,3,5,6,7,8],
                Page::Tuner if opts.tuner.display.value==crate::options::DisplayMode::Linear => &[1],
                Page::Tuner => &[0,1],
                _ => &[0,1,13,14,9,10,3,2,11,12,4,5,15,6,7,8],
            };
            let index=opts.tracker.selected.and_then(|s|order.iter().position(|n|*n==s));
            opts.tracker.selected=match (index,step) {
                (None,1)=>Some(order[0]), (Some(0),-1)=>None,
                (Some(n),1)=>Some(order[(n+1).min(order.len()-1)]),
                (Some(n),-1)=>Some(order[n-1]), _=>None,
            };
        } else {
            opts.consume_ticks(step as i8);
            if (opts.tracker.page.value == Page::Calibrate && opts.tracker.selected == Some(2))
                || (opts.tracker.page.value == Page::Quantizer && opts.tracker.selected == Some(6)) {
                opts.consume_ticks(step as i8);
            }
        }
        let tools=opts.tracker.page.value==Page::QuantNotes;
        let span=if tools {opts.quant_notes.octaves.value}else{opts.quantizer.octaves.value};
        opts.quant_notes.octave.value=opts.quant_notes.octave.value.min(span-1);
        if tools {opts.quant_notes.view.value=crate::ui_keyboard::window(opts.quant_notes.view.value,span,None);}
        else {opts.quantizer.view_octave.value=crate::ui_keyboard::window(opts.quantizer.view_octave.value,span,None);}

    }
}
