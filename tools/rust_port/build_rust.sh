#!/usr/bin/env bash
# Build the Rust copula engine and install it as a Python extension module.
#
#   bash tools/rust_port/build_rust.sh
#
# No maturin: cargo builds a cdylib and the file is copied to the platform
# extension suffix from sysconfig. Exits non-zero on any failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
export PYO3_PYTHON="${PYO3_PYTHON:-$PYTHON}"
MANIFEST="rust/copula_engine/Cargo.toml"

if [ ! -f "$MANIFEST" ]; then
    echo "build_rust: missing $MANIFEST" >&2
    exit 1
fi

echo "build_rust: cargo build --release ($MANIFEST)"
cargo build --release --manifest-path "$MANIFEST"

suffix="$("$PYTHON" -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")"
if [ -z "$suffix" ]; then
    echo "build_rust: could not read EXT_SUFFIX from $PYTHON" >&2
    exit 1
fi

artifact=""
for candidate in \
    "rust/copula_engine/target/release/libcopula_engine.dylib" \
    "rust/copula_engine/target/release/libcopula_engine.so" \
    "rust/copula_engine/target/release/copula_engine.dll"; do
    if [ -f "$candidate" ]; then
        artifact="$candidate"
        break
    fi
done
if [ -z "$artifact" ]; then
    echo "build_rust: no cdylib artifact found under rust/copula_engine/target/release/" >&2
    exit 1
fi

target="src/ceminiparlays/_copula_engine${suffix}"
cp "$artifact" "$target"
echo "build_rust: $artifact -> $target"

PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" - <<'PY'
from ceminiparlays import _copula_engine as engine

value = engine.norm_ppf(0.5)
assert abs(value) <= 1e-12, value
print(f"build_rust: import ok ({engine.__version__}) norm_ppf(0.5)={value}")
PY
