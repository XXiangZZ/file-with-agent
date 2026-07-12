"""
台账统计页面
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QLabel, QGroupBox, QPushButton, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox
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

        # 批次统计表
        batch_group = QGroupBox('批次统计')
        batch_group.setStyleSheet("""
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
        batch_layout = QVBoxLayout()

        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(5)
        self.batch_table.setHorizontalHeaderLabels(
            ['批次ID', '批次名称', '模板', '记录数', '状态']
        )
        self.batch_table.verticalHeader().setVisible(False)
        self.batch_table.setStyleSheet("""
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
        """)

        header = self.batch_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)

        self.batch_table.setColumnWidth(0, 60)
        self.batch_table.setColumnWidth(3, 70)
        self.batch_table.setColumnWidth(4, 70)

        batch_layout.addWidget(self.batch_table)

        batch_group.setLayout(batch_layout)
        main_layout.addWidget(batch_group)



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
        """加载统计数据"""
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

            # 批次统计
            cursor.execute('''
                SELECT b.id, b.name, 
                       COALESCE(t.name, b.template_name, 'N/A') as template_name,
                       COUNT(r.id) as record_count
                FROM batches b
                LEFT JOIN templates t ON b.template_id = t.id
                LEFT JOIN records r ON r.batch_id = b.id
                GROUP BY b.id
            ''')
            batches = cursor.fetchall()

            self.batch_table.setRowCount(len(batches))
            for i, batch in enumerate(batches):
                id_item = QTableWidgetItem(str(batch['id']))
                id_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.batch_table.setItem(i, 0, id_item)
                
                name_item = QTableWidgetItem(batch['name'])
                name_item.setToolTip(batch['name'])
                self.batch_table.setItem(i, 1, name_item)
                
                template_item = QTableWidgetItem(batch['template_name'] or 'N/A')
                template_item.setToolTip(batch['template_name'] or 'N/A')
                self.batch_table.setItem(i, 2, template_item)
                
                count_item = QTableWidgetItem(str(batch['record_count']))
                count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.batch_table.setItem(i, 3, count_item)
                
                status_item = QTableWidgetItem('正常')
                status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.batch_table.setItem(i, 4, status_item)

    def _export_batch_stats(self):
        """导出批次统计表"""
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
        
        headers = ['批次ID', '批次名称', '模板', '记录数', '状态']
        header_fill = PatternFill('solid', fgColor='34495E')
        header_font = Font(bold=True, color='FFFFFF')
        
        for j, h in enumerate(headers, 1):
            c = ws.cell(1, j, h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center', vertical='center')
        
        row_count = self.batch_table.rowCount()
        for i in range(row_count):
            for j in range(5):
                item = self.batch_table.item(i, j)
                ws.cell(i + 2, j + 1, item.text() if item else '')
        
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
        
        for i, row in enumerate(summary_data, 1):
            for j, val in enumerate(row, 1):
                c = ws_summary.cell(i, j, val)
                if i == 1:
                    c.font = header_font
                    c.fill = header_fill
                    c.alignment = Alignment(horizontal='center', vertical='center')
        
        for col in ws_summary.columns:
            max_len = max(len(str(c.value or '')) for c in col)
            ws_summary.column_dimensions[col[0].column_letter].width = min(max_len + 4, 20)
        
        ws_batches = wb.create_sheet('批次统计')
        batch_headers = ['批次ID', '批次名称', '模板', '记录数', '状态']
        
        for j, h in enumerate(batch_headers, 1):
            c = ws_batches.cell(1, j, h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center', vertical='center')
        
        row_count = self.batch_table.rowCount()
        for i in range(row_count):
            for j in range(5):
                item = self.batch_table.item(i, j)
                ws_batches.cell(i + 2, j + 1, item.text() if item else '')
        
        for col in ws_batches.columns:
            max_len = max(len(str(c.value or '')) for c in col)
            ws_batches.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)
        
        from core.record_manager import RecordManager
        from core.template_manager import TemplateManager
        
        record_manager = RecordManager()
        template_manager = TemplateManager()
        
        with get_cursor() as cursor:
            cursor.execute('SELECT id, name FROM batches')
            batch_map = {row['id']: row['name'] for row in cursor.fetchall()}
        
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
