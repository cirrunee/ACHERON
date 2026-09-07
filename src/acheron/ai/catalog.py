"""Pinned official downloads; SHA-256 verified before use."""
import json
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
MODELS = {model["id"]: model for model in CATALOG["models"]}
DEFAULT_MODEL = "qwen-coder-7b"
RUNTIMES = {runtime["id"]: runtime for runtime in CATALOG["runtimes"]}


def model_path(data_dir: Path, model_id: str) -> Path:
    return data_dir / "models" / MODELS[model_id]["filename"]


def installed(data_dir: Path, model_id: str) -> bool:
    model = MODELS[model_id]
    path = model_path(data_dir, model_id)
    receipt = path.with_suffix(".verified.json")
    try:
        record = json.loads(receipt.read_text(encoding="utf-8"))
        stat = path.stat()
        return stat.st_size == model["size"] and record == {"sha256": model["sha256"], "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    except (OSError, ValueError):
        return False
