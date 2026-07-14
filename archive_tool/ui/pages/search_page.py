"""
检索核对页面 - 支持多条件并行筛查
"""
from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
            QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QLabel,
            QGroupBox, QDialog, QScrollArea, QTextEdit, QMessageBox,
            QHeaderView, QAbstractItemView, QLayout, QSizePolicy
        )
from PySide6.QtCore import Qt, QEvent

from core.record_manager import RecordManager
from core.template_manager import TemplateManager
from core.logger import Logger
from ui.components.fixed_combo import FixedComboBox


class RecordDetailDialog(QDialog):
    """档案详情弹窗"""
    
    def __init__(self, record, parent=None):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("档案详情")
        self.setMinimumSize(480, 400)
        self.resize(520, 450)

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
        layout.setSpacing(12)

        info_group = QGroupBox("基本信息")
        info_layout = QFormLayout(info_group)
        info_layout.addRow("记录ID:", QLabel(str(self.record.get('id', ''))))
        info_layout.addRow("模板:", QLabel(str(self.record.get('template_name', ''))))
        filing_type = self.record.get('filing_type', '')
        filing_display = '以卷归档' if filing_type == 'volume' else '以件归档'
        info_layout.addRow("归档类型:", QLabel(filing_display))
        review_map = {'pending': '待审核', 'reviewed': '已审核', 'uploaded': '已上传'}
        info_layout.addRow("审核状态:", QLabel(review_map.get(self.record.get('review_status', ''), '')))
        info_layout.addRow("录入时间:", QLabel(str(self.record.get('created_at', '') or '')[:19]))
        layout.addWidget(info_group)

        values_group = QGroupBox("字段内容")
        values_layout = QFormLayout(values_group)
        
        values = self.record.get('values', {})
        for key, display_name in self._field_names.items():
            value = values.get(key, '')
            value_label = QLabel(str(value) if value else '')
            value_label.setStyleSheet("color: #374151;")
            values_layout.addRow(f"{display_name}:", value_label)
        
        if not self._field_names:
            for key, value in values.items():
                value_label = QLabel(str(value) if value else '')
                value_label.setStyleSheet("color: #374151;")
                values_layout.addRow(f"{key}:", value_label)
        
        scroll = QScrollArea()
        scroll.setWidget(values_group)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        layout.addWidget(scroll)

        close_btn = QPushButton("关闭")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.close)
        btn_layout = QHBoxLayout()
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
        self._row_records = []
        self._init_ui()
        self._load_options()
        self._on_search()

    def _init_ui(self):
        """初始化UI"""
        self.setStyleSheet("""
            QComboBox {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                font-size: 13px;
                background: white;
                min-height: 26px;
                max-height: 26px;
                padding: 0 8px;
            }
            QComboBox::drop-down {
                border: none;
                width: 32px;
                border-radius: 0 6px 6px 0;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                background: white;
                selection-background-color: #EFF6FF;
                selection-color: #1E40AF;
                outline: none;
                padding: 4px 0;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px 12px;
                font-size: 12px;
                color: #374151;
                min-height: 24px;
                border-radius: 0;
                margin: 0;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #EFF6FF;
                color: #1E40AF;
            }
            QComboBox QAbstractItemView::item:selected {
                background: #EFF6FF;
                color: #1E40AF;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

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
        
        search_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.setSpacing(15)
        
        self._add_search_field(row1, "档案类型", "archive_type", QLineEdit)
        self._add_search_field(row1, "全宗号", "quanzong_no", QLineEdit)
        self._add_search_field(row1, "分类号", "class_no", QLineEdit)
        self._add_search_field(row1, "类目名称", "category_name", QLineEdit)
        
        row1.addStretch()
        search_layout.addLayout(row1)
        
        row2 = QHBoxLayout()
        row2.setSpacing(15)
        
        self._add_search_field(row2, "年度", "year", FixedComboBox)
        self._add_search_field(row2, "保管期限", "retention_period", FixedComboBox)
        
        row2.addStretch()
        
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
        search_btn.setFixedWidth(100)
        row2.addWidget(search_btn)
        
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
        reset_btn.setFixedWidth(100)
        row2.addWidget(reset_btn)
        
        self.export_btn = QPushButton('📥 导出')
        self.export_btn.setFixedWidth(100)
        self.export_btn.setFixedHeight(32)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #F39C12;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #F1C40F;
            }
            QPushButton:disabled {
                background-color: #BDC3C7;
            }
        """)
        self.export_btn.clicked.connect(self._on_export)
        self.export_btn.setEnabled(False)
        row2.addWidget(self.export_btn)
        
        search_layout.addLayout(row2)
        
        search_group.setLayout(search_layout)
        main_layout.addWidget(search_group)

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

        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)
        
        self.result_count_label = QLabel("共 0 条记录")
        self.result_count_label.setStyleSheet("color: #7F8C8D; font-size: 13px;")
        stats_layout.addWidget(self.result_count_label)
        
        stats_layout.addStretch()
        
        result_layout.addLayout(stats_layout)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(10)
        self.result_table.setHorizontalHeaderLabels([
            '文件档号', '文件题名', '文件编号', '名称', '模板', '归档类型', '审核状态', '批次', '年度', '操作'
        ])
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
                padding: 12px 16px;
                border: none;
                font-weight: bold;
            }
            QTableWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #EEF2F4;
                text-align: center;
            }
            QTableWidget::item:selected {
                background-color: #E8EFFE;
                color: #1E40AF;
            }
            QTableWidget::item:alternate {
                background-color: #FBFCFD;
            }
            QScrollBar:horizontal {
                height: 10px;
                background: transparent;
                margin: 0px 20px 0 20px;
            }
            QScrollBar::handle:horizontal {
                background: #B0B7BD;
                min-width: 20px;
                border-radius: 5px;
            }
            QScrollBar:vertical {
                width: 10px;
                background: transparent;
                margin: 20px 0 20px 0;
            }
            QScrollBar::handle:vertical {
                background: #B0B7BD;
                min-height: 20px;
                border-radius: 5px;
            }
        """)

        self.result_table.setColumnWidth(0, 150)
        self.result_table.setColumnWidth(1, 200)
        self.result_table.setColumnWidth(2, 150)
        self.result_table.setColumnWidth(3, 170)
        self.result_table.setColumnWidth(4, 120)
        self.result_table.setColumnWidth(5, 100)
        self.result_table.setColumnWidth(6, 100)
        self.result_table.setColumnWidth(7, 120)
        self.result_table.setColumnWidth(8, 80)
        self.result_table.setColumnWidth(9, 220)
        
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.result_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        
        self.result_table.verticalHeader().setDefaultSectionSize(46)
        self.result_table.verticalHeader().setMinimumSectionSize(40)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.horizontalHeader().setFixedHeight(48)
        self.result_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.result_table.setViewportMargins(0, 0, 0, 8)
        result_layout.addWidget(self.result_table)
        result_layout.setStretch(0, 0)
        result_layout.setStretch(1, 1)

        result_group.setLayout(result_layout)
        main_layout.addWidget(result_group)

        main_layout.setStretch(0, 0)
        main_layout.setStretch(1, 1)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if hasattr(event, 'key'):
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if isinstance(obj, FixedComboBox):
                        self._on_search()
                        return True
        return super().eventFilter(obj, event)

    def _add_search_field(self, layout, label_text, field_key, widget_type, placeholder=""):
        """添加搜索字段"""
        label = QLabel(f"{label_text}:")
        label.setStyleSheet("font-weight: bold; color: #2C3E50;")

        if widget_type == FixedComboBox:
            widget = FixedComboBox()
            widget.setObjectName(f"{field_key}Combo")
            widget.setMinimumWidth(140)
            widget.addItem("全部", None)
            widget.installEventFilter(self)
        else:
            widget = QLineEdit()
            widget.setObjectName(f"{field_key}Edit")
            widget.setMinimumWidth(140)
            if placeholder:
                widget.setPlaceholderText(placeholder)
            widget.returnPressed.connect(self._on_search)
        
        setattr(self, f"{field_key}_widget", widget)
        layout.addWidget(label)
        layout.addWidget(widget)

    def _load_options(self):
        """加载下拉选项"""
        years = self.record_manager.get_all_years()
        for year in years:
            self.year_widget.addItem(str(year['year']), year['year'])
        
        self.retention_period_widget.addItems(["永久", "30年", "10年", "长期", "短期"])

    def _on_search(self):
        """执行检索"""
        conditions = {}
        
        archive_type = self.archive_type_widget.text().strip()
        if archive_type:
            conditions['archive_type'] = archive_type
        
        quanzong_no = self.quanzong_no_widget.text().strip()
        if quanzong_no:
            conditions['quanzong_no'] = quanzong_no
        
        class_no = self.class_no_widget.text().strip()
        if class_no:
            conditions['class_no'] = class_no
        
        category_name = self.category_name_widget.text().strip()
        if category_name:
            conditions['category_name'] = category_name
        
        year = self.year_widget.currentData()
        if year:
            conditions['year'] = year
        
        retention_period = self.retention_period_widget.currentText()
        if retention_period != "全部":
            conditions['retention_period'] = retention_period
        
        self.search_results = self.record_manager.advanced_search(conditions)
        self._display_results()

    def _extract_field_value(self, values, candidate_keys):
        """从values字典中按候选key顺序提取第一个非空值"""
        for key in candidate_keys:
            val = values.get(key)
            if val is not None and str(val).strip() != '':
                return str(val)
        return ''

    def _display_results(self):
        """显示检索结果"""
        self.result_table.setRowCount(0)
        self.result_count_label.setText(f"共 {len(self.search_results)} 条记录")

        self._row_records = []

        danghao_keys = ['wj_wenjiandanghao', 'wj_archive_code']
        timing_keys = ['wj_wentiming', 'wj_title', 'wj_hetongmingcheng']
        bianhao_keys = ['wj_wenjianbianhao', 'wj_file_number', 'wj_hetongbianhao']

        for row, record in enumerate(self.search_results):
            values = record.get('values', {})
            self._row_records.append(record)

            self.result_table.insertRow(row)

            danghao = self._extract_field_value(values, danghao_keys)
            item0 = QTableWidgetItem(danghao)
            item0.setToolTip(danghao)
            self.result_table.setItem(row, 0, item0)

            timing = self._extract_field_value(values, timing_keys)
            item1 = QTableWidgetItem(timing)
            item1.setToolTip(timing)
            self.result_table.setItem(row, 1, item1)

            bianhao = self._extract_field_value(values, bianhao_keys)
            item2 = QTableWidgetItem(bianhao)
            item2.setToolTip(bianhao)
            self.result_table.setItem(row, 2, item2)

            record_name = record.get('name', '')
            item3 = QTableWidgetItem(str(record_name) if record_name else '')
            item3.setToolTip(str(record_name) if record_name else '')
            self.result_table.setItem(row, 3, item3)
            
            template_name = record.get('template_name', '')
            item4 = QTableWidgetItem(str(template_name) if template_name else '')
            item4.setToolTip(str(template_name) if template_name else '')
            self.result_table.setItem(row, 4, item4)
            
            filing_type = record.get('filing_type', '')
            filing_display = '以卷归档' if filing_type == 'volume' else '以件归档'
            item5 = QTableWidgetItem(filing_display)
            item5.setToolTip(filing_display)
            self.result_table.setItem(row, 5, item5)
            
            review_map = {'pending': '待审核', 'reviewed': '已审核', 'uploaded': '已上传'}
            review_status = review_map.get(record.get('review_status', ''), '')
            item6 = QTableWidgetItem(review_status)
            item6.setToolTip(review_status)
            self.result_table.setItem(row, 6, item6)
            
            batch_name = record.get('batch_name', '')
            item7 = QTableWidgetItem(str(batch_name) if batch_name else '')
            item7.setToolTip(str(batch_name) if batch_name else '')
            self.result_table.setItem(row, 7, item7)
            
            year = record.get('year', '')
            item8 = QTableWidgetItem(str(year) if year else '')
            item8.setToolTip(str(year) if year else '')
            self.result_table.setItem(row, 8, item8)

            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(6, 2, 6, 2)
            action_layout.setSpacing(8)
            action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            view_btn = QPushButton("查看")
            view_btn.setFixedSize(70, 28)
            view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            view_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3498DB;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 0px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2980B9;
                }
            """)
            view_btn.clicked.connect(lambda checked, r=record: self._show_detail(r))
            action_layout.addWidget(view_btn)

            review_btn = QPushButton("核对")
            review_btn.setFixedSize(70, 28)
            review_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            review_btn.setStyleSheet("""
                QPushButton {
                    background-color: #27AE60;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 0px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2ECC71;
                }
            """)
            review_btn.clicked.connect(lambda checked, rid=record['id']: self._mark_single_reviewed(rid))
            action_layout.addWidget(review_btn)

            self.result_table.setCellWidget(row, 9, action_widget)

        has_results = len(self.search_results) > 0
        self.export_btn.setEnabled(has_results)

    def _on_reset(self):
        """重置检索条件"""
        self.archive_type_widget.clear()
        self.quanzong_no_widget.clear()
        self.class_no_widget.clear()
        self.category_name_widget.clear()
        self.year_widget.setCurrentIndex(0)
        self.retention_period_widget.setCurrentIndex(0)
        self.result_table.setRowCount(0)
        self.result_count_label.setText("共 0 条记录")
        self.search_results = []
        self.export_btn.setEnabled(False)

    def _on_mark_reviewed(self):
        """批量标记为已核对"""
        selected_rows = self.result_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "提示", "请先选择要标记的记录")
            return

        record_ids = []
        for model_index in selected_rows:
            row = model_index.row()
            if row < len(self._row_records):
                record_ids.append(self._row_records[row]['id'])
        
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
        
        from PySide6.QtWidgets import QFileDialog
        
        path, _ = QFileDialog.getSaveFileName(
            self, "导出检索结果", "检索结果", "Excel Files (*.xlsx)"
        )
        
        if path:
            import openpyxl
            from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
            
            wb = openpyxl.Workbook()
            
            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
            header_alignment = Alignment(horizontal="center", vertical="center")
            thin_border = Border(
                left=Side(style='thin'),
                right=Side(style='thin'),
                top=Side(style='thin'),
                bottom=Side(style='thin')
            )
            
            headers = ['文件档号', '文件题名', '文件编号', '名称', '模板', '归档类型', '审核状态', '批次', '年度']
            data = []
            danghao_keys = ['wj_wenjiandanghao', 'wj_archive_code']
            timing_keys = ['wj_wentiming', 'wj_title', 'wj_hetongmingcheng']
            bianhao_keys = ['wj_wenjianbianhao', 'wj_file_number', 'wj_hetongbianhao']
            for record in self.search_results:
                values = record.get('values', {})
                def _extract(keys):
                    for k in keys:
                        v = values.get(k)
                        if v is not None and str(v).strip() != '':
                            return str(v)
                    return ''
                danghao = _extract(danghao_keys)
                timing = _extract(timing_keys)
                bianhao = _extract(bianhao_keys)
                record_name = record.get('name', '')
                filing_type = '以卷归档' if record.get('filing_type') == 'volume' else '以件归档'
                review_map = {'pending': '待审核', 'reviewed': '已审核', 'uploaded': '已上传'}
                review_status = review_map.get(record.get('review_status', ''), '')
                data.append([
                    danghao,
                    timing,
                    bianhao,
                    str(record_name) if record_name else '',
                    str(record.get('template_name', '')),
                    filing_type,
                    review_status,
                    str(record.get('batch_name', '')),
                    str(record.get('year', ''))
                ])
            
            ws_summary = wb.active
            ws_summary.title = "检索结果汇总"
            
            for col, header in enumerate(headers, 1):
                cell = ws_summary.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border
            
            for row_idx, row_data in enumerate(data, 2):
                for col_idx, value in enumerate(row_data, 1):
                    cell = ws_summary.cell(row=row_idx, column=col_idx, value=str(value))
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.border = thin_border
            
            for col in range(1, len(headers) + 1):
                ws_summary.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20
            
            templates = {}
            for record in self.search_results:
                template_name = record.get('template_name', '')
                if template_name not in templates:
                    templates[template_name] = []
                templates[template_name].append(record)
            
            for template_name, records in templates.items():
                if template_name:
                    ws = wb.create_sheet(title=template_name[:31])
                else:
                    ws = wb.create_sheet(title="未分类")
                
                all_fields = set()
                for record in records:
                    values = record.get('values', {})
                    all_fields.update(values.keys())
                
                from core.template_manager import TemplateManager
                template_manager = TemplateManager()
                template = template_manager.get_template_by_name(template_name)
                
                ordered_fields = []
                if template and 'fields' in template:
                    for field in template['fields']:
                        field_key = field.get('key', '')
                        if field_key in all_fields:
                            ordered_fields.append(field_key)
                
                for field_key in all_fields:
                    if field_key not in ordered_fields:
                        ordered_fields.append(field_key)
                
                field_labels = {}
                if template and 'fields' in template:
                    for field in template['fields']:
                        field_key = field.get('key', '')
                        field_labels[field_key] = field.get('name', field_key)
                
                danghao_keys = ['wj_wenjiandanghao', 'wj_archive_code']
                timing_keys = ['wj_wentiming', 'wj_title', 'wj_hetongmingcheng']
                bianhao_keys = ['wj_wenjianbianhao', 'wj_file_number', 'wj_hetongbianhao']
                def _extract(values, keys):
                    for k in keys:
                        v = values.get(k)
                        if v is not None and str(v).strip() != '':
                            return str(v)
                    return ''
                
                ws_headers = ['文件档号', '文件题名', '文件编号', '名称'] + [field_labels.get(f, f) for f in ordered_fields]
                
                for col, header in enumerate(ws_headers, 1):
                    cell = ws.cell(row=1, column=col, value=header)
                    cell.font = header_font
                    cell.fill = header_fill
                    cell.alignment = header_alignment
                    cell.border = thin_border
                
                for row_idx, record in enumerate(records, 2):
                    values = record.get('values', {})
                    row_data = [
                        _extract(values, danghao_keys),
                        _extract(values, timing_keys),
                        _extract(values, bianhao_keys),
                        str(record.get('name', ''))
                    ]
                    for field_key in ordered_fields:
                        row_data.append(str(values.get(field_key, '')))
                    
                    for col_idx, value in enumerate(row_data, 1):
                        cell = ws.cell(row=row_idx, column=col_idx, value=str(value))
                        cell.alignment = Alignment(horizontal="center", vertical="center")
                        cell.border = thin_border
                
                for col in range(1, len(ws_headers) + 1):
                    ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 20
            
            wb.save(path)
            
            QMessageBox.information(self, "提示", f"导出成功\n{path}")
            self.logger.log('export_search', {'count': len(self.search_results), 'path': path})