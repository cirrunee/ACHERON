"""Read-only text, strings, directory listing and byte inspection for any file."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPlainTextEdit, QTabWidget, QTreeWidgetItem, QVBoxLayout, QWidget
from .primitives import button, label, tree


class FileView(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.selected_offset = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        self.description = label('', 'muted', wrap=True)
        layout.addWidget(self.description)
        self.views = QTabWidget()
        self.summary = QPlainTextEdit()
        self.text = QPlainTextEdit()
        self.hex = QPlainTextEdit()
        for editor, name in ((self.summary, 'File details'), (self.text, 'Readable text')):
            editor.setReadOnly(True)
            editor.setAccessibleName(name)
            self.views.addTab(editor, name)
        self.strings = tree(['File offset', 'Encoding', 'Extracted string'])
        self.strings.setColumnWidth(0, 95)
        self.strings.setColumnWidth(1, 95)
        self.strings.itemActivated.connect(lambda item, column: self.open_offset(item.data(0, Qt.ItemDataRole.UserRole)))
        self.views.addTab(self.strings, 'Strings')
        self.entries = tree(['Name inside archive', 'Size (bytes)', 'Compressed', 'Encrypted'])
        self.entries.setColumnWidth(0, 340)
        self.views.addTab(self.entries, 'Archive contents')
        self.hex.setReadOnly(True)
        self.hex.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.hex.setAccessibleName('File bytes with hexadecimal offsets')
        self.views.addTab(self.hex, 'Raw bytes')
        layout.addWidget(self.views, 1)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search text, strings, archive names or bytes…')
        self.search.setAccessibleName('Search extracted file content')
        self.search.returnPressed.connect(self.find_next)
        row.addWidget(self.search, 1)
        row.addWidget(button('Find next', self.find_next))
        row.addWidget(button('Download results…', window.download_results))
        if window.edition == 'charon':
            row.addWidget(button('Explain with AI', lambda: window.tabs.setCurrentIndex(window.investigation_index), primary=True))
        layout.addLayout(row)
        self.status = label('', 'muted', wrap=True)
        layout.addWidget(self.status)

    def refresh(self):
        project = self.window.project
        data = project.image.get('inspection', {}) if project else {}
        self.selected_offset = None
        self.description.setText(f"{data.get('format', 'File inspection')} · Read-only inspection. No file content is executed.")
        properties = data.get('properties', {})
        text = '\n'.join(f'{key}: {value}' for key, value in properties.items())
        text += f"\nSHA-256: {project.binary['sha256']}\n\nWHAT YOU CAN DO\nRead extracted text, search strings, browse archive names, inspect bytes, or download one text report.\n\nINSPECTION LIMITS\n" + '\n'.join(project.diagnostics)
        self.summary.setPlainText(text)
        self.text.setPlainText(data.get('text') or 'No readable text was extracted. Try Strings or Raw bytes. Compressed or encrypted content may require a format-specific decoder or key.')
        self.strings.clear()
        for row in data.get('strings', []):
            item = QTreeWidgetItem([hex(row['offset']), row['encoding'], row['text']])
            item.setData(0, Qt.ItemDataRole.UserRole, row['offset'])
            item.setToolTip(2, row['text'])
            self.strings.addTopLevelItem(item)
        self.entries.clear()
        for row in data.get('entries', []):
            item = QTreeWidgetItem([row['name'], str(row['size']), str(row['compressed']), 'Yes' if row['encrypted'] else 'No'])
            item.setToolTip(0, row['name'])
            self.entries.addTopLevelItem(item)
        self.views.setTabVisible(3, bool(data.get('entries')) or 'ZIP' in data.get('format', ''))
        raw = bytes.fromhex(data.get('hex', ''))
        self.hex.setPlainText('\n'.join(f'{offset:08x}  ' + ' '.join(f'{b:02x}' for b in raw[offset:offset + 16]).ljust(47) + '  ' + ''.join(chr(b) if 32 <= b < 127 else '.' for b in raw[offset:offset + 16]) for offset in range(0, len(raw), 16)) or 'Empty file — no bytes.')
        self.views.setCurrentIndex(1 if data.get('text') else 0)
        self.status.setText(f"{len(data.get('strings', []))} strings · {len(data.get('entries', []))} archive entries · Raw-byte preview: first {len(raw):,} bytes")

    def find_next(self):
        query = self.search.text().strip()
        if not query:
            return
        view = self.views.currentWidget()
        if isinstance(view, QPlainTextEdit):
            if not view.find(query):
                view.moveCursor(QTextCursor.MoveOperation.Start)
                if not view.find(query):
                    self.status.setText('No match in this preview.')
        else:
            current = view.indexOfTopLevelItem(view.currentItem())
            count = view.topLevelItemCount()
            for step in range(1, count + 1):
                item = view.topLevelItem((current + step) % count)
                if any(query.casefold() in item.text(c).casefold() for c in range(view.columnCount())):
                    view.setCurrentItem(item)
                    view.scrollToItem(item)
                    return
            self.status.setText('No match in this list.')

    def open_offset(self, offset):
        if offset is None:
            return
        self.selected_offset = offset
        self.window.tabs.setCurrentIndex(self.window.file_index)
        raw_length = len(self.window.project.image['inspection'].get('hex', '')) // 2
        if offset < raw_length:
            self.views.setCurrentIndex(4)
            block = self.hex.document().findBlockByNumber(offset // 16)
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            self.hex.setTextCursor(cursor)
            self.hex.centerCursor()
            self.status.setText(f'File offset {offset:#x} selected. Offsets refer to file bytes, not virtual code addresses.')
        else:
            self.views.setCurrentIndex(2)
            for index in range(self.strings.topLevelItemCount()):
                item = self.strings.topLevelItem(index)
                if item.data(0, Qt.ItemDataRole.UserRole) == offset:
                    self.strings.setCurrentItem(item)
                    self.strings.scrollToItem(item)
                    break
            self.status.setText(f'File offset {offset:#x} is outside the 64 KB byte preview; showing its extracted string.')
