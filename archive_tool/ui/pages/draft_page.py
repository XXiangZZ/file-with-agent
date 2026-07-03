"""
草稿管理页面
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QPushButton, QLabel, QMessageBox, QGroupBox, QTableWidgetItem,
    QHeaderView
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QBrush

from core.draft_manager import DraftManager
from core.logger import Logger


class DraftPage(QWidget):
    """草稿管理页面"""

    draft_load_requested = Signal(dict)

    def __init__(self):
        super().__init__()
        self.draft_manager = DraftManager()
        self.logger = Logger()
        self._highlighted_row = -1
        self._init_ui()
        self._load_drafts()

    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # 说明标签
        info_group = QGroupBox('说明')
        info_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #2C3E50;
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px 10px 5px 10px;
                background-color: #F8F9FA;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 8px;
                color: #3498DB;
            }
        """)
        info_layout = QVBoxLayout()
        info_label = QLabel('草稿管理器：手动保存档案录入的中间状态，支持多版本管理')
        info_label.setStyleSheet("color: #555; font-size: 13px; font-weight: normal;")
        info_layout.addWidget(info_label)
        info_group.setLayout(info_layout)
        main_layout.addWidget(info_group)

        # 按钮区域
        btn_layout = QHBoxLayout()

        self.load_draft_btn = QPushButton('加载草稿')
        self.load_draft_btn.setStyleSheet("""
            QPushButton {
                background-color: #E0F2FE;
                color: #1F2937;
                border: 1px solid #7DD3FC;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #BAE6FD;
            }
            QPushButton:pressed {
                background-color: #7DD3FC;
            }
        """)
        self.load_draft_btn.clicked.connect(self._on_load_draft)
        btn_layout.addWidget(self.load_draft_btn)

        self.delete_draft_btn = QPushButton('删除草稿')
        self.delete_draft_btn.setStyleSheet("""
            QPushButton {
                background-color: #FEE2E2;
                color: #1F2937;
                border: 1px solid #FCA5A5;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #FECACA;
            }
            QPushButton:pressed {
                background-color: #FCA5A5;
            }
        """)
        self.delete_draft_btn.clicked.connect(self._on_delete_draft)
        btn_layout.addWidget(self.delete_draft_btn)

        self.refresh_btn = QPushButton('刷新列表')
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #F3F4F6;
                color: #1F2937;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
            }
            QPushButton:pressed {
                background-color: #D1D5DB;
            }
        """)
        self.refresh_btn.clicked.connect(self._load_drafts)
        btn_layout.addWidget(self.refresh_btn)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # 草稿列表
        self.draft_table = QTableWidget()
        self.draft_table.setColumnCount(6)
        self.draft_table.setHorizontalHeaderLabels(['ID', '草稿名称', '关联批次', '模板', '归档类型', '创建时间'])
        self.draft_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.draft_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.draft_table.setAlternatingRowColors(True)
        self.draft_table.verticalHeader().setVisible(False)
        self.draft_table.verticalHeader().setDefaultSectionSize(28)

        header = self.draft_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)

        self.draft_table.setColumnWidth(0, 60)
        self.draft_table.setColumnWidth(3, 120)
        self.draft_table.setColumnWidth(4, 80)
        self.draft_table.setColumnWidth(5, 180)

        self.draft_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                background-color: white;
                font-size: 13px;
                gridline-color: #F0F0F0;
                alternate-background-color: #FAFBFC;
            }
            QTableWidget::item {
                padding: 4px 8px;
            }
            QHeaderView::section {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #34495E,
                    stop: 1 #2C3E50
                );
                color: white;
                padding: 8px 10px;
                border: none;
                font-weight: bold;
                font-size: 13px;
            }
            QTableWidget::item:selected {
                background-color: #DBEAFE;
                color: #1E40AF;
            }
        """)
        main_layout.addWidget(self.draft_table)

        self.draft_table.itemDoubleClicked.connect(self._on_draft_item_clicked)

    def _load_drafts(self):
        """加载草稿列表"""
        from db.database import get_cursor

        self.draft_table.clearSpans()
        self.draft_table.clearSelection()

        with get_cursor() as cursor:
            cursor.execute('''
                SELECT d.*, b.name as batch_name, t.filing_type
                FROM drafts d
                LEFT JOIN batches b ON d.batch_id = b.id
                LEFT JOIN templates t ON d.template_name = t.name
                ORDER BY d.created_at DESC
            ''')
            drafts = cursor.fetchall()

        self.draft_table.setRowCount(len(drafts))
        for i, draft in enumerate(drafts):
            seq_item = QTableWidgetItem(str(i + 1))
            seq_item.setData(Qt.UserRole, draft['id'])
            seq_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.draft_table.setItem(i, 0, seq_item)
            
            name_item = QTableWidgetItem(draft['draft_name'])
            name_item.setToolTip(draft['draft_name'])
            self.draft_table.setItem(i, 1, name_item)
            
            batch_item = QTableWidgetItem(draft['batch_name'] or 'N/A')
            batch_item.setToolTip(draft['batch_name'] or 'N/A')
            self.draft_table.setItem(i, 2, batch_item)
            
            template_item = QTableWidgetItem(draft['template_name'] or 'N/A')
            template_item.setToolTip(draft['template_name'] or 'N/A')
            self.draft_table.setItem(i, 3, template_item)
            
            filing_type = draft['filing_type'] or ''
            filing_text = '以卷归档' if filing_type == 'volume' else '以件归档'
            self.draft_table.setItem(i, 4, QTableWidgetItem(filing_text))
            self.draft_table.setItem(i, 5, QTableWidgetItem(str(draft['created_at'])))

        if not drafts:
            self.draft_table.setRowCount(1)
            item = QTableWidgetItem('暂无草稿，点击录入页「存草稿」按钮保存')
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QBrush(QColor('#9CA3AF')))
            self.draft_table.setItem(0, 0, item)
            self.draft_table.setSpan(0, 0, 1, 6)

    def _highlight_row(self, row):
        """高亮指定行，200ms后恢复"""
        if self._highlighted_row >= 0:
            self._restore_row(self._highlighted_row)

        self._highlighted_row = row
        highlight_color = QColor('#DBEAFE')
        for col in range(self.draft_table.columnCount()):
            item = self.draft_table.item(row, col)
            if item:
                item.setBackground(QBrush(highlight_color))

        QTimer.singleShot(200, lambda: self._restore_row(row))

    def _restore_row(self, row):
        """恢复行背景色"""
        if row == self._highlighted_row:
            self._highlighted_row = -1
        for col in range(self.draft_table.columnCount()):
            item = self.draft_table.item(row, col)
            if item:
                if row % 2 == 0:
                    item.setBackground(QBrush(QColor('#FFFFFF')))
                else:
                    item.setBackground(QBrush(QColor('#FAFBFC')))

    def _on_draft_item_clicked(self, item):
        """双击草稿行加载"""
        row = item.row()
        seq_item = self.draft_table.item(row, 0)
        if not seq_item:
            return

        draft_id = seq_item.data(Qt.UserRole)
        if not draft_id:
            return

        draft = self.draft_manager.get_draft(draft_id)
        if draft:
            self._highlight_row(row)
            self.draft_load_requested.emit(draft)

    def _on_load_draft(self):
        """加载草稿"""
        selected_rows = self.draft_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, '提示', '请先选择要加载的草稿')
            return

        row = selected_rows[0].row()
        seq_item = self.draft_table.item(row, 0)
        if not seq_item:
            QMessageBox.warning(self, '提示', '请选择有效的草稿')
            return

        draft_id = seq_item.data(Qt.UserRole)
        if not draft_id:
            QMessageBox.warning(self, '提示', '请选择有效的草稿')
            return

        draft = self.draft_manager.get_draft(draft_id)
        if draft:
            self._highlight_row(row)
            self.draft_load_requested.emit(draft)
            self.logger.log('load_draft', {'draft_id': draft_id})

    def _on_delete_draft(self):
        """删除草稿"""
        selected_rows = self.draft_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, '提示', '请先选择要删除的草稿')
            return

        row = selected_rows[0].row()
        seq_item = self.draft_table.item(row, 0)
        if not seq_item:
            QMessageBox.warning(self, '提示', '请选择有效的草稿')
            return

        draft_id = seq_item.data(Qt.UserRole)
        if not draft_id:
            QMessageBox.warning(self, '提示', '请选择有效的草稿')
            return

        draft_name = self.draft_table.item(row, 1).text() if self.draft_table.item(row, 1) else ''

        reply = QMessageBox.question(self, '确认',
            f'确定要删除草稿「{draft_name}」吗？')
        if reply == QMessageBox.StandardButton.Yes:
            self.draft_manager.delete_draft(draft_id)
            self.logger.log('delete_draft', {'draft_id': draft_id})
            self._load_drafts()
            QMessageBox.information(self, '提示', '删除成功')
