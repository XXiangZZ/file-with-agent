"""
检索核对页面 - 支持多条件检索
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QLabel, 
    QGroupBox, QDateEdit, QDialog, QScrollArea, QTextEdit, QMessageBox,
    QListView, QHeaderView
)
from PySide6.QtCore import Qt, QDate, QDateTime

from core.record_manager import RecordManager
from core.template_manager import TemplateManager
from core.logger import Logger


class RecordDetailDialog(QDialog):
    """档案详情弹窗"""
    
    def __init__(self, record, parent=None):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("档案详情")
        self.setMinimumSize(600, 500)
        self.resize(650, 600)

        # 从模板动态获取字段显示名称（不写死字段）
        self._field_names = {}
        template_id = record.get('template_id')
        if template_id:
            from core.template_manager import TemplateManager
            tm = TemplateManager()
            tmpl_name = tm.get_template_name(template_id)
            if tmpl_name:
                for f in tm.get_fields(tmpl_name):
                    self._field_names[f['key']] = f['name']

        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        
        # 基本信息
        info_group = QGroupBox("基本信息")
        info_layout = QFormLayout(info_group)
        info_layout.addRow("记录ID:", QLabel(str(self.record.get('id', ''))))
        info_layout.addRow("批次ID:", QLabel(str(self.record.get('batch_id', ''))))
        info_layout.addRow("模板ID:", QLabel(str(self.record.get('template_id', ''))))
        info_layout.addRow("归档类型:", QLabel(self.record.get('filing_type', '')))
        info_layout.addRow("审核状态:", QLabel(self.record.get('review_status', '')))
        info_layout.addRow("录入时间:", QLabel(self.record.get('created_at', '')))
        info_layout.addRow("更新时间:", QLabel(self.record.get('updated_at', '')))

        # 字段统计
        template_count = len(self._field_names)
        value_count = len(self.record.get('values', {}))
        diff = template_count - value_count
        if diff == 0:
            stats_text = f"模板字段: {template_count}（已全部填写）"
        else:
            stats_text = f"模板字段: {template_count}    当前记录: {value_count}（缺少 {diff} 个字段）"
        info_layout.addRow("字段统计:", QLabel(stats_text))

        content_layout.addWidget(info_group)

        # 字段值 — 按模板字段顺序遍历，缺失的显示"无"
        values = self.record.get('values', {})
        if self._field_names:
            fields_group = QGroupBox("字段内容")
            fields_layout = QVBoxLayout(fields_group)

            # 字段区域可滚动
            field_scroll = QScrollArea()
            field_scroll.setWidgetResizable(True)
            field_scroll.setMaximumHeight(400)
            field_scroll_widget = QWidget()
            field_scroll_layout = QFormLayout(field_scroll_widget)

            for field_key, field_name in self._field_names.items():
                value = values.get(field_key, '')
                if value and str(value).strip():
                    display_value = str(value)
                else:
                    display_value = "无"

                if len(display_value) > 50:
                    text_edit = QTextEdit()
                    text_edit.setPlainText(display_value)
                    text_edit.setReadOnly(True)
                    text_edit.setMaximumHeight(80)
                    field_scroll_layout.addRow(field_name + ":", text_edit)
                else:
                    field_scroll_layout.addRow(field_name + ":", QLabel(display_value))

            field_scroll.setWidget(field_scroll_widget)
            fields_layout.addWidget(field_scroll)
            content_layout.addWidget(fields_group)
        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)
        
        # 关闭按钮
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)


class SearchPage(QWidget):
    """检索核对页面"""

    def __init__(self):
        super().__init__()
        self.record_manager = RecordManager()
        self.template_manager = TemplateManager()
        self.logger = Logger()
        self.search_results = []
        self._init_ui()
        self._load_templates()
        self._on_search()

    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # 搜索区域
        search_group = QGroupBox('检索条件')
        search_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #2C3E50;
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                margin-top: 10px;
                padding: 12px 10px 8px 10px;
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
        
        # 使用网格布局
        search_layout = QVBoxLayout()
        
        # 第一行：模板选择 + 审核状态
        row1 = QHBoxLayout()
        row1.setSpacing(15)
        
        template_label = QLabel("模板:")
        template_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.template_combo = QComboBox()
        self.template_combo.setView(QListView())
        self.template_combo.setMinimumWidth(150)
        row1.addWidget(template_label)
        row1.addWidget(self.template_combo)
        
        status_label = QLabel("审核状态:")
        status_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.status_combo = QComboBox()
        self.status_combo.setView(QListView())
        self.status_combo.addItems(["全部", "待审核", "已审核", "已上传"])
        self.status_combo.setMinimumWidth(120)
        row1.addWidget(status_label)
        row1.addWidget(self.status_combo)
        
        row1.addStretch()
        search_layout.addLayout(row1)
        
        # 第二行：档案编号 + 题名
        row2 = QHBoxLayout()
        row2.setSpacing(15)
        
        archive_no_label = QLabel("档案编号:")
        archive_no_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.archive_no_edit = QLineEdit()
        self.archive_no_edit.setPlaceholderText("输入档案编号关键词")
        row2.addWidget(archive_no_label)
        row2.addWidget(self.archive_no_edit)
        
        title_label = QLabel("题名:")
        title_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("输入题名关键词")
        row2.addWidget(title_label)
        row2.addWidget(self.title_edit)
        
        row2.addStretch()
        search_layout.addLayout(row2)
        
        # 第三行：部门 + 录入时间范围
        row3 = QHBoxLayout()
        row3.setSpacing(15)
        
        dept_label = QLabel("部门:")
        dept_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.dept_edit = QLineEdit()
        self.dept_edit.setPlaceholderText("输入部门名称")
        row3.addWidget(dept_label)
        row3.addWidget(self.dept_edit)
        
        date_label = QLabel("录入时间:")
        date_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        
        date_layout = QHBoxLayout()
        date_layout.setSpacing(5)
        
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setDate(QDate().addYears(-1))
        self.start_date_edit.setFixedWidth(120)
        
        date_separator = QLabel("至")
        
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setFixedWidth(120)
        
        date_layout.addWidget(self.start_date_edit)
        date_layout.addWidget(date_separator)
        date_layout.addWidget(self.end_date_edit)
        
        row3.addWidget(date_label)
        row3.addLayout(date_layout)
        
        row3.addStretch()
        search_layout.addLayout(row3)
        
        # 第四行：全文搜索 + 按钮
        row4 = QHBoxLayout()
        row4.setSpacing(15)
        
        keyword_label = QLabel("全文搜索:")
        keyword_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("输入任意关键词进行全文检索")
        row4.addWidget(keyword_label)
        row4.addWidget(self.keyword_edit, stretch=1)
        
        search_btn = QPushButton('🔍 搜索')
        search_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498DB;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
        """)
        search_btn.clicked.connect(self._on_search)
        row4.addWidget(search_btn)
        
        reset_btn = QPushButton('🔄 重置')
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #95A5A6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #7F8C8D;
            }
        """)
        reset_btn.clicked.connect(self._on_reset)
        row4.addWidget(reset_btn)
        
        search_layout.addLayout(row4)
        
        search_group.setLayout(search_layout)
        main_layout.addWidget(search_group)

        # 结果区域
        result_group = QGroupBox('检索结果')
        result_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                color: #2C3E50;
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                margin-top: 10px;
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
        result_layout = QVBoxLayout()

        # 结果统计
        self.result_count_label = QLabel("共 0 条记录")
        self.result_count_label.setStyleSheet("color: #7F8C8D; font-size: 13px;")
        result_layout.addWidget(self.result_count_label)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(8)
        self.result_table.setHorizontalHeaderLabels(
            ['ID', '档案编号', '题名', '部门', '录入时间', '审核状态', '归档类型', '操作']
        )
        self.result_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                background-color: white;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 #34495E,
                    stop: 1 #2C3E50
                );
                color: white;
                padding: 10px;
                border: none;
                font-weight: bold;
            }
            QTableWidget::item {
                padding: 8px;
                border-bottom: 1px solid #E5E9EC;
            }
            QTableWidget::item:selected {
                background-color: #3498DB;
                color: white;
            }
        """)
        
        # 设置列宽
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.setColumnWidth(1, 150)
        self.result_table.setColumnWidth(2, 200)
        self.result_table.setColumnWidth(3, 120)
        self.result_table.setColumnWidth(4, 160)
        self.result_table.setColumnWidth(5, 100)
        self.result_table.setColumnWidth(6, 100)
        self.result_table.setColumnWidth(7, 160)
        
        # 表头自适应
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.verticalHeader().setDefaultSectionSize(45)
        self.result_table.verticalHeader().setVisible(False)
        result_layout.addWidget(self.result_table)

        result_group.setLayout(result_layout)
        main_layout.addWidget(result_group)

        # 底部按钮栏
        btn_layout = QHBoxLayout()

        self.review_btn = QPushButton('✅ 标记为已核对')
        self.review_btn.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2ECC71;
            }
            QPushButton:disabled {
                background-color: #BDC3C7;
            }
        """)
        self.review_btn.clicked.connect(self._on_mark_reviewed)
        btn_layout.addWidget(self.review_btn)

        self.detail_btn = QPushButton('👁 查看详情')
        self.detail_btn.setStyleSheet("""
            QPushButton {
                background-color: #9B59B6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #8E44AD;
            }
            QPushButton:disabled {
                background-color: #BDC3C7;
            }
        """)
        self.detail_btn.clicked.connect(self._on_view_detail)
        btn_layout.addWidget(self.detail_btn)

        btn_layout.addStretch()
        
        # 导出按钮
        self.export_btn = QPushButton('📥 导出结果')
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #F39C12;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #F1C40F;
            }
            QPushButton:disabled {
                background-color: #BDC3C7;
            }
        """)
        self.export_btn.clicked.connect(self._on_export)
        btn_layout.addWidget(self.export_btn)

        main_layout.addLayout(btn_layout)

    def _load_templates(self):
        """加载模板列表"""
        self.template_combo.addItem("全部", None)
        templates = self.record_manager.get_all_templates()
        for template in templates:
            self.template_combo.addItem(template['name'], template['id'])

    def _on_search(self):
        """执行检索"""
        conditions = {}
        
        # 模板ID
        template_id = self.template_combo.currentData()
        if template_id:
            conditions['template_id'] = template_id
        
        # 审核状态
        status_text = self.status_combo.currentText()
        if status_text == "待审核":
            conditions['review_status'] = 'pending'
        elif status_text == "已审核":
            conditions['review_status'] = 'reviewed'
        elif status_text == "已上传":
            conditions['upload_status'] = 'uploaded'
        
        # 档案编号
        archive_no = self.archive_no_edit.text().strip()
        if archive_no:
            conditions['archive_no'] = archive_no
        
        # 题名
        title = self.title_edit.text().strip()
        if title:
            conditions['title'] = title
        
        # 部门
        dept = self.dept_edit.text().strip()
        if dept:
            conditions['dept'] = dept
        
        # 录入时间范围
        start_date = self.start_date_edit.date().toString("yyyy-MM-dd")
        end_date = self.end_date_edit.date().toString("yyyy-MM-dd")
        conditions['start_date'] = start_date + " 00:00:00"
        conditions['end_date'] = end_date + " 23:59:59"
        
        # 全文搜索
        keyword = self.keyword_edit.text().strip()
        if keyword:
            conditions['keyword'] = keyword
        
        # 执行检索
        self.search_results = self.record_manager.advanced_search(conditions)
        
        # 显示结果
        self._display_results()
        
        self.logger.log('advanced_search', {'conditions': conditions, 'count': len(self.search_results)})

    def _display_results(self):
        """显示检索结果"""
        self.result_table.setRowCount(0)
        self.result_count_label.setText(f"共 {len(self.search_results)} 条记录")
        
        for row, record in enumerate(self.search_results):
            values = record.get('values', {})
            
            # 获取字段值
            archive_no = values.get('file_no', values.get('bianhao', values.get('archive_no', '')))
            title = values.get('title', values.get('mingcheng', values.get('subject', '')))
            dept = values.get('dept', values.get('bumen', values.get('department', '')))
            
            # 审核状态映射
            review_status = record.get('review_status', 'pending')
            status_text = {
                'pending': '待审核',
                'reviewed': '已审核',
                'uploaded': '已上传'
            }.get(review_status, review_status)
            
            # 归档类型映射
            filing_type = record.get('filing_type', '')
            filing_text = '以卷归档' if filing_type == 'volume' else '以件归档'
            
            # 创建行
            self.result_table.insertRow(row)
            
            self.result_table.setItem(row, 0, QTableWidgetItem(str(record['id'])))
            self.result_table.setItem(row, 1, QTableWidgetItem(archive_no))
            self.result_table.setItem(row, 2, QTableWidgetItem(title))
            self.result_table.setItem(row, 3, QTableWidgetItem(dept))
            self.result_table.setItem(row, 4, QTableWidgetItem(record.get('created_at', '')[:19]))
            self.result_table.setItem(row, 5, QTableWidgetItem(status_text))
            self.result_table.setItem(row, 6, QTableWidgetItem(filing_text))
            
            # 操作按钮
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 0, 4, 0)
            action_layout.setSpacing(6)
            
            view_btn = QPushButton("查看")
            view_btn.setFixedSize(56, 28)
            view_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3498DB;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2980B9;
                }
            """)
            view_btn.clicked.connect(lambda checked, r=record: self._show_detail(r))
            action_layout.addWidget(view_btn)
            
            review_btn = QPushButton("核对")
            review_btn.setFixedSize(56, 28)
            review_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27AE60;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2ECC71;
                }
            """)
            review_btn.clicked.connect(lambda checked, id=record['id']: self._mark_single_reviewed(id))
            action_layout.addWidget(review_btn)
            
            self.result_table.setCellWidget(row, 7, action_widget)
        
        # 更新按钮状态
        has_results = len(self.search_results) > 0
        self.review_btn.setEnabled(has_results)
        self.detail_btn.setEnabled(has_results)
        self.export_btn.setEnabled(has_results)

    def _on_reset(self):
        """重置检索条件"""
        self.template_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.archive_no_edit.clear()
        self.title_edit.clear()
        self.dept_edit.clear()
        self.keyword_edit.clear()
        self.start_date_edit.setDate(QDate().addYears(-1))
        self.end_date_edit.setDate(QDate.currentDate())
        self.result_table.setRowCount(0)
        self.result_count_label.setText("共 0 条记录")
        self.search_results = []
        self.review_btn.setEnabled(False)
        self.detail_btn.setEnabled(False)
        self.export_btn.setEnabled(False)

    def _on_mark_reviewed(self):
        """批量标记为已核对"""
        selected_rows = self.result_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要标记的记录")
            return
        
        record_ids = []
        for row in selected_rows:
            record_id = int(self.result_table.item(row.row(), 0).text())
            record_ids.append(record_id)
        
        for record_id in record_ids:
            self.record_manager.update_record_status(record_id, review_status='reviewed')
        
        self.logger.log('mark_reviewed_batch', {'record_ids': record_ids})
        QMessageBox.information(self, "提示", f"已成功标记 {len(record_ids)} 条记录为已核对")
        self._on_search()

    def _mark_single_reviewed(self, record_id):
        """标记单条记录为已核对"""
        self.record_manager.update_record_status(record_id, review_status='reviewed')
        self.logger.log('mark_reviewed', {'record_id': record_id})
        self._on_search()

    def _on_view_detail(self):
        """查看选中记录详情"""
        selected_rows = self.result_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要查看的记录")
            return
        
        row = selected_rows[0].row()
        record = self.search_results[row]
        self._show_detail(record)

    def _show_detail(self, record):
        """显示档案详情"""
        dialog = RecordDetailDialog(record, self)
        dialog.exec()

    def _on_export(self):
        """导出检索结果"""
        if not self.search_results:
            QMessageBox.warning(self, "提示", "没有可导出的数据")
            return
        
        from core.export_manager import ExportManager
        from PySide6.QtWidgets import QFileDialog
        
        export_manager = ExportManager()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出检索结果", "检索结果", "Excel Files (*.xlsx)"
        )
        
        if path:
            export_manager.export_search_results(self.search_results, path)
            QMessageBox.information(self, "提示", f"导出成功\n{path}")
            self.logger.log('export_search', {'count': len(self.search_results), 'path': path})