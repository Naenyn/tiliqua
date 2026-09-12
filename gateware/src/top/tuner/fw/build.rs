fn main() {
    println!("cargo:rerun-if-env-changed=TILIQUA_TUNER_NSDF_TRACE");
    let trace=std::env::var("TILIQUA_TUNER_NSDF_TRACE").unwrap_or_else(|_|"full".into());
    assert!(matches!(trace.as_str(),"full"|"fast-native"|"fast-low"|"fast-all"),"invalid NSDF trace mode");
    assert!(trace=="full" || std::env::var("TILIQUA_TUNER_NSDF").as_deref()==Ok("1"),
        "fast trace requires NSDF gateware");
    println!("cargo:rustc-env=TILIQUA_TUNER_NSDF_TRACE={trace}");
    println!("cargo:rustc-check-cfg=cfg(tuner_nsdf)");
    println!("cargo:rerun-if-env-changed=TILIQUA_TUNER_NSDF");
    if std::env::var("TILIQUA_TUNER_NSDF").as_deref() == Ok("1") {
        println!("cargo:rustc-cfg=tuner_nsdf");
    }
}
