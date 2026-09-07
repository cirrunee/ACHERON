"""Shared, accessible UI primitives for the ACHERON product family."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTreeWidget, QPushButton, QToolButton

SPACING = (4, 8, 12, 16, 24)


def label(text: str, role: str = "", *, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if role:
        widget.setObjectName(role)
    return widget


def tree(headers: list[str]) -> QTreeWidget:
    widget = QTreeWidget()
    widget.setHeaderLabels(headers)
    widget.setRootIsDecorated(False)
    widget.setUniformRowHeights(True)
    widget.setAccessibleName(" / ".join(headers))
    widget.setTextElideMode(Qt.TextElideMode.ElideRight)
    return widget


def button(text, callback, *, tip="", primary=False):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    widget.setAccessibleName(text.replace("…", ""))
    if tip:
        widget.setToolTip(tip)
    if primary:
        widget.setObjectName("primary")
    return widget


def disclosure(title, content, *, expanded=False):
    widget = QToolButton()
    widget.setText(title)
    widget.setCheckable(True)
    widget.setChecked(expanded)
    widget.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    widget.setObjectName("disclosure")
    widget.setAccessibleName(title)

    def toggle(checked):
        widget.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        content.setVisible(checked)

    widget.toggled.connect(toggle)
    toggle(expanded)
    return widget
