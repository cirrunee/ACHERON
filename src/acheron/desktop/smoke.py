"""Optional packaged-app diagnostic: --smoke-test OUTPUT_DIRECTORY.

Exercises the actual GUI and child analyzer using the bundled known-source sample.
This is not run during normal application startup.
"""
import json
import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase

from ..project import Project
from ..report import ReportOptions, write_report


def prepare_smoke_fonts():
    """Register installed fonts before constructing offscreen widgets."""
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        # The Windows offscreen Qt plugin does not enumerate system fonts.
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))


def run_smoke(app, window, destination: Path, x86=False):
    destination.mkdir(parents=True, exist_ok=True)
    state = {"finished": False}

    def finish(success, detail):
        if state["finished"]:
            return
        state["finished"] = True
        (destination / "report.json").write_text(json.dumps({"success": success, **detail}, indent=2), encoding="utf-8")
        window.close()
        app.exit(0 if success else 2)

    def loaded(project):
        try:
            assert len(project.functions) == 5
            assert project.image['bitness'] == (32 if x86 else 64)
            assert window.functions.topLevelItemCount() == 5
            function = next(f for f in project.functions if f.name == "choose")
            window.navigate(function.address)
            assert "condition_le" in window.pseudocode.toPlainText()
            assert len(window.cfg.nodes) == 4
            window.select_address(function.blocks[1].instructions[0].address)
            assert window.pseudocode.extraSelections()
            assert window.air.extraSelections()
            address = window.current_address
            window.commands["entry"].trigger()
            assert window.current_function.address == project.image["entry"]
            window.commands["back"].trigger()
            assert window.current_address == address
            assert "entry evidence" in window.confidence.text()
            assert not window.log_panel.isVisible()
            window.about()
            assert "Created by cirrune" in window.about_dialog.text()
            window.about_dialog.close()
            window.tabs.setCurrentIndex(4)
            assert len(window.calls.nodes) == 5
            window.tabs.setCurrentIndex(0)
            window.export_to("code", destination / "choose.pseudo.c")
            write_report(project, destination / 'all-results.txt')
            assert (destination / 'all-results.txt').read_text(encoding='utf-8').count('FUNCTION: ') == 5
            window.download_button.click()
            app.processEvents()
            assert window.download_dialog.isVisible()
            window.download_dialog.grab().save(str(destination / 'download.png'))
            window.download_dialog.close()
            project.save(destination / "sample.acheron")
            assert len(Project.load(destination / "sample.acheron").functions) == 5
            app.processEvents()
            window.grab().save(str(destination / "desktop.png"))
            finish(True, {"functions": 5, "instructions": len(window.instruction_index), "cfg_nodes": 4,
                          "checks": ["bundled-sample", "separate-worker", "function-list", "pseudocode", "source-sync", "entry-navigation", "history", "evidence-confidence", "progressive-disclosure", "cirrune-attribution", "cfg", "callgraph", "export", "text-report", "download-dialog", "project-reload"]})
        except Exception as exc:
            finish(False, {"error": str(exc) or repr(exc)})

    window.projectLoaded.connect(loaded)
    window.analysisFailed.connect(lambda message: finish(False, {"error": message}))
    QTimer.singleShot(30000, lambda: finish(False, {"error": "Packaged-app check timed out"}))
    QTimer.singleShot(0, window.commands['sample_x86'].trigger if x86 else window.welcome_sample.click)


