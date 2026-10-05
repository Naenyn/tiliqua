//! Keyboard focus shares the existing toggle action index, preserving option keys.
//! Walk only the visible keys before moving to the surrounding controls.
pub const KEYBOARD: usize = 2;
const ORDER: [usize; 9] = [8, KEYBOARD, 0, 3, 4, 6, 7, 11, 5];
pub fn next(selected: Option<usize>, key: u8, forward: bool) -> (Option<usize>, u8) {
    next_in_order(&ORDER,selected,key,forward)
}
pub fn next_scales(selected: Option<usize>, key: u8, forward: bool) -> (Option<usize>, u8) {
    next_in_order(&[0,1,KEYBOARD,5,10,11,12],selected,key,forward)
}
fn next_in_order(order: &[usize],selected: Option<usize>,key:u8,forward:bool) -> (Option<usize>,u8) {
    if selected == Some(KEYBOARD) {
        if forward && key < 23 { return (selected, key + 1); }
        if !forward && key > 0 { return (selected, key - 1); }
    }
    let position=selected.and_then(|s|order.iter().position(|n|*n==s));
    let selected=match (position,forward) {
        (None,true)=>Some(order[0]), (Some(0),false)=>None,
        (Some(n),true)=>Some(order[(n+1).min(order.len()-1)]),
        (Some(n),false)=>Some(order[n-1]), _=>None,
    };
    let key=if selected==Some(KEYBOARD) {if forward {0}else{23}}else{key};
    (selected,key)
}
/// Clamp the selected page without following the keyboard cursor.
pub fn window(view:u8,span:u8,_key:Option<u8>)->u8 {
    view.min(span.saturating_sub(2))
}
pub fn order(span:u8,tools:bool)->&'static [usize] {
    if span==1 {if tools {&[8,9,KEYBOARD,0,5,3,4,6,7,11]}else{&[0,1,KEYBOARD,9,5,10,11,12]}}else if tools {&[8,9,KEYBOARD,10,0,5,3,4,6,7,11]}else{&[0,1,KEYBOARD,8,9,5,10,11,12]}
}
pub fn next_span(selected:Option<usize>,key:u8,forward:bool,span:u8,view:u8,tools:bool)->(Option<usize>,u8) {
    let order=order(span,tools);
    let first=window(view,span,None)*12;
    let last=(first+24).min(span*12)-1;
    let key=key.clamp(first,last);
    if selected==Some(KEYBOARD) {
        if forward && key<last {return (selected,key+1);}
        if !forward && key>first {return (selected,key-1);}
    }
    let selected=next_in_order(order,selected,if forward {23}else{0},forward).0;
    (selected,if selected==Some(KEYBOARD) {if forward {first}else{last}}else{key})
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn traverse_every_key_and_return_to_navigation_in_both_directions() {
        let mut state=(None,0);
        state=next(state.0,state.1,true);assert_eq!(state.0,Some(8));
        for key in 0..24 {state=next(state.0,state.1,true);assert_eq!(state,(Some(KEYBOARD),key));}
        state=next(state.0,state.1,true);assert_eq!(state.0,Some(0));
        for key in (0..24).rev() {state=next(state.0,state.1,false);assert_eq!(state,(Some(KEYBOARD),key));}
        state=next(state.0,state.1,false);assert_eq!(state.0,Some(8));
        state=next(state.0,state.1,false);assert_eq!(state.0,None);
    }
    #[test]
    fn main_scales_page_walks_keys_after_transpose_without_a_root_editor() {
        let mut state=(None,0);
        for control in [0,1] {state=next_scales(state.0,state.1,true);assert_eq!(state.0,Some(control));}
        for key in 0..24 {state=next_scales(state.0,state.1,true);assert_eq!(state,(Some(KEYBOARD),key));}
        state=next_scales(state.0,state.1,true);assert_eq!(state.0,Some(5));
        for key in (0..24).rev() {state=next_scales(state.0,state.1,false);assert_eq!(state,(Some(KEYBOARD),key));}
        state=next_scales(state.0,state.1,false);assert_eq!(state.0,Some(1));
    }
    #[test]
    fn saved_scale_controls_follow_the_visible_keyboard_and_tools() {
        let mut state=(Some(KEYBOARD),11);
        for control in [9,5,10,11,12] {
            state=next_span(state.0,state.1,true,1,0,false);
            assert_eq!(state.0,Some(control));
        }
        for control in [11,10,5,9,KEYBOARD] {
            state=next_span(state.0,state.1,false,1,0,false);
            assert_eq!(state.0,Some(control));
        }
        assert_eq!(state.1,11);
    }
    #[test]
    fn controls_remain_reachable_and_endpoints_do_not_wrap() {
        let mut state=(Some(KEYBOARD),23);
        for control in [0,3,4,6,7,11,5,5] {state=next(state.0,state.1,true);assert_eq!(state.0,Some(control));}
        for control in [11,7,6,4,3,0] {state=next(state.0,state.1,false);assert_eq!(state.0,Some(control));}
        assert_eq!(next(None,0,false),(None,0));
    }
}
