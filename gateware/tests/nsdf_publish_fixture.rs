#[path="../src/top/tuner/fw/src/nsdf_publish.rs"] mod publish;
use publish::{Frame,Pitch,publish};
fn f(hz:u32,time:u64,count:u32)->Frame {Frame {mhz:hz,count,completed:time,request_ms:4,qualified:true}}
fn main() {
    let empty=Frame {qualified:false,..f(0,0,0)};
    assert_eq!(publish(empty,empty,100),Pitch::NONE);
    let n=f(880000,100,1);let l=f(880000,110,1);
    let p=publish(n,l,120);
    assert_eq!((p.mhz,p.source,p.generation,p.end_age_ms,p.window_age_ms),(880000,1,1,16,136));
    assert_eq!(publish(n,l,357).source,0); // request age makes both stale
    assert_eq!(publish(n,l,109).source,2); // future low timestamp is rejected
    assert_eq!(publish(n,f(440000,120,2),121).source,3); // real step conflicts with old bank
    assert_eq!(publish(Frame{qualified:false,..n},f(440000,120,2),122).source,1);
    assert_eq!(publish(f(1200000,130,3),f(1200000,140,3),150).source,2);
    // Identical pitch refreshed: new generation, not a repeated old measurement.
    assert_eq!(publish(n,f(880000,130,2),140).generation,2);
    // Missing/invalid current frame must not retain an earlier successful result.
    assert_eq!(publish(empty,Frame{qualified:false,..l},120),Pitch::NONE);
    assert_eq!(publish(empty,Frame{count:0,..l},120),Pitch::NONE);
    assert_eq!(publish(empty,Frame{request_ms:u32::MAX,..l},120),Pitch::NONE);
    assert_eq!(publish(empty,l,u64::MAX),Pitch::NONE);
    // Freshness boundary is inclusive, with conservative observation rounding.
    assert_eq!(publish(empty,l,356).end_age_ms,252);
    // No cross-channel state: a call for another channel cannot alter an outcome.
    let first=publish(n,l,120);let _=publish(f(2000000,10,1),empty,30);
    assert_eq!(publish(n,l,120),first);
    // Moving pitch: display follows the native window without requiring the
    // older/longer window to agree. Strict diagnostic publication is unchanged.
    let moving=f(930490,110,2);let current=f(889312,115,3);
    assert_eq!(publish(current,moving,120).source,3);
    assert_eq!(publish::display(current,moving,120).mhz,889312);
    assert_eq!(publish::display(n,l,120).source,2);
    assert_eq!(publish::display(empty,l,120).source,1);
    assert_eq!(publish::display(n,l,357),Pitch::NONE);
    assert_eq!(publish::display(empty,empty,120),Pitch::NONE);
    assert_eq!(publish::display(Frame{qualified:false,..n},l,120).source,1);
    assert_eq!(publish::display(Frame{count:0,..n},l,120).source,1);
    assert_eq!(publish::display(f(599999,110,2),l,120).source,1);
    assert_eq!(publish::display(f(20000001,110,2),l,120).source,1);
}
