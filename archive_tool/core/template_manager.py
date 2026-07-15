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
                template_name = template_data.get('name', json_file.stem)
                self.templates[template_name] = template_data

    def get_template(self, name):
        """获取模板配置"""
        return self.templates.get(name)

    def get_all_templates(self):
        """获取所有模板列表（从数据库加载）"""
        with get_cursor() as cursor:
            cursor.execute('SELECT id, name, description, filing_type FROM templates ORDER BY id')
            rows = cursor.fetchall()
            result = []
            for row in rows:
                result.append({
                    'id': row['id'],
                    'filename': row['name'],
                    'name': row['name'],
                    'filing_type': row['filing_type'] or 'item',
                })
            return result

    def get_template_by_name(self, name):
        """根据友好名称获取模板配置（从数据库加载）"""
        template_id = self.get_template_id(name)
        if not template_id:
            return None
        
        with get_cursor() as cursor:
            cursor.execute('SELECT name, description, filing_type FROM templates WHERE id = ?', (template_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            fields = self.get_fields(name)
            return {
                'name': row['name'],
                'description': row['description'] or '',
                'filing_type': row['filing_type'],
                'fields': fields
            }

    def get_filename_by_name(self, name):
        """根据友好名称获取文件名（返回数据库中的名称）"""
        return name

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

    def get_template_by_id(self, template_id):
        """根据模板ID获取模板配置（包含字段）"""
        template_name = self.get_template_name(template_id)
        if not template_name:
            return None
        return self.get_template_by_name(template_name)

    def get_templates_with_id(self):
        """获取所有模板列表（包含ID）"""
        with get_cursor() as cursor:
            cursor.execute('SELECT id, name, description, filing_type FROM templates ORDER BY id')
            return [dict(row) for row in cursor.fetchall()]

    def add_field(self, template_id, key, name, required=False, field_type='text', layer='item', dropdown_options=None, hint=''):
        """添加字段到模板"""
        with get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO fields (template_id, key, name, required, field_type, layer, dropdown_options, hint, is_custom)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (
                template_id,
                key,
                name,
                1 if required else 0,
                field_type,
                layer,
                json.dumps(dropdown_options or [], ensure_ascii=False),
                hint
            ))
            return cursor.lastrowid

    def update_field(self, field_id, name=None, required=None, field_type=None, layer=None, dropdown_options=None, hint=None):
        """更新字段信息"""
        with get_cursor() as cursor:
            updates = []
            params = []
            
            if name is not None:
                updates.append('name = ?')
                params.append(name)
            if required is not None:
                updates.append('required = ?')
                params.append(1 if required else 0)
            if field_type is not None:
                updates.append('field_type = ?')
                params.append(field_type)
            if layer is not None:
                updates.append('layer = ?')
                params.append(layer)
            if dropdown_options is not None:
                updates.append('dropdown_options = ?')
                params.append(json.dumps(dropdown_options, ensure_ascii=False))
            if hint is not None:
                updates.append('hint = ?')
                params.append(hint)
            
            if not updates:
                return False
            
            params.append(field_id)
            cursor.execute(f'UPDATE fields SET {", ".join(updates)} WHERE id = ?', params)
            return cursor.rowcount > 0

    def delete_field(self, field_id):
        """删除字段"""
        with get_cursor() as cursor:
            cursor.execute('DELETE FROM fields WHERE id = ?', (field_id,))
            return cursor.rowcount > 0

    def get_field_by_id(self, field_id):
        """根据ID获取字段信息"""
        with get_cursor() as cursor:
            cursor.execute('''
                SELECT id, key, name, required, field_type, layer, dropdown_options, hint, is_custom
                FROM fields WHERE id = ?
            ''', (field_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            field = {
                'id': row['id'],
                'key': row['key'],
                'name': row['name'],
                'required': bool(row['required']),
                'type': row['field_type'],
                'layer': row['layer'] or 'item',
                'hint': row['hint'] or '',
                'is_custom': bool(row['is_custom']),
            }
            if row['dropdown_options']:
                try:
                    field['dropdown_options'] = json.loads(row['dropdown_options'])
                except json.JSONDecodeError:
                    field['dropdown_options'] = []
            return field

    def create_template(self, name, description='', filing_type='item'):
        """创建新模板"""
        with get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO templates (name, description, filing_type)
                VALUES (?, ?, ?)
            ''', (name, description, filing_type))
            return cursor.lastrowid
