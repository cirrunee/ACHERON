"""Analysis worker protocol. Runs only our parser; never executes input binaries."""
from __future__ import annotations

import json
from pathlib import Path
import time

from ..project import open_project


def run_worker(source: str, destination: str, status_path: str) -> int:
    status = Path(status_path)

    def report(message: str, *, error: bool = False, done: bool = False) -> None:
        staging = status.with_suffix(".pending")
        staging.write_text(json.dumps({"message": message, "error": error, "done": done}), encoding="utf-8")
        # Windows readers can briefly deny replacement while the GUI polls.
        # Keep the atomic protocol, with a bounded retry for that sharing race.
        for attempt in range(6):
            try:
                staging.replace(status)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.01 * (attempt + 1))

    try:
        project = open_project(source, progress=report, inspect_fallback=True)
        report("Preparing analysis views")
        project.save(destination)
        report("Analysis ready", done=True)
        return 0
    except Exception as exc:
        report(str(exc) or type(exc).__name__, error=True, done=True)
        return 2
