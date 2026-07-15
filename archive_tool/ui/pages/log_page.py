"""
操作日志页面
"""
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QLabel, QFrame, QPushButton, QTableWidgetItem,
    QHeaderView, QComboBox, QLineEdit, QDateEdit,
    QDialog, QTextEdit, QDialogButtonBox, QFormLayout
)
from ui.components.fixed_combo import FixedComboBox
from PySide6.QtCore import Qt, QEvent, QDate
from PySide6.QtWidgets import QAbstractItemView
from PySide6.QtGui import QColor, QBrush
from datetime import datetime

from core.logger import Logger


COMBO_STYLE = """
    QComboBox {
        border: 1px solid #D1D5DB;
        border-radius: 6px;
        padding: 4px 8px 4px 12px;
        font-size: 13px;
        min-height: 26px;
        max-height: 26px;
        background: white;
    }
    QComboBox:hover { border-color: #9CA3AF; }
    QComboBox:focus { border-color: #3B82F6; }
    QComboBox::drop-down {
        border: none;
        width: 32px;
        border-radius: 0 6px 6px 0;
        background: transparent;
    }
    QComboBox::down-arrow {
        image: none;
        border: none;
        width: 12px;
        height: 12px;
    }
    QComboBox QAbstractItemView {
        border: 1px solid #E5E7EB;
        border-radius: 6px;
        background: white;
        padding: 4px 0;
        outline: 0;
        selection-background-color: transparent;
    }
    QComboBox QAbstractItemView::item {
        padding: 6px 12px;
        font-size: 12px;
        min-height: 24px;
        margin: 0;
    }
    QComboBox QAbstractItemView::item:selected {
        background: #EFF6FF;
        color: #1E40AF;
    }
    QComboBox QAbstractItemView::item:hover {
        background: #EFF6FF;
        color: #1E40AF;
    }
"""

DATE_EDIT_STYLE = """
    QDateEdit {
        border: 1px solid #D1D5DB;
        border-radius: 6px;
        padding: 4px 8px 4px 12px;
        font-size: 13px;
        min-width: 120px;
        min-height: 26px;
        max-height: 26px;
        background: white;
    }
    QDateEdit:hover { border-color: #9CA3AF; }
    QDateEdit:focus { border-color: #3B82F6; outline: none; }
    QDateEdit::drop-down {
        border: none;
        width: 32px;
        border-radius: 0 6px 6px 0;
        background: #F3F4F6;
    }
    QDateEdit::drop-down:hover { background: #E5E7EB; }
    QDateEdit::up-button, QDateEdit::down-button {
        width: 32px;
        border: none;
        background: transparent;
    }
    QDateEdit::up-button:hover, QDateEdit::down-button:hover {
        background: #E5E7EB;
    }
    QDateEdit::up-arrow {
        width: 14px;
        height: 14px;
        image: none;
        border: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 6px solid #6B7280;
    }
    QDateEdit::down-arrow {
        width: 14px;
        height: 14px;
        image: none;
        border: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 6px solid #6B7280;
    }
    QDateEdit::up-button {
        subcontrol-origin: content;
        subcontrol-position: top right;
        border-radius: 0 6px 0 0;
    }
    QDateEdit::down-button {
        subcontrol-origin: content;
        subcontrol-position: bottom right;
        border-radius: 0 0 6px 0;
    }
    QDateEdit QAbstractItemView {
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        background: white;
        padding: 6px;
        outline: 0;
    }
    QDateEdit QAbstractItemView::item {
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
    }
    QDateEdit QCalendarWidget QToolButton {
        color: #1F2937;
        font-size: 13px;
        icon-size: 18px;
        padding: 4px;
        border-radius: 4px;
    }
    QDateEdit QCalendarWidget QToolButton:hover {
        background: #EFF6FF;
        color: #1E40AF;
    }
    QDateEdit QCalendarWidget QMenu {
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        background: white;
        padding: 6px;
    }
    QDateEdit QCalendarWidget QMenu::item {
        padding: 6px 16px;
        border-radius: 4px;
        font-size: 13px;
    }
    QDateEdit QCalendarWidget QMenu::item:selected {
        background: #EFF6FF;
        color: #1E40AF;
    }
    QDateEdit QCalendarWidget QWidget#qt_calendar_navigationbar {
        background: #F8FAFC;
        border: none;
        border-radius: 8px 8px 0 0;
        padding: 4px;
    }
    QDateEdit QCalendarWidget {
        background: white;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 0px;
    }
"""

