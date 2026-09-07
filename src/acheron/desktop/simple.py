"""Beginner readout from deterministic facts, with no invented purpose."""
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget
from .primitives import label, button


class SimpleReadout(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        layout.addWidget(label("What am I looking at?", "functionTitle"))
        self.description = label("Open a file, then pick a function — one section of the program.", wrap=True)
        layout.addWidget(self.description)
        layout.addWidget(label("WHAT WE CAN SEE", "section"))
        self.facts = label("No file loaded yet.", wrap=True)
        layout.addWidget(self.facts)
        self.gaps = label("", "muted", wrap=True)
        layout.addWidget(self.gaps)
        layout.addWidget(label("WHERE TO GO NEXT", "section"))
        layout.addWidget(label("Read the recovered code, or see the routes through this section in Flow.\nDownload results saves your work as a text file you can open anywhere.", "muted", wrap=True))
        actions = QHBoxLayout()
        actions.addWidget(button("Show code", lambda: window.tabs.setCurrentIndex(0)))
        actions.addWidget(button("Show flow", lambda: window.tabs.setCurrentIndex(3)))
        if window.edition == "charon":
            actions.addWidget(button("Explain with AI", lambda: window.tabs.setCurrentIndex(window.investigation_index), primary=True))
        actions.addWidget(button("Download results…", lambda: window.download_results(selected=True)))
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()

    def refresh(self):
        window = self.window
        if not window.project or not window.current_function:
            self.description.setText("No function was recovered. Try the included sample or inspect the file's extracted contents.")
            self.facts.setText("There is no function to summarize.")
            self.gaps.clear()
            return
        function = window.current_function
        instructions = [i for b in function.blocks for i in b.instructions]
        decisions = sum(i.flow == "branch" for i in instructions)
        calls = sum(i.flow in ("call", "indirect_call") for i in instructions)
        unsupported = sum(not op.supported for b in function.blocks for op in b.air)
        self.description.setText(f"{function.name} is one section of {window.project.binary['filename']}.\nA function is a group of instructions that performs part of the program's work.")
        self.facts.setText(f"• {len(instructions)} decoded instructions in {len(function.blocks)} connected blocks.\n"
                           f"• {decisions} conditional branches: places where execution can take different routes.\n"
                           f"• {calls} calls to other sections of code.\n"
                           f"• {unsupported} instructions whose behavior is not fully understood by the current lifter.")
        self.gaps.setText("These are facts from static analysis. The original variable names, types and purpose are not recovered.\n"
                          "The code view is a reconstruction. In CHARON, ask the model for a plain-language hypothesis and check its evidence.")
