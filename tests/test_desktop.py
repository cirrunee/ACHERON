"""Qt integration tests exercise real analysis, navigation, exports and workers."""
import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from acheron import analyze
from acheron.desktop.theme import STYLE
from acheron.desktop.window import MainWindow
from acheron.desktop.worker import run_worker
from acheron.project import Project

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "known_O0.exe"


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyle("Fusion")
    for font in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
        path = Path("C:/Windows/Fonts") / font
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    instance.setStyleSheet(STYLE)
    return instance


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    app.processEvents()
    yield window
    window.close()
    app.processEvents()


def wait_for(app, condition, seconds=20):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(30)
        app.processEvents()
    assert condition(), "Timed out waiting for GUI/worker condition"


def test_real_sample_worker_and_synchronized_views(app, window):
    QTest.mouseClick(window.welcome_sample, Qt.MouseButton.LeftButton)
    assert not window.open_button.isEnabled()
    wait_for(app, lambda: window.project is not None or hasattr(window, "error_dialog"))
    assert window.project is not None, window.error_dialog.text() if hasattr(window, "error_dialog") else "No analysis result"
    assert window.worker is None
    assert window.functions.topLevelItemCount() == 5
    choose = next(f for f in window.project.functions if f.name == "choose")
    window.navigate(choose.address)
    assert window.current_function == choose
    assert "condition_le" in window.pseudocode.toPlainText()
    assert window.disassembly.rowCount() == 17
    assert len(window.cfg.nodes) == 4
    assert window.cfg.edges_count == 4
    instruction = choose.blocks[1].instructions[1]
    window.disassembly.selectRow(window.instruction_rows[instruction.address])
    app.processEvents()
    assert window.current_address == instruction.address
    assert window.pseudocode.extraSelections()
    assert window.air.extraSelections()
    window.filter.setText("choose")
    visible = [i for i in window.function_items.values() if not i.isHidden()]
    assert len(visible) == 1
    window.tabs.setCurrentIndex(4)
    app.processEvents()
    assert len(window.calls.nodes) == 5
    assert window.calls.edges_count == len(window.project.references)


def test_call_navigation_history_exports_and_reload(app, window, tmp_path):
    window.set_project(analyze(FIXTURE))
    invoke = next(f for f in window.project.functions if f.name == "invoke")
    window.navigate(invoke.address)
    call = next(i for b in invoke.blocks for i in b.instructions if i.flow == "call")
    window.follow_instruction(call.address)
    assert window.current_function.address == call.target
    window.go_back()
    assert window.current_function.address == invoke.address
    for kind in ("code", "air", "cfg", "json"):
        path = tmp_path / kind
        window.export_to(kind, path)
        assert path.stat().st_size > 100
        with pytest.raises(FileExistsError):
            window.export_to(kind, path)
    database = tmp_path / "saved.acheron"
    window.project.save(database)
    assert Project.load(database).snapshot() == window.project.snapshot()
    original = window.project
    window.open_path(database)
    wait_for(app, lambda: window.worker is None)
    assert window.project is not original
    assert window.project.snapshot() == original.snapshot()


def test_worker_error_preserves_previous_project(app, window, tmp_path):
    original = analyze(FIXTURE)
    window.set_project(original)
    bad = tmp_path / "broken.exe"
    # Any readable file now opens for inspection; a missing file must still
    # preserve the current workspace when the worker fails.
    window.open_path(bad)
    wait_for(app, lambda: window.worker is None)
    assert window.project is original
    assert "No such file" in window.error_dialog.text()
    assert window.open_button.isEnabled()
    window.error_dialog.close()


def test_cancel_stops_process_and_cleans_workspace(app, window):
    window.open_sample()
    directory = Path(window.workspace.path())
    window.cancel_analysis()
    wait_for(app, lambda: window.worker is None)
    assert not directory.exists()
    assert window.open_button.isEnabled()
    assert window.project is None


def test_worker_unicode_input_and_failure_protocol(tmp_path):
    source = tmp_path / "probă test.exe"
    source.write_bytes(FIXTURE.read_bytes())
    destination = tmp_path / "output.acheron"
    status = tmp_path / "status.json"
    assert run_worker(str(source), str(destination), str(status)) == 0
    assert len(Project.load(destination).functions) == 5
    assert run_worker(str(source), str(destination), str(status)) == 2
    assert '"error": true' in status.read_text()


