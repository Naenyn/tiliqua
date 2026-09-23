fn main() {
    println!("cargo:rerun-if-env-changed=TILIQUA_TUNER_REPEAT_DIAGNOSTIC");
    let repeat = std::env::var("TILIQUA_TUNER_REPEAT_DIAGNOSTIC").unwrap_or_default();
    assert!(matches!(repeat.as_str(), "" | "0" | "1"));
    println!("cargo:rustc-env=TILIQUA_TUNER_REPEAT_DIAGNOSTIC={repeat}");
    println!("cargo:rerun-if-env-changed=TILIQUA_TUNER_NSDF_TRACE");
    let trace = std::env::var("TILIQUA_TUNER_NSDF_TRACE")
        .unwrap_or_else(|_| "continuous".into());
    assert!(
        matches!(
            trace.as_str(),
            "full" | "fast-native" | "fast-low" | "fast-all" | "continuous"
        ),
        "invalid NSDF trace mode"
    );
    println!("cargo:rustc-check-cfg=cfg(tuner_nsdf_continuous)");
    if trace == "continuous" {
        println!("cargo:rustc-cfg=tuner_nsdf_continuous");
    }
    println!("cargo:rustc-env=TILIQUA_TUNER_NSDF_TRACE={trace}");
}
