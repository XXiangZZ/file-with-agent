"""
Excel 批量导入/编辑/导出页面 — v4
核心改进方向：「批量导入后快速核查修改」

UX 改进清单：
  1. 导入体验：文件选择后立刻预览行数/列数确认，支持拖拽高亮
  2. 表格导航：方向键在单元格间移动，Tab/Shift+Tab 跨行跳转，F2 进入编辑
  3. 批量操作：多选后状态栏显示「已选 N 行」并提供快捷操作浮条
  4. 内联差异高亮：修改前/后值可 Hover 查看，颜色语义统一
  5. 实时字段验证：空值/超长/格式错误用颜色区分，不弹窗
  6. 状态通知：Toast 系统替代阻塞式 MessageBox（成功/失败/进度）
  7. OCR 改为独立浮窗，不占用主界面空间，仅在需要时唤起
  8. 撤销/重做：每次操作节点可回退，历史栈最大 50 步
  9. 导出：显示实际写入行数，导出后自动清除修改标记
 10. 空状态：明确引导，减少认知负担
"""

from __future__ import annotations

import copy
import os
import re
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox,
    QAbstractItemView, QHeaderView, QFrame, QLineEdit,
    QStatusBar, QSizePolicy, QApplication, QMenu, QScrollArea,
    QTextEdit, QProgressBar, QSplitter, QDialog, QGraphicsOpacityEffect,
    QToolButton, QComboBox, QListView,
)
from PySide6.QtCore import (
    Qt, QThread, Signal, QPoint, QPropertyAnimation, QEasingCurve,
    QTimer, QRect, QParallelAnimationGroup, QMutex, QMutexLocker,
)
from PySide6.QtGui import (
    QColor, QKeySequence, QDragEnterEvent, QDropEvent, QPixmap,
    QPainter, QPen, QBrush, QFont, QAction,
)

from ui.components.ocr.ocr_worker import OCRWorker
from ui.components.ocr.region_selector import RegionSelector
from ui.components.ocr.ocr_dialog import OCRDialog


# ─────────────────────────────────────────────────────────────────────────────
#  Toast 通知系统（替代阻塞式弹窗）
# ─────────────────────────────────────────────────────────────────────────────

class Toast(QWidget):
    """非阻塞式通知条，自动消失"""

    STYLE_SUCCESS = ("background:#065F46; color:#D1FAE5;", "✓")
    STYLE_ERROR   = ("background:#7F1D1D; color:#FECACA;", "✕")
    STYLE_INFO    = ("background:#1E3A5F; color:#BFDBFE;", "ℹ")
    STYLE_WARNING = ("background:#78350F; color:#FDE68A;", "⚠")

    def __init__(self, parent: QWidget, message: str, style=None, duration=3000):
        super().__init__(parent)
        if style is None:
            style = self.STYLE_INFO
        css, icon = style
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedHeight(40)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)

        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet("font-size:16px; background:transparent;")
        lay.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet("font-size:13px; background:transparent; font-family:'Microsoft YaHei';")
        lay.addWidget(msg_lbl)

        self.setStyleSheet(f"""
            QWidget {{
                {css}
                border-radius: 8px;
                font-family: "Microsoft YaHei";
            }}
        """)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._opacity_effect.setOpacity(0.0)

        self._reposition(parent)
        self.show()

        # 淡入
        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.start()

        # 自动消失
        QTimer.singleShot(duration, self._start_fade_out)

    def _reposition(self, parent: QWidget):
        # 居中到父窗口顶部
        pw = parent.width()
        self.setFixedWidth(min(pw - 80, 500))
        x = (pw - self.width()) // 2
        self.move(parent.mapToGlobal(QPoint(x, 16)))

    def _start_fade_out(self):
        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.finished.connect(self.close)
        self._fade_out.start()


class ToastManager:
    """管理 Toast 队列，避免叠加"""

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._toasts: list[Toast] = []

    def show(self, message: str, style=None, duration=3000):
        # 清除已关闭的 toast
        self._toasts = [t for t in self._toasts if t.isVisible()]
        t = Toast(self._parent, message, style or Toast.STYLE_INFO, duration)
        # 竖向错开
        offset = len(self._toasts) * 50
        pos = t.pos()
        t.move(pos.x(), pos.y() + offset)
        self._toasts.append(t)

    def success(self, msg: str, duration=2500):
        self.show(msg, Toast.STYLE_SUCCESS, duration)

    def error(self, msg: str, duration=4000):
        self.show(msg, Toast.STYLE_ERROR, duration)

    def info(self, msg: str, duration=2000):
        self.show(msg, Toast.STYLE_INFO, duration)

    def warning(self, msg: str, duration=3000):
        self.show(msg, Toast.STYLE_WARNING, duration)


# ─────────────────────────────────────────────────────────────────────────────
#  浮动批量操作工具条（多选行时出现）
# ─────────────────────────────────────────────────────────────────────────────

class _FloatActionBar(QWidget):
    """选中多行时显示在表格上方的操作浮条"""

    delete_requested  = Signal()
    copy_requested    = Signal()
    clear_requested   = Signal()
    dismiss_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("floatBar")
        self.setFixedHeight(38)
        self.hide()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(6)

        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("floatBarCount")
        lay.addWidget(self._count_lbl)

        lay.addWidget(self._sep())

        for text, obj, sig in [
            ("⧉ 复制行",   "floatBarBtn", self.copy_requested),
            ("✕ 清空内容", "floatBarBtn", self.clear_requested),
            ("🗑 删除行",   "floatBarBtnDanger", self.delete_requested),
        ]:
            b = QPushButton(text)
            b.setObjectName(obj)
            b.setFixedHeight(28)
            b.clicked.connect(sig)
            lay.addWidget(b)

        lay.addStretch()

        close = QPushButton("取消选择")
        close.setObjectName("floatBarDismiss")
        close.setFixedHeight(28)
        close.clicked.connect(self.dismiss_requested)
        lay.addWidget(close)

    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedSize(1, 20)
        f.setObjectName("floatBarSep")
        return f

    def update_count(self, n: int):
        self._count_lbl.setText(f"已选 {n} 行")
        self.setVisible(n > 0)


# ─────────────────────────────────────────────────────────────────────────────
#  可编辑表格 — 全面增强键盘导航和视觉反馈
# ─────────────────────────────────────────────────────────────────────────────

