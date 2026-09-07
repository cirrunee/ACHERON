from pathlib import Path
import json
import pytest

from acheron import analyze
from acheron.ai.evidence import build_context, parse_result
from acheron.report import ReportCancelled, ReportOptions, report_chunks, write_report

FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/known_O0.exe'


def test_report_scopes_and_separates_ai_from_evidence(tmp_path):
    project = analyze(FIXTURE)
    function = project.function(0x401020)
    before = project.snapshot()
    result = parse_result(json.dumps({'summary': 'AI test overview', 'findings': [{'title': 'Test branch', 'explanation': 'Synthetic test only', 'evidence_ids': ['E006', 'E999'], 'confidence': 'low'}], 'limitations': ['Not a real inference']}), build_context(project, function), 'local', 'test-model')
    project.hypotheses.extend(result['findings'])
    project.annotations.append({'address': function.address, 'kind': 'charon-run', 'value': result['run']})
    destination = tmp_path / 'results.txt'
    write_report(project, destination)
    text = destination.read_text(encoding='utf-8')
    assert all(f'FUNCTION: {f.name} at {f.address:#x}' in text for f in project.functions)
    assert text.count('AI test overview') == 1
    assert 'Unresolved model citation: E999' in text
    assert '0x40102c' in text
    assert 'HYPOTHESIZED, NOT VERIFIED' in text
    assert 'not the original source' in text
    assert 'EXTRACTED FILE DETAILS' in text
    assert str(FIXTURE) not in text
    selected = ''.join(report_chunks(project, ReportOptions(function.address, metadata=False, ai=False, instructions=True)))
    assert selected.count('FUNCTION: ') == 1
    assert 'AI test overview' not in selected
    assert 'DECODED INSTRUCTIONS' in selected
    assert project.snapshot() == before


def test_report_preserves_existing_files_and_cleans_cancelled_output(tmp_path):
    project = analyze(FIXTURE)
    path = tmp_path / 'keep.txt'
    path.write_text('keep this', encoding='utf-8')
    with pytest.raises(FileExistsError):
        write_report(project, path)
    assert path.read_text() == 'keep this'
    calls = 0
    def cancel_after_first_chunk():
        nonlocal calls
        calls += 1
        return calls > 1
    partial = tmp_path / 'cancelled.txt'
    with pytest.raises(ReportCancelled):
        write_report(project, partial, cancelled=cancel_after_first_chunk)
    assert not partial.exists()
    assert calls > 1


def test_download_dialog_writes_text_and_recovers_after_existing_file(tmp_path):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from acheron.desktop.window import MainWindow
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    try:
        window.set_project(analyze(FIXTURE))
        window.download_button.click()
        dialog = window.download_dialog
        assert dialog.isVisible()
        assert 'Whole file' in dialog.preview.toPlainText()
        dialog.scope.setCurrentIndex(1)
        target = tmp_path / 'output.txt'
        target.write_text('keep')
        dialog.save_to(target)
        for _ in range(100):
            QTest.qWait(10)
            if not dialog.writer.isRunning():
                break
        QTest.qWait(10)
        assert target.read_text() == 'keep'
        assert 'Could not save' in dialog.status.text()
        assert dialog.save_button.isEnabled()
        target = tmp_path / 'download.txt'
        dialog.save_to(target)
        for _ in range(100):
            QTest.qWait(10)
            if not dialog.writer.isRunning():
                break
        QTest.qWait(10)
        assert dialog.saved_path == target
        assert dialog.open_button.isVisible()
        assert target.read_text(encoding='utf-8').count('FUNCTION: ') == 1
        dialog.close()
    finally:
        window.close()
