"""
模板与字段配置管理
"""
import json
from pathlib import Path
from db.database import get_cursor
from config.settings import TEMPLATE_DIR


class TemplateManager:
    """模板管理器"""

    def __init__(self):
        self.templates = {}
        self._load_templates()

    def _load_templates(self):
        """从JSON文件加载模板配置"""
        for json_file in TEMPLATE_DIR.glob('*.json'):
            with open(json_file, 'r', encoding='utf-8') as f:
                template_data = json.load(f)
                template_name = json_file.stem
                self.templates[template_name] = template_data

    def get_template(self, name):
        """获取模板配置"""
        return self.templates.get(name)

    def get_all_templates(self):
        """获取所有模板列表（返回包含文件名和友好名称的列表）"""
        result = []
        for filename, data in self.templates.items():
            result.append({
                'filename': filename,
                'name': data.get('name', filename)
            })
        return result

    def get_template_by_name(self, name):
        """根据友好名称获取模板配置"""
        for filename, data in self.templates.items():
            if data.get('name') == name:
                return data
        return None

    def get_filename_by_name(self, name):
        """根据友好名称获取文件名"""
        for filename, data in self.templates.items():
            if data.get('name') == name:
                return filename
        return None

    def get_fields(self, template_name):
        """获取模板的字段列表（从数据库加载）"""
        template_id = self.get_template_id(template_name)
        if not template_id:
            return []

        with get_cursor() as cursor:
            cursor.execute('''
                SELECT key, name, required, field_type, layer, dropdown_options, hint
                FROM fields WHERE template_id = ? ORDER BY id
            ''', (template_id,))
            rows = cursor.fetchall()

            fields = []
            for row in rows:
                field = {
                    'key': row['key'],
                    'name': row['name'],
                    'required': bool(row['required']),
                    'type': row['field_type'],
                    'layer': row['layer'] or 'item',
                    'hint': row['hint'] or '',
                }
                if row['dropdown_options']:
                    try:
                        field['dropdown_options'] = json.loads(row['dropdown_options'])
                    except json.JSONDecodeError:
                        field['dropdown_options'] = []
                fields.append(field)
            return fields

    def get_required_fields(self, template_name):
        """获取必填字段列表"""
        fields = self.get_fields(template_name)
        return [f for f in fields if f.get('required')]

    def init_database_templates(self):
        """初始化数据库中的模板数据"""
        with get_cursor() as cursor:
            for name, data in self.templates.items():
                # 检查是否已存在
                cursor.execute('SELECT id FROM templates WHERE name = ?', (name,))
                if cursor.fetchone():
                    continue

                # 插入模板
                cursor.execute('''
                    INSERT INTO templates (name, description, filing_type)
                    VALUES (?, ?, ?)
                ''', (name, data.get('description', ''), data.get('filing_type', 'item')))

                template_id = cursor.lastrowid

                # 插入字段
                for field in data.get('fields', []):
                    cursor.execute('''
                        INSERT INTO fields (template_id, key, name, required, field_type, layer, dropdown_options, hint)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        template_id,
                        field['key'],
                        field['name'],
                        1 if field.get('required') else 0,
                        field.get('type', 'text'),
                        field.get('layer', 'item'),
                        json.dumps(field.get('dropdown_options', []), ensure_ascii=False),
                        field.get('hint', '')
                    ))

    def get_template_id(self, name):
        """获取模板ID"""
        with get_cursor() as cursor:
            cursor.execute('SELECT id FROM templates WHERE name = ?', (name,))
            result = cursor.fetchone()
            return result['id'] if result else None

    def get_template_name(self, template_id):
        """根据模板ID获取模板名称"""
        with get_cursor() as cursor:
            cursor.execute('SELECT name FROM templates WHERE id = ?', (template_id,))
            result = cursor.fetchone()
            return result['name'] if result else None