class _EditableTable(QTableWidget):
    data_changed     = Signal()
    selection_changed = Signal(int)   # 选中行数

    C_EVEN     = QColor("#FFFFFF")
    C_ODD      = QColor("#F8FAFC")
    C_MODIFIED = QColor("#FFFBEB")   # 已修改：淡黄
    C_NEW      = QColor("#F0FDF4")   # 新增行：淡绿
    C_ACTIVE   = QColor("#EFF6FF")   # 当前行：淡蓝
    C_ERROR    = QColor("#FEF2F2")   # 校验错误：淡红

    def __init__(self):
        super().__init__()
        self._modified: set[int] = set()
        self._new_rows: set[int] = set()
        self._errors:   dict[tuple[int,int], str] = {}   # (row,col) -> 错误说明
        self._active_row = -1
        self._original_values: dict[tuple[int,int], str] = {}  # 记录原始值

        self.setEditTriggers(
            QAbstractItemView.EditTrigger.AnyKeyPressed |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().sectionDoubleClicked.connect(self._on_header_dclick)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(32)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_menu)
        self.setAlternatingRowColors(False)
        self.setAcceptDrops(False)
        self.setTabKeyNavigation(False)  # 手动控制 Tab

        self.itemChanged.connect(self._on_item_changed)
        self.currentCellChanged.connect(self._on_current_cell_changed)
        self.itemSelectionChanged.connect(self._on_selection_changed)

        self._header_editors: dict[int, QLineEdit] = {}

    # ── 列头内联重命名 ────────────────────────────────────────────────────────

    def _on_header_dclick(self, col: int):
        if col in self._header_editors:
            return
        cur = self.horizontalHeaderItem(col)
        rect = self.horizontalHeader().sectionViewportPosition(col)
        w = self.horizontalHeader().sectionSize(col)
        h = self.horizontalHeader().height()
        ed = QLineEdit(cur.text() if cur else "", self)
        ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ed.selectAll()
        ed.setStyleSheet("""
            QLineEdit {
                background:#1E3A5F; color:white;
                border:2px solid #60A5FA; border-radius:0;
                font-size:12px; font-weight:bold;
                font-family:"Microsoft YaHei"; padding:0 4px;
            }
        """)
        ed.setGeometry(rect, 0, w, h)
        ed.returnPressed.connect(lambda: self._commit_header(col, ed))
        ed.editingFinished.connect(lambda: self._commit_header(col, ed))
        self._header_editors[col] = ed
        ed.show()
        ed.setFocus()

    def _commit_header(self, col: int, ed: QLineEdit):
        name = ed.text().strip()
        if name:
            self.setHorizontalHeaderItem(col, QTableWidgetItem(name))
            self.data_changed.emit()
        ed.deleteLater()
        self._header_editors.pop(col, None)

    # ── 键盘导航（核心改进） ──────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        editing = self.state() == QAbstractItemView.State.EditingState

        # Tab / Shift+Tab：在单元格间横向移动（跨行）
        if key == Qt.Key.Key_Tab and not editing:
            self._move_next()
            return
        if key == Qt.Key.Key_Backtab and not editing:
            self._move_prev()
            return

        # Enter / Return：向下移动（类似 Excel）
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not editing:
            r, c = self.currentRow(), self.currentColumn()
            nr = r + 1
            if nr >= self.rowCount():
                self._insert_row(self.rowCount())
            self.setCurrentCell(nr, c)
            return

        # Escape：退出编辑，保持选中
        if key == Qt.Key.Key_Escape and editing:
            self.closePersistentEditor(self.currentItem())
            return

        # F2：强制进入编辑模式
        if key == Qt.Key.Key_F2 and not editing:
            self.editItem(self.currentItem())
            return

        # Delete：清空内容（不弹窗）
        if key == Qt.Key.Key_Delete and not editing:
            rows = set()
            self.blockSignals(True)
            for item in self.selectedItems():
                item.setText("")
                rows.add(item.row())
            self.blockSignals(False)
            for r in rows:
                self._mark_mod(r)
                self._refresh_row_color(r)
            self.data_changed.emit()
            return

        # Ctrl+Z / Ctrl+Y handled by parent
        if event.matches(QKeySequence.StandardKey.Undo):
            event.ignore()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            event.ignore()
            return

        # Ctrl+C：复制选中内容到剪贴板
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_to_clipboard()
            return

        # Ctrl+V：粘贴
        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste()
            return

        # Ctrl+A：全选
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.selectAll()
            return

        super().keyPressEvent(event)

    def _move_next(self):
        r, c = self.currentRow(), self.currentColumn()
        c += 1
        if c >= self.columnCount():
            c = 0
            r += 1
            if r >= self.rowCount():
                r = 0
        self.setCurrentCell(r, c)

    def _move_prev(self):
        r, c = self.currentRow(), self.currentColumn()
        c -= 1
        if c < 0:
            c = self.columnCount() - 1
            r -= 1
            if r < 0:
                r = self.rowCount() - 1
        self.setCurrentCell(r, c)

    # ── 选择变化 ─────────────────────────────────────────────────────────────

    def _on_selection_changed(self):
        rows = {i.row() for i in self.selectedIndexes()}
        self.selection_changed.emit(len(rows))

    def _on_current_cell_changed(self, cr, cc, pr, pc):
        if pr >= 0 and pr != cr:
            self._refresh_row_color(pr)
        self._active_row = cr
        if cr >= 0:
            for c in range(self.columnCount()):
                item = self.item(cr, c)
                if item:
                    item.setBackground(self.C_ACTIVE)

    # ── 右键菜单 ─────────────────────────────────────────────────────────────

    def _show_ctx_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background:white; border:1px solid #E5E7EB;
                border-radius:8px; padding:4px;
                font-family:"Microsoft YaHei"; font-size:12px;
            }
            QMenu::item { padding:7px 16px; border-radius:5px; color:#374151; }
            QMenu::item:selected { background:#EFF6FF; color:#1D4ED8; }
            QMenu::separator { height:1px; background:#F3F4F6; margin:3px 8px; }
        """)
        has = bool(self.selectedItems())
        rows = sorted({i.row() for i in self.selectedIndexes()})
        
        current_item = self.itemAt(pos)
        has_single_cell = current_item is not None and len(rows) == 1 and len({i.column() for i in self.selectedIndexes()}) == 1

        a_ins_above = menu.addAction("⬆  在上方插入行")
        a_ins_below = menu.addAction("⬇  在下方插入行")
        a_dup       = menu.addAction("⧉  复制此行")
        menu.addSeparator()
        
        a_view_full = menu.addAction("👁  查看完整内容")
        a_view_full.setEnabled(has_single_cell)
        
        menu.addSeparator()
        a_clear     = menu.addAction("✕  清空选中单元格")
        menu.addSeparator()
        a_del       = menu.addAction("🗑  删除选中行")

        for a in (a_dup, a_clear, a_del):
            a.setEnabled(has)

        act = menu.exec(self.viewport().mapToGlobal(pos))
        if act == a_ins_above:   self._insert_row(rows[0] if rows else self.rowCount())
        elif act == a_ins_below: self._insert_row((rows[-1]+1) if rows else self.rowCount())
        elif act == a_dup:       self._dup_row(rows[0] if rows else -1)
        elif act == a_view_full: self._show_full_content(current_item)
        elif act == a_clear:
            self.blockSignals(True)
            for item in self.selectedItems():
                item.setText("")
            self.blockSignals(False)
            for r in rows:
                self._mark_mod(r)
                self._refresh_row_color(r)
            self.data_changed.emit()
        elif act == a_del:
            self._delete_rows(rows)

    # ── 行操作 ────────────────────────────────────────────────────────────────

    def _insert_row(self, pos: int):
        self.blockSignals(True)
        self.insertRow(pos)
        self._modified = {r+1 if r >= pos else r for r in self._modified}
        self._new_rows  = {r+1 if r >= pos else r for r in self._new_rows}
        self._new_rows.add(pos)
        for c in range(self.columnCount()):
            item = QTableWidgetItem("")
            item.setBackground(self.C_NEW)
            self.setItem(pos, c, item)
        self.blockSignals(False)
        self.data_changed.emit()

    def add_empty_row(self):
        self._insert_row(self.rowCount())
        self.scrollToBottom()
        self.setCurrentCell(self.rowCount()-1, 0)

    def _dup_row(self, src: int):
        if src < 0:
            return
        dst = self.rowCount()
        self.blockSignals(True)
        self.insertRow(dst)
        self._new_rows.add(dst)
        for c in range(self.columnCount()):
            si = self.item(src, c)
            ni = QTableWidgetItem(si.text() if si else "")
            ni.setBackground(self.C_NEW)
            self.setItem(dst, c, ni)
        self.blockSignals(False)
        self.scrollToBottom()
        self.data_changed.emit()

    def _delete_rows(self, rows: list[int]):
        for r in sorted(rows, reverse=True):
            self.removeRow(r)
            self._modified.discard(r)
            self._new_rows.discard(r)
        self.data_changed.emit()

    def delete_selected_rows(self):
        self._delete_rows(sorted({i.row() for i in self.selectedIndexes()}))

    def _show_full_content(self, item):
        """显示单元格的完整内容"""
        if item is None:
            return
        row, col = item.row(), item.column()
        content = item.text()
        headers = self.get_headers()
        col_name = headers[col] if col < len(headers) else f"列{col+1}"
        title = f"第 {row+1} 行 - {col_name}"
        dlg = _FullContentDialog(title, content, self.window())
        dlg.exec()

    def clear_selected_content(self):
        rows = set()
        self.blockSignals(True)
        for item in self.selectedItems():
            item.setText("")
            rows.add(item.row())
        self.blockSignals(False)
        for r in rows:
            self._mark_mod(r)
            self._refresh_row_color(r)
        self.data_changed.emit()

    # ── 改动追踪 ─────────────────────────────────────────────────────────────

    def _mark_mod(self, row: int):
        if row not in self._new_rows:
            self._modified.add(row)

    def _on_item_changed(self, item: QTableWidgetItem):
        row = item.row()
        self._mark_mod(row)
        # 实时验证（空值标红边框，不弹窗）
        self._validate_item(item)
        if row != self._active_row:
            self._refresh_row_color(row)
        self.data_changed.emit()

    def _validate_item(self, item: QTableWidgetItem):
        """实时校验：过长内容标黄，格式错误标红"""
        row, col = item.row(), item.column()
        text = item.text()
        key = (row, col)
        if len(text) > 500:
            self._errors[key] = "内容过长（超过500字）"
            item.setToolTip(f"⚠ {self._errors[key]}")
            item.setForeground(QColor("#B45309"))
        else:
            self._errors.pop(key, None)
            item.setToolTip("")
            item.setForeground(QColor("#374151"))

    # ── 颜色管理 ─────────────────────────────────────────────────────────────

    def _refresh_row_color(self, row: int):
        if row == self._active_row:      color = self.C_ACTIVE
        elif row in self._new_rows:      color = self.C_NEW
        elif row in self._modified:      color = self.C_MODIFIED
        else: color = self.C_EVEN if row % 2 == 0 else self.C_ODD
        for c in range(self.columnCount()):
            item = self.item(row, c)
            if item:
                item.setBackground(color)

    def refresh_all_colors(self):
        self.blockSignals(True)
        for r in range(self.rowCount()):
            self._refresh_row_color(r)
        self.blockSignals(False)

    def clear_change_marks(self):
        self._modified.clear()
        self._new_rows.clear()
        self.refresh_all_colors()

    # ── 剪贴板 ───────────────────────────────────────────────────────────────

    def _copy_to_clipboard(self):
        rows = sorted({i.row() for i in self.selectedIndexes()})
        cols = sorted({i.column() for i in self.selectedIndexes()})
        if not rows:
            return
        lines = []
        for r in rows:
            cells = []
            for c in cols:
                item = self.item(r, c)
                cells.append(item.text() if item else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def _paste(self):
        text = QApplication.clipboard().text()
        if not text:
            return
        sr = max(self.currentRow(), 0)
        sc = max(self.currentColumn(), 0)
        self.blockSignals(True)
        for dr, line in enumerate(text.strip("\n").split("\n")):
            row = sr + dr
            if row >= self.rowCount():
                self.insertRow(row)
                self._new_rows.add(row)
                for c in range(self.columnCount()):
                    self.setItem(row, c, QTableWidgetItem(""))
            for dc, val in enumerate(line.split("\t")):
                col = sc + dc
                if col < self.columnCount():
                    self.setItem(row, col, QTableWidgetItem(val))
            self._mark_mod(row)
        self.blockSignals(False)
        self.refresh_all_colors()
        self.data_changed.emit()

    # ── 数据读取 ─────────────────────────────────────────────────────────────

    def get_headers(self) -> list[str]:
        return [
            (self.horizontalHeaderItem(c).text()
             if self.horizontalHeaderItem(c) else f"列{c+1}")
            for c in range(self.columnCount())
        ]

    def get_all_data(self) -> list[list[str]]:
        return [
            [(self.item(r, c).text() if self.item(r, c) else "")
             for c in range(self.columnCount())]
            for r in range(self.rowCount())
        ]

    @property
    def modified_count(self) -> int:
        return len(self._modified)

    @property
    def new_count(self) -> int:
        return len(self._new_rows)

    @property
    def error_count(self) -> int:
        return len(self._errors)


# ─────────────────────────────────────────────────────────────────────────────
#  Excel 后台加载线程
# ─────────────────────────────────────────────────────────────────────────────

class _ExcelLoader(QThread):
    finished = Signal(list, list)
    error    = Signal(str)
    progress = Signal(int)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            ext = os.path.splitext(self.path)[1].lower()
            if ext == ".csv":
                self._load_csv()
            else:
                self._load_xlsx()
        except Exception as e:
            self.error.emit(str(e))

    def _load_xlsx(self):
        import openpyxl
        wb = openpyxl.load_workbook(self.path, data_only=True)
        ws = wb.active
        rows_raw = list(ws.iter_rows(values_only=True))
        if not rows_raw:
            self.finished.emit([], [])
            return
        headers = [str(c) if c is not None else "" for c in rows_raw[0]]
        data, total = [], len(rows_raw) - 1
        for i, row in enumerate(rows_raw[1:], 1):
            data.append([str(c) if c is not None else "" for c in row])
            if i % 300 == 0:
                self.progress.emit(int(i / max(total, 1) * 90))
        self.progress.emit(100)
        self.finished.emit(headers, data)

    def _load_csv(self):
        import csv
        with open(self.path, encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.reader(f))
        if not rows:
            self.finished.emit([], [])
            return
        self.progress.emit(100)
        self.finished.emit(rows[0], rows[1:])


# ─────────────────────────────────────────────────────────────────────────────
#  OCR 工作线程
# ─────────────────────────────────────────────────────────────────────────────

class _OCRWorker(QThread):
    """
    OCR 识别线程，使用单例缓存的引擎：
      · 启动时探测可用引擎（只探测一次）
      · 识别时直接使用已缓存的引擎实例
      · 支持 CnOCR、PaddleOCR、EasyOCR、Tesseract
    """
    finished = Signal(str)
    error    = Signal(str)
    progress = Signal(str)

    # ── 单例缓存 ────────────────────────────────────────────────────────────
    _paddle_ocr = None       # PaddleOCR 单例
    _cnocr_ocr  = None       # CnOCR 单例
    _easy_reader = None       # EasyOCR reader 单例
    _tesseract_ok = False     # Tesseract 是否可用

    # ── 启动时探测结果 ──────────────────────────────────────────────────────
    _available_engine = None   # 当前可用的引擎名称
    _probe_done = False         # 是否已完成探测
    _probe_lock = QMutex()      # 探测锁，保证只探测一次

    @classmethod
    def _probe_available_engine(cls):
        """探测可用的OCR引擎（类方法，只在第一次识别前调用一次）"""
        with QMutexLocker(cls._probe_lock):
            if cls._probe_done:
                return

            engines = [
                ("CnOCR",    cls._try_init_cnocr),
                ("PaddleOCR",cls._try_init_paddle),
                ("EasyOCR",  cls._try_init_easyocr),
                ("Tesseract",cls._try_init_tesseract),
            ]

            for name, init_fn in engines:
                try:
                    if init_fn():
                        cls._available_engine = name
                        print(f"[OCR] 探测到可用引擎: {name}")
                        break
                except Exception as e:
                    print(f"[OCR] {name} 探测失败: {e}")
                    continue

            cls._probe_done = True
            if cls._available_engine is None:
                print("[OCR] 警告: 未探测到任何可用OCR引擎")

    @classmethod
    def _try_init_cnocr(cls) -> bool:
        """探测 CnOCR 是否可用"""
        try:
            from cnocr import CnOcr
            if cls._cnocr_ocr is None:
                cls._cnocr_ocr = CnOcr()
            return True
        except Exception:
            cls._cnocr_ocr = None
            return False

    @classmethod
    def _try_init_paddle(cls) -> bool:
        """探测 PaddleOCR 是否可用"""
        try:
            from paddleocr import PaddleOCR
            if cls._paddle_ocr is None:
                cls._paddle_ocr = PaddleOCR(lang='ch', use_angle_cls=True, show_log=False)
            return True
        except Exception:
            cls._paddle_ocr = None
            return False

    @classmethod
    def _try_init_easyocr(cls) -> bool:
        """探测 EasyOCR 是否可用"""
        try:
            import easyocr
            if cls._easy_reader is None:
                cls._easy_reader = easyocr.Reader(
                    ['ch_sim', 'en'],
                    gpu=False,
                    verbose=False,
                )
            return True
        except Exception:
            cls._easy_reader = None
            return False

    @classmethod
    def _try_init_tesseract(cls) -> bool:
        """探测 Tesseract 是否可用"""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            cls._tesseract_ok = True
            return True
        except Exception:
            cls._tesseract_ok = False
            return False

    def __init__(self, image_path: str):
        super().__init__()
        self.image_path = image_path

    def run(self):
        # 启动时探测可用引擎（只在第一次识别前触发）
        self._probe_available_engine()

        # 如果已经探测过且没有可用引擎，直接报错
        if _OCRWorker._probe_done and _OCRWorker._available_engine is None:
            self._emit_no_engine_error()
            return

        # 获取当前可用引擎
        engine_name = _OCRWorker._available_engine
        if not engine_name:
            engine_name = "CnOCR"  # 默认尝试 CnOCR

        self.progress.emit(f"使用 {engine_name} 识别中…")

        try:
            text = self._recognize_with_engine(engine_name)
            if text and text.strip():
                self.finished.emit(text.strip())
            else:
                # 引擎返回空，尝试其他引擎作为 fallback
                text = self._fallback_to_other_engines(engine_name)
                if text:
                    self.finished.emit(text.strip())
                else:
                    self.error.emit("⚠ 未识别到文字，请检查图片是否包含文字")
        except Exception as e:
            self._emit_error(e, engine_name)

    def _recognize_with_engine(self, engine_name: str) -> str | None:
        """使用指定引擎识别"""
        if engine_name == "CnOCR":
            return self._try_cnocr_cached()
        elif engine_name == "PaddleOCR":
            return self._try_paddle_cached()
        elif engine_name == "EasyOCR":
            return self._try_easyocr_cached()
        elif engine_name == "Tesseract":
            return self._try_tesseract_cached()
        return None

    def _fallback_to_other_engines(self, skip_engine: str) -> str | None:
        """尝试其他引擎作为 fallback"""
        engines = [
            ("CnOCR",    self._try_cnocr_cached),
            ("PaddleOCR",self._try_paddle_cached),
            ("EasyOCR",  self._try_easyocr_cached),
            ("Tesseract",self._try_tesseract_cached),
        ]

        for name, method in engines:
            if name == skip_engine:
                continue
            try:
                text = method()
                if text and text.strip():
                    self.progress.emit(f"回退到 {name} 成功")
                    return text
            except Exception:
                continue
        return None

    def _emit_no_engine_error(self):
        """发射无可用引擎的错误"""
        self.error.emit(
            "未找到可用的 OCR 引擎。\n\n"
            "请安装以下任一依赖（推荐首选）：\n\n"
            "1. CnOCR（推荐）:\n"
            "   pip install cnocr\n\n"
            "2. PaddleOCR:\n"
            "   pip install paddlepaddle paddleocr\n\n"
            "3. EasyOCR:\n"
            "   pip install easyocr\n\n"
            "4. Tesseract:\n"
            "   pip install pytesseract\n"
            "   并安装 Tesseract 程序"
        )

    def _emit_error(self, e: Exception, engine_name: str):
        """发射错误信息（记录完整错误日志）"""
        error_msg = str(e)
        # 记录完整错误日志
        print(f"[OCR] {engine_name} 识别异常: {error_msg}")

        # 判断是否是资源问题
        if any(x in error_msg.lower() for x in ["memory", "句柄", "资源", "临时文件"]):
            self.error.emit(
                f"{engine_name} 资源不足，可能是模型重复加载导致。\n"
                f"错误: {error_msg[:100]}...\n\n"
                f"建议：关闭 OCR 窗口重新打开，或重启程序"
            )
        else:
            self.error.emit(f"{engine_name} 识别失败: {error_msg}")

    # ── 缓存的引擎识别方法 ──────────────────────────────────────────────────

    def _try_cnocr_cached(self) -> str | None:
        """使用 CnOCR 单例识别"""
        try:
            if _OCRWorker._cnocr_ocr is None:
                from cnocr import CnOcr
                _OCRWorker._cnocr_ocr = CnOcr()

            result = _OCRWorker._cnocr_ocr.ocr(self.image_path)
            if not result:
                return None

            lines = []
            for item in result:
                if isinstance(item, dict):
                    text = item.get('text', '')
                    if text:
                        lines.append(text)
                elif isinstance(item, list) and len(item) > 1:
                    text = item[1] if isinstance(item[1], str) else str(item[1])
                    if text:
                        lines.append(text)
                elif isinstance(item, str):
                    lines.append(item)

            return "\n".join(lines) if lines else None
        except Exception as e:
            import traceback
            print(f"[OCR] CnOCR 详细错误: {e}")
            print(f"[OCR] CnOCR 堆栈: {traceback.format_exc()}")
            # 清除单例，下次尝试重新初始化
            _OCRWorker._cnocr_ocr = None
            raise

    def _try_paddle_cached(self) -> str | None:
        """使用 PaddleOCR 单例识别"""
        if _OCRWorker._paddle_ocr is None:
            from paddleocr import PaddleOCR
            _OCRWorker._paddle_ocr = PaddleOCR(lang='ch', use_angle_cls=True, show_log=False)

        result = _OCRWorker._paddle_ocr.ocr(self.image_path, cls=True)
        if not result:
            return None

        lines = []
        if isinstance(result, list):
            for page in result:
                if isinstance(page, list):
                    for item in page:
                        if isinstance(item, list) and len(item) > 1:
                            if isinstance(item[1], tuple):
                                text = item[1][0]
                            elif isinstance(item[1], str):
                                text = item[1]
                            else:
                                continue
                            if text:
                                lines.append(text)

        return "\n".join(lines) if lines else None

    def _try_easyocr_cached(self) -> str | None:
        """使用 EasyOCR 单例识别"""
        if _OCRWorker._easy_reader is None:
            import easyocr
            _OCRWorker._easy_reader = easyocr.Reader(
                ['ch_sim', 'en'],
                gpu=False,
                verbose=False,
            )

        result = _OCRWorker._easy_reader.readtext(self.image_path)
        if not result:
            return None

        lines = []
        for item in result:
            if len(item) > 1 and item[1]:
                text = item[1].strip()
                if text:
                    lines.append(text)

        return "\n".join(lines) if lines else None

    def _try_tesseract_cached(self) -> str | None:
        """使用 Tesseract 识别"""
        if not _OCRWorker._tesseract_ok:
            from PIL import Image
            import pytesseract
            # 再次尝试初始化
            try:
                pytesseract.get_tesseract_version()
                _OCRWorker._tesseract_ok = True
            except Exception:
                return None

        from PIL import Image
        import pytesseract

        img = Image.open(self.image_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        text = pytesseract.image_to_string(
            img,
            lang='chi_sim+eng',
            config='--psm 6'
        )
        return text.strip() if text.strip() else None


# ─────────────────────────────────────────────────────────────────────────────
#  框选图片识别控件
# ─────────────────────────────────────────────────────────────────────────────

class _RegionSelector(QWidget):
    """
    图片显示 + 鼠标拖拽框选：
      · 左键拖拽 → 绘制橡皮筋矩形（蓝色半透明）
      · 松开鼠标 → 发射 region_selected(QRect)，坐标已映射回原图像素
      · 支持拖拽/放下图片文件
      · 显示尺寸提示（框选时右下角显示宽×高）
    """
    region_selected   = Signal(object)   # QRect，原图像素坐标
    region_previewing = Signal(object)   # 拖拽过程中实时预览

    _VALID_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".pdf"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap:    QPixmap | None = None   # 原始图片
        self._scaled:    QPixmap | None = None   # 缩放后显示用
        self._scale_x  = 1.0
        self._scale_y  = 1.0
        self._offset_x = 0
        self._offset_y = 0

        self._drag_start: QPoint | None = None
        self._drag_cur:   QPoint | None = None
        self._dragging    = False

        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAcceptDrops(True)

    # ── 公共接口 ─────────────────────────────────────────────────────────────

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._drag_start = self._drag_cur = None
        self._recalc_scale()
        self.update()

    def has_image(self) -> bool:
        return self._pixmap is not None

    def clear_selection(self):
        self._drag_start = self._drag_cur = None
        self.update()

    # ── 内部 ────────────────────────────────────────────────────────────────

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
        """控件坐标 → 原图像素坐标（clamp 在图像范围内）"""
        if not self._pixmap:
            return p
        x = (p.x() - self._offset_x) / self._scale_x
        y = (p.y() - self._offset_y) / self._scale_y
        x = max(0.0, min(float(self._pixmap.width()),  x))
        y = max(0.0, min(float(self._pixmap.height()), y))
        return QPoint(int(x), int(y))

    def _sel_widget_rect(self) -> QRect | None:
        if not (self._drag_start and self._drag_cur):
            return None
        x1, y1 = self._drag_start.x(), self._drag_start.y()
        x2, y2 = self._drag_cur.x(),   self._drag_cur.y()
        return QRect(min(x1,x2), min(y1,y2), abs(x2-x1), abs(y2-y1))

    # ── 绘制 ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # 背景
        painter.fillRect(self.rect(), QColor("#F1F5F9"))

        if not self._scaled:
            painter.setPen(QColor("#94A3B8"))
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "拖拽图片 / PDF 到此处\n或点击「选择文件」")
            return

        # 图片
        painter.drawPixmap(self._offset_x, self._offset_y, self._scaled)

        # 框选矩形
        rect = self._sel_widget_rect()
        if rect and rect.width() > 2 and rect.height() > 2:
            # 半透明蓝色填充
            painter.fillRect(rect, QColor(59, 130, 246, 35))
            # 实线边框
            painter.setPen(QPen(QColor("#2563EB"), 1.5, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            # 四角控制点
            painter.setBrush(QBrush(QColor("#2563EB")))
            painter.setPen(Qt.PenStyle.NoPen)
            for cx, cy in [
                (rect.left(), rect.top()), (rect.right(), rect.top()),
                (rect.left(), rect.bottom()), (rect.right(), rect.bottom()),
            ]:
                painter.drawRect(cx - 3, cy - 3, 6, 6)
            # 右下角尺寸标注
            if self._pixmap:
                p1 = self._widget_to_image(self._drag_start)
                p2 = self._widget_to_image(self._drag_cur)
                w_px = abs(p2.x() - p1.x())
                h_px = abs(p2.y() - p1.y())
                label = f"{w_px} × {h_px}"
                lx = rect.right() + 4
                ly = rect.bottom() + 4
                painter.setPen(QColor("#1D4ED8"))
                painter.setFont(QFont("Consolas", 10))
                painter.drawText(lx, ly + 12, label)

    # ── 鼠标 ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap:
            self._drag_start = event.position().toPoint()
            self._drag_cur   = None
            self._dragging   = True
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

    # ── 拖拽文件 ─────────────────────────────────────────────────────────────

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            ext = os.path.splitext(e.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in self._VALID_EXTS:
                e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            # 向上冒泡给 OCRDialog 处理
            self.parent()._load_image(urls[0].toLocalFile())


# ─────────────────────────────────────────────────────────────────────────────
#  OCR 浮窗（带框选识别）— v5 重写
# ─────────────────────────────────────────────────────────────────────────────


class _ImportPreviewDialog(QDialog):
    """
    文件选择后先预览：显示行数/列数/列名，
    用户确认后再正式载入，避免误操作覆盖现有数据。
    """
    confirmed = Signal(str)   # 路径

    def __init__(self, path: str, headers: list[str], row_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认导入")
        self.setFixedWidth(440)
        self._path = path

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        # 文件信息
        fname = os.path.basename(path)
        size_kb = os.path.getsize(path) // 1024
        info_lbl = QLabel(f"<b>{fname}</b>  ({size_kb} KB)")
        info_lbl.setStyleSheet("font-family:'Microsoft YaHei'; font-size:14px; color:#1E293B;")
        lay.addWidget(info_lbl)

        # 统计
        stats = QWidget()
        stats.setStyleSheet("background:#F1F5F9; border-radius:8px;")
        s_lay = QHBoxLayout(stats)
        s_lay.setContentsMargins(14, 10, 14, 10)
        s_lay.setSpacing(24)
        for label, val in [("数据行", str(row_count)), ("列数", str(len(headers)))]:
            col = QVBoxLayout()
            v = QLabel(val)
            v.setStyleSheet("font-size:24px; font-weight:bold; color:#1D4ED8; font-family:'Microsoft YaHei';")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l = QLabel(label)
            l.setStyleSheet("font-size:11px; color:#6B7280; font-family:'Microsoft YaHei';")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(v)
            col.addWidget(l)
            s_lay.addLayout(col)
        lay.addWidget(stats)

        # 列名列表（最多显示8个）
        col_lbl = QLabel("列名：" + "、".join(headers[:8]) + ("…" if len(headers) > 8 else ""))
        col_lbl.setWordWrap(True)
        col_lbl.setStyleSheet("font-size:12px; color:#6B7280; font-family:'Microsoft YaHei';")
        lay.addWidget(col_lbl)

        # 按钮
        btn_row = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.setFixedHeight(34)
        cancel.setStyleSheet("""
            QPushButton {
                background:#F1F5F9; border:1px solid #E2E8F0;
                border-radius:7px; font-size:13px;
                font-family:"Microsoft YaHei"; color:#6B7280;
            }
            QPushButton:hover { background:#E2E8F0; }
        """)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        ok = QPushButton(f"确认导入  {row_count} 行")
        ok.setFixedHeight(34)
        ok.setStyleSheet("""
            QPushButton {
                background:#3B82F6; border:none;
                border-radius:7px; font-size:13px; font-weight:bold;
                font-family:"Microsoft YaHei"; color:white; padding:0 20px;
            }
            QPushButton:hover { background:#2563EB; }
        """)
        ok.clicked.connect(lambda: (self.confirmed.emit(self._path), self.accept()))
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)


# ─────────────────────────────────────────────────────────────────────────────
#  查看完整内容对话框
# ─────────────────────────────────────────────────────────────────────────────

class _FullContentDialog(QDialog):
    """
    用于显示单元格的完整内容，支持长文本查看和复制
    """
    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)
        self.resize(700, 500)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(12)

        # 统计信息
        info_bar = QWidget()
        info_bar.setObjectName("fullContentInfo")
        info_lay = QHBoxLayout(info_bar)
        info_lay.setContentsMargins(10, 6, 10, 6)
        
        char_count = len(content)
        line_count = content.count('\n') + 1
        info_lbl = QLabel(f"共 {char_count} 字符  |  {line_count} 行")
        info_lbl.setObjectName("fullContentInfoLabel")
        info_lay.addWidget(info_lbl)
        info_lay.addStretch()
        
        copy_btn = QPushButton("📋 复制全部")
        copy_btn.setObjectName("fullContentCopyBtn")
        copy_btn.setFixedHeight(26)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(content))
        info_lay.addWidget(copy_btn)
        
        lay.addWidget(info_bar)

        # 内容显示区域
        self._content_edit = QTextEdit()
        self._content_edit.setObjectName("fullContentEdit")
        self._content_edit.setPlainText(content)
        self._content_edit.setReadOnly(True)
        self._content_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        lay.addWidget(self._content_edit, stretch=1)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(32)
        close_btn.setObjectName("fullContentCloseBtn")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._apply_style()

    def _copy_to_clipboard(self, text: str):
        QApplication.clipboard().setText(text)
        Toast(self.parent(), "已复制到剪贴板", Toast.STYLE_SUCCESS)

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background:#FFFFFF; font-family:"Microsoft YaHei"; }
            
            QWidget#fullContentInfo {
                background:#F8FAFC; border:1px solid #E9ECF0; border-radius:8px;
            }
            QLabel#fullContentInfoLabel { font-size:12px; color:#6B7280; }
            
            QPushButton#fullContentCopyBtn {
                background:#EFF6FF; border:1px solid #93C5FD; border-radius:6px;
                font-size:12px; color:#1D4ED8; padding:0 12px;
            }
            QPushButton#fullContentCopyBtn:hover { background:#DBEAFE; }
            
            QTextEdit#fullContentEdit {
                border:1px solid #E2E8F0; border-radius:8px;
                padding:12px; font-size:13px; color:#374151;
                background:white; font-family:"Microsoft YaHei";
                line-height:1.6;
            }
            
            QPushButton#fullContentCloseBtn {
                background:#3B82F6; border:none; border-radius:7px;
                font-size:13px; font-weight:bold; color:white;
                padding:0 20px;
            }
            QPushButton#fullContentCloseBtn:hover { background:#2563EB; }
        """)


# ─────────────────────────────────────────────────────────────────────────────
#  快捷键提示面板（帮助页，按 ? 或 F1 唤起）
# ─────────────────────────────────────────────────────────────────────────────

class _ShortcutHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("键盘快捷键")
        self.setFixedSize(420, 360)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        shortcuts = [
            ("方向键",          "在单元格间移动"),
            ("Tab / Shift+Tab", "向右 / 向左移动"),
            ("Enter",           "向下移动（末行自动新增）"),
            ("F2",              "进入当前单元格编辑模式"),
            ("Escape",          "退出编辑模式"),
            ("Delete",          "清空选中单元格内容"),
            ("Ctrl+C",          "复制选中行内容"),
            ("Ctrl+V",          "从剪贴板粘贴"),
            ("Ctrl+Z",          "撤销"),
            ("Ctrl+Y",          "重做"),
            ("Ctrl+A",          "全选所有行"),
            ("Ctrl+F",          "聚焦搜索框"),
        ]

        for key, desc in shortcuts:
            row = QWidget()
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(0, 3, 0, 3)
            k = QLabel(key)
            k.setFixedWidth(160)
            k.setStyleSheet("""
                background:#F1F5F9; border:1px solid #E2E8F0;
                border-radius:4px; padding:2px 8px; font-size:12px;
                font-family:Consolas,monospace; color:#374151;
            """)
            d = QLabel(desc)
            d.setStyleSheet("font-size:12px; color:#6B7280; font-family:'Microsoft YaHei';")
            r_lay.addWidget(k)
            r_lay.addWidget(d)
            lay.addWidget(row)

        lay.addStretch()
        close = QPushButton("关闭")
        close.setFixedHeight(32)
        close.clicked.connect(self.close)
        close.setStyleSheet("""
            QPushButton {
                background:#F1F5F9; border:1px solid #E2E8F0;
                border-radius:7px; font-size:12px; color:#374151;
            }
            QPushButton:hover { background:#E2E8F0; }
        """)
        lay.addWidget(close)


# ─────────────────────────────────────────────────────────────────────────────
#  主页面
# ─────────────────────────────────────────────────────────────────────────────

class ExcelImportPage(QWidget):

    def __init__(self):
        super().__init__()
        self._source_path = ""
        self._loader: _ExcelLoader | None = None
        self._undo_stack: list[tuple] = []
        self._redo_stack: list[tuple] = []
        self._ocr_dialog: OCRDialog | None = None

        self.setAcceptDrops(True)
        self._init_ui()
        self._apply_style()
        self._set_has_data(False)

        # 快捷键
        QAction(parent=self, shortcut=QKeySequence("Ctrl+F"),
                triggered=lambda: self.search_box.setFocus()).setParent(self)
        QAction(parent=self, shortcut=QKeySequence("Ctrl+Z"),
                triggered=self._on_undo).setParent(self)
        QAction(parent=self, shortcut=QKeySequence("Ctrl+Y"),
                triggered=self._on_redo).setParent(self)
        QAction(parent=self, shortcut=QKeySequence("F1"),
                triggered=self._show_shortcuts).setParent(self)

        # Toast 管理器
        self.toast = ToastManager(self)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)

        root.addWidget(self._build_toolbar())

        # 进度条（细线，嵌在工具栏和表格之间）
        self._prog_track = QFrame()
        self._prog_track.setFixedHeight(3)
        self._prog_track.setObjectName("progTrack")
        self._prog_fill = QFrame(self._prog_track)
        self._prog_fill.setObjectName("progFill")
        self._prog_fill.setFixedHeight(3)
        self._prog_fill.setFixedWidth(0)
        self._prog_track.hide()
        root.addWidget(self._prog_track)

        # 浮动批量操作工具条
        self.float_bar = _FloatActionBar()
        self.float_bar.delete_requested.connect(self._on_del_rows)
        self.float_bar.copy_requested.connect(self._copy_selected_rows)
        self.float_bar.clear_requested.connect(self._clear_selected_content)
        self.float_bar.dismiss_requested.connect(lambda: self.table.clearSelection())
        root.addWidget(self.float_bar)

        # 表格区域
        self.empty_widget = self._build_empty()
        self.table = _EditableTable()
        self.table.data_changed.connect(self._on_data_changed)
        self.table.selection_changed.connect(self._on_selection_changed)

        root.addWidget(self.empty_widget, stretch=1)
        root.addWidget(self.table, stretch=1)

        # 状态栏
        self._build_statusbar()
        root.addWidget(self.status_bar)

    # ── 工具栏 ───────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        wrapper = QWidget()
        wrapper.setObjectName("toolbar")
        root = QVBoxLayout(wrapper)
        root.setContentsMargins(12, 6, 12, 6)
        root.setSpacing(6)

        # 第一行：文件操作
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.import_btn = self._btn("📂 导入文件", "importBtn", self._on_import)
        row1.addWidget(self.import_btn)

        self.file_label = QLabel("拖拽 Excel / CSV 或点击导入")
        self.file_label.setObjectName("fileLabel")
        row1.addWidget(self.file_label)

        self.close_file_btn = self._btn("✕ 关闭", "closeFileBtn", self._on_close_file)
        self.close_file_btn.setFixedHeight(28)
        self.close_file_btn.hide()
        row1.addWidget(self.close_file_btn)

        row1.addStretch()

        # 修改统计徽标
        self.change_badge = QLabel("")
        self.change_badge.setObjectName("changeBadge")
        self.change_badge.hide()
        row1.addWidget(self.change_badge)

        self.export_btn = self._btn("↓ 导出 Excel", "exportBtn", self._on_export)
        row1.addWidget(self.export_btn)

        root.addLayout(row1)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("toolbarSep")
        root.addWidget(sep)

        # 第二行：编辑操作
        row2 = QHBoxLayout()
        row2.setSpacing(4)

        self.add_row_btn = self._btn("＋ 新增行", "toolBtn", self._on_add_row)
        self.del_row_btn = self._btn("－ 删除行", "toolBtn", self._on_del_rows)
        self.undo_btn    = self._btn("↩ 撤销",   "toolBtn", self._on_undo)
        self.redo_btn    = self._btn("↪ 重做",   "toolBtn", self._on_redo)
        self.undo_btn.setToolTip("撤销 (Ctrl+Z)")
        self.redo_btn.setToolTip("重做 (Ctrl+Y)")

        for b in (self.add_row_btn, self.del_row_btn,
                  self.undo_btn, self.redo_btn):
            b.setFixedHeight(28)
            row2.addWidget(b)

        row2.addWidget(self._vdiv())

        # 列管理
        self.col_btn = self._btn("列管理 ▾", "toolBtn", self._show_col_menu)
        self.col_btn.setFixedHeight(28)
        row2.addWidget(self.col_btn)

        row2.addWidget(self._vdiv())

        # OCR
        self.ocr_btn = self._btn("🤖 OCR 识别", "ocrBtn", self._open_ocr)
        self.ocr_btn.setFixedHeight(28)
        row2.addWidget(self.ocr_btn)

        row2.addWidget(self._vdiv())

        # 快捷键帮助
        help_btn = self._btn("？ 快捷键", "toolBtn", self._show_shortcuts)
        help_btn.setFixedHeight(28)
        help_btn.setToolTip("查看键盘快捷键 (F1)")
        row2.addWidget(help_btn)

        row2.addStretch()

        # 搜索框
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索内容…  Ctrl+F")
        self.search_box.setFixedWidth(200)
        self.search_box.setFixedHeight(28)
        self.search_box.setObjectName("searchBox")
        self.search_box.textChanged.connect(self._on_search)

        # 清除按钮
        self.search_clear = QToolButton()
        self.search_clear.setText("×")
        self.search_clear.setFixedSize(20, 20)
        self.search_clear.setStyleSheet("background:transparent; border:none; color:#9CA3AF; font-size:14px;")
        self.search_clear.hide()
        self.search_clear.clicked.connect(lambda: self.search_box.clear())
        self.search_box.textChanged.connect(
            lambda t: self.search_clear.setVisible(bool(t))
        )

        search_wrap = QHBoxLayout()
        search_wrap.setContentsMargins(0, 0, 0, 0)
        search_wrap.setSpacing(0)
        search_wrap.addWidget(self.search_box)
        search_wrap.addWidget(self.search_clear)
        row2.addLayout(search_wrap)

        root.addLayout(row2)
        return wrapper

    # ── 状态栏 ───────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setFixedHeight(28)
        self.status_bar.setObjectName("statusBar")

        # 图例
        legend = QWidget()
        leg_l = QHBoxLayout(legend)
        leg_l.setContentsMargins(0, 0, 8, 0)
        leg_l.setSpacing(12)
        for color, text in [
            ("#FFFBEB", "已修改"),
            ("#F0FDF4", "新增行"),
            ("#EFF6FF", "当前行"),
        ]:
            dot = QLabel("■")
            dot.setStyleSheet(
                f"color:{color}; font-size:15px; background:{color};"
                f"border:1px solid #E5E7EB; border-radius:3px; padding:0 2px;"
            )
            lbl = QLabel(text)
            lbl.setObjectName("legendText")
            leg_l.addWidget(dot)
            leg_l.addWidget(lbl)
        self.status_bar.addPermanentWidget(legend)

    # ── 空状态 ───────────────────────────────────────────────────────────────

    def _build_empty(self):
        w = QWidget()
        w.setObjectName("emptyState")
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(14)

        icon = QLabel("📊")
        icon.setObjectName("emptyIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)

        title = QLabel("拖拽文件到此处，或点击「导入文件」")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)

        sub = QLabel("支持 .xlsx  .xls  .csv  |  最大 10 万行")
        sub.setObjectName("emptySub")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)

        # 快速导入按钮（空状态居中的大按钮）
        quick_btn = QPushButton("选择文件")
        quick_btn.setObjectName("emptyImportBtn")
        quick_btn.setFixedSize(140, 40)
        quick_btn.clicked.connect(self._on_import)
        lay.addWidget(quick_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        return w

    # ── 工具函数 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _btn(text: str, obj: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(obj)
        b.setFixedHeight(34)
        b.clicked.connect(slot)
        return b

    @staticmethod
    def _vdiv() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedSize(1, 18)
        f.setObjectName("toolDiv")
        return f

    def _set_has_data(self, has: bool):
        self.empty_widget.setVisible(not has)
        self.table.setVisible(has)
        for b in (self.add_row_btn, self.del_row_btn, self.undo_btn,
                  self.redo_btn, self.export_btn, self.search_box,
                  self.col_btn, self.ocr_btn, self.close_file_btn):
            b.setEnabled(has)
        if not has:
            self.change_badge.hide()

    # ── 导入 ─────────────────────────────────────────────────────────────────

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "",
            "表格文件 (*.xlsx *.xls *.csv);;所有文件 (*)"
        )
        if path:
            self._preview_before_import(path)

    def _preview_before_import(self, path: str):
        """先快速预读行/列信息，弹确认对话框"""
        if not os.path.exists(path):
            self.toast.error(f"文件不存在：{os.path.basename(path)}")
            return

        # 快速预读（仅读头+行数）
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".csv":
                import csv
                with open(path, encoding="utf-8-sig", errors="replace") as f:
                    rows = list(csv.reader(f))
                headers = rows[0] if rows else []
                row_count = max(0, len(rows) - 1)
            else:
                import openpyxl
                wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
                ws = wb.active
                all_rows = list(ws.iter_rows(values_only=True))
                headers = [str(c) if c is not None else "" for c in (all_rows[0] if all_rows else [])]
                row_count = max(0, len(all_rows) - 1)
                wb.close()
        except Exception as e:
            self.toast.error(f"读取失败：{e}")
            return

        # 如果当前已有数据，弹确认对话框
        if self.table.isVisible() and self.table.rowCount() > 0:
            dlg = _ImportPreviewDialog(path, headers, row_count, self)
            dlg.confirmed.connect(self._load_file)
            dlg.exec()
        else:
            self._load_file(path)

    def _load_file(self, path: str):
        self._source_path = path
        fname = os.path.basename(path)
        self.file_label.setText(f"📄 {fname}")
        self.close_file_btn.show()
        self._prog_track.show()
        self._prog_fill.setFixedWidth(0)

        self._loader = _ExcelLoader(path)
        self._loader.finished.connect(self._on_loaded)
        self._loader.error.connect(lambda m: (
            self._prog_track.hide(),
            self.toast.error(f"导入失败：{m}")
        ))
        self._loader.progress.connect(self._set_prog)
        self._loader.start()

    def _set_prog(self, val: int):
        w = max(self._prog_track.width(), 1)
        self._prog_fill.setFixedWidth(int(w * val / 100))

    def _on_loaded(self, headers: list[str], rows: list[list[str]]):
        self._prog_track.hide()
        self._push_snap()
        self._populate(headers, rows)
        self._set_has_data(True)
        self._update_status()
        self.toast.success(f"已载入 {len(rows)} 行 × {len(headers)} 列")

    def _populate(self, headers: list[str], rows: list[list[str]]):
        self.table.blockSignals(True)
        self.table.clear()
        self.table._modified.clear()
        self.table._new_rows.clear()
        self.table._errors.clear()
        self.table._active_row = -1

        nc = len(headers)
        self.table.setColumnCount(nc)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            bg = _EditableTable.C_EVEN if r % 2 == 0 else _EditableTable.C_ODD
            for c in range(nc):
                val = row[c] if c < len(row) else ""
                item = QTableWidgetItem(str(val))
                item.setBackground(bg)
                self.table.setItem(r, c, item)

        self.table.resizeColumnsToContents()
        for col in range(nc):
            w = self.table.columnWidth(col)
            self.table.setColumnWidth(col, min(max(w, 60), 240))
        self.table.blockSignals(False)

        self._update_change_badge()

    # ── 关闭文件 ─────────────────────────────────────────────────────────────

    def _on_close_file(self):
        has_changes = (self.table.modified_count + self.table.new_count) > 0
        if has_changes:
            reply = QMessageBox.question(
                self, "关闭确认",
                f"有 {self.table.modified_count + self.table.new_count} 行未保存的修改，确定关闭？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._source_path = ""
        self.file_label.setText("拖拽 Excel / CSV 或点击导入")
        self.close_file_btn.hide()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._set_has_data(False)
        self.float_bar.hide()

    # ── OCR ─────────────────────────────────────────────────────────────────

    def _open_ocr(self):
        if not self.table.isVisible():
            self.toast.info("请先导入 Excel 文件")
            return
        headers = self.table.get_headers()
        if self._ocr_dialog is None or not self._ocr_dialog.isVisible():
            self._ocr_dialog = OCRDialog(self, headers=headers)
            self._ocr_dialog.fill_requested.connect(self._fill_from_ocr)
        self._ocr_dialog.show()
        self._ocr_dialog.raise_()

    def _fill_from_ocr(self, col_name: str, value: str):
        if self.table.isHidden() or self.table.rowCount() == 0:
            self.toast.warning("请先选择目标行")
            return
        row = max(self.table.currentRow(), 0)
        headers = self.table.get_headers()
        headers_lower = [h.lower() for h in headers]
        try:
            col = headers_lower.index(col_name.lower())
        except ValueError:
            self.toast.error(f"未找到列「{col_name}」")
            return
        self.table.blockSignals(True)
        self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.blockSignals(False)
        self.table._mark_mod(row)
        self.table._refresh_row_color(row)
        self.table.data_changed.emit()
        self.toast.success(f"已填入第 {row+1} 行「{col_name}」")

    # ── 选择变化 ─────────────────────────────────────────────────────────────

    def _on_selection_changed(self, count: int):
        self.float_bar.update_count(count)
        self._update_status()

    def _copy_selected_rows(self):
        self.table._copy_to_clipboard()
        rows = {i.row() for i in self.table.selectedIndexes()}
        self.toast.info(f"已复制 {len(rows)} 行到剪贴板")

    def _clear_selected_content(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        self._push_snap()
        self.table.clear_selected_content()
        self.toast.info(f"已清空 {len(rows)} 行内容")

    # ── 列管理 ───────────────────────────────────────────────────────────────

    def _show_col_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background:white; border:1px solid #E5E7EB;
                border-radius:8px; padding:6px;
                font-family:"Microsoft YaHei"; font-size:12px; min-width:160px;
            }
            QMenu::item { padding:7px 14px; border-radius:5px; color:#374151; }
            QMenu::item:selected { background:#EFF6FF; color:#1D4ED8; }
            QMenu::separator { height:1px; background:#F3F4F6; margin:4px 8px; }
        """)
        menu.addAction("＋ 末尾添加列",    self._add_col)
        menu.addAction("＋ 当前列后插入",  self._insert_col_after)
        menu.addSeparator()
        menu.addAction("✕ 删除当前列",     self._del_cur_col)
        menu.addSeparator()
        menu.addAction("↔ 重置所有列宽",   self._reset_col_widths)
        menu.exec(self.col_btn.mapToGlobal(QPoint(0, self.col_btn.height() + 2)))

    def _add_col(self):
        name = self._ask_col_name("新列")
        if not name:
            return
        self._push_snap()
        col = self.table.columnCount()
        self.table.insertColumn(col)
        self.table.setHorizontalHeaderItem(col, QTableWidgetItem(name))
        for r in range(self.table.rowCount()):
            self.table.setItem(r, col, QTableWidgetItem(""))
        self.toast.success(f"已添加列「{name}」")

    def _insert_col_after(self):
        name = self._ask_col_name("新列")
        if not name:
            return
        self._push_snap()
        col = (self.table.currentColumn() + 1) if self.table.currentColumn() >= 0 else self.table.columnCount()
        self.table.insertColumn(col)
        self.table.setHorizontalHeaderItem(col, QTableWidgetItem(name))
        for r in range(self.table.rowCount()):
            self.table.setItem(r, col, QTableWidgetItem(""))
        self.toast.success(f"已插入列「{name}」")

    def _del_cur_col(self):
        col = self.table.currentColumn()
        if col < 0:
            self.toast.warning("请先点击要删除的列")
            return
        h = self.table.horizontalHeaderItem(col)
        name = h.text() if h else f"列{col+1}"
        if QMessageBox.question(
            self, "确认", f"删除列「{name}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self._push_snap()
            self.table.removeColumn(col)
            self.toast.success(f"已删除列「{name}」")

    def _reset_col_widths(self):
        self.table.resizeColumnsToContents()
        for c in range(self.table.columnCount()):
            self.table.setColumnWidth(c, min(max(self.table.columnWidth(c), 60), 240))

    @staticmethod
    def _ask_col_name(default="") -> str | None:
        from PySide6.QtWidgets import QInputDialog
        t, ok = QInputDialog.getText(None, "列名", "请输入列名：", text=default)
        return t.strip() if ok and t.strip() else None

    # ── 行操作 ───────────────────────────────────────────────────────────────

    def _on_add_row(self):
        if self.table.isHidden():
            return
        self._push_snap()
        self.table.add_empty_row()

    def _on_del_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self.toast.warning("请先选择要删除的行")
            return
        if len(rows) == 1 or QMessageBox.question(
            self, "确认删除", f"确定删除选中的 {len(rows)} 行？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self._push_snap()
            self.table.delete_selected_rows()
            self.toast.success(f"已删除 {len(rows)} 行")

    # ── 快捷键帮助 ───────────────────────────────────────────────────────────

    def _show_shortcuts(self):
        dlg = _ShortcutHelpDialog(self)
        dlg.exec()

    # ── 撤销/重做 ─────────────────────────────────────────────────────────────

    def _push_snap(self):
        if self.table.isHidden():
            return
        self._undo_stack.append((self.table.get_headers(), self.table.get_all_data()))
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self.undo_btn.setEnabled(True)
        self.redo_btn.setEnabled(False)

    def _on_undo(self):
        if not self._undo_stack:
            self.toast.info("已到最早记录")
            return
        self._redo_stack.append((self.table.get_headers(), self.table.get_all_data()))
        h, rows = self._undo_stack.pop()
        self._populate(h, rows)
        self.undo_btn.setEnabled(bool(self._undo_stack))
        self.redo_btn.setEnabled(True)
        self._update_status()
        self.toast.info(f"已撤销（还可撤销 {len(self._undo_stack)} 步）")

    def _on_redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append((self.table.get_headers(), self.table.get_all_data()))
        h, rows = self._redo_stack.pop()
        self._populate(h, rows)
        self.undo_btn.setEnabled(True)
        self.redo_btn.setEnabled(bool(self._redo_stack))
        self._update_status()
        self.toast.info("已重做")

    # ── 搜索 ─────────────────────────────────────────────────────────────────

    def _on_search(self, text: str):
        q = text.strip().lower()
        match_count = 0
        for r in range(self.table.rowCount()):
            match = not q or any(
                q in (self.table.item(r, c).text().lower()
                      if self.table.item(r, c) else "")
                for c in range(self.table.columnCount())
            )
            self.table.setRowHidden(r, not match)
            if match:
                match_count += 1
        self._update_status()
        if q and match_count == 0:
            self.search_box.setStyleSheet(
                self.search_box.styleSheet() + "border-color:#EF4444; background:#FEF2F2;"
            )
        else:
            self.search_box.setStyleSheet("")

    # ── 导出 ─────────────────────────────────────────────────────────────────

    def _on_export(self):
        if self.table.isHidden() or self.table.rowCount() == 0:
            self.toast.warning("没有可导出的数据")
            return
        base = ""
        if self._source_path:
            base = os.path.splitext(os.path.basename(self._source_path))[0] + "_edited"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Excel", base, "Excel 文件 (*.xlsx)"
        )
        if not path:
            return
        if not path.endswith(".xlsx"):
            path += ".xlsx"
        try:
            vis_rows = [r for r in range(self.table.rowCount())
                        if not self.table.isRowHidden(r)]
            self._write_xlsx(path, vis_rows)
            self.table.clear_change_marks()
            self._update_status()
            self._update_change_badge()
            self.toast.success(f"已导出 {len(vis_rows)} 行  →  {os.path.basename(path)}", duration=4000)
        except Exception as e:
            self.toast.error(f"导出失败：{e}")

    def _write_xlsx(self, path: str, vis_rows: list[int]):
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "数据"
        thin = Side(style="thin", color="E5E7EB")
        brd  = Border(left=thin, right=thin, top=thin, bottom=thin)
        headers = self.table.get_headers()
        for ci, h in enumerate(headers, 1):
            cell = ws.cell(1, ci, h)
            cell.font = Font(name="Arial", bold=True, color="FFFFFF", size=11)
            cell.fill = PatternFill("solid", start_color="1E3A5F")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = brd
        ws.row_dimensions[1].height = 26
        for ei, tr in enumerate(vis_rows, 2):
            ws.row_dimensions[ei].height = 20
            fill = PatternFill("solid", start_color="FFFFFF" if ei % 2 == 0 else "F8FAFC")
            for ci in range(self.table.columnCount()):
                item = self.table.item(tr, ci)
                cell = ws.cell(ei, ci + 1, item.text() if item else "")
                cell.font = Font(name="Arial", size=10)
                cell.fill = fill
                cell.alignment = Alignment(vertical="center")
                cell.border = brd
        for ci, _ in enumerate(headers, 1):
            vals = [ws.cell(r, ci).value or "" for r in range(1, len(vis_rows) + 2)]
            ml = max((len(str(v)) for v in vals), default=8)
            ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = min(max(ml + 4, 10), 40)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(path)

    # ── 拖拽 ─────────────────────────────────────────────────────────────────

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            ext = os.path.splitext(e.mimeData().urls()[0].toLocalFile())[1].lower()
            if ext in (".xlsx", ".xls", ".csv"):
                e.acceptProposedAction()
                self.empty_widget.setStyleSheet(
                    self.empty_widget.styleSheet().replace(
                        "border:2px dashed #D1D5DB",
                        "border:2px dashed #3B82F6"
                    )
                )

    def dragLeaveEvent(self, e):
        self.empty_widget.setStyleSheet(
            self.empty_widget.styleSheet().replace(
                "border:2px dashed #3B82F6",
                "border:2px dashed #D1D5DB"
            )
        )

    def dropEvent(self, e: QDropEvent):
        self.dragLeaveEvent(None)
        urls = e.mimeData().urls()
        if urls:
            self._preview_before_import(urls[0].toLocalFile())

    # ── 状态更新 ─────────────────────────────────────────────────────────────

    def _on_data_changed(self):
        self._update_status()
        self._update_change_badge()

    def _update_change_badge(self):
        mod = self.table.modified_count
        new = self.table.new_count
        total = mod + new
        if total > 0:
            parts = []
            if mod:
                parts.append(f"{mod} 已修改")
            if new:
                parts.append(f"{new} 新增")
            self.change_badge.setText("  ".join(parts))
            self.change_badge.show()
        else:
            self.change_badge.hide()

    def _update_status(self):
        if self.table.isHidden():
            self.status_bar.showMessage("就绪  —  请导入文件")
            return
        total = self.table.rowCount()
        vis = sum(1 for r in range(total) if not self.table.isRowHidden(r))
        sel = len({i.row() for i in self.table.selectedIndexes()})
        parts = [f"共 {total} 行  {self.table.columnCount()} 列"]
        if vis != total:
            parts.append(f"筛选中 {vis} 行可见")
        if sel:
            parts.append(f"已选 {sel} 行")
        if self.table.error_count:
            parts.append(f"⚠ {self.table.error_count} 处警告")
        self.status_bar.showMessage("    ".join(parts))

    # ── 样式表 ───────────────────────────────────────────────────────────────

    def _apply_style(self):
        self.setStyleSheet("""
        QWidget { font-family:"Microsoft YaHei"; font-size:13px; color:#1E293B; }

        /* ── 工具栏 ── */
        QWidget#toolbar {
            background:#FFFFFF;
            border:1px solid #E9ECF0;
            border-radius:10px;
        }
        QFrame#toolbarSep {
            background:#F1F5F9; border:none; max-height:1px;
        }

        QPushButton#importBtn {
            background:#3B82F6; color:white; border:none;
            border-radius:7px; padding:0 18px; font-weight:bold;
            font-size:13px; min-width:100px;
        }
        QPushButton#importBtn:hover { background:#2563EB; }

        QPushButton#exportBtn {
            background:#10B981; color:white; border:none;
            border-radius:7px; padding:0 18px; font-weight:bold;
            font-size:13px; min-width:100px;
        }
        QPushButton#exportBtn:hover { background:#059669; }
        QPushButton#exportBtn:disabled { background:#D1FAE5; color:#6EE7B7; }

        QPushButton#closeFileBtn {
            background:transparent; border:1px solid #E5E7EB;
            border-radius:5px; color:#9CA3AF; font-size:11px;
            padding:0 8px;
        }
        QPushButton#closeFileBtn:hover { background:#FEF2F2; color:#EF4444; border-color:#FECACA; }

        QPushButton#toolBtn {
            background:transparent; border:none; border-radius:6px;
            padding:0 10px; color:#374151; font-size:12px; min-width:56px;
        }
        QPushButton#toolBtn:hover { background:#F3F4F6; }
        QPushButton#toolBtn:pressed { background:#E5E7EB; }
        QPushButton#toolBtn:disabled { color:#D1D5DB; }

        QPushButton#ocrBtn {
            background:transparent; border:1px solid #E9ECF0;
            border-radius:6px; padding:0 12px; color:#7C3AED;
            font-size:12px; font-weight:bold;
        }
        QPushButton#ocrBtn:hover { background:#F5F3FF; border-color:#C4B5FD; }
        QPushButton#ocrBtn:disabled { color:#C4B5FD; }

        QFrame#toolDiv { background:#E9ECF0; border:none; }
        QLabel#fileLabel { color:#6B7280; font-size:12px; }

        /* 修改徽标 */
        QLabel#changeBadge {
            background:#FEF9C3; color:#854D0E;
            border:1px solid #FDE047; border-radius:5px;
            font-size:11px; padding:2px 8px; font-weight:bold;
        }

        /* ── 搜索框 ── */
        QLineEdit#searchBox {
            border:1px solid #E9ECF0; border-radius:6px;
            padding:4px 10px; background:#F9FAFB; font-size:12px;
        }
        QLineEdit#searchBox:focus { border-color:#3B82F6; background:white; }

        /* ── 进度条 ── */
        QFrame#progTrack { background:#E5E7EB; border-radius:2px; }
        QFrame#progFill  { background:#3B82F6; border-radius:2px; }

        /* ── 浮动操作条 ── */
        QWidget#floatBar {
            background:#1E3A5F; border-radius:8px;
        }
        QLabel#floatBarCount {
            color:#BFDBFE; font-size:12px; font-weight:bold;
        }
        QPushButton#floatBarBtn {
            background:transparent; border:1px solid rgba(255,255,255,0.2);
            border-radius:5px; color:#E2E8F0; font-size:11px; padding:0 10px;
        }
        QPushButton#floatBarBtn:hover { background:rgba(255,255,255,0.1); }
        QPushButton#floatBarBtnDanger {
            background:transparent; border:1px solid #FCA5A5;
            border-radius:5px; color:#FCA5A5; font-size:11px; padding:0 10px;
        }
        QPushButton#floatBarBtnDanger:hover { background:#7F1D1D; }
        QFrame#floatBarSep { background:rgba(255,255,255,0.2); border:none; }
        QPushButton#floatBarDismiss {
            background:transparent; border:none;
            color:rgba(255,255,255,0.5); font-size:11px;
        }
        QPushButton#floatBarDismiss:hover { color:white; }

        /* ── 空状态 ── */
        QWidget#emptyState {
            background:#F9FAFB; border:2px dashed #D1D5DB; border-radius:14px;
        }
        QLabel#emptyIcon  { font-size:52px; color:#9CA3AF; }
        QLabel#emptyTitle { font-size:15px; font-weight:bold; color:#6B7280; }
        QLabel#emptySub   { font-size:12px; color:#9CA3AF; }
        QPushButton#emptyImportBtn {
            background:#3B82F6; color:white; border:none;
            border-radius:8px; font-size:13px; font-weight:bold;
        }
        QPushButton#emptyImportBtn:hover { background:#2563EB; }

        /* ── 表格 ── */
        QTableWidget {
            background:white; border:1px solid #E9ECF0;
            border-radius:10px; gridline-color:#F3F4F6;
            font-size:13px; outline:0;
        }
        QTableWidget::item { padding:2px 8px; border:none; }
        QTableWidget::item:selected { background:#DBEAFE; color:#1E40AF; }
        QTableWidget QLineEdit {
            border:2px solid #3B82F6; border-radius:3px;
            background:white; padding:1px 6px; font-size:13px;
        }
        QHeaderView::section {
            background:#1E3A5F; color:#E2E8F0; font-weight:bold;
            font-size:12px; padding:0 8px; border:none;
            border-right:1px solid #2D5A8E; height:36px;
        }
        QHeaderView::section:hover { background:#2563EB; }
        QHeaderView::section:last  { border-right:none; }

        /* ── 滚动条 ── */
        QScrollBar:vertical { width:7px; background:transparent; }
        QScrollBar::handle:vertical {
            background:#CBD5E1; border-radius:4px; min-height:28px;
        }
        QScrollBar::handle:vertical:hover { background:#94A3B8; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        QScrollBar:horizontal { height:7px; background:transparent; }
        QScrollBar::handle:horizontal {
            background:#CBD5E1; border-radius:4px; min-width:28px;
        }
        QScrollBar::handle:horizontal:hover { background:#94A3B8; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }

        /* ── 状态栏 ── */
        QStatusBar#statusBar {
            background:#F8FAFC; border-top:1px solid #E9ECF0;
            font-size:11px; color:#6B7280; padding:0 10px;
        }
        QLabel#legendText { font-size:11px; color:#9CA3AF; }
        """)

        self.undo_btn.setEnabled(False)
        self.redo_btn.setEnabled(False)
