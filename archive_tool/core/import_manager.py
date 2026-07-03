"""
Excel导入管理
"""
import openpyxl


class ImportManager:
    """Excel导入管理器"""

    def _clean_header(self, header):
        """清理表头，去除常见标记符号"""
        if not header:
            return ''
        return header.replace('*', '').replace('（必填）', '').replace('(必填)', '').strip()

    def import_from_excel(self, file_path, expected_fields):
        """
        从Excel文件导入数据
        :param file_path: Excel文件路径
        :param expected_fields: 期望的字段列表，每个元素包含 'key' 和 'name'
        :return: (success, data/error_msg)
            success: True表示导入成功，False表示失败
            data: 成功时返回导入的数据列表，每个元素是字段值字典
            error_msg: 失败时返回错误信息
        """
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            ws = wb.active

            raw_headers = []
            cleaned_headers = []
            for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
                for cell in row:
                    raw_header = str(cell).strip() if cell else ''
                    raw_headers.append(raw_header)
                    cleaned_headers.append(self._clean_header(raw_header))

            expected_names = {f['name']: f['key'] for f in expected_fields}

            missing_columns = []
            extra_columns = []
            header_mapping = {}

            for expected_name in expected_names:
                cleaned_expected = self._clean_header(expected_name)
                found = False
                for idx, cleaned_header in enumerate(cleaned_headers):
                    if cleaned_header == cleaned_expected:
                        found = True
                        header_mapping[idx] = expected_names[expected_name]
                        break
                if not found:
                    missing_columns.append(expected_name)

            for idx, cleaned_header in enumerate(cleaned_headers):
                if cleaned_header and idx not in header_mapping:
                    extra_columns.append(raw_headers[idx])

            if missing_columns:
                wb.close()
                expected_list = ', '.join(expected_names.keys())
                actual_list = ', '.join(raw_headers)
                return False, f"缺少必要的列：{', '.join(missing_columns)}\n\n期望列名：{expected_list}\n实际列名：{actual_list}"

            data = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                row_data = {}
                empty_row = True
                for idx, value in enumerate(row):
                    if idx in header_mapping:
                        if value is not None:
                            empty_row = False
                        row_data[header_mapping[idx]] = str(value).strip() if value else ''
                if not empty_row:
                    data.append(row_data)

            wb.close()

            if not data:
                return False, "Excel文件中没有有效数据行"

            if extra_columns:
                return True, {'data': data, 'extra_columns': extra_columns}

            return True, {'data': data, 'extra_columns': []}

        except Exception as e:
            return False, f"读取Excel文件失败: {str(e)}"