"""Desktop entry point, also used by the frozen Windows executable."""
from pathlib import Path
import sys


def main(argv=None, edition="base"):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--ai-worker"]:
        from ..ai.worker import main as ai_main
        return ai_main()
    if args and args[0] == "--worker":
        if len(args) != 4:
            return 2
        from .worker import run_worker
        return run_worker(*args[1:])
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .theme import STYLE, app_icon
    from .window import MainWindow

    if "--charon" in args:
        args.remove("--charon")
        edition = "charon"
    data_dir = Path(sys.executable).parent / "data" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3] / "work" / (edition + "-data")
    if "--data-dir" in args:
        index = args.index("--data-dir")
        if index + 1 >= len(args):
            return 2
        data_dir = Path(args[index + 1]).resolve()
        del args[index:index + 2]

    app = QApplication([sys.argv[0]])
    app.setApplicationName("ACHERON")
    app.setOrganizationName("cirrune")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(app_icon())
    if len(args) == 2 and args[0] in ("--smoke-test", "--ai-smoke-test", '--x86-smoke-test', '--x86-ai-smoke-test', '--file-smoke-test', '--file-ai-smoke-test'):
        from .smoke import prepare_smoke_fonts
        prepare_smoke_fonts()
    if edition == "charon":
        from .charon import CharonWindow
        window = CharonWindow(data_dir)
    else:
        window = MainWindow(settings_path=data_dir / "ui-settings.json")
    window.show()
    if len(args) == 2 and args[0] in ('--file-smoke-test', '--file-ai-smoke-test'):
        from .smoke import run_file_smoke
        run_file_smoke(app, window, Path(args[1]), with_ai=args[0] == '--file-ai-smoke-test' and edition == 'charon')
    elif len(args) == 2 and args[0] in ("--ai-smoke-test", '--x86-ai-smoke-test') and edition == "charon":
        from .smoke import run_ai_smoke
        run_ai_smoke(app, window, Path(args[1]), x86=args[0] == '--x86-ai-smoke-test')
    elif len(args) == 2 and args[0] in ("--smoke-test", '--x86-smoke-test'):
        from .smoke import run_smoke
        run_smoke(app, window, Path(args[1]), x86=args[0] == '--x86-smoke-test')
    elif args:
        QTimer.singleShot(0, lambda: window.open_path(Path(args[0])))
    return app.exec()
