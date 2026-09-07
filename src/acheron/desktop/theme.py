"""Native Qt theme and code-native application icon."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
from string import Template

COLORS = {"background": "#15191f", "surface": "#1b222b", "code": "#121820",
          "text": "#dde4eb", "muted": "#a2afbd", "border": "#34404e",
          "accent": "#83cfbf", "selection": "#294851", "known": "#95bfe9",
          "inferred": "#dfbd82", "hypothesized": "#c1a5e8", "unknown": "#adb6c2"}

# One compact scale and one palette apply to Base and CHARON.
STYLE = Template("""
QMainWindow, QWidget { background: $background; color: $text; font-family: 'Segoe UI'; font-size: 13px; }
QLabel { background: transparent; }
QPlainTextEdit, QTableWidget { font-family: 'Consolas'; font-size: 14px; }
QPlainTextEdit#explanation { font-family: 'Segoe UI'; font-size: 14px; padding: 8px; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px; }
QMenuBar, QMenu { background: $surface; }
QMenuBar::item { padding: 5px 10px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected, QMenuBar::item:selected { background: $selection; }
QMenu::separator { background: $border; height: 1px; margin: 4px 8px; }
QLabel#brand { font-size: 17px; font-weight: 700; letter-spacing: 2px; }
QLabel#hero { font-size: 25px; font-weight: 600; }
QLabel#muted, QLabel#section, QLabel#signature { color: $muted; }
QLabel#section { font-size: 12px; font-weight: 600; }
QLabel#functionTitle { font-size: 20px; font-weight: 600; }
QLabel#address { font-family: 'Consolas'; color: $muted; }
QLabel#confidence { color: $inferred; font-size: 12px; }
QLabel#notice { color: $muted; font-size: 12px; }
QFrame#toolbar, QFrame#activity { background: $surface; border-bottom: 1px solid $border; }
QPushButton, QToolButton { background: $surface; border: 1px solid $border; border-radius: 3px; padding: 5px 10px; }
QPushButton:hover, QToolButton:hover { background: #293542; }
QPushButton:focus, QToolButton:focus { border-color: $accent; }
QPushButton:disabled, QToolButton:disabled { color: #7d8996; background: #1b222b; }
QPushButton#primary { background: #37665e; color: #f3faf8; border-color: #558d81; font-weight: 600; }
QPushButton#primary:hover { background: #467d72; }
QToolButton#disclosure { background: transparent; border: none; text-align: left; padding: 4px 0; color: $muted; }
QLineEdit { background: $code; border: 1px solid $border; border-radius: 3px; padding: 5px 7px; selection-background-color: $selection; }
QLineEdit:focus { border-color: $accent; }
QComboBox { background: $surface; border: 1px solid $border; border-radius: 3px; padding: 5px 8px; min-height: 18px; }
QComboBox:focus { border-color: $accent; }
QComboBox QAbstractItemView { background: $surface; color: $text; selection-background-color: $selection; }
QPushButton:checked { background: $selection; border-color: $accent; }
QTabWidget::pane { border: none; border-top: 1px solid $border; }
QTabBar::tab { background: transparent; color: $muted; padding: 7px 11px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $text; border-bottom-color: $accent; background: $surface; }
QTabBar::tab:focus { color: $accent; }
QPlainTextEdit, QTextEdit, QTreeWidget, QTableWidget, QListWidget { background: $code; border: none; selection-background-color: $selection; selection-color: #f4fafb; }
QTreeWidget::item, QListWidget::item { padding: 3px 2px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: $selection; }
QHeaderView::section { background: $surface; color: $muted; padding: 5px; border: none; border-bottom: 1px solid $border; }
QTableWidget { gridline-color: #25303b; }
QSplitter::handle { background: $border; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QScrollBar:vertical { background: $background; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #526273; min-height: 24px; border-radius: 2px; }
QScrollBar:horizontal { background: $background; height: 10px; }
QScrollBar::handle:horizontal { background: #526273; min-width: 24px; border-radius: 2px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QStatusBar { background: $surface; color: $muted; border-top: 1px solid $border; }
QProgressBar { background: $surface; border: none; height: 2px; }
QProgressBar::chunk { background: $accent; }
""").substitute(COLORS)

def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#142630"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, size * .20, size * .20)
        painter.setPen(QPen(QColor("#79e2ce"), size * .08, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline(QPolygonF([QPointF(size * .23, size * .75), QPointF(size * .50, size * .23), QPointF(size * .77, size * .75)]))
        painter.drawLine(QPointF(size * .37, size * .59), QPointF(size * .63, size * .59))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def code_font() -> QFont:
    font = QFont("Cascadia Code", 10)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font