def test_worker_retries_windows_status_sharing_violation(tmp_path, monkeypatch):
    replace = Path.replace
    blocked = []

    def briefly_locked(source, target):
        if source.suffix == ".pending" and len(blocked) < 2:
            blocked.append(source)
            raise PermissionError("Status is briefly open in the GUI")
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", briefly_locked)
    destination = tmp_path / "output.acheron"
    status = tmp_path / "status.json"
    assert run_worker(str(FIXTURE), str(destination), str(status)) == 0
    assert len(blocked) == 2
    assert len(Project.load(destination).functions) == 5
    import json
    assert json.loads(status.read_text())["done"]
    assert not status.with_suffix(".pending").exists()


def test_keyboard_open_entry_search_callers_and_cfg_workflow(app, window):
    window.set_project(analyze(FIXTURE))
    window.activateWindow()
    window.setFocus()
    QTest.qWait(30)
    QTest.keyClick(window, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    assert window.current_function.address == window.project.image["entry"]
    assert window.tabs.currentIndex() == 0
    QTest.keyClick(window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert window.filter.hasFocus()
    QTest.keyClicks(window.filter, "choose")
    QTest.keyClick(window.filter, Qt.Key.Key_Return)
    assert window.current_function.name == "choose"
    assert window.filter.text() == "choose"  # Inspecting a match does not reset search.
    assert "entry evidence" in window.confidence.text()
    assert "not a probability" in window.confidence.toolTip()
    QTest.keyClick(window, Qt.Key.Key_R, Qt.KeyboardModifier.ControlModifier)
    assert window.xrefs.hasFocus()
    QTest.keyClick(window.xrefs, Qt.Key.Key_Return)
    assert window.current_function.name == "invoke"
    QTest.keyClick(window, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert window.current_function.name == "choose"
    QTest.keyClick(window, Qt.Key.Key_4, Qt.KeyboardModifier.AltModifier)
    assert window.tabs.currentIndex() == 3
    assert len(window.cfg.nodes) == 4


def test_source_selection_copy_search_and_view_switch_preserve_address(app, window):
    window.set_project(analyze(FIXTURE))
    window.navigate(0x401020)
    view = window.pseudocode
    view.setFocus()
    address = 0x401035
    line = view.address_lines[address][0]
    cursor = QTextCursor(view.document().findBlockByNumber(line - 1))
    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
    view.setTextCursor(cursor)
    selected = view.textCursor().selectedText()
    assert "sub32" in selected
    assert view.textCursor().hasSelection()
    QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == selected
    assert window.current_address == address
    window.tabs.setCurrentIndex(1)
    assert window.disassembly.item(window.disassembly.currentRow(), 0).data(Qt.ItemDataRole.UserRole) == address
    window.tabs.setCurrentIndex(0)
    window.find_input.setText("sub32")
    window.find_next()
    assert view.textCursor().selectedText() == "sub32"


def test_forward_history_restores_instruction_and_view(app, window):
    window.set_project(analyze(FIXTURE))
    window.navigate(0x401035)
    window.tabs.setCurrentIndex(2)
    window.navigate(0x4010B0)
    window.tabs.setCurrentIndex(1)
    window.go_back()
    assert window.current_address == 0x401035
    assert window.tabs.currentIndex() == 2
    window.go_forward()
    assert window.current_address == 0x4010B0
    assert window.tabs.currentIndex() == 1


def test_progressive_disclosure_identity_and_compact_layout(app, window):
    window.resize(1024, 720)
    window.set_project(analyze(FIXTURE))
    app.processEvents()
    assert window.width() == 1024
    assert not window.log_panel.isVisible()
    window.commands["log"].trigger()
    assert window.log_panel.isVisible()
    window.commands["log"].trigger()
    assert not window.log_panel.isVisible()
    groups = {window.inspector.topLevelItem(i).text(0): window.inspector.topLevelItem(i) for i in range(window.inspector.topLevelItemCount())}
    assert not groups["Machine effects"].isExpanded()
    assert not groups["Block data flow"].isExpanded()
    assert window.signature.width() >= 112
    window.about()
    assert "Created by cirrune" in window.about_dialog.text()
    assert "CHARON" in window.about_dialog.text()
    window.about_dialog.close()


def test_readable_projection_preserves_source_map_and_export(app, window):
    window.set_project(analyze(FIXTURE))
    window.navigate(0x401020)
    function = window.current_function
    original = function.decompile()
    visible = window.pseudocode.toPlainText()
    assert "/* 0x" not in visible
    assert "/* 0x" in original
    assert set(window.pseudocode.address_lines) == {i.address for b in function.blocks for i in b.instructions}
    for address, lines in window.pseudocode.address_lines.items():
        assert all(0 < line <= len(visible.splitlines()) for line in lines)
    assert function.decompile() == original
