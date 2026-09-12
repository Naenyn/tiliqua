#[path="../src/top/tuner/fw/src/nsdf_select.rs"] mod selector;
use std::io::{self,BufRead};
fn main() {
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
