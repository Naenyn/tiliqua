#[path="../src/top/tuner/fw/src/nsdf_select.rs"] mod selector;
use std::io::{self,BufRead};
fn main() {
    for low in [false,true] {
        for scaled in [false,true] {
            let threshold=(if low {604} else {674})*(if scaled {1} else {4});
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
        assert_eq!(scores.len(),if low {302}else{322});
        let mut reads=0;
        let result=selector::select(|k|{reads+=1;scores[k]},low);
        assert!(reads<=2*scores.len()+63);
        if let Some(r)=result {println!("{} {} {} {} {}",r.hz,r.clarity,r.qualified,r.unrefined_hz,reads);}
        else {println!("none {}",reads);}
    }
}
