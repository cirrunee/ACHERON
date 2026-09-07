"""Rebuild test binaries using Zig 0.13.0's Clang/LLD; never execute output.

Install developer tool only: python -m pip install ziglang==0.13.0
Run from any directory: python fixtures/build.py
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys


def main() -> None:
    here = Path(__file__).resolve().parent
    cache = here.parent / "build" / "zig-cache"
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(cache), ZIG_LOCAL_CACHE_DIR=str(cache / "local"))
    version = subprocess.check_output([sys.executable, "-m", "ziglang", "version"], text=True).strip()
    if version != "0.13.0":
        raise SystemExit(f"Expected Zig 0.13.0, found {version}")
    manifest = {"compiler": "Zig 0.13.0 (bundled Clang/LLD)", "license": "MIT", "binaries": []}
    for target, opt in (("x86_64", "0"), ("x86_64", "1"), ("x86", "0")):
        name = f"known_x86_O{opt}.exe" if target == 'x86' else f"known_O{opt}.exe"
        flags = ["cc", "-target", f"{target}-windows-msvc", f"-O{opt}", "-fno-stack-protector", "-fno-sanitize=all",
                 "-nostdlib", "-Wl,--entry,entry", "-Wl,--subsystem,console",
                 "known_source.c", "-o", name]
        subprocess.run([sys.executable, "-m", "ziglang", *flags], cwd=here, env=env, check=True)
        manifest["binaries"].append({"file": name, "sha256": hashlib.sha256((here / name).read_bytes()).hexdigest(),
                                     "flags": flags})
    (here / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
