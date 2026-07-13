"""
操作日志页面
"""
import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QLabel, QGroupBox, QPushButton, QTableWidgetItem,
    QHeaderView, QComboBox, QLineEdit, QDateEdit,
    QDialog, QTextEdit, QDialogButtonBox
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor, QBrush
from datetime import datetime

from core.logger import Logger


class LogPage(QWidget):
    """操作日志页面"""

    def __init__(self):
        super().__init__()
        self.logger = Logger()
        self._init_ui()
        self._load_logs()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        filter_group = QGroupBox('筛选条件')
        filter_group.setStyleSheet("""
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
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(15)

        type_label = QLabel('操作类型：')
        type_label.setStyleSheet("color: #6B7280; font-size: 13px;")
        filter_layout.addWidget(type_label)

        self.type_combo = QComboBox()
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
        self.type_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
                min-width: 120px;
            }
        """)
        filter_layout.addWidget(self.type_combo)

        date_label = QLabel('日期范围：')
        date_label.setStyleSheet("color: #6B7280; font-size: 13px;")
        filter_layout.addWidget(date_label)

        date_style = """
            QDateEdit {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
                min-width: 110px;
                background-color: white;
            }
            QDateEdit:hover { border-color: #3B82F6; }
            QDateEdit:focus { border-color: #3B82F6; outline: none; }
            QDateEdit::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 22px;
                border: none;
                border-left: 1px solid #E5E7EB;
                border-radius: 0 6px 6px 0;
                background-color: #F3F4F6;
            }
            QDateEdit::drop-down:hover { background-color: #E5E7EB; }
            QDateEdit QAbstractItemView {
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                background: white;
                selection-background-color: #3B82F6;
                selection-color: white;
            }
        """

        self.date_start = QDateEdit()
        self.date_start.setDate(QDate.currentDate().addMonths(-1))
        self.date_start.setDisplayFormat('yyyy-MM-dd')
        self.date_start.setCalendarPopup(True)
        self.date_start.setStyleSheet(date_style)
        filter_layout.addWidget(self.date_start)

        sep_label = QLabel('至')
        sep_label.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        filter_layout.addWidget(sep_label)

        self.date_end = QDateEdit()
        self.date_end.setDate(QDate.currentDate())
        self.date_end.setDisplayFormat('yyyy-MM-dd')
        self.date_end.setCalendarPopup(True)
        self.date_end.setStyleSheet(date_style)
        filter_layout.addWidget(self.date_end)

        self.date_clear_btn = QPushButton('全部时间')
        self.date_clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #6B7280;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #FEE2E2;
                color: #DC2626;
                border-color: #FCA5A5;
            }
        """)
        self.date_clear_btn.clicked.connect(self._clear_date_filter)
        filter_layout.addWidget(self.date_clear_btn)

        self.date_month_btn = QPushButton('本月')
        self.date_month_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #3B82F6;
                border: 1px solid #BFDBFE;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #EFF6FF;
                color: #1D4ED8;
                border-color: #93C5FD;
            }
        """)
        self.date_month_btn.clicked.connect(self._set_date_this_month)
        filter_layout.addWidget(self.date_month_btn)

        keyword_label = QLabel('关键词：')
        keyword_label.setStyleSheet("color: #6B7280; font-size: 13px;")
        filter_layout.addWidget(keyword_label)

        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText('搜索操作类型或详情...')
        self.keyword_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 13px;
                min-width: 200px;
            }
        """)
        filter_layout.addWidget(self.keyword_edit)

        self.search_btn = QPushButton('🔍 查询')
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        self.search_btn.clicked.connect(self._load_logs)
        filter_layout.addWidget(self.search_btn)

        self.refresh_btn = QPushButton('🔄 刷新')
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #F3F4F6;
                color: #1F2937;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 4px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
            }
        """)
        self.refresh_btn.clicked.connect(self._load_logs)
        filter_layout.addWidget(self.refresh_btn)

        filter_layout.addStretch()
        filter_group.setLayout(filter_layout)
        main_layout.addWidget(filter_group)

        log_group = QGroupBox('操作日志')
        log_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #2C3E50;
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                margin-top: 15px;
                padding: 12px 10px 8px 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 8px;
                color: #3498DB;
            }
        """)
        log_layout = QVBoxLayout()

        self.log_table = QTableWidget()
        self.log_table.setColumnCount(5)
        self.log_table.setHorizontalHeaderLabels(
            ['ID', '操作类型', '操作详情', '机器名称', '时间']
        )
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.log_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        header = self.log_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)

        self.log_table.setColumnWidth(0, 60)
        self.log_table.setColumnWidth(1, 120)
        self.log_table.setColumnWidth(3, 150)
        self.log_table.setColumnWidth(4, 180)

        self.log_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                background-color: white;
                font-size: 13px;
                gridline-color: #F0F0F0;
                alternate-background-color: #FAFBFC;
            }
            QTableWidget::item {
                padding: 6px 8px;
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

        self.log_table.itemDoubleClicked.connect(self._on_log_double_clicked)

        log_layout.addWidget(self.log_table)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)

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

        # Date range filter
        date_from = self.date_start.date().toString('yyyy-MM-dd')
        date_to = self.date_end.date().toString('yyyy-MM-dd')
        query += ' AND DATE(created_at) >= ? AND DATE(created_at) <= ?'
        params.append(date_from)
        params.append(date_to)

        if keyword:
            query += ' AND (operation_type LIKE ? OR details LIKE ?)'
            params.append(f'%{keyword}%')
            params.append(f'%{keyword}%')

        query += ' ORDER BY created_at DESC LIMIT 200'

        with get_cursor() as cursor:
            cursor.execute(query, params)
            logs = cursor.fetchall()

        self.log_table.setRowCount(len(logs))
        for i, log in enumerate(logs):
            id_item = QTableWidgetItem(str(i + 1))
            id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            id_item.setData(Qt.ItemDataRole.UserRole, log['id'])
            self.log_table.setItem(i, 0, id_item)

            type_item = QTableWidgetItem(self._format_type(log['operation_type']))
            type_item.setToolTip(log['operation_type'])
            self.log_table.setItem(i, 1, type_item)

            details_text = self._format_details(log['operation_type'], log['details'])
            details_item = QTableWidgetItem(self._truncate_text(details_text, 60))
            details_item.setToolTip(details_text)
            self.log_table.setItem(i, 2, details_item)

            machine_item = QTableWidgetItem(log['machine_name'] or 'N/A')
            self.log_table.setItem(i, 3, machine_item)

            time_item = QTableWidgetItem(self._format_time(log['created_at']))
            self.log_table.setItem(i, 4, time_item)

        if not logs:
            self.log_table.setRowCount(1)
            item = QTableWidgetItem('暂无日志记录')
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setForeground(QBrush(QColor('#9CA3AF')))
            self.log_table.setItem(0, 0, item)
            self.log_table.setSpan(0, 0, 1, 5)

    def _clear_date_filter(self):
        """清除日期筛选，重置为全部时间范围"""
        self.date_start.setDate(QDate(2000, 1, 1))
        self.date_end.setDate(QDate.currentDate())
        self._load_logs()

    def _set_date_this_month(self):
        """设置日期范围为本月"""
        today = QDate.currentDate()
        self.date_start.setDate(QDate(today.year(), today.month(), 1))
        self.date_end.setDate(today)
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
        row = item.row()
        id_item = self.log_table.item(row, 0)
        log_id = id_item.data(Qt.ItemDataRole.UserRole)

        from db.database import get_cursor
        with get_cursor() as cursor:
            cursor.execute('SELECT * FROM operation_log WHERE id = ?', (log_id,))
            log = cursor.fetchone()

        if not log:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f'日志详情 - ID: {log_id}')
        dialog.setMinimumSize(550, 450)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        info_widget = QWidget()
        info_layout = QHBoxLayout(info_widget)
        info_layout.setSpacing(15)

        type_label = QLabel(f'<b>操作类型：</b>{self._format_type(log["operation_type"])}')
        type_label.setStyleSheet("font-size: 13px;")
        info_layout.addWidget(type_label)

        machine_label = QLabel(f'<b>机器名称：</b>{log["machine_name"] or "N/A"}')
        machine_label.setStyleSheet("font-size: 13px;")
        info_layout.addWidget(machine_label)

        time_label = QLabel(f'<b>时间：</b>{self._format_time(log["created_at"])}')
        time_label.setStyleSheet("font-size: 13px;")
        info_layout.addWidget(time_label)

        info_layout.addStretch()
        layout.addWidget(info_widget)

        desc_label = QLabel('<b>操作描述：</b>')
        desc_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(desc_label)

        desc_text = self._format_details(log['operation_type'], log['details'])
        desc_edit = QTextEdit()
        desc_edit.setReadOnly(True)
        desc_edit.setPlainText(desc_text)
        desc_edit.setMaximumHeight(80)
        desc_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid #E5E9EC;
                border-radius: 6px;
                font-size: 13px;
                background-color: #F8FAFC;
            }
        """)
        layout.addWidget(desc_edit)

        raw_label = QLabel('<b>原始数据（JSON）：</b>')
        raw_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(raw_label)

        raw_edit = QTextEdit()
        raw_edit.setReadOnly(True)
        raw_edit.setPlainText(log['details'] or '')
        raw_edit.setStyleSheet("""
            QTextEdit {
                border: 1px solid #E5E9EC;
                border-radius: 6px;
                font-size: 12px;
                font-family: Consolas, monospace;
                background-color: #F8FAFC;
            }
        """)
        layout.addWidget(raw_edit, stretch=1)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(dialog.accept)
        layout.addWidget(button_box)

        dialog.exec()