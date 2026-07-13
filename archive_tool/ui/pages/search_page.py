"""
检索核对页面 - 支持多条件检索
"""
from PySide6.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
            QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QLabel,
            QGroupBox, QDialog, QScrollArea, QTextEdit, QMessageBox,
            QListView, QHeaderView, QAbstractItemView, QLayout, QSizePolicy
        )
from PySide6.QtCore import Qt, QEvent

from core.record_manager import RecordManager
from core.template_manager import TemplateManager
from core.logger import Logger


class RecordDetailDialog(QDialog):
    """档案详情弹窗"""
    
    def __init__(self, record, parent=None):
        super().__init__(parent)
        self.record = record
        self.setWindowTitle("档案详情")
        self.setMinimumSize(380, 300)
        self.resize(420, 340)

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
        layout.setSpacing(10)

        # 基本信息
        info_group = QGroupBox("基本信息")
        info_layout = QFormLayout(info_group)
        info_layout.addRow("记录ID:", QLabel(str(self.record.get('id', ''))))
        info_layout.addRow("批次ID:", QLabel(str(self.record.get('batch_id', ''))))
        info_layout.addRow("模板:", QLabel(str(self.record.get('template_name', ''))))
        info_layout.addRow("归档类型:", QLabel('以卷归档' if self.record.get('filing_type') == 'volume' else '以件归档'))
        review_map = {'pending': '待审核', 'reviewed': '已审核', 'uploaded': '已上传'}
        info_layout.addRow("审核状态:", QLabel(review_map.get(self.record.get('review_status', ''), '')))
        info_layout.addRow("录入时间:", QLabel(str(self.record.get('created_at', '') or '')[:19]))

        # 字段统计
        template_count = len(self._field_names)
        value_count = len(self.record.get('values', {}))
        diff = template_count - value_count
        if diff == 0:
            stats_text = f"模板字段: {template_count}（已全部填写）"
        else:
            stats_text = f"模板字段: {template_count}    当前记录: {value_count}（缺少 {diff} 个字段）"
        info_layout.addRow("字段统计:", QLabel(stats_text))

        layout.addWidget(info_group)
        layout.addStretch()

        # 关闭按钮
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
        self._display_fields = []  # [(key, name), ...] 当前显示的字段
        self._row_records = []     # 每行对应的记录数据
        self._init_ui()
        self._load_templates()
        self._load_batches()
        self._load_years()
        self._rebuild_table_columns()
        self._on_search()

    def _init_ui(self):
        """初始化UI"""
        # 页面级样式表，对齐录入页面的做法，消除下拉弹窗的黑底框
        self.setStyleSheet("""
            QComboBox {
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                font-size: 13px;
                background: white;
                min-height: 26px;
                max-height: 26px;
            }
            QComboBox::drop-down {
                border: none;
                width: 32px;
                border-radius: 0 6px 6px 0;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                background: white;
                selection-background-color: #3B82F6;
                selection-color: white;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 6px 12px;
                font-size: 12px;
                color: #374151;
                min-height: 24px;
                border-radius: 4px;
                margin: 1px 4px;
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
        
        # 第一行：模板选择 + 归档类型 + 审核状态
        row1 = QHBoxLayout()
        row1.setSpacing(15)
        
        template_label = QLabel("模板:")
        template_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.template_combo = QComboBox()
        self.template_combo.setView(QListView())
        self.template_combo.setObjectName("templateCombo")
        self.template_combo.setMinimumWidth(150)
        self.template_combo.currentIndexChanged.connect(self._on_template_changed)
        row1.addWidget(template_label)
        row1.addWidget(self.template_combo)
        
        filing_label = QLabel("归档类型:")
        filing_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.filing_combo = QComboBox()
        self.filing_combo.setView(QListView())
        self.filing_combo.setObjectName("filingTypeCombo")
        self.filing_combo.addItems(["全部", "以件归档", "以卷归档"])
        self.filing_combo.setMinimumWidth(120)
        row1.addWidget(filing_label)
        row1.addWidget(self.filing_combo)
        
        status_label = QLabel("审核状态:")
        status_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.status_combo = QComboBox()
        self.status_combo.setView(QListView())
        self.status_combo.setObjectName("statusCombo")
        self.status_combo.addItems(["全部", "待审核", "已审核", "已上传"])
        self.status_combo.setMinimumWidth(120)
        row1.addWidget(status_label)
        row1.addWidget(self.status_combo)
        
        row1.addStretch()
        search_layout.addLayout(row1)
        
        # 第二行：批次 + 年度
        row2 = QHBoxLayout()
        row2.setSpacing(15)
        
        batch_label = QLabel("批次:")
        batch_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.batch_combo = QComboBox()
        self.batch_combo.setView(QListView())
        self.batch_combo.setObjectName("batchCombo")
        self.batch_combo.setMinimumWidth(150)
        row2.addWidget(batch_label)
        row2.addWidget(self.batch_combo)
        
        year_label = QLabel("年度:")
        year_label.setStyleSheet("font-weight: bold; color: #2C3E50;")
        self.year_combo = QComboBox()
        self.year_combo.setView(QListView())
        self.year_combo.setObjectName("yearCombo")
        self.year_combo.setMinimumWidth(120)
        row2.addWidget(year_label)
        row2.addWidget(self.year_combo)
        
        row2.addStretch()
        search_layout.addLayout(row2)
        
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
        # 列将由 _rebuild_table_columns() 动态设置
        self.result_table.setColumnCount(0)
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
            }
            QTableWidget::item:selected {
                background-color: #3498DB;
                color: white;
            }
            QTableWidget::item:alternate {
                background-color: #FBFCFD;
            }

            /* Scrollbar */
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

        # 列宽将在 _rebuild_table_columns() 中动态设置
        self.result_table.horizontalHeader().setMinimumSectionSize(60)
        
        # 表头自适应（最后一列固定宽度避免按钮被压缩）
        self.result_table.horizontalHeader().setStretchLastSection(False)
        self.result_table.verticalHeader().setDefaultSectionSize(46)
        self.result_table.verticalHeader().setMinimumSectionSize(40)
        self.result_table.verticalHeader().setVisible(False)
        # 交替行、整行选择、只读
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.horizontalHeader().setFixedHeight(48)
        # 保证纵向滚动条出现时不会挤压操作列，始终能拖出水平滚动条看到完整按钮
        self.result_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.result_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 设置表格大小策略：允许自由伸缩，内部滚动而非撑开父容器
        self.result_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 视口底部留白，防止水平滚动条遮挡最后一行的操作按钮
        self.result_table.setViewportMargins(0, 0, 0, 8)
        result_layout.addWidget(self.result_table)
        # 结果区域内表格伸缩，统计标签不伸缩
        result_layout.setStretch(0, 0)
        result_layout.setStretch(1, 1)

        result_group.setLayout(result_layout)
        main_layout.addWidget(result_group)

        # 底部按钮栏（右侧对齐，增加间距和内边距）
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 12, 12, 12)
        btn_layout.setSpacing(16)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.review_btn = QPushButton('✅  标记为已核对')
        self.review_btn.setMinimumWidth(140)
        self.review_btn.setFixedHeight(40)
        self.review_btn.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
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

        self.detail_btn = QPushButton('👁  查看详情')
        self.detail_btn.setMinimumWidth(120)
        self.detail_btn.setFixedHeight(40)
        self.detail_btn.setStyleSheet("""
            QPushButton {
                background-color: #9B59B6;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
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

        # 导出按钮（放在最右侧，增加图标左侧留白以保持图标与文字间距）
        self.export_btn = QPushButton('📥  导出结果')
        self.export_btn.setMinimumWidth(130)
        self.export_btn.setFixedHeight(40)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #F39C12;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
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

        # 设置伸缩因子：检索条件（索引0）不伸缩，结果区域（索引1）伸缩，底部按钮（索引2）不伸缩
        main_layout.setStretch(0, 0)
        main_layout.setStretch(1, 1)
        main_layout.setStretch(2, 0)

    def _rebuild_table_columns(self):
        """根据选中的模板动态重建表格列"""
        template_id = self.template_combo.currentData()

        if template_id:
            # 特定模板：使用该模板的字段
            template_name = self.template_manager.get_template_name(template_id)
            fields = self.template_manager.get_fields(template_name) if template_name else []
            self._display_fields = [(f['key'], f['name']) for f in fields]
        else:
            # "全部"模板：收集所有模板的字段（按首次出现顺序去重）
            all_fields = {}  # key -> name
            templates = self.record_manager.get_all_templates()
            for tmpl in templates:
                fields = self.template_manager.get_fields(tmpl['name'])
                for f in fields:
                    if f['key'] not in all_fields:
                        all_fields[f['key']] = f['name']
            self._display_fields = [(key, name) for key, name in all_fields.items()]

        # 重建表格列
        num_cols = len(self._display_fields) + 1  # 最后一列：操作
        self.result_table.setColumnCount(num_cols)
        headers = [name for _, name in self._display_fields] + ['操作']
        self.result_table.setHorizontalHeaderLabels(headers)

        # 动态设置列宽：字段列交互调整，操作列占满剩余空间
        for i in range(len(self._display_fields)):
            self.result_table.setColumnWidth(i, 130)
            self.result_table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        action_col = len(self._display_fields)
        self.result_table.setColumnWidth(action_col, 200)
        self.result_table.horizontalHeader().setSectionResizeMode(action_col, QHeaderView.ResizeMode.Interactive)
        self.result_table.horizontalHeader().setMinimumSectionSize(60)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        # 重建列后重新设置视口底部留白，防止滚动条遮挡操作按钮
        self.result_table.setViewportMargins(0, 0, 0, 14)

    def _on_template_changed(self):
        """模板选择变化时重建列并重新搜索"""
        self._rebuild_table_columns()
        self._on_search()

    def _load_templates(self):
        """加载模板列表"""
        # 阻止信号以免在加载过程中触发 _on_template_changed
        self.template_combo.blockSignals(True)
        self.template_combo.addItem("全部", None)
        templates = self.record_manager.get_all_templates()
        for template in templates:
            self.template_combo.addItem(template['name'], template['id'])
        self.template_combo.blockSignals(False)
    
    def _load_batches(self):
        """加载批次列表"""
        self.batch_combo.clear()
        self.batch_combo.addItem("全部", None)
        batches = self.record_manager.get_all_batches()
        for batch in batches:
            self.batch_combo.addItem(batch['name'], batch['id'])
    
    def _load_years(self):
        """加载年度列表"""
        self.year_combo.clear()
        self.year_combo.addItem("全部", None)
        years = self.record_manager.get_all_years()
        for year in years:
            self.year_combo.addItem(str(year['year']), year['year'])

    def _on_search(self):
        """执行检索"""
        conditions = {}
        
        # 模板ID
        template_id = self.template_combo.currentData()
        if template_id:
            conditions['template_id'] = template_id
        
        # 归档类型
        filing_text = self.filing_combo.currentText()
        if filing_text == "以件归档":
            conditions['filing_type'] = 'item'
        elif filing_text == "以卷归档":
            conditions['filing_type'] = 'volume'
        
        # 审核状态
        status_text = self.status_combo.currentText()
        if status_text == "待审核":
            conditions['review_status'] = 'pending'
        elif status_text == "已审核":
            conditions['review_status'] = 'reviewed'
        elif status_text == "已上传":
            conditions['upload_status'] = 'uploaded'
        
        # 批次ID
        batch_id = self.batch_combo.currentData()
        if batch_id:
            conditions['batch_id'] = batch_id
        
        # 年度
        year = self.year_combo.currentData()
        if year:
            conditions['year'] = year
        
        # 全文搜索
        keyword = self.keyword_edit.text().strip()
        if keyword:
            conditions['keyword'] = keyword
        
        # 执行检索
        self.search_results = self.record_manager.advanced_search(conditions)
        
        # 显示结果
        self._display_results()

    def _display_results(self):
        """显示检索结果 - 动态列显示模板字段内容"""
        self.result_table.setRowCount(0)
        self.result_count_label.setText(f"共 {len(self.search_results)} 条记录")

        self._row_records = []
        field_keys = [key for key, _ in self._display_fields]
        action_col = len(field_keys)

        for row, record in enumerate(self.search_results):
            values = record.get('values', {})
            self._row_records.append(record)

            self.result_table.insertRow(row)

            # 按当前显示字段顺序填充值（居中显示）
            for col, key in enumerate(field_keys):
                value = values.get(key, '')
                item = QTableWidgetItem(str(value) if value else '')
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.result_table.setItem(row, col, item)

            # 操作按钮
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

            self.result_table.setCellWidget(row, action_col, action_widget)

        # 更新按钮状态
        has_results = len(self.search_results) > 0
        self.review_btn.setEnabled(has_results)
        self.detail_btn.setEnabled(has_results)
        self.export_btn.setEnabled(has_results)

    def _on_reset(self):
        """重置检索条件"""
        self.template_combo.setCurrentIndex(0)
        self.filing_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.batch_combo.setCurrentIndex(0)
        self.year_combo.setCurrentIndex(0)
        self.keyword_edit.clear()
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
        
        from core.export_manager import ExportManager
        from PySide6.QtWidgets import QFileDialog
        
        export_manager = ExportManager()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出检索结果", "检索结果", "Excel Files (*.xlsx)"
        )
        
        if path:
            export_manager.export_search_results(self.search_results, path, self._display_fields)
            QMessageBox.information(self, "提示", f"导出成功\n{path}")
            self.logger.log('export_search', {'count': len(self.search_results), 'path': path})