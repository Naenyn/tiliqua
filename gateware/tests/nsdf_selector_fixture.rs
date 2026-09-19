#[path="../src/top/tuner/fw/src/nsdf_select.rs"] mod selector;
use std::io::{self,BufRead};
fn main() {
    for low in [false,true] {
        for scaled in [false,true] {
            let threshold=674*(if scaled {1} else {4});
            for energy in [0,threshold-1,threshold] {
                assert!(selector::select_frame(|_|panic!("quiet frame read"),low,energy,scaled,false).is_none());
            }
            assert!(selector::select_frame(|_|panic!("clipped frame read"),low,u64::MAX,scaled,true).is_none());
            let mut reads=0;
            assert!(selector::select_frame(|_|{reads+=1;0},low,threshold+1,scaled,false).is_none());
            assert!(reads>0);
        }
    }
    for line in io::stdin().lock().lines() {
        let line=line.unwrap();let mut words=line.split_whitespace();
        let low=words.next().unwrap()=="low";
        let scores:Vec<i32>=words.map(|v|v.parse().unwrap()).collect();
        // Shorter arrays replay historical physical windows without padding.
        assert!(if low {[302,502,602,622].contains(&scores.len())}else{scores.len()==322});
        let mut reads=0;
        let result=selector::select_with_limit(|k|{reads+=1;scores[k]},low,scores.len()-1);
        assert!(reads<=2*scores.len()+63);
        if let Some(r)=result {println!("{} {} {} {} {}",r.hz,r.clarity,r.qualified,r.unrefined_hz,reads);}
        else {println!("none {}",reads);}
    }
}
