"""GUI-owned workers and inference server. No target program is executed."""
import json
from pathlib import Path
import secrets
import socket
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from ..ai.catalog import installed, model_path


class AIJob(QObject):
    progress = Signal(object)
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.buffer = b""
        self.completed = False
        self.cancelled = False

    def start(self, request):
        if self.process:
            raise ValueError("An AI operation is already running")
        self.buffer = b""
        self.completed = self.cancelled = False
        process = self.process = QProcess(self)
        if getattr(sys, "frozen", False):
            arguments = ["--ai-worker"]
        else:
            arguments = ["-m", "acheron.ai.worker"]
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("PYTHONPATH", str(Path(__file__).resolve().parents[2]))
            environment.insert("PYTHONDONTWRITEBYTECODE", "1")
            process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._read)
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self._done)
        process.errorOccurred.connect(self._error)
        process.start(sys.executable, arguments)
        process.write(json.dumps(request).encode("utf-8"))
        process.closeWriteChannel()

    def _read(self):
        if not self.process:
            return
        self.buffer += bytes(self.process.readAllStandardOutput())
        if len(self.buffer) > 2_000_000:
            self.cancel()
            self.failed.emit("AI output exceeded its size limit.")
            return
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if self.cancelled:
                continue
            if record.get("type") == "progress":
                self.progress.emit(record)
            elif record.get("type") == "result":
                self.completed = True
                self.result.emit(record["result"])
            elif record.get("type") == "error":
                self.completed = True
                self.failed.emit(record["message"])

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.process:
            self.completed = True
            self.failed.emit("Unable to start the AI worker.")
            self._done(-1, None)

    def _done(self, code, status):
        if not self.process:
            return
        self._read()
        process, self.process = self.process, None
        process.deleteLater()
        if not self.completed and not self.cancelled:
            self.failed.emit(f"The AI worker stopped before returning a result (code {code}).")
        self.finished.emit()

    def cancel(self):
        self.cancelled = True
        if self.process:
            self.process.kill()
            self.process.waitForFinished(3000)


class LocalEngine(QObject):
    changed = Signal(str)
    ready = Signal()
    failed = Signal(str)

    def __init__(self, data_dir, runtime_root, parent=None):
        super().__init__(parent)
        self.data_dir, self.runtime_root = Path(data_dir), Path(runtime_root)
        self.process = None
        self.model_id = None
        self.endpoint = ""
        self.key = ""
        self.is_ready = False
        self.attempts = 0
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._poll)

    def start(self, model_id, acceleration="vulkan"):
        if self.is_ready and self.model_id == model_id and self.acceleration == acceleration:
            self.ready.emit()
            return
        self.stop()
        if not installed(self.data_dir, model_id):
            self.failed.emit("Download and verify this model in AI setup first.")
            return
        executable = self.runtime_root / acceleration / "llama-server.exe"
        if acceleration not in ("vulkan", "cpu") or not executable.is_file():
            self.failed.emit("The local AI runtime is missing. Extract the complete CHARON ZIP, including runtime/.")
            return
        try:
            with socket.socket() as port_socket:
                port_socket.bind(("127.0.0.1", 0))
                port = port_socket.getsockname()[1]
        except OSError:
            self.failed.emit("Windows could not open the local model connection. Allow local connections for CHARON and retry.")
            return
        self.endpoint = f"http://127.0.0.1:{port}"
        self.key = secrets.token_urlsafe(32)
        self.model_id, self.acceleration = model_id, acceleration
        process = self.process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        for name in environment.keys():
            if name.startswith("LLAMA_"):
                environment.remove(name)
        environment.insert("LLAMA_API_KEY", self.key)
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(str(executable.parent))
        process.readyReadStandardOutput.connect(lambda: process.readAllStandardOutput())
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.finished.connect(self._exited)
        process.errorOccurred.connect(self._error)
        self.attempts = 0
        arguments = ["--model", str(model_path(self.data_dir, model_id).resolve()), "--alias", model_id,
                     "--host", "127.0.0.1", "--port", str(port), "--ctx-size", "8192", "--parallel", "1",
                     "--n-gpu-layers", "99" if acceleration == "vulkan" else "0", "--no-webui"]
        process.start(str(executable.resolve()), arguments)
        self.changed.emit("Loading local model into memory…")
        self.timer.start()

    def _poll(self):
        if self.reply or not self.process:
            return
        self.attempts += 1
        if self.attempts > 240:
            self.stop()
            self.failed.emit("Model loading timed out. Try CPU mode or a smaller model in AI setup.")
            return
        request = QNetworkRequest(QUrl(self.endpoint + "/health"))
        request.setTransferTimeout(2000)
        self.reply = self.network.get(request)
        self.reply.finished.connect(self._health)

    def _health(self):
        reply, self.reply = self.reply, None
        if reply is None:
            return
        code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        reply.deleteLater()
        if code == 200 and self.process:
            self.is_ready = True
            self.timer.stop()
            self.changed.emit(f"Local model ready · {self.acceleration.upper()}")
            self.ready.emit()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.stop()
            self.failed.emit("Local engine could not start. Extract all runtime files or select CPU in AI setup.")

    def _exited(self, code, status):
        self.stop()
        self.failed.emit(f"Local engine stopped (code {code}). Try CPU mode or a smaller model in AI setup.")

    def stop(self):
        self.timer.stop()
        if self.reply:
            self.reply.blockSignals(True)
            self.reply.abort()
            self.reply.deleteLater()
            self.reply = None
        if self.process:
            process, self.process = self.process, None
            process.blockSignals(True)
            process.kill()
            process.waitForFinished(3000)
            process.deleteLater()
        self.is_ready = False
        self.model_id = None
        self.key = ""
        self.changed.emit("Local model stopped")
