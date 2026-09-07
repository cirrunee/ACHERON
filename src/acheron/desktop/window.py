"""Desktop workbench backed exclusively by real analysis artifacts."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys

from PySide6.QtCore import QDir, QElapsedTimer, QProcess, QProcessEnvironment, QTemporaryDir, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QApplication,
)

from ..model import AnalysisError, plain
from ..identity import ATTRIBUTION, PRODUCT, DESCRIPTION, AIR_NAME, CHARON_PRODUCT, CHARON_DESCRIPTION
from ..project import Project
from ..pseudocode import cfg_dot, render_with_map
from .codeview import CodeView
from .graph import GraphView
from .theme import app_icon, code_font
from .primitives import label, tree, button, disclosure
from .presentation import Location, readable_pseudocode, confidence_text, confidence_explanation, human_progress


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))


class MainWindow(QMainWindow):
    projectLoaded = Signal(object)
    analysisFailed = Signal(str)
    functionSelected = Signal(object)
    simpleModeChanged = Signal(bool)

    def __init__(self, edition="base", settings_path=None):
        super().__init__()
        self.edition = edition
        self.product_name = CHARON_PRODUCT if edition == "charon" else PRODUCT
        self.product_description = CHARON_DESCRIPTION if edition == "charon" else DESCRIPTION
        self.settings_path = settings_path
        self.simple_mode = False
        self.full_view = 0
        self.full_panels = (True, False)
        self.project: Project | None = None
        self.current_function = None
        self.current_address = None
        self.instruction_index = {}
        self.function_items = {}
        self.syncing = False
        self.worker: QProcess | None = None
        self.workspace: QTemporaryDir | None = None
        self.cancelled = False
        self.source_path = None
        self.last_status = ""
        self.history: list[Location] = []
        self.forward_history: list[Location] = []
        self.elapsed = QElapsedTimer()
        self.call_graph_ready = False
        self.setWindowTitle(f"{self.product_name} · {self.product_description}")
        self.setWindowIcon(app_icon())
        self.resize(1440, 900)
        self.setMinimumSize(1024, 680)
        self.setAcceptDrops(True)
        self._build_ui()
        self.poller = QTimer(self)
        self.poller.setInterval(150)
        self.poller.timeout.connect(self._poll_status)
        if settings_path:
            try:
                self.set_simple_mode(bool(json.loads(Path(settings_path).read_text(encoding="utf-8")).get("simple_mode", True)))
            except (OSError, ValueError):
                self.set_simple_mode(True)

    def _build_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        row = QHBoxLayout(toolbar)
        self.toolbar_row = row
        row.setContentsMargins(12, 6, 12, 6)
        mark = label("")
        mark.setPixmap(app_icon().pixmap(24, 24))
        row.addWidget(mark)
        row.addWidget(label("ACHERON", "brand"))
        row.addWidget(label("// CHARON" if self.edition == "charon" else "BASE", "section"))
        row.addSpacing(16)
        self.open_button = QPushButton("Open file…")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.choose_file)
        self.open_button.setToolTip("Open any file or saved project · Ctrl+O")
        self.sample_button = QPushButton("Explore sample")
        self.sample_button.clicked.connect(self.open_sample)
        self.sample_button.setToolTip("Analyze the bundled example compiled from known source")
        self.save_button = QPushButton("Save project…")
        self.save_button.clicked.connect(self.save_project_dialog)
        self.save_button.setToolTip("Save analysis as a new project · Ctrl+S")
        self.export_button = QToolButton()
        self.export_button.setText("More…")
        self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        exports = QMenu(self)
        exports.addAction("Save project…", self.save_project_dialog)
        exports.addAction("Analysis log", self.toggle_log)
        exports.addSeparator()
        for title, kind in (("Pseudocode…", "code"), ("Function AIR + data flow…", "air"),
                            ("Control-flow graph (DOT)…", "cfg"), ("Project analysis (JSON)…", "json")):
            action = exports.addAction(title)
            action.triggered.connect(lambda checked=False, k=kind: self.export_dialog(k))
        self.export_button.setMenu(exports)
        self.download_button = button("Download results…", self.download_results, tip="Save recovered code, extracted details and AI answers as one text file · Ctrl+Shift+S")
        for control in (self.open_button, self.download_button, self.export_button):
            row.addWidget(control)
        self.save_button.hide()
        self.sample_button.hide()
        row.addStretch()
        self.entry_button = button("Entry point", self.go_entry, tip="Inspect the PE entry point · Ctrl+Home")
        row.addWidget(self.entry_button)
        self.log_button = button("Analysis log", self.toggle_log, tip="Show or hide analysis details · Ctrl+L")
        self.log_button.hide()
        self.simple_button = button("Easy mode", lambda: None, tip="Dumbass mode: fewer controls and plain-language guidance · Ctrl+Shift+D")
        self.simple_button.setCheckable(True)
        self.simple_button.toggled.connect(self.set_simple_mode)
        row.addWidget(self.simple_button)
        self.cancel_button = QPushButton("Cancel analysis")
        self.cancel_button.clicked.connect(self.cancel_analysis)
        self.cancel_button.hide()
        self.help_button = QPushButton("About")
        self.help_button.clicked.connect(self.about)
        self.help_button.hide()
        layout.addWidget(toolbar)
        self.activity = QFrame()
        self.activity.setObjectName("activity")
        activity_row = QHBoxLayout(self.activity)
        activity_row.setContentsMargins(12, 7, 12, 7)
        self.activity_text = label("Reading file…")
        self.activity_text.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.activity_text.setWordWrap(True)
        self.activity_time = label("", "muted")
        activity_row.addWidget(self.activity_text, 1)
        activity_row.addWidget(self.activity_time)
        activity_row.addWidget(self.cancel_button)
        layout.addWidget(self.activity)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(3)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._welcome())
        self.pages.addWidget(self._workbench())
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(container)
        self.statusBar().showMessage("Ready · Open any file to inspect its contents")
        self.mode = label("STATIC ANALYSIS", "muted")
        self.statusBar().addPermanentWidget(self.mode)
        self._set_busy(False)
        self._menus()

    def _welcome(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(28, 24, 28, 24)
        content = QWidget()
        content.setMaximumWidth(1000)
        column = QVBoxLayout(content)
        column.setSpacing(12)
        column.addWidget(label(self.product_name, "hero"))
        column.addWidget(label(self.product_description))
        column.addWidget(label(ATTRIBUTION, "muted"))
        column.addSpacing(12)
        subtitle = label("Open a file to inspect its text, strings, metadata and bytes.\nWindows x86 and x64 programs also support code and control-flow analysis.", "muted")
        subtitle.setWordWrap(True)
        column.addWidget(subtitle)
        actions = QHBoxLayout()
        self.welcome_open = QPushButton("Open a file…")
        self.welcome_open.setObjectName("primary")
        self.welcome_open.clicked.connect(self.choose_file)
        self.welcome_sample = QPushButton("Explore sample")
        self.welcome_sample.clicked.connect(self.open_sample)
        actions.addWidget(self.welcome_open)
        actions.addWidget(self.welcome_sample)
        actions.addStretch()
        column.addLayout(actions)
        column.addSpacing(16)
        column.addWidget(label("FIRST INSPECTION", "section"))
        for heading, explanation in (("1   Open a file", "Choose a program, document, archive, media file or any other file. Try Explore sample to learn the app."),
                                     ("2   Choose a section", "Pick a function on the left. Read its recovered code" + (" or open AI help and click Explain." if self.edition == "charon" else " and its At a glance summary.")),
                                     ("3   Download your results", "Save code, extracted details and any AI explanations in one text file.")):
            column.addWidget(label(heading))
            column.addWidget(label(explanation, "muted", wrap=True))
        column.addSpacing(12)
        note = label("Any-file inspection · Windows x86/x64 code analysis · Input files are never executed", "muted")
        note.setWordWrap(True)
        column.addWidget(note)
        outer.addWidget(content, 0)
        shortcuts = label("Ctrl+O  Open file     Ctrl+K  Find function     Ctrl+Home  Entry point     F1  Keyboard help", "muted")
        shortcuts.setWordWrap(True)
        outer.addSpacing(24)
        outer.addWidget(shortcuts)
        outer.addStretch(1)
        return page

    def _workbench(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 6)
        heading = QHBoxLayout()
        self.file_title = label("", "section")
        self.file_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.summary = label("", "muted")
        heading.addWidget(self.file_title, 1)
        heading.addWidget(self.summary)
        layout.addLayout(heading)
        vertical = QSplitter(Qt.Orientation.Vertical)
        panes = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left.setMinimumWidth(175)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self.explorer_heading = label("BINARY EXPLORER", "section")
        left_layout.addWidget(self.explorer_heading)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter functions or address…")
        self.filter.setToolTip("Find a function by name or hexadecimal address · Ctrl+K")
        self.filter.setAccessibleName("Find function")
        self.filter.returnPressed.connect(self.activate_first_match)
        self.filter.textChanged.connect(self.filter_functions)
        left_layout.addWidget(self.filter)
        self.explorer = QTabWidget()
        self.functions = tree(["Function", "Address"])
        self.functions.setColumnWidth(0, 145)
        self.functions.currentItemChanged.connect(self._function_selected)
        self.functions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.functions.customContextMenuRequested.connect(self.function_menu)
        self.imports = tree(["Import", "Library"])
        self.exports = tree(["Export", "Address"])
        self.exports.itemActivated.connect(lambda item, column: self.navigate(item.data(0, Qt.ItemDataRole.UserRole)))
        for name, widget in (("Functions", self.functions), ("Imports", self.imports), ("Exports", self.exports)):
            self.explorer.addTab(widget, name)
        left_layout.addWidget(self.explorer)
        panes.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(8, 0, 8, 0)
        function_row = QHBoxLayout()
        self.back_button = QPushButton("←")
        self.back_button.setMaximumWidth(36)
        self.back_button.setToolTip("Previous function · Alt+Left")
        self.back_button.clicked.connect(self.go_back)
        self.forward_button = button("→", self.go_forward, tip="Next location · Alt+Right")
        self.forward_button.setMaximumWidth(34)
        self.function_title = label("Select a function", "functionTitle")
        self.function_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Go to address…")
        self.address_input.setToolTip("Go to an original virtual address · Ctrl+G")
        self.address_input.setAccessibleName("Go to virtual address")
        self.address_input.setMaximumWidth(160)
        self.address_input.returnPressed.connect(self.go_address)
        function_row.addWidget(self.back_button)
        function_row.addWidget(self.forward_button)
        function_row.addWidget(self.function_title, 1)
        function_row.addWidget(self.address_input)
        center_layout.addLayout(function_row)
        metadata_row = QHBoxLayout()
        self.function_address = label("", "address")
        self.signature = label("Signature unknown", "signature")
        self.signature.setMinimumWidth(112)
        self.signature.setToolTip("A source-level function signature has not been recovered. The pseudocode uses machine-state notation.")
        self.signature.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.confidence = label("", "confidence")
        self.confidence.setAccessibleName("Function entry evidence score")
        metadata_row.addWidget(self.function_address)
        metadata_row.addWidget(self.signature)
        metadata_row.addStretch()
        metadata_row.addWidget(self.confidence)
        center_layout.addLayout(metadata_row)
        self.notice = label("Reconstructed machine-state pseudocode · Original source and types are not recovered", "notice")
        self.notice.setWordWrap(True)
        center_layout.addWidget(self.notice)
        self.tabs = QTabWidget()
        self.pseudocode = CodeView()
        self.pseudocode.setToolTip("Select a line to inspect its source instruction. Double-click a call to follow it.")
        self.disassembly = QTableWidget(0, 3)
        self.disassembly.setHorizontalHeaderLabels(["Address", "Bytes", "Assembly"])
        self.disassembly.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.disassembly.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.disassembly.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.disassembly.setFont(code_font())
        self.disassembly.verticalHeader().hide()
        self.disassembly.setColumnWidth(0, 135)
        self.disassembly.setColumnWidth(1, 150)
        self.disassembly.horizontalHeader().setStretchLastSection(True)
        self.disassembly.verticalHeader().setDefaultSectionSize(24)
        self.disassembly.setShowGrid(False)
        self.disassembly.setAccessibleName("Assembly instructions")
        self.disassembly.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.disassembly.customContextMenuRequested.connect(self.assembly_menu)
        self.disassembly.itemSelectionChanged.connect(self._disassembly_selected)
        self.disassembly.cellDoubleClicked.connect(lambda row, column: self.follow_instruction(self.disassembly.item(row, 0).data(Qt.ItemDataRole.UserRole)))
        self.air = CodeView()
        self.cfg = GraphView()
        self.calls = GraphView()
        for widget, name in ((self.pseudocode, "Pseudocode"), (self.disassembly, "Assembly"), (self.air, "AIR"),
                             (self._graph_page(self.cfg), "Control flow"), (self._graph_page(self.calls), "Call graph")):
            self.tabs.addTab(widget, name)
        for index, tip in enumerate(("Reconstructed machine-state code · Alt+1", "Original decoded instructions · Alt+2",
                                     AIR_NAME + " · Alt+3", "Basic blocks and branches · Alt+4", "Recovered function calls · Alt+5")):
            self.tabs.setTabToolTip(index, tip)
        self.tabs.currentChanged.connect(self._tab_changed)
        for widget in (self.pseudocode, self.air):
            widget.addressSelected.connect(self.select_address)
            widget.addressActivated.connect(self.follow_instruction)
        self.cfg.addressActivated.connect(self._graph_navigate)
        self.calls.addressActivated.connect(self.navigate)
        self.find_bar = QWidget()
        find_row = QHBoxLayout(self.find_bar)
        find_row.setContentsMargins(0, 0, 0, 0)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find in current code view…")
        self.find_input.setAccessibleName("Find in code")
        self.find_input.returnPressed.connect(self.find_next)
        find_row.addWidget(self.find_input, 1)
        find_row.addWidget(button("Previous", lambda: self.find_next(True), tip="Previous match · Shift+F3"))
        find_row.addWidget(button("Next", self.find_next, tip="Next match · F3"))
        find_row.addWidget(button("Close", self.find_bar.hide, tip="Close code search"))
        self.find_bar.hide()
        center_layout.addWidget(self.find_bar)
        from .simple import SimpleReadout
        self.simple_readout = SimpleReadout(self)
        self.overview_index = self.tabs.addTab(self.simple_readout, "At a glance")
        from .fileview import FileView
        self.file_view = FileView(self)
        self.file_index = self.tabs.addTab(self.file_view, 'File contents')
        self.tabs.setTabVisible(self.file_index, False)
        center_layout.addWidget(self.tabs)
        panes.addWidget(center)
        right = QWidget()
        self.right_panel = right
        right.setMinimumWidth(220)
        right.setMaximumWidth(330)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(label("EVIDENCE & REFERENCES", "section"))
        self.inspector = tree(["Property", "Value"])
        self.inspector.setRootIsDecorated(True)
        self.inspector.setColumnWidth(0, 145)
        right_layout.addWidget(self.inspector, 3)
        references_title = label("CROSS-REFERENCES", "section")
        references_title.setToolTip("Double-click a reference to navigate")
        right_layout.addWidget(references_title)
        self.xrefs = QListWidget()
        self.xrefs.setAccessibleName("Callers and calls · press Enter to navigate")
        self.xrefs.itemActivated.connect(lambda item: self.navigate(item.data(Qt.ItemDataRole.UserRole)))
        right_layout.addWidget(self.xrefs, 2)
        panes.addWidget(right)
        panes.setSizes([280, 820, 290])
        panes.setStretchFactor(1, 1)
        panes.setChildrenCollapsible(False)
        vertical.addWidget(panes)
        log_panel = QWidget()
        self.log_panel = log_panel
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 8, 0, 0)
        log_layout.addWidget(label("ANALYSIS LOG", "section"))
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setFont(code_font())
        self.logs.setMaximumBlockCount(3000)
        log_layout.addWidget(self.logs)
        vertical.addWidget(log_panel)
        log_panel.hide()
        vertical.setSizes([680, 120])
        vertical.setStretchFactor(0, 1)
        layout.addWidget(vertical, 1)
        return page

    def _menus(self):
        self.commands = {}
        file_menu = self.menuBar().addMenu("&File")
        navigation = self.menuBar().addMenu("&Navigate")
        view = self.menuBar().addMenu("&View")
        help_menu = self.menuBar().addMenu("&Help")

        def command(menu, key, title, shortcut, callback):
            action = QAction(title, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda checked=False: callback())
            action.setToolTip(title.replace("&", "") + (f" · {shortcut}" if shortcut else ""))
            menu.addAction(action)
            self.commands[key] = action
            return action

        command(file_menu, "open", "&Open file…", "Ctrl+O", self.choose_file)
        command(file_menu, "sample", "Explore &sample", "", self.open_sample)
        command(file_menu, "sample_x86", "Explore 32-bit sample", "", lambda: self.open_path(resource_root() / 'fixtures/known_x86_O0.exe'))
        command(file_menu, "save", "Save &project as…", "Ctrl+S", self.save_project_dialog)
        command(file_menu, "download", "&Download results…", "Ctrl+Shift+S", self.download_results)
        command(file_menu, "export", "Export pseudo&code…", "Ctrl+E", lambda: self.export_dialog("code"))
        file_menu.addSeparator()
        command(file_menu, "quit", "E&xit", "Alt+F4", self.close)
        command(navigation, "back", "&Back", "Alt+Left", self.go_back)
        command(navigation, "forward", "&Forward", "Alt+Right", self.go_forward)
        navigation.addSeparator()
        command(navigation, "entry", "&Entry point", "Ctrl+Home", self.go_entry)
        command(navigation, "functions", "Find &function", "Ctrl+K", self.focus_functions)
        command(navigation, "address", "Go to &address", "Ctrl+G", lambda: self.address_input.setFocus())
        command(navigation, "callers", "Show &callers and calls", "Ctrl+R", self.show_callers)
        command(navigation, "follow", "Follow selected call or branch", "Ctrl+Return", lambda: self.follow_instruction(self.current_address))
        command(navigation, "copy_address", "Copy source address", "Ctrl+Shift+C", self.copy_address)
        for index, name in enumerate(("Pseudocode", "Assembly", "AIR", "Control flow", "Call graph")):
            command(view, f"view_{index}", name, f"Alt+{index + 1}", lambda i=index: self.tabs.setCurrentIndex(i))
        view.addSeparator()
        command(view, "find", "Find in code…", "Ctrl+F", self.show_find)
        command(view, "find_next", "Next match", "F3", self.find_next)
        command(view, "find_previous", "Previous match", "Shift+F3", lambda: self.find_next(True))
        self.log_action = QAction("Analysis log", self)
        self.log_action.setShortcut(QKeySequence("Ctrl+L"))
        self.log_action.setCheckable(True)
        self.log_action.toggled.connect(self.log_panel.setVisible)
        view.addAction(self.log_action)
        inspector = QAction("Evidence and references", self)
        inspector.setCheckable(True)
        inspector.setChecked(True)
        inspector.toggled.connect(self.right_panel.setVisible)
        view.addAction(inspector)
        self.inspector_action = inspector
        self.commands["log"] = self.log_action
        self.simple_action = QAction("Easy mode (Dumbass mode)", self)
        self.simple_action.setCheckable(True)
        self.simple_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.simple_action.toggled.connect(self.set_simple_mode)
        view.addAction(self.simple_action)
        command(view, "overview", "At a glance", "Alt+6", lambda: self.tabs.setCurrentIndex(self.overview_index))
        command(help_menu, "shortcuts", "Keyboard shortcuts", "F1", self.keyboard_help)
        command(help_menu, "about", "About ACHERON", "", self.about)
        self._update_commands()

    def _update_commands(self):
        if not hasattr(self, "commands"):
            return
        ready = self.project is not None and self.worker is None
        self.commands['overview'].setEnabled(ready)
        for key in ("save", "download", "export", "entry", "functions", "address", "callers", "follow", "copy_address", "find", "find_next", "find_previous"):
            self.commands[key].setEnabled(ready)
        for index in range(5):
            self.commands[f"view_{index}"].setEnabled(ready)
        if ready and self.project.image.get('kind') == 'file':
            for key in ('export', 'entry', 'functions', 'address', 'callers', 'follow', 'copy_address', 'find', 'find_next', 'find_previous', 'overview', *(f'view_{i}' for i in range(5))):
                self.commands[key].setEnabled(False)
        self.commands["open"].setEnabled(self.worker is None)
        self.commands["sample"].setEnabled(self.worker is None)
        self.commands['sample_x86'].setEnabled(self.worker is None)
        self.commands["back"].setEnabled(bool(self.history) and ready)
        self.commands["forward"].setEnabled(bool(self.forward_history) and ready)

    def toggle_log(self):
        self.log_action.setChecked(not self.log_action.isChecked())

    def set_simple_mode(self, enabled):
        enabled = bool(enabled)
        if enabled == self.simple_mode:
            return
        if enabled:
            self.full_view = self.tabs.currentIndex()
            self.full_panels = (self.inspector_action.isChecked(), self.log_action.isChecked())
        self.simple_mode = enabled
        for control in (self.simple_button, self.simple_action):
            control.blockSignals(True)
            control.setChecked(enabled)
            control.blockSignals(False)
        self.simple_button.setText("Easy mode: on" if enabled else "Easy mode")
        self.explorer_heading.setText("SECTIONS OF THE PROGRAM" if enabled else "BINARY EXPLORER")
        self.explorer.setTabText(0, "Sections" if enabled else "Functions")
        self.functions.setColumnHidden(1, enabled)
        for index in (1, 2):
            self.explorer.setTabVisible(index, not enabled)
        self.explorer.setCurrentIndex(0)
        for index in (1, 2, 4):
            self.tabs.setTabVisible(index, not enabled)
        self.tabs.setTabText(0, "Code" if enabled else "Pseudocode")
        self.tabs.setTabText(3, "Flow" if enabled else "Control flow")
        self.address_input.setVisible(not enabled)
        self.signature.setVisible(not enabled)
        self.function_address.setVisible(not enabled)
        self.confidence.setVisible(not enabled)
        self.export_button.setVisible(not enabled)
        self.entry_button.setText("Start here" if enabled else "Entry point")
        self.inspector_action.setChecked(False if enabled else self.full_panels[0])
        self.log_action.setChecked(False if enabled else self.full_panels[1])
        self.tabs.setCurrentIndex(self.overview_index if enabled else self.full_view)
        self.simple_readout.refresh()
        if self.settings_path:
            try:
                path = Path(self.settings_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"simple_mode": enabled}), encoding="utf-8")
            except OSError:
                self.statusBar().showMessage("Mode changed for this session; the app folder is not writable.")
        self.simpleModeChanged.emit(enabled)
        if self.project and self.project.image.get('kind') == 'file':
            self.show_file_inspection()

    def focus_functions(self):
        self.explorer.setCurrentIndex(0)
        self.filter.setFocus()
        self.filter.selectAll()

    def activate_first_match(self):
        first = next((item for item in self.function_items.values() if not item.isHidden()), None)
        if first:
            self.navigate(first.data(0, Qt.ItemDataRole.UserRole))
            self.pseudocode.setFocus()

    def go_entry(self):
        if self.project:
            self.navigate(self.project.image.get("entry"))
            self.tabs.setCurrentIndex(0)

    def show_callers(self):
        self.inspector_action.setChecked(True)
        self.xrefs.setFocus()
        if self.xrefs.count():
            self.xrefs.setCurrentRow(0)

    def copy_address(self):
        if self.current_address is not None:
            QApplication.clipboard().setText(hex(self.current_address))

    def show_find(self):
        if self.tabs.currentIndex() > 2:
            self.tabs.setCurrentIndex(0)
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def find_next(self, backward=False):
        query = self.find_input.text()
        if not query:
            self.show_find()
            return
        index = self.tabs.currentIndex()
        if index == 1:
            count = self.disassembly.rowCount()
            if not count:
                return
            start = self.disassembly.currentRow()
            for offset in range(1, count + 1):
                row = (start + (-offset if backward else offset)) % count
                if any(query.casefold() in self.disassembly.item(row, col).text().casefold() for col in range(3)):
                    self.disassembly.selectRow(row)
                    self.statusBar().showMessage(f"Match at {self.disassembly.item(row, 0).text()}")
                    return
        else:
            editor = self.air if index == 2 else self.pseudocode
            flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
            if editor.find(query, flags):
                return
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            if editor.find(query, flags):
                self.statusBar().showMessage("Search wrapped to the start/end of this view")
                return
        self.statusBar().showMessage(f"No match for {query!r} in this view")

    def function_menu(self, position):
        item = self.functions.itemAt(position)
        if not item:
            return
        address = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("Inspect function", lambda: self.navigate(address))
        menu.addAction("Show callers and calls", lambda: (self.navigate(address), self.show_callers()))
        menu.addAction("Show control flow", lambda: (self.navigate(address), self.tabs.setCurrentIndex(3)))
        menu.addSeparator()
        menu.addAction("Copy address", lambda: QApplication.clipboard().setText(hex(address)))
        menu.addAction("Copy function name", lambda: QApplication.clipboard().setText(self.project.function(address).name))
        menu.exec(self.functions.viewport().mapToGlobal(position))

    def assembly_menu(self, position):
        item = self.disassembly.itemAt(position)
        if not item:
            return
        address = item.data(Qt.ItemDataRole.UserRole)
        self.select_address(address)
        ins = self.instruction_index[address][2]
        menu = QMenu(self)
        follow = menu.addAction("Follow destination", lambda: self.follow_instruction(address))
        follow.setEnabled(ins.target is not None)
        menu.addAction("Copy address", self.copy_address)
        menu.addAction("Copy instruction", lambda: QApplication.clipboard().setText(ins.text))
        menu.addAction("Copy bytes", lambda: QApplication.clipboard().setText(ins.raw))
        menu.exec(self.disassembly.viewport().mapToGlobal(position))

    def keyboard_help(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("ACHERON · Keyboard shortcuts")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        rows = [f"{action.shortcut().toString():18} {action.text().replace('&', '')}" for action in self.commands.values() if not action.shortcut().isEmpty()]
        dialog.setText("\n".join(rows))
        dialog.setInformativeText("Enter activates a tree/reference selection. Tab moves focus.\nGraphs: drag to pan, Ctrl+wheel to zoom, Enter follows a selected node.")
        dialog.open()
        self.help_dialog = dialog

    def _graph_page(self, graph):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        tip = label("Drag to pan · Ctrl + wheel to zoom · Double-click a node", "muted")
        tip.setWordWrap(True)
        row.addWidget(tip, 1)
        fit = QPushButton("Fit graph")
        fit.clicked.connect(graph.fit_graph)
        row.addWidget(fit)
        layout.addLayout(row)
        layout.addWidget(graph)
        return page

    def _set_busy(self, busy):
        for button in (self.open_button, self.sample_button, self.welcome_open, self.welcome_sample):
            button.setEnabled(not busy)
        self.save_button.setEnabled(not busy and self.project is not None)
        self.export_button.setEnabled(not busy and self.project is not None)
        self.download_button.setEnabled(not busy and self.project is not None)
        self.cancel_button.setVisible(busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 100)
        self.activity.setVisible(busy)
        self.entry_button.setEnabled(not busy and self.project is not None)
        self._update_commands()

    def log(self, message):
        self.logs.appendPlainText(f"{datetime.now():%H:%M:%S}  {message}")

    def choose_file(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open any file", "", "All files (*);;Windows programs (*.exe *.dll *.sys *.ocx);;Documents and data (*.txt *.json *.csv *.xml *.pdf *.docx *.xlsx *.pptx);;Archives (*.zip *.jar *.apk *.7z *.rar);;ACHERON projects (*.acheron)")
        if path:
            self.open_path(Path(path))

    def open_sample(self):
        self.open_path(resource_root() / "fixtures" / "known_O0.exe")

    def open_path(self, path: Path):
        if self.worker:
            return
        self.workspace = QTemporaryDir(str(Path(QDir.tempPath()) / "acheron-XXXXXX"))
        if not self.workspace.isValid():
            self.show_error("Unable to create temporary analysis workspace")
            return
        self.source_path = Path(path)
        self.cancelled = False
        self.last_status = ""
        self.elapsed.start()
        self.activity_text.setText(f"Opening {path.name}…")
        self.activity_time.setText("0s")
        self._set_busy(True)
        self.statusBar().showMessage(f"Opening {path.name}…")
        self.log(f"Opening {path}")
        self.worker = QProcess(self)
        self.worker.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        arguments = ["--worker", str(path.resolve()), str(Path(self.workspace.path()) / "analysis.acheron"),
                     str(Path(self.workspace.path()) / "status.json")]
        if not getattr(sys, "frozen", False):
            arguments = ["-m", "acheron.desktop", *arguments]
            environment = QProcessEnvironment.systemEnvironment()
            source_dir = str(Path(__file__).resolve().parents[2])
            environment.insert("PYTHONPATH", source_dir)
            environment.insert("PYTHONDONTWRITEBYTECODE", "1")
            self.worker.setProcessEnvironment(environment)
        self.worker.finished.connect(self._worker_finished)
        self.worker.errorOccurred.connect(self._worker_error)
        self.worker.start(sys.executable, arguments)
        self.poller.start()
        self._update_commands()

    def _poll_status(self):
        if self.elapsed.isValid():
            self.activity_time.setText(f"{self.elapsed.elapsed() // 1000}s")
        if not self.workspace:
            return {}
        try:
            status = json.loads((Path(self.workspace.path()) / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if status.get("message") != self.last_status:
            self.last_status = status.get("message", "")
            self.log(self.last_status)
            self.activity_text.setText(human_progress(self.last_status))
            self.statusBar().showMessage(human_progress(self.last_status))
        return status

    def _worker_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            message = self.worker.errorString()
            self._dispose_worker()
            self.show_error(f"Analysis process could not start: {message}")

    def _worker_finished(self, code, exit_status):
        status = self._poll_status()
        stderr = bytes(self.worker.readAllStandardError()).decode("utf-8", "replace")[-2000:] if self.worker else ""
        project = None
        error = None
        if not self.cancelled:
            if code != 0:
                error = status.get("message") if status.get("error") else stderr or f"Analysis process stopped unexpectedly (exit code {code})"
            else:
                try:
                    project = Project.load(Path(self.workspace.path()) / "analysis.acheron")
                except (OSError, ValueError) as exc:
                    error = f"Unable to read analysis result: {exc}"
        self._dispose_worker()
        if project is not None:
            self.set_project(project)
        elif error:
            self.show_error(error)
        else:
            self.log("Analysis cancelled")
            self.statusBar().showMessage("Analysis cancelled")

    def _dispose_worker(self):
        self.poller.stop()
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if self.workspace:
            self.workspace.remove()
            self.workspace = None
        self._set_busy(False)

    def cancel_analysis(self):
        if self.worker:
            self.cancelled = True
            self.worker.kill()

    def set_project(self, project: Project):
        self.project = project
        for index in range(5):
            self.tabs.setTabVisible(index, not self.simple_mode or index in (0, 3))
        self.tabs.setTabVisible(self.overview_index, True)
        self.tabs.setTabVisible(self.file_index, False)
        self.explorer.parentWidget().show()
        self.signature.setVisible(not self.simple_mode)
        self.address_input.setVisible(not self.simple_mode)
        self.current_function = None
        self.current_address = None
        self.history = []
        self.forward_history = []
        self.instruction_index = {i.address: (f, b, i, op) for f in project.functions for b in f.blocks for i, op in zip(b.instructions, b.air)}
        self.call_graph_ready = False
        self.calls.draw_graph({}, [], 0)
        self.file_title.setText(project.binary["filename"])
        self.setWindowTitle(f"{project.binary['filename']} — {self.product_name}")
        count = sum(len(b.instructions) for f in project.functions for b in f.blocks)
        self.summary.setText(f"{'x86 · 32-bit' if project.image.get('bitness') == 32 else 'x64 · 64-bit'}   /   {len(project.functions)} functions   /   {count:,} instructions")
        self.functions.blockSignals(True)
        self.functions.clear()
        self.function_items.clear()
        for function in project.functions:
            is_entry = function.address == project.image.get("entry")
            item = QTreeWidgetItem([function.name + ("  · entry" if is_entry else ""), hex(function.address)])
            if is_entry:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            item.setData(0, Qt.ItemDataRole.UserRole, function.address)
            item.setToolTip(0, confidence_explanation(function))
            self.functions.addTopLevelItem(item)
            self.function_items[function.address] = item
        self.functions.blockSignals(False)
        self.imports.clear()
        for record in project.image["imports"]:
            self.imports.addTopLevelItem(QTreeWidgetItem([record["name"] or f"Ordinal {record['ordinal']}", record["dll"]]))
        if not project.image["imports"]:
            self.imports.addTopLevelItem(QTreeWidgetItem(["No imports recorded", ""]))
        self.exports.clear()
        for record in project.image["exports"]:
            item = QTreeWidgetItem([", ".join(record["names"]) or f"Ordinal {record['ordinal']}",
                                   hex(record["address"]) if record["address"] is not None else record["forwarder"] or "Unknown"])
            item.setData(0, Qt.ItemDataRole.UserRole, record["address"])
            self.exports.addTopLevelItem(item)
        if not project.image["exports"]:
            self.exports.addTopLevelItem(QTreeWidgetItem(["No exports recorded", ""]))
        self.filter.clear()
        self.pages.setCurrentIndex(1)
        self._set_busy(False)
        for note in project.diagnostics:
            self.log(note)
        self.log(f"Ready: {len(project.functions)} functions, {count} instructions. SHA-256 {project.binary['sha256']}")
        if project.functions:
            entry = project.image.get("entry")
            self.navigate(entry if entry in self.function_items else project.functions[0].address)
        else:
            self.function_title.setText("No functions recovered")
            self.function_address.clear()
            self.confidence.clear()
            self.signature.setText("Signature unknown")
            self.notice.setText("No function could be inspected. Open Analysis log for details.")
            self.pseudocode.set_code("No function entry could be recovered from this binary.\nSee analysis diagnostics below.", {})
            self.disassembly.setRowCount(0)
            self.air.set_code("", {})
            self.cfg.draw_graph({}, [], 0)
            self.inspector.clear()
            self.xrefs.clear()
        self.statusBar().showMessage(f"Ready · {project.binary['filename']}")
        self._tab_changed(self.tabs.currentIndex())
        self._update_commands()
        self.simple_readout.refresh()
        if project.image.get('kind') == 'file':
            self.show_file_inspection()
        self.projectLoaded.emit(project)

    def show_file_inspection(self):
        if not self.project or self.project.image.get('kind') != 'file':
            return
        for index in (*range(5), self.overview_index):
            self.tabs.setTabVisible(index, False)
        self.tabs.setTabVisible(self.file_index, True)
        self.tabs.setCurrentIndex(self.file_index)
        self.explorer.parentWidget().hide()
        self.inspector_action.setChecked(False)
        self.entry_button.setEnabled(False)
        self.address_input.hide()
        self.signature.hide()
        self.function_title.setText(self.project.image['inspection']['format'])
        self.notice.setText('KNOWN · Extracted file content. Code decompilation is not available in this inspection view.')
        self.summary.setText(f"{self.project.binary['size']:,} bytes · File inspection")
        self.file_view.refresh()

    def filter_functions(self, value):
        value = value.casefold()
        for item in self.function_items.values():
            item.setHidden(value not in (item.text(0) + " " + item.text(1)).casefold())

    def _function_selected(self, current, previous):
        if current:
            self.navigate(current.data(0, Qt.ItemDataRole.UserRole))

    def select_function(self, address):
        if not self.project:
            return
        function = self.project.function(address)
        if self.current_function and self.current_function.address == address:
            return
        self.current_function = function
        self.back_button.setEnabled(bool(self.history))
        self.function_title.setText(function.name)
        self.function_title.setToolTip(function.name)
        self.function_address.setText(hex(function.address))
        self.confidence.setText(confidence_text(function))
        self.confidence.setToolTip(confidence_explanation(function))
        code, source_map = readable_pseudocode(function)
        self.pseudocode.set_code(code, source_map)
        instructions = [i for b in function.blocks for i in b.instructions]
        self.disassembly.blockSignals(True)
        self.disassembly.setRowCount(len(instructions))
        self.instruction_rows = {}
        for row, ins in enumerate(instructions):
            self.instruction_rows[ins.address] = row
            for column, value in enumerate((hex(ins.address), ins.raw, ins.text)):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, ins.address)
                self.disassembly.setItem(row, column, item)
        self.disassembly.blockSignals(False)
        air_lines, air_map = [], {}
        for block in function.blocks:
            air_lines.append(f"// Block {block.address:#x}")
            for op in block.air:
                air_lines.append(f"{op.id}: {op.opcode:9} {op.detail}")
                air_map[op.address] = [len(air_lines)]
                air_lines.append(f"    reads={','.join(op.reads) or '—'}  writes={','.join(op.writes) or '—'}")
                air_map[op.address].append(len(air_lines))
        self.air.set_code("\n".join(air_lines), air_map)
        opaque = sum(not op.supported for b in function.blocks for op in b.air)
        details = []
        if opaque:
            details.append(f"{opaque} operations have unsupported semantics")
        if function.diagnostics:
            details.append(f"{len(function.diagnostics)} recovery notes · see Analysis log")
        self.notice.setText("Reconstruction, not original source" + (" · " + " · ".join(details) if details else " · Source addresses shown in the margin"))
        self.xrefs.clear()
        names = {f.address: f.name for f in self.project.functions}
        for ref in self.project.references:
            if ref["function"] == address:
                dest = names.get(ref["target"], hex(ref["target"]) if ref["target"] is not None else "Unresolved target")
                item = QListWidgetItem(f"Calls  →  {dest}\n{ref['address']:#x}")
                item.setData(Qt.ItemDataRole.UserRole, ref["target"])
                self.xrefs.addItem(item)
            if ref["target"] == address:
                item = QListWidgetItem(f"Caller  ←  {names.get(ref['function'], hex(ref['function']))}\n{ref['address']:#x}")
                item.setData(Qt.ItemDataRole.UserRole, ref["address"])
                self.xrefs.addItem(item)
        if not self.xrefs.count():
            self.xrefs.addItem("No recovered call references")
        self._draw_cfg()
        for note in function.diagnostics:
            self.log(f"{function.name}: {note}")
        self.select_address(instructions[0].address if instructions else address)
        self.simple_readout.refresh()
        self.functionSelected.emit(function)

    def _draw_cfg(self):
        function = self.current_function
        if not function:
            return
        nodes = {b.address: [f"BLOCK {b.address:#x}", *(i.text for i in b.instructions)] for b in function.blocks}
        edges = [(b.address, e.target, e.kind) for b in function.blocks for e in b.edges]
        self.cfg.draw_graph(nodes, edges, function.address)

    def _tab_changed(self, index):
        if self.simple_mode and index in (1, 2, 4):
            self.set_simple_mode(False)
            self.tabs.setCurrentIndex(index)
        if index == 3:
            QTimer.singleShot(0, self.cfg.fit_graph)
        if index == 4 and self.project:
            if not self.call_graph_ready:
                nodes = {f.address: [f.name, hex(f.address), f"{len(f.blocks)} basic blocks"] for f in self.project.functions}
                edges = [(r["function"], r["target"], r["kind"]) for r in self.project.references]
                self.calls.draw_graph(nodes, edges, self.project.image.get("entry", 0))
                self.call_graph_ready = True
            QTimer.singleShot(0, self.calls.fit_graph)

    def location(self):
        if self.current_function:
            return Location(self.current_function.address, self.current_address or self.current_function.address, self.tabs.currentIndex())
        return None

    def navigate(self, address, *, record_history=True):
        if address is None or not self.project:
            self.statusBar().showMessage("This reference has no recovered destination")
            return
        owner = self.instruction_index.get(address)
        entry = address if address in self.function_items else owner[0].address if owner else None
        if entry is None:
            self.statusBar().showMessage(f"No recovered code at {address:#x}")
            return
        current = self.location()
        if record_history and current and (entry != current.function or address != current.address):
            self.history.append(current)
            self.forward_history.clear()
        if self.function_items[entry].isHidden():
            self.filter.clear()
        self.functions.blockSignals(True)
        self.functions.setCurrentItem(self.function_items[entry])
        self.functions.blockSignals(False)
        self.select_function(entry)
        if owner:
            self.select_address(address)
        self.back_button.setEnabled(bool(self.history))
        self.forward_button.setEnabled(bool(self.forward_history))
        self._update_commands()

    def go_address(self):
        try:
            address = int(self.address_input.text().strip(), 16)
        except ValueError:
            self.statusBar().showMessage("Enter a hexadecimal virtual address, for example 0x401020")
            return
        self.navigate(address)

    def go_back(self):
        if self.history:
            previous = self.history.pop()
            if self.location():
                self.forward_history.append(self.location())
            self.navigate(previous.address, record_history=False)
            self.tabs.setCurrentIndex(previous.view)

    def go_forward(self):
        if self.forward_history:
            following = self.forward_history.pop()
            if self.location():
                self.history.append(self.location())
            self.navigate(following.address, record_history=False)
            self.tabs.setCurrentIndex(following.view)

    def _disassembly_selected(self):
        row = self.disassembly.currentRow()
        if row >= 0 and self.disassembly.item(row, 0):
            self.select_address(self.disassembly.item(row, 0).data(Qt.ItemDataRole.UserRole))

    def select_address(self, address):
        if self.syncing or not self.current_function:
            return
        self.syncing = True
        try:
            self.current_address = address
            self.pseudocode.highlight_address(address, move_cursor=self.sender() is not self.pseudocode)
            self.air.highlight_address(address, move_cursor=self.sender() is not self.air)
            if address in getattr(self, "instruction_rows", {}):
                self.disassembly.selectRow(self.instruction_rows[address])
                self.disassembly.scrollToItem(self.disassembly.item(self.instruction_rows[address], 0))
            record = self.instruction_index.get(address)
            self._inspect(record)
            if record:
                self.cfg.select_address(record[1].address)
        finally:
            self.syncing = False

    def _inspect(self, record):
        expanded = {self.inspector.topLevelItem(i).text(0) for i in range(self.inspector.topLevelItemCount()) if self.inspector.topLevelItem(i).isExpanded()}
        initial = self.inspector.topLevelItemCount() == 0
        self.inspector.clear()
        function = self.current_function
        group = QTreeWidgetItem(["Function summary", "INFERRED"])
        self.inspector.addTopLevelItem(group)
        for key, value in (("Entry", hex(function.address)), ("Entry evidence", f"{function.confidence * 100:.0f}/100 · heuristic"),
                           ("Basic blocks", str(len(function.blocks))), ("Signature", "UNKNOWN")):
            group.addChild(QTreeWidgetItem([key, value]))
        evidence = QTreeWidgetItem(["Why this entry?", "Evidence"])
        self.inspector.addTopLevelItem(evidence)
        for item in function.evidence:
            source = {"pe-entry": "PE entry point", "pe-export": "Exported symbol", "x64-runtime-function": "Unwind function range", "direct-call": "Direct call target"}.get(item.source, item.source)
            child = QTreeWidgetItem([source, f"{item.confidence * 100:.0f}/100"])
            child.setToolTip(0, item.detail + "\nAddresses: " + ", ".join(hex(a) for a in item.addresses))
            evidence.addChild(child)
        if record:
            _, block, ins, op = record
            instruction = QTreeWidgetItem(["Selected instruction", "KNOWN bytes"])
            self.inspector.addTopLevelItem(instruction)
            for key, value in (("Address", hex(ins.address)), ("Assembly", ins.text), ("Bytes", ins.raw), ("Block", hex(block.address)),
                               ("AIR operation", op.opcode), ("Lift status", op.evidence.status.value),
                               ):
                instruction.addChild(QTreeWidgetItem([key, value]))
            effects = QTreeWidgetItem(["Machine effects", "Advanced"])
            for key, value in (("Reads", ", ".join(ins.reads) or "—"), ("Writes", ", ".join(ins.writes) or "—"), ("Memory", ", ".join(ins.memory) or "—")):
                effects.addChild(QTreeWidgetItem([key, value]))
            self.inspector.addTopLevelItem(effects)
            live = function.dataflow.get("liveness", {}).get(hex(block.address), {})
            dataflow = QTreeWidgetItem(["Block data flow", "INFERRED"])
            dataflow.addChild(QTreeWidgetItem(["Live in", ", ".join(live.get("in", []))]))
            dataflow.addChild(QTreeWidgetItem(["Live out", ", ".join(live.get("out", []))]))
            self.inspector.addTopLevelItem(dataflow)
        for i in range(self.inspector.topLevelItemCount()):
            item = self.inspector.topLevelItem(i)
            item.setToolTip(0, item.text(0))
            item.setExpanded(item.text(0) in (expanded if not initial else {"Function summary", "Selected instruction"}))
            for j in range(item.childCount()):
                for col in (0, 1):
                    if not item.child(j).toolTip(col):
                        item.child(j).setToolTip(col, item.child(j).text(col))

    def follow_instruction(self, address):
        record = self.instruction_index.get(address)
        if record and record[2].flow in ("call", "jump", "branch", "indirect_call", "indirect_jump"):
            self.navigate(record[2].target)

    def _graph_navigate(self, address):
        self.navigate(address)
        self.tabs.setCurrentIndex(1)

    def save_project_dialog(self):
        if not self.project or self.worker:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save analysis as a new project", Path(self.project.binary["filename"]).stem + ".acheron",
                                             "ACHERON project (*.acheron)", options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            try:
                self.project.save(path)
                self.log(f"Saved project: {path}")
                self.statusBar().showMessage("Project saved")
            except (OSError, ValueError) as exc:
                self.show_error(str(exc))

    def download_results(self, checked=False, *, selected=False, ai_only=False):
        if not self.project or self.worker:
            return
        from .download import DownloadDialog
        self.download_dialog = DownloadDialog(self, selected=selected, ai_only=ai_only)
        self.download_dialog.show()

    def export_dialog(self, kind):
        if not self.project or self.worker:
            return
        if kind != "json" and not self.current_function:
            return
        title, suffix = {"code": ("C-style pseudocode", ".pseudo.c"), "air": ("AIR + data flow", ".air.json"),
                         "cfg": ("Graphviz CFG", ".dot"), "json": ("Analysis snapshot", ".json")}[kind]
        name = self.current_function.name if kind != "json" else Path(self.project.binary["filename"]).stem
        path, _ = QFileDialog.getSaveFileName(self, f"Export {title}", name + suffix, f"{title} (*{suffix});;All files (*)",
                                             options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            try:
                self.export_to(kind, Path(path))
                self.log(f"Exported {title}: {path}")
            except (OSError, ValueError) as exc:
                self.show_error(str(exc))

    def export_to(self, kind, destination: Path):
        if kind == "code":
            output = self.current_function.decompile()
        elif kind == "cfg":
            output = cfg_dot(self.current_function)
        elif kind == "air":
            output = json.dumps(plain(self.current_function), indent=2)
        elif kind == "json":
            output = json.dumps(self.project.snapshot(), indent=2)
        else:
            raise AnalysisError("Unsupported export format")
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(output + "\n")

    def show_error(self, text):
        self.log(f"Error: {text}")
        self.statusBar().showMessage("Could not complete the operation · see analysis log")
        self.analysisFailed.emit(text)
        message = QMessageBox(self)
        message.setWindowTitle("ACHERON")
        message.setIcon(QMessageBox.Icon.Warning)
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setText(text)
        message.setInformativeText("Choose a different file or review the analysis log. Existing files are preserved.")
        message.open()
        self.error_dialog = message

    def about(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("About ACHERON")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"{self.product_name}\n{self.product_description}\n{ATTRIBUTION}\n\nDesktop · 0.4\n\n"
                       "Any-file inspection and Windows x86/x64 code analysis. Reconstructed code is not original source.\n\n"
                       "CHARON is the optional AI investigation edition, with local models and optional OpenAI access. AI findings remain hypotheses.")
        dialog.setInformativeText("ACHERON: MIT. Third-party components retain their own copyright and licenses.")
        dialog.setDetailedText("iced-x86: MIT\nQt/PySide6: LGPLv3\nSee THIRD_PARTY.md and licenses/ in the app folder.\n\n"
                               "SSA and type/class recovery remain unsupported. Other executable architectures and managed code open in file inspection.")
        dialog.open()
        self.about_dialog = dialog

    def dragEnterEvent(self, event):
        if not self.worker and event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_path(Path(url.toLocalFile()))
                event.acceptProposedAction()
                return

    def closeEvent(self, event):
        if self.worker:
            self.worker.blockSignals(True)
            self.worker.kill()
            self.worker.waitForFinished(3000)
            self._dispose_worker()
        event.accept()
