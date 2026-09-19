//! Continuous acquisition for tuner display and diagnostics. No DAC writes.
//! Latest-value storage is bounded; a blocked UART cannot hold the score engine.
use core::fmt::Write;
use heapless::String;
use tiliqua_pac as pac;
#[path="nsdf_resolve.rs"]
mod resolve;
#[path="nsdf_publish.rs"]
mod publish;
#[path="nsdf_sequence.rs"] mod sequence;
pub use sequence::Sequence;

#[derive(Clone,Copy)]
struct Latest {
    count:u32, seq:u32, mhz:u32, cycles:u32, work:u32, dt:u32, done:u64,
    raw:bool, guard:bool, valid:bool,
}
impl Latest {
    const EMPTY:Self=Self {count:0,seq:0,mhz:0,cycles:0,work:0,dt:0,done:0,
        raw:false,guard:false,valid:false};
}
pub struct Scheduler {
    latest:[Latest;8], pending:String<512>, offset:usize,
    slot:u8, report:u8, active:bool, due:u64, started:u64,
    report_due:u64, faults:u32,
    baseline:[(u32,bool,u32,u64);4],
}
// Also checked by the embedded compiler with the real heapless buffer layout.
const _:()=assert!(core::mem::size_of::<Scheduler>()<=1024);
impl Scheduler {
    pub fn fast(&self)->bool {true}
    pub fn ui_period_ms(&self,_idle_tuner:bool,normal:u64)->u64 {normal}
    pub fn new()->Self {
        Self {latest:[Latest::EMPTY;8],pending:String::new(),offset:0,
            slot:0,report:0,active:false,due:2000,started:0,
            report_due:2000,faults:0,baseline:[(0,false,u32::MAX,0);4]}
    }
    pub fn observe_baseline(&mut self,input:u8,hz:f32,qualified:bool,end_age:u32,now:u64) {
        if let Some(slot)=self.baseline.get_mut(input as usize) {
            *slot=((hz*1000.0) as u32,qualified,end_age,now);
        }
    }
    fn selected(&self,input:u8,now:u64,settled:bool)->publish::Pitch {
        if input>=4 {return publish::Pitch::NONE;}
        let frame=|r:Latest|publish::Frame {mhz:r.mhz,count:r.count,completed:r.done,
            request_ms:r.dt,qualified:r.valid && r.raw && r.guard};
        let n=frame(self.latest[input as usize*2]);let l=frame(self.latest[input as usize*2+1]);
        if settled {publish::publish(n,l,now)}else{publish::display(n,l,now)}
    }
    /// Display-only pitch. Re-evaluate freshness on every render; never fall
    /// back to an old result or the baseline detector when unqualified.
    pub fn display_hz(&self,input:u8,now:u64)->Option<f32> {
        let pitch=self.selected(input,now,false);
        if matches!(pitch.source,1|2) {Some(pitch.mhz as f32/1000.0)} else {None}
    }
    /// Frequency, qualification, consumer sequence, full-window and endpoint
    /// ages. CAL's existing post-output settling gate uses these conservative
    /// ages; repeated UI reads are not additional acquired measurements.
    pub fn measurement(&self,input:u8,now:u64,identity:&mut Sequence)->(f32,bool,u16,u32,u32) {
        self.measurement_with(input,now,identity,false)
    }
    /// Settled CAL/CHECK observations prefer the longer low-rate bank in its
    /// overlap, retaining cross-bank disagreement and full-window age guards.
    /// Do not apply this asynchronous-bank veto to the live tuner display.
    pub fn calibration_measurement(&self,input:u8,now:u64,identity:&mut Sequence)->(f32,bool,u16,u32,u32) {
        self.measurement_with(input,now,identity,true)
    }
    fn measurement_with(&self,input:u8,now:u64,identity:&mut Sequence,settled:bool)->(f32,bool,u16,u32,u32) {
        let p=self.selected(input,now,settled);
        if input<4 {
            if let Some(sequence)=identity.observe(p.source,p.generation) {
                return (p.mhz as f32/1000.0,true,sequence,p.window_age_ms,p.end_age_ms);
            }
        }
        (0.0,false,0,u32::MAX,u32::MAX)
    }
    fn finish(&mut self,now:u64) {
        self.active=false;self.slot=(self.slot+1)&7;
        // At most 100 acquisitions/s TOTAL. Late service never queues catch-up.
        self.due=now.max(self.started.saturating_add(10));
    }
    pub fn tick(&mut self,uart:&pac::UART0,now:u64) {
        self.tick_reporting(uart,now,true);
    }
    pub fn serial_idle(&self)->bool {self.offset==self.pending.len()}
    /// Pause telemetry generation, not acquisition, during a status report.
    /// Always drain the old batch before handing UART ownership to its writer.
    pub fn tick_reporting(&mut self,uart:&pac::UART0,now:u64,reports:bool) {
        let nsdf=unsafe {&*pac::NSDF_PERIPH::ptr()};
        // UART service never gates acquisition, even when disconnected/stalled.
        for _ in 0..32 {
            if self.offset==self.pending.len() || !uart.tx_ready().read().txe().bit() {break;}
            uart.tx_data().write(|w|unsafe {w.data().bits(self.pending.as_bytes()[self.offset].into())});
            self.offset+=1;
        }
        let low=self.slot&1!=0;let channel=self.slot>>1;
        if self.active {
            let status=nsdf.status().read().value().bits();
            let complete=status&2!=0;
            if status&0x1c!=0 || (!complete && now.saturating_sub(self.started)>=250)
                || (complete && status>>16!=622) {
                nsdf.control().write(|w|unsafe {w.value().bits(2)});
                self.latest[self.slot as usize].valid=false;
                self.faults=self.faults.saturating_add(1);self.finish(now);
            } else if complete {
                let started=crate::playback_cycles();
                let energy=(nsdf.energy_low().read().value().bits() as u64)
                    |((nsdf.energy_high().read().value().bits() as u64)<<32);
                let seq=nsdf.sequence().read().value().bits();
                let result=crate::nsdf_select::select_frame(|index| {
                    nsdf.address().write(|w|unsafe {w.value().bits(index as u16)});
                    let _=nsdf.data().read();
                    nsdf.data().read().value().bits() as i32
                },low,energy,status&(1<<8)!=0,status&(1<<9)!=0);
                let guard=crate::nsdf_guard::passes(crate::nsdf_guard::Source {
                    end:nsdf.source_sequence().read().value().bits(),
                    samples:nsdf.source_samples().read().value().bits(),
                    sum:nsdf.source_sum().read().value().bits() as i32,
                    squares:(nsdf.source_squares_low().read().value().bits() as u64)
                        |((nsdf.source_squares_high().read().value().bits() as u64)<<32),
                    status:nsdf.source_status().read().value().bits(),
                },channel,low,seq,nsdf.frame_native_end().read().value().bits(),energy,
                    status&(1<<8)!=0,status&(1<<9)!=0);
                let cycles=crate::playback_cycles().wrapping_sub(started) as u32;
                let (mhz,raw)=result.map_or((0,false),|r|((r.hz*1000.0) as u32,r.qualified));
                let old=self.latest[self.slot as usize];
                self.latest[self.slot as usize]=Latest {count:old.count.saturating_add(1),
                    seq,mhz,cycles,work:old.work.wrapping_add(cycles),
                    dt:now.saturating_sub(self.started).min(u32::MAX as u64) as u32,
                    done:now,raw,guard,valid:true};
                self.finish(now);
            }
        } else if now>=self.due {
            if nsdf.identity().read().value().bits()!=0x4e534407 {
                self.faults=self.faults.saturating_add(1);
                self.latest=[Latest::EMPTY;8];self.due=now.saturating_add(5000);
            } else {
                let fill=nsdf.fill().read().value().bits();
                let ready=(if low {(fill>>16)&2047}else{fill&2047})>=674;
                if ready {
                    nsdf.control().write(|w|unsafe {w.value().bits(1|((low as u32)<<2)|((channel as u32)<<3))});
                    self.started=now;self.active=true;
                } else {
                    // A bank that cannot fill must not starve the other seven.
                    self.latest[self.slot as usize].valid=false;
                    self.started=now;self.finish(now);self.due=now.saturating_add(10);
                }
            }
        }
        if reports && self.serial_idle() && now>=self.report_due {
            self.pending.clear();self.offset=0;
            let r=self.latest[self.report as usize];
            let age=now.saturating_sub(r.done).min(u32::MAX as u64) as u32;
            let ok=r.valid && age<=500 && r.raw && r.guard;
            // One immutable line in flight; after a stall report current latest
            // results, never replay an unbounded backlog. age is at formatting.
            write!(self.pending,"NSDF RUN ch={} low={} count={} seq={} mhz={} raw={} guard={} ok={} age={} dt={} cycles={} work={} faults={} ms={}\n",
                self.report>>1,self.report&1!=0,r.count,r.seq,r.mhz,r.raw,r.guard,ok,age,r.dt,r.cycles,r.work,self.faults,now as u32).ok();
            if self.report&1!=0 {
                let n=self.latest[(self.report-1) as usize];
                let na=now.saturating_sub(n.done).min(u32::MAX as u64) as u32;
                let nq=n.valid && n.count>0 && n.raw && n.guard;
                let lq=r.valid && r.count>0 && r.raw && r.guard;
                let selected=resolve::resolve(resolve::Candidate {mhz:n.mhz,age:na,qualified:nq},
                    resolve::Candidate {mhz:r.mhz,age,qualified:lq});
                write!(self.pending,"NSDF PICK ch={} ms={} n={} na={} nq={} l={} la={} lq={} mhz={} src={}\n",
                    self.report>>1,now as u32,n.mhz,na,nq,r.mhz,age,lq,selected.mhz,selected.source).ok();
                let p=self.selected(self.report>>1,now,false);
                let (base,bq,end_age,observed)=self.baseline[(self.report>>1) as usize];
                let bage=now.saturating_sub(observed).saturating_add(end_age as u64).min(u32::MAX as u64) as u32;
                write!(self.pending,"NSDF COMP ch={} ms={} mhz={} src={} gen={} age={} win={} base={} bq={} bage={}\n",
                    self.report>>1,now as u32,p.mhz,p.source,p.generation,p.end_age_ms,p.window_age_ms,
                    base,bq && bage<=250,bage).ok();
            }
            self.report=(self.report+1)&7;self.report_due=now.saturating_add(50);
        }
    }
}
