import json
import os
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from acheron import analyze
from acheron.ai.evidence import build_context, parse_result
from acheron.desktop.charon import CharonWindow
from acheron.desktop.window import MainWindow
from acheron.desktop.theme import STYLE

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/known_O0.exe"


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    return app


def test_simple_mode_restores_views_panels_and_persists(app, tmp_path):
    settings = tmp_path / "ui-settings.json"
    window = MainWindow(settings_path=settings)
    window.show()
    try:
        window.set_project(analyze(FIXTURE))
        window.navigate(0x401020)
        window.tabs.setCurrentIndex(2)
        window.set_simple_mode(True)
        assert window.tabs.currentIndex() == window.overview_index
        assert window.functions.isColumnHidden(1)
        assert not window.tabs.isTabVisible(2)
        assert "1 conditional branches" in window.simple_readout.facts.text()
        assert not window.right_panel.isVisible()
        assert window.current_function.address == 0x401020
        window.set_simple_mode(False)
        assert window.tabs.currentIndex() == 2
        assert window.right_panel.isVisible()
        assert window.tabs.isTabVisible(2)
        window.set_simple_mode(True)
    finally:
        window.close()
    reopened = MainWindow(settings_path=settings)
    try:
        assert reopened.simple_mode
        reopened.activateWindow()
        reopened.show()
        QTest.qWait(20)
        QTest.keyClick(reopened, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert not reopened.simple_mode
    finally:
        reopened.close()


def test_charon_evidence_navigation_review_and_session_key(app, tmp_path):
    window = CharonWindow(tmp_path)
    window.show()
    try:
        window.set_project(analyze(FIXTURE))
        window.navigate(0x401020)
        context = build_context(window.project, window.current_function)
        raw = json.dumps({"summary": "A test hypothesis", "findings": [{"title": "Branch", "explanation": "Test only", "evidence_ids": ["E006"], "confidence": "low"}], "limitations": ["Not a real inference"]})
        findings = parse_result(raw, context, "local", "test-model")["findings"]
        window.project.hypotheses.extend(findings)
        before = window.project.snapshot()
        window.ai_panel.refresh_findings()
        assert window.ai_panel.findings.count() == 2
        assert window.ai_panel.current['overview']
        assert "1 hypotheses" in window.ai_panel.status.text()
        window.ai_panel.findings.setCurrentRow(1)
        assert "interpretation not verified" in window.ai_panel.claim_status.text()
        window.ai_panel.review.setCurrentIndex(1)
        assert window.project.hypotheses[0]["review"] == "useful"
        window.set_simple_mode(True)
        window.ai_panel.open_evidence(1)
        assert not window.simple_mode
        assert window.current_address == 0x40102C
        assert window.tabs.currentIndex() == 1
        assert window.project.snapshot() == before
        # The same instruction in another view still needs a Back destination.
        window.tabs.setCurrentIndex(window.investigation_index)
        window.ai_panel.open_evidence(0)
        window.go_back()
        assert window.tabs.currentIndex() == window.investigation_index
        window.api_key = "test-secret-not-a-real-key"
        window.cloud_model = "model-from-test"
        window.provider = "openai"
        window.save_ai_settings()
        assert window.api_key not in (tmp_path / "ai-settings.json").read_text()
        window.ai_panel.refresh_status()
        assert window.ai_panel.run.text() == "Send to OpenAI & explain"
        window.show_ai_setup()
        assert window.ai_setup.key_input.echoMode() == window.ai_setup.key_input.EchoMode.Password
        window.set_project(analyze(FIXTURE))
        assert window.ai_panel.findings.count() == 0
    finally:
        window.close()
    assert window.api_key == ""


def test_missing_model_opens_actionable_setup_without_fake_findings(app, tmp_path):
    window = CharonWindow(tmp_path)
    try:
        window.set_project(analyze(FIXTURE))
        window.investigate()
        assert window.ai_setup is not None
        assert "Download" in window.ai_panel.status.text()
        assert not window.project.hypotheses
        assert not window.ai_busy
    finally:
        window.close()


def test_presets_custom_question_survives_refresh_and_overview_persists(app, tmp_path):
    from acheron.project import Project
    from acheron.report import report_chunks
    window = CharonWindow(tmp_path)
    window.show()
    try:
        window.set_project(analyze(FIXTURE))
        window.tabs.setCurrentIndex(window.investigation_index)
        panel = window.ai_panel
        assert window.simple_mode
        assert not panel.question.isVisible()
        panel.presets.setCurrentIndex(3)
        panel.question.setText('What happens at the return?')
        panel.run.setFocus()
        panel.refresh_status()
        assert panel.question.isVisible()
        assert panel.question.text() == 'What happens at the return?'
        panel.presets.setCurrentIndex(1)
        assert 'step by step' in panel.question.text()
        panel.presets.setCurrentIndex(3)
        assert panel.question.text() == 'What happens at the return?'
        context = build_context(window.project, window.current_function, panel.question.text())
        result = parse_result(json.dumps({'summary': 'Summary without findings', 'findings': [], 'limitations': ['Insufficient evidence']}), context, 'local', 'test-model')
        before = window.project.snapshot()
        window.ai_busy = True
        window.origin_project = window.project
        window.ai_result(result)
        window.ai_finished()
        assert 'Summary without findings' in panel.details.toPlainText()
        assert not window.project.hypotheses
        assert window.project.snapshot() == before
        path = tmp_path / 'answer.acheron'
        window.project.save(path)
        window.set_project(Project.load(path))
        assert 'Summary without findings' in panel.details.toPlainText()
        report = ''.join(report_chunks(window.project))
        assert 'Summary without findings' in report
        assert 'What happens at the return?' in report
        assert 'HYPOTHESIZED' in report
    finally:
        window.close()


def test_any_file_ui_ai_evidence_and_switch_back_to_code(app, tmp_path):
    from acheron.inspection import inspect_file
    path = tmp_path / 'notes.txt'
    path.write_text('These are real extracted file contents.', encoding='utf-8')
    window = CharonWindow(tmp_path / 'data')
    window.show()
    try:
        window.set_project(inspect_file(path))
        assert window.tabs.currentIndex() == window.file_index
        assert window.file_view.text.toPlainText() == path.read_text()
        assert not window.commands['entry'].isEnabled()
        assert not window.tabs.isTabVisible(0)
        assert window.ai_panel.run.isEnabled()
        assert window.ai_panel.presets.itemText(0) == 'What is in this file?'
        window.tabs.setCurrentIndex(window.investigation_index)
        context = build_context(window.project, None)
        result = parse_result(json.dumps({'summary': 'File summary test', 'findings': [{'title': 'Text', 'explanation': 'Synthetic finding', 'confidence': 'low', 'evidence_ids': ['E001']}], 'limitations': ['Test only']}), context, 'local', 'test')
        window.ai_busy = True
        window.origin_project = window.project
        window.ai_result(result)
        window.ai_finished()
        window.ai_panel.findings.setCurrentRow(1)
        window.ai_panel.open_evidence(0)
        assert window.tabs.currentIndex() == window.file_index
        assert window.file_view.selected_offset == 0
        assert window.file_view.views.currentWidget() == window.file_view.hex
        window.download_results()
        assert window.download_dialog.code.text() == 'Text and strings'
        assert 'File summary test' in window.download_dialog.preview.toPlainText()
        window.download_dialog.close()
        window.set_project(analyze(FIXTURE))
        assert window.tabs.isTabVisible(0)
        assert not window.tabs.isTabVisible(window.file_index)
        assert window.explorer.parentWidget().isVisible()
        assert window.commands['overview'].isEnabled()
        assert window.ai_panel.presets.itemText(0) == 'What does this section do?'
    finally:
        window.close()
