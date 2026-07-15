"""
台账统计页面
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QLabel, QGroupBox, QPushButton, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QTreeWidget,
    QTreeWidgetItem
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from db.database import get_cursor


class StatsPage(QWidget):
    """台账统计页面"""

    def __init__(self):
        super().__init__()
        self._init_ui()
        self._load_stats()

    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # 统计卡片
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)

        self.total_label = self._create_stat_card('总录入数', '0', '#3498DB', export_key='all')
        stats_layout.addWidget(self.total_label)

        self.pending_label = self._create_stat_card('待核对', '0', '#F39C12', export_key='pending')
        stats_layout.addWidget(self.pending_label)

        self.reviewed_label = self._create_stat_card('已核对', '0', '#27AE60', export_key='reviewed')
        stats_layout.addWidget(self.reviewed_label)

        self.uploaded_label = self._create_stat_card('已上传', '0', '#9B59B6', export_key='uploaded')
        stats_layout.addWidget(self.uploaded_label)

        self.failed_label = self._create_stat_card('上传失败', '0', '#E74C3C', export_key='failed')
        stats_layout.addWidget(self.failed_label)

        main_layout.addLayout(stats_layout)

        # 批次-模板-年度-记录 树形统计
        tree_group = QGroupBox('台账层级统计')
        tree_group.setStyleSheet("""
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
        tree_layout = QVBoxLayout()

        self.stats_tree = QTreeWidget()
        self.stats_tree.setHeaderLabels(['名称 / 编号', '类型', '记录数', '状态'])
        self.stats_tree.setAnimated(True)
        self.stats_tree.setIndentation(24)
        self.stats_tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #E5E9EC;
                border-radius: 8px;
                background-color: white;
                font-size: 13px;
            }
            QTreeWidget::item {
                padding: 8px 4px;
                border-bottom: 1px solid #F3F4F6;
            }
            QTreeWidget::item:hover {
                background-color: #F0F4FF;
            }
            QTreeWidget::item:selected {
                background-color: #E8EFFE;
                color: #1F2937;
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
        """)

        header = self.stats_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.stats_tree.setColumnWidth(1, 80)
        self.stats_tree.setColumnWidth(2, 80)
        self.stats_tree.setColumnWidth(3, 80)

        self.stats_tree.itemExpanded.connect(self._on_tree_item_expanded)
        tree_layout.addWidget(self.stats_tree)

        # 底部工具栏
        tree_footer = QWidget()
        tree_footer_layout = QHBoxLayout(tree_footer)
        tree_footer_layout.setContentsMargins(0, 4, 0, 0)

        self.refresh_btn = QPushButton('↻ 刷新')
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: #F3F4F6; color: #374151;
                border: 1px solid #D1D5DB; border-radius: 6px;
                padding: 6px 16px; font-size: 13px;
            }
            QPushButton:hover { background: #E5E7EB; }
        """)
        self.refresh_btn.clicked.connect(self._load_stats)
        tree_footer_layout.addWidget(self.refresh_btn)

        self.export_tree_btn = QPushButton('导出层级统计')
        self.export_tree_btn.setStyleSheet("""
            QPushButton {
                background: #059669; color: white;
                border: none; border-radius: 6px;
                padding: 6px 16px; font-size: 13px;
            }
            QPushButton:hover { background: #047857; }
        """)
        self.export_tree_btn.clicked.connect(self._export_batch_stats)
        tree_footer_layout.addWidget(self.export_tree_btn)

        tree_footer_layout.addStretch()
        tree_layout.addWidget(tree_footer)

        tree_group.setLayout(tree_layout)
        main_layout.addWidget(tree_group)



    def _create_stat_card(self, title, value, color, export_key=None):
        """创建统计卡片"""
        card = QGroupBox(title)
        card.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                color: #666;
                border: 1px solid #E5E9EC;
                border-radius: 10px;
                margin-top: 5px;
                padding: 15px 10px 10px 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                left: 0;
                padding: 0 10px;
                color: #888;
            }
        """)
        card_layout = QVBoxLayout()
        
        value_label = QLabel(value)
        value_label.setStyleSheet(f'''
            font-size: 28px;
            font-weight: bold;
            color: {color};
        ''')
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(value_label)
        
        if export_key:
            export_btn = QPushButton('导出')
            export_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FFFFFF;
                    color: #3498DB;
                    border: 1px solid #3498DB;
                    border-radius: 4px;
                    padding: 4px 12px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #3498DB;
                    color: #FFFFFF;
                }
            """)
            export_btn.clicked.connect(lambda checked, key=export_key: self._export_by_status(key))
            card_layout.addWidget(export_btn)
        
        card.setLayout(card_layout)
        return card

    def _load_stats(self):
        """加载统计数据 - 树形层级：批次 → 模板 → 年度 → 记录"""
        with get_cursor() as cursor:
            # 总录入数
            cursor.execute('SELECT COUNT(*) as count FROM records')
            total = cursor.fetchone()['count']
            self.total_label.findChild(QLabel).setText(str(total))

            # 待核对
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE review_status = ?', ('pending',))
            pending = cursor.fetchone()['count']
            self.pending_label.findChild(QLabel).setText(str(pending))

            # 已核对
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE review_status = ?', ('reviewed',))
            reviewed = cursor.fetchone()['count']
            self.reviewed_label.findChild(QLabel).setText(str(reviewed))

            # 已上传
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE upload_status = ?', ('uploaded',))
            uploaded = cursor.fetchone()['count']
            self.uploaded_label.findChild(QLabel).setText(str(uploaded))

            # 上传失败
            cursor.execute('SELECT COUNT(*) as count FROM records WHERE upload_status = ?', ('failed',))
            failed = cursor.fetchone()['count']
            self.failed_label.findChild(QLabel).setText(str(failed))

            # 构建树形层级：批次 → 模板 → 年度 → 记录
            self.stats_tree.clear()

            # 查询所有批次
            cursor.execute('SELECT id, name FROM batches ORDER BY id DESC')
            batches = cursor.fetchall()

            for batch in batches:
                batch_id = batch['id']
                batch_name = batch['name']

                # 该批次下的记录数
                cursor.execute('SELECT COUNT(*) as cnt FROM records WHERE batch_id = ?', (batch_id,))
                batch_count = cursor.fetchone()['cnt']

                batch_item = QTreeWidgetItem(self.stats_tree)
                batch_item.setText(0, batch_name)
                batch_item.setText(1, '批次')
                batch_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                batch_item.setText(2, str(batch_count))
                batch_item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
                batch_item.setText(3, '')
                batch_item.setData(0, Qt.UserRole, {'type': 'batch', 'id': batch_id})
                font = batch_item.font(0)
                font.setBold(True)
                batch_item.setFont(0, font)

                # 该批次下按模板+年度分组
                cursor.execute('''
                    SELECT template_name, year, COUNT(*) as cnt
                    FROM records
                    WHERE batch_id = ? AND template_name IS NOT NULL
                    GROUP BY template_name, year
                    ORDER BY template_name, year DESC
                ''', (batch_id,))
                groups = cursor.fetchall()

                # 先按模板名分组
                template_groups = {}
                for g in groups:
                    tmpl = g['template_name'] or '未分类'
                    if tmpl not in template_groups:
                        template_groups[tmpl] = {'total': 0, 'years': []}
                    template_groups[tmpl]['total'] += g['cnt']
                    template_groups[tmpl]['years'].append((g['year'], g['cnt']))

                for tmpl_name, tmpl_data in template_groups.items():
                    tmpl_item = QTreeWidgetItem(batch_item)
                    tmpl_item.setText(0, tmpl_name)
                    tmpl_item.setText(1, '模板')
                    tmpl_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                    tmpl_item.setText(2, str(tmpl_data['total']))
                    tmpl_item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
                    tmpl_item.setText(3, '')
                    tmpl_item.setData(0, Qt.UserRole, {'type': 'template', 'name': tmpl_name, 'batch_id': batch_id})

                    for year, year_count in tmpl_data['years']:
                        year_item = QTreeWidgetItem(tmpl_item)
                        year_item.setText(0, f'{year}年')
                        year_item.setText(1, '年度')
                        year_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                        year_item.setText(2, str(year_count))
                        year_item.setTextAlignment(2, Qt.AlignmentFlag.AlignCenter)
                        year_item.setText(3, '')
                        year_item.setData(0, Qt.UserRole, {'type': 'year', 'year': year, 'template_name': tmpl_name, 'batch_id': batch_id})

            self.stats_tree.expandAll()

    def _on_tree_item_expanded(self, item):
        """节点展开事件（预留，当前为全量加载，无需懒加载）"""
        pass

    def _export_batch_stats(self):
        """导出批次统计表（树形结构展开为列表）"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出批次统计", f"batch_stats_{datetime.now().strftime('%Y%m%d')}",
            "Excel文件 (*.xlsx)"
        )

        if not filename:
            return

        if not filename.endswith('.xlsx'):
            filename += '.xlsx'

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '批次统计'

        headers = ['批次', '模板', '年度', '记录数']
        header_fill = PatternFill('solid', fgColor='34495E')
        header_font = Font(bold=True, color='FFFFFF')

        for j, h in enumerate(headers, 1):
            c = ws.cell(1, j, h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center', vertical='center')

        row = 2
        root = self.stats_tree.invisibleRootItem()
        for bi in range(root.childCount()):
            batch_item = root.child(bi)
            batch_name = batch_item.text(0)
            for ti in range(batch_item.childCount()):
                tmpl_item = batch_item.child(ti)
                tmpl_name = tmpl_item.text(0)
                for yi in range(tmpl_item.childCount()):
                    year_item = tmpl_item.child(yi)
                    ws.cell(row, 1, batch_name)
                    ws.cell(row, 2, tmpl_name)
                    ws.cell(row, 3, year_item.text(0))
                    ws.cell(row, 4, int(year_item.text(2)))
                    row += 1

        for col in ws.columns:
            max_len = max(len(str(c.value or '')) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        wb.save(filename)
        QMessageBox.information(self, "成功", f"批次统计已导出到:\n{filename}")

    def _export_all_data(self):
        """导出全部数据（按模板分组到不同Sheet）"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "导出全部数据", f"all_data_{datetime.now().strftime('%Y%m%d')}",
            "Excel文件 (*.xlsx)"
        )

        if not filename:
            return

        if not filename.endswith('.xlsx'):
            filename += '.xlsx'

        wb = openpyxl.Workbook()

        header_fill = PatternFill('solid', fgColor='34495E')
        header_font = Font(bold=True, color='FFFFFF')

        # 汇总 Sheet
        ws_summary = wb.active
        ws_summary.title = '统计汇总'

        summary_data = [
            ['统计项', '数量'],
            ['总录入数', self.total_label.findChild(QLabel).text()],
            ['待核对', self.pending_label.findChild(QLabel).text()],
            ['已核对', self.reviewed_label.findChild(QLabel).text()],
            ['已上传', self.uploaded_label.findChild(QLabel).text()],
            ['上传失败', self.failed_label.findChild(QLabel).text()]
        ]

        for i, r in enumerate(summary_data, 1):
            for j, val in enumerate(r, 1):
                c = ws_summary.cell(i, j, val)
                if i == 1:
                    c.font = header_font
                    c.fill = header_fill
                    c.alignment = Alignment(horizontal='center', vertical='center')

        for col in ws_summary.columns:
            max_len = max(len(str(c.value or '')) for c in col)
            ws_summary.column_dimensions[col[0].column_letter].width = min(max_len + 4, 20)

        # 树形展开 Sheet
        ws_tree = wb.create_sheet('台账层级')
        tree_headers = ['批次', '模板', '年度', '记录数']
        for j, h in enumerate(tree_headers, 1):
            c = ws_tree.cell(1, j, h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center', vertical='center')

        row = 2
        root = self.stats_tree.invisibleRootItem()
        for bi in range(root.childCount()):
            batch_item = root.child(bi)
            batch_name = batch_item.text(0)
            for ti in range(batch_item.childCount()):
                tmpl_item = batch_item.child(ti)
                tmpl_name = tmpl_item.text(0)
                for yi in range(tmpl_item.childCount()):
                    year_item = tmpl_item.child(yi)
                    ws_tree.cell(row, 1, batch_name)
                    ws_tree.cell(row, 2, tmpl_name)
                    ws_tree.cell(row, 3, year_item.text(0))
                    ws_tree.cell(row, 4, int(year_item.text(2)))
                    row += 1

        for col in ws_tree.columns:
            max_len = max(len(str(c.value or '')) for c in col)
            ws_tree.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        from core.record_manager import RecordManager
        from core.template_manager import TemplateManager

        record_manager = RecordManager()
        template_manager = TemplateManager()

        with get_cursor() as cursor:
            cursor.execute('SELECT id, name FROM batches')
            batch_map = {r['id']: r['name'] for r in cursor.fetchall()}

        all_records = record_manager.get_all_records()

        if not all_records:
            wb.save(filename)
            QMessageBox.information(self, "成功", f"全部数据已导出到:\n{filename}")
            return

        records_by_template = {}
        for record in all_records:
            template_name = record.get('template_name', '未知模板')
            if template_name not in records_by_template:
                records_by_template[template_name] = []
            records_by_template[template_name].append(record)

        for template_name, records in records_by_template.items():
            ws = wb.create_sheet(template_name[:31])

            template_id = records[0].get('template_id')
            template = template_manager.get_template_by_id(template_id)
            field_defs = template.get('fields', []) if template else []

            headers = ['批次名称', '审核状态', '上传状态', '录入时间']
            field_keys = [f['key'] for f in field_defs]
            field_names = [f['name'] for f in field_defs]

            for name in field_names:
                headers.append(name)

            for j, h in enumerate(headers, 1):
                c = ws.cell(1, j, h)
                c.font = header_font
                c.fill = header_fill
                c.alignment = Alignment(horizontal='center', vertical='center')

            for row_idx, record in enumerate(records, 2):
                values = record.get('values', {})

                batch_id = record.get('batch_id', '')
                ws.cell(row_idx, 1, batch_map.get(batch_id, batch_id))

                review_status = record.get('review_status', '')
                review_text = {'pending': '待审核', 'reviewed': '已审核', 'uploaded': '已上传'}.get(review_status, review_status)
                ws.cell(row_idx, 2, review_text)

                upload_status = record.get('upload_status', '')
                upload_text = {'pending': '待上传', 'uploaded': '已上传', 'failed': '上传失败'}.get(upload_status, upload_status)
                ws.cell(row_idx, 3, upload_text)

                created_at = record.get('created_at', '')
                ws.cell(row_idx, 4, created_at[:19] if created_at else '')

                for col_idx, key in enumerate(field_keys, 5):
                    ws.cell(row_idx, col_idx, values.get(key, ''))

            for col in ws.columns:
                max_len = max(len(str(c.value or '')) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        if 'Sheet' in wb.sheetnames:
            wb.remove(wb['Sheet'])

        wb.save(filename)
        QMessageBox.information(self, "成功", f"全部数据已导出到:\n{filename}")

    def _export_by_status(self, status_key):
        """按状态导出数据"""
        status_map = {
            'all': ('总录入数', None),
            'pending': ('待核对', 'pending'),
            'reviewed': ('已核对', 'reviewed'),
            'uploaded': ('已上传', 'uploaded'),
            'failed': ('上传失败', 'failed')
        }
        
        title, status_value = status_map.get(status_key, ('未知', None))
        
        filename, _ = QFileDialog.getSaveFileName(
            self, f"导出{title}", f"{status_key}_{datetime.now().strftime('%Y%m%d')}",
            "Excel文件 (*.xlsx)"
        )
        
        if not filename:
            return
        
        if not filename.endswith('.xlsx'):
            filename += '.xlsx'
        
        from core.record_manager import RecordManager
        from core.template_manager import TemplateManager
        
        record_manager = RecordManager()
        template_manager = TemplateManager()
        
        all_records = record_manager.get_all_records()
        
        if status_value:
            if status_value in ('uploaded', 'failed'):
                records = [r for r in all_records if r.get('upload_status') == status_value]
            else:
                records = [r for r in all_records if r.get('review_status') == status_value]
        else:
            records = all_records
        
        if not records:
            QMessageBox.information(self, "提示", f"没有{title}数据可导出")
            return
        
        with get_cursor() as cursor:
            cursor.execute('SELECT id, name FROM batches')
            batch_map = {row['id']: row['name'] for row in cursor.fetchall()}
        
        wb = openpyxl.Workbook()
        
        header_fill = PatternFill('solid', fgColor='34495E')
        header_font = Font(bold=True, color='FFFFFF')
        
        records_by_template = {}
        for record in records:
            template_name = record.get('template_name', '未知模板')
            if template_name not in records_by_template:
                records_by_template[template_name] = []
            records_by_template[template_name].append(record)
        
        for template_name, template_records in records_by_template.items():
            ws = wb.create_sheet(template_name[:31])
            
            template_id = template_records[0].get('template_id')
            template = template_manager.get_template_by_id(template_id)
            field_defs = template.get('fields', []) if template else []
            
            headers = ['批次名称', '审核状态', '上传状态', '录入时间']
            field_keys = [f['key'] for f in field_defs]
            field_names = [f['name'] for f in field_defs]
            
            for name in field_names:
                headers.append(name)
            
            for j, h in enumerate(headers, 1):
                c = ws.cell(1, j, h)
                c.font = header_font
                c.fill = header_fill
                c.alignment = Alignment(horizontal='center', vertical='center')
            
            for row_idx, record in enumerate(template_records, 2):
                values = record.get('values', {})
                
                batch_id = record.get('batch_id', '')
                ws.cell(row_idx, 1, batch_map.get(batch_id, batch_id))
                
                review_status = record.get('review_status', '')
                review_text = {'pending': '待审核', 'reviewed': '已审核', 'uploaded': '已上传'}.get(review_status, review_status)
                ws.cell(row_idx, 2, review_text)
                
                upload_status = record.get('upload_status', '')
                upload_text = {'pending': '待上传', 'uploaded': '已上传', 'failed': '上传失败'}.get(upload_status, upload_status)
                ws.cell(row_idx, 3, upload_text)
                
                created_at = record.get('created_at', '')
                ws.cell(row_idx, 4, created_at[:19] if created_at else '')
                
                for col_idx, key in enumerate(field_keys, 5):
                    ws.cell(row_idx, col_idx, values.get(key, ''))
            
            for col in ws.columns:
                max_len = max(len(str(c.value or '')) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)
        
        if 'Sheet' in wb.sheetnames:
            wb.remove(wb['Sheet'])
        
        wb.save(filename)
        QMessageBox.information(self, "成功", f"{title}已导出到:\n{filename}")
