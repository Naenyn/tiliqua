include!("../help_build.rs");

fn main() {
    println!("cargo:rerun-if-changed=memory.x");
    configure_help("REZO");
}
