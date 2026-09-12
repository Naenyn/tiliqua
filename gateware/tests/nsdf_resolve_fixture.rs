use std::io::{self,BufRead};
#[path="../src/top/tuner/fw/src/nsdf_resolve.rs"] mod resolve;
fn main() {
    for line in io::stdin().lock().lines() {
        let line=line.unwrap();let v:Vec<u32>=line.split_whitespace().map(|s|s.parse().unwrap()).collect();
        assert_eq!(v.len(),6);
        let r=resolve::resolve(resolve::Candidate{mhz:v[0],age:v[1],qualified:v[2]!=0},
            resolve::Candidate{mhz:v[3],age:v[4],qualified:v[5]!=0});
        println!("{} {}",r.mhz,r.source);
    }
}
