fn main() {
    println!("cargo:rerun-if-env-changed=TILIQUA_INTONO_REPEAT_DIAGNOSTIC");
    println!("cargo:rerun-if-env-changed=TILIQUA_TUNER_REPEAT_DIAGNOSTIC");
    let repeat = std::env::var("TILIQUA_INTONO_REPEAT_DIAGNOSTIC")
        .or_else(|_| std::env::var("TILIQUA_TUNER_REPEAT_DIAGNOSTIC"))
        .unwrap_or_default();
    assert!(matches!(repeat.as_str(), "" | "0" | "1"));
    println!("cargo:rustc-env=TILIQUA_INTONO_REPEAT_DIAGNOSTIC={repeat}");
    println!("cargo:rerun-if-env-changed=TILIQUA_INTONO_NSDF_TRACE");
    println!("cargo:rerun-if-env-changed=TILIQUA_TUNER_NSDF_TRACE");
    let trace = std::env::var("TILIQUA_INTONO_NSDF_TRACE")
        .or_else(|_| std::env::var("TILIQUA_TUNER_NSDF_TRACE"))
        .unwrap_or_else(|_| "continuous-quiet".into());
    assert!(
        matches!(
            trace.as_str(),
            "full" | "fast-native" | "fast-low" | "fast-all" | "continuous" | "continuous-quiet" | "continuous-wave" | "continuous-pair"
        ),
        "invalid NSDF trace mode"
    );
    println!("cargo:rustc-check-cfg=cfg(tuner_nsdf_continuous)");
    println!("cargo:rustc-check-cfg=cfg(tuner_nsdf_wave_diag)");
    println!("cargo:rustc-check-cfg=cfg(tuner_nsdf_pair_diag)");
    if trace == "continuous" || trace == "continuous-quiet" || trace == "continuous-wave" || trace == "continuous-pair" {
        println!("cargo:rustc-cfg=tuner_nsdf_continuous");
    }
    if trace == "continuous-wave" || trace == "continuous-pair" {
        println!("cargo:rustc-cfg=tuner_nsdf_wave_diag");
    }
    if trace == "continuous-pair" {
        println!("cargo:rustc-cfg=tuner_nsdf_pair_diag");
    }
    println!("cargo:rustc-env=TILIQUA_INTONO_NSDF_TRACE={trace}");
}
