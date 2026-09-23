fn main() {
    // Cargo does not discover linker-script dependencies passed through
    // rustflags. Force a relink whenever the generated memory map changes.
    println!("cargo:rerun-if-changed=memory.x");
    println!("cargo:rerun-if-changed=../help_content.py");
    println!("cargo:rerun-if-changed=../STREZO_HELP.md");
    println!("cargo:rerun-if-env-changed=TILIQUA_REZO_HELP_FIRST_BOOT");
    let first_boot = match std::env::var("TILIQUA_REZO_HELP_FIRST_BOOT")
        .unwrap_or_else(|_| "1".into())
        .as_str()
    {
        "1" | "true" => true,
        "0" | "false" => false,
        _ => panic!("TILIQUA_REZO_HELP_FIRST_BOOT must be 0 or 1"),
    };
    let output = std::process::Command::new("python3")
        .arg("../help_content.py")
        .output()
        .expect("Python is required to format the built-in help");
    assert!(
        output.status.success(),
        "Help formatting failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let tables = String::from_utf8(output.stdout).unwrap();
    let destination =
        std::path::PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("help_scroll.rs");
    std::fs::write(
        destination,
        format!("{tables}\nconst SHOW_HELP_ON_FIRST_BOOT: bool = {first_boot};\n"),
    )
    .unwrap();
}
