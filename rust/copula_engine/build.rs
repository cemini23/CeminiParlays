//! macOS links a cdylib with `-undefined error` by default. A Python extension
//! module must leave the `Py*` symbols undefined and resolve them from the
//! interpreter that dlopen()s it, so pass `-undefined dynamic_lookup`. Other
//! platforms already allow undefined symbols in a shared object.
fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rustc-cdylib-link-arg=-undefined");
        println!("cargo:rustc-cdylib-link-arg=dynamic_lookup");
    }
}
