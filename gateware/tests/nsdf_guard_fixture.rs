use std::io::{self,BufRead};
#[path="../src/top/tuner/fw/src/nsdf_guard.rs"] mod guard;
fn main() {
    for line in io::stdin().lock().lines() {
        let line=line.unwrap();
        let v:Vec<i128>=line.split_whitespace().map(|s|s.parse().unwrap()).collect();
        assert_eq!(v.len(),12);
        println!("{}",guard::passes(guard::Source {end:v[4] as u32,samples:v[5] as u32,
            sum:v[6] as i32,squares:v[7] as u64,status:v[8] as u32},
            v[1] as u8,v[0]!=0,v[2] as u32,v[3] as u32,v[9] as u64,v[10]!=0,v[11]!=0));
    }
}
