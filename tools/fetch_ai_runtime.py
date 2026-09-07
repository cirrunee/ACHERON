"""Fetch pinned official llama.cpp CPU/GPU releases and preserve their notices."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile
from acheron.ai.catalog import RUNTIMES, MODELS, DEFAULT_MODEL

root = Path(__file__).resolve().parents[1]
assets = root / "work" / "ai-assets"
assets.mkdir(parents=True, exist_ok=True)
for kind, runtime in RUNTIMES.items():
    destination = assets / runtime["filename"]
    if not destination.exists():
        urllib.request.urlretrieve(runtime["url"], destination)
    with destination.open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != runtime["sha256"]:
            raise ValueError("Runtime checksum mismatch")
    folder = assets / kind
    folder.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination) as archive:
        for item in archive.infolist():
            (folder / item.filename).resolve().relative_to(folder.resolve())
        archive.extractall(folder)
    print(f"Verified {kind} runtime {runtime['version']}")
model = MODELS[DEFAULT_MODEL]
for filename, url in (("llama.cpp-LICENSE.txt", f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{RUNTIMES['cpu']['version']}/LICENSE"),
                      ("Qwen-Apache-2.0.txt", f"https://huggingface.co/{model['repo']}/raw/{model['revision']}/LICENSE")):
    urllib.request.urlretrieve(url, assets / filename)