def run_ai_smoke(app, window, destination: Path, x86=False):
    """Explicit diagnostic invokes the real bundled local model on known source."""
    destination.mkdir(parents=True, exist_ok=True)
    state = {"finished": False}

    def finish(success, detail):
        if state["finished"]:
            return
        state["finished"] = True
        (destination / "report.json").write_text(json.dumps({"success": success, **detail}, indent=2), encoding="utf-8")
        window.close()
        app.exit(0 if success else 2)

    def loaded(project):
        state["snapshot"] = project.snapshot()
        window.navigate(next(f.address for f in project.functions if f.name == "choose"))
        window.set_simple_mode(True)
        window.tabs.setCurrentIndex(window.investigation_index)
        window.ai_panel.run.click()

    def result_ready(result):
        try:
            (destination / "findings.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            assert window.project.hypotheses, "No hypotheses were attached to the project"
            assert window.project.snapshot() == state["snapshot"], "Deterministic snapshot changed"
            assert all(f["status"] == "HYPOTHESIZED" for f in window.project.hypotheses), "Invalid finding status"
            assert window.ai_panel.current.get('overview'), 'The answer did not open with its overview'
            app.processEvents()
            window.grab().save(str(destination / 'answer-overview.png'))
            window.resize(1024, 720)
            app.processEvents()
            window.grab().save(str(destination / 'overview-compact.png'))
            window.resize(1440, 900)
            # Uncertainty findings may correctly have no source citation. Select
            # an evidence-bearing finding to exercise navigation deterministically.
            finding = next((f for f in window.project.hypotheses if f["addresses"]), None)
            assert finding, "The model returned no findings with resolvable instruction references"
            for index in range(window.ai_panel.findings.count()):
                item = window.ai_panel.findings.item(index)
                from PySide6.QtCore import Qt
                if item.data(Qt.ItemDataRole.UserRole)["id"] == finding["id"]:
                    window.ai_panel.findings.setCurrentItem(item)
                    break
            assert window.ai_panel.evidence.topLevelItemCount() > 0, "Resolved evidence was not displayed"
            window.ai_panel.evidence_toggle.setChecked(True)
            app.processEvents()
            window.grab().save(str(destination / "charon-ai.png"))
            window.resize(1024, 720)
            app.processEvents()
            window.grab().save(str(destination / "charon-compact.png"))
            window.ai_panel.open_evidence(1)
            assert window.tabs.currentIndex() == 1
            assert window.current_address in finding["addresses"], "Evidence navigation selected the wrong address"
            window.project.save(destination / "ai-sample.acheron")
            assert Project.load(destination / "ai-sample.acheron").hypotheses == window.project.hypotheses
            assert Project.load(destination / 'ai-sample.acheron').annotations == window.project.annotations
            write_report(window.project, destination / 'ai-explanation.txt', ReportOptions(finding['function_address'], code=False, metadata=False))
            exported = (destination / 'ai-explanation.txt').read_text(encoding='utf-8')
            assert result['summary'] in exported and 'HYPOTHESIZED' in exported
            (destination / "findings.json").write_text(json.dumps(window.project.hypotheses, indent=2), encoding="utf-8")
            finish(True, {"model": window.local_model, "backend": window.engine.acceleration,
                          "findings": len(window.project.hypotheses), "checks": ["real-packaged-local-inference", "windowed-worker-pipes", "bundled-model",
                          "structured-findings", "hypothesis-isolation", "answer-overview", "source-evidence-navigation", "simplified-mode", "compact-layout", "text-report", "answer-persistence", "save-reload"]})
        except Exception as exc:
            finish(False, {"error": str(exc) or repr(exc)})

    window.projectLoaded.connect(loaded)
    window.ai_job.result.connect(result_ready)
    window.ai_job.failed.connect(lambda message: finish(False, {"error": message}))
    window.verify_job.failed.connect(lambda message: finish(False, {"error": message}))
    window.engine.failed.connect(lambda message: finish(False, {"error": message}))
    window.analysisFailed.connect(lambda message: finish(False, {"error": message}))
    QTimer.singleShot(240000, lambda: finish(False, {"error": "Packaged AI check timed out"}))
    QTimer.singleShot(0, window.commands['sample_x86'].trigger if x86 else window.welcome_sample.click)


def run_file_smoke(app, window, destination: Path, with_ai=False):
    """Exercise real worker, file UI, background report download and optional AI."""
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / 'example-config.json'
    source.write_text('{\n  "project": "Example file inspection",\n  "enabled": true,\n  "retries": 3\n}\n', encoding='utf-8')
    state = {'finished': False}

    def finish(success, detail):
        if state['finished']:
            return
        state['finished'] = True
        (destination / 'report.json').write_text(json.dumps({'success': success, **detail}, indent=2), encoding='utf-8')
        window.close()
        app.exit(0 if success else 2)

    def downloaded():
        try:
            assert 'Example file inspection' in (destination / 'download.txt').read_text(encoding='utf-8')
            window.download_dialog.close()
            if with_ai:
                window.tabs.setCurrentIndex(window.investigation_index)
                window.ai_panel.run.click()
            else:
                finish(True, {'checks': ['any-file-worker', 'text-preview', 'file-offset-navigation', 'background-download', 'compact-layout']})
        except Exception as exc:
            finish(False, {'error': str(exc) or repr(exc)})

    def loaded(project):
        try:
            state['snapshot'] = project.snapshot()
            assert project.image['kind'] == 'file' and not project.functions
            assert 'Example file inspection' in window.file_view.text.toPlainText()
            window.file_view.open_offset(2)
            assert window.file_view.selected_offset == 2
            window.file_view.views.setCurrentIndex(1)
            for width, height in ((1440, 900), (1024, 720)):
                window.resize(width, height)
                app.processEvents()
                window.grab().save(str(destination / f'file-{width}.png'))
            window.download_button.click()
            window.download_dialog.save_to(destination / 'download.txt')
            window.download_dialog.writer.finished.connect(downloaded)
        except Exception as exc:
            finish(False, {'error': str(exc) or repr(exc)})

    def explained(result):
        try:
            assert window.project.snapshot() == state['snapshot']
            assert window.project.annotations and result['summary']
            assert all(f.get('source_kind') == 'file_offset' for f in result['findings'])
            app.processEvents()
            window.grab().save(str(destination / 'file-ai.png'))
            write_report(window.project, destination / 'ai-file-report.txt')
            assert result['summary'] in (destination / 'ai-file-report.txt').read_text(encoding='utf-8')
            window.project.save(destination / 'file.acheron')
            assert Project.load(destination / 'file.acheron').annotations == window.project.annotations
            finish(True, {'model': window.local_model, 'findings': len(result['findings']), 'checks': ['any-file-worker', 'text-preview', 'file-offset-navigation', 'background-download', 'real-local-file-ai', 'snapshot-isolation', 'report-export', 'save-reload']})
        except Exception as exc:
            finish(False, {'error': str(exc) or repr(exc)})

    window.projectLoaded.connect(loaded)
    window.analysisFailed.connect(lambda error: finish(False, {'error': error}))
    if with_ai:
        window.ai_job.result.connect(explained)
        window.ai_job.failed.connect(lambda error: finish(False, {'error': error}))
        window.engine.failed.connect(lambda error: finish(False, {'error': error}))
        window.verify_job.failed.connect(lambda error: finish(False, {'error': error}))
    QTimer.singleShot(180000, lambda: finish(False, {'error': 'File check timed out'}))
    QTimer.singleShot(0, lambda: window.open_path(source))
