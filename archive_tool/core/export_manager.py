"""
Excel导出管理
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from datetime import datetime
from PySide6.QtWidgets import QFileDialog
from config.settings import EXPORT_HEADER_FILL, EXPORT_HEADER_FONT_COLOR
from core.record_manager import RecordManager
from core.template_manager import TemplateManager


class ExportManager:
    """Excel导出管理器"""

    HEADER_FILL = PatternFill('solid', fgColor=EXPORT_HEADER_FILL)
    HEADER_FONT = Font(bold=True, color=EXPORT_HEADER_FONT_COLOR, name='Arial')
    ALT_FILL = PatternFill('solid', fgColor='F2F2F2')

    def __init__(self):
        self.record_manager = RecordManager()
        self.template_manager = TemplateManager()

    def export_records(self, record_ids, filing_type):
        """导出记录到Excel"""
        records = []
        for record_id in record_ids:
            record = self.record_manager.get_record(record_id)
            if record:
                records.append(record)
        
        if not records:
            return

        template_id = records[0].get('template_id')
        template = self.template_manager.get_template_by_id(template_id)
        field_defs = template.get('fields', []) if template else []

        filename, _ = QFileDialog.getSaveFileName(
            None, "导出Excel", f"records_{datetime.now().strftime('%Y%m%d')}",
            "Excel文件 (*.xlsx)"
        )
        
        if not filename:
            return

        if not filename.endswith('.xlsx'):
            filename += '.xlsx'

        output_path = filename.replace('.xlsx', '')

        if filing_type == 'volume':
            self.export_volume_filing({'project': records}, output_path)
        else:
            self.export_item_filing(records, field_defs, output_path)

    def export_item_filing(self, records, field_defs, output_path):
        """以件归档导出：标准字段+自定义字段合并一张Sheet"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '档案数据'

        # 写入表头
        headers = [f['name'] for f in field_defs]
        self._write_header(ws, headers)

        # 写入数据
        for i, record in enumerate(records, 2):
            values = record.get('values', {})
            for j, field in enumerate(field_defs, 1):
                ws.cell(i, j, values.get(field['key'], ''))
            # 隔行着色
            if i % 2 == 0:
                for j in range(1, len(headers) + 1):
                    ws.cell(i, j).fill = self.ALT_FILL

        self._auto_width(ws)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        wb.save(f'{output_path}_{timestamp}.xlsx')

    def export_volume_filing(self, data, output_path):
        """以卷归档导出：一个文件三个Sheet"""
        wb = openpyxl.Workbook()

        # 删除默认Sheet
        if 'Sheet' in wb.sheetnames:
            del wb['Sheet']

        for layer_name, layer_data in [
            ('项目层', data.get('project', [])),
            ('案卷层', data.get('case', [])),
            ('文件层', data.get('file', []))
        ]:
            ws = wb.create_sheet(layer_name)
            if layer_data and len(layer_data) > 0:
                # 表头
                headers = list(layer_data[0].keys())
                self._write_header(ws, headers)
                # 数据
                for i, row in enumerate(layer_data, 2):
                    for j, val in enumerate(row.values(), 1):
                        ws.cell(i, j, val)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        wb.save(f'{output_path}_{timestamp}.xlsx')

    def _write_header(self, ws, headers):
        """写入表头"""
        for j, h in enumerate(headers, 1):
            c = ws.cell(1, j, h)
            c.font = self.HEADER_FONT
            c.fill = self.HEADER_FILL
            c.alignment = Alignment(horizontal='center', vertical='center')

    def _auto_width(self, ws):
        """自动调整列宽"""
        for col in ws.columns:
            max_len = max(len(str(c.value or '')) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    def export_search_results(self, records, output_path, display_fields=None, include_template_column=False):
        """导出检索结果 - 使用模板字段作为列"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '检索结果'

        if display_fields:
            # 使用传入的动态字段定义
            field_keys = [key for key, _ in display_fields]
            field_names = {key: name for key, name in display_fields}
            headers = [name for _, name in display_fields]
        else:
            # 回退：从记录中收集字段
            all_keys = set()
            for record in records:
                values = record.get('values', {})
                all_keys.update(values.keys())
            field_keys = list(all_keys)
            field_names = {k: k for k in all_keys}
            headers = list(field_keys)

        # 多模板时，在首列添加模板名
        if include_template_column:
            headers = ['模板'] + headers

        # 写入表头
        self._write_header(ws, headers)

        # 写入数据
        for row_idx, record in enumerate(records, 2):
            values = record.get('values', {})
            col_start = 1
            if include_template_column:
                ws.cell(row_idx, 1, record.get('template_name', ''))
                col_start = 2
            for col_idx, key in enumerate(field_keys, col_start):
                ws.cell(row_idx, col_idx, values.get(key, ''))

            # 隔行着色
            if row_idx % 2 == 0:
                for j in range(1, len(headers) + 1):
                    ws.cell(row_idx, j).fill = self.ALT_FILL

        self._auto_width(ws)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        wb.save(f'{output_path}_{timestamp}.xlsx')
