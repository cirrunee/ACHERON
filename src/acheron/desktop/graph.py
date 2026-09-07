"""Interactive graph projection of real CFG/call edges; no external renderer."""
from collections import deque
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView


class Node(QGraphicsRectItem):
    def __init__(self, rect, address, callback):
        super().__init__(rect)
        self.address, self.callback = address, callback
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseDoubleClickEvent(self, event):
        self.callback(self.address)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.callback(self.address)
            event.accept()
        else:
            super().keyPressEvent(event)


class GraphView(QGraphicsView):
    addressActivated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#111923"))
        self.setToolTip("Drag to pan · Ctrl + wheel to zoom · Double-click a node to navigate")
        self.nodes = {}
        self.edges_count = 0
        self.setAccessibleName("Analysis graph")
        self.setAccessibleDescription("Nodes represent recovered functions or basic blocks. Select a node and press Enter to navigate.")

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            if .15 <= self.transform().m11() * factor <= 4:
                self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def fit_graph(self):
        self.resetTransform()
        if not self.scene().itemsBoundingRect().isEmpty():
            self.fitInView(self.scene().itemsBoundingRect().adjusted(-24, -24, 24, 24), Qt.AspectRatioMode.KeepAspectRatio)
            if self.transform().m11() > 1:
                self.resetTransform()

    def draw_graph(self, nodes: dict[int, list[str]], edges: list[tuple[int, int | None, str]], entry: int):
        self.scene().clear()
        self.nodes, self.edges_count = {}, 0
        if not nodes:
            item = self.scene().addText("No graph is available for this selection.")
            item.setDefaultTextColor(QColor("#97a9ba"))
            return
        # Limit rendering cost; analysis and exports still retain the full graph.
        displayed = dict(list(nodes.items())[:250])
        successors = {a: [] for a in displayed}
        for source, target, _ in edges:
            if source in successors and target in displayed:
                successors[source].append(target)
        depths = {entry: 0} if entry in displayed else {}
        queue = deque(depths)
        while queue:
            source = queue.popleft()
            for target in successors[source]:
                if target not in depths:
                    depths[target] = depths[source] + 1
                    queue.append(target)
        for address in displayed:
            if address not in depths:
                depths[address] = max(depths.values(), default=0) + 1
        layers = {}
        for address in displayed:
            layers.setdefault(depths[address], []).append(address)
        for layer, addresses in layers.items():
            for column, address in enumerate(addresses):
                lines = displayed[address]
                visible = lines[:8]
                if len(lines) > 8:
                    visible.append(f"… {len(lines) - 8} more instructions")
                width, height = 320, 28 + len(visible) * 17
                x = (column - (len(addresses) - 1) / 2) * 365
                y = layer * 260
                item = Node(QRectF(0, 0, width, height), address, self.addressActivated.emit)
                item.setPos(x, y)
                item.setPen(QPen(QColor("#488478" if address == entry else "#3a4d61"), 1.5))
                item.setBrush(QColor("#1b2c32" if address == entry else "#1c2735"))
                item.setZValue(1)
                self.scene().addItem(item)
                text = self.scene().addSimpleText("\n".join(line[:43] for line in visible), QFont("Consolas", 9))
                text.setBrush(QColor("#d3e2ed"))
                text.setParentItem(item)
                text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                text.setPos(12, 12)
                item.setToolTip("\n".join(lines[:80]))
                self.nodes[address] = item
        for source, target, label in edges:
            if source not in self.nodes:
                continue
            source_node = self.nodes[source]
            a = source_node.pos() + QPointF(160, source_node.rect().height())
            color = QColor("#76cdb8" if label == "true" else "#c39569" if label == "false" else "#6a839e")
            if target in self.nodes:
                b = self.nodes[target].pos() + QPointF(160, 0)
                if b.y() <= a.y():
                    a = source_node.pos() + QPointF(320, source_node.rect().height() / 2)
                    b = self.nodes[target].pos() + QPointF(320, self.nodes[target].rect().height() / 2)
                    c1, c2 = a + QPointF(70, 0), b + QPointF(70, 0)
                else:
                    c1, c2 = a + QPointF(0, 45), b - QPointF(0, 45)
                path = QPainterPath(a)
                path.cubicTo(c1, c2, b)
                self.scene().addPath(path, QPen(color, 1.5))
                angle = math.atan2(b.y() - c2.y(), b.x() - c2.x())
                arrow = QPolygonF([b, b - QPointF(9 * math.cos(angle - .4), 9 * math.sin(angle - .4)),
                                   b - QPointF(9 * math.cos(angle + .4), 9 * math.sin(angle + .4))])
                self.scene().addPolygon(arrow, QPen(color), color)
                marker = self.scene().addSimpleText(label, QFont("Segoe UI", 8))
                marker.setPos(path.pointAtPercent(.35))
            else:
                marker = self.scene().addSimpleText(f"{label} → {hex(target) if target is not None else 'unresolved'}", QFont("Segoe UI", 8))
                marker.setPos(a + QPointF(5, 12))
            marker.setBrush(color)
            self.edges_count += 1
        if len(nodes) > 250:
            note = self.scene().addText(f"Showing 250 of {len(nodes)} nodes. Export the full graph as DOT.")
            note.setDefaultTextColor(QColor("#d9b77a"))
            note.setPos(self.scene().itemsBoundingRect().topLeft() - QPointF(0, 40))
        self.setSceneRect(self.scene().itemsBoundingRect().adjusted(-50, -50, 50, 50))
        self.fit_graph()

    def select_address(self, address: int):
        for candidate, item in self.nodes.items():
            item.setSelected(candidate == address)
