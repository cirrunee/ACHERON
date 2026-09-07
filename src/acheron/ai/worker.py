"""Cancellable process for downloads and inference; request arrives through stdin."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
from urllib.request import Request, urlopen

from .catalog import MODELS, model_path
from .evidence import SCHEMA, SYSTEM, parse_result, prompt
from .transport import json_request


def emit(kind, **values):
    print(json.dumps({"type": kind, **values}), flush=True)


def download_model(model_id, data_dir, progress=lambda **kw: None):
    model = MODELS[model_id]
    destination = model_path(Path(data_dir), model_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part")
    if destination.exists() and destination.stat().st_size == model["size"]:
        progress(message="Verifying installed model…", completed=0, total=model["size"])
        with destination.open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() == model["sha256"]:
                _receipt(destination, model)
                return str(destination)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > model["size"]:
        raise ValueError("Partial download exceeds the expected model size. Remove that .part file and retry.")
    if shutil.disk_usage(destination.parent).free < model["size"] - offset + 100_000_000:
        raise ValueError("Not enough free disk space for this model. Choose a smaller model or free space.")
    if offset < model["size"]:
        headers = {"User-Agent": "ACHERON-CHARON/0.2"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        with urlopen(Request(model["url"], headers=headers), timeout=30) as response:
            if response.status == 206:
                if not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("The download server returned the wrong resume range.")
            else:
                offset = 0
            with partial.open("ab" if offset else "wb") as output:
                last = 0
                while chunk := response.read(1024 * 1024):
                    offset += len(chunk)
                    if offset > model["size"]:
                        raise ValueError("Download exceeded its expected size.")
                    output.write(chunk)
                    if time.monotonic() - last > .15:
                        progress(message="Downloading model…", completed=offset, total=model["size"])
                        last = time.monotonic()
    if partial.stat().st_size != model["size"]:
        raise ValueError("Download was interrupted. Press Download again to resume.")
    progress(message="Verifying SHA-256…", completed=model["size"], total=model["size"])
    with partial.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if digest != model["sha256"]:
        partial.unlink()
        raise ValueError("Model checksum did not match. The incomplete file was removed; retry the download.")
    partial.replace(destination)
    _receipt(destination, model)
    return str(destination)


def _receipt(path, model):
    path.with_suffix(".verified.json").write_text(json.dumps({"sha256": model["sha256"], "size": path.stat().st_size,
                                                            "mtime_ns": path.stat().st_mtime_ns}), encoding="utf-8")


def investigate(request):
    provider, model, context = request["provider"], request["model"], request["context"]
    if provider == "openai":
        result = json_request("https://api.openai.com/v1/responses", {
            "model": model, "instructions": SYSTEM, "input": prompt(context), "store": False,
            "max_output_tokens": 3000,
            "text": {"format": {"type": "json_schema", "name": "charon_investigation", "strict": True, "schema": SCHEMA}}}, key=request["key"], timeout=300)
        if result.get("status") != "completed":
            raise ValueError("The provider did not complete the answer. Try a shorter question or another model.")
        raw = "\n".join(part["text"] for item in result.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")
    elif provider == "local":
        result = json_request(request["endpoint"] + "/v1/chat/completions", {
            "model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(context)}],
            "temperature": .2, "max_tokens": 1600, "stream": False,
            "response_format": {"type": "json_schema", "json_schema": {"name": "charon_investigation", "strict": True, "schema": SCHEMA}}},
            key=request["key"], timeout=600)
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ValueError("The model reached its answer limit. Ask a narrower question or retry.")
        raw = choice["message"]["content"]
    else:
        raise ValueError("Unknown provider")
    return parse_result(raw, context, provider, model)


def main():
    # PyInstaller's windowed bootloader leaves Python streams unset even when
    # QProcess supplies valid Windows pipe handles. Reattach only our own pipes.
    if sys.platform == "win32" and (sys.stdin is None or sys.stdout is None):
        import ctypes
        import msvcrt
        import os
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
        kernel.GetStdHandle.restype = ctypes.c_void_p
        if sys.stdin is None:
            handle = kernel.GetStdHandle(ctypes.c_ulong(-10).value)
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            sys.stdin = open(descriptor, "r", encoding="utf-8", closefd=False)
        if sys.stdout is None:
            handle = kernel.GetStdHandle(ctypes.c_ulong(-11).value)
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
            sys.stdout = open(descriptor, "w", encoding="utf-8", buffering=1, closefd=False)
    try:
        raw = sys.stdin.buffer.read(500_001)
        if len(raw) > 500_000:
            raise ValueError("AI request is too large")
        request = json.loads(raw)
        if request["operation"] == "download":
            result = download_model(request["model_id"], request["data_dir"], lambda **values: emit("progress", **values))
        elif request["operation"] == "models":
            result = sorted(row["id"] for row in json_request("https://api.openai.com/v1/models", key=request["key"], timeout=30)["data"])
        elif request["operation"] == "investigate":
            result = investigate(request)
        else:
            raise ValueError("Unknown AI operation")
        emit("result", result=result)
        return 0
    except Exception as exc:
        message = str(exc)[:1000]
        if isinstance(locals().get("request"), dict) and request.get("key"):
            message = message.replace(request["key"], "[redacted]")
        emit("error", message=message or type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
