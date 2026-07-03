"""
字段格式与必填校验
"""
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ValidationError:
    field_key: str
    field_name: str
    layer: str
    error_type: str
    message: str


class Validator:
    """字段校验器"""

    DATE_PATTERN = re.compile(r'^\d{8}$')  # YYYYMMDD

    def validate_field(self, field_def, value) -> Optional[ValidationError]:
        """校验单个字段"""
        field_key = field_def.get('key', '')
        field_name = field_def.get('name', '')
        layer = field_def.get('layer', 'item')

        # 必填校验
        if field_def.get('required') and not value:
            return ValidationError(
                field_key=field_key,
                field_name=field_name,
                layer=layer,
                error_type='required',
                message=f'{field_name} 为必填字段'
            )

        # 日期格式校验
        if value and field_def.get('type') == 'date':
            if not self.DATE_PATTERN.match(value):
                return ValidationError(
                    field_key=field_key,
                    field_name=field_name,
                    layer=layer,
                    error_type='format',
                    message=f'{field_name} 格式错误，应为YYYYMMDD'
                )

        return None

    def validate_record(self, field_defs, field_data) -> List[ValidationError]:
        """校验整条记录"""
        errors = []
        for field_def in field_defs:
            value = field_data.get(field_def.get('key', ''), '')
            error = self.validate_field(field_def, value)
            if error:
                errors.append(error)
        return errors

    def validate_batch_duplicates(self, records, key_field='record_number') -> List[ValidationError]:
        """检查同批次档案编号是否重复"""
        errors = []
        numbers = []
        for r in records:
            val = r.get('values', {}).get(key_field)
            if val:
                numbers.append(val)
        duplicates = {n for n in numbers if numbers.count(n) > 1}

        for rec in records:
            val = rec.get('values', {}).get(key_field)
            if val in duplicates:
                errors.append(ValidationError(
                    field_key=key_field,
                    field_name='档案编号',
                    layer='item',
                    error_type='duplicate',
                    message=f'批次内档案编号重复: {val}'
                ))
        return errors
