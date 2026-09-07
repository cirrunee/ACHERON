"""Package both editions, excluding user settings and investigation data."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
manifest = {"creator": "cirrune", "version": "0.4.0", "platform": "Windows x64", "editions": []}
for edition, folder, executable in (("Base", "ACHERON-Base-0.4", "ACHERON.exe"), ("CHARON", "ACHERON-CHARON-0.4", "ACHERON-CHARON.exe")):
    app = root / "outputs" / folder
    archive = root / "outputs" / f"ACHERON-{edition}-Windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
        for path in sorted(app.rglob("*")):
            relative = path.relative_to(app)
            if not path.is_file() or path.suffix == ".part":
                continue
            if relative.parts[0] == "data":
                if relative.parts[:2] != ("data", "models") or path.name not in ("qwen2.5-coder-7b-instruct-q4_k_m.gguf", "qwen2.5-coder-7b-instruct-q4_k_m.verified.json"):
                    continue
            print(f"{edition}: {relative}", flush=True)
            bundle.write(path, Path(folder) / relative, compress_type=zipfile.ZIP_STORED if path.suffix == ".gguf" else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert f"{folder}/{executable}" in bundle.namelist()
        assert f"{folder}/_internal/python312.dll" in bundle.namelist()
        assert not any("ai-settings.json" in item for item in bundle.namelist())
    def digest(path):
        with path.open("rb") as file:
            return hashlib.file_digest(file, "sha256").hexdigest()
    manifest["editions"].append({"edition": edition, "entrypoint": f"{folder}/{executable}",
        "archive": archive.name, "bytes": archive.stat().st_size, "sha256": digest(archive),
        "executable_sha256": digest(app / executable),
        "bundled_model": "Qwen2.5-Coder-7B-Instruct Q4_K_M" if edition == "CHARON" and (app / "data/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf").is_file() else None})
(root / "outputs" / "desktop-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(json.dumps(manifest, indent=2), flush=True)
