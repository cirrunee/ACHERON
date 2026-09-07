"""Source-mapped text views and modest syntax highlighting."""
import re

from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget, QApplication

from .theme import code_font, COLORS


class Highlighter(QSyntaxHighlighter):
    def highlightBlock(self, text):
        for pattern, color in ((r"\b(?:void|return|if|goto|u8|u16|u32|u64|machine_state)\b", "#cfa6ee"),
                               (r"\b(?:0x[0-9a-fA-F]+|L_[0-9a-f]+|[0-9]+)\b", "#e7bb7d"),
                               (r"\b(?:rax|rbx|rcx|rdx|rsp|rbp|rflags|r[89]|r1[0-5])\b", "#7cd7cf"),
                               (r"\b\w+(?=\()", "#83b7eb")):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), len(match.group()), fmt)
        comment = QTextCharFormat()
        comment.setForeground(QColor("#8999aa"))
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == 1 else text.find("/*")
        while start >= 0:
            end = text.find("*/", start)
            if end < 0:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, comment)
                break
            self.setFormat(start, end - start + 2, comment)
            start = text.find("/*", end + 2)


class SourceGutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_gutter(event)


class CodeView(QPlainTextEdit):
    addressSelected = Signal(object)
    addressActivated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(code_font())
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(32)
        self.line_addresses = {}
        self.address_lines = {}
        self.gutter = SourceGutter(self)
        self.gutter.setToolTip("Original instruction address. Repeated lines share the same source instruction.")
        self.setAccessibleName("Source-mapped code")
        self.highlighter = Highlighter(self.document())
        self.cursorPositionChanged.connect(self._cursor_changed)
        self.blockCountChanged.connect(self.update_gutter_width)
        self.updateRequest.connect(self.update_gutter)

    def gutter_width(self):
        digits = max((len(f"{address:x}") for address in self.address_lines), default=6)
        return self.fontMetrics().horizontalAdvance("0") * digits + 16

    def update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_gutter_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.gutter.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))

    def paint_gutter(self, event):
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor(COLORS["code"]))
        painter.setFont(self.font())
        painter.setPen(QColor("#8496a8"))
        block = self.firstVisibleBlock()
        while block.isValid():
            top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
            if top > event.rect().bottom():
                break
            address = self.line_addresses.get(block.blockNumber())
            if block.isVisible() and address is not None and self.address_lines[address][0] == block.blockNumber() + 1:
                painter.drawText(0, top, self.gutter.width() - 8, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, f"{address:x}")
            block = block.next()
        painter.end()

    def set_code(self, text: str, source_map: dict[int, list[int]]) -> None:
        self.blockSignals(True)
        self.address_lines = source_map
        self.line_addresses = {line - 1: address for address, lines in source_map.items() for line in lines}
        self.setPlainText(text)
        self.setExtraSelections([])
        self.blockSignals(False)
        self.update_gutter_width()
        self.gutter.update()

    def _cursor_changed(self):
        address = self.line_addresses.get(self.textCursor().blockNumber())
        if address is not None:
            self.addressSelected.emit(address)

    def highlight_address(self, address: int, *, move_cursor=True) -> None:
        selections = []
        for line in self.address_lines.get(address, []):
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(self.document().findBlockByNumber(line - 1))
            selection.format.setBackground(QColor(COLORS["selection"]))
            selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selections.append(selection)
        self.setExtraSelections(selections)
        if selections and move_cursor:
            self.blockSignals(True)
            self.setTextCursor(selections[0].cursor)
            self.ensureCursorVisible()
            self.blockSignals(False)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        cursor = self.cursorForPosition(event.pos())
        address = self.line_addresses.get(cursor.blockNumber())
        if address is not None:
            menu.addSeparator()
            menu.addAction("Copy source address", lambda: QApplication.clipboard().setText(hex(address)))
            menu.addAction("Follow call or branch", lambda: self.addressActivated.emit(address))
        menu.exec(event.globalPos())
        menu.deleteLater()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        address = self.line_addresses.get(self.textCursor().blockNumber())
        if address is not None:
            self.addressActivated.emit(address)
