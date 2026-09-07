"""ACHERON // CHARON: findings, explicit evidence and real local/cloud inference."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QElapsedTimer, QTimer
from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QSplitter, QTreeWidgetItem, QVBoxLayout, QWidget

from ..ai.catalog import DEFAULT_MODEL, MODELS, installed, model_path
from ..ai.evidence import SYSTEM, build_context, prompt
from .ai_jobs import AIJob, LocalEngine
from .ai_setup import ModelSetup
from .primitives import button, label, tree, disclosure
from .window import MainWindow


class InvestigationPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.current = None
        self.file_scope = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(7)
        self.heading = QWidget()
        title = QHBoxLayout(self.heading)
        title.setContentsMargins(0, 0, 0, 0)
        title.addWidget(label("Investigate with CHARON", "functionTitle"), 1)
        title.addWidget(button("AI setup", window.show_ai_setup))
        layout.addWidget(self.heading)
        self.provider_status = label("", "muted", wrap=True)
        layout.addWidget(self.provider_status)
        self.presets = QComboBox()
        self.presets.setAccessibleName("Choose what to ask the AI")
        for title, question in (("What does this section do?", "Explain what this function does and what is uncertain."),
                                ("Explain it step by step", "Walk through this function step by step in plain language. Explain branches and calls, and state what is unknown."),
                                ("What should I check?", "Which parts of this function need a closer look? Give evidence-linked checks and explain what remains uncertain."),
                                ("Ask my own question…", None)):
            self.presets.addItem(title, question)
        layout.addWidget(self.presets)
        self.question = QLineEdit()
        self.question.setText("Explain what this function does and what is uncertain.")
        self.question.setMaxLength(1000)
        self.question.setAccessibleName("Investigation question")
        self.question.setPlaceholderText("Ask about the selected function…")
        layout.addWidget(self.question)
        self.question.hide()
        self.custom_question = ""
        self.presets.currentIndexChanged.connect(self.select_question)
        row = QHBoxLayout()
        self.run = button("Explain", window.investigate, primary=True)
        self.preview = button("What gets sent?", self.preview_context)
        self.ask_other = button("Ask something else", self.toggle_question)
        self.cancel = button("Stop", window.cancel_investigation)
        self.cancel.hide()
        row.addWidget(self.run)
        row.addWidget(self.preview)
        self.ask_other.hide()
        row.addWidget(self.cancel)
        self.save_answer = button("Save explanation…", lambda: window.download_results(selected=True, ai_only=True))
        row.addWidget(self.save_answer)
        row.addStretch()
        self.elapsed = QElapsedTimer()
        self.elapsed_label = label("", "muted")
        row.addWidget(self.elapsed_label)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(lambda: self.elapsed_label.setText(f"{self.elapsed.elapsed() // 1000}s"))
        layout.addLayout(row)
        self.status = label("Open a binary or explore the sample to start.", "muted", wrap=True)
        layout.addWidget(self.status)
        self.scope = label("AI output is HYPOTHESIZED. Linked addresses verify the source of evidence; they do not prove the model's interpretation.", "notice", wrap=True)
        layout.addWidget(self.scope)
        self.claim_status = label("", "confidence", wrap=True)
        layout.addWidget(self.claim_status)
        splitter = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.findings = QListWidget()
        self.findings.setAccessibleName("AI findings for the selected function")
        self.findings.setMinimumWidth(120)
        self.findings.setMaximumWidth(190)
        self.findings.currentItemChanged.connect(self.select_finding)
        top_layout.addWidget(self.findings)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("explanation")
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.details.setPlaceholderText("1. Choose a question above.\n2. Click Explain.\n\nYour answer will appear here. The local model loads automatically on first use.")
        top_layout.addWidget(self.details, 1)
        splitter.addWidget(top)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 4, 0, 0)
        self.source_heading = label("Instructions behind the selected hypothesis", "section")
        bottom_layout.addWidget(self.source_heading)
        self.evidence = tree(["ID", "Address", "Instruction"])
        self.evidence.setColumnWidth(0, 50)
        self.evidence.setColumnWidth(1, 95)
        self.evidence.itemActivated.connect(lambda item, column: self.open_evidence(0))
        bottom_layout.addWidget(self.evidence)
        actions = QHBoxLayout()
        self.source_buttons = []
        for text, index in (("Open recovered code", 0), ("AIR", 2), ("Assembly", 1)):
            control = button(text, lambda checked=False, i=index: self.open_evidence(i))
            self.source_buttons.append(control)
            actions.addWidget(control)
        self.review = QComboBox()
        self.review.addItems(["Unreviewed", "Useful hypothesis", "Rejected"])
        self.review.currentIndexChanged.connect(self.review_finding)
        actions.addWidget(self.review)
        bottom_layout.addLayout(actions)
        splitter.addWidget(bottom)
        self.evidence_panel = bottom
        self.evidence_toggle = disclosure("Supporting code and review", bottom)
        layout.addWidget(self.evidence_toggle)
        splitter.setSizes([360, 200])
        layout.addWidget(splitter, 1)
        self.refresh_status()

    def select_question(self, index):
        if self.question.isVisible():
            self.custom_question = self.question.text()
        preset = self.presets.currentData()
        self.question.setVisible(preset is None)
        self.question.setText(self.custom_question if preset is None else preset)
        if preset is None:
            self.question.setFocus()
        self.refresh_status()

    def refresh_status(self):
        window = self.window
        file_scope = bool(window.project and window.project.image.get('kind') == 'file')
        if file_scope != self.file_scope:
            self.file_scope = file_scope
            for index, (title, question) in enumerate((('What is in this file?', 'Explain the extracted contents of this file and what is uncertain.'),
                                                      ('Summarize the contents', 'Summarize the visible file content in plain language. State the limits of this excerpt.'),
                                                      ('What should I check?', 'What should I examine next in this file? Cite visible evidence and avoid guessing missing content.')) if file_scope else
                                                     (('What does this section do?', 'Explain what this function does and what is uncertain.'),
                                                      ('Explain it step by step', 'Walk through this function step by step in plain language. Explain branches and calls, and state what is unknown.'),
                                                      ('What should I check?', 'Which parts of this function need a closer look? Give evidence-linked checks and explain what remains uncertain.'))):
                self.presets.setItemText(index, title)
                self.presets.setItemData(index, question)
            if self.presets.currentData() is not None:
                self.question.setText(self.presets.currentData())
            self.evidence.setHeaderLabels(['ID', 'File offset' if file_scope else 'Address', 'Extracted content' if file_scope else 'Instruction'])
            self.source_buttons[0].setText('Open file bytes' if file_scope else 'Open recovered code')
            self.source_heading.setText('Extracted content behind the selected hypothesis' if file_scope else 'Instructions behind the selected hypothesis')
        self.heading.hide()
        self.scope.setText("HYPOTHESIZED · AI can be wrong. Supporting content lets you check its claims.")
        self.scope.setToolTip("Linked addresses verify the source of evidence; they do not prove the model's interpretation.")
        if window.provider == "local":
            name = MODELS[window.local_model]["name"]
            path = model_path(window.data_dir, window.local_model)
            available = path.is_file() and path.stat().st_size == MODELS[window.local_model]['size']
            state = "ready" if window.engine.is_ready and window.engine.model_id == window.local_model else "loads automatically when you click Explain" if available else "choose Download and use in AI settings"
            self.provider_status.setText(f"On this PC · {name}\n{state}")
            self.provider_status.setToolTip("The selected content stays on this PC.")
            self.run.setText("Explain")
        else:
            self.provider_status.setText(f"OPENAI · {window.cloud_model or 'choose a model in AI settings'}\nSends the previewed content to api.openai.com. API usage is billed by your provider.")
            self.run.setText("Send to OpenAI & explain")
        self.run.setEnabled(window.project is not None and (window.current_function is not None or file_scope) and not window.ai_busy and window.worker is None)
        self.preview.setEnabled(window.current_function is not None or file_scope)
        self.cancel.setVisible(window.ai_busy)
        self.presets.setEnabled(not window.ai_busy)
        self.question.setEnabled(not window.ai_busy)
        self.save_answer.setEnabled(window.project is not None and not window.ai_busy)
        for control in self.source_buttons[1:]:
            control.setVisible(not window.simple_mode and not file_scope)
        if window.ai_busy and not self.timer.isActive():
            self.elapsed.start()
            self.elapsed_label.setText("0s")
            self.timer.start()
        elif not window.ai_busy:
            self.timer.stop()

    def toggle_question(self):
        self.presets.setCurrentIndex(self.presets.count() - 1)

    def refresh_findings(self):
        window = self.window
        previous = self.current.get("id") if self.current else None
        self.findings.clear()
        self.details.clear()
        self.evidence.clear()
        self.current = None
        self.claim_status.clear()
        self.evidence_toggle.setChecked(False)
        self.evidence_toggle.setEnabled(False)
        self.evidence_toggle.setText("Supporting content and review")
        if window.project and (window.current_function or window.project.image.get('kind') == 'file'):
            address = window.current_function.address if window.current_function else None
            relevant = [f for f in window.project.hypotheses if f.get("function_address") == address and f.get("binary_sha256") == window.project.binary["sha256"]]
            runs = [a['value'] for a in window.project.annotations if a.get('kind') == 'charon-run' and isinstance(a.get('value'), dict)
                    and a['value'].get('function_address') == address and a['value'].get('binary_sha256') == window.project.binary['sha256']]
            if relevant or runs:
                answer = runs[-1] if runs else relevant[-1]
                item = QListWidgetItem("Answer overview")
                item.setData(Qt.ItemDataRole.UserRole, {**answer, "overview": True, "id": "overview", "parts": [f for f in relevant if f.get('run_id') == answer.get('run_id')]})
                self.findings.addItem(item)
            for finding in window.project.hypotheses:
                if finding.get("function_address") == address and finding.get("binary_sha256") == window.project.binary["sha256"]:
                    title = str(finding.get("title", "Saved hypothesis"))[:300]
                    item = QListWidgetItem(title)
                    item.setData(Qt.ItemDataRole.UserRole, finding)
                    item.setToolTip("HYPOTHESIZED · " + str(finding.get("model", "Unknown model")))
                    self.findings.addItem(item)
                    if finding.get("id") == previous:
                        self.findings.setCurrentItem(item)
            if self.findings.currentRow() < 0 and self.findings.count():
                self.findings.setCurrentRow(0)
            if not self.findings.count():
                self.status.setText("Choose a question, then click Explain. AI reads a bounded excerpt of the selected content.")
            elif not window.ai_busy:
                self.status.setText(f"{len(relevant)} hypotheses for this section. Save explanation to keep a readable copy.")
        self.refresh_status()

    def select_finding(self, item, previous):
        if item is None:
            self.current = None
            return
        self.current = finding = item.data(Qt.ItemDataRole.UserRole)
        self.evidence.clear()
        if finding.get('overview'):
            self.claim_status.setText("Answer overview · HYPOTHESIZED, not verified")
            parts = [finding.get('summary', '')]
            for part in finding.get('parts', []):
                parts.append(f"{part.get('title', '')}\n{part.get('suggestion', '')}\nModel confidence: {part.get('confidence_label', 'unknown')} (uncalibrated)")
            parts.append("What is uncertain\n" + "\n".join('• ' + str(s) for s in finding.get('limitations', [])))
            self.details.setPlainText('\n\n'.join(parts))
            self.evidence_toggle.setChecked(False)
            self.evidence_toggle.setEnabled(False)
            self.evidence_toggle.setText("Select a hypothesis on the left to see supporting content")
            return
        self.evidence_toggle.setEnabled(True)
        self.evidence_toggle.setText("Supporting content and review")
        validation = "Evidence IDs resolved · interpretation not verified" if finding.get("validation_status") == "references_checked_only" else "Missing or invalid evidence references · review required"
        self.claim_status.setText(f"HYPOTHESIZED · Model confidence: {finding.get('confidence_label', 'unknown')} (uncalibrated)\n{validation}")
        limits = finding.get("limitations", [])
        if finding.get("unresolved_evidence"):
            limits = [*limits, "Unresolved model citations: " + ", ".join(finding["unresolved_evidence"])]
        self.details.setPlainText(f"{finding.get('title', '')}\n\n{finding.get('suggestion', '')}\n\n"
                                  + "LIMITS\n" + "\n".join("• " + str(value) for value in limits)
                                  + f"\n\nModel: {finding.get('model', 'unknown')} · {finding.get('provider', 'unknown')}")
        self.evidence.clear()
        for row in finding.get("evidence", []):
            item = QTreeWidgetItem([row["id"], row["address"], row["assembly"]])
            item.setData(0, Qt.ItemDataRole.UserRole, int(row["address"], 16))
            item.setToolTip(2, row["assembly"])
            self.evidence.addTopLevelItem(item)
        if self.evidence.topLevelItemCount():
            self.evidence.setCurrentItem(self.evidence.topLevelItem(0))
        self.review.blockSignals(True)
        self.review.setCurrentIndex({"unreviewed": 0, "useful": 1, "rejected": 2}.get(finding.get("review"), 0))
        self.review.blockSignals(False)

    def review_finding(self, index):
        if self.current and self.window.project:
            for finding in self.window.project.hypotheses:
                if finding.get("id") == self.current.get("id"):
                    finding["review"] = ("unreviewed", "useful", "rejected")[index]
                    self.current["review"] = finding["review"]
                    self.status.setText("Review saved in this session. Save project to preserve it. The finding remains a hypothesis.")
                    break

    def open_evidence(self, index):
        item = self.evidence.currentItem()
        if not item:
            self.status.setText("This finding has no valid instruction reference to open.")
            return
        address = item.data(0, Qt.ItemDataRole.UserRole)
        if self.window.project.image.get('kind') == 'file':
            self.window.file_view.open_offset(address)
            return
        previous = self.window.location()
        history_size = len(self.window.history)
        self.window.navigate(address)
        if index in (1, 2) and self.window.simple_mode:
            self.window.set_simple_mode(False)
        self.window.tabs.setCurrentIndex(index)
        if previous and len(self.window.history) == history_size and previous.view != index:
            self.window.history.append(previous)
            self.window.forward_history.clear()
            self.window.back_button.setEnabled(True)
            self.window.forward_button.setEnabled(False)
            self.window._update_commands()
        self.window.inspector_action.setChecked(True)

    def preview_context(self):
        if not self.window.project or (not self.window.current_function and self.window.project.image.get('kind') != 'file'):
            return
        context = build_context(self.window.project, self.window.current_function, self.question.text(), self.window.simple_mode)
        dialog = QDialog(self)
        dialog.setWindowTitle("CHARON · Exact model input")
        dialog.resize(850, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("This exact content snapshot and instruction are sent when you click Explain. Your API key and local file path are excluded; extracted content may itself contain sensitive text.", "muted", wrap=True))
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(SYSTEM + "\n\n" + json.dumps(context, indent=2))
        layout.addWidget(text)
        layout.addWidget(button("Close", dialog.close))
        dialog.show()
        self.preview_dialog = dialog

    def export_findings(self):
        if not self.window.project:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CHARON findings", "charon-findings.json", "JSON (*.json)")
        if path:
            try:
                with Path(path).open("x", encoding="utf-8") as output:
                    json.dump({"creator": "cirrune", "product": "ACHERON // CHARON", "binary_sha256": self.window.project.binary["sha256"],
                               "hypotheses": self.window.project.hypotheses}, output, indent=2)
                self.status.setText("Findings exported with evidence and model provenance.")
            except OSError as exc:
                self.status.setText(str(exc))


class CharonWindow(MainWindow):
    def __init__(self, data_dir, runtime_root=None):
        self.data_dir = Path(data_dir)
        self.provider = "local"
        self.local_model = DEFAULT_MODEL
        self.cloud_model = ""
        self.api_key = ""
        self.acceleration = "vulkan"
        self.ai_busy = False
        self.pending = None
        self.origin_project = None
        try:
            config = json.loads((self.data_dir / "ai-settings.json").read_text(encoding="utf-8"))
            self.local_model = config.get("local_model") if config.get("local_model") in MODELS else DEFAULT_MODEL
            self.cloud_model = str(config.get("cloud_model", ""))[:200]
            self.acceleration = "cpu" if config.get("acceleration") == "cpu" else "vulkan"
        except (OSError, ValueError):
            pass
        super().__init__(edition="charon", settings_path=self.data_dir / "ui-settings.json")
        if runtime_root is None:
            runtime_root = Path(sys.executable).parent / "runtime" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3] / "work/ai-assets"
        self.engine = LocalEngine(self.data_dir, runtime_root, self)
        self.ai_job = AIJob(self)
        self.verify_job = AIJob(self)
        self.ai_panel = InvestigationPanel(self)
        self.investigation_index = self.tabs.addTab(self.ai_panel, "AI help")
        self.ai_setup_button = button("AI settings", self.show_ai_setup)
        self.toolbar_row.insertWidget(self.toolbar_row.indexOf(self.export_button), self.ai_setup_button)
        self.ai_setup = None
        self.ai_job.result.connect(self.ai_result)
        self.ai_job.failed.connect(self.ai_failure)
        self.ai_job.finished.connect(self.ai_finished)
        self.verify_job.result.connect(self.verified_model)
        self.verify_job.failed.connect(self.ai_failure)
        self.engine.ready.connect(self.engine_ready)
        self.engine.failed.connect(self.ai_failure)
        self.engine.changed.connect(lambda message: self.ai_panel.refresh_status())
        self.functionSelected.connect(lambda function: self.ai_panel.refresh_findings())
        self.projectLoaded.connect(self.new_project)
        self.simpleModeChanged.connect(lambda enabled: self.ai_panel.refresh_status())
        self.tabs.setCurrentIndex(self.overview_index if self.simple_mode else self.investigation_index)

    def show_ai_setup(self):
        if self.ai_setup is None:
            self.ai_setup = ModelSetup(self)
        self.ai_setup.show()
        self.ai_setup.raise_()
        self.ai_setup.activateWindow()

    def save_ai_settings(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            (self.data_dir / "ai-settings.json").write_text(json.dumps({"local_model": self.local_model, "cloud_model": self.cloud_model, "acceleration": self.acceleration}), encoding="utf-8")
        except OSError:
            self.ai_panel.status.setText("Settings remain in this session; the app folder is not writable.")

    def new_project(self, project):
        self.cancel_investigation()
        self.ai_panel.refresh_findings()
        self.tabs.setCurrentIndex(self.file_index if project.image.get('kind') == 'file' else self.overview_index if self.simple_mode else self.investigation_index)

    def investigate(self):
        if not self.project or (not self.current_function and self.project.image.get('kind') != 'file') or self.ai_busy or self.worker:
            return
        if not self.ai_panel.question.text().strip():
            self.ai_panel.status.setText("Type your question first, or choose one from the list.")
            self.ai_panel.question.setFocus()
            return
        if self.provider == "openai" and (not self.api_key or not self.cloud_model):
            self.show_ai_setup()
            return
        path = model_path(self.data_dir, self.local_model)
        needs_verification = self.provider == "local" and not installed(self.data_dir, self.local_model)
        if needs_verification and not (path.is_file() and path.stat().st_size == MODELS[self.local_model]["size"]):
            self.show_ai_setup()
            self.ai_panel.status.setText("Choose Download and use in AI settings. Then return here and click Explain.")
            return
        context = build_context(self.project, self.current_function, self.ai_panel.question.text(), self.simple_mode)
        self.pending = {"operation": "investigate", "provider": self.provider, "model": self.local_model if self.provider == "local" else self.cloud_model, "context": context}
        self.origin_project = self.project
        self.ai_busy = True
        self.ai_panel.refresh_status()
        self.ai_panel.status.setText("Loading local model…" if self.provider == "local" else "Investigating the selected excerpt…")
        if self.provider == "local":
            if needs_verification:
                self.ai_panel.status.setText("Verifying the bundled model before first use…")
                self.verify_job.start({"operation": "download", "model_id": self.local_model, "data_dir": str(self.data_dir)})
            else:
                self.engine.start(self.local_model, self.acceleration)
        else:
            self.pending["key"] = self.api_key
            self.ai_job.start(self.pending)
            self.pending = None

    def verified_model(self, path):
        if self.pending and self.ai_busy:
            self.engine.start(self.pending["model"], self.acceleration)

    def engine_ready(self):
        self.ai_panel.refresh_status()
        if self.pending and self.pending["provider"] == "local":
            self.pending.update(endpoint=self.engine.endpoint, key=self.engine.key)
            self.ai_panel.status.setText("Reading the excerpt and generating evidence-linked findings…")
            self.ai_job.start(self.pending)
            self.pending = None

    def ai_result(self, result):
        if self.project is not self.origin_project or not self.ai_busy:
            return
        self.project.hypotheses.extend(result["findings"])
        if 'run' in result:
            self.project.annotations.append({'address': result['run']['function_address'], 'kind': 'charon-run', 'value': result['run']})
        self.ai_panel.current = None
        self.ai_panel.refresh_findings()
        self.ai_panel.status.setText("Explanation ready. Read the overview, or select a hypothesis to inspect its supporting code.")

    def ai_failure(self, message):
        self.pending = None
        self.ai_busy = False
        self.ai_panel.status.setText(message)
        self.ai_panel.refresh_status()

    def ai_finished(self):
        self.ai_busy = False
        self.ai_panel.refresh_status()

    def cancel_investigation(self):
        was_busy = self.ai_busy
        self.pending = None
        self.ai_busy = False
        self.ai_job.cancel()
        self.verify_job.cancel()
        if not self.engine.is_ready and self.engine.process:
            self.engine.stop()
        if was_busy:
            self.ai_panel.status.setText("Investigation cancelled. Existing findings are preserved.")
        self.ai_panel.refresh_status()

    def _set_busy(self, busy):
        super()._set_busy(busy)
        if hasattr(self, "ai_panel"):
            self.ai_panel.refresh_status()

    def _tab_changed(self, index):
        super()._tab_changed(index)
        if hasattr(self, "investigation_index") and index == self.investigation_index:
            # The investigation includes its own evidence pane. Detailed source
            # inspection remains available through the evidence navigation.
            self.inspector_action.setChecked(False)

    def closeEvent(self, event):
        self.cancel_investigation()
        if self.ai_setup:
            self.ai_setup.shutdown()
        self.engine.stop()
        self.api_key = ""
        super().closeEvent(event)