TABLE_STYLE = """
    QTableWidget {
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        background: white;
        font-size: 13px;
        gridline-color: #F0F0F0;
        alternate-background-color: #FAFBFC;
        selection-background-color: #E8EFFE;
        selection-color: #1E40AF;
        text-align: center;
    }
    QTableWidget::item {
        padding: 8px 10px;
        text-align: center;
    }
    QHeaderView::section {
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 #1E40AF,
            stop: 1 #1E3A8A
        );
        color: white;
        padding: 10px 12px;
        border: none;
        border-right: 1px solid #1E3A8A;
        font-weight: 600;
        font-size: 13px;
    }
    QHeaderView::section:last {
        border-right: none;
        border-top-right-radius: 8px;
    }
    QHeaderView::section:first {
        border-top-left-radius: 8px;
    }
    QTableWidget::item:selected {
        background-color: #E8EFFE;
        color: #1E40AF;
    }
    QScrollBar:vertical {
        border: none;
        background: transparent;
        width: 8px;
        margin: 4px;
    }
    QScrollBar::handle:vertical {
        background: #CBD5E1;
        border-radius: 4px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover { background: #94A3B8; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar:horizontal {
        border: none;
        background: transparent;
        height: 8px;
        margin: 4px;
    }
    QScrollBar::handle:horizontal {
        background: #CBD5E1;
        border-radius: 4px;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover { background: #94A3B8; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
"""

FIELD_STYLE = """
    QLabel {
        color: #1F2937;
        font-size: 13px;
        font-weight: 500;
        background: transparent;
        border: none;
    }
"""

INPUT_STYLE = """
    QLineEdit {
        border: 1px solid #D1D5DB;
        border-radius: 6px;
        padding: 4px 8px 4px 12px;
        font-size: 13px;
        min-height: 26px;
        max-height: 26px;
        background: white;
    }
    QLineEdit:hover { border-color: #9CA3AF; }
    QLineEdit:focus {
        border-color: #3B82F6;
    }
    QLineEdit::placeholder { color: #9CA3AF; }
"""

BUTTON_STYLE_SEARCH = """
    QPushButton {
        background-color: #3498DB;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 6px 20px;
        font-weight: bold;
        font-size: 13px;
        min-height: 26px;
        max-height: 26px;
    }
    QPushButton:hover {
        background-color: #2980B9;
    }
"""

BUTTON_STYLE_RESET = """
    QPushButton {
        background-color: #95A5A6;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 6px 20px;
        font-weight: bold;
        font-size: 13px;
        min-height: 26px;
        max-height: 26px;
    }
    QPushButton:hover {
        background-color: #7F8C8D;
    }
"""

BUTTON_STYLE_REFRESH = """
    QPushButton {
        background-color: #10B981;
        color: white;
        border: none;
        border-radius: 6px;
        padding: 6px 20px;
        font-weight: bold;
        font-size: 13px;
        min-height: 26px;
        max-height: 26px;
    }
    QPushButton:hover {
        background-color: #059669;
    }
"""

BUTTON_STYLE_QUICK = """
    QPushButton {
        background-color: transparent;
        color: #6B7280;
        border: 1px solid #D1D5DB;
        border-radius: 6px;
        padding: 4px 12px;
        font-size: 12px;
        font-weight: 500;
        min-height: 26px;
        max-height: 26px;
    }
    QPushButton:hover {
        background-color: #F3F4F6;
        color: #374151;
        border-color: #9CA3AF;
    }
"""


