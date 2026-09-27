//! Host UART/CSR mock exercising the actual firmware trace state machine.
extern crate self as heapless;
extern crate self as tiliqua_pac;
use std::{cell::RefCell,fmt};
pub struct String<const N:usize>(std::string::String);
impl<const N:usize> String<N> {
    pub fn new()->Self {Self(std::string::String::new())}
    pub fn len(&self)->usize {self.0.len()}
    pub fn as_bytes(&self)->&[u8] {self.0.as_bytes()}
    pub fn clear(&mut self) {self.0.clear()}
    pub fn push_str(&mut self,s:&str)->Result<(),fmt::Error> {fmt::Write::write_str(self,s)}
}
impl<const N:usize> fmt::Write for String<N> {
    fn write_str(&mut self,s:&str)->fmt::Result {
        assert!(self.0.len()+s.len()<=N,"diagnostic line overflow");
        self.0.push_str(s);Ok(())
    }
}
#[derive(Default)] struct State {now:u64,seq:u32,command:u32,cycles:usize,ready:bool,space:usize,out:Vec<u8>,starts:Vec<(u64,u32)>,scenario:u8}
thread_local! {static STATE:RefCell<State>=RefCell::new(State::default());}
pub fn playback_cycles()->usize {STATE.with(|s|{let mut s=s.borrow_mut();s.cycles+=100;s.cycles})}
pub struct Bits(u32);
impl Bits {pub fn value(self)->Self{self} pub fn bits(self)->u32{self.0} pub fn txe(self)->Self{self} pub fn bit(self)->bool{self.0!=0}}
pub struct Reg(u8);
impl Reg {
    pub fn read(&self)->Bits {Bits(STATE.with(|s|{let s=s.borrow();let low=s.command&4!=0;match self.0 {
        0=>(s.ready && s.space>0) as u32,1=>0x4e534407,
        2=>if s.scenario==2 && (4000..5000).contains(&s.now) {0}else{1024|(1024<<16)},
        3=>if s.scenario==1 && s.command==1 && (3000..4000).contains(&s.now) {0}else{2|(622<<16)},4=>s.seq,
        5=>s.seq-s.seq%512,6=>20480,7=>0,8=>204800000,9=>0,
        10=>1|((s.command>>3)&3)<<2,11=>s.seq,12=>674*10000,13=>0,_=>0
    }}))}
    pub fn write(&self,f:impl for<'a> FnOnce(&'a mut Writer)->&'a mut Writer) {
        let mut w=Writer(0);f(&mut w);STATE.with(|s|{let mut s=s.borrow_mut();
            if self.0==20 {assert!(s.ready && s.space>0);s.space-=1;s.out.push(w.0 as u8);}
            if self.0==21 && w.0&1!=0 {let now=s.now;s.command=w.0;s.seq=(now*192) as u32;s.starts.push((now,w.0));}
        });
    }
}
pub struct Writer(u32);
impl Writer {pub fn value(&mut self)->&mut Self{self} pub fn data(&mut self)->&mut Self{self} pub unsafe fn bits(&mut self,v:u32)->&mut Self{self.0=v;self}}
pub struct Addr;
pub struct AddrWriter;
impl AddrWriter {pub fn value(&mut self)->&mut Self{self} pub unsafe fn bits(&mut self,_:u16)->&mut Self{self}}
impl Addr {pub fn write(&self,f:impl for<'a> FnOnce(&'a mut AddrWriter)->&'a mut AddrWriter){f(&mut AddrWriter);}}
pub struct UART0;
impl UART0 {pub fn tx_ready(&self)->Reg{Reg(0)} pub fn tx_data(&self)->Reg{Reg(20)}}
pub struct NSDF_PERIPH;
static PERIPH:NSDF_PERIPH=NSDF_PERIPH;
macro_rules! regs {($($name:ident:$id:expr),*)=>{$(pub fn $name(&self)->Reg{Reg($id)})*};}
impl NSDF_PERIPH {
    pub fn ptr()->*const Self{&PERIPH}
    pub fn address(&self)->Addr{Addr}
    regs!(identity:1,fill:2,status:3,sequence:4,source_sequence:5,source_samples:6,
          source_sum:7,source_squares_low:8,source_squares_high:9,source_status:10,
          frame_native_end:11,energy_low:12,energy_high:13,data:14,control:21);
}
mod nsdf_select {
    pub struct Result {pub hz:f32,pub unrefined_hz:f32,pub clarity:f32,pub qualified:bool}
    pub fn select_frame(_:impl FnMut(usize)->i32,low:bool,_:u64,_:bool,_:bool)->Option<Result>{
        let hz=super::STATE.with(|s|if s.borrow().scenario==4 && !low {881.0}else{880.0});
        Some(Result{hz,unrefined_hz:hz,clarity:0.99,qualified:true})
    }
}
#[path="../src/top/intono/fw/src/nsdf_trace.rs"] mod trace;
#[path="../src/top/intono/fw/src/nsdf_guard.rs"] mod nsdf_guard;
fn main() {
    let scenario=std::env::args().nth(1).map_or(0,|s|s.parse::<u8>().unwrap());
    STATE.with(|s|s.borrow_mut().scenario=scenario);
    let mut trace=trace::Trace::new();let uart=UART0;
    #[cfg(tuner_nsdf_continuous)]
    let (mut status_due,mut status_offset)=(2450u64,0usize);
    #[cfg(tuner_nsdf_continuous)]
    let status="VERIFY MOCK immutable status report\n".repeat(28);
    assert_eq!(trace.ui_period_ms(false,5),5);
    let all=env!("TILIQUA_INTONO_NSDF_TRACE")=="fast-all";
    let continuous=env!("TILIQUA_INTONO_NSDF_TRACE")=="continuous";
    assert_eq!(trace.ui_period_ms(true,5),if trace.fast() && !all && !continuous {100}else{5});
    for now in 0..12000 {
        // Approximate 115200-baud 8N1 draining between 1-ms foreground visits.
        // Ready falls within a service call, unlike the old always-ready mock.
        let before=STATE.with(|s|{let mut s=s.borrow_mut();s.now=now;s.ready=!(2500..2900).contains(&now);s.space=(s.space+11).min(16);s.out.len()});
        #[cfg(tuner_nsdf_continuous)]
        if scenario==3 {
            let due=now>=status_due;
            trace.tick_reporting(&uart,now,!due);
            if due && trace.serial_idle() {
                for _ in 0..32 {
                    if !uart.tx_ready().read().txe().bit() {break;}
                    uart.tx_data().write(|w|unsafe {w.data().bits(status.as_bytes()[status_offset].into())});
                    status_offset+=1;
                    if status_offset==status.len() {
                        status_offset=0;status_due=now+1000;break;
                    }
                }
            }
        } else {trace.tick(&uart,now);}
        #[cfg(not(tuner_nsdf_continuous))]
        trace.tick(&uart,now);
        #[cfg(tuner_nsdf_continuous)]
        {
            assert_eq!(trace.display_hz(4,now),None);
            for channel in 0..4 {
                let hz=trace.display_hz(channel,now);
                if now<2000 || (scenario==2 && (4350..4900).contains(&now)) {
                    // No samples yet, or both banks have aged out. The UI
                    // must remove markers rather than holding the last pitch.
                    assert_eq!(hz,None);
                }
                if now>11000 {
                    assert_eq!(hz,Some(if scenario==4 {881.0}else{880.0}));
                    let mut live_id=trace::Sequence::default();let mut cal_id=trace::Sequence::default();
                    let live=trace.measurement(channel,now,&mut live_id);
                    let cal=trace.calibration_measurement(channel,now,&mut cal_id);
                    assert_eq!(live.0,if scenario==4 {881.0}else{880.0});
                    assert_eq!(cal.0,880.0);assert!(live.1 && cal.1);
                    assert!(cal.3>=cal.4+110);
                }
            }
        }
        STATE.with(|s|{let s=s.borrow();assert!(s.out.len()-before<=32);
            if !s.ready {assert_eq!(s.out.len(),before);}
        });
    }
    STATE.with(|s|{let s=s.borrow();assert!(s.starts.len()>4);
        if trace.fast() {
            for pair in s.starts.windows(2){assert!(pair[1].0-pair[0].0>=if continuous {10}else{50});}
            let low=env!("TILIQUA_INTONO_NSDF_TRACE")=="fast-low";
            if all || continuous {
                if scenario!=2 {for (i,(_,command)) in s.starts.iter().enumerate() {
                    assert_eq!(*command,1|(((i/2)&3) as u32)<<3|((i&1) as u32)<<2);
                }}
                // UART stalls delay, but never skip a bank or queue catch-up.
                assert!(s.starts.len()>100);
                if continuous {
                    assert!(s.starts.len()>=800);
                    if scenario==0 {assert!(s.starts.windows(2).all(|p|p[1].0-p[0].0==10));}
                    assert!(s.starts.iter().filter(|(t,_)|(2500..2900).contains(t)).count()>=39);
                }
            } else {assert!(s.starts.iter().all(|(_,c)|*c==if low {5}else{1}));}
            assert!(!std::str::from_utf8(&s.out).unwrap().contains("NSDF BEGIN"));
        } else {assert!(std::str::from_utf8(&s.out).unwrap().contains("NSDF BEGIN"));}
        print!("{}",std::str::from_utf8(&s.out).unwrap());
    });
}
