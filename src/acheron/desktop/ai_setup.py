"""Real model selection, installation and session-only cloud credentials."""
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QProgressBar, QTabWidget, QVBoxLayout, QWidget

from ..ai.catalog import MODELS, installed, model_path
from .ai_jobs import AIJob
from .primitives import button, label


class ModelSetup(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("CHARON · AI settings")
        self.resize(700, 510)
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(label("Choose your AI", "functionTitle", wrap=True))
        layout.addWidget(label("Local models run on this PC. Cloud models use your API account and receive only the excerpt you choose to send.", "muted", wrap=True))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        local = QWidget()
        local_layout = QVBoxLayout(local)
        self.local_models = QComboBox()
        for model_id, model in MODELS.items():
            self.local_models.addItem(f"{model['name']} · {model['role']} · {model['size'] / 1e9:.2f} GB", model_id)
        self.local_models.setCurrentIndex(self.local_models.findData(window.local_model))
        self.local_models.currentIndexChanged.connect(self.select_local)
        local_layout.addWidget(self.local_models)
        self.model_details = label("", "muted", wrap=True)
        local_layout.addWidget(self.model_details)
        controls = QHBoxLayout()
        self.download = button("Download and use", self.download_model, primary=True)
        self.load_model = button("Use local model", self.use_local)
        self.load_model.hide()
        self.stop_model = button("Unload model", self.window.engine.stop)
        controls.addWidget(self.download)
        controls.addWidget(self.stop_model)
        local_layout.addLayout(controls)
        engine_form = QFormLayout()
        self.acceleration = QComboBox()
        self.acceleration.addItem("GPU acceleration (Vulkan)", "vulkan")
        self.acceleration.addItem("CPU · widest compatibility", "cpu")
        self.acceleration.setCurrentIndex(self.acceleration.findData(window.acceleration))
        engine_form.addRow("Run on", self.acceleration)
        local_layout.addLayout(engine_form)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setMinimumHeight(12)
        self.progress.setTextVisible(False)
        self.progress.hide()
        local_layout.addWidget(self.progress)
        self.cancel_download = button("Pause download", self.pause_download)
        self.cancel_download.hide()
        local_layout.addWidget(self.cancel_download)
        self.download_status = label("", wrap=True)
        local_layout.addWidget(self.download_status)
        local_layout.addWidget(label("Weights: Qwen · Apache-2.0. Runtime: llama.cpp · MIT.\nEach official download is pinned to a revision and checked with SHA-256.", "muted", wrap=True))
        local_layout.addWidget(button("Open model folder", self.open_model_folder))
        local_layout.addStretch()
        self.tabs.addTab(local, "Local · no API key")
        cloud = QWidget()
        cloud_layout = QVBoxLayout(cloud)
        cloud_layout.addWidget(label("OpenAI · your own API account", "section"))
        cloud_layout.addWidget(label("API usage is billed by the provider. Your key stays in memory for this session and is never saved in the app, projects or exports.", "muted", wrap=True))
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Paste your OpenAI API key")
        self.key_input.setAccessibleName("OpenAI API key, kept only for this session")
        self.key_input.setText(window.api_key)
        cloud_layout.addWidget(self.key_input)
        self.refresh_cloud = button("Load my available models", self.load_cloud_models)
        cloud_layout.addWidget(self.refresh_cloud)
        self.cloud_models = QComboBox()
        self.cloud_models.setEditable(True)
        self.cloud_models.setPlaceholderText("Select a text model or enter its exact ID")
        if window.cloud_model:
            self.cloud_models.setEditText(window.cloud_model)
        cloud_layout.addWidget(self.cloud_models)
        self.cloud_status = label("Model availability comes from your account. Choose a model that supports Responses and structured text output.", "muted", wrap=True)
        cloud_layout.addWidget(self.cloud_status)
        cloud_layout.addWidget(button("Use OpenAI", self.use_cloud, primary=True))
        cloud_layout.addStretch()
        self.tabs.addTab(cloud, "Cloud · OpenAI")
        self.engine_status = label("", "muted", wrap=True)
        layout.addWidget(self.engine_status)
        layout.addWidget(button("Done", self.hide))
        self.job = AIJob(self)
        self.job.progress.connect(self.on_progress)
        self.job.result.connect(self.on_download)
        self.job.failed.connect(self.download_status.setText)
        self.job.finished.connect(self.download_finished)
        self.cloud_job = AIJob(self)
        self.cloud_job.result.connect(self.on_cloud_models)
        self.cloud_job.failed.connect(self.cloud_status.setText)
        self.cloud_job.finished.connect(lambda: self.refresh_cloud.setEnabled(True))
        window.engine.changed.connect(self.engine_status.setText)
        window.engine.failed.connect(self.engine_status.setText)
        self.select_local()

    def select_local(self):
        model_id = self.local_models.currentData()
        model = MODELS[model_id]
        ready = installed(self.window.data_dir, model_id)
        path = model_path(self.window.data_dir, model_id)
        available = path.is_file() and path.stat().st_size == model['size']
        partial = path.with_suffix(".part")
        state = "Ready to use" if ready else "Already included · will be verified before use" if available else "Partial download · ready to resume" if partial.exists() else "Download required"
        self.model_details.setText(f"{state}. Approximate memory budget: {model['ram_gb']} GB or more, depending on context and hardware.\n"
                                   "All choices are instruction-tuned coding models. The 1.5B model is faster but gives less reliable explanations than the larger choices.")
        self.download.setText("Use this model" if ready else "Verify and use" if available else "Resume and use" if partial.exists() else "Download and use")
        self.load_model.setEnabled(ready)

    def download_model(self):
        if self.job.process:
            return
        if installed(self.window.data_dir, self.local_models.currentData()):
            self.use_local()
            self.hide()
            return
        self.local_models.setEnabled(False)
        self.acceleration.setEnabled(False)
        self.download.setEnabled(False)
        self.load_model.setEnabled(False)
        self.progress.show()
        self.progress.setValue(0)
        self.cancel_download.show()
        self.download_status.setText("Connecting to the official model download…")
        self.job.start({"operation": "download", "model_id": self.local_models.currentData(), "data_dir": str(self.window.data_dir)})

    def on_progress(self, record):
        total = max(1, record.get("total", 1))
        done = record.get("completed", 0)
        self.progress.setValue(int(done * 100 / total))
        self.download_status.setText(f"{record['message']}  {done / 1e9:.2f} / {total / 1e9:.2f} GB")

    def on_download(self, path):
        self.download_status.setText("Model ready. Return to AI help and click Explain.")
        self.progress.setValue(100)
        self.use_local()
        self.hide()

    def download_finished(self):
        self.download.setEnabled(True)
        self.local_models.setEnabled(True)
        self.acceleration.setEnabled(True)
        self.cancel_download.hide()
        self.select_local()

    def pause_download(self):
        self.job.cancel()
        self.download_status.setText("Download paused. Resume and use continues from the saved partial file.")

    def use_local(self):
        self.window.local_model = self.local_models.currentData()
        self.window.acceleration = self.acceleration.currentData()
        self.window.provider = "local"
        self.window.save_ai_settings()
        self.window.ai_panel.refresh_status()
        self.window.engine.start(self.window.local_model, self.window.acceleration)

    def open_model_folder(self):
        try:
            folder = self.window.data_dir / "models"
            folder.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))
        except OSError as exc:
            self.download_status.setText(str(exc))

    def load_cloud_models(self):
        key = self.key_input.text().strip()
        if not key:
            self.cloud_status.setText("Enter your API key first.")
            return
        if self.cloud_job.process:
            return
        self.refresh_cloud.setEnabled(False)
        self.cloud_status.setText("Loading models from your account…")
        self.cloud_job.start({"operation": "models", "key": key})

    def on_cloud_models(self, models):
        candidates = [model for model in models if (model.startswith("gpt-") or model.startswith(("o1", "o3", "o4")))
                      and not any(word in model for word in ("audio", "realtime", "image", "transcribe", "tts", "search", "instruct"))]
        self.cloud_models.clear()
        self.cloud_models.addItems(candidates)
        self.cloud_models.setCurrentIndex(-1)
        self.cloud_status.setText(f"{len(candidates)} text-model candidates returned by your account. Select one; endpoint compatibility is checked when you run it.")

    def use_cloud(self):
        if not self.key_input.text().strip() or not self.cloud_models.currentText().strip():
            self.cloud_status.setText("Enter your key and select or enter a text-model ID.")
            return
        self.window.api_key = self.key_input.text().strip()
        self.window.cloud_model = self.cloud_models.currentText().strip()
        self.window.provider = "openai"
        self.window.save_ai_settings()
        self.window.ai_panel.refresh_status()
        self.cloud_status.setText("OpenAI selected. Return to AI help and click Send to OpenAI & explain.")

    def shutdown(self):
        self.job.cancel()
        self.cloud_job.cancel()
        self.key_input.clear()
