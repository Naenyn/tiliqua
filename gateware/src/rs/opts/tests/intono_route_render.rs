//! Capture the real firmware presenter for layout checks and visual inspection.
#[path = "../../../top/intono/fw/src/ui_help.rs"] mod ui_help;
#[path="../../../top/intono/fw/src/reference_cv.rs"] mod reference_cv;
#[path="../../../top/intono/fw/src/midi_transpose.rs"] mod midi_transpose;
#[path="../../../top/intono/fw/src/options.rs"] mod options;
#[path="../../../top/intono/fw/src/route_group.rs"] mod route_group;
#[path="../../../top/intono/fw/src/route_ui.rs"] mod route_ui;
#[path="../../../top/intono/fw/src/ui_navigation.rs"] mod ui_navigation;
#[path="../../../top/intono/fw/src/ui_keyboard.rs"] mod ui_keyboard;
#[path="../../../top/intono/fw/src/ownership.rs"] mod ownership;
#[path="../../../top/intono/fw/src/ui_route.rs"] mod ui_route;
#[path="../../../top/intono/fw/src/ui_canvas.rs"] mod ui_canvas;
#[path="../../../top/intono/fw/src/ui_text.rs"] mod ui_text;
#[path="../../../top/intono/fw/src/pitch_units.rs"] mod pitch_units;
#[path="../../../top/intono/fw/src/route_render.rs"] mod route_render;
use critical_section::Mutex;
use std::cell::RefCell;
use core::fmt::Write;
use heapless::String;
use ownership::Owner;
#[derive(Clone,Copy)]struct Channel {quantize:bool,scale_slot:u8,scale:u8,root:u8,equal:bool,transpose:i8,correction:u8,zero:u8}
#[derive(Clone,Copy)]struct Midi {channel:u8}
struct Ui {opts:options::Opts}
struct App {quant_channels:[Channel;4],groups:route_group::Layout,route_selected:u8,quant_selected:u8,midi:[Midi;4],ui:Ui}
static APP:Mutex<RefCell<Option<App>>>=Mutex::new(RefCell::new(None));
fn with_app<T>(f:impl FnOnce(&App)->T)->T{critical_section::with(|cs|f(APP.borrow_ref(cs).as_ref().unwrap()))}
static ROUTE_VIEW:Mutex<RefCell<route_ui::View>>=Mutex::new(RefCell::new(route_ui::View::new()));
static ROUTE_HISTORY:Mutex<RefCell<ui_route::History>>=Mutex::new(RefCell::new(ui_route::History::new()));
static SETUP_STATUS:Mutex<RefCell<(u8,&'static str)>>=Mutex::new(RefCell::new((1,"")));
static OWNERS:Mutex<RefCell<ownership::Reservations>>=Mutex::new(RefCell::new(ownership::Reservations::new()));
#[derive(Clone,Copy)]struct Lane {active:bool,pitch:i32,status:&'static str}
struct Quant {lanes:[Lane;4],bound:[u8;4],shifts:[i8;4],midi_base_learn:midi_transpose::Learn}
static MULTI_QUANT:Mutex<RefCell<Quant>>=Mutex::new(RefCell::new(Quant {lanes:[Lane{active:true,pitch:6_000_000,status:"STOPPED"};4],bound:[0;4],shifts:[0;4],midi_base_learn:midi_transpose::Learn::new()}));
struct TextWriter<'a>{cells:&'a mut [u32;2025]}
impl TextWriter<'_>{fn cell(&mut self,a:u16,c:u32){self.cells[a as usize]=c;}}
struct Entry {value:std::string::String}
struct MenuSnapshot {entries:[Option<Entry>;16]}
const NOTE_NAMES:[&str;12]=["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];
fn scale_label(id:u8)->&'static str {use strum::IntoEnumIterator;options::ScalePreset::iter().nth(id as usize).map(Into::into).unwrap_or("INVALID")}
fn write_profile_source(s:&mut impl core::fmt::Write,n:u8){match n{0=>write!(s,"NOMINAL"),1=>write!(s,"RAM"),_=>write!(s,"SLOT {}",n-1)}.ok();}
#[test]
fn capture_dense_views_with_bounded_geometry(){
    let channel=Channel{quantize:true,scale_slot:0,scale:0,root:1,equal:false,transpose:0,correction:0,zero:60};
    let mut opts=options::Opts::default();opts.tracker.page.value=options::Page::Play;opts.tracker.selected=Some(0);
    critical_section::with(|cs|{*APP.borrow_ref_mut(cs)=Some(App{quant_channels:[channel;4],groups:route_group::Layout{inputs:[0,1,2,3],outputs:[15,0,0,0]},route_selected:0,quant_selected:0,midi:[Midi{channel:1};4],ui:Ui{opts}});
        let mut h=ROUTE_HISTORY.borrow_ref_mut(cs);for t in (0..1000).step_by(125){h.sample(t,[6_000_000,4_800_000,7_200_000,8_400_000],15);}});
    let menu=MenuSnapshot{entries:core::array::from_fn(|i|Some(Entry{value:match i{5=>"SCALE",9=>"CHROMATIC",10=>"C#",15=>"NEAREST",12=>"1",_=>""}.into()}))};
    for (name,screen) in [("overview",route_ui::Screen::Overview),("flow",route_ui::Screen::Flow),("editor",route_ui::Screen::Editor(route_ui::Stage::Scale)),("destination",route_ui::Screen::Editor(route_ui::Stage::Destination)),("single",route_ui::Screen::Flow),("warning",route_ui::Screen::Warning),("empty",route_ui::Screen::Flow),("midi",route_ui::Screen::Editor(route_ui::Stage::Midi)),("config-midi",route_ui::Screen::Editor(route_ui::Stage::Midi)),("configs",route_ui::Screen::Overview),("preferences",route_ui::Screen::Overview)]{
        critical_section::with(|cs|{if name=="preferences" {APP.borrow_ref_mut(cs).as_mut().unwrap().ui.opts.tracker.page.value=options::Page::Settings;}if name=="configs" {let mut a=APP.borrow_ref_mut(cs);let a=a.as_mut().unwrap();a.ui.opts.tracker.page.value=options::Page::QuantSetups;a.groups.outputs=[15,0,0,0];}if name=="single" {APP.borrow_ref_mut(cs).as_mut().unwrap().groups.outputs=[1,2,4,8];}if name=="empty" {let mut app=APP.borrow_ref_mut(cs);let a=app.as_mut().unwrap();a.groups.outputs=[0;4];a.ui.opts.tracker.selected=Some(11);}let mut v=ROUTE_VIEW.borrow_ref_mut(cs);v.screen=screen;v.midi_from_configs=name=="config-midi";if name=="warning" {v.warning=Some(route_ui::Warning {kind:route_ui::WarningKind::Running(1),page:options::Page::QuantSetups,focus:Some(2),go:true});}v.layout=APP.borrow_ref(cs).as_ref().unwrap().groups;});
        let sample_menu=MenuSnapshot{entries:core::array::from_fn(|i|Some(Entry{value:if name=="midi"||name=="config-midi" {match i {0=>"1",1=>"1",2=>"C4",4=>"RESET ON RELEASE",_=>""}.into()}else if name=="preferences" && i==0 {"440Hz".into()}else if name=="configs" && i==0 {"1".into()}else{menu.entries[i].as_ref().unwrap().value.clone()}}))};
        let mut cells=[0;2025];let d=route_render::publish(&mut TextWriter{cells:&mut cells},&sample_menu);
        assert!((d.len as usize)<ui_route::MAX_SHAPES,"{name} exhausted geometry capacity");
        for s in &d.shapes[..d.len as usize]{assert!(s.rect().fits_circle(360),"{name} shape outside circle");}
        let mut dump=std::string::String::new();
        for s in &d.shapes[..d.len as usize]{writeln!(dump,"S {} {} {} {} {} {}",s.x,s.y,s.w,s.h,s.color,s.kind as u8).unwrap();}
        for (a,c) in cells.iter().enumerate(){if c&127!=0 {writeln!(dump,"T {a} {c}").unwrap();}}
        std::fs::write(format!("/tmp/intono-route-{name}.txt"),dump).unwrap();
    }
    critical_section::with(|cs|APP.borrow_ref_mut(cs).as_mut().unwrap().ui.opts.tracker.page.value=options::Page::Play);
    // Filled editing controls use contrasting ink and restore outlines on exit.
    critical_section::with(|cs|ROUTE_VIEW.borrow_ref_mut(cs).screen=route_ui::Screen::Editor(route_ui::Stage::Scale));
    for editing in [false,true] {
        critical_section::with(|cs| {let mut a=APP.borrow_ref_mut(cs);let a=a.as_mut().unwrap();a.groups.outputs=[0;4];a.ui.opts.tracker.selected=Some(5);a.ui.opts.tracker.modify=editing;});
        let mut cells=[0;2025];let d=route_render::publish(&mut TextWriter{cells:&mut cells},&menu);
        assert_eq!(d.shapes[..d.len as usize].iter().any(|s|s.kind==ui_route::ShapeKind::RoundedFill),editing);
        assert_eq!(cells.iter().any(|c|c&127!=0 && ((c>>8)&255)==0x09),editing);
    }
    critical_section::with(|cs|APP.borrow_ref_mut(cs).as_mut().unwrap().ui.opts.tracker.modify=false);
    // The remembered/expanded route is not the encoder focus on the page tabs.
    critical_section::with(|cs|ROUTE_VIEW.borrow_ref_mut(cs).screen=route_ui::Screen::Overview);
    for focus in [None,Some(0),Some(4)] {
        critical_section::with(|cs|APP.borrow_ref_mut(cs).as_mut().unwrap().ui.opts.tracker.selected=focus);
        let mut cells=[0;2025];let d=route_render::publish(&mut TextWriter{cells:&mut cells},&menu);
        let cards:Vec<_>=d.shapes[..d.len as usize].iter().filter(|s|s.x==144 && s.w==432).collect();
        assert_eq!(cards.len(),4);
        for (n,card) in cards.iter().enumerate() {assert_eq!(card.color,if focus==Some(n){0xD9}else{0x49});}
    }

}

#[test]
fn reference_panel_geometry_and_longest_voltage_fit() {
    let menu=MenuSnapshot{entries:core::array::from_fn(|i|Some(Entry{value:match i{0=>"3",1=>"-5.00V",2=>"10 mV",_=>""}.into()}))};
    let mut reference=reference_cv::Reference::new();reference.free=8;
    for focus in 0..5 {
        let mut cells=[0;2025];
        let d=route_render::reference(&mut TextWriter{cells:&mut cells},&menu,Some(focus),true,reference);
        assert!((d.len as usize)<ui_route::MAX_SHAPES);
        for shape in &d.shapes[..d.len as usize] {assert!(shape.rect().fits_circle(360));}
        assert!(cells.iter().any(|c|c&127!=0));
    }
}
