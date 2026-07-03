import os
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget


class RegionSelector(QWidget):
    region_selected = Signal(object)
    region_previewing = Signal(object)

    _VALID_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.pdf'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._scaled = None
        self._scale_x = 1.0
        self._scale_y = 1.0
        self._offset_x = 0
        self._offset_y = 0

        self._drag_start = None
        self._drag_cur = None
        self._dragging = False

        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAcceptDrops(True)

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self._drag_start = self._drag_cur = None
        self._recalc_scale()
        self.update()

    def has_image(self) -> bool:
        return self._pixmap is not None

    def clear_selection(self):
        self._drag_start = self._drag_cur = None
        self.update()

    def _recalc_scale(self):
        if not self._pixmap:
            return
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        if pw == 0 or ph == 0 or ww == 0 or wh == 0:
            return
        scale = min(ww / pw, wh / ph)
        self._scale_x = self._scale_y = scale
        sw = int(pw * scale)
        sh = int(ph * scale)
        self._offset_x = (ww - sw) // 2
        self._offset_y = (wh - sh) // 2
        self._scaled = self._pixmap.scaled(
            sw, sh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _widget_to_image(self, p: QPoint) -> QPoint:
        if not self._pixmap:
            return p
        x = (p.x() - self._offset_x) / self._scale_x
        y = (p.y() - self._offset_y) / self._scale_y
        x = max(0.0, min(float(self._pixmap.width()), x))
        y = max(0.0, min(float(self._pixmap.height()), y))
        return QPoint(int(x), int(y))

    def _sel_widget_rect(self) -> QRect | None:
        if not (self._drag_start and self._drag_cur):
            return None
        x1, y1 = self._drag_start.x(), self._drag_start.y()
        x2, y2 = self._drag_cur.x(), self._drag_cur.y()
        return QRect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        painter.fillRect(self.rect(), QColor('#F1F5F9'))

        if not self._scaled:
            painter.setPen(QColor('#94A3B8'))
            painter.setFont(QFont('Microsoft YaHei', 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             '拖拽图片 / PDF 到此处\n或点击「选择文件」')
            return

        painter.drawPixmap(self._offset_x, self._offset_y, self._scaled)

        rect = self._sel_widget_rect()
        if rect and rect.width() > 2 and rect.height() > 2:
            painter.fillRect(rect, QColor(59, 130, 246, 35))
            painter.setPen(QPen(QColor('#2563EB'), 1.5, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(QBrush(QColor('#2563EB')))
            painter.setPen(Qt.PenStyle.NoPen)
            for cx, cy in [
                (rect.left(), rect.top()), (rect.right(), rect.top()),
                (rect.left(), rect.bottom()), (rect.right(), rect.bottom()),
            ]:
                painter.drawRect(cx - 3, cy - 3, 6, 6)
            if self._pixmap:
                p1 = self._widget_to_image(self._drag_start)
                p2 = self._widget_to_image(self._drag_cur)
                w_px = abs(p2.x() - p1.x())
                h_px = abs(p2.y() - p1.y())
                label = f'{w_px} x {h_px}'
                lx = rect.right() + 4
                ly = rect.bottom() + 4
                painter.setPen(QColor('#1D4ED8'))
                painter.setFont(QFont('Consolas', 10))
                painter.drawText(lx, ly + 12, label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap:
            self._drag_start = event.position().toPoint()
            self._drag_cur = None
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._drag_cur = event.position().toPoint()
            self.update()
            if self._drag_start and self._drag_cur:
                p1 = self._widget_to_image(self._drag_start)
                p2 = self._widget_to_image(self._drag_cur)
                rect = QRect(
                    min(p1.x(), p2.x()), min(p1.y(), p2.y()),
                    abs(p2.x() - p1.x()), abs(p2.y() - p1.y()),
                )
                if rect.width() > 4 and rect.height() > 4:
                    self.region_previewing.emit(rect)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._drag_cur = event.position().toPoint()
            self.update()
            if self._drag_start and self._drag_cur:
                p1 = self._widget_to_image(self._drag_start)
                p2 = self._widget_to_image(self._drag_cur)
                rect = QRect(
                    min(p1.x(), p2.x()), min(p1.y(), p2.y()),
                    abs(p2.x() - p1.x()), abs(p2.y() - p1.y()),
                )
                if rect.width() > 4 and rect.height() > 4:
                    self.region_selected.emit(rect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalc_scale()
        self.update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            ext = os.path.splitext(e.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in self._VALID_EXTS:
                e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.parent()._load_image(urls[0].toLocalFile())
            e.acceptProposedAction()
