fn main() {
    // NDK r27 defaults to 4 KiB; keep the library loadable on 16 KiB Android devices.
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("android") {
        println!("cargo:rustc-link-arg=-Wl,-z,max-page-size=16384");
    }
    tauri_build::build()
}
