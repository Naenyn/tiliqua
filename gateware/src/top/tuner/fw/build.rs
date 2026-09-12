fn main() {
    println!("cargo:rustc-check-cfg=cfg(tuner_nsdf)");
    println!("cargo:rerun-if-env-changed=TILIQUA_TUNER_NSDF");
    if std::env::var("TILIQUA_TUNER_NSDF").as_deref() == Ok("1") {
        println!("cargo:rustc-cfg=tuner_nsdf");
    }
}
