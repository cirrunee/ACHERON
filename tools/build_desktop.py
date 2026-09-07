"""Build a portable Windows app with dynamically linked Qt libraries.

Run with the build virtual environment: python tools/build_desktop.py
No analyzed target binary is executed by this script.
"""
from pathlib import Path
import importlib.metadata
import os
import shutil
import subprocess
import sys
import argparse


def build(edition, with_model):
    root = Path(__file__).resolve().parents[1]
    name = "ACHERON-CHARON" if edition == "charon" else "ACHERON"
    folder = "ACHERON-CHARON-0.4" if edition == "charon" else "ACHERON-Base-0.4"
    work = root / "work" / "packaging-0.4" / edition
    work.mkdir(parents=True, exist_ok=True)
    staging = work / "distribution"
    destination = root / "outputs" / folder
    # Both generated locations must remain inside this workspace. The previous
    # desktop package stays intact so a running analyst session is not closed.
    staging.resolve().relative_to(root.resolve())
    destination.resolve().relative_to(root.resolve())
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(work / "config")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from acheron.desktop.theme import app_icon
    app = QApplication.instance() or QApplication([])
    icon = work / "acheron.ico"
    if not app_icon().pixmap(256, 256).save(str(icon), "ICO"):
        raise RuntimeError("Unable to create Windows application icon")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                    "--name", name, "--contents-directory", "_internal", "--paths", str(root / "src"),
                    "--icon", str(icon), "--distpath", str(staging),
                    "--version-file", str(root / "tools" / ("windows-charon-version.txt" if edition == "charon" else "windows-version.txt")),
                    "--workpath", str(work / "build"), "--specpath", str(work),
                    "--add-data", str(root / "fixtures" / "known_O0.exe") + ";fixtures",
                    "--add-data", str(root / "fixtures" / "known_x86_O0.exe") + ";fixtures",
                    "--collect-data", "acheron.ai",
                    str(root / ("charon_entry.py" if edition == "charon" else "desktop_entry.py"))], cwd=root, check=True)
    shutil.copytree(staging / name, destination, dirs_exist_ok=True)
    shutil.copy2(root / "LICENSE", destination / "LICENSE.txt")
    shutil.copy2(root / "THIRD_PARTY.md", destination / "THIRD_PARTY.md")
    shutil.copytree(root / "docs" / "provenance", destination / "docs" / "provenance", dirs_exist_ok=True)
    shutil.copy2(root / "docs" / "design-system.md", destination / "docs" / "design-system.md")
    shutil.copy2(root / "docs" / "validation.md", destination / "docs" / "validation.md")
    shutil.copy2(root / "docs" / "release-notes.txt", destination / "RELEASE NOTES.txt")
    shutil.copy2(root / "docs" / "third-party-notices.txt", destination / "docs" / "third-party-notices.txt")
    shutil.copy2(root / "docs" / "desktop-quickstart.txt", destination / "START HERE.txt")
    shutil.copy2(root / "docs" / "charon-quickstart.txt", destination / "CHARON GUIDE.txt")
    shutil.copy2(root / "docs" / "third-party-notices.txt", destination / "THIRD-PARTY-NOTICES.txt")
    (destination / "sample-source").mkdir(exist_ok=True)
    for filename in ("known_source.c", "manifest.json", "build.py"):
        shutil.copy2(root / "fixtures" / filename, destination / "sample-source" / filename)
    if (root / "docs" / "licenses").exists():
        shutil.copytree(root / "docs" / "licenses", destination / "licenses", dirs_exist_ok=True)
    # Include the licenses from installed distributions used in the app.
    for package in ("PySide6-Essentials", "shiboken6", "iced-x86", "pyinstaller"):
        distribution = importlib.metadata.distribution(package)
        for entry in distribution.files or []:
            if any("license" in part.lower() or "copying" in part.lower() for part in entry.parts):
                source = Path(distribution.locate_file(entry))
                if source.is_file() and source.suffix.lower() not in (".py", ".pyc"):
                    target = destination / "licenses" / package / Path(*entry.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    # Python is included by the bundler, so preserve its distribution license.
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, destination / "licenses" / "Python-LICENSE.txt")
    if edition == "charon":
        assets = root / "work" / "ai-assets"
        for kind in ("cpu", "vulkan"):
            if not (assets / kind / "llama-server.exe").is_file():
                raise RuntimeError("Prepare the pinned AI runtimes with tools/fetch_ai_runtime.py first")
            shutil.copytree(assets / kind, destination / "runtime" / kind, dirs_exist_ok=True)
        for filename in ("llama.cpp-LICENSE.txt", "Qwen-Apache-2.0.txt"):
            shutil.copy2(assets / filename, destination / "licenses" / filename)
        if with_model:
            from acheron.ai.catalog import DEFAULT_MODEL, installed, model_path
            data_dir = root / "work" / "charon-data"
            if not installed(data_dir, DEFAULT_MODEL):
                raise RuntimeError("Download and verify Qwen2.5-Coder 7B in the source CHARON app first")
            source = model_path(data_dir, DEFAULT_MODEL)
            target = destination / "data" / "models" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                try:
                    os.link(source, target)
                except OSError:
                    shutil.copy2(source, target)
            shutil.copy2(source.with_suffix(".verified.json"), target.with_suffix(".verified.json"))
    print(f"Built {destination / (name + '.exe')}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", choices=("base", "charon", "both"), default="both")
    parser.add_argument("--with-model", action="store_true", help="Include the verified 7B model in CHARON")
    args = parser.parse_args()
    for edition in (("base", "charon") if args.edition == "both" else (args.edition,)):
        build(edition, args.with_model)


if __name__ == "__main__":
    main()
