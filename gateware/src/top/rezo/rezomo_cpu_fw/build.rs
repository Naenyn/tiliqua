fn main() {
    // Cargo does not discover linker-script dependencies passed through
    // rustflags. Force a relink whenever the generated memory map changes.
    println!("cargo:rerun-if-changed=memory.x");
}