class LogPage(QWidget):
    """操作日志页面"""

    def __init__(self):
        super().__init__()
        self.logger = Logger()
        self._combo_popup_initialized = set()
        self._init_ui()
        self._load_logs()

    def _add_search_field(self, layout: QHBoxLayout, label: str, field_name: str, widget_cls) -> QWidget:
        container = QWidget()
        field_layout = QHBoxLayout(container)
        field_layout.setSpacing(6)
        field_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(f'{label}：')
        lbl.setFixedWidth(70)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl.setStyleSheet(FIELD_STYLE)
        field_layout.addWidget(lbl)

        widget = widget_cls()
        widget.setMinimumWidth(140)
        field_layout.addWidget(widget, 1)

        self.search_fields[field_name] = widget
        layout.addWidget(container, 1)
        return widget

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)
        self.search_fields = {}

        filter_card = QFrame()
        filter_card.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
            }
        """)
        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(20, 16, 20, 16)
        filter_layout.setSpacing(12)

        filter_title = QLabel('筛选条件')
        filter_title.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #1E3A8A;
            padding: 0px;
            background: transparent;
            border: none;
        """)
        filter_layout.addWidget(filter_title)

        row1 = QHBoxLayout()
        row1.setSpacing(15)

        self.type_combo = self._add_search_field(row1, "操作类型", "operation_type", FixedComboBox)
        self.type_combo.setObjectName('logTypeCombo')
        self.type_combo.addItem('全部', '')
        self.type_combo.addItem('保存记录', 'save_record')
        self.type_combo.addItem('更新记录', 'update_record')
        self.type_combo.addItem('删除记录', 'delete_record')
        self.type_combo.addItem('保存草稿', 'save_draft')
        self.type_combo.addItem('删除草稿', 'delete_draft')
        self.type_combo.addItem('Excel导入', 'import_excel')
        self.type_combo.addItem('Excel导出', 'export_excel')
        self.type_combo.addItem('数据校验', 'validate')
        self.type_combo.addItem('创建批次', 'create_batch')
        self.type_combo.addItem('删除批次', 'delete_batch')
        self.type_combo.addItem('重命名批次', 'rename_batch')
        self.type_combo.addItem('批量导入记录', 'import_records')
        self.type_combo.addItem('标记已核对', 'mark_reviewed')
        self.type_combo.addItem('批量标记核对', 'mark_reviewed_batch')
        self.type_combo.addItem('导出检索结果', 'export_search')
        self.type_combo.setStyleSheet(COMBO_STYLE)
        self.type_combo.view().installEventFilter(self)
        self.type_combo.installEventFilter(self)

        date_container = QWidget()
        date_layout = QHBoxLayout(date_container)
        date_layout.setSpacing(6)
        date_layout.setContentsMargins(0, 0, 0, 0)

        date_lbl = QLabel('日期范围：')
        date_lbl.setFixedWidth(70)
        date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        date_lbl.setStyleSheet(FIELD_STYLE)
        date_layout.addWidget(date_lbl)

        self.date_start = QLineEdit()
        self.date_start.setText(QDate.currentDate().addMonths(-1).toString('yyyy-MM-dd'))
        self.date_start.setPlaceholderText('yyyy-MM-dd')
        self.date_start.setStyleSheet(INPUT_STYLE)
        self.date_start.setMinimumWidth(120)
        self.date_start.returnPressed.connect(self._load_logs)
        date_layout.addWidget(self.date_start, 1)

        sep_label = QLabel('至')
        sep_label.setStyleSheet("color: #6B7280; font-size: 13px; padding: 0 4px; background: transparent; border: none;")
        sep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date_layout.addWidget(sep_label)

        self.date_end = QLineEdit()
        self.date_end.setText(QDate.currentDate().toString('yyyy-MM-dd'))
        self.date_end.setPlaceholderText('yyyy-MM-dd')
        self.date_end.setStyleSheet(INPUT_STYLE)
        self.date_end.setMinimumWidth(120)
        self.date_end.returnPressed.connect(self._load_logs)
        date_layout.addWidget(self.date_end, 1)

        row1.addWidget(date_container, 2)

        self.keyword_edit = self._add_search_field(row1, "关键词", "keyword", QLineEdit)
        self.keyword_edit.setObjectName('logKeywordEdit')
        self.keyword_edit.setPlaceholderText('搜索操作类型或详情...')
        self.keyword_edit.setStyleSheet(INPUT_STYLE)
        self.keyword_edit.returnPressed.connect(self._load_logs)

        filter_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.date_clear_btn = QPushButton('📅 全部时间')
        self.date_clear_btn.setStyleSheet(BUTTON_STYLE_QUICK)
        self.date_clear_btn.setFixedWidth(100)
        self.date_clear_btn.clicked.connect(self._clear_date_filter)
        row2.addWidget(self.date_clear_btn)

        self.date_month_btn = QPushButton('📆 本月')
        self.date_month_btn.setStyleSheet(BUTTON_STYLE_QUICK)
        self.date_month_btn.setFixedWidth(100)
        self.date_month_btn.clicked.connect(self._set_date_this_month)
        row2.addWidget(self.date_month_btn)

        self.date_week_btn = QPushButton('📖 本周')
        self.date_week_btn.setStyleSheet(BUTTON_STYLE_QUICK)
        self.date_week_btn.setFixedWidth(100)
        self.date_week_btn.clicked.connect(self._set_date_this_week)
        row2.addWidget(self.date_week_btn)

        row2.addStretch()

        search_btn = QPushButton('查询')
        search_btn.setStyleSheet(BUTTON_STYLE_SEARCH)
        search_btn.setFixedWidth(80)
        search_btn.clicked.connect(self._load_logs)
        row2.addWidget(search_btn)

        reset_btn = QPushButton('重置')
        reset_btn.setStyleSheet(BUTTON_STYLE_RESET)
        reset_btn.setFixedWidth(80)
        reset_btn.clicked.connect(self._on_reset)
        row2.addWidget(reset_btn)

        refresh_btn = QPushButton('刷新')
        refresh_btn.setStyleSheet(BUTTON_STYLE_REFRESH)
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self._load_logs)
        row2.addWidget(refresh_btn)

        filter_layout.addLayout(row2)

        main_layout.addWidget(filter_card)

        log_card = QFrame()
        log_card.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
            }
        """)
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(20, 16, 20, 16)
        log_layout.setSpacing(12)

        log_header = QHBoxLayout()
        log_header.setSpacing(10)

        log_title = QLabel('操作日志')
        log_title.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #1E3A8A;
            padding: 0px;
            background: transparent;
            border: none;
        """)
        log_header.addWidget(log_title)

        self.stats_label = QLabel('')
        self.stats_label.setStyleSheet("""
            color: #6B7280;
            font-size: 12px;
            background: transparent;
            border: none;
            padding: 0 8px;
        """)
        log_header.addWidget(self.stats_label)

        log_header.addStretch()

        log_layout.addLayout(log_header)

        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(
            ['序号', '操作类型', '操作详情', '机器名称', '操作时间']
        )
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.log_table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)

        header = self.log_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.log_table.setColumnWidth(0, 70)
        self.log_table.setMinimumHeight(400)
        self.log_table.setStyleSheet(TABLE_STYLE)

        log_layout.addWidget(self.log_table)
        main_layout.addWidget(log_card, 1)

        self._init_combo_popup_style()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QAbstractItemView):
            if obj not in self._combo_popup_initialized:
                try:
                    w = obj.window()
                    w.setWindowFlags(w.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
                    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                    self._combo_popup_initialized.add(obj)
                except Exception:
                    pass
        elif event.type() == QEvent.KeyPress:
            if hasattr(event, 'key'):
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if isinstance(obj, QComboBox):
                        self._load_logs()
                        return True
        return super().eventFilter(obj, event)

    def _init_combo_popup_style(self):
        pass

    def _on_reset(self):
        self.type_combo.setCurrentIndex(0)
        self.keyword_edit.clear()
        self.date_start.setText(QDate.currentDate().addMonths(-1).toString('yyyy-MM-dd'))
        self.date_end.setText(QDate.currentDate().toString('yyyy-MM-dd'))
        self._load_logs()

    def _load_logs(self):
        from db.database import get_cursor

        self.log_table.clearSelection()

        operation_type = self.type_combo.currentData()
        keyword = self.keyword_edit.text().strip()

        query = '''
            SELECT * FROM operation_log
            WHERE 1=1
        '''
        params = []

        if operation_type:
            query += ' AND operation_type = ?'
            params.append(operation_type)

        date_from = self._validate_date(self.date_start.text().strip(), QDate.currentDate().addMonths(-1).toString('yyyy-MM-dd'))
        date_to = self._validate_date(self.date_end.text().strip(), QDate.currentDate().toString('yyyy-MM-dd'))
        query += ' AND DATE(created_at) >= ? AND DATE(created_at) <= ?'
        params.append(date_from)
        params.append(date_to)

        if keyword:
            query += ' AND (operation_type LIKE ? OR details LIKE ?)'
            params.append(f'%{keyword}%')
            params.append(f'%{keyword}%')

        query += ' ORDER BY created_at DESC LIMIT 500'

        with get_cursor() as cursor:
            cursor.execute(query, params)
            logs = cursor.fetchall()

        self.stats_label.setText(f'共 {len(logs)} 条记录')

        self.log_table.setRowCount(len(logs))
        for i, log in enumerate(logs):
            id_item = QTableWidgetItem(str(i + 1))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            id_item.setData(Qt.ItemDataRole.UserRole, log['id'])
            self.log_table.setItem(i, 0, id_item)

            type_text = self._format_type(log['operation_type'])
            type_item = QTableWidgetItem(type_text)
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            type_item.setToolTip(type_text)
            type_item.setForeground(self._get_type_color(log['operation_type']))
            self.log_table.setItem(i, 1, type_item)

            details_text = self._format_details(log['operation_type'], log['details'])
            details_item = QTableWidgetItem(self._truncate_text(details_text, 80))
            details_item.setToolTip(details_text)
            self.log_table.setItem(i, 2, details_item)

            machine_item = QTableWidgetItem(log['machine_name'] or 'N/A')
            machine_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.log_table.setItem(i, 3, machine_item)

            time_item = QTableWidgetItem(self._format_time(log['created_at']))
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.log_table.setItem(i, 4, time_item)

        if not logs:
            self.log_table.setRowCount(1)
            item = QTableWidgetItem('📭 暂无日志记录')
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QBrush(QColor('#9CA3AF')))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.log_table.setItem(0, 0, item)
            self.log_table.setSpan(0, 0, 1, 5)

    def _get_type_color(self, operation_type):
        color_map = {
            'save_record': QColor('#059669'),
            'update_record': QColor('#D97706'),
            'delete_record': QColor('#DC2626'),
            'save_draft': QColor('#6366F1'),
            'delete_draft': QColor('#EF4444'),
            'import_excel': QColor('#0891B2'),
            'export_excel': QColor('#0EA5E9'),
            'validate': QColor('#8B5CF6'),
            'create_batch': QColor('#10B981'),
            'delete_batch': QColor('#EF4444'),
            'rename_batch': QColor('#F59E0B'),
            'import_records': QColor('#0284C7'),
            'mark_reviewed': QColor('#14B8A6'),
            'mark_reviewed_batch': QColor('#2DD4BF'),
            'export_search': QColor('#3B82F6'),
        }
        return QBrush(color_map.get(operation_type, QColor('#374151')))

    def _validate_date(self, text: str, default: str) -> str:
        """验证日期格式，如果无效返回默认值"""
        if not text:
            return default
        parsed = QDate.fromString(text, 'yyyy-MM-dd')
        if not parsed.isValid():
            return default
        return text

    def _set_date_this_week(self):
        """设置日期范围为本周"""
        today = QDate.currentDate()
        start_of_week = today.addDays(-(today.dayOfWeek() - 1))
        self.date_start.setText(start_of_week.toString('yyyy-MM-dd'))
        self.date_end.setText(today.toString('yyyy-MM-dd'))
        self._load_logs()

    def _clear_date_filter(self):
        """清除日期筛选，重置为全部时间范围"""
        self.date_start.setText(QDate(2000, 1, 1).toString('yyyy-MM-dd'))
        self.date_end.setText(QDate.currentDate().toString('yyyy-MM-dd'))
        self._load_logs()

    def _set_date_this_month(self):
        """设置日期范围为本月"""
        today = QDate.currentDate()
        self.date_start.setText(QDate(today.year(), today.month(), 1).toString('yyyy-MM-dd'))
        self.date_end.setText(today.toString('yyyy-MM-dd'))
        self._load_logs()

    def _format_type(self, operation_type):
        mappings = {
            'save_record': '保存记录',
            'update_record': '更新记录',
            'delete_record': '删除记录',
            'save_draft': '保存草稿',
            'delete_draft': '删除草稿',
            'import_excel': 'Excel导入',
            'export_excel': 'Excel导出',
            'validate': '数据校验',
            'create_batch': '创建批次',
            'delete_batch': '删除批次',
            'rename_batch': '重命名批次',
            'import_records': '批量导入记录',
            'mark_reviewed': '标记已核对',
            'mark_reviewed_batch': '批量标记核对',
            'export_search': '导出检索结果',
        }
        return mappings.get(operation_type, operation_type)

    def _format_details(self, operation_type, details):
        try:
            data = json.loads(details) if details and details != '""' else {}
        except Exception:
            data = {}

        if not data:
            return '无详细信息'

        formatters = {
            'save_record': lambda d: f"记录名称: {d.get('record_name', '未知')} (ID: {d.get('record_id', '未知')}), 模板: {d.get('template_name', '未知')}",
            'update_record': lambda d: f"记录ID: {d.get('record_id', '未知')}",
            'delete_record': lambda d: f"记录ID: {d.get('record_id', '未知')}",
            'save_draft': lambda d: f"草稿名称: {d.get('draft_name', '未知')}",
            'delete_draft': lambda d: f"草稿名称: {d.get('draft_name', '未知')} (ID: {d.get('draft_id', '未知')})",
            'import_excel': lambda d: (
                f"成功: {d.get('success_count', 0)}条, 失败: {d.get('fail_count', 0)}条"
                if 'success_count' in d else f"文件: {d.get('file_path', '未知')}"
            ),
            'export_excel': lambda d: f"导出文件: {d.get('path', '未知')}",
            'validate': lambda d: f"校验记录ID: {d.get('record_id', '未知')}, "
                                  f"结果: {'通过' if d.get('passed') else '未通过'}",
            'create_batch': lambda d: f"批次名称: {d.get('batch_name', '未知')}",
            'delete_batch': lambda d: f"批次ID: {d.get('batch_id', '未知')}, 名称: {d.get('batch_name', '未知')}",
            'rename_batch': lambda d: f"批次ID: {d.get('batch_id', '未知')}, "
                                      f"原名称: {d.get('old_name', '未知')} → 新名称: {d.get('new_name', '未知')}",
            'import_records': lambda d: f"成功: {d.get('success_count', 0)}条, 失败: {d.get('fail_count', 0)}条",
            'mark_reviewed': lambda d: f"记录ID: {d.get('record_id', '未知')}",
            'mark_reviewed_batch': lambda d: f"标记记录数: {len(d.get('record_ids', []))}条",
            'export_search': lambda d: f"导出记录数: {d.get('count', 0)}条, 文件: {d.get('path', '未知')}",
        }

        formatter = formatters.get(operation_type)
        if formatter:
            return formatter(data)

        return ', '.join([f"{k}: {v}" for k, v in data.items()])

    def _format_time(self, timestamp):
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
                return dt.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                return timestamp[:19] if len(timestamp) >= 19 else timestamp
        return ''

    def _truncate_text(self, text, max_length):
        if not text:
            return ''
        if len(text) <= max_length:
            return text
        return text[:max_length] + '...'

    def _on_log_double_clicked(self, item):
        pass

    @staticmethod
    def _detail_label(text: str) -> QLabel:
        label = QLabel(f'{text}：')
        label.setStyleSheet("color: #6B7280; font-size: 13px; background: transparent; border: none;")
        return label

    @staticmethod
    def _detail_value(text: str) -> QLabel:
        label = QLabel(text if text else '-')
        label.setWordWrap(True)
        label.setStyleSheet("color: #1F2937; font-size: 13px; background: transparent; border: none;")
        return label
