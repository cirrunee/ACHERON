"""Package both editions, excluding user settings and investigation data."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--github", action="store_true", help="Create versioned release assets; CHARON downloads model weights in the app")
args = parser.parse_args()
destination = root / "outputs" / "github" / "v0.4.0" if args.github else root / "outputs"
destination.mkdir(parents=True, exist_ok=True)
model_note = ("GITHUB DOWNLOAD — FIRST-TIME AI SETUP\n\n"
              "This ZIP includes CHARON and the CPU/Vulkan AI runtimes. Model weights\n"
              "are downloaded separately. Open ACHERON-CHARON.exe, click AI settings,\n"
              "choose a model, then click Download and use. No API key is needed.\n"
              "Choose 1.5B for a smaller download or 7B for the balanced option.\n"
              "Internet is needed for the first model download; local AI works offline\n"
              "afterward. Keep the full extracted folder together.\n\n"
              "The instructions below also describe the optional full offline bundle.\n"
              "Its preinstalled-model references do not apply to this smaller ZIP.\n\n")
manifest = {"creator": "cirrune", "version": "0.4.0", "platform": "Windows x64", "editions": []}
for edition, folder, executable in (("Base", "ACHERON-Base-0.4", "ACHERON.exe"), ("CHARON", "ACHERON-CHARON-0.4", "ACHERON-CHARON.exe")):
    app = root / "outputs" / folder
    archive = destination / (f"ACHERON-{edition}-0.4.0-Windows-x64.zip" if args.github else f"ACHERON-{edition}-Windows.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
        for path in sorted(app.rglob("*")):
            relative = path.relative_to(app)
            if not path.is_file() or path.suffix == ".part":
                continue
            if relative.parts[0] == "data":
                if args.github:
                    continue
                if relative.parts[:2] != ("data", "models") or path.name not in ("qwen2.5-coder-7b-instruct-q4_k_m.gguf", "qwen2.5-coder-7b-instruct-q4_k_m.verified.json"):
                    continue
            print(f"{edition}: {relative}", flush=True)
            if args.github and edition == "CHARON" and relative.as_posix() in ("START HERE.txt", "CHARON GUIDE.txt"):
                bundle.writestr(str(Path(folder) / relative).replace("\\", "/"), model_note + path.read_text(encoding="utf-8"))
                continue
            bundle.write(path, Path(folder) / relative, compress_type=zipfile.ZIP_STORED if path.suffix == ".gguf" else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert f"{folder}/{executable}" in bundle.namelist()
        assert f"{folder}/_internal/python312.dll" in bundle.namelist()
        assert not any("ai-settings.json" in item for item in bundle.namelist())
        if args.github:
            assert archive.stat().st_size < 2 * 1024**3
            assert not any(item.startswith(f"{folder}/data/") for item in bundle.namelist())
            if edition == "CHARON":
                assert all(f"{folder}/runtime/{kind}/llama-server.exe" in bundle.namelist() for kind in ("cpu", "vulkan"))
    def digest(path):
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()
    manifest["editions"].append({"edition": edition, "entrypoint": f"{folder}/{executable}",
        "archive": archive.name, "bytes": archive.stat().st_size, "sha256": digest(archive),
        "executable_sha256": digest(app / executable),
        "bundled_model": "Qwen2.5-Coder-7B-Instruct Q4_K_M" if not args.github and edition == "CHARON" and (app / "data/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf").is_file() else None})
(destination / "desktop-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
if args.github:
    (destination / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['archive']}\n" for item in manifest['editions']), encoding="utf-8")
print(json.dumps(manifest, indent=2), flush=True)
