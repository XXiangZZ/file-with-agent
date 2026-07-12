"""
档案记录增删改查
"""
import json
from datetime import datetime
from db.database import get_cursor


class RecordManager:
    """档案记录管理器"""

    def create_record(self, batch_id, template_id, name=None, filing_type=None, layer='item', parent_id=None, year=None, data=None, template_name=None):
        """创建新档案记录"""
        if data is not None and year is None:
            year = self._extract_year_from_data(data)
        
        with get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO records (batch_id, template_id, template_name, name, filing_type, layer, parent_id, year)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (batch_id, template_id, template_name, name, filing_type, layer, parent_id, year))
            record_id = cursor.lastrowid
            
            if data is not None:
                self.save_record_values(record_id, data)
            
            return record_id

    def _extract_year_from_data(self, data):
        """从字段数据中提取年份值"""
        year_keys = ['year', 'doc_year', 'nianfen', '年度', '档案年度', '文件年度']
        
        for key in year_keys:
            if key in data and data[key]:
                try:
                    return int(data[key])
                except ValueError:
                    pass
        
        from datetime import datetime
        return datetime.now().year

    def save_record_values(self, record_id, field_data, is_custom=False):
        """保存字段值"""
        with get_cursor() as cursor:
            for key, value in field_data.items():
                cursor.execute('''
                    INSERT INTO record_values (record_id, field_key, field_value, is_custom)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(record_id, field_key) DO UPDATE SET
                    field_value=excluded.field_value
                ''', (record_id, key, str(value) if value else '', is_custom))

    def get_record(self, record_id):
        """获取单条记录"""
        with get_cursor() as cursor:
            cursor.execute('SELECT * FROM records WHERE id = ?', (record_id,))
            record = cursor.fetchone()
            if not record:
                return None

            # 获取字段值
            cursor.execute('SELECT field_key, field_value FROM record_values WHERE record_id = ?', (record_id,))
            values = {row['field_key']: row['field_value'] for row in cursor.fetchall()}

            result = dict(record)
            result['values'] = values
            return result

    def get_records_by_batch(self, batch_id):
        """获取批次下所有记录"""
        with get_cursor() as cursor:
            cursor.execute('SELECT * FROM records WHERE batch_id = ?', (batch_id,))
            records = cursor.fetchall()

            result = []
            for record in records:
                record_dict = dict(record)
                cursor.execute('SELECT field_key, field_value FROM record_values WHERE record_id = ?', (record['id'],))
                record_dict['values'] = {row['field_key']: row['field_value'] for row in cursor.fetchall()}
                result.append(record_dict)
            return result

    def get_all_records(self):
        """获取所有记录"""
        with get_cursor() as cursor:
            cursor.execute('SELECT * FROM records ORDER BY id')
            records = cursor.fetchall()

            result = []
            for record in records:
                record_dict = dict(record)
                cursor.execute('SELECT field_key, field_value FROM record_values WHERE record_id = ?', (record['id'],))
                record_dict['values'] = {row['field_key']: row['field_value'] for row in cursor.fetchall()}
                result.append(record_dict)
            return result

    def get_record_names_by_batch(self, batch_id):
        """获取批次下所有记录名称"""
        with get_cursor() as cursor:
            cursor.execute('SELECT name FROM records WHERE batch_id = ?', (batch_id,))
            return [row['name'] for row in cursor.fetchall()]

    def update_record(self, record_id, field_data):
        """更新记录字段值"""
        with get_cursor() as cursor:
            # 更新字段值
            for key, value in field_data.items():
                cursor.execute('''
                    INSERT INTO record_values (record_id, field_key, field_value, is_custom)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(record_id, field_key) DO UPDATE SET
                    field_value=excluded.field_value
                ''', (record_id, key, str(value) if value else '', False))
            
            # 更新更新时间
            cursor.execute('UPDATE records SET updated_at = ? WHERE id = ?',
                         (datetime.now().isoformat(), record_id))

    def update_record_status(self, record_id, review_status=None, upload_status=None):
        """更新记录状态"""
        with get_cursor() as cursor:
            if review_status:
                cursor.execute('UPDATE records SET review_status = ?, updated_at = ? WHERE id = ?',
                             (review_status, datetime.now().isoformat(), record_id))
            if upload_status:
                cursor.execute('UPDATE records SET upload_status = ?, updated_at = ? WHERE id = ?',
                             (upload_status, datetime.now().isoformat(), record_id))

    def delete_record(self, record_id):
        """删除记录"""
        with get_cursor() as cursor:
            cursor.execute('DELETE FROM records WHERE id = ?', (record_id,))

    def search_records(self, template_id, keyword):
        """搜索记录"""
        with get_cursor() as cursor:
            cursor.execute('''
                SELECT r.* FROM records r
                JOIN record_values rv ON r.id = rv.record_id
                WHERE r.template_id = ? AND rv.field_value LIKE ?
            ''', (template_id, f'%{keyword}%'))
            return [dict(row) for row in cursor.fetchall()]

    def advanced_search(self, conditions):
        """
        高级检索 - 支持多条件组合查询
        :param conditions: 检索条件字典，支持以下键：
            - archive_no: 档案编号
            - title: 题名/名称
            - dept: 部门
            - start_date: 录入开始时间
            - end_date: 录入结束时间
            - filing_type: 归档类型
            - template_id: 模板ID
            - review_status: 审核状态
            - keyword: 全文搜索关键词
        :return: 匹配的记录列表，包含字段值
        """
        with get_cursor() as cursor:
            query = '''
                SELECT DISTINCT r.* FROM records r
                LEFT JOIN record_values rv ON r.id = rv.record_id
                WHERE 1=1
            '''
            params = []

            # 模板ID过滤
            if conditions.get('template_id'):
                query += ' AND r.template_id = ?'
                params.append(conditions['template_id'])

            # 归档类型过滤
            if conditions.get('filing_type'):
                query += ' AND r.filing_type = ?'
                params.append(conditions['filing_type'])

            # 审核状态过滤
            if conditions.get('review_status'):
                query += ' AND r.review_status = ?'
                params.append(conditions['review_status'])

            # 录入时间范围
            if conditions.get('start_date'):
                query += ' AND r.created_at >= ?'
                params.append(conditions['start_date'])
            
            if conditions.get('end_date'):
                query += ' AND r.created_at <= ?'
                params.append(conditions['end_date'])

            # 档案编号
            if conditions.get('archive_no'):
                query += ' AND EXISTS (SELECT 1 FROM record_values rv2 WHERE rv2.record_id = r.id AND rv2.field_key IN ("file_no", "bianhao", "archive_no") AND rv2.field_value LIKE ?)'
                params.append(f'%{conditions["archive_no"]}%')

            # 题名/名称
            if conditions.get('title'):
                query += ' AND EXISTS (SELECT 1 FROM record_values rv2 WHERE rv2.record_id = r.id AND rv2.field_key IN ("title", "mingcheng", "subject") AND rv2.field_value LIKE ?)'
                params.append(f'%{conditions["title"]}%')

            # 部门
            if conditions.get('dept'):
                query += ' AND EXISTS (SELECT 1 FROM record_values rv2 WHERE rv2.record_id = r.id AND rv2.field_key IN ("dept", "bumen", "department") AND rv2.field_value LIKE ?)'
                params.append(f'%{conditions["dept"]}%')

            # 全文搜索关键词
            if conditions.get('keyword'):
                query += ' AND EXISTS (SELECT 1 FROM record_values rv2 WHERE rv2.record_id = r.id AND rv2.field_value LIKE ?)'
                params.append(f'%{conditions["keyword"]}%')

            query += ' ORDER BY r.id ASC'

            cursor.execute(query, params)
            records = cursor.fetchall()

            # 获取完整字段值
            result = []
            for record in records:
                record_dict = dict(record)
                cursor.execute('SELECT field_key, field_value FROM record_values WHERE record_id = ?', (record['id'],))
                record_dict['values'] = {row['field_key']: row['field_value'] for row in cursor.fetchall()}
                result.append(record_dict)
            
            return result

    def get_all_templates(self):
        """获取所有模板列表（含ID和名称）"""
        with get_cursor() as cursor:
            cursor.execute('SELECT id, name FROM templates ORDER BY id')
            return [dict(row) for row in cursor.fetchall()]

    def get_all_batches(self):
        """获取所有批次列表"""
        with get_cursor() as cursor:
            cursor.execute('SELECT id, name, template_id, created_at FROM batches ORDER BY id DESC')
            return [dict(row) for row in cursor.fetchall()]
