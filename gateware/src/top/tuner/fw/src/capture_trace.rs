//! Bounded, non-blocking export of a rejected point's pre-stop history.
use core::fmt::Write;
use heapless::String;
use tiliqua_pac as pac;
use crate::pitch_verification::Diagnostic;

#[derive(Default)]
pub struct Trace {
    pending:String<128>, offset:usize, index:u16, started:Option<u64>,
    ready_offset:usize, ready_at:u64,
    ready_line:String<128>,
    // Four route configurations plus concurrent calibration diagnostics.
    status_line:String<1536>,
    capture_status:&'static str,
}

impl Trace {
    /// Retain UART ownership until the immutable status report is drained.
    pub fn status_due(&self,now:u64)->bool {
        self.started.is_none() && (self.ready_offset!=0 || now>=self.ready_at)
    }
    pub fn with_calibration(report:Option<(i32,i32,u8)>,hardware_bits:u8)->Self {
        let mut trace=Self::default();
        trace.capture_status="IDLE";
        if let Some((gain,zero,bits))=report {
            write!(trace.ready_line,"\nCAPTURE READY\nCAL SOURCE EEPROM OUT1 A={} B={} FBITS={} HWBITS={}\n",
                gain,zero,bits,hardware_bits).ok();
        } else {
            write!(trace.ready_line,"\nCAPTURE READY\nCAL SOURCE DEFAULT - EEPROM UNAVAILABLE HWBITS={}\n",hardware_bits).ok();
        }
        trace
    }
    pub fn cancel(&mut self,tuner:&pac::TUNER_PERIPH) {
        if self.started.is_none() {return;}
        tuner.capture_control().write(|w|w.arm().clear_bit());
        self.started=None;self.pending.clear();self.offset=0;self.index=0;
    }
    pub fn arm(&mut self,tuner:&pac::TUNER_PERIPH,now:u64,raw:f32,factor:u8,d:Diagnostic) {
        if self.started.is_some() {return;}
        self.pending.clear();self.offset=0;self.index=0;self.ready_offset=0;
        write!(self.pending,"\nCAPTURE BEGIN fs={} div={} lag={} raw={:.3} factor={} error={} span={}\n",
            tuner.info().read().sample_rate().bits(),d.divisor,d.lag_q8,raw,factor,d.error,d.span).ok();
        self.started=Some(now);
        self.capture_status="ARMED";
        tuner.capture_control().write(|w|w.arm().set_bit());
    }
    pub fn tick(&mut self,tuner:&pac::TUNER_PERIPH,uart:&pac::UART0,now:u64,cal:&crate::calibration_live::Live,
                feedback:crate::runtime::ChannelMeasurement) {
        let cal_active=cal.active();
        // Confirm the host/bridge path before asking for a hardware scan.
        // Repeat while idle so opening the reader after boot still works.
        if self.started.is_none() && now>=self.ready_at {
            if self.ready_offset==0 {
                self.status_line.clear();
                self.status_line.push_str(self.ready_line.as_str()).ok();
                write!(self.status_line,"CAL STATUS {} ACTIVE={} IN={} OUT={} MV={} POINT={} COUNT={}\nCAPTURE STATUS {}\n",
                    cal.status,cal_active,cal.input,cal.output,cal.millivolts,cal.point,cal.point_count,
                    self.capture_status).ok();
                if let Some(f)=cal.tracking_failure {
                    write!(self.status_line,"CAL REJECT UV={} MC={}\n",f.rejected.microvolts,f.rejected.millicents).ok();
                    if let Some(p)=f.neighbour {
                        write!(self.status_line,"CAL PREVIOUS UV={} MC={}\n",p.microvolts,p.millicents).ok();
                    }
                }
                if let Some((raw,factor))=cal.rejected_detector {
                    write!(self.status_line,"CAL DETECTOR RAW={:.3} FACTOR={}\n",raw,factor).ok();
                }
                if let Some(d)=cal.rejected_verifier {
                    write!(self.status_line,"CAL VERIFIER LAG={} DIV={} ERROR={} SPAN={}\n",d.lag_q8,d.divisor,d.error,d.span).ok();
                }
                let report=if crate::playback_visible() {crate::write_playback_status(&mut self.status_line,feedback)}
                    else {crate::serial_report::verification(&mut self.status_line,cal)};
                if report.is_err() {
                    // Never transmit a silently truncated report as complete.
                    self.status_line.clear();
                    self.status_line.push_str("\nSERIAL REPORT OVERFLOW\n").ok();
                }
            }
            let ready=self.status_line.as_bytes();
            if uart.tx_ready().read().txe().bit() {
                uart.tx_data().write(|w|unsafe {w.data().bits(ready[self.ready_offset].into())});
                self.ready_offset+=1;
                if self.ready_offset==ready.len() {
                    self.ready_offset=0;self.ready_at=now.saturating_add(5000);
                }
            }
        }
        let Some(start)=self.started else {return;};
        if now.saturating_sub(start)>180000 {
            self.capture_status="TIMEOUT - NO COMPLETE EXPORT";
            self.cancel(tuner);return;
        }
        if cal_active {return;}
        let data=tuner.capture_data().read();
        if !data.frozen().bit() {return;}
        if !data.ready().bit() {
            self.capture_status="UNAVAILABLE - HISTORY NOT FULL";
            self.cancel(tuner);return;
        }
        // Never wait for USB/UART readiness. At most 64 bytes per 5ms UI tick;
        // a one-byte UART can take about a minute for the complete capture.
        for _ in 0..64 {
            if !uart.tx_ready().read().txe().bit() {break;}
            if self.offset==self.pending.len() {
                self.pending.clear();self.offset=0;
                if self.index<2048 {
                    tuner.capture_control().write(|w|unsafe {w.arm().set_bit().address().bits(self.index)});
                    // Allow the shared synchronous memory read to settle.
                    let _=tuner.capture_data().read();
                    let sample=tuner.capture_data().read().sample().bits();
                    write!(self.pending,"{:04X}\n",sample).ok();
                    self.index+=1;
                } else if self.index==2048 {
                    self.pending.push_str("CAPTURE END\n").ok();self.index+=1;
                } else {self.capture_status="EXPORTED";self.cancel(tuner);break;}
            }
            let byte=self.pending.as_bytes()[self.offset];
            uart.tx_data().write(|w|unsafe {w.data().bits(byte.into())});
            self.offset+=1;
        }
    }
}
