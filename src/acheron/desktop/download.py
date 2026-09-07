"""A single readable-file download, with bounded preview and background writing."""
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from ..report import ReportOptions, ReportCancelled, report_chunks, write_report
from .primitives import button, label


class ReportWriter(QThread):
    saved = Signal(str)
    failed = Signal(str)

    def __init__(self, project, destination, options, parent):
        super().__init__(parent)
        self.project, self.destination, self.options = project, destination, options

    def run(self):
        try:
            write_report(self.project, self.destination, self.options, self.isInterruptionRequested)
            self.saved.emit(str(self.destination))
        except ReportCancelled:
            self.failed.emit('Download cancelled. No incomplete report was kept.')
        except Exception as exc:
            self.failed.emit(f'Could not save this file: {exc}. Choose a new name or a writable folder.')


class DownloadDialog(QDialog):
    def __init__(self, window, selected=False, ai_only=False):
        super().__init__(window)
        self.project = window.project
        self.function_address = window.current_function.address if window.current_function else None
        self.writer = None
        self.saved_path = None
        self.setWindowTitle('Download results')
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(label('Save your results as one text file', 'functionTitle', wrap=True))
        layout.addWidget(label('Opens in Notepad or any text editor. Choose what to include, then pick where to save it.', 'muted', wrap=True))
        row = QHBoxLayout()
        row.addWidget(label('Include results from'))
        self.scope = QComboBox()
        self.scope.setAccessibleName('Report scope')
        self.scope.addItem('Whole file — all discovered functions', None)
        if self.function_address is not None:
            self.scope.addItem(f'This section — {window.current_function.name}', self.function_address)
        self.scope.setCurrentIndex(1 if selected and self.function_address is not None else 0)
        row.addWidget(self.scope, 1)
        layout.addLayout(row)
        choices = QHBoxLayout()
        self.code = QCheckBox('Recovered code')
        self.metadata = QCheckBox('Extracted file details')
        self.ai = QCheckBox('AI explanations')
        self.instructions = QCheckBox('Original instructions')
        if self.project.image.get('kind') == 'file':
            self.code.setText('Text and strings')
            self.metadata.setText('File details / archive list')
            self.instructions.setText('Raw byte preview')
        self.controls = [self.scope, self.code, self.metadata, self.ai, self.instructions]
        for control in self.controls[1:]:
            control.setChecked(control != self.instructions and (not ai_only or control == self.ai))
            choices.addWidget(control)
            control.toggled.connect(self.update_preview)
        layout.addLayout(choices)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName('Text report preview')
        layout.addWidget(self.preview, 1)
        self.status = label('', 'muted', wrap=True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.save_button = button('Save text file…', self.choose_destination, primary=True)
        self.open_button = button('Open saved file', self.open_saved)
        self.open_button.hide()
        self.close_button = button('Close', self.reject)
        actions.addWidget(self.save_button)
        actions.addWidget(self.open_button)
        actions.addStretch()
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.scope.currentIndexChanged.connect(self.update_preview)
        self.update_preview()

    def options(self):
        return ReportOptions(self.scope.currentData(), self.code.isChecked(), self.metadata.isChecked(), self.ai.isChecked(), self.instructions.isChecked())

    def update_preview(self):
        if not hasattr(self, 'preview'):
            return
        chunks, length = [], 0
        for chunk in report_chunks(self.project, self.options()):
            chunks.append(chunk[:max(0, 16000 - length)])
            length += len(chunk)
            if length >= 16000:
                chunks.append('\n[Preview shortened. The saved file includes the full report.]')
                break
        self.preview.setPlainText(''.join(chunks))
        self.save_button.setEnabled(any(c.isChecked() for c in self.controls[1:]))
        self.status.setText('Text file (.txt) · No extra software required')

    def choose_destination(self):
        suffix = f'-{self.scope.currentData():x}' if self.scope.currentData() is not None else ''
        name = Path(self.project.binary['filename']).stem + suffix + '-results.txt'
        path, _ = QFileDialog.getSaveFileName(self, 'Save results as a text file', name, 'Text file (*.txt)', options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            path = Path(path)
            if path.suffix.lower() != '.txt':
                path = path.with_name(path.name + '.txt')
            self.save_to(path)

    def save_to(self, path):
        if self.writer and self.writer.isRunning():
            return
        self.writer = ReportWriter(self.project, path, self.options(), self)
        for control in [*self.controls, self.save_button, self.open_button]:
            control.setEnabled(False)
        self.close_button.setText('Cancel download')
        self.status.setText('Writing your text file…')
        self.writer.saved.connect(self.saved)
        self.writer.failed.connect(self.status.setText)
        self.writer.finished.connect(self.finished_writing)
        self.writer.start()

    def saved(self, path):
        self.saved_path = Path(path)
        self.status.setText(f'Saved: {path}')
        self.open_button.show()

    def finished_writing(self):
        for control in [*self.controls, self.save_button, self.open_button]:
            control.setEnabled(True)
        self.close_button.setText('Close')

    def open_saved(self):
        if self.saved_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.saved_path.resolve())))

    def reject(self):
        if self.writer and self.writer.isRunning():
            self.writer.requestInterruption()
            self.status.setText('Stopping the download…')
            return
        super().reject()

    def closeEvent(self, event):
        if self.writer and self.writer.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
