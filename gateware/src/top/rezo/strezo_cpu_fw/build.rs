fn main() {
    // Cargo does not discover linker-script dependencies passed through
    // rustflags. Force a relink whenever the generated memory map changes.
    println!("cargo:rerun-if-changed=memory.x");
    println!("cargo:rerun-if-changed=../help_content.py");
    println!("cargo:rerun-if-changed=../STREZO_HELP.md");
    let output = std::process::Command::new("python3")
        .arg("../help_content.py")
        .output()
        .expect("Python is required to format the built-in help");
    assert!(
        output.status.success(),
        "Help formatting failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let limit: u32 = String::from_utf8(output.stdout)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    let destination =
        std::path::PathBuf::from(std::env::var("OUT_DIR").unwrap()).join("help_scroll.rs");
    std::fs::write(
        destination,
        format!("const HELP_SCROLL_MAX: u32 = {limit};\n"),
    )
    .unwrap();
}
