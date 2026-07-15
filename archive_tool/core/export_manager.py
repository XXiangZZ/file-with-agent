"""
Excel导出管理
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from datetime import datetime
from PySide6.QtWidgets import QFileDialog
from collections import defaultdict
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

    @staticmethod
    def _sanitize_sheet_name(name, existing_names=None):
        """清理Sheet名称：去除非法字符、截断到31字符、避免重名"""
        if not name:
            name = '未命名'
        invalid = set('[]:*?/\\')
        cleaned = ''.join(c for c in str(name) if c not in invalid).strip()
        if not cleaned:
            cleaned = 'Sheet'
        cleaned = cleaned[:31]

        if existing_names is None:
            existing_names = set()
        if cleaned not in existing_names:
            return cleaned
        # 重名时追加数字后缀
        base = cleaned
        suffix = 2
        while True:
            candidate = f'{base[:28]}_{suffix}'
            if candidate not in existing_names:
                return candidate
            suffix += 1

    def export_batch_by_template(self, batch_id, parent=None):
        """
        导出批次内所有记录：按模板分Sheet
        - 同一模板的记录写入同一个Sheet，使用模板的字段定义作为表头
        - 模板不存在时（历史数据），使用记录上的template_name并收集所有字段键
        - 返回执行信息字典：{success, message, record_count, template_count, output_file, batch_id}
        """
        records = self.record_manager.get_records_by_batch(batch_id)
        if not records:
            return {'success': False, 'message': '当前批次没有记录', 'record_count': 0,
                    'template_count': 0, 'output_file': None, 'batch_id': batch_id}

        # 按 template_id 分组
        groups = defaultdict(list)
        for r in records:
            tid = r.get('template_id')
            if tid is None:
                tid = '__no_template__'
            groups[tid].append(r)

        # 弹出保存对话框
        default_name = f"batch_{batch_id}_records_{datetime.now().strftime('%Y%m%d')}"
        filename, _ = QFileDialog.getSaveFileName(
            parent, "导出批次记录（按模板分Sheet）", default_name, "Excel文件 (*.xlsx)"
        )
        if not filename:
            return {'success': False, 'message': '用户取消导出', 'record_count': len(records),
                    'template_count': len(groups), 'output_file': None, 'batch_id': batch_id}

        if not filename.endswith('.xlsx'):
            filename += '.xlsx'

        # 创建工作簿
        wb = openpyxl.Workbook()
        if 'Sheet' in wb.sheetnames:
            del wb['Sheet']

        used_names = set()
        template_stats = []

        for tid, group_records in groups.items():
            # 获取模板字段定义
            template = None
            template_name = ''
            field_defs = []

            if tid != '__no_template__':
                template = self.template_manager.get_template_by_id(tid)

            if template:
                template_name = template.get('name', '')
                field_defs = template.get('fields', [])

            if not field_defs:
                # 模板不存在或无字段：回退到记录上的template_name + 收集字段键
                sample = group_records[0]
                template_name = sample.get('template_name') or template_name or f'模板{tid}'
                all_keys = []
                seen = set()
                for r in group_records:
                    for k in r.get('values', {}).keys():
                        if k not in seen:
                            seen.add(k)
                            all_keys.append(k)
                field_defs = [{'key': k, 'name': k} for k in all_keys]

            if not template_name:
                template_name = f'模板{tid}'

            sheet_name = self._sanitize_sheet_name(template_name, used_names)
            used_names.add(sheet_name)
            ws = wb.create_sheet(title=sheet_name)

            # 写入表头（字段名）
            headers = [f['name'] for f in field_defs]
            self._write_header(ws, headers)

            # 写入数据
            for i, record in enumerate(group_records, 2):
                values = record.get('values', {})
                for j, field in enumerate(field_defs, 1):
                    ws.cell(i, j, values.get(field['key'], ''))
                if i % 2 == 0:
                    for j in range(1, len(headers) + 1):
                        ws.cell(i, j).fill = self.ALT_FILL

            self._auto_width(ws)
            template_stats.append((template_name, len(group_records)))

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = filename.replace('.xlsx', f'_{timestamp}.xlsx')
        wb.save(output_file)

        msg_lines = [f'导出成功：共 {len(records)} 条记录，{len(template_stats)} 个模板：']
        for tname, count in template_stats:
            msg_lines.append(f'  · {tname}：{count} 条')
        message = '\n'.join(msg_lines)

        return {
            'success': True,
            'message': message,
            'record_count': len(records),
            'template_count': len(template_stats),
            'output_file': output_file,
            'batch_id': batch_id,
            'template_stats': template_stats,
        }

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
