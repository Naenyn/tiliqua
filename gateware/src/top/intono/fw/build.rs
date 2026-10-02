#[allow(dead_code)]
#[path = "src/ui_scene.rs"]
mod ui_scene;

// Exact point coordinates stored as an origin every 16 points and signed
// byte offsets from that origin. Lookup is constant-time integer arithmetic.
fn pack_guide(source: &mut String, name: &str, points: &[(i32,i32)]) {
    use std::fmt::Write;
    let origins = points.iter().step_by(16).copied().collect::<Vec<_>>();
    writeln!(source, "pub static {name}_ORIGINS: [(u16,u16);{}] = {:?};", origins.len(), origins).unwrap();
    writeln!(source, "pub static {name}_OFFSETS: [u16;{}] = [", points.len()).unwrap();
    for (index, &(x,y)) in points.iter().enumerate() {
        assert!((0..720).contains(&x) && (0..720).contains(&y));
        let (ox,oy) = origins[index/16];
        let dx = i8::try_from(x-ox).expect("guide x offset exceeds signed byte");
        let dy = i8::try_from(y-oy).expect("guide y offset exceeds signed byte");
        writeln!(source, "{},", dx as u8 as u16 | ((dy as u8 as u16)<<8)).unwrap();
    }
    source.push_str("];\n");
    writeln!(source, "pub const {name}: Guide = Guide {{origins: &{name}_ORIGINS, offsets: &{name}_OFFSETS}};").unwrap();
}

// Explicit micromath operations match the former no_std drawing path.
fn static_guides(output: &std::path::Path) {
    let mut source = String::from(r#"
pub struct Guide {
    origins: &'static [(u16,u16)],
    offsets: &'static [u16],
}
impl Guide {
    pub fn len(&self) -> usize { self.offsets.len() }
    pub fn point(&self, index: usize) -> (u16,u16) {
        let (x,y) = self.origins[index/16];
        let packed = self.offsets[index];
        ((x as i32 + (packed as u8 as i8) as i32) as u16,
         (y as i32 + ((packed>>8) as u8 as i8) as i32) as u16)
    }
}
"#);
    let border = (0..=2048).map(|step| {
        let angle = step as f32 * core::f32::consts::TAU / 2048.0;
        (360 + micromath::F32Ext::round(356.0 * micromath::F32Ext::cos(angle)) as i32,
         360 + micromath::F32Ext::round(356.0 * micromath::F32Ext::sin(angle)) as i32)
    }).collect::<Vec<_>>();
    pack_guide(&mut source,"BORDER",&border);
    let steps = ui_scene::SPIRAL_OCTAVES * ui_scene::SPIRAL_STEPS;
    let spiral = (0..=steps).map(|step| {
        let turns = 1.0 + step as f32 / ui_scene::SPIRAL_STEPS as f32;
        let radius = ui_scene::spiral_radius(turns * 12.0);
        let angle = turns * core::f32::consts::TAU - core::f32::consts::FRAC_PI_2;
        (ui_scene::SPIRAL_CENTER.0 + (radius * micromath::F32Ext::cos(angle)) as i32,
         ui_scene::SPIRAL_CENTER.1 + (radius * micromath::F32Ext::sin(angle)) as i32)
    }).collect::<Vec<_>>();
    pack_guide(&mut source,"SPIRAL",&spiral);
    std::fs::write(output.join("static-guides.rs"), source).unwrap();
}

fn main() {
    // Framebuffer caches reserve PSRAM from +8 MiB. Limit the executable
    // region at link time so a future larger firmware cannot overlap them.
    println!("cargo:rerun-if-changed=memory.x");
    let memory = std::fs::read_to_string("memory.x").expect("generated memory.x");
    let bounded = memory.lines().map(|line| {
        if line.contains("psram :") { line.replace("LENGTH = 0x01000000", "LENGTH = 0x00800000") }
        else { line.to_owned() }
    }).collect::<Vec<_>>().join("\n");
    assert!(bounded.contains("psram : ORIGIN = 0x20000000, LENGTH = 0x00800000"));
    let output = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    std::fs::write(output.join("intono-cache-memory.x"), bounded).unwrap();
    std::fs::write(output.join("intono-runtime.x"), r#"
SECTIONS {
    .intono_runtime 0x20500000 (NOLOAD) : ALIGN(16) {
        KEEP(*(.intono_runtime));
    } > psram
} INSERT AFTER .bss;
/* Leave room for the live loop, nested calibration calls and interrupt frames.
   This is a static-data guard; compiled stack use still requires inspection. */
ASSERT(_stack_start - _ebss >= 0x6000,
       "Intono SRAM leaves less than 24 KiB for runtime stack");
ASSERT(LOADADDR(.data) + SIZEOF(.data) <= 0x20500000,
       "Intono firmware overlaps reserved runtime storage");
ASSERT(ADDR(.intono_runtime) + SIZEOF(.intono_runtime) <= 0x20800000,
       "Intono runtime storage overlaps framebuffer caches");
"#).unwrap();
    static_guides(&output);
    println!("cargo:rerun-if-changed=src/ui_scene.rs");
    println!("cargo:rustc-link-search={}", output.display());
    println!("cargo:rerun-if-env-changed=TILIQUA_INTONO_VERBOSE_DIAGNOSTICS");
    println!("cargo:rustc-check-cfg=cfg(intono_verbose_diagnostics)");
    let verbose = std::env::var("TILIQUA_INTONO_VERBOSE_DIAGNOSTICS").unwrap_or_default();
    assert!(matches!(verbose.as_str(), "" | "0" | "1"));
    if verbose == "1" {
        println!("cargo:rustc-cfg=intono_verbose_diagnostics");
    }
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
